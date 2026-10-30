#!/usr/bin/env python3
"""
NovelTea Engine Extraction Pipeline
==============================
Reads raw chapter text files and calls the Anthropic API to extract
structured delta JSON, then saves and merges automatically.

Usage:
    python extract.py --novel my_novel --chapters 41-50
    python extract.py --novel my_novel --chapter 41
    python extract.py --novel my_novel --resume
    python extract.py --novel my_novel --chapters 1-100 --batch-size 10

Prerequisites:
    pip install anthropic loguru rich
    export ANTHROPIC_API_KEY=sk-...

Directory layout expected:
    corpus/
      raw/<novel_id>/ch001.txt  ch002.txt  ...
      novels/<novel_id>/deltas_v2/
      logs/
"""

import json
import os
import sys
import time
import argparse
import subprocess

# Load API key from .env file if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, will use environment variable directly
from pathlib import Path
from datetime import datetime, timezone

try:
    import anthropic
except ImportError:
    print("ERROR: anthropic package not installed. Run: pip install anthropic")
    sys.exit(1)

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("noveltea")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

try:
    RICH = True
except ImportError:
    RICH = False

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096
LOGS_DIR = Path("logs")
CHECKPOINT_DIR = Path("checkpoints")
SCHEMA_VERSION = "2.0"


def load_checkpoint(novel_id: str) -> dict:
    path = CHECKPOINT_DIR / f"{novel_id}.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"novel": novel_id, "last_completed": 0, "failed": []}


def save_checkpoint(novel_id: str, last_completed: int, failed: list) -> None:
    CHECKPOINT_DIR.mkdir(exist_ok=True)
    path = CHECKPOINT_DIR / f"{novel_id}.json"
    path.write_text(json.dumps({
        "novel": novel_id,
        "last_completed": last_completed,
        "failed": failed,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }, indent=2), encoding='utf-8')


def log_result(novel_id: str, chapter: int, status: str,
               tokens_in: int = 0, tokens_out: int = 0,
               cost: float = 0.0, elapsed: float = 0.0,
               error: str = "") -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    log_path = LOGS_DIR / f"{novel_id}.jsonl"
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "novel": novel_id,
        "chapter": chapter,
        "status": status,
        "tokens_input": tokens_in,
        "tokens_output": tokens_out,
        "cost_usd": round(cost, 6),
        "time_seconds": round(elapsed, 2),
        "error": error
    }
    with open(log_path, "a") as f:
        f.write(json.dumps(record) + "\n")


def estimate_cost(tokens_in: int, tokens_out: int) -> float:
    # claude-sonnet-4-6 pricing (update if pricing changes)
    cost_in = tokens_in * 3.0 / 1_000_000    # $3/M input
    cost_out = tokens_out * 15.0 / 1_000_000  # $15/M output
    return cost_in + cost_out


def build_extraction_prompt(novel_id: str, chapter_num: int, chapter_text: str) -> str:
    # Load existing novel metadata for context
    meta_path = Path(f"novels/{novel_id}/novel_metadata.json")
    meta_summary = ""
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        meta_summary = f"Novel: {meta.get('title', novel_id)}\nCultural DNA: {json.dumps(meta.get('cultural_dna', {}))}\n"

    # Load last 3 chapter summaries for continuity
    prior_context = ""
    for offset in [3, 2, 1]:
        prior_ch = chapter_num - offset
        if prior_ch > 0:
            prior_path = Path(f"novels/{novel_id}/deltas_v2/ch{prior_ch:03d}.json")
            if prior_path.exists():
                prior = json.loads(prior_path.read_text(encoding='utf-8'))
                prior_context += f"Ch.{prior_ch} summary: {prior.get('summary', '')[:300]}\n"

    return f"""You are a literary analysis engine for the NovelTea Engine corpus.
Extract a structured delta JSON for the chapter below.

{meta_summary}
Prior context:
{prior_context}

OUTPUT FORMAT — return ONLY valid JSON, no markdown fences, no preamble:
{{
  "schema_version": "2.0",
  "chapter_number": {chapter_num},
  "chapter_title": "...",
  "title_function": "thematic_statement|ironic_statement|dialogue_quote|setting|thematic_question",
  "chapter_function": "setup|escalation|payoff|climax|resolution|transition|hook|cooldown|arc_finale|reveal",
  "summary": "2-4 sentence summary of major plot events",
  "arc_label_suggestion": "Arc N: Name",
  "arc_boundary_signal": false,
  "new_characters": [],
  "new_locations": [],
  "new_glossary_terms": [],
  "humor_instances": [],
  "reveals": [],
  "schemes": [],
  "facts": [],
  "timeline_events": [],
  "reader_psychology": {{
    "reader_emotions": {{}},
    "payoff_categories": {{}},
    "tension_curve": {{"start": 0, "peak": 0, "end": 0}}
  }},
  "author_intent": {{
    "author_goal": "...",
    "reader_effect": "...",
    "theme_reinforced": "...",
    "strategy_notes": "..."
  }},
  "novel_metadata_hints": {{}}
}}

CHAPTER {chapter_num} TEXT:
{chapter_text[:12000]}
"""


