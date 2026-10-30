"""
delta_audit.py - Score every extracted chapter delta for "could this be upgraded?" and keep the
result in one registry file, delta_quality.json.  No LLM: pure counting against the raw text.

Why: a side-by-side of Haiku vs Sonnet 5 on the same chapter showed the cheaper model is accurate
but THIN (about half the reveals, fewer timeline/knowledge/dialogue entries). Thinness is
measurable from the delta itself, so it can be found across the whole corpus without reading a
single chapter by eye, and re-checked automatically whenever a chapter is (re)extracted.

What the registry holds (per chapter):
  score / tier      richness 0-100 = average percentile of seven density metrics (per 10k chars of
                    chapter text) against the whole corpus; tier A >= 60, B 35-59, C < 35
  flags             concrete, checkable problems (see FLAGS below)
  metrics           the raw counts and densities behind the score
  extracted_at      the delta file's modification time
  engine / model    who produced it — recorded for chapters extracted AFTER this file existed; older
                    chapters say "unknown" (the deltas themselves never recorded it)
  upgraded_by       set when upgrade_deltas.py has re-done the chapter
Registry top level also has `reference` (the quantile tables the scores are measured against),
`upgrade_candidates` (lowest-scoring, not yet upgraded, first) and per-novel / per-run summaries.

FLAGS (all objective):
  thin              score in tier C
  no_reveals        zero reveals in a chapter of normal length
  few_dialogue      fewer than 5 dialogue samples
  short_summary     summary under 350 characters
  prose_not_verbatim / dialogue_not_verbatim
                    excerpts/quotes that are not actually in the chapter text (possible paraphrase
                    or fabrication)
  style_dna_zero    style refinements never filled in (all content_ratios zero)
  title_is_header   chapter_title is the page header ("... Chapter 65"), not a real title
  guessed_scheme_refs
                    a scheme names a setup/payoff chapter other than this one (the chapter text
                    almost never states those, so they are guesses)
  schema_incomplete required keys missing

Usage:
    python delta_audit.py                    # score everything, rewrite delta_quality.json, print a report
    python delta_audit.py --novel my_novel
    python delta_audit.py --chapter nine_star_hegemon_body_arts 65     # (re)mark one chapter only
Also called automatically after every save_delta() (see extract_v3.py) so new extractions are marked.
"""
import argparse
import bisect
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOVELS_DIR = HERE / "novels"
REGISTRY = HERE / "delta_quality.json"

_CH_RE = re.compile(r"^ch(\d+)\.json$")
METRICS = ("facts", "timeline", "reveals", "knowledge", "prose", "dialogue", "glossary")
REQUIRED_KEYS = {"summary", "facts", "timeline_events", "reveals", "prose_samples", "character_voice_samples",
                 "knowledge_state", "style_dna", "reader_psychology", "author_intent"}
TIER_A, TIER_B = 60, 35

# Set by a caller that is NOT the app's selected engine (e.g. upgrade_deltas.py) so the mark says who really did the work.
_PROVENANCE_OVERRIDE = {}


def set_provenance(engine: str, model: str, upgraded: bool = False):
    _PROVENANCE_OVERRIDE.clear()
    _PROVENANCE_OVERRIDE.update({"engine": engine, "model": model, "upgraded": upgraded})


# ── text / counting helpers ────────────────────────────────────────────────────
def _norm(s: str) -> str:
    """Letters and digits only, lower-cased. Raw text varies a lot between novels in spacing, curly vs straight
    quotes, dashes, missing spaces after full stops ("before.They") — none of which means an excerpt is
    paraphrased. Comparing only the letters/digits makes 'is this passage really in the chapter' robust to that."""
    s = s.replace("’", "'").replace("‘", "'")
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _verbatim(quotes, text_norm):
    ok = tot = 0
    for q in quotes:
        for seg in re.split(r"\.\.\.|\[[^\]]*\]|…", str(q)):
            seg = _norm(seg)
            if len(seg) >= 20:
                tot += 1
                ok += 1 if seg in text_norm else 0
    return ok, tot


