"""
build_author_brain_local.py - the AUTHOR'S BRAIN of a corpus novel, built with Python + local semantic search (no cloud LLM).

Same output as build_author_brain.py (novels/<id>/author_brain.json, read by the app's Arc planner, Conspiracy and Timeline through
the knowledge index), built from what extraction already saved, joined by meaning:
  - ARCS: chapters grouped by their arc labels; near-duplicate labels ("Resource Competition" / "Blue Sea Town Resource Competition")
    are joined by embedding similarity. Each arc's promise and plan come from the author's own per-chapter intent (reader_effect,
    author_goal, arc_notes); the turn is the chapter where tension peaks; the payoff is how its last chapter closes.
  - THREADS: every fact the extraction recorded as hidden from someone (knowledge_state), clustered by meaning across chapters, so a
    secret mentioned in chapter 122 and again in 140, 143 and 145 becomes ONE thread with a seed, clue chapters and a last mention. The
    reveal that settles it is found by meaning among the reveals logged after the seed. Ranked by how long the secret was kept.
  - MILESTONES: fights (chapter mechanics), breakthroughs (power curve), reveals, thread clues, and the high-tension plot / character /
    place beats (timeline events), one or two per chapter, ranked by the reader-psychology peaks.
  - RHYTHM: measured from the above.
Embeddings: the chapter summaries and reveals already in knowledge_index.db are reused; secret facts and arc labels are embedded with
the local Ollama nomic-embed-text (cached in novels/<id>/author_brain/embed_cache.json).

The author-level writing (the engine, book shape, author rules, conspiracy craft, and each top thread's truth and misdirection) comes
from novels/<id>/author_brain/author_notes.json when present: notes written by an author (or Claude) from the digest this script
writes to novels/<id>/author_brain/digest.md.

Usage:
    python build_author_brain_local.py --novel my_novel
    python build_author_brain_local.py                # every novel
"""
import argparse
import hashlib
import json
import math
import re
import sqlite3
import statistics as st
import time
from collections import Counter
from pathlib import Path

import numpy as np

NOVELS_PATH = Path("novels")
DB = Path("knowledge_index.db")
SCHEMA = 1
CATEGORIES = ["fight", "breakthrough", "reveal", "clue", "plot", "character", "place", "personal"]
LABEL_JOIN = 0.80        # two consecutive arc labels this similar are the same arc
SECRET_JOIN = 0.83       # a secret fact this similar to a thread's centroid belongs to that thread
REVEAL_LINK = 0.78       # a later reveal must be at least this similar to a thread (and well above its baseline) to settle it
REVEAL_REACH = 80        # ...and logged no later than this many chapters after the thread's last mention
SCHEME_LINK = 0.80       # a scheme logged before the first mention this similar is where the thread really starts
CLUE_EXTRA = 4           # chapter summaries added as clues, the ones furthest above the thread's baseline...
CLUE_LIFT = 0.10         # ...and at least this far above it
GREP_BACK = 15           # a rare name first introduced up to this many chapters before a thread's first mention is its real seed
GREP_RARE = 0.12         # ...when it appears in no more than this share of chapters (a new element, not a main character)
GREP_COMMON = 0.25       # a name in more than this share of chapters (the hero, the main cast) is not distinctive
GREP_BOOST = 0.04        # a chapter whose summary names the thread's names ranks this much higher as a clue
_NAME = re.compile(r"\b[A-Z][a-z'’]+(?:[ -][A-Z][a-z'’]+){0,3}\b")
_STOP = {"The", "He", "She", "His", "Her", "They", "After", "When", "While", "With", "At", "In", "On", "As", "Meanwhile", "Then",
         "Chapter", "However", "Later", "Before", "During", "This", "That", "It", "A", "An", "One", "Two", "Three", "Both", "Despite"}
_KIND = {"identity": "identity", "ability": "power", "power": "power", "relationship": "romance", "conspiracy": "conspiracy",
         "plot": "conspiracy", "world": "world", "lore": "world", "secret": "mystery", "twist": "mystery"}


