"""FIGHT PLAN (Pre-generation, in the Combat tab): a short interview that plans one chapter's fight BEFORE it is written, against a word budget.

- The budget comes from the chapter plan's fight scene (estimated_word_count), or the style novel's Combat DNA when there is no plan yet; it is
  shown on every option, with a running total, and the finished card's beats always add up to it.
- Each of the five beats (threat, attack, hit or dodge, reversal, finish) asks one question with three options. The options are built from the
  foe (Foes tab), the hero's realm and the realm-gap rule (Timeline), the chapter plan, the book's plan, and labelled corpus fight passages
  matched to the beat (adapted, never copied). The hero is never a punching bag.
- The result is a FIGHT CARD, a proposal the author accepts or declines. An accepted card goes to the chapter writer (and the interview's fight
  part) as the beats and per-beat word counts to follow. Nothing in the gates is touched: the budgets are only read.
- Corpus matching also tags each retrieved passage for free (no AI): fight beat, technique family, crowd, hero outmatched.
Stored: project["fight_plans"][chapter] (accepted), project["fight_plans_pending"][chapter] (proposed), project["fight_sessions"][id] (in progress).
"""
import json
import re
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

# (key, label, share of the fight's words, corpus prose types that fit the beat)
BEATS = [
    ("threat", "The threat", 0.12, ["dialogue_threat"]),
    ("attack", "The attack he reads", 0.25, ["combat_technique"]),
    ("hit", "The hit, or the dodge", 0.20, ["combat_reaction"]),
    ("reversal", "The reversal", 0.28, ["power_reveal", "combat_technique"]),
    ("finish", "The finish and the aftermath", 0.15, ["combat_reaction", "power_reveal"]),
]
_MIN_BEAT_WORDS = 40


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
        return int(v)
    except (TypeError, ValueError):
        return None


# ── the budget, the foe, the hero ───────────────────────────────────────────────────────────────────────────────────────
def _plan_of(project: dict, ch: int) -> Optional[dict]:
    return next((c for c in project.get("chapter_skeletons") or [] if isinstance(c, dict) and c.get("number") == ch), None)


def _dna_words(project: dict) -> dict:
    fw = ((project.get("author_profile") or {}).get("combat_dna") or {}).get("fight_words") or {}
    return {"target": int(fw.get("target") or 700), "low": int(fw.get("low") or 400), "high": int(fw.get("high") or 1000)}


def fight_budget(project: dict, ch: int, override: Optional[int] = None) -> dict:
    """Words for the fight: the override, else the plan's fight scene, else the Combat DNA target. Notes anything odd; never blocks."""
    G = _G()
    dna = _dna_words(project)
    plan = _plan_of(project, ch)
    scene_words, total = None, 0
    for s in (plan or {}).get("scenes") or []:
        if not isinstance(s, dict):
            continue
        w = _int(s.get("estimated_word_count")) or 0
        total += w
        if scene_words is None and (str(s.get("scene_type") or "").lower() in G._FIGHT_SCENE_TYPES or G._FIGHT_PLAN_RE.search(str(s.get("structure_notes") or ""))):
            scene_words = w or None
    words, source = (override, "your number") if override else ((scene_words, "the chapter plan's fight scene") if scene_words else (dna["target"], "the Combat DNA target"))
    notes = []
    if words < dna["low"]:
        notes.append(f"{words} words is under the style novel's fight range ({dna['low']}-{dna['high']}); the fight will read thin.")
    if words > dna["high"]:
        notes.append(f"{words} words is over the style novel's fight range ({dna['low']}-{dna['high']}).")
    if total and words > 0.6 * total:
        notes.append(f"The fight is {round(100 * words / total)}% of the planned chapter ({total} words): the rest of the chapter gets squeezed.")
    return {"words": words, "source": source, "chapter_words": total or None, "dna": dna, "notes": notes, "has_plan": bool(plan), "plan_has_fight": G._chapter_plan_has_fight(project, ch)}


