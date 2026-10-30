"""
migrate_to_v4.py — fold the Chapter Mechanics sidecars into the chapter deltas (V4).

For every chapter that has novels/<id>/deltas_mechanics/chN.json and a novels/<id>/deltas_v3/chN.json, the sidecar's
mechanics are written into the delta as delta["mechanics"] and the delta is marked schema_version "4.0" (its first key).
Additive and reversible: the sidecar files are NOT touched or deleted (a zip backup also exists in _backups), and undoing it
is removing the "mechanics" key. Each write is verified by reading the file back.

    python migrate_to_v4.py --dry-run          # count what would change
    python migrate_to_v4.py                    # all novels
    python migrate_to_v4.py --novel my_novel
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mechanics_core as mc  # noqa: E402

CH = re.compile(r"^ch(\d+)\.json$")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--novel")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    tot = {"moved": 0, "already": 0, "no_delta": 0, "failed": 0}
    for nd in sorted((HERE / "novels").iterdir()):
        side = nd / "deltas_mechanics"
        if not side.is_dir() or (a.novel and nd.name != a.novel):
            continue
        n = {"moved": 0, "already": 0, "no_delta": 0, "failed": 0}
        for f in sorted(side.iterdir(), key=lambda p: p.name):
            m = CH.match(f.name)
            if not m:
                continue
            ch = int(m.group(1))
            dp = nd / "deltas_v3" / f.name
            if not dp.exists():
                n["no_delta"] += 1
                continue
            if mc.has_mechanics(nd.name, ch, current_schema=False) and _in_delta(dp):
                n["already"] += 1
                continue
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                n["failed"] += 1
                continue
            if a.dry_run:
                n["moved"] += 1
                continue
            if mc.attach_mechanics(nd.name, ch, rec) and _verify(dp, rec):
                n["moved"] += 1
            else:
                n["failed"] += 1
                print(f"  FAILED {nd.name} ch{ch}")
        for k in tot:
            tot[k] += n[k]
        print(f"{nd.name}: {n}")
    print(("DRY RUN " if a.dry_run else "") + f"total {tot}")


def _in_delta(dp: Path) -> bool:
    try:
        return bool(json.loads(dp.read_text(encoding="utf-8")).get("mechanics"))
    except Exception:
        return False


def _verify(dp: Path, rec: dict) -> bool:
    """The file reads back as valid JSON, is marked 4.0 first, and its mechanics equal the sidecar's."""
    try:
        raw = dp.read_text(encoding="utf-8")
        d = json.loads(raw)
        return bool(re.match(r'\{\s*"schema_version"\s*:\s*"4\.0"', raw)) and d.get("mechanics") == rec
    except Exception:
        return False


if __name__ == "__main__":
    main()
