"""
Reference mechanics — the Chapter Mechanics delta (corpus/build_mechanics_deltas.py) put to work.

When the Author DNA tab's "Plan from this novel's corpus data and raws" is ticked, the book's voice-source novel (e.g.
a reference novel) becomes a construction reference at every level, each seeing what it needs:
  - arcs:      how the reference paces its set-piece runs over the same chapter span (types, lengths, gaps);
  - skeletons: the matching reference chapters' beat order, each beat's MEANING / purpose / motive, the measured
               proportions (words before / in / after a fight, spoken share), fight talk rhythm and cast roles —
               never quotes, names or events;
  - writer:    the reference beats' exact QUOTES for the roles this chapter's plan uses, to hear the rhythm (not to copy).
It sits at the bottom of the canon order — conspiracy tree > timeline > arc > skeleton > chapter — so it only shapes how
a chapter is built, never what happens in it.

Also served to the app (router /api/reference): mechanics search with novel / chapter / kind filters for the Timeline,
Cast and Foes tabs, and the raw passage around any quote.
"""
import json
import os
import re
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


def _G():
    from routers.generation import generate
    return generate


class _Paths:
    """CORPUS_PATH comes from generate (resolved at runtime, same as the other routers)."""
    @property
    def corpus(self):
        return _G().CORPUS_PATH


_P = _Paths()


# ── data access ───────────────────────────────────────────────────────────────────────────────────────────────
def _prof(project: dict) -> dict:
    return (project or {}).get("author_profile") or {}


def reference_scope(project: dict) -> str:
    """"corpus": plan from every corpus novel's mechanics (the chosen novel ranked first); "novel": the chosen novel(s) only."""
    return "corpus" if _prof(project).get("reference_scope") == "corpus" else "novel"


def _core():
    """corpus/mechanics_core.py (the corpus folder is the backend's working data folder)."""
    import sys
    p = str(_P.corpus)
    if p not in sys.path:
        sys.path.insert(0, p)
    import mechanics_core
    return mechanics_core


def _has_any_mechanics(novel: str) -> bool:
    """Does this novel have mechanics: a sidecar folder, or any delta already marked schema 4.0 (checked on a few files)."""
    if (_P.corpus / "novels" / novel / "deltas_mechanics").is_dir():
        return True
    d = _P.corpus / "novels" / novel / "deltas_v3"
    try:
        core = _core()
        for name in sorted(os.listdir(d))[:400]:
            m = core.CH_FILE.match(name)
            if m and core.has_mechanics(novel, int(m.group(1))):
                return True
    except Exception:
        pass
    return False


def _with_mechanics(novels) -> list:
    return [n for n in novels if _has_any_mechanics(n)]


def primary_novels(project: dict) -> list:
    """The novels chosen in Author DNA (voice source), when 'plan from this novel' is ticked and they have mechanics."""
    prof = _prof(project)
    if not prof.get("reference_plans"):
        return []
    vs = prof.get("voice_source") or {}
    if vs.get("mode") not in ("novel", "mix"):
        return []
    return _with_mechanics(vs.get("novels") or [])


def reference_novels(project: dict) -> list:
    """Every novel this plan may draw on, best-anchored first: the chosen novel(s), then — in "corpus" scope — all the
    others that have mechanics. [] when the Author DNA checkbox is off (or, in "novel" scope, no novel is chosen)."""
    if not _prof(project).get("reference_plans"):
        return []
    prim = primary_novels(project)
    if reference_scope(project) != "corpus":
        return prim
    nd = _P.corpus / "novels"
    allnov = sorted(d.name for d in nd.iterdir() if d.is_dir() and _has_any_mechanics(d.name)) if nd.is_dir() else []
    return prim + [n for n in allnov if n not in prim]


def mechanics(novel: str, ch: int) -> Optional[dict]:
    """One chapter's mechanics: the copy inside its delta (V4) first, else the old sidecar file."""
    try:
        return _core().load_mechanics(novel, int(ch))
    except Exception:
        return None


def runs(novel: str) -> list:
    try:
        return json.loads((_P.corpus / "novels" / novel / "set_pieces" / "runs.json").read_text(encoding="utf-8")) or []
    except Exception:
        return []


def _title(novel: str) -> str:
    try:
        return json.loads((_P.corpus / "novels" / novel / "novel_metadata.json").read_text(encoding="utf-8")).get("title") or novel
    except Exception:
        return novel.replace("_", " ").title()


