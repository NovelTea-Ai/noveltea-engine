"""List every chapter that needs (re)downloading, per novel.

Two kinds of hole:
  corrupt  - a .htm exists but is all null bytes (interrupted write); the
             converter refuses it, so no .txt was ever produced.
  missing  - no file of any kind for that chapter number.

Both need the same fix: fetch the chapter again.
"""
import re
from pathlib import Path

RAW = Path(__file__).parent / "raw"
OUT = Path(__file__).with_name("chapters_to_download.txt")

# Highest chapter known to exist for a novel, when that is BEYOND what is on
# disk. Without this the scan can only infer the range from files present, so
# a hole at the END of a novel is invisible — deleting corrupt tail files makes
# those chapters silently disappear from the report instead of being listed as
# missing. Add an entry whenever the true chapter count is known.
KNOWN_LAST = {
    # "my_novel": 1665,      # the true last chapter, so a missing tail shows up in the report
}


def num(stem):
    m = re.search(r"(\d+)", stem)
    return int(m.group(1)) if m else None


def spans(nums):
    """Collapse a sorted int list into contiguous 'a-b' runs."""
    runs, start, prev = [], None, None
    for n in nums:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            runs.append((start, prev))
            start = prev = n
    if start is not None:
        runs.append((start, prev))
    return ", ".join(f"{a}-{b}" if a != b else str(a) for a, b in runs)


report = []
grand_corrupt = grand_missing = 0

for d in sorted(p for p in RAW.iterdir() if p.is_dir()):
    have, corrupt = set(), set()
    for f in d.glob("*.txt"):
        n = num(f.stem)
        if n:
            have.add(n)
    for f in list(d.glob("*.htm")) + list(d.glob("*.html")):
        n = num(f.stem)
        if n is None:
            continue
        b = f.read_bytes()
        if not b or b.count(0) == len(b):
            corrupt.add(n)
        else:
            have.add(n)

    alln = have | corrupt
    if not alln:
        continue
    lo, hi = min(alln), max(alln)
    # Extend past what's on disk when the real chapter count is known, so holes
    # at the end of a novel are reported rather than falling outside the range.
    hi = max(hi, KNOWN_LAST.get(d.name, 0))
    missing = sorted(set(range(lo, hi + 1)) - alln)
    corrupt = sorted(corrupt)
    if not missing and not corrupt:
        continue

    grand_corrupt += len(corrupt)
    grand_missing += len(missing)
    need = sorted(set(missing) | set(corrupt))

    report.append(f"{d.name}")
    report.append(f"  range on disk : {lo}-{hi}  ({len(have)} good)")
    if corrupt:
        report.append(f"  corrupt ({len(corrupt)}) : {spans(corrupt)}")
    if missing:
        report.append(f"  missing ({len(missing)}) : {spans(missing)}")
    report.append(f"  TO DOWNLOAD ({len(need)}) : {spans(need)}")
    report.append(f"  flat list    : {','.join(str(n) for n in need)}")
    report.append("")

header = [
    "CHAPTERS NEEDING DOWNLOAD",
    "=" * 60,
    f"corrupt (null-byte .htm on disk) : {grand_corrupt}",
    f"missing (no file at all)         : {grand_missing}",
    f"TOTAL                            : {grand_corrupt + grand_missing}",
    "",
    "Novels not listed below are complete.",
    "",
]
text = "\n".join(header + report)
OUT.write_text(text, encoding="utf-8")
print(text)
print(f"[saved] {OUT}")