def extract_chapter(client: anthropic.Anthropic, novel_id: str,
                    chapter_num: int, chapter_text: str) -> tuple[dict | None, dict]:
    prompt = build_extraction_prompt(novel_id, chapter_num, chapter_text)
    start = time.time()

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}]
        )
        elapsed = time.time() - start
        tokens_in = response.usage.input_tokens
        tokens_out = response.usage.output_tokens
        cost = estimate_cost(tokens_in, tokens_out)

        raw_text = response.content[0].text.strip()
        # Strip markdown fences if model adds them
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1]
            if raw_text.endswith("```"):
                raw_text = raw_text.rsplit("```", 1)[0]

        data = json.loads(raw_text)
        data["schema_version"] = SCHEMA_VERSION

        stats = {"tokens_in": tokens_in, "tokens_out": tokens_out,
                 "cost": cost, "elapsed": elapsed, "status": "success"}
        return data, stats

    except json.JSONDecodeError as e:
        elapsed = time.time() - start
        stats = {"tokens_in": 0, "tokens_out": 0, "cost": 0,
                 "elapsed": elapsed, "status": "json_error", "error": str(e)}
        return None, stats
    except Exception as e:
        elapsed = time.time() - start
        stats = {"tokens_in": 0, "tokens_out": 0, "cost": 0,
                 "elapsed": elapsed, "status": "api_error", "error": str(e)}
        return None, stats


def run_merge(novel_id: str, delta_paths: list[Path]) -> bool:
    args = ["python3", "merge.py", "--novel", novel_id] + [str(p) for p in delta_paths]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"merge.py failed:\n{result.stderr}")
        return False
    return True


def parse_chapter_range(spec: str) -> list[int]:
    if "-" in spec:
        start, end = spec.split("-")
        return list(range(int(start), int(end) + 1))
    return [int(spec)]


