"""
build_mechanics_deltas.py — the Chapter Mechanics delta: HOW each chapter is built, not what happens in it.

The v3 deltas record a chapter's content (summary, facts, reveals, humor, voice). Nothing recorded its construction:
the order of its beats, how its scenes join, how it opens and ends, who talks during a fight and what kind of line
each one is, and how a set piece (a duel, an auction, a face-slap) runs across several chapters. This builds that,
one file per already-extracted chapter: novels/<novel>/deltas_mechanics/chN.json. It is general-purpose data — the
chapter skeleton is its first reader, not its only one.

Per chapter, three steps:
  1. MEASURED (Python, free): words, paragraphs, spoken share, fight passages and the words before / in / after them,
     scene-break markers and time jumps, who speaks each quoted line where the text names them, and the chapter each
     named character was first mentioned in across the novel's raws.
  2. TARGETED CONTEXT (Python + nomic, free): the chapter's own v3 delta (summary, scenes, antagonist instances,
     cast), the previous and next chapters' summaries, the start of the next chapter's raw text (does a fight carry
     on?), the dialogue lines the index holds for this chapter with their speakers, and the novel's antagonist
     templates and narrative patterns nearest this chapter (nomic, filtered to this novel).
  3. ONE AI CALL with the paragraph-numbered chapter text and that context: beat roles, scenes and joins, opening and
     ending, fights exchange by exchange with every spoken line's speaker and role (verbatim quotes, checked), the
     chapter's place in a set-piece run, and the opponents it introduces.
Then, per novel (free): consecutive chapters are stitched into runs (novels/<novel>/set_pieces/runs.json), and the
chapters, fights and runs are embedded into knowledge_index.db as the opt-in "mechanics" category.

Only chapters that already have a v3 delta and a raw text are built. a reference novel goes first, then every
other novel in round-robin. Resumable: a chapter whose mechanics file exists at this SCHEMA_VERSION is skipped. The
engine is whichever is selected in the app (like every other job), re-read on each call.

    python build_mechanics_deltas.py --dry-run --novel my_novel --chapters 14   # context only, no AI
    python build_mechanics_deltas.py --novel my_novel --chapters 13-14
    python build_mechanics_deltas.py                       # everything not built yet (DMWG first)
    python build_mechanics_deltas.py --runs-only           # re-stitch runs + re-index from existing files, no AI
"""
import argparse
import json
import math
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import llm_client as L                     # noqa: E402
import upgrade_deltas as U                 # noqa: E402  (engine choice, limit waits, live status, verbatim checks)
from knowledge_index import embed_text, init_db, store_chunk, _unpack  # noqa: E402

import mechanics_core as _mc               # noqa: E402  (measuring, tag validation, exact fields: shared with extract_v3)
globals().update({k: getattr(_mc, k) for k in _mc.__all__ if k not in globals()})

L.NO_BAD_JSON_RETRY = True                 # a reply that isn't clean JSON is salvaged, never re-asked

NOVELS_DIR = HERE / "novels"
RAW_DIR = HERE / "raw"
DB = HERE / "knowledge_index.db"
JOB = "mechanics_delta"
SCHEMA_VERSION = 3   # 3: fixed facet tags (mechanics_tags.json), beat meaning/purpose/motive + quotes, cast section, humor context
FIRST_NOVEL = ""            # a novel id to build before the others (none by default)
CH_FILE = re.compile(r"^ch(\d+)\.json$")
OUT_KEYS = ["chapter_type", "opening", "ending", "scenes", "beats", "fights", "run", "opponents", "cast", "devices"]

