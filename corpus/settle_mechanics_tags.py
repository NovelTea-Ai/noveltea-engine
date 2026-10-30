"""
settle_mechanics_tags.py — turn the trial's free "specifics" into the fixed tag set (mechanics_tags.json), no AI.

Every beat / cast entry keeps off-list words as "facet:word" specifics. This collects them across the built mechanics
deltas, embeds each word and every existing term of its facet with nomic, and:
  - a specific within SYNONYM of an existing term is that term (e.g. moment:cultivation_surge -> breakthrough);
  - a word that recurs MIN_COUNT+ times with no close term becomes a NEW term of its facet;
  - the rest stay specifics (kept, searchable, never a tag).
Then it rewrites the built files so mapped / new terms move from specifics into tags, and writes the report to
mechanics_tags_report.json. --apply writes; without it, it only reports.

    python settle_mechanics_tags.py            # report only
    python settle_mechanics_tags.py --apply --lock
"""
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from knowledge_index import embed_text   # noqa: E402

TAGS = HERE / "mechanics_tags.json"
REPORT = HERE / "mechanics_tags_report.json"
CH = re.compile(r"^ch(\d+)\.json$")
SYNONYM = 0.80
MIN_COUNT = 3
BEAT_FACETS = ("moment", "purpose", "motive", "reader_effect", "device", "humor")
JUNK = {"none", "other", "misc", "unknown", "general", "null", "with", "from", "into", "that", "this"}


def files():
    for nd in sorted((HERE / "novels").iterdir()):
        d = nd / "deltas_mechanics"
        if d.is_dir():
            for f in d.iterdir():
                if CH.match(f.name):
                    yield f


def _cos(a, b):
    na, nb = math.sqrt(sum(x * x for x in a)) or 1, math.sqrt(sum(x * x for x in b)) or 1
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


_E = {}


def emb(word):
    if word not in _E:
        _E[word] = embed_text(word.replace("_", " "))
    return _E[word]


def main():
    apply_ = "--apply" in sys.argv
    tagfile = json.loads(TAGS.read_text(encoding="utf-8"))
    vocab = tagfile["facets"]
    counts = Counter()
    for f in files():
        m = json.loads(f.read_text(encoding="utf-8"))
        for b in (m.get("beats") or []) + (m.get("cast") or []):
            for s in (b.get("specifics") or []) if isinstance(b, dict) else []:
                if isinstance(s, str) and ":" in s:
                    fac, w = s.split(":", 1)
                    w = re.sub(r"[^a-z0-9_]+", "_", w.strip().lower()).strip("_")
                    if fac in vocab and w:
                        counts[(fac, w)] += 1
    mapping, new_terms = {}, {}
    for (fac, w), n in counts.most_common():
        if w in vocab[fac]:
            mapping[(fac, w)] = w
            continue
        best = max(((_cos(emb(w), emb(t)), t) for t in vocab[fac]), default=(0, None))
        if best[0] >= SYNONYM:
            mapping[(fac, w)] = best[1]
        elif n >= MIN_COUNT and w not in JUNK:
            new_terms.setdefault(fac, []).append(w)
            mapping[(fac, w)] = w
    # families: several one-off words sharing a head word (marriage_deadline, marriage_pressure, marriage_refusal) make
    # that head word a term when the family recurs MIN_COUNT+ times across 2+ different words
    fam = {}
    for (fac, w), n in counts.items():
        if (fac, w) in mapping:
            continue
        for tok in w.split("_"):
            if len(tok) >= 4 and tok not in JUNK:
                fam.setdefault((fac, tok), []).append((w, n))
    for (fac, tok), members in sorted(fam.items(), key=lambda kv: -sum(n for _, n in kv[1])):
        members = [(w, n) for w, n in members if (fac, w) not in mapping]
        if len(members) >= 2 and sum(n for _, n in members) >= MIN_COUNT:
            best = max(((_cos(emb(tok), emb(t)), t) for t in vocab[fac]), default=(0, None))
            term = best[1] if best[0] >= SYNONYM else tok
            if term == tok and tok not in vocab[fac]:
                new_terms.setdefault(fac, []).append(tok)
            for w, _n in members:
                mapping[(fac, w)] = term
    report = {"specifics_seen": len(counts),
              "mapped_to_existing": {f"{f}:{w}": t for (f, w), t in mapping.items() if t != w},
              "new_terms": new_terms,
              "kept_as_specifics": {f"{f}:{w}": n for (f, w), n in counts.items() if (f, w) not in mapping}}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(counts)} distinct specifics; {len(report['mapped_to_existing'])} map to an existing term; "
          f"new terms: {json.dumps(new_terms)}; {len(report['kept_as_specifics'])} stay specifics")
    if not apply_:
        return
    for fac, ws in new_terms.items():
        vocab[fac] = vocab[fac] + [w for w in ws if w not in vocab[fac]]
    if "--lock" in sys.argv:
        tagfile["status"] = "locked"
    TAGS.write_text(json.dumps(tagfile, ensure_ascii=False, indent=2), encoding="utf-8")
    moved = 0
    for f in files():
        m = json.loads(f.read_text(encoding="utf-8"))
        for b in (m.get("beats") or []) + (m.get("cast") or []):
            if not isinstance(b, dict):
                continue
            keep = []
            for s in b.get("specifics") or []:
                fac, _, w = str(s).partition(":")
                w = re.sub(r"[^a-z0-9_]+", "_", w.strip().lower()).strip("_")
                t = mapping.get((fac, w))
                if t is None:
                    keep.append(s)
                    continue
                moved += 1
                if b in (m.get("cast") or []) and fac in ("purpose", "motive", "humor"):
                    b[fac] = sorted(set((b.get(fac) or []) + [t]))
                elif b in (m.get("cast") or []) and fac == "cast_role":
                    b["cast_role"] = b.get("cast_role") or t
                elif fac in BEAT_FACETS:
                    tg = b.setdefault("tags", {})
                    tg[fac] = sorted(set((tg.get(fac) or []) + [t]))
                else:
                    keep.append(s)
                    moved -= 1
            b["specifics"] = keep
        f.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"applied: {moved} specific(s) moved into tags; tag set {'locked' if '--lock' in sys.argv else 'still draft'}")


if __name__ == "__main__":
    main()
