"""
upgrade_deltas.py - Upgrade existing chapter deltas with a stronger model.

For each chosen chapter, the SAME four-part extraction (prose / voice / plot / world) is
run again, but the prompt also contains the chapter's EXISTING extraction from the faster
model. The model is told to keep what is correct, fix what is wrong or unsupported, and add
what was missed — an upgrade, not a redo.

ENGINE: not locked to any model. By default ("auto") it uses whichever engine/model is
selected in the app (top-bar dropdown + Settings), exactly like the extractor and every other
pipeline job; the Corpus Pipeline card shows which one is doing the work. Pass --model
claude-sonnet-5-5 (or set "model" in upgrade_deltas_config.json) to force a specific Claude model
instead. Stronger models give better upgrades; the safety checks below apply to any of them.

Origin: a side-by-side of one Haiku-extracted chapter (Nine Star ch65) against a Sonnet 5
extraction of the same text found Haiku's accuracy fine (quotes ~99% verbatim, summaries
faithful) but thin — about half the reveals, fewer timeline/knowledge-state entries, a
mislabelled "scheme", and over-read humor. The rules below encode those findings.

SAFETY (the corpus data must never be lost):
  * The original delta is copied to chNN.haiku45-original.json BEFORE anything is written
    (never overwritten; the name doesn't match the pipelines' ^chNN.json$ guard, so it is
    ignored by every job) and the new delta is only written after validation.
  * Per field, Sonnet's answer is used only if it passes: valid type, quotes verbatim in
    the chapter text, and no suspicious shrinkage. Otherwise Haiku's value for that field
    is kept and the reason is logged.
  * The delta is assembled by extract_v3.extract_chapter_v3 itself (style pass, none-
    sentinels, title fallback, metadata), not hand-stitched.
  * Resumable: state is written after every chapter; done chapters are skipped.

Usage:
    python upgrade_deltas.py                      # targets from upgrade_deltas_config.json
    python upgrade_deltas.py --novel nine_star_hegemon_body_arts --chapters 41-60
    python upgrade_deltas.py --chapters 41 --force        # redo one chapter
"""
import argparse
import json
import os
import re
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.chdir(HERE)   # extract_v3 resolves novels/... relative to the working directory
sys.path.insert(0, str(HERE))

import extract_v3 as ex          # noqa: E402
import llm_client as L           # noqa: E402
import mechanics_core as mc      # noqa: E402  (the Chapter Mechanics: prompts + accept-if-not-worse for isolated field upgrades)
from delta_audit import MECH_FLAGS   # noqa: E402  (thin_beats / thin_fight_talk / thin_cast)

# A reply that isn't clean JSON comes back as-is and is salvaged here (_parse_reply) instead of
# the engine re-asking the same 3-15 minute question -- see llm_client.NO_BAD_JSON_RETRY.
L.NO_BAD_JSON_RETRY = True

NOVELS_DIR = HERE / "novels"
CONFIG = HERE / "upgrade_deltas_config.json"
STATE = HERE / "upgrade_deltas_state.json"
MODEL = "auto"   # "auto" = whichever engine/model is selected in the app (top-bar dropdown + Settings), like every other job.
                 # Anything else (e.g. "claude-sonnet-5-5") forces that Claude model through the CLI regardless of the selection.


def _is_auto(model) -> bool:
    return model in (None, "", "auto")


def _is_nemotron_model_id(model) -> bool:
    """Nemotron model ids are always 'nvidia/...' (see SettingsPage.jsx's NEMOTRON_MODELS) —
    distinguishes an explicit Nemotron override from an explicit Claude one, since they need
    two entirely different call paths below (direct API vs. the subscription CLI)."""
    return isinstance(model, str) and model.startswith("nvidia/")


def _claude_effort():
    """The Delta Upgrade card's "Claude: low effort" checkbox (upgrade_deltas_config.json's
    "claude_effort"). Read on every call, unlike "model", so ticking it changes the very next
    Claude call of a run already going. None = the Claude CLI's own default effort."""
    try:
        v = json.loads(CONFIG.read_text(encoding="utf-8")).get("claude_effort")
    except Exception:
        return None
    return v if v in L.CLI_EFFORTS else None


def _ask(system: str, user: str, keys: list, model) -> str:
    """One extraction-style call. Auto: the app's selected engine and model (call_llm, same as the
    extractor itself). Explicit Claude model: that model via the subscription CLI. Explicit Nemotron
    model (nvidia/...): straight to the Nemotron API directly -- _call_cli is Claude-only, it would
    hand a Nemotron model id to `claude -p --model` and fail every call."""
    if _is_auto(model):
        return L.call_llm(system=system, user=user, max_tokens=8000, temperature=0.3, required_keys=keys,
                          effort=_claude_effort())
    if _is_nemotron_model_id(model):
        return L._call_nemotron(system, user, model=model, required_keys=keys)
    return L._call_cli(system, user, model=model, required_keys=keys, effort=_claude_effort())


def _engine_label(model) -> str:
    """'engine:model' of what _ask will use — shown on the Corpus Pipeline card and in the log."""
    label = L.current_model_label() if _is_auto(model) else (
        f"nemotron:{model}" if _is_nemotron_model_id(model) else f"claude:{model}")
    effort = _claude_effort()
    return f"{label} · {effort} effort" if effort and label.startswith("claude") else label


_LIMIT_SIGNS = ("session limit", "usage limit", "hit your limit", "limit reached", "rate limit", "quota",
                "429", "credit balance", "overloaded", "too many requests")


def _is_limit_error(msg) -> bool:
    """True for 'you've hit a usage / rate limit' style failures — retrying the SAME chapter later is right,
    skipping ahead to the next chapter (which will fail the same way) is not."""
    m = str(msg or "").lower()
    return any(s in m for s in _LIMIT_SIGNS)


def _wait_out_limit(job: str, novel: str, what: str, label: str, seconds: int = 60):
    """Sleep, then let the caller retry. The engine is re-read on every call, so switching the app's engine while this
    waits lets the job carry on immediately with the new one."""
    print(f"  usage/rate limit hit on {label} — waiting {seconds}s then retrying {what} "
          f"(switch the engine in the app to continue now)", flush=True)
    _live(novel, "waiting", f"limit hit on {label} — retrying {what} every {seconds}s; switch the engine in the app to continue now",
          job=job, model=label)
    time.sleep(seconds)


def _round_robin(items: list, key) -> list:
    """Interleave items by group: first of each group, then second of each, ... so every novel makes progress
    together instead of one novel finishing before the next starts. Order within a group is preserved."""
    groups: dict = {}
    for it in items:
        groups.setdefault(key(it), []).append(it)
    queues = [list(reversed(v)) for v in groups.values()]   # pop() from the end = the group's first item
    out = []
    while queues:
        nxt = []
        for q in queues:
            out.append(q.pop())
            if q:
                nxt.append(q)
        queues = nxt
    return out


def _provenance(model) -> tuple:
    """(engine, model) to record in delta_quality.json for chapters this run writes."""
    if _is_auto(model):
        import delta_audit
        pv = delta_audit.current_engine_model()
        return pv.get("engine"), pv.get("model")
    if _is_nemotron_model_id(model):
        return "nemotron", model
    return "claude", model


UPGRADE_RULES = """

─── UPGRADE MODE ─────────────────────────────────────────────────────────────
A faster model has already extracted this chapter. Its values for the keys above are given
after the chapter text, under EXISTING EXTRACTION. Your job is to UPGRADE that extraction,
not to start over:

1. KEEP every existing item that is correct and supported by the chapter text.
2. FIX items that are wrong or unsupported. A rescue, a training session or an act of help
   is NOT a scheme (schemes are deliberate deceptions or plots against someone); a tonal
   shift is NOT humor unless the text is playing it for laughs; never guess a setup_chapter,
   execution_chapter, payoff_chapter or source that this chapter's text does not state or
   clearly imply — leave such fields empty/null instead; fix wrong names, types and scales.
3. ADD everything the existing extraction missed: every genuine reveal (power, identity,
   relationship, conspiracy, world, betrayal, secret-goal or ability reveal — including a
   character's hidden intent disclosed to another), knowledge asymmetries (who knows what,
   who is kept in the dark), facts, timeline events, glossary terms, dialogue samples and
   prose excerpts. Be thorough: a chapter where something is disclosed usually has 2-4
   reveals.
4. new_characters / new_locations / new_factions mean things INTRODUCED in this chapter
   (first appearance or first naming). Do not list an established character who merely
   appears.
5. VERBATIM RULE: every prose_samples excerpt and every dialogue line must be copied EXACTLY
   from the chapter text — same words, same punctuation. Keep existing excerpts that are
   good; replace any that are paraphrased. Never invent a quote.
6. Return the COMPLETE upgraded value for every requested key — not a diff or a patch. Do not
   drop correct content just to be shorter.
7. If the existing value is "none" and the chapter genuinely has nothing for that key, keep
   "none"."""

LIST_KEYS_SHRINK_GUARDED = ("facts", "timeline_events", "knowledge_state", "reveals", "new_glossary_terms",
                            "prose_samples", "character_voice_samples", "new_characters", "new_locations")
DICT_KEYS = ("reader_psychology", "author_intent", "scene_structure_patterns", "narrative_voice_analysis",
             "style_dna_refinements")
REFINEMENT_FIELDS = ("content_ratios", "pacing_markers", "stylistic_devices", "vocabulary_markers",
                     "character_catchphrases", "distinctive_style_markers")


