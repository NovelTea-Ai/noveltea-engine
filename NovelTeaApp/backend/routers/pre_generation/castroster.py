"""CAST ROSTER tab (Pre-generation): every character who is not an enemy (allies, mentors, friendly rivals, love interests, merchants,
comic relief, neutrals), each with the chapter they are introduced in, planned at the pace the book's style novel introduces new people.

- The pace comes from the corpus character roster (character_roster/<novel>/*.json: role, notes, first appearance, real lines) of the
  project's style novel(s): new named characters per chapter, by chapter band, and the share that are not enemies.
- Likeness: any character can be matched against the whole corpus roster (18 novels) for similar people, with their notes and real lines.
- Generate: drafts new characters for a chapter span to reach the target pace, grounded in the book's canon (no secrets) and modelled on
  corpus characters; they come back as PROPOSALS (project["cast_pending"]) that the author accepts or declines.
- The roster IS project["character_list"]; a character's intro_chapter makes the chapter's planner and writer introduce them there.
"""
import copy
import glob
import hashlib
import json
import re
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()
_ENEMY = re.compile(r"antagonist|villain|enemy|assassin|bully|demon lord|rival_hostile", re.I)
_ROSTER_CACHE = {}


def _G():
    from routers.generation import generate as G
    return G


def _root():
    return _G().CORPUS_PATH


def _load(pid: str) -> dict:
    p = _root() / "projects" / pid / "project.json"
    if not p.exists():
        raise HTTPException(404, f"Project {pid} not found")
    return json.loads(p.read_text(encoding="utf-8"))


def _save(pid: str, project: dict):
    (_root() / "projects" / pid / "project.json").write_text(json.dumps(project, indent=2, ensure_ascii=False), encoding="utf-8")


def _int(v):
    try:
        return int(v) if v not in (None, "", "null") else None
    except (TypeError, ValueError):
        return None


def _rev(project: dict) -> str:
    return hashlib.sha1(json.dumps([project.get("character_list") or [], project.get("cast_pending") or [], project.get("cast_pending_journeys") or {},
                                    project.get("cast_pending_voices") or {}], ensure_ascii=False,
                                   sort_keys=True).encode("utf-8")).hexdigest()[:16]


# ── the corpus character roster ───────────────────────────────────────────────────────────────────────────────────────
def _first_chapter(d: dict) -> Optional[int]:
    m = re.search(r"First appearance:\s*ch\s*(\d+)", d.get("notes") or "", re.I)
    chs = ([int(m.group(1))] if m else []) + [f.get("source_chapter") for f in d.get("facts") or [] if isinstance(f.get("source_chapter"), int)] \
        + [v.get("chapter") for v in d.get("voice_samples") or [] if isinstance(v.get("chapter"), int)]
    return min(chs) if chs else None


def _roster(novel: Optional[str] = None) -> list:
    key = novel or "*"
    if key not in _ROSTER_CACHE:
        out = []
        for f in glob.glob(str(_root() / "character_roster" / (novel or "*") / "*.json")):
            try:
                d = json.loads(open(f, encoding="utf-8").read())
            except Exception:
                continue
            if not isinstance(d, dict) or not d.get("canonical_name"):
                continue
            vs = [v for v in d.get("voice_samples") or [] if isinstance(v, dict) and v.get("line")]
            sample = vs[0]["line"] if vs else ""
            out.append({"lines": [{"line": str(v["line"])[:260], "note": str(v.get("voice_notes") or "")[:200]} for v in vs[:4]],
                        "novel": d.get("novel_id"), "name": d["canonical_name"], "role": str(d.get("role") or ""),
                        "notes": str(d.get("notes") or "")[:600], "first_chapter": _first_chapter(d), "line": str(sample)[:300],
                        "facts": " ".join(str(f.get("object") or "") for f in (d.get("facts") or [])[:6])[:600]})
        _ROSTER_CACHE[key] = out
    return _ROSTER_CACHE[key]


def _style_novels(project: dict) -> list:
    ap = project.get("author_profile") or {}
    for src in (ap.get("seeded_from") or {}, ap.get("voice_source") or {}):
        n = src.get("novels") if isinstance(src, dict) else None
        if n:
            return [x for x in n if isinstance(x, str)]
    return []


BANDS = [(1, 10), (11, 50), (51, 100)]


def intro_rate(project: dict) -> dict:
    """New named characters per chapter in the style novel(s), by chapter band, and the share that are not enemies. The corpus roster covers
    roughly each novel's first hundred chapters, so after that the last measured pace is carried forward (an estimate, said so)."""
    novels = _style_novels(project)
    chars = [c for n in novels for c in _roster(n)]
    firsts = [c["first_chapter"] for c in chars if c["first_chapter"]]
    bands = []
    for lo, hi in BANDS:
        k = sum(1 for f in firsts if lo <= f <= hi) / max(1, len(novels))
        bands.append({"from": lo, "to": hi, "per_chapter": round(k / (hi - lo + 1), 3)})
    non_enemy = [c for c in chars if not _ENEMY.search(c["role"])]
    share = round(len(non_enemy) / max(1, len(chars)), 2)
    return {"novels": novels, "bands": bands, "after": bands[-1]["per_chapter"], "measured_up_to": BANDS[-1][1], "non_enemy_share": share,
            "characters_measured": len(chars),
            "note": f"Measured from the corpus roster of {', '.join(novels)} (notable named characters only). After chapter {BANDS[-1][1]} the "
                    "corpus has no data, so the last measured pace is carried forward as an estimate."}


def target_for(rate: dict, first: int, last: int) -> int:
    """How many NEW non-enemy characters the pace calls for in chapters first..last."""
    total = 0.0
    for ch in range(first, last + 1):
        r = next((b["per_chapter"] for b in rate["bands"] if b["from"] <= ch <= b["to"]), rate["after"])
        total += r
    return int(round(total * rate["non_enemy_share"]))


