"""Symbol/motif tracking, stage 2 (V4 Phase 3, doc Layer 10).

Filters extract_symbols_regex.py's candidates.json — a regex harvest catches
plenty of purely literal/incidental mentions ("light" as in "light armor",
"fire" as in a cooking scene) alongside genuinely symbolic/thematic ones.
This is the cheap targeted LLM pass that tells them apart and, for the real
ones, extracts what the symbol represents in context.

Idempotent/resumable: candidates already carrying `_filtered` are skipped, so
a partial or repeated run only classifies what's missing — same pattern as
classify_thread_types.py, including saving after every batch (not once at the
end) so an interrupted run doesn't lose progress on a large novel.

Usage: python filter_symbols_llm.py [novel_id ...]   (no args = every novel)
Writes back into symbols/candidates.json in place, then rebuilds
symbols/frequency.json (cheap aggregation, no LLM cost) from every candidate
currently marked symbolic — safe to rebuild in full on every run.
"""
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract_v3 import _parse_json_response  # reuse the same tolerant JSON-from-LLM parser
from llm_client import call_llm, engine_batch_size, current_model_label

NOVELS_DIR = Path(__file__).parent / "novels"
BATCH_SIZE_NEMOTRON = 1    # one record per call — maximum live-status granularity
BATCH_SIZE_OTHER = 15      # Claude (and every other engine) — excerpts are longer than thread-typing's one-line summaries, so smaller than its 40

# Pinned for THIS pipeline only — see classify_thread_types.py's
# NEMOTRON_MODEL_PIPELINE docstring for why (speed over reasoning depth for a
# simple true/false + short phrase call; does not touch the author's own
# models.nemotron choice in Settings for chapter generation).
# (nemotron-3-nano-30b-a3b was retired 2026-09-01 — see classify_thread_types.py)
# Ultra, not lightning-30b: measured 2026-09-25 — ultra 15s/call and returns clean
# JSON; lightning-30b timed out (>170s) in a timing test and, on this task, kept
# prefixing its answer with prose ("Here ...") so batches failed to parse.
NEMOTRON_MODEL_PIPELINE = "nvidia/nemotron-3-ultra-550b-a55b"

SYSTEM_PROMPT = """You are identifying genuine symbolic/thematic use of a word in short web-novel prose excerpts, as opposed to purely literal or incidental use.

For each excerpt given, the word in question is already identified. Decide:
- symbolic: true if the word is doing thematic/symbolic work in this excerpt — representing an idea, foreshadowing, marking a character's state, tied to a recurring motif — NOT just literal scene-setting (e.g. "light armor", "put out the fire", "the tree in the yard").
- If symbolic is true, give a short phrase (under 12 words) for what it represents IN THIS CONTEXT (e.g. "blood = the cost of power", "silence = repressed grief", "moon = isolation/otherworldliness").
- If symbolic is false, omit meaning.

Respond with ONLY a JSON object mapping each given id to its verdict — no prose, no markdown fences:
{"prose_0001_fire": {"symbolic": true, "meaning": "fire = his buried rage"}, "prose_0002_moon": {"symbolic": false}, ...}"""


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def filter_batch(items: list) -> dict:
    """items: [(id, symbol, excerpt)]. Returns {id: {"symbolic": bool, "meaning": str}}."""
    lines = [f'- {rid}: word="{symbol}" — "{excerpt[:400]}"' for rid, symbol, excerpt in items]
    user = "Excerpts:\n" + "\n".join(lines)
    raw = call_llm(system=SYSTEM_PROMPT, user=user, max_tokens=3000, temperature=0.1,
                   nemotron_model=NEMOTRON_MODEL_PIPELINE)
    result = _parse_json_response(raw, label="symbol_filter")
    return result if isinstance(result, dict) else {}


_SAVE_LOCK = threading.Lock()


def _novel_state(novel_id: str):
    """(candidates, by_id, pending, path) for one novel, or None when there is nothing to classify."""
    cand_path = NOVELS_DIR / novel_id / "symbols" / "candidates.json"
    candidates = load_json(cand_path, [])
    if not isinstance(candidates, list) or not candidates:
        return None
    by_id = {c.get("id"): c for c in candidates if c.get("id")}
    pending = [(c.get("id"), c.get("symbol", ""), c.get("excerpt", "")) for c in candidates if c.get("id") and "_filtered" not in c]
    return candidates, by_id, pending, cand_path


