#!/usr/bin/env python3
"""
Chapter Generator — NovelTea Engine Generation Pipeline
=================================================

Purpose:
  Takes a chapter_plan.json from planner.py and generates the actual
  chapter text by calling the Anthropic API with the plan + context bundle.

  This is the "writer's hand" — the planner is the brain, this executes.

Input:
  - chapter_plan.json (from planner.py)
  - OR: novel_id + chapter_number (generates plan automatically)

Output:
  - Generated chapter text
  - Optional: auto-extract delta and merge into wiki brain

Usage:
  python generator.py <plan_file>
  python generator.py --novel <novel_id> --chapter <N>
  python generator.py --novel my_novel --chapter 111
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# Load API key from .env file if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, will use environment variable directly

import anthropic

from planner import create_chapter_plan
from query import get_chapter_context, get_prose_samples, load_json

NOVELS_DIR = Path(__file__).parent / "novels"
OUTPUT_DIR = Path(__file__).parent / "generated"


def load_character_dna(novel_id: str, protagonist_id: str) -> Optional[Dict[str, Any]]:
    """
    Load protagonist DNA file for the novel.

    Args:
        novel_id: Novel identifier
        protagonist_id: Protagonist entity ID

    Returns:
        Character DNA dict or None if not found
    """
    dna_dir = Path(__file__).parent / "character_dna" / "protagonist"

    # Try to find DNA file matching protagonist_id
    for dna_file in dna_dir.glob("*.json"):
        dna_data = load_json(dna_file, {})
        if dna_data.get("character_id") == protagonist_id or dna_data.get("novel_id") == novel_id:
            return dna_data

    return None


def build_generation_prompt(
    plan: Dict[str, Any],
    context: Dict[str, Any],
    protagonist_dna: Optional[Dict[str, Any]] = None
) -> str:
    """
    Build the complete generation prompt for the API.

    This is the most critical function — the prompt quality determines
    the generation quality.

    Args:
        plan: Chapter plan from planner.py
        context: Full context from query layer
        protagonist_dna: Protagonist character DNA

    Returns:
        Complete prompt string
    """
    novel_meta = context.get("novel_metadata", {})
    novel_title = novel_meta.get("title", plan["novel_id"])
    cultural_dna = novel_meta.get("cultural_dna", {})

    # Recent chapter summaries
    recent_summaries = "\n".join([
        f"Chapter {ch['chapter']}: {ch['title']} — {ch['summary']}"
        for ch in plan.get("recent_chapter_summaries", [])
    ])

    # Prose samples
    prose_samples = get_prose_samples(plan["novel_id"], recent_chapters=20)
    prose_examples = "\n\n".join([
        f"[{sample.get('type', 'unknown')}] {sample.get('excerpt', '')} — {sample.get('notes', '')}"
        for sample in prose_samples[:5]  # Top 5 most recent
    ])

    # Protagonist DNA summary
    protag_summary = ""
    if protagonist_dna:
        protag_summary = f"""
**Protagonist: {protagonist_dna.get('character_name', 'Unknown')}**
Archetype: {protagonist_dna.get('archetype', 'Unknown')}

Core Beliefs (IDENTITY LOCK - DO NOT VIOLATE):
{chr(10).join(f"- {belief}" for belief in protagonist_dna.get('identity_lock', {}).get('core_beliefs', []))}

Core Personality Traits:
{chr(10).join(f"- {trait}" for trait in protagonist_dna.get('identity_lock', {}).get('core_personality_traits', []))}

Generation Rules (CRITICAL):
{chr(10).join(f"- {rule}" for rule in protagonist_dna.get('identity_lock', {}).get('generation_rules', []))}

Speech DNA:
- Formality: {protagonist_dna.get('speech_dna', {}).get('formality', 50)}/100
- Signature expressions: {', '.join(protagonist_dna.get('speech_dna', {}).get('signature_expressions', [])[:3])}