def main():
    parser = argparse.ArgumentParser(description="NovelTea Engine extraction pipeline")
    parser.add_argument("--novel", required=True, help="Novel ID")
    parser.add_argument("--chapter", type=int, help="Single chapter number")
    parser.add_argument("--chapters", help="Chapter range, e.g. 41-50")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    parser.add_argument("--batch-size", type=int, default=10, help="Auto-merge every N chapters")
    parser.add_argument("--dry-run", action="store_true", help="Print what would run, don't call API")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key and not args.dry_run:
        print("ERROR: ANTHROPIC_API_KEY environment variable not set")
        sys.exit(1)

    novel_id = args.novel
    raw_dir = Path(f"raw/{novel_id}")
    delta_dir = Path(f"novels/{novel_id}/deltas_v2")
    delta_dir.mkdir(parents=True, exist_ok=True)

    # Determine chapter list
    if args.resume:
        checkpoint = load_checkpoint(novel_id)
        last = checkpoint["last_completed"]
        # Find all raw files after last_completed
        all_raw = sorted(raw_dir.glob("ch*.txt"))
        chapters = [int(p.stem[2:]) for p in all_raw if int(p.stem[2:]) > last]
        print(f"Resuming from chapter {last + 1}. {len(chapters)} chapters to process.")
    elif args.chapters:
        chapters = parse_chapter_range(args.chapters)
    elif args.chapter:
        chapters = [args.chapter]
    else:
        chapters = [int(p.stem[2:]) for p in sorted(raw_dir.glob("ch*.txt"))]

    if not chapters:
        print("No chapters to process.")
        sys.exit(0)

    if args.dry_run:
        print(f"DRY RUN: Would extract {len(chapters)} chapters from {raw_dir}")
        print(f"  Chapters: {chapters[0]}–{chapters[-1]}")
        print(f"  Batch size: {args.batch_size}")
        print(f"  Estimated cost: ~${len(chapters) * 0.008:.2f} (rough estimate)")
        sys.exit(0)

    client = anthropic.Anthropic(api_key=api_key)

    total_cost = 0.0
    total_tokens_in = 0
    total_tokens_out = 0
    failed = []
    batch_deltas = []
    checkpoint = load_checkpoint(novel_id)

    print(f"\nNovelTea Engine Extraction Pipeline")
    print(f"Novel: {novel_id} | Chapters: {len(chapters)} | Batch size: {args.batch_size}\n")

    for i, ch_num in enumerate(chapters, 1):
        raw_path = raw_dir / f"ch{ch_num:03d}.txt"
        delta_path = delta_dir / f"ch{ch_num:03d}.json"

        # Skip if already extracted
        if delta_path.exists():
            print(f"  [SKIP] ch{ch_num:03d} already extracted")
            continue

        if not raw_path.exists():
            print(f"  [MISS] ch{ch_num:03d} raw file not found: {raw_path}")
            failed.append(ch_num)
            continue

        chapter_text = raw_path.read_text(encoding="utf-8")
        print(f"  [{i:03d}/{len(chapters)}] Extracting ch{ch_num:03d}...", end=" ", flush=True)

        data, stats = extract_chapter(client, novel_id, ch_num, chapter_text)

        if data:
            delta_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
            batch_deltas.append(delta_path)
            total_cost += stats["cost"]
            total_tokens_in += stats["tokens_in"]
            total_tokens_out += stats["tokens_out"]
            log_result(novel_id, ch_num, "success", stats["tokens_in"],
                       stats["tokens_out"], stats["cost"], stats["elapsed"])
            print(f"OK ${stats['cost']:.4f} | {stats['tokens_in']}+{stats['tokens_out']} tok | {stats['elapsed']:.1f}s")
            save_checkpoint(novel_id, ch_num, failed)
        else:
            failed.append(ch_num)
            log_result(novel_id, ch_num, stats["status"], error=stats.get("error", ""))
            print(f"FAILED: {stats.get('error', 'unknown')}")

        # Auto-merge on batch boundaries
        if len(batch_deltas) >= args.batch_size:
            print(f"\n  >> Auto-merging {len(batch_deltas)} chapters...")
            if run_merge(novel_id, batch_deltas):
                print(f"  OK Merge complete\n")
            else:
                print(f"  FAILED Merge failed -- check logs\n")
            batch_deltas = []

        # Rate limit protection: small sleep between API calls
        if i < len(chapters):
            time.sleep(0.5)

    # Final merge for remaining deltas
    if batch_deltas:
        print(f"\n  >> Final merge of {len(batch_deltas)} chapters...")
        run_merge(novel_id, batch_deltas)

    # Summary
    print(f"\n{'='*50}")
    print(f"Extraction complete")
    print(f"  Chapters processed: {len(chapters) - len(failed)}/{len(chapters)}")
    print(f"  Failed: {failed if failed else 'none'}")
    print(f"  Total cost: ${total_cost:.4f}")
    print(f"  Total tokens: {total_tokens_in:,} in / {total_tokens_out:,} out")
    if failed:
        print(f"\nRe-run with --resume to retry failed chapters")


if __name__ == "__main__":
    main()