def _n(v) -> int:
    if v in (None, "", "none"):
        return 0
    return len(v) if isinstance(v, (list, dict)) else 1


def _dialogue(d) -> list:
    out = []
    for v in d.get("character_voice_samples") or []:
        if isinstance(v, dict):
            for s in v.get("dialogue_samples") or []:
                if isinstance(s, dict) and s.get("line"):
                    out.append(s["line"])
    return out


def _chapter_text(novel: str, ch: int) -> str:
    """Prefer the extractor's own loader (same cleaning); fall back to the raw file."""
    try:
        sys.path.insert(0, str(HERE))
        import extract_v3
        cwd = os.getcwd()
        os.chdir(HERE)
        try:
            return extract_v3.load_chapter_text(novel, ch)
        finally:
            os.chdir(cwd)
    except Exception:
        p = HERE / "raw" / novel / f"ch{ch}.txt"
        return p.read_text(encoding="utf-8", errors="ignore") if p.exists() else ""


# Fields whose emptiness is ambiguous: either "the chapter has none" or "the extraction missed it".
# extract_v3 resolves that ambiguity per chapter with delta["confirmed_empty"] (the model answered "none"
# after looking), so an empty field is one of:
#   confirmed_none  - the model looked and said there is nothing (fine — not a problem, not penalised)
#   unconfirmed     - empty and nobody ever ruled on it (could be a genuine gap; needs a check)
CHECK_FIELDS = ("reveals", "knowledge_state", "facts", "timeline_events", "new_glossary_terms",
                "character_voice_samples", "prose_samples", "humor_instances", "scheme_instances",
                "new_characters", "new_locations", "new_factions", "antagonist_template_instances")
# The subset where a genuine gap matters for generation — these drive the "resolve" list.
IMPORTANT_FIELDS = ("reveals", "knowledge_state", "facts", "timeline_events", "prose_samples", "character_voice_samples")
# metric name -> the delta field it is computed from (so a confirmed-empty field can be left out of the score)
METRIC_FIELD = {"facts": "facts", "timeline": "timeline_events", "reveals": "reveals", "knowledge": "knowledge_state",
                "prose": "prose_samples", "dialogue": "character_voice_samples", "glossary": "new_glossary_terms"}


def empty_status(d: dict) -> dict:
    """{field: 'confirmed_none' | 'unconfirmed'} for every checked field that is empty in this delta."""
    confirmed = set(d.get("confirmed_empty") or [])
    return {k: ("confirmed_none" if k in confirmed else "unconfirmed")
            for k in CHECK_FIELDS if _n(d.get(k)) == 0}


def measure(novel: str, ch: int, d: dict, text: str) -> dict:
    kchars = max(len(text), 1) / 10000.0
    counts = {"facts": _n(d.get("facts")), "timeline": _n(d.get("timeline_events")), "reveals": _n(d.get("reveals")),
              "knowledge": _n(d.get("knowledge_state")), "prose": _n(d.get("prose_samples")),
              "dialogue": len(_dialogue(d)), "glossary": _n(d.get("new_glossary_terms"))}
    dens = {k: round(v / kchars, 3) for k, v in counts.items()}
    tn = _norm(text)
    po, pt = _verbatim([p.get("excerpt", "") for p in (d.get("prose_samples") or []) if isinstance(p, dict)], tn)
    do, dt = _verbatim(_dialogue(d), tn)
    return {"text_chars": len(text), "counts": counts, "density_per_10k": dens,
            "prose_verbatim": [po, pt], "dialogue_verbatim": [do, dt]}


# ── reference quantiles ────────────────────────────────────────────────────────
def build_reference(all_dens: dict) -> dict:
    """{metric: [21 quantile values, 0%..100% in 5% steps]} over the whole corpus."""
    ref = {}
    for m, vals in all_dens.items():
        vals = sorted(vals)
        if not vals:
            ref[m] = [0.0] * 21
            continue
        ref[m] = [round(vals[min(len(vals) - 1, int(i / 20 * (len(vals) - 1) + 0.5))], 3) for i in range(21)]
    return ref


