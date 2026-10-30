"""
extract_batch.py - Batch extraction using Message Batches API

Uses Anthropic's Message Batches API for:
- 50% cost reduction (batch pricing)
- No rate limit issues (batches process asynchronously)
- Stacks with prompt caching for even greater savings
- Processes all chapters in parallel

Cost comparison:
- Sequential API: ~$0.89 for 444 chapters
- Batch API with caching: ~$0.22-0.45 for 444 chapters

Usage:
    python extract_batch.py --novel my_novel --start 22 --end 225
"""

import json
import argparse
from pathlib import Path
import anthropic
import os
from dotenv import load_dotenv
import time

load_dotenv()
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# Shared system prompt (will be cached across all batch requests!)
SYSTEM_PROMPT = """You are analyzing chapters of a xianxia web novel to extract complete v2.1 schema data for novel generation.

Extract the following in JSON format:

1. **summary**:
   - Concise 2-3 sentence summary of what happens in this chapter
   - Include key events, character actions, and outcomes

2. **facts** (5-10 items):
   - Important information revealed in this chapter
   - Format: {"fact": "description", "category": "character|item|power|location|plot", "chapter": N}
   - Extract character names, power levels, items introduced, key decisions

3. **timeline_events** (3-6 items):
   - Key sequential events in this chapter
   - Format: {"event_id": "TEN-XX", "sequence": N, "description": "brief", "chapter": N}

4. **emotion_targets**:
   - Primary emotions this chapter should evoke: {"emotion_name": intensity_0_to_100}
   - Examples: "tension", "triumph", "shock", "comedy", "progression"

5. **tension_curve**:
   - How tension evolves: {"start": 0-100, "peak": 0-100, "end": 0-100}

6. **prose_samples** (10-20 samples):
   - Extract diverse samples covering: combat_technique, combat_reaction, dialogue_threat, dialogue_banter, dialogue_exposition, internal_monologue_planning, internal_monologue_reaction, scene_transition, power_reveal, comedy_setup, comedy_payoff, description_environment, description_character, emotional_beat, cultivation_description
   - For each sample:
     * type: one of the categories above
     * excerpt: verbatim 2-8 sentences from the text
     * source_character_pov: which character's perspective (or "omniscient")
     * narrative_distance: "close_third" | "distant_third" | "omniscient"
     * style_notes: what makes this exemplary (rhythm, word choice, etc.)
     * tags: ["absurdist", "repetition", "stream_of_consciousness", etc.]

7. **character_voice_samples**:
   - For each character who speaks in this chapter:
     * character_name: canonical name
     * dialogue_samples: 3-5 verbatim lines with context
     * speech_dna:
       - formality_level: "street" | "casual" | "neutral" | "formal" | "archaic"
       - verbosity: "terse" | "normal" | "verbose"
       - emotional_expression: "stoic" | "controlled" | "expressive" | "volatile"
       - signature_phrases: ["phrase1", "phrase2"]
       - humor_style: "sarcastic" | "deadpan" | "slapstick" | "none"

8. **scene_structure_patterns**:
   - For each distinct scene in the chapter:
     * scene_type: "combat" | "dialogue" | "internal_reflection" | "transition" | "revelation" | "comedy"
     * tension_level: 1-10
     * pacing: "fast" | "medium" | "slow"
     * structure_notes: brief notes on how the scene is constructed

9. **narrative_voice_tracking**:
   - pov_character: main POV character for this chapter (or "omniscient")
   - narrative_distance: "close_third" | "distant_third" | "omniscient"
   - narrative_intrusions: any narrator commentary (with excerpt, type, tone)
   - thought_presentation:
     * internal_monologue_style: how thoughts are shown
     * frequency: "rare" | "occasional" | "frequent"
     * depth: "surface_reactions" | "strategic_planning" | "philosophical_reflection"

10. **style_dna**:
   - sentence_length_distribution: {"short": 0.0-1.0, "medium": 0.0-1.0, "long": 0.0-1.0} (must sum to 1.0)
   - content_ratios: {"dialogue": 0.0-1.0, "action": 0.0-1.0, "description": 0.0-1.0, "internal_thought": 0.0-1.0} (must sum to 1.0)
   - favorite_intensifiers: ["extremely", "incredibly", etc.]
   - favorite_descriptors_power: ["formidable", "terrifying", etc.]
   - favorite_descriptors_emotion: ["shocked", "furious", etc.]
   - character_catchphrases: {"Character": ["phrase1", "phrase2"]}

Return ONLY valid JSON with these 10 keys. Be thorough and extract verbatim excerpts."""


