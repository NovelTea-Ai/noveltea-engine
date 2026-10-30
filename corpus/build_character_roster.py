"""V4 Phase 6 Step 1 + 1.5 — zero-LLM character roster build, then semantic
enrichment. See PHASE6_CHARACTER_ROSTER.md for the full design writeup.

Step 1 (deterministic, no LLM, no embeddings): for every entities/*.json with
type == "character" across all 18 corpus novels, pull the already-extracted
structured data — facts[], voice_dna.dialogue_samples[], voice_dna's
speech_dna_history[] (discovered live while building this: a per-chapter
formality/verbosity/signature_phrases record, richer than dialogue_samples
alone) — plus a free-text name/alias sweep of that novel's reveals/schemes
for weaker "mentioned_in" context. Nothing here is invented; every field is
copied verbatim from data already on disk.

Step 1.5 (still zero LLM calls — local embeddings only): for each roster
character, query the existing knowledge_index.py semantic search with the
character's own name as an anchor (validated live: name-anchored queries are
highly precise; queries without a name return nothing usable — this is WHY
step 1.5 has to run after step 1, not standalone). This is what gives real
grounding to the 12 novels with zero character_dna files and to the many
characters that have facts but no voice_dna samples.

Output: corpus/character_roster/{novel_id}/{character_id}.json — a new
directory, parallel to character_dna/, so nothing existing is touched.

Usage:
    python build_character_roster.py                # all 18 novels
    python build_character_roster.py my_novel   # one novel
    python build_character_roster.py --no-semantic   # skip step 1.5 (fast, for testing step 1 alone)
"""
import json
import re
import sys
from pathlib import Path

from llm_client import write_live_status

NOVELS_DIR = Path(__file__).parent / "novels"
ROSTER_DIR = Path(__file__).parent / "character_roster"
CHARACTER_DNA_DIR = Path(__file__).parent / "character_dna"

# Score floor for semantic hits — validated live against a known character:
# genuinely-relevant hits scored >=0.65, unrelated novels/characters scored
# well below that. Not a formally tuned threshold, just what the live test
# showed as the visible cliff between "on topic" and "not."
SEMANTIC_SCORE_FLOOR = 0.65
SEMANTIC_TOP_K = 40  # generous — search() has no cap (confirmed live), filtered down by score floor after


def _dedupe_facts(facts: list) -> list:
    """Confirmed live: source entities/*.json files often carry the SAME fact
    repeated verbatim — not rare noise, a systematic pattern (a spot-check
    found clean integer-multiple clustering: 201 characters at exactly 2x
    duplication, 57 at 3x, 27 at 4x, 20 at 8x — the signature of an upstream
    extraction/merge pass re-appending the same records, not genuinely
    repeated in-story dialogue). Dedupe on the full fact tuple so a
    genuinely different fact with the same subject/predicate isn't
    conflated."""
    seen = set()
    out = []
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        key = (fact.get("subject"), fact.get("predicate"), fact.get("object"), fact.get("source_chapter"))
        if key in seen:
            continue
        seen.add(key)
        out.append(fact)
    return out


def _dedupe_voice_samples(samples: list) -> list:
    """Same upstream duplication pattern as facts (see _dedupe_facts) — plus
    a real key-shape inconsistency confirmed live: most novels use "line" for
    the quoted text, but my_novel and my_novel use "text"
    instead. Normalizes to "line" in the output so nothing downstream has to
    know about the inconsistency, and dedupes on the actual quoted text."""
    seen = set()
    out = []
    for s in samples:
        if not isinstance(s, dict):
            continue
        text = s.get("line") or s.get("text")
        if not text or text in seen:
            continue
        seen.add(text)
        out.append({**s, "line": text})
    return out


def _normalize_chapter(val):
    """source_chapter/chapter is USUALLY a bare int, but confirmed live
    (crashed the whole roster build on the very first novel,
    my_novel) that real corpus records also carry it
    as a numeric string ('98') or a prefixed string ('Chapter 93') —
    inconsistent across characters within the SAME novel, not one outlier
    file. Returns an int where a chapter number can be recovered, else None
    (rather than raising) so one malformed record doesn't crash the whole
    run — matches build_knowledge_index.py's _normalize_chapter's spirit for
    the list-vs-int version of this same class of problem."""
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        m = re.search(r"\d+", val)
        if m:
            return int(m.group())
    return None


def load_json(path: Path, default=None, warn_missing: bool = True):
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        if warn_missing:
            print(f"  WARN could not read {path.name}: {str(e)[:100]}")
        return default