def _filter_batch_into(state, batch: list) -> int:
    """Classify one batch (up to 3 attempts - a transient failure must not drop the candidates until a later restart) and
    write the verdicts into the novel's candidates file. Returns how many candidates were classified."""
    candidates, by_id, _pending, cand_path = state
    verdicts = None
    last_err = None
    for attempt in range(3):
        try:
            verdicts = filter_batch(batch)
            break
        except Exception as e:
            last_err = e
            if attempt < 2:
                print(f"  batch failed ({e}) - retrying ({attempt + 1}/2)")
    if verdicts is None:
        print(f"  batch failed after retries ({last_err}) - skipping, continuing")
        return 0
    batch_n = 0
    for rid, _symbol, _excerpt in batch:
        v = verdicts.get(rid)
        rec = by_id.get(rid)
        if rec is None:
            continue
        rec["_filtered"] = True
        if isinstance(v, dict) and v.get("symbolic"):
            rec["symbolic"] = True
            rec["meaning"] = str(v.get("meaning", ""))[:200]
        else:
            rec["symbolic"] = False
        batch_n += 1
    if batch_n:
        with _SAVE_LOCK:      # the record objects are shared, so concurrent agents' verdicts are all in the list being saved
            save_json(cand_path, candidates)
    return batch_n


def filter_novel(novel_id: str) -> int:
    """One novel on its own (single agent). main() runs every novel through the shared agent pool instead."""
    state = _novel_state(novel_id)
    if not state:
        return 0
    batch_size = engine_batch_size(BATCH_SIZE_NEMOTRON, BATCH_SIZE_OTHER)
    n = 0
    for i in range(0, len(state[2]), batch_size):
        n += _filter_batch_into(state, state[2][i:i + batch_size])
    rebuild_frequency(novel_id, state[0])
    return n


def rebuild_frequency(novel_id: str, candidates: list):
    """Cheap aggregation (no LLM cost) — rebuilt in full from every candidate
    currently marked symbolic, so it always reflects complete state
    regardless of which run tagged which candidate."""
    by_symbol = {}
    for c in candidates:
        if not c.get("symbolic"):
            continue
        sym = c.get("symbol", "")
        entry = by_symbol.setdefault(sym, {"symbol": sym, "mentions": []})
        entry["mentions"].append({
            "chapter": c.get("chapter"),
            "meaning": c.get("meaning", ""),
            "prose_id": c.get("prose_id", ""),
        })

    registry = []
    for sym, entry in by_symbol.items():
        mentions = sorted(entry["mentions"], key=lambda m: (m["chapter"] is None, m["chapter"]))
        chapters = [m["chapter"] for m in mentions if m["chapter"] is not None]
        registry.append({
            "symbol": sym,
            "count": len(mentions),
            "first_chapter": min(chapters) if chapters else None,
            "last_chapter": max(chapters) if chapters else None,
            "mentions": mentions,
        })
    registry.sort(key=lambda e: -e["count"])

    if registry:
        save_json(NOVELS_DIR / novel_id / "symbols" / "frequency.json", registry)


def main():
    from agent_pool import AgentPool
    novel_ids = sys.argv[1:] or [p.name for p in NOVELS_DIR.iterdir() if p.is_dir()]
    batch_size = engine_batch_size(BATCH_SIZE_NEMOTRON, BATCH_SIZE_OTHER)
    states, items = {}, []
    for novel_id in novel_ids:
        if not (NOVELS_DIR / novel_id).is_dir():
            continue
        try:
            st = _novel_state(novel_id)
        except Exception as e:
            print(f"{novel_id}: FAILED ({e}) - skipping, continuing")
            continue
        if not st or not st[2]:
            print(f"{novel_id}: nothing to classify (no candidates or already done)")
            continue
        states[novel_id] = st
        for i in range(0, len(st[2]), batch_size):
            b = st[2][i:i + batch_size]
            items.append({"novel": novel_id, "unit": f"{len(b)} words", "batch": b,
                          "preview": " | ".join(f'{s}: "{e[:80]}"' for _r, s, e in b[:3])})
    # Same agent method as Chapter Mechanics: one agent per Nvidia key, batches dealt round-robin across novels, one batch per
    # novel in flight (they share that novel's candidates file).
    pool = AgentPool("symbol_filtering", model=current_model_label(NEMOTRON_MODEL_PIPELINE), want=4)
    done = {nid: 0 for nid in states}

    def work(it):
        pool.step("classifying symbols", it["preview"])
        n = _filter_batch_into(states[it["novel"]], it["batch"])
        done[it["novel"]] += n
        return n

    pool.run(items, work)
    for nid, st in states.items():
        try:
            rebuild_frequency(nid, st[0])
        except Exception as e:
            print(f"{nid}: frequency rebuild failed ({e})")
        print(f"{nid}: {done[nid]} candidate(s) classified")


if __name__ == "__main__":
    main()
