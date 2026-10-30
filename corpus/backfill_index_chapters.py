"""
backfill_index_chapters.py — give already-indexed chunks the chapter they came
from, without re-embedding anything.

The index builders used to store prose, dialogue and many humor/reveal chunks with
no chapter (see chapter_lookup.py). They now look the chapter up in deltas_v3, so
a fresh build gets it right; this fills the same chapters into the rows already in
knowledge_index.db. Only rows whose chapter is empty are touched, and only the
chapter column: the text and its embedding stay as they are, so incremental
re-runs of the builders still recognise every row (they key on category, chapter
and text, and now compute the same chapter).

Usage: python backfill_index_chapters.py [--dry-run] [novel_id ...]   (no ids = every novel)
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build_knowledge_index as bki
import build_humor_index as bhi

ROOT = Path(__file__).parent
DB = ROOT / "knowledge_index.db"
# {novel_id: chunk ids checked with no chapter found} — read by the Pipeline tab's "Index Chapters" progress bar
UNMATCHED = ROOT / "index_chapters_unmatched.json"
def _int(ch):
    try:
        return int(ch)
    except (TypeError, ValueError):
        return None             # junk in a chapter field ("Implied questions throughout the story")


CATS = ("prose", "dialogue", "humor", "reveal", "symbol", "scheme")


def main(argv):
    dry = "--dry-run" in argv
    only = [a for a in argv if not a.startswith("--")]
    conn = sqlite3.connect(DB)
    novels = [r[0] for r in conn.execute("SELECT DISTINCT novel_id FROM chunks")]
    total_fixed = total_empty = 0
    import json
    try:
        unmatched = json.loads(UNMATCHED.read_text(encoding="utf-8"))
    except Exception:
        unmatched = {}
    for nid in sorted(novels):
        if only and nid not in only:
            continue
        ndir = bki.NOVELS_DIR / nid
        if not (ndir / "deltas_v3").is_dir():
            continue
        want = {}
        for cat, text, ch, _meta in bki._collect_candidates(ndir):
            if cat in CATS and _int(ch) is not None:
                want.setdefault((cat, text), _int(ch))
        try:
            for text, ch, _meta in bhi.collect(ndir):
                if _int(ch) is not None:
                    want.setdefault(("humor", text), _int(ch))
        except Exception as e:
            print(f"  WARN {nid}: humor collect failed: {str(e)[:100]}")
        rows = conn.execute(
            f"SELECT id, category, text FROM chunks WHERE novel_id=? AND chapter IS NULL "
            f"AND category IN ({','.join('?' * len(CATS))})", (nid, *CATS)).fetchall()
        fixes = [(want[(cat, text)], rid) for rid, cat, text in rows if (cat, text) in want]
        unmatched[nid] = [rid for rid, cat, text in rows if (cat, text) not in want]
        by_cat = {}
        for rid, cat, text in rows:
            got = (cat, text) in want
            a, b = by_cat.get(cat, (0, 0))
            by_cat[cat] = (a + got, b + 1)
        total_fixed += len(fixes)
        total_empty += len(rows)
        print(f"{nid}: {len(fixes)} of {len(rows)} chapter-less chunks get a chapter  "
              + "  ".join(f"{c} {a}/{b}" for c, (a, b) in sorted(by_cat.items())))
        if fixes and not dry:
            # OR IGNORE: a text indexed twice (once with its chapter, once without) would become an exact twin
            conn.executemany("UPDATE OR IGNORE chunks SET chapter=? WHERE id=?", fixes)
            twins = [rid for ch, rid in fixes if conn.execute(
                "SELECT 1 FROM chunks a JOIN chunks b ON b.novel_id=a.novel_id AND b.category=a.category "
                "AND b.text=a.text AND b.chapter=? WHERE a.id=? AND a.chapter IS NULL", (ch, rid)).fetchone()]
            conn.executemany("DELETE FROM chunks WHERE id=? AND chapter IS NULL", [(r,) for r in twins])
            if twins:
                print(f"  {len(twins)} chapter-less duplicate(s) of an already-chaptered chunk removed")
            conn.commit()
    if not dry:
        UNMATCHED.write_text(json.dumps(unmatched), encoding="utf-8")
    print(f"{'DRY RUN — ' if dry else ''}{total_fixed} of {total_empty} chapter-less chunks "
          f"{'would get' if dry else 'now have'} a chapter")
    conn.close()


if __name__ == "__main__":
    main(sys.argv[1:])