def _curated_dna_lookup() -> dict:
    """character_id (file stem, minus the _<novelshort> suffix isn't reliable
    to guess, so instead this indexes by (novel_id, canonical_name-ish) —
    simplest robust key is novel_id read from inside each curated file, since
    all 8 existing files carry it."""
    out = {}
    if not CHARACTER_DNA_DIR.exists():
        return out
    for role_dir in CHARACTER_DNA_DIR.iterdir():
        if not role_dir.is_dir():
            continue
        for f in role_dir.glob("*.json"):
            d = load_json(f, {}) or {}
            nid = d.get("novel_id")
            cid = d.get("character_id")
            # A file build_character_dna.py wrote itself carries a _source_snapshot — that is MACHINE-built, not hand-
            # curated. This used to flag every existing file as curated, including the pipeline's own output, so once a
            # character was built it became "protected" and could never be rebuilt: the stale badge's Rebuild button did
            # nothing (235 machine-built characters were affected). Hand-curated originals have no snapshot and stay
            # protected. (Very early machine builds that predate the snapshot also stay protected — the safe direction.)
            if d.get("_source_snapshot"):
                continue
            if nid and cid:
                out[(nid, cid)] = role_dir.name
    return out


def _collect_mentions(novel_dir: Path, canonical_name: str, aliases: list) -> dict:
    """Free-text name/alias sweep of reveals + schemes — weaker signal than
    facts[]/voice_dna (those are structurally attributed; this is a string
    match on free-text content), kept in a separate field so nothing
    downstream conflates the two confidence levels."""
    names = [canonical_name] + list(aliases or [])
    names = [n for n in names if n and len(n) > 2]  # skip tiny/empty aliases, too noisy to match
    if not names:
        return {"reveals": [], "schemes": []}
    pattern = re.compile("|".join(re.escape(n) for n in names))

    reveals_hits = []
    reveals_path = novel_dir / "reveals" / "log.json"
    if reveals_path.exists():
        for r in load_json(reveals_path, []) or []:
            content = r.get("content", "") if isinstance(r, dict) else ""
            revealed_to = " ".join(r.get("revealed_to") or []) if isinstance(r, dict) else ""
            if pattern.search(content) or pattern.search(revealed_to):
                reveals_hits.append(r.get("id") or r.get("content", "")[:60])

    schemes_hits = []
    schemes_path = novel_dir / "schemes" / "instances.json"
    if schemes_path.exists():
        for s in load_json(schemes_path, []) or []:
            if not isinstance(s, dict):
                continue
            if s.get("schemer") in names or s.get("target") in names:
                schemes_hits.append({"schemer": s.get("schemer"), "target": s.get("target"),
                                     "goal": s.get("goal", "")[:100]})

    return {"reveals": reveals_hits, "schemes": schemes_hits}


