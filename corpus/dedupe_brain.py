"""Remove exact duplicate records from a novel's merged brain (the copies a chapter left when it was merged more than once).

    python dedupe_brain.py <novel_id>            dry run: counts what would be removed, writes nothing
    python dedupe_brain.py <novel_id> --apply    backs the novel up first (corpus/_backups/), then removes the duplicates
    python dedupe_brain.py --all [--apply]       every novel

A record is a duplicate when an identical record (every field the same, ids ignored) for the SAME chapter already appears earlier in the
same list. Only records that name a chapter are touched, only the later copies go, and the first one keeps its id. A list of chapter
numbers (appearances, chapters) loses repeated numbers. Chapter deltas, the rolling summary, the genome and the conflicts file are never
touched. The search index is checked for identical repeated chunks too.
"""
import json
import re
import sqlite3
import sys
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).parent
NOVELS = HERE / "novels"
PRIMARY = ("chapter", "source_chapter", "established_chapter", "setup_chapter", "created_chapter", "first_seen_chapter",
           "first_chapter", "from_chapter", "start_chapter", "introduced_chapter")
INT_LISTS = ("chapters", "appearances", "setup_chapters")
SKIP = ("rolling_summary.json", "narrative_genome.json", "conflicts.json", "novel_metadata.json")


def chapter_of(d):
    for k in PRIMARY:
        v = d.get(k)
        if isinstance(v, int) and not isinstance(v, bool):
            return v
    m = re.match(r"^fact_ch(\d+)_", str(d.get("id", "")))
    return int(m.group(1)) if m else None


def sig(d):
    return json.dumps({k: v for k, v in d.items() if k != "id"}, sort_keys=True, ensure_ascii=False)


def dedupe(o, stats, where):
    if isinstance(o, list):
        out, seen = [], set()
        for x in o:
            x = dedupe(x, stats, where)
            if isinstance(x, dict) and chapter_of(x) is not None:
                k = (chapter_of(x), sig(x))
                if k in seen:
                    stats[where] = stats.get(where, 0) + 1
                    continue
                seen.add(k)
            out.append(x)
        return out
    if isinstance(o, dict):
        for k in list(o):
            v = o[k]
            if k in INT_LISTS and isinstance(v, list) and v and all(isinstance(i, int) for i in v):
                u = list(dict.fromkeys(v))
                if len(u) != len(v):
                    stats[where + ":" + k] = stats.get(where + ":" + k, 0) + (len(v) - len(u))
                o[k] = u
            elif isinstance(v, (list, dict)):
                o[k] = dedupe(v, stats, where)
        return o
    return o


def backup(novel):
    dest = HERE / "_backups" / f"{novel}_before_dedupe_{time.strftime('%Y%m%d_%H%M')}.zip"
    dest.parent.mkdir(exist_ok=True)
    root = NOVELS / novel
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for f in root.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(NOVELS).as_posix())
    return dest


def run(novel, apply):
    root = NOVELS / novel
    if not root.is_dir():
        print("no such novel:", novel)
        return {}
    if apply:
        print(f"  backup: {backup(novel).name}")
    stats, touched = {}, 0
    for f in sorted(root.rglob("*.json")):
        rel = f.relative_to(root).as_posix()
        if rel.startswith("deltas_") or f.name in SKIP or ".bak" in f.name or rel.startswith("set_pieces/") or rel.startswith("symbols/"):
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        before = json.dumps(d, sort_keys=True, ensure_ascii=False)
        where = "entities" if rel.startswith("entities/") else rel
        r = dedupe(d, stats, where)
        if json.dumps(r, sort_keys=True, ensure_ascii=False) != before:
            touched += 1
            if apply:
                f.write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
    # the search index: identical repeated chunks
    dbn = 0
    db = HERE / "knowledge_index.db"
    if db.exists():
        c = sqlite3.connect(str(db), timeout=60)
        dbn = c.execute("select count(*) from chunks where id not in (select min(id) from chunks where novel_id=? group by category, chapter, text) and novel_id=?",
                        (novel, novel)).fetchone()[0]
        if apply and dbn:
            c.execute("delete from chunks where novel_id=? and id not in (select min(id) from chunks where novel_id=? group by category, chapter, text)", (novel, novel))
            c.commit()
        c.close()
    total = sum(stats.values())
    print(f"{'APPLIED' if apply else 'dry run'} {novel}: {total} duplicate record(s) in {touched} file(s)"
          + (f", {dbn} repeated search-index chunk(s)" if dbn else ""))
    top = sorted(stats.items(), key=lambda kv: -kv[1])[:6]
    if top:
        print("   " + "; ".join(f"{k}: {v}" for k, v in top))
    return {"removed": total, "files": touched, "index": dbn}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply = "--apply" in sys.argv
    novels = sorted(p.name for p in NOVELS.iterdir() if p.is_dir()) if "--all" in sys.argv else args
    if not novels:
        print(__doc__)
        return
    tot = 0
    for n in novels:
        r = run(n, apply)
        tot += r.get("removed", 0)
    print(f"TOTAL {'removed' if apply else 'would remove'}: {tot}")


if __name__ == "__main__":
    main()