# ── helpers ────────────────────────────────────────────────────────────────────
def _norm(s: str) -> str:
    """Letters and digits only, lower-cased. Raw text differs a lot between novels in spacing, curly vs straight quotes,
    dashes and missing spaces after full stops ("before.They"); none of that means an excerpt is paraphrased. (The old
    spacing-sensitive version rejected correct quotes from such novels — chapters checked with it ended 'left'.)"""
    s = s.replace("’", "'").replace("‘", "'")
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _verbatim_rate(quotes: list, text_norm: str):
    ok = tot = 0
    for q in quotes:
        for seg in re.split(r"\.\.\.|\[[^\]]*\]|…", str(q)):
            seg = _norm(seg)
            if len(seg) >= 20:
                tot += 1
                ok += 1 if seg in text_norm else 0
    return ok, tot


def _text_is_verbatim(quote, text_norm: str) -> bool:
    """True if every meaningful piece of `quote` (split on ellipses / [elisions]) really appears in the chapter."""
    segs = [_norm(s) for s in re.split(r"\.\.\.|\[[^\]]*\]|…", str(quote))]
    segs = [s for s in segs if len(s) >= 6]
    return bool(segs) and all(s in text_norm for s in segs)


def _keep_verbatim(key: str, items: list, text_norm: str) -> list:
    """For fields made of quoted text, keep only what is genuinely in the chapter. Other fields pass through."""
    if key == "prose_samples":
        return [p for p in items if isinstance(p, dict) and _text_is_verbatim(p.get("excerpt", ""), text_norm)]
    if key == "character_voice_samples":
        kept = []
        for v in items:
            if not isinstance(v, dict):
                continue
            lines = [s for s in (v.get("dialogue_samples") or [])
                     if isinstance(s, dict) and _text_is_verbatim(s.get("line", ""), text_norm)]
            if lines:
                kept.append({**v, "dialogue_samples": lines})
        return kept
    return items


def _dialogue_lines(voice_samples) -> list:
    out = []
    for v in voice_samples or []:
        if isinstance(v, dict):
            for s in v.get("dialogue_samples") or []:
                if isinstance(s, dict) and s.get("line"):
                    out.append(s["line"])
    return out


def _count(v) -> int:
    if v in (None, "", "none"):
        return 0
    return len(v) if isinstance(v, (list, dict)) else 1


def _summary_counts(d: dict) -> dict:
    return {"facts": _count(d.get("facts")), "timeline": _count(d.get("timeline_events")),
            "reveals": _count(d.get("reveals")), "knowledge": _count(d.get("knowledge_state")),
            "prose": _count(d.get("prose_samples")), "dialogue": len(_dialogue_lines(d.get("character_voice_samples"))),
            "glossary": _count(d.get("new_glossary_terms")), "characters": _count(d.get("new_characters")),
            "humor": _count(d.get("humor_instances")), "schemes": _count(d.get("scheme_instances"))}


def _existing_for(delta: dict, keys: list) -> dict:
    """The current (Haiku) values for one group's keys, in the shape the model is asked to return."""
    ce = set(delta.get("confirmed_empty") or [])
    out = {}
    for k in keys:
        if k == "style_dna_refinements":
            sd = delta.get("style_dna") or {}
            out[k] = {f: sd[f] for f in REFINEMENT_FIELDS if f in sd}
        else:
            v = delta.get(k)
            out[k] = "none" if (k in ce and v in (None, "", [], {})) else v
    return out


def _system_for(idx: int, total: int, label: str, keys: list, rules: str = None) -> str:
    key_list = "\n".join(f"  - {k}" for k in keys)
    return (ex.SYSTEM_PROMPT
            + f"\n\n─── THIS CALL ({idx}/{total}: {label}) ───\n"
              f"The full schema is above for context, but for THIS response you must return ONLY these keys:\n{key_list}\n"
              f"Return a single JSON object containing exactly (and only) those keys, following their definitions "
              f"above. Omit every other key."
            + (UPGRADE_RULES if rules is None else rules))


# Which specific delta key(s) each delta_audit flag actually implicates — lets a
# candidate that's only wrong in specific KEY(S) (e.g. "prose_not_verbatim" -> just
# prose_samples) get ONE call for exactly those keys, not a whole group's worth
# (measured on the real delta_quality.json registry: of 685 upgrade candidates,
# 145 need exactly one recognized flag and NONE of those 145 ever had a second
# flag land in the same group -- so a group-wide call was routinely re-deriving
# 5-7 sibling keys nobody flagged as wrong, for zero benefit). "thin" and
# "schema_incomplete" aren't attributable to specific keys (thin = an overall
# density score across every field; schema_incomplete = some unknown key is
# missing) so they still fall back to the full 4-way plan.
#
# title_is_header maps to 3 keys, not 1: title_function/chapter_function are the
# model's own commentary ON chapter_title, so fixing the title alone and leaving
# those two untouched would leave them describing the OLD (bad) title.
_FLAG_KEYS = {
    # (reveals_confirmed_none is deliberately absent: the model already checked and found none --
    # re-asking it on every chapter that happens to carry another flag was pure waste.)
    "reveals_unconfirmed": ["reveals"],
    "knowledge_unconfirmed": ["knowledge_state"],
    "short_summary": ["summary"],
    "title_is_header": ["chapter_title", "title_function", "chapter_function"],
    "few_dialogue": ["character_voice_samples"], "dialogue_not_verbatim": ["character_voice_samples"],
    "prose_not_verbatim": ["prose_samples"],
    "guessed_scheme_refs": ["scheme_instances"],
}
_LOW_FLAG_KEYS = {"low_facts": ["facts"], "low_timeline": ["timeline_events"], "low_reveals": ["reveals"],
                  "low_knowledge": ["knowledge_state"], "low_prose": ["prose_samples"],
                  "low_dialogue": ["character_voice_samples"], "low_glossary": ["new_glossary_terms"]}
_FLAG_KEYS.update(_LOW_FLAG_KEYS)      # a weak field is re-asked on its own (it is too SHORT, so additively: see _VOLUME_FLAGS)
_BROAD_FLAGS = {"thin"}   # "thin" is a genuine cross-field signal, left broad here on purpose -- a
# per-metric breakdown belongs in its own pipeline, not folded into this one (see _missing_required_keys
# below for why "schema_incomplete" does NOT need to be broad: unlike "thin" it names an exact key).
_ALL_KEYS = ["chapter_title"] + [k for _, keys in ex.SPLIT_GROUPS for k in keys]   # flat key list, for a stable sort order
# (chapter_title is read from the chapter's first line by Python now, so it is no longer in a split group, but a "title_is_header"
#  flag still maps to it: leaving it out made the sort below raise ValueError and crashed the whole job at start)


def _key_order(k: str) -> int:
    return _ALL_KEYS.index(k) if k in _ALL_KEYS else len(_ALL_KEYS)


def _missing_required_keys(old: dict) -> list:
    """"schema_incomplete" (a delta_audit.REQUIRED_KEYS member entirely absent from the
    delta) needs an exact key, not a broad redo -- with ONE exception: "style_dna" is a
    required key that is NEVER LLM-sourced (extract_v3.extract_chapter_v3 always rebuilds
    it locally from the raw text via analyze_style_dna(), on every single call regardless
    of which keys were requested -- see its `style_dna = merge_style_dna(...)` line). Checked
    against every schema_incomplete candidate in delta_quality.json on 2026-09-27: 20/20 had
    ONLY "style_dna" missing, i.e. already fixed for free by any upgrade_chapter pass,
    targeted or not -- that's why it was wrongly in _BROAD_FLAGS before this. Intersecting
    with _ALL_KEYS excludes style_dna (and any other non-LLM required key) automatically,
    so a genuinely-missing LLM key (not seen in the data, but not impossible) still gets
    targeted instead of silently staying absent."""
    import delta_audit as da
    return sorted((da.REQUIRED_KEYS & set(_ALL_KEYS)) - old.keys())


def _without_thin_when_localized(flags: list) -> list:
    """'thin' (tier C) means "redo everything" only when the audit could not say WHICH fields are weak. When it did (low_*
    flags), 'thin' is dropped so exactly those fields are re-asked - each on its own - instead of the full four-group plan."""
    flags = list(flags or [])
    if "thin" in flags and any(f in _LOW_FLAG_KEYS for f in flags):
        flags.remove("thin")
    return flags


def _keys_for_flags(flags: list):
    """Exactly which delta keys this chapter's flags implicate -> a single targeted
    call asking for just those, whether it's 1, 2, or 3+ of them. Returns None (run
    the full 4-way plan instead) when flags is empty (explicit --novel/--chapters
    runs, which carry no audit data), a broad flag is present, or nothing recognized
    maps -- always the safe fallback, never under-upgrade a chapter we can't localize."""
    flags = _without_thin_when_localized(flags)
    if not flags or (_BROAD_FLAGS & set(flags)):
        return None
    keys = set()
    for f in flags:
        keys.update(_FLAG_KEYS.get(f, ()))
    if not keys:
        return None
    return sorted(keys, key=_key_order)


# What each in-flight chapter is doing right now. Chapters run several at a time (see
# _upgrade_loop), and the live-status entry used to hold only whichever one wrote last -- the
# Corpus Pipeline card now gets all of them as "active".
_SLOTS: dict = {}            # (novel, ch) -> {novel, chapter, size, step, preview, model, started}
_SLOTS_LOCK = threading.Lock()
_TL = threading.local()      # .slot = (novel, ch) this worker thread is on


def _write_slots(novel: str, kind: str, preview: str, model):
    active = sorted(_SLOTS.values(), key=lambda s: s["started"])
    L.write_live_status("delta_upgrade", novel=novel, kind=kind, batch_size=len(active),
                        preview=preview[:200], model=model, active=active)


