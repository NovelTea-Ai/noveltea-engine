"""One-time (and re-runnable) backfill for knowledge/state.json's missing `id`
fields.

merge_knowledge_state() in merge.py only ever assigned `id` to brand-new
records; a legacy record matched by fact text on a later re-merge never got
one backfilled, so records extracted before that line existed stayed id-less
forever. Confirmed across the corpus: reveals/log.json and schemes/
instances.json are 100% id-covered on all 16 novels, but knowledge/state.json
is missing ids on 14 of 16 (26,363 of 38,622 total corpus records) — this is
what silently made classify_thread_types.py skip ~90% of knowledge_state
records (it can only merge an LLM's answer back to a record by id). The root
cause is now fixed in merge.py for future merges; this repairs already-written
files.

Usage: python backfill_knowledge_ids.py [novel_id ...]  (no args = every novel)
"""
import json
import sys
from pathlib import Path

NOVELS_DIR = Path(__file__).parent / "novels"


def backfill(path: Path) -> int:
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if not isinstance(records, list):
        return 0

    nums = []
    for r in records:
        rid = isinstance(r, dict) and r.get("id")
        if isinstance(rid, str) and rid.startswith("knowledge_") and rid.split("_")[-1].isdigit():
            nums.append(int(rid.split("_")[-1]))
    next_num = (max(nums) + 1) if nums else 1

    n = 0
    for r in records:
        if isinstance(r, dict) and not r.get("id"):
            r["id"] = f"knowledge_{next_num:04d}"
            next_num += 1
            n += 1

    if n:
        path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    return n


def main():
    novel_ids = sys.argv[1:] or [p.name for p in NOVELS_DIR.iterdir() if p.is_dir()]
    for novel_id in novel_ids:
        f = NOVELS_DIR / novel_id / "knowledge" / "state.json"
        if not f.exists():
            continue
        n = backfill(f)
        print(f"{novel_id}: backfilled {n} id(s)" if n else f"{novel_id}: already complete")


if __name__ == "__main__":
    main()