def percentile(ref_m: list, x: float) -> float:
    """0-100: where x falls in the reference distribution."""
    lo = bisect.bisect_left(ref_m, x)
    hi = bisect.bisect_right(ref_m, x)
    return round(((lo + hi) / 2) / (len(ref_m)) * 100, 1)


def score(dens: dict, ref: dict, skip: set = frozenset()) -> float:
    """Average percentile over the density metrics. `skip` = metrics whose field the model CONFIRMED is genuinely
    empty for this chapter: a chapter with nothing to extract must not be scored as a poor extraction."""
    used = [m for m in METRICS if METRIC_FIELD[m] not in skip] or list(METRICS)
    return round(sum(percentile(ref[m], dens[m]) for m in used) / len(used), 1)


def tier(s: float) -> str:
    return "A" if s >= TIER_A else "B" if s >= TIER_B else "C"


# ── flags ──────────────────────────────────────────────────────────────────────
# ── Chapter Mechanics quality (V4 deltas carry d["mechanics"]) ──
# Three NARROW flags, each re-asks only its own part (see upgrade_deltas._upgrade_mechanics):
#   thin_beats      - fewer beats than the corpus norm for the chapter's length
#   thin_fight_talk - a fight whose passage has quoted lines, but none were recorded as talk between blows
#   thin_cast       - fewer than 2 cast although the chapter has 4+ named speakers
# Measured over all 2,079 mechanics records on 2026-10-21: median 6.4 beats per 1,000 words (p10 4.0, p25 4.9); 60% of the
# median = 3.8 flags the thinnest ~8%. A chapter whose mechanics were already upgraded is never flagged again (it may
# simply be a quiet chapter), which also stops an endless re-ask.
MECH_FLAGS = ("thin_beats", "thin_fight_talk", "thin_cast")
MECH_MIN_BEATS_PER_KWORD = 3.8


def mechanics_flags(d: dict) -> list:
    mech = d.get("mechanics")
    if not isinstance(mech, dict) or not mech or mech.get("upgraded"):
        return []
    meas = mech.get("measured") or {}
    words = meas.get("words") or 0
    out = []
    beats = mech.get("beats") or []
    if words >= 900 and len(beats) / words * 1000 < MECH_MIN_BEATS_PER_KWORD:
        out.append("thin_beats")
    fights = mech.get("fights") or []
    talk = sum(len(e.get("talk") or []) for f in fights if isinstance(f, dict) for e in (f.get("exchanges") or []) if isinstance(e, dict))
    fight_lines = sum((fp.get("spoken_lines") or 0) for fp in (meas.get("fight_passages") or []) if isinstance(fp, dict))
    if fights and talk == 0 and fight_lines >= 2:
        out.append("thin_fight_talk")
    speakers = [s for s in (meas.get("lines_by_speaker") or {}) if s and s != "?"]
    if len(speakers) >= 4 and len(mech.get("cast") or []) < 2:
        out.append("thin_cast")
    return out


# ── 'thin' decomposed: WHICH fields make a tier-C chapter thin ──
# Tier C is a low AVERAGE rank over the seven measured fields. The fix is rarely all seven: measured 2026-10-21 over the 338
# tier-C chapters, 317 have at least one field below the 15th percentile of the corpus (2.7 such fields on average). So a tier-C
# chapter now also carries one low_<metric> flag per weak field, and Delta Upgrade re-asks ONLY those fields, one call each.
# The bar steps 15 -> 25 -> 35 until it finds a weak field (a mean below 35 guarantees at least one field is under it).
LOW_FLAGS = tuple(f"low_{m}" for m in METRICS)
LOW_BARS = (15, 25, 35)


