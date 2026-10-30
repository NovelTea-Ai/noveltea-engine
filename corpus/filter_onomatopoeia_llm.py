"""
filter_onomatopoeia_llm.py - Phase 2 of the onomatopoeia backlog pipeline.

Phase 1 (extract_onomatopoeia_regex.py) casts a wide, cheap regex net and adds
unconfirmed "candidate" entries to the ONE ROOT DICTIONARY: novels/onomatopoeia.json.
This script reviews those candidates PER (novel, chapter) with one LLM call each:
  1. CONFIRM or REJECT every candidate for that chapter (false positives —
     acronyms, character catchphrases, non-sound capitalized words — get
     dropped; real onomatopoeia gets its status flipped to "confirmed").
  2. ADD any genuine onomatopoeia the regex missed entirely (inline uses,
     unusual formatting) as new "confirmed" entries, by re-reading the raw
     chapter text directly — only if not already present in the root
     dictionary for that novel/chapter/word/excerpt.

By default, only (novel, chapter) pairs with at least one "candidate" entry
are sent to the LLM. Pass --full to instead review EVERY chapter already in
deltas_v3 for the target novel(s) — catches onomatopoeia the regex missed
entirely on chapters that produced zero candidates. A reviewed-chapters
sidecar (novels/onomatopoeia_reviewed.json) tracks which (novel, chapter)
pairs have had a full LLM pass, since a chapter with genuinely zero
onomatopoeia adds no entries to the dictionary at all.

This is entirely separate from deltas_v3 / merge.py — same root dictionary,
just a second pass filtering/expanding it.

Usage:
    python filter_onomatopoeia_llm.py --novel my_novel
    python filter_onomatopoeia_llm.py --all
    python filter_onomatopoeia_llm.py --novel my_novel --recheck   # re-review already-reviewed chapters too
    python filter_onomatopoeia_llm.py --all --full                      # review every extracted chapter, not just candidate-bearing ones
"""
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

BRAIN_DIR = Path(__file__).parent
NOVELS_DIR = BRAIN_DIR / "novels"
RAW_DIR = BRAIN_DIR / "raw"
ROOT_DICT_PATH = NOVELS_DIR / "onomatopoeia.json"
REVIEWED_PATH = NOVELS_DIR / "onomatopoeia_reviewed.json"

SYSTEM_PROMPT = """You are reviewing candidate onomatopoeia extracted from a web novel chapter by a regex pass \
(which is deliberately over-inclusive — many candidates will be false positives you need to reject).

Real onomatopoeia = a standalone sound-effect word representing an actual sound (a physical impact, an \
explosion, a creak, a moan, an animal sound, a mechanical beep, etc.), set apart from the surrounding \
sentence — italicized, capitalized, or its own clause/line.

NOT onomatopoeia (reject these): acronyms, a character's name or catchphrase in caps, an ordinary word \
capitalized for EMPHASIS ("I said NO"), a system/UI label, a title, a transliterated non-sound interjection \
used as dialogue filler that isn't actually representing a sound.

You will be given: (1) the full chapter text, (2) a list of CANDIDATE entries already found by regex. \
Return ONLY this JSON object, no markdown fences, no commentary:

{
  "confirmed_candidate_indices": [0, 2, 5],
  "additional_instances": [
    {"word": "thud", "excerpt": "the exact sentence or clause containing it, verbatim from the chapter"}
  ]
}

confirmed_candidate_indices = the 0-based indices (from the CANDIDATES list given) of every candidate that \
IS real onomatopoeia. Every index not listed is treated as rejected.
additional_instances = any GENUINE onomatopoeia present in the chapter text that is NOT already covered by \
one of the candidates (inline mid-sentence sound-words, unusual formatting the regex missed). Empty array is \
normal and expected if the regex candidates already covered everything, or if this chapter has no onomatopoeia \
at all — do not invent examples that aren't actually in the text."""


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


