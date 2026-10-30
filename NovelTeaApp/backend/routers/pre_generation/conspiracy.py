"""CONSPIRACY tab (Pre-generation): the book's hidden scheme as a tree.

The author's final, biggest scheme sits at the root. It is reverse-engineered downward into the minor schemes that serve it, and each of
those into the events, false flags and cover-ups that carry it out, and finally into the clues, breadcrumbs and mistakes the hero can find.
Research comes from the corpus: whole-novel rolling summaries (story shapes), semantic search over extracted schemes/reveals/antagonist
templates, and the raw chapter text around the best matches.

Stored at project["conspiracy"] = {"reveal_arc": int, "nodes": [node], "updated": ts}. A node:
  {id, parent, type, title, text (the TRUTH), surface (what people believe happened), who, chapter, arc, status, sources}
type is one of NODE_TYPES. Secrecy (author's choice): the arc and chapter-skeleton PLANNERS see the whole tree, marked secret; the CHAPTER
WRITER sees only what is pinned to its chapter, as surface events to show and clues to plant, never the truth behind them."""
import copy
import json
import re
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

NODE_TYPES = ["final_scheme", "scheme", "agent", "event", "false_flag", "patsy", "cover_up", "clue", "breadcrumb", "mistake"]
# Words the model uses for a node type, mapped onto the tree's types (a Bourne-style plot brings handlers, safehouses, burn notices...).
_TYPE_ALIASES = {
    "agent": ["agent", "operative", "handler", "sleeper", "sleeper_agent", "cleaner", "assassin", "asset", "proxy", "spy", "informant", "mole",
              "infiltrator", "courier", "enforcer", "puppet", "pawn", "person", "character", "recruiter", "controller"],
    "scheme": ["scheme", "minor_scheme", "sub_scheme", "plot", "operation", "op", "programme", "program", "project", "network", "front",
               "cell", "ring", "conspiracy", "plan", "psyop", "psychological_operation"],
    "event": ["event", "kill_order", "burn_notice", "purge", "hit", "ambush", "raid", "meeting", "handoff", "drop", "dead_drop",
              "safehouse", "extraction", "incident", "operation_event", "assassination", "rescue", "staged_rescue", "lottery_draw", "bout"],
    "false_flag": ["false_flag", "false_flame", "falseflag", "staged_attack", "frame_attack"],
    "patsy": ["patsy", "scapegoat", "fall_guy", "framed"],
    "cover_up": ["cover_up", "coverup", "cover", "erasure", "scrub", "cleanup", "clean_up", "tidy"],
    "clue": ["clue", "evidence", "hint", "lead", "trace"],
    "breadcrumb": ["breadcrumb", "bread_crumb", "trail", "rumor", "rumour", "sign"],
    "mistake": ["mistake", "slip", "error", "blunder", "flaw", "leak"],
    "final_scheme": ["final_scheme", "root", "master_scheme", "final"],
}
_ALIAS = {a: t for t, words in _TYPE_ALIASES.items() for a in words}
VISIBLE_TYPES = {"clue", "breadcrumb", "mistake"}            # things the hero can find; planted in the chapter they are pinned to
SURFACE_TYPES = {"event", "false_flag", "patsy", "cover_up", "agent"}   # an agent shows on the page only as their cover identity
SURFACE_TYPES_PLACEHOLDER = None   # things that happen on the page; the writer sees only their surface
# A PATSY is the person or group framed for a false flag or a crime: its surface is the public accusation, its text why they were chosen.


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


def _llm(pid: str, provider: Optional[str] = None):
    G = _G()
    prov = provider or G._get_generation_cfg().get("default_provider", "anthropic")
    return prov, (G._get_models_cfg() or {}).get(prov, ""), G._get_key(prov)


def _int_or_none(v):
    try:
        return int(v) if v not in (None, "", "null") else None
    except (TypeError, ValueError):
        return None


def _new_id(i: int = 0) -> str:
    return f"c{int(time.time() * 1000) % 10**10}{i}"


def _clean_node(n: dict, i: int = 0) -> dict:
    n = n if isinstance(n, dict) else {}
    t = str(n.get("type") or n.get("kind") or n.get("node_type") or "").strip().lower().replace(" ", "_").replace("-", "_")
    t = t if t in NODE_TYPES else _ALIAS.get(t) or next((v for k, v in _ALIAS.items() if k in t), "event")
    pick = lambda *keys: next((str(n[k]) for k in keys if n.get(k) not in (None, "")), "")
    return {
        "id": str(n.get("id") or _new_id(i)),
        "parent": (str(n["parent"]) if n.get("parent") else None),
        "type": t,
        "title": pick("title", "name", "label", "codename", "heading").strip()[:140],
        "text": pick("text", "truth", "description", "details", "summary", "what").strip()[:1500],
        "surface": pick("surface", "cover_story", "cover", "public_story", "seen_as", "what_people_believe").strip()[:600],
        "who": str(n.get("who") or "").strip()[:200],
        "chapter": _int_or_none(n.get("chapter")),
        "arc": _int_or_none(n.get("arc")),
        "status": str(n.get("status") or "planned") if str(n.get("status") or "planned") in ("planned", "planted", "revealed") else "planned",
        "sources": [str(s)[:200] for s in (n.get("sources") or []) if s][:6],
    }


