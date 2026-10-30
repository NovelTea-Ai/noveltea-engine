"""Chapter LORE cards (Pre- and Post-generation tab): the WHY behind what happens in a chapter, kept apart from the prose and the plan.

A card holds where/when/atmosphere, why each event happens, ongoing background, who knows what, and what must stay hidden from the
reader (shown by action, never explained). It is drafted from the plan, the world lore, the Foes roster and the earlier chapters, edited by
the author, and fed into the chapter prompt as canon. After a chapter is read or listened to, the author's feedback becomes a change to the
CARD (shown as a difference, approved by the author), and only the paragraphs that change touches are rewritten, through the same paragraph
write the gate's click-to-fix uses (version archived, re-indexed, audio cleared). Stored at project["lore"] = {"chapters": {"<n>": card}}."""
import json
import re
import time
import copy
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


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


def _llm(project_id: str, provider: Optional[str] = None):
    G = _G()
    prov = provider or G._get_generation_cfg().get("default_provider", "anthropic")
    return prov, (G._get_models_cfg() or {}).get(prov, ""), G._get_key(prov)


def _clean_card(c: dict) -> dict:
    out = {}
    for k in ("where", "when", "atmosphere", "summary"):
        out[k] = str((c or {}).get(k) or "").strip()[:600]
    for k in ("background", "reader_hidden"):
        v = (c or {}).get(k) or []
        out[k] = [str(x).strip()[:400] for x in (v if isinstance(v, list) else [v]) if str(x).strip()][:12]
    why = []
    for w in (c or {}).get("why") or []:
        if isinstance(w, dict) and str(w.get("event") or "").strip():
            why.append({"event": str(w["event"]).strip()[:240], "because": str(w.get("because") or "").strip()[:500]})
        elif isinstance(w, str) and w.strip():
            why.append({"event": w.strip()[:240], "because": ""})
    out["why"] = why[:14]
    kn = []
    for k in (c or {}).get("knowledge") or []:
        if isinstance(k, dict) and str(k.get("who") or "").strip():
            kn.append({"who": str(k["who"]).strip()[:80], "knows": str(k.get("knows") or "").strip()[:300],
                       "hidden_from": str(k.get("hidden_from") or "").strip()[:200]})
    out["knowledge"] = kn[:12]
    out["history"] = [h for h in ((c or {}).get("history") or []) if isinstance(h, dict)][-30:]
    out["status"] = str((c or {}).get("status") or "draft")
    out["updated"] = (c or {}).get("updated") or int(time.time())
    return out


def _clean_entry(e: dict, i: int = 0) -> dict:
    e = e if isinstance(e, dict) else {}
    return {"id": str(e.get("id") or f"w{int(time.time() * 1000) % 10**9}{i}"),
            "title": str(e.get("title") or "").strip()[:120],
            "kind": str(e.get("kind") or "").strip()[:40],
            "text": str(e.get("text") or "").strip()[:1500],
            "status": "approved" if e.get("status") == "approved" else "draft"}


_LORE_WORD = re.compile(r"[a-z][a-z'-]{3,}")
_LORE_STOP = {"that", "this", "with", "from", "they", "their", "them", "have", "into", "only", "every", "which", "what", "when",
              "where", "there", "been", "were", "will", "than", "then", "each", "more", "most", "over", "under", "city"}


def _chapter_focus(project: dict, ch: int) -> str:
    """What chapter ch is about: its plan and its timeline events (for ranking the lore it needs most)."""
    sk = next((c for c in (project.get("chapter_skeletons") or []) if isinstance(c, dict) and c.get("number") == ch), None) or {}
    evs = [e for e in ((project.get("timeline") or {}).get("events") or []) if isinstance(e, dict) and e.get("chapter") == ch]
    return " ".join([json.dumps(sk, ensure_ascii=False)[:6000]] + [f"{e.get('title')} {e.get('mc_sees') or ''}" for e in evs])


