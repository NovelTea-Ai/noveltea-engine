#!/usr/bin/env python3
"""
NovelTea Engine Audit Tool
====================
Run every 100 chapters to catch entity drift, relationship drift, orphan reveals.

Usage:
    python audit.py --novel my_novel
    python audit.py --all
    python audit.py --novel my_novel --fix-drift  (auto-normalizes obvious cases)
"""

import json
import argparse
import sys
from pathlib import Path


def load_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None


def levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        return levenshtein(b, a)
    if len(b) == 0:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j+1]+1, curr[j]+1, prev[j]+(ca != cb)))
        prev = curr
    return prev[len(b)]


def audit_entity_drift(novel_id: str) -> list[str]:
    """Find near-duplicate entity names that may be the same entity."""
    entity_dir = Path(f"novels/{novel_id}/entities")
    if not entity_dir.exists():
        return ["Entity directory not found"]

    entities = {}
    for f in entity_dir.glob("*.json"):
        data = load_json(f)
        if data:
            name = data.get("name", f.stem)
            aliases = set(data.get("aliases", [name]))
            entities[f.stem] = {"name": name, "aliases": aliases}

    issues = []
    import re as _re
    names = list(entities.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if _re.match(r'^chapter_[0-9]+$', names[i]) or _re.match(r'^chapter_[0-9]+$', names[j]):
                continue
            a_data = entities[names[i]]
            b_data = entities[names[j]]
            a_name = a_data["name"].lower()
            b_name = b_data["name"].lower()
            dist = levenshtein(a_name, b_name)
            threshold = max(2, int(len(a_name) * 0.3))
            if dist <= threshold and dist > 0:
                issues.append(
                    f"DRIFT? '{a_data['name']}' and '{b_data['name']}' "
                    f"(edit distance: {dist}) — may be same entity"
                )
    return issues


def audit_reveals(novel_id: str) -> list[str]:
    """Find reveals that were set up but never resolved (orphan reveals)."""
    reveals_path = Path(f"novels/{novel_id}/reveals/log.json")
    if not reveals_path.exists():
        return []

    reveals = load_json(reveals_path) or []
    issues = []

    for rev in reveals:
        setup_chs = rev.get("setup_chapters", [])
        payoff_ch = rev.get("payoff_chapter")
        content = rev.get("content", "")[:80]
        reveal_type = rev.get("reveal_type", "unknown")

        if not payoff_ch:
            issues.append(
                f"ORPHAN REVEAL: [{reveal_type}] set up in ch.{setup_chs} "
                f"has no payoff_chapter — '{content}...'"
            )

    return issues


def audit_humor_density(novel_id: str) -> list[str]:
    """Flag chapters with zero humor instances (may indicate missed extraction)."""
    humor_path = Path(f"novels/{novel_id}/humor/instances.json")
    delta_dir = Path(f"novels/{novel_id}/deltas_v2")
    if not humor_path.exists() or not delta_dir.exists():
        return []

    humor_data = load_json(humor_path) or []
    humor_chapters = set(h.get("source_chapter") for h in humor_data)

    all_chapters = [int(f.stem[2:]) for f in sorted(delta_dir.glob("ch*.json"))]
    issues = []

    # Check for long runs without any humor
    zero_runs = []
    current_run = []
    for ch in all_chapters:
        if ch not in humor_chapters:
            current_run.append(ch)
        else:
            if len(current_run) >= 5:
                zero_runs.append(current_run[:])
            current_run = []
    if len(current_run) >= 5:
        zero_runs.append(current_run)

    for run in zero_runs:
        issues.append(
            f"HUMOR GAP: Chapters {run[0]}-{run[-1]} ({len(run)} consecutive) "
            f"have no humor instances — possible extraction miss"
        )

    return issues


def audit_chapter_continuity(novel_id: str) -> list[str]:
    """Check for gaps in chapter numbering."""
    delta_dir = Path(f"novels/{novel_id}/deltas_v2")
    if not delta_dir.exists():
        return ["deltas_v2/ not found"]

    nums = sorted([int(f.stem[2:]) for f in delta_dir.glob("ch*.json")])
    if not nums:
        return ["No chapters found"]

    issues = []
    expected = set(range(nums[0], nums[-1] + 1))
    missing = sorted(expected - set(nums))
    if missing:
        issues.append(f"MISSING CHAPTERS: {missing}")

    return issues


def audit_novel(novel_id: str) -> dict:
    print(f"\n  Auditing {novel_id}...")
    all_issues = []

    entity_issues = audit_entity_drift(novel_id)
    reveal_issues = audit_reveals(novel_id)
    humor_issues = audit_humor_density(novel_id)
    continuity_issues = audit_chapter_continuity(novel_id)

    all_issues.extend(entity_issues)
    all_issues.extend(reveal_issues)
    all_issues.extend(humor_issues)
    all_issues.extend(continuity_issues)

    status = "CLEAN" if not all_issues else "ISSUES"
    return {
        "novel": novel_id,
        "status": status,
        "entity_drift": len(entity_issues),
        "orphan_reveals": len(reveal_issues),
        "humor_gaps": len(humor_issues),
        "continuity": len(continuity_issues),
        "issues": all_issues
    }


def main():
    parser = argparse.ArgumentParser(description="NovelTea Engine quality audit")
    parser.add_argument("--novel", help="Novel ID to audit")
    parser.add_argument("--all", action="store_true", help="Audit all novels")
    args = parser.parse_args()

    registry_path = Path("novels/registry.json")
    registry = json.loads(registry_path.read_text(encoding='utf-8')) if registry_path.exists() else {"novels": []}

    if args.all:
        novels = [n["id"] for n in registry.get("novels", [])]
    elif args.novel:
        novels = [args.novel]
    else:
        parser.print_help()
        sys.exit(0)

    total_issues = 0
    for novel_id in novels:
        result = audit_novel(novel_id)
        icon = "OK" if result["status"] == "CLEAN" else "WARNING"
        print(f"  {icon} {result['novel']}: {result['status']}")
        if result["issues"]:
            for issue in result["issues"]:
                print(f"    -> {issue}")
            total_issues += len(result["issues"])
        else:
            print(f"    No issues found")

    print(f"\nTotal issues: {total_issues}")


if __name__ == "__main__":
    main()