def build_novel_roster(novel_id: str, curated_lookup: dict) -> list:
    novel_dir = NOVELS_DIR / novel_id
    entities_dir = novel_dir / "entities"
    if not entities_dir.exists():
        print(f"  {novel_id}: no entities/ dir, skipping")
        return []

    out_dir = ROSTER_DIR / novel_id
    out_dir.mkdir(parents=True, exist_ok=True)

    built = []
    for f in sorted(entities_dir.glob("*.json")):
        d = load_json(f, {}) or {}
        if not isinstance(d, dict) or d.get("type") != "character":
            continue

        character_id = f.stem
        canonical_name = d.get("canonical_name", character_id)
        aliases = d.get("aliases", []) or []
        facts = _dedupe_facts(d.get("facts", []) or [])
        voice_dna = d.get("voice_dna") or {}
        voice_samples = _dedupe_voice_samples(voice_dna.get("dialogue_samples") or [])
        speech_dna_history = voice_dna.get("speech_dna_history") or []

        chapters = [_normalize_chapter(fact.get("source_chapter")) for fact in facts if isinstance(fact, dict)]
        chapters += [_normalize_chapter(v.get("chapter")) for v in voice_samples if isinstance(v, dict)]
        chapters = [c for c in chapters if c is not None]
        chapter_range = [min(chapters), max(chapters)] if chapters else None

        curated_role = curated_lookup.get((novel_id, character_id))

        # Preserve prior semantic_enrichment across a re-run — step 1 always
        # re-derives facts/voice_samples/mentions fresh from entities/ (cheap,
        # and picks up any source-data edits), but step 1.5's embedding calls
        # are the expensive part, and enrich_with_semantic's own incremental
        # skip only works if this rebuild doesn't wipe what it already found.
        prior = load_json(out_dir / f"{character_id}.json", {}) or {}
        prior_enrichment = prior.get("semantic_enrichment") or []
        prior_attempted = bool(prior.get("enrichment_attempted"))

        entry = {
            "novel_id": novel_id,
            "character_id": character_id,
            "canonical_name": canonical_name,
            "aliases": aliases,
            "role": d.get("role"),
            "comedic_role": d.get("comedic_role"),
            "notes": d.get("notes"),
            "facts": facts,
            "voice_samples": voice_samples,
            "speech_dna_history": speech_dna_history,
            "mentioned_in": _collect_mentions(novel_dir, canonical_name, aliases),
            "semantic_enrichment": prior_enrichment,  # carried over — see comment above; step 1.5 fills it fresh only if empty/incremental=False
            "enrichment_attempted": prior_attempted,  # distinguishes "processed, found nothing above the score floor" from "not processed yet" — semantic_enrichment==[] is ambiguous between those two on its own (269/1350 characters legitimately fall in the first bucket)
            "has_curated_dna": curated_role is not None,
            "curated_dna_role": curated_role,
            "chapter_range": chapter_range,
        }
        mentioned = entry["mentioned_in"]
        entry["weight"] = (len(facts) + 3 * len(voice_samples) + 2 * len(prior_enrichment)
                           + len(mentioned["reveals"]) + len(mentioned["schemes"]))
        (out_dir / f"{character_id}.json").write_text(
            json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")
        built.append(entry)

    print(f"  {novel_id}: {len(built)} character(s) rostered "
          f"({sum(1 for c in built if c['voice_samples'])} with voice samples, "
          f"{sum(1 for c in built if c['has_curated_dna'])} with curated DNA)")
    return built


def enrich_with_semantic(novel_id: str, roster: list, incremental: bool = True):
    """Step 1.5 — name-anchored semantic search per character, still zero LLM
    calls. Imported lazily so `--no-semantic` runs don't need Ollama up.

    Incremental by default (matches build_knowledge_index.py's convention):
    a character already MARKED enrichment_attempted from a prior run is
    skipped entirely, so a restart/re-run doesn't re-pay the embedding-call
    cost for everyone already processed. Deliberately keyed on
    enrichment_attempted, NOT on semantic_enrichment being non-empty — a
    genuinely thin character (confirmed live: 269/1350 in the first full
    run) can be correctly processed and still find zero hits above the score
    floor; skipping only on a non-empty list would re-attempt those 269
    forever, on every run, silently re-paying embedding calls for characters
    that were never going to yield anything different. Pass
    incremental=False to force re-enrichment (e.g. after raising
    SEMANTIC_TOP_K or changing the score floor)."""
    from knowledge_index import search, ollama_available

    if not ollama_available():
        print(f"  {novel_id}: Ollama not reachable, skipping semantic enrichment for this novel")
        return

    out_dir = ROSTER_DIR / novel_id
    todo = [e for e in roster if not (incremental and e.get("enrichment_attempted"))]
    skipped = len(roster) - len(todo)
    if skipped:
        print(f"  {novel_id}: {skipped} character(s) already enriched, skipping")

    for i, entry in enumerate(todo):
        name = entry["canonical_name"]
        write_live_status("character_roster", novel=novel_id, character=name,
                          progress=f"{i + 1}/{len(todo)}")
        hits_by_key = {}
        for q in (f"{name} character personality and behavior", f"{name} dialogue and speech"):
            try:
                results = search(q, top_k=SEMANTIC_TOP_K)
            except Exception as e:
                print(f"    WARN semantic search failed for {name!r}: {str(e)[:100]}")
                continue
            for r in results:
                if r.get("novel_id") != novel_id:
                    continue
                if r.get("score", 0) < SEMANTIC_SCORE_FLOOR:
                    continue
                key = (r["category"], r["text"])  # dedupe across the two queries
                if key not in hits_by_key or r["score"] > hits_by_key[key]["score"]:
                    hits_by_key[key] = {"category": r["category"], "text": r["text"], "score": round(r["score"], 3)}

        enrichment = sorted(hits_by_key.values(), key=lambda h: -h["score"])
        entry["semantic_enrichment"] = enrichment
        entry["enrichment_attempted"] = True   # set regardless of hit count — see docstring above for why
        entry["weight"] = (len(entry["facts"]) + 3 * len(entry["voice_samples"]) + 2 * len(enrichment)
                           + len(entry["mentioned_in"]["reveals"]) + len(entry["mentioned_in"]["schemes"]))
        (out_dir / f"{entry['character_id']}.json").write_text(
            json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")

    n_attempted = sum(1 for e in roster if e.get("enrichment_attempted"))
    n_with_hits = sum(1 for e in roster if e["semantic_enrichment"])
    print(f"  {novel_id}: semantic enrichment processed for {n_attempted}/{len(roster)} character(s) "
          f"({n_with_hits} found at least one hit above the score floor)")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    no_semantic = "--no-semantic" in sys.argv

    novel_ids = args if args else sorted(
        p.name for p in NOVELS_DIR.iterdir()
        if p.is_dir() and (p / "entities").exists()
    )

    print(f"Building character roster for {len(novel_ids)} novel(s)"
          f"{' (semantic enrichment skipped)' if no_semantic else ''}...")
    curated_lookup = _curated_dna_lookup()
    print(f"  {len(curated_lookup)} character(s) already have curated character_dna/ files")

    total = 0
    for novel_id in novel_ids:
        roster = build_novel_roster(novel_id, curated_lookup)
        total += len(roster)
        if roster and not no_semantic:
            enrich_with_semantic(novel_id, roster)

    print(f"\nTOTAL: {total} character(s) rostered across {len(novel_ids)} novel(s)")
    print(f"Output: {ROSTER_DIR}")


if __name__ == "__main__":
    main()