def load_json(p: Path, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def _cut(s, n: int) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _first_sentence(s: str, n: int = 260) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    m = re.match(r"(.+?[.!?])(\s|$)", s)
    return _cut(m.group(1) if m else s, n)


def _title(nid: str) -> str:
    t = (load_json(NOVELS_PATH / nid / "novel_metadata.json", {}) or {}).get("title") or ""
    return t if t and t != nid else nid.replace("_", " ").title()


def _deltas(nid: str) -> dict:
    out = {}
    for f in (NOVELS_PATH / nid / "deltas_v3").glob("ch*.json"):
        m = re.match(r"ch(\d+)\.json$", f.name)
        if m:
            d = load_json(f)
            if isinstance(d, dict) and d.get("summary"):
                out[int(m.group(1))] = d
    return out


# ── embeddings ──────────────────────────────────────────────────────────────────────────────────────────────────────
def _unit(v):
    v = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(v))
    return v / n if n else v


class Embedder:
    """Local nomic-embed-text with a per-novel cache, plus the vectors the knowledge index already holds."""
    def __init__(self, nid: str):
        self.path = NOVELS_PATH / nid / "author_brain" / "embed_cache.json"
        self.cache = load_json(self.path, {}) or {}
        self.dirty = False

    def many(self, texts: list) -> np.ndarray:
        from knowledge_index import embed_texts_batch, EMBED_MODEL
        keys = [hashlib.sha1(t.encode("utf-8")).hexdigest()[:20] for t in texts]
        todo = [(k, t) for k, t in zip(keys, texts) if k not in self.cache]
        for i in range(0, len(todo), 64):
            chunk = todo[i:i + 64]
            vecs = embed_texts_batch([t for _, t in chunk], EMBED_MODEL)
            for (k, _), v in zip(chunk, vecs):
                self.cache[k] = [round(float(x), 5) for x in v]
            self.dirty = True
        return np.stack([_unit(self.cache[k]) for k in keys]) if keys else np.zeros((0, 768), dtype=np.float32)

    def save(self):
        if self.dirty:
            save_json(self.path, self.cache)


def _index_vectors(nid: str, category: str) -> dict:
    """{chapter: [(text, unit vector)]} from knowledge_index.db (the extraction's own embeddings)."""
    out = {}
    if not DB.exists():
        return out
    con = sqlite3.connect(DB)
    try:
        for ch, text, blob in con.execute("SELECT chapter, text, embedding FROM chunks WHERE novel_id=? AND category=?", (nid, category)):
            if _int(ch) is None or not blob:                  # a few rows carry text in the chapter column
                continue
            out.setdefault(int(ch), []).append((text, _unit(np.frombuffer(blob, dtype=np.float32))))
    finally:
        con.close()
    return out


# ── arcs ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _norm_label(s: str) -> str:
    s = re.sub(r"^\s*arc\s*\d*\s*[:\-–]\s*", "", str(s or ""), flags=re.I).strip()
    return re.sub(r"\s+", " ", s)


def _tension(d: dict):
    rp = d.get("reader_psychology")
    tc = rp.get("tension_curve") if isinstance(rp, dict) else None
    return (_int(tc.get("peak")) or 0) if isinstance(tc, dict) else 0