def world_lore_block(project: dict, cap: int = 7000, focus: str = "") -> str:
    """The project-wide lore (Pre-generation Lore tab): approved entries only. Not tied to any chapter. With a focus (the
    chapter's plan and timeline), the entries it touches come first, so the cap trims the ones it needs least."""
    items = [e for e in (((project.get("lore") or {}).get("world")) or []) if isinstance(e, dict) and e.get("status") == "approved" and e.get("text")]
    if not items:
        return ""
    if focus:
        fw = {w for w in _LORE_WORD.findall(focus.lower()) if w not in _LORE_STOP}
        def score(e):
            ew = {w for w in _LORE_WORD.findall(f"{e.get('title')} {e.get('text')}".lower()) if w not in _LORE_STOP}
            return len(ew & fw) / (1 + len(ew) ** 0.5)
        items = sorted(items, key=score, reverse=True)
    lines = ["ESTABLISHED LORE OF THIS WORLD (the author's canon: it is BACKGROUND, never explain it in narration, show it only through what people do, say and notice):"]
    for e in items:
        lines.append(f"- {e.get('title') or 'Lore'}: {e['text']}")
    return "\n".join(lines)[:cap]


def lore_block(project: dict, ch: int, cap: int = 3800) -> str:
    """The project-wide lore plus the chapter's lore card (canon for the chapter). A draft is never included."""
    wl = world_lore_block(project, focus=_chapter_focus(project, ch))
    card = ((project.get("lore") or {}).get("chapters") or {}).get(str(ch))
    if not isinstance(card, dict) or card.get("status") != "approved":     # a draft is for the author to read; only an approved card is canon
        return wl
    lines = [f"WHY THIS CHAPTER'S EVENTS HAPPEN (the author's lore for chapter {ch} - canon; it is BACKGROUND: never explain it in narration, "
             "show it only through what people do, say and notice):"]
    place = " | ".join(x for x in (card.get("where"), card.get("when"), card.get("atmosphere")) if x)
    if place:
        lines.append(f"SETTING: {place}")
    for w in card.get("why") or []:
        lines.append(f"- {w.get('event')} BECAUSE {w.get('because')}")
    if card.get("background"):
        lines.append("ONGOING BACKGROUND: " + " ".join(card["background"]))
    for k in card.get("knowledge") or []:
        lines.append(f"- {k.get('who')} knows: {k.get('knows')}" + (f" (hidden from: {k.get('hidden_from')})" if k.get("hidden_from") else ""))
    if card.get("reader_hidden"):
        lines.append("MUST STAY UNEXPLAINED TO THE READER (action only): " + " ".join(card["reader_hidden"]))
    out = "\n".join(lines)[:cap]
    return (wl + "\n\n" + out) if wl else out


# ── endpoints ───────────────────────────────────────────────────────────────────────────────────────────────────────────
@router.get("/{project_id}")
def get_lore(project_id: str):
    G = _G()
    project = _load(project_id)
    cards = (project.get("lore") or {}).get("chapters") or {}
    plans = sorted(c["number"] for c in (project.get("chapter_skeletons") or []) if isinstance(c, dict) and isinstance(c.get("number"), int))
    written = sorted(G._written_chapter_numbers(project_id)) if hasattr(G, "_written_chapter_numbers") else []
    return {"ok": True, "cards": cards, "plans": plans, "written": written, "world": (project.get("lore") or {}).get("world") or []}


class DraftRequest(BaseModel):
    project_id: str
    chapter: int
    provider: Optional[str] = None


def _store(project: dict, pid: str, ch: int, card: dict, note: Optional[str] = None, status: Optional[str] = None):
    lore = project.setdefault("lore", {"chapters": {}})
    chapters = lore.setdefault("chapters", {})
    old = chapters.get(str(ch))
    if old:
        project.setdefault("_field_history", {}).setdefault("lore", []).append({"chapter": ch, "card": copy.deepcopy(old)})
        project["_field_history"]["lore"] = project["_field_history"]["lore"][-40:]
    new = _clean_card({**card, "history": (old or {}).get("history") or card.get("history") or []})
    if note:
        new["history"].append({"ts": int(time.time()), "note": note[:600]})
    if status:
        new["status"] = status
    new["updated"] = int(time.time())
    chapters[str(ch)] = new
    _save(pid, project)
    return new


