"""
extract_onomatopoeia_regex.py - Pure-regex (no LLM), phase 1 of the
onomatopoeia backlog pipeline.

Scans the RAW chapter text for chapters that already have a deltas_v3/chN.json
(i.e. chapters already brought into that novel's merged corpus knowledge base)
for candidate sound-effect words/lines, and adds any not already present as
non-duplicate entries to ONE ROOT DICTIONARY: novels/onomatopoeia.json. Every
entry is tagged with which novel and chapter it came from. No LLM call, no
cost: this is a mechanical pattern match, not narrative judgment.

Deliberately WIDE net — false positives are expected and cheap to produce
here, since phase 2 (filter_onomatopoeia_llm.py) reviews every "candidate"
entry and either confirms or rejects it.

This is entirely separate from deltas_v3 / merge.py — a standalone dictionary
that only this pipeline reads and writes.

Usage:
    python extract_onomatopoeia_regex.py --novel my_novel
    python extract_onomatopoeia_regex.py --all
Then, to review the candidates with one LLM pass:
    python filter_onomatopoeia_llm.py --novel my_novel
    python filter_onomatopoeia_llm.py --all
"""
import argparse
import json
import re
from pathlib import Path

BRAIN_DIR = Path(__file__).parent
NOVELS_DIR = BRAIN_DIR / "novels"
RAW_DIR = BRAIN_DIR / "raw"
ROOT_DICT_PATH = NOVELS_DIR / "onomatopoeia.json"

# WIDE candidate patterns — deliberately loose, phase 2 (LLM) is the real filter:
#   1. A line consisting only of one or more *Word* tokens (the classic device:
#      "*Boom*", "*Crack* *Crack* *Crack*").
#   2. A line consisting only of one or more ALL-CAPS short words, optionally
#      with punctuation ("BOOM!", "CRASH! CRASH!") — same device, different markup.
#   3. Any *Word* token appearing INLINE within a longer line (mid-sentence
#      onomatopoeia) — a lower-confidence candidate for phase 2 to judge.
_STANDALONE_STAR_LINE = re.compile(r"^\s*(\*[A-Za-z]{2,14}\*[!.,\s]*){1,6}\s*$")
_STANDALONE_CAPS_LINE = re.compile(r"^\s*([A-Z]{3,14}[!.,\s]*){1,6}\s*$")
_STAR_TOKEN = re.compile(r"\*([A-Za-z]{2,14})\*")
_INLINE_CAPS_TOKEN = re.compile(r"\b([A-Z]{4,14})\b")

# Words that are ALL-CAPS in normal prose for reasons that have nothing to do
# with sound (acronyms, emphasis on ordinary words, roman numerals) — skip
# these outright rather than passing obvious noise to the LLM filter pass.
_CAPS_STOPWORDS = {
    "THE", "AND", "YOU", "NOT", "ALL", "BUT", "WHY", "HOW", "WHO", "WHAT",
    "STOP", "WAIT", "NEVER", "ALWAYS", "REALLY", "PLEASE", "SORRY", "THANKS",
    "OKAY", "YES", "NO", "HELLO", "GOODBYE", "MASTER", "SENIOR", "ELDER",
}


def _extracted_chapter_numbers(novel_id: str) -> set:
    """Chapter numbers this novel already has a deltas_v3/chN.json for —
    onomatopoeia should only cover chapters already in the merged knowledge
    base, not raw text that hasn't been through the normal pipeline yet."""
    deltas_dir = NOVELS_DIR / novel_id / "deltas_v3"
    if not deltas_dir.exists():
        return set()
    nums = set()
    for p in deltas_dir.glob("ch*.json"):
        m = re.match(r"ch(\d+)\.json$", p.name)
        if m:
            nums.add(int(m.group(1)))
    return nums