def build_arcs(nid: str, deltas: dict, emb: Embedder) -> list:
    chs = sorted(deltas)
    labels = [_norm_label(deltas[c].get("arc_label_suggestion")) or "(untitled)" for c in chs]
    vecs = emb.many(labels)
    segs = []                                   # [first_index, last_index, [label indices]]
    for i, c in enumerate(chs):
        if segs:
            seg = segs[-1]
            centroid = _unit(vecs[seg[2]].mean(axis=0))
            same = float(vecs[i] @ centroid) >= LABEL_JOIN or labels[i].lower() == labels[seg[2][-1]].lower()
            if same or not deltas[c].get("arc_boundary_signal"):
                seg[1] = i
                seg[2].append(i)
                continue
        segs.append([i, i, [i]])
    # an arc of 1-2 chapters is a bridge, not an arc: it joins the arc it is most like (before or after)
    merged = []
    for s in segs:
        if merged and (s[1] - s[0] + 1) < 3:
            merged[-1][1] = s[1]
            merged[-1][2] += s[2]
        else:
            merged.append(s)
    if len(merged) > 1 and (merged[0][1] - merged[0][0] + 1) < 3:
        merged[1][0] = merged[0][0]
        merged[1][2] = merged[0][2] + merged[1][2]
        merged.pop(0)
    arcs = []
    for a, b, idx in merged:
        first, last = chs[a], chs[b]
        label = Counter(labels[i] for i in idx).most_common(1)[0][0]
        d0, d1 = deltas[first], deltas[last]
        ai0, ai1 = d0.get("author_intent"), d1.get("author_intent")
        ai0, ai1 = (ai0 if isinstance(ai0, dict) else {}), (ai1 if isinstance(ai1, dict) else {})
        span = [c for c in chs if first <= c <= last]
        peak = max(span, key=lambda c: _tension(deltas[c]))
        t0, tp = _tension(d0), _tension(deltas[peak])
        notes = next((deltas[c].get("arc_notes") for c in span if deltas[c].get("arc_boundary_signal") and deltas[c].get("arc_notes")), "")
        arcs.append({
            "chapters": [first, last], "label": _cut(label, 120),
            "promise": _cut(ai0.get("reader_effect") if isinstance(ai0, dict) else "", 400),
            "plan": _cut(" ".join(filter(None, [ai0.get("author_goal") if isinstance(ai0, dict) else "", notes])), 600),
            "escalation": f"Tension rises from {t0} at ch{first} to its peak of {tp} at ch{peak}." if tp and t0 else "",
            "turn": f"ch{peak}: {_first_sentence(deltas[peak].get('summary'))}",
            "payoff": _cut(" ".join(filter(None, [_first_sentence(d1.get('summary')), ai1.get("author_goal") if isinstance(ai1, dict) else ""])), 500),
            "cost": "", "seeds": []})
    return arcs