@router.post("/draft")
def draft_card(req: DraftRequest):
    """Draft this chapter's card from the plan, the world lore, the Foes roster, the earlier chapter and (if it is written) the chapter itself."""
    G = _G()
    pid, ch = req.project_id, req.chapter
    project = _load(pid)
    plan = next((c for c in (project.get("chapter_skeletons") or []) if isinstance(c, dict) and c.get("number") == ch), None)
    if not plan:
        raise HTTPException(400, f"Chapter {ch} has no plan to draw a card from.")
    gen = G.CORPUS_PATH / "generated" / pid
    text = (gen / f"ch{ch:03d}_generated.txt").read_text(encoding="utf-8") if (gen / f"ch{ch:03d}_generated.txt").exists() else ""
    prev = ""
    if ch > 1 and (gen / f"ch{ch - 1:03d}_generated.txt").exists():
        prev = " ".join((gen / f"ch{ch - 1:03d}_generated.txt").read_text(encoding="utf-8").split()[-500:])
    wb = project.get("world_bible") or {}
    world = "\n".join(f"- {r}" for r in (wb.get("rules") or [])[:8])
    try:
        from routers.pre_generation.antagonists import antagonists_block
        foes = antagonists_block(project, ch, cap=3500)
    except Exception:
        foes = ""
    prov, model, key = _llm(pid, req.provider)
    scenes = [{"scene": s.get("scene_number"), "type": s.get("scene_type"), "notes": s.get("structure_notes")} for s in (plan.get("scenes") or []) if isinstance(s, dict)]
    prompt = (
        f"You are writing the LORE CARD for chapter {ch} of \"{project.get('title', '')}\": the WHY behind what happens in it, as background the author can read and edit.\n\n"
        f"PREMISE: {project.get('premise') or (project.get('creative_brief') or {}).get('premise', '')}\n\nWORLD LORE (canon):\n{world}\n"
        + f"\n{foes}\n\nTHIS CHAPTER'S PLAN: purpose: {plan.get('purpose')}; key event: {plan.get('key_event')}; scenes: {json.dumps(scenes, ensure_ascii=False)[:5000]}\n\n"
        + (f"THE END OF THE PREVIOUS CHAPTER:\n{prev}\n\n" if prev else "")
        + (f"THE WRITTEN CHAPTER (the card must explain why the events in it happen and must not contradict it):\n{text[:9000]}\n\n" if text else "")
        + "Write the card as ONE JSON object, no markdown fences:\n"
        "{\"summary\": \"one sentence\", \"where\": \"the place and what state it is in tonight\", \"when\": \"time of day / season / what point in the world's calendar\", "
        "\"atmosphere\": \"weather, sounds, mood\", \"why\": [{\"event\": \"something that happens in the chapter\", \"because\": \"the cause in this world - a faction's "
        "aim, an institution, the land itself, a person's motive\"}], \"background\": [\"2-4 ongoing things the chapter sits inside\"], "
        "\"knowledge\": [{\"who\": \"name\", \"knows\": \"what they know or believe\", \"hidden_from\": \"who must not learn it\"}], "
        "\"reader_hidden\": [\"things the prose must NOT explain - show by action only, e.g. what a key object is, who the hidden antagonist is\"]}\n"
        "Give a cause for EVERY notable event, grounded in the world lore, in plain concrete language. Do not invent new factions, techniques or artifacts.")
    raw = G._call_llm(prompt, prov, model, key, timeout=600, abort_key=(pid, "lore"))
    try:
        data = G._parse_json_from_text(raw)
    except Exception:
        data = None
    if not isinstance(data, dict) or not data.get("why"):
        raise HTTPException(502, "The AI's reply wasn't a usable lore card, so nothing was saved. Try again.")
    card = _store(project, pid, ch, data, note="Drafted from the plan" + (" and the written chapter" if text else ""), status="draft")
    return {"ok": True, "card": card}