def _live(novel: str, kind: str, preview: str, job: str = "delta_upgrade", model: str = None):
    try:
        if job != "delta_upgrade":
            L.write_live_status(job, novel=novel, kind=kind, batch_size=1, preview=preview[:200], model=model)
            return
        with _SLOTS_LOCK:
            slot = _SLOTS.get(getattr(_TL, "slot", None))
            if slot is not None:
                slot.update(step=kind, preview=preview[:200], model=model)
            _write_slots(novel, kind, preview, model)
    except Exception:
        pass


def _slot_start(novel: str, ch: int, flags: list, model):
    mech = [f for f in flags if f in MECH_FLAGS]
    v3 = [f for f in flags if f not in MECH_FLAGS]
    keys = _keys_for_flags(v3)
    size = "full plan (thin)" if keys is None else f"{len(keys)} field{'s' if len(keys) != 1 else ''}"
    if mech and not v3:
        size = "mechanics: " + ", ".join(mc.MX_KEYS[mc.UPGRADE_KEYS[f]] for f in mech)
    elif mech:
        size += " + mechanics"
    _TL.slot = (novel, ch)
    nem = getattr(L._NEM_SLOT, "slot", None)
    with _SLOTS_LOCK:
        _SLOTS[(novel, ch)] = {"novel": novel, "chapter": ch, "size": size, "step": "starting",
                               "preview": "", "model": _engine_label(model), "started": time.strftime("%H:%M:%S"),
                               "agent": (nem + 1) if nem is not None else None}
        if nem is not None and L._agent_engine() == "nemotron" and L.nemotron_pool_size():
            _SLOTS[(novel, ch)]["key"] = nem % L.nemotron_pool_size() + 1
        try:
            _write_slots(novel, f"ch{ch} starting", "", _engine_label(model))
        except Exception:
            pass


def _slot_end(novel: str, ch: int):
    _TL.slot = None
    with _SLOTS_LOCK:
        _SLOTS.pop((novel, ch), None)
        try:
            last = max(_SLOTS.values(), key=lambda s: s["started"], default=None)
            if last:
                _write_slots(last["novel"], last["step"], last["preview"], last["model"])
            else:
                _write_slots(novel, f"ch{ch} finished", "", None)
        except Exception:
            pass


def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, STATE)


def parse_chapters(spec: str) -> list:
    out = []
    for part in str(spec).split(","):
        part = part.strip()
        m = re.match(r"^(\d+)\s*-\s*(\d+)$", part)
        if m:
            out += list(range(int(m.group(1)), int(m.group(2)) + 1))
        elif part.isdigit():
            out.append(int(part))
    return sorted(set(out))


def _apply_key_guard(k: str, part: dict, prev, text_norm: str, notes: list):
    """One key's raw LLM answer -> the value to actually save, applying every upgrade
    guard (validity, shrink, verbatim) exactly the same way whether this key came out
    of a full-group call or a single targeted call. Falls back to `prev` (and leaves
    a note) on any rejection, same behaviour as before this was pulled out into its
    own function."""
    new = part.get(k)
    if k not in part or (new is None and k != "power_curve_notes"):   # null is a valid power_curve_notes answer
        notes.append(f"{k}: missing in the answer — kept original")
        return prev
    is_none = isinstance(new, str) and new.strip().lower() == "none"
    if k in DICT_KEYS and not isinstance(new, dict):
        notes.append(f"{k}: wrong type — kept original")
        return prev
    if k not in DICT_KEYS and k not in ("chapter_title", "title_function", "chapter_function", "summary",
                                        "arc_label_suggestion", "arc_notes", "arc_boundary_signal",
                                        "power_curve_notes") and not isinstance(new, list) and not is_none:
        notes.append(f"{k}: wrong type — kept original")
        return prev
    if k in LIST_KEYS_SHRINK_GUARDED and isinstance(new, list) and isinstance(prev, list) \
            and len(prev) >= 3 and len(new) < 0.7 * len(prev):
        notes.append(f"{k}: upgrade shrank {len(prev)} -> {len(new)} — kept original")
        return prev
    if k == "prose_samples" and isinstance(new, list):
        ok, tot = _verbatim_rate([p.get("excerpt", "") for p in new if isinstance(p, dict)], text_norm)
        if tot and ok / tot < 0.9:
            notes.append(f"prose_samples: only {ok}/{tot} excerpts verbatim — kept original")
            return prev
    if k == "character_voice_samples" and isinstance(new, list):
        ok, tot = _verbatim_rate(_dialogue_lines(new), text_norm)
        if tot and ok / tot < 0.8:
            notes.append(f"character_voice_samples: only {ok}/{tot} lines verbatim — kept original")
            return prev
    return new


def _run_keys_call(novel: str, ch: int, chapter_text: str, idx: int, total: int, label: str, keys: list,
                    existing: dict, text_norm: str, model: str, notes: list) -> dict:
    """One LLM call for exactly `keys`, guarded, -> {key: value_to_save}. `existing` is
    _existing_for(old, keys) -- the caller passes it in (rather than this function
    recomputing it from `old`) because it's also the correct carry-over/fallback value
    on failure, "none"-sentinel-preserving and all, and the caller needs that same dict
    either way. Raises on a rate/usage limit (the caller waits and retries the whole
    chapter); any other call failure returns None and leaves `existing` as the caller's
    fallback, reported back via `notes` so the caller can still raise (the chapter
    stays queued for retry, never marked done off of an incomplete pass)."""
    user = (f"Chapter {ch}:\n\n{chapter_text}\n\n"
            f"=== EXISTING EXTRACTION (from a faster model) for the requested keys ===\n"
            f"{json.dumps(existing, ensure_ascii=False, indent=1)}\n\n"
            f"Now return the UPGRADED JSON object for exactly those keys.")
    _live(novel, f"ch{ch} {label}", f"upgrading {label} ({idx}/{total})", model=_engine_label(model))
    t0 = time.time()
    try:
        raw = _ask(_system_for(idx, total, label, keys), user, keys, model)
        part = _parse_reply(raw, f"{novel} ch{ch} {label}", keys, model, notes)
    except Exception as e:
        if _is_limit_error(e):
            raise   # a usage/rate limit is not "this call has nothing" — let the caller wait and retry the whole chapter
        notes.append(f"{label}: call failed ({str(e)[:100]}) — kept the original for these keys")
        return None
    print(f"    [{novel} ch{ch}] [{idx}/{total}] {label}: {time.time() - t0:.0f}s, "
          f"{len(json.dumps(part, ensure_ascii=False)):,} bytes", flush=True)
    return {k: _apply_key_guard(k, part, existing[k], text_norm, notes) for k in keys}


def _is_haiku(model) -> bool:
    return "haiku" in _engine_label(model).lower()


def _is_nemotron_lightning(model) -> bool:
    return "lightning" in _engine_label(model).lower()


# The "fast, checked/compounded, escalate if still short" model pairs available for the Delta
# Upgrade card's hard-lock checkboxes. Add a (detector, escalate-to-model) pair here to support
# another combo -- both paths in upgrade_chapter (full plan and targeted) key off this same
# table via _is_gated_fast_model() / _escalate_model_for().
_GATED_PAIRS = (
    (_is_haiku, "claude-sonnet-5-5"),
    (_is_nemotron_lightning, "nvidia/nemotron-3-ultra-550b-a55b"),
)


def _is_gated_fast_model(model) -> bool:
    return any(detector(model) for detector, _ in _GATED_PAIRS)


def _escalate_model_for(model):
    """The model to escalate to if `model` is one of the fast/gated variants -- None for
    anything else (Sonnet, Nemotron Ultra/Super, "auto", ...), which just runs a single call
    or a fixed compound with no adaptive checking."""
    for detector, escalate in _GATED_PAIRS:
        if detector(model):
            return escalate
    return None


# Under a gated fast model (Haiku, Nemotron Lightning) a "thin" chapter's groups get up to this
# many passes: pass 1 is a normal upgrade, passes 2+ are TOP-UP passes (see _additive_call) on
# the list keys only. No escalation on this path -- a "thin" chapter's score blends 7 metrics,
# so there's no single field to judge "still short, escalate" by.
GATED_COMPOUND_PASSES = 3


# ── salvaging a jumbled reply (no second extraction call) ─────────────────────────
# Measured on the 2026-09-28 Nemotron Lightning run: most "failed" calls DID contain the data --
# wrapped in reasoning prose, preceded by schema echoes like "{excerpt, type, tone}" (which is
# why the old outermost-{...} parse failed), or cut off at the end. Each of those was thrown
# away and the next pass effectively re-ran a 3-15 minute call. Now the data is recovered from
# the reply itself; only a reply with no usable JSON at all gets one small reformat call (no
# chapter text, no re-extraction), and the verbatim guards still check every quote afterwards.
_DECODER = json.JSONDecoder()

CLEANUP_SYSTEM = (
    "You convert a messy model reply into ONE valid JSON object. Use ONLY data actually present "
    "in the reply text: copy quotes, names and values exactly as written there; never add, infer "
    "or invent anything. Ignore reasoning, commentary and any restated instructions or schema "
    "descriptions. Do not explain. Your reply must begin with '{' and end with '}'.")


def _close_truncated(s: str):
    """A JSON text cut off mid-way -> its longest prefix that ends on a complete object/array,
    with the still-open brackets closed. Keeps every complete item of a truncated list."""
    stack, cuts, in_str, esc = [], [], False, False
    for i, c in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c in "{[":
            stack.append("}" if c == "{" else "]")
        elif c in "}]":
            if not stack or stack[-1] != c:
                break
            stack.pop()
            if not stack:
                return None   # it closed properly -- not a truncation (the caller's plain parse failed for another reason)
            cuts.append((i + 1, "".join(reversed(stack))))
    for end, closer in reversed(cuts[-40:]):
        try:
            return json.loads(s[:end] + closer)
        except Exception:
            continue
    return None