# ── threads ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def build_threads(nid: str, deltas: dict, emb: Embedder, summaries: dict, reveals: dict, schemes: dict = None) -> list:
    facts = []                                  # (chapter, fact, hidden_from, resolved)
    for c in sorted(deltas):
        for k in deltas[c].get("knowledge_state") or []:
            if isinstance(k, dict) and k.get("fact") and k.get("hidden_from"):
                est = _int(k.get("established_chapter")) or c
                hid = k["hidden_from"] if isinstance(k["hidden_from"], list) else [k["hidden_from"]]
                facts.append((min(est, c), _cut(k["fact"], 300), ", ".join(map(str, hid))[:120], _int(k.get("resolved_chapter"))))
    if not facts:
        return []
    vecs = emb.many([f[1] for f in facts])
    clusters = []                               # {"idx": [...], "sum": vector}
    for i in sorted(range(len(facts)), key=lambda i: facts[i][0]):
        best, score = None, SECRET_JOIN
        for cl in clusters:
            s = float(vecs[i] @ _unit(cl["sum"]))
            if s >= score:
                best, score = cl, s
        if best is None:
            clusters.append({"idx": [i], "sum": vecs[i].copy()})
        else:
            best["idx"].append(i)
            best["sum"] += vecs[i]
    rev_rows = [(c, t, v) for c, rows in reveals.items() for t, v in rows]
    sum_rows = [(c, t, v) for c, rows in summaries.items() for t, v in rows]
    scheme_rows = [(c, t, v) for c, rows in (schemes or {}).items() for t, v in rows]
    # every name in the chapter summaries -> the chapters it appears in (for the grep side of the linking)
    name_chs = {}
    for c in sorted(deltas):
        for n in set(_NAME.findall(str(deltas[c].get("summary") or ""))):
            name_chs.setdefault(n, []).append(c)
    common = {n for n, cs in name_chs.items() if len(cs) > len(deltas) * GREP_COMMON} | _STOP
    # the hero under every word order ("Kai Yang" / "Yang Kai"): any name made of the same words as the most frequent name
    if name_chs:
        hero = set(max(name_chs, key=lambda n: len(name_chs[n])).split())
        common |= {n for n in name_chs if set(n.split()) == hero or (set(n.split()) & hero and len(n.split()) <= 2)}
    threads = []
    for cl in clusters:
        idx = sorted(cl["idx"], key=lambda i: facts[i][0])
        cen = _unit(cl["sum"])
        seed = facts[idx[0]][0]
        mentions = sorted({facts[i][0] for i in idx})
        resolved = max([facts[i][3] for i in idx if facts[i][3]] or [0]) or None
        # Similarity is judged against this thread's own baseline (every summary mentions the hero, so raw scores run high and
        # differ by thread): a link must stand clear of the median score of all the novel's summaries for this thread.
        base = float(np.median([float(v @ cen) for _, _, v in sum_rows])) if sum_rows else 0.6
        # where the scheme behind it really starts: a scheme logged before the first mention that is clearly about it
        sc = max(((float(v @ cen), c) for c, t, v in scheme_rows if c < seed), default=None)
        if sc and sc[0] >= max(SCHEME_LINK, base + 0.15):
            seed = sc[1]
        # names are exact where meaning is fuzzy: the thread's distinctive names (not the hero, not anyone in a quarter of the
        # chapters) grepped in the summaries; if they turn up shortly before the seed, that is where the thread starts
        names = {n for i in idx for n in _NAME.findall(facts[i][1]) if n in name_chs and n not in common}
        named = sorted({c for n in names for c in name_chs[n]})
        intro = [name_chs[n][0] for n in names if len(name_chs[n]) <= len(deltas) * GREP_RARE]
        early = [c for c in intro if seed - GREP_BACK <= c < seed]
        if early:
            seed = min(early)
        # the reveal that settles it: the best reveal logged 3+ chapters after the seed and within reach of the last mention
        rv = max(((float(v @ cen), c, t) for c, t, v in rev_rows if seed + 3 <= c <= max(mentions) + REVEAL_REACH), default=None)
        reveal_ch, how = None, ""
        if rv and rv[0] >= max(REVEAL_LINK, base + 0.14):
            reveal_ch, how = rv[1], rv[2]
        elif resolved and resolved >= seed + 3:
            reveal_ch = resolved
        end = reveal_ch or max(mentions)
        # clue chapters: up to four mentions spread over the thread, plus the few chapter summaries between seed and reveal that
        # stand furthest above the baseline
        spread = mentions if len(mentions) <= 4 else [mentions[round(k * (len(mentions) - 1) / 3)] for k in range(4)]
        clue_ch = {m: facts[next(i for i in idx if facts[i][0] == m)][1] for m in spread if m != reveal_ch}
        named_set = set(named)
        near = sorted(((float(v @ cen) + (GREP_BOOST if c in named_set else 0), c, t) for c, t, v in sum_rows
                       if seed < c < end and c not in clue_ch), reverse=True)
        for s, c, t in near[:CLUE_EXTRA]:
            if s >= base + CLUE_LIFT:
                clue_ch[c] = _first_sentence(t, 220)
        kind = _KIND.get(str(how.split(":", 1)[0]).replace("_reveal", "").strip(), "mystery") if how else "mystery"
        life = (end - seed) if end else 0
        if life < 5 and len(mentions) < 3:
            continue                                         # a passing secret, not a thread
        first_fact = facts[idx[0]]
        threads.append({
            "name": _cut(first_fact[1], 80), "kind": kind, "truth": first_fact[1],
            "hidden_from": first_fact[2], "seeded_chapter": seed,
            "clues": [{"chapter": c, "reader_sees": _cut(t, 260)} for c, t in sorted(clue_ch.items())[:10]],
            "misdirection": "", "reveal_chapter": reveal_ch, "how_revealed": _cut(how, 400), "payoff_effect": "",
            "mentions": len(idx), "kept_chapters": life,
            "_score": life * math.log(1 + len(idx)) * (1.3 if reveal_ch else 1.0)})
    threads.sort(key=lambda t: -t["_score"])
    for i, t in enumerate(threads):
        t["id"] = f"t{i + 1}"
        t.pop("_score", None)
    return threads[:16]


