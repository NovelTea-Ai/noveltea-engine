"""V4 Phase 6 Step 3 — LLM genome build, per shortlisted roster character.
See PHASE6_CHARACTER_ROSTER.md's "Step 3" section for the full design.

Staged and resumable, mirroring corpus_builder.py's own pipeline shape
(convert -> extract -> merge -> genome, each stage checking real disk state
before acting, plus a pre-flight catch-up pass) rather than tracking progress
in a separate counter that can drift from reality:

  Stage A (draft):  one LLM call per shortlisted character, grounded in the
                     roster's already-extracted facts/voice_samples/
                     speech_dna_history/semantic_enrichment PLUS the actual
                     raw chapter text at every source_chapter the roster
                     cites for that character (corpus/raw/{novel}/ch{N}.txt)
                     -- not a fallback for thin characters, the standard input
                     for every build, same as _character_dna_block_for_shaping's
                     own principle of grounding in real material.
  Stage B (verify):  confirm the output file is valid JSON with the required
                     top-level keys for its role -- a malformed write from an
                     interrupted call is NOT marked done, stays eligible for
                     retry.

Save-state is the output file itself: character_dna/{role}/{character_id}_{novel_short}.json
existing AND passing Stage B verification means done. No separate progress
tracker -- resuming is just "check what's on disk," the same property
build_character_roster.py's enrichment_attempted flag already has.

Usage:
    python build_character_dna.py                        # top N per novel, all 18 (see build_roster_shortlist.py's N)
    python build_character_dna.py my_novel   # one novel's shortlist only
    python build_character_dna.py --char my_novel/hero_name  # exactly one character (testing)
    python build_character_dna.py --revalidate            # pre-flight only: verify existing outputs, report bad ones, exit
"""
import json
import os
import sys
import time
from pathlib import Path

# Line-buffer stdout so character_dna.log fills in as each character
# completes rather than sitting empty until the whole batch exits or the
# buffer fills — confirmed live: with the default block-buffering that
# happens when stdout is a redirected file (not a real terminal), the log
# stayed genuinely empty for 35+ seconds of real, successful progress. The
# live-status JSON (write_live_status) already shows the CURRENT call in
# real time, but the log file is the durable per-call history the author
# actually asked to see -- this makes it behave that way, not just in
# principle. Reconfigure rather than flush=True on every print() call.
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

from llm_client import call_llm, write_live_status, current_model_label
from extract_v3 import _parse_json_response

from build_roster_shortlist import load_roster, is_placeholder

ROSTER_DIR = Path(__file__).parent / "character_roster"
CHARACTER_DNA_DIR = Path(__file__).parent / "character_dna"
RAW_DIR = Path(__file__).parent / "raw"

SHORTLIST_N = 15  # matches build_roster_shortlist.py's default

# Required top-level keys per role shape -- confirmed live against the 8
# existing hand-curated files (hero_a.json for protagonist-shape,
# big_yellow_dmwg.json for sidekick-shape). A file missing any of these for
# its role fails Stage B verification.
_REQUIRED_KEYS = {
    "protagonist": {"personality_dna", "morality_dna", "competence_dna", "banter_dna",
                    "speech_dna", "emotional_dna", "identity_lock"},
    "deuteragonist": {"personality_dna", "morality_dna", "competence_dna", "banter_dna",
                      "speech_dna", "emotional_dna", "identity_lock"},
    "antagonist": {"personality_dna", "morality_dna", "competence_dna", "banter_dna",
                   "speech_dna", "emotional_dna", "identity_lock"},
    "mentor": {"personality_dna", "morality_dna", "competence_dna", "banter_dna",
               "speech_dna", "emotional_dna", "identity_lock"},
    "sidekick": {"personality_dna", "story_function", "humor_dna", "loyalty_dna"},
}
_GENERIC_REQUIRED = {"system_version", "character_id", "novel_id", "role", "character_name", "grounding"}


def _novel_short(novel_id: str) -> str:
    """Same abbreviation convention as the 8 existing files (dmwg, gof, uss,
    mg, xu_que_uss, lmgip) -- first letter of each underscore-separated word."""
    return "".join(w[0] for w in novel_id.split("_"))