def load_chapter_text(novel_id: str, chapter_num: int) -> str:
    """Load raw chapter text."""
    raw_path = Path(f"raw/{novel_id}/ch{chapter_num}.txt")
    if not raw_path.exists():
        raise FileNotFoundError(f"Raw chapter not found: {raw_path}")

    with open(raw_path, 'r', encoding='utf-8') as f:
        return f.read()


def create_batch_requests(novel_id: str, start: int, end: int) -> list:
    """Create batch request list for chapters."""
    requests = []

    for ch_num in range(start, end + 1):
        try:
            text = load_chapter_text(novel_id, ch_num)

            # Truncate if too long
            text_content = text[:12000]
            if len(text) > 12000:
                text_content += "\n[... text truncated for context ...]"

            # Create batch request with caching
            requests.append({
                "custom_id": f"{novel_id}_ch{ch_num}",
                "params": {
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 16000,
                    "temperature": 0.3,
                    "system": [
                        {
                            "type": "text",
                            "text": SYSTEM_PROMPT,
                            "cache_control": {"type": "ephemeral"}  # Cache system prompt!
                        }
                    ],
                    "messages": [
                        {
                            "role": "user",
                            "content": f"Chapter {ch_num}:\n\n{text_content}"
                        }
                    ]
                }
            })
            print(f"[Prepared] {novel_id} ch{ch_num}")

        except FileNotFoundError:
            print(f"[Skip] {novel_id} ch{ch_num} - file not found")
            continue

    return requests


def create_message_batch(novel_id: str, start: int, end: int):
    """Create and submit a message batch."""
    print(f"\n=== Creating batch for {novel_id} ch{start}-{end} ===")

    # Create requests
    requests = create_batch_requests(novel_id, start, end)

    if not requests:
        print("[ERROR] No valid chapters found")
        return None

    print(f"\n[Batch] Submitting {len(requests)} chapters...")

    # Submit batch
    message_batch = client.messages.batches.create(requests=requests)

    print(f"[OK] Batch created: {message_batch.id}")
    print(f"[Status] {message_batch.processing_status}")
    print(f"[Expires] {message_batch.expires_at}")

    # Save batch ID for later retrieval
    batch_log_path = Path(f"batch_logs/{novel_id}_batch.json")
    batch_log_path.parent.mkdir(parents=True, exist_ok=True)

    with open(batch_log_path, 'w') as f:
        json.dump({
            "batch_id": message_batch.id,
            "novel_id": novel_id,
            "start": start,
            "end": end,
            "created_at": str(message_batch.created_at),
            "expires_at": str(message_batch.expires_at),
            "status": message_batch.processing_status
        }, f, indent=2)

    print(f"[Saved] Batch info to {batch_log_path}")
    return message_batch


def poll_batch(batch_id: str, novel_id: str):
    """Poll batch until completion."""
    print(f"\n=== Polling batch {batch_id} ===")

    while True:
        batch = client.messages.batches.retrieve(batch_id)

        status = batch.processing_status
        counts = batch.request_counts

        print(f"[Status] {status}")
        print(f"  Processing: {counts.processing}")
        print(f"  Succeeded: {counts.succeeded}")
        print(f"  Errored: {counts.errored}")
        print(f"  Canceled: {counts.canceled}")
        print(f"  Expired: {counts.expired}")

        if status == "ended":
            print(f"\n[COMPLETE] Batch finished!")
            return batch

        elif status == "canceling":
            print(f"[WARNING] Batch is being canceled")
            return batch

        print(f"[Wait] Checking again in 60 seconds...")
        time.sleep(60)