class SaveRequest(BaseModel):
    project_id: str
    chapter: int
    card: dict
    approve: bool = False


@router.post("/save")
def save_card(req: SaveRequest):
    project = _load(req.project_id)
    card = _store(project, req.project_id, req.chapter, req.card, note="Edited by the author", status="approved" if req.approve else None)
    return {"ok": True, "card": card}


class UndoRequest(BaseModel):
    project_id: str
    chapter: int


@router.post("/undo")
def undo_card(req: UndoRequest):
    project = _load(req.project_id)
    hist = (project.get("_field_history") or {}).get("lore") or []
    idx = next((i for i in range(len(hist) - 1, -1, -1) if hist[i].get("chapter") == req.chapter), None)
    if idx is None:
        raise HTTPException(400, "Nothing to undo for this chapter's card.")
    entry = hist.pop(idx)
    project["lore"]["chapters"][str(req.chapter)] = entry["card"]
    _save(req.project_id, project)
    return {"ok": True, "card": entry["card"]}


class FeedbackRequest(BaseModel):
    project_id: str
    chapter: int
    feedback: str
    provider: Optional[str] = None


@router.post("/feedback")
def propose_change(req: FeedbackRequest):
    """Turn the author's feedback (after reading or listening) into a PROPOSED change to the chapter's card. Nothing is saved."""
    G = _G()
    pid, ch = req.project_id, req.chapter
    if not req.feedback.strip():
        raise HTTPException(400, "Say what you want changed.")
    project = _load(pid)
    card = ((project.get("lore") or {}).get("chapters") or {}).get(str(ch))
    if not card:
        raise HTTPException(400, "This chapter has no lore card yet: draft one first.")
    gen = G.CORPUS_PATH / "generated" / pid
    text = (gen / f"ch{ch:03d}_generated.txt").read_text(encoding="utf-8") if (gen / f"ch{ch:03d}_generated.txt").exists() else ""
    prov, model, key = _llm(pid, req.provider)
    base = {k: v for k, v in card.items() if k not in ("history", "status", "updated")}
    prompt = (
        f"The author has read or listened to chapter {ch} and given feedback. Turn it into a CHANGE TO THE LORE CARD (the why behind the chapter), not to the prose.\n\n"
        f"CURRENT CARD:\n{json.dumps(base, ensure_ascii=False)}\n\n"
        + (f"THE CHAPTER (for reference):\n{text[:9000]}\n\n" if text else "")
        + f"AUTHOR'S FEEDBACK:\n{req.feedback.strip()}\n\n"
        "Update the card so the feedback is true in this world: add or change causes, background, knowledge, or the setting. Keep everything the feedback does not "
        "touch exactly as it is. If the feedback is about something that should stay unexplained, put it under reader_hidden instead.\n"
        "Output ONE JSON object, no fences: {\"changes\": [\"one plain sentence per change\"], \"card\": <the full updated card, same shape>}")
    raw = G._call_llm(prompt, prov, model, key, timeout=600, abort_key=(pid, "lore"))
    try:
        data = G._parse_json_from_text(raw)
    except Exception:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("card"), dict):
        raise HTTPException(502, "The AI's reply wasn't a usable change, so nothing was proposed. Try again.")
    return {"ok": True, "changes": [str(c)[:300] for c in (data.get("changes") or [])][:10], "card": _clean_card(data["card"]), "current": _clean_card(card)}


class ApplyRequest(BaseModel):
    project_id: str
    chapter: int
    card: dict
    feedback: str
    provider: Optional[str] = None