def _map_role(roster_role: str) -> str:
    """Roster roles come straight from entities/*.json's own `role` field,
    which is free-text from the original extraction (confirmed live: values
    like 'minor_supporting' exist alongside 'protagonist'/'antagonist') --
    not guaranteed to be one of character_dna/'s five fixed role directories.
    Anything that doesn't map cleanly falls to sidekick, the lighter schema,
    rather than forcing a full protagonist-depth identity_lock onto a side
    character the extraction never called out as a lead."""
    r = (roster_role or "").lower()
    if "protagonist" in r and "de" not in r:
        return "protagonist"
    if "deuteragonist" in r:
        return "deuteragonist"
    if "antagonist" in r or "villain" in r:
        return "antagonist"
    if "mentor" in r:
        return "mentor"
    return "sidekick"


def _read_raw_chapter(novel_id: str, chapter: int) -> str:
    """corpus/raw/{novel_id}/ch{N}.txt -- confirmed live this path pattern
    exists and is populated for all 18 novels. Returns "" (not an error) if a
    specific chapter file is missing -- the roster's OTHER material still
    grounds the call, one missing raw file shouldn't abort the whole build."""
    p = RAW_DIR / novel_id / f"ch{chapter}.txt"
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _collect_chapters_to_read(entry: dict, max_chapters: int = 6) -> list:
    """Every chapter the roster cites for this character, most-frequently-
    cited first (a chapter appearing in 3 facts is more central to this
    character than one appearing in 1) -- capped so a very well-documented
    character (Wang Teng: 234 facts) doesn't try to stuff dozens of full
    chapters into one prompt."""
    from collections import Counter
    counts = Counter()
    for fact in entry.get("facts", []):
        ch = fact.get("source_chapter")
        if isinstance(ch, int):
            counts[ch] += 1
    for v in entry.get("voice_samples", []):
        ch = v.get("chapter")
        if isinstance(ch, int):
            counts[ch] += 2  # a chapter with a direct quote is stronger signal than a bare fact
    return [ch for ch, _ in counts.most_common(max_chapters)]


def _build_prompt(entry: dict, role_dir: str) -> tuple:
    novel_id = entry["novel_id"]
    name = entry["canonical_name"]
    chapters_to_read = _collect_chapters_to_read(entry)

    raw_blocks = []
    for ch in chapters_to_read:
        text = _read_raw_chapter(novel_id, ch)
        if text:
            raw_blocks.append(f"--- Chapter {ch} (raw text, {len(text)} chars) ---\n{text[:12000]}")
    raw_section = "\n\n".join(raw_blocks) if raw_blocks else "(no raw chapter text available for this character)"

    schema_note = (
        "protagonist-depth schema: personality_dna, morality_dna, competence_dna, banter_dna, "
        "speech_dna, emotional_dna, identity_lock (core_beliefs/core_motivations/core_personality_traits/"
        "generation_rules), consistency_tracker, attachment_sources, character_arc_dna"
        if role_dir != "sidekick" else
        "sidekick-depth schema: personality_dna, story_function, function_notes, humor_dna "
        "(style/frequency/signature_lines/comedy_mechanism), loyalty_dna, unique_value, generation_rules"
    )

    system = f"""You are building a structured character DNA file for "{name}" from "{novel_id}", matching \
NovelTea Engine's existing character_dna/ schema exactly (this is Phase 6 Step 3 of the roadmap -- see \
PHASE6_CHARACTER_ROSTER.md). You are extending an existing, hand-curated corpus of files with the SAME \
rigor -- not writing a generic template.

GROUNDING RULES (the whole point of this pass):
- Everything you write must be traceable to the ALREADY-EXTRACTED data below or the RAW CHAPTER TEXT \
provided -- do not invent plot events, relationships, or traits with no basis in what's given.
- Where the given material genuinely supports a specific, evidenced observation (a repeated behavior, an \
exact quote, a specific chapter event), write that -- match the specificity of NovelTea Engine's existing \
curated files (e.g. noting the ONE chapter where a character shows unusual emotion, not a vague "sometimes \
emotional").
- Where the material is thin, still fill every schema field (a plausible, internally-consistent read is \
better than a missing field) but set "grounding" honestly -- see below.
- {schema_note}.

Output ONLY this JSON (no commentary):
{{
  "system_version": "1.0",
  "character_id": "{entry['character_id']}",
  "novel_id": "{novel_id}",
  "role": "{role_dir}",
  "character_name": "{name}",
  "grounding": "strong" | "moderate" | "thin",
  ... (the full schema fields per the depth note above)
}}

"grounding" is YOUR OWN assessment: "strong" if the facts/quotes/raw chapters gave you real, specific, \
citable material for most fields; "moderate" if some fields are well-evidenced and others are reasonable \
inference from limited material; "thin" if you had to infer most of the personality/moral/speech shape from \
very little (few facts, few or no quotes, little raw text). Be honest -- this flag is what tells a human \
reviewer or a future UI whether to trust this file's specificity or treat it as a first-pass guess."""

    user = f"""ALREADY-EXTRACTED DATA for {name}:

Role (from corpus extraction): {entry.get('role') or '(not tagged)'}
Notes: {entry.get('notes') or '(none)'}

Facts ({len(entry['facts'])}):
{json.dumps(entry['facts'], ensure_ascii=False, indent=2)}

Voice samples ({len(entry['voice_samples'])}):
{json.dumps(entry['voice_samples'], ensure_ascii=False, indent=2)}

Speech DNA history:
{json.dumps(entry['speech_dna_history'], ensure_ascii=False, indent=2)}

Semantic enrichment (weaker signal -- corpus-wide search hits, verify against raw text before relying on these):
{json.dumps(entry['semantic_enrichment'], ensure_ascii=False, indent=2)}

RAW CHAPTER TEXT (the {len(chapters_to_read)} chapters most central to this character, per fact/quote frequency):
{raw_section}

Build the character DNA file now."""

    return system, user


