"""Add hand-written (agent-written) top-up material to chapter deltas: python apply_topup.py <novel> <topup_dir> <ch> [<ch> ...]

Each <topup_dir>/chN.json holds new facts / timeline / knowledge / reveals / voice lines (see the shape in the file written for ch125).
Nothing is added unless it passes: a dialogue line must appear verbatim in the raw chapter, and an item that is already in the delta
(same subject-predicate-object, same event, same line...) is skipped. The delta is saved through extract_v3.save_delta, so the
mechanics block and the quality registry are handled exactly as for any other save.
"""
import json
import re
import sys
from pathlib import Path

import extract_v3 as E

HERE = Path(__file__).parent


def norm(s) -> str:
    s = str(s or "").replace("�", "'").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


def apply(novel: str, ch: int, add: dict) -> dict:
    path = HERE / "novels" / novel / "deltas_v3" / f"ch{ch}.json"
    d = json.loads(path.read_text(encoding="utf-8"))
    raw = norm((HERE / "raw" / novel / f"ch{ch}.txt").read_text(encoding="utf-8"))
    n = {"facts": 0, "timeline": 0, "knowledge": 0, "reveals": 0, "voice lines": 0, "skipped": 0, "bad quotes": 0}

    have = {norm(f"{x.get('subject')}|{x.get('predicate')}|{x.get('object')}") for x in d.get("facts") or []}
    for subj, pred, obj, otype, notes in add.get("facts") or []:
        k = norm(f"{subj}|{pred}|{obj}")
        if k in have or not subj or not obj:
            n["skipped"] += 1
            continue
        have.add(k)
        d.setdefault("facts", []).append({"subject": subj, "predicate": pred, "object": obj, "object_type": otype or "entity",
                                          "source_chapter": ch, "status": "active", "notes": notes or "", "spoiler_note": ""})
        n["facts"] += 1

    tl = d.setdefault("timeline_events", [])
    seen = {norm(x.get("event")) for x in tl}
    order = max([x.get("order") or 0 for x in tl] + [0])
    for ev, stakes in add.get("timeline") or []:
        if norm(ev) in seen or not ev:
            n["skipped"] += 1
            continue
        seen.add(norm(ev))
        order += 1
        tl.append({"event": ev, "order": order, "source_chapter": ch, "stakes": stakes or "", "spoiler_note": ""})
        n["timeline"] += 1

    ks = d.setdefault("knowledge_state", [])
    seen = {norm(x.get("fact")) for x in ks}
    for fact, known, hidden, hnotes in add.get("knowledge") or []:
        if norm(fact) in seen or not fact:
            n["skipped"] += 1
            continue
        seen.add(norm(fact))
        ks.append({"fact": fact, "known_to": known or [], "hidden_from": hidden or [], "hidden_from_notes": hnotes or "",
                   "established_chapter": ch, "resolved_chapter": "", "resolution": ""})
        n["knowledge"] += 1

    rv = d.setdefault("reveals", [])
    seen = {norm(x.get("content")) for x in rv}
    for rtype, content, setup, payoff, to, hidden, impact in add.get("reveals") or []:
        if norm(content) in seen or not content:
            n["skipped"] += 1
            continue
        seen.add(norm(content))
        rv.append({"reveal_type": rtype, "content": content, "setup_chapters": setup or [], "payoff_chapter": payoff or ch,
                   "revealed_to": to or ["reader"], "hidden_from_until_now": hidden or ["reader"], "impact": impact or ""})
        n["reveals"] += 1

    voices = d.setdefault("character_voice_samples", [])
    lines_have = {norm(s.get("line")) for v in voices for s in v.get("dialogue_samples") or []}
    for name, samples in add.get("voice") or []:
        good = []
        for line, context, notes in samples:
            nl = norm(line)
            if nl in lines_have:
                n["skipped"] += 1
                continue
            if nl not in raw:
                n["bad quotes"] += 1
                continue
            lines_have.add(nl)
            good.append({"line": line, "context": context or "", "voice_notes": notes or ""})
        if not good:
            continue
        ent = next((v for v in voices if norm(v.get("character_name")) == norm(name)), None)
        if ent is None:
            voices.append({"character_name": name, "dialogue_samples": good})
        else:
            ent.setdefault("dialogue_samples", []).extend(good)
        n["voice lines"] += len(good)

    E._V4_CTX["novel"] = novel
    E.save_delta(d, novel)
    return n


def main():
    novel, topdir, chs = sys.argv[1], Path(sys.argv[2]), [int(x) for x in sys.argv[3:]]
    for ch in chs:
        f = topdir / f"ch{ch}.json"
        if not f.exists():
            print(f"ch{ch}: no top-up file yet")
            continue
        print(f"ch{ch}:", apply(novel, ch, json.loads(f.read_text(encoding="utf-8"))))


if __name__ == "__main__":
    main()
