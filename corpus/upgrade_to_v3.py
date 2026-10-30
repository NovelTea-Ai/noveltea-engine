"""
upgrade_to_v3.py - Merge existing v2 and v2.1 deltas into v3 format

For each chapter of each novel:
  - v2 delta  → contributes plot fields (author_intent, knowledge_state, schemes, etc.)
  - v2.1 delta → contributes style fields (style_dna, character_voice_samples, etc.)
  - v3 output = both layers combined

Chapter coverage:
  - Chapter has BOTH v2 + v2.1 → full v3 (all fields populated)
  - Chapter has v2 ONLY         → v3 with empty style fields
  - Chapter has v2.1 ONLY       → v3 with empty plot fields
  - (no chapter is skipped)

Output: novels/<novel>/deltas_v3/chN.json

Usage:
    python upgrade_to_v3.py                                         # all novels
    python upgrade_to_v3.py --novel my_novel           # one novel
    python upgrade_to_v3.py --novel my_novel --dry-run # preview only
"""

import json
import argparse
from pathlib import Path


# ── helpers ───────────────────────────────────────────────────────────────────

def load_json(path: Path):
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def find_delta(folder: Path, chapter_num: int):
    """Find a delta file by chapter number regardless of zero-padding style."""
    for pattern in [f"ch{chapter_num}.json", f"ch{chapter_num:03d}.json"]:
        p = folder / pattern
        if p.exists():
            return load_json(p)
    return None


def all_chapter_numbers(v2_dir: Path, v21_dir: Path) -> list[int]:
    """Collect every chapter number present in either folder, sorted."""
    nums = set()
    for folder in [v2_dir, v21_dir]:
        if folder.exists():
            for f in folder.glob("*.json"):
                digits = f.stem.lstrip("ch")
                if digits.isdigit():
                    nums.add(int(digits))
    return sorted(nums)


# ── field merging ─────────────────────────────────────────────────────────────

def merge_reader_psychology(v2: dict, v21: dict) -> dict:
    """
    v2  has reader_psychology = {reader_emotions, payoff_categories, tension_curve}
    v2.1 has top-level emotion_targets + tension_curve
    v3  wants reader_psychology with all three sub-keys.
    v2 wins when it has the field; v2.1 fills gaps.
    """
    base = {}
    if v2:
        base = v2.get("reader_psychology") or {}

    # If v2 had nothing, try to build from v2.1 top-level fields
    if v21 and not base:
        et = v21.get("emotion_targets") or {}
        tc = v21.get("tension_curve") or {}
        if et or tc:
            base = {
                "reader_emotions": et,
                "payoff_categories": {},
                "tension_curve": tc
            }

    return base


def merge_scheme_instances(v2: dict, v21: dict) -> list:
    """
    v2  uses scheme_instances (list)
    v2.1 uses schemes (list) — same concept, different key name
    v3  uses scheme_instances.
    Prefer v2 list; supplement with any v2.1 entries not already covered.
    """
    v2_schemes  = (v2  or {}).get("scheme_instances", [])
    v21_schemes = (v21 or {}).get("schemes", [])

    if v2_schemes:
        return v2_schemes
    return v21_schemes  # v2.1-only chapter


def merge_prose_samples(v2: dict, v21: dict) -> list:
    """
    Both versions have prose_samples. v2.1 ones are richer (more fields, more samples).
    Strategy: use whichever list is larger; deduplicate by excerpt prefix.
    """
    v2_samples  = (v2  or {}).get("prose_samples", [])
    v21_samples = (v21 or {}).get("prose_samples", [])

    if not v2_samples:
        return v21_samples
    if not v21_samples:
        return v2_samples

    # Build a set of short excerpt keys from v2 to detect duplicates
    v2_keys = {s.get("excerpt", "")[:60] for s in v2_samples}
    extra = [s for s in v21_samples if s.get("excerpt", "")[:60] not in v2_keys]
    return v2_samples + extra


