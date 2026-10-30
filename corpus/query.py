#!/usr/bin/env python3
"""
Query Layer — NovelTea Engine Knowledge Brain Query Functions
=========================================================

Purpose:
  Provides programmatic read access to the accumulated wiki brain.
  These functions are the primary interface for the chapter planner
  and generator to query novel state, open threads, entity states,
  and reader psychology patterns.

  All queries read from JSON files (not SQLite) — JSON is the source
  of truth. SQLite is for analytics only.

Functions:
  - get_entity_state()      - all active facts for an entity as of chapter N
  - get_open_threads()      - unresolved plot threads at chapter N
  - get_chapter_context()   - full context bundle for generating chapter N+1
  - get_tension_targets()   - suggested tension curve based on recent chapters
  - search_humor_patterns() - find humor instances by type/pattern
  - get_recent_chapters()   - load recent chapter deltas for continuity
  - get_prose_samples()     - find prose samples by type
  - get_active_relationships() - get all active relationships for entity
  - get_power_progression() - get character power history
  - get_arc_state()         - current arc label and position

Usage:
  from query import get_chapter_context, get_open_threads

  context = get_chapter_context("my_novel", 110)
  threads = get_open_threads("my_novel", 110)
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any

NOVELS_DIR = Path(__file__).parent / "novels"


def load_json(path: Path, default=None):
    """Load JSON file, return default if not found."""
    if not path.exists():
        return default if default is not None else {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def novel_paths(novel_id: str) -> Dict[str, Path]:
    """Return dict of all file/dir paths for a novel."""
    root = NOVELS_DIR / novel_id
    return {
        "root": root,
        "entities": root / "entities",
        "timeline": root / "timeline" / "events.json",
        "arcs": root / "timeline" / "arcs.json",
        "glossary": root / "glossary" / "terms.json",
        "humor": root / "humor" / "instances.json",
        "schemes": root / "schemes" / "instances.json",
        "knowledge": root / "knowledge" / "state.json",
        "prose": root / "prose" / "samples.json",
        "antagonist_templates": root / "templates" / "antagonists.json",
        "power_curve": root / "power_curve" / "notes.json",
        "reader_psychology": root / "reader_psychology" / "chapters.json",
        "author_intent": root / "author_intent" / "chapters.json",
        "reveals": root / "reveals" / "log.json",
        "novel_meta": root / "novel_metadata.json",
        "deltas_v3": root / "deltas_v3",
    }


def get_entity_state(novel_id: str, entity_id: str, at_chapter: int) -> Dict[str, Any]:
    """
    Return all active facts for an entity as of chapter N.

    Reads the entity JSON file, filters facts where:
    - source_chapter <= at_chapter
    - status == 'active' (or missing status field, which defaults to active)

    Args:
        novel_id: Novel identifier
        entity_id: Entity slug (e.g., "hero_name")
        at_chapter: Chapter number to query state at

    Returns:
        Dict with entity metadata and filtered facts:
        {
            "canonical_name": str,
            "type": str,
            "aliases": [str],
            "facts": [fact dicts],
            "roles": [str] (if character),
            "chapter_state": int (the at_chapter value)
        }
    """
    paths = novel_paths(novel_id)
    entity_file = paths["entities"] / f"{entity_id}.json"

    entity_data = load_json(entity_file, {})
    if not entity_data:
        return {
            "canonical_name": entity_id,
            "type": "unknown",
            "aliases": [],
            "facts": [],
            "chapter_state": at_chapter,
            "found": False
        }

    # Filter facts to those that apply at this chapter
    active_facts = []
    for fact in entity_data.get("facts", []):
        source_ch = fact.get("source_chapter", 0)
        status = fact.get("status", "active")

        # Include if: introduced by this chapter AND still active
        if source_ch <= at_chapter and status == "active":
            active_facts.append(fact)

    return {
        "canonical_name": entity_data.get("canonical_name", entity_id),
        "type": entity_data.get("type", "unknown"),
        "aliases": entity_data.get("aliases", []),
        "facts": active_facts,
        "roles": entity_data.get("roles", []) if entity_data.get("type") == "character" else [],
        "chapter_state": at_chapter,
        "found": True
    }


def get_open_threads(novel_id: str, as_of_chapter: int) -> Dict[str, Any]:
    """
    Return all unresolved plot threads as of chapter N.

    Searches for:
    - Reveals with setup_chapters but no payoff_chapter (or payoff > as_of_chapter)
    - Schemes where execution happened but payoff_chapter is None or future
    - Knowledge gaps not yet resolved

    Args:
        novel_id: Novel identifier
        as_of_chapter: Chapter number to query open threads at

    Returns:
        Dict with categorized open threads:
        {
            "unresolved_reveals": [reveal dicts],
            "ongoing_schemes": [scheme dicts],
            "knowledge_gaps": [knowledge_state dicts],
            "total_open_threads": int
        }
    """
    paths = novel_paths(novel_id)

    # Load reveals
    reveals = load_json(paths["reveals"], [])
    unresolved_reveals = []
    for reveal in reveals:
        payoff_ch = reveal.get("payoff_chapter")
        setup_chs = reveal.get("setup_chapters", [])

        # Reveal is open if: setup started, but no payoff yet or payoff is in future
        if setup_chs and max(setup_chs) <= as_of_chapter:
            if payoff_ch is None or payoff_ch > as_of_chapter:
                unresolved_reveals.append(reveal)

    # Load schemes
    schemes = load_json(paths["schemes"], [])
    ongoing_schemes = []
    for scheme in schemes:
        setup_ch = scheme.get("setup_chapter", 0)
        payoff_ch = scheme.get("payoff_chapter")
        status = scheme.get("status", "ongoing")

        # Scheme is open if: started but not completed, or status is ongoing
        if setup_ch <= as_of_chapter:
            if payoff_ch is None or payoff_ch > as_of_chapter or status == "ongoing":
                ongoing_schemes.append(scheme)

    # Load knowledge state
    knowledge_states = load_json(paths["knowledge"], [])
    knowledge_gaps = []
    for ks in knowledge_states:
        established_ch = ks.get("established_chapter", 0)
        resolved_ch = ks.get("resolved_chapter")

        # Gap is open if: established but not yet resolved
        if established_ch <= as_of_chapter:
            if resolved_ch is None or resolved_ch > as_of_chapter:
                knowledge_gaps.append(ks)

    return {
        "unresolved_reveals": unresolved_reveals,
        "ongoing_schemes": ongoing_schemes,
        "knowledge_gaps": knowledge_gaps,
        "total_open_threads": len(unresolved_reveals) + len(ongoing_schemes) + len(knowledge_gaps)
    }


def get_recent_chapters(novel_id: str, up_to_chapter: int, count: int = 3) -> List[Dict[str, Any]]:
    """
    Load the most recent N chapter delta files.

    Args:
        novel_id: Novel identifier
        up_to_chapter: Load chapters up to and including this number
        count: How many recent chapters to load (default: 3)

    Returns:
        List of chapter delta dicts, ordered from oldest to newest
    """
    paths = novel_paths(novel_id)
    deltas_dir = paths["deltas_v3"]

    if not deltas_dir.exists():
        return []

    # Calculate which chapters to load
    start_chapter = max(1, up_to_chapter - count + 1)
    chapters = []

    for ch_num in range(start_chapter, up_to_chapter + 1):
        ch_file = deltas_dir / f"ch{ch_num}.json"
        ch_data = load_json(ch_file)
        if ch_data:
            chapters.append(ch_data)

    return chapters


def get_tension_targets(novel_id: str, chapter_num: int, lookback: int = 5) -> Dict[str, Any]:
    """
    Suggest tension curve targets for chapter N based on recent chapters.

    Analyzes last N chapters to avoid:
    - Flatness (5 consecutive low-tension chapters)
    - Whiplash (peak→peak→peak without recovery)

    Args:
        novel_id: Novel identifier
        chapter_num: Chapter to generate targets for
        lookback: How many previous chapters to analyze (default: 5)

    Returns:
        Dict with suggested tension targets:
        {
            "suggested_start": int (0-100),
            "suggested_peak": int (0-100),
            "suggested_end": int (0-100),
            "reasoning": str,
            "recent_pattern": str (e.g., "flat", "rising", "volatile")
        }
    """
    paths = novel_paths(novel_id)
    reader_psych = load_json(paths["reader_psychology"], [])

    # Get recent chapters' tension curves
    recent_tensions = []
    for entry in reader_psych:
        if entry.get("chapter", 0) >= (chapter_num - lookback) and entry.get("chapter", 0) < chapter_num:
            curve = entry.get("tension_curve", {})
            if curve:
                recent_tensions.append(curve)

    if not recent_tensions:
        # No data, suggest baseline
        return {
            "suggested_start": 75,
            "suggested_peak": 85,
            "suggested_end": 78,
            "reasoning": "No recent tension data available, using baseline targets",
            "recent_pattern": "unknown"
        }

    # Calculate averages
    avg_end = sum(t.get("end", 75) for t in recent_tensions) / len(recent_tensions)
    avg_peak = sum(t.get("peak", 80) for t in recent_tensions) / len(recent_tensions)

    # Detect patterns
    peaks = [t.get("peak", 80) for t in recent_tensions]
    is_flat = max(peaks) - min(peaks) < 15
    is_volatile = all(p > 85 for p in peaks[-3:]) if len(peaks) >= 3 else False

    # Generate suggestions
    if is_flat:
        # Add variety — spike higher
        return {
            "suggested_start": int(avg_end),
            "suggested_peak": int(min(95, avg_peak + 15)),
            "suggested_end": int(avg_end + 5),
            "reasoning": "Recent chapters show flat tension; suggesting escalation",
            "recent_pattern": "flat"
        }
    elif is_volatile:
        # Cool down — give reader breathing room
        return {
            "suggested_start": int(avg_end - 10),
            "suggested_peak": int(max(70, avg_peak - 15)),
            "suggested_end": int(avg_end - 5),
            "reasoning": "Recent chapters sustained high tension; suggesting cooldown",
            "recent_pattern": "volatile"
        }
    else:
        # Maintain current rhythm
        return {
            "suggested_start": int(avg_end),
            "suggested_peak": int(avg_peak + 3),
            "suggested_end": int(avg_end + 2),
            "reasoning": "Maintaining current tension rhythm with slight escalation",
            "recent_pattern": "rising"
        }


def search_humor_patterns(novel_id: str, pattern_type: Optional[str] = None,
                          participant: Optional[str] = None,
                          tone_tag: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Find humor instances matching criteria.

    Args:
        novel_id: Novel identifier
        pattern_type: Humor type to filter by (e.g., "deadpan_reaction", "situational_irony")
        participant: Entity name to filter by
        tone_tag: Tone tag to filter by (e.g., "dark_comedy", "dramatic_irony")

    Returns:
        List of matching humor instance dicts
    """
    paths = novel_paths(novel_id)
    humor_instances = load_json(paths["humor"], [])

    results = []
    for instance in humor_instances:
        # Apply filters
        if pattern_type and instance.get("type") != pattern_type:
            continue
        if participant and participant not in instance.get("participants", []):
            continue
        if tone_tag and tone_tag not in instance.get("tone_tags", []):
            continue

        results.append(instance)

    return results