def search(query: str, top_k: int = 8, novel: str = None, kind: str = None, chapter_from: int = None,
           chapter_to: int = None, current_chapter: int = None) -> list:
    """Mechanics chunks (opt-in category) by meaning, filtered before ranking."""
    from routers.corpus_tools.corpus import knowledge_search
    hits = knowledge_search(query, top_k=max(top_k * 4 if kind else top_k, 8), category="mechanics", novel_id=novel,
                            chapter_from=chapter_from, chapter_to=chapter_to, current_chapter=current_chapter) or []
    if kind:
        hits = [h for h in hits if (h.get("meta") or {}).get("kind") == kind]
    return hits[:top_k]


def find_reference_chapters(project: dict, ch: int, query: str, k: int = None) -> list:
    """[(novel, chapter)] for this chapter's job. "novel" scope: in the chosen novel, the best match by meaning, then the
    best near this chapter's place in the book. "corpus" scope: the best match by meaning across ALL corpus novels, then
    the best in the chosen novel (the author's voice anchor), then the best at a similar stage from a novel not yet used.
    Whole-chapter, fight and run records rank before single beats, which can match on a side detail."""
    rank = {"chapter": 0, "run": 0, "fight": 1}

    def ordered(hits):
        return sorted(hits, key=lambda h: (rank.get((h.get("meta") or {}).get("kind"), 2), -(h.get("score") or 0)))

    def first_new(pool, out, avoid=(), same_type=None):
        for h in ordered(pool):
            nv, c = h.get("novel_id"), h.get("chapter")
            if nv and isinstance(c, int) and (nv, c) not in out and nv not in avoid:
                m = mechanics(nv, c)
                if m and (not same_type or m.get("chapter_type") == same_type):
                    return (nv, c)
        return None
    out: list = []
    if reference_scope(project) == "corpus" and reference_novels(project):
        everywhere = search(query, top_k=60)
        stage = search(query, top_k=60, current_chapter=ch)
        p1 = first_new(everywhere, out)
        if p1:
            out.append(p1)
        for nv in primary_novels(project)[:1]:
            p2 = first_new(search(query, top_k=30, novel=nv), out)
            if p2:
                out.append(p2)
        used = {n for n, _ in out}
        kind = (mechanics(*out[0]) or {}).get("chapter_type") if out else None      # keep the third pick the same kind of chapter
        p3 = first_new(stage, out, avoid=used, same_type=kind) or first_new(stage, out, same_type=kind) or first_new(stage, out, avoid=used)
        if p3:
            out.append(p3)
        return out[:k or 3]
    for nv in reference_novels(project):
        for pool in (search(query, top_k=30, novel=nv), search(query, top_k=30, novel=nv, current_chapter=ch)):
            p = first_new(pool, out)
            if p:
                out.append(p)
    return out[:k or 2]


def _run_of(novel: str, ch: int) -> Optional[dict]:
    return next((r for r in runs(novel) if ch in (r.get("chapters") or [])), None)


_CHAPTER_TYPES = ("fight", "run_up", "set_up", "fallout", "reveal", "comedy", "cultivation", "breakthrough", "alchemy", "auction_or_trade", "contest", "travel", "romance", "scheme", "celebration", "training", "daily_life", "recruitment", "healing", "mixed")


# ── what each level sees ───────────────────────────────────────────────────────────────────────────────────────
def _tags(t) -> str:
    return "; ".join(f"{f} {', '.join(v)}" for f, v in (t or {}).items()) if isinstance(t, dict) else ""


