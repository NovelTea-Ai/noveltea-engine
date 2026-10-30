"""V4 Phase 6 Step 2 — triage report. Reads character_roster/ (built by
build_character_roster.py) and produces a markdown shortlist, top N per
novel by weight, for the author to review BEFORE any LLM spend (step 3).
Read-only — does not touch character_roster/ or character_dna/.

Usage:
    python build_roster_shortlist.py            # top 15 per novel (default)
    python build_roster_shortlist.py --n 20
"""
import json
import sys
from pathlib import Path

ROSTER_DIR = Path(__file__).parent / "character_roster"
OUT_PATH = Path(__file__).parent / "ROSTER_SHORTLIST.md"

# Names that are obviously extraction placeholders, not real character names
# — confirmed live: "Protagonist" surfaced at #3 in my_novel
# purely on weight, which would silently feed a placeholder into step 3's LLM
# call if not flagged. Flagged in the report, not auto-excluded — the author
# should decide, not this script.
_PLACEHOLDER_MARKERS = {"protagonist", "antagonist", "narrator", "unknown", "unnamed", "mc", "the protagonist"}


def is_placeholder(name: str) -> bool:
    return name.strip().lower() in _PLACEHOLDER_MARKERS


def load_roster():
    by_novel = {}
    for novel_dir in sorted(ROSTER_DIR.iterdir()):
        if not novel_dir.is_dir():
            continue
        chars = []
        for f in novel_dir.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            chars.append(d)
        if chars:
            by_novel[novel_dir.name] = chars
    return by_novel


def main():
    n = 15
    if "--n" in sys.argv:
        n = int(sys.argv[sys.argv.index("--n") + 1])

    by_novel = load_roster()
    total_chars = sum(len(v) for v in by_novel.values())
    total_shortlisted = 0
    total_placeholders_flagged = 0

    lines = [
        "# Character Roster — Step 2 Shortlist",
        "",
        f"Generated from `character_roster/` — {total_chars} characters across "
        f"{len(by_novel)} novels. Top {n} per novel by weight "
        f"(`facts + 3×voice_samples + 2×semantic_enrichment + mentions`), for "
        f"review BEFORE any LLM spend (Phase 6 Step 3). Nothing below has been "
        f"sent to an LLM — this is a read-only ranking of already-collected data.",
        "",
        "**⚠ = flagged as a likely extraction placeholder, not a real character "
        "name** (e.g. \"Protagonist\") — review before including in a Step 3 build.",
        "",
    ]

    for novel_id, chars in by_novel.items():
        chars_sorted = sorted(chars, key=lambda c: -c["weight"])
        top = chars_sorted[:n]
        total_shortlisted += len(top)

        lines.append(f"## {novel_id}  _{len(chars)} characters total_")
        lines.append("")
        lines.append("| Weight | Name | Facts | Quotes | Enrichment | Curated DNA |")
        lines.append("|---|---|---|---|---|---|")
        for c in top:
            flag = "⚠ " if is_placeholder(c["canonical_name"]) else ""
            if flag:
                total_placeholders_flagged += 1
            curated = "✓" if c["has_curated_dna"] else ""
            lines.append(
                f"| {c['weight']} | {flag}{c['canonical_name']} | {len(c['facts'])} | "
                f"{len(c['voice_samples'])} | {len(c['semantic_enrichment'])} | {curated} |"
            )
        lines.append("")

    lines.insert(6, f"**{total_shortlisted} characters shortlisted** "
                    f"({total_placeholders_flagged} flagged as possible placeholders).")
    lines.insert(7, "")

    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_PATH} — {total_shortlisted} characters shortlisted across {len(by_novel)} novels "
          f"({total_placeholders_flagged} flagged)")


if __name__ == "__main__":
    main()