def _arcs(project: dict) -> list:
    from routers.pre_generation.conspiracy import book_volumes
    c = project.get("conspiracy") or {}
    return book_volumes(_int(c.get("book_chapters")) or _int(project.get("target_chapters")) or 1500, _int(c.get("arcs_total")))


def cast_intro_block(project: dict, ch: int, cap: int = 2500) -> str:
    """Characters planned to be introduced in this chapter, for its planner and writer."""
    new = [c for c in project.get("character_list") or [] if isinstance(c, dict) and _int(c.get("intro_chapter")) == ch]
    if not new:
        return ""
    lines = ["NEW CHARACTERS TO INTRODUCE IN THIS CHAPTER (the author's cast plan; give each a clear, memorable first appearance):"]
    for c in new:
        lines.append(f"- {c['name']} ({c.get('role', '')}, {c.get('faction', '')}): {str(c.get('archetype', ''))[:240]}"
                     + (f" Speech: {c.get('speech_style')}" if c.get("speech_style") else ""))
    return "\n".join(lines)[:cap]


def _no_ledger(t):
    """Kept for callers that import it: text passes through unchanged."""
    return t


def _scrub(o):
    if isinstance(o, str):
        return _no_ledger(o)
    if isinstance(o, list):
        return [_scrub(x) for x in o]
    if isinstance(o, dict):
        return {k: _scrub(v) for k, v in o.items()}
    return o


def _clean_char(c: dict) -> Optional[dict]:
    c = _scrub(c) if isinstance(c, dict) else c
    if not isinstance(c, dict) or not str(c.get("name") or "").strip():
        return None
    out = {k: c.get(k) for k in ("name", "role", "faction", "archetype", "motivation", "speech_style", "core_belief", "secret", "banter_style")}
    out = {k: (str(v).strip() if v is not None else "") for k, v in out.items()}
    t = c.get("personality_traits")
    out["personality_traits"] = [str(x)[:40] for x in (t if isinstance(t, list) else str(t or "").split(",")) if str(x).strip()][:6]
    out["intro_chapter"] = _int(c.get("intro_chapter"))
    out["tier"] = str(c.get("tier") or "supporting") if str(c.get("tier") or "supporting") in ("major", "supporting", "minor") else "supporting"
    if c.get("likeness"):
        out["likeness"] = str(c["likeness"])[:200]
    if isinstance(c.get("journey"), list):
        out["journey"] = [{"arc": _int(j.get("arc")), "standing": str(j.get("standing") or "")[:30], "realm": str(j.get("realm") or "")[:80],
                           "note": str(j.get("note") or "")[:300]} for j in c["journey"] if isinstance(j, dict) and _int(j.get("arc"))][:50]
    if isinstance(c.get("exit"), dict) and _int(c["exit"].get("chapter")):
        out["exit"] = {"chapter": _int(c["exit"]["chapter"]), "kind": str(c["exit"].get("kind") or "leaves")[:20], "note": str(c["exit"].get("note") or "")[:300]}
    if isinstance(c.get("stints"), list):
        out["stints"] = [[_int(a), _int(b)] for a, b in (x for x in c["stints"] if isinstance(x, (list, tuple)) and len(x) == 2) if _int(a) and _int(b)][:40]
    if c.get("voice"):
        out["voice"] = str(c["voice"])[:400]
    if isinstance(c.get("voice_lines"), list):
        out["voice_lines"] = [str(x).strip()[:260] for x in c["voice_lines"] if str(x).strip()][:4]
    if c.get("voice_from"):
        out["voice_from"] = str(c["voice_from"])[:200]
    if c.get("id"):
        out["id"] = str(c["id"])
    return out


# ── endpoints ─────────────────────────────────────────────────────────────────────────────────────────────────────────
@router.get("/{project_id}")
def get_roster(project_id: str):
    project = _load(project_id)
    rate = intro_rate(project)
    cast = project.get("character_list") or []
    arcs = []
    for v in _arcs(project):
        lo, hi = v["chapters"]
        planned = sum(1 for c in cast if isinstance(c, dict) and _int(c.get("intro_chapter")) and lo <= _int(c["intro_chapter"]) <= hi
                      and not _ENEMY.search(str(c.get("role", ""))))         # the pace counts non-enemies only
        arcs.append({"arc": v["volume"], "chapters": [lo, hi], "planned": planned, "target": target_for(rate, lo, hi)})
    prof = presence_profile(project)
    stints = {c["name"]: stints_of(project, c, prof) for c in cast if isinstance(c, dict) and c.get("name")}
    return {"ok": True, "cast": cast, "pending": project.get("cast_pending") or [], "rate": rate, "arcs": arcs, "rev": _rev(project),
            "presence": prof, "stints": stints, "flags": presence_flags(project),
            "pending_journeys": project.get("cast_pending_journeys") or {},
            "pending_voices": project.get("cast_pending_voices") or {}}


class LikenessRequest(BaseModel):
    project_id: str
    query: str
    top_k: int = 8


@router.post("/likeness")
def likeness(req: LikenessRequest):
    """Corpus characters most like a description (role, personality, situation), across all 18 novels, with a real line of theirs."""
    q = [w for w in re.findall(r"[a-z]{3,}", req.query.lower()) if w not in {"the", "and", "who", "with", "for", "his", "her", "that"}]
    if not q:
        raise HTTPException(400, "Describe the character to match.")
    return {"ok": True, "matches": _like(q, max(1, min(req.top_k, 20)))}


def _like(q: list, top_k: int, need_lines: int = 0) -> list:
    import math
    docs = [c for c in _roster() if len(c.get("lines") or []) >= need_lines]
    hays = [f"{c['role']} {c['notes']} {c['facts']} {c['line']}".lower() for c in docs]
    df = {w: sum(1 for h in hays if w in h) for w in q}              # rare words count for more than common ones
    idf = {w: math.log((len(docs) + 1) / (df[w] + 1)) for w in q}
    scored = []
    for c, hay in zip(docs, hays):
        s = sum(idf[w] * (1 + math.log(hay.count(w))) for w in q if w in hay) + sum(2 * idf[w] for w in q if w in c["role"].lower())
        if s:
            scored.append((s, c))
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:top_k]]