# ── milestones ──────────────────────────────────────────────────────────────────────────────────────────────────────
_BREAK = re.compile(r"\b(break(s|ing)? ?through|breakthrough|advanc\w+ to|reach(es|ed)? (the )?\w+ (realm|level|rank)|level(s|ed)? up|evolv\w+|realm)\b", re.I)
_PLACE = re.compile(r"\b(arriv\w+|enter\w*|travel\w*|journey|leave[s]? for|reach(es|ed)? the)\b", re.I)
_PERSONAL = re.compile(r"\b(famil\w+|mother|father|sister|brother|love|kiss|grave|mourn|reunit\w+|friend\w*)\b", re.I)


def build_milestones(deltas: dict, threads: list) -> list:
    cands = []                                  # (rank, chapter, category, title, mc_sees)
    clue_at = {}
    for t in threads[:8]:
        for c in t["clues"]:
            clue_at.setdefault(c["chapter"], (t["name"], c["reader_sees"]))
    for c in sorted(deltas):
        d = deltas[c]
        psych = d.get("reader_psychology") if isinstance(d.get("reader_psychology"), dict) else {}
        peak = _tension(d)
        pc_ = psych.get("payoff_categories")
        pay = max([v for v in (pc_.values() if isinstance(pc_, dict) else []) if isinstance(v, (int, float))] or [0])
        base = peak / 10 + pay
        mech = d.get("mechanics") if isinstance(d.get("mechanics"), dict) else {}
        fights = mech.get("fights") or []
        if fights and isinstance(fights[0], dict):
            opp = ", ".join(map(str, (fights[0].get("opponents") or [])[:3]))
            blow = ((fights[0].get("exchanges") or [{}])[0] or {}).get("blow") or ""
            cands.append((base + 3, c, "fight", _cut(f"Fight: {opp}" if opp else "A fight", 110), _cut(blow, 240)))
        pc = d.get("power_curve_notes") or {}
        pat = pc.get("pattern") if isinstance(pc, dict) else ""
        if pat and _BREAK.search(pat):
            cands.append((base + 2.5, c, "breakthrough", _cut(_first_sentence(pat, 110), 110), _cut(pat, 240)))
        for r in d.get("reveals") or []:
            if isinstance(r, dict) and r.get("content") and str(r.get("reveal_type", "")).replace("_reveal", "") in ("identity", "plot", "secret", "twist", "world", "lore"):
                cands.append((base + 2, c, "reveal", _cut(_first_sentence(r["content"], 110), 110), _cut(r["content"], 240)))
                break
        if c in clue_at:
            cands.append((base + 1.5, c, "clue", _cut(clue_at[c][0], 110), clue_at[c][1]))
        for ev in (d.get("timeline_events") or [])[:4]:
            if not isinstance(ev, dict) or not ev.get("event"):
                continue
            txt = str(ev["event"])
            cat = "place" if _PLACE.search(txt) else "personal" if _PERSONAL.search(txt) else "character" if "relationship" in str(ev.get("stakes", "")).lower() else "plot"
            cands.append((base + (1 if cat != "plot" else 0.5), c, cat, _cut(txt, 110), _cut(ev.get("stakes"), 200)))
    # one or two per chapter, then the strongest ~16 of every 40 chapters
    per_ch = {}
    for r in sorted(cands, key=lambda r: -r[0]):
        per_ch.setdefault(r[1], [])
        if len(per_ch[r[1]]) < 2 and all(x[2] != r[2] for x in per_ch[r[1]]):
            per_ch[r[1]].append(r)
    out = []
    for w in range(1, (max(deltas) if deltas else 0) + 1, 40):
        rows = [r for c, rs in per_ch.items() if w <= c < w + 40 for r in rs]
        rows = sorted(rows, key=lambda r: -r[0])[:16]
        out += [{"chapter": c, "category": cat, "title": t, "mc_sees": s} for _, c, cat, t, s in sorted(rows, key=lambda r: r[1])]
    return out


