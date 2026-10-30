"""
mechanics_core.py — the pure-Python half of the Chapter Mechanics delta, shared by the extractor (extract_v3, V4) and the
Pipeline job (build_mechanics_deltas.py): paragraph split, fight-passage and spoken-share measurements, who-is-named-where,
tag validation against the locked tag set (mechanics_tags.json), verbatim-quote checks and the exact fields Python knows
better than the model (first-mention chapters). No LLM, no embedding, no dependency on the extractor — importable anywhere.
"""
import json
import re
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOVELS_DIR = HERE / "novels"
RAW_DIR = HERE / "raw"
CH_FILE = re.compile(r"^ch(\d+)\.json$")


def _norm(s: str) -> str:
    """Letters and digits only, lower-cased (same rule as upgrade_deltas._norm: curly quotes, spacing and dashes differ
    between novels and mean nothing about whether an excerpt is verbatim)."""
    s = str(s).replace("\u2019", "'").replace("\u2018", "'")
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def text_is_verbatim(quote, text_norm: str) -> bool:
    """True if every meaningful piece of `quote` (split on ellipses / [elisions]) really appears in the chapter."""
    segs = [_norm(x) for x in re.split(r"\.\.\.|\[[^\]]*\]|\u2026", str(quote))]
    segs = [x for x in segs if len(x) >= 6]
    return bool(segs) and all(x in text_norm for x in segs)


TAGS_FILE = HERE / "mechanics_tags.json"
ROLES = frozenset("""set_up arrival provocation insult_exchange record_named stakes_set bet offered_first_move ally_worry
ally_offers_to_fight crowd_odds crowd_gossip challenge_accepted power_display exchange boast put_down disbelief
crowd_conclusion new_move interruption rules_argument escalation_backer finishing_blow humiliation stakes_paid reaction
fallout reward plant_next reveal comedy cultivation planning internal_monologue travel exposition face_slap
recognition_reversal onlookers_regret praise celebration banquet gift_given showing_off banter flirting romance_beat
training shopping healing recruitment negotiation flashback rest other""".split())
CHAPTER_TYPES = ("fight", "run_up", "set_up", "fallout", "reveal", "comedy", "cultivation", "breakthrough", "alchemy", "auction_or_trade", "contest", "travel", "romance", "scheme", "celebration", "training", "daily_life", "recruitment", "healing", "mixed")


def facets() -> dict:
    """{facet: [terms]} — the fixed tag set in mechanics_tags.json (re-read per chapter, so edits apply mid-run)."""
    try:
        return json.loads(TAGS_FILE.read_text(encoding="utf-8")).get("facets") or {}
    except Exception:
        return {}


# ── step 1: measured ────────────────────────────────────────────────────────────────────────────────────────────
_QUOTE = re.compile(r"[\"“]([^\"“”\n]{2,600})[\"”]")
_SOUND = re.compile(r"\b(bang|boom|crack|clang|whoosh|swish|thud|crash|shoo+p|swoosh|pu+|peng|hong|kacha|ka-?cha|"
                    r"rumble|roar(?:ed|ing)?)\b[!.]*", re.I)
_VIOLENT = re.compile(r"\b(punch(?:ed|es)?|kick(?:ed)?|slash(?:ed)?|stab(?:bed)?|strike|struck|smash(?:ed)?|"
                      r"slam(?:med)?|blood|vomit(?:ed)?|shatter(?:ed)?|collid(?:e|ed)|attack(?:ed)?|palm strike|"
                      r"sword (?:light|qi)|fist|blow|flung|sent flying|crushed|exploded|qi surged)\b", re.I)
_BREAK = re.compile(r"^\s*(\*{3,}|…{2,}|\.{6,}|-{3,}|~{3,}|-\s*[^-]{2,60}\s*-|※+)\s*$")
_TIMEJUMP = re.compile(r"\b(the next (?:day|morning|night)|(?:a|one|two|three|four|five|several|a few|half an?) "
                       r"(?:hours?|days?|months?|years?|weeks?) (?:later|passed)|meanwhile|at the same time|"
                       r"that (?:same )?(?:night|evening|morning)|on the other side|elsewhere)\b", re.I)


def paragraphs(raw: str) -> list:
    """The chapter's paragraphs, title lines dropped (raws open with "Chapter N – Title", often twice)."""
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", raw or "") if p.strip()]
    while paras and re.match(r"^chapter\s*\d+", paras[0], re.I) and len(paras[0].split()) <= 20:
        paras.pop(0)
    return paras


def _hot(p: str) -> int:
    return len(_SOUND.findall(p)) * 2 + len(_VIOLENT.findall(p))