def _arc_brief(project: dict, first: int, last: int) -> tuple:
    """What this stretch of the book holds, for the cast generator: the hero's place and realm band, the map's places named there, who is
    already around (with their standing and what they do), and the Systems passages about those places. Visible content only."""
    info = {}
    for v in _arcs(project):
        if v["chapters"][0] <= first <= v["chapters"][1]:
            info = ((project.get("timeline") or {}).get("arcs") or {}).get(str(v["volume"])) or {}
            arc_no = v["volume"]
            break
    else:
        arc_no = None
    text = " ".join(str(info.get(k) or "") for k in ("place", "fights", "escapes", "untouchable"))
    text += " " + " ".join(f"{e.get('title', '')} {e.get('mc_sees', '')}" for e in (project.get("timeline") or {}).get("events") or []
                           if isinstance(e, dict) and e.get("chapter") and first <= e["chapter"] <= last)
    stop = {"the", "and", "with", "then", "only", "from", "into", "their", "they", "them", "this", "that", "beneath", "above", "early", "late",
            "middle", "peak", "realm", "seen", "presence", "condensation", "foundation", "establishment", "core", "formation", "nascent",
            "soul", "deity", "transformation", "void", "refinement", "body", "integration", "mahayana", "tribulation", "transcendence", "mortal",
            "awakening", "fights", "whole", "scroll", "masters", "elders", "younger", "sect"}
    words = [w for w in dict.fromkeys(re.findall(r"[a-z]{4,}", text.lower())) if w not in stop]
    lines = []
    places = [n for n in project.get("location_map") or [] if isinstance(n, dict) and n.get("name")
              and any(w in (n["name"] + " " + str(n.get("description") or "")).lower() for w in words)]
    if places:
        lines.append("THE PLACES OF THIS STRETCH (from the map):")
        lines += [f"- {n['name']}: {str(n.get('description') or '')[:200]}" for n in places[:8]]
    prof = presence_profile(project)
    around = []
    for c in project.get("character_list") or []:
        if not isinstance(c, dict) or not c.get("name") or str(c.get("role", "")).lower() == "protagonist":
            continue
        if any(a <= last and b >= first for a, b in stints_of(project, c, prof)):
            j = next((x for x in c.get("journey") or [] if x.get("arc") == arc_no), {})
            around.append(f"- {c['name']} ({c.get('role', '')}{', ' + j['standing'] if j.get('standing') else ''}{', ' + j['realm'] if j.get('realm') else ''})"
                          + (f": {j['note'][:160]}" if j.get("note") else ""))
    if around:
        lines.append("WHO IS ALREADY AROUND IN THIS STRETCH (new people can work with, serve, owe or know them):")
        lines += around[:25]
    paras = []
    import ast

    def units(v):                        # Systems entries: overview prose by paragraph, listed items as name + description
        if isinstance(v, str) and v.lstrip().startswith(("[{", "{'")):
            try:
                v = ast.literal_eval(v.strip())
            except Exception:
                pass
        if isinstance(v, str):
            yield from (x for x in re.split(r"\n+", v) if len(x) > 60)
        elif isinstance(v, list):
            for x in v:
                yield from units(x)
        elif isinstance(v, dict):
            if v.get("name"):
                yield f"{v['name']}: " + " ".join(str(x) for k, x in v.items() if k != "name" and isinstance(x, str))
            else:
                for x in v.values():
                    yield from units(x)
    for cat, v in (project.get("systems") or {}).items():
        if cat in ("power_levels",):
            continue
        for para in units(v):
            sc = sum(1 for w in words if re.search(rf"\b{w}", para.lower()))
            if sc:
                paras.append((sc, f"- [{cat}] {para.strip()[:320]}"))
    paras.sort(key=lambda x: -x[0])
    if paras:
        lines.append("WHAT THE SYSTEMS SAY ABOUT THESE PLACES:")
        lines += [p for _, p in paras[:6]]
    return "\n".join(lines), words


def _realm_ladder(project: dict) -> list:
    """The book's own realm names, from Systems > power_levels (\"Realm 3: Core Formation (Early / ...)\")."""
    import ast
    lv = ((project.get("systems") or {}).get("power_levels") or {}).get("levels")
    if isinstance(lv, str):
        try:
            lv = ast.literal_eval(lv.strip())
        except Exception:
            lv = []
    out = []
    for x in lv or []:
        m = re.match(r"\s*Realm\s*\d+\s*:\s*([^(]+)", str(x.get("name") if isinstance(x, dict) else x))
        if m:
            out.append(m.group(1).strip())
    return out


def _arc_models(novels: list, words: list) -> list:
    """Corpus characters most like the people this stretch's places need: half from the style novel(s), half from the whole corpus."""
    q = words + ["merchant", "guard", "elder", "friend", "healer", "guide", "official", "servant"]
    style = [m for m in _like(q, 60, need_lines=1) if m["novel"] in novels and not _ENEMY.search(m["role"])][:7]
    other = [m for m in _like(q, 60, need_lines=1) if m["novel"] not in novels and not _ENEMY.search(m["role"])][:7]
    return style + other


class GenerateRequest(BaseModel):
    project_id: str
    first_chapter: int
    last_chapter: int
    count: Optional[int] = None
    note: Optional[str] = None
    provider: Optional[str] = None


@router.post("/generate")
def generate(req: GenerateRequest):
    """Draft new non-enemy characters for a chapter span, at the style novel's pace, as proposals."""
    try:
        return _generate(req)
    except HTTPException:
        raise
    except Exception as e:                   # keep the real cause: log it and say it plainly instead of a bare 500
        import traceback
        try:
            (_root() / "castroster_error.log").write_text(traceback.format_exc(), encoding="utf-8")
        except Exception:
            pass
        raise HTTPException(502, f"Generating characters failed ({type(e).__name__}: {str(e)[:200]}). Nothing was added. Try again.")


