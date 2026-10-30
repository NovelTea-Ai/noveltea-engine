"""One shared CANON block for every generator, so each one sees the tabs the author has built: the approved Lore, the Cast, the Foes, the
book's standing rules (craft notes), the Timeline (the hero's realm and place per arc, the author's events) and, for planning generators
only, the Conspiracy tree marked secret.

scope "visible": no secrets (premise, tagline, themes, lore suggestions).
scope "plan":    everything, the Conspiracy marked SECRET (arcs, chapter plans, cast, foes, world, systems).
A caller that already adds one of the parts itself passes it in `skip` (lore, cast, foes, rules, timeline, conspiracy)."""
from typing import Optional

def hero_name(project: dict) -> str:
    """The protagonist's name for this project (every book has its own), never a hard-coded one."""
    for k in ("protagonist_name", "protagonist"):
        v = project.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    for c in project.get("character_list") or []:
        if isinstance(c, dict) and str(c.get("role", "")).lower() == "protagonist" and c.get("name"):
            return c["name"]
    return "the hero"


RULE_KEYS = [("combat_rule", "COMBAT"), ("realm_gap", "REALM GAP"), ("treasure_rules", "THE TREASURE"), ("economy", "ECONOMY"),
             ("face_slaps", "FACE-SLAPS"), ("clues_and_questions", "CLUES"), ("romance", "ROMANCE"), ("beast_tide", "BEAST TIDE")]


def cast_block(project: dict, cap: int = 3000) -> str:
    cl = [c for c in (project.get("character_list") or []) if isinstance(c, dict) and c.get("name")]
    if not cl:
        return ""
    return ("THE CAST (canon; reuse these people, keep their names and roles; do not duplicate them under new names):\n"
            + "\n".join(f"- {c['name']} ({c.get('role', '')}; {c.get('faction', '')}): {str(c.get('archetype', ''))[:150]}" for c in cl))[:cap]


def rules_block(project: dict, cap: int = 5600) -> str:
    cn = project.get("craft_notes") or {}
    if not isinstance(cn, dict):
        return ""
    lines = [f"- {label}: {str(cn[k])[:650]}" for k, label in RULE_KEYS if cn.get(k)]
    return ("THE BOOK'S STANDING RULES (canon, never break them):\n" + "\n".join(lines))[:cap] if lines else ""


def _arcs(project: dict):
    try:
        from routers.pre_generation.conspiracy import book_volumes
        c = project.get("conspiracy") or {}
        total = int(c.get("book_chapters") or project.get("target_chapters") or 1500)
        return book_volumes(total, c.get("arcs_total"))
    except Exception:
        return []


def arc_of(project: dict, ch: int) -> Optional[int]:
    for v in _arcs(project):
        if v["chapters"][0] <= ch <= v["chapters"][1]:
            return v["volume"]
    return None


def timeline_block(project: dict, first: Optional[int] = None, last: Optional[int] = None, cap: int = 3500, events: bool = True) -> str:
    """The hero's realm and place for each arc (the arcs overlapping first..last, or the whole book), plus the author's timeline events there."""
    tl = project.get("timeline") or {}
    info = tl.get("arcs") or {}
    vols = _arcs(project)
    if first is not None:
        last = last or first
        vols = [v for v in vols if v["chapters"][1] >= first and v["chapters"][0] <= last]
    hero = hero_name(project)
    lines = []
    for v in vols:
        i = info.get(str(v["volume"])) or {}
        if not i:
            continue
        lines.append(f"- Arc {v['volume']} (ch {v['chapters'][0]}-{v['chapters'][1]}), {i.get('place', '')}: {hero} {i.get('realm', '')}. "
                     f"Can fight: {i.get('fights', '-')}. Only escape: {i.get('escapes', '-')}. Untouchable: {i.get('untouchable', '-')}.")
    if events:
        evs = [e for e in (tl.get("events") or []) if isinstance(e, dict) and e.get("chapter")]
        if first is not None:
            evs = [e for e in evs if first <= e["chapter"] <= last or (e.get("end_chapter") and e["chapter"] <= last and e["end_chapter"] >= first)]
        for e in sorted(evs, key=lambda x: x["chapter"])[:60]:
            span = f"-{e['end_chapter']}" if e.get("end_chapter") else ""
            lines.append(f"  ch {e['chapter']}{span} [{e.get('category')}] {e.get('title')}" + (f": {str(e.get('mc_sees'))[:140]}" if e.get("mc_sees") else ""))
    if not lines:
        return ""
    return (f"THE TIMELINE (the author's plan, chapter by chapter, from {hero}'s point of view; follow it):\n" + "\n".join(lines))[:cap]