def _salvage_json(raw: str, keys: list) -> dict:
    """Best-effort recovery of the answer object from a messy reply. Tries a clean parse, a
    fenced block, then every '{' as the start of a complete object (skipping reasoning prose
    and schema echoes that aren't valid JSON), then truncation repair. Picks the candidate that
    carries the most requested keys. {} if nothing usable."""
    if not raw:
        return {}
    text = raw.strip()
    cands = []

    def consider(obj):
        if isinstance(obj, dict):
            cands.append(obj)
        elif isinstance(obj, list) and len(keys) == 1:
            cands.append({keys[0]: obj})

    try:
        consider(json.loads(text))
    except Exception:
        pass
    for m in re.finditer(r"```(?:json)?\s*(.*?)```", text, re.DOTALL):
        try:
            consider(json.loads(m.group(1)))
        except Exception:
            pass
    if not any(any(k in c for k in keys) for c in cands):
        repaired = 0
        for i in (i for i, c in enumerate(text) if c == "{"):
            try:
                obj, _ = _DECODER.raw_decode(text, i)
                consider(obj)
                continue
            except Exception:
                pass
            # only worth a truncation repair where a real object starts: {"<one of our keys>"
            if repaired < 6 and re.match(r'\{\s*"(%s)"' % "|".join(map(re.escape, keys)), text[i:i + 200]):
                repaired += 1
                fixed = _close_truncated(text[i:])
                if fixed is not None:
                    consider(fixed)

    def score(c):
        present = sum(1 for k in keys if k in c)
        filled = sum(1 for k in keys if c.get(k) not in (None, "", [], {}))
        return (filled, present, len(json.dumps(c, ensure_ascii=False)))

    best = max(cands, key=score, default={})
    return best if any(k in best for k in keys) else {}


def _parse_reply(raw: str, tag: str, keys: list, model, notes: list) -> dict:
    """The one JSON parse every upgrade call goes through. Never re-runs the extraction."""
    try:
        d = json.loads((raw or "").strip())
        if isinstance(d, dict) and any(k in d for k in keys):
            return d
    except Exception:
        pass
    part = _salvage_json(raw, keys)
    if part:
        notes.append(f"{tag}: reply wasn't clean JSON — salvaged {sorted(k for k in keys if k in part)} from it")
        return part
    if raw and len(raw) >= 300:
        # Prose with the data in it ("Example 1: excerpt: '...' type: comedy"): one small
        # reformat call -- only the reply text goes in, not the chapter, and nothing is re-extracted.
        try:
            cleaned = _ask(CLEANUP_SYSTEM,
                           f"Required top-level keys: {', '.join(keys)}. A key with no data in the reply "
                           f"gets an empty list [].\n\n=== REPLY ===\n{raw[:24000]}", keys, model)
            part = _salvage_json(cleaned, keys)
            if part:
                notes.append(f"{tag}: reply was prose, not JSON — reformatted it (small cleanup call, no re-extraction)")
                return part
        except Exception as e:
            if _is_limit_error(e):
                raise
    print(f"ERROR: nothing recoverable in the reply ({tag}). First 300 chars: {(raw or '')[:300]!r}", flush=True)
    return {}


# ── top-up (append-only) passes ─────────────────────────────────────────────────
# A field that already has correct items but is short is TOPPED UP, never redone: the model is
# shown what's already listed (compactly) and asked only for what's missing; its answer is
# appended. Existing items are never re-sent for rewriting, so they can't drift, shrink or be
# dropped, and the reply is a fraction of the size. An empty answer is a result, not a failure:
# the model looked and there is no more, so the key is recorded as confirmed complete
# (delta["confirmed_complete"], or confirmed_empty if it's still empty) and is never re-asked.
LIST_KEYS = {"new_characters", "new_locations", "new_factions", "new_glossary_terms", "facts", "timeline_events",
             "humor_instances", "scheme_instances", "knowledge_state", "antagonist_template_instances", "reveals",
             "prose_samples", "character_voice_samples"}
_ID_FIELDS = ("excerpt", "content", "fact", "event", "term", "name", "line", "description", "summary")

ADDITIVE_RULES = """

─── TOP-UP MODE ──────────────────────────────────────────────────────────────
The requested keys already have items, listed after the chapter under ALREADY LISTED. They are
correct. Do NOT repeat, rephrase, correct or re-describe any of them. Your only job is to find
what is MISSING: further items of the same kinds that this chapter genuinely contains but that
are not listed yet.
- Return a JSON object with exactly the requested keys; each value is a list of ONLY the NEW
  items, in the item format the schema above defines.
- character_voice_samples: for a character already listed, give an entry with the SAME
  character_name and only the new dialogue_samples (no speech_dna); for a new character, give
  the full entry.
- Every excerpt and dialogue line must be copied EXACTLY from the chapter text.
- If the chapter has nothing more for a key, return an empty list [] for it. That is a correct,
  useful answer. Do NOT invent items to fill a key."""


def _item_id(item) -> str:
    if isinstance(item, dict):
        if all(f in item for f in ("subject", "predicate", "object")):
            return _norm(f"{item['subject']}|{item['predicate']}|{item['object']}")
        for f in _ID_FIELDS:
            v = item.get(f)
            if isinstance(v, str) and v.strip():
                return _norm(v)
        return _norm(json.dumps(item, sort_keys=True, ensure_ascii=False))
    return _norm(str(item))


def _compact_listing(key: str, value) -> list:
    """What's already there, as short identity strings -- enough for the model to avoid repeats,
    a fraction of the tokens of the full items."""
    if not isinstance(value, list):
        return []
    if key == "character_voice_samples":
        return [{"character_name": c.get("character_name"),
                 "dialogue_lines": [str(s.get("line", ""))[:160] for s in (c.get("dialogue_samples") or [])
                                    if isinstance(s, dict)]}
                for c in value if isinstance(c, dict)]
    out = []
    for it in value:
        if isinstance(it, dict) and all(f in it for f in ("subject", "predicate", "object")):
            out.append(f"{it['subject']} | {it['predicate']} | {it['object']}")
        elif isinstance(it, dict):
            txt = next((it[f] for f in _ID_FIELDS if isinstance(it.get(f), str) and it[f].strip()), None)
            out.append((txt or json.dumps(it, ensure_ascii=False))[:200])
        else:
            out.append(str(it)[:200])
    return out


def _merge_voice_additive(cur: list, new: list, text_norm: str, notes: list, tag: str):
    cur = [dict(c, dialogue_samples=list(c.get("dialogue_samples") or [])) for c in cur if isinstance(c, dict)]
    by_name = {_norm(str(c.get("character_name", ""))): c for c in cur}
    seen = {_norm(str(s.get("line", ""))) for c in cur for s in c["dialogue_samples"] if isinstance(s, dict)}
    added = dropped = 0
    for e in new:
        if not isinstance(e, dict):
            continue
        lines = []
        for s in e.get("dialogue_samples") or []:
            if not (isinstance(s, dict) and s.get("line")):
                continue
            if not _text_is_verbatim(s["line"], text_norm):
                dropped += 1
                continue
            n = _norm(s["line"])
            if n and n not in seen:
                seen.add(n)
                lines.append(s)
        if not lines:
            continue
        name = _norm(str(e.get("character_name", "")))
        if name and name in by_name:
            by_name[name]["dialogue_samples"].extend(lines)
        else:
            entry = {"character_name": e.get("character_name", ""), "dialogue_samples": lines}
            if isinstance(e.get("speech_dna"), dict):
                entry["speech_dna"] = e["speech_dna"]
            cur.append(entry)
            by_name[name] = entry
        added += len(lines)
    if dropped:
        notes.append(f"{tag}: character_voice_samples: dropped {dropped} new line(s) that weren't verbatim")
    return cur, added


def _merge_additive(key: str, current, new, text_norm: str, notes: list, tag: str):
    """current + only the genuinely new items -> (merged, n_added). Existing items untouched;
    repeats de-duplicated; for quoted fields only the non-verbatim NEW items are dropped (the
    good ones in the same answer are kept, not the whole batch thrown out)."""
    cur = list(current) if isinstance(current, list) else []
    if isinstance(new, str) and new.strip().strip('."').lower() in ("none", "", "[]"):
        new = []
    if not isinstance(new, list):
        return cur, 0
    if key == "character_voice_samples":
        return _merge_voice_additive(cur, new, text_norm, notes, tag)
    seen = {_item_id(x) for x in cur}
    added = dropped = 0
    for item in new:
        if key == "prose_samples" and not (isinstance(item, dict) and _text_is_verbatim(item.get("excerpt", ""), text_norm)):
            dropped += 1
            continue
        iid = _item_id(item)
        if iid and iid not in seen:
            seen.add(iid)
            cur.append(item)
            added += 1
    if dropped:
        notes.append(f"{tag}: {key}: dropped {dropped} new excerpt(s) that weren't verbatim")
    return cur, added


