"""SCENE PLAN (Pre-generation, the "Scenes" tool): the fight-plan interview for every other kind of scene, planned BEFORE the chapter is written, against
the scene's word budget.

Kinds: a conversation or confrontation, a discovery, learning or cultivation, a place (arrival, market, travel), and the fallout after something.
Like the fight plan: five beats, one question each with three options that show their word cost and a running total; options are built from the
chapter plan's scene, the people in it (their archetype and how they talk), the book's plan (writer-safe), and labelled corpus passages matched to the
beat. Options can carry the chapter's planned clues, reveals, arrivals and timeline events, so they surface INSIDE the scene.
The result is a card the author accepts or declines; accepted cards reach the chapter writer and the interview. Gates are not touched.
Stored: project["scene_plans"][chapter][slot] (accepted), project["scene_plans_pending"][chapter][slot], project["scene_sessions"][id].
"""
import re
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from routers.pre_generation.fightplan import (_MIN_BEAT_WORDS, _G, _int, _load, _plan_of, _save, corpus_moves, weave_items)

router = APIRouter()

# kind: (label, default words, keyword regex that suggests it from a plan scene, beats [(key, label, share, corpus prose types)])
KINDS = {
    "dialogue": ("A conversation or confrontation", 600, r"dialog|conversation|talk|negotiat|argu|banter|confront|interrogat|haggl|bargain", [
        ("opening", "The opening and the stakes", 0.15, ["dialogue_exposition", "dialogue_banter"]),
        ("pressure", "What each side wants", 0.25, ["dialogue_threat", "dialogue_banter"]),
        ("turn", "The turn", 0.25, ["dialogue_exposition", "emotional_beat"]),
        ("decision", "The decision", 0.20, ["emotional_beat", "dialogue_banter"]),
        ("exit", "The exit line", 0.15, ["dialogue_banter", "scene_transition"])]),
    "discovery": ("A discovery", 500, r"discover|find|found|investigat|search|secret|clue|uncover|notice", [
        ("approach", "The approach", 0.15, ["description_environment", "internal_monologue_planning"]),
        ("find", "The find", 0.25, ["power_reveal", "description_environment"]),
        ("handling", "What he does with it", 0.25, ["internal_monologue_reaction", "internal_monologue_planning"]),
        ("cost", "The cost or the near miss", 0.20, ["emotional_beat", "dialogue_threat"]),
        ("leave", "Leaving with it", 0.15, ["scene_transition", "internal_monologue_reaction"])]),
    "training": ("Learning or cultivation", 700, r"train|cultivat|learn|breakthrough|comprehen|archives|teacher|practi[cs]e|lesson", [
        ("shown", "What he is shown", 0.20, ["cultivation_description", "power_reveal"]),
        ("attempt", "His first attempt", 0.20, ["internal_monologue_planning", "cultivation_description"]),
        ("failure", "Where it fails", 0.20, ["internal_monologue_reaction", "emotional_beat"]),
        ("insight", "The insight", 0.25, ["power_reveal", "cultivation_description"]),
        ("price", "The price and what changed", 0.15, ["emotional_beat", "scene_transition"])]),
    "place": ("A place: arrival, market or travel", 450, r"travel|arriv|market|journey|district|wander|street|tier|bridge|isle|gate|checkpoint", [
        ("arrival", "The first sight", 0.20, ["description_environment", "scene_transition"]),
        ("people", "Who is there", 0.25, ["description_character", "dialogue_banter"]),
        ("snag", "The snag", 0.25, ["dialogue_threat", "internal_monologue_reaction"]),
        ("hint", "The hint", 0.15, ["description_environment", "internal_monologue_planning"]),
        ("leaving", "Moving on", 0.15, ["scene_transition"])]),
    "aftermath": ("Fallout and feeling", 400, r"aftermath|emotional|reaction|recover|mourn|rest|reflect|quiet|heal", [
        ("reaction", "The reaction", 0.25, ["internal_monologue_reaction", "emotional_beat"]),
        ("cost", "What it cost", 0.20, ["emotional_beat", "description_character"]),
        ("bond", "The bond", 0.25, ["dialogue_banter", "emotional_beat"]),
        ("warning", "A warning or a question", 0.15, ["internal_monologue_planning", "dialogue_exposition"]),
        ("hook", "The hook", 0.15, ["scene_transition", "internal_monologue_reaction"])]),
}