@router.post("/apply")
def apply_change(req: ApplyRequest):
    """Save the approved card, then rewrite ONLY the paragraphs the change touches. Each is written through the gate's own paragraph write:
    the previous text is archived as a version, the chapter re-indexes, and narration audio is cleared."""
    G = _G()
    pid, ch = req.project_id, req.chapter
    project = _load(pid)
    card = _store(project, pid, ch, req.card, note="Feedback: " + req.feedback.strip()[:500], status="approved")
    draft = G._load_chapter_parts(pid, ch)
    if not draft["parts"]:
        return {"ok": True, "card": card, "edited": [], "message": "The card is saved. This chapter has no text yet, so nothing was rewritten."}
    paras = [p for part in draft["parts"] for p in G._paragraphs_of(part)]
    numbered = "\n".join(f"[{i}] {p}" for i, p in enumerate(paras))[:60000]
    prov, model, key = _llm(pid, req.provider)
    prompt = (
        f"You are a surgical prose editor. The author changed the LORE for chapter {ch} after reading it. Rewrite ONLY the paragraphs that must change so the chapter "
        "reflects the lore and the feedback, and leave every other paragraph exactly as it is.\n\n"
        f"AUTHOR'S FEEDBACK:\n{req.feedback.strip()}\n\nUPDATED LORE CARD:\n{lore_block({'lore': {'chapters': {str(ch): card}}}, ch)}\n\n"
        f"THE CHAPTER, numbered by paragraph:\n{numbered}\n\n"
        "RULES:\n1. Change as little as possible: at most 6 paragraphs; prefer adding a line or two to an existing paragraph over rewriting a scene.\n"
        "2. SHOW the lore by what people do, say, notice or fear. Never explain it in narration or add an exposition paragraph.\n"
        "3. Keep the voice: short sentences, plain physical comparisons only (weather, animals, stone, blades), NO bookish or paperwork comparisons, no semicolons.\n"
        "4. Keep every name, fact and line of dialogue that the change does not touch. Keep each rewritten paragraph within about 40% of its old length.\n"
        "5. A paragraph may become two or three paragraphs (separate them with a blank line).\n"
        "Output ONLY this JSON, no fences: {\"edits\": [{\"paragraph\": <number>, \"new_text\": \"...\", \"why\": \"one short phrase\"}], \"summary\": \"one sentence\"}")
    raw = G._call_llm(prompt, prov, model, key, timeout=900, abort_key=(pid, "lore"))
    try:
        data = G._parse_json_from_text(raw)
    except Exception:
        data = None
    edits = data.get("edits") if isinstance(data, dict) else None
    if not isinstance(edits, list):
        raise HTTPException(502, "The AI's reply wasn't usable edits. The card is saved; nothing was rewritten. Try again.")
    clean, seen = [], set()
    for e in edits:
        try:
            i = int(e.get("paragraph"))
        except Exception:
            continue
        nt = str(e.get("new_text") or "").strip()
        if 0 <= i < len(paras) and i not in seen and nt and nt != paras[i]:
            seen.add(i)
            clean.append((i, nt, str(e.get("why") or "")[:120]))
    clean = sorted(clean)[:6]
    if not clean:
        return {"ok": True, "card": card, "edited": [], "message": "The card is saved. The AI found no paragraph that needed to change."}
    done = []
    for i, nt, why in sorted(clean, reverse=True):          # last paragraph first, so earlier indexes stay valid
        draft = G._load_chapter_parts(pid, ch)
        flat = 0
        for part_i, part_text in enumerate(draft["parts"]):
            n = len(G._paragraphs_of(part_text))
            if i < flat + n:
                local = i - flat
                old = G._paragraphs_of(part_text)[local]
                new_part = G._replace_nth_paragraph(part_text, local, nt)
                G._gate_write_paragraph(pid, ch, draft, part_i, local, part_text, new_part, nt)
                done.append({"paragraph": i, "why": why, "before": old[:260], "after": nt[:600]})
                break
            flat += n
    done.sort(key=lambda d: d["paragraph"])
    marks = 0
    try:
        final = G._load_chapter_parts(pid, ch)
        for pr in G._gate_part_marks("\n\n".join(final["parts"]))["paragraphs"]:
            marks += 1 if pr["failures"] else 0
    except Exception:
        marks = -1
    G._progress_log(pid, f"LORE: chapter {ch}: rewrote {len(done)} paragraph(s) from the changed card", "success")
    return {"ok": True, "card": card, "edited": done, "summary": str(data.get("summary") or "")[:300], "orange_after": marks}