def low_metric_flags(m: dict, ref: dict, skip=frozenset()) -> list:
    pcts = {k: percentile(ref[k], m["density_per_10k"][k]) for k in METRICS if k in ref and METRIC_FIELD[k] not in skip}
    for bar in LOW_BARS:
        weak = [k for k, p in pcts.items() if p < bar]
        if weak:
            return [f"low_{k}" for k in weak]
    return []


def flags_for(ch: int, d: dict, m: dict, sc: float, ref: dict = None, skip=frozenset()) -> list:
    f = []
    c = m["counts"]
    es = empty_status(d)
    if tier(sc) == "C":
        f.append("thin")
        if ref:
            f.extend(low_metric_flags(m, ref, skip))
    # Empty is only a PROBLEM if nobody ruled on it. "confirmed none" is the model saying the chapter has nothing.
    if c["reveals"] == 0 and m["text_chars"] >= 5000:
        f.append("reveals_confirmed_none" if es.get("reveals") == "confirmed_none" else "reveals_unconfirmed")
    if c["knowledge"] == 0 and es.get("knowledge_state") == "unconfirmed":
        f.append("knowledge_unconfirmed")
    if (c["dialogue"] < 5 and es.get("character_voice_samples") != "confirmed_none"
            and "character_voice_samples" not in (d.get("confirmed_complete") or [])):
        f.append("few_dialogue")
    if len(str(d.get("summary") or "")) < 350:
        f.append("short_summary")
    po, pt = m["prose_verbatim"]
    if pt and po / pt < 0.9:
        f.append("prose_not_verbatim")
    do, dt = m["dialogue_verbatim"]
    if dt >= 4 and do / dt < 0.75:
        f.append("dialogue_not_verbatim")
    cr = (d.get("style_dna") or {}).get("content_ratios")
    if isinstance(cr, dict) and cr and all(v == 0.0 for v in cr.values()):
        f.append("style_dna_zero")
    title = str(d.get("chapter_title") or "")
    if re.search(r"chapter\s*\d+", title, re.I) and len(title) > 14:
        f.append("title_is_header")
    for s in d.get("scheme_instances") or []:
        if isinstance(s, dict):
            refs = [s.get("setup_chapter"), s.get("payoff_chapter"), s.get("execution_chapter")]
            if any(isinstance(r, int) and r != ch for r in refs):
                f.append("guessed_scheme_refs")
                break
    if not REQUIRED_KEYS.issubset(d.keys()):
        f.append("schema_incomplete")
    f.extend(mechanics_flags(d))
    return f


# ── engine provenance ──────────────────────────────────────────────────────────
def current_engine_model() -> dict:
    """Best-effort: which engine/model the app has selected right now (recorded for NEW extractions)."""
    if _PROVENANCE_OVERRIDE:
        return dict(_PROVENANCE_OVERRIDE)
    try:
        sys.path.insert(0, str(HERE))
        import llm_client as L
        eng = L._agent_engine()
        cfg = {}
        try:
            cfg = json.loads((Path.home() / ".noveltea-engine" / "config.json").read_text(encoding="utf-8-sig"))
        except Exception:
            pass
        model = None
        if eng == "claude":
            model = (L._settings_claude_model() or L.DEFAULT_MODEL)
        else:
            model = (cfg.get("models") or {}).get(eng)
        return {"engine": eng, "model": model, "upgraded": False}
    except Exception:
        return {"engine": "unknown", "model": None, "upgraded": False}


# ── registry ───────────────────────────────────────────────────────────────────
def load_registry() -> dict:
    try:
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_registry(reg: dict):
    tmp = REGISTRY.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, REGISTRY)


