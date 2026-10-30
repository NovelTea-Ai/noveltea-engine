"""TIMELINE tab (Pre-generation): the book chapter by chapter, from the main character's point of view.

The unit is the chapter. The tab shows the arcs (with the hero's realm and where he is), the author's own timeline events, and every
Conspiracy-tree node pinned to a chapter, seen the way the hero sees it (its surface, or its truth once revealed). The author's events
are stored at project["timeline"] = {"events": [...], "arcs": {"<n>": {"realm", "place", "fights", "escapes", "untouchable"}}}.
An event: {id, chapter, end_chapter, category, title, text, mc_sees}. Events pinned to a chapter are given to that chapter's planner
and writer (timeline_chapter_block)."""
import copy
import json
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

CATEGORIES = ["fight", "breakthrough", "reveal", "clue", "plot", "character", "place", "personal"]
# how a Conspiracy-tree node shows on the hero's timeline
_TREE_CAT = {"clue": "clue", "breadcrumb": "clue", "mistake": "clue", "event": "plot", "false_flag": "plot", "patsy": "plot",
             "cover_up": "plot", "agent": "character", "scheme": "reveal", "final_scheme": "reveal"}


def _G():
    from routers.generation import generate as G
    return G


def _load(pid: str) -> dict:
    p = _G().CORPUS_PATH / "projects" / pid / "project.json"
    if not p.exists():
        raise HTTPException(404, f"Project {pid} not found")
    return json.loads(p.read_text(encoding="utf-8"))


def _save(pid: str, project: dict):
    (_G().CORPUS_PATH / "projects" / pid / "project.json").write_text(json.dumps(project, indent=2, ensure_ascii=False), encoding="utf-8")


def _int(v):
    try:
        return int(v) if v not in (None, "", "null") else None
    except (TypeError, ValueError):
        return None


def _clean_event(e: dict, i: int = 0) -> Optional[dict]:
    if not isinstance(e, dict):
        return None
    ch = _int(e.get("chapter"))
    if not ch or not str(e.get("title") or "").strip():
        return None
    end = _int(e.get("end_chapter"))
    cat = str(e.get("category") or "plot").strip().lower()
    return {"id": str(e.get("id") or f"t{int(time.time() * 1000) % 10**10}{i}"), "chapter": ch,
            "end_chapter": end if end and end > ch else None, "category": cat if cat in CATEGORIES else "plot",
            "title": str(e.get("title")).strip()[:160], "text": str(e.get("text") or "").strip()[:1200],
            "mc_sees": str(e.get("mc_sees") or "").strip()[:600]}


def _book(project: dict):
    from routers.pre_generation.conspiracy import book_volumes
    c = project.get("conspiracy") or {}
    total = _int(c.get("book_chapters")) or _int(project.get("target_chapters")) or 1500
    return total, book_volumes(total, _int(c.get("arcs_total")))


def _tree_events(project: dict) -> list:
    c = project.get("conspiracy") or {}
    reveal = _int(c.get("reveal_arc")) or 2
    out = []
    for n in c.get("nodes") or []:
        if not n.get("chapter"):
            continue
        out.append({"id": "tree:" + n["id"], "chapter": n["chapter"], "end_chapter": None, "from_tree": True,
                    "category": "reveal" if n.get("title", "").startswith("Grand reveal") else _TREE_CAT.get(n.get("type"), "plot"),
                    "tree_type": n.get("type"), "title": n.get("title", ""), "mc_sees": n.get("surface") or "", "text": n.get("text") or "",
                    "revealed": n.get("status") == "revealed"})
    return out


def timeline_chapter_block(project: dict, ch: int, cap: int = 1500) -> str:
    """The author's own timeline events on this chapter, for its planner and writer (tree nodes reach them through the Conspiracy blocks)."""
    evs = [e for e in ((project.get("timeline") or {}).get("events") or [])
           if isinstance(e, dict) and e.get("chapter") and (e["chapter"] == ch or (e.get("end_chapter") and e["chapter"] <= ch <= e["end_chapter"]))]
    if not evs:
        return ""
    from routers.pre_generation.canon import hero_name
    lines = [f"THE AUTHOR'S TIMELINE FOR THIS CHAPTER (from {hero_name(project)}'s point of view; make these happen):"]
    for e in evs:
        span = f" (chapters {e['chapter']}-{e['end_chapter']})" if e.get("end_chapter") else ""
        # the writer gets only what the hero sees; an event's notes (the truth behind it) are for the author and the planners
        lines.append(f"- [{e.get('category')}] {e.get('title')}{span}" + (f": {e['mc_sees']}" if e.get("mc_sees") else ""))
    return "\n".join(lines)[:cap]