def fight_passages(paras: list) -> list:
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


def spoken_words(text: str) -> int:
    return sum(len(q.split()) for q in _QUOTE.findall(text or ""))


class NovelNames:
    """Every named character of one novel (entities + v3 new_characters, with aliases), a regex to find them, and the
    chapter each was first mentioned in across the novel's raws (scanned once, cached on disk by raw mtimes)."""

    def __init__(self, novel: str):
        self.novel = novel
        names = {}
        ndir = NOVELS_DIR / novel
        for f in (ndir / "entities").glob("*.json") if (ndir / "entities").is_dir() else []:
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(d, dict) and d.get("type") == "character" and d.get("canonical_name"):
                for a in [d["canonical_name"]] + [x for x in (d.get("aliases") or []) if isinstance(x, str)]:
                    if len(a) >= 3 and a[0].isupper():
                        names[a] = d["canonical_name"]
        for f in (ndir / "deltas_v3").iterdir() if (ndir / "deltas_v3").is_dir() else []:
            if not CH_FILE.match(f.name):
                continue
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            for c in (d.get("new_characters") or []) if isinstance(d, dict) else []:
                if isinstance(c, dict) and isinstance(c.get("name"), str) and len(c["name"]) >= 3:
                    names.setdefault(c["name"], c["name"])
        self.alias = names
        ordered = sorted(names, key=len, reverse=True)
        self.rx = re.compile(r"\b(" + "|".join(re.escape(n) for n in ordered) + r")\b") if ordered else None
        self.first = self._first_mentions()

    def _first_mentions(self) -> dict:
        cache = NOVELS_DIR / self.novel / "deltas_mechanics" / "_first_mentions.json"
        raws = sorted(((int(m.group(1)), f) for f in (RAW_DIR / self.novel).glob("ch*.txt")
                       if (m := re.match(r"^ch(\d+)\.txt$", f.name))), key=lambda x: x[0])
        sig = f"{len(raws)}:{len(self.alias)}:{max((f.stat().st_mtime for _, f in raws), default=0):.0f}"
        try:
            c = json.loads(cache.read_text(encoding="utf-8"))
            if c.get("sig") == sig:
                return c["first"]
        except Exception:
            pass
        first = {}
        if self.rx:
            for n, f in raws:
                try:
                    found = set(self.rx.findall(f.read_text(encoding="utf-8", errors="ignore")))
                except Exception:
                    continue
                for a in found:
                    first.setdefault(self.alias[a], n)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"sig": sig, "first": first}, ensure_ascii=False), encoding="utf-8")
        return first

    def in_text(self, text: str) -> list:
        return sorted({self.alias[a] for a in self.rx.findall(text or "")}) if self.rx else []

    def speaker(self, para: str):
        """The name the paragraph gives for its quoted line, if any (outside the quotes, nearest the quote)."""
        if not self.rx:
            return None
        outside = _QUOTE.sub(" § ", para)
        hits = [(m.start(), self.alias[m.group(1)]) for m in self.rx.finditer(outside)]
        if not hits:
            return None
        q = outside.find("§")
        return min(hits, key=lambda h: abs(h[0] - q))[1]


def measure(paras: list, names: NovelNames) -> dict:
    text = "\n".join(paras)
    words = len(text.split())
    fights = fight_passages(paras)
    fwords = [sum(len(paras[k].split()) for k in range(a, b + 1)) for a, b in fights]
    before = sum(len(p.split()) for p in paras[:fights[0][0]]) if fights else None
    after = sum(len(p.split()) for p in paras[fights[-1][1] + 1:]) if fights else None
    lines = []
    for i, p in enumerate(paras):
        for q in _QUOTE.findall(p):
            lines.append({"para": i + 1, "speaker_named": names.speaker(p), "words": len(q.split())})
    return {
        "words": words, "paragraphs": len(paras), "spoken_lines": len(lines),
        "spoken_share": round(spoken_words(text) / words, 3) if words else 0,
        "fight_passages": [{"paras": [a + 1, b + 1], "words": w,
                            "spoken_share": round(spoken_words("\n".join(paras[a:b + 1])) / w, 3) if w else 0,
                            "spoken_lines": sum(1 for x in lines if a + 1 <= x["para"] <= b + 1)}
                           for (a, b), w in zip(fights, fwords)],
        "words_before_first_fight": before, "words_in_fights": sum(fwords) if fights else 0,
        "words_after_last_fight": after,
        "opens_in_fight": bool(fights and fights[0][0] <= 1),
        "ends_in_fight": bool(fights and fights[-1][1] >= len(paras) - 2),
        "scene_breaks": [i + 1 for i, p in enumerate(paras) if _BREAK.match(p)],
        "time_jumps": [{"para": i + 1, "phrase": m.group(0)} for i, p in enumerate(paras) for m in [_TIMEJUMP.search(p)] if m],
        "lines_by_speaker": _count_by([x["speaker_named"] or "?" for x in lines]),
    }