def _planner_view(novel: str, ch: int, cap: int = 3000) -> str:
    m = mechanics(novel, ch) or {}
    ms = m.get("measured") or {}
    run = _run_of(novel, ch)
    ctype = m.get("chapter_type") if m.get("chapter_type") in _CHAPTER_TYPES else "mixed"
    lines = [f"REFERENCE: {_title(novel)} chapter {ch} ({ctype})"]
    if run:
        roles = ", ".join(f"ch{x['chapter']} {x.get('role')}" for x in run.get("roles") or [])
        lines.append(f"  part of a {run.get('set_piece_type')} run over {len(run.get('chapters') or [])} chapter(s): {roles}")
    op, en = m.get("opening") or {}, m.get("ending") or {}
    lines.append(f"  opens {op.get('kind')}{' (continues the previous chapter)' if op.get('continues_previous_chapter') else ''}; "
                 f"ends {en.get('kind')}{' (carries into the next)' if en.get('carries_into_next_chapter') else ''}")
    if ms:
        fight = (f"; {ms.get('words_before_first_fight')} words before the first blow, {ms.get('words_in_fights')} in the fight, "
                 f"{ms.get('words_after_last_fight')} after" if ms.get("fight_passages") else "")
        lines.append(f"  measured: {ms.get('words')} words, spoken share {round((ms.get('spoken_share') or 0) * 100)}%{fight}")
    for i, s in enumerate(m.get("scenes") or [], 1):
        if isinstance(s, dict):
            lines.append(f"  scene {i}: joins {s.get('join_from_previous')}; {s.get('purpose') or ''}")
    for i, b in enumerate(m.get("beats") or [], 1):
        if isinstance(b, dict):
            lines.append(f"  beat {i} {b.get('role')} (driver {b.get('driver')}): {b.get('meaning') or ''}"
                         + (f" [{_tags(b.get('tags'))}]" if b.get("tags") else ""))
    for f in m.get("fights") or []:
        talk = [" > ".join(t.get("role", "?") for t in (ex.get("talk") or [])) or "(no talk)"
                for ex in (f.get("exchanges") or []) if isinstance(ex, dict)]
        lines.append(f"  fight: {len(talk)} exchanges, talk per exchange: {' | '.join(talk)}; "
                     f"escalation: {'; '.join(f.get('escalation') or [])}; ends mid-fight: {bool(f.get('ends_chapter_mid_fight'))}")
    for c in m.get("cast") or []:
        if isinstance(c, dict):
            lines.append(f"  cast {c.get('cast_role')}: {c.get('in_this_chapter') or ''} "
                         f"(purpose {', '.join(c.get('purpose') or []) or '-'}; motive {', '.join(c.get('motive') or []) or '-'})")
    r = m.get("run") or {}
    if r.get("run_up_moves"):
        lines.append(f"  run-up moves in order: {', '.join(r['run_up_moves'])}")
    return "\n".join(lines)[:cap]


def skeleton_block(project: dict, ch: int, query: str) -> tuple:
    """(prompt block, [(novel, chapter)]) for chapter planning; ("", []) when the checkbox is off or nothing matches."""
    picks = find_reference_chapters(project, ch, query)
    if not picks:
        return "", []
    whole = reference_scope(project) == "corpus"
    head = ("━━ REFERENCE CONSTRUCTION (" + ("from the corpus: the best matches across all novels, the author's chosen novel included"
            if whole else "from the author's chosen novel") + "; the lowest authority: the conspiracy tree, the "
            "timeline and the arc contract above all win) ━━\n"
            "Model HOW this chapter is built on these reference chapters: their beat order, how long the run-up is "
            "against the fight, how scenes join, the talk between blows, what each beat is FOR (meaning, purpose, "
            "motive). Adapt every move to this story. Never borrow names, places, techniques, items or events.\n"
            "Also record in the plan: \"reference_chapters\": [{\"novel\", \"chapter\", \"why\"}]; on every scene "
            "\"follows_from\": how it joins the scene before (continuous / same place later / ...), never a jump cut; "
            "when the chapter has a fight, \"fight_plan\": {\"opponent\", \"first_named_in_chapter\", \"run_up_moves\": [...], "
            "\"talk_per_exchange\": \"who says what kind of line between blows\", \"ends_mid_fight\": true/false}; and "
            "\"plants_for_later\": [names, threats or questions this chapter sets up for a later set piece].")
    body = "\n\n".join(_planner_view(nv, c, cap=2600 if len(picks) > 2 else 3000) for nv, c in picks)
    return head + "\n\n" + body, picks