def _foes_in_play(project: dict, ch: int) -> list:
    from routers.pre_generation.antagonists import _active
    roster = [e for e in ((project.get("antagonists") or {}).get("roster") or []) if isinstance(e, dict) and e.get("name")]
    order = {"boss": 0, "nemesis": 1, "enemy": 2, "rival": 3, "annoyance": 4}
    live = [e for e in roster if _active(e, ch)]
    live.sort(key=lambda e: (order.get(e.get("tier"), 5), -(e.get("first_chapter") or 0)))
    return live


def _hero(project: dict, ch: int) -> dict:
    from routers.pre_generation.canon import arc_of, hero_name
    a = arc_of(project, ch)
    info = ((project.get("timeline") or {}).get("arcs") or {}).get(str(a)) or {} if a else {}
    return {"name": hero_name(project), "arc": a, "realm": info.get("realm", ""), "fights": info.get("fights", ""), "escapes": info.get("escapes", ""),
            "untouchable": info.get("untouchable", "")}


# ── free corpus tagging: what a retrieved fight passage is, from its words ──────────────────────────────────────────────
_FAMILIES = {"palm": r"\bpalm", "fist": r"\b(fist|punch)", "blade": r"\b(sabre|saber|sword|blade|slash)", "spear": r"\b(spear|halberd|lance)",
             "formation": r"\b(formation|array)", "beast": r"\b(beast|claw|fang)", "movement": r"\b(step|footwork|dodg|evad|sidestep)",
             "elemental": r"\b(fire|flame|lightning|ice|wind|water)", "bow": r"\b(arrow|bow)"}


def tag_passage(text: str, ptype: str) -> dict:
    t = text.lower()
    beat = {"dialogue_threat": "threat", "combat_technique": "attack", "combat_reaction": "hit", "power_reveal": "reversal"}.get(ptype, "attack")
    if beat == "hit" and re.search(r"\b(dodg|evad|sidestep|slipped|ducked|avoided|twisted his body)", t):
        beat = "dodge"
    if re.search(r"\b(collaps|fell unconscious|defeated|finished|died|dead|corpse|surrender|kneel)", t) and beat in ("hit", "reversal", "attack"):
        beat = "finish"
    return {"beat": beat, "family": [k for k, rx in _FAMILIES.items() if re.search(rx, t)][:3],
            "crowd": bool(re.search(r"\b(crowd|onlooker|spectator|audience|everyone watching|cheered|gasped)", t)),
            "outmatched": bool(re.search(r"\b(overwhelm|crush|suppress|couldn't resist|unable to resist|pressure|too strong|helpless|no match)", t))}


def corpus_moves(query: str, types: list, top_k: int = 12) -> list:
    from routers.corpus_tools.corpus import knowledge_search
    from routers.generation.generate import _corpus_novel_titles, _novel_label
    try:
        hits = knowledge_search(query, top_k=top_k, category="prose", prose_types=types)
    except Exception:
        return []
    titles = _corpus_novel_titles()
    out = []
    for r in hits or []:
        pt = (r.get("meta") or {}).get("type") or ""
        out.append({"novel_id": r.get("novel_id"), "novel_title": _novel_label(r.get("novel_id"), r.get("novel_title"), titles), "chapter": r.get("chapter"),
                    "type": pt, "text": r.get("text") or "", "score": round(float(r.get("score") or 0), 3), "tags": tag_passage(r.get("text") or "", pt)})
    return out


def _foe_query(foe: dict, beat_key: str, hero: dict) -> str:
    bits = {"threat": f"{foe.get('who', '')} {foe.get('speech', '')} threatens the hero before the fight",
            "attack": f"{foe.get('strength', '')} {foe.get('archetype', '')} signature technique attack",
            "hit": f"hero reads the attack and dodges or takes the blow {foe.get('strength', '')}",
            "reversal": f"hero turns the {foe.get('archetype', '')} technique around, exploiting {foe.get('weakness', '')}",
            "finish": f"the {foe.get('tier', '')} opponent is beaten and the crowd reacts, aftermath"}
    return re.sub(r"\s+", " ", bits.get(beat_key, "")).strip()[:300]