def _count_by(xs):
    out = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))



def _numbered(paras: list) -> str:
    return "\n".join(f"[P{i + 1}] {p}" for i, p in enumerate(paras))


def _clean(out: dict, paras: list, text_norm: str, notes: list) -> dict:
    n = len(paras)

    def rng(v):
        try:
            a, b = int(v[0]), int(v[-1])
            a, b = max(1, min(a, n)), max(1, min(b, n))
            return [min(a, b), max(a, b)]
        except Exception:
            return None
    for key in ("scenes", "beats", "fights"):
        items = out.get(key) if isinstance(out.get(key), list) else []
        for it in items:
            if isinstance(it, dict) and "paras" in it:
                it["paras"] = rng(it.get("paras") or [])
        out[key] = [it for it in items if isinstance(it, dict)]
    dropped = 0
    for f in out["fights"]:
        for ex in f.get("exchanges") or []:
            if not isinstance(ex, dict):
                continue
            keep = []
            for t in ex.get("talk") or []:
                if isinstance(t, dict) and t.get("quote") and text_is_verbatim(t["quote"], text_norm):
                    keep.append(t)
                else:
                    dropped += 1
            ex["talk"] = keep
    if dropped:
        notes.append(f"{dropped} fight line(s) dropped: not verbatim")
    for key in ("opening", "ending", "run"):
        if not isinstance(out.get(key), dict):
            out[key] = {}
    if not isinstance(out.get("opponents"), list):
        out["opponents"] = []
    vocab = facets()
    bad_quotes = 0

    def keep_terms(facet, vals, spec):
        vals = vals if isinstance(vals, list) else ([vals] if vals else [])
        kept = []
        for v in vals:
            v = str(v).strip().lower().replace(" ", "_")
            if v and v in (vocab.get(facet) or []):
                kept.append(v)
            elif v:
                spec.append(f"{facet}:{v}")           # off-list: kept as a candidate term, never as a tag
        return kept
    for b in out["beats"]:
        spec = [str(s) for s in b.get("specifics") or [] if s] if isinstance(b.get("specifics"), list) else []
        role = str(b.get("role") or "other").strip().lower().replace(" ", "_")
        if role not in ROLES:                  # the model's own word is kept as a candidate, the role itself stays searchable
            spec.append(f"role:{role}")
            role = "other"
        b["role"] = role
        tags = b.get("tags") if isinstance(b.get("tags"), dict) else {}
        b["tags"] = {f: k for f, vals in tags.items() if (k := keep_terms(f, vals, spec))}
        b["specifics"] = spec
        qs = [q for q in (b.get("quotes") or []) if isinstance(q, str)]
        b["quotes"] = [q for q in qs if text_is_verbatim(q, text_norm)]
        bad_quotes += len(qs) - len(b["quotes"])
    cast = [c for c in (out.get("cast") or []) if isinstance(c, dict)] if isinstance(out.get("cast"), list) else []
    for c in cast:
        spec = [str(s) for s in c.get("specifics") or [] if s] if isinstance(c.get("specifics"), list) else []
        role = keep_terms("cast_role", c.get("cast_role"), spec)
        c["cast_role"] = role[0] if role else None
        for f in ("purpose", "motive", "humor"):
            c[f] = keep_terms(f, c.get(f), spec)
        c["specifics"] = spec
        qs = [q for q in (c.get("quotes") or []) if isinstance(q, str)]
        c["quotes"] = [q for q in qs if text_is_verbatim(q, text_norm)]
        bad_quotes += len(qs) - len(c["quotes"])
    out["cast"] = cast
    if bad_quotes:
        notes.append(f"{bad_quotes} beat/cast quote(s) dropped: not verbatim")
    out["devices"] = [x for x in (out.get("devices") or []) if isinstance(x, dict)] if isinstance(out.get("devices"), list) else []
    for x in out["devices"]:
        if "paras" in x:
            x["paras"] = rng(x.get("paras") or [])
    out["chapter_type"] = str(out.get("chapter_type") or "mixed").strip().lower()
    return out