def _clean_tree(c: dict) -> dict:
    c = c if isinstance(c, dict) else {}
    nodes = [_clean_node(n, i) for i, n in enumerate(c.get("nodes") or []) if isinstance(n, dict)][:400]
    ids = {n["id"] for n in nodes}
    for n in nodes:                                   # orphans hang off the root instead of vanishing
        if n["parent"] and n["parent"] not in ids:
            n["parent"] = None
    pend = c.get("pending") if isinstance(c.get("pending"), dict) else None
    if pend:
        pend = {"replace": bool(pend.get("replace")), "note": str(pend.get("note") or "")[:600], "created": pend.get("created") or int(time.time()),
                "nodes": [_clean_node(n, i) for i, n in enumerate(pend.get("nodes") or []) if isinstance(n, dict)][:400]}
        if not pend["nodes"]:
            pend = None
    return {"reveal_arc": _int_or_none(c.get("reveal_arc")) or 2, "book_chapters": _int_or_none(c.get("book_chapters")) or 1500,
            "arcs_total": _int_or_none(c.get("arcs_total")), "pending": pend, "nodes": nodes, "updated": int(time.time())}


def _tree(project: dict) -> dict:
    return _clean_tree(project.get("conspiracy") or {})


def _store(pid: str, project: dict, tree: dict):
    old = project.get("conspiracy")
    if old and old.get("nodes"):
        hist = project.setdefault("_field_history", {}).setdefault("conspiracy", [])
        hist.append(copy.deepcopy(old))
        project["_field_history"]["conspiracy"] = hist[-20:]
    project["conspiracy"] = _clean_tree(tree)
    _save(pid, project)
    return project["conspiracy"]


# ── prompt blocks ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _outline(nodes: list, cap: int) -> str:
    kids = {}
    for n in nodes:
        kids.setdefault(n.get("parent"), []).append(n)
    out = []

    def rec(pid, depth):
        for n in kids.get(pid, []):
            pin = []
            if n.get("chapter"):
                pin.append(f"ch {n['chapter']}")
            elif n.get("arc"):
                pin.append(f"arc {n['arc']}")
            line = f"{'  ' * depth}- [{n['type']}{', ' + ', '.join(pin) if pin else ''}] {n['title']}: {n['text']}"
            if n.get("surface"):
                line += f" (what people believe: {n['surface']})"
            if n.get("who"):
                line += f" (who: {n['who']})"
            out.append(line)
            rec(n["id"], depth + 1)
    rec(None, 0)
    return "\n".join(out)[:cap]


def conspiracy_planner_block(project: dict, cap: int = 6000) -> str:
    """The whole tree, for the arc and chapter-skeleton planners only (author's choice). Marked secret."""
    t = _tree(project)
    if not t["nodes"]:
        return ""
    return ("THE CONSPIRACY (SECRET - for planning only. Plan around it: put its events, false flags and cover-ups where they are pinned, and "
            f"plant its clues, breadcrumbs and mistakes in their chapters. Its truth is revealed no earlier than arc {t['reveal_arc']}. Before then "
            "NEVER write the hidden truth into a chapter plan's text, a hook, or anything the reader sees: plans describe only what happens on "
            "the surface and what the hero notices and questions.):\n" + _outline(t["nodes"], cap))


def conspiracy_chapter_block(project: dict, ch: int, cap: int = 2000) -> str:
    """What the chapter WRITER may see: only nodes pinned to this chapter. Events show as their surface; clues show as things to plant."""
    t = _tree(project)
    pinned = [n for n in t["nodes"] if n.get("chapter") == ch]
    if not pinned:
        return ""
    arc_of = _G()._arc_index_of(project, ch) if hasattr(_G(), "_arc_index_of") else 0
    revealed = (arc_of or 0) + 1 >= t["reveal_arc"]
    lines = ["IN THIS CHAPTER (the author's plan - show these, never explain them, and never state who is behind them):"]
    for n in pinned:
        if n["type"] == "agent":
            if revealed or n.get("status") == "revealed":
                lines.append(f"- ON THE PAGE: {n['title']}: {n['text']}")
            elif n.get("surface"):
                lines.append(f"- ON THE PAGE (only as their cover; never reveal what they really are): {n['surface']}")
        elif n["type"] in SURFACE_TYPES:
            what = n["text"] if (revealed or n.get("status") == "revealed") else (n.get("surface") or n["title"])
            lines.append(f"- HAPPENS: {what}")
        elif n["type"] in VISIBLE_TYPES:
            lines.append(f"- PLANT ({n['type']}): {n.get('surface') or n['title']}. The hero may notice it and question it; nobody explains it.")
        elif revealed or n.get("status") == "revealed":
            lines.append(f"- REVEALED: {n['title']}: {n['text']}")
    return "\n".join(lines)[:cap] if len(lines) > 1 else ""