# ── what a chapter carries, to weave INTO its scenes (a fight can reveal a clue; a new face can arrive as it ends) ──────────────────
def weave_items(project: dict, ch: int, foe: Optional[dict] = None) -> list:
    """The planned things this chapter must show, in writer-safe form (surfaces only, never the truth behind them)."""
    items = []
    try:
        from routers.pre_generation.conspiracy import _tree, VISIBLE_TYPES, SURFACE_TYPES
        t = _tree(project)
        arc_idx = _G()._arc_index_of(project, ch) or 0
        revealed_arc = (arc_idx + 1) >= t["reveal_arc"]            # from the reveal arc on, the plan lets the writer show what is behind a thing
        for n in t["nodes"]:
            if n.get("chapter") != ch or n["type"] == "agent":
                continue
            revealed = revealed_arc or n.get("status") == "revealed"
            if n["type"] in VISIBLE_TYPES:
                items.append({"kind": "clue", "text": str(n.get("surface") or n["title"])[:220]})
            elif n["type"] in SURFACE_TYPES:
                items.append({"kind": "reveal" if revealed else "event", "text": str((n["text"] if revealed else (n.get("surface") or n["title"])))[:260]})
            elif revealed:
                items.append({"kind": "reveal", "text": f"{n['title']}: {n['text']}"[:260]})
    except Exception:
        pass
    plan = _plan_of(project, ch) or {}
    for r in plan.get("reveals") or []:                       # the chapter plan's own reveals
        txt = r if isinstance(r, str) else " ".join(str(v) for v in r.values() if isinstance(v, str)) if isinstance(r, dict) else ""
        if txt.strip():
            items.append({"kind": "reveal", "text": txt.strip()[:220]})
    for c in project.get("character_list") or []:
        if isinstance(c, dict) and _int(c.get("intro_chapter")) == ch and c.get("name"):
            items.append({"kind": "arrival", "text": f"{c['name']} ({c.get('role', '')}) first appears: {str(c.get('archetype', ''))[:120]}"})
    for e in (project.get("timeline") or {}).get("events") or []:
        if isinstance(e, dict) and e.get("chapter") == ch and e.get("mc_sees"):
            items.append({"kind": "timeline", "text": f"{e.get('title')}: {str(e.get('mc_sees'))[:160]}"})
    if foe:
        try:
            from routers.pre_generation.antagonists import _stage_for
            st = _stage_for(foe, ch)
            if st:
                items.append({"kind": "escalation", "text": f"{foe.get('name')} at this stage: {st[:160]}"})
        except Exception:
            pass
    for i, it in enumerate(items, 1):
        it["id"] = f"w{i}"
    return items


def weave_rule_block(project: dict, ch: int, cap: int = 1800) -> str:
    """For the chapter writer and the interview: the chapter's planned things AND the rule to put them inside the scenes."""
    items = weave_items(project, ch)
    if not items:
        return ""
    lines = ["WEAVE THESE INTO THE SCENES (never as a separate paragraph of explanation): a clue can surface in the middle of a fight, when he reads a move or "
             "sees what the foe wears or where he looks; a reveal can land mid-fight (what the foe lets slip, what a blow knocks loose); a new face can arrive as a fight ends; a foe's escalation "
             "shows in how he fights; a joke can land between blows. Put each where it fits naturally, in the fight too:"]
    lines += [f"- ({it['kind']}) {it['text']}" for it in items]
    return "\n".join(lines)[:cap]


