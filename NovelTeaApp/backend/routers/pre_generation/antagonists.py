"""The project's ANTAGONISTS & OBSTACLES plan (Pre-generation tab).

A standing roster of the people and forces that get in the hero's way - from the petty annoyance who blocks him with a rule, to the
rival who challenges him in public, to the hidden mastermind. It is built from the corpus's own antagonist research (656 recurring
antagonist templates with their real instances and escalation notes, plus 150 antagonist character profiles) and it is ALWAYS in the
prompts: chapter-skeleton planning, chapter writing and the final plan gate all see who is in play and how each obstructs.

Stored at project["antagonists"] = {"overview": str, "rules": [str], "roster": [entry, ...]} - see _ENTRY_FIELDS for an entry."""
import json
import re
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

TIERS = ["annoyance", "rival", "enemy", "nemesis", "boss"]
_ENTRY_FIELDS = ("id", "name", "tier", "archetype", "who", "personality", "speech", "tells", "wants", "strength", "weakness",
                 "how_they_obstruct", "annoyance_beats", "escalation", "first_chapter", "active_chapters", "comeuppance",
                 "ties", "corpus_sources", "status", "realm", "arc")

# What the corpus is searched for: (tier, what it is, the search query). Each is run against the antagonist templates.
_RESEARCH_QUERIES = [
    ("annoyance", "petty gatekeeper", "a petty official, clerk or gatekeeper who blocks the hero with rules, fees and paperwork and enjoys it"),
    ("annoyance", "gloating peer", "a mocking peer or classmate who gloats, spreads rumours and keeps turning up to humiliate the hero in public"),
    ("annoyance", "jealous sabotager", "a jealous disciple who sabotages the hero's work, steals credit or sets small traps"),
    ("annoyance", "bully with backers", "a bully whose rich or powerful backer makes him untouchable until the hero reveals his strength"),
    ("rival", "arrogant young master", "an arrogant young master or genius who publicly challenges the hero and underestimates him"),
    ("rival", "matched genius", "a rival genius who matches the hero at every step and escalates each time they meet"),
    ("rival", "tournament opponent", "an opponent in a formal competition or arena who is arranged by antagonists to humiliate the hero"),
    ("enemy", "scheming elder", "an elder or senior with clan backing who suppresses the hero and schemes to claim what the hero has"),
    ("enemy", "enforcer or collector", "an enforcer, debt collector or hired thug who ambushes the hero and demands payment or submission"),
    ("enemy", "family threat", "antagonists who target the hero's family, friends or loved ones when direct confrontation fails"),
    ("nemesis", "hidden mastermind", "a hidden mastermind behind the sect who watches the hero for years and widens the net around him"),
    ("boss", "signature-technique boss", "a boss opponent with a signature technique and a fatal flaw that the hero learns in the middle of the fight"),
    ("annoyance", "greedy merchant or broker", "a greedy merchant, broker or auctioneer who cheats the hero, inflates prices and spreads word of his purchases"),
    ("annoyance", "fawning lackey", "a fawning lackey or follower of a young master who provokes the hero on his master's behalf and runs to fetch him"),
    ("annoyance", "corrupt guard", "a corrupt guard, patrolman or checkpoint officer who extorts fees, searches the hero and abuses petty authority"),
    ("rival", "noble heir", "a noble heir from a great family who looks down on a low-born hero and is publicly humiliated by him"),
    ("rival", "rigged-match patron", "a patron who fixes matches, buys fighters and arranges for the hero to lose in a tournament or arena"),
    ("rival", "zealous believer", "a sincere believer or temple figure who denounces the hero as a heretic and turns the crowd against him"),
    ("enemy", "martial-law enforcer", "a martial-law enforcer or captain who hunts the hero under orders, with checkpoints, curfews and summary tribunals"),
    ("enemy", "hidden assassin", "an assassin or masked hunter sent to kill the hero quietly, who studies him and strikes when he is weakest"),
    ("enemy", "traitor in the circle", "someone close to the hero who betrays him to his enemies for gain or under threat"),
    ("nemesis", "puppet-master noble", "a powerful noble or official who rules from behind others, giving orders the hero can only trace through his agents"),
    ("boss", "beast-tide general", "a monstrous beast king or general who leads a beast tide against a city and must be fought on the walls"),
    ("boss", "ancient sealed power", "an ancient power at the peak of cultivation, sealed or hidden, whose presence alone crushes the hero"),
]


def _G():
    from routers.generation import generate as G
    return G


def _project_path(project_id: str):
    return _G().CORPUS_PATH / "projects" / project_id / "project.json"


def _load(project_id: str) -> dict:
    p = _project_path(project_id)
    if not p.exists():
        raise HTTPException(404, f"Project {project_id} not found")
    return json.loads(p.read_text(encoding="utf-8"))


def _save(project_id: str, project: dict):
    _project_path(project_id).write_text(json.dumps(project, indent=2, ensure_ascii=False), encoding="utf-8")


# ── corpus research ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _research_one(query: str, top_k: int = 4) -> list:
    from routers.corpus_tools.corpus import knowledge_search
    out = []
    for r in knowledge_search(query, top_k=top_k, category="antagonist_template") or []:
        meta = r.get("meta") or {}
        out.append({"novel": r.get("novel_title"), "score": round(float(r.get("score") or 0), 3), "pattern": str(r.get("text") or "")[:700],
                    "entities": (meta.get("entities") or [])[:4], "variation_notes": str(meta.get("variation_notes") or "")[:600]})
    return out