def conspiracy_surface_block(project: dict, first: int, last: int, cap: int = 2000) -> str:
    """What happens on the page over a stretch of the book, from the tree, writer-safe: only the SURFACE of events, false flags, cover-ups and
    clues (what a reader and the hero see), never the truth, the schemes or who is behind it."""
    t = _tree(project)
    rows = []
    for n in t["nodes"]:
        ch = n.get("chapter")
        if not isinstance(ch, int) or not (first <= ch <= last) or n["type"] not in SURFACE_TYPES | VISIBLE_TYPES:
            continue
        if n["type"] == "agent" or (n["type"] in SURFACE_TYPES and not (n.get("surface") or n.get("title"))):
            continue
        rows.append((ch, f"- ch {ch}: {n.get('surface') or n['title']}"))
    if not rows:
        return ""
    rows.sort()
    step = max(1, len(rows) // 24)                               # an even spread when the stretch is long
    return ("PLANNED HAPPENINGS IN THESE CHAPTERS (what the page shows; use them as scenes and moods, never explain or hint at the cause):\n"
            + "\n".join(r for _, r in rows[::step]))[:cap]


# ── corpus research ───────────────────────────────────────────────────────────────────────────────────────────────────
def _research(query: str, pid: str, raw_excerpts: int = 4, project: Optional[dict] = None) -> tuple[str, list]:
    """Rolling summaries (whole-novel story shapes), the comparable authors' own long-running threads (author brains: truth, seed chapter,
    clues with chapters, misdirection, reveal), semantic search over schemes/reveals/antagonist templates, and raw chapter text around the
    best matches. Returns (prompt block, source labels). Empty on any failure: research helps, it is never required."""
    G = _G()
    parts, sources = [], []
    try:
        shape = G._semantic_story_shape_block(query, top_k=3, label="conspiracy", project_id=pid, max_chars=1000)
        if shape:
            parts.append(shape)
    except Exception:
        pass
    try:    # how comparable authors ran their long secrets, seed to reveal, with chapter timing
        from routers.corpus_tools.author_brain import thread_block
        tb = thread_block(project or {}, query, project_id=pid, top_k=6, cap=4200)
        if tb:
            parts.append(tb)
    except Exception:
        pass
    try:    # saved Blueprints (reference systems the author extracted) by semantic search
        bp = G._semantic_blueprint_block(query, top_k=6, label="conspiracy", project_id=pid)
        if bp:
            parts.append(bp)
    except Exception:
        pass
    try:    # this book's own Systems (factions, places, techniques, encounters) by semantic search, so new nodes reuse real canon
        own = G._semantic_project_systems_block(query, pid, top_k=6, label="conspiracy")
        if own:
            parts.append(own)
    except Exception:
        pass
    try:
        from routers.corpus_tools.corpus import knowledge_search
        rows = []
        for cat, k in (("scheme", 6), ("reveal", 6), ("antagonist_template", 3)):
            try:
                rows += knowledge_search(query, top_k=k, category=cat)
            except Exception:
                pass
        rows.sort(key=lambda r: -float(r.get("score") or 0))
        if rows:
            parts.append("HOW CORPUS NOVELS RUN SCHEMES, FALSE FLAGS, COVER-UPS AND REVEALS (adapt the mechanics, never copy names or plots):\n"
                         + "\n".join(f"- [{r['category']}] {r['novel_title']} ch{r.get('chapter') or '?'}: {r['text'][:260]}" for r in rows[:14]))
            sources += [f"{r['novel_title']} ch{r.get('chapter')}" for r in rows[:14] if r.get("chapter")]
        got = 0
        for r in rows:
            if got >= raw_excerpts or not r.get("chapter"):
                continue
            needle = re.split(r"[:;.]", r["text"].split(": ", 1)[-1])[0][:60]
            raw = G._grep_raw_chapter_context(r["novel_id"], int(r["chapter"]), needle, context_chars=700)
            if raw:
                parts.append(f"RAW TEXT, {r['novel_title']} ch{r['chapter']} (how the moment is actually written on the page):\n{raw[:1400]}")
                got += 1
    except Exception:
        pass
    return "\n\n".join(parts)[:12000], sources[:12]      # kept short: a long prompt made the slower engines time out


def _story_context(project: dict) -> str:
    wb = project.get("world_bible") or {}
    lore = [f"- {e.get('title')}: {str(e.get('text'))[:240]}" for e in ((project.get("lore") or {}).get("world") or [])
            if isinstance(e, dict) and e.get("status") == "approved"]
    secrets = project.get("author_secrets") or {}
    sec = ("\n".join(f"- {k}: {str(v)[:330]}" for k, v in secrets.items() if k != "note") if isinstance(secrets, dict)
           else "\n".join(f"- {str(s)[:330]}" for s in secrets))
    facs = [f"- {f.get('name')}: {str(f.get('description') or '')[:130]}" for f in (wb.get("factions") or []) if isinstance(f, dict)]
    arcs = [f"- Arc {i + 1} '{a.get('label')}' (chapters {(a.get('chapters') or [0])[0]}-{(a.get('chapters') or [0])[-1]})"
            for i, a in enumerate(project.get("arcs") or []) if isinstance(a, dict)]
    foes = [f"- {e.get('name')} ({e.get('tier')}): {str(e.get('who') or '')[:160]}" for e in ((project.get("antagonists") or {}).get("roster") or []) if isinstance(e, dict)]
    clue_note = _notes(project).get("clues_and_questions", "")
    return (f"PREMISE: {project.get('premise') or (project.get('creative_brief') or {}).get('premise', '')}\n\n"
            "WORLD RULES:\n" + "\n".join(f"- {r}" for r in (wb.get("rules") or [])) + "\n\n"
            + ("LORE:\n" + "\n".join(lore) + "\n\n" if lore else "")
            + ("THE AUTHOR'S SECRETS (the hidden truth this tree must serve):\n" + sec + "\n\n" if sec else "")
            + ("FACTIONS:\n" + "\n".join(facs[:18]) + "\n\n" if facs else "")
            + ("ARCS ALREADY PLANNED:\n" + "\n".join(arcs) + "\n\n" if arcs else "")
            + _book_shape(project)
            + ("FOES:\n" + "\n".join(foes[:20]) + "\n\n" if foes else "")
            + (f"HOW CLUES WORK IN THIS BOOK: {clue_note}\n\n" if clue_note else "")
            + _canon_extra(project))



def _rnd(x: float) -> int:
    return int(x + 0.5)


def book_volumes(total: int, arcs_total: Optional[int] = None) -> list:
    """The book's volumes ("maps"), growing as the book goes on, then a shorter finale. Modelled on real long web novels:
    volumes that start short and grow (for example ~115 -> 250 -> 371 -> 967 -> 2,155 chapters, then a shorter finale), moving
    through ~8 worlds of ~300 -> 1,000+ chapters. Arcs inside a volume lengthen too (about a quarter of the volume, 30-150 chapters).
    Mirrored exactly by bookVolumes() in ConspiracyTab.jsx. Returns [{volume, chapters: [first, last], arcs: [first, last]}]."""
    total = max(40, int(total or 1500))
    if arcs_total:      # the author fixed the number of arcs: each arc is its own map, growing more gently, then a shorter finale
        n = max(2, min(50, int(arcs_total)))
        w = [1.2 ** i for i in range(n - 1)] + [1.2 ** (n - 2) * 0.45]
        lens = [max(10, _rnd(total * x / sum(w))) for x in w]
        lens[-1] = max(10, lens[-1] + total - sum(lens))
        out, ch = [], 1
        for v, L in enumerate(lens, 1):
            out.append({"volume": v, "chapters": [ch, ch + L - 1], "arcs": [v, v]})
            ch += L
        return out
    nv = 9 if total >= 3000 else 8 if total >= 1500 else 6 if total >= 600 else 4
    w = [1.35 ** i for i in range(nv - 1)] + [1.35 ** (nv - 2) * 0.45]
    lens = [max(20, _rnd(total * x / sum(w))) for x in w]
    lens[-1] = max(20, lens[-1] + total - sum(lens))
    out, ch, arc = [], 1, 1
    for v, L in enumerate(lens, 1):
        n = max(1, _rnd(L / min(150, max(30, _rnd(L / 4)))))
        out.append({"volume": v, "chapters": [ch, ch + L - 1], "arcs": [arc, arc + n - 1]})
        ch += L
        arc += n
    return out


def _notes(project: dict) -> dict:
    """craft_notes as named sections; some books keep them as a plain list, which has no named rules."""
    cn = project.get("craft_notes")
    return cn if isinstance(cn, dict) else {}


def _maps_rule(project: dict) -> str:
    """What a 'map' is in THIS book: the author's own rule (craft note book_maps) or the usual web-novel default."""
    rule = str((_notes(project).get("book_maps")) or "").strip()
    return ("THE MAPS: " + rule + "\n") if rule else ("THE MAPS: each new volume is a new map: a new place, a new power tier and new enemies, "
                                                       "and each map hides its own part of the conspiracy.\n")


def _book_shape(project: dict) -> str:
    """The plan of volumes and arcs given to the tree builder, and the rule that the conspiracy is peeled one layer per volume."""
    c = project.get("conspiracy") or {}
    total = _int_or_none(c.get("book_chapters")) or _int_or_none(project.get("target_chapters")) or 1500
    vols = book_volumes(total, _int_or_none(c.get("arcs_total")))
    n_arcs = vols[-1]["arcs"][1]
    lines = "\n".join(f"  Volume {v['volume']}: chapters {v['chapters'][0]}-{v['chapters'][1]}, arcs {v['arcs'][0]}-{v['arcs'][1]}" for v in vols)
    return (f"THE BOOK'S SHAPE (a long web novel, ~{total} chapters). It is built from VOLUMES, each a new 'map' (new place, new power tier, "
            "new enemies) that runs opening -> rising conflict -> turn -> climax -> close. Volumes GROW as the book goes on, as in long web novels "
            "generally, then the finale is shorter. Each volume holds several ARCS:\n" + lines + "\n"
            + _maps_rule(project)
            + "PEEL THE CONSPIRACY ONE LAYER PER VOLUME: each minor scheme is exposed at the climax of one volume (the last arc of that volume), "
            "its clues are seeded one to three volumes earlier, and every reveal opens the next, deeper layer. The final scheme is exposed only "
            "in the last volume, but it gets small breadcrumbs from volume 1. Most volumes should expose one scheme. Pin every node to an arc "
            f"between 1 and {n_arcs}; pin early clues and on-page events to chapters as well.\n\n")


def _canon_extra(project: dict) -> str:
    try:
        from routers.pre_generation.canon import canon_context_block
        b = canon_context_block(project, "plan", skip=("lore", "conspiracy", "foes"), cap=11000)
        return (b + "\n\n") if b else ""
    except Exception:
        return ""


_NODE_SCHEMA = ('{"type": "final_scheme | scheme | agent | event | false_flag | patsy | cover_up | clue | breadcrumb | mistake", "title": "short name", '
                '"text": "the TRUTH, 1-3 plain sentences", "surface": "what people believe happened (for events, false flags, cover-ups) or what '
                'the hero actually sees (for clues)", "who": "who does it", "arc": 1, "chapter": null, "children": [ ...same shape... ]}')


def _flatten(node: dict, parent: Optional[str], out: list, sources: list):
    n = _clean_node({**node, "parent": parent, "sources": sources if not parent else []}, len(out))
    if not n["title"] and not n["text"]:          # a blank node is skipped; anything under it hangs on its parent instead
        for c in (node.get("children") or [])[:12]:
            if isinstance(c, dict):
                _flatten(c, parent, out, sources)
        return
    n["id"] = _new_id(len(out))
    out.append(n)
    for c in (node.get("children") or [])[:12]:
        if isinstance(c, dict):
            _flatten(c, n["id"], out, sources)



_LAST_RAW = ""


def _dump_raw(pid: str):
    """Keep the last unusable AI reply on disk so a failure can be looked at."""
    try:
        (_G().CORPUS_PATH / "projects" / pid / "_conspiracy_last_reply.txt").write_text(_LAST_RAW[:200000], encoding="utf-8")
    except Exception:
        pass


def _list_from(data, keys) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in keys:
            if isinstance(data.get(k), list):
                return data[k]
        lists = [v for v in data.values() if isinstance(v, list)]
        if len(lists) == 1:
            return lists[0]
    return []

def _ask(prompt: str, pid: str, provider: Optional[str]):
    G = _G()
    prov, model, key = _llm(pid, provider)
    try:
        raw = G._call_llm(prompt, prov, model, key, timeout=1800, abort_key=(pid, "conspiracy"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"The AI call failed ({type(e).__name__}: {str(e)[:200]}). Nothing was changed; try again.")
    global _LAST_RAW
    _LAST_RAW = str(raw or "")
    try:
        return G._parse_json_from_text(raw)
    except Exception:
        _dump_raw(pid)
        return None




def _fit_chapters(project: dict, nodes: list) -> list:
    """A node's chapter must sit inside its arc's chapter range (the model often pins an arc-6 event to chapter 5). A chapter outside the
    range is moved into it, keeping its relative place; a node with a chapter but no arc takes the arc that chapter falls in."""
    c = project.get("conspiracy") or {}
    vols = book_volumes(_int_or_none(c.get("book_chapters")) or 1500, _int_or_none(c.get("arcs_total")))
    by_arc = {}
    for v in vols:
        for a in range(v["arcs"][0], v["arcs"][1] + 1):
            span = v["chapters"][1] - v["chapters"][0] + 1
            per = max(1, span // (v["arcs"][1] - v["arcs"][0] + 1))
            k = a - v["arcs"][0]
            by_arc[a] = (v["chapters"][0] + k * per, v["chapters"][0] + (k + 1) * per - 1)
    for n in nodes:
        ch, a = n.get("chapter"), n.get("arc")
        if ch and not a:
            n["arc"] = next((x for x, (lo, hi) in by_arc.items() if lo <= ch <= hi), None)
        elif ch and a in by_arc:
            lo, hi = by_arc[a]
            if not lo <= ch <= hi:
                n["chapter"] = lo + (ch - 1) % (hi - lo + 1)
    return nodes

def _keep_pending(pid: str, project: dict, nodes: list, replace: bool, note: Optional[str]) -> list:
    """Store generated nodes as the tree's pending proposal (not part of the tree until the author accepts them). A new rebuild replaces
    the pending proposal; a grow adds to it. Returns everything now pending."""
    c = project.get("conspiracy") or {}
    nodes = _fit_chapters(project, nodes)
    old = c.get("pending") if isinstance(c.get("pending"), dict) else None
    if replace or not old or old.get("replace"):
        pend = {"replace": replace, "note": note or "", "created": int(time.time()), "nodes": nodes}
    else:
        pend = {**old, "nodes": (old.get("nodes") or []) + nodes, "note": ((old.get("note") or "") + " | " + (note or "")).strip(" |")}
    c["pending"] = pend
    project["conspiracy"] = c
    _save(pid, project)
    return pend["nodes"]



def tree_rev(project: dict) -> str:
    """A fingerprint of the tree as it is on disk, so a save from a stale copy (another tab, another device) can be refused."""
    import hashlib
    c = project.get("conspiracy") or {}
    return hashlib.sha1(json.dumps([c.get("nodes") or [], (c.get("pending") or {}).get("nodes") or [], c.get("book_chapters"),
                                    c.get("arcs_total"), c.get("reveal_arc")], ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]

# ── endpoints ─────────────────────────────────────────────────────────────────────────────────────────────────────────
@router.get("/{project_id}")
def get_tree(project_id: str):
    project = _load(project_id)
    t = _tree(project)
    return {"ok": True, "conspiracy": t, "rev": tree_rev(project), "types": NODE_TYPES, "volumes": book_volumes(t["book_chapters"], t.get("arcs_total")),
            "arcs": [{"label": a.get("label"), "chapters": a.get("chapters")} for a in (project.get("arcs") or []) if isinstance(a, dict)]}


class SaveRequest(BaseModel):
    project_id: str
    conspiracy: dict
    base_rev: Optional[str] = None      # the tree's rev when this copy was loaded; a mismatch means someone else changed it since


@router.post("/save")
def save_tree(req: SaveRequest):
    project = _load(req.project_id)
    if req.base_rev and req.base_rev != tree_rev(project):
        raise HTTPException(409, "The tree changed since you opened it (another tab, another device or an update). Nothing was saved: reload the "
                                 "tab and make your change again.")
    _store(req.project_id, project, req.conspiracy)
    project = _load(req.project_id)
    return {"ok": True, "conspiracy": _tree(project), "rev": tree_rev(project)}


class UndoRequest(BaseModel):
    project_id: str


@router.post("/undo")
def undo_tree(req: UndoRequest):
    project = _load(req.project_id)
    hist = (project.get("_field_history") or {}).get("conspiracy") or []
    if not hist:
        raise HTTPException(400, "Nothing to undo.")
    project["conspiracy"] = hist.pop()
    _save(req.project_id, project)
    return {"ok": True, "conspiracy": _tree(project), "rev": tree_rev(project)}


class BuildRequest(BaseModel):
    project_id: str
    note: Optional[str] = None
    provider: Optional[str] = None
    preview: bool = True    # return the proposal without saving; the author accepts or declines it


@router.post("/build")
def build_tree(req: BuildRequest):
    """Reverse-engineer the whole tree: the final scheme first, then the minor schemes that serve it, then their events, false flags and
    cover-ups, then the clues, breadcrumbs and mistakes the hero can find. Replaces the current tree (the old one stays on Undo)."""
    pid = req.project_id
    project = _load(pid)
    ctx = _story_context(project)
    research, sources = _research("a hidden ruling council stages false flag attacks, covers its tracks, silences a whistleblower, "
                                  "suppresses techniques, and the hero slowly uncovers the conspiracy through clues " + (req.note or ""), pid,
                                  project=project)
    prompt = (
        f"You are designing the hidden CONSPIRACY of the web novel \"{project.get('title', '')}\" for its author. Work BACKWARDS:\n"
        "1. Decide the FINAL major scheme (the root): the biggest thing the villains are really doing, which the last reveal exposes.\n"
        "2. Break it into minor SCHEMES that each serve it, roughly one per volume of the book (see THE BOOK'S SHAPE), ordered so each reveal leads to the next layer.\n"
        "3. Under each scheme put the AGENTS who run it (handlers, sleepers, cleaners, proxies; their surface is their cover identity), the EVENTS, FALSE FLAGS (attacks staged and blamed on someone else) and COVER-UPS that carry it out. Under every false flag put its PATSY: who is framed for it (a rebel, a rival sect, an innocent clerk), why they were chosen and what happens to them; a patsy's surface is the public accusation.\n"
        "4. Under each of those put 2-4 CLUES, BREADCRUMBS (small things that point the right way) and MISTAKES (where the villains slipped), "
        "concrete and physical, that the hero can find, notice and question long before he understands them.\n"
        "Spread the pieces across the whole book: early arcs get surface events and small clues, each scheme is revealed at its volume's climax, and the final scheme in the last volume. Pin each node to an arc, "
        "and pin clues and on-page events to a chapter where you can. Every event and false flag needs a 'surface' (what people believe). "
        "Fit the premise, rules, lore and secrets below exactly; never contradict them; reuse their names.\n\n"
        + ctx
        + (f"THE AUTHOR ASKS FOR: {req.note}\n\n" if (req.note or "").strip() else "")
        + (research + "\n\n" if research else "")
        + "Reply with ONE JSON object, no markdown fences: the root node, with every other node nested under it in \"children\". Each node: "
        + _NODE_SCHEMA)
    data = _ask(prompt, pid, req.provider)
    if isinstance(data, dict) and "root" in data and isinstance(data["root"], dict):
        data = data["root"]
    if not isinstance(data, dict) or not data.get("title"):
        raise HTTPException(502, "The AI's reply wasn't a usable conspiracy tree, so nothing was saved. Try again.")
    data["type"] = "final_scheme"
    nodes = []
    _flatten(data, None, nodes, sources)
    old = _tree(project)
    if req.preview:
        proposed = _clean_tree({"nodes": nodes})["nodes"]
        _keep_pending(pid, project, proposed, replace=True, note=req.note)
        return {"ok": True, "proposed": proposed, "replace": True, "sources": sources, "rev": tree_rev(_load(pid))}
    tree = _store(pid, project, {"reveal_arc": old["reveal_arc"], "nodes": nodes})
    return {"ok": True, "conspiracy": tree, "added": len(nodes), "sources": sources}


class ExpandRequest(BaseModel):
    project_id: str
    node_id: str
    note: Optional[str] = None
    provider: Optional[str] = None
    preview: bool = True


@router.post("/expand")
def expand_node(req: ExpandRequest):
    """Grow children under one node: schemes get events, false flags and cover-ups; those get clues, breadcrumbs and mistakes."""
    pid = req.project_id
    project = _load(pid)
    tree = _tree(project)
    node = next((n for n in tree["nodes"] if n["id"] == req.node_id), None)
    if not node:
        raise HTTPException(404, "That node no longer exists.")
    chain, cur = [], node
    by_id = {n["id"]: n for n in tree["nodes"]}
    while cur:
        chain.append(cur)
        cur = by_id.get(cur.get("parent"))
    path = " > ".join(f"[{n['type']}] {n['title']}" for n in reversed(chain))
    siblings = [c for c in tree["nodes"] if c.get("parent") == node["id"]]
    want = ("the patsy framed for it (who is blamed, why they were chosen, what happens to them), plus clues the hero can find" if node["type"] == "false_flag"
            else "clues that the patsy was framed: an alibi, a planted object, a too-neat confession, a witness who changes their story" if node["type"] == "patsy"
            else "clues, breadcrumbs and mistakes the hero can find" if node["type"] in SURFACE_TYPES
            else "events, false flags and cover-ups that carry it out, each with a clue or two" if node["type"] in ("final_scheme", "scheme")
            else "smaller clues, breadcrumbs and mistakes that lead to it")
    research, sources = _research(f"{node['title']}. {node['text']} {req.note or ''}", pid, raw_excerpts=3, project=project)
    prompt = (
        f"You are growing the hidden CONSPIRACY tree of \"{project.get('title', '')}\". Add 3-6 child nodes under this node: {want}.\n\n"
        f"THE NODE: {path}\nITS TRUTH: {node['text']}\n" + (f"WHAT PEOPLE BELIEVE: {node['surface']}\n" if node.get("surface") else "")
        + (f"PINNED TO: arc {node.get('arc')}, chapter {node.get('chapter')}\n" if node.get("arc") or node.get("chapter") else "")
        + ("CHILDREN IT ALREADY HAS (do not repeat them):\n" + "\n".join(f"- [{c['type']}] {c['title']}" for c in siblings) + "\n" if siblings else "")
        + "\nTHE WHOLE TREE SO FAR:\n" + _outline(tree["nodes"], 5000) + "\n\n" + _story_context(project)
        + (f"THE AUTHOR ASKS FOR: {req.note}\n\n" if (req.note or "").strip() else "")
        + (research + "\n\n" if research else "")
        + "Clues must be concrete and physical, findable before they are understood. Pin each child to an arc and, where you can, a chapter. "
        "Reply with ONE JSON object, no markdown fences: {\"children\": [" + _NODE_SCHEMA + "]}")
    data = _ask(prompt, pid, req.provider)
    kids = _list_from(data, ("children", "nodes", "add", "items"))
    if not kids:
        raise HTTPException(502, "The AI's reply wasn't usable, so nothing was added. Try again.")
    added = []
    for k in kids[:8]:
        if isinstance(k, dict):
            _flatten(k, node["id"], added, [])
    for a in added:
        if a["parent"] == node["id"]:
            a["sources"] = sources[:4]
    if req.preview:
        allp = _keep_pending(pid, project, added, replace=False, note=req.note)
        return {"ok": True, "proposed": allp, "replace": False, "rev": tree_rev(_load(pid))}
    tree["nodes"] += added
    tree = _store(pid, project, tree)
    return {"ok": True, "conspiracy": tree, "added": len(added)}


class GrowRequest(BaseModel):
    project_id: str
    note: Optional[str] = None          # new material from the author to weave in (optional)
    provider: Optional[str] = None
    preview: bool = True


@router.post("/grow")
def grow_tree(req: GrowRequest):
    """Grow the WHOLE tree without replacing anything: new schemes, false flags with their patsies, cover-ups, and clues, breadcrumbs
    and mistakes, each hung under an existing node. The author's new material (note), if given, is woven in first."""
    pid = req.project_id
    project = _load(pid)
    tree = _tree(project)
    if not tree["nodes"]:
        raise HTTPException(400, "The tree is empty. Reverse-engineer it first, or add a final scheme.")
    pend = (tree.get("pending") or {}) if not (tree.get("pending") or {}).get("replace") else {}
    pend_nodes = pend.get("nodes") or []
    ids = {n["id"] for n in tree["nodes"]} | {n["id"] for n in pend_nodes}
    outline = "\n".join(f"{n['id']} | parent {n.get('parent') or '-'} | {n['type']} | arc {n.get('arc')} ch {n.get('chapter')} | {n['title']}: {n['text'][:200]}"
                        for n in tree["nodes"] + pend_nodes)[:11000]
    research, sources = _research("conspiracy false flag patsy cover-up clue mistake " + (req.note or "")
                                  + " " + " ".join(n["title"] for n in tree["nodes"][:8]), pid, raw_excerpts=3, project=project)
    weak = [n for n in tree["nodes"] if n["type"] in ("scheme", "event", "false_flag", "patsy", "cover_up")
            and not any(c.get("parent") == n["id"] for c in tree["nodes"])]
    prompt = (
        f"You are GROWING the hidden CONSPIRACY tree of \"{project.get('title', '')}\". Keep everything that exists; only ADD.\n"
        + (f"THE AUTHOR'S NEW MATERIAL - weave this in first, wherever it fits best:\n{req.note}\n\n" if (req.note or "").strip() else "")
        + "Add 6-12 new nodes, each hung under an EXISTING node by its id. Favour: false flags that still lack a patsy, branches with no clues, "
        "schemes with no mistake, arcs with few clues, and fresh minor schemes or false flags that serve the final scheme. Do not repeat a node "
        "that already exists in other words.\n\n"
        + ("BRANCHES THAT HAVE NOTHING UNDER THEM YET: " + "; ".join(f"{n['id']} ({n['type']}: {n['title']})" for n in weak[:20]) + "\n\n" if weak else "")
        + "THE TREE (id | parent | type | pin | title: truth):\n" + outline + "\n\n" + _story_context(project)
        + (research + "\n\n" if research else "")
        + "Reply with ONE JSON object, no markdown fences: {\"add\": [{\"parent_id\": \"an existing id\", \"node\": " + _NODE_SCHEMA + "}]}")
    data = _ask(prompt, pid, req.provider)
    adds = _list_from(data, ("add", "additions", "nodes", "new_nodes", "items", "children"))
    if not adds:
        _dump_raw(pid)
        raise HTTPException(502, "The AI's reply wasn't usable, so nothing was added. Try again.")
    # a node may come flat ({parent_id, type, title...}) instead of {parent_id, node: {...}}
    adds = [a if isinstance(a.get("node"), dict) else {"parent_id": a.get("parent_id") or a.get("parent"), "node": a} for a in adds if isinstance(a, dict)]
    added = []
    for a in adds[:16]:
        if not isinstance(a, dict) or not isinstance(a.get("node"), dict):
            continue
        parent = str(a.get("parent_id") or "")
        if parent not in ids:
            continue                                    # only hang new content on nodes that exist
        start = len(added)
        _flatten(a["node"], parent, added, [])
        if len(added) > start:
            added[start]["sources"] = sources[:4]
    if not added:
        raise HTTPException(502, "The AI didn't hang anything on existing nodes, so nothing was added. Try again.")
    if req.preview:
        allp = _keep_pending(pid, project, added, replace=False, note=req.note)
        return {"ok": True, "proposed": allp, "replace": False, "rev": tree_rev(_load(pid))}
    tree["nodes"] += added
    tree = _store(pid, project, tree)
    return {"ok": True, "conspiracy": tree, "added": len(added), "added_ids": [n["id"] for n in added]}