def writer_block(project: dict, ch: int, sk: Optional[dict], cap: int = 3200) -> str:
    """Exact reference lines for the beat roles this chapter's plan uses, so the writer hears the rhythm."""
    if not reference_novels(project):
        return ""
    picks = []
    for r in (sk or {}).get("reference_chapters") or []:
        if isinstance(r, dict) and r.get("novel") and isinstance(r.get("chapter"), int):
            picks.append((r["novel"], r["chapter"]))
    if not picks:
        q = " ".join(str((sk or {}).get(k) or "") for k in ("purpose", "key_event")).strip()
        picks = find_reference_chapters(project, ch, q) if q else []
    lines = []
    for nv, c in picks[:2]:
        m = mechanics(nv, c) or {}
        for b in m.get("beats") or []:
            qs = [q for q in (b.get("quotes") or []) if isinstance(q, str)] if isinstance(b, dict) else []
            if qs:
                lines.append(f"- {b.get('role')} ({b.get('meaning') or ''}): " + " / ".join(f'"{q}"' for q in qs[:2]))
        for f in m.get("fights") or []:
            for ex in f.get("exchanges") or []:
                for t in (ex.get("talk") or [])[:3] if isinstance(ex, dict) else []:
                    lines.append(f"- in the fight, {t.get('role')}: \"{t.get('quote')}\"")
    if not lines:
        return ""
    names = ", ".join(sorted({_title(nv) for nv, _ in picks}))
    return (f"HOW THE REFERENCE SOUNDS ({names}) — real lines from the beats this chapter's plan models. Hear their rhythm, "
            f"bite and length; never copy a line, a name or an event:\n" + "\n".join(lines))[:cap]


def arc_block(project: dict, first: int, last: int, cap: int = 2600) -> str:
    """How the reference paces set-piece runs over the same chapter span."""
    out = []
    for nv in (primary_novels(project) or reference_novels(project)[:3]):      # the chosen novel's pacing (else a few corpus novels)
        rs = [r for r in runs(nv) if r.get("chapters") and first <= r["chapters"][0] <= last]
        if not rs:
            continue
        rows = [f"  ch {r['chapters'][0]}-{r['chapters'][-1]}: {r.get('set_piece_type')}"
                + (f" vs {', '.join(r.get('opponents') or [])}" if r.get("opponents") else "")
                + f" ({', '.join(str(x.get('role')) for x in r.get('roles') or [])})" for r in rs]
        out.append(f"{_title(nv)}, chapters {first}-{last}: {len(rs)} set-piece runs\n" + "\n".join(rows[:30]))
    if not out:
        return ""
    return ("REFERENCE PACING (the chosen reference novel over the same chapter span; follow its rhythm of set pieces — "
            "how often a run starts, how many chapters each spans, what sits between — never its events):\n"
            + "\n\n".join(out))[:cap]


_JUMP = re.compile(r"\b(meanwhile|at the same time|elsewhere|on the other side)\b", re.I)


def shape_warnings(project: dict, sk: dict) -> list:
    """Non-blocking notes on a plan made with the reference on (prefix 'Reference shape', never a gate)."""
    if not reference_novels(project) or not isinstance(sk, dict):
        return []
    w = []
    scenes = [s for s in (sk.get("scenes") or []) if isinstance(s, dict)]
    for i, s in enumerate(scenes[1:], 2):
        ff = str(s.get("follows_from") or "")
        if not ff:
            w.append(f"Reference shape — scene {i} does not say how it follows from scene {i - 1}")
        elif _JUMP.search(ff):
            w.append(f"Reference shape — scene {i} is a jump cut ('{ff[:60]}')")
    fights = [i for i, s in enumerate(scenes) if str(s.get("scene_type")) in ("action", "combat")]
    if fights:
        fp = sk.get("fight_plan") if isinstance(sk.get("fight_plan"), dict) else None
        if not fp:
            w.append("Reference shape — a fight is planned but there is no fight_plan (opponent, run-up moves, talk between blows)")
        before = sum(int(s.get("estimated_word_count") or 0) for s in scenes[:fights[0]])
        during = sum(int(scenes[i].get("estimated_word_count") or 0) for i in fights)
        carried = bool(fp and fp.get("first_named_in_chapter") and int(fp.get("first_named_in_chapter") or 0) < int(sk.get("number") or 0))
        if during > before and not carried:
            w.append(f"Reference shape — the fight ({during} words) runs longer than its build-up ({before}); the reference "
                     f"builds up first unless the run-up was in an earlier chapter")
    return w


# ── app endpoints ──────────────────────────────────────────────────────────────────────────────────────────────
class SearchRequest(BaseModel):
    query: str
    top_k: int = 10
    novel_id: Optional[str] = None
    kind: Optional[str] = None            # chapter | beat | fight | run | cast | device
    chapter_from: Optional[int] = None
    chapter_to: Optional[int] = None


@router.post("/search")
def search_endpoint(req: SearchRequest):
    if not req.query.strip():
        raise HTTPException(400, "query is required.")
    hits = search(req.query.strip(), top_k=max(1, min(req.top_k, 40)), novel=req.novel_id or None, kind=req.kind or None,
                  chapter_from=req.chapter_from, chapter_to=req.chapter_to)
    for h in hits:
        h["novel_title"] = _title(h.get("novel_id") or "")
    return {"results": hits}