@router.get("/{project_id}")
def get_timeline(project_id: str):
    project = _load(project_id)
    total, vols = _book(project)
    tl = project.get("timeline") or {}
    from routers.pre_generation.canon import hero_name
    return {"ok": True, "hero": hero_name(project), "chapters": total, "arcs": vols, "arc_info": tl.get("arcs") or {}, "categories": CATEGORIES,
            "events": tl.get("events") or [], "tree_events": _tree_events(project),
            "arc_labels": [a.get("label") for a in (project.get("arcs") or []) if isinstance(a, dict)]}


class SaveRequest(BaseModel):
    project_id: str
    events: list
    arcs: Optional[dict] = None


@router.post("/save")
def save_timeline(req: SaveRequest):
    project = _load(req.project_id)
    old = project.get("timeline")
    if old:
        hist = project.setdefault("_field_history", {}).setdefault("timeline", [])
        hist.append(copy.deepcopy(old))
        project["_field_history"]["timeline"] = hist[-20:]
    tl = project.setdefault("timeline", {})
    tl["events"] = [e for e in (_clean_event(x, i) for i, x in enumerate(req.events or [])) if e][:2000]
    if req.arcs is not None:
        tl["arcs"] = {str(k): {kk: str(vv)[:400] for kk, vv in (v or {}).items()} for k, v in req.arcs.items() if isinstance(v, dict)}
    _save(req.project_id, project)
    return {"ok": True, "events": tl["events"], "arc_info": tl.get("arcs") or {}}


class UndoRequest(BaseModel):
    project_id: str


@router.post("/undo")
def undo_timeline(req: UndoRequest):
    project = _load(req.project_id)
    hist = (project.get("_field_history") or {}).get("timeline") or []
    if not hist:
        raise HTTPException(400, "Nothing to undo.")
    project["timeline"] = hist.pop()
    _save(req.project_id, project)
    tl = project["timeline"]
    return {"ok": True, "events": tl.get("events") or [], "arc_info": tl.get("arcs") or {}}


# ── suggestions: the author's brain at work ───────────────────────────────────────────────────────────────────────────
class SuggestRequest(BaseModel):
    project_id: str
    first: int
    last: int
    note: Optional[str] = None
    provider: Optional[str] = None


def _plan_arcs(project: dict, first: int, last: int) -> str:
    """The planned story arcs over this stretch (Arc Planner), as the planner wrote them."""
    out = []
    for i, a in enumerate(project.get("arcs") or []):
        ch = (a or {}).get("chapters") or []
        if not isinstance(a, dict) or not ch or ch[-1] < first or ch[0] > last:
            continue
        bits = [f"Arc {i + 1} '{a.get('label')}' (chapters {ch[0]}-{ch[-1]}): {str(a.get('description') or '')[:700]}"]
        for k, l in (("power_milestone", "power milestone"), ("tension_shape", "tension"), ("reveals_planned", "reveals planned"),
                     ("opens_threads", "opens"), ("closes_threads", "closes")):
            if a.get(k):
                bits.append(f"  {l}: {json.dumps(a[k], ensure_ascii=False)[:400]}")
        out.append("\n".join(bits))
    return ("THE STORY ARCS PLANNED OVER THESE CHAPTERS:\n" + "\n".join(out) + "\n\n") if out else ""


def _tree_pins(project: dict, first: int, last: int) -> str:
    """Conspiracy-tree nodes pinned in (or just around) this stretch: the truth and what the hero sees. For the author's timeline only."""
    rows = []
    for n in (project.get("conspiracy") or {}).get("nodes") or []:
        ch = n.get("chapter")
        if isinstance(ch, int) and first - 5 <= ch <= last + 5:
            rows.append((ch, f"- ch {ch} [{n.get('type')}] {n.get('title')}: truth: {str(n.get('text') or '')[:260]}"
                             + (f" | the hero sees: {str(n.get('surface'))[:200]}" if n.get("surface") else "")))
    rows.sort()
    return ("THE CONSPIRACY TREE PINS THESE TO THIS STRETCH (already on the timeline as Plot slips: do not repeat them; build the hero's days "
            "around them, and let him meet their surface):\n" + "\n".join(r for _, r in rows[:40]) + "\n\n") if rows else ""