# ── step 2: targeted context ───────────────────────────────────────────────────────────────────────────────────
class NovelIndex:
    """One novel's rows of knowledge_index.db, for chapter-scoped lookups and nomic search filtered to the novel."""

    def __init__(self, conn, novel: str):
        self.rows = conn.execute("SELECT category, chapter, text, meta, embedding FROM chunks WHERE novel_id=? "
                                 "AND category IN ('dialogue','antagonist_template','pattern')", (novel,)).fetchall()
        self._vecs = None

    def dialogue_for(self, ch: int) -> list:
        out = []
        for cat, c, text, meta, _e in self.rows:
            if cat == "dialogue" and c == ch:
                try:
                    who = (json.loads(meta or "{}") or {}).get("character")
                except Exception:
                    who = None
                out.append({"speaker": who, "line": text[:220]})
        return out[:40]

    def nearest(self, query: str, cats=("antagonist_template", "pattern"), k: int = 4) -> list:
        if not query.strip():
            return []
        try:
            q = embed_text(query[:2000])
        except Exception:
            return []
        qn = math.sqrt(sum(x * x for x in q)) or 1.0
        scored = []
        for cat, c, text, meta, emb in self.rows:
            if cat not in cats or not emb:
                continue
            v = _unpack(emb)
            vn = math.sqrt(sum(x * x for x in v)) or 1.0
            scored.append((sum(a * b for a, b in zip(q, v)) / (qn * vn), cat, c, text))
        scored.sort(key=lambda s: s[0], reverse=True)    # by score only: some rows hold the chapter as text, some as NULL
        return [{"kind": cat, "chapter": c, "text": t[:400]} for _s, cat, c, t in scored[:k]]


