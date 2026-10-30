#!/usr/bin/env python3
"""
NovelTea Engine Validation Layer
==========================
Run after every extraction batch. Fails fast on schema violations.

Usage:
    python validate.py --novel my_novel
    python validate.py --novel my_novel --chapter 41
    python validate.py --all
"""

import json
import sys
import argparse
from pathlib import Path
from typing import Optional

REQUIRED_DELTA_FIELDS = [
    "chapter_number",
    "chapter_title",
    "chapter_function",
    "summary",
    "reader_psychology",
    "author_intent",
]

VALID_CHAPTER_FUNCTIONS = {
    "setup", "escalation", "payoff", "climax", "resolution",
    "transition", "hook", "cooldown", "arc_finale", "reveal"
}

VALID_REVEAL_TYPES = {
    "power_reveal", "identity_reveal", "relationship_reveal",
    "conspiracy_reveal", "world_reveal", "betrayal_reveal",
    "secret_goal_reveal", "ability_reveal"
}


def load_json(path: Path) -> Optional[dict | list]:
    try:
        with open(path) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        return None, f"JSON parse error: {e}"
    except FileNotFoundError:
        return None, f"File not found: {path}"


def validate_delta(path: Path) -> list[str]:
    errors = []
    raw = path.read_text(encoding='utf-8')
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return [f"INVALID JSON in {path.name}: {e}"]

    # Required fields
    for field in REQUIRED_DELTA_FIELDS:
        if field not in data:
            errors.append(f"Missing required field: '{field}'")

    # chapter_number matches filename
    if "chapter_number" in data:
        expected = int(path.stem[2:])  # ch042 -> 42
        if data["chapter_number"] != expected:
            errors.append(f"chapter_number {data['chapter_number']} doesn't match filename {path.name}")

    # chapter_function is valid
    if "chapter_function" in data:
        if data["chapter_function"] not in VALID_CHAPTER_FUNCTIONS:
            errors.append(f"Unknown chapter_function: '{data['chapter_function']}'")

    # reader_psychology structure
    rp = data.get("reader_psychology", {})
    if rp:
        tc = rp.get("tension_curve", {})
        if tc:
            for k in ("start", "peak", "end"):
                if k not in tc:
                    errors.append(f"reader_psychology.tension_curve missing '{k}'")
                elif not (0 <= tc.get(k, 0) <= 100):
                    errors.append(f"reader_psychology.tension_curve.{k} out of range 0-100")

    # reveals reference validation
    for rev in data.get("reveals", []):
        if "reveal_type" in rev and rev["reveal_type"] not in VALID_REVEAL_TYPES:
            errors.append(f"Unknown reveal_type: '{rev['reveal_type']}'")
        if "payoff_chapter" in rev:
            if rev["payoff_chapter"] != data.get("chapter_number"):
                errors.append(f"reveal payoff_chapter {rev['payoff_chapter']} != chapter {data.get('chapter_number')}")

    # humor_instances structure
    for i, h in enumerate(data.get("humor_instances", [])):
        if "type" not in h:
            errors.append(f"humor_instance[{i}] missing 'type'")
        if "source_chapter" not in h:
            errors.append(f"humor_instance[{i}] missing 'source_chapter'")

    return errors


def validate_novel(novel_id: str, chapter: Optional[int] = None) -> dict:
    nd = Path(f"novels/{novel_id}")
    if not nd.exists():
        return {"novel": novel_id, "status": "ERROR", "errors": [f"Novel directory not found: {nd}"]}

    delta_dir = nd / "deltas_v2"
    if not delta_dir.exists():
        return {"novel": novel_id, "status": "ERROR", "errors": ["deltas_v2/ directory not found"]}

    if chapter:
        deltas = [delta_dir / f"ch{chapter:03d}.json"]
    else:
        deltas = sorted(delta_dir.glob("ch*.json"))

    if not deltas:
        return {"novel": novel_id, "status": "WARN", "errors": ["No delta files found"]}

    all_errors = {}
    chapter_nums = []

    for delta_path in deltas:
        if not delta_path.exists():
            all_errors[delta_path.name] = [f"File not found: {delta_path}"]
            continue
        errs = validate_delta(delta_path)
        if errs:
            all_errors[delta_path.name] = errs
        # track chapter numbers for sequence check
        try:
            data = json.loads(delta_path.read_text())
            chapter_nums.append(data.get("chapter_number", 0))
        except Exception:
            pass

    # Sequence check
    if len(chapter_nums) > 1 and not chapter:
        sorted_nums = sorted(chapter_nums)
        expected = list(range(sorted_nums[0], sorted_nums[-1] + 1))
        missing = set(expected) - set(sorted_nums)
        if missing:
            all_errors["__sequence__"] = [f"Missing chapters: {sorted(missing)}"]

    # Entity files check
    entity_dir = nd / "entities"
    entity_count = len(list(entity_dir.glob("*.json"))) if entity_dir.exists() else 0

    status = "PASS" if not all_errors else "FAIL"
    return {
        "novel": novel_id,
        "status": status,
        "chapters_checked": len(deltas),
        "entities": entity_count,
        "errors": all_errors
    }


def validate_all() -> None:
    registry_path = Path("novels/registry.json")
    if not registry_path.exists():
        print("ERROR: novels/registry.json not found")
        sys.exit(1)

    registry = json.loads(registry_path.read_text())
    novels = [n["id"] for n in registry.get("novels", [])]

    total_pass = 0
    total_fail = 0

    for novel_id in novels:
        result = validate_novel(novel_id)
        status_icon = "OK" if result["status"] == "PASS" else "FAIL"
        print(f"  {status_icon} {novel_id}: {result['status']} ({result.get('chapters_checked', 0)} chapters, {result.get('entities', 0)} entities)")
        if result["errors"]:
            for fname, errs in result["errors"].items():
                for e in errs:
                    print(f"      -> {fname}: {e}")
            total_fail += 1
        else:
            total_pass += 1

    print(f"\nResult: {total_pass} pass / {total_fail} fail")
    if total_fail:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NovelTea Engine validation layer")
    parser.add_argument("--novel", help="Novel ID to validate")
    parser.add_argument("--chapter", type=int, help="Specific chapter number to validate")
    parser.add_argument("--all", action="store_true", help="Validate all novels")
    args = parser.parse_args()

    if args.all:
        print("Validating all novels...\n")
        validate_all()
    elif args.novel:
        print(f"Validating {args.novel}{'  ch.' + str(args.chapter) if args.chapter else ''}...\n")
        result = validate_novel(args.novel, args.chapter)
        status_icon = "OK" if result["status"] == "PASS" else "FAIL"
        print(f"  {status_icon} {result['novel']}: {result['status']}")
        print(f"  Chapters checked: {result.get('chapters_checked', 0)}")
        print(f"  Entities: {result.get('entities', 0)}")
        if result["errors"]:
            print("\n  Errors:")
            for fname, errs in result["errors"].items():
                for e in errs:
                    print(f"    -> {fname}: {e}")
            sys.exit(1)
        else:
            print("  No errors found.")
    else:
        parser.print_help()
