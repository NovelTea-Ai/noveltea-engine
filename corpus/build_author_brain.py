"""
build_author_brain.py - the AUTHOR'S BRAIN of a corpus novel: how its author planned it.

Where the rolling summary says WHAT happens and the genome lists recurring patterns, the author brain reconstructs the author's own
planning notes, the way a writer keeps them:
  - arcs: chapter range, the promise made to the reader, the plan, escalation, turn, payoff, the cost to the hero, and the threads seeded
    in it for later;
  - threads: the long-running secrets, mysteries, conspiracies and rivalries: the truth the author knew, the chapter it was first seeded,
    the clues the reader saw and when, the misdirection, and the chapter (and way) it was revealed, or that it is still open;
  - milestones: the key on-page events chapter by chapter (fight, breakthrough, reveal, clue, plot, character, place, personal), as the
    hero sees them;
  - author_rules / conspiracy_craft: the author's habits in plain rules;
  - rhythm: measured by Python from the above: arc lengths, seed-to-reveal gaps, and how many of each milestone per 20 chapters.

Two passes. Pass 1 reads each 40-chapter stretch (chapter summaries, the author's goal per chapter, arc signals, the secrets ledger from
knowledge_state, reveals) and writes that stretch's notes; each stretch is saved as it lands (novels/<id>/author_brain/), so a stopped
run resumes. Pass 2 reads the whole book (rolling summary + every stretch's notes) and joins the threads across stretches and writes the
rules. Saved to novels/<id>/author_brain.json. Read by the app's Conspiracy, Arc planner and Timeline (via the knowledge index).

Usage:
    python build_author_brain.py --novel my_novel          # one novel (skipped when current; --force rebuilds)
    python build_author_brain.py                                 # every novel that is missing or has grown
"""
import argparse
import json
import re
import statistics as st
import time
from pathlib import Path

NOVELS_PATH = Path("novels")
WINDOW = 40
SCHEMA = 1
CATEGORIES = ["fight", "breakthrough", "reveal", "clue", "plot", "character", "place", "personal"]


