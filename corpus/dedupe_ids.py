"""Duplicate-ID repair — a data-integrity self-check run automatically at the
start of classify_thread_types.py, not a one-off manual fix.

Two separate extraction/merge runs can end up numbering records from the
same starting point, producing the SAME id string on two DIFFERENT records
(confirmed live: this happened to reveals/log.json and schemes/instances.json
on 8 corpus novels). Since every by-id lookup in the classification pipeline
keys off that id, a collision means one occurrence becomes PERMANENTLY
invisible to every future "still pending" scan, no matter how many times the
job runs — it silently wastes an LLM call on the visible occurrence every
pass while the colliding one never gets touched. This isn't a rare edge
case: across the corpus it accounted for 307 stuck records.

Repairs by renumbering colliding LATER occurrences to a fresh, unique id
(continuing the file's existing numeric sequence) — never touches content or
any existing classification (thread_type etc.), just makes ids unique again
so every record becomes independently trackable.

Usage: repair_novel_ids(novel_dir, [("reveals/log.json", "reveal"), ...])
"""
import json
import re
from pathlib import Path


def repair_duplicate_ids(path: Path, prefix: str) -> list:
    """Returns [(old_id, new_id), ...] for whatever got renumbered."""
    if not path.exists():
        return []
    try:
        recs = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(recs, list):
        return []

    max_num = 0
    for r in recs:
        if not isinstance(r, dict):
            continue
        m = re.match(rf"^{prefix}_(\d+)$", r.get("id") or "")
        if m:
            max_num = max(max_num, int(m.group(1)))

    seen = set()
    renamed = []
    next_num = max_num + 1
    for r in recs:
        if not isinstance(r, dict):
            continue
        rid = r.get("id")
        if not rid:
            continue
        if rid in seen:
            new_id = f"{prefix}_{next_num:04d}"
            next_num += 1
            renamed.append((rid, new_id))
            r["id"] = new_id
        else:
            seen.add(rid)

    if renamed:
        path.write_text(json.dumps(recs, indent=2, ensure_ascii=False), encoding="utf-8")
    return renamed


def repair_novel_ids(novel_dir: Path, targets: list) -> dict:
    """targets: [(relative_path, id_prefix), ...].
    Returns {relative_path: [(old_id, new_id), ...]} for whichever files
    actually had collisions — empty dict when the novel was already clean."""
    out = {}
    for rel_path, prefix in targets:
        renamed = repair_duplicate_ids(novel_dir / rel_path, prefix)
        if renamed:
            out[rel_path] = renamed
    return out