def _additive_call(novel: str, ch: int, chapter_text: str, idx: int, total: int, label: str, keys: list,
                   current: dict, text_norm: str, model, notes: list):
    """One TOP-UP call for `keys`; merges the new items into `current` in place.
    -> {key: n_added, or None if the reply had nothing for that key}, or None if the call failed."""
    listed = {k: _compact_listing(k, current.get(k)) for k in keys}
    user = (f"Chapter {ch}:\n\n{chapter_text}\n\n"
            f"=== ALREADY LISTED for the requested keys (correct -- do NOT repeat any of these) ===\n"
            f"{json.dumps(listed, ensure_ascii=False, indent=1)}\n\n"
            f"Return ONLY the NEW items for exactly those keys ([] where there is nothing more).")
    tag = f"{novel} ch{ch} {label}"
    _live(novel, f"ch{ch} {label}", f"topping up {', '.join(keys)} ({idx}/{total})", model=_engine_label(model))
    t0 = time.time()
    try:
        raw = _ask(_system_for(idx, total, label, keys, rules=ADDITIVE_RULES), user, keys, model)
        part = _parse_reply(raw, tag, keys, model, notes)
    except Exception as e:
        if _is_limit_error(e):
            raise
        notes.append(f"{label}: top-up call failed ({str(e)[:100]}) — kept what was there")
        return None
    added = {}
    for k in keys:
        if k not in part:
            added[k] = None
            continue
        merged, n = _merge_additive(k, current.get(k), part[k], text_norm, notes, tag)
        if n:
            current[k] = merged
        added[k] = n
    print(f"    [{novel} ch{ch}] [{idx}/{total}] {label}: {time.time() - t0:.0f}s, top-up added "
          + ", ".join(f"{k} +{n if n is not None else '?'}" for k, n in added.items()), flush=True)
    return added


# Validated on my_novel ch31's "prose" group (2026-09-27): baseline density sat at
# the 4.8th percentile (deep tier-C); pass 1 ALONE already reached the 42.9th (clear of the
# tier-C/B line at 35) at ~100s, with passes 2-3 adding real but smaller further gains (52.4,
# 61.9) at ~150s each. So for a key with a measured density metric, one pass is often already
# "good enough" -- check and stop, rather than always paying for a fixed compound count.
#
# Only 7 keys have a measured metric at all (delta_audit.METRIC_FIELD, inverted here) --
# everything else (chapter_title, scheme_instances, world-building lists, the narrative-voice
# dict fields, ...) has no density signal to check against, so there's nothing to adaptively
# decide there; those get exactly one pass, same as any other engine.
_METRIC_FOR_KEY = {"facts": "facts", "timeline_events": "timeline", "reveals": "reveals",
                   "knowledge_state": "knowledge", "prose_samples": "prose",
                   "character_voice_samples": "dialogue", "new_glossary_terms": "glossary"}
GATED_TOPUP_MAX_PASSES = 3        # hard cap of quick fast-model passes; every pass is checked (see the
                                   # loop below), so this is a ceiling on worst-case cost, not a count
                                   # that always runs. Still short of the bar after all 3 -> one
                                   # escalation pass on this model's pair (_GATED_PAIRS) rather than
                                   # settle for the fast model's best or keep paying for more passes.
GATED_TOPUP_TARGET_PCT = 40.0     # stop once at/above this -- a little past the tier-C/B line (35)

_REFERENCE_CACHE = {}


def _reference() -> dict:
    """delta_audit's corpus-wide density reference quantiles, loaded once and cached --
    this is what a real audit run would compare against, so the stopping decision here
    matches what delta_quality.json would actually say about the result."""
    if "ref" not in _REFERENCE_CACHE:
        try:
            reg = json.loads((HERE / "delta_quality.json").read_text(encoding="utf-8"))
            _REFERENCE_CACHE["ref"] = reg.get("reference") or {}
        except Exception:
            _REFERENCE_CACHE["ref"] = {}
    return _REFERENCE_CACHE["ref"]


def _key_percentile(key: str, value, kchars: float, ref: dict):
    """This key's current value's density percentile against the corpus reference, using
    the exact same counting rule delta_audit.measure() uses for its metric -- or None if
    `key` has no measured metric (see _METRIC_FOR_KEY)."""
    metric = _METRIC_FOR_KEY.get(key)
    if not metric or metric not in ref:
        return None
    import delta_audit as da
    count = len(da._dialogue({"character_voice_samples": value})) if key == "character_voice_samples" else da._n(value)
    return da.percentile(ref[metric], count / kchars)


def _run_keys_gated(novel: str, ch: int, chapter_text: str, idx: int, total: int, label: str, keys: list,
                    existing: dict, text_norm: str, model, notes: list, kchars: float, passes: int,
                    topup_keys: list, first_additive: bool, escalate_model, complete: set):
    """Pass 1 settles every key: a normal upgrade call ("keep what's right, fix what's wrong, add
    what's missing") -- or, with first_additive, a top-up call, for keys that are only SHORT with
    nothing wrong in what's there. Passes 2..`passes` are top-up calls on `topup_keys` only
    (dict/string keys are settled by pass 1 and never re-asked). A key leaves the loop the moment
      (a) a top-up adds nothing -- the model looked and there is no more: recorded in
          `complete`, never re-asked, no escalation -- or
      (b) its density reaches GATED_TOPUP_TARGET_PCT (keys with a measured metric).
    A metric key still short after the last pass gets one top-up on `escalate_model` (if given).
    -> {key: value}, or None if pass 1 itself failed."""
    ref = _reference()
    current = dict(existing)
    tag = f"{novel} ch{ch} {label}"

    def cleared(k) -> bool:
        pct = _key_percentile(k, current.get(k), kchars, ref)
        return pct is not None and pct >= GATED_TOPUP_TARGET_PCT

    def settle(added: dict, open_keys: list, what: str):
        for k, n in added.items():
            if k not in open_keys:
                continue
            if n == 0:
                open_keys.remove(k)
                complete.add(k)
                notes.append(f"{tag}: {k}: {what} found nothing more — confirmed complete, moving on")
            elif n and cleared(k):
                open_keys.remove(k)

    if first_additive:
        added = _additive_call(novel, ch, chapter_text, idx, total, f"{label} top-up 1/{passes}", keys,
                               current, text_norm, model, notes)
        if added is None:
            return None
        open_keys = [k for k in topup_keys if k in keys]
        settle(added, open_keys, "top-up 1")
    else:
        # Only say "pass 1/N" when later top-up passes are actually possible for these keys --
        # a key with nothing to top up (scheme_instances, chapter_title, ...) gets exactly one call.
        more = passes > 1 and any(k in topup_keys for k in keys)
        r = _run_keys_call(novel, ch, chapter_text, idx, total, f"{label} pass 1/{passes}" if more else label,
                           keys, current, text_norm, model, notes)
        if r is None:
            return None
        current.update(r)
        open_keys = [k for k in topup_keys if k in keys and not cleared(k)]

    for p in range(2, passes + 1):
        if not open_keys:
            break
        added = _additive_call(novel, ch, chapter_text, idx, total, f"{label} top-up {p}/{passes}", list(open_keys),
                               current, text_norm, model, notes)
        if added is None:
            notes.append(f"{tag}: top-up {p} failed — kept what was there")
            break
        settle(added, open_keys, f"top-up {p}")

    short = [k for k in open_keys if k in _METRIC_FOR_KEY and not cleared(k)]
    if escalate_model and short:
        notes.append(f"{tag}: {short} still short after {passes} pass(es) — one top-up on {escalate_model}")
        added = _additive_call(novel, ch, chapter_text, idx, total, f"{label} escalation", short,
                               current, text_norm, escalate_model, notes)
        if added:
            settle(added, list(short), f"escalation ({escalate_model})")
    return current


# Flags that mean a field is only SHORT (nothing wrong with what's there) -- their keys are
# topped up from the first call instead of being rewritten. Every other flag (not verbatim,
# guessed scheme refs, page-header title, missing key) means something IS wrong, so pass 1 is
# a real upgrade call that can fix it.
_VOLUME_FLAGS = {"few_dialogue", "reveals_unconfirmed", "knowledge_unconfirmed"} | set(_LOW_FLAG_KEYS)

# Chapters now run in parallel (see _upgrade_loop). Assembling a delta swaps
# ex.extract_with_llm for a moment -- a module-wide attribute -- so that step, which is local
# and takes well under a second, runs one chapter at a time. The LLM calls don't.
_ASSEMBLE_LOCK = threading.Lock()


