"""Plot thread typing (V4 Phase 2, doc Layer 21 "Plot Intelligence").

Cheap classification pass over records extract_v3.py already produced —
reveals/log.json, schemes/instances.json, knowledge/state.json — tagging
each with a `thread_type` from a small controlled vocabulary. This is NOT a
new extraction pass over chapter text: the input is the short existing JSON
records (already merged/deduped by merge.py), not the raw chapters, so a
whole novel's worth of records fits in a handful of batched LLM calls
instead of one call per chapter.

Idempotent/resumable: records that already carry a thread_type are skipped,
so a partial or repeated run only classifies what's missing.

Usage: python classify_thread_types.py [novel_id ...]   (no args = every novel)
Writes thread_type back into reveals/log.json, schemes/instances.json,
knowledge/state.json in place — the same canonical files merge.py owns.
"""
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract_v3 import _parse_json_response  # reuse the same tolerant JSON-from-LLM parser
from llm_client import call_llm, engine_batch_size, current_model_label
from dedupe_ids import repair_novel_ids

_DEDUPE_TARGETS = [
    ("reveals/log.json", "reveal"),
    ("schemes/instances.json", "scheme"),
    ("knowledge/state.json", "knowledge"),
]

NOVELS_DIR = Path(__file__).parent / "novels"
BATCH_SIZE_NEMOTRON = 1    # one record per call — maximum live-status granularity
BATCH_SIZE_OTHER = 40      # Claude (and every other engine) — proven reliable at this size

# Pinned for THIS pipeline only — deliberately does NOT touch models.nemotron
# in Settings, which is the author's own pick for chapter generation/dialogue
# shaping (kept on Ultra 550B). Classifying a record into 1 of 6 fixed
# categories doesn't need Ultra's reasoning depth; tested live: Ultra ran
# 13-90s per call (queues on shared infra), Nano 30B ran a consistent ~2-5s
# for identical real content, same correct answer.
# nemotron-3-nano-30b-a3b was retired by NVIDIA on 2026-09-01 (HTTP 410 Gone);
# the "renamed" nemotron-nano-3-30b-a3b is listed but 404s for this account.
# The same-class live model (nemotron-3.5-lightning-30b-a3b) proved slow and
# unreliable for JSON output, so this pipeline now uses Ultra.
NEMOTRON_MODEL_PIPELINE = "nvidia/nemotron-3-ultra-550b-a55b"   # see filter_symbols_llm.py: lightning-30b was slow and unreliable for JSON output

THREAD_TYPES = ("mystery", "foreshadowing", "twist", "red_herring", "chekhovs_gun", "subplot")

SYSTEM_PROMPT = f"""You are tagging narrative thread records from an already-extracted web novel with a plot-intelligence taxonomy.

For each record given, choose exactly one thread_type from this controlled vocabulary:
- mystery: an unanswered question the reader is meant to actively wonder about
- foreshadowing: an early hint or setup that points toward a specific later payoff
- twist: a reveal that overturns the reader's or a character's prior understanding
- red_herring: a deliberately misleading setup that does NOT pay off as the setup implied
- chekhovs_gun: an established detail, object, or ability that is planted so it can matter later
- subplot: a self-contained secondary thread not central to the main plot

Respond with ONLY a JSON object mapping each given id to its thread_type — no prose, no markdown fences:
{{"reveal_0001": "twist", "scheme_0004": "subplot", ...}}"""


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _s(v, limit: int = None) -> str:
    """Coerce a field to str before slicing — some corpus records have a
    non-string value (an int, a list) in a field the schema expects to be
    text, which crashed this script mid-run on real data (see the classify
    novel my_novel incident: an `impact` field was an int)."""
    s = v if isinstance(v, str) else ("" if v is None else str(v))
    return s[:limit] if limit else s


def _record_summary(kind: str, r: dict) -> str:
    if kind == "reveal":
        return f"{_s(r.get('reveal_type'))}: {_s(r.get('content'), 180)} (impact: {_s(r.get('impact'), 120)})"
    if kind == "scheme":
        return f"{_s(r.get('goal'), 120)} via {_s(r.get('mechanism'), 120)} (status: {_s(r.get('status'))})"
    if kind == "knowledge":
        return f"{_s(r.get('fact'), 180)} (resolution: {_s(r.get('resolution') or 'unresolved', 120)})"
    return ""


def classify_batch(items: list) -> dict:
    """items: [(id, kind, summary)]. Returns {id: thread_type}."""
    lines = [f"- [{kind}] {rid}: {summary}" for rid, kind, summary in items]
    user = "Records:\n" + "\n".join(lines)
    raw = call_llm(system=SYSTEM_PROMPT, user=user, max_tokens=4000, temperature=0.1,
                   nemotron_model=NEMOTRON_MODEL_PIPELINE)
    result = _parse_json_response(raw, label="thread_type_classify")
    return {k: v for k, v in result.items() if v in THREAD_TYPES} if isinstance(result, dict) else {}