def _verify(path: Path, role_dir: str) -> bool:
    """Stage B. A missing or unparsable file fails outright; a parsable file
    missing required keys for its role also fails -- both stay eligible for
    retry on the next run, matching corpus_builder.py's _verify_merge/
    _verify_genome pattern of 'don't trust that a write happened, check what
    it actually produced.'"""
    if not path.exists():
        return False
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(d, dict):
        return False
    required = _REQUIRED_KEYS.get(role_dir, _REQUIRED_KEYS["sidekick"]) | _GENERIC_REQUIRED
    return required.issubset(d.keys())


_POOL = None     # set by main() while the agents run


def build_one(entry: dict, force: bool = False) -> str:
    """Returns 'skipped' | 'built' | 'failed' | 'protected'.

    Second guard against overwriting a hand-curated file (see main()'s own
    queue-building filter for the first) — this one covers --char, which
    bypasses that filter entirely, and any future caller of build_one()
    directly. has_curated_dna is never bypassable via --force; force is for
    re-running a machine-built file that failed verification, not for
    overwriting a human's hand-curated work. Confirmed live this exact gap
    let a real batch overwrite hero_a.json and hero_b.json
    before this fix existed — restored from backup, not hypothetical."""
    if entry.get("has_curated_dna"):
        return "protected"

    novel_id = entry["novel_id"]
    character_id = entry["character_id"]
    role_dir = _map_role(entry.get("role"))
    out_dir = CHARACTER_DNA_DIR / role_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{character_id}_{_novel_short(novel_id)}.json"

    if not force and _verify(out_path, role_dir):
        return "skipped"

    name = entry["canonical_name"]
    chapters_to_read = _collect_chapters_to_read(entry)
    model_label = current_model_label()
    n_facts = len(entry.get("facts") or [])
    n_quotes = len(entry.get("voice_samples") or [])
    n_enrichment = len(entry.get("semantic_enrichment") or [])

    # Real per-call visibility into what's actually being sent, not just a
    # pass/fail line -- input volume (facts/quotes/enrichment/chapters), the
    # model actually resolved for THIS call (call_llm resolves per-chain, see
    # its own docstring, so this can differ call to call if Settings changes
    # or failover kicks in mid-batch), and timing. Printed to stdout (lands
    # in character_dna.log via the pipeline job's own redirect, same as every
    # other pipeline script's log), and the richer fields also go into
    # write_live_status so the Corpus Pipeline tab's "now processing" line
    # shows the same detail, not just a name. Plain ASCII only in print() --
    # confirmed live that a unicode arrow crashed EVERY call with
    # UnicodeEncodeError on Windows' cp1252 console codepage; none of the
    # other pipeline scripts (classify_thread_types.py etc.) use non-ASCII
    # symbols in their own print()s, for the same reason.
    print(f"  -> {novel_id}/{character_id} ({name}, role={role_dir}) "
          f"| input: {n_facts} facts, {n_quotes} quotes, {n_enrichment} enrichment hits, "
          f"reading ch.{chapters_to_read or '(none)'} "
          f"| model: {model_label}")

    if _POOL is not None:       # agent row on the card (see agent_pool.py)
        _POOL.step(f"writing {role_dir} DNA", f"{name}: {n_facts} facts, {n_quotes} quotes, reading ch.{chapters_to_read or '-'}")
    else:
        write_live_status("character_dna", novel=novel_id, character=name, role=role_dir,
                          model=model_label, facts=n_facts, quotes=n_quotes,
                          chapters_read=chapters_to_read)

    system, user = _build_prompt(entry, role_dir)
    t0 = time.time()
    try:
        raw = call_llm(system=system, user=user, max_tokens=8000, temperature=0.4)
        data = _parse_json_response(raw, label="character_dna_build")
    except Exception as e:
        print(f"    FAILED {novel_id}/{character_id} after {time.time()-t0:.1f}s: {str(e)[:150]}")
        return "failed"
    elapsed = time.time() - t0

    if not isinstance(data, dict):
        print(f"    FAILED {novel_id}/{character_id} after {elapsed:.1f}s: response was not a JSON object "
              f"(got {type(raw).__name__ if not isinstance(raw, str) else f'str, {len(raw)} chars'})")
        return "failed"

    # Snapshot of the input volume THIS build actually used — the only thing
    # that lets a later check answer "has the roster changed since this file
    # was built" (e.g. new chapters added the character to, via Corpus
    # Builder's auto-refresh of the roster -- see corpus_builder.py's
    # _notify_pipeline_new_data -- without a corresponding DNA rebuild).
    # Namespaced under one key, separate from the actual DNA content, so it
    # never interferes with _verify()'s required-keys check for the file's
    # role schema.
    data["_source_snapshot"] = {"facts": n_facts, "voice_samples": n_quotes,
                                "semantic_enrichment": n_enrichment, "built_at": time.strftime("%Y-%m-%d %H:%M:%S")}

    # Write to a TEMP file, verify THAT, and only then replace the real file. This used to write straight over the
    # existing file and verify afterwards, so when the model returned an incomplete object (a "failed" build) the
    # character's previous valid DNA had already been overwritten by a stub containing only _source_snapshot — a
    # failed Rebuild destroyed a good file (seen live on Xia Baichi and Huang Chang). Now a bad answer leaves the
    # existing file untouched; the rejected output is kept beside it as .rejected.txt (not *.json, so no scan
    # mistakes it for a DNA file) for inspection.
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    if not _verify(tmp_path, role_dir):
        missing = (_REQUIRED_KEYS.get(role_dir, _REQUIRED_KEYS["sidekick"]) | _GENERIC_REQUIRED) - set(data.keys())
        rejected = out_path.with_name(out_path.stem + ".rejected.txt")
        os.replace(tmp_path, rejected)
        kept = "the existing file was left untouched" if out_path.exists() else "no file written"
        print(f"    FAILED {novel_id}/{character_id} after {elapsed:.1f}s: the model's output is missing "
              f"required key(s) {sorted(missing)} for role={role_dir} -- {kept}; rejected output saved as {rejected.name}; "
              f"will retry next run")
        return "failed"
    os.replace(tmp_path, out_path)

    grounding = data.get("grounding", "?")
    print(f"    built {novel_id}/{character_id} in {elapsed:.1f}s | grounding: {grounding}")
    return "built"