# ── one chapter ────────────────────────────────────────────────────────────────
def _upgrade_chapter_v3(novel: str, ch: int, model: str, notes: list, flags: list = None) -> dict:
    delta_path = NOVELS_DIR / novel / "deltas_v3" / f"ch{ch}.json"
    backup = NOVELS_DIR / novel / "deltas_v3" / f"ch{ch}.haiku45-original.json"
    old = json.loads(delta_path.read_text(encoding="utf-8"))
    text = ex.load_chapter_text(novel, ch)
    text_norm = _norm(text)
    chapter_text = f"{text[:14000]}{'[... truncated ...]' if len(text) > 14000 else ''}"
    kchars = max(len(text), 1) / 10000.0
    gated = _is_gated_fast_model(model)
    complete: set = set()   # keys a top-up confirmed have nothing more in this chapter
    # (The backup is written just before saving, not here: a chapter whose calls fail is left
    # untouched, and a backup made up front used to make it look "upgraded" to the scan, which
    # then never offered it again.)

    target_keys = _keys_for_flags(flags)
    flags = flags or []
    if "schema_incomplete" in flags and "thin" not in flags:
        # "thin" (if present) already forces the full plan below -- don't let this narrow it.
        # Otherwise: fold in any REQUIRED_KEYS member that's actually LLM-sourced and genuinely
        # missing (see _missing_required_keys) instead of leaving schema_incomplete to force a
        # full redo it doesn't need.
        missing = _missing_required_keys(old)
        if missing:
            target_keys = sorted(set(target_keys or []) | set(missing), key=_key_order)
            notes.append(f"schema_incomplete: {missing} genuinely missing -- added to the targeted call")
    llm, failed, total_calls = {}, 0, 0

    if target_keys is not None:
        # ---- targeted path: only the flagged key(s); every other key is carried over untouched.
        # Keys that are only SHORT are topped up (append-only) from the first call; keys with
        # something wrong get a real upgrade call first. Under a gated fast model, density-measured
        # keys then keep topping up until they clear the bar or come back with nothing more. ----
        untouched = [k for k in _ALL_KEYS if k not in target_keys]
        notes.append(f"targeted upgrade: {target_keys} (flags: {flags}) — {len(untouched)} other key(s) left as they were")
        llm.update(_existing_for(old, untouched))   # sentinel-preserving carry-over, not a raw old.get()
        volume = {k for f in flags if f in _VOLUME_FLAGS for k in _FLAG_KEYS.get(f, ())}
        corrective = {k for f in flags if f not in _VOLUME_FLAGS for k in _FLAG_KEYS.get(f, ())}
        additive_first = [k for k in target_keys if k in volume and k not in corrective and k in LIST_KEYS]
        rewrite_first = [k for k in target_keys if k not in additive_first]
        passes = GATED_TOPUP_MAX_PASSES if gated else 1
        topup = [k for k in target_keys if k in _METRIC_FOR_KEY]
        # ISOLATED: one call per field (a weak facts list is re-asked on its own; it no longer drags the other flagged
        # fields into the same answer, where one bad value could cost them all)
        for keys_, first_add in [([k], False) for k in rewrite_first] + [([k], True) for k in additive_first]:
            total_calls += 1
            existing = _existing_for(old, keys_)
            llm.update(existing)   # fallback; overwritten below on success
            label = ("top-up: " if first_add else "targeted: ") + ", ".join(keys_)
            result = _run_keys_gated(novel, ch, chapter_text, 1, 1, label, keys_, existing, text_norm, model, notes,
                                     kchars, passes, [k for k in keys_ if k in topup], first_add, _escalate_model_for(model), complete)
            if result is None:
                failed += 1
            else:
                llm.update(result)
    else:
        # ---- full plan (thin / unlocalizable / no flags): every group. Under a gated fast model
        # each group gets pass 1 plus up to GATED_COMPOUND_PASSES-1 top-up passes on its list keys. ----
        groups = ex.SPLIT_GROUPS
        passes = GATED_COMPOUND_PASSES if gated else 1
        if passes > 1:
            notes.append(f"gated: pass 1 + up to {passes - 1} top-up pass(es) per group with {_engine_label(model)}")
        for idx, (label, keys) in enumerate(groups, 1):
            total_calls += 1
            existing = _existing_for(old, keys)
            llm.update(existing)   # fallback; overwritten below on success
            result = _run_keys_gated(novel, ch, chapter_text, idx, len(groups), label, keys, existing, text_norm, model,
                                     notes, kchars, passes, [k for k in keys if k in LIST_KEYS], False, None, complete)
            if result is None:
                failed += 1
            else:
                llm.update(result)

    if failed:
        # A chapter where any call failed was NOT upgraded in full — don't mark it done (it used to be: the failed group
        # silently kept Haiku's values and the chapter still counted as upgraded). It stays in the queue for a retry.
        raise RuntimeError(f"{failed} of {total_calls} call(s) failed — chapter left as it was, will be retried")

    with _ASSEMBLE_LOCK:
        if not backup.exists():
            shutil.copy2(delta_path, backup)   # never overwritten: the first copy is the real original
        # Assemble through the extractor's own code path (style pass, none-sentinels, title fallback, metadata).
        real = ex.extract_with_llm
        ex.extract_with_llm = lambda t, n: json.loads(json.dumps(llm))
        try:
            delta = ex.extract_chapter_v3(novel, ch)
        finally:
            ex.extract_with_llm = real
        delta["merge_notes"] = old.get("merge_notes") or delta.get("merge_notes") or {}
        if old.get("novel_metadata_hints"):
            delta["novel_metadata_hints"] = old["novel_metadata_hints"]
        # Record what the top-ups settled: a field that came back with nothing more is complete (or,
        # if it's still empty, confirmed empty) -- the audit stops flagging it and nothing re-asks it.
        ce = set(delta.get("confirmed_empty") or [])
        cc = set(old.get("confirmed_complete") or [])
        for k in complete:
            if delta.get(k) in (None, "", [], {}):
                if k in ex.CONFIRMABLE_EMPTY_FIELDS:
                    ce.add(k)
            else:
                cc.add(k)
        delta["confirmed_empty"] = sorted(ce)
        if cc - ce:
            delta["confirmed_complete"] = sorted(cc - ce)
        if target_keys is not None:      # each field is re-asked once: stamp it so the audit stops flagging it (see delta_audit)
            delta["retried_fields"] = sorted(set(old.get("retried_fields") or []) | set(target_keys))
        elif old.get("retried_fields"):
            delta["retried_fields"] = old["retried_fields"]
        try:   # so the quality mark written by save_delta records the engine/model that actually did this upgrade
            import delta_audit
            delta_audit.set_provenance(*_provenance(model), upgraded=True)
        except Exception:
            pass
        ex.save_delta(delta, novel)
    return {"before": _summary_counts(old), "after": _summary_counts(delta)}


# ── resolve mode: "nothing to extract" vs "missed it" ─────────────────────────────
RESOLVE_RULES = """

─── CHECK MODE ───────────────────────────────────────────────────────────────
An earlier extraction left the keys above EMPTY, and nobody has ever checked whether that is because the
chapter genuinely contains nothing for them, or because the earlier extraction missed what is there.
Read the chapter and decide, key by key:
- If the chapter contains content for the key, extract it fully, following the definitions above.
- If the chapter genuinely contains nothing for that key, return the exact string "none" for it. That is a real,
  useful answer — it records that the emptiness is correct. Do NOT invent content to fill a field.
Every quote or excerpt must be copied exactly from the chapter text. Return a JSON object with exactly the
requested keys and no others."""

RESOLVE_STATE = HERE / "resolve_empties_state.json"