def apply_exact(rec: dict, names: "NovelNames") -> dict:
    """Fields Python knows exactly, set over whatever the model wrote: each cast member's and opponent's first-mention
    chapter (from the raws scan), and specifics that merely repeat a tag the beat already has."""
    def first(name):
        n = str(name or "").strip()
        canon = names.alias.get(n) or next((names.alias[a] for a in names.alias if a and a in n), None)
        return names.first.get(canon) if canon else None
    if str(rec.get("chapter_type") or "") not in CHAPTER_TYPES:
        rec["chapter_type"] = "mixed"
    for key in ("cast", "opponents"):
        for c in rec.get(key) or []:
            if isinstance(c, dict) and c.get("name"):
                c["first_mentioned_in_chapter"] = first(c["name"])
    for b in rec.get("beats") or []:
        if isinstance(b, dict) and isinstance(b.get("specifics"), list):
            have = {f"{f}:{v}" for f, vs in (b.get("tags") or {}).items() for v in vs} if isinstance(b.get("tags"), dict) else set()
            b["specifics"] = [s for s in dict.fromkeys(b["specifics"]) if s not in have]
    return rec




# ══ V4: the mechanics live INSIDE the chapter delta (deltas_v3/chN.json["mechanics"], schema_version "4.0") ══════════════════
# The extractor asks for the mechanics fields (flat keys mx_*) in its four split calls; assemble_v4 turns them into one
# validated "mechanics" object. Older chapters were built by the Pipeline job into novels/<id>/deltas_mechanics/chN.json
# (the sidecar); readers use load_mechanics(), which prefers the merged copy and falls back to the sidecar.
MECH_SCHEMA = 3                        # the mechanics object's own schema (tags, beats, cast ...), unchanged by the merge
MX_KEYS = {"mx_chapter_type": "chapter_type", "mx_opening": "opening", "mx_ending": "ending", "mx_beats": "beats",
           "mx_fights": "fights", "mx_run": "run", "mx_opponents": "opponents", "mx_cast": "cast", "mx_devices": "devices"}
# which of the extractor's four calls carries each key (balanced by size: prose ~14 KB, voice ~14, plot ~17, world ~8)
MX_GROUP = {"prose": ["mx_devices", "mx_opponents", "mx_run"],
            "voice": ["mx_chapter_type", "mx_opening", "mx_ending", "mx_scene_joins"],
            "plot": ["mx_beats", "mx_fights"],
            "world": ["mx_cast"]}
NUMBERED_GROUPS = ("voice", "plot")    # calls that see paragraph-numbered text ([P#]); prose keeps plain text so quotes stay exact
CONTEXT_GROUPS = ("voice", "plot", "world")