# ── the plan block that reaches the writers ────────────────────────────────────────────────────────────────────────────
def fight_plan_block(project: dict, ch: int, cap: int = 2200) -> str:
    card = (project.get("fight_plans") or {}).get(str(ch))
    if not card:
        return ""
    lines = [f"THE FIGHT PLAN FOR THIS CHAPTER (the author's fight card: write the fight in these beats, in this order, near these word counts; "
             f"about {card.get('budget')} words in all; {card.get('foe')} is the opponent, {card.get('hero_realm')} against {card.get('foe_realm') or 'his realm'}):"]
    for i, b in enumerate(card.get("beats") or [], 1):
        lines.append(f"{i}. {b.get('label')} (~{b.get('words')} words): {b.get('text')}")
        for w in b.get("weave") or []:
            lines.append(f"     also in this beat ({w.get('kind')}): {w.get('text')}")
    if card.get("unplaced"):
        lines.append("Also carried by this chapter (place them in the other scenes, or in the fight where it fits): " + "; ".join(u.get("text", "") for u in card["unplaced"]))
    lines.append("The hero is never a punching bag: he reads each technique as it begins, and the reversal is his.")
    return "\n".join(lines)[:cap]


# ── endpoints ────────────────────────────────────────────────────────────────────────────────────────────────────────
@router.get("/{project_id}")
def overview(project_id: str):
    project = _load(project_id)
    chapters = sorted({c.get("number") for c in project.get("chapter_skeletons") or [] if isinstance(c, dict) and c.get("number")}
                      | {int(k) for k in (project.get("fight_plans") or {})} | {int(k) for k in (project.get("fight_plans_pending") or {})})
    rows = []
    G = _G()
    for ch in chapters:
        b = fight_budget(project, ch)
        rows.append({"chapter": ch, "has_fight": b["plan_has_fight"], "budget": b["words"], "card": (project.get("fight_plans") or {}).get(str(ch)),
                     "pending": (project.get("fight_plans_pending") or {}).get(str(ch))})
    return {"ok": True, "chapters": rows, "dna": _dna_words(project), "beats": [{"key": k, "label": l, "share": s} for k, l, s, _ in BEATS],
            "sessions": {sid: {"chapter": s["chapter"], "step": s["step"]} for sid, s in (project.get("fight_sessions") or {}).items()}}


class StartRequest(BaseModel):
    project_id: str
    chapter: int
    foe: Optional[str] = None
    budget: Optional[int] = None
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
    action: str            # accept | decline | remove


class MovesRequest(BaseModel):
    project_id: str
    chapter: int
    foe: Optional[str] = None
    beat: Optional[str] = None


class BudgetRequest(BaseModel):
    project_id: str
    chapter: int
    budget: Optional[int] = None


@router.post("/budget")
def budget_preview(req: BudgetRequest):
    """The word budget, the foes in play and the hero's realm for a chapter, before the interview starts."""
    project = _load(req.project_id)
    foes = _foes_in_play(project, req.chapter)
    return {"ok": True, "budget": fight_budget(project, req.chapter, req.budget), "hero": _hero(project, req.chapter),
            "foes": [{"name": e["name"], "tier": e.get("tier"), "realm": e.get("realm", "")} for e in foes],
            "card": (project.get("fight_plans") or {}).get(str(req.chapter)), "pending": (project.get("fight_plans_pending") or {}).get(str(req.chapter))}


@router.post("/moves")
def moves(req: MovesRequest):
    """Corpus fight passages matched to this chapter's foe, one list per beat, each tagged for free. No AI call."""
    project = _load(req.project_id)
    foes = _foes_in_play(project, req.chapter)
    foe = next((e for e in foes if e["name"] == req.foe), None) or (foes[0] if foes else {})
    hero = _hero(project, req.chapter)
    out = {}
    for key, label, _, types in BEATS:
        if req.beat and req.beat != key:
            continue
        res = corpus_moves(_foe_query(foe, key, hero) or label, types, 10)
        res.sort(key=lambda r: (-(r["tags"]["beat"] == key), -r["tags"]["outmatched"], -r["score"]))      # beat first, then "he is outmatched", then closeness
        out[key] = res[:6]
    return {"ok": True, "foe": foe.get("name"), "moves": out}