def load_json(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _title(novel_id: str) -> str:
    meta = load_json(NOVELS_PATH / novel_id / "novel_metadata.json", {}) or {}
    t = meta.get("title") or ""
    return t if t and t != novel_id else novel_id.replace("_", " ").title()


def _deltas(novel_id: str) -> dict:
    out = {}
    d = NOVELS_PATH / novel_id / "deltas_v3"
    for f in d.glob("ch*.json"):
        m = re.match(r"ch(\d+)\.json$", f.name)
        if m:
            x = load_json(f)
            if isinstance(x, dict) and x.get("summary"):
                out[int(m.group(1))] = x
    return out


def _windows(chapters: list) -> list:
    """Consecutive stretches of WINDOW chapters, by number: [(first, last)]."""
    if not chapters:
        return []
    top = max(chapters)
    return [(a, min(a + WINDOW - 1, top)) for a in range(1, top + 1, WINDOW) if any(a <= c <= a + WINDOW - 1 for c in chapters)]


def _cut(s, n: int) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def _intent(x) -> str:
    if isinstance(x, dict):
        return _cut(x.get("author_goal") or "", 170)
    return _cut(x, 170)


def window_context(novel_id: str, deltas: dict, first: int, last: int) -> str:
    lines, arc_was = [], None
    for n in range(first, last + 1):
        d = deltas.get(n)
        if not d:
            continue
        head = f"Ch{n}"
        if d.get("chapter_title"):
            head += f" «{_cut(d['chapter_title'], 60)}»"
        fn = str(d.get("chapter_function") or "")
        if fn and len(fn) <= 30:                                  # a short label; some deltas hold a run-on scene dump here
            head += f" [{fn}]"
        arc = re.sub(r"^arc\s*\d*\s*[:\-]\s*", "", str(d.get("arc_label_suggestion") or ""), flags=re.I).strip()
        if arc and arc.lower() != (arc_was or "").lower():       # the arc signal fires on most chapters: show it only when the arc changes
            head += f" ARC: {_cut(arc, 80)}"
            arc_was = arc
        lines.append(f"{head}: {_cut(d.get('summary'), 400)}")
        goal = _intent(d.get("author_intent"))
        if goal:
            lines.append(f"   author's goal: {goal}")
    # the secrets ledger: facts hidden from someone, when they were set up and when (if ever) they came out
    secrets = []
    for n in range(first, last + 1):
        for k in (deltas.get(n) or {}).get("knowledge_state") or []:
            if not isinstance(k, dict) or not k.get("hidden_from") or not k.get("fact"):
                continue
            est = _int(k.get("established_chapter")) or n
            res = _int(k.get("resolved_chapter"))
            # kept longest first (a secret that came out 3+ chapters later is the author's long game), then the still-hidden ones,
            # oldest first, then the ones that came straight out
            rank = ((0, -(res - est), est) if res and res - est >= 3 else (1, 0, est) if not res else (2, 0, est))
            hidden = k["hidden_from"] if isinstance(k["hidden_from"], list) else [k["hidden_from"]]
            secrets.append((rank, f"Ch{est}: {_cut(k['fact'], 150)} (hidden from {', '.join(map(str, hidden))[:80]}) -> "
                                  + (f"comes out ch{res}" if res else "still hidden")))
    secrets.sort(key=lambda x: x[0])
    reveals = []
    for n in range(first, last + 1):
        for r in (deltas.get(n) or {}).get("reveals") or []:
            if isinstance(r, dict) and r.get("content"):
                setup = [c for c in (r.get("setup_chapters") or []) if isinstance(c, int)]
                reveals.append(f"Ch{r.get('payoff_chapter') or n} [{r.get('reveal_type', '?')}]{' set up ch' + ','.join(map(str, setup)) if setup else ''}: "
                               f"{_cut(r['content'], 170)}")
    out = [f"CHAPTERS {first}-{last}:", *lines]
    if secrets:
        out += ["", "SECRETS LEDGER (facts hidden from someone; longest-kept first):", *[s for _, s in secrets[:28]]]
    if reveals:
        out += ["", "REVEALS IN THESE CHAPTERS:", *reveals[:26]]
    return "\n".join(out)


WINDOW_PROMPT = """You are the AUTHOR of the web novel "{title}". Below are your own working notes on chapters {first}-{last}: each chapter's
summary, what you were trying to do in it, where you started a new arc, the secrets you were keeping and the reveals you paid off.
Reconstruct the PLAN you were working to in this stretch, the way an author keeps it in their head: not what happens, but WHY it
happens there, what you promised the reader, what you were hiding, and what you were setting up for later.

Return ONE JSON object, no markdown fences:
{{
  "arcs": [   // every arc (or part of one) that runs in chapters {first}-{last}, in order
    {{"chapters": [first, last], "label": "short arc name",
      "promise": "what this arc promises the reader (the question or desire that keeps them reading)",
      "plan": "2-3 sentences: how you built the arc and why it sits here in the book",
      "escalation": "how the pressure rises inside the arc", "turn": "the twist or reversal and its chapter",
      "payoff": "how the arc pays off (or 'continues past ch{last}')", "cost": "what it costs the hero",
      "seeds": [{{"chapter": 0, "thread": "thread name", "what": "what you planted for later"}}]}}
  ],
  "threads": [   // 3-8 long-running secrets, mysteries, conspiracies, identities, rivalries or promises active here
    {{"name": "short name", "kind": "conspiracy | mystery | identity | power | rivalry | romance | world | promise",
      "truth": "what you, the author, know that the reader does not (yet)",
      "seeded_chapter": 0, "clues": [{{"chapter": 0, "reader_sees": "the concrete thing the reader sees"}}],
      "misdirection": "how you kept the reader from guessing (or '')",
      "reveal_chapter": null, "how_revealed": "how it came out (or '' if still hidden by ch{last})"}}
  ],
  "milestones": [   // the 10-16 key on-page moments of this stretch, as the hero lives them
    {{"chapter": 0, "category": "fight | breakthrough | reveal | clue | plot | character | place | personal",
      "title": "short title", "mc_sees": "one sentence: what the hero experiences"}}
  ]
}}
Use real chapter numbers from the notes. Be specific to THIS novel: names, powers, places."""


BOOK_PROMPT = """You are the AUTHOR of the web novel "{title}". Below are the story so far (chapters 1-{last}) and your plan notes for each
stretch of it. Join them into your master notes for the whole book.

Return ONE JSON object, no markdown fences:
{{
  "engine": "one sentence: the engine that drives this story",
  "book_shape": "3-5 sentences: how you paced chapters 1-{last}: how arcs open, grow and hand over, where the big turns fall",
  "author_rules": ["8-12 plain rules you follow as this book's author, each specific and usable by another writer"],
  "conspiracy_craft": ["5-8 rules for how you hide truths, plant clues, misdirect and time your reveals in this book"],
  "threads": [   // the 6-14 most important long-running threads of the book, each joined across stretches
    {{"name": "short name", "kind": "conspiracy | mystery | identity | power | rivalry | romance | world | promise",
      "truth": "what the author knows", "seeded_chapter": 0,
      "clues": [{{"chapter": 0, "reader_sees": "concrete thing"}}],
      "misdirection": "", "reveal_chapter": null, "how_revealed": "",
      "payoff_effect": "what the reveal does to the story and the hero (or what it is building towards if still open)"}}
  ]
}}
Use real chapter numbers. Keep a thread open (reveal_chapter null) if it is not revealed by ch{last}."""


_RANGE = re.compile(r'("(?:chapter|seeded_chapter|reveal_chapter)"\s*:\s*)(\d+)\s*[-–]\s*\d+')


def _parse(raw: str):
    raw = _RANGE.sub(r"\1\2", str(raw or ""))           # "chapter": 51-52 is not JSON: keep the first chapter
    try:
        from extract_v3 import _parse_json_response
        got = _parse_json_response(raw, "author brain")
        if got:
            return got
    except Exception:
        pass
    s = str(raw or "")
    m = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
    if m:
        s = m.group(1)
    a, b = s.find("{"), s.rfind("}")
    try:
        return json.loads(s[a:b + 1]) if 0 <= a < b else None
    except Exception:
        return None


def _ask(system: str, user: str, max_tokens: int, keys: list):
    """One call, retried once: these long planning answers take Nemotron ~13-15 minutes, so the read timeout is 25 minutes, and a
    timeout or an unusable reply gets one more try before the stretch is reported as failed (a re-run resumes it)."""
    from llm_client import call_llm, set_nemotron_timeout
    err = None
    for attempt in (1, 2):
        set_nemotron_timeout(1500)
        try:
            raw = call_llm(system=system, user=user, max_tokens=max_tokens, temperature=0.4, required_keys=keys)
            data = _parse(raw)
            if isinstance(data, dict):
                return data
            err = RuntimeError("the reply was not a JSON object")
        except Exception as e:
            err = e
        finally:
            set_nemotron_timeout(None)
        if attempt == 1:
            print(f"  retrying once: {str(err)[:120]}", flush=True)
    raise err


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _clean_window(data: dict, first: int, last: int) -> dict:
    arcs = []
    for a in data.get("arcs") or []:
        if not isinstance(a, dict):
            continue
        ch = a.get("chapters") or []
        lo, hi = (_int(ch[0]) if ch else None), (_int(ch[-1]) if ch else None)
        lo, hi = max(first, lo or first), min(last, hi or last)
        arcs.append({"chapters": [lo, max(lo, hi)], **{k: _cut(a.get(k), 600) for k in ("label", "promise", "plan", "escalation", "turn", "payoff", "cost")},
                     "seeds": [{"chapter": _int(s.get("chapter")), "thread": _cut(s.get("thread"), 80), "what": _cut(s.get("what"), 300)}
                               for s in (a.get("seeds") or []) if isinstance(s, dict) and s.get("what")][:8]})
    ms = []
    for m in data.get("milestones") or []:
        if not isinstance(m, dict) or not _int(m.get("chapter")) or not m.get("title"):
            continue
        cat = str(m.get("category") or "plot").strip().lower()
        ms.append({"chapter": _int(m["chapter"]), "category": cat if cat in CATEGORIES else "plot",
                   "title": _cut(m["title"], 120), "mc_sees": _cut(m.get("mc_sees"), 300)})
    return {"chapters": [first, last], "arcs": arcs, "threads": [_clean_thread(t) for t in (data.get("threads") or []) if isinstance(t, dict) and t.get("name")][:10],
            "milestones": sorted(ms, key=lambda m: m["chapter"])[:24]}


def _clean_thread(t: dict) -> dict:
    return {"name": _cut(t.get("name"), 100), "kind": _cut(t.get("kind") or "mystery", 30).lower(), "truth": _cut(t.get("truth"), 700),
            "seeded_chapter": _int(t.get("seeded_chapter")),
            "clues": [{"chapter": _int(c.get("chapter")), "reader_sees": _cut(c.get("reader_sees"), 260)}
                      for c in (t.get("clues") or []) if isinstance(c, dict) and c.get("reader_sees")][:10],
            "misdirection": _cut(t.get("misdirection"), 400), "reveal_chapter": _int(t.get("reveal_chapter")),
            "how_revealed": _cut(t.get("how_revealed"), 400), "payoff_effect": _cut(t.get("payoff_effect"), 400)}


def _rhythm(arcs: list, milestones: list, threads: list, last: int) -> dict:
    lens = [a["chapters"][1] - a["chapters"][0] + 1 for a in arcs if a.get("chapters")]
    gaps = [t["reveal_chapter"] - t["seeded_chapter"] for t in threads
            if isinstance(t.get("reveal_chapter"), int) and isinstance(t.get("seeded_chapter"), int) and t["reveal_chapter"] >= t["seeded_chapter"]]
    per20 = {}
    for c in CATEGORIES:
        n = sum(1 for m in milestones if m["category"] == c)
        per20[c] = round(n * 20 / max(1, last), 1)
    return {"arc_length_median": st.median(lens) if lens else None, "arc_length_range": [min(lens), max(lens)] if lens else None,
            "reveal_gap_median": st.median(gaps) if gaps else None, "reveal_gap_max": max(gaps) if gaps else None,
            "threads_open": sum(1 for t in threads if not t.get("reveal_chapter")), "milestones_per_20_chapters": per20}


def _work_dir(novel_id: str) -> Path:
    return NOVELS_PATH / novel_id / "author_brain"


def is_stale(novel_id: str) -> bool:
    brain = load_json(NOVELS_PATH / novel_id / "author_brain.json")
    if not brain or brain.get("schema_version") != SCHEMA:
        return True
    have = len(_deltas(novel_id))
    return have - int(brain.get("source_chapter_count") or 0) >= 20


def run_window(novel_id: str, first: int, last: int, deltas: dict, pool=None) -> dict:
    out = _work_dir(novel_id) / f"w{first:04d}-{last:04d}.json"
    have = load_json(out)
    if have and have.get("source_chapters") == sum(1 for n in deltas if first <= n <= last):
        return have
    ctx = window_context(novel_id, deltas, first, last)
    if pool:
        pool.step(f"author's plan ch{first}-{last}", ctx[:160])
    print(f"[{novel_id}] ch{first}-{last}: {len(ctx):,} chars to the model", flush=True)
    t0 = time.time()
    data = _ask("You are a novelist reconstructing your own planning notes. Output only the JSON requested.",
                WINDOW_PROMPT.format(title=_title(novel_id), first=first, last=last) + "\n\n" + ctx, 9000, ["arcs", "threads", "milestones"])
    w = _clean_window(data, first, last)
    w["source_chapters"] = sum(1 for n in deltas if first <= n <= last)
    save_json(out, w)
    print(f"[{novel_id}] ch{first}-{last}: {len(w['arcs'])} arcs, {len(w['threads'])} threads, {len(w['milestones'])} milestones "
          f"in {time.time() - t0:.0f}s", flush=True)
    return w


def run_book(novel_id: str, windows: list, deltas: dict, pool=None) -> dict:
    last = max(deltas)
    rolling = (load_json(NOVELS_PATH / novel_id / "rolling_summary.json", {}) or {}).get("summary") or ""
    notes = []
    for w in windows:
        notes.append(f"== CHAPTERS {w['chapters'][0]}-{w['chapters'][1]} ==")
        for a in w["arcs"]:
            notes.append(f"ARC ch{a['chapters'][0]}-{a['chapters'][1]} {a['label']}: promise: {a['promise']} | turn: {a['turn']} | payoff: {a['payoff']}")
        for t in w["threads"]:
            clues = "; ".join(f"ch{c['chapter']}: {c['reader_sees']}" for c in t["clues"][:5])
            notes.append(f"THREAD {t['name']} [{t['kind']}] seeded ch{t['seeded_chapter']}, revealed ch{t['reveal_chapter']}: {t['truth']} | "
                         f"clues: {clues} | misdirection: {t['misdirection']} | how: {t['how_revealed']}")
    ctx = "STORY SO FAR:\n" + rolling + "\n\nYOUR PLAN NOTES BY STRETCH:\n" + "\n".join(notes)
    if pool:
        pool.step("joining the book's threads", ctx[:160])
    print(f"[{novel_id}] whole book: {len(ctx):,} chars to the model", flush=True)
    data = _ask("You are a novelist writing your master notes for your own book. Output only the JSON requested.",
                BOOK_PROMPT.format(title=_title(novel_id), last=last) + "\n\n" + ctx[:60000], 10000, ["engine", "author_rules", "threads"])
    return data


def build(novel_id: str, pool=None) -> dict:
    deltas = _deltas(novel_id)
    if len(deltas) < 20:
        print(f"[SKIP] {novel_id}: only {len(deltas)} extracted chapters")
        return {}
    windows = [run_window(novel_id, a, b, deltas, pool) for a, b in _windows(sorted(deltas))]
    book = run_book(novel_id, windows, deltas, pool)
    last = max(deltas)
    arcs = [a for w in windows for a in w["arcs"]]
    milestones = [m for w in windows for m in w["milestones"]]
    threads = [_clean_thread(t) for t in (book.get("threads") or []) if isinstance(t, dict) and t.get("name")][:16]
    if not threads:                                   # the book pass gave none: keep the stretches' threads
        threads = [t for w in windows for t in w["threads"]]
    brain = {"schema_version": SCHEMA, "novel_id": novel_id, "title": _title(novel_id), "chapters_covered": [min(deltas), last],
             "source_chapter_count": len(deltas), "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "engine": _cut(book.get("engine"), 400), "book_shape": _cut(book.get("book_shape"), 1200),
             "author_rules": [_cut(r, 300) for r in (book.get("author_rules") or []) if r][:14],
             "conspiracy_craft": [_cut(r, 300) for r in (book.get("conspiracy_craft") or []) if r][:10],
             "arcs": arcs, "threads": threads, "milestones": milestones,
             "rhythm": _rhythm(arcs, milestones, threads, last)}
    save_json(NOVELS_PATH / novel_id / "author_brain.json", brain)
    print(f"[OK] {novel_id}: {len(arcs)} arcs, {len(threads)} threads, {len(milestones)} milestones, "
          f"{len(brain['author_rules'])} rules -> novels/{novel_id}/author_brain.json", flush=True)
    return brain


def main():
    ap = argparse.ArgumentParser(description="Build the author's brain (planning notes) of corpus novels")
    ap.add_argument("--novel", help="one novel id (omit for every novel that is missing or has grown)")
    ap.add_argument("--force", action="store_true", help="rebuild even when current (the saved stretches are reused if unchanged)")
    args = ap.parse_args()
    from agent_pool import AgentPool
    from llm_client import current_model_label
    if args.novel:
        if not (NOVELS_PATH / args.novel).is_dir():
            print(f"[ERROR] Novel not found: {args.novel}")
            return
        if not args.force and not is_stale(args.novel):
            print(f"[SKIP] {args.novel}: author brain already current (use --force to rebuild)")
            return
        novels = [args.novel]
    else:
        novels = [p.name for p in sorted(NOVELS_PATH.iterdir()) if p.is_dir() and (args.force or is_stale(p.name))]
    if not novels:
        print("[DONE] every author brain is current")
        return
    # pass 1: every stretch of every novel, shared by the agents; pass 2: one whole-book call per novel
    pool = AgentPool("author_brain", model=current_model_label(None), want=4)
    items = []
    cache = {n: _deltas(n) for n in novels}
    for n in novels:
        for a, b in _windows(sorted(cache[n])):
            items.append({"novel": n, "unit": f"ch{a}-{b}", "first": a, "last": b})
    res = pool.run(items, lambda it: run_window(it["novel"], it["first"], it["last"], cache[it["novel"]], pool))
    bad = {it["novel"] for it, r in res if isinstance(r, Exception)}
    for it, r in res:
        if isinstance(r, Exception):
            print(f"[ERROR] {it['novel']} {it['unit']}: {str(r)[:200]}")
    todo = [n for n in novels if n not in bad]
    pool2 = AgentPool("author_brain", model=current_model_label(None), want=4)
    res2 = pool2.run([{"novel": n, "unit": "whole book"} for n in todo], lambda it: build(it["novel"], pool2))
    for it, r in res2:
        if isinstance(r, Exception):
            print(f"[ERROR] {it['novel']} whole book: {str(r)[:200]}")
    done = sum(1 for _, r in res2 if not isinstance(r, Exception) and r)
    print(f"\n[DONE] {done} author brain(s) built, {len(bad)} novel(s) had a failed stretch (re-run to resume)")


if __name__ == "__main__":
    main()