def _generate(req: GenerateRequest):
    G = _G()
    pid = req.project_id
    project = _load(pid)
    rate = intro_rate(project)
    cast = project.get("character_list") or []
    planned = sum(1 for c in cast if _int(c.get("intro_chapter")) and req.first_chapter <= _int(c["intro_chapter"]) <= req.last_chapter
                  and not _ENEMY.search(str(c.get("role", ""))))
    count = req.count or max(1, target_for(rate, req.first_chapter, req.last_chapter) - planned)
    count = max(1, min(count, 25))
    brief, words = _arc_brief(project, req.first_chapter, req.last_chapter)
    ladder = _realm_ladder(project)
    models = _arc_models(rate["novels"], words)
    try:
        from routers.pre_generation.canon import canon_context_block
        canon = canon_context_block(project, "visible", req.first_chapter, req.last_chapter, skip=("cast",), cap=8000)
    except Exception:
        canon = ""
    existing = ", ".join(f"{c['name']} ({c.get('role', '')})" for c in cast + (project.get("cast_pending") or []) if isinstance(c, dict))
    arc_lo, arc_hi = next((tuple(v["chapters"]) for v in _arcs(project) if v["chapters"][0] <= req.first_chapter <= v["chapters"][1]),
                          (req.first_chapter, req.last_chapter))
    filled = []                              # the jobs this arc already has, so a later batch fills different needs
    for c in cast + (project.get("cast_pending") or []):
        ic = _int(c.get("intro_chapter")) if isinstance(c, dict) else None
        if ic and arc_lo <= ic <= arc_hi:
            m = re.search(r"Job:\s*([^.]+)", str(c.get("archetype") or ""))
            filled.append(f"- {c['name']} ({c.get('role', '')}): {(m.group(1) if m else str(c.get('archetype') or ''))[:150]}")
    prov = req.provider or G._get_generation_cfg().get("default_provider", "anthropic")
    model, key = (G._get_models_cfg() or {}).get(prov, ""), G._get_key(prov)
    prompt = (
        f"You are building the supporting cast of the web novel \"{project.get('title', '')}\" for chapters {req.first_chapter}-{req.last_chapter}. "
        f"Create {count} NEW characters who are NOT enemies (allies, mentors, friendly rivals, possible love interests, merchants and fixers, "
        "comic relief, neutral officials, people the hero protects).\n\n"
        "Do not invent people at random. First work out what this part of the book NEEDS from its places, events, fights and the people "
        "already around: who runs, guards, serves, trades, judges, cheers, heals or lives in each place the hero passes through; who the "
        "existing allies would bring along; who the events require (a referee for a bout, a ferryman for a crossing, a witness, a guide). "
        "Then make one character per need, so every character has a job in this stretch and a tie to a named place, event or existing "
        "character. Mix tiers (a few major, more supporting, some minor) and kinds of people; no two with the same job.\n\n"
        + (canon + "\n\n" if canon else "")
        + brief + "\n\n"
        + f"THE CAST ALREADY IN THE BOOK (do not repeat or rename them; new people may be tied to them): {existing}\n\n"
        + ("JOBS ALREADY FILLED IN THIS ARC (these needs are covered: do NOT create another person for any of them, find different "
           "needs, places, trades and walks of life):\n" + "\n".join(filled[:60]) + "\n\n" if filled else "")
        + "CORPUS CHARACTERS LIKE THE PEOPLE THESE PLACES NEED (adapt the type and the way they talk, never copy a name):\n"
        + "\n".join(f"- [{m['novel']}] {m['name']} ({m['role']}): {m['notes'][:200]}" + (f" Line: \"{m['line'][:130]}\"" if m['line'] else "") for m in models)
        + (f"\n\nTHE AUTHOR ASKS FOR: {req.note}" if (req.note or "").strip() else "")
        + (f"\n\nREALMS OF THIS BOOK (use only these names, lowest to highest, each with Early, Middle, Late or Peak): "
           f"{', '.join(ladder)}." if ladder else "")
        + "\n\nRULES: no secrets, only what readers can learn from the page. Nobody names or knows of any hidden ruling group; people speak "
          "only of what the world can see: its public institutions, houses, guilds and customs. Nobody knows of the hero's secrets, and no one "
          "is waiting for him or guarding them. At most one character in this batch quietly keeps proof of wrongdoing; the rest have ordinary "
          "jobs, wants and troubles. Tie each character only to people listed under WHO IS ALREADY AROUND, to the existing cast who are present "
          "then, or to places and events of this stretch. Where the book has a power ladder, give each character a rank from it that fits the "
          "place and the hero's rank in this stretch (most below or around him, a few far above); introduce each in the chapter where their "
          "place or event comes up, spread across the span; names that fit the book's culture and setting. Reply with ONE JSON object, no "
          "markdown fences: {\"characters\": [{\"name\": \"\", \"role\": \"ally|mentor|rival-ally|love interest|merchant|comic relief|"
          "neutral|supporting\", \"tier\": \"major|supporting|minor\", \"faction\": \"\", \"job\": \"what they do in this stretch\", "
          "\"tied_to\": \"the place, event or character they connect to\", \"realm\": \"\", \"archetype\": \"one or two sentences\", "
          "\"motivation\": \"\", \"personality_traits\": [\"\"], \"speech_style\": \"\", \"voice\": \"how they talk\", "
          "\"lines\": [\"two short sample lines\"], \"core_belief\": \"\", \"intro_chapter\": 0, \"likeness\": \"novel: corpus "
          "character it is modelled on\"}]}")
    raw = G._call_llm(prompt, prov, model, key, timeout=1800, abort_key=(pid, "castroster"))
    try:
        data = G._parse_json_from_text(raw)
    except Exception:
        data = None
    chars = (data or {}).get("characters") if isinstance(data, dict) else (data if isinstance(data, list) else None)
    if not chars:
        raise HTTPException(502, "The AI's reply wasn't a usable list of characters, so nothing was added. Try again.")
    try:
        from routers.pre_generation.antagonists import _corpus_name_clashes
        clashes = set(_corpus_name_clashes([{"name": c.get("name")} for c in chars if isinstance(c, dict)], project))
    except Exception:
        clashes = set()
    have = {str(c.get("name", "")).lower() for c in cast} | {str(c.get("name", "")).lower() for c in project.get("cast_pending") or []}
    new, dropped = [], []
    for i, c in enumerate(chars):
        cc = _clean_char(c)
        if not cc:
            continue
        if cc["name"].lower() in have or cc["name"] in clashes:
            dropped.append(cc["name"]); continue
        ic = cc.get("intro_chapter")
        cc["intro_chapter"] = ic if ic and req.first_chapter <= ic <= req.last_chapter else req.first_chapter + (i * max(1, (req.last_chapter - req.first_chapter) // max(1, count)))
        cc["id"] = f"cp{int(time.time() * 1000) % 10**10}{i}"
        for k in ("archetype", "motivation"):              # the prompt's own words ("in this batch") never belong in the cast
            cc[k] = re.sub(r"[^.]*\b(in|of) this (batch|list)\b[^.]*\.\s*", " ", cc.get(k) or "").strip()
            cc[k] = re.sub(r"\s{2,}", " ", cc[k])
        realm = str(c.get("realm") or "").strip()
        if ladder and realm and not any(r.lower() in realm.lower() for r in ladder):
            realm = ""                                     # a realm from another novel: leave it for the author rather than keep it
        c["realm"] = realm
        job, tie = (re.sub(r"[,;]?\s*[^.,;:]*(?:in|of) this (?:batch|list)[^.]*", "", _no_ledger(str(c.get(k) or ""))).strip().rstrip(".")
                    for k in ("job", "tied_to"))
        if job or tie:
            cc["archetype"] = (cc.get("archetype") or "") + (f" Job: {job}." if job else "") + (f" Tied to: {tie}." if tie else "")
        arc_no = next((v["volume"] for v in _arcs(project) if v["chapters"][0] <= cc["intro_chapter"] <= v["chapters"][1]), None)
        if arc_no and (c.get("realm") or job):
            cc["journey"] = [{"arc": arc_no, "standing": "stranger", "realm": str(c.get("realm") or "")[:80], "note": job[:300]}]
        if c.get("voice") or c.get("lines"):
            cc["voice"] = str(c.get("voice") or cc.get("speech_style") or "")[:400]
            cc["voice_lines"] = [str(x).strip()[:260] for x in (c.get("lines") or []) if str(x).strip()][:3]
            cc["voice_from"] = str(cc.get("likeness") or "")[:200]
        new.append(cc)
    project = _load(pid)
    project["cast_pending"] = (project.get("cast_pending") or []) + new
    _save(pid, project)
    return {"ok": True, "pending": project["cast_pending"], "added": len(new), "dropped": dropped, "rev": _rev(project)}


class SaveRequest(BaseModel):
    project_id: str
    cast: list
    pending: list = []
    base_rev: Optional[str] = None


@router.post("/save")
def save(req: SaveRequest):
    project = _load(req.project_id)
    if req.base_rev and req.base_rev != _rev(project):
        raise HTTPException(409, "The cast changed since you opened it (another tab, another device or an update). Nothing was saved: reload and try again.")
    hist = project.setdefault("_field_history", {}).setdefault("character_list", [])
    hist.append(copy.deepcopy(project.get("character_list") or []))
    project["_field_history"]["character_list"] = hist[-20:]
    old = {c.get("name"): c for c in project.get("character_list") or [] if isinstance(c, dict)}
    cast = []
    for c in req.cast:
        cc = _clean_char(c)
        if cc:
            cast.append({**old.get(cc["name"], {}), **cc})       # keep any fields this tab does not edit
    project["character_list"] = cast
    project["character_count"] = len(cast)
    project["cast_pending"] = [x for x in (_clean_char(p) for p in req.pending or []) if x]
    _save(req.project_id, project)
    return {"ok": True, "cast": cast, "pending": project["cast_pending"], "rev": _rev(project)}


class UndoRequest(BaseModel):
    project_id: str


@router.post("/undo")
def undo(req: UndoRequest):
    project = _load(req.project_id)
    hist = (project.get("_field_history") or {}).get("character_list") or []
    if not hist:
        raise HTTPException(400, "Nothing to undo.")
    project["character_list"] = hist.pop()
    _save(req.project_id, project)
    return {"ok": True, "cast": project["character_list"], "pending": project.get("cast_pending") or [], "rev": _rev(project)}



# ── presence: who is around when, journeys across the arcs, exits ────────────────────────────────────────────────────
GONE = {"absent", "dead", "gone", "departed", "ascended", "not met", "unknown"}


def presence_profile(project: dict) -> dict:
    """How long characters stay on stage in the style novel: supporting characters live in stints of about a dozen chapters, about half of
    all named characters appear once (measured from the corpus roster, which covers roughly each novel's first hundred chapters)."""
    import statistics as st
    spans = {"supporting": [], "minor": []}
    once = total = 0
    for n in _style_novels(project):
        for f in glob.glob(str(_root() / "character_roster" / n / "*.json")):
            try:
                d = json.loads(open(f, encoding="utf-8").read())
            except Exception:
                continue
            chs = sorted({x.get("source_chapter") for x in d.get("facts") or [] if isinstance(x.get("source_chapter"), int)}
                         | {v.get("chapter") for v in d.get("voice_samples") or [] if isinstance(v.get("chapter"), int)})
            if not chs:
                continue
            total += 1
            if len(chs) == 1:
                once += 1
                continue
            role = str(d.get("role") or "").lower()
            if _ENEMY.search(role):
                continue                                             # the cast roster is the non-enemy cast
            spans["minor" if "minor" in role else "supporting"].append(chs[-1] - chs[0] + 1)
    med = {k: (int(st.median(v)) if v else None) for k, v in spans.items()}
    return {"supporting_stint": max(6, med["supporting"] or 12), "minor_stint": max(2, min(6, med["minor"] or 3)),
            "seen_once_share": round(once / max(1, total), 2),
            "note": "Measured from the style novel's corpus roster (its first ~100 chapters): how long a character stays on stage once introduced."}


def _arc_ranges(project: dict) -> dict:
    return {v["volume"]: tuple(v["chapters"]) for v in _arcs(project)}


def stints_of(project: dict, c: dict, prof: Optional[dict] = None) -> list:
    """When a character is on stage: the author's own stints if set; otherwise from tier, intro chapter, journey and exit."""
    if c.get("stints"):
        return [tuple(x) for x in c["stints"]]
    intro = _int(c.get("intro_chapter"))
    if not intro:
        return []
    prof = prof or presence_profile(project)
    arcs = _arc_ranges(project)
    end_book = max(hi for _, hi in arcs.values()) if arcs else intro
    exit_ch = _int((c.get("exit") or {}).get("chapter")) or end_book
    tier = c.get("tier") or "supporting"
    journey = {j["arc"]: j for j in c.get("journey") or [] if j.get("arc")}
    out = []
    for a, (lo, hi) in sorted(arcs.items()):
        if hi < intro or lo > exit_ch:
            continue
        j = journey.get(a)
        standing = str((j or {}).get("standing") or "").lower()
        if standing in GONE:
            continue
        start, stop = max(lo, intro), min(hi, exit_ch)
        if tier == "major" and (j or lo <= intro <= hi):
            out.append((start, stop))                                    # a major character is around for the whole arc
        elif lo <= intro <= hi:
            span = prof["minor_stint"] if tier == "minor" else prof["supporting_stint"]
            out.append((intro, min(stop, intro + span - 1)))             # the introduction stint
        elif j:                                                          # a return the journey plans
            span = prof["minor_stint"] if tier == "minor" else prof["supporting_stint"]
            out.append((start, min(stop, start + span - 1)))
    return out


def presence_flags(project: dict) -> list:
    arcs = _arc_ranges(project)
    end_book = max(hi for _, hi in arcs.values()) if arcs else 0
    prof = presence_profile(project)
    flags = []
    for c in project.get("character_list") or []:
        if not isinstance(c, dict) or not c.get("name") or _ENEMY.search(str(c.get("role", ""))) or str(c.get("role", "")).lower() == "protagonist":
            continue
        intro, tier = _int(c.get("intro_chapter")), c.get("tier") or "supporting"
        st_ = stints_of(project, c, prof)
        last = max((b for _, b in st_), default=intro or 0)
        exit_ = c.get("exit")
        if tier == "major" and not c.get("journey"):
            flags.append({"name": c["name"], "kind": "no journey", "text": "A major character with no journey across the arcs yet."})
        if intro and not exit_ and end_book - last > 150 and tier != "minor":
            flags.append({"name": c["name"], "kind": "loose end",
                          "text": f"Introduced in chapter {intro}, last around chapter {last}, and no exit: give them a return or an exit."})
        for j in c.get("journey") or []:
            if str(j.get("standing", "")).lower() in ("dead", "ascended") and any(
                    str(k.get("standing", "")).lower() not in GONE for k in c.get("journey") or [] if (k.get("arc") or 0) > (j.get("arc") or 0)):
                flags.append({"name": c["name"], "kind": "contradiction", "text": f"Marked {j['standing']} in arc {j['arc']} but present in a later arc."})
                break
        if exit_ and intro and exit_["chapter"] < intro:
            flags.append({"name": c["name"], "kind": "contradiction", "text": "Exits before being introduced."})
    return flags


def cast_presence_block(project: dict, ch: int, cap: int = 3500) -> str:
    """Who is around in this chapter (from their stints), with their standing and realm for this arc."""
    prof = presence_profile(project)
    arc = next((a for a, (lo, hi) in _arc_ranges(project).items() if lo <= ch <= hi), None)
    rows = []
    for c in project.get("character_list") or []:
        if not isinstance(c, dict) or not c.get("name") or _int(c.get("intro_chapter")) == ch or str(c.get("role", "")).lower() == "protagonist":
            continue
        if any(a <= ch <= b for a, b in stints_of(project, c, prof)):
            j = next((x for x in c.get("journey") or [] if x.get("arc") == arc), {})
            bits = [x for x in (j.get("standing"), j.get("realm")) if x]
            rows.append((0 if c.get("tier") == "major" else 1 if c.get("tier") != "minor" else 2,
                         f"- {c['name']} ({c.get('role', '')}{'; ' + ', '.join(bits) if bits else ''})" + (f": {j['note']}" if j.get("note") else "")))
    if not rows:
        return ""
    rows.sort(key=lambda r: r[0])
    return ("WHO IS AROUND IN THIS PART OF THE BOOK (the cast plan; use them rather than inventing new people, keep their standing and "
            "realm):\n" + "\n".join(r[1] for r in rows))[:cap]


class JourneyRequest(BaseModel):
    project_id: str
    names: Optional[list] = None
    provider: Optional[str] = None


@router.post("/journeys/generate")
def generate_journeys(req: JourneyRequest):
    """Plan the journey across the arcs (standing with the hero, realm, a note per arc) and the exit for the major characters, as proposals."""
    G = _G()
    pid = req.project_id
    project = _load(pid)
    cast = [c for c in project.get("character_list") or [] if isinstance(c, dict)]
    pick = [c for c in cast if (c["name"] in (req.names or [])) or (not req.names and c.get("tier") == "major" and not c.get("journey")
                                                        and str(c.get("role", "")).lower() != "protagonist" and not _ENEMY.search(str(c.get("role", ""))))][:8]
    if not pick:
        raise HTTPException(400, "No major character without a journey. Pick characters, or mark some as major.")
    arcs = _arcs(project)
    try:
        from routers.pre_generation.canon import canon_context_block
        canon = canon_context_block(project, "plan", skip=("cast",), cap=12000)        # planning: the secret tree is allowed here
    except Exception:
        canon = ""
    prov = req.provider or G._get_generation_cfg().get("default_provider", "anthropic")
    model, key = (G._get_models_cfg() or {}).get(prov, ""), G._get_key(prov)
    who = "\n".join(f"- {c['name']} ({c.get('role', '')}, {c.get('faction', '')}), introduced in chapter {c.get('intro_chapter') or '?'}: {str(c.get('archetype', ''))[:200]}" for c in pick)
    arc_list = "; ".join(f"arc {v['volume']} = chapters {v['chapters'][0]}-{v['chapters'][1]}" for v in arcs)
    prompt = (f"Plan the journey of these characters of \"{project.get('title', '')}\" across the book's arcs ({arc_list}).\n\n{who}\n\n"
              + (canon + "\n\n" if canon else "")
              + "For each character and each arc from their introduction to their exit: their STANDING with the hero (stranger, ally, friend, "
                "rival, love, enemy, betrayed, absent, dead or ascended), their REALM that arc (allies grow too, within the realm-gap rule), and a "
                "one-line note of what they do in that arc. Give each an EXIT if they leave the story (chapter, kind: leaves, dies, betrays, "
                "ascends; note), or none if they stay to the end. Use 'absent' for arcs where they are elsewhere (for example while the hero is "
                "beyond the wall). RULES: nothing happens to a character before their introduction chapter; where the canon above fixes a chapter or a "
                "fact for a character (when they break free, who they really are, how they die), follow it exactly; the hero's treasure and "
                "what it holds stay his alone unless the canon says otherwise, so no one else opens, enters or uses it. Reply with ONE JSON "
                "object, no fences: {\"characters\": [{\"name\": \"\", \"journey\": [{\"arc\": 1, \"standing\": "
                "\"\", \"realm\": \"\", \"note\": \"\"}], \"exit\": {\"chapter\": 0, \"kind\": \"\", \"note\": \"\"} or null}]}")
    raw = G._call_llm(prompt, prov, model, key, timeout=1800, abort_key=(pid, "castjourney"))
    try:
        data = G._parse_json_from_text(raw)
    except Exception:
        data = None
    out = (data or {}).get("characters") if isinstance(data, dict) else None
    if not out:
        raise HTTPException(502, "The AI's reply wasn't usable journeys, so nothing was added. Try again.")
    names = {c["name"] for c in pick}
    props = {}
    for o in out:
        if isinstance(o, dict) and o.get("name") in names:
            cc = _clean_char({"name": o["name"], "journey": o.get("journey"), "exit": o.get("exit")})
            props[o["name"]] = {"journey": cc.get("journey") or [], "exit": cc.get("exit")}
    project = _load(pid)
    project["cast_pending_journeys"] = {**(project.get("cast_pending_journeys") or {}), **props}
    _save(pid, project)
    return {"ok": True, "pending_journeys": project["cast_pending_journeys"], "rev": _rev(project)}


class JourneyDecisionRequest(BaseModel):
    project_id: str
    accept: list = []
    decline: list = []
    base_rev: Optional[str] = None


@router.post("/journeys/decide")
def decide_journeys(req: JourneyDecisionRequest):
    project = _load(req.project_id)
    if req.base_rev and req.base_rev != _rev(project):
        raise HTTPException(409, "The cast changed since you opened it. Nothing was saved: reload and try again.")
    pend = project.get("cast_pending_journeys") or {}
    hist = project.setdefault("_field_history", {}).setdefault("character_list", [])
    hist.append(copy.deepcopy(project.get("character_list") or []))
    project["_field_history"]["character_list"] = hist[-20:]
    for c in project.get("character_list") or []:
        if c.get("name") in req.accept and c["name"] in pend:
            c["journey"] = pend[c["name"]]["journey"]
            if pend[c["name"]].get("exit"):
                c["exit"] = pend[c["name"]]["exit"]
    for n in list(req.accept) + list(req.decline):
        pend.pop(n, None)
    project["cast_pending_journeys"] = pend
    _save(req.project_id, project)
    return {"ok": True, "cast": project["character_list"], "pending_journeys": pend, "rev": _rev(project)}


# ── voices: how each character talks, adapted from the corpus characters they are most like ─────────────────────────
def _voice_query(c: dict) -> list:
    t = " ".join([str(c.get(k) or "") for k in ("role", "archetype", "speech_style", "banter_style", "motivation")]
                 + [str(x) for x in c.get("personality_traits") or []]).lower()
    stop = {"the", "and", "who", "with", "for", "his", "her", "that", "their", "from", "into", "they", "this", "when", "but", "not", "him", "has", "are", "was"}
    return list(dict.fromkeys(w for w in re.findall(r"[a-z]{3,}", t) if w not in stop))[:40]


def cast_voice_block(project: dict, ch: int, cap: int = 3000) -> str:
    """How the characters around in this chapter talk: their voice and a few sample lines, for the writer. Samples show the voice only."""
    prof = presence_profile(project)
    rows = []
    for c in project.get("character_list") or []:
        if not isinstance(c, dict) or not c.get("name") or not (c.get("voice") or c.get("voice_lines")):
            continue
        here = _int(c.get("intro_chapter")) == ch or any(a <= ch <= b for a, b in stints_of(project, c, prof))
        if not here and str(c.get("role", "")).lower() != "protagonist":
            continue
        line = f"- {c['name']}: {c.get('voice') or c.get('speech_style') or ''}"
        if c.get("voice_lines"):
            line += " Sounds like: " + " / ".join(f"\"{x}\"" for x in c["voice_lines"][:3])
        rows.append((0 if str(c.get("role", "")).lower() == "protagonist" else 1 if c.get("tier") == "major" else 2, line))
    if not rows:
        return ""
    rows.sort(key=lambda r: r[0])
    return ("HOW THESE CHARACTERS TALK (give each speaker this voice so they can be told apart without tags; the sample lines show the voice, "
            "never repeat them word for word):\n" + "\n".join(r[1] for r in rows))[:cap]


class VoiceRequest(BaseModel):
    project_id: str
    names: Optional[list] = None
    provider: Optional[str] = None


@router.post("/voices/generate")
def generate_voices(req: VoiceRequest):
    """Give characters a voice (a short description and three sample lines) adapted from the real lines of the corpus characters they are
    most like, as proposals."""
    G = _G()
    pid = req.project_id
    project = _load(pid)
    cast = [c for c in project.get("character_list") or [] if isinstance(c, dict) and c.get("name")]
    if req.names:
        pick = [c for c in cast if c["name"] in req.names]
    else:
        order = {"major": 0, "supporting": 1, "minor": 2}
        pick = sorted([c for c in cast if not c.get("voice_lines")], key=lambda c: (order.get(c.get("tier"), 1), _int(c.get("intro_chapter")) or 9999))
    pick = pick[:10]
    if not pick:
        raise HTTPException(400, "Every character already has a voice. Pick characters to redo.")
    blocks = []
    for c in pick:
        models = _like(_voice_query(c), 3, need_lines=2)
        ex = "\n".join(f"    [{m['novel']}] {m['name']} ({m['role']}): " + " | ".join(
            f"\"{x['line'][:180]}\"" + (f" ({x['note'][:110]})" if x["note"] else "") for x in m["lines"][:3]) for m in models)
        blocks.append((c, ", ".join(f"{m['novel']}: {m['name']}" for m in models),
                       f"- {c['name']} ({c.get('role', '')}, {c.get('tier', '')}, {c.get('faction', '')}): {str(c.get('archetype', ''))[:220]}"
                       + (f" Speech now: {c.get('speech_style')}" if c.get("speech_style") else "")
                       + (f" Traits: {', '.join(c.get('personality_traits') or [])}" if c.get("personality_traits") else "")
                       + ("\n  Corpus characters most like them, with real lines:\n" + ex if ex else "")))
    try:
        from routers.pre_generation.canon import canon_context_block
        canon = canon_context_block(project, "visible", skip=("cast", "timeline"), cap=5000)      # voices reach the writer: no secrets
    except Exception:
        canon = ""
    prov = req.provider or G._get_generation_cfg().get("default_provider", "anthropic")
    model, key = (G._get_models_cfg() or {}).get(prov, ""), G._get_key(prov)
    prompt = (f"Give each of these characters of the web novel \"{project.get('title', '')}\" a distinct VOICE, so a reader can tell who is "
              "speaking without a tag. Study the real lines of the corpus characters listed under each one: their rhythm, sentence length, "
              "register, verbal habits, how they address others, what they joke or boast about. Adapt that to this character and this world. "
              "Never copy a corpus line, name or place.\n\n"
              + (canon + "\n\n" if canon else "")
              + "\n\n".join(b[2] for b in blocks)
              + "\n\nFor each character: VOICE = one or two sentences on how they talk (register, rhythm, habits, words they favour or avoid). "
                "LINES = three short lines they might say in this book, in different moods (for example calm, angry, joking), with no secrets "
                "and nothing that commits the plot. Make the characters sound different from each other. Reply with ONE JSON object, no fences: "
                "{\"characters\": [{\"name\": \"\", \"voice\": \"\", \"lines\": [\"\", \"\", \"\"]}]}")
    raw = G._call_llm(prompt, prov, model, key, timeout=1800, abort_key=(pid, "castvoice"))
    try:
        data = G._parse_json_from_text(raw)
    except Exception:
        data = None
    out = (data or {}).get("characters") if isinstance(data, dict) else (data if isinstance(data, list) else None)
    if not out:
        raise HTTPException(502, "The AI's reply wasn't usable voices, so nothing was added. Try again.")
    src = {b[0]["name"]: b[1] for b in blocks}
    props = {}
    for o in out:
        if isinstance(o, dict) and o.get("name") in src:
            cc = _clean_char({"name": o["name"], "voice": o.get("voice"), "voice_lines": o.get("lines") or o.get("voice_lines")})
            if cc.get("voice") or cc.get("voice_lines"):
                props[o["name"]] = {"voice": cc.get("voice", ""), "voice_lines": cc.get("voice_lines") or [], "voice_from": src[o["name"]]}
    if not props:
        raise HTTPException(502, "The AI's reply named none of the characters asked for, so nothing was added. Try again.")
    project = _load(pid)
    project["cast_pending_voices"] = {**(project.get("cast_pending_voices") or {}), **props}
    _save(pid, project)
    return {"ok": True, "pending_voices": project["cast_pending_voices"], "rev": _rev(project)}


@router.post("/voices/decide")
def decide_voices(req: JourneyDecisionRequest):
    project = _load(req.project_id)
    if req.base_rev and req.base_rev != _rev(project):
        raise HTTPException(409, "The cast changed since you opened it. Nothing was saved: reload and try again.")
    pend = project.get("cast_pending_voices") or {}
    hist = project.setdefault("_field_history", {}).setdefault("character_list", [])
    hist.append(copy.deepcopy(project.get("character_list") or []))
    project["_field_history"]["character_list"] = hist[-20:]
    for c in project.get("character_list") or []:
        if c.get("name") in req.accept and c["name"] in pend:
            c.update({k: pend[c["name"]][k] for k in ("voice", "voice_lines", "voice_from") if pend[c["name"]].get(k)})
    for n in list(req.accept) + list(req.decline):
        pend.pop(n, None)
    project["cast_pending_voices"] = pend
    _save(req.project_id, project)
    return {"ok": True, "cast": project["character_list"], "pending_voices": pend, "rev": _rev(project)}