def _options_for(project: dict, pid: str, session: dict, provider: Optional[str]) -> dict:
    G = _G()
    ch, step = session["chapter"], session["step"]
    key, label, share, types = BEATS[step]
    budget = session["budget"]
    beat_words = max(_MIN_BEAT_WORDS, round(budget * share))
    foes = _foes_in_play(project, ch)
    foe = next((e for e in foes if e["name"] == session["foe"]), None) or {"name": session["foe"] or "the opponent"}
    hero = _hero(project, ch)
    plan = _plan_of(project, ch) or {}
    corpus = corpus_moves(_foe_query(foe, key, hero) or label, types, 8)
    corpus.sort(key=lambda r: (-(r["tags"]["beat"] == key), -r["score"]))
    corpus = corpus[:3]
    try:
        from routers.pre_generation.canon import craft_context_block
        plan_block = craft_context_block(project, ch, "combat", 5000)
    except Exception:
        plan_block = ""
    done = "\n".join(f"- {b['label']} (~{b['words']} words): {b['text']}" for b in session["answers"]) or "(nothing yet)"
    used = {w for a in session["answers"] for w in a.get("weave", [])}
    left = [it for it in session.get("items") or [] if it["id"] not in used]
    weave_txt = ("THE CHAPTER ALSO CARRIES THESE PLANNED THINGS (still unplaced). Weave them INTO the fight where they fit naturally: a clue surfaces when "
                 "the hero reads a move or notices what the foe wears or where he looks; a reveal lands when a blow or a slip of the tongue knocks something loose; "
                 "a new face arrives as the fight ends; the foe's escalation shows in how he fights. An option may carry one or two; list their ids in \"weave\". Some of these belong to other scenes of the chapter, so carry only what fits THIS fight, and do not force one in:\n"
                 + "\n".join(f"  {it['id']} ({it['kind']}): {it['text']}" for it in left[:12]) + "\n\n") if left else ""
    ladder = ""
    try:
        from routers.pre_generation.castroster import _realm_ladder
        ladder = ", ".join(_realm_ladder(project))
    except Exception:
        pass
    prompt = (
        f"You are planning ONE beat of a fight scene for chapter {ch} of the web novel \"{project.get('title', '')}\". Do not write the scene; plan the beat.\n\n"
        f"{plan_block}\n\n"
        f"THE FIGHT: {hero['name']} (realm {hero['realm'] or 'unknown'}) against {foe.get('name')}"
        + (f" [{foe.get('tier')}, {foe.get('realm') or 'realm not set'}]: {str(foe.get('who') or '')[:240]}. Strength: {str(foe.get('strength') or '-')[:160]}. "
           f"Weakness: {str(foe.get('weakness') or '-')[:160]}. Obstructs by: {'; '.join(str(x)[:80] for x in (foe.get('how_they_obstruct') or [])[:2])}." if foe.get("who") else ".")
        + f"\nThe timeline says in this arc he can fight: {hero['fights'] or '-'}; only escape: {hero['escapes'] or '-'}; cannot touch: {hero['untouchable'] or '-'}.\n"
        f"The chapter plan: {str(plan.get('purpose') or '')[:240]} | key event: {str(plan.get('key_event') or '')[:300]}\n"
        f"THE WORD BUDGET: the whole fight is about {budget} words; this beat ({label}) gets about {beat_words}. "
        f"Beats chosen so far:\n{done}\n\n"
        f"{weave_txt}THIS BEAT: {label}.\n"
        + ("CORPUS PASSAGES THAT FIT THIS BEAT (adapt the mechanism to this book; never reuse a name, technique or place):\n"
           + "\n".join(f"  - [{c['novel_title']}; {c['tags']['beat']}; {', '.join(c['tags']['family']) or 'general'}] {c['text'][:360]}" for c in corpus) + "\n\n" if corpus else "")
        + "RULES: the hero is never a punching bag: he reads a technique as it begins, sees through it and dodges or counters, and the reversal is his. The "
          "foe uses only what fits his realm and strength. Keep to the realm-gap rule" + (f" (realms: {ladder})" if ladder else "") + ". Nobody sees the hero's "
          "hidden source of power or hears his hidden mentor. No secrets. Three DIFFERENT options (different moves, not rewordings). Each option's "
          f"'words' is the words this beat would take: between {_MIN_BEAT_WORDS} and {round(beat_words * 1.5)}, near {beat_words} unless the option is deliberately "
          "brief or long.\n\n"
          "Reply with ONE JSON object, no fences: {\"options\": [{\"label\": \"under 8 words\", \"text\": \"1-2 sentences: what happens in this beat\", "
          "\"words\": 0, \"source\": \"corpus novel it adapts, or empty\", \"weave\": [\"ids of planned things this option carries, or none\"]}], \"recommended\": 0}")
    prov = provider or G._get_generation_cfg().get("default_provider", "anthropic")
    model, key_ = (G._get_models_cfg() or {}).get(prov, ""), G._get_key(prov)
    opts, data = None, None
    for _try in range(2):                      # the first call after a restart sometimes comes back unusable: one automatic retry
        raw = G._call_llm(prompt, prov, model, key_, timeout=900, abort_key=(pid, "fightplan"))
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
    out = []
    for o in opts[:3]:
        if not isinstance(o, dict) or not str(o.get("text") or "").strip():
            continue
        w = max(_MIN_BEAT_WORDS, min(round(beat_words * 1.5), _int(o.get("words")) or beat_words))
        ids = {it["id"] for it in left}
        out.append({"label": _no_ledger(str(o.get("label") or "Option"))[:80], "text": _no_ledger(str(o["text"]).strip())[:500], "words": w,
                    "source": str(o.get("source") or "")[:80], "over": bool(running + w > budget * 1.1),
                    "weave": [x for x in (o.get("weave") or []) if isinstance(x, str) and x in ids][:2]})
    if not out:
        raise HTTPException(502, "The AI's reply wasn't usable options for this beat. Nothing was changed: try again.")
    rec = _int((data or {}).get("recommended")) or 0
    return {"beat": {"key": key, "label": label, "words": beat_words, "step": step + 1, "of": len(BEATS)}, "options": out,
            "recommended": rec if 0 <= rec < len(out) else 0, "running": running, "budget": budget, "items": session.get("items") or [], "left": [it["id"] for it in left],
            "corpus": [{"novel_title": c["novel_title"], "text": c["text"][:240], "tags": c["tags"]} for c in corpus]}