def _rhythm(arcs, milestones, threads, last) -> dict:
    lens = [a["chapters"][1] - a["chapters"][0] + 1 for a in arcs]
    gaps = [t["reveal_chapter"] - t["seeded_chapter"] for t in threads if t.get("reveal_chapter")]
    return {"arc_length_median": st.median(lens) if lens else None, "arc_length_range": [min(lens), max(lens)] if lens else None,
            "reveal_gap_median": st.median(gaps) if gaps else None, "reveal_gap_max": max(gaps) if gaps else None,
            "threads_open": sum(1 for t in threads if not t.get("reveal_chapter")),
            "milestones_per_20_chapters": {c: round(sum(1 for m in milestones if m["category"] == c) * 20 / max(1, last), 1) for c in CATEGORIES}}


# ── the author's notes (written from the digest) ────────────────────────────────────────────────────────────────────
def apply_notes(brain: dict, notes: dict) -> dict:
    if not isinstance(notes, dict):
        return brain
    for k in ("engine", "book_shape"):
        if notes.get(k):
            brain[k] = _cut(notes[k], 1400)
    for k in ("author_rules", "conspiracy_craft"):
        if notes.get(k):
            brain[k] = [_cut(x, 320) for x in notes[k] if x][:14]
    by_id = {t["id"]: t for t in brain["threads"]}
    for tid, upd in (notes.get("threads") or {}).items():
        t = by_id.get(tid)
        if t and isinstance(upd, dict):
            for k in ("name", "kind", "truth", "misdirection", "payoff_effect", "how_revealed"):
                if upd.get(k):
                    t[k] = _cut(upd[k], 700)
            if upd.get("drop"):
                brain["threads"].remove(t)
    # threads the author knows of that the Python pass missed (found by searching the summaries / reveals), placed first
    added = []
    for i, t in enumerate(notes.get("add_threads") or []):
        if isinstance(t, dict) and t.get("name") and t.get("truth"):
            added.append({"id": f"a{i + 1}", "name": _cut(t["name"], 100), "kind": _cut(t.get("kind") or "mystery", 30), "truth": _cut(t["truth"], 700),
                          "hidden_from": _cut(t.get("hidden_from"), 120), "seeded_chapter": _int(t.get("seeded_chapter")),
                          "clues": [{"chapter": _int(c.get("chapter")), "reader_sees": _cut(c.get("reader_sees"), 260)}
                                    for c in (t.get("clues") or []) if isinstance(c, dict) and c.get("reader_sees")][:10],
                          "misdirection": _cut(t.get("misdirection"), 500), "reveal_chapter": _int(t.get("reveal_chapter")),
                          "how_revealed": _cut(t.get("how_revealed"), 500), "payoff_effect": _cut(t.get("payoff_effect"), 500),
                          "mentions": len(t.get("clues") or []), "kept_chapters": (_int(t.get("reveal_chapter")) or 0) - (_int(t.get("seeded_chapter")) or 0)})
    if added:
        brain["threads"] = added + brain["threads"]
    for key, upd in (notes.get("arcs") or {}).items():
        for a in brain["arcs"]:
            if f"{a['chapters'][0]}-{a['chapters'][1]}" == key and isinstance(upd, dict):
                for k in ("label", "promise", "plan", "escalation", "turn", "payoff", "cost"):
                    if upd.get(k):
                        a[k] = _cut(upd[k], 700)
    brain["notes_by"] = notes.get("by") or "author notes"
    return brain