def v4_spec() -> str:
    """The mechanics part of the extraction prompt (appended to the V3 schema when V4 is on)."""
    tagset = "\n".join(f"  {f}: {', '.join(v)}" for f, v in facets().items())
    return f'''

─── CHAPTER MECHANICS (V4): HOW the chapter is built, not what happens ───────────────────────────────────────────────
Besides the keys above, you may be asked for these mechanics keys. Work only from the chapter text and the CONTEXT block
(measured numbers there are exact). When the chapter text is paragraph-numbered, [P#] marks the paragraphs and "paras" is
[first, last] in those numbers; when it is not numbered, "paras" is null.

"mx_chapter_type": one of fight | run_up | set_up | fallout | reveal | comedy | cultivation | breakthrough | alchemy |
  auction_or_trade | contest | travel | romance | scheme | celebration | training | daily_life | recruitment | healing | mixed
"mx_opening": {{"kind": continues_scene | continues_fight | fresh_scene | time_skip | flashback,
  "continues_previous_chapter": true/false, "note": "one line"}}
"mx_ending": {{"kind": mid_fight | cliffhanger_line | new_threat | reveal | arrival | decision | quiet_close | aftermath,
  "carries_into_next_chapter": true/false, "note": "one line"}}
"mx_scene_joins": [{{"scene_number": the scene's number in scene_structure_patterns above, "place": "short",
  "join_from_previous": continuous | later_same_place | cut_away | parallel | time_skip | first_scene,
  "paras": [first, last] or null}}] — one entry for EVERY scene you listed in scene_structure_patterns.
"mx_beats": [{{"paras": [first, last], "role": ROLE, "driver": who drives it (a name, or crowd / ally / outsider / narrator),
  "spoken": true if carried mainly by dialogue,
  "meaning": "one line a PLANNER reads: what the beat is for and why the character does it, no quotes and no plot
  specifics (e.g. 'the rival mocks the hero in public to force a duel he expects will win back his family's face')",
  "tags": {{"moment": [...], "purpose": [...], "motive": [...], "reader_effect": [...], "device": [...], "humor": [...]}}
  — each facet that applies, terms chosen ONLY from the TAG SET below,
  "specifics": ["anything notable no tag covers, written facet:word, e.g. moment:tea_ceremony"],
  "quotes": ["up to 3 lines from this beat copied EXACTLY from the text, for a WRITER to hear how it sounds"]}}]
  — in order, covering the chapter. ROLE is one of: set_up, arrival, provocation, insult_exchange, record_named,
  stakes_set, bet, offered_first_move, ally_worry, ally_offers_to_fight, crowd_odds, crowd_gossip, challenge_accepted,
  power_display, exchange, boast, put_down, disbelief, crowd_conclusion, new_move, interruption, rules_argument,
  escalation_backer, finishing_blow, humiliation, stakes_paid, reaction, fallout, reward, plant_next, reveal, comedy,
  cultivation, planning, internal_monologue, travel, exposition, face_slap, recognition_reversal, onlookers_regret, praise,
  celebration, banquet, gift_given, showing_off, banter, flirting, romance_beat, training, shopping, healing, recruitment,
  negotiation, flashback, rest, other.
"mx_fights": [{{"opponents": ["names"], "paras": [first, last], "exchanges": [{{"blow": "what is thrown and how it lands, one
  line", "talk": [{{"speaker": "name or crowd/ally/outsider", "role": boast | put_down | disbelief | taunt | threat |
  crowd_conclusion | new_move_announced | interruption | rules_argument | plea | command | other,
  "quote": "the line copied EXACTLY from the text"}}]}}], "escalation": ["each step that raised the stakes"],
  "outcome": "one line", "ends_chapter_mid_fight": true/false}}] — [] if no fight.
"mx_run": {{"set_piece_type": duel | face_slap | ambush | battle | auction | contest | breakthrough | alchemy | reveal |
  comedy_run | hunt | celebration | banquet | training | recruitment | romance | none,
  "role_in_run": set_up | run_up | fight | fallout | standalone | none, "main_opponent": "name or null",
  "continues_from_previous": true/false, "continues_into_next": true/false, "run_up_moves": ["provocation / record_named /
  stakes_set / bet / offered_first_move / ally_worry / crowd_odds ... in the order they happen this chapter"],
  "fallout": "one line or null", "next_hook": "the name, threat or question this chapter plants for the next set piece, or null"}}
"mx_opponents": [{{"name": "...", "introduced_how": "one line", "record": "what the text says of his strength or past",
  "reason": "why he is against the hero", "status_at_end": defeated | humiliated | crippled | killed | fled | standing | absent}}]
  — [] if none.
"mx_cast": [{{"name": "...", "cast_role": a cast_role term from the TAG SET, "in_this_chapter": "one line: what they do here",
  "purpose": [purpose terms], "motive": [motive terms], "bond_with_hero": closer | cooler | owes_him | he_owes | betrayed |
  recruited | unchanged | none, "humor": [humor terms if they are played for laughs], "quotes": ["up to 3 of their lines, EXACT"]}}]
  — every named character who speaks, acts, or is named as a threat, rival or ally in the chapter, except the hero
  (opponents too, cast_role opponent). Use the full name as the text or the CONTEXT list gives it (e.g. "Uncle Hui").
"mx_devices": [{{"device": "a recurring technique the chapter uses, named plainly (face_slap, crowd_chorus, underestimation,
  dramatic_irony, running_gag, misunderstanding, showing_off_reward, cliffhanger_threat, elders_reaction ...)",
  "paras": [first, last] or null, "how": "one line"}}]

Tags come only from the TAG SET; never invent a tag, use specifics instead. For the humor facet follow the humor already
recorded for this chapter. Every "quote" must be copied exactly from the chapter; never invent or paraphrase one.

TAG SET (the only tags allowed):
{tagset}
'''


def numbered_text(text: str, limit: int = 14000) -> str:
    """The chapter, paragraph-numbered, cut at the same character budget the extractor uses for plain text."""
    out, used = [], 0
    for i, p in enumerate(paragraphs(text), 1):
        if used + len(p) > limit:
            out.append("[... truncated ...]")
            break
        out.append(f"[P{i}] {p}")
        used += len(p)
    return "\n".join(out)


