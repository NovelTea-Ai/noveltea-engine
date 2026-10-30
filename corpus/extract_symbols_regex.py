"""Symbol/motif tracking (V4 Phase 3, doc Layer 10 "Symbol Tracking").

The one capability in the V4 doc with no existing raw ingredient to process —
unlike Promise Drift and thread typing, nothing in the extraction pipeline
already flags recurring symbols. Follows the same precedent already in this
codebase as onomatopoeia (extract_onomatopoeia_regex.py + filter_onomatopoeia_llm.py):
a cheap regex harvest of candidate mentions, filtered by a second cheap LLM
pass (filter_symbols_llm.py) that decides which mentions are actually
symbolic/thematic rather than incidental/literal.

Reads from prose/samples.json (already-extracted curated excerpts, ~150-250
per novel), NOT raw chapter text — keeps this near-zero additional cost, same
scoping discipline as Phase 2's thread typing.

Idempotent, and it KEEPS the filtering stage's verdicts: candidates.json is the
only place filter_symbols_llm.py stores what it decided (_filtered / symbolic /
meaning), so a re-harvest (the Corpus Builder runs it after every re-extraction)
carries those fields over for every candidate whose id AND excerpt are unchanged.
Only genuinely new or changed candidates come out unfiltered. (It used to rebuild
the file from scratch, which silently wiped every verdict of a re-extracted novel.)

Usage: python extract_symbols_regex.py [novel_id ...]   (no args = every novel)
Writes symbols/candidates.json per novel.
"""
import json
import re
import sys
from pathlib import Path

NOVELS_DIR = Path(__file__).parent / "novels"

# Seed vocabulary straight from the V4 doc's Layer 10 example list. Matched as
# a word-family (base word + suffix, e.g. "moon" also catches "moonlight",
# "moonlit", "moons") rather than exact-word-only, since symbol mentions are
# often compound/adjectival forms in translated web-novel prose.
SEED_SYMBOLS = [
    "fire", "water", "moon", "sword", "tree", "bird",
    "blood", "silence", "voice", "darkness", "light",
]

_PATTERNS = {sym: re.compile(rf"\b{re.escape(sym)}\w*\b", re.IGNORECASE) for sym in SEED_SYMBOLS}


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def harvest_novel(novel_id: str) -> int:
    root = NOVELS_DIR / novel_id
    samples_path = root / "prose" / "samples.json"
    samples = load_json(samples_path, [])
    if not isinstance(samples, list) or not samples:
        return 0

    candidates = []
    seen = set()  # (symbol, prose_id) — one candidate per symbol per excerpt, not per occurrence
    for s in samples:
        excerpt = s.get("excerpt")
        if not isinstance(excerpt, str) or not excerpt.strip():
            continue
        prose_id = s.get("id", "")
        chapter = s.get("source_chapter")
        for sym, pattern in _PATTERNS.items():
            key = (sym, prose_id)
            if key in seen or not pattern.search(excerpt):
                continue
            seen.add(key)
            candidates.append({
                "id": f"{prose_id}_{sym}",
                "symbol": sym,
                "prose_id": prose_id,
                "chapter": chapter,
                "excerpt": excerpt,
            })

    if not candidates:
        return 0
    cand_path = root / "symbols" / "candidates.json"
    old = load_json(cand_path, [])
    if isinstance(old, list):
        prior = {c.get("id"): c for c in old if isinstance(c, dict) and c.get("id")}
        for c in candidates:
            o = prior.get(c["id"])
            if o and o.get("excerpt") == c["excerpt"]:     # same id AND same text: the old verdict still applies
                for k in ("_filtered", "symbolic", "meaning"):
                    if k in o:
                        c[k] = o[k]
    tmp = cand_path.with_suffix(".json.tmp")                # write whole, then swap in: a kill mid-write can't leave a half file
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(candidates, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(cand_path)
    return len(candidates)


def main():
    novel_ids = sys.argv[1:] or [p.name for p in NOVELS_DIR.iterdir() if p.is_dir()]
    for novel_id in novel_ids:
        if not (NOVELS_DIR / novel_id).is_dir():
            continue
        try:
            n = harvest_novel(novel_id)
            print(f"{novel_id}: {n} candidate mention(s) harvested" if n else f"{novel_id}: no candidates (no prose samples or no matches)")
        except Exception as e:
            print(f"{novel_id}: FAILED ({e}) — skipping, continuing")


if __name__ == "__main__":
    main()
