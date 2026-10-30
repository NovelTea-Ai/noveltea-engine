"""
extract_enhanced.py - Schema v2.1 Enhanced Extraction for Novel Generation

Extracts comprehensive stylistic DNA from raw chapter text:
1. Programmatic analysis: sentence/paragraph stats, content ratios
2. LLM-assisted extraction: prose samples (10-20), character voices, scene structure
3. Outputs generation-ready JSON delta with v2.1 enhancements

Usage:
    python extract_enhanced.py --novel my_novel --chapter 1
    python extract_enhanced.py --novel my_novel --start 1 --end 10
"""

import json
import re
import sys
import argparse
from pathlib import Path
from collections import Counter
import anthropic
import os
from dotenv import load_dotenv

# Load API key from .env file
load_dotenv()

# Initialize Claude client
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

def load_chapter_text(novel_id: str, chapter_num: int) -> str:
    """Load raw chapter text from file."""
    raw_path = Path(f"raw/{novel_id}/ch{chapter_num}.txt")
    if not raw_path.exists():
        raise FileNotFoundError(f"Raw chapter not found: {raw_path}")

    with open(raw_path, 'r', encoding='utf-8') as f:
        return f.read()

def analyze_style_dna(text: str) -> dict:
    """
    Programmatic analysis of prose style metrics.
    Returns style_dna dict with quantitative measurements.
    """
    # Remove chapter title line
    lines = text.strip().split('\n')
    if lines and re.match(r'^Chapter \d+', lines[0]):
        text = '\n'.join(lines[1:])

    # Sentence extraction (simple heuristic)
    sentences = re.split(r'[.!?]+\s+', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]

    # Paragraph extraction
    paragraphs = [p.strip() for p in text.split('\n') if len(p.strip()) > 20]

    # Sentence length distribution
    sentence_lengths = [len(s.split()) for s in sentences]
    total_sentences = len(sentence_lengths)
    short = sum(1 for l in sentence_lengths if 1 <= l <= 10)
    medium = sum(1 for l in sentence_lengths if 11 <= l <= 25)
    long = sum(1 for l in sentence_lengths if l >= 26)

    sentence_dist = {
        "short_1_10_words": round(short / total_sentences, 2) if total_sentences else 0,
        "medium_11_25_words": round(medium / total_sentences, 2) if total_sentences else 0,
        "long_26_plus_words": round(long / total_sentences, 2) if total_sentences else 0
    }

    # Paragraph length distribution (sentences per paragraph)
    para_sentence_counts = []
    for para in paragraphs:
        para_sentences = re.split(r'[.!?]+\s+', para)
        para_sentence_counts.append(len([s for s in para_sentences if len(s.strip()) > 10]))

    single = sum(1 for c in para_sentence_counts if c == 1)
    two_to_four = sum(1 for c in para_sentence_counts if 2 <= c <= 4)
    five_plus = sum(1 for c in para_sentence_counts if c >= 5)
    total_paras = len(para_sentence_counts)

    para_dist = {
        "single_sentence": round(single / total_paras, 2) if total_paras else 0,
        "two_to_four_sentences": round(two_to_four / total_paras, 2) if total_paras else 0,
        "five_plus_sentences": round(five_plus / total_paras, 2) if total_paras else 0
    }

    # Dialogue detection (rough heuristic: quoted text or "X said" patterns)
    dialogue_chars = len(re.findall(r'"[^"]{10,}?"', text))
    total_chars = len(text)

    # Approximate content ratios (very rough)
    dialogue_pct = round(dialogue_chars / total_chars, 2) if total_chars else 0

    # Count exclamations, questions, profanity
    exclamations = text.count('!')
    questions = text.count('?')
    words = text.split()
    total_words = len(words)

    exclamation_rate = round(exclamations / total_sentences, 2) if total_sentences else 0
    question_rate = round(questions / total_sentences, 2) if total_sentences else 0

    # Profanity detection
    profanity_words = ['fuck', 'damn', 'shit', 'bastard', 'bitch', 'hell']
    profanity_count = sum(text.lower().count(p) for p in profanity_words)
    profanity_freq = round(profanity_count / total_words, 4) if total_words else 0

    # Find common profanity
    common_prof = []
    for p in profanity_words:
        pattern = re.compile(r'\b' + p + r'\w*\b', re.IGNORECASE)
        matches = pattern.findall(text)
        if matches:
            # Get most common capitalization
            counter = Counter(matches)
            most_common = counter.most_common(1)[0][0]
            common_prof.append(most_common)

    # Find common transitions (simple pattern matching)
    transition_patterns = [
        r'right at this moment', r'at the same time', r'after that',
        r'suddenly', r'immediately', r'in an instant', r'at this point',
        r'just as', r'meanwhile', r'however', r'therefore'
    ]
    found_transitions = []
    for pattern in transition_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            match = re.search(pattern, text, re.IGNORECASE)
            found_transitions.append(match.group())

    found_transitions = list(set(found_transitions))[:4]  # Top 4 unique

    return {
        "sentence_length_distribution": sentence_dist,
        "paragraph_length_distribution": para_dist,
        "content_ratios": {
            "dialogue_percentage": dialogue_pct,
            "action_percentage": 0.0,  # LLM will refine
            "description_percentage": 0.0,  # LLM will refine
            "internal_monologue_percentage": 0.0  # LLM will refine
        },
        "pacing_markers": {
            "average_words_between_dialogue": 0,  # LLM will refine
            "average_words_between_paragraphs": round(total_words / total_paras, 1) if total_paras else 0,
            "action_sequence_avg_length_words": 0,  # LLM will refine
            "exposition_block_avg_length_words": 0  # LLM will refine
        },
        "stylistic_devices": {
            "repetition_for_emphasis": 0.0,  # LLM will identify
            "rhetorical_questions": question_rate,
            "exclamations": exclamation_rate,
            "em_dashes_parentheticals": round(text.count('—') / total_sentences, 2) if total_sentences else 0,
            "sensory_details_per_scene": 0.0,  # LLM will count
            "metaphor_simile_frequency": 0.0  # LLM will identify
        },
        "vocabulary_markers": {
            "favorite_intensifiers": [],  # LLM will extract
            "favorite_transitions": found_transitions,
            "favorite_descriptors_power": [],  # LLM will extract
            "favorite_descriptors_emotion": [],  # LLM will extract
            "profanity_frequency": profanity_freq,
            "common_profanity": common_prof
        },
        "character_catchphrases": {}  # LLM will extract
    }