@router.post("/start")
def start(req: StartRequest):
    project = _load(req.project_id)
    b = fight_budget(project, req.chapter, req.budget)
    foes = _foes_in_play(project, req.chapter)
    foe = next((e for e in foes if e["name"] == req.foe), None) or (foes[0] if foes else None)
    sid = f"fp{int(time.time() * 1000) % 10**10}"
    session = {"id": sid, "chapter": req.chapter, "foe": foe["name"] if foe else (req.foe or ""), "budget": b["words"], "step": 0, "answers": [],
               "notes": b["notes"], "items": weave_items(project, req.chapter, foe)}
    res = _options_for(project, req.project_id, session, req.provider)
    session["_options"] = res["options"]
    project = _load(req.project_id)                     # re-read: the AI call was slow
    project.setdefault("fight_sessions", {})[sid] = session
    _save(req.project_id, project)
    return {"ok": True, "session_id": sid, "chapter": req.chapter, "foe": session["foe"], "foes": [e["name"] for e in foes], "notes": b["notes"], **res}


def _assemble(project: dict, session: dict) -> dict:
    hero = _hero(project, session["chapter"])
    foe = next((e for e in _foes_in_play(project, session["chapter"]) if e["name"] == session["foe"]), {})
    ans = session["answers"]
    total = sum(a["words"] for a in ans) or 1
    scaled = [max(_MIN_BEAT_WORDS, round(a["words"] * session["budget"] / total)) for a in ans]
    scaled[-1] += session["budget"] - sum(scaled)      # the beats add up to the budget exactly
    items = {it["id"]: it for it in session.get("items") or []}
    beats = [{"key": a["key"], "label": a["label"], "text": a["text"], "words": w, "source": a.get("source", ""),
              "weave": [{"kind": items[i]["kind"], "text": items[i]["text"]} for i in a.get("weave", []) if i in items]} for a, w in zip(ans, scaled)]
    used = {i for a in ans for i in a.get("weave", [])}
    unplaced = [{"kind": it["kind"], "text": it["text"]} for it in session.get("items") or [] if it["id"] not in used]
    return {"unplaced": unplaced, "chapter": session["chapter"], "foe": session["foe"], "foe_realm": foe.get("realm", ""), "hero_realm": hero["realm"], "budget": session["budget"],
            "beats": beats, "created": time.strftime("%Y-%m-%d %H:%M"), "status": "proposed"}