def guess_kind(scene: dict) -> str:
    text = f"{scene.get('scene_type', '')} {scene.get('structure_notes', '')}".lower()
    for k, (_, _, rx, _) in KINDS.items():
        if re.search(rx, text):
            return k
    return "dialogue"


def _scenes(project: dict, ch: int) -> list:
    """The chapter plan's scenes that are not fights (fights have the fight plan), with a guessed kind."""
    G = _G()
    out = []
    for s in (_plan_of(project, ch) or {}).get("scenes") or []:
        if not isinstance(s, dict):
            continue
        fight = str(s.get("scene_type") or "").lower() in G._FIGHT_SCENE_TYPES or G._FIGHT_PLAN_RE.search(str(s.get("structure_notes") or ""))
        out.append({"number": _int(s.get("scene_number")) or len(out) + 1, "type": s.get("scene_type"), "words": _int(s.get("estimated_word_count")),
                    "notes": str(s.get("structure_notes") or "")[:600], "fight": bool(fight), "kind": guess_kind(s)})
    return out


def _people(project: dict, ch: int, scene: Optional[dict]) -> list:
    """Who can be in the scene: the plan's characters, then the cast around this chapter."""
    names = [str(n) for n in (_plan_of(project, ch) or {}).get("characters_in_chapter") or [] if isinstance(n, str)]
    try:
        from routers.pre_generation.castroster import presence_profile, stints_of
        prof = presence_profile(project)
        for c in project.get("character_list") or []:
            if isinstance(c, dict) and c.get("name") and c["name"] not in names and (_int(c.get("intro_chapter")) == ch or any(a <= ch <= b for a, b in stints_of(project, c, prof))):
                names.append(c["name"])
    except Exception:
        pass
    return names[:24]


def scene_plan_block(project: dict, ch: int, cap: int = 2600) -> str:
    cards = (project.get("scene_plans") or {}).get(str(ch)) or {}
    if not cards:
        return ""
    lines = ["SCENE PLANS FOR THIS CHAPTER (the author's cards: write each scene in these beats, in this order, near these word counts):"]
    for slot, c in sorted(cards.items()):
        lines.append((f"Scene {c['scene']} - " if c.get("scene") else "Scene - ") + f"{c.get('label')} (~{c.get('budget')} words)" + (f", with {', '.join(c.get('people') or [])}" if c.get("people") else "") + ":")
        for i, b in enumerate(c.get("beats") or [], 1):
            lines.append(f"  {i}. {b.get('label')} (~{b.get('words')} words): {b.get('text')}")
            for w in b.get("weave") or []:
                lines.append(f"       also in this beat ({w.get('kind')}): {w.get('text')}")
        if c.get("unplaced"):
            lines.append("  Also carried by the chapter (place elsewhere): " + "; ".join(u.get("text", "") for u in c["unplaced"][:6]))
    return "\n".join(lines)[:cap]


# ── endpoints ──────────────────────────────────────────────────────────────────────────────────────────────────────────
class BudgetRequest(BaseModel):
    project_id: str
    chapter: int
    scene: Optional[int] = None
    kind: Optional[str] = None
    words: Optional[int] = None


class StartRequest(BudgetRequest):
    people: Optional[list] = None
    provider: Optional[str] = None


class AnswerRequest(BaseModel):
    project_id: str
    session_id: str
    choice: Optional[int] = None
    custom: Optional[str] = None
    custom_words: Optional[int] = None
    back: bool = False
    provider: Optional[str] = None


class DecideRequest(BaseModel):
    project_id: str
    chapter: int
    slot: str
    action: str            # accept | decline | remove


def _resolve(project: dict, req: BudgetRequest) -> dict:
    scenes = _scenes(project, req.chapter)
    sc = next((s for s in scenes if s["number"] == req.scene), None) if req.scene else None
    kind = req.kind if req.kind in KINDS else (sc["kind"] if sc else "dialogue")
    default = KINDS[kind][1]
    words = req.words or (sc or {}).get("words") or default
    total = sum(s.get("words") or 0 for s in scenes) or None
    notes = []
    if words < 150:
        notes.append(f"{words} words is very short for five beats; the scene will be sketchy.")
    if total and words > 0.6 * total:
        notes.append(f"This scene is {round(100 * words / total)}% of the planned chapter.")
    return {"kind": kind, "label": KINDS[kind][0], "words": words, "scene": sc, "source": "your number" if req.words else ("the chapter plan" if sc and sc.get("words") else "the usual length for this kind"),
            "notes": notes, "chapter_words": total}