def revalidate():
    """Pre-flight, mirroring _catchup_unfinished: check every EXISTING
    machine-built file (not the hand-curated 8) actually still passes Stage B
    -- catches a corrupted/truncated write from a prior crash without
    re-running the whole shortlist."""
    print("Revalidating existing character_dna/ outputs...")
    bad = []
    for role_dir_path in CHARACTER_DNA_DIR.iterdir():
        if not role_dir_path.is_dir():
            continue
        role_dir = role_dir_path.name
        if role_dir not in _REQUIRED_KEYS:
            continue
        for f in role_dir_path.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                bad.append(f)
                continue
            if not isinstance(d, dict) or "grounding" not in d:
                continue  # one of the 8 original hand-curated files (no "grounding" field) -- not this pipeline's output, skip
            if not _verify(f, role_dir):
                bad.append(f)
    if bad:
        print(f"  {len(bad)} malformed file(s) found -- will be rebuilt on next run:")
        for f in bad:
            print(f"    {f.relative_to(CHARACTER_DNA_DIR)}")
    else:
        print("  all machine-built outputs verified clean")
    return bad


def main():
    if "--revalidate" in sys.argv:
        revalidate()
        return

    force = "--force" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    # pre-flight, always -- a crashed prior run's partial write shouldn't
    # silently count as "done" just because the file exists
    revalidate()

    if "--char" in sys.argv:
        target = args[args.index("--char") + 1] if "--char" in args else sys.argv[sys.argv.index("--char") + 1]
        novel_id, character_id = target.split("/")
        entry = json.loads((ROSTER_DIR / novel_id / f"{character_id}.json").read_text(encoding="utf-8"))
        result = build_one(entry, force=force)
        print(f"{novel_id}/{character_id}: {result}")
        return

    by_novel = load_roster()
    novel_ids = args if args else sorted(by_novel.keys())

    # Round-robin, matching classify_thread_types.py's _build_batch_queue —
    # one character per novel per round, not one novel fully exhausted
    # before the next starts. Same stated reason applies here (see that
    # function's docstring): if the process dies or is stopped mid-run
    # (confirmed live: a real Stop click left my_novel
    # at 2/15 and every OTHER novel at 0/15, purely because it was first
    # alphabetically — an artifact of iteration order, not actual priority),
    # progress should be spread evenly across every novel instead of one
    # novel finished and seventeen untouched.
    queues = {}
    for novel_id in novel_ids:
        chars = by_novel.get(novel_id, [])
        # Confirmed live as a REAL bug (not hypothetical): has_curated_dna was
        # captured in the roster and described in the design doc as excluding
        # the 8 hand-curated files, but that exclusion was never actually
        # implemented here — a real batch run overwrote hero_a.json
        # and hero_b.json (both high-weight protagonists, both curated)
        # before this fix. Restored from a local backup; this filter is what
        # stops it happening again. See also build_one()'s own guard below —
        # belt and suspenders, since --char bypasses this shortlist filter.
        chars = [c for c in chars if not c.get("has_curated_dna")]
        shortlist = sorted(chars, key=lambda c: -c["weight"])[:SHORTLIST_N]
        shortlist = [c for c in shortlist if not is_placeholder(c["canonical_name"])]
        if shortlist:
            queues[novel_id] = shortlist
    total_shortlisted = sum(len(q) for q in queues.values())
    print(f"{len(queues)} novel(s), {total_shortlisted} character(s) shortlisted total (round-robin order)")

    # Same agent method as Chapter Mechanics: one agent per Nvidia key, characters dealt round-robin across novels.
    global _POOL
    from agent_pool import AgentPool
    _POOL = AgentPool("character_dna", model=current_model_label(None), want=4)
    items = [{"novel": nid, "unit": e["canonical_name"], "entry": e} for nid, q in queues.items() for e in q]
    counts = {"built": 0, "skipped": 0, "protected": 0, "failed": 0}

    def work(it):
        result = build_one(it["entry"], force=force)
        counts[result if result in counts else "failed"] += 1
        if result == "built":
            print(f"  [{it['novel']}] {it['entry']['canonical_name']}: built")
        return result

    _POOL.run(items, work)
    total_built, total_skipped = counts["built"], counts["skipped"]
    total_protected, total_failed = counts["protected"], counts["failed"]

    print(f"\nTOTAL: {total_built} built, {total_skipped} already done, "
          f"{total_protected} protected (hand-curated, skipped), {total_failed} failed")


if __name__ == "__main__":
    main()