class _locked:
    """Cross-process lock around a registry read-modify-write. Several processes can touch delta_quality.json at once
    (an extraction/upgrade/check job marking chapters as it saves them, plus a scan from the Corpus Pipeline button);
    each does load -> change -> save of the WHOLE file, so without a lock the last writer silently wipes out the
    other's update (seen: a checked chapter whose 'confirmed none' never reached the registry)."""
    LOCK = REGISTRY.with_suffix(".lock")

    def __enter__(self):
        deadline = time.time() + 60
        while True:
            try:
                fd = os.open(str(self.LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return self
            except FileExistsError:
                try:   # a lock left behind by a crashed process must not block forever
                    if time.time() - self.LOCK.stat().st_mtime > 120:
                        self.LOCK.unlink()
                        continue
                except OSError:
                    pass
                if time.time() > deadline:
                    return self   # give up waiting rather than hang an extraction; a lost mark is recoverable by a scan
                time.sleep(0.05)

    def __exit__(self, *exc):
        try:
            self.LOCK.unlink()
        except OSError:
            pass


def _differs_from_backup(path: Path, backup: Path) -> bool:
    """The upgrade job's backup exists AND the delta was actually changed since. A backup alone
    isn't proof: a chapter whose upgrade calls all failed was left byte-for-byte as it was."""
    try:
        return backup.exists() and (backup.stat().st_size != path.stat().st_size
                                    or backup.read_bytes() != path.read_bytes())
    except OSError:
        return False


def _build_entry(ch: int, d: dict, path: Path, ref: dict, m: dict) -> dict:
    """One chapter's registry entry (everything except who made it)."""
    es = empty_status(d)
    skip = {k for k, v in es.items() if v == "confirmed_none"}   # model ruled: nothing to extract — don't score it as a gap
    # Topped up until the model found nothing more (upgrade_deltas.py): the chapter simply has
    # no more of it, so a low count there is not an extraction gap either.
    skip |= set(d.get("confirmed_complete") or [])
    # Fields Delta Upgrade has already re-asked on their own (upgrade_deltas stamps them into retried_fields): settled - each
    # field gets ONE retry, so a chapter that keeps gaining a little can never be sent round again and again.
    skip |= set(d.get("retried_fields") or [])
    sc = score(m["density_per_10k"], ref, skip)
    return {"score": sc, "tier": tier(sc), "flags": flags_for(ch, d, m, sc, ref, skip), "metrics": m["counts"],
            "density_per_10k": m["density_per_10k"], "text_chars": m["text_chars"],
            "prose_verbatim": m["prose_verbatim"], "dialogue_verbatim": m["dialogue_verbatim"],
            "empty_fields": es,                                     # {field: confirmed_none | unconfirmed}
            "extracted_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime)),
            # ONLY the upgrade job's backup counts as "upgraded". This used to glob every *original.json, so the
            # Empty-field Check's own backups (chNN.pre-resolve-original.json) made ~670 chapters look upgraded — which
            # also hid them from the upgrade candidates even when thin.
            "has_original_backup": _differs_from_backup(path, path.parent / f"ch{ch}.haiku45-original.json"),
            "checked_for_empties": (path.parent / f"ch{ch}.pre-resolve-original.json").exists()}


def _entry(novel: str, ch: int, d: dict, path: Path, ref: dict, prov: dict = None, prev: dict = None) -> dict:
    text = _chapter_text(novel, ch)
    m = measure(novel, ch, d, text)
    e = _build_entry(ch, d, path, ref, m)
    if prov:
        e.update({"engine": prov.get("engine"), "model": prov.get("model"), "upgraded": bool(prov.get("upgraded"))})
    elif prev:
        e.update({k: prev[k] for k in ("engine", "model", "upgraded") if k in prev})
    else:
        e.update({"engine": "unknown", "model": None, "upgraded": e["has_original_backup"]})
    return e


def mark_chapter(novel: str, ch: int, d: dict = None):
    """Called after a delta is saved: (re)score this one chapter against the stored reference and record who made it.
    Must never break an extraction — every failure is swallowed."""
    try:
        path = NOVELS_DIR / novel / "deltas_v3" / f"ch{ch}.json"
        d = d or json.loads(path.read_text(encoding="utf-8"))
        text = _chapter_text(novel, ch)            # slow part (disk + measuring) done BEFORE taking the lock
        m = measure(novel, ch, d, text)
        prov = current_engine_model()
        with _locked():
            reg = load_registry()                  # read fresh INSIDE the lock so concurrent updates aren't lost
            ref = reg.get("reference")
            if not ref or not path.exists():
                return   # no baseline yet — the next full scan will pick this chapter up
            e = _build_entry(ch, d, path, ref, m)
            e.update({"engine": prov.get("engine"), "model": prov.get("model"), "upgraded": bool(prov.get("upgraded"))})
            reg.setdefault("novels", {}).setdefault(novel, {}).setdefault("chapters", {})[str(ch)] = e
            reg["last_marked"] = {"novel": novel, "chapter": ch, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
            save_registry(reg)
    except Exception:
        pass


def full_scan(only_novel: str = None) -> dict:
    rows = []   # (novel, ch, delta, path)
    for nd in sorted(NOVELS_DIR.iterdir()) if NOVELS_DIR.exists() else []:
        if not nd.is_dir() or (only_novel and nd.name != only_novel):
            continue
        dd = nd / "deltas_v3"
        if not dd.exists():
            continue
        for f in dd.glob("ch*.json"):
            m = _CH_RE.match(f.name)
            if not m:
                continue
            try:
                mt = f.stat().st_mtime
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(d, dict):
                rows.append((nd.name, int(m.group(1)), d, f, mt))

    # Pass 1: measure everything, collect densities for the reference (always corpus-wide, even for one-novel runs)
    measured = []
    for novel, ch, d, f, mt in rows:
        text = _chapter_text(novel, ch)
        mm = measure(novel, ch, d, text)
        mm["_mtime"] = mt                      # the delta version this measurement belongs to
        measured.append((novel, ch, d, f, mm))

    with _locked():
        # The scan takes a while, and jobs keep saving chapters meanwhile. Anything changed since we read it is
        # re-measured NOW (inside the lock) — otherwise this scan would overwrite that chapter's fresh mark with a
        # result computed from its OLD content.
        for i, (novel, ch, d, f, mm) in enumerate(measured):
            try:
                cur = f.stat().st_mtime
            except OSError:
                continue
            if cur != mm.get("_mtime"):
                try:
                    d2 = json.loads(f.read_text(encoding="utf-8"))
                    m2 = measure(novel, ch, d2, _chapter_text(novel, ch))
                    m2["_mtime"] = cur
                    measured[i] = (novel, ch, d2, f, m2)
                except Exception:
                    pass
        return _finish_scan(only_novel, measured)


def _finish_scan(only_novel, measured) -> dict:
    # Read the registry only NOW (inside the lock, after the slow measuring pass): save_delta's hook may have marked
    # chapters with the engine that really extracted them while we were measuring, and those marks must survive.
    prev = load_registry()
    if only_novel and prev.get("reference"):
        ref = prev["reference"]
    else:
        ref = build_reference({k: [mm["density_per_10k"][k] for *_, mm in measured] for k in METRICS})

    reg = prev if only_novel and prev else {}
    reg["generated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    reg["reference"] = ref
    novels = reg.setdefault("novels", {})
    for novel, ch, d, f, m in measured:
        old = ((novels.get(novel) or {}).get("chapters") or {}).get(str(ch))
        e = _build_entry(ch, d, f, ref, m)
        if old and old.get("engine") not in (None, "unknown"):
            e.update({k: old.get(k) for k in ("engine", "model", "upgraded")})
        else:
            e.update({"engine": "unknown", "model": None, "upgraded": e["has_original_backup"]})
        novels.setdefault(novel, {}).setdefault("chapters", {})[str(ch)] = e

    # A chapter whose delta no longer exists (trimmed / deleted) must leave the registry too, or its old score keeps counting.
    present = {(novel, str(ch)) for novel, ch, *_ in measured}
    scanned = {novel for novel, *_ in measured} | ({only_novel} if only_novel else set())
    for novel in scanned:
        chs_ = (novels.get(novel) or {}).get("chapters") or {}
        for k in [k for k in chs_ if (novel, k) not in present]:
            del chs_[k]

    # Summaries
    cands, resolve = [], []
    for novel, nd in novels.items():
        chs = nd.get("chapters", {})
        tiers = Counter(e["tier"] for e in chs.values())
        fl = Counter(x for e in chs.values() for x in e["flags"])
        runs = defaultdict(list)
        for e in chs.values():
            runs[e["extracted_at"][:10]].append(e["score"])
        # Empty fields, split by whether anyone ruled on them (the point of confirmed_empty)
        empt = {k: {"confirmed_none": 0, "unconfirmed": 0} for k in IMPORTANT_FIELDS}
        for e in chs.values():
            for k, st_ in (e.get("empty_fields") or {}).items():
                if k in empt:
                    empt[k][st_] += 1
        nd["summary"] = {"chapters": len(chs), "tiers": dict(tiers), "flags": dict(fl), "empty_fields": empt,
                         "mean_score": round(sum(e["score"] for e in chs.values()) / max(len(chs), 1), 1),
                         "runs_by_day": {d: {"chapters": len(v), "mean_score": round(sum(v) / len(v), 1)} for d, v in sorted(runs.items())}}
    reg["upgrade_candidates"], reg["resolve_candidates"] = candidate_lists(novels)
    save_registry(reg)
    return reg


def candidate_lists(novels: dict):
    """(upgrade_candidates, resolve_candidates) from the per-chapter entries — the worklists the Delta Upgrade and
    Empty-field Check jobs run from. Built by a full scan, and rebuilt on demand by refresh_candidates()."""
    cands, resolve = [], []
    for novel, nd in novels.items():
        for c, e in (nd.get("chapters") or {}).items():
            # Quality candidates: worth a stronger model's second pass.
            mech_f = [x for x in e["flags"] if x in MECH_FLAGS]
            if not e.get("upgraded") and (e["tier"] == "C" or "reveals_unconfirmed" in e["flags"] or "prose_not_verbatim" in e["flags"]
                                          or "dialogue_not_verbatim" in e["flags"] or "guessed_scheme_refs" in e["flags"]):
                cands.append({"novel": novel, "chapter": int(c), "score": e["score"], "flags": e["flags"]})
            elif mech_f:       # V3 part already upgraded (or fine): only the thin mechanics part is on the worklist
                cands.append({"novel": novel, "chapter": int(c), "score": e["score"], "flags": mech_f})
            low_f = [x for x in e["flags"] if x in LOW_FLAGS]
            if e.get("upgraded") and e["tier"] == "C" and low_f:
                # SECOND CHANCE, field by field: upgraded once and still thin. Only the weak fields not yet settled (not
                # confirmed complete / empty / already retried - see _build_entry) come back, one isolated call each.
                prev = next((x for x in cands if x["novel"] == novel and x["chapter"] == int(c)), None)
                if prev:
                    prev["flags"] = prev["flags"] + low_f
                else:
                    cands.append({"novel": novel, "chapter": int(c), "score": e["score"], "flags": low_f})
            # Resolve candidates: an important field is empty and nobody ever ruled on it. A single cheap targeted
            # call settles it either way (fills it, or records "confirmed none").
            unresolved = [k for k, v in (e.get("empty_fields") or {}).items() if v == "unconfirmed" and k in IMPORTANT_FIELDS]
            if unresolved:
                resolve.append({"novel": novel, "chapter": int(c), "fields": unresolved})
    cands.sort(key=lambda x: (x["score"], x["novel"], x["chapter"]))
    return cands, sorted(resolve, key=lambda x: (x["novel"], x["chapter"]))


def refresh_candidates() -> dict:
    """Rebuild both worklists from the registry's per-chapter entries, no rescan. mark_chapter() updates one chapter's
    entry as a job saves it but leaves the worklists alone, so they drift out of step with the entries the Corpus
    Pipeline counts from: the card then shows chapters pending that the job's own list no longer holds ("Checking 0
    chapter(s)", closes at once, same percentage). Returns {"upgrade": [before, after], "resolve": [before, after]}."""
    with _locked():
        reg = load_registry()
        before = (len(reg.get("upgrade_candidates") or []), len(reg.get("resolve_candidates") or []))
        reg["upgrade_candidates"], reg["resolve_candidates"] = candidate_lists(reg.get("novels") or {})
        save_registry(reg)
    return {"upgrade": [before[0], len(reg["upgrade_candidates"])], "resolve": [before[1], len(reg["resolve_candidates"])]}


def report(reg: dict):
    novels = reg["novels"]
    total = sum(len(n["chapters"]) for n in novels.values())
    tiers = Counter(e["tier"] for n in novels.values() for e in n["chapters"].values())
    flags = Counter(x for n in novels.values() for e in n["chapters"].values() for x in e["flags"])
    print(f"\nAUDITED {total} chapters across {len(novels)} novels  |  tiers: A={tiers['A']}  B={tiers['B']}  C={tiers['C']}")
    print("flags across the corpus:", dict(flags.most_common()))
    print(f"\n{'novel':42}{'chapters':>9}{'mean':>7}{'A':>5}{'B':>5}{'C':>5}   flags (top)")
    for name, n in sorted(novels.items(), key=lambda kv: kv[1]["summary"]["mean_score"]):
        s = n["summary"]
        top = ", ".join(f"{k}:{v}" for k, v in sorted(s["flags"].items(), key=lambda kv: -kv[1])[:3])
        print(f"{name:42}{s['chapters']:>9}{s['mean_score']:>7}{s['tiers'].get('A', 0):>5}{s['tiers'].get('B', 0):>5}{s['tiers'].get('C', 0):>5}   {top}")
    print(f"\nupgrade candidates (not yet upgraded, flagged): {len(reg['upgrade_candidates'])}")
    # The "nothing there vs. missed it" question, per important field
    print(f"\nEMPTY FIELDS — confirmed none (the model looked; fine) vs UNCONFIRMED (nobody ruled; may be missed):")
    for k in IMPORTANT_FIELDS:
        c = sum(n["summary"]["empty_fields"][k]["confirmed_none"] for n in novels.values())
        u = sum(n["summary"]["empty_fields"][k]["unconfirmed"] for n in novels.values())
        print(f"  {k:26} confirmed none {c:>5}    unconfirmed {u:>5}")
    print(f"chapters with at least one unconfirmed important field: {len(reg.get('resolve_candidates', []))}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--novel")
    ap.add_argument("--chapter", nargs="+", metavar="NOVEL CH [CH ...]", help="mark one or more chapters of a novel")
    ap.add_argument("--engine", help="record this engine for the marked chapter(s) (e.g. claude)")
    ap.add_argument("--model", help="record this model (e.g. claude-sonnet-5-5)")
    ap.add_argument("--refresh-candidates", action="store_true", help="rebuild the upgrade / empty-check worklists from the registry (no rescan)")
    ap.add_argument("--upgraded", action="store_true", help="record that the chapter was upgraded by a stronger model")
    args = ap.parse_args()
    if args.chapter:
        if args.engine:
            set_provenance(args.engine, args.model, upgraded=args.upgraded)
        novel = args.chapter[0]
        for c in args.chapter[1:]:
            mark_chapter(novel, int(c))
        e = load_registry()["novels"][novel]["chapters"][args.chapter[-1]]
        print(json.dumps({k: e[k] for k in ("score", "tier", "flags", "engine", "model", "upgraded", "extracted_at")}))
        return
    if args.refresh_candidates:
        print(json.dumps(refresh_candidates()))
        return
    reg = full_scan(args.novel)
    report(reg)


if __name__ == "__main__":
    main()
