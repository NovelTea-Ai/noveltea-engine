"""
refresh_style_dna_evolution.py - Rebuild novels/<id>/prose/style_dna_evolution.json
from the per-chapter deltas (deltas_v3/chNN.json), one entry per chapter.

Why this exists: merge.py's aggregate_style_dna() only APPENDS to that file, so
(a) every re-merge of the same delta added another copy of that chapter (thousands
of duplicate chapters accumulated across the corpus), and (b) the style_dna
backfill (repair_style_dna.py) patched the deltas but never reached this
aggregate, leaving stale all-zero content_ratios there. Re-running merge.py to
"refresh" it would just append more duplicates, so this script rebuilds the one
derived file from its source of truth instead.

Safety (the corpus data must never be lost):
  - Reads deltas only; never writes to deltas_v3/ or any other file.
  - Dry run by default; pass --apply to write.
  - Before overwriting, copies the old file to style_dna_evolution.json.bak-<stamp>
    (never overwritten, never deleted by this script).
  - Only chapters whose delta has a style_dna block are included, matching
    aggregate_style_dna(). Test-artifact files (ch3.compare-nemotron.json) skipped.

Usage:
    python refresh_style_dna_evolution.py                 # dry run, whole corpus
    python refresh_style_dna_evolution.py --apply
    python refresh_style_dna_evolution.py --apply --novel my_novel
"""

import argparse
import json
import re
import shutil
import time
from pathlib import Path

NOVELS_DIR = Path(__file__).parent / "novels"
_CH_RE = re.compile(r"^ch(\d+)\.json$")


def rebuild(novel_dir: Path) -> list:
    entries = []
    for f in (novel_dir / "deltas_v3").glob("ch*.json"):
        m = _CH_RE.match(f.name)
        if not m:
            continue
        try:
            delta = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(delta, dict) and "style_dna" in delta:
            entries.append({"chapter": delta.get("chapter_number") or int(m.group(1)),
                            "style_dna": delta["style_dna"]})
    entries.sort(key=lambda e: e["chapter"])
    return entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    ap.add_argument("--novel", help="restrict to one novel id")
    args = ap.parse_args()

    stamp = time.strftime("%Y%m%d-%H%M%S")
    dirs = [NOVELS_DIR / args.novel] if args.novel else sorted(p for p in NOVELS_DIR.iterdir() if p.is_dir())
    total_old = total_new = 0
    for nd in dirs:
        if not (nd / "deltas_v3").exists():
            continue
        new = rebuild(nd)
        target = nd / "prose" / "style_dna_evolution.json"
        old_n = 0
        if target.exists():
            try:
                old_n = len(json.loads(target.read_text(encoding="utf-8")))
            except Exception:
                old_n = -1
        total_old += max(old_n, 0)
        total_new += len(new)
        print(f"{nd.name}: {old_n} entries -> {len(new)}")
        if args.apply and new:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.copy2(target, target.with_name(f"{target.name}.bak-{stamp}"))
            target.write_text(json.dumps(new, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{'APPLIED' if args.apply else 'DRY RUN'}: {total_old} entries -> {total_new}")


if __name__ == "__main__":
    main()
