#!/usr/bin/env python3
"""
Chapter Planner — NovelTea Engine Decision Engine
===========================================

Purpose:
  The most important missing piece. Takes the current novel state and
  produces a chapter_plan.json that tells the writer LLM exactly what
  to write.

  This is the "actual author brain" — it makes strategic decisions about:
  - Which chapter_function to use (setup, escalation, payoff, etc.)
  - Which open threads to advance
  - What emotion targets to hit
  - What tension curve to follow
  - Which entities should appear
  - Whether a reveal happens

  The LLM is only the final writer. This planner is the strategist.

Input:
  - novel_id
  - chapter_number
  - optional: arc_label override
  - optional: chapter_function override

Output:
  - chapter_plan.json with complete generation instructions

Usage:
  python planner.py <novel_id> <chapter_number>
  python planner.py my_novel 111
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any
from collections import Counter

from query import (
    get_chapter_context
)

NOVELS_DIR = Path(__file__).parent / "novels"


def determine_chapter_function(
    context: Dict[str, Any],
    recent_chapters: List[Dict[str, Any]],
    override: Optional[str] = None
) -> str:
    """
    Determine appropriate chapter_function based on arc rhythm.

    Rules:
    - Can't have 5 setup chapters in a row (leads to flatness)
    - After 2-3 escalation chapters, need a payoff
    - Cooldown chapters follow major payoffs or climaxes
    - Arc finales must be payoff/climax/resolution

    Valid functions: setup, escalation, payoff, climax, resolution,
                     transition, hook, cooldown, arc_finale, reveal

    Args:
        context: Full chapter context from query layer
        recent_chapters: Last 5 chapter deltas
        override: Manual override if specified

    Returns:
        chapter_function string
    """
    if override:
        return override

    # Analyze recent chapter functions
    recent_functions = [ch.get("chapter_function", "setup") for ch in recent_chapters]
    function_counts = Counter(recent_functions)

    # Get arc state
    arc_state = context.get("arc_state", {})
    chapters_into_arc = arc_state.get("chapters_into_arc", 1)

    # Rule 1: Prevent flatness (5 consecutive setup chapters)
    if len(recent_functions) >= 4 and all(f == "setup" for f in recent_functions[-4:]):
        return "escalation"

    # Rule 2: After prolonged escalation, must pay off
    if len(recent_functions) >= 3 and all(f == "escalation" for f in recent_functions[-3:]):
        return "payoff"

    # Rule 3: After payoff/climax, cooldown unless arc is ending
    if recent_functions and recent_functions[-1] in ["payoff", "climax"]:
        if chapters_into_arc < 5:  # Not near arc end
            return "cooldown"

    # Rule 4: Arc rhythm
    if chapters_into_arc == 1:
        return "setup"
    elif chapters_into_arc == 2:
        return "setup"
    elif 3 <= chapters_into_arc <= 5:
        return "escalation"
    elif chapters_into_arc >= 6:
        # Later in arc, rotate between escalation and payoff
        if function_counts.get("payoff", 0) < function_counts.get("escalation", 0):
            return "payoff"
        else:
            return "escalation"

    # Default
    return "escalation"


def select_payoff_categories(
    context: Dict[str, Any],
    chapter_function: str
) -> Dict[str, int]:
    """
    Select which payoff categories to hit this chapter.

    Rotate through categories to avoid repeating the same payoff type
    every chapter. Some chapter functions naturally emphasize certain
    payoffs.

    Args:
        context: Full chapter context
        chapter_function: The determined chapter function

    Returns:
        Dict of payoff_category -> score (0-10)
    """
    # Get recent psychology to avoid repetition
    recent_psych = context.get("recent_psychology", [])
    recent_payoffs = []
    for entry in recent_psych:
        recent_payoffs.extend(entry.get("payoff_categories", {}).keys())

    payoff_counter = Counter(recent_payoffs)

    # Base payoffs by chapter function
    payoffs = {}

    if chapter_function == "setup":
        payoffs = {"anticipation": 7, "discovery": 6}
    elif chapter_function == "escalation":
        payoffs = {"tension": 8, "power_fantasy": 6}
    elif chapter_function == "payoff":
        # Rotate to least-used payoff from recent chapters
        available = ["power_fantasy", "justice", "revenge", "strategic_victory",
                     "catharsis", "wish_fulfillment"]
        least_used = min(available, key=lambda x: payoff_counter.get(x, 0))
        payoffs = {least_used: 9, "satisfaction": 7}
    elif chapter_function == "climax":
        payoffs = {"catharsis": 10, "power_fantasy": 9, "tension": 8}
    elif chapter_function == "cooldown":
        payoffs = {"emotional_connection": 7, "comedy": 6}
    elif chapter_function == "reveal":
        payoffs = {"mystery": 9, "discovery": 8}
    else:
        # Default mix
        payoffs = {"tension": 6, "anticipation": 6}

    return payoffs


def select_emotion_targets(
    context: Dict[str, Any],
    chapter_function: str,
    payoff_categories: Dict[str, int]
) -> Dict[str, int]:
    """
    Set target reader emotions for this chapter.

    Emotions should align with chapter_function and payoff_categories.

    Args:
        context: Full chapter context
        chapter_function: The determined chapter function
        payoff_categories: Selected payoff categories

    Returns:
        Dict of emotion -> score (0-10)
    """
    # Base emotions by chapter function
    emotions = {}

    if chapter_function == "setup":
        emotions = {"anticipation": 7, "curiosity": 7}
    elif chapter_function == "escalation":
        emotions = {"tension": 8, "anticipation": 7, "fear": 5}
    elif chapter_function == "payoff":
        emotions = {"satisfaction": 9, "awe": 7}
    elif chapter_function == "climax":
        emotions = {"awe": 9, "tension": 9, "satisfaction": 8}
    elif chapter_function == "cooldown":
        emotions = {"satisfaction": 6, "comedy": 7}
    elif chapter_function == "reveal":
        emotions = {"curiosity": 9, "awe": 8}
    else:
        emotions = {"anticipation": 6, "tension": 6}

    # Adjust based on payoff categories
    if "comedy" in payoff_categories:
        emotions["comedy"] = max(emotions.get("comedy", 0), payoff_categories["comedy"])

    return emotions


def select_threads_to_advance(
    open_threads: Dict[str, Any],
    chapter_function: str,
    max_threads: int = 2
) -> List[Dict[str, Any]]:
    """
    Choose which open threads to advance this chapter.

    Rules:
    - Payoff chapters should resolve at least one thread
    - Setup chapters can introduce threads without resolving
    - Don't advance more than 2-3 threads per chapter (focus)

    Args:
        open_threads: All open threads from query layer
        chapter_function: The determined chapter function
        max_threads: Maximum threads to advance

    Returns:
        List of thread dicts to advance
    """
    threads_to_advance = []

    # Prioritize reveals with longest setup time
    reveals = open_threads.get("unresolved_reveals", [])
    if reveals and chapter_function in ["payoff", "reveal", "climax"]:
        # Sort by setup time (oldest first)
        reveals_sorted = sorted(reveals, key=lambda r: min(r.get("setup_chapters", [999])))
        if reveals_sorted:
            threads_to_advance.append({
                "type": "reveal",
                "content": reveals_sorted[0]
            })

    # Add a scheme if we have room
    schemes = open_threads.get("ongoing_schemes", [])
    if schemes and len(threads_to_advance) < max_threads:
        # Prioritize schemes near payoff
        schemes_sorted = sorted(schemes, key=lambda s: s.get("setup_chapter", 999))
        if schemes_sorted:
            threads_to_advance.append({
                "type": "scheme",
                "content": schemes_sorted[0]
            })

    return threads_to_advance[:max_threads]


def select_entities_in_chapter(
    context: Dict[str, Any],
    threads_to_advance: List[Dict[str, Any]],
    chapter_function: str
) -> List[str]:
    """
    Determine which entities should appear in this chapter.

    Rules:
    - Protagonist always appears
    - Entities involved in threads being advanced should appear
    - Combat chapters need antagonists
    - Cooldown chapters can feature companions/allies

    Args:
        context: Full chapter context
        threads_to_advance: Threads selected for advancement
        chapter_function: The determined chapter function

    Returns:
        List of entity IDs
    """
    entities = []

    # Protagonist always present
    protagonist_id = context.get("protagonist_id")
    if protagonist_id:
        entities.append(protagonist_id)

    # Entities from threads
    for thread in threads_to_advance:
        thread_content = thread.get("content", {})
        if thread["type"] == "scheme":
            schemer = thread_content.get("schemer")
            target = thread_content.get("target")
            if schemer:
                entities.append(schemer.lower().replace(" ", "_"))
            if target:
                entities.append(target.lower().replace(" ", "_"))
        elif thread["type"] == "reveal":
            revealed_to = thread_content.get("revealed_to", [])
            for entity in revealed_to:
                if entity != "reader":
                    entities.append(entity.lower().replace(" ", "_"))

    # Add companion for cooldown chapters
    if chapter_function == "cooldown" and protagonist_id:
        # Get relationships
        entity_states = context.get("entity_states", {})
        if protagonist_id in entity_states:
            # Try to add a companion/ally
            for entity_id in entity_states.keys():
                if entity_id != protagonist_id and len(entities) < 3:
                    entities.append(entity_id)
                    break

    # Deduplicate
    return list(dict.fromkeys(entities))


def generate_suggested_hook(chapter_function: str, threads: List[Dict[str, Any]]) -> str:
    """
    Generate a suggested cliffhanger/hook for chapter end.

    Args:
        chapter_function: The chapter function
        threads: Open threads being advanced

    Returns:
        Suggested hook description
    """
    if chapter_function in ["escalation", "reveal"]:
        return "End on a revelation or threat that makes the reader want to immediately continue"
    elif chapter_function == "payoff":
        return "End with satisfaction but hint at the next challenge"
    elif chapter_function == "climax":
        return "End at peak tension or immediately after victory"
    elif chapter_function == "setup":
        return "End with a question or mystery that pulls reader forward"
    else:
        return "End with forward momentum toward next chapter"


def generate_author_intent_guidance(
    chapter_function: str,
    novel_meta: Dict[str, Any],
    threads: List[Dict[str, Any]]
) -> str:
    """
    Generate strategic guidance for the generator LLM.

    This tells the generator *why* to make certain choices, not just what.

    Args:
        chapter_function: The chapter function
        novel_meta: Novel metadata with cultural DNA
        threads: Threads being advanced

    Returns:
        Author intent guidance string
    """
    cultural_dna = novel_meta.get("cultural_dna", {})
    ea_weight = cultural_dna.get("east_asian", 0)
    western_weight = cultural_dna.get("western", 0)

    guidance = []

    # Base guidance by chapter function
    if chapter_function == "payoff":
        guidance.append("This chapter should deliver satisfaction — a promise made earlier is fulfilled")
    elif chapter_function == "escalation":
        guidance.append("Raise stakes without resolving them — tension should increase")
    elif chapter_function == "setup":
        guidance.append("Establish new pieces on the board — information, characters, or conflicts")

    # Cultural DNA guidance
    if ea_weight > 0.7:
        guidance.append("Emphasize power hierarchy and face dynamics in conflicts")
    elif western_weight > 0.7:
        guidance.append("Emphasize individual choice and moral ambiguity")

    # Thread-specific guidance
    for thread in threads:
        if thread["type"] == "reveal":
            guidance.append("The reveal should feel earned — setup from previous chapters pays off")
        elif thread["type"] == "scheme":
            guidance.append("Scheme payoff should demonstrate protagonist's strategic superiority")

    return "; ".join(guidance) if guidance else "Follow natural story progression"


def create_chapter_plan(
    novel_id: str,
    chapter_number: int,
    arc_override: Optional[str] = None,
    function_override: Optional[str] = None
) -> Dict[str, Any]:
    """
    Main function: Generate a complete chapter plan.

    Args:
        novel_id: Novel identifier
        chapter_number: Chapter to plan
        arc_override: Optional arc label override
        function_override: Optional chapter function override

    Returns:
        Complete chapter plan dict ready for generator.py
    """
    # Load context
    print(f"Loading context for {novel_id} chapter {chapter_number}...")
    context = get_chapter_context(novel_id, chapter_number)

    # Get recent chapters for rhythm analysis
    recent_chapters = context.get("recent_chapters", [])

    # Determine chapter function
    chapter_function = determine_chapter_function(context, recent_chapters, function_override)
    print(f"Chapter function: {chapter_function}")

    # Get arc state
    arc_state = context.get("arc_state", {})
    arc_label = arc_override or arc_state.get("current_arc", f"Arc {chapter_number // 10 + 1}")

    # Select payoff categories
    payoff_categories = select_payoff_categories(context, chapter_function)

    # Select emotion targets
    emotion_targets = select_emotion_targets(context, chapter_function, payoff_categories)

    # Get tension targets
    tension_targets = context.get("tension_targets", {})

    # Select threads to advance
    open_threads = context.get("open_threads", {})
    threads_to_advance = select_threads_to_advance(open_threads, chapter_function)
    print(f"Advancing {len(threads_to_advance)} threads")

    # Select entities for this chapter
    entities_in_chapter = select_entities_in_chapter(context, threads_to_advance, chapter_function)
    print(f"Entities: {entities_in_chapter}")

    # Get protagonist state note
    protagonist_id = context.get("protagonist_id")
    protagonist_power = context.get("protagonist_power_progression", [])
    protagonist_state_note = ""
    if protagonist_power:
        latest_power = protagonist_power[-1]
        protagonist_state_note = f"Current power: {latest_power.get('rank', 'Unknown')}"

    # Generate hook and guidance
    suggested_hook = generate_suggested_hook(chapter_function, threads_to_advance)
    author_intent_guidance = generate_author_intent_guidance(
        chapter_function,
        context.get("novel_metadata", {}),
        threads_to_advance
    )

    # Assemble plan
    plan = {
        "novel_id": novel_id,
        "chapter_number": chapter_number,
        "chapter_function": chapter_function,
        "arc_label": arc_label,
        "entities_in_chapter": entities_in_chapter,
        "open_threads_to_advance": [
            {
                "type": t["type"],
                "description": t["content"].get("content", t["content"].get("goal", "Unknown"))
            }
            for t in threads_to_advance
        ],
        "payoff_categories": payoff_categories,
        "tension_curve_target": {
            "start": tension_targets.get("suggested_start", 75),
            "peak": tension_targets.get("suggested_peak", 85),
            "end": tension_targets.get("suggested_end", 78)
        },
        "emotion_targets": emotion_targets,
        "protagonist_state_note": protagonist_state_note,
        "suggested_hook": suggested_hook,
        "author_intent_guidance": author_intent_guidance,
        "recent_chapter_summaries": [
            {
                "chapter": ch.get("chapter_number"),
                "title": ch.get("chapter_title", ""),
                "summary": ch.get("summary", "")[:200]  # First 200 chars
            }
            for ch in recent_chapters
        ],
        "tension_pattern": tension_targets.get("recent_pattern", "unknown"),
        "arc_state": {
            "chapters_into_arc": arc_state.get("chapters_into_arc", 1),
            "arc_chapter_count": arc_state.get("arc_chapter_count", 10)
        }
    }

    return plan


def save_plan(plan: Dict[str, Any], output_path: Optional[Path] = None):
    """Save chapter plan to JSON file."""
    if output_path is None:
        novel_id = plan["novel_id"]
        chapter_num = plan["chapter_number"]
        output_path = NOVELS_DIR / novel_id / f"plan_ch{chapter_num:03d}.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)

    print(f"\nPlan saved to: {output_path}")
    return output_path


def print_plan_summary(plan: Dict[str, Any]):
    """Print human-readable plan summary."""
    print(f"\n{'='*60}")
    print(f"CHAPTER PLAN: {plan['novel_id']} Ch.{plan['chapter_number']}")
    print(f"{'='*60}")
    print(f"Arc: {plan['arc_label']}")
    print(f"Function: {plan['chapter_function']}")
    print(f"Chapters into arc: {plan['arc_state']['chapters_into_arc']}/{plan['arc_state']['arc_chapter_count']}")
    print(f"\nEntities: {', '.join(plan['entities_in_chapter'])}")
    print(f"\nThreads to advance: {len(plan['open_threads_to_advance'])}")
    for thread in plan['open_threads_to_advance']:
        print(f"  - [{thread['type']}] {thread['description'][:60]}...")
    print(f"\nEmotion targets: {plan['emotion_targets']}")
    print(f"Payoff categories: {plan['payoff_categories']}")
    print(f"\nTension curve: {plan['tension_curve_target']['start']} -> {plan['tension_curve_target']['peak']} -> {plan['tension_curve_target']['end']}")
    print(f"Tension pattern: {plan['tension_pattern']}")
    print(f"\nHook: {plan['suggested_hook']}")
    print(f"\nGuidance: {plan['author_intent_guidance']}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python planner.py <novel_id> <chapter_number> [arc_override] [function_override]")
        print("Example: python planner.py my_novel 111")
        print("Example: python planner.py my_novel 111 'Arc 7: Black Sect' escalation")
        sys.exit(1)

    novel_id = sys.argv[1]
    chapter_number = int(sys.argv[2])
    arc_override = sys.argv[3] if len(sys.argv) > 3 else None
    function_override = sys.argv[4] if len(sys.argv) > 4 else None

    try:
        plan = create_chapter_plan(novel_id, chapter_number, arc_override, function_override)
        print_plan_summary(plan)
        save_plan(plan)
        print(f"\nChapter plan ready for generator.py")
    except Exception as e:
        print(f"Error creating plan: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