def _paras(raw: str) -> list:
    return [p.strip() for p in re.split(r"\n\s*\n|\n", raw or "") if p.strip()]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


@router.get("/raw-context")
def raw_context(novel: str, chapter: int, quote: str = "", around: int = 3):
    """The raw paragraphs around a quote (or the chapter's opening when no quote is given / found)."""
    p = _P.corpus / "raw" / novel / f"ch{int(chapter)}.txt"
    if not p.exists() or "/" in novel or "\\" in novel or ".." in novel:
        raise HTTPException(404, "No raw text for that chapter.")
    paras = _paras(p.read_text(encoding="utf-8", errors="ignore"))
    q = _norm(quote)[:80]
    at = next((i for i, x in enumerate(paras) if q and q in _norm(x)), None)
    if at is None and q:
        q = _norm(quote)[:30]
        at = next((i for i, x in enumerate(paras) if q and q in _norm(x)), None)
    lo = max(0, (at if at is not None else 0) - around)
    hi = min(len(paras), (at if at is not None else 0) + around + 1)
    return {"novel_id": novel, "novel_title": _title(novel), "chapter": chapter, "found": at is not None,
            "paragraphs": [{"index": i + 1, "text": paras[i], "hit": i == at} for i in range(lo, hi)], "total": len(paras)}


class TimelineRefRequest(BaseModel):
    project_id: str
    chapter: int
    title: str = ""
    text: str = ""


@router.post("/timeline-event")
def timeline_event_reference(req: TimelineRefRequest):
    """How the reference novel(s) — or the whole corpus when none is chosen — runs a moment like this timeline event."""
    pf = _P.corpus / "projects" / req.project_id / "project.json"
    if not pf.exists():
        raise HTTPException(404, "Project not found")
    project = json.loads(pf.read_text(encoding="utf-8"))
    vs = ((project.get("author_profile") or {}).get("voice_source") or {})
    novels = [None] if reference_scope(project) == "corpus" else (vs.get("novels") if vs.get("mode") in ("novel", "mix") else [None])
    q = f"{req.title}. {req.text}".strip()[:900]
    out = []
    for nv in novels or [None]:
        for h in search(q, top_k=6, novel=nv, current_chapter=req.chapter):
            m = (h.get("meta") or {})
            h["novel_title"] = _title(h.get("novel_id") or "")
            run = _run_of(h["novel_id"], h["chapter"]) if isinstance(h.get("chapter"), int) else None
            h["run"] = run
            h["kind"] = m.get("kind")
            out.append(h)
    out.sort(key=lambda h: -(h.get("score") or 0))
    return {"results": out[:10]}


# ── critique: a written chapter measured beside the reference chapters its plan modelled ─────────────────────────
_QUOTE = re.compile(r"[\"“]([^\"“”\n]{2,600})[\"”]")


# The mechanics builder's own paragraph split and fight detector (corpus/build_mechanics_deltas.py), copied so a written
# chapter is measured exactly the way its reference chapters were. Keep the two in step.
_SOUND = re.compile(r"\b(bang|boom|crack|clang|whoosh|swish|thud|crash|shoo+p|swoosh|pu+|peng|hong|kacha|ka-?cha|"
                    r"rumble|roar(?:ed|ing)?)\b[!.]*", re.I)
_VIOLENT = re.compile(r"\b(punch(?:ed|es)?|kick(?:ed)?|slash(?:ed)?|stab(?:bed)?|strike|struck|smash(?:ed)?|"
                      r"slam(?:med)?|blood|vomit(?:ed)?|shatter(?:ed)?|collid(?:e|ed)|attack(?:ed)?|palm strike|"
                      r"sword (?:light|qi)|fist|blow|flung|sent flying|crushed|exploded|qi surged)\b", re.I)
def _builder_paragraphs(raw: str) -> list:
    """The chapter's paragraphs, title lines dropped (raws open with "Chapter N – Title", often twice)."""
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", raw or "") if p.strip()]
    while paras and re.match(r"^chapter\s*\d+", paras[0], re.I) and len(paras[0].split()) <= 20:
        paras.pop(0)
    return paras


def _hot(p: str) -> int:
    return len(_SOUND.findall(p)) * 2 + len(_VIOLENT.findall(p))