def _candidates_from_line(line: str, novel_id: str, ch_num: int) -> list:
    stripped = line.strip()
    if not stripped:
        return []
    out = []

    if _STANDALONE_STAR_LINE.match(line):
        for word in dict.fromkeys(w.lower() for w in _STAR_TOKEN.findall(line)):
            out.append({"word": word, "excerpt": stripped, "novel": novel_id, "source_chapter": ch_num,
                       "status": "candidate", "match_kind": "standalone_star_line"})
        return out

    if _STANDALONE_CAPS_LINE.match(line):
        for word in dict.fromkeys(w.lower() for w in _INLINE_CAPS_TOKEN.findall(line) if w not in _CAPS_STOPWORDS):
            out.append({"word": word, "excerpt": stripped, "novel": novel_id, "source_chapter": ch_num,
                       "status": "candidate", "match_kind": "standalone_caps_line"})
        return out

    for word in dict.fromkeys(w.lower() for w in _STAR_TOKEN.findall(line)):
        out.append({"word": word, "excerpt": stripped, "novel": novel_id, "source_chapter": ch_num,
                   "status": "candidate", "match_kind": "inline_star"})
    return out


def extract_novel(novel_id: str) -> list:
    """Scan raw chapters already covered by deltas_v3 for this novel, return
    a flat list of WIDE candidate onomatopoeia dicts, each tagged with novel
    and chapter — for phase 2 (filter_onomatopoeia_llm.py) to review."""
    chapters = _extracted_chapter_numbers(novel_id)
    instances = []
    for ch_num in sorted(chapters):
        raw_path = RAW_DIR / novel_id / f"ch{ch_num}.txt"
        if not raw_path.exists():
            continue
        try:
            text = raw_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for line in text.split("\n"):
            instances.extend(_candidates_from_line(line, novel_id, ch_num))
    return instances


def load_root_dict() -> list:
    if not ROOT_DICT_PATH.exists():
        return []
    try:
        data = json.loads(ROOT_DICT_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_root_dict(entries: list):
    ROOT_DICT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ROOT_DICT_PATH.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def merge_into_root(root: list, new_instances: list) -> int:
    """Appends only entries not already present (by novel+chapter+word+excerpt)
    to the root dictionary list, in place. Returns count added."""
    seen = {(e.get("novel"), e.get("source_chapter"), (e.get("word") or "").lower(), (e.get("excerpt") or "")[:120])
            for e in root}
    added = 0
    for inst in new_instances:
        key = (inst["novel"], inst["source_chapter"], inst["word"], inst["excerpt"][:120])
        if key in seen:
            continue
        seen.add(key)
        inst = dict(inst)
        inst["id"] = f"onomatopoeia_{len(root) + 1:04d}"
        inst["source"] = "regex"
        root.append(inst)
        added += 1
    return added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--novel", help="single novel id")
    ap.add_argument("--all", action="store_true", help="run for every novel with a deltas_v3 folder")
    args = ap.parse_args()

    if args.all:
        novel_ids = sorted(p.name for p in NOVELS_DIR.iterdir() if p.is_dir() and (p / "deltas_v3").exists())
    elif args.novel:
        novel_ids = [args.novel]
    else:
        ap.error("pass --novel <id> or --all")
        return

    root = load_root_dict()
    total_added = 0
    for novel_id in novel_ids:
        found = extract_novel(novel_id)
        added = merge_into_root(root, found)
        total_added += added
        print(f"  [{novel_id}] scanned {len(_extracted_chapter_numbers(novel_id))} extracted chapters, "
              f"found {len(found)} candidates, added {added} new non-duplicate entries")
        save_root_dict(root)  # save after each novel — safe to interrupt/resume

    print(f"\nPhase 1 done. {total_added} new candidate entries added to {ROOT_DICT_PATH} "
          f"(root dictionary now has {len(root)} total entries).")
    print("Run filter_onomatopoeia_llm.py next to confirm/reject candidates and catch anything phase 1 missed.")


if __name__ == "__main__":
    main()