def _load_reviewed() -> set:
    """(novel, chapter) pairs that have already had a full LLM pass under
    --full — tracked separately since a chapter with genuinely zero
    onomatopoeia adds no entries to the root dictionary at all, so the
    dictionary alone can't distinguish 'never reviewed' from 'reviewed,
    found nothing'."""
    if not REVIEWED_PATH.exists():
        return set()
    try:
        data = json.loads(REVIEWED_PATH.read_text(encoding="utf-8"))
        return {tuple(pair) for pair in data} if isinstance(data, list) else set()
    except Exception:
        return set()


def _save_reviewed(reviewed: set):
    REVIEWED_PATH.parent.mkdir(parents=True, exist_ok=True)
    REVIEWED_PATH.write_text(json.dumps(sorted([list(p) for p in reviewed]), ensure_ascii=False), encoding="utf-8")


def _all_extracted_chapters(novel_id: str) -> list:
    deltas_dir = NOVELS_DIR / novel_id / "deltas_v3"
    if not deltas_dir.exists():
        return []
    nums = []
    for p in deltas_dir.glob("ch*.json"):
        m = re.match(r"ch(\d+)\.json$", p.name)
        if m:
            nums.append(int(m.group(1)))
    return sorted(nums)


def _chapters_needing_review(novel_id: str, root: list, recheck: bool, full: bool) -> list:
    if full:
        reviewed = set() if recheck else _load_reviewed()
        return [ch for ch in _all_extracted_chapters(novel_id) if (novel_id, ch) not in reviewed]

    by_chapter = defaultdict(list)
    for e in root:
        if e.get("novel") == novel_id:
            by_chapter[e.get("source_chapter")].append(e)
    if recheck:
        return sorted(by_chapter.keys())
    return sorted(ch for ch, items in by_chapter.items()
                  if any(i.get("status") == "candidate" for i in items))


def review_chapter(novel_id: str, chapter_num: int, chapter_candidates: list) -> dict:
    """One LLM call: confirm/reject this chapter's candidates, and surface any
    onomatopoeia the regex pass missed. Returns {"confirmed_candidate_indices": [...],
    "additional_instances": [...]}."""
    raw_path = RAW_DIR / novel_id / f"ch{chapter_num}.txt"
    if not raw_path.exists():
        return {"confirmed_candidate_indices": [], "additional_instances": []}
    text = raw_path.read_text(encoding="utf-8", errors="ignore")

    candidates_block = "\n".join(f'{idx}. word="{c["word"]}" excerpt="{c["excerpt"]}"'
                                 for idx, c in enumerate(chapter_candidates))

    user_message = f"""CHAPTER {chapter_num} TEXT:

{text[:14000]}{'[... truncated ...]' if len(text) > 14000 else ''}

CANDIDATES (0-indexed):
{candidates_block if candidates_block else '(none — only scanning for anything the regex pass missed)'}"""

    from llm_client import call_llm
    response_text = call_llm(
        system=SYSTEM_PROMPT,
        user=user_message,
        model="claude-sonnet-4-6",
        max_tokens=4000,
        temperature=0.1,
        required_keys=["confirmed_candidate_indices", "additional_instances"],
    )
    json_match = re.search(r"```json\s*\n(.*?)\n```", response_text, re.DOTALL)
    json_str = json_match.group(1) if json_match else response_text.strip()
    try:
        result = json.loads(json_str)
    except json.JSONDecodeError:
        print(f"    [warn] ch{chapter_num}: could not parse LLM response, skipping")
        return {"confirmed_candidate_indices": [], "additional_instances": []}
    result.setdefault("confirmed_candidate_indices", [])
    result.setdefault("additional_instances", [])
    return result