def extract_with_llm(text: str, chapter_num: int, style_dna_base: dict) -> dict:
    """
    Use Claude to extract generation-critical elements with PROMPT CACHING for cost savings.
    - 10-20 prose samples with categorization
    - Character voice samples
    - Scene structure patterns
    - Narrative voice analysis
    - Refinements to style_dna

    Uses automatic caching to reduce API costs by ~85-90% on batch processing.
    """

    # System prompt (this will be cached across all chapters - HUGE cost savings!)
    system_prompt = """You are analyzing chapters of a xianxia web novel to extract stylistic DNA for novel generation.

Extract the following in JSON format:

1. **prose_samples** (10-20 samples):
   - Extract diverse samples covering: combat_technique, combat_reaction, dialogue_threat, dialogue_banter, dialogue_exposition, internal_monologue_planning, internal_monologue_reaction, scene_transition, power_reveal, comedy_setup, comedy_payoff, description_environment, description_character, emotional_beat, cultivation_description
   - For each sample:
     * type: one of the categories above
     * excerpt: verbatim 2-8 sentences from the text
     * source_character_pov: which character's perspective (or "omniscient")
     * narrative_distance: "close_third" | "distant_third" | "omniscient"
     * style_notes: what makes this exemplary (rhythm, word choice, etc.)
     * tags: ["absurdist", "repetition", "stream_of_consciousness", etc.]

2. **character_voice_samples**:
   - For each character who speaks in this chapter:
     * character_name: canonical name
     * dialogue_samples: 3-5 verbatim lines with context
     * speech_dna:
       - formality_level: "street" | "casual" | "neutral" | "formal" | "archaic"
       - verbosity: "terse" | "normal" | "verbose"
       - emotional_expression: "stoic" | "controlled" | "expressive" | "volatile"
       - signature_phrases: ["phrase1", "phrase2"]
       - sentence_structure_preference: "simple" | "compound" | "complex" | "fragmented"
       - uses_profanity: true/false
       - uses_humor: "never" | "rarely" | "often" | "constantly"
       - humor_style: "deadpan" | "sarcastic" | "absurd" | "boastful" | "none"

3. **scene_structure_patterns**:
   - scenes: identify 3-6 scenes with:
     * scene_number, estimated_word_count
     * scene_type: "combat" | "dialogue" | "exposition" | etc.
     * pov_character, narrative_distance
     * tension_level: 0.0-1.0
     * pacing: "slow_burn" | "steady" | "rapid" | "explosive"
     * structure_notes: how scene is built
   - chapter_rhythm:
     * opening_hook: "action" | "dialogue" | "mystery" | "continuation"
     * middle_build: "steady_escalation" | "plateau" | "multiple_peaks"
     * ending_type: "cliffhanger" | "resolution" | "transition" | "comedy_button"
     * scene_count, average_scene_length_words

4. **narrative_voice_analysis**:
   - dominant_pov: "Character Name" | "Omniscient" | "Shifting"
   - pov_shifts: list any POV changes
   - narrative_intrusions: any narrator commentary (with excerpt, type, tone)
   - thought_presentation:
     * internal_monologue_style: how thoughts are shown
     * frequency: "rare" | "occasional" | "frequent"
     * depth: "surface_reactions" | "strategic_planning" | "philosophical_reflection"

5. **style_dna_refinements**:
   - content_ratios: estimate dialogue/action/description/internal_monologue percentages (must sum to 1.0)
   - favorite_intensifiers: ["extremely", "incredibly", etc.]
   - favorite_descriptors_power: ["formidable", "terrifying", etc.]
   - favorite_descriptors_emotion: ["shocked", "furious", etc.]
   - character_catchphrases: {{"Character": ["phrase1", "phrase2"]}}

Return ONLY valid JSON with these 5 keys. Be thorough and extract verbatim excerpts."""

    # User message with chapter-specific content
    user_message = f"""Chapter {chapter_num}:

{text[:12000]}

{'[... text truncated for context ...]' if len(text) > 12000 else ''}"""

    # Use automatic caching - system prompt will be cached!
    response = client.messages.create(
        model="claude-sonnet-4-6",  # Claude Sonnet 4.6
        max_tokens=16000,
        temperature=0.3,
        cache_control={"type": "ephemeral"},  # Enable automatic caching
        system=system_prompt,  # This gets cached across all chapters
        messages=[{"role": "user", "content": user_message}]
    )

    response_text = response.content[0].text

    # Extract JSON from response (handle markdown code blocks)
    json_match = re.search(r'```json\s*\n(.*?)\n```', response_text, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        # Try to find raw JSON
        json_str = response_text.strip()

    try:
        extracted = json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to parse LLM response as JSON: {e}")
        print(f"Response was: {response_text[:500]}")
        # Return minimal structure
        extracted = {
            "prose_samples": [],
            "character_voice_samples": [],
            "scene_structure_patterns": {"scenes": [], "chapter_rhythm": {}},
            "narrative_voice_analysis": {},
            "style_dna_refinements": {}
        }

    return extracted

def merge_style_dna(base: dict, refinements: dict) -> dict:
    """Merge LLM refinements into programmatic base."""
    result = base.copy()

    if "content_ratios" in refinements:
        result["content_ratios"].update(refinements["content_ratios"])

    if "favorite_intensifiers" in refinements:
        result["vocabulary_markers"]["favorite_intensifiers"] = refinements["favorite_intensifiers"]

    if "favorite_descriptors_power" in refinements:
        result["vocabulary_markers"]["favorite_descriptors_power"] = refinements["favorite_descriptors_power"]

    if "favorite_descriptors_emotion" in refinements:
        result["vocabulary_markers"]["favorite_descriptors_emotion"] = refinements["favorite_descriptors_emotion"]

    if "character_catchphrases" in refinements:
        result["character_catchphrases"] = refinements["character_catchphrases"]

    return result

def extract_chapter_enhanced(novel_id: str, chapter_num: int) -> dict:
    """Main extraction function - combines programmatic + LLM analysis."""
    print(f"Extracting chapter {chapter_num} with enhanced schema v2.1...")

    # Load raw text
    text = load_chapter_text(novel_id, chapter_num)

    # Step 1: Programmatic style DNA analysis
    print("  - Analyzing style DNA (programmatic)...")
    style_dna_base = analyze_style_dna(text)

    # Step 2: LLM extraction
    print("  - Extracting prose samples, voices, scenes (LLM)...")
    llm_extracted = extract_with_llm(text, chapter_num, style_dna_base)

    # Step 3: Merge style DNA
    style_dna = merge_style_dna(style_dna_base, llm_extracted.get("style_dna_refinements", {}))

    # Step 4: Build v2.1 delta
    delta = {
        "schema_version": "2.1",
        "chapter_number": chapter_num,
        "chapter_title": "",  # Extract from first line if needed

        # v2.1 ENHANCED FIELDS
        "prose_samples": llm_extracted.get("prose_samples", []),
        "style_dna": style_dna,
        "character_voice_samples": llm_extracted.get("character_voice_samples", []),
        "scene_structure_patterns": llm_extracted.get("scene_structure_patterns", {}),
        "narrative_voice_analysis": llm_extracted.get("narrative_voice_analysis", {}),

        # v2.0 FIELDS (empty for now - can be filled by existing extraction logic)
        "title_function": "payoff",
        "chapter_function": "escalation",
        "summary": "",
        "arc_label_suggestion": "",
        "arc_boundary_signal": False,
        "new_characters": [],
        "new_locations": [],
        "new_glossary_terms": [],
        "humor_instances": [],
        "reveals": [],
        "schemes": [],
        "facts": [],
        "timeline_events": [],
        "emotion_targets": {},
        "tension_curve": {"start": 50, "peak": 75, "end": 60}
    }

    # Extract chapter title from first line
    first_line = text.split('\n')[0]
    if re.match(r'^Chapter \d+', first_line):
        title_match = re.search(r'Chapter \d+\s*[–-]\s*(.+)', first_line)
        if title_match:
            delta["chapter_title"] = title_match.group(1).strip()

    return delta

def save_delta(delta: dict, novel_id: str, output_dir: str = "novels"):
    """Save enhanced delta to novels/<novel>/deltas_v2_1/chXXX.json"""
    chapter_num = delta["chapter_number"]
    output_path = Path(output_dir) / novel_id / "deltas_v2_1" / f"ch{chapter_num}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(delta, f, indent=2, ensure_ascii=False)

    print(f"[OK] Saved enhanced delta: {output_path}")

def main():
    parser = argparse.ArgumentParser(description="Extract enhanced schema v2.1 deltas for generation")
    parser.add_argument("--novel", required=True, help="Novel ID (e.g., my_novel)")
    parser.add_argument("--chapter", type=int, help="Single chapter number to extract")
    parser.add_argument("--start", type=int, help="Start chapter for batch extraction")
    parser.add_argument("--end", type=int, help="End chapter for batch extraction")

    args = parser.parse_args()

    if args.chapter:
        # Single chapter
        delta = extract_chapter_enhanced(args.novel, args.chapter)
        save_delta(delta, args.novel)
    elif args.start and args.end:
        # Batch extraction
        import time
        for ch in range(args.start, args.end + 1):
            try:
                delta = extract_chapter_enhanced(args.novel, ch)
                save_delta(delta, args.novel)
                # Small delay to avoid rate limits when running multiple jobs
                time.sleep(0.5)
            except Exception as e:
                print(f"[ERROR] Ch{ch}: {str(e)[:100]}")
                # If rate limit, wait longer
                if "rate_limit" in str(e).lower():
                    print("[RATE LIMIT] Waiting 60 seconds...")
                    time.sleep(60)
                continue
    else:
        print("Error: Must specify either --chapter or both --start and --end")
        sys.exit(1)

if __name__ == "__main__":
    main()