@router.get("/{project_id}")
def overview(project_id: str):
    project = _load(project_id)
    chapters = sorted({c.get("number") for c in project.get("chapter_skeletons") or [] if isinstance(c, dict) and c.get("number")}
                      | {int(k) for k in (project.get("scene_plans") or {})})
    rows = [{"chapter": ch, "scenes": _scenes(project, ch), "cards": (project.get("scene_plans") or {}).get(str(ch)) or {},
             "pending": (project.get("scene_plans_pending") or {}).get(str(ch)) or {}} for ch in chapters]
    return {"ok": True, "chapters": rows, "kinds": {k: {"label": v[0], "words": v[1]} for k, v in KINDS.items()}}


@router.post("/budget")
def budget(req: BudgetRequest):
    project = _load(req.project_id)
    r = _resolve(project, req)
    return {"ok": True, **r, "people": _people(project, req.chapter, r["scene"]), "scenes": _scenes(project, req.chapter),
            "cards": (project.get("scene_plans") or {}).get(str(req.chapter)) or {}, "pending": (project.get("scene_plans_pending") or {}).get(str(req.chapter)) or {}}


def _options_for(project: dict, pid: str, session: dict, provider: Optional[str]) -> dict:
    G = _G()
    ch, step, kind = session["chapter"], session["step"], session["kind"]
    label_k, _, _, beats = KINDS[kind]
    key, label, share, types = beats[step]
    budget_w = session["budget"]
    beat_words = max(_MIN_BEAT_WORDS, round(budget_w * share))
    plan = _plan_of(project, ch) or {}
    scene = next((s for s in _scenes(project, ch) if s["number"] == session.get("scene")), None)
    people = []
    for n in session.get("people") or []:
        c = next((x for x in project.get("character_list") or [] if isinstance(x, dict) and x.get("name") == n), None)
        if c:
            people.append(f"- {n} ({c.get('role', '')}): {str(c.get('archetype', ''))[:200]} Voice: {str(c.get('voice') or c.get('speech_style') or '')[:160]}"
                          + (f" Sounds like: {' / '.join(str(x) for x in (c.get('voice_lines') or [])[:2])}" if c.get("voice_lines") else ""))
    query = f"{label} {(scene or {}).get('notes', '')[:160]} {plan.get('purpose', '')[:100]}"
    corpus = corpus_moves(query, types, 8)
    corpus.sort(key=lambda r: -r["score"])
    corpus = corpus[:3]
    try:
        from routers.pre_generation.canon import craft_context_block
        plan_block = craft_context_block(project, ch, "edit", 4500)
    except Exception:
        plan_block = ""
    done = "\n".join(f"- {b['label']} (~{b['words']} words): {b['text']}" for b in session["answers"]) or "(nothing yet)"
    used = {w for a in session["answers"] for w in a.get("weave", [])}
    left = [it for it in session.get("items") or [] if it["id"] not in used]
    weave_txt = ("THE CHAPTER ALSO CARRIES THESE PLANNED THINGS (still unplaced). Weave them INTO this scene where they fit naturally (a clue is noticed, never "
                 "explained; a reveal lands through what someone says or does; a new face arrives; a foe's escalation shows). An option may carry one or two; "
                 "list their ids in \"weave\". Some belong to other scenes, so carry only what fits THIS scene, and do not force one in:\n"
                 + "\n".join(f"  {it['id']} ({it['kind']}): {it['text']}" for it in left[:12]) + "\n\n") if left else ""
    prompt = (
        f"You are planning ONE beat of a scene for chapter {ch} of the web novel \"{project.get('title', '')}\". Do not write the scene; plan the beat.\n\n"
        f"{plan_block}\n\n"
        f"THE SCENE: {label_k}" + (f" (scene {scene['number']} of the chapter plan)" if scene else "") + ". "
        + (f"The plan says: {scene['notes']}\n" if scene and scene.get("notes") else "\n")
        + f"The chapter plan: {str(plan.get('purpose') or '')[:240]} | key event: {str(plan.get('key_event') or '')[:300]}\n"
        + ("WHO IS IN IT:\n" + "\n".join(people) + "\n" if people else "")
        + f"THE WORD BUDGET: the whole scene is about {budget_w} words; this beat ({label}) gets about {beat_words}. Beats chosen so far:\n{done}\n\n"
        + ("CORPUS PASSAGES THAT FIT THIS BEAT (adapt the mechanism to this book; never reuse a name or place):\n"
           + "\n".join(f"  - [{c['novel_title']}] {c['text'][:340]}" for c in corpus) + "\n\n" if corpus else "")
        + f"{weave_txt}THIS BEAT: {label}.\n"
        + "RULES: every speaker sounds like their own voice; the hero keeps his secrets and never explains them; nobody sees his hidden source of power or hears "
          "his hidden mentor; clues are noticed, not explained; reveals follow the chapter plan only. No secrets. Three DIFFERENT options "
          f"(different turns, not rewordings). Each option's 'words' is what this beat would take: between {_MIN_BEAT_WORDS} and {round(beat_words * 1.5)}, near {beat_words}.\n\n"
          "Reply with ONE JSON object, no fences: {\"options\": [{\"label\": \"under 8 words\", \"text\": \"1-2 sentences: what happens in this beat\", \"words\": 0, "
          "\"source\": \"corpus novel it adapts, or empty\", \"weave\": [\"ids of planned things this option carries, or none\"]}], \"recommended\": 0}")
    prov = provider or G._get_generation_cfg().get("default_provider", "anthropic")
    model, key_ = (G._get_models_cfg() or {}).get(prov, ""), G._get_key(prov)
    opts, data = None, None
    for _try in range(2):                      # the first call after a restart sometimes comes back unusable: one automatic retry
        raw = G._call_llm(prompt, prov, model, key_, timeout=900, abort_key=(pid, "sceneplan"))
        try:
            data = G._parse_json_from_text(raw)
        except Exception:
            data = None
        opts = (data or {}).get("options") if isinstance(data, dict) else None
        if opts:
            break
    if not opts:
        raise HTTPException(502, "The AI's reply wasn't usable options for this beat. Nothing was changed: try again.")
    from routers.pre_generation.castroster import _no_ledger
    running = sum(b["words"] for b in session["answers"])
    ids = {it["id"] for it in left}
    out = []
    for o in opts[:3]:
        if not isinstance(o, dict) or not str(o.get("text") or "").strip():
            continue
        w = max(_MIN_BEAT_WORDS, min(round(beat_words * 1.5), _int(o.get("words")) or beat_words))
        out.append({"label": _no_ledger(str(o.get("label") or "Option"))[:80], "text": _no_ledger(str(o["text"]).strip())[:500], "words": w,
                    "source": str(o.get("source") or "")[:80], "over": bool(running + w > budget_w * 1.1),
                    "weave": [x for x in (o.get("weave") or []) if isinstance(x, str) and x in ids][:2]})
    if not out:
        raise HTTPException(502, "The AI's reply wasn't usable options for this beat. Nothing was changed: try again.")
    rec = _int((data or {}).get("recommended")) or 0
    return {"beat": {"key": key, "label": label, "words": beat_words, "step": step + 1, "of": len(beats)}, "options": out, "recommended": rec if 0 <= rec < len(out) else 0,
            "running": running, "budget": budget_w, "items": session.get("items") or [], "left": [it["id"] for it in left],
            "corpus": [{"novel_title": c["novel_title"], "text": c["text"][:240]} for c in corpus]}


