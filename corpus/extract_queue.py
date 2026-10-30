"""Parallel part queue for the Corpus Builder (Nvidia, one pooled key per worker).

extract_v3 used to take one chapter at a time: its 4 split calls ran together and the NEXT chapter waited for the slowest of
them, so the other agents sat idle (measured on a real 10-chapter run: agents busy ~61% of the time). Here the whole range is
one shared queue of (chapter, part) tasks. Every worker takes the next task whatever chapter it belongs to, so a worker that
finished its part of chapter N moves straight on to a part of chapter N+1 while another is still on N's slowest part.
A chapter is assembled and saved the moment its LAST part lands, by whichever worker finished it; each part is checkpointed
to disk (corpus/_split_parts/<novel>/chN_*.json) the moment it arrives, so a stop or a crash loses nothing.

In V4 the plot call (the slowest, ~35% of the output) is cut in two: plot_a = the V3 plot fields, plot_b = beats + fights.
Voice is cut in two as well (voice_a / voice_b), so no single call writes more than ~5-6 KB.
"""
import json
import os
import threading
import time
from collections import deque
from pathlib import Path

import extract_v3 as E
import llm_client as L

# Read timeout per part (seconds). Measured on real runs: voice / prose / world answers that succeed arrive well inside this, while a
# request Nvidia sits on would otherwise wait the full 300 s and then repeat (calls of 520-770 s). The beats call (plot_b) writes
# up to 12,000 tokens and keeps the full 300 s.
_TIMEOUT_S = {"voice": 210, "prose": 210, "world": 210, "plot": 240, "plot_b": 300}

_PRINT = threading.Lock()
_SAVE = threading.Lock()

# the order a chapter's parts are handed out in: the slowest first, so they start early and the short ones fill the gaps
_ORDER = ["voice_b", "voice_a", "plot_b", "plot_a", "world", "prose", "plot", "voice"]

# voice (the slowest single call: median 166 s, up to 800 s) is cut in two, each half writing ~5 KB. Every field stays in exactly
# one half; the paragraph-numbered text and the measured context still go to both (they key on the part before the underscore).
_VOICE_A = ("character_voice_samples", "narrative_voice_analysis", "scene_structure_patterns", "mx_chapter_type")


def eligible() -> bool:
    """The part queue needs split extraction on Nvidia with at least two pooled keys (anything else keeps the old loop)."""
    if os.environ.get("NM_PART_QUEUE", "").strip().lower() in ("0", "false", "no", "off"):
        return False
    try:
        return E._split_enabled() and L._agent_engine() == "nemotron" and L.nemotron_pool_size() >= 2
    except Exception:
        return False


def plan() -> list:
    """[(label, keys)] for this run: the active split plan, with plot cut in two on V4."""
    v4 = E._v4_enabled()
    groups = E._split_groups_v4() if v4 else list(E.SPLIT_GROUPS)
    if not v4:
        return groups
    out = []
    for label, keys in groups:
        if label == "plot":
            import mechanics_core as mc
            mx = [k for k in keys if k in set(mc.MX_GROUP.get("plot", []))]
            out.append(("plot_a", [k for k in keys if k not in mx]))
            out.append(("plot_b", mx))
        elif label == "voice":
            out.append(("voice_a", [k for k in keys if k in _VOICE_A]))
            out.append(("voice_b", [k for k in keys if k not in _VOICE_A]))
        else:
            out.append((label, keys))
    return sorted(out, key=lambda g: _ORDER.index(g[0]) if g[0] in _ORDER else 99)


def _log(ch, msg):
    with _PRINT:
        print(f"[ch{ch}] {msg}", flush=True)


class _Chapter:
    def __init__(self, num: int, text: str):
        self.num = num
        self.text = text
        self.merged: dict = {}
        self.done: list = []
        self.failed: dict = {}
        self.stats: list = []
        self.pending = 0
        self.lock = threading.Lock()
        self.t0 = time.time()
        self.ckpt: Path = None