def build_v3_delta(v2: dict, v21: dict, chapter_num: int) -> dict:
    """Combine v2 and v2.1 data into a single v3 delta."""

    # Shared fields — v2 wins, fall back to v2.1
    def pick(key, default=None):
        if v2 and v2.get(key) not in (None, "", [], {}):
            return v2[key]
        if v21 and v21.get(key) not in (None, "", [], {}):
            return v21[key]
        return default if default is not None else ([] if key in LIST_FIELDS else "")

    LIST_FIELDS = {
        "new_characters", "new_locations", "new_factions", "new_glossary_terms",
        "facts", "timeline_events", "humor_instances", "reveals",
        "antagonist_template_instances"
    }

    delta = {
        "schema_version": "3.0",
        "chapter_number": chapter_num,

        # ── identity ──────────────────────────────────────────────────────
        "chapter_title":       pick("chapter_title"),
        "title_function":      pick("title_function", "none"),
        "chapter_function":    pick("chapter_function", "setup"),
        "summary":             pick("summary"),
        "arc_label_suggestion": pick("arc_label_suggestion"),
        "arc_boundary_signal": pick("arc_boundary_signal", False),
        "arc_notes":           (v2 or {}).get("arc_notes", ""),
        "merge_notes":         (v2 or {}).get("merge_notes", {}),

        # ── entities ──────────────────────────────────────────────────────
        "new_characters":     pick("new_characters", []),
        "new_locations":      pick("new_locations",  []),
        "new_factions":       (v2 or {}).get("new_factions", []),
        "new_glossary_terms": pick("new_glossary_terms", []),

        # ── knowledge graph ───────────────────────────────────────────────
        "facts":           pick("facts",          []),
        "timeline_events": pick("timeline_events", []),
        "humor_instances": pick("humor_instances", []),
        "reveals":         pick("reveals",         []),

        # ── plot intelligence (v2-only fields) ────────────────────────────
        "scheme_instances":              merge_scheme_instances(v2, v21),
        "knowledge_state":               (v2 or {}).get("knowledge_state", []),
        "antagonist_template_instances": (v2 or {}).get("antagonist_template_instances", []),
        "power_curve_notes":             (v2 or {}).get("power_curve_notes", None),

        # ── reader layer ──────────────────────────────────────────────────
        "reader_psychology": merge_reader_psychology(v2, v21),
        "author_intent":     (v2 or {}).get("author_intent", {}),

        # ── style / generation DNA (v2.1-only fields) ─────────────────────
        "prose_samples":            merge_prose_samples(v2, v21),
        "style_dna":                (v21 or {}).get("style_dna", {}),
        "character_voice_samples":  (v21 or {}).get("character_voice_samples", []),
        "scene_structure_patterns": (v21 or {}).get("scene_structure_patterns", {}),
        "narrative_voice_analysis": (v21 or {}).get("narrative_voice_analysis", {}),

        # ── metadata ──────────────────────────────────────────────────────
        "novel_metadata_hints": (v2 or {}).get("novel_metadata_hints", {
            "alt_titles": [], "translator_notes": [], "genre_signals": []
        }),
    }

    return delta


# ── per-novel upgrade ─────────────────────────────────────────────────────────

def upgrade_novel(novel_id: str, dry_run: bool = False) -> tuple[int, int, int]:
    """
    Returns (chapters_written, both_sources, v2_only, v21_only) counts.
    """
    base  = Path("novels") / novel_id
    v2_dir  = base / "deltas_v2"
    v21_dir = base / "deltas_v2_1"
    v3_dir  = base / "deltas_v3"

    chapters = all_chapter_numbers(v2_dir, v21_dir)
    if not chapters:
        print(f"  [{novel_id}] No deltas found — skipping")
        return 0, 0, 0

    written = both = v2_only = v21_only = 0

    for ch in chapters:
        v2  = find_delta(v2_dir,  ch)
        v21 = find_delta(v21_dir, ch)

        source_tag = ""
        if v2 and v21:
            both += 1
            source_tag = "v2+v2.1"
        elif v2:
            v2_only += 1
            source_tag = "v2 only"
        else:
            v21_only += 1
            source_tag = "v2.1 only"

        delta = build_v3_delta(v2, v21, ch)

        out_path = v3_dir / f"ch{ch}.json"
        if dry_run:
            print(f"  [DRY] ch{ch:>4}  {source_tag:<12}  -> {out_path}")
        else:
            save_json(out_path, delta)
            written += 1

    return written, both, v2_only, v21_only


# ── main ──────────────────────────────────────────────────────────────────────

ALL_NOVELS = sorted(p.name for p in (Path(__file__).parent / "novels").iterdir() if p.is_dir()) if (Path(__file__).parent / "novels").exists() else []


def main():
    parser = argparse.ArgumentParser(description="Merge v2 + v2.1 deltas into v3 format")
    parser.add_argument("--novel",   help="Single novel ID (default: all novels)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    args = parser.parse_args()

    novels = [args.novel] if args.novel else ALL_NOVELS

    total_written = 0
    for novel_id in novels:
        print(f"\n-- {novel_id} --")
        written, both, v2_only, v21_only = upgrade_novel(novel_id, dry_run=args.dry_run)
        total_chapters = both + v2_only + v21_only
        print(f"  chapters: {total_chapters}  "
              f"(both={both}, v2-only={v2_only}, v2.1-only={v21_only})  "
              f"-> {'(dry run)' if args.dry_run else f'{written} v3 files written'}")
        total_written += written

    if not args.dry_run:
        print(f"\nDone. {total_written} total v3 deltas written.")
    else:
        print("\n[DRY RUN] No files written.")


if __name__ == "__main__":
    main()