def canon_context_block(project: dict, scope: str = "plan", first: Optional[int] = None, last: Optional[int] = None,
                        skip=(), cap: int = 16000) -> str:
    parts = []
    if "lore" not in skip:
        try:
            from routers.pre_generation.lore import world_lore_block
            wl = world_lore_block(project)
            if wl:
                parts.append(wl)
        except Exception:
            pass
    if "rules" not in skip:
        rb = rules_block(project)
        if rb:
            parts.append(rb)
    if "cast" not in skip:
        cb = cast_block(project)
        if cb:
            parts.append(cb)
    if "foes" not in skip:
        try:
            from routers.pre_generation.antagonists import roster_overview_block
            fb = roster_overview_block(project, first or 1, last or 100000)
            if fb:
                parts.append(fb)
        except Exception:
            pass
    if "timeline" not in skip:
        tb = timeline_block(project, first, last)
        if tb:
            parts.append(tb)
    if scope == "plan" and "conspiracy" not in skip:
        try:
            from routers.pre_generation.conspiracy import conspiracy_planner_block
            pb = conspiracy_planner_block(project, cap=5000)
            if pb:
                parts.append(pb)
        except Exception:
            pass
    if not parts:
        return ""
    return ("━━ THE BOOK'S CANON (from the author's Lore, Cast, Foes, Rules, Timeline and Plot tabs; it overrides anything older) ━━\n"
            + "\n\n".join(parts))[:cap]


def craft_context_block(project: dict, chapter: Optional[int] = None, kind: str = "humor", cap: int = 8000) -> str:
    """The book's plan for the humor and combat generators: lore, standing rules, the timeline (the hero's realm, who he fights, escapes
    and cannot touch), the foes, the arc, and what the Plot tree plants, in its WRITER-SAFE form (surfaces only, no truth, no schemes).
    Their output reaches the writer, so nothing secret goes in. With a chapter: that chapter's neighbourhood, the foes in play, who is
    around with their voices. Without: the whole book, with the foes' strengths and weaknesses."""
    parts = []
    lo = hi = chapter
    try:                                              # in priority order, each capped, so the timeline is never cut off by the lore
        tb = timeline_block(project, lo, hi, cap=2800 if chapter else 3200, events=True)
        if tb:
            parts.append(tb)
        rb = rules_block(project, cap=2600)
        if rb:
            parts.append(rb)
        from routers.pre_generation.lore import world_lore_block
        wl = world_lore_block(project)
        if wl:
            parts.append(wl[:1800])
    except Exception:
        pass
    if chapter:
        try:                                              # the chapter plan: this chapter's skeleton and its neighbours'
            sk = {c.get("number"): c for c in (project.get("chapter_skeletons") or []) if isinstance(c, dict)}
            rows = []
            for k, label in ((chapter - 1, "PREVIOUS"), (chapter, "THIS CHAPTER"), (chapter + 1, "NEXT")):
                c = sk.get(k)
                if c:
                    rows.append(f"- {label} (ch {k}): " + "; ".join(f"{f}: {str(c.get(f))[:220]}" for f in
                                                                     ("purpose", "key_event", "conflict", "fight", "hook") if c.get(f)))
            if rows:
                parts.append("THE CHAPTER PLAN (the author's skeleton; it decides what happens, so jokes and fights serve it and never change it):\n"
                             + "\n".join(rows))
        except Exception:
            pass
        try:
            from routers.generation.generate import _arc_index_of
            idx = _arc_index_of(project, chapter)
            arc = (project.get("arcs") or [])[idx] if idx is not None else None
            if arc:
                bits = [str(arc.get(k))[:260] for k in ("label", "summary", "description", "purpose") if arc.get(k)]
                parts.append("THIS ARC (the author's plan): " + " | ".join(bits))
        except Exception:
            pass
        try:
            kb = known_beasts_block(project, chapter, cap=1600)
            if kb:
                parts.append(kb)
        except Exception:
            pass
        try:
            from routers.pre_generation.fightplan import fight_plan_block
            fp = fight_plan_block(project, chapter, cap=1800)
            if fp:
                parts.append(fp)
            from routers.pre_generation.sceneplan import scene_plan_block
            sp = scene_plan_block(project, chapter, cap=1800)
            if sp:
                parts.append(sp)
        except Exception:
            pass
        try:
            from routers.pre_generation.antagonists import antagonists_block
            fb = antagonists_block(project, chapter, cap=2200)
            if fb:
                parts.append(fb)
        except Exception:
            pass
        try:
            from routers.pre_generation.conspiracy import conspiracy_chapter_block, conspiracy_surface_block
            cb = conspiracy_chapter_block(project, chapter) or conspiracy_surface_block(project, max(1, chapter - 4), chapter + 8, cap=1200)
            if cb:
                parts.append(cb)
        except Exception:
            pass
        try:
            from routers.pre_generation.castroster import cast_presence_block, cast_voice_block
            for fn, c in ((cast_presence_block, 1800), (cast_voice_block, 1800)):
                b = fn(project, chapter, c)
                if b:
                    parts.append(b)
        except Exception:
            pass
    else:
        try:
            roster = [e for e in ((project.get("antagonists") or {}).get("roster") or []) if isinstance(e, dict) and e.get("name")]
            if roster:
                lines = []
                for e in sorted(roster, key=lambda e: e.get("first_chapter") if isinstance(e.get("first_chapter"), int) else 0)[:40]:
                    lines.append(f"- {e['name']} [{e.get('tier')}{', ' + str(e['realm']) if e.get('realm') else ''}, from ch {e.get('first_chapter') or '?'}]: "
                                 f"strength: {str(e.get('strength') or '-')[:70]}; weakness: {str(e.get('weakness') or '-')[:70]}")
                head = "THE FOES AND HOW THEY FIGHT (adapt jokes and fights so they could happen to or with these people):"
                parts.append((head + chr(10) + chr(10).join(lines))[:3200])
        except Exception:
            pass
        try:
            from routers.pre_generation.conspiracy import conspiracy_surface_block
            cb = conspiracy_surface_block(project, 1, 100000, cap=1800)
            if cb:
                parts.append(cb)
        except Exception:
            pass
        try:
            from routers.pre_generation.castroster import cast_voice_block
            vb = ""
            tops = [c for c in (project.get("character_list") or []) if isinstance(c, dict) and c.get("voice") and c.get("tier") == "major"][:10]
            if tops:
                vb = "HOW THE MAIN CHARACTERS TALK:\n" + "\n".join(f"- {c['name']}: {str(c['voice'])[:160]}" for c in tops)
                parts.append(vb)
        except Exception:
            pass
    if not parts:
        return ""
    head = ("━━ THE BOOK'S PLAN FOR THIS " + {"humor": "JOKE", "combat": "FIGHT"}.get(kind, "EDIT") + " (from the author's Lore, Timeline, Foes, Cast, Plot and Arc tabs; "
            "it overrides anything older; do not contradict it) ━━\n")
    return (head + "\n\n".join(parts))[:cap]


