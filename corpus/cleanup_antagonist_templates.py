"""One-time (and re-runnable) cleanup for templates/antagonists.json files.

merge_antagonist_templates() in merge.py used to (a) collapse every
antagonist_template_instance missing a template_id into one shared
`template_id: None` junk bucket, and (b) append instances with no dedup
check, so re-merging the same chapters duplicated entries. Both bugs are
fixed at the source in merge.py; this script repairs files that were
already written before that fix.

Usage: python cleanup_antagonist_templates.py [novel_id ...]
       (no args = clean every novel under novels/)
"""
import json
import sys
from pathlib import Path

NOVELS_DIR = Path(__file__).parent / "novels"


def clean(path: Path) -> tuple[int, int]:
    """Returns (templates_dropped, instances_deduped)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return (0, 0)

    kept = []
    templates_dropped = 0
    instances_deduped = 0

    for template in data:
        tid = template.get("template_id")
        instances = template.get("instances") or []
        real_instances = [i for i in instances if i.get("entity")]

        if not tid or not real_instances:
            templates_dropped += 1
            continue

        deduped = []
        for inst in real_instances:
            if inst not in deduped:
                deduped.append(inst)
        instances_deduped += len(real_instances) - len(deduped)

        template["instances"] = deduped
        kept.append(template)

    if templates_dropped or instances_deduped:
        path.write_text(json.dumps(kept, indent=2, ensure_ascii=False), encoding="utf-8")
    return (templates_dropped, instances_deduped)


def main():
    novel_ids = sys.argv[1:] or [p.name for p in NOVELS_DIR.iterdir() if p.is_dir()]
    for novel_id in novel_ids:
        f = NOVELS_DIR / novel_id / "templates" / "antagonists.json"
        if not f.exists():
            continue
        dropped, deduped = clean(f)
        if dropped or deduped:
            print(f"{novel_id}: dropped {dropped} junk template(s), removed {deduped} duplicate instance(s)")
        else:
            print(f"{novel_id}: clean, no changes")


if __name__ == "__main__":
    main()