def _load_resolve_state() -> dict:
    try:
        return json.loads(RESOLVE_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def resolve_chapter(novel: str, ch: int, keys: list, model: str, dry_run: bool = False, final_try: bool = False) -> dict:
    """Ask about ONE chapter's unconfirmed empty fields. Returns {field: 'filled'|'confirmed_none'|'left'} and,
    unless dry_run, writes the result into the delta (fills the field, or records it in confirmed_empty)."""
    path = NOVELS_DIR / novel / "deltas_v3" / f"ch{ch}.json"
    delta = json.loads(path.read_text(encoding="utf-8"))
    text = ex.load_chapter_text(novel, ch)
    text_norm = _norm(text)
    chapter_text = f"{text[:14000]}{'[... truncated ...]' if len(text) > 14000 else ''}"

    key_list = "\n".join(f"  - {k}" for k in keys)
    system = (ex.SYSTEM_PROMPT
              + f"\n\n─── THIS CALL ───\nThe full schema is above for context, but for THIS response you must return ONLY these keys:\n"
                f"{key_list}\nReturn a single JSON object containing exactly (and only) those keys." + RESOLVE_RULES)
    user = (f"Chapter {ch}:\n\n{chapter_text}\n\nThe keys above are currently empty. Return the JSON object now: "
            f"real content where the chapter has it, the string \"none\" where it genuinely does not.")
    part = _parse_reply(_ask(system, user, keys, model), f"{novel} ch{ch} resolve", keys, model, [])

    outcome, filled = {}, {}
    for k in keys:
        v = part.get(k)
        if isinstance(v, str) and v.strip().strip('."').lower() in ex._NONE_TOKENS:
            outcome[k] = "confirmed_none"
        elif k in part and v in ([], {}, ""):
            # The model was pointed straight at this key and explicitly answered with an empty value. That is an answer,
            # the same rule repair_chapter_fields applies ("asked for it and produced nothing"): the chapter has nothing
            # for it. Only a key that is MISSING from the reply, or unusable content, is left unresolved.
            outcome[k] = "confirmed_none"
        elif isinstance(v, list) and v and all(isinstance(i, (dict, str)) for i in v):
            # Keep only the quotes that really are in the chapter and drop the rest, instead of rejecting the whole
            # answer when a few lines are paraphrased (that left chapters with real dialogue "unresolved" because e.g.
            # 6 of 8 lines were verbatim). Nothing invented can get in; the verified content is kept.
            kept = _keep_verbatim(k, v, text_norm)
            if kept:
                outcome[k] = "filled"
                filled[k] = kept
            else:
                outcome[k] = "left"          # returned content, but none of the quotes were actually in the chapter
        else:
            # The key was missing from the reply, or unusable. First time: leave it unconfirmed for one more try. On the
            # final try it is a real answer — the model was asked about exactly this field twice and produced nothing —
            # the same rule extract_v3.repair_chapter_fields applies, so the chapter can finally be closed.
            outcome[k] = "confirmed_none" if final_try else "left"

    if dry_run:
        return {"outcome": outcome, "filled_counts": {k: len(v) for k, v in filled.items()}, "filled": filled}

    backup = NOVELS_DIR / novel / "deltas_v3" / f"ch{ch}.pre-resolve-original.json"
    if not backup.exists():
        shutil.copy2(path, backup)
    ce = set(delta.get("confirmed_empty") or [])
    for k, res in outcome.items():
        if res == "filled":
            delta[k] = filled[k]
            ce.discard(k)
        elif res == "confirmed_none":
            delta.setdefault(k, [])
            ce.add(k)
    delta["confirmed_empty"] = sorted(ce)
    # Keep the chapter's recorded engine/upgraded status: this pass fills gaps, it doesn't re-extract the chapter.
    try:
        import delta_audit
        prev = ((delta_audit.load_registry().get("novels", {}).get(novel, {}).get("chapters", {})) or {}).get(str(ch)) or {}
        delta_audit.set_provenance(prev.get("engine") or "unknown", prev.get("model"), upgraded=bool(prev.get("upgraded")))
    except Exception:
        pass
    ex.save_delta(delta, novel)
    return {"outcome": outcome, "filled_counts": {k: len(v) for k, v in filled.items()}}


def resolve_main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--novel")
    ap.add_argument("--chapters", help='limit to these chapters, e.g. "41-60"')
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true", help="ask the model but write nothing")
    ap.add_argument("--model", default=None, help='"auto" (default) = the app\'s selected engine/model; or force e.g. claude-sonnet-5-5')
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    args.model = args.model or MODEL

    import delta_audit
    reg = delta_audit.load_registry()
    targets = [c for c in reg.get("resolve_candidates", [])
               if (not args.novel or c["novel"] == args.novel)]
    if args.chapters:
        want = set(parse_chapters(args.chapters))
        targets = [c for c in targets if c["chapter"] in want]
    state = _load_resolve_state()
    def _needs_visit(key: str) -> bool:
        s = state.get(key)
        # Never visited, OR visited but left unresolved on the first try (one retry, after which it is closed).
        return s is None or (any(v == "left" for v in (s.get("outcome") or {}).values()) and s.get("attempts", 1) < 2)
    todo = [c for c in targets if args.force or _needs_visit(f"{c['novel']}/{c['chapter']}")]
    # Round-robin: one chapter from each novel in turn, so all novels progress together (results across the whole
    # corpus show up early, and no single novel's problems block the rest).
    todo = _round_robin(todo, key=lambda c: c["novel"])
    print(f"Checking {len(todo)} chapter(s) with unconfirmed empty fields ({len(targets) - len(todo)} already checked) with {_engine_label(args.model)}"
          + f" — round-robin across {len({c['novel'] for c in todo})} novels"
          + ("  [DRY RUN — nothing is written]" if args.dry_run else ""), flush=True)
    # Same agent method as Chapter Mechanics: one agent per Nvidia key, chapters dealt round-robin across novels.
    from agent_pool import AgentPool
    if args.limit:
        todo = todo[:args.limit]
    pool = AgentPool("empty_check", model=_engine_label(args.model), want=4)
    state_lock = threading.Lock()
    t0, n = time.time(), [0]

    def work(it):
        novel, ch, keys = it["novel"], it["chapter"], it["fields"]
        print(f"\n[{novel} ch{ch}] checking: {', '.join(keys)}", flush=True)
        res = None
        while True:
            pool.step("checking empty fields", ", ".join(keys))
            try:
                prior = state.get(f"{novel}/{ch}")
                res = resolve_chapter(novel, ch, keys, args.model, dry_run=args.dry_run,
                                      final_try=bool(prior and any(v == "left" for v in (prior.get("outcome") or {}).values())))
                break
            except Exception as e:
                if _is_limit_error(e):     # wait and retry THIS chapter; skipping ahead would just fail the same way
                    _wait_out_limit("empty_check", novel, f"ch{ch}", _engine_label(args.model))
                    continue
                print(f"  FAILED: {str(e)[:200]}", flush=True)
                break
        if res is None:
            return None
        print(f"  [{novel} ch{ch}] " + "  ".join(f"{k}: {v}" + (f" ({res['filled_counts'][k]} items)" if k in res["filled_counts"] else "") for k, v in res["outcome"].items()), flush=True)
        with state_lock:
            if not args.dry_run:
                # "by" matters: a 'confirmed none' is only as trustworthy as the model that said it, and the model is no
                # longer fixed - so every ruling records who made it (a weak engine's "none" can be re-checked later).
                prev_attempts = (state.get(f"{novel}/{ch}") or {}).get("attempts", 0) or (1 if f"{novel}/{ch}" in state else 0)
                state[f"{novel}/{ch}"] = {"outcome": res["outcome"], "by": _engine_label(args.model),
                                          "attempts": prev_attempts + 1, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
                tmp = RESOLVE_STATE.with_suffix(".tmp")
                tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
                os.replace(tmp, RESOLVE_STATE)
            n[0] += 1
            print(f"  progress: {n[0]}/{len(todo)} | about {(time.time() - t0) / n[0] * (len(todo) - n[0]) / 60:.0f} min left", flush=True)
        return res

    pool.run([{"novel": c["novel"], "chapter": c["chapter"], "fields": c["fields"]} for c in todo], work)
    n = n[0]
    print(f"\nDONE. {n} chapter(s) checked.")


# ── run history (survives restarts) ──────────────────────────────────────────────
# delta_upgrade.log is truncated by every launch (cmd.exe `>`), so when a run died silently
# there was no way to tell afterwards how. This file is only ever appended to: start, each
# finished chapter, normal exit, any uncaught exception (any thread), and a native-crash dump
# via faulthandler. A "start" with no matching "exit" = the process was ended from outside.
HISTORY = HERE / "delta_upgrade.history.log"
_HIST_LOCK = threading.Lock()


def _hist(msg: str):
    try:
        with _HIST_LOCK, open(HISTORY, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} pid {os.getpid()}: {msg}\n")
    except Exception:
        pass


def _install_history_hooks():
    import atexit
    import faulthandler
    import traceback
    try:
        faulthandler.enable(file=open(HISTORY, "a", encoding="utf-8"), all_threads=True)
    except Exception:
        pass
    atexit.register(lambda: _hist("exit (normal shutdown)"))
    prev_sys, prev_thr = sys.excepthook, threading.excepthook

    def _sys_hook(t, v, tb):
        _hist("CRASH (main thread): " + "".join(traceback.format_exception(t, v, tb))[-1500:])
        prev_sys(t, v, tb)

    def _thr_hook(args):
        _hist(f"CRASH (thread {args.thread.name if args.thread else '?'}): "
              + "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))[-1500:])
        prev_thr(args)

    sys.excepthook, threading.excepthook = _sys_hook, _thr_hook


# ── driver ─────────────────────────────────────────────────────────────────────
def main():
    _install_history_hooks()
    _hist(f"start: {' '.join(sys.argv[1:]) or '(scan mode)'}")
    ap = argparse.ArgumentParser()
    ap.add_argument("--novel")
    ap.add_argument("--chapters", help='e.g. "41-60" or "41,43,50-52"')
    ap.add_argument("--model", default=None)
    ap.add_argument("--limit", type=int, default=0, help="stop after this many chapters (testing)")
    ap.add_argument("--force", action="store_true", help="redo chapters already marked done")
    args = ap.parse_args()

    cfg = {}
    if CONFIG.exists():
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    model = args.model or cfg.get("model") or MODEL

    if args.novel or args.chapters or (cfg.get("source") != "scan" and cfg.get("novel") and cfg.get("chapters")):
        # Explicit list: --novel/--chapters, or a fixed novel + chapters in the config (the original behaviour).
        novel = args.novel or cfg.get("novel")
        chapters = parse_chapters(args.chapters) if args.chapters else cfg.get("chapters", [])
        if not novel or not chapters:
            print("Nothing to do: give --novel and --chapters, or set them in upgrade_deltas_config.json")
            sys.exit(1)
        # No audit flags available for an explicit list -- run the full 4-way plan on each,
        # same as before (see _keys_for_flags: empty flags -> everything).
        targets = [(novel, c, []) for c in chapters]
    else:
        # Scan mode (default): the worklist is whatever the upgrade scan flags RIGHT NOW. Re-scanning first means a fresh
        # list (chapters the Empty-field Check fixed have dropped out; newly extracted thin chapters have been added), and
        # a chapter stops being a candidate as soon as it has been upgraded. Round-robin so all novels advance together.
        import delta_audit
        print("Refreshing the upgrade scan for a current worklist ...", flush=True)
        reg = delta_audit.full_scan()
        flagged = _round_robin([{"novel": c["novel"], "chapter": c["chapter"], "flags": c.get("flags") or []}
                                for c in reg.get("upgrade_candidates", [])],
                               key=lambda x: x["novel"])
        targets = [(t["novel"], t["chapter"], t["flags"]) for t in flagged]
        # Smallest jobs first, biggest last: targeted chapters (1-5 keys, often one call) before the
        # full-plan "thin" ones (every group, several calls each). Stable sort, so the round-robin
        # across novels still holds inside each size.
        def _size(t):
            mech = [x for x in t[2] if x in MECH_FLAGS]
            v3 = [x for x in t[2] if x not in MECH_FLAGS]
            if mech and not v3:                      # mechanics-only: one short call per flagged field
                return (False, len(mech))
            keys = _keys_for_flags(v3)
            return (keys is None, len(keys or ()) + len(mech))
        targets.sort(key=_size)
        n_full = sum(1 for t in targets if _size(t)[0])
        print(f"The scan flags {len(targets)} chapter(s) across {len({n for n, _, _ in targets})} novels — round-robin, "
              f"{len(targets) - n_full} targeted first, {n_full} full-plan (thin) last.", flush=True)
    workers = max(1, int(cfg.get("workers") or DEFAULT_WORKERS))
    _upgrade_loop(targets, model, args.limit, args.force, workers)


# Chapters processed at once. Each LLM call is minutes of waiting on a remote model, and one
# chapter's calls don't depend on another's -- running them one at a time left the job idle
# ~95% of the time. Override with "workers" in upgrade_deltas_config.json (1 = old behaviour).
DEFAULT_WORKERS = 4
_STATE_LOCK = threading.Lock()


def _mech_counts(rec: dict) -> dict:
    return {"mx_beats": len(rec.get("beats") or []), "mx_cast": len(rec.get("cast") or []),
            "mx_fight_talk": mc.talk_lines(rec.get("fights"))}


def _upgrade_mechanics(novel: str, ch: int, model, notes: list, mech_flags: list) -> dict:
    """ISOLATED field upgrade of a chapter's mechanics: each flag (thin_beats / thin_fight_talk / thin_cast) is ONE call that
    re-asks ONLY its own key, with that key's existing value, and is accepted or rejected on its own (never fewer beats, cast
    or talk lines than before). Every other part of the record, and the whole V3 delta, is left exactly as it was."""
    delta_path = NOVELS_DIR / novel / "deltas_v3" / f"ch{ch}.json"
    old_delta = json.loads(delta_path.read_text(encoding="utf-8"))
    old = old_delta.get("mechanics")
    if not isinstance(old, dict) or not old:
        raise RuntimeError("no mechanics on this chapter to upgrade (the Chapter Mechanics job builds them first)")
    text = ex.load_chapter_text(novel, ch)
    backup = NOVELS_DIR / novel / "deltas_v3" / f"ch{ch}.mech-original.json"
    if not backup.exists():                     # the first copy is the real original, never overwritten
        backup.write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")
    rec = dict(old)
    rec.setdefault("novel", novel)
    rec.setdefault("chapter_number", ch)
    words = (rec.get("measured") or {}).get("words") or len(text.split())
    numbered, ctx = mc.numbered_text(text), mc.context_v4(novel, ch, text)
    before = _mech_counts(rec)
    already = set(rec.get("upgrade_progress") or [])      # fields a previous (interrupted) pass finished
    changed, kept, failed = [], [], 0
    for flag in mech_flags:
        key = mc.UPGRADE_KEYS[flag]
        field = mc.MX_KEYS[key]
        if field in already:
            continue
        _live(novel, f"ch{ch} mechanics: {field}", f"re-asking only {field}", model=_engine_label(model))
        user = (f"Chapter {ch} (paragraph-numbered):\n\n{numbered}\n\nCONTEXT (measured by Python; exact):\n{ctx}\n\n"
                f"EXISTING {key} (keep what is right, fix what is wrong, add what is missing):\n"
                f"{json.dumps(rec.get(field), ensure_ascii=False)[:14000]}\n\nReturn ONLY the key {key} as one valid JSON object.")
        try:
            raw = _ask(mc.upgrade_system(key, rec, words), user, [key], model)
        except Exception as e:
            if _is_limit_error(e):
                raise                              # the caller waits out the limit and retries; finished fields are kept
            notes.append(f"{key}: the call failed — {str(e)[:120]}")
            failed += 1
            continue
        part = _parse_reply(raw, f"{novel} ch{ch} {key}", [key], model, notes)
        new, why = mc.apply_upgraded_part(rec, key, part.get(key) if isinstance(part, dict) else None, text, notes)
        if new is rec:
            kept.append(field)
            notes.append(why)
        else:
            rec = new
            changed.append(field)
        rec["upgrade_progress"] = sorted(already | set(changed) | set(kept))
        mc.attach_mechanics(novel, ch, rec)        # saved after every field: an interrupted pass keeps what it finished
    if failed and failed == len([f for f in mech_flags if mc.MX_KEYS[mc.UPGRADE_KEYS[f]] not in already]):
        raise RuntimeError("every mechanics call failed")
    eng, mdl = _provenance(model)
    rec.pop("upgrade_progress", None)
    rec["upgraded"] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "fields": changed, "kept": kept, "engine": eng, "model": mdl}
    mc.attach_mechanics(novel, ch, rec)
    try:   # refresh the audit mark WITHOUT touching the chapter's recorded engine / V3 'upgraded' status
        import delta_audit
        prev = ((delta_audit.load_registry().get("novels", {}).get(novel, {}).get("chapters", {})) or {}).get(str(ch)) or {}
        delta_audit.set_provenance(prev.get("engine") or "unknown", prev.get("model"), upgraded=bool(prev.get("upgraded")))
        delta_audit.mark_chapter(novel, ch)
    except Exception:
        pass
    notes.append(f"mechanics upgraded: {changed or 'nothing improved'}" + (f" (kept as they were: {kept})" if kept else ""))
    return {"before": before, "after": _mech_counts(rec)}


def upgrade_chapter(novel: str, ch: int, model: str, notes: list, flags: list = None) -> dict:
    """One chapter's upgrade. The V3 part (the original behaviour, targeted by flag or the full plan) and the mechanics part
    (isolated, one call per flagged field) are independent: a chapter whose V3 part is done only gets its mechanics fields."""
    flags = list(flags or [])
    mech_flags = [f for f in flags if f in MECH_FLAGS]
    v3_flags = _without_thin_when_localized([f for f in flags if f not in MECH_FLAGS])
    res = {"before": {}, "after": {}, "ran": {"v3": False, "mech": False}}
    if v3_flags or not flags:                    # no flags at all = an explicit run: the full V3 plan, as always
        r = _upgrade_chapter_v3(novel, ch, model, notes, v3_flags or None)
        res["before"].update(r["before"])
        res["after"].update(r["after"])
        res["ran"]["v3"] = True
    if mech_flags:
        r = _upgrade_mechanics(novel, ch, model, notes, mech_flags)
        res["before"].update(r["before"])
        res["after"].update(r["after"])
        res["ran"]["mech"] = True
    return res


def _upgrade_one(novel: str, ch: int, flags: list, model):
    """One chapter, with the usage-limit wait-and-retry. -> (result or None, notes, error or None)."""
    L.ensure_nemotron_slot()          # Nvidia: each worker thread keeps its own pooled key (no effect on other engines)
    _slot_start(novel, ch, flags, model)
    try:
        while True:
            notes: list = []
            try:
                return upgrade_chapter(novel, ch, model, notes, flags), notes, None
            except Exception as e:
                if _is_limit_error(e):     # wait and retry this chapter rather than failing every remaining one
                    _wait_out_limit("delta_upgrade", novel, f"ch{ch}", _engine_label(model))
                    continue
                return None, notes, str(e)[:200]
    finally:
        _slot_end(novel, ch)


def _pending_flags(n: str, c: int, f: list, state: dict, force: bool):
    """What is still to do for one chapter: its V3 flags (if its V3 part is not done) plus its mechanics flags (if not done).
    None = nothing. [] = the full V3 plan (an explicit run with no flags)."""
    ns = state.get(n) or {}
    mech = [x for x in f if x in MECH_FLAGS]
    v3 = [x for x in f if x not in MECH_FLAGS]
    if v3 and all(x in _LOW_FLAG_KEYS for x in v3) and c in ns.get("done", []):
        v3_todo = force or c not in ns.get("retry_done", [])         # second chance, field by field: once per chapter
    else:
        v3_todo = (bool(v3) or not f) and (force or c not in ns.get("done", []))
    mech_todo = bool(mech) and (force or c not in ns.get("mech_done", []))
    if not (v3_todo or mech_todo):
        return None
    return (v3 if v3_todo else []) + (mech if mech_todo else [])


def _upgrade_loop(targets: list, model, limit: int, force: bool, workers: int = 1):
    state = _load_state()
    todo = [(n, c, eff) for n, c, f in targets if (eff := _pending_flags(n, c, f, state, force)) is not None]
    if limit:
        todo = todo[:limit]
    print(f"Upgrading {len(todo)} chapter(s) with {_engine_label(model)}, {workers} at a time "
          f"({len(targets) - len(todo)} already done)", flush=True)

    t_start = time.time()
    n_done = n_finished = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for novel, ch, flags in todo:
            print(f"[{novel} ch{ch}] queued", flush=True)
            futures[pool.submit(_upgrade_one, novel, ch, flags, model)] = (novel, ch)
        for fut in as_completed(futures):
            novel, ch = futures[fut]
            res, notes, err = fut.result()
            with _STATE_LOCK:
                n_finished += 1
                ns = state.setdefault(novel, {"done": [], "failed": {}, "log": {}})
                _hist(f"{'FAILED' if res is None else 'done'} {novel} ch{ch} ({n_finished}/{len(todo)})")
                if res is None:
                    ns["failed"][str(ch)] = err or "failed"
                    _save_state(state)
                    print(f"\n[{novel} ch{ch}] FAILED: {err}", flush=True)
                    for n in notes:
                        print(f"  note: {n}", flush=True)
                    continue
                b, a = res["before"], res["after"]
                print(f"\n[{novel} ch{ch}] done  " + "  ".join(f"{k} {b[k]}->{a[k]}" for k in b), flush=True)
                for n in notes:
                    print(f"  note: {n}", flush=True)
                ns["log"][str(ch)] = {**res, "notes": notes, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
                ns["failed"].pop(str(ch), None)
                ran = res.get("ran") or {"v3": True}
                if ran.get("v3", True):
                    if ch in ns["done"]:
                        if ch not in ns.setdefault("retry_done", []):
                            ns["retry_done"].append(ch)      # the second chance for a chapter upgraded before: used
                    else:
                        ns["done"].append(ch)
                if ran.get("mech") and ch not in ns.setdefault("mech_done", []):
                    ns["mech_done"].append(ch)
                _save_state(state)
                n_done += 1
                el = time.time() - t_start
                remaining = len(todo) - n_finished
                print(f"  progress: {n_finished}/{len(todo)} ({n_done} upgraded) | "
                      f"about {el / n_finished * remaining / 60:.0f} min left", flush=True)
    print(f"\nDONE. {n_done} upgraded, {sum(len(v['failed']) for v in state.values())} failed in total.")


if __name__ == "__main__":
    main()