_BEAST_RX = None


def known_beasts_block(project: dict, ch: int, cap: int = 3400) -> str:
    """For a chapter whose plan has a beast in it: the beasts the writer may name. First this book's own Systems monsters; then verbatim beast terms from the
    corpus glossary and the saved Blueprints, found by semantic search on the chapter's own scenes. Never an invented nickname type."""
    import ast
    import re
    global _BEAST_RX
    if _BEAST_RX is None:
        _BEAST_RX = re.compile(r"\b(beasts?|boars?|wolf|wolves|monsters?|tides?|ambush\w*|wilds|nests?|howl\w*|tusks?|claws?|fangs?|horde|herd|pack)\b", re.I)
    plan = next((x for x in project.get("chapter_skeletons") or [] if isinstance(x, dict) and x.get("number") == ch), None)
    if not plan:
        return ""
    scenes = " ".join(str(s.get("structure_notes") or "") for s in plan.get("scenes") or [] if isinstance(s, dict))
    text = f"{plan.get('purpose', '')} {plan.get('key_event', '')} {scenes}"
    if not _BEAST_RX.search(text):
        return ""
    parts = []
    mons = ((project.get("systems") or {}).get("bosses_monsters") or {}).get("monsters")
    if isinstance(mons, str):
        try:
            mons = ast.literal_eval(mons)
        except Exception:
            mons = []
    own = [f"- {m['name']} ({str(m.get('threat_tier') or '').split(' — ')[0][:40]})" for m in mons or [] if isinstance(m, dict) and m.get("name")]
    if own:
        parts.append("THIS BOOK'S OWN BEASTS (use one of these first):\n" + "\n".join(own[:24]))
    query = (scenes[:400] or text[:400]) + " beast monster species"
    try:
        from routers.corpus_tools.corpus import knowledge_search
        seen, rows = set(), []
        for r in knowledge_search(query, top_k=18, category="glossary") or []:
            term = (r.get("meta") or {}).get("term") or ""
            body = str(r.get("text") or "")
            if term and term[0].isupper() and not re.search(r"level|transform|technique|meat|dish|rank|core|tide|system|attribute|realm|stage|tamer|warrior|golem|mechanical|profession", term, re.I)                     and term.lower() not in seen and re.search(r"beast|monster|boar|wolf|ape|serpent|bear|tiger|ox\b|bird|centipede|spider|lizard", body, re.I):
                seen.add(term.lower())
                rows.append(f"- {term} ({r.get('novel_id')}): {body.split(':', 1)[-1].strip()[:110]}")
        if rows:
            parts.append("BEASTS FROM THE CORPUS, for inspiration only (when none of this book's beasts fits: invent your own names and adapt the traits to this world; never reuse the source novel's names or places):\n" + "\n".join(rows[:6]))
        brows = []
        for r in knowledge_search(query, top_k=10, category="blueprint") or []:
            meta = r.get("meta") or {}
            if re.search(r"monster|boss|beast|creature", f"{meta.get('display_name', '')} {meta.get('field', '')}", re.I):
                brows.append(f"- {str(r.get('text') or '')[:150]}")
        if brows:
            parts.append("BEASTS FROM THE SAVED BLUEPRINTS:\n" + "\n".join(brows[:4]))
    except Exception:
        pass
    if not parts:
        return ""
    head = ("KNOWN BEASTS (the author's rule: name every beast by a known beast, from the lists below, verbatim. Never invent a nickname type. Name the species the first "
            "time the beast appears, and keep its size, weapons and grade the same afterwards.)\n")
    return (head + "\n\n".join(parts))[:cap]