Banter frequency: {protagonist_dna.get('banter_dna', {}).get('frequency', 0.5)}
"""

    # Open threads context
    threads_context = ""
    if plan.get("open_threads_to_advance"):
        threads_context = "**Open Threads to Advance:**\n" + "\n".join([
            f"- [{thread['type']}] {thread['description']}"
            for thread in plan["open_threads_to_advance"]
        ])

    # Build complete prompt
    prompt = f"""You are writing chapter {plan['chapter_number']} of the web novel "{novel_title}".

**Arc Context:**
Arc: {plan['arc_label']}
Position: Chapter {plan['arc_state']['chapters_into_arc']} of ~{plan['arc_state']['arc_chapter_count']} in this arc
Chapter Function: {plan['chapter_function']}

**Recent Chapters (for continuity):**
{recent_summaries}

**This Chapter's Strategic Goals:**

Chapter Function: {plan['chapter_function']}
{threads_context}

Emotion Targets: {plan['emotion_targets']}
Payoff Categories: {plan['payoff_categories']}

Tension Curve Target:
- Start: {plan['tension_curve_target']['start']}/100
- Peak: {plan['tension_curve_target']['peak']}/100
- End: {plan['tension_curve_target']['end']}/100

Suggested Hook: {plan['suggested_hook']}

**Author Intent Guidance:**
{plan['author_intent_guidance']}

**Cultural DNA (affects pacing, morality, humor style):**
{json.dumps(cultural_dna, indent=2)}

{protag_summary}

**Prose Style Examples from this Novel:**
{prose_examples}

**Entities in This Chapter:**
{', '.join(plan['entities_in_chapter'])}

**CRITICAL INSTRUCTIONS:**

1. **Character Consistency**: Follow the protagonist's identity lock rules exactly. DO NOT violate core beliefs or generation rules.

2. **Tension Curve**: Structure the chapter to hit the tension targets. Start at {plan['tension_curve_target']['start']}, peak at {plan['tension_curve_target']['peak']}, end at {plan['tension_curve_target']['end']}.

3. **Prose Style**: Match the prose samples. Use similar sentence structure, vocabulary, and voice.

4. **Chapter Function**: This is a {plan['chapter_function']} chapter — {plan['author_intent_guidance']}

5. **Hook**: End with: {plan['suggested_hook']}

6. **Length**: Write approximately 2000-3000 words.

7. **Format**: Write ONLY the chapter text. Do not include meta-commentary, chapter numbers, or titles. Start directly with the narrative.