def _builder_fights(paras: list) -> list:
    """[(first, last)] paragraph runs that read as a fight: 3+ hot paragraphs with gaps of at most 2 cool ones."""
    hot = [_hot(p) >= 1 for p in paras]
    out, i, n = [], 0, len(paras)
    while i < n:
        if not hot[i]:
            i += 1
            continue
        last, gap, j = i, 0, i
        while j + 1 < n:
            j += 1
            if hot[j]:
                last, gap = j, 0
            else:
                gap += 1
                if gap > 2:
                    break
        run = range(i, last + 1)
        if sum(hot[k] for k in run) >= 3 and sum(_hot(paras[k]) for k in run) >= 5:
            out.append((i, last))
        i = last + 1
    return out




def _measure_text(text: str) -> dict:
    paras = _builder_paragraphs(text)
    words = len(" ".join(paras).split())
    spoken = sum(len(q.split()) for q in _QUOTE.findall(text or ""))
    spans = _builder_fights(paras)
    fw = sum(len(paras[k].split()) for a, b in spans for k in range(a, b + 1))
    before = sum(len(p.split()) for p in paras[:spans[0][0]]) if spans else None
    after = sum(len(p.split()) for p in paras[spans[-1][1] + 1:]) if spans else None
    lines = _QUOTE.findall(text or "")
    fight_lines = sum(len(_QUOTE.findall(paras[k])) for a, b in spans for k in range(a, b + 1))
    return {"words": words, "spoken_share": round(spoken / words, 3) if words else 0, "spoken_lines": len(lines),
            "fight_passages": len(spans), "words_before_first_fight": before, "words_in_fights": fw,
            "words_after_last_fight": after, "fight_lines": fight_lines,
            "time_jumps": len(_JUMP.findall(text or "")), "ends_in_fight": bool(spans and spans[-1][1] >= len(paras) - 2)}


@router.get("/chapter-check/{project_id}/{chapter}")
def chapter_check(project_id: str, chapter: int):
    pf = _P.corpus / "projects" / project_id / "project.json"
    gp = _P.corpus / "generated" / project_id / f"ch{chapter:03d}_generated.txt"
    if not pf.exists() or not gp.exists():
        raise HTTPException(404, "No such chapter.")
    project = json.loads(pf.read_text(encoding="utf-8"))
    if not reference_novels(project):
        return {"ok": False, "reason": "Tick 'Plan from this novel's corpus data and raws' in Author DNA first."}
    ours = _measure_text(gp.read_text(encoding="utf-8", errors="ignore"))
    sk = next((c for c in (project.get("chapter_skeletons") or []) if isinstance(c, dict) and c.get("number") == chapter), None) or {}
    picks = [(r["novel"], r["chapter"]) for r in (sk.get("reference_chapters") or [])
             if isinstance(r, dict) and r.get("novel") and isinstance(r.get("chapter"), int)]
    if not picks:
        q = " ".join(str(sk.get(k) or "") for k in ("purpose", "key_event")).strip()
        picks = find_reference_chapters(project, chapter, q) if q else []
    refs = []
    for nv, c in picks:
        m = mechanics(nv, c)
        if m:
            refs.append({"novel": nv, "novel_title": _title(nv), "chapter": c, "measured": m.get("measured") or {},
                         "fight_lines": sum(len(ex.get("talk") or []) for f in (m.get("fights") or []) for ex in (f.get("exchanges") or []) if isinstance(ex, dict))})
    notes = []
    if refs:
        ref_sp = sum(r["measured"].get("spoken_share") or 0 for r in refs) / len(refs)
        if ours["spoken_share"] < ref_sp * 0.6:
            notes.append(f"Much less talk than the reference ({round(ours['spoken_share'] * 100)}% spoken against about {round(ref_sp * 100)}%).")
        rf = [r for r in refs if r["measured"].get("fight_passages")]
        if ours["fight_passages"] and rf:
            if (ours["words_before_first_fight"] or 0) < (ours["words_in_fights"] or 0):
                notes.append("The fight runs longer than the build-up before it; the reference builds up first.")
            if ours["fight_lines"] < max(2, min(r["fight_lines"] for r in rf)):
                notes.append(f"Few lines spoken inside the fight ({ours['fight_lines']}); in the reference the fighters keep talking between blows.")
    if ours["time_jumps"]:
        notes.append(f"{ours['time_jumps']} jump phrase(s) (meanwhile / at the same time / elsewhere) — check the scenes follow on.")
    return {"ok": True, "ours": ours, "references": refs, "notes": notes}