def _research_all() -> list:
    """The standing research: every archetype query, deduplicated by pattern text. Returns [{tier, label, hits: [...]}]."""
    rows, seen = [], set()
    for tier, label, q in _RESEARCH_QUERIES:
        try:
            hits = _research_one(q)
        except Exception:
            hits = []
        fresh = []
        for h in hits:
            key = h["pattern"][:80]
            if key in seen:
                continue
            seen.add(key)
            fresh.append(h)
        rows.append({"tier": tier, "label": label, "query": q, "hits": fresh})
    return rows


def _novel_id_for(novel: str) -> str:
    """Accepts a novel id or the title the search hits carry, returns the id."""
    G = _G()
    if not novel:
        return ""
    if (G.NOVELS_PATH / novel).is_dir():
        return novel
    low = novel.strip().lower()
    for nid, title in (G._corpus_novel_titles() or {}).items():
        if str(title).strip().lower() == low or nid.lower() == low:
            return nid
    return ""


def profile_for(name: str, novel: str = "") -> dict:
    """EVERYTHING the corpus holds about one named antagonist, looked up live for the names actually chosen (no batch job): the novel's
    entity file (facts, aliases, role, voice), every antagonist template the name appears in with its chapters and how that instance
    varied, the antagonist character profile, and the most relevant summaries and schemes from that novel (semantic search)."""
    G = _G()
    nid = _novel_id_for(novel)
    low = name.strip().lower()
    out = {"name": name, "novel_id": nid, "entity": None, "templates": [], "character_profile": None, "passages": []}
    novels = [nid] if nid else [p.name for p in G.NOVELS_PATH.iterdir() if p.is_dir()]
    for n in novels:
        ed = G.NOVELS_PATH / n / "entities"
        if out["entity"] is None and ed.is_dir():
            for f in ed.glob("*.json"):
                try:
                    e = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    continue
                names = [str(e.get("canonical_name") or "")] + [str(a) for a in (e.get("aliases") or [])]
                if low in (x.strip().lower() for x in names if x):
                    facts = [f"{x.get('predicate')}: {str(x.get('object'))[:220]}" for x in (e.get("facts") or [])
                             if isinstance(x, dict) and x.get("status", "active") == "active"][:14]
                    out["entity"] = {"novel_id": n, "canonical_name": e.get("canonical_name"), "type": e.get("type"), "role": e.get("role"),
                                     "aliases": (e.get("aliases") or [])[:6], "comedic_role": e.get("comedic_role"),
                                     "notes": str(e.get("notes") or "")[:500], "facts": facts, "appearances": e.get("appearances")}
                    out["novel_id"] = out["novel_id"] or n
                    break
        tf = G.NOVELS_PATH / n / "templates" / "antagonists.json"
        if tf.exists():
            try:
                for t in json.loads(tf.read_text(encoding="utf-8")):
                    for inst in t.get("instances") or []:
                        if str(inst.get("entity") or "").strip().lower() == low:
                            out["templates"].append({"novel_id": n, "template_id": t.get("template_id"), "pattern": str(t.get("pattern") or "")[:600],
                                                     "chapters": inst.get("chapters"), "variation_notes": str(inst.get("variation_notes") or "")[:700]})
            except Exception:
                pass
    try:
        from routers.corpus_tools.corpus import list_character_dna
        for c in list_character_dna(role="antagonist", novel_id=nid or None).get("characters", []):
            if str(c.get("character_name") or "").strip().lower() == low:
                out["character_profile"] = {"archetype": c.get("archetype"), "traits": [f"{t.get('field')}: {t.get('label')}" for t in c.get("traits") or []][:14]}
                break
    except Exception:
        pass
    try:
        from routers.corpus_tools.corpus import knowledge_search
        seen = set()
        for cat in ("summary", "scheme", "reveal"):
            for r in knowledge_search(name, top_k=3, category=cat, novel_id=out["novel_id"] or None) or []:
                txt = str(r.get("text") or "")
                if name.split()[0].lower() not in txt.lower() or txt[:60] in seen:
                    continue
                seen.add(txt[:60])
                out["passages"].append({"kind": cat, "chapter": r.get("chapter"), "text": txt[:420]})
    except Exception:
        pass
    return out


def _profile_text(p: dict) -> str:
    lines = [f"CORPUS PROFILE - {p['name']}" + (f" [{p['novel_id']}]" if p.get("novel_id") else "")]
    e = p.get("entity")
    if e:
        lines.append(f"  role: {e.get('role') or e.get('type')}; aliases: {', '.join(e.get('aliases') or [])}; {str(e.get('notes') or '')[:300]}")
        lines += [f"  - {f}" for f in (e.get("facts") or [])[:8]]
    cp = p.get("character_profile")
    if cp:
        lines.append("  character profile: " + "; ".join(cp.get("traits") or [])[:420])
    for t in (p.get("templates") or [])[:2]:
        lines.append(f"  template {t.get('template_id')} (ch {t.get('chapters')}): {t.get('pattern')[:300]} | varied: {t.get('variation_notes')[:300]}")
    for ps in (p.get("passages") or [])[:3]:
        lines.append(f"  [{ps['kind']} ch{ps.get('chapter')}] {ps['text'][:260]}")
    return "\n".join(lines)


def _voice_profiles(limit: int = 14) -> list:
    """Corpus antagonist character profiles (traits, core belief, banter) - the characteristics half of the research."""
    try:
        from routers.corpus_tools.corpus import list_character_dna
        chars = list_character_dna(role="antagonist").get("characters", [])
    except Exception:
        return []
    chars = [c for c in chars if c.get("grounding") in ("strong", "moderate", None)]
    chars.sort(key=lambda c: (c.get("grounding") != "strong", -len(c.get("traits") or [])))
    out = []
    for c in chars[:limit]:
        tr = {}
        for t in c.get("traits") or []:
            tr.setdefault(t.get("field"), []).append(str(t.get("label"))[:90])
        out.append({"name": c.get("character_name"), "novel": c.get("novel_id"),
                    "core_belief": (tr.get("core_belief") or [""])[0], "banter": (tr.get("banter_style") or [""])[0],
                    "speech": (tr.get("speech_style") or [""])[0], "traits": (tr.get("personality_traits") or [])[:6]})
    return out