def _run_group(ch: _Chapter, idx: int, n: int, label: str, keys: list, v4: bool, novel: str):
    """One part: ask, parse, salvage, retry lost keys. Returns (part dict, seconds)."""
    user_message = f"Chapter {ch.num}:\n\n{ch.text[:14000]}{'[... truncated ...]' if len(ch.text) > 14000 else ''}"
    system = E.split_system_for(idx, n, label, keys, v4)
    user = E.split_user_for(label, ch.num, ch.text, user_message, v4, novel)
    mt = E.split_max_tokens(label, v4)
    t0 = time.time()
    L.set_nemotron_timeout(_TIMEOUT_S.get(label.split("_")[0] + ("_b" if label == "plot_b" else ""), 300))
    try:
        resp = L.call_llm(system=system, user=user, max_tokens=mt, temperature=0.3, required_keys=keys)
    finally:
        L.set_nemotron_timeout(None)
    part = E._parse_json_response(resp, f"ch{ch.num} {label}")
    if v4:
        if not part:
            part = E._salvage_partial(resp, keys)
            if part:
                _log(ch.num, f"{label}: salvaged {len(part)}/{len(keys)} keys from an unparseable answer")
        lost = [k for k in keys if k not in part]
        if lost:
            _log(ch.num, f"{label}: re-asking for {len(lost)} lost key(s): {', '.join(lost)}")
            try:
                L.set_nemotron_timeout(_TIMEOUT_S.get(label.split("_")[0] + ("_b" if label == "plot_b" else ""), 300))
                again = L.call_llm(
                    system=system.replace("return ONLY these keys:", "return ONLY these keys (an earlier answer was "
                                          "not valid JSON: escape every double quote inside a string as backslash-quote):", 1),
                    user=user + "\n\nReturn ONLY these keys, as one valid JSON object: " + ", ".join(lost),
                    max_tokens=mt, temperature=0.2, required_keys=lost)
                got = E._parse_json_response(again, label + " retry") or E._salvage_partial(again, lost)
                part.update({k: v for k, v in got.items() if k in lost})
            except Exception as e:
                _log(ch.num, f"{label}: retry failed - {str(e)[:100]}")
            finally:
                L.set_nemotron_timeout(None)
    return part, time.time() - t0


def _finish(ch: _Chapter, novel: str, all_keys: list, results: dict):
    """The last part of a chapter has landed: assemble the delta, save it, spend the checkpoint."""
    wall = time.time() - ch.t0
    got = sum(1 for k in all_keys if ch.merged.get(k) not in (None, "", [], {}))
    busy = sum(s[3] for s in ch.stats)
    _log(ch.num, f"== all {len(ch.stats)} part(s) in: {got}/{len(all_keys)} fields, {busy:.0f}s of calls, {wall:.0f}s on the clock ==")
    empty = [k for k in all_keys if ch.merged.get(k) in (None, "", [], {})]
    if empty:
        _log(ch.num, f"still empty: {', '.join(empty)}")
    try:
        delta = E.delta_from_llm(novel, ch.num, ch.text, ch.merged, E.analyze_style_dna(ch.text))
        with _SAVE:
            E.save_delta(delta, novel)
        results["ok"].append(ch.num)
        try:
            if ch.ckpt and ch.ckpt.exists():
                ch.ckpt.unlink()
        except OSError:
            pass
    except Exception as e:
        results["failed"].append(ch.num)
        _log(ch.num, f"ERROR assembling the delta: {str(e)[:150]} - the parts are kept, re-run the chapter")