def _build_batch_queue(novel_ids: list, batch_size: int) -> dict:
    """{novel_id: [(path, kind, batch_items), ...]} — every novel's PENDING
    (not yet thread_type'd) records, pre-split into batch_size-sized chunks.
    Built once up front so main() can round-robin one batch per novel per
    round instead of exhausting one novel before starting the next — if the
    process dies mid-run, progress is spread evenly across every novel
    instead of some at 100% and others untouched."""
    queue = {}
    for novel_id in novel_ids:
        root = NOVELS_DIR / novel_id
        if not root.is_dir():
            continue
        batches = []
        for path, kind in [(root / "reveals" / "log.json", "reveal"),
                            (root / "schemes" / "instances.json", "scheme"),
                            (root / "knowledge" / "state.json", "knowledge")]:
            if not path.exists():
                continue
            records = load_json(path, [])
            if not isinstance(records, list) or not records:
                continue
            pending = [(r.get("id"), kind, _record_summary(kind, r)) for r in records
                       if r.get("id") and not r.get("thread_type")]
            for i in range(0, len(pending), batch_size):
                batches.append((path, kind, pending[i:i + batch_size]))
        if batches:
            queue[novel_id] = batches
    return queue


_SAVE_LOCK = threading.Lock()


def _process_one_batch(novel_id: str, path: Path, kind: str, batch: list) -> int:
    """Classify one batch, then (under a lock, re-reading the file fresh) write the tags back. Several agents can work on
    the same novel at once: the slow model call is outside the lock, so no agent overwrites another's tags."""
    tagged = classify_batch(batch)
    n = 0
    with _SAVE_LOCK:
        records = load_json(path, [])
        if not isinstance(records, list):
            return 0
        by_id = {r.get("id"): r for r in records if r.get("id")}
        for rid, thread_type in tagged.items():
            if rid in by_id:
                by_id[rid]["thread_type"] = thread_type
                n += 1
        if n:
            save_json(path, records)
    return n


def main():
    novel_ids = sys.argv[1:] or sorted(p.name for p in NOVELS_DIR.iterdir() if p.is_dir())

    # Self-heal FIRST, before anything is scanned for pending work — a
    # duplicate id makes one occurrence permanently invisible to the
    # pending-scan below, silently wasting every future classification
    # attempt on it (confirmed live: 307 records stuck this way across 8
    # novels before this check existed). Free — pure JSON read/write, no LLM
    # calls — so it runs on every invocation, not just when something looks
    # stuck.
    total_repaired = 0
    for novel_id in novel_ids:
        repaired = repair_novel_ids(NOVELS_DIR / novel_id, _DEDUPE_TARGETS)
        for rel_path, renamed in repaired.items():
            print(f"  DEDUPE {novel_id}/{rel_path}: repaired {len(renamed)} colliding duplicate id(s)")
            total_repaired += len(renamed)
    if total_repaired:
        print(f"DEDUPE: {total_repaired} duplicate id(s) repaired across the corpus this run")

    batch_size = engine_batch_size(BATCH_SIZE_NEMOTRON, BATCH_SIZE_OTHER)
    queue = _build_batch_queue(novel_ids, batch_size)
    total_batches = sum(len(b) for b in queue.values())
    print(f"Round-robin: {len(queue)} novel(s), {total_batches} batch(es) of up to {batch_size} records queued")

    # Same agent method as the Chapter Mechanics job: one worker per Nvidia key, batches dealt round-robin across novels so the
    # agents sit on different novels, one batch per novel in flight (each batch rewrites that collection's file).
    from agent_pool import AgentPool
    items = []
    for novel_id, batches in queue.items():
        for path, kind, batch in batches:
            items.append({"novel": novel_id, "unit": kind, "path": path, "kind": kind, "batch": batch,
                          "preview": " | ".join(s for _r, _k, s in batch[:3])})
    pool = AgentPool("thread_typing", model=current_model_label(NEMOTRON_MODEL_PIPELINE), want=4)
    totals = {nid: 0 for nid in queue}
    MAX_RETRIES = 2

    def work(it):
        n = 0
        for attempt in range(MAX_RETRIES + 1):
            pool.step(f"classifying {it['kind']} ({len(it['batch'])})", it["preview"])
            try:
                n = _process_one_batch(it["novel"], it["path"], it["kind"], it["batch"])
            except Exception as e:
                print(f"  {it['novel']}/{it['kind']}: batch FAILED ({e})")
                n = 0
            if n:
                break
            if attempt < MAX_RETRIES:
                print(f"  {it['novel']}/{it['kind']}: 0 tagged - retrying ({attempt + 1}/{MAX_RETRIES})")
        totals[it["novel"]] += n
        print(f"  {it['novel']}/{it['kind']}: tagged {n} (novel total: {totals[it['novel']]})")
        return n

    pool.run(items, work)
    for nid, n in totals.items():
        print(f"{nid}: complete - {n} record(s) tagged this run")
    print("All novels' pending records classified.")


if __name__ == "__main__":
    main()