def apply_review(root: list, novel_id: str, chapter_num: int, review: dict) -> tuple:
    """Mutates root in place: flips confirmed candidates' status, drops
    rejected ones, appends new confirmed entries the LLM found (deduped
    against the WHOLE root dictionary, not just this chapter).
    Returns (confirmed_count, rejected_count, added_count)."""
    chapter_candidate_indices = [i for i, e in enumerate(root)
                                 if e.get("novel") == novel_id and e.get("source_chapter") == chapter_num
                                 and e.get("status") == "candidate"]
    confirmed_set = set(review.get("confirmed_candidate_indices") or [])

    to_remove = []
    confirmed_count = 0
    for local_idx, global_idx in enumerate(chapter_candidate_indices):
        if local_idx in confirmed_set:
            root[global_idx]["status"] = "confirmed"
            root[global_idx]["source"] = root[global_idx].get("source", "regex") + "+llm_reviewed"
            confirmed_count += 1
        else:
            to_remove.append(global_idx)
    rejected_count = len(to_remove)
    for idx in sorted(to_remove, reverse=True):
        del root[idx]

    existing_keys = {(e.get("novel"), e.get("source_chapter"), (e.get("word") or "").lower(), (e.get("excerpt") or "")[:120])
                     for e in root}
    added_count = 0
    for extra in review.get("additional_instances") or []:
        word = (extra.get("word") or "").strip().lower()
        excerpt = (extra.get("excerpt") or "").strip()
        if not word or not excerpt:
            continue
        key = (novel_id, chapter_num, word, excerpt[:120])
        if key in existing_keys:
            continue
        existing_keys.add(key)
        root.append({
            "word": word, "excerpt": excerpt, "novel": novel_id, "source_chapter": chapter_num,
            "status": "confirmed", "match_kind": "llm_found", "source": "llm",
            "id": f"onomatopoeia_{len(root) + 1:04d}",
        })
        added_count += 1

    return confirmed_count, rejected_count, added_count


def run_novel(novel_id: str, root: list, recheck: bool, full: bool, reviewed: set):
    chapters = _chapters_needing_review(novel_id, root, recheck, full)
    if not chapters:
        reason = "already reviewed — use --recheck to force" if full else "no candidates, or already reviewed — use --recheck to force"
        print(f"  [{novel_id}] nothing to review ({reason})")
        return 0, 0, 0

    total_confirmed = total_rejected = total_added = 0
    for ch_num in chapters:
        chapter_candidates = [e for e in root if e.get("novel") == novel_id
                              and e.get("source_chapter") == ch_num and e.get("status") == "candidate"]
        review = review_chapter(novel_id, ch_num, chapter_candidates)
        c, r, a = apply_review(root, novel_id, ch_num, review)
        total_confirmed += c
        total_rejected += r
        total_added += a
        save_root_dict(root)  # save after each chapter — safe to interrupt/resume
        if full:
            reviewed.add((novel_id, ch_num))
            _save_reviewed(reviewed)
        print(f"    [{novel_id}] ch{ch_num}: confirmed {c}, rejected {r}, LLM-found {a}")

    print(f"  [{novel_id}] {len(chapters)} chapter(s) reviewed — "
          f"{total_confirmed} confirmed, {total_rejected} rejected, {total_added} new from LLM read")
    return total_confirmed, total_rejected, total_added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--novel", help="single novel id")
    ap.add_argument("--all", action="store_true", help="run for every novel with a deltas_v3 folder")
    ap.add_argument("--recheck", action="store_true",
                    help="re-review chapters even if already reviewed (default: only pending)")
    ap.add_argument("--full", action="store_true",
                    help="review EVERY extracted chapter, not just ones with a regex candidate — "
                         "catches onomatopoeia the regex missed entirely on candidate-free chapters")
    args = ap.parse_args()

    if args.all:
        novel_ids = sorted(p.name for p in NOVELS_DIR.iterdir() if p.is_dir() and (p / "deltas_v3").exists())
    elif args.novel:
        novel_ids = [args.novel]
    else:
        ap.error("pass --novel <id> or --all")
        return

    root = load_root_dict()
    reviewed = _load_reviewed()
    for novel_id in novel_ids:
        run_novel(novel_id, root, args.recheck, args.full, reviewed)

    print(f"\nRoot dictionary ({ROOT_DICT_PATH}) now has {len(root)} total entries.")


if __name__ == "__main__":
    main()