def _research_block(rows: list, voices: list) -> str:
    lines = ["CORPUS RESEARCH - how published novels build the people who get in the hero's way (adapt the ARCHETYPE and how it escalates; never copy a character):"]
    for row in rows:
        if not row["hits"]:
            continue
        lines.append(f"\n[{row['tier'].upper()} - {row['label']}]")
        for h in row["hits"][:3]:
            ent = f" (e.g. {', '.join(h['entities'][:3])})" if h["entities"] else ""
            lines.append(f"  - {h['novel']}{ent}: {h['pattern'][:420]}")
            if h["variation_notes"]:
                lines.append(f"      how it escalated: {h['variation_notes'][:300]}")
    if voices:
        lines.append("\nANTAGONIST CHARACTER PROFILES FROM THE CORPUS (personality, belief, speech):")
        for v in voices:
            lines.append(f"  - {v['name']} [{v['novel']}]: belief \"{v['core_belief'][:110]}\"; traits {', '.join(v['traits'])}; banter {v['banter']}; speech {v['speech']}")
    return "\n".join(lines)


# ── what the generators see ─────────────────────────────────────────────────────────────────────────────────────────────
def _stage_for(entry: dict, ch: int) -> str:
    esc = [str(x) for x in (entry.get("escalation") or []) if str(x).strip()]
    if not esc:
        return ""
    first = entry.get("first_chapter")
    if not isinstance(first, int):
        return esc[0]
    idx = min(len(esc) - 1, max(0, (ch - first) // 3))
    return esc[idx]


def _active(entry: dict, ch: int) -> bool:
    if str(entry.get("status") or "").lower() in ("defeated", "turned", "dead", "retired"):
        return False
    first = entry.get("first_chapter")
    if isinstance(first, int) and first > ch + 1:
        return False
    rng = str(entry.get("active_chapters") or "")
    if "-" in rng:
        try:                                     # one range, or several ("8-30, 67-145, 656-760")
            return any(int(x.split("-", 1)[0]) - 1 <= ch <= int(x.split("-", 1)[1]) for x in rng.replace(" ", "").split(",") if "-" in x)
        except Exception:
            return True
    return True


def roster_overview_block(project: dict, first_ch: int, last_ch: int, cap: int = 3500) -> str:
    """For ARC planning: who the Foes plan brings in by the end of this arc's chapter span, with the chapter each first appears.
    (The per-chapter block shows only who is in play right now; an arc needs the whole span.)"""
    roster = [e for e in ((project.get("antagonists") or {}).get("roster") or []) if isinstance(e, dict) and e.get("name")]
    rows = []
    for e in roster:
        fc = e.get("first_chapter")
        if isinstance(fc, int) and fc > last_ch:
            continue
        rows.append((fc if isinstance(fc, int) else 0, e))
    if not rows:
        return ""
    lines = [f"THE FOES PLAN FOR CHAPTERS {first_ch}-{last_ch} (the author's standing roster of everyone who gets in the hero's way; the arc should "
             "bring them in at about these chapters and give each a real obstacle or fight):"]
    for fc, e in sorted(rows, key=lambda r: r[0]):
        lines.append(f"- {e['name']} [{e.get('tier')}] from ch {fc or '?'}: {str(e.get('who') or '')[:140]}")
    return "\n".join(lines)[:cap]


def antagonists_block(project: dict, ch: int, cap: int = 7000) -> str:
    """The standing antagonist plan as a prompt block for chapter `ch`: who is in play, how each gets in the hero's way, and where each
    one's escalation stands. Empty when the project has no roster."""
    a = project.get("antagonists") or {}
    roster = [e for e in (a.get("roster") or []) if isinstance(e, dict) and e.get("name")]
    if not roster:
        return ""
    lines = ["ANTAGONISTS & OBSTACLES (the author's standing plan - the hero is never unopposed: every chapter puts at least one of these in his "
             "way, as an annoyance or an obstacle, in the way described):"]
    if a.get("overview"):
        lines.append(str(a["overview"])[:500])
    for r in (a.get("rules") or [])[:5]:
        lines.append(f"* {str(r)[:220]}")
    live = [e for e in roster if _active(e, ch)]
    dormant = [e for e in roster if e not in live]
    lines.append(f"\nIN PLAY AROUND CHAPTER {ch}:")
    for e in live:
        stage = _stage_for(e, ch)
        meth = "; ".join(str(x)[:90] for x in (e.get("how_they_obstruct") or [])[:3])
        beats = "; ".join(str(x)[:90] for x in (e.get("annoyance_beats") or [])[:3])
        lines.append(f"- {e['name']} [{e.get('tier')}{', ' + str(e['realm']) if e.get('realm') else ''}] {str(e.get('who') or '')[:170]} OBSTRUCTS BY: {meth}. NUISANCE BEATS: {beats}."
                     + (f" ESCALATION NOW: {stage[:160]}." if stage else "")
                     + (f" HOW HE/SHE IS FACED: {str(e.get('comeuppance'))[:140]}." if e.get("comeuppance") else ""))
    if dormant:
        lines.append("NOT YET IN PLAY (do not bring them on early): " + ", ".join(f"{e['name']} (ch {e.get('first_chapter') or '?'})" for e in dormant[:12]))
    return "\n".join(lines)[:cap]


# ── endpoints ───────────────────────────────────────────────────────────────────────────────────────────────────────────
@router.get("/{project_id}")
def get_antagonists(project_id: str):
    project = _load(project_id)
    a = project.get("antagonists") or {}
    try:
        from routers.corpus_tools.corpus import knowledge_search  # noqa: F401  (research needs the knowledge index)
        research_ready = True
    except Exception:
        research_ready = False
    return {"ok": True, "overview": a.get("overview", ""), "rules": a.get("rules", []), "roster": a.get("roster", []), "tiers": TIERS,
            "research_ready": research_ready, "queries": [{"tier": t, "label": l} for t, l, _ in _RESEARCH_QUERIES],
            "coverage": arc_coverage(project), "pending": project.get("antagonists_pending") or {}}


def _name_key(n) -> str:
    return re.split(r",| the ", str(n or "").strip().lower(), 1)[0].strip()


def _span(e: dict):
    fc = e.get("first_chapter") if isinstance(e.get("first_chapter"), int) else None
    rng = str(e.get("active_chapters") or "").replace(" ", "")
    if "-" in rng:
        try:
            parts = [tuple(int(y) for y in x.split("-", 1)) for x in rng.split(",") if "-" in x]
            return min(a for a, _ in parts), max(b for _, b in parts)
        except Exception:
            pass
    return (fc or 1), ((fc or 1) + 60)


def arc_coverage(project: dict) -> list:
    """Per arc: what the timeline says the hero fights, escapes and cannot touch there; which foes are introduced and active; and the gaps."""
    from routers.pre_generation.castroster import _arcs, _ENEMY, _int
    roster = [e for e in ((project.get("antagonists") or {}).get("roster") or []) if isinstance(e, dict) and e.get("name")]
    have = {_name_key(e["name"]) for e in roster}
    info = (project.get("timeline") or {}).get("arcs") or {}
    out = []
    for v in _arcs(project):
        lo, hi = v["chapters"]
        i = info.get(str(v["volume"])) or {}
        new = [e["name"] for e in roster if isinstance(e.get("first_chapter"), int) and lo <= e["first_chapter"] <= hi]
        active = [e for e in roster if _span(e)[0] <= hi and _span(e)[1] >= lo and str(e.get("status") or "").lower() not in ("defeated", "dead", "turned", "retired")]
        tiers = {}
        for e in active:
            tiers[e.get("tier")] = tiers.get(e.get("tier"), 0) + 1
        missing = [c["name"] for c in project.get("character_list") or [] if isinstance(c, dict) and _ENEMY.search(str(c.get("role", "")))
                   and _int(c.get("intro_chapter")) and lo <= _int(c["intro_chapter"]) <= hi and _name_key(c["name"]) not in have]
        gaps = []
        if not new:
            gaps.append("no new foe is introduced in this arc")
        if not tiers.get("annoyance"):
            gaps.append("no annoyance in play, so chapters here have nobody small getting in the hero's way")
        if not (tiers.get("boss") or tiers.get("enemy") or tiers.get("nemesis")):
            gaps.append("no enemy, nemesis or boss in play")
        if missing:
            gaps.append("cast antagonists with no Foes entry: " + ", ".join(missing))
        out.append({"arc": v["volume"], "chapters": [lo, hi], "place": i.get("place", ""), "fights": i.get("fights", ""),
                    "escapes": i.get("escapes", ""), "untouchable": i.get("untouchable", ""), "new": new,
                    "active": [{"name": e["name"], "tier": e.get("tier")} for e in active], "tiers": tiers, "missing": missing, "gaps": gaps})
    return out


_CATALOGUE: dict = {}


def _catalogue() -> list:
    """Every antagonist template in the corpus (all novels' templates/antagonists.json), one row each with a brief, the characters who
    embody it and the chapters they appear in. File reads only, cached by the files' modification times."""
    G = _G()
    files = sorted(G.NOVELS_PATH.glob("*/templates/antagonists.json"))
    stamp = tuple((str(f), f.stat().st_mtime) for f in files)
    if _CATALOGUE.get("stamp") == stamp:
        return _CATALOGUE["rows"]
    titles = G._corpus_novel_titles() or {}
    rows = []
    for f in files:
        nid = f.parent.parent.name
        try:
            items = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for i, t in enumerate(items if isinstance(items, list) else []):
            if not isinstance(t, dict):
                continue
            pattern = str(t.get("pattern") or "")
            brief = pattern.split(". ")[0][:220] + ("." if not pattern.split(". ")[0].endswith(".") else "")
            ents = []
            for inst in t.get("instances") or []:
                nm = inst.get("entity")
                nm = ", ".join(map(str, nm)) if isinstance(nm, list) else str(nm or "")
                if nm:
                    ents.append({"name": nm, "chapters": inst.get("chapters")})
            rows.append({"key": f"{nid}:{i}", "novel_id": nid, "novel": titles.get(nid, nid), "template_id": t.get("template_id") or "",
                         "brief": brief, "pattern": pattern[:900], "entities": ents[:8], "instances": len(t.get("instances") or [])})
    _CATALOGUE.update({"stamp": stamp, "rows": rows})
    return rows


def _corpus_names() -> set:
    """Every corpus antagonist character's name (lower-case), plus each name's distinctive words, for the no-copied-names check."""
    names = set()
    for r in _catalogue():
        for e in r["entities"]:
            for part in str(e["name"]).split(","):
                p = part.strip().lower()
                if len(p) >= 3:
                    names.add(p)
    return names


def _corpus_name_clashes(roster: list, project: dict) -> list:
    """Roster names that copy a corpus character's name. Names from THIS book's own cast are always allowed."""
    own = {str(c.get("name") or "").strip().lower() for c in (project.get("character_list") or []) if isinstance(c, dict)}
    corpus = _corpus_names() - own
    out = []
    for e in roster:
        if not isinstance(e, dict):
            continue
        n = str(e.get("name") or "").strip()
        if n and n.lower() not in own and n.lower() in corpus:
            out.append(n)
    return out


@router.get("/catalogue/all")
def catalogue():
    """The browsable list of all the corpus's antagonist templates, with a brief and the characters for each (no AI call)."""
    rows = _catalogue()
    return {"ok": True, "total": len(rows), "novels": sorted({r["novel"] for r in rows}), "rows": rows}


class ProfileRequest(BaseModel):
    name: str
    novel: Optional[str] = ""


@router.post("/profile")
def corpus_profile(req: ProfileRequest):
    """Everything the corpus holds about one named antagonist (looked up live, for the name you picked)."""
    if not req.name.strip():
        raise HTTPException(400, "Pick a name.")
    try:
        return {"ok": True, **profile_for(req.name.strip(), req.novel or "")}
    except Exception as e:
        raise HTTPException(502, f"The lookup could not run ({str(e)[:120]}).")


class SearchRequest(BaseModel):
    query: str
    top_k: int = 8


@router.post("/search")
def search_corpus(req: SearchRequest):
    """Browse the corpus's antagonist research for any query (no AI call)."""
    if not req.query.strip():
        raise HTTPException(400, "Type what kind of antagonist or obstacle you are looking for.")
    try:
        return {"ok": True, "hits": _research_one(req.query.strip(), top_k=max(1, min(req.top_k, 20)))}
    except Exception as e:
        raise HTTPException(502, f"The corpus search could not run ({str(e)[:120]}). Is Ollama running?")


class SaveRequest(BaseModel):
    project_id: str
    overview: Optional[str] = None
    rules: Optional[list] = None
    roster: list


def _clean_entry(e: dict, i: int) -> Optional[dict]:
    if not isinstance(e, dict) or not str(e.get("name") or "").strip():
        return None
    out = {k: e.get(k) for k in _ENTRY_FIELDS if k in e}
    out["name"] = str(e["name"]).strip()
    out["id"] = str(e.get("id") or f"ant{i + 1}")
    t = str(e.get("tier") or "annoyance").lower()
    out["tier"] = t if t in TIERS else "annoyance"
    for k in ("how_they_obstruct", "annoyance_beats", "escalation"):
        v = out.get(k)
        out[k] = [str(x) for x in v] if isinstance(v, list) else ([str(v)] if v else [])
    fc = out.get("first_chapter")
    out["first_chapter"] = fc if isinstance(fc, int) else (int(fc) if str(fc or "").isdigit() else None)
    out.setdefault("status", "planned")
    return out


def _store(project: dict, project_id: str, overview, rules, roster: list):
    import copy as _copy
    old = project.get("antagonists")
    if old:
        project.setdefault("_field_history", {}).setdefault("antagonists", []).append({"antagonists": _copy.deepcopy(old)})
    cleaned = [c for c in (_clean_entry(e, i) for i, e in enumerate(roster)) if c]
    project["antagonists"] = {"overview": overview if overview is not None else (old or {}).get("overview", ""),
                              "rules": rules if rules is not None else (old or {}).get("rules", []), "roster": cleaned}
    _save(project_id, project)
    return project["antagonists"]


@router.post("/save")
def save_antagonists(req: SaveRequest):
    project = _load(req.project_id)
    return {"ok": True, **_store(project, req.project_id, req.overview, req.rules, req.roster)}


class UndoRequest(BaseModel):
    project_id: str


@router.post("/undo")
def undo_antagonists(req: UndoRequest):
    project = _load(req.project_id)
    hist = (project.get("_field_history") or {}).get("antagonists") or []
    if not hist:
        raise HTTPException(400, "Nothing to undo.")
    project["antagonists"] = hist.pop()["antagonists"]
    _save(req.project_id, project)
    return {"ok": True, **project["antagonists"]}


class GenerateRequest(BaseModel):
    project_id: str
    mode: str = "replace"        # "replace" the roster, or "add" new antagonists to it
    count: int = 12
    provider: Optional[str] = None
    selected: Optional[list] = None   # catalogue keys the author picked: these MUST be adapted
    first_chapter: Optional[int] = None   # with last_chapter: plan the foes of this stretch (an arc) only
    last_chapter: Optional[int] = None


@router.post("/generate")
def generate_antagonists(req: GenerateRequest):
    """Research the corpus's antagonists and draft the standing roster for THIS book: the whole thing in one AI call, grounded in the
    premise, world, systems, cast and the author's intent, with every entry citing the corpus archetype it adapts."""
    G = _G()
    project = _load(req.project_id)
    pid = req.project_id
    gen_cfg = G._get_generation_cfg()
    provider = req.provider or gen_cfg.get("default_provider", "anthropic")
    api_key = G._get_key(provider)
    model = (G._get_models_cfg() or {}).get(provider, "")
    G._progress_log(pid, "ANTAGONISTS: researching the corpus's antagonists and obstacles…", engine="antagonists")
    rows = _research_all()
    if req.first_chapter and req.last_chapter:       # an arc: also search the catalogue for the opponents its timeline names
        cov = next((c for c in arc_coverage(project) if c["chapters"][0] <= req.first_chapter <= c["chapters"][1]), {})
        seen = {h["pattern"][:80] for r in rows for h in r["hits"]}
        own = []
        for kind, label in (("fights", "the hero fights"), ("escapes", "the hero can only escape"), ("untouchable", "the hero cannot touch")):
            for item in [x.strip() for x in re.split(r"[;]", str(cov.get(kind) or "")) if x.strip() and x.strip() != "-"][:3]:
                q = f"{re.sub(r'[(][^)]*[)]', '', item).strip()}: an antagonist {label}, {cov.get('place', '')}"
                try:
                    hits = [h for h in _research_one(q, top_k=3) if h["pattern"][:80] not in seen]
                except Exception:
                    hits = []
                seen.update(h["pattern"][:80] for h in hits)
                if hits:
                    own.append({"tier": "this arc", "label": f"{label}: {item}", "query": q, "hits": hits})
        rows = own + rows                               # first, so they survive the prompt's length cap
    voices = _voice_profiles()
    n_hits = sum(len(r["hits"]) for r in rows)
    G._progress_log(pid, f"ANTAGONISTS: {n_hits} corpus archetypes and {len(voices)} antagonist profiles found", "success" if n_hits else "warn", engine="antagonists")
    # The names the search surfaced: look each chosen name up live (one per archetype, the best hit's lead character), so the AI adapts real, fully
    # known antagonists instead of a one-line pattern.
    profiles = []
    for row in rows:
        for h in row["hits"][:2]:
            if h.get("entities"):
                try:
                    pr = profile_for(h["entities"][0], h.get("novel") or "")
                    if pr.get("entity") or pr.get("templates") or pr.get("passages"):
                        profiles.append(_profile_text(pr))
                except Exception:
                    pass
                break
    if profiles:
        G._progress_log(pid, f"ANTAGONISTS: looked up {len(profiles)} named corpus antagonists in full", engine="antagonists")
    # The author's own picks from the catalogue: each template in full plus a live profile of its lead character.
    picked_block = ""
    if req.selected:
        by_key = {r["key"]: r for r in _catalogue()}
        picks = [by_key[k] for k in req.selected if k in by_key][:16]
        chunks = []
        for r in picks:
            lead = r["entities"][0]["name"] if r["entities"] else ""
            prof = ""
            if lead:
                try:
                    prof = _profile_text(profile_for(lead, r["novel_id"]))[:1200]
                except Exception:
                    prof = ""
            chunks.append(f"- [{r['novel']} / {r['template_id']}] {r['pattern'][:600]}\n  characters: {', '.join(e['name'] for e in r['entities'][:4])}" + (f"\n{prof}" if prof else ""))
        if chunks:
            picked_block = ("AUTHOR-SELECTED CORPUS ANTAGONISTS - the author picked these; EVERY ONE must be adapted into at least one roster entry "
                            "(fitted to this world and cast, never copied):\n" + "\n\n".join(chunks)[:12000] + "\n\n")
            G._progress_log(pid, f"ANTAGONISTS: adapting {len(chunks)} antagonists you selected from the catalogue", engine="antagonists")
    existing = (project.get("antagonists") or {}).get("roster") or []
    from routers.pre_generation.castroster import _ENEMY, _int, _arc_brief, _realm_ladder
    lo, hi = req.first_chapter, req.last_chapter
    arc_mode = bool(lo and hi)
    allcast = [c for c in project.get("character_list") or [] if isinstance(c, dict) and c.get("name")]
    have = {_name_key(e.get("name")) for e in existing}
    foes_cast = [c for c in allcast if _ENEMY.search(str(c.get("role", "")))]
    cast = ", ".join(f"{c['name']} ({c.get('role', '')})" for c in allcast)          # the whole cast: names are taken
    missing = [c for c in foes_cast if _name_key(c["name"]) not in have and (not arc_mode or (_int(c.get("intro_chapter")) and lo <= _int(c["intro_chapter"]) <= hi))]
    n = max(4, min(req.count, 20))
    try:    # the book's canon: lore, rules and timeline (no secrets: the roster reaches the chapter writer)
        from routers.pre_generation.canon import canon_context_block as _canon
        canon_block = _canon(project, "visible", lo, hi, skip=("foes", "cast"), cap=9000 if arc_mode else 16000)
    except Exception:
        canon_block = ""
    arc_block = ""
    if arc_mode:
        brief, _w = _arc_brief(project, lo, hi)
        cov = next((c for c in arc_coverage(project) if c["chapters"][0] <= lo <= c["chapters"][1]), {})
        live = [e for e in existing if _span(e)[0] <= hi and _span(e)[1] >= lo]
        arc_block = (f"THIS STRETCH: chapters {lo}-{hi}" + (f", arc {cov.get('arc')} in {cov.get('place')}" if cov else "") + ".\n"
                     + (f"THE TIMELINE SAYS THE HERO FIGHTS HERE: {cov.get('fights')}. HE CAN ONLY ESCAPE: {cov.get('escapes')}. UNTOUCHABLE "
                        f"(only seen or felt): {cov.get('untouchable')}. The roster must hold specific people (or forces) for each of these.\n" if cov else "")
                     + brief + "\n"
                     + ("FOES ALREADY IN PLAY IN THIS STRETCH (keep them; do not repeat their role):\n"
                        + "\n".join(f"- {e['name']} [{e.get('tier')}]: {str(e.get('who') or '')[:140]}" for e in live) + "\n" if live else ""))
    elif req.mode == "add" and existing:     # "fill the gaps": the arcs where the roster is thin, and what their timeline needs
        cov = [c for c in arc_coverage(project) if c["gaps"]]
        if cov:
            arc_block = ("GAPS TO FILL (the arcs where the Foes roster is thin; put every new foe in one of these arcs, first_chapter inside its "
                         "span, and cover what its timeline says the hero fights, escapes and cannot touch):\n"
                         + "\n".join(f"- Arc {c['arc']} (ch {c['chapters'][0]}-{c['chapters'][1]}, {c['place']}): fights {c['fights']}; escapes "
                                      f"{c['escapes']}; untouchable {c['untouchable']}. In play: "
                                      f"{', '.join(x['name'] + ' [' + str(x['tier']) + ']' for x in c['active']) or 'nobody'}. Gaps: {'; '.join(c['gaps'])}"
                                      for c in cov) + "\n")
    ladder = _realm_ladder(project)
    prompt = (
        (canon_block + "\n\n" if canon_block else "") + (arc_block + "\n" if arc_block else "") +
        f"You are designing the ANTAGONISTS & OBSTACLES plan for the novel \"{project.get('title', '')}\".\n\n"
        f"PREMISE: {project.get('premise') or (project.get('creative_brief') or {}).get('premise', '')}\n\n"
        + ("" if arc_block else f"{G._format_world_bible_block(project)[:6000]}\n\n") +
        f"THE BOOK'S SYSTEMS (so the antagonists belong to this world; use its named factions, wars, bosses and techniques):\n{G._systems_digest(project, cap=3000 if arc_block else 6000)}\n\n"
        f"AUTHOR INTENT: {G._author_intent_text(project) or '(none set)'}\n\n"
        f"EXISTING CAST (these names are taken; never turn an ally, friend, mentor or neutral into a foe; only the cast's antagonists may "
        f"become Foes entries, keeping their names): {cast or '(none)'}\n\n"
        + (f"EXISTING ANTAGONIST ROSTER (mode: add - do NOT repeat these):\n{json.dumps([e.get('name') for e in existing], ensure_ascii=False)}\n\n" if (req.mode == "add" or arc_mode) and existing else "")
        + ("CAST ANTAGONISTS WITH NO FOES ENTRY YET (build an entry for EACH of these first, keeping the name, role and chapter they come in):\n"
           + "\n".join(f"- {c['name']} ({c.get('role', '')}, from ch {c.get('intro_chapter') or '?'}): {str(c.get('archetype') or '')[:220]}" for c in missing[:12]) + "\n\n" if missing else "")
        + (f"REALMS OF THIS BOOK (use only these names, each with Early, Middle, Late or Peak): {', '.join(ladder)}. Give every foe a realm "
           "that fits the stretch and the realm-gap rule.\n\n" if ladder else "")
        + _research_block(rows, voices)[:8000] + "\n\n"
        + ("FULL CORPUS PROFILES OF THE NAMED ANTAGONISTS ABOVE (what they actually did, said and how they were faced - adapt, never copy):\n"
           + "\n\n".join(profiles[:8])[:4000] + "\n\n" if profiles else "")
        + picked_block
        + (f"TASK: design {n} antagonists for chapters {lo}-{hi} only (first_chapter inside that span), covering what the timeline says "
           "the hero fights, escapes and cannot touch there. " if arc_mode else "")
        + "No secrets: only what the world can see.\n"
        + f"TASK: design {n} antagonists across five tiers: annoyance (a recurring nuisance who gets in the hero's way every other chapter with a small "
        "obstacle, an insult, a rule or a fee), rival (a public challenger), enemy (an enforcer, elder or clan who actively hurts him), nemesis "
        "(a long game), boss (a fight he must win). At least a third are annoyances: the hero needs people who irritate and obstruct him in "
        "EVERY chapter, not only at the climaxes. Each must be a specific person (or force) of this world with a personality that makes him "
        "annoying or dangerous in a particular way, a way he gets in front of the hero and blocks him, nuisance beats that can recur, an escalation "
        "ladder (3-4 stages, each worse than the last), the chapter he first appears, and a comeuppance - the reversal that faces him. "
        "Fights must be possible: the rivals, enemies and bosses each have a combat angle (signature technique and a flaw the hero can learn mid-fight). "
        "Cite in corpus_sources which corpus archetype(s) above each entry adapts. Never copy a corpus character.\n"
        "NAMES: never use a corpus character's name (or a near copy of it) for anyone in the roster. From a corpus antagonist take their SITUATION, "
        "STATUS, PERSONALITY, INTENTIONS and METHODS, and give the adapted person a new name that fits this world (or re-use a name from the "
        "EXISTING CAST above, which belongs to this book). The corpus name may appear only inside corpus_sources, as the reference.\n\n"
        "Output ONE JSON object, no markdown fences:\n"
        "{\"overview\": \"how opposition works in this book, 2-3 sentences\", \"rules\": [\"3-5 standing rules, e.g. the hero is never unopposed in a chapter\"], "
        "\"roster\": [{\"name\": \"...\", \"tier\": \"annoyance|rival|enemy|nemesis|boss\", \"archetype\": \"short label\", \"who\": \"1-2 sentences: who they are, their standing\", "
        "\"personality\": \"...\", \"speech\": \"how they talk\", \"tells\": \"recognisable habits\", \"wants\": \"...\", \"strength\": \"...\", \"weakness\": \"...\", "
        "\"how_they_obstruct\": [\"3 concrete ways they get in front of the hero\"], \"annoyance_beats\": [\"3 recurring small beats\"], "
        "\"escalation\": [\"stage 1\", \"stage 2\", \"stage 3\", \"stage 4\"], \"first_chapter\": 1, \"active_chapters\": \"1-10\", \"comeuppance\": \"...\", "
        "\"ties\": \"faction / war / relationship in this world\", \"realm\": \"\", \"corpus_sources\": [\"novel: archetype adapted\"], \"status\": \"planned\"}]}")
    raw = G._call_llm(prompt, provider, model, api_key, timeout=900, abort_key=(pid, "antagonists"))
    try:
        data = G._parse_json_from_text(raw)
    except Exception:
        data = None
    if isinstance(data, list):
        data = {"roster": data}
    if not isinstance(data, dict) or not isinstance(data.get("roster"), list) or not data["roster"]:
        raise HTTPException(502, "The AI's reply wasn't a usable antagonist roster, so nothing was changed. Try again.")
    # Hard check: no roster name may be a corpus character's name. Clashes go back once to be renamed (everything else kept).
    clashes = _corpus_name_clashes(data["roster"], project)
    if clashes:
        G._progress_log(pid, f"ANTAGONISTS: {len(clashes)} name(s) copied from the corpus ({', '.join(clashes[:5])}) - renaming…", "warn", engine="antagonists")
        ask = (prompt + "\n\nYOUR ROSTER (below) re-used these corpus character names, which is not allowed: " + ", ".join(clashes)
               + ". Give each of those entries a NEW name that fits this world; keep every other field exactly as it is. Output the same JSON "
               "object again, no fences.\n" + json.dumps(data, ensure_ascii=False)[:30000])
        try:
            fixed = G._parse_json_from_text(G._call_llm(ask, provider, model, api_key, timeout=600, abort_key=(pid, "antagonists")))
            if isinstance(fixed, list):
                fixed = {"roster": fixed}
            if isinstance(fixed, dict) and isinstance(fixed.get("roster"), list) and fixed["roster"]:
                data = {**data, **fixed}
        except Exception:
            pass
        left = _corpus_name_clashes(data["roster"], project)
        data["roster"] = [e for e in data["roster"] if not (isinstance(e, dict) and str(e.get("name") or "").strip().lower() in {c.lower() for c in left})]
        if left:
            G._progress_log(pid, f"ANTAGONISTS: dropped {len(left)} entr{'y' if len(left) == 1 else 'ies'} still named after a corpus character", "warn", engine="antagonists")
        if not data["roster"]:
            raise HTTPException(502, "Every antagonist the AI drafted was named after a corpus character, so nothing was saved. Try again.")
    from routers.pre_generation.castroster import _scrub
    import time as _t
    props = []
    for i, e in enumerate(data["roster"]):
        if not isinstance(e, dict) or not str(e.get("name") or "").strip():
            continue
        e = _scrub(e)
        if arc_mode:
            fc = e.get("first_chapter") if isinstance(e.get("first_chapter"), int) else _int(e.get("first_chapter"))
            e["first_chapter"] = fc if fc and lo <= fc <= hi else lo + i * max(1, (hi - lo) // max(1, n))
        cm = next((c for c in allcast if _name_key(c["name"]) == _name_key(e["name"])), None)
        if cm and _int(cm.get("intro_chapter")):
            e["first_chapter"] = _int(cm["intro_chapter"])      # a cast member comes in when the cast plan says, whatever arc this entry is for
        if cm and not _ENEMY.search(str(cm.get("role", ""))):
            continue                                            # an ally or neutral from the cast is never made a foe
        if req.mode == "add" or arc_mode:
            if _name_key(e["name"]) in have or _name_key(e["name"]) in {_name_key(x.get("name")) for x in props}:
                continue
        if isinstance(e.get("realm"), str):
            e["realm"] = re.sub(r"\bTribulation(?! Transcendence)", "Tribulation Transcendence", e["realm"])
        e["id"] = f"ap{int(_t.time() * 1000) % 10**10}{i}"
        props.append(e)
    project = _load(pid)
    pend = project.get("antagonists_pending") or {}
    replace = req.mode == "replace" and not arc_mode and bool(existing)
    pend = {"roster": (([] if replace else pend.get("roster") or []) + props), "replace": replace or bool(pend.get("replace") and not props),
            "overview": data.get("overview") or pend.get("overview") or "", "rules": data.get("rules") or pend.get("rules") or []}
    project["antagonists_pending"] = pend
    _save(pid, project)
    G._progress_log(pid, f"ANTAGONISTS: {len(props)} foes proposed - accept or decline them in the Foes tab", "success", engine="antagonists")
    return {"ok": True, "pending": pend, "proposed": len(props), "research_used": n_hits}


class DecideRequest(BaseModel):
    project_id: str
    accept: list = []
    decline: list = []


@router.post("/decide")
def decide_antagonists(req: DecideRequest):
    """Apply the author's accept/decline on proposed foes. A rebuild proposal replaces the roster with the accepted ones (old roster on Undo)."""
    project = _load(req.project_id)
    pend = project.get("antagonists_pending") or {}
    props = pend.get("roster") or []
    roster = (project.get("antagonists") or {}).get("roster") or []
    taken = set() if pend.get("replace") else {_name_key(e.get("name")) for e in roster}
    acc = []
    for e in props:
        if e.get("id") in req.accept and _name_key(e.get("name")) not in taken:
            acc.append(e)
            taken.add(_name_key(e.get("name")))
    if acc:
        a = project.get("antagonists") or {}
        new_roster = acc if pend.get("replace") else roster + acc
        _store(project, req.project_id, (pend.get("overview") or None) if (pend.get("replace") or not a.get("overview")) else None,
               (pend.get("rules") or None) if (pend.get("replace") or not a.get("rules")) else None, new_roster)
        project = _load(req.project_id)
    done = set(req.accept) | set(req.decline)
    left = [e for e in props if e.get("id") not in done]
    project["antagonists_pending"] = {**pend, "roster": left} if left else {}
    _save(req.project_id, project)
    a = project.get("antagonists") or {}
    return {"ok": True, "overview": a.get("overview", ""), "rules": a.get("rules", []), "roster": a.get("roster", []),
            "pending": project["antagonists_pending"], "coverage": arc_coverage(project)}