Generate the chapter now:"""

    return prompt


def generate_chapter(
    plan: Dict[str, Any],
    api_key: Optional[str] = None,
    model: str = "claude-sonnet-4-6"
) -> str:
    """
    Call Anthropic API to generate chapter based on plan.

    Args:
        plan: Chapter plan dict
        api_key: Anthropic API key (or from env)
        model: Model to use

    Returns:
        Generated chapter text
    """
    if api_key is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    # Load context
    print(f"Loading context for {plan['novel_id']} chapter {plan['chapter_number']}...")
    context = get_chapter_context(plan["novel_id"], plan["chapter_number"])

    # Load protagonist DNA
    protagonist_id = context.get("protagonist_id")
    protagonist_dna = None
    if protagonist_id:
        print(f"Loading protagonist DNA for {protagonist_id}...")
        protagonist_dna = load_character_dna(plan["novel_id"], protagonist_id)
        if protagonist_dna:
            print(f"Loaded DNA for {protagonist_dna.get('character_name', protagonist_id)}")
        else:
            print(f"No DNA file found for {protagonist_id}, proceeding without DNA")

    # Build prompt
    print("Building generation prompt...")
    prompt = build_generation_prompt(plan, context, protagonist_dna)

    generated_text = None

    if api_key:
        try:
            print(f"Calling Anthropic API ({model})...")
            client = anthropic.Anthropic(api_key=api_key)
            message = client.messages.create(
                model=model,
                max_tokens=8000,
                messages=[{"role": "user", "content": prompt}]
            )
            generated_text = message.content[0].text
            print(f"API Usage: {message.usage.input_tokens} in / {message.usage.output_tokens} out")
        except anthropic.BadRequestError as e:
            if "credit balance" in str(e).lower() or "billing" in str(e).lower():
                print(f"API credits exhausted — falling back to Claude Code CLI...")
            else:
                raise

    if generated_text is None:
        # No key or credits exhausted — use Claude Code CLI subscription
        import subprocess, shutil
        cli = shutil.which("claude")
        if not cli:
            raise ValueError(
                "No ANTHROPIC_API_KEY set and claude CLI not found in PATH. "
                "Add an API key in NovelTea Engine Settings or install Claude Code."
            )
        print(f"Using Claude Code CLI subscription...")
        system = (
            "You are a professional web novel author. Write the chapter exactly as requested. "
            "Output only the chapter prose — no titles, no commentary, no meta-text."
        )
        result = subprocess.run(
            [cli, "-p", "--output-format", "text", "--system-prompt", system],
            input=prompt,
            capture_output=True, text=True, timeout=300, encoding="utf-8",
        )
        if result.returncode != 0:
            raise RuntimeError(f"claude CLI error: {result.stderr.strip()[:400]}")
        generated_text = result.stdout.strip()
        print(f"Generated via Claude Code CLI ({len(generated_text)} chars)")

    return generated_text


def save_generated_chapter(
    text: str,
    plan: Dict[str, Any],
    output_dir: Optional[Path] = None
) -> Path:
    """
    Save generated chapter to file.

    Args:
        text: Generated chapter text
        plan: Chapter plan
        output_dir: Output directory (default: generated/)

    Returns:
        Path to saved file
    """
    if output_dir is None:
        output_dir = OUTPUT_DIR / plan["novel_id"]

    output_dir.mkdir(parents=True, exist_ok=True)

    chapter_num = plan["chapter_number"]
    filename = f"ch{chapter_num:03d}_generated.txt"
    output_path = output_dir / filename

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(text)

    print(f"\n✓ Chapter saved to: {output_path}")
    return output_path


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate novel chapters")
    parser.add_argument("--plan", type=str, help="Path to chapter plan JSON file")
    parser.add_argument("--novel", type=str, help="Novel ID (if generating plan automatically)")
    parser.add_argument("--chapter", type=int, help="Chapter number (if generating plan automatically)")
    parser.add_argument("--model", type=str, default="claude-sonnet-4-6", help="Model to use")
    parser.add_argument("--output", type=str, help="Output directory")

    args = parser.parse_args()

    # Load or generate plan
    if args.plan:
        print(f"Loading plan from {args.plan}...")
        with open(args.plan, 'r', encoding='utf-8') as f:
            plan = json.load(f)
    elif args.novel and args.chapter:
        print(f"Generating plan for {args.novel} chapter {args.chapter}...")
        plan = create_chapter_plan(args.novel, args.chapter)
        # Save plan
        plan_path = NOVELS_DIR / args.novel / f"plan_ch{args.chapter:03d}.json"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        with open(plan_path, 'w', encoding='utf-8') as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)
        print(f"✓ Plan saved to {plan_path}")
    else:
        parser.print_help()
        sys.exit(1)

    # Generate chapter
    try:
        generated_text = generate_chapter(plan, model=args.model)

        # Save output
        output_dir = Path(args.output) if args.output else None
        output_path = save_generated_chapter(generated_text, plan, output_dir)

        print(f"\n{'='*60}")
        print(f"GENERATION COMPLETE")
        print(f"{'='*60}")
        print(f"Novel: {plan['novel_id']}")
        print(f"Chapter: {plan['chapter_number']}")
        print(f"Function: {plan['chapter_function']}")
        print(f"Output: {output_path}")
        print(f"Word count: ~{len(generated_text.split())}")
        print(f"{'='*60}\n")

        print("Next steps:")
        print(f"1. Review generated chapter: {output_path}")
        print(f"2. Extract delta: python extract.py --novel {plan['novel_id']} --chapter {plan['chapter_number']}")
        print(f"3. Merge delta: python merge.py --novel {plan['novel_id']} <delta_file>")

    except Exception as e:
        print(f"\n❌ Error during generation: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