def _delta_of(novel: str, ch: int):
    try:
        d = json.loads((NOVELS_DIR / novel / "deltas_v3" / f"ch{ch}.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except Exception:
        return None


_NAMES_CACHE: dict = {}


def names_for(novel: str) -> "NovelNames":
    """One NovelNames per novel per process (building it scans entities and, once, every raw chapter)."""
    if novel not in _NAMES_CACHE:
        _NAMES_CACHE[novel] = NovelNames(novel)
    return _NAMES_CACHE[novel]


def context_v4(novel: str, ch: int, text: str) -> str:
    """The Python-measured context the mechanics calls get: exact numbers, who is named here and when each was first
    mentioned, the previous chapter's summary and ending, and the opening of the next chapter if its raw text exists."""
    paras = paragraphs(text)
    names = names_for(novel)
    m = measure(paras, names)
    prev = _delta_of(novel, ch - 1) or {}
    pm = prev.get("mechanics") or {}
    nxt_raw = RAW_DIR / novel / f"ch{ch + 1}.txt"
    nxt = ""
    try:
        nxt = " ".join(paragraphs(nxt_raw.read_text(encoding="utf-8", errors="ignore"))[:3])[:900] if nxt_raw.exists() else ""
    except Exception:
        pass
    ctx = {
        "measured": {k: m[k] for k in ("words", "paragraphs", "spoken_lines", "spoken_share", "fight_passages",
                                       "words_before_first_fight", "words_in_fights", "words_after_last_fight",
                                       "opens_in_fight", "ends_in_fight", "scene_breaks", "time_jumps") if k in m},
        "named_characters_present": [{"name": n, "first_mentioned_in_chapter": names.first.get(n)} for n in names.in_text(text)][:30],
        "previous_chapter_summary": prev.get("summary"),
        "previous_chapter_ending": pm.get("ending"),
        "next_chapter_opening": nxt or None,
    }
    return json.dumps(ctx, ensure_ascii=False, indent=1)


_LIST_FIELDS = ("beats", "fights", "opponents", "cast", "devices")
_GROUP_NAME = re.compile(r"^(the\s+)?(crowd|onlookers?|bystanders?|spectators?|audience|people|villagers|townsfolk|guards|soldiers|"
                         r"mercenaries|disciples|servants|elders)\b[^A-Za-z]*(/|and|&)?\s*(crowd|onlookers?|bystanders?|spectators?)?\s*$", re.I)
_DICT_FIELDS = ("opening", "ending", "run")


def assemble_v4(llm: dict, text: str, novel: str, ch: int, engine: str = None, model: str = None):
    """The mx_* answers of the four calls -> one validated mechanics record (the sidecar's shape), or None when the model
    returned none of them. Tags are checked against the locked set, quotes against the chapter, first mentions are set by
    Python. Never raises: a failure here must not lose the rest of the extraction."""
    try:
        got = {field: llm.get(k) for k, field in MX_KEYS.items() if k in llm}
        if not any(v not in (None, "", [], {}) for v in got.values()):
            return None
        for f in _LIST_FIELDS:
            if not isinstance(got.get(f), list):
                got[f] = []
        for f in _DICT_FIELDS:
            if not isinstance(got.get(f), dict):
                got[f] = {}
        # a group is not a character: "Crowd / Onlookers" belongs in a beat's driver, not in the cast list
        got["cast"] = drop_group_names(got["cast"])
        got["chapter_type"] = str(got.get("chapter_type") or "mixed")
        got["scenes"] = []                       # scenes (and their joins) live in the delta's scene_structure_patterns
        paras = paragraphs(text)
        notes: list = []
        out = _clean(got, paras, _norm(text), notes)
        out.pop("scenes", None)
        names = names_for(novel)
        rec = {"schema_version": MECH_SCHEMA, "novel": novel, "chapter_number": ch, "built_at": time.time(),
               "engine": engine, "model": model, "source": "v4-extraction", "measured": measure(paras, names),
               **{f: out.get(f) for f in ("chapter_type", "opening", "ending", "beats", "fights", "run", "opponents", "cast", "devices")},
               "notes": notes}
        return apply_exact(rec, names)
    except Exception as e:
        print(f"  [mechanics] could not assemble (kept the rest of the extraction): {str(e)[:120]}")
        return None


def merge_scene_joins(llm: dict) -> int:
    """Fold the voice call's mx_scene_joins into scene_structure_patterns.scenes (by scene_number) and drop the key, so a
    chapter keeps ONE scene list that also says how each scene joins the one before. Returns how many scenes got a join."""
    joins = llm.pop("mx_scene_joins", None)
    ssp = llm.get("scene_structure_patterns")
    scenes = ssp.get("scenes") if isinstance(ssp, dict) else None
    if not isinstance(joins, list) or not isinstance(scenes, list):
        return 0
    by = {j.get("scene_number"): j for j in joins if isinstance(j, dict)}
    n = 0
    for s in scenes:
        j = by.get(s.get("scene_number")) if isinstance(s, dict) else None
        if j:
            for k in ("place", "join_from_previous", "paras"):
                if j.get(k) is not None:
                    s[k] = j[k]
            n += 1
    return n


# ── isolated field upgrade (Delta Upgrade): one flag -> one key -> one call, each accepted or rejected on its own ──────────
UPGRADE_KEYS = {"thin_beats": "mx_beats", "thin_fight_talk": "mx_fights", "thin_cast": "mx_cast"}
BEATS_PER_KWORD = 6.4          # the corpus median (2,079 mechanics records, 2026-10-21)


def talk_lines(fights) -> int:
    return sum(len(e.get("talk") or []) for f in (fights or []) if isinstance(f, dict)
               for e in (f.get("exchanges") or []) if isinstance(e, dict))


def drop_group_names(cast: list) -> list:
    """A group is not a character: 'Crowd / Onlookers' belongs in a beat's driver, not in the cast list."""
    return [c for c in cast if isinstance(c, dict) and not _GROUP_NAME.match(str(c.get("name") or "").strip())]


def upgrade_system(key: str, rec: dict, words: int) -> str:
    """The prompt for ONE field's upgrade: the mechanics spec, the upgrade rules, and what is measurably thin about it."""
    meas = rec.get("measured") or {}
    if key == "mx_beats":
        have = len(rec.get("beats") or [])
        aim = max(have + 3, round(words * BEATS_PER_KWORD / 1000))
        top = max(aim + 4, round(aim * 1.5))
        what = (f"The existing record has {have} beats for a {words}-word chapter; chapters in this corpus average about "
                f"{BEATS_PER_KWORD:g} beats per 1,000 words (about {aim} here). Return between {aim} and {top} beats - not more: one "
                f"beat per distinct move (an insult, an offer, a decision, a blow, the crowd's reaction), never one per sentence or "
                f"per thought, in order, covering the whole chapter. Every beat keeps its meaning, its tags from the TAG SET, its "
                f"specifics and up to 3 exact quotes.")
    elif key == "mx_fights":
        lines = sum((fp.get("spoken_lines") or 0) for fp in (meas.get("fight_passages") or []) if isinstance(fp, dict))
        what = (f"The fight passage(s) contain {lines} quoted lines, but the existing record has {talk_lines(rec.get('fights'))} talk "
                f"lines. For every exchange of blows give what is thrown and how it lands, and EVERY line spoken around it in "
                f"\"talk\" (speaker, role, the exact quote). Keep the escalation steps and the outcome.")
    else:
        names = [s for s in (meas.get("lines_by_speaker") or {}) if s and s != "?"]
        what = (f"Named speakers measured in the text: {', '.join(names[:12])}. The existing cast has {len(rec.get('cast') or [])}. "
                f"Include every named character who speaks, acts, or is named as a threat, rival or ally (except the hero), each "
                f"with cast_role, what they do here, purpose, motive, bond and up to 3 exact quotes. Use the names as the text gives them.")
    return (v4_spec() + f"""

─── UPGRADE MODE ───────────────────────────────────────────────────────────────────────────────────────────────────────
You are UPGRADING one part of this chapter's mechanics record. Its existing value is given after the chapter text. KEEP every
existing item that is correct and supported by the text, FIX wrong ones, ADD what is missing, and return the COMPLETE value of
{key} (not a diff). Return ONLY the key {key} as one valid JSON object (escape every double quote inside a string).
{what}""")


def apply_upgraded_part(rec: dict, key: str, value, text: str, notes: list):
    """(new record, "") when `value` is accepted for this key, else (rec, why-not). ISOLATED: only this field of the record is
    replaced, and only this field is re-validated (tags, roles, verbatim quotes, group-name cast); every other field stays
    byte-for-byte as it was. It must be STRICTLY better (more beats / cast / talk lines) - an equal answer changes nothing."""
    field = MX_KEYS[key]
    old = rec.get(field)
    if not isinstance(value, list) or not value:
        return rec, f"{key}: the model returned nothing usable - kept the existing value"
    probe = {f: ([] if f in _LIST_FIELDS or f == "scenes" else ({} if f in _DICT_FIELDS else "mixed"))
             for f in ("chapter_type", "opening", "ending", "beats", "fights", "run", "opponents", "cast", "devices", "scenes")}
    probe[field] = value
    cl = _clean(probe, paragraphs(text), _norm(text), notes)        # validates the one field we are replacing
    checked = cl.get(field) or []
    if field == "cast":
        checked = drop_group_names(checked)
    better = talk_lines(checked) > talk_lines(old) if field == "fights" else len(checked) > len(old or [])
    if not better:
        have = talk_lines(old) if field == "fights" else len(old or [])
        got = talk_lines(checked) if field == "fights" else len(checked)
        return rec, f"{key}: the new value was not better ({got} against {have}) - kept the existing one"
    new = dict(rec)
    new[field] = checked
    if field in ("beats", "cast") and rec.get("novel"):             # first-mention chapters are Python's to set, as always
        names = names_for(rec["novel"])
        part = apply_exact({"chapter_type": new.get("chapter_type"), "beats": new.get("beats") or [], "cast": new.get("cast") or [],
                            "opponents": []}, names)
        new[field] = part[field]
    return new, ""


def scenes_of(delta: dict) -> list:
    """The chapter's scenes in the mechanics shape, from the delta's scene_structure_patterns (V4 keeps one scene list)."""
    ssp = delta.get("scene_structure_patterns")
    out = []
    for s in (ssp.get("scenes") if isinstance(ssp, dict) else None) or []:
        if isinstance(s, dict):
            out.append({"paras": s.get("paras"), "place": s.get("place"), "join_from_previous": s.get("join_from_previous"),
                        "purpose": s.get("structure_notes") or s.get("purpose"), "scene_type": s.get("scene_type")})
    return out


def load_mechanics(novel: str, ch: int):
    """One chapter's mechanics: the merged copy inside the delta when it has one, else the sidecar the Pipeline job wrote.
    The result always has `scenes`, `novel` and `chapter_number`. None when the chapter has neither."""
    d = _delta_of(novel, ch)
    m = d.get("mechanics") if isinstance(d, dict) else None
    if isinstance(m, dict) and m:
        m = dict(m)
        m.setdefault("novel", novel)
        m.setdefault("chapter_number", ch)
        if not m.get("scenes"):
            m["scenes"] = scenes_of(d)
        return m
    try:
        return json.loads((NOVELS_DIR / novel / "deltas_mechanics" / f"ch{ch}.json").read_text(encoding="utf-8"))
    except Exception:
        return None


def has_mechanics(novel: str, ch: int, current_schema: bool = True) -> bool:
    """Cheap test (reads the first bytes only): the delta is marked schema 4.0, or a current-schema sidecar exists."""
    p = NOVELS_DIR / novel / "deltas_v3" / f"ch{ch}.json"
    try:
        with open(p, "rb") as f:
            if re.search(r'"schema_version"\s*:\s*"4\.0"', f.read(200).decode("utf-8", errors="ignore")):
                return True
    except Exception:
        pass
    q = NOVELS_DIR / novel / "deltas_mechanics" / f"ch{ch}.json"
    try:
        with open(q, "rb") as f:
            m = re.search(r'"schema_version"\s*:\s*(\d+)', f.read(160).decode("utf-8", errors="ignore"))
        return bool(m) and (not current_schema or int(m.group(1)) == MECH_SCHEMA)
    except Exception:
        return False


def all_mechanics(novel: str) -> dict:
    """{chapter: mechanics} for every chapter of a novel that has any (merged copy preferred, else sidecar)."""
    chapters = set()
    for sub in ("deltas_v3", "deltas_mechanics"):
        d = NOVELS_DIR / novel / sub
        if d.is_dir():
            for f in d.iterdir():
                m = CH_FILE.match(f.name)
                if m:
                    chapters.add(int(m.group(1)))
    out = {}
    for ch in sorted(chapters):
        m = load_mechanics(novel, ch)
        if m:
            out[ch] = m
    return out


def attach_mechanics(novel: str, ch: int, rec: dict) -> bool:
    """Write `rec` into the chapter's delta as delta["mechanics"] and mark it schema 4.0 (atomic replace). False when the
    chapter has no delta file."""
    p = NOVELS_DIR / novel / "deltas_v3" / f"ch{ch}.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(d, dict):
        return False
    d["mechanics"] = dict(rec)
    d["schema_version"] = "4.0"
    # keep schema_version the FIRST key, so has_mechanics() can tell from the first bytes
    d = {"schema_version": d.pop("schema_version"), **d}
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
    return True


__all__ = ["UPGRADE_KEYS", "BEATS_PER_KWORD", "talk_lines", "drop_group_names", "upgrade_system", "apply_upgraded_part", "ROLES", "HERE", "NOVELS_DIR", "RAW_DIR", "CH_FILE", "TAGS_FILE", "CHAPTER_TYPES", "facets", "paragraphs", "fight_passages",
           "spoken_words", "NovelNames", "measure", "_count_by", "_numbered", "_clean", "apply_exact", "_norm",
           "text_is_verbatim", "_hot", "_QUOTE", "MECH_SCHEMA", "MX_KEYS", "MX_GROUP", "NUMBERED_GROUPS", "CONTEXT_GROUPS",
           "v4_spec", "merge_scene_joins", "numbered_text", "names_for", "context_v4", "assemble_v4", "scenes_of", "load_mechanics",
           "has_mechanics", "all_mechanics", "attach_mechanics"]