# ── project-wide lore (not locked to chapters) ───────────────────────────────────────────────────────────────────────────
class WorldSaveRequest(BaseModel):
    project_id: str
    entries: list


@router.post("/world/save")
def world_save(req: WorldSaveRequest):
    """Replace the project-wide lore list. Each entry: title, kind, text, status (draft | approved)."""
    project = _load(req.project_id)
    lore = project.setdefault("lore", {"chapters": {}})
    old = lore.get("world") or []
    if old:
        project.setdefault("_field_history", {}).setdefault("lore_world", []).append({"world": copy.deepcopy(old)})
        project["_field_history"]["lore_world"] = project["_field_history"]["lore_world"][-20:]
    lore["world"] = [_clean_entry(e, i) for i, e in enumerate(req.entries or [])
                     if isinstance(e, dict) and (str(e.get("title") or "").strip() or str(e.get("text") or "").strip())][:60]
    _save(req.project_id, project)
    return {"ok": True, "world": lore["world"]}


def _canon_visible(project: dict) -> str:
    try:
        from routers.pre_generation.canon import canon_context_block
        b = canon_context_block(project, "visible", skip=("lore",), cap=6000)
        return (b + "\n\n") if b else ""
    except Exception:
        return ""


class WorldDraftRequest(BaseModel):
    project_id: str
    note: Optional[str] = None
    provider: Optional[str] = None


@router.post("/world/draft")
def world_draft(req: WorldDraftRequest):
    """Suggest new lore entries from the premise, the world rules and the existing lore. They are added as DRAFTS for the author to edit and approve."""
    G = _G()
    pid = req.project_id
    project = _load(pid)
    wb = project.get("world_bible") or {}
    rules = "\n".join(f"- {r}" for r in (wb.get("rules") or []))
    have = "\n".join(f"- {e.get('title')}: {e.get('text')}" for e in ((project.get("lore") or {}).get("world") or []))
    prov, model, key = _llm(pid, req.provider)
    prompt = (
        f"You are helping the author build the LORE of the web novel \"{project.get('title', '')}\": the history, forces and facts behind the world, written as background, not as plot.\n\n"
        f"PREMISE: {project.get('premise') or (project.get('creative_brief') or {}).get('premise', '')}\n\nWORLD RULES (canon):\n{rules}\n\n"
        + (f"LORE ALREADY WRITTEN (do not repeat it):\n{have}\n\n" if have else "")
        + _canon_visible(project)
        + (f"THE AUTHOR ASKS FOR: {req.note}\n\n" if (req.note or "").strip() else "")
        + "Suggest 5 to 8 NEW lore entries that deepen the world and fit the rules above (history, how the city really works, powers, customs, places, why things are the way they are). "
        "Do not invent anything that contradicts the rules. Reply with ONE JSON object, no markdown fences: "
        "{\"entries\": [{\"title\": \"short name\", \"kind\": \"history | power | place | custom | rule\", \"text\": \"2-4 plain sentences\"}]}")
    raw = G._call_llm(prompt, prov, model, key, timeout=600, abort_key=(pid, "lore"))
    try:
        data = G._parse_json_from_text(raw)
    except Exception:
        data = None
    ents = (data or {}).get("entries") if isinstance(data, dict) else None
    if not ents:
        raise HTTPException(502, "The AI's reply wasn't usable lore, so nothing was saved. Try again.")
    lore = project.setdefault("lore", {"chapters": {}})
    world = lore.setdefault("world", [])
    for i, e in enumerate(ents):
        if isinstance(e, dict) and str(e.get("text") or "").strip():
            world.append(_clean_entry({**e, "status": "draft"}, len(world) + i))
    _save(pid, project)
    return {"ok": True, "world": world}
