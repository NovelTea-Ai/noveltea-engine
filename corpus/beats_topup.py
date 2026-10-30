"""Beats top-up helper.

    python beats_topup.py show <novel> <ch>              the chapter paragraph-numbered, its existing beats, the allowed tags and roles, the target count
    python beats_topup.py check <novel> <ch> <file.json> validate a proposed FULL beats list (dry run: writes nothing)
    python beats_topup.py apply <novel> <dir> <ch> ...   apply <dir>/chN.json to each chapter's mechanics record (isolated: only beats change)

A beats file is {"mx_beats": [ {paras:[a,b], role, driver, spoken, meaning, tags:{moment,purpose,motive,reader_effect,device},
specifics:[...], quotes:[...]} , ...]} holding the COMPLETE list in story order: every existing beat kept (reworded only if wrong)
plus the missing ones. Tags must come from the fixed tag set, roles from the role list, quotes must be verbatim from the chapter.
mechanics_core.apply_upgraded_part does the validation and accepts the list only if it is strictly longer.
"""
import json
import sys
from pathlib import Path

import mechanics_core as mc

HERE = Path(__file__).parent


def _load(novel, ch):
    text = (HERE / "raw" / novel / f"ch{ch}.txt").read_text(encoding="utf-8")
    d = json.loads((HERE / "novels" / novel / "deltas_v3" / f"ch{ch}.json").read_text(encoding="utf-8"))
    return text, d


def target(text):
    words = len(text.split())
    aim = max(4, round(words / 1000 * mc.BEATS_PER_KWORD))
    return words, aim, max(aim + 4, round(aim * 1.5))


def show(novel, ch):
    text, d = _load(novel, ch)
    words, aim, top = target(text)
    rec = d.get("mechanics") or {}
    print(f"CHAPTER {ch}: {words} words, {len(mc.paragraphs(text))} paragraphs. Existing beats: {len(rec.get('beats') or [])}. "
          f"Return between {aim} and {top} beats in total.\n")
    print("ROLES:", " ".join(sorted(mc.ROLES)))
    for f, terms in mc.facets().items():
        print(f"TAGS {f}: {', '.join(terms)}")
    print("\n===== PARAGRAPH-NUMBERED TEXT =====")
    print(mc.numbered_text(text))
    print("\n===== EXISTING BEATS =====")
    for i, b in enumerate(rec.get("beats") or [], 1):
        print(i, json.dumps(b, ensure_ascii=False))


def check(novel, ch, f, write=False):
    text, d = _load(novel, ch)
    rec = d.get("mechanics")
    val = json.loads(Path(f).read_text(encoding="utf-8")).get("mx_beats")
    notes = []
    new, why = mc.apply_upgraded_part(rec, "mx_beats", val, text, notes)
    words, aim, top = target(text)
    have = len(rec.get("beats") or [])
    got = len(new.get("beats") or [])
    print(f"ch{ch}: existing {have} -> proposed {len(val or [])} -> valid {got} (aim {aim}-{top})", "ACCEPTED" if not why else f"REJECTED: {why}")
    for n in notes[:12]:
        print("   note:", n)
    if write and not why:
        new = dict(new)
        new["upgraded"] = True
        ok = mc.attach_mechanics(novel, ch, new)
        print(f"   saved: {ok}")
    return not why


def main():
    cmd = sys.argv[1]
    if cmd == "show":
        show(sys.argv[2], int(sys.argv[3]))
    elif cmd == "check":
        check(sys.argv[2], int(sys.argv[3]), sys.argv[4])
    elif cmd == "apply":
        novel, d = sys.argv[2], Path(sys.argv[3])
        for ch in sys.argv[4:]:
            f = d / f"ch{ch}.json"
            if f.exists():
                check(novel, int(ch), f, write=True)
            else:
                print(f"ch{ch}: no file")


if __name__ == "__main__":
    main()