@router.post("/answer")
def answer(req: AnswerRequest):
    project = _load(req.project_id)
    session = (project.get("fight_sessions") or {}).get(req.session_id)
    if not session:
        raise HTTPException(404, "This fight interview is no longer open. Start it again.")
    if req.back:
        if session["step"] == 0:
            raise HTTPException(400, "This is the first question.")
        session["step"] -= 1
        session["answers"] = session["answers"][:session["step"]]
        res = _options_for(project, req.project_id, session, req.provider)
        session["_options"] = res["options"]
        project = _load(req.project_id)
        project.setdefault("fight_sessions", {})[req.session_id] = session
        _save(req.project_id, project)
        return {"ok": True, "done": False, **res}
    key, label = BEATS[session["step"]][0], BEATS[session["step"]][1]
    if req.custom and req.custom.strip():
        w = max(_MIN_BEAT_WORDS, req.custom_words or round(session["budget"] * BEATS[session["step"]][2]))
        picked = {"key": key, "label": label, "text": req.custom.strip()[:500], "words": w, "source": "", "weave": []}
    else:
        opts = session.get("_options") or []
        if req.choice is None or not (0 <= req.choice < len(opts)):
            raise HTTPException(400, "Pick one of the options, or write your own.")
        o = opts[req.choice]
        picked = {"key": key, "label": label, "text": o["text"], "words": o["words"], "source": o.get("source", ""), "weave": o.get("weave", [])}
    session["answers"] = session["answers"][:session["step"]] + [picked]
    session["step"] += 1
    if session["step"] >= len(BEATS):
        card = _assemble(project, session)
        project = _load(req.project_id)
        project.setdefault("fight_plans_pending", {})[str(session["chapter"])] = card
        (project.get("fight_sessions") or {}).pop(req.session_id, None)
        _save(req.project_id, project)
        return {"ok": True, "done": True, "card": card}
    res = _options_for(project, req.project_id, session, req.provider)
    session["_options"] = res["options"]
    project = _load(req.project_id)
    project.setdefault("fight_sessions", {})[req.session_id] = session
    _save(req.project_id, project)
    return {"ok": True, "done": False, **res}


@router.post("/decide")
def decide(req: DecideRequest):
    project = _load(req.project_id)
    ch = str(req.chapter)
    if req.action == "accept":
        card = (project.get("fight_plans_pending") or {}).pop(ch, None)
        if not card:
            raise HTTPException(400, "There is no proposed fight card for this chapter.")
        card["status"] = "accepted"
        project.setdefault("fight_plans", {})[ch] = card
    elif req.action == "decline":
        (project.get("fight_plans_pending") or {}).pop(ch, None)
    elif req.action == "remove":
        (project.get("fight_plans") or {}).pop(ch, None)
    else:
        raise HTTPException(400, "action must be accept, decline or remove")
    _save(req.project_id, project)
    return {"ok": True}