def run_range(novel: str, chapters: list, skip_existing: bool = True) -> dict:
    """Extract `chapters` of `novel` through the shared part queue. Returns {"ok": [...], "failed": [...], "skipped": [...]}."""
    E._V4_CTX["novel"] = novel
    v4 = E._v4_enabled()
    groups = plan()
    labels = [l for l, _ in groups]
    all_keys = list(E.LLM_FIELDS)
    if v4:
        import mechanics_core as mc
        all_keys += list(mc.MX_KEYS)
    results = {"ok": [], "failed": [], "skipped": []}
    tasks: deque = deque()
    chaps: dict = {}
    for num in chapters:
        dp = Path("novels") / novel / "deltas_v3" / f"ch{num}.json"
        try:
            if skip_existing and dp.exists() and dp.stat().st_size > 500:
                print(f"[SKIP] Ch{num}: delta already exists ({dp.stat().st_size} bytes)")
                results["skipped"].append(num)
                continue
        except OSError:
            pass
        try:
            text = E.load_chapter_text(novel, num)
        except FileNotFoundError as e:
            print(f"[SKIP] {e}")
            results["skipped"].append(num)
            continue
        ch = _Chapter(num, text)
        ch.ckpt = E._split_checkpoint_path(num)
        ch.merged, done = E._load_split_checkpoint(ch.ckpt, num)
        if "plot" in done:                       # a checkpoint from the one-chapter path holds plot as one part
            done = [d for d in done if d != "plot"] + ["plot_a", "plot_b"]
        if "voice" in done:                      # likewise a one-call voice part covers both halves
            done = [d for d in done if d != "voice"] + ["voice_a", "voice_b"]
        ch.done = [d for d in done if d in labels]
        if ch.done:
            _log(num, f"resuming from saved parts: {', '.join(ch.done)}")
        todo = [(i, l, k) for i, (l, k) in enumerate(groups, 1) if l not in ch.done]
        ch.pending = len(todo)
        chaps[num] = ch
        if not todo:
            _finish(ch, novel, all_keys, results)
            continue
        for i, l, k in todo:
            tasks.append((ch, i, l, k))

    if not tasks:
        return results
    pool_n = min(8, L.nemotron_pool_size())
    n_workers = max(1, min(pool_n, len(tasks)))
    print(f"[queue] {len(chaps)} chapter(s), {len(tasks)} part(s) shared by {n_workers} Nvidia agent(s) "
          f"(a free agent takes the next part of any chapter)", flush=True)
    tlock = threading.Lock()
    announced = [False]

    def worker(w):
        L.ensure_nemotron_slot()
        slot = getattr(L._NEM_SLOT, "slot", 0) or 0
        key_no = slot % max(1, L.nemotron_pool_size()) + 1
        while True:
            with tlock:
                if not tasks:
                    return
                ch, idx, label, keys = tasks.popleft()
                if not tasks and not announced[0]:
                    announced[0] = True
                    # the Corpus Builder watches for this line: from here the agents that finish their part have nothing left to do
                    # here, so it can start the next queued range straight away
                    print("[queue] all parts handed out - agents free for the next range", flush=True)
            _log(ch.num, f"{label}: {len(keys)} fields -> agent {w + 1} (key {key_no})")
            part, took, err = {}, 0, None
            for attempt in range(1, 6):
                try:
                    part, took = _run_group(ch, idx, len(groups), label, keys, v4, novel)
                    err = None
                    break
                except Exception as e:
                    err = e
                    msg = str(e).lower()
                    limited = "429" in msg or "too many requests" in msg or "rate" in msg
                    if attempt >= (5 if limited else 2):
                        break
                    wait = 30 * attempt if limited else 10
                    _log(ch.num, f"{label}: {'rate limited' if limited else 'call failed'} - waiting {wait}s, then retrying "
                         f"({attempt}/{(5 if limited else 2) - 1})")
                    time.sleep(wait)
            with ch.lock:
                if err is not None:
                    ch.failed[label] = err
                    _log(ch.num, f"{label}: FAILED - {str(err)[:120]} (other parts are kept)")
                else:
                    for k in keys:
                        if k in part:
                            ch.merged[k] = part[k]
                    ch.done.append(label)
                    E._save_split_checkpoint(ch.ckpt, ch.num, ch.merged, ch.done)       # this part is safe on disk now
                    filled = [k for k in keys if ch.merged.get(k) not in (None, "", [], {})]
                    size = len(json.dumps({k: ch.merged.get(k) for k in filled}, ensure_ascii=False))
                    counts = ", ".join(f"{k}={len(ch.merged[k])}" for k in filled if isinstance(ch.merged.get(k), (list, dict)))
                    _log(ch.num, f"{label}: {len(filled)}/{len(keys)} filled in {took:.0f}s, {size:,} bytes"
                         + (f" ({counts})" if counts else ""))
                    ch.stats.append((label, len(filled), len(keys), took, size))
                ch.pending -= 1
                last = ch.pending == 0
                failed = dict(ch.failed)
            if last:
                if failed:
                    E._save_split_checkpoint(ch.ckpt, ch.num, ch.merged, ch.done)
                    results["failed"].append(ch.num)
                    _log(ch.num, f"NOT saved - {len(failed)} part(s) failed ({', '.join(failed)}); the other parts are kept "
                         f"and the validation round resumes from them")
                else:
                    _finish(ch, novel, all_keys, results)

    threads = [threading.Thread(target=worker, args=(w,), daemon=True) for w in range(n_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results