@router.post("/start")
def start(req: StartRequest):
    project = _load(req.project_id)
    r = _resolve(project, req)
    sid = f"sp{int(time.time() * 1000) % 10**10}"
    session = {"id": sid, "chapter": req.chapter, "scene": req.scene, "kind": r["kind"], "label": r["label"], "budget": r["words"], "step": 0, "answers": [],
               "people": [n for n in (req.people or []) if isinstance(n, str)][:6], "items": weave_items(project, req.chapter, None)}
    res = _options_for(project, req.project_id, session, req.provider)
    session["_options"] = res["options"]
    project = _load(req.project_id)
    project.setdefault("scene_sessions", {})[sid] = session
    _save(req.project_id, project)
    return {"ok": True, "session_id": sid, "chapter": req.chapter, "kind": r["kind"], "label": r["label"], "notes": r["notes"], **res}


def _assemble(session: dict) -> dict:
    ans = session["answers"]
    total = sum(a["words"] for a in ans) or 1
    scaled = [max(_MIN_BEAT_WORDS, round(a["words"] * session["budget"] / total)) for a in ans]
    scaled[-1] += session["budget"] - sum(scaled)
    items = {it["id"]: it for it in session.get("items") or []}
    beats = [{"key": a["key"], "label": a["label"], "text": a["text"], "words": w, "source": a.get("source", ""),
              "weave": [{"kind": items[i]["kind"], "text": items[i]["text"]} for i in a.get("weave", []) if i in items]} for a, w in zip(ans, scaled)]
    used = {i for a in ans for i in a.get("weave", [])}
    return {"chapter": session["chapter"], "scene": session.get("scene"), "kind": session["kind"], "label": session["label"], "people": session.get("people") or [],
            "budget": session["budget"], "beats": beats, "unplaced": [{"kind": it["kind"], "text": it["text"]} for it in session.get("items") or [] if it["id"] not in used],
            "created": time.strftime("%Y-%m-%d %H:%M"), "status": "proposed"}