def digest(brain: dict) -> str:
    out = [f"# {brain['title']} — author brain digest (chapters {brain['chapters_covered'][0]}-{brain['chapters_covered'][1]})", "",
           f"Rolling summary: {brain.get('_rolling', '')}", "", "## Arcs"]
    for a in brain["arcs"]:
        out.append(f"- ch{a['chapters'][0]}-{a['chapters'][1]} {a['label']} | promise: {_cut(a['promise'], 160)} | turn: {_cut(a['turn'], 160)}")
    out += ["", "## Threads (id: seed -> reveal, kept chapters, mentions)"]
    for t in brain["threads"]:
        clues = "; ".join(f"ch{c['chapter']}: {_cut(c['reader_sees'], 90)}" for c in t["clues"][:5])
        out.append(f"- {t['id']}: ch{t['seeded_chapter']} -> {('ch' + str(t['reveal_chapter'])) if t['reveal_chapter'] else 'open'} "
                   f"({t['kept_chapters']} ch, {t['mentions']} mentions; hidden from {t.get('hidden_from', '')}) {t['truth']}"
                   + (f" | REVEAL: {_cut(t['how_revealed'], 200)}" if t["how_revealed"] else "") + f"\n    clues: {clues}")
    r = brain["rhythm"]
    out += ["", f"## Rhythm: arcs median {r['arc_length_median']} ch; reveal gap median {r['reveal_gap_median']}; per 20 ch: {r['milestones_per_20_chapters']}"]
    return "\n".join(out)


def build(nid: str) -> dict:
    deltas = _deltas(nid)
    if len(deltas) < 20:
        print(f"[SKIP] {nid}: only {len(deltas)} extracted chapters")
        return {}
    t0 = time.time()
    emb = Embedder(nid)
    summaries, reveals, schemes = _index_vectors(nid, "summary"), _index_vectors(nid, "reveal"), _index_vectors(nid, "scheme")
    arcs = build_arcs(nid, deltas, emb)
    threads = build_threads(nid, deltas, emb, summaries, reveals, schemes)
    emb.save()
    for t in threads:                                        # each arc lists the threads seeded inside it
        for a in arcs:
            if a["chapters"][0] <= t["seeded_chapter"] <= a["chapters"][1]:
                a["seeds"].append({"chapter": t["seeded_chapter"], "thread": t["name"], "what": _cut(t["truth"], 240)})
    milestones = build_milestones(deltas, threads)
    last = max(deltas)
    rolling = (load_json(NOVELS_PATH / nid / "rolling_summary.json", {}) or {}).get("summary") or ""
    brain = {"schema_version": SCHEMA, "method": "local (python + semantic)", "novel_id": nid, "title": _title(nid),
             "chapters_covered": [min(deltas), last], "source_chapter_count": len(deltas), "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "engine": "", "book_shape": "", "author_rules": [], "conspiracy_craft": [],
             "arcs": arcs, "threads": threads, "milestones": milestones, "rhythm": _rhythm(arcs, milestones, threads, last)}
    brain["_rolling"] = rolling
    wd = NOVELS_PATH / nid / "author_brain"
    (wd).mkdir(parents=True, exist_ok=True)
    (wd / "digest.md").write_text(digest(brain), encoding="utf-8")
    brain.pop("_rolling", None)
    brain = apply_notes(brain, load_json(wd / "author_notes.json"))
    save_json(NOVELS_PATH / nid / "author_brain.json", brain)
    print(f"[OK] {nid}: {len(arcs)} arcs, {len(threads)} threads ({sum(1 for t in threads if t['reveal_chapter'])} with a reveal), "
          f"{len(milestones)} milestones in {time.time() - t0:.0f}s" + ("  + author notes" if brain.get("notes_by") else "  (no author notes yet)"), flush=True)
    return brain


def main():
    ap = argparse.ArgumentParser(description="Build the author's brain of corpus novels with Python + local semantic search")
    ap.add_argument("--novel", help="one novel id (omit for every novel)")
    args = ap.parse_args()
    novels = [args.novel] if args.novel else [p.name for p in sorted(NOVELS_PATH.iterdir()) if p.is_dir()]
    for n in novels:
        try:
            build(n)
        except Exception as e:
            print(f"[ERROR] {n}: {type(e).__name__}: {str(e)[:200]}", flush=True)


if __name__ == "__main__":
    main()