@router.post("/suggest")
def suggest_events(req: SuggestRequest):
    """Propose the hero's timeline events for chapters first..last the way an author plans a stretch, grounded in the book's own canon
    (tree > timeline > arcs) and in what the authors of comparable published novels put on the page over the same stretch (their
    author brains: milestones and rhythm). Nothing is saved: the author accepts or declines each proposal in the tab."""
    pid = req.project_id
    project = _load(pid)
    total, _ = _book(project)
    first = max(1, min(int(req.first or 1), total))
    last = max(first, min(int(req.last or first), total, first + 79))       # at most 80 chapters per call
    span = last - first + 1
    G = _G()
    from routers.pre_generation.canon import hero_name, canon_context_block
    from routers.corpus_tools import author_brain as AB
    from routers.pre_generation.conspiracy import _llm
    hero = hero_name(project)
    events = [e for e in ((project.get("timeline") or {}).get("events") or []) if isinstance(e, dict) and e.get("chapter")]
    near = [e for e in events if first - 15 <= e["chapter"] <= last + 15]
    near_txt = "\n".join(f"- ch {e['chapter']}{'-' + str(e['end_chapter']) if e.get('end_chapter') else ''} [{e.get('category')}] {e.get('title')}"
                         + (f": {str(e.get('mc_sees'))[:160]}" if e.get("mc_sees") else "") for e in sorted(near, key=lambda e: e["chapter"]))
    premise = project.get("premise") or (project.get("creative_brief") or {}).get("premise", "")
    query = " ".join(filter(None, [premise, " ".join(str((a or {}).get("label") or "") + " " + str((a or {}).get("description") or "")[:300]
                                                     for a in (project.get("arcs") or []) if isinstance(a, dict)
                                                     and (a.get("chapters") or [0])[-1] >= first and (a.get("chapters") or [10**6])[0] <= last),
                                   req.note or ""]))[:2000]
    material = AB.timeline_material(project, first, last, query, project_id=pid)
    per20 = (AB.corpus_rhythm().get("per_20") or {})
    want = max(6, min(24, round(span / 20 * sum(per20.values())) if per20 else span // 2))
    try:
        canon = canon_context_block(project, "plan", first, last, cap=9000)
    except Exception:
        canon = ""
    prompt = (
        f"You are the AUTHOR of the web novel \"{project.get('title', '')}\", planning {hero}'s timeline for chapters {first}-{last}. Think "
        "like an author, not a summariser: this stretch must keep its arc's promise to the reader, raise the pressure, turn, and pay off or "
        "hand over; fights, breakthroughs, reveals and quiet personal beats are spaced the way published novels space them (the rhythm "
        "below); the conspiracy's clues land on the chapters the tree pins; every event sets up something later or pays off something "
        "earlier; the hero's power stays inside what this arc lets him fight and escape.\n"
        f"Propose about {want} events for chapters {first}-{last}. Do not repeat events already on the timeline. Use only names, places, "
        "factions and powers from this book's canon below (never names from the comparable novels).\n\n"
        f"PREMISE: {premise}\n\n"
        + _plan_arcs(project, first, last)
        + _tree_pins(project, first, last)
        + (f"ALREADY ON {hero.upper()}'S TIMELINE NEAR THESE CHAPTERS (keep continuity with them):\n{near_txt}\n\n" if near_txt else "")
        + (canon + "\n\n" if canon else "")
        + (f"THE AUTHOR ASKS FOR: {req.note}\n\n" if (req.note or "").strip() else "")
        + (material + "\n\n" if material else "")
        + "Reply with ONE JSON object, no markdown fences: {\"events\": [{\"chapter\": 0, \"end_chapter\": null, \"category\": \""
        + " | ".join(CATEGORIES) + "\", \"title\": \"what happens, short\", \"mc_sees\": \"what " + hero + " sees and feels, one or two "
        "sentences, never the hidden truth\", \"text\": \"your author's note: why it is here (the setup it pays off or the payoff it sets "
        "up, the truth behind it)\"}]}")
    prov, model, key = _llm(pid, req.provider)
    try:
        raw = G._call_llm(prompt, prov, model, key, timeout=1800, abort_key=(pid, "timeline"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"The AI call failed ({type(e).__name__}: {str(e)[:200]}). Nothing was changed; try again.")
    try:
        data = G._parse_json_from_text(raw)
    except Exception:
        data = None
    items = data.get("events") if isinstance(data, dict) else data if isinstance(data, list) else None
    if not isinstance(items, list) or not items:
        raise HTTPException(502, "The AI's reply wasn't a usable list of events, so nothing was suggested. Try again.")
    have = {(e["chapter"], str(e.get("title") or "").strip().lower()) for e in events}
    out = []
    for i, x in enumerate(items[:40]):
        e = _clean_event({**x, "id": None} if isinstance(x, dict) else x, i)
        if not e:
            continue
        e["id"] = f"s{int(time.time() * 1000) % 10**10}{i}"
        e["chapter"] = max(first, min(last, e["chapter"]))
        if e.get("end_chapter"):
            e["end_chapter"] = min(total, e["end_chapter"]) if e["end_chapter"] > e["chapter"] else None
        if (e["chapter"], e["title"].lower()) in have:
            continue
        out.append(e)
    out.sort(key=lambda e: e["chapter"])
    return {"ok": True, "first": first, "last": last, "proposed": out, "grounded": bool(material)}