def _delta(novel: str, ch: int):
    try:
        d = json.loads((NOVELS_DIR / novel / "deltas_v3" / f"ch{ch}.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def _raw(novel: str, ch: int):
    p = RAW_DIR / novel / f"ch{ch}.txt"
    return p.read_text(encoding="utf-8", errors="ignore") if p.exists() else None


def context_block(novel: str, ch: int, d: dict, names: NovelNames, idx: NovelIndex, paras: list, measured: dict) -> str:
    prev, nxt = _delta(novel, ch - 1), _delta(novel, ch + 1)
    nxt_raw = _raw(novel, ch + 1)
    prev_mech = _mc.load_mechanics(novel, ch - 1)      # merged copy first, then the old sidecar
    present = names.in_text("\n".join(paras))
    scenes = ((d.get("scene_structure_patterns") or {}).get("scenes") if isinstance(d.get("scene_structure_patterns"), dict) else None) or []
    ctx = {
        "this_chapter_summary": d.get("summary"),
        "chapter_function": d.get("chapter_function"),
        "extracted_scene_outline": [{"type": s.get("scene_type"), "notes": s.get("structure_notes")}
                                    for s in scenes if isinstance(s, dict)],
        "antagonist_instances": [{"template": a.get("template_id"), "who": a.get("instance_entity"),
                                  "chapters": a.get("instance_chapters")}
                                 for a in (d.get("antagonist_template_instances") or []) if isinstance(a, dict)],
        "introduced_here": [c.get("name") for c in (d.get("new_characters") or []) if isinstance(c, dict)],
        "humor_already_recorded_for_this_chapter": [
            {"type": h.get("type"), "who": h.get("participants") or h.get("characters_involved"),
             "setup": str(h.get("setup") or h.get("context") or "")[:200], "payoff": str(h.get("payoff") or h.get("excerpt") or "")[:200]}
            for h in (d.get("humor_instances") or []) if isinstance(h, dict)][:12],
        "named_characters_present": [{"name": n, "first_mentioned_in_chapter": names.first.get(n)} for n in present][:30],
        "previous_chapter_summary": (prev or {}).get("summary"),
        "previous_chapter_mechanics": ({"ending": prev_mech.get("ending"), "run": prev_mech.get("run")} if prev_mech else None),
        "next_chapter_summary": (nxt or {}).get("summary"),
        "next_chapter_opening": " ".join(paragraphs(nxt_raw)[:3])[:900] if nxt_raw else None,
        "dialogue_lines_indexed_for_this_chapter": idx.dialogue_for(ch),
        "this_novels_nearest_antagonist_templates_and_patterns": idx.nearest(str(d.get("summary") or "")),
        "measured": measured,
    }
    return json.dumps(ctx, ensure_ascii=False, indent=1)


# ── step 3: the AI call ────────────────────────────────────────────────────────────────────────────────────────
SYSTEM = """You analyse HOW a web-novel chapter is built — its construction, not its plot — for a library other tools
query later for ANY kind of moment: fights, but equally celebrations, banquets, face-slaps, rewards, training, shopping,
romance, comedy, daily life, or anything else a writer might want to model. Work only from the chapter text and the
context given. Output ONE JSON object with exactly these keys, no markdown fences:

"chapter_type": one of fight | run_up | set_up | fallout | reveal | comedy | cultivation | breakthrough | alchemy |
  auction_or_trade | contest | travel | romance | scheme | celebration | training | daily_life | recruitment | healing |
  mixed (pick the dominant one).
"opening": {"kind": continues_scene | continues_fight | fresh_scene | time_skip | flashback,
  "continues_previous_chapter": true/false, "note": "one line"}
"ending": {"kind": mid_fight | cliffhanger_line | new_threat | reveal | arrival | decision | quiet_close | aftermath,
  "carries_into_next_chapter": true/false, "note": "one line"}
"scenes": [{"paras": [first, last], "place": "short", "join_from_previous": continuous | later_same_place | cut_away |
  parallel | time_skip | first_scene, "purpose": "one line", "tags": ["free short words for what the scene is"]}]
"beats": [{"paras": [first, last], "role": ROLE, "driver": who drives it (a name, or crowd / ally / outsider /
  narrator), "spoken": true if carried mainly by dialogue,
  "meaning": "one line a PLANNER reads: what the beat is for and why the character does it, no quotes and no plot
  specifics (e.g. 'the rival mocks the hero in public to force a duel he expects will win back his family's face')",
  "tags": {"moment": [...], "purpose": [...], "motive": [...], "reader_effect": [...], "device": [...], "humor": [...]}
  — each facet that applies, terms chosen ONLY from the TAG SET,
  "specifics": ["anything notable no tag covers, written facet:word, e.g. moment:tea_ceremony, motive:filial_piety"],
  "quotes": ["up to 3 lines from this beat copied EXACTLY from the text, for a WRITER to hear how it sounds"]}]
  — in order, covering the chapter.
  ROLE is one of: set_up, arrival, provocation, insult_exchange, record_named, stakes_set, bet, offered_first_move,
  ally_worry, ally_offers_to_fight, crowd_odds, crowd_gossip, challenge_accepted, power_display, exchange, boast,
  put_down, disbelief, crowd_conclusion, new_move, interruption, rules_argument, escalation_backer, finishing_blow,
  humiliation, stakes_paid, reaction, fallout, reward, plant_next, reveal, comedy, cultivation, planning,
  internal_monologue, travel, exposition, face_slap, recognition_reversal, onlookers_regret, praise, celebration,
  banquet, gift_given, showing_off, banter, flirting, romance_beat, training, shopping, healing, recruitment,
  negotiation, flashback, rest, other. If none fits, use other and say what it is in meaning and specifics.
"fights": [{"opponents": ["names"], "paras": [first, last], "exchanges": [{"blow": "what is thrown and how it lands,
  one line", "talk": [{"speaker": "name or crowd/ally/outsider", "role": boast | put_down | disbelief | taunt | threat |
  crowd_conclusion | new_move_announced | interruption | rules_argument | plea | command | other,
  "quote": "the line copied EXACTLY from the text"}]}], "escalation": ["each step that raised the stakes"],
  "outcome": "one line", "ends_chapter_mid_fight": true/false}] — [] if no fight.
"run": {"set_piece_type": duel | face_slap | ambush | battle | auction | contest | breakthrough | alchemy | reveal |
  comedy_run | hunt | celebration | banquet | training | recruitment | romance | none, "role_in_run": set_up | run_up | fight | fallout | standalone | none,
  "main_opponent": "name or null", "continues_from_previous": true/false, "continues_into_next": true/false,
  "run_up_moves": ["provocation / record_named / stakes_set / bet / offered_first_move / ally_worry / crowd_odds ... in
  the order they happen this chapter"], "fallout": "one line or null", "next_hook": "the name, threat or question this
  chapter plants for the next set piece, or null"}
"opponents": [{"name": "...", "introduced_how": "one line", "record": "what the text says of his strength or past",
  "reason": "why he is against the hero", "first_mentioned_in_chapter": number from the context or null,
  "status_at_end": defeated | humiliated | crippled | killed | fled | standing | absent}] — [] if none.
"cast": [{"name": "...", "cast_role": a cast_role term from the TAG SET, "in_this_chapter": "one line: what they do
  here", "purpose": [purpose terms], "motive": [motive terms], "bond_with_hero": closer | cooler | owes_him | he_owes |
  betrayed | recruited | unchanged | none, "humor": [humor terms if they are played for laughs],
  "first_mentioned_in_chapter": number from the context or null, "quotes": ["up to 3 of their lines, EXACT"]}]
  — every named character who matters in the chapter except the hero (opponents too, cast_role opponent).
"devices": [{"device": "a recurring technique the chapter uses, named plainly (face_slap, crowd_chorus,
  underestimation, dramatic_irony, running_gag, internal_monologue_reveal, misunderstanding, showing_off_reward,
  cliffhanger_threat, toast_or_celebration, elders_reaction ...)", "paras": [first, last], "how": "one line"}].

Rules: paragraph numbers refer to the [P#] marks. Tags come only from the TAG SET; never invent a tag, use specifics
instead. For the humor facet, follow the humor already recorded for this chapter rather than re-deciding it. Every "quote" must be copied exactly from the chapter (same words);
never invent or paraphrase one — leave a talk line out rather than guess. Use names as the text gives them. Keep every
note to one short line. Prefer the measured numbers given over your own estimates."""


def repair_all(only_novel=None):
    """--repair: re-apply apply_exact to every mechanics file already built (no AI)."""
    for nd in sorted(NOVELS_DIR.iterdir()):
        if not nd.is_dir() or (only_novel and nd.name != only_novel):
            continue
        names = NovelNames(nd.name)
        n = 0
        folder = nd / "deltas_mechanics"
        for f in folder.glob("ch*.json") if folder.is_dir() else []:          # the old sidecar files
            if not CH_FILE.match(f.name):
                continue
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            f.write_text(json.dumps(apply_exact(rec, names), ensure_ascii=False, indent=1), encoding="utf-8")
            n += 1
        for ch, rec in _mc.all_mechanics(nd.name).items():                      # the merged copies inside the deltas
            if _mc.has_mechanics(nd.name, ch) and (nd / "deltas_v3" / f"ch{ch}.json").exists():
                if _mc.attach_mechanics(nd.name, ch, apply_exact({k: v for k, v in rec.items() if k != "scenes"}, names)):
                    n += 1
        print(f"{nd.name}: {n} record(s) repaired")


# ── the agents on screen: every worker thread is an "agent" (on Nvidia, pinned to its own key), and each in-flight chapter is
#    published in the job's live status as one row, so the Pipeline card shows all of them and turns each one's novel orange ──
_AGENTS: dict = {}
_AGENTS_LOCK = threading.Lock()


def _agent_row(novel: str, ch: int, step: str, preview: str = "") -> dict:
    slot = getattr(L._NEM_SLOT, "slot", None)
    row = {"novel": novel, "chapter": ch, "step": step, "preview": preview[:160], "started": time.strftime("%H:%M:%S"),
           "agent": (slot + 1) if slot is not None else None}
    if slot is not None and L._agent_engine() == "nemotron" and L.nemotron_pool_size():
        row["key"] = slot % L.nemotron_pool_size() + 1
    return row


def _agents_publish(model: str = None):
    """Write all in-flight chapters to the job's live status. Caller holds _AGENTS_LOCK."""
    active = sorted(_AGENTS.values(), key=lambda r: (r.get("agent") or 99, r["started"]))
    last = active[-1] if active else {"novel": "", "step": "idle", "preview": ""}
    L.write_live_status(JOB, novel=last["novel"], kind=last["step"], batch_size=len(active), preview=last["preview"],
                        model=model or U._engine_label("auto"), active=active)


def _agent_step(novel: str, ch: int, step: str, preview: str = ""):
    with _AGENTS_LOCK:
        row = _AGENTS.get((novel, ch))
        if row:
            row.update(step=step, preview=preview[:160])
        try:
            _agents_publish()
        except Exception:
            pass


def build_chapter(novel: str, ch: int, names: NovelNames, idx: NovelIndex, dry: bool = False) -> str:
    """One chapter, shown as an agent row on the Pipeline card while it runs."""
    if dry:
        return _build_chapter(novel, ch, names, idx, dry=True)
    with _AGENTS_LOCK:
        _AGENTS[(novel, ch)] = _agent_row(novel, ch, "reading the chapter")
        try:
            _agents_publish()
        except Exception:
            pass
    try:
        return _build_chapter(novel, ch, names, idx, dry=False)
    finally:
        with _AGENTS_LOCK:
            _AGENTS.pop((novel, ch), None)
            try:
                _agents_publish()
            except Exception:
                pass


def _build_chapter(novel: str, ch: int, names: NovelNames, idx: NovelIndex, dry: bool = False) -> str:
    d, raw = _delta(novel, ch), _raw(novel, ch)
    if d is None or raw is None:
        return "skip"
    paras = paragraphs(raw)
    if len(paras) < 5:
        return "skip"
    measured = measure(paras, names)
    ctx = context_block(novel, ch, d, names, idx, paras, measured)
    tagset = "\n".join(f"  {f}: {', '.join(v)}" for f, v in facets().items())
    user = (f"NOVEL: {novel}\nCHAPTER: {ch}\n\nTAG SET (the only tags allowed):\n{tagset}\n\n"
            f"CONTEXT (from the corpus; measured numbers are exact):\n{ctx}\n\n"
            f"CHAPTER TEXT (paragraph-numbered):\n{_numbered(paras)}")
    if dry:
        print(f"--- {novel} ch{ch}: prompt {len(SYSTEM) + len(user):,} chars (~{(len(SYSTEM) + len(user)) // 4:,} tokens)")
        print(ctx[:3000])
        return "dry"
    label = U._engine_label("auto")
    _agent_step(novel, ch, "asking the engine", f"{measured['words']} words, {len(measured['fight_passages'])} fight passage(s)")
    notes = []
    while True:
        try:
            reply = U._ask(SYSTEM, user, OUT_KEYS, "auto")
            break
        except Exception as e:
            if U._is_limit_error(e):
                _agent_step(novel, ch, "rate-limited: waiting 60 s, then retrying", str(e)[:100])
                print(f"  usage/rate limit hit on {label} — waiting 60s then retrying ch{ch}", flush=True)
                time.sleep(60)
                _agent_step(novel, ch, "asking the engine")
                continue
            print(f"  ch{ch}: call failed: {str(e)[:160]}", flush=True)
            return "failed"
    _agent_step(novel, ch, "checking quotes and saving")
    out = U._parse_reply(reply, f"{novel} ch{ch}", OUT_KEYS, "auto", notes)
    if not isinstance(out, dict) or not any(out.get(k) for k in OUT_KEYS):
        print(f"  ch{ch}: unusable reply", flush=True)
        return "failed"
    out = _clean(out, paras, U._norm(raw), notes)
    eng, mdl = U._provenance("auto")
    rec = {"schema_version": SCHEMA_VERSION, "novel": novel, "chapter_number": ch, "built_at": time.time(),
           "engine": eng, "model": mdl, "measured": measured, **{k: out.get(k) for k in OUT_KEYS}, "notes": notes}
    rec = apply_exact(rec, names)
    # V4: the mechanics live inside the chapter's delta. (No delta file = nothing to attach to: write the old sidecar.)
    if not _mc.attach_mechanics(novel, ch, rec):
        path = NOVELS_DIR / novel / "deltas_mechanics" / f"ch{ch}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return "built"


# ── per novel: runs + index ────────────────────────────────────────────────────────────────────────────────────
def _mechanics(novel: str) -> dict:
    """{chapter: mechanics} — the merged copy inside each delta, else the old sidecar file."""
    return _mc.all_mechanics(novel)


def stitch_runs(novel: str) -> list:
    """Consecutive chapters joined into one run when one carries into the next (run or ending flags) and they share a
    main opponent or set-piece type. Written to novels/<novel>/set_pieces/runs.json."""
    mech = _mechanics(novel)
    runs, cur = [], None
    for ch in sorted(mech):
        r = mech[ch].get("run") or {}
        typ = r.get("set_piece_type") or "none"
        opp = (r.get("main_opponent") or "").strip() or None
        linked = cur and ch == cur["chapters"][-1] + 1 and (
            r.get("continues_from_previous") or (mech[ch].get("opening") or {}).get("continues_previous_chapter")
            or cur["_carries"]) and (
            (opp and opp in cur["opponents"]) or typ == cur["set_piece_type"])
        if linked:
            cur["chapters"].append(ch)
            cur["roles"].append({"chapter": ch, "role": r.get("role_in_run")})
            if opp and opp not in cur["opponents"]:
                cur["opponents"].append(opp)
        else:
            if cur and cur["set_piece_type"] != "none":
                runs.append(cur)
            cur = {"set_piece_type": typ, "chapters": [ch], "opponents": [opp] if opp else [],
                   "roles": [{"chapter": ch, "role": r.get("role_in_run")}]}
        cur["_carries"] = bool(r.get("continues_into_next") or (mech[ch].get("ending") or {}).get("carries_into_next_chapter"))
        cur["next_hook"] = r.get("next_hook")
    if cur and cur["set_piece_type"] != "none":
        runs.append(cur)
    for x in runs:
        x.pop("_carries", None)
    path = NOVELS_DIR / novel / "set_pieces" / "runs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding="utf-8")
    return runs


def index_novel(conn, novel: str, title: str):
    """Chapters, fights and runs as the opt-in "mechanics" category (incremental: existing texts are skipped)."""
    mech = _mechanics(novel)
    have = {(c, t) for c, t in conn.execute("SELECT chapter, text FROM chunks WHERE novel_id=? AND category='mechanics'", (novel,))}
    items = []
    for ch, m in sorted(mech.items()):
        roles = " > ".join(b.get("role", "?") for b in (m.get("beats") or []) if isinstance(b, dict))
        ms = m.get("measured") or {}
        devs = ", ".join(str(x.get("device")) for x in (m.get("devices") or []) if isinstance(x, dict))
        items.append((ch, f"chapter {m.get('chapter_type')}: opens {(m.get('opening') or {}).get('kind')}, ends "
                          f"{(m.get('ending') or {}).get('kind')}; beats {roles}; devices {devs}"[:900],
                      {"kind": "chapter", "spoken_share": ms.get("spoken_share"), "run": m.get("run")}))
        for b in m.get("beats") or []:       # the meaning + tags are embedded (a planner's search); quotes ride in meta (a writer's)
            if isinstance(b, dict) and (b.get("meaning") or b.get("tags")):
                tg = b.get("tags") if isinstance(b.get("tags"), dict) else {}
                flat = "; ".join(f"{f} {', '.join(v)}" for f, v in tg.items())
                items.append((ch, f"beat {b.get('role')}: {b.get('meaning') or ''} [{flat}]"[:700],
                              {"kind": "beat", "paras": b.get("paras"), "driver": b.get("driver"), "role": b.get("role"),
                               "tags": tg, "quotes": (b.get("quotes") or [])[:3]}))
        for c in m.get("cast") or []:
            if isinstance(c, dict) and c.get("name"):
                items.append((ch, f"cast {c.get('cast_role') or '?'} {c.get('name')}: {c.get('in_this_chapter') or ''} "
                                  f"[purpose {', '.join(c.get('purpose') or [])}; motive {', '.join(c.get('motive') or [])}; "
                                  f"bond {c.get('bond_with_hero')}]"[:700],
                              {"kind": "cast", "name": c.get("name"), "cast_role": c.get("cast_role"),
                               "first_mentioned_in_chapter": c.get("first_mentioned_in_chapter"),
                               "quotes": (c.get("quotes") or [])[:3]}))
        # a device a beat already carries as a tag is searchable through that beat; only the rest get an entry of their own
        tagged = {str(v) for b in (m.get("beats") or []) if isinstance(b, dict) and isinstance(b.get("tags"), dict)
                  for v in (b["tags"].get("device") or [])}
        for x in m.get("devices") or []:
            if isinstance(x, dict) and x.get("device") and str(x["device"]).strip().lower().replace(" ", "_") not in tagged:
                items.append((ch, f"device {x.get('device')}: {x.get('how') or ''}"[:600], {"kind": "device", "paras": x.get("paras")}))
        for f in m.get("fights") or []:
            talk = [t.get("role") for ex in (f.get("exchanges") or []) if isinstance(ex, dict) for t in (ex.get("talk") or [])]
            items.append((ch, f"fight vs {', '.join(f.get('opponents') or [])}: {len(f.get('exchanges') or [])} exchanges; "
                              f"talk {' > '.join(talk)}; escalation {'; '.join(f.get('escalation') or [])}; {f.get('outcome')}"[:900],
                          {"kind": "fight", "paras": f.get("paras"), "ends_chapter_mid_fight": f.get("ends_chapter_mid_fight")}))
    try:
        runs = json.loads((NOVELS_DIR / novel / "set_pieces" / "runs.json").read_text(encoding="utf-8"))
    except Exception:
        runs = []
    for r in runs:
        roles = ", ".join(f"ch{x['chapter']} {x['role']}" for x in r["roles"])
        items.append((r["chapters"][0], f"run {r['set_piece_type']} vs {', '.join(r['opponents']) or '?'} over "
                                        f"{len(r['chapters'])} chapter(s): {roles}"[:900],
                      {"kind": "run", "chapters": r["chapters"], "next_hook": r.get("next_hook")}))
    # prune: entries this novel no longer produces (an indexing rule changed, a file was rebuilt) leave the index
    want = {(ch, text) for ch, text, _m in items}
    stale = [(novel, c, tx) for c, tx in have if (c, tx) not in want]
    if stale:
        conn.executemany("DELETE FROM chunks WHERE novel_id=? AND category='mechanics' AND chapter IS ? AND text=?", stale)
        conn.commit()
    pruned = len(stale)
    added = 0
    for ch, text, meta in items:
        if (ch, text) in have:
            continue
        try:
            store_chunk(conn, novel, title, "mechanics", text, ch, meta, embed_text(text))
            added += 1
        except Exception as e:
            print(f"  WARN index {novel} ch{ch}: {str(e)[:100]}")
        if added and added % 25 == 0:
            conn.commit()
    conn.commit()
    if pruned:
        print(f"  {novel}: {pruned} redundant mechanics entr{'y' if pruned == 1 else 'ies'} removed", flush=True)
    return added


# ── driver ─────────────────────────────────────────────────────────────────────────────────────────────────────
def targets(only_novel=None, chapters=None) -> list:
    out = []
    for nd in sorted(NOVELS_DIR.iterdir()):
        if not nd.is_dir() or (only_novel and nd.name != only_novel) or not (nd / "deltas_v3").is_dir():
            continue
        for f in nd.joinpath("deltas_v3").iterdir():
            m = CH_FILE.match(f.name)
            if not m:
                continue
            ch = int(m.group(1))
            if chapters and ch not in chapters:
                continue
            if (RAW_DIR / nd.name / f"ch{ch}.txt").exists():
                out.append((nd.name, ch))
    out.sort(key=lambda x: (x[0], x[1]))
    first = [t for t in out if t[0] == FIRST_NOVEL]
    rest = U._round_robin([t for t in out if t[0] != FIRST_NOVEL], key=lambda t: t[0])
    return first + rest


def is_built(novel: str, ch: int) -> bool:
    return _mc.has_mechanics(novel, ch)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--novel")
    ap.add_argument("--chapters", help="e.g. 13-14,18")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rebuild", action="store_true", help="rebuild chapters that already have a file")
    ap.add_argument("--runs-only", action="store_true")
    ap.add_argument("--repair", action="store_true", help="re-apply the exact fields (first mentions...) to built files, no AI")
    ap.add_argument("--workers", type=int, help="chapters built in parallel (default: mechanics_deltas_config.json, else 2)")
    a = ap.parse_args()
    chapters = set(U.parse_chapters(a.chapters)) if a.chapters else None
    conn = init_db()
    titles = {}
    for nd in NOVELS_DIR.iterdir():
        try:
            titles[nd.name] = json.loads((nd / "novel_metadata.json").read_text(encoding="utf-8")).get("title") or nd.name
        except Exception:
            titles[nd.name] = nd.name
    if a.repair:
        repair_all(a.novel)
        return
    todo = targets(a.novel, chapters)
    if a.runs_only:
        for novel in sorted({n for n, _ in todo}):
            runs = stitch_runs(novel)
            print(f"{novel}: {len(runs)} run(s), {index_novel(conn, novel, titles.get(novel) or novel)} chunk(s) indexed")
        return
    pending = [t for t in todo if a.rebuild or not is_built(*t)]
    if a.limit:
        pending = pending[:a.limit]
    workers = max(1, a.workers if a.workers else _config_workers())
    print(f"{len(pending)} chapter(s) to build ({len(todo) - len([t for t in todo if not is_built(*t)])} already built); "
          f"engine {U._engine_label('auto')}, {workers} worker(s)", flush=True)
    lock = threading.Lock()
    cache_names, cache_idx = {}, {}
    left = {}
    for n, _ in pending:
        left[n] = left.get(n, 0) + 1
    built = {"n": 0}
    started = {"n": 0}

    def novel_tools(novel):
        with lock:
            if novel not in cache_names:
                cache_names[novel] = NovelNames(novel)
                c = sqlite3.connect(DB)
                cache_idx[novel] = NovelIndex(c, novel)
                c.close()
            return cache_names[novel], cache_idx[novel]

    def work(item):
        novel, ch = item
        L.ensure_nemotron_slot()          # Nvidia: each worker thread keeps its own pooled key
        names, idx = novel_tools(novel)
        with lock:
            started["n"] += 1
            k = started["n"]
        t0 = time.time()
        res = build_chapter(novel, ch, names, idx, dry=a.dry_run)
        print(f"[{k}/{len(pending)}] {novel} ch{ch}: {res} ({time.time() - t0:.0f}s)", flush=True)
        with lock:
            left[novel] -= 1
            if res == "built":
                built["n"] += 1
            last = left[novel] == 0
        if last and not a.dry_run:      # a novel's last chapter: stitch its runs and index it
            c = init_db()
            runs = stitch_runs(novel)
            added = index_novel(c, novel, titles.get(novel) or novel)
            c.close()
            print(f"{novel}: {len(runs)} run(s) stitched, {added} mechanics chunk(s) indexed", flush=True)

    # a reference novel first: its chapters run (in parallel) before any other novel's start.
    first = [t for t in pending if t[0] == FIRST_NOVEL]
    rest = [t for t in pending if t[0] != FIRST_NOVEL]
    for batch in (first, rest):
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for f in as_completed([pool.submit(work, it) for it in batch]):
                try:
                    f.result()
                except Exception as e:
                    print(f"  worker error: {str(e)[:200]}", flush=True)
    U._live("", "finished", f"{built['n']} chapter(s) built", job=JOB)


def _config_workers() -> int:
    """Parallel chapters (mechanics_deltas_config.json "workers", default 2) — read at start."""
    try:
        return int(json.loads((HERE / "mechanics_deltas_config.json").read_text(encoding="utf-8")).get("workers") or 2)
    except Exception:
        return 2


if __name__ == "__main__":
    main()