def get_prose_samples(novel_id: str, sample_type: Optional[str] = None,
                      recent_chapters: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Find prose samples by type, optionally filtered to recent chapters.

    Args:
        novel_id: Novel identifier
        sample_type: Type to filter by (e.g., "internal_monologue", "action_beat", "banter")
        recent_chapters: If set, only return samples from last N chapters

    Returns:
        List of matching prose sample dicts
    """
    paths = novel_paths(novel_id)
    prose_samples = load_json(paths["prose"], [])

    results = []
    max_chapter = max((s.get("source_chapter", 0) for s in prose_samples), default=0)
    cutoff_chapter = max_chapter - recent_chapters if recent_chapters else 0

    for sample in prose_samples:
        # Apply filters
        if sample_type and sample.get("type") != sample_type:
            continue
        if recent_chapters and sample.get("source_chapter", 0) < cutoff_chapter:
            continue

        results.append(sample)

    return results


def get_active_relationships(novel_id: str, entity_id: str, at_chapter: int) -> Dict[str, List[str]]:
    """
    Get all active relationships for an entity at chapter N.

    Returns categorized relationships: allies, enemies, family, romantic partners.

    Args:
        novel_id: Novel identifier
        entity_id: Entity slug
        at_chapter: Chapter number

    Returns:
        Dict of relationship types to entity names:
        {
            "allies": [entity_names],
            "enemies": [entity_names],
            "family": [entity_names],
            "romantic": [entity_names]
        }
    """
    entity_state = get_entity_state(novel_id, entity_id, at_chapter)

    relationships = {
        "allies": [],
        "enemies": [],
        "family": [],
        "romantic": []
    }

    for fact in entity_state.get("facts", []):
        predicate = fact.get("predicate", "")
        obj = fact.get("object", "")

        if predicate == "ally_of":
            relationships["allies"].append(obj)
        elif predicate == "enemy_of":
            relationships["enemies"].append(obj)
        elif predicate == "family_of":
            relationships["family"].append(obj)
        elif predicate == "romantic_with":
            relationships["romantic"].append(obj)

    return relationships


def get_power_progression(novel_id: str, entity_id: str, up_to_chapter: int) -> List[Dict[str, Any]]:
    """
    Get the power progression history for a character.

    Returns all has_power_rank facts in chronological order.

    Args:
        novel_id: Novel identifier
        entity_id: Entity slug
        up_to_chapter: Include power ranks up to this chapter

    Returns:
        List of power rank changes with chapters:
        [
            {"chapter": int, "rank": str, "status": str},
            ...
        ]
    """
    entity_state = get_entity_state(novel_id, entity_id, up_to_chapter)

    power_ranks = []
    for fact in entity_state.get("facts", []):
        if fact.get("predicate") == "has_power_rank":
            power_ranks.append({
                "chapter": fact.get("source_chapter", 0),
                "rank": fact.get("object", ""),
                "status": fact.get("status", "active"),
                "notes": fact.get("notes", "")
            })

    # Sort by chapter
    power_ranks.sort(key=lambda x: x["chapter"])
    return power_ranks


def get_arc_state(novel_id: str, at_chapter: int) -> Dict[str, Any]:
    """
    Get current arc label and position at chapter N.

    Args:
        novel_id: Novel identifier
        at_chapter: Chapter number

    Returns:
        Dict with arc information:
        {
            "current_arc": str,
            "arc_start_chapter": int,
            "chapters_into_arc": int,
            "arc_chapters": [int]
        }
    """
    paths = novel_paths(novel_id)
    arcs = load_json(paths["arcs"], [])

    # arcs.json is a list of arc objects, not a dict
    # Find which arc contains this chapter
    for arc_entry in arcs:
        arc_label = arc_entry.get("label", "Unknown Arc")
        chapters = arc_entry.get("chapters", [])
        if at_chapter in chapters:
            return {
                "current_arc": arc_label,
                "arc_start_chapter": min(chapters) if chapters else at_chapter,
                "chapters_into_arc": at_chapter - min(chapters) + 1 if chapters else 1,
                "arc_chapters": chapters,
                "arc_chapter_count": len(chapters)
            }

    # Chapter not in any labeled arc
    return {
        "current_arc": None,
        "arc_start_chapter": at_chapter,
        "chapters_into_arc": 1,
        "arc_chapters": [at_chapter],
        "arc_chapter_count": 1
    }


def get_chapter_context(novel_id: str, chapter_num: int) -> Dict[str, Any]:
    """
    Return the full context bundle needed to generate chapter N+1.

    This is the primary function used by the chapter planner.

    Includes:
    - Recent chapter summaries and reader psychology
    - Entity states for recently active characters
    - Open plot threads
    - Current arc state
    - Tension targets
    - Power curve position for protagonist
    - Recent prose samples

    Args:
        novel_id: Novel identifier
        chapter_num: Generate context for planning this chapter

    Returns:
        Comprehensive context dict for chapter generation
    """
    paths = novel_paths(novel_id)

    # Load novel metadata
    novel_meta = load_json(paths["novel_meta"], {})

    # Get recent chapters for continuity
    recent_chapters = get_recent_chapters(novel_id, chapter_num - 1, count=3)

    # Extract entities mentioned in recent chapters
    recent_entities = set()
    for ch in recent_chapters:
        for char in ch.get("new_characters", []):
            recent_entities.add(char.get("name", "").lower().replace(" ", "_"))

    # Get entity states for recent characters
    entity_states = {}
    for entity_id in recent_entities:
        if entity_id:
            entity_states[entity_id] = get_entity_state(novel_id, entity_id, chapter_num - 1)

    # Get protagonist state (always include)
    protagonist_id = None
    for entity_id, state in entity_states.items():
        if "protagonist" in state.get("roles", []):
            protagonist_id = entity_id
            break

    # If no protagonist found in recent entities, try to load from character DNA
    if not protagonist_id:
        # Fallback: try common protagonist entity names
        for candidate in ["protagonist", "hero", "main_character"]:
            test_state = get_entity_state(novel_id, candidate, chapter_num - 1)
            if test_state.get("found"):
                protagonist_id = candidate
                entity_states[candidate] = test_state
                break

    # Get open threads
    open_threads = get_open_threads(novel_id, chapter_num - 1)

    # Get arc state
    arc_state = get_arc_state(novel_id, chapter_num - 1)

    # Get tension targets
    tension_targets = get_tension_targets(novel_id, chapter_num)

    # Get recent reader psychology for pattern analysis
    reader_psych = load_json(paths["reader_psychology"], [])
    recent_psychology = [
        entry for entry in reader_psych
        if entry.get("chapter", 0) >= chapter_num - 3 and entry.get("chapter", 0) < chapter_num
    ]

    # Get recent prose samples
    prose_samples = get_prose_samples(novel_id, recent_chapters=20)

    # Get protagonist power progression
    protagonist_power = []
    if protagonist_id:
        protagonist_power = get_power_progression(novel_id, protagonist_id, chapter_num - 1)

    return {
        "novel_id": novel_id,
        "target_chapter": chapter_num,
        "novel_metadata": novel_meta,
        "recent_chapters": recent_chapters,
        "entity_states": entity_states,
        "protagonist_id": protagonist_id,
        "protagonist_power_progression": protagonist_power,
        "open_threads": open_threads,
        "arc_state": arc_state,
        "tension_targets": tension_targets,
        "recent_psychology": recent_psychology,
        "prose_samples": prose_samples,
        "total_entities_loaded": len(entity_states)
    }


# Convenience function for debugging
def print_chapter_context_summary(context: Dict[str, Any]):
    """Print a human-readable summary of chapter context."""
    print(f"\n=== Chapter Context for {context['novel_id']} Ch.{context['target_chapter']} ===\n")
    print(f"Protagonist: {context['protagonist_id']}")
    print(f"Current Arc: {context['arc_state']['current_arc']}")
    print(f"Chapters into arc: {context['arc_state']['chapters_into_arc']}")
    print(f"\nOpen Threads: {context['open_threads']['total_open_threads']}")
    print(f"  - Unresolved reveals: {len(context['open_threads']['unresolved_reveals'])}")
    print(f"  - Ongoing schemes: {len(context['open_threads']['ongoing_schemes'])}")
    print(f"  - Knowledge gaps: {len(context['open_threads']['knowledge_gaps'])}")
    print(f"\nTension Targets:")
    print(f"  Start: {context['tension_targets']['suggested_start']}")
    print(f"  Peak: {context['tension_targets']['suggested_peak']}")
    print(f"  End: {context['tension_targets']['suggested_end']}")
    print(f"  Pattern: {context['tension_targets']['recent_pattern']}")
    print(f"\nEntities Loaded: {context['total_entities_loaded']}")
    print(f"Recent Chapters: {len(context['recent_chapters'])}")
    print(f"Prose Samples Available: {len(context['prose_samples'])}")


if __name__ == "__main__":
    # Example usage / testing
    import sys

    if len(sys.argv) < 3:
        print("Usage: python query.py <novel_id> <chapter_num>")
        print("Example: python query.py my_novel 111")
        sys.exit(1)

    novel_id = sys.argv[1]
    chapter_num = int(sys.argv[2])

    print(f"Loading chapter context for {novel_id}, chapter {chapter_num}...")
    context = get_chapter_context(novel_id, chapter_num)
    print_chapter_context_summary(context)

    # Show some open threads
    if context['open_threads']['total_open_threads'] > 0:
        print("\n=== Sample Open Threads ===")
        for reveal in context['open_threads']['unresolved_reveals'][:3]:
            print(f"\nReveal: {reveal.get('content', 'N/A')}")
            print(f"  Type: {reveal.get('reveal_type', 'N/A')}")
            print(f"  Setup: ch.{reveal.get('setup_chapters', [])}")