def slot_of(session_or_card: dict) -> str:
    return f"{session_or_card['kind']}{session_or_card.get('scene') or ''}"


@router.post("/answer")
def answer(req: AnswerRequest):
    project = _load(req.project_id)
    session = (project.get("scene_sessions") or {}).get(req.session_id)
    if not session:
        raise HTTPException(404, "This scene interview is no longer open. Start it again.")
    beats = KINDS[session["kind"]][3]
    if req.back:
        if session["step"] == 0:
            raise HTTPException(400, "This is the first question.")
        session["step"] -= 1
        session["answers"] = session["answers"][:session["step"]]
        res = _options_for(project, req.project_id, session, req.provider)
        session["_options"] = res["options"]
        project = _load(req.project_id)
        project.setdefault("scene_sessions", {})[req.session_id] = session
        _save(req.project_id, project)
        return {"ok": True, "done": False, **res}
    key, label, share, _ = beats[session["step"]]
    if req.custom and req.custom.strip():
        picked = {"key": key, "label": label, "text": req.custom.strip()[:500], "words": max(_MIN_BEAT_WORDS, req.custom_words or round(session["budget"] * share)),
                  "source": "", "weave": []}
    else:
        opts = session.get("_options") or []
        if req.choice is None or not (0 <= req.choice < len(opts)):
            raise HTTPException(400, "Pick one of the options, or write your own.")
        o = opts[req.choice]
        picked = {"key": key, "label": label, "text": o["text"], "words": o["words"], "source": o.get("source", ""), "weave": o.get("weave", [])}
    session["answers"] = session["answers"][:session["step"]] + [picked]
    session["step"] += 1
    if session["step"] >= len(beats):
        card = _assemble(session)
        project = _load(req.project_id)
        project.setdefault("scene_plans_pending", {}).setdefault(str(session["chapter"]), {})[slot_of(session)] = card
        (project.get("scene_sessions") or {}).pop(req.session_id, None)
        _save(req.project_id, project)
        return {"ok": True, "done": True, "card": card, "slot": slot_of(session)}
    res = _options_for(project, req.project_id, session, req.provider)
    session["_options"] = res["options"]
    project = _load(req.project_id)
    project.setdefault("scene_sessions", {})[req.session_id] = session
    _save(req.project_id, project)
    return {"ok": True, "done": False, **res}


@router.post("/decide")
def decide(req: DecideRequest):
    project = _load(req.project_id)
    ch = str(req.chapter)
    pend = (project.get("scene_plans_pending") or {}).get(ch) or {}
    if req.action == "accept":
        card = pend.pop(req.slot, None)
        if not card:
            raise HTTPException(400, "There is no proposed card for this scene.")
        card["status"] = "accepted"
        project.setdefault("scene_plans", {}).setdefault(ch, {})[req.slot] = card
    elif req.action == "decline":
        pend.pop(req.slot, None)
    elif req.action == "remove":
        ((project.get("scene_plans") or {}).get(ch) or {}).pop(req.slot, None)
    else:
        raise HTTPException(400, "action must be accept, decline or remove")
    for k in ("scene_plans", "scene_plans_pending"):
        d = project.get(k) or {}
        if ch in d and not d[ch]:
            d.pop(ch)
    _save(req.project_id, project)
    return {"ok": True}