def download_results(batch_id: str, novel_id: str):
    """Download and save batch results."""
    print(f"\n=== Downloading results for {batch_id} ===")

    output_dir = Path(f"novels/{novel_id}/deltas_v2_1")
    output_dir.mkdir(parents=True, exist_ok=True)

    succeeded = 0
    errored = 0

    # Stream results
    for result in client.messages.batches.results(batch_id):
        custom_id = result.custom_id  # Format: "{novel_id}_ch{num}"
        ch_num = int(custom_id.split("_ch")[1])

        if result.result.type == "succeeded":
            # Extract JSON from response
            message = result.result.message
            response_text = message.content[0].text

            try:
                # Parse LLM output
                import re
                json_match = re.search(r'```json\s*\n(.*?)\n```', response_text, re.DOTALL)
                if json_match:
                    llm_data = json.loads(json_match.group(1))
                else:
                    # Try raw JSON
                    llm_data = json.loads(response_text)

                # Build complete delta with ALL extracted fields
                delta = {
                    "schema_version": "2.1",
                    "chapter_number": ch_num,
                    "summary": llm_data.get("summary", f"Chapter {ch_num}"),
                    "facts": llm_data.get("facts", []),
                    "timeline_events": llm_data.get("timeline_events", []),
                    "emotion_targets": llm_data.get("emotion_targets", {}),
                    "tension_curve": llm_data.get("tension_curve", {"start": 50, "peak": 50, "end": 50}),
                    "prose_samples": llm_data.get("prose_samples", []),
                    "character_voice_samples": llm_data.get("character_voice_samples", []),
                    "scene_structure_patterns": llm_data.get("scene_structure_patterns", []),
                    "narrative_voice_tracking": llm_data.get("narrative_voice_tracking", {}),
                    "style_dna": llm_data.get("style_dna", {})
                }

                # Save
                output_path = output_dir / f"ch{ch_num}.json"
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(delta, f, indent=2, ensure_ascii=False)

                print(f"[OK] Saved ch{ch_num}")
                succeeded += 1

            except Exception as e:
                print(f"[ERROR] Ch{ch_num} parsing failed: {e}")
                errored += 1

        elif result.result.type == "errored":
            error_type = result.result.error.error.type
            print(f"[ERROR] Ch{ch_num}: {error_type}")
            errored += 1

        else:
            print(f"[SKIP] Ch{ch_num}: {result.result.type}")

    print(f"\n[Summary] Succeeded: {succeeded}, Errored: {errored}")
    return succeeded, errored


def main():
    parser = argparse.ArgumentParser(description="Batch extraction using Message Batches API")
    parser.add_argument("--novel", required=True, help="Novel ID")
    parser.add_argument("--start", type=int, help="Start chapter")
    parser.add_argument("--end", type=int, help="End chapter")
    parser.add_argument("--batch-id", help="Retrieve existing batch by ID")
    parser.add_argument("--poll-only", action="store_true", help="Only poll, don't create")

    args = parser.parse_args()

    # Validate args
    if not args.poll_only and not args.batch_id:
        if not args.start or not args.end:
            parser.error("--start and --end are required when creating a new batch")

    if args.batch_id or args.poll_only:
        # Retrieve existing batch
        if not args.batch_id:
            batch_log_path = Path(f"batch_logs/{args.novel}_batch.json")
            with open(batch_log_path) as f:
                batch_info = json.load(f)
                args.batch_id = batch_info["batch_id"]

        batch = poll_batch(args.batch_id, args.novel)

        if batch.processing_status == "ended":
            download_results(args.batch_id, args.novel)
    else:
        # Create new batch
        batch = create_message_batch(args.novel, args.start, args.end)

        if batch:
            print(f"\n[Next] Poll with: python extract_batch.py --novel {args.novel} --batch-id {batch.id}")


if __name__ == "__main__":
    main()
