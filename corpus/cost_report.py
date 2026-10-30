#!/usr/bin/env python3
"""
NovelTea Engine Cost Monitor
=======================
Reads extraction logs and reports API costs per novel and total corpus.

Usage:
    python cost_report.py
    python cost_report.py --novel my_novel
    python cost_report.py --since 2025-01-01
"""

import json
import argparse
from pathlib import Path
from collections import defaultdict


def load_logs(novel_id=None, since=None):
    logs_dir = Path("logs")
    if not logs_dir.exists():
        return []

    records = []
    pattern = f"{novel_id}.jsonl" if novel_id else "*.jsonl"
    for log_file in logs_dir.glob(pattern):
        with open(log_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if since:
                        ts = rec.get("timestamp", "")
                        if ts < since:
                            continue
                    records.append(rec)
                except json.JSONDecodeError:
                    continue
    return records


def main():
    parser = argparse.ArgumentParser(description="NovelTea Engine cost report")
    parser.add_argument("--novel", help="Filter by novel ID")
    parser.add_argument("--since", help="Filter by date (YYYY-MM-DD)")
    args = parser.parse_args()

    records = load_logs(args.novel, args.since)

    if not records:
        print("No extraction logs found. Run extract.py first.")
        return

    # Aggregate by novel
    by_novel = defaultdict(lambda: {
        "chapters": 0, "success": 0, "failed": 0,
        "cost": 0.0, "tokens_in": 0, "tokens_out": 0,
        "time_total": 0.0
    })

    for r in records:
        nid = r.get("novel", "unknown")
        by_novel[nid]["chapters"] += 1
        if r.get("status") == "success":
            by_novel[nid]["success"] += 1
        else:
            by_novel[nid]["failed"] += 1
        by_novel[nid]["cost"] += r.get("cost_usd", 0)
        by_novel[nid]["tokens_in"] += r.get("tokens_input", 0)
        by_novel[nid]["tokens_out"] += r.get("tokens_output", 0)
        by_novel[nid]["time_total"] += r.get("time_seconds", 0)

    print("\n" + "="*60)
    print("NovelTea Engine Cost Report")
    if args.since:
        print(f"Since: {args.since}")
    print("="*60)

    total_cost = 0.0
    total_chapters = 0
    total_tokens = 0

    for novel_id, stats in sorted(by_novel.items()):
        success_rate = stats["success"] / max(stats["chapters"], 1) * 100
        avg_cost = stats["cost"] / max(stats["chapters"], 1)
        avg_time = stats["time_total"] / max(stats["chapters"], 1)
        tokens_total = stats["tokens_in"] + stats["tokens_out"]

        print(f"\n  {novel_id}")
        print(f"    Chapters:     {stats['chapters']} ({stats['success']} ok / {stats['failed']} failed = {success_rate:.0f}%)")
        print(f"    Cost:         ${stats['cost']:.4f}  (avg ${avg_cost:.4f}/chapter)")
        print(f"    Tokens:       {tokens_total:,}  ({stats['tokens_in']:,} in + {stats['tokens_out']:,} out)")
        print(f"    Time:         {stats['time_total']:.0f}s total  ({avg_time:.1f}s/chapter)")

        total_cost += stats["cost"]
        total_chapters += stats["chapters"]
        total_tokens += tokens_total

    print(f"\n{'─'*60}")
    print(f"  TOTAL")
    print(f"    Chapters:     {total_chapters}")
    print(f"    Cost:         ${total_cost:.4f}")
    print(f"    Tokens:       {total_tokens:,}")
    if total_chapters > 0:
        proj_10k = (total_cost / total_chapters) * 10000
        print(f"\n  Projection @ 10,000 chapters: ~${proj_10k:.2f}")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
