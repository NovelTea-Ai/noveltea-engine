import json
import threading
import os
import re as _re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from config import NOVELS_PATH, CHARACTER_DNA_PATH, CORPUS_PATH

router = APIRouter()


def read_json(path: Path):
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@router.get("/stats")
def corpus_stats():
    """Global corpus statistics for the dashboard."""
    registry = read_json(NOVELS_PATH / "registry.json")
    if not registry:
        return {"novels": 0, "chapters": 0, "patterns": 0, "characters": 0, "arcs": 0}

    novels = registry.get("novels", [])
    total_chapters = sum(_extracted_chapters(n.get("id", ""))[0] or n.get("chapters_extracted", 0) for n in novels)
    total_patterns = 0
    total_chars = 0
    total_arcs = 0

    for novel in novels:
        novel_dir = NOVELS_PATH / novel["id"]
        genome = read_json(novel_dir / "narrative_genome.json")
        if genome:
            patterns = genome.get("patterns", genome) if isinstance(genome, dict) else []
            if isinstance(genome, list):
                total_patterns += len(genome)
            elif isinstance(genome, dict):
                total_patterns += len(genome.get("patterns", []))

        entities_dir = novel_dir / "entities"
        if entities_dir.exists():
            total_chars += sum(1 for f in entities_dir.glob("*.json") if not f.stem.startswith("chapter_"))

        arcs = read_json(novel_dir / "timeline" / "arcs.json")
        if arcs:
            total_arcs += len(arcs) if isinstance(arcs, list) else 0

    dna_dir = CHARACTER_DNA_PATH / "protagonist"
    dna_count = len(list(dna_dir.glob("*.json"))) if dna_dir.exists() else 0

    return {
        "novels": len(novels),
        "chapters": total_chapters,
        "patterns": total_patterns,
        "characters": total_chars,
        "arcs": total_arcs,
        "character_dna": dna_count,
    }


_CH_JSON = _re.compile(r"^ch(\d+)\.json$")


def _extracted_chapters(novel_id: str) -> tuple:
    """(how many chapters are really extracted, the highest chapter number among them): the plain chN.json files in
    deltas_v3 (engine-comparison and backup copies like ch3.haiku45-original.json are not chapters). The registry file
    used to store only the highest number as 'chapters extracted', which read 5,105 for a novel with 234 chapters."""
    d = NOVELS_PATH / novel_id / "deltas_v3"
    nums = []
    try:
        for name in os.listdir(d):
            m = _CH_JSON.match(name)
            if m:
                nums.append(int(m.group(1)))
    except OSError:
        pass
    return len(nums), (max(nums) if nums else 0)


@router.get("/registry")
def get_registry():
    registry = read_json(NOVELS_PATH / "registry.json")
    if not registry:
        # a fresh corpus has no registry yet: list whatever novel folders exist (none at first)
        registry = {"novels": [{"id": d.name, "title": d.name.replace("_", " ").title(), "directory": f"novels/{d.name}", "status": "active"}
                               for d in sorted(NOVELS_PATH.iterdir()) if d.is_dir()] if NOVELS_PATH.exists() else []}
    for n in registry.get("novels", []):          # the true count, always (not whatever the merge step last wrote)
        count, highest = _extracted_chapters(n.get("id", ""))
        if count:
            n["chapters_extracted"], n["highest_chapter_extracted"] = count, highest
    return registry


# ── CHARACTER DNA PICKER — V4 Phase 6 (PHASE6_CHARACTER_DNA_PICKER.md) ─────
# Flattens whatever character_dna/{role}/*.json shape a given file actually
# has into the FOUR fields the project's own Character tab already carries
# (personality_traits, core_belief, speech_style, banter_style) — the picker
# UI never needs to know the corpus schema's internal shape, only these four
# buckets. Confirmed live across real files that at least THREE distinct
# shapes exist for the same logical content (hand-curated numeric-axis dict,
# hand-curated flat string list, and a machine-built structured
# {trait,description,evidence,chapters} list) — every extractor below is
# written defensively (isinstance checks before indexing) rather than
# assuming any one shape, since a future build could easily introduce a
# fourth.

_CDNA_NULLISH = {"none", "never", "n/a", "na", "null", "unknown", ""}


def _cdna_str(val) -> str:
    """Coerce a value that MIGHT be a plain string into one, else ''.
    Confirmed live: a real file's humor_dna.style was literally the string
    "none" (a character with no banter) — a plain truthiness/isinstance
    check treats that as a real trait, offering '[+ Add] none' as a clickable
    row. Filters those out here so every caller gets the same treatment for
    free, rather than re-deriving this per extractor."""
    if not isinstance(val, str):
        return ""
    v = val.strip()
    return v if v and v.lower() not in _CDNA_NULLISH else ""


def _cdna_personality_traits(d: dict) -> list:
    """Returns [{"label": ..., "evidence": ...}, ...]."""
    out = []
    pdna = d.get("personality_dna")

    # Shape 1 (machine-built "strong"): core_traits[] of structured objects.
    if isinstance(pdna, dict) and isinstance(pdna.get("core_traits"), list):
        for item in pdna["core_traits"]:
            if isinstance(item, dict) and _cdna_str(item.get("trait")):
                out.append({"label": item["trait"], "evidence": _cdna_str(item.get("evidence")) or _cdna_str(item.get("description"))})
            elif isinstance(item, str) and item.strip():
                out.append({"label": item, "evidence": ""})
    if out:
        return out

    # Shape 2 (hand-curated protagonist): identity_lock.core_personality_traits[].
    identity = d.get("identity_lock")
    if isinstance(identity, dict) and isinstance(identity.get("core_personality_traits"), list):
        for t in identity["core_personality_traits"]:
            if isinstance(t, str) and t.strip():
                out.append({"label": t, "evidence": ""})
    if out:
        return out

    # Shape 3: personality_dna as a flat numeric-axis dict — surface high-scoring axes.
    if isinstance(pdna, dict):
        for k, v in pdna.items():
            if isinstance(v, (int, float)) and v >= 80:
                out.append({"label": f"{k}: high ({v})", "evidence": _cdna_str(pdna.get("notes"))})
    if out:
        return out

    # Shape 4 (sidekick-shape fallback): story_function as a plain list.
    sf = d.get("story_function")
    if isinstance(sf, list):
        for f in sf:
            if isinstance(f, str) and f.strip():
                out.append({"label": f, "evidence": _cdna_str(d.get("function_notes"))})
    return out


def _cdna_core_belief(d: dict) -> dict | None:
    identity = d.get("identity_lock")
    if isinstance(identity, dict) and isinstance(identity.get("core_beliefs"), list) and identity["core_beliefs"]:
        first = identity["core_beliefs"][0]
        if isinstance(first, str) and first.strip():
            return {"label": first, "evidence": ""}

    pdna = d.get("personality_dna")
    if isinstance(pdna, dict):
        worldview = _cdna_str(pdna.get("worldview"))
        if worldview:
            return {"label": worldview, "evidence": ""}

    mdna = d.get("morality_dna")
    if isinstance(mdna, dict):
        notes = _cdna_str(mdna.get("notes"))
        if notes:
            return {"label": notes, "evidence": ""}

    fn = _cdna_str(d.get("function_notes"))
    if fn:
        return {"label": fn[:200], "evidence": ""}
    return None


def _cdna_speech_style(d: dict) -> dict | None:
    sdna = d.get("speech_dna")
    if isinstance(sdna, dict):
        vocab = _cdna_str(sdna.get("vocabulary"))
        length = _cdna_str(sdna.get("sentence_length"))
        label = ", ".join(p for p in (vocab, length) if p)
        if label:
            examples = sdna.get("signature_expressions")
            evidence = " / ".join(f'"{e}"' for e in examples if isinstance(e, str)) if isinstance(examples, list) else ""
            return {"label": label, "evidence": evidence}

    rules = d.get("generation_rules")
    if isinstance(rules, dict):
        patterns = rules.get("speech_patterns")
        if isinstance(patterns, dict):
            default = _cdna_str(patterns.get("default_register"))
            if default:
                extra = [f"{k}: {v}" for k, v in patterns.items()
                        if k != "default_register" and isinstance(v, str) and v.strip()]
                return {"label": default, "evidence": " / ".join(extra[:2])}
    return None


def _cdna_str_from_list(val) -> str:
    """First non-nullish string in a list, or '' — used wherever a field
    might be either a list[str] or a bare str (confirmed live: humor_dna.style
    is a list in some builds, a plain string in others)."""
    if isinstance(val, list):
        for item in val:
            s = _cdna_str(item)
            if s:
                return s
        return ""
    return _cdna_str(val)


def _cdna_banter_style(d: dict) -> dict | None:
    bdna = d.get("banter_dna")
    if isinstance(bdna, dict):
        label = _cdna_str_from_list(bdna.get("style"))
        if label:
            evidence = _cdna_str_from_list(bdna.get("signature_patterns"))
            return {"label": label, "evidence": evidence}

    hdna = d.get("humor_dna")
    if isinstance(hdna, dict):
        label = _cdna_str_from_list(hdna.get("style"))
        if label:
            evidence = _cdna_str_from_list(hdna.get("signature_lines")) or _cdna_str(hdna.get("comedy_mechanism"))
            return {"label": label, "evidence": evidence}
    return None


def _character_dna_to_traits(d: dict) -> list:
    """Flattens one character_dna file into the picker's traits[] contract —
    each item tagged with WHICH of the four project fields it targets."""
    traits = []
    for field, extractor in (
        ("personality_traits", None),  # handled separately below (multi-value)
        ("core_belief", _cdna_core_belief),
        ("speech_style", _cdna_speech_style),
        ("banter_style", _cdna_banter_style),
    ):
        if extractor is None:
            continue
        result = extractor(d)
        if result:
            traits.append({"field": field, "label": result["label"], "evidence": result["evidence"]})
    for pt in _cdna_personality_traits(d):
        traits.append({"field": "personality_traits", "label": pt["label"], "evidence": pt["evidence"]})
    return traits


@router.get("/character-dna")
def list_character_dna(role: Optional[str] = None, novel_id: Optional[str] = None):
    """Read-only — character_dna/ is corpus data, never written to by the app
    (mirrors novels.py's own read-only invariant for the corpus). Powers the
    Character DNA Picker (PHASE6_CHARACTER_DNA_PICKER.md): every corpus
    character with a DNA file, grouped by role, each pre-flattened into the
    picker's traits[] contract so the frontend never needs to know which of
    the (confirmed: at least three) underlying schema shapes a given file
    actually uses."""
    roles = [role] if role else ["protagonist", "deuteragonist", "sidekick", "mentor", "antagonist"]
    out = []
    for r in roles:
        role_dir = CHARACTER_DNA_PATH / r
        if not role_dir.exists():
            continue
        for f in sorted(role_dir.glob("*.json")):
            d = read_json(f)
            if not isinstance(d, dict):
                continue
            if novel_id and d.get("novel_id") != novel_id:
                continue
            out.append({
                "character_id": d.get("character_id", f.stem),
                "character_name": d.get("character_name", f.stem),
                "novel_id": d.get("novel_id"),
                "role": r,
                "archetype": d.get("archetype") or d.get("story_function") if isinstance(d.get("story_function"), str) else d.get("archetype"),
                "grounding": d.get("grounding"),  # None for the 8 hand-curated files (no such field), else the LLM's own self-assessment
                "traits": _character_dna_to_traits(d),
            })
    return {"characters": out}


# ── STALE CHARACTER REBUILD — one-click, per-character ──────────────────────
# The Corpus Pipeline tab's "N stale" badge (see _character_dna_is_stale) was
# a notification with no action behind it — acting on it meant a manual
# `--char novel/id --force` terminal command. This is that action, as a
# button. A single character's LLM call takes up to ~90s (confirmed live),
# too slow to block an HTTP request on — same class of problem the rest of
# this session's timeout-chasing was about — so it's backgrounded via a
# thread + a small in-memory job dict, polled the same way
# corpus_builder.py's own `_jobs`/`job_status` already works, just scoped to
# this one narrow use rather than importing that whole machinery.
_dna_rebuild_jobs: dict = {}


def _run_dna_rebuild(rebuild_id: str, novel_id: str, character_id: str):
    job = _dna_rebuild_jobs[rebuild_id]
    job["status"] = "running"
    python_exe = shutil.which("python")
    if not python_exe:
        job["status"] = "error"
        job["error"] = "No system python.exe found on PATH."
        return
    try:
        # Confirmed live: a single character normally takes ~20-90s, but the
        # SAME call took 230s while the character_dna batch job was also
        # running (both compete for the same LLM endpoint) — 300s left no
        # real margin. 600s gives headroom for that contention without
        # masking a genuinely wedged call for many minutes.
        result = subprocess.run(
            [python_exe, str(CORPUS_PATH / "build_character_dna.py"),
             "--char", f"{novel_id}/{character_id}", "--force"],
            cwd=str(CORPUS_PATH), capture_output=True, text=True, timeout=600)
        job["stdout"] = result.stdout[-2000:]
        job["stderr"] = result.stderr[-2000:]
        # build_character_dna.py's --char path prints exactly one final line:
        # "{novel}/{character}: {result}" where result is built/skipped/failed/protected.
        outcome = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        job["outcome"] = outcome.split(":")[-1].strip() if ":" in outcome else None
        job["status"] = "done" if result.returncode == 0 else "error"
        if result.returncode != 0:
            job["error"] = (result.stderr or result.stdout)[-500:]
    except subprocess.TimeoutExpired:
        job["status"] = "error"
        job["error"] = "Rebuild timed out after 600s."
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)[:300]
    job["finished_at"] = time.time()


class CharacterDnaRebuildRequest(BaseModel):
    novel_id: str
    character_id: str


@router.post("/character-dna-rebuild")
def character_dna_rebuild(req: CharacterDnaRebuildRequest):
    """Kick off a single-character rebuild (--force, so it overwrites even a
    currently-valid file — this endpoint is only ever reached from the
    stale-badge action, so overwriting IS the point). Never targets a
    hand-curated file: build_one()'s own has_curated_dna guard (see
    build_character_dna.py) protects that regardless of what's passed here,
    the same protection that stopped a real accidental overwrite earlier —
    this endpoint doesn't duplicate that check, it relies on it."""
    import threading
    rebuild_id = f"{req.novel_id}/{req.character_id}/{int(time.time()*1000)}"
    _dna_rebuild_jobs[rebuild_id] = {
        "status": "queued", "novel_id": req.novel_id, "character_id": req.character_id,
        "started_at": time.time(), "outcome": None, "error": None,
    }
    t = threading.Thread(target=_run_dna_rebuild, args=(rebuild_id, req.novel_id, req.character_id), daemon=True)
    t.start()
    return {"ok": True, "rebuild_id": rebuild_id}


@router.get("/character-dna-rebuild-status")
def character_dna_rebuild_status(rebuild_id: str):
    job = _dna_rebuild_jobs.get(rebuild_id)
    if not job:
        raise HTTPException(404, "Rebuild job not found — it may have finished and been cleared, or the id is wrong.")
    return job


@router.get("/{novel_id}/metadata")
def get_metadata(novel_id: str):
    data = read_json(NOVELS_PATH / novel_id / "novel_metadata.json")
    if not data:
        raise HTTPException(404, f"Metadata not found for {novel_id}")
    return data


@router.get("/{novel_id}/arcs")
def get_arcs(novel_id: str):
    data = read_json(NOVELS_PATH / novel_id / "timeline" / "arcs.json")
    if data is None:
        raise HTTPException(404, "Arcs not found")
    return data


@router.get("/{novel_id}/reader_psychology")
def get_reader_psychology(novel_id: str):
    data = read_json(NOVELS_PATH / novel_id / "reader_psychology" / "chapters.json")
    if data is None:
        raise HTTPException(404, "Reader psychology not found")
    return data


@router.get("/{novel_id}/patterns")
def get_patterns(novel_id: str):
    data = read_json(NOVELS_PATH / novel_id / "narrative_genome.json")
    if data is None:
        return []
    if isinstance(data, list):
        return data
    return data.get("patterns", [])


@router.get("/{novel_id}/schemes")
def get_schemes(novel_id: str):
    data = read_json(NOVELS_PATH / novel_id / "schemes" / "instances.json")
    return data or []


@router.get("/{novel_id}/knowledge_state")
def get_knowledge_state(novel_id: str):
    data = read_json(NOVELS_PATH / novel_id / "knowledge" / "state.json")
    return data or []


@router.get("/{novel_id}/humor")
def get_humor(novel_id: str):
    data = read_json(NOVELS_PATH / novel_id / "humor" / "instances.json")
    return data or []


@router.get("/{novel_id}/entities")
def get_entities(novel_id: str):
    entities_dir = NOVELS_PATH / novel_id / "entities"
    if not entities_dir.exists():
        return []
    entities = []
    real_files = sorted(f for f in entities_dir.glob("*.json") if not f.stem.startswith("chapter_"))
    for f in real_files[:100]:
        data = read_json(f)
        if data:
            entities.append({
                "id": f.stem,
                "canonical_name": data.get("canonical_name", f.stem),
                "type": data.get("type", "unknown"),
                "role": data.get("role", ""),
                "comedic_role": data.get("comedic_role", ""),
                "appearances": len(data.get("appearances", [])),
                "aliases": data.get("aliases", [])[:3],
            })
    return entities


@router.get("/{novel_id}/entity/{entity_id}")
def get_entity(novel_id: str, entity_id: str):
    data = read_json(NOVELS_PATH / novel_id / "entities" / f"{entity_id}.json")
    if not data:
        raise HTTPException(404, f"Entity {entity_id} not found")
    return data


@router.get("/{novel_id}/timeline")
def get_timeline(novel_id: str):
    data = read_json(NOVELS_PATH / novel_id / "timeline" / "events.json")
    return data or []


@router.get("/{novel_id}/reveals")
def get_reveals(novel_id: str):
    data = read_json(NOVELS_PATH / novel_id / "reveals" / "log.json")
    return data or []


# ── CORPUS PIPELINE — long-running background classification jobs ──────────
# Thread Typing (V4 Phase 2) and Symbol Filtering (V4 Phase 3) are cheap
# LLM classification passes over already-extracted corpus records, run as
# detached OS processes (corpus/classify_thread_types.py,
# corpus/filter_symbols_llm.py) since a full corpus pass takes hours.
#
# Launched via WMI Win32_Process.Create rather than subprocess.Popen —
# confirmed live that a plain detached child (even via Start-Process/
# subprocess with no window) gets reaped once its launching shell/tool-call
# exits; a WMI-created process is parented to a system service (WmiPrvSE.exe)
# instead, which survives independently of this backend and any shell that
# triggered the restart.

_PIPELINE_JOBS = {
    "thread_typing": {"script": "classify_thread_types.py", "label": "Thread Typing"},
    "symbol_filtering": {"script": "filter_symbols_llm.py", "label": "Symbol Filtering"},
    "knowledge_index": {"script": "build_knowledge_index.py", "label": "Knowledge Index"},
    # Every corpus humor beat (setup → payoff) embedded as the opt-in "humor"
    # category, for the project Humor tab's corpus gag search.
    "humor_index": {"script": "build_humor_index.py", "label": "Humor Index (nomic)"},
    "character_roster": {"script": "build_character_roster.py", "label": "Character Roster"},
    "character_dna": {"script": "build_character_dna.py", "label": "Character DNA (LLM)"},
    "blueprint_index": {"script": "build_blueprint_index.py", "label": "Blueprint Index"},
    "project_systems_index": {"script": "build_project_systems_index.py", "label": "Project Systems Index"},
    "narrative_genome": {"script": "generate_genome.py", "label": "Narrative Genome (LLM)"},
    "rolling_summary": {"script": "update_rolling_summary.py", "label": "Rolling Summary (LLM)"},
    # The author's brain: how each novel's author planned it (arcs, the long secrets with seed -> clue -> reveal timing, milestones,
    # the author's rules and conspiracy craft). Python + local semantic search build the skeleton (seconds), then Claude Code
    # (your subscription accounts) greps the summaries and runs the filtered knowledge search to write the author's notes (~2 min
    # per novel). Read by the Arc planner, Conspiracy and Timeline. Needs numpy: runs under the Python that has it (py -3.12).
    "author_brain": {"script": "author_brain_claude.py", "label": "Author Brain (Claude + semantic)",
                     "python": str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python312" / "python.exe")},
    # Re-runs the 4-part extraction (engine/model = whatever is selected in the app) on chapters a faster model already
    # extracted, with the existing extraction in the prompt (fix / add, not redo). Targets come
    # from upgrade_deltas_config.json; originals are kept as chNN.haiku45-original.json.
    "delta_upgrade": {"script": "upgrade_deltas.py", "label": "Delta Upgrade"},
    # For chapters whose important fields are empty with nobody having ruled on it: ask Sonnet once, per chapter,
    # "extract it, or say none" — fills the field or records it as genuinely empty (delta confirmed_empty).
    "empty_check": {"script": "resolve_empties.py", "label": "Empty-field Check"},
    # Fills the chapter into indexed chunks whose merged source file lost it (prose, dialogue, humor, reveals), read
    # from the per-chapter extractions (deltas_v3/chN.json); no re-embedding, only the chapter column changes.
    "index_chapters": {"script": "backfill_index_chapters.py", "label": "Index Chapters"},
    # How each extracted chapter is BUILT (beats, scene joins, opening/ending, fight talk, set-piece runs): free Python
    # measurements + nomic-targeted context, then one AI call per chapter (the app's selected engine). Writes novels/<id>/deltas_mechanics/chN.json + set_pieces/runs.json; indexes the opt-in
    # "mechanics" category.
    "mechanics_delta": {"script": "build_mechanics_deltas.py", "label": "Chapter Mechanics Delta (LLM)"},
    # Second embedding per indexed chunk from the corpus-fine-tuned model; search merges it
    # with the base model's. Resumable (only fills chunks still missing one).
    "tuned_embeddings": {"script": "backfill_tuned_embeddings.py", "label": "Tuned Embeddings"},
    # Fine-tunes the retrieval embedding model on the corpus (embedding_ft/). Runs
    # under its OWN venv (torch + sentence-transformers) — deliberately not the
    # system Python that builds this exe. Resumes from checkpoints automatically.
    "embedding_finetune": {
        "script": "embedding_ft\\train.py",
        "label": "Embedding Fine-Tune",
        "python": str(Path(os.environ.get("LOCALAPPDATA", "")) / "nm_ft" / "venv" / "Scripts" / "python.exe"),
        "args": ["--out", str(Path(os.environ.get("LOCALAPPDATA", "")) / "nm_ft" / "run1"), "--save-steps", "50"],
    },
}
_EMBEDDING_FT_PROGRESS = Path(os.environ.get("LOCALAPPDATA", "")) / "nm_ft" / "progress.json"

# Shared TTL cache for the *_progress() functions below. Confirmed live: with
# the corpus at its current size (thousands of records per novel across 18
# novels), several of these functions individually cost multiple seconds —
# re-walking and JSON-parsing hundreds/thousands of files just to recompute
# counts that only change when a pipeline job or Corpus Builder extraction
# actually runs, never between one 6s pipeline-status poll (see
# CorpusPipelinePage.jsx) and the next. Uncached, the combined cost of all
# five functions made single requests take 8-19s, and because uvicorn here
# runs with its default single worker, overlapping polls queued up rather
# than running in parallel — confirmed live: 3 concurrent requests each took
# ~19s, completing serially, which is what actually broke page load, not any
# one slow response alone. A short TTL is the right tool: staleness up to the
# TTL window is completely fine for a progress bar, unlike e.g. the search
# index which needs to reflect true content on every query.
_PROGRESS_CACHE_TTL = 30  # seconds
_progress_cache: dict = {}  # key -> {"ts": float, "value": Any}


def _cached_progress(key: str, compute):
    now = time.time()
    entry = _progress_cache.get(key)
    if entry is not None and (now - entry["ts"]) < _PROGRESS_CACHE_TTL:
        return entry["value"]
    value = compute()
    _progress_cache[key] = {"ts": now, "value": value}
    return value


def _invalidate_progress_cache(key: str):
    """Drop one cached entry so the NEXT read recomputes instead of serving
    up to _PROGRESS_CACHE_TTL (30s) of stale data. Used after Stop/Restart —
    those calls already pay for a fresh, uncached WMI query internally (see
    _running_pipeline_pid's fresh=True path) to decide what to do, but the
    pipeline-status DISPLAY path (what the frontend re-fetches right after)
    reads the SEPARATE cached "wmi_python_processes" key, which the fresh
    query never touches — without this, a Stop/Restart click's own fresh
    data goes to waste and the UI could still show the pre-change state for
    up to 30 more seconds despite the action having genuinely completed."""
    _progress_cache.pop(key, None)


def _thread_typing_progress() -> list:
    return _cached_progress("thread_typing", _compute_thread_typing_progress)


def _compute_thread_typing_progress() -> list:
    rows = []
    for nd in sorted(NOVELS_PATH.iterdir()) if NOVELS_PATH.exists() else []:
        if not nd.is_dir():
            continue
        total = done = 0
        for fname in ("reveals/log.json", "schemes/instances.json", "knowledge/state.json"):
            recs = read_json(nd / fname)
            if isinstance(recs, list):
                for r in recs:
                    if isinstance(r, dict):
                        total += 1
                        if r.get("thread_type"):
                            done += 1
        if total:
            rows.append({"novel_id": nd.name, "done": done, "total": total})
    return rows


def _knowledge_index_normalize_chapter(val):
    """Mirrors build_knowledge_index.py's _normalize_chapter exactly — some
    corpus records store setup_chapters as a bare int instead of a list."""
    if isinstance(val, list):
        return val[0] if val else None
    return val


def _knowledge_index_expected_chunks(novel_dir: Path) -> int:
    """Count of UNIQUE (category, chapter, text) chunks build_knowledge_index.py
    will actually store for this novel — NOT a raw source-record count.
    Confirmed live: some novels have duplicate reveal/scheme records in the
    source JSON (my_novel has 1,418 duplicate rows
    out of 3,792; my_novel has 682 of 3,058), which the
    indexer's own dedup naturally collapses to one stored chunk each. Counting
    raw rows as "total" made two FULLY indexed novels (indexer's own queue
    empty, nothing left to do) permanently show as 63%/78% instead of 100% —
    their duplicate rows could never be "done" no matter how many passes ran,
    since only one copy of each ever gets stored. Mirrors
    build_knowledge_index.py's _collect_candidates key-building exactly
    (same text/chapter formulas) so the count matches what's really stored."""
    keys = set()
    for r in read_json(novel_dir / "reveals" / "log.json") or []:
        if isinstance(r, dict) and r.get("content"):
            text = f"{r.get('reveal_type', '')}: {r['content']}"
            chapter = r.get("payoff_chapter") or _knowledge_index_normalize_chapter(r.get("setup_chapters"))
            keys.add(("reveal", chapter, text))
    for r in read_json(novel_dir / "schemes" / "instances.json") or []:
        if isinstance(r, dict) and r.get("goal"):
            text = f"{r['goal']} via {r.get('mechanism', '')}"
            keys.add(("scheme", _knowledge_index_normalize_chapter(r.get("setup_chapter")), text))
    for entry in read_json(novel_dir / "symbols" / "frequency.json") or []:
        if isinstance(entry, dict):
            for m in entry.get("mentions", []):
                if isinstance(m, dict) and m.get("meaning"):
                    text = f"{entry.get('symbol', '')}: {m['meaning']}"
                    keys.add(("symbol", _knowledge_index_normalize_chapter(m.get("chapter")), text))
    for t in read_json(novel_dir / "glossary" / "terms.json") or []:
        if isinstance(t, dict) and t.get("term") and t.get("definition"):
            text = f"{t['term']}: {t['definition']}"
            keys.add(("glossary", _knowledge_index_normalize_chapter(t.get("first_seen_chapter")), text))
    for s in read_json(novel_dir / "prose" / "samples.json") or []:
        if isinstance(s, dict) and s.get("excerpt"):
            keys.add(("prose", _knowledge_index_normalize_chapter(s.get("chapter")), s["excerpt"][:600]))
    genome = read_json(novel_dir / "narrative_genome.json") or {}
    genome_patterns = genome.get("patterns", genome if isinstance(genome, list) else [])
    for p in (genome_patterns or []):
        if isinstance(p, dict) and p.get("description"):
            text = f"{p.get('pattern_type', p.get('pattern_id', 'pattern'))}: {p['description']}"
            chrange = p.get("chapter_range")
            chapter = chrange[0] if isinstance(chrange, list) and chrange else None
            keys.add(("pattern", chapter, text))
    entities_dir = novel_dir / "entities"
    if entities_dir.exists():
        for f in entities_dir.glob("*.json"):
            if f.stem.startswith("chapter_"):
                continue
            d = read_json(f) or {}
            if not isinstance(d, dict):
                continue
            for s in ((d.get("voice_dna") or {}).get("dialogue_samples") or []):
                if isinstance(s, dict):
                    line = str(s.get("line") or "").strip()
                    if line:
                        keys.add(("dialogue", None, line))
    # summary + antagonist_template categories (8th/9th) — without these in the
    # expected total, done was capped at a total that never included them, so a
    # novel with NONE of its chapter summaries indexed still read 100%.
    deltas_dir = novel_dir / "deltas_v3"
    if deltas_dir.exists():
        for f in deltas_dir.glob("ch*.json"):
            if not _re.match(r"^ch\d+\.json$", f.name):   # same test-artifact guard as the indexer
                continue
            d = read_json(f)
            if isinstance(d, dict):
                summary = str(d.get("summary") or "").strip()
                if summary:
                    keys.add(("summary", d.get("chapter_number"), summary))
    for t in read_json(novel_dir / "templates" / "antagonists.json") or []:
        if not isinstance(t, dict) or not t.get("pattern"):
            continue
        first_chapter = None
        for inst in (t.get("instances") or []):
            chs = inst.get("chapters") if isinstance(inst, dict) else None
            if isinstance(chs, list) and chs:
                try:
                    c0 = int(chs[0])
                except (TypeError, ValueError):
                    continue
                if first_chapter is None or c0 < first_chapter:
                    first_chapter = c0
        keys.add(("antagonist_template", first_chapter, f"{t.get('template_id', 'antagonist_pattern')}: {t['pattern']}"))
    # story_shape (10th category) — the novel's whole rolling plot summary, one chunk.
    try:
        rolling = read_json(novel_dir / "rolling_summary.json") or {}
    except Exception:
        rolling = {}
    shape = str(rolling.get("summary") or "").strip() if isinstance(rolling, dict) else ""
    if shape:
        keys.add(("story_shape", None, shape))
    # A record held both with and without its chapter is ONE chunk: the indexer looks a missing chapter up in deltas_v3
    # (corpus/chapter_lookup.py), so the chapter-less copy lands on the chaptered one.
    chaptered = {(cat, text) for cat, ch, text in keys if ch is not None}
    return sum(1 for cat, ch, text in keys if ch is not None or (cat, text) not in chaptered)


def _knowledge_index_progress() -> list:
    return _cached_progress("knowledge_index", _compute_knowledge_index_progress)


_BLUEPRINTS_DIR = CORPUS_PATH / "blueprints"
# Mirrors build_blueprint_index.py's _LIST_FIELDS exactly — the list field(s)
# each system_type's blueprint file carries items under. Kept in sync by
# hand (small, stable list) rather than importing the corpus-script module
# from this backend package, same cross-boundary-avoidance reasoning as the
# rest of this file's corpus-script integration points.
_BLUEPRINT_LIST_FIELDS = {
    "world": ["factions", "key_locations", "races"],
    "power_levels": ["levels"], "techniques": ["techniques"], "weapons": ["weapons"],
    "alchemy": ["pills"], "arrays": ["formations"], "artifact_forging": ["artifacts"],
    "treasures_materials": ["treasures"], "wars": ["wars"], "relationships": ["relationships"],
    "encounters": ["encounters"], "character_templates": ["characters"],
    "pets_mounts": ["companions"], "bosses_monsters": ["monsters"],
    "currency_commerce": ["entities"],
}


def _blueprint_index_expected_items(system_type: str) -> int:
    """Count of named items across every saved blueprint file for this
    system_type — the real ceiling build_blueprint_index.py will index (an
    item with no `name` is skipped by the indexer, so it's excluded here
    too, matching what actually gets stored)."""
    type_dir = _BLUEPRINTS_DIR / system_type
    if not type_dir.is_dir():
        return 0
    total = 0
    for f in type_dir.glob("*.json"):
        d = read_json(f) or {}
        if not isinstance(d, dict):
            continue
        for list_field in _BLUEPRINT_LIST_FIELDS.get(system_type, []):
            items = d.get(list_field)
            if isinstance(items, list):
                total += sum(1 for it in items if isinstance(it, dict) and it.get("name"))
    return total


def _blueprint_index_progress() -> list:
    return _cached_progress("blueprint_index", _compute_blueprint_index_progress)


def _compute_blueprint_index_progress() -> list:
    rows = []
    if not _KNOWLEDGE_DB.exists():
        by_type = {}
    else:
        conn = _sqlite3.connect(_KNOWLEDGE_DB)
        by_type = dict(conn.execute(
            "SELECT novel_id, COUNT(*) FROM chunks WHERE category = 'blueprint' GROUP BY novel_id"
        ).fetchall())
        conn.close()
    if not _BLUEPRINTS_DIR.exists():
        return rows
    for type_dir in sorted(_BLUEPRINTS_DIR.iterdir()):
        if not type_dir.is_dir():
            continue
        total = _blueprint_index_expected_items(type_dir.name)
        # Was `if total:` — skipped any system_type with zero saved items,
        # which hid brand-new categories (an empty folder created for a
        # just-added engine, e.g. pets_mounts/bosses_monsters/
        # currency_commerce) from this dashboard entirely until the author
        # saved their first Blueprint under it. Now always shown as 0/0 —
        # visible and trackable from the moment the category exists, not
        # only once it has content.
        # "novel_id" field name kept for JobCard reuse (see CorpusPipelinePage.jsx
        # — job.rowLabel controls the displayed column header, the field itself
        # stays novel_id across every job so the component logic is shared).
        rows.append({"novel_id": type_dir.name, "done": min(by_type.get(type_dir.name, 0), total), "total": total})
    return rows


_PROJECTS_DIR = CORPUS_PATH / "projects"
# Mirrors build_project_systems_index.py's _EXCLUDED_PROJECT_IDS — throwaway
# test projects, kept out of the pipeline cards for the same reason. 2026-09-27.
_EXCLUDED_PROJECT_IDS = set()      # ids of throwaway test projects to keep out of the index (add your own)
# Mirrors build_project_systems_index.py's _SYSTEMS_LIST_FIELDS /
# _WORLD_BIBLE_LIST_FIELDS — kept in sync by hand, same reasoning as
# _BLUEPRINT_LIST_FIELDS above.
_PROJECT_SYSTEMS_LIST_FIELDS = {
    "power_levels": ["levels"], "techniques": ["techniques"], "weapons": ["weapons"],
    "alchemy": ["pills"], "arrays": ["formations"], "artifact_forging": ["artifacts"],
    "treasures_materials": ["treasures"], "wars": ["wars"], "relationships": ["relationships"],
    "encounters": ["encounters"], "pets_mounts": ["companions"], "bosses_monsters": ["monsters"],
    "currency_commerce": ["entities"],
}
_PROJECT_WORLD_BIBLE_LIST_FIELDS = ["factions", "key_locations", "races"]


def _project_systems_index_expected_items(project_id: str) -> int:
    """Count of named items across this ONE project's systems + world_bible —
    the real ceiling build_project_systems_index.py will index for it."""
    path = _PROJECTS_DIR / project_id / "project.json"
    d = read_json(path) or {}
    if not isinstance(d, dict):
        return 0
    total = 0
    systems = d.get("systems") or {}
    if isinstance(systems, dict):
        for system_type, list_fields in _PROJECT_SYSTEMS_LIST_FIELDS.items():
            sys_data = systems.get(system_type)
            if not isinstance(sys_data, dict):
                continue
            for list_field in list_fields:
                items = sys_data.get(list_field)
                if isinstance(items, list):
                    total += sum(1 for it in items if isinstance(it, dict) and it.get("name"))
    world = d.get("world_bible") or {}
    if isinstance(world, dict):
        for list_field in _PROJECT_WORLD_BIBLE_LIST_FIELDS:
            items = world.get(list_field)
            if isinstance(items, list):
                total += sum(1 for it in items if isinstance(it, dict) and it.get("name"))
    return total


def _project_systems_index_progress() -> list:
    return _cached_progress("project_systems_index", _compute_project_systems_index_progress)


def _compute_project_systems_index_progress() -> list:
    rows = []
    if not _KNOWLEDGE_DB.exists():
        by_project = {}
    else:
        conn = _sqlite3.connect(_KNOWLEDGE_DB)
        by_project = dict(conn.execute(
            "SELECT novel_id, COUNT(*) FROM chunks WHERE category = 'project_system' GROUP BY novel_id"
        ).fetchall())
        conn.close()
    if not _PROJECTS_DIR.exists():
        return rows
    for proj_dir in sorted(_PROJECTS_DIR.iterdir()):
        if not proj_dir.is_dir() or proj_dir.name in _EXCLUDED_PROJECT_IDS or not (proj_dir / "project.json").exists():
            continue
        total = _project_systems_index_expected_items(proj_dir.name)
        if total:
            rows.append({"novel_id": proj_dir.name, "done": min(by_project.get(proj_dir.name, 0), total), "total": total})
    return rows


def _indexer_status_rows(script: str):
    """Ask an indexer script itself (--status: no embedding, no writes) how many chunks each novel wants, how many it would still add
    (queued) and how many rows it holds that nothing wants any more (stale). None when it cannot be asked."""
    try:
        py = shutil.which("python")
        r = subprocess.run([py, "-u", str(CORPUS_PATH / script), "--status"], cwd=str(CORPUS_PATH), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        rows = []
        for line in r.stdout.splitlines():
            if line.startswith("STATUS "):
                s = json.loads(line[7:])
                if s["wanted"]:
                    rows.append({"novel_id": s["novel"], "done": max(0, s["wanted"] - s["queued"]), "total": s["wanted"],
                                 "stale_chunks": s.get("stale", 0)})
        return rows or None
    except Exception:
        return None


def _compute_knowledge_index_progress() -> list:
    """done = chunks the indexer would NOT have to add, asked of the indexer itself, so the card can never disagree with what a run
    would do. Falls back to counting rows if the indexer cannot be asked."""
    return _indexer_status_rows("build_knowledge_index.py") or _compute_knowledge_index_progress_by_rows()


def _compute_knowledge_index_progress_by_rows() -> list:
    rows = []
    if not _KNOWLEDGE_DB.exists():
        by_novel = {}
    else:
        conn = _sqlite3.connect(_KNOWLEDGE_DB)
        # humor rows are the Humor Index job's own (see _humor_index_progress), not this one's.
        by_novel = dict(conn.execute("SELECT novel_id, COUNT(*) FROM chunks WHERE category != 'humor' "
                                     "GROUP BY novel_id").fetchall())
        conn.close()
    for nd in sorted(NOVELS_PATH.iterdir()) if NOVELS_PATH.exists() else []:
        if not nd.is_dir():
            continue
        total = _knowledge_index_expected_chunks(nd)
        if total:
            rows.append({"novel_id": nd.name, "done": min(by_novel.get(nd.name, 0), total), "total": total})
    return rows


def _humor_beat_parts(h: dict) -> tuple:
    """Mirrors corpus/build_humor_index.py's beat_parts exactly."""
    setup = str(h.get("setup") or h.get("context") or h.get("description") or "").strip()
    payoff = str(h.get("payoff") or h.get("excerpt") or h.get("example_text") or "").strip()
    return setup, payoff


def _humor_chunk_text(h: dict) -> str:
    """Mirrors corpus/build_humor_index.py's humor_chunk_text exactly, so the
    progress total is the number of chunks a complete humor index holds."""
    kind = str(h.get("type") or "humor").replace("_", " ")
    setup, payoff = _humor_beat_parts(h)
    body = f"{setup} → {payoff}" if setup and payoff else (setup or payoff)
    return f"{kind}: {body}"[:700] if body else ""


def _humor_index_progress() -> list:
    return _cached_progress("humor_index", _compute_humor_index_progress)


def _compute_humor_index_progress() -> list:
    """Asked of the humor indexer itself (--status); falls back to the row count."""
    return _indexer_status_rows("build_humor_index.py") or _compute_humor_index_progress_by_rows()


def _compute_humor_index_progress_by_rows() -> list:
    """done = humor chunks indexed for a novel, total = the distinct (chapter,
    text) chunks its humor log yields (the index table's UNIQUE key)."""
    by_novel = {}
    if _KNOWLEDGE_DB.exists():
        conn = _sqlite3.connect(_KNOWLEDGE_DB)
        by_novel = dict(conn.execute("SELECT novel_id, COUNT(*) FROM chunks WHERE category = 'humor' "
                                     "GROUP BY novel_id").fetchall())
        conn.close()
    rows = []
    for nd in sorted(NOVELS_PATH.iterdir()) if NOVELS_PATH.exists() else []:
        beats = read_json(nd / "humor" / "instances.json") if nd.is_dir() else None
        if not isinstance(beats, list):
            continue
        keys = set()
        for h in beats:
            if not isinstance(h, dict):
                continue
            try:
                ch = int(h.get("source_chapter"))
            except Exception:
                ch = None
            text = _humor_chunk_text(h)
            if text:
                keys.add((ch, text))
        # A beat the merged log holds both with and without its chapter is ONE chunk: the indexer now looks the missing
        # chapter up in deltas_v3 (corpus/chapter_lookup.py), so the chapter-less copy lands on the chaptered one.
        chaptered = {t for c, t in keys if c is not None}
        keys = {(c, t) for c, t in keys if c is not None or t not in chaptered}
        if keys:
            rows.append({"novel_id": nd.name, "done": min(by_novel.get(nd.name, 0), len(keys)), "total": len(keys)})
    return rows


_ROSTER_DIR = CORPUS_PATH / "character_roster"


def _character_roster_progress() -> list:
    """done = characters step 1.5 has ACTUALLY PROCESSED (enrichment_attempted
    == True), total = character-type entities in that novel's entities/ dir
    (the roster's real ceiling, independent of how many have been rostered
    yet). Deliberately NOT keyed on semantic_enrichment being non-empty —
    confirmed live that a real full run left 269/1350 characters correctly
    processed but with zero hits above the score floor (too little corpus
    presence to match), which made an earlier version of this function
    plateau at 80% forever on a fully-finished job — looked exactly like a
    crash from the UI, wasn't one. enrichment_attempted is the completion
    signal; semantic_enrichment's hit count is a quality/richness detail, not
    a progress signal. TTL-cached (see _cached_progress) — confirmed live this
    cost ~3.75s/call uncached, parsing every entities/*.json AND every
    character_roster/*.json across all 18 novels."""
    return _cached_progress("character_roster", _compute_character_roster_progress)


def _compute_character_roster_progress() -> list:
    rows = []
    for nd in sorted(NOVELS_PATH.iterdir()) if NOVELS_PATH.exists() else []:
        if not nd.is_dir():
            continue
        entities_dir = nd / "entities"
        if not entities_dir.exists():
            continue
        chars = set()
        for f in entities_dir.glob("*.json"):
            d = read_json(f)
            if isinstance(d, dict) and d.get("type") == "character":
                chars.add(f.stem)
        total = len(chars)
        if not total:
            continue
        done = 0
        roster_dir = _ROSTER_DIR / nd.name
        if roster_dir.exists():
            for f in roster_dir.glob("*.json"):
                if f.stem not in chars:          # a roster file whose character is gone is not progress
                    continue
                d = read_json(f)
                if isinstance(d, dict) and d.get("enrichment_attempted"):
                    done += 1
        rows.append({"novel_id": nd.name, "done": done, "total": total})
    return rows


_CHARACTER_DNA_DIR = CORPUS_PATH / "character_dna"
_CHARACTER_DNA_SHORTLIST_N = 15  # mirrors build_roster_shortlist.py / build_character_dna.py's own default — kept in sync deliberately, not re-derived from either script, since the total this drives is a UI-only estimate, not the pipeline's own resume logic
_CHARACTER_DNA_PLACEHOLDER_NAMES = {"protagonist", "antagonist", "narrator", "unknown", "unnamed", "mc", "the protagonist"}
_CHARACTER_DNA_REQUIRED_KEYS = {
    "protagonist": {"personality_dna", "morality_dna", "competence_dna", "banter_dna", "speech_dna", "emotional_dna", "identity_lock"},
    "deuteragonist": {"personality_dna", "morality_dna", "competence_dna", "banter_dna", "speech_dna", "emotional_dna", "identity_lock"},
    "antagonist": {"personality_dna", "morality_dna", "competence_dna", "banter_dna", "speech_dna", "emotional_dna", "identity_lock"},
    "mentor": {"personality_dna", "morality_dna", "competence_dna", "banter_dna", "speech_dna", "emotional_dna", "identity_lock"},
    "sidekick": {"personality_dna", "story_function", "humor_dna", "loyalty_dna"},
}
_CHARACTER_DNA_GENERIC_REQUIRED = {"system_version", "character_id", "novel_id", "role", "character_name", "grounding"}


def _character_dna_map_role(roster_role) -> str:
    """Mirrors build_character_dna.py's _map_role exactly — kept as a literal
    duplicate rather than imported, since this router runs inside the packaged
    exe's own process and importing a corpus/ pipeline script here would
    cross the same corpus-script/app boundary every other corpus_builder.py
    subprocess call deliberately stays on the other side of."""
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


def _character_dna_verify(path: Path, role_dir: str) -> bool:
    d = read_json(path)
    if not isinstance(d, dict):
        return False
    required = _CHARACTER_DNA_REQUIRED_KEYS.get(role_dir, _CHARACTER_DNA_REQUIRED_KEYS["sidekick"]) | _CHARACTER_DNA_GENERIC_REQUIRED
    return required.issubset(d.keys())


def _character_dna_shortlists() -> dict:
    """Confirmed live: computing the shortlist fresh on every call means
    reading and JSON-parsing all ~1350 roster files per request.
    pipeline-status is polled every 6s by the Corpus Pipeline page
    (CorpusPipelinePage.jsx) — with the per-request cost this high, requests
    queue up faster than the single-worker uvicorn server can drain them
    (confirmed live: 3 concurrent requests took ~19s each, served serially,
    not in parallel), which is what actually broke page load, not any one
    slow response alone. The shortlist only meaningfully changes when
    build_character_roster.py runs (periodic, human-triggered), never between
    one 6s poll and the next, so TTL-caching it (see _cached_progress) is
    exactly right — unlike the true done-counts in _character_dna_progress
    below (verified character_dna/ output files), which stay cheap enough to
    recompute every call and SHOULD reflect a build finishing promptly."""
    return _cached_progress("character_dna_shortlists", _compute_character_dna_shortlists)


def _compute_character_dna_shortlists() -> dict:
    by_novel = {}
    for nd in sorted(_ROSTER_DIR.iterdir()) if _ROSTER_DIR.exists() else []:
        if not nd.is_dir():
            continue
        entries = []
        for f in nd.glob("*.json"):
            d = read_json(f)
            if isinstance(d, dict):
                entries.append(d)
        if not entries:
            continue
        # NOTE: has_curated_dna characters are deliberately NOT filtered out
        # here, unlike build_character_dna.py's own queue-building filter —
        # this shortlist is a UI-facing "who's in the top 15" ranking
        # (consumed by the picker's stale-check and progress display, both
        # of which want to know about curated characters too), not the
        # machine pipeline's own build target list. See
        # _character_dna_progress() for where curated slots are excluded
        # from the done/total COUNT specifically — that's the fix for the
        # real bug (251/258 stuck forever), not this ranking step, which was
        # tried first and confirmed NOT to change the total (a curated
        # character's high weight just gets backfilled by the next-highest
        # remaining one, so the shortlist SIZE per novel never shrinks).
        shortlist = sorted(entries, key=lambda e: -e.get("weight", 0))[:_CHARACTER_DNA_SHORTLIST_N]
        shortlist = [e for e in shortlist if e.get("canonical_name", "").strip().lower() not in _CHARACTER_DNA_PLACEHOLDER_NAMES]
        if shortlist:
            by_novel[nd.name] = shortlist
    return by_novel


def _character_dna_is_stale(dna_data: dict, roster_entry: dict) -> bool:
    """True if the roster has more source material now than when this file
    was built — e.g. Corpus Builder's auto-refresh (_notify_pipeline_new_data
    in corpus_builder.py) added new chapters that gave this character new
    facts/quotes since its DNA was last generated. Never flags a DECREASE
    (a roster rebuild's own dedup fix, or a data edit, isn't "new material"
    needing a rebuild) — only growth counts. A file with no _source_snapshot
    at all (the 8 hand-curated originals, or a machine-built file from before
    this field existed) is never flagged stale — there's nothing to compare
    against, and flagging "unknown" as "stale" would be a false positive on
    every pre-existing file the moment this shipped."""
    snap = dna_data.get("_source_snapshot")
    if not isinstance(snap, dict):
        return False
    facts_now = len(roster_entry.get("facts") or [])
    quotes_now = len(roster_entry.get("voice_samples") or [])
    enrich_now = len(roster_entry.get("semantic_enrichment") or [])
    return (facts_now > snap.get("facts", facts_now)
            or quotes_now > snap.get("voice_samples", quotes_now)
            or enrich_now > snap.get("semantic_enrichment", enrich_now))


def _character_dna_progress() -> list:
    """done = shortlisted characters with a verified character_dna/ output
    file (same Stage-B verification build_character_dna.py itself runs before
    counting anything as done — not "file exists", since a crashed write can
    leave a malformed leftover that still needs a retry, exactly the
    enrichment_attempted-vs-semantic_enrichment distinction this router
    already got wrong once for the roster job). total = shortlist size (top
    _CHARACTER_DNA_SHORTLIST_N by weight per novel, placeholders excluded) —
    NOT all 1350 roster characters, since only the shortlist is ever a
    build_character_dna.py target. The shortlist itself is TTL-cached (see
    _character_dna_shortlists) — only the done-count re-verification below
    runs fresh every call, which is cheap (~258 file checks, not 1350).

    Also surfaces `stale` — built characters whose roster data has grown
    since their DNA file was generated (see _character_dna_is_stale) — as a
    NOTIFICATION only, never auto-rebuilt: the author decides whether a
    rebuild is worth the LLM spend, from the Corpus Pipeline tab."""
    rows = []
    for novel_id, shortlist in _character_dna_shortlists().items():
        # Real bug, confirmed live: a shortlist slot occupied by a
        # has_curated_dna character (Jiang Chen, Han Fei, Zhou Wen, etc. —
        # top-weight protagonists, so near-guaranteed to rank in the top 15)
        # counts toward TOTAL here but is never a build_character_dna.py
        # target (that script's own queue-building filter excludes them
        # outright, on purpose — the whole point is protecting hand-curated
        # files from being overwritten). Result: done permanently stuck
        # below total (251/258 observed live) even after every actually
        # machine-buildable character finished, reading in the UI as "still
        # running" / "stuck" rather than done. The real content for these
        # characters exists (at their curated file, a different path this
        # loop never checks) — they're just not what this counter should be
        # measuring completion against, so exclude them from both done and
        # total rather than trying to verify a file that was never supposed
        # to be written.
        #
        # SECOND real bug in that same fix, confirmed live: has_curated_dna is
        # set by build_character_roster.py's _curated_dna_lookup(), which flags
        # a character if ANY character_dna/ file exists for it — the machine's
        # own output included, not only the hand-curated originals. So each
        # character this pipeline FINISHES gets re-flagged "curated" on the
        # next roster rebuild, and excluding those from both sides made a fully
        # built novel read 0/0 (17 of 18 novels: all 15 top characters flagged,
        # ~27 real DNA files each). Fix: keep every shortlisted character in
        # `total`. A flagged character counts as done if its file verifies at
        # the machine path OR — for a genuinely hand-curated file with a
        # non-standard layout that can never verify — by the flag alone, since
        # the flag itself means a DNA file exists. Staleness is checked for any
        # verified file, so previously-built characters can surface it again.
        done = 0
        stale = []
        for entry in shortlist:
            role_dir = entry.get("curated_dna_role") or _character_dna_map_role(entry.get("role"))
            novel_short = "".join(w[0] for w in novel_id.split("_"))
            out_path = _CHARACTER_DNA_DIR / role_dir / f"{entry['character_id']}_{novel_short}.json"
            verified = _character_dna_verify(out_path, role_dir)
            if verified or entry.get("has_curated_dna"):
                done += 1
            if verified:
                dna_data = read_json(out_path)
                if isinstance(dna_data, dict) and _character_dna_is_stale(dna_data, entry):
                    # full identifiers, not just the display name — the
                    # Corpus Pipeline tab's per-character Rebuild button
                    # needs novel_id/character_id to call
                    # /character-dna-rebuild, a bare name isn't addressable
                    stale.append({"character_name": entry["canonical_name"],
                                  "character_id": entry["character_id"], "novel_id": novel_id})
        rows.append({"novel_id": novel_id, "done": done, "total": len(shortlist), "stale": stale})
    return rows


def _symbol_filtering_progress() -> list:
    return _cached_progress("symbol_filtering", _compute_symbol_filtering_progress)


def _compute_symbol_filtering_progress() -> list:
    rows = []
    for nd in sorted(NOVELS_PATH.iterdir()) if NOVELS_PATH.exists() else []:
        if not nd.is_dir():
            continue
        recs = read_json(nd / "symbols" / "candidates.json")
        if not isinstance(recs, list) or not recs:
            continue
        total = len(recs)
        done = sum(1 for r in recs if isinstance(r, dict) and ("_filtered" in r or "symbolic" in r))
        rows.append({"novel_id": nd.name, "done": done, "total": total})
    return rows


class _ComThread:
    """win32com/WMI requires COM initialized on the CALLING thread. FastAPI's
    sync endpoints run on whichever thread-pool worker happens to pick up the
    request — sometimes one that's used WMI before (fine), sometimes a fresh
    one that's never had CoInitialize called on it (WMI then throws a
    misleading generic error like "Invalid syntax" instead of anything
    mentioning COM/threading — confirmed live: a restart click failed with
    exactly that, then a LATER retry on a different thread launched the
    process fine, then failed reading the result — a half-succeeded launch
    is worse than a clean failure). CoInitialize is safe to call repeatedly
    on the same thread (returns S_FALSE, not an error).

    Deliberately does NOT call CoUninitialize on exit: FastAPI reuses these
    worker threads across requests, and tearing the apartment down right
    after each `with` block races Python's own garbage collection of the WMI
    objects — if one gets collected AFTER CoUninitialize runs, releasing its
    COM pointer into a dead apartment throws "Win32 exception occurred
    releasing IUnknown" (confirmed live in the packaged exe's stderr, non-
    fatal but real). Initializing once per thread and leaving it live for the
    thread's lifetime is the standard fix for a long-running server; the
    thread's own teardown at process exit cleans it up."""
    def __enter__(self):
        import pythoncom
        pythoncom.CoInitialize()
        return self

    def __exit__(self, *exc):
        pass


def _wmi_service():
    import win32com.client
    return win32com.client.GetObject("winmgmts:")


def _list_python_processes() -> list:
    """One WMI enumeration of every python.exe process, TTL-cached (see
    _cached_progress) — confirmed live each ExecQuery call alone costs
    ~1.5-2s, and pipeline_status() used to call _running_pipeline_pid (which
    did its OWN fresh ExecQuery) once per job, five times per request, adding
    up to ~13.5s on its own — the single biggest remaining cost after the
    file-scanning fixes elsewhere in this module, and the actual cause of
    pipeline-status hanging well past those fixes. One shared query per TTL
    window, checked against all five jobs' script names locally, fixes this
    properly instead of caching around it."""
    return _cached_progress("wmi_python_processes", _compute_list_python_processes)


def _compute_list_python_processes() -> list:
    try:
        with _ComThread():
            wmi = _wmi_service()
            return [(proc.ProcessId, proc.CommandLine or "")
                    for proc in wmi.ExecQuery("SELECT ProcessId, CommandLine FROM Win32_Process WHERE Name='python.exe'")]
    except Exception:
        return []


def _running_pipeline_pid(script_name: str, fresh: bool = False) -> int | None:
    """Find a running python.exe whose command line references this script —
    works regardless of how/when it was launched (this app's own restart, or
    a manually-started one). By default checks the shared, TTL-cached process
    list (see _list_python_processes) — fine for the pipeline-status DISPLAY
    path, where up-to-_PROGRESS_CACHE_TTL staleness is harmless.

    fresh=True forces a real, uncached WMI query — REQUIRED for any call site
    that acts on the result (Stop, Restart) rather than just displaying it: a
    job just killed or just launched must be seen accurately on the very next
    check, not through a stale cache window, or Stop/Restart's own logic
    (which branches on "is it currently running") makes the wrong call —
    e.g. Restart's kill-then-relaunch step deciding NOT to kill an instance
    that in reality is already running under a new PID the cache hasn't
    picked up yet."""
    processes = _compute_list_python_processes() if fresh else _list_python_processes()
    for pid, cmdline in processes:
        if script_name in cmdline:
            return pid
    return None


def _cmd_wrapper_pid(python_pid: int):
    """The cmd.exe that Win32_Process.Create launched, which then spawned
    python_pid as its child — needed so Stop can kill the WHOLE tree, not
    just the python.exe leaf (see _stop_pipeline_job)."""
    try:
        with _ComThread():
            wmi = _wmi_service()
            for proc in wmi.ExecQuery(f"SELECT ParentProcessId FROM Win32_Process WHERE ProcessId={int(python_pid)}"):
                ppid = proc.ParentProcessId
                for parent in wmi.ExecQuery(f"SELECT ProcessId, Name FROM Win32_Process WHERE ProcessId={ppid}"):
                    if parent.Name == "cmd.exe":
                        return ppid
    except Exception:
        pass
    return None


def _launch_pipeline_job(job_key: str) -> int:
    job = _PIPELINE_JOBS[job_key]
    # Most jobs run under the system python; a job may name its own interpreter
    # (embedding_finetune needs the venv that has torch) and extra arguments.
    python_exe = job.get("python") or shutil.which("python")
    if not python_exe or (job.get("python") and not Path(python_exe).exists()):
        raise HTTPException(500, (f"{job['label']} needs its Python environment at {python_exe} — it isn't set up on this PC."
                                  if job.get("python") else
                                  "No system python.exe found on PATH — cannot launch corpus pipeline jobs."))
    extra_args = "".join(f' "{a}"' for a in job.get("args", []))
    # Fixed filename (not timestamped) — cmd.exe's `>` truncates on each new
    # launch, so a restart always overwrites the previous run's log instead
    # of piling up a new file every time.
    out_log = f"{job_key}.log"
    err_log = f"{job_key}.err.log"
    cmd = f'cmd.exe /c ""{python_exe}" "{job["script"]}"{extra_args} > "{out_log}" 2> "{err_log}""'
    try:
        with _ComThread():
            wmi = _wmi_service()
            # Without an explicit hidden ProcessStartupInformation, cmd.exe
            # has no parent console to inherit and pops up a NEW visible
            # window — confirmed live, and Stop didn't close it since taskkill
            # only ever targeted the python.exe leaf, not this cmd.exe
            # wrapper. ShowWindow=0 (SW_HIDE) keeps it fully background.
            startup_class = wmi.Get("Win32_ProcessStartup")
            startup = startup_class.SpawnInstance_()
            startup.ShowWindow = 0
            proc_class = wmi.Get("Win32_Process")
            in_params = proc_class.Methods_("Create").InParameters.SpawnInstance_()
            in_params.CommandLine = cmd
            in_params.CurrentDirectory = str(CORPUS_PATH)
            in_params.ProcessStartupInformation = startup
            out_params = wmi.ExecMethod("Win32_Process", "Create", in_params)
            if out_params.ReturnValue != 0:
                raise HTTPException(500, f"Failed to launch {job['label']} (WMI Create returned {out_params.ReturnValue}).")
            return out_params.ProcessId
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to launch {job['label']}: {e}")


_LIVE_STATUS_FILE = CORPUS_PATH / "_pipeline_live_status.json"


def _live_status(job_key: str):
    """What a pipeline script is ACTUALLY processing right now — written by
    corpus/llm_client.write_live_status() right before each LLM call, so
    the UI can show real activity instead of only a done/total count that
    updates once per batch. None if the file is missing/stale-shaped."""
    if not _LIVE_STATUS_FILE.exists():
        return None
    try:
        data = json.loads(_LIVE_STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data.get(job_key) if isinstance(data, dict) else None


def _narrative_genome_chapter_count(novel_dir: Path) -> int:
    """Mirrors generate_genome.py's _chapter_summary_count exactly — how many
    chapter summaries this novel currently has extracted."""
    delta_dir = novel_dir / "deltas_v3"
    if not delta_dir.exists():
        return 0
    n = 0
    for f in delta_dir.glob("*.json"):
        d = read_json(f)
        if isinstance(d, dict) and d.get("summary"):
            n += 1
    return n


def _narrative_genome_is_current(novel_dir: Path) -> bool:
    """Mirrors generate_genome.py's is_stale() (inverted) exactly — same
    15-chapter-or-20%-growth threshold, so the dashboard's done/total count
    agrees with what a pipeline run would actually decide to skip or redo."""
    genome = read_json(novel_dir / "narrative_genome.json")
    if not genome or "source_chapter_count" not in genome:
        return False
    built_at = genome.get("source_chapter_count", 0)
    current = _narrative_genome_chapter_count(novel_dir)
    if current <= built_at:
        return True
    grown = current - built_at
    return grown < min(15, max(1, int(built_at * 0.2)))


def _narrative_genome_progress() -> list:
    """done = 1 if this novel's genome is current (per _narrative_genome_is_current),
    total = 1 for every novel with enough extracted data to be genome-eligible
    (has at least one chapter summary) — same one-row-per-novel shape every
    other pipeline progress function uses, just binary instead of a count
    since a genome run is one LLM call producing one file, not many small
    items like the embedding-based jobs."""
    rows = []
    for nd in sorted(NOVELS_PATH.iterdir()) if NOVELS_PATH.exists() else []:
        if not nd.is_dir():
            continue
        if _narrative_genome_chapter_count(nd) == 0:
            continue   # no extracted chapters yet — not genome-eligible
        rows.append({"novel_id": nd.name, "done": 1 if _narrative_genome_is_current(nd) else 0, "total": 1})
    return rows


def _author_brain_progress() -> list:
    """done = 1 once this novel's author notes cover its extracted chapters (written when it had fewer than 20 chapters less than now),
    total = 1 for every novel with at least 20 extracted chapters. Mirrors author_brain_claude.py's _notes_current."""
    rows = []
    for nd in sorted(NOVELS_PATH.iterdir()) if NOVELS_PATH.exists() else []:
        if not nd.is_dir():
            continue
        # real chapters only (ch<N>.json with a summary), like author_brain_claude.py: not the haiku45-original / pre-resolve backups
        have = 0
        for f in (nd / "deltas_v3").glob("ch*.json") if (nd / "deltas_v3").is_dir() else []:
            if _re.fullmatch(r"ch\d+\.json", f.name):
                d_ = read_json(f)
                have += 1 if isinstance(d_, dict) and d_.get("summary") else 0
        if have < 20:
            continue
        notes = read_json(nd / "author_brain" / "author_notes.json") or {}
        built = int(notes.get("source_chapter_count") or 0) if isinstance(notes, dict) and notes.get("author_rules") else None
        rows.append({"novel_id": nd.name, "done": 1 if built is not None and have - built < 20 else 0, "total": 1})
    return rows


_rolling_chapters_cache: dict = {}   # novel_id -> {"ts": float, "chapters": list[int]}
_ROLLING_CHAPTERS_TTL = 300  # seconds — the set of chapters that HAVE a summary only changes when an extraction runs


def _rolling_summary_chapters(nd: Path) -> list:
    """Chapter numbers with a non-empty summary — mirrors update_rolling_summary.py's
    _chapter_summaries (real chNN.json deltas only, test artifacts skipped). Reading
    every delta is the expensive part, so it gets its own longer TTL than the
    30s progress cache; the cheap per-novel state files are re-read every time."""
    now = time.time()
    hit = _rolling_chapters_cache.get(nd.name)
    if hit is not None and (now - hit["ts"]) < _ROLLING_CHAPTERS_TTL:
        return hit["chapters"]
    chapters = []
    deltas = nd / "deltas_v3"
    if deltas.is_dir():
        for f in deltas.glob("ch*.json"):
            m = _re.match(r"^ch(\d+)\.json$", f.name)
            if not m:
                continue
            try:
                d = read_json(f)
            except Exception:
                continue
            if isinstance(d, dict) and str(d.get("summary") or "").strip():
                chapters.append(int(m.group(1)))
    _rolling_chapters_cache[nd.name] = {"ts": now, "chapters": chapters}
    return chapters


def _rolling_summary_progress() -> list:
    return _cached_progress("rolling_summary", _compute_rolling_summary_progress)


def _compute_rolling_summary_progress() -> list:
    """done = chapters covered by the novel's running summary (chapter number <=
    last_chapter_folded — a periodic full rebuild jumps this straight to the
    newest chapter), total = chapters that have a summary to fold in."""
    rows = []
    for nd in sorted(NOVELS_PATH.iterdir()) if NOVELS_PATH.exists() else []:
        if not nd.is_dir():
            continue
        chapters = _rolling_summary_chapters(nd)
        if not chapters:
            continue
        try:
            state = read_json(nd / "rolling_summary.json") or {}
        except Exception:
            state = {}
        fs = state.get("folded_chapters") if isinstance(state, dict) else None
        if isinstance(fs, list):
            done = len(set(chapters) & {int(x) for x in fs})
        else:       # old state: the marker only counts when it covers a straight run 1..N (see update_rolling_summary.folded_set)
            marker = (state.get("last_chapter_folded", 0) if isinstance(state, dict) else 0) or 0
            legacy = {c for c in chapters if c <= marker}
            done = len(legacy) if legacy == set(range(1, marker + 1)) else 0
        rows.append({"novel_id": nd.name, "done": done, "total": len(chapters)})
    return rows


def _tuned_embeddings_progress() -> list:
    return _cached_progress("tuned_embeddings", _compute_tuned_embeddings_progress)


def _compute_tuned_embeddings_progress() -> list:
    """done = chunks that have a fine-tuned-model vector, total = all indexed chunks,
    per novel (blueprint/project-systems rows group under their system type / project id)."""
    if not _KNOWLEDGE_DB.exists():
        return []
    try:
        conn = _sqlite3.connect(f"file:{_KNOWLEDGE_DB}?mode=ro", uri=True, timeout=30)
        rows = conn.execute("SELECT novel_id, COUNT(*), SUM(CASE WHEN embedding_tuned IS NOT NULL THEN 1 ELSE 0 END) "
                            "FROM chunks GROUP BY novel_id ORDER BY novel_id").fetchall()
        conn.close()
    except Exception:
        return []
    return [{"novel_id": nid, "done": int(done or 0), "total": int(total)} for nid, total, done in rows]


_INDEX_CHAPTER_CATS = ("prose", "dialogue", "humor", "reveal")


def _index_chapters_progress() -> list:
    return _cached_progress("index_chapters", _compute_index_chapters_progress)


def _compute_index_chapters_progress() -> list:
    """done = prose/dialogue/humor/reveal chunks that have their chapter, plus those backfill_index_chapters.py checked
    and found no chapter for (index_chapters_unmatched.json: checked, not pending); total = all of those chunks."""
    if not _KNOWLEDGE_DB.exists():
        return []
    try:
        checked = json.loads((CORPUS_PATH / "index_chapters_unmatched.json").read_text(encoding="utf-8"))
    except Exception:
        checked = {}
    try:
        conn = _sqlite3.connect(f"file:{_KNOWLEDGE_DB}?mode=ro", uri=True, timeout=30)
        marks = ",".join("?" * len(_INDEX_CHAPTER_CATS))
        rows = conn.execute(f"SELECT novel_id, COUNT(*), SUM(CASE WHEN chapter IS NOT NULL THEN 1 ELSE 0 END) FROM chunks "
                            f"WHERE category IN ({marks}) GROUP BY novel_id ORDER BY novel_id", _INDEX_CHAPTER_CATS).fetchall()
        empty_ids = {nid: {r[0] for r in conn.execute(
            f"SELECT id FROM chunks WHERE novel_id=? AND chapter IS NULL AND category IN ({marks})", (nid, *_INDEX_CHAPTER_CATS))}
            for nid, _t, _d in rows}
        conn.close()
    except Exception:
        return []
    out = []
    for nid, total, done in rows:
        seen = len(empty_ids.get(nid, set()) & set(checked.get(nid) or []))
        out.append({"novel_id": nid, "done": min(int(total), int(done or 0) + seen), "total": int(total)})
    return out


_MECHANICS_SCHEMA = 3     # keep in step with corpus/build_mechanics_deltas.py SCHEMA_VERSION


def _mechanics_built(path: Path) -> bool:
    """A chapter the Chapter Mechanics job counts as built: its delta carries the mechanics (schema_version "4.0", the
    delta's first key), or the old sidecar file exists AND is at the current schema (the job rebuilds older ones)."""
    try:
        with open(path.parent.parent / "deltas_v3" / path.name, "rb") as f:
            if _re.search(r'"schema_version"\s*:\s*"4\.0"', f.read(200).decode("utf-8", errors="ignore")):
                return True
    except Exception:
        pass
    try:
        with open(path, "rb") as f:
            head = f.read(160).decode("utf-8", errors="ignore")
        m = _re.search(r'"schema_version"\s*:\s*(\d+)', head)
        return bool(m) and int(m.group(1)) == _MECHANICS_SCHEMA
    except Exception:
        return False


def _mechanics_delta_progress() -> list:
    return _cached_progress("mechanics_delta", _compute_mechanics_delta_progress)


def _compute_mechanics_delta_progress() -> list:
    """done = chapters with a mechanics delta, total = extracted chapters (deltas_v3/chN.json) that have a raw text."""
    rows = []
    for nd in sorted(NOVELS_PATH.iterdir()) if NOVELS_PATH.exists() else []:
        dv = nd / "deltas_v3"
        if not dv.is_dir():
            continue
        raw = CORPUS_PATH / "raw" / nd.name
        chs = [f.name for f in dv.iterdir() if _re.match(r"^ch\d+\.json$", f.name) and (raw / f"{f.stem}.txt").exists()]
        if not chs:
            continue
        mdir = nd / "deltas_mechanics"
        done = sum(1 for c in chs if _mechanics_built(mdir / c))
        rows.append({"novel_id": nd.name, "done": done, "total": len(chs)})
    rows.sort(key=lambda r: r["novel_id"])
    return rows


def _delta_upgrade_progress() -> list:
    """done = chapters already upgraded, total = chapters targeted in upgrade_deltas_config.json."""
    try:
        cfg = json.loads((CORPUS_PATH / "upgrade_deltas_config.json").read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    try:
        all_state = json.loads((CORPUS_PATH / "upgrade_deltas_state.json").read_text(encoding="utf-8"))
    except Exception:
        all_state = {}

    novel, chapters = cfg.get("novel"), cfg.get("chapters") or []
    if cfg.get("source") != "scan" and novel and chapters:
        # Fixed list (the original mode): exactly the chapters named in the config.
        state = all_state.get(novel, {})
        return [{"novel_id": novel, "done": len(set(state.get("done", [])) & set(chapters)), "total": len(chapters)}]

    # Scan mode (default): the worklist IS the upgrade scan's flagged chapters, so re-scanning adds and removes records.
    # done = chapters this job has upgraded; pending = flagged chapters still not upgraded. A chapter is counted once
    # (the job's own record plus the registry's live 'upgraded' flag), so the card can reach 100%.
    try:
        reg = json.loads((CORPUS_PATH / "delta_quality.json").read_text(encoding="utf-8"))
    except Exception:
        reg = {}
    # A chapter is complete when its V3 part is upgraded (or never flagged) AND its flagged mechanics fields are done
    # (isolated field upgrades are tracked apart, in the job state's "mech_done").
    mech_flags = ("thin_beats", "thin_fight_talk", "thin_cast")
    exists = {n: {int(c) for c in (nd.get("chapters") or {})} for n, nd in (reg.get("novels") or {}).items()}
    complete = {n: (set(s.get("done", [])) | set(s.get("mech_done", []))) & exists.get(n, set()) for n, s in all_state.items()}
    pending: dict = {}
    for c in reg.get("upgrade_candidates", []):
        entry = ((reg.get("novels") or {}).get(c["novel"], {}).get("chapters", {})).get(str(c["chapter"]), {})
        ns = all_state.get(c["novel"], {})
        flags = c.get("flags") or []
        v3f = [f for f in flags if f not in mech_flags]
        if v3f and all(f.startswith("low_") for f in v3f) and c["chapter"] in ns.get("done", []):
            v3_pending = c["chapter"] not in ns.get("retry_done", [])      # second chance for a chapter upgraded before
        else:
            v3_pending = bool(v3f) and not (entry.get("upgraded") or c["chapter"] in ns.get("done", []))
        mech_pending = any(f in mech_flags for f in flags) and c["chapter"] not in ns.get("mech_done", [])
        if not (v3_pending or mech_pending):
            continue
        pending.setdefault(c["novel"], set()).add(c["chapter"])
        complete.setdefault(c["novel"], set()).discard(c["chapter"])
    rows = []
    for name in sorted(set(pending) | {n for n, s in complete.items() if s}):
        done = len(complete.get(name, ()))
        rows.append({"novel_id": name, "done": done, "total": done + len(pending.get(name, ()))})
    return rows


def _empty_check_progress() -> list:
    """Per novel: done = chapters the check has already ruled on, total = done + chapters that still have an important
    field that is empty and unconfirmed (both read from the audit registry, which save_delta keeps current)."""
    try:
        reg = json.loads((CORPUS_PATH / "delta_quality.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    try:
        state = json.loads((CORPUS_PATH / "resolve_empties_state.json").read_text(encoding="utf-8"))
    except Exception:
        state = {}
    important = ("reveals", "knowledge_state", "facts", "timeline_events", "prose_samples", "character_voice_samples")
    rows = []
    for name, nd in sorted((reg.get("novels") or {}).items()):
        # done = chapters the check has visited (the check's own record — authoritative). pending = chapters with an
        # unconfirmed field it has NOT visited yet. A chapter is never counted in both: this used to add every
        # visited-but-still-unresolved chapter to the total a second time, so a novel could never reach 100%
        # (and a stale registry entry did the same).
        have = set((nd.get("chapters") or {}).keys())
        visited = {k.split("/", 1)[1] for k in state if k.startswith(name + "/")} & have     # only chapters that still exist
        pending = sum(1 for c, e in (nd.get("chapters") or {}).items()
                      if c not in visited and any(v == "unconfirmed" and k in important
                                                  for k, v in (e.get("empty_fields") or {}).items()))
        done = len(visited)
        unresolved = sum(1 for k, s in state.items() if k.startswith(name + "/")
                         and any(v == "left" for v in (s.get("outcome") or {}).values()))
        if pending or done:
            label = name + (f" — {unresolved} couldn't be resolved" if unresolved else "")
            rows.append({"novel_id": label, "done": done, "total": done + pending})
    return rows


def _fmt_eta(seconds) -> str:
    if not seconds or seconds < 0:
        return "?"
    h, m = int(seconds // 3600), int((seconds % 3600) // 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


def _embedding_finetune_state() -> dict:
    """Read embedding_ft/train.py's progress file (uncached — it's one tiny file)."""
    try:
        return json.loads(_EMBEDDING_FT_PROGRESS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _embedding_finetune_progress(st: dict) -> list:
    """One row per run: done = training step, total = steps in the run. When the
    run has finished and scored itself, the row label carries the before/after
    retrieval numbers so the result is visible right on the page."""
    if not st or not st.get("max_steps"):
        return []
    label = st.get("run") or "run1"
    res = st.get("result") or {}
    if st.get("phase") == "done" and res.get("tuned") and res.get("baseline"):
        t, b = res["tuned"], res["baseline"]
        label += f" — recall@10 {t['recall']:.3f} (was {b['recall']:.3f}) · MRR {t['mrr']:.3f} (was {b['mrr']:.3f})"
    step = st.get("max_steps") if st.get("phase") in ("evaluating", "done") else st.get("step", 0)
    return [{"novel_id": label, "done": int(step or 0), "total": int(st["max_steps"])}]


def _embedding_finetune_live(st: dict):
    if not st or st.get("phase") is None:
        return None
    phase = st["phase"]
    if phase == "training":
        loss = f" · loss {st['loss']}" if st.get("loss") is not None else ""
        preview = f"step {st.get('step', 0)}/{st.get('max_steps') or '?'}{loss} · about {_fmt_eta(st.get('eta_s'))} left"
    elif phase == "evaluating":
        preview = "training finished — scoring the tuned model against the baseline on the held-out novels"
    elif phase == "loading":
        preview = "loading the base model and training pairs"
    else:
        preview = phase
    return {"ts": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.get("updated", time.time()))),
            "novel": st.get("run") or "run1", "kind": phase, "batch_size": 32, "preview": preview}


# ── Delta quality scan (the "Scan for upgrades" button on the Delta Upgrade card) ──────────────
# Runs corpus/delta_audit.py (no LLM; ~25s for the whole corpus) in the background and serves a
# summary of delta_quality.json. The scan itself lives in that script so it can also be run from a
# terminal and is called automatically after every extraction save.
import threading as _threading

_audit_job = {"running": False, "started": None, "finished": None, "ok": None, "error": ""}
_audit_cache = {"mtime": None, "summary": None}


def _run_delta_audit_thread():
    py = shutil.which("python")
    try:
        if not py:
            raise RuntimeError("No system python.exe found on PATH — cannot run the scan.")
        r = subprocess.run([py, "delta_audit.py"], cwd=str(CORPUS_PATH), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600, creationflags=0x08000000)
        _audit_job.update(ok=(r.returncode == 0), error="" if r.returncode == 0 else (r.stderr or r.stdout)[-300:])
    except Exception as e:
        _audit_job.update(ok=False, error=str(e)[:300])
    finally:
        _audit_job.update(running=False, finished=time.time())


# The Delta Upgrade card's hard-lock checkboxes -- mirrors upgrade_deltas.py's _GATED_PAIRS
# (gated fast model -> its escalation model), just the model ids needed to WRITE the config;
# upgrade_deltas.py itself owns what each one actually does with the model once launched.
_UPGRADE_CONFIG_PATH = CORPUS_PATH / "upgrade_deltas_config.json"
_LOCK_MODEL_IDS = {
    "haiku": "claude-haiku-4-5-20251001",
    "nemotron_lightning": "nvidia/nemotron-3.5-lightning-30b-a3b",
}
_MODEL_ID_TO_LOCK = {v: k for k, v in _LOCK_MODEL_IDS.items()}


class DeltaUpgradeConfigRequest(BaseModel):
    lock: str   # "auto" | "haiku" | "nemotron_lightning"


@router.get("/delta-upgrade/config")
def delta_upgrade_config_get():
    """Which model the Delta Upgrade job is hard-locked to, if any (the checkboxes on its card)
    -- upgrade_deltas.py reads this file's "model" field once at process start, so a toggle here
    takes effect on the NEXT launch of the job, not a live one already running."""
    cfg = read_json(_UPGRADE_CONFIG_PATH) or {}
    return {"lock": _MODEL_ID_TO_LOCK.get(cfg.get("model"), "auto"), "claude_effort": cfg.get("claude_effort")}


@router.post("/delta-upgrade/config")
def delta_upgrade_config_set(req: DeltaUpgradeConfigRequest):
    if req.lock not in ("auto", *_LOCK_MODEL_IDS):
        raise HTTPException(400, f"unknown lock '{req.lock}' — must be one of: auto, {', '.join(_LOCK_MODEL_IDS)}")
    cfg = read_json(_UPGRADE_CONFIG_PATH) or {}
    cfg["model"] = _LOCK_MODEL_IDS.get(req.lock, "auto")
    tmp = _UPGRADE_CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, _UPGRADE_CONFIG_PATH)
    return {"ok": True, "lock": req.lock}


class DeltaUpgradeEffortRequest(BaseModel):
    claude_effort: Optional[str] = None   # "low", or None for the Claude CLI's default


@router.post("/delta-upgrade/effort")
def delta_upgrade_effort_set(req: DeltaUpgradeEffortRequest):
    """The Delta Upgrade card's "Claude: low effort" checkbox: every Claude call the job makes
    runs with the Claude CLI's --effort set to this. upgrade_deltas.py reads it on every call
    (not once at launch like "model"), so it changes the next call of a run already going."""
    if req.claude_effort not in (None, "low", "medium", "high"):
        raise HTTPException(400, "claude_effort must be low, medium, high or empty")
    cfg = read_json(_UPGRADE_CONFIG_PATH) or {}
    if req.claude_effort:
        cfg["claude_effort"] = req.claude_effort
    else:
        cfg.pop("claude_effort", None)
    tmp = _UPGRADE_CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, _UPGRADE_CONFIG_PATH)
    return {"ok": True, "claude_effort": req.claude_effort}


@router.post("/delta-audit/run")
def delta_audit_run():
    if _audit_job["running"]:
        return {"ok": True, "already_running": True}
    _audit_job.update(running=True, started=time.time(), finished=None, ok=None, error="")
    _threading.Thread(target=_run_delta_audit_thread, name="delta-audit", daemon=True).start()
    return {"ok": True}


@router.get("/delta-audit")
def delta_audit_status():
    """Scan job state + a compact summary of the last scan (per-novel rows, flag counts, top candidates)."""
    out = {"job": dict(_audit_job), "scanned": False}
    reg_path = CORPUS_PATH / "delta_quality.json"
    if not reg_path.exists():
        return out
    mtime = reg_path.stat().st_mtime
    if _audit_cache["mtime"] != mtime:
        try:
            reg = json.loads(reg_path.read_text(encoding="utf-8"))
        except Exception:
            return out
        cand_by_novel: dict = {}
        for c in reg.get("upgrade_candidates", []):
            cand_by_novel[c["novel"]] = cand_by_novel.get(c["novel"], 0) + 1
        novels = []
        tiers = {"A": 0, "B": 0, "C": 0}
        flags: dict = {}
        total = upgraded = 0
        for name, nd in (reg.get("novels") or {}).items():
            s = nd.get("summary") or {}
            for t, n in (s.get("tiers") or {}).items():
                tiers[t] = tiers.get(t, 0) + n
            for f, n in (s.get("flags") or {}).items():
                flags[f] = flags.get(f, 0) + n
            n_up = sum(1 for e in (nd.get("chapters") or {}).values() if e.get("upgraded"))
            total += s.get("chapters", 0)
            upgraded += n_up
            novels.append({"novel_id": name, "chapters": s.get("chapters", 0), "mean_score": s.get("mean_score", 0),
                           "tiers": s.get("tiers", {}), "candidates": cand_by_novel.get(name, 0), "upgraded": n_up,
                           "top_flags": dict(sorted((s.get("flags") or {}).items(), key=lambda kv: -kv[1])[:3])})
        novels.sort(key=lambda n: n["mean_score"])
        # Empty fields split by whether the model ever ruled on them (delta["confirmed_empty"]): "confirmed none" means
        # the chapter genuinely has nothing; "unconfirmed" means empty with nobody having checked — possibly a miss.
        empty = {}
        for nd in (reg.get("novels") or {}).values():
            for k, v in ((nd.get("summary") or {}).get("empty_fields") or {}).items():
                e = empty.setdefault(k, {"confirmed_none": 0, "unconfirmed": 0})
                e["confirmed_none"] += v.get("confirmed_none", 0)
                e["unconfirmed"] += v.get("unconfirmed", 0)
        _audit_cache.update(mtime=mtime, summary={
            "generated": reg.get("generated"), "last_marked": reg.get("last_marked"), "total": total,
            "empty_fields": empty, "resolve_chapters": len(reg.get("resolve_candidates", [])),
            "tiers": tiers, "flags": dict(sorted(flags.items(), key=lambda kv: -kv[1])),
            "candidates": len(reg.get("upgrade_candidates", [])), "upgraded": upgraded, "novels": novels,
            "top_candidates": (reg.get("upgrade_candidates") or [])[:10]})
    return {**out, "scanned": True, **_audit_cache["summary"]}


# ── per-job status: the Pipeline page shows each card's last saved values instantly and refreshes one card at a time;
#    only running/live (cheap) is polled. The full /pipeline-status still works (every card computed fresh). ──
def _rows_entry(key: str, rows: list, **extra) -> dict:
    return {"label": _PIPELINE_JOBS[key]["label"], "novels": rows,
            "done": sum(r["done"] for r in rows), "total": sum(r["total"] for r in rows), **extra}


def _ft_entry():
    st = _embedding_finetune_state()
    return _rows_entry("embedding_finetune", _embedding_finetune_progress(st), rowLabel="Run")


def _dna_entry():
    rows = _character_dna_progress()
    return _rows_entry("character_dna", rows, stale_count=sum(len(r.get("stale") or []) for r in rows))


_JOB_COUNTS = {   # job key -> builds its card's counts (the slow part); order = card order
    "thread_typing": lambda: _rows_entry("thread_typing", _thread_typing_progress()),
    "symbol_filtering": lambda: _rows_entry("symbol_filtering", _symbol_filtering_progress()),
    "knowledge_index": lambda: _rows_entry("knowledge_index", _knowledge_index_progress()),
    "humor_index": lambda: _rows_entry("humor_index", _humor_index_progress()),
    "character_roster": lambda: _rows_entry("character_roster", _character_roster_progress()),
    "character_dna": _dna_entry,
    "blueprint_index": lambda: _rows_entry("blueprint_index", _blueprint_index_progress(), rowLabel="System"),
    "project_systems_index": lambda: _rows_entry("project_systems_index", _project_systems_index_progress(), rowLabel="Project"),
    "narrative_genome": lambda: _rows_entry("narrative_genome", _narrative_genome_progress()),
    "rolling_summary": lambda: _rows_entry("rolling_summary", _rolling_summary_progress()),
    "author_brain": lambda: _rows_entry("author_brain", _author_brain_progress()),
    "mechanics_delta": lambda: _rows_entry("mechanics_delta", _mechanics_delta_progress()),
    "index_chapters": lambda: _rows_entry("index_chapters", _index_chapters_progress()),
    "empty_check": lambda: _rows_entry("empty_check", _empty_check_progress()),
    "delta_upgrade": lambda: _rows_entry("delta_upgrade", _delta_upgrade_progress(), rowLabel="Novel"),
    "tuned_embeddings": lambda: _rows_entry("tuned_embeddings", _tuned_embeddings_progress()),
    "embedding_finetune": _ft_entry,
}
_SNAPSHOT = CORPUS_PATH / "_pipeline_snapshot.json"
_SNAPSHOT_LOCK = threading.Lock()


def _job_live(key: str) -> dict:
    """The cheap part of a card: is it running, and what is it doing right now (one shared, TTL-cached process list)."""
    live = _embedding_finetune_live(_embedding_finetune_state()) if key == "embedding_finetune" else _live_status(key)
    return {"running": _running_pipeline_pid(_PIPELINE_JOBS[key]["script"]) is not None, "live": live}


def _snapshot_read() -> dict:
    try:
        return json.loads(_SNAPSHOT.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _snapshot_write(key: str, entry: dict):
    with _SNAPSHOT_LOCK:
        snap = _snapshot_read()
        snap[key] = {k: v for k, v in entry.items() if k not in ("running", "live")}
        snap[key]["checked_at"] = time.time()
        try:
            _SNAPSHOT.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass


def _job_status(key: str, check: bool = False) -> dict:
    """One card computed fresh (counts + running/live), saved as its last known state. With check=True it is also
    DIAGNOSED (routers/pipeline_health.py): why a stopped job is stuck, free repairs applied first (a stale worklist is
    rebuilt BEFORE counting, since the counts depend on it), an engine test call when the last run hit a limit."""
    from routers.corpus_tools import pipeline_health as _ph
    lv = _job_live(key)
    pre = _ph.repair_worklists(key, lv["running"], CORPUS_PATH) if check else None
    if pre:
        _invalidate_progress_cache(key)
    entry = _JOB_COUNTS[key]()
    if check:
        entry["health"] = _ph.diagnose(key, _PIPELINE_JOBS[key]["label"], entry, lv["running"], lv.get("live"), CORPUS_PATH, pre=pre)
    else:                                  # a plain recount keeps the last diagnosis shown
        entry["health"] = (_snapshot_read().get(key) or {}).get("health")
    _snapshot_write(key, entry)
    return {**entry, "checked_at": time.time(), **lv}


@router.get("/pipeline-status")
def pipeline_status():
    """Status of the long-running corpus background jobs, every card computed fresh (slow: use /pipeline-status/cached +
    /pipeline-status/job/{key} for the page, /pipeline-live for polling). Each job uses whichever engine is explicitly
    selected in Settings/the top dropdown (no cross-engine failover — see llm_client.call_llm's docstring)."""
    return {"jobs": {k: _job_status(k) for k in _JOB_COUNTS}}


@router.get("/pipeline-status/cached")
def pipeline_status_cached():
    """Every card's last saved counts (instant) with live running/doing; a card never checked has never_checked."""
    snap = _snapshot_read()
    jobs = {}
    for k in _JOB_COUNTS:
        base = snap.get(k) or {"label": _PIPELINE_JOBS[k]["label"], "novels": [], "done": 0, "total": 0, "never_checked": True}
        jobs[k] = {**base, **_job_live(k)}
    return {"jobs": jobs}


@router.get("/pipeline-status/job/{job_key}")
def pipeline_status_job(job_key: str, check: bool = False):
    """check=true is the card's ⟳: recount AND diagnose + repair (an engine test call may be made). Without it, a recount only."""
    if job_key not in _JOB_COUNTS:
        raise HTTPException(404, f"Unknown job '{job_key}'")
    _invalidate_progress_cache(job_key)          # the card's ⟳ means "true values now", not the 30 s cache
    return {"job": job_key, "status": _job_status(job_key, check)}


@router.get("/pipeline-live")
def pipeline_live():
    """Running + what each job is doing right now, for polling (the app-wide console log and the Pipeline page's cards)."""
    return {"jobs": {k: {"label": _PIPELINE_JOBS[k]["label"], **_job_live(k)} for k in _JOB_COUNTS}}


def _stop_pipeline_job(job_key: str) -> bool:
    """Kill the running instance of this job's script, if any. Uses taskkill
    rather than WMI's Terminate() method — confirmed live that calling
    .Terminate() on a win32com-enumerated Win32_Process object raises
    "'int' object is not callable" (late-bound COM dispatch resolves the name
    as a property, not a method, for this particular object type); taskkill
    has none of that ambiguity.

    Kills the cmd.exe WRAPPER with /T (tree-kill), not just the python.exe
    leaf — python.exe is a CHILD of the cmd.exe Win32_Process.Create launched
    (see _launch_pipeline_job), so killing only the leaf left that wrapper
    (and its now-visible console window, before the ShowWindow fix) running
    orphaned; Stop looked like it did nothing. Falls back to killing just the
    python.exe if the wrapper can't be found, rather than doing nothing.
    Returns True if something was actually running and got stopped."""
    pid = _running_pipeline_pid(_PIPELINE_JOBS[job_key]["script"], fresh=True)
    if pid is None:
        return False
    target = _cmd_wrapper_pid(pid) or pid
    result = subprocess.run(["taskkill", "/F", "/T", "/PID", str(target)],
                            capture_output=True, text=True, creationflags=0x08000000)
    if result.returncode != 0:
        raise HTTPException(500, f"Failed to stop {_PIPELINE_JOBS[job_key]['label']}: "
                                  f"{(result.stderr or result.stdout).strip()[:200]}")
    return True


class PipelineJobRequest(BaseModel):
    job: str   # "thread_typing" | "symbol_filtering"


@router.post("/pipeline-restart")
def pipeline_restart(req: PipelineJobRequest):
    """Start the job if it's stopped, or genuinely RESTART it (kill + fresh
    launch) if it's already running — e.g. after switching the engine in
    Settings, so the new engine's batch size takes effect immediately instead
    of only on the next natural process death."""
    if req.job not in _PIPELINE_JOBS:
        raise HTTPException(400, f"Unknown job '{req.job}' ({', '.join(_PIPELINE_JOBS)} only).")
    if _running_pipeline_pid(_PIPELINE_JOBS[req.job]["script"], fresh=True) is not None:
        _stop_pipeline_job(req.job)
        import time as _time
        _time.sleep(0.5)   # give the OS a moment to actually free the process before relaunching
    pid = _launch_pipeline_job(req.job)
    _invalidate_progress_cache("wmi_python_processes")   # so the status the frontend re-fetches next reflects this launch, not up to 30s of stale cache
    return {"ok": True, "pid": pid}


@router.post("/pipeline-stop")
def pipeline_stop(req: PipelineJobRequest):
    if req.job not in _PIPELINE_JOBS:
        raise HTTPException(400, f"Unknown job '{req.job}' ({', '.join(_PIPELINE_JOBS)} only).")
    stopped = _stop_pipeline_job(req.job)
    _invalidate_progress_cache("wmi_python_processes")   # so the status the frontend re-fetches next reflects this stop, not up to 30s of stale cache
    return {"ok": True, "stopped": stopped}


# ── KNOWLEDGE SEARCH — V4 Phase 4 (doc Layers 19/27/28) ─────────────────────
# Semantic search over the corpus, via local embeddings (Ollama +
# nomic-embed-text — no per-call API cost, no external vector-DB dependency).
# The index itself is built by corpus/build_knowledge_index.py into
# knowledge_index.db (novel_id/category/chapter/text/meta/embedding rows);
# this reads that SQLite file directly rather than importing the corpus
# pipeline's own knowledge_index.py module — keeps the packaged-exe/corpus-
# script boundary clean, same as every other corpus_builder.py subprocess
# call, instead of a new cross-boundary Python import.

import sqlite3 as _sqlite3
import struct as _struct
import urllib.request as _urllib_request

_KNOWLEDGE_DB = CORPUS_PATH / "knowledge_index.db"
# 127.0.0.1, NOT localhost: on Windows "localhost" resolves to IPv6 (::1) first, Ollama
# only listens on IPv4, and every connection then waits ~2s for the IPv6 attempt to fail
# (measured: 2.05s vs 0.01s per embedding call). Every semantic search paid that.
_OLLAMA_HOST = "http://127.0.0.1:11434"
_EMBED_MODEL = "nomic-embed-text"
# The corpus-fine-tuned sibling (corpus/embedding_ft/, loaded into Ollama from its
# GGUF). Every chunk carries a vector from each model; search merges their scores.
_EMBED_MODEL_TUNED = "nomic-embed-corpus"


def _embed_query(text: str, timeout: int = 30, model: str = None) -> list:
    body = json.dumps({"model": model or _EMBED_MODEL, "prompt": text[:8000]}).encode("utf-8")
    req = _urllib_request.Request(f"{_OLLAMA_HOST}/api/embeddings", data=body,
                                  headers={"Content-Type": "application/json"}, method="POST")
    with _urllib_request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    emb = data.get("embedding")
    if not emb:
        raise HTTPException(502, "Ollama returned no embedding — is it running with nomic-embed-text pulled?")
    return emb


def _unpack_vec(blob: bytes) -> list:
    n = len(blob) // 4
    return list(_struct.unpack(f"{n}f", blob))


_INDEX_CACHE = {"mtime": None, "matrix": None, "rows": None}


def _load_index_matrix():
    import numpy as np
    if not _KNOWLEDGE_DB.exists():
        return None, None
    mtime = _KNOWLEDGE_DB.stat().st_mtime
    if _INDEX_CACHE["mtime"] == mtime and _INDEX_CACHE["matrix"] is not None:
        return _INDEX_CACHE["matrix"], _INDEX_CACHE["rows"]
    conn = _sqlite3.connect(_KNOWLEDGE_DB)
    rows = conn.execute(
        "SELECT id, novel_id, novel_title, category, chapter, text, meta, embedding FROM chunks"
    ).fetchall()
    conn.close()
    if not rows:
        return None, None
    vecs = np.array([_unpack_vec(r[7]) for r in rows], dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1e-9
    vecs = vecs / norms
    _INDEX_CACHE.update(mtime=mtime, matrix=vecs, rows=rows)
    return vecs, rows


def _hybrid_enabled() -> bool:
    """Settings switch (~/.noveltea-engine/config.json -> search.hybrid_embeddings, default on)."""
    try:
        cfg = json.loads((Path.home() / ".noveltea-engine" / "config.json").read_text(encoding="utf-8-sig"))
        return bool((cfg.get("search") or {}).get("hybrid_embeddings", True))
    except Exception:
        return True


_TUNED_CACHE = {"mtime": None, "matrix": None, "has": None}


def _load_tuned_matrix():
    """(matrix_t, has_t): the fine-tuned model's normalized vectors aligned to the
    base matrix's row order, plus a per-row 'has a tuned vector' mask. (None, None)
    when the column doesn't exist yet or the index was built by different models
    than the ones this code would embed the query with — comparing vectors across
    models is meaningless and both are 768-dim, so a mismatch would fail silently."""
    import numpy as np
    matrix, rows = _load_index_matrix()
    if matrix is None:
        return None, None
    mtime = _INDEX_CACHE["mtime"]
    if _TUNED_CACHE["mtime"] == mtime and _TUNED_CACHE["matrix"] is not None:
        return _TUNED_CACHE["matrix"], _TUNED_CACHE["has"]
    try:
        conn = _sqlite3.connect(_KNOWLEDGE_DB)
        meta = dict(conn.execute("SELECT key, value FROM index_meta").fetchall())
        if meta.get("embedding_model") != _EMBED_MODEL or meta.get("embedding_tuned_model") != _EMBED_MODEL_TUNED:
            conn.close()
            return None, None
        tuned = dict(conn.execute("SELECT id, embedding_tuned FROM chunks WHERE embedding_tuned IS NOT NULL").fetchall())
        conn.close()
    except Exception:
        return None, None
    dim = matrix.shape[1]
    mt = np.zeros((len(rows), dim), dtype=np.float32)
    has = np.zeros(len(rows), dtype=bool)
    for i, r in enumerate(rows):
        blob = tuned.get(r[0])
        if blob is not None:
            mt[i] = np.frombuffer(blob, dtype=np.float32)
            has[i] = True
    norms = np.linalg.norm(mt, axis=1, keepdims=True)
    norms[norms == 0] = 1e-9
    mt /= norms
    _TUNED_CACHE.update(mtime=mtime, matrix=mt, has=has)
    return mt, has


def _fuse_with_tuned(base_sims, eligible, query_text: str):
    """Merge the base model's similarities with the fine-tuned model's.

    Each model's scores are z-scored over the candidate pool, averaged, then mapped back
    onto the BASE model's score scale — so everything downstream that was tuned to cosine
    values (the chapter-proximity boost, score displays) keeps working unchanged. The two
    models return quite different top results (measured: ~1 of the top 5 in common), so
    averaging their z-scores rewards material both agree on and dilutes a chunk that only
    one model likes (the tuned model alone showed a 'hub' chunk that matched unrelated
    queries).

    Returns base_sims untouched whenever hybrid can't be trusted for THIS query: setting
    off, model-mismatch guard tripped, any candidate row still lacking a tuned vector
    (e.g. while the backfill runs), or the tuned model not answering.
    eligible: array of row indexes base_sims corresponds to, or None for all rows."""
    import numpy as np
    if not _hybrid_enabled():
        return base_sims
    matrix_t, has_t = _load_tuned_matrix()
    if matrix_t is None:
        return base_sims
    covered = has_t.all() if eligible is None else has_t[eligible].all()
    if not covered:
        return base_sims
    try:
        qt = np.array(_embed_query(query_text, model=_EMBED_MODEL_TUNED), dtype=np.float32)
    except Exception:
        return base_sims
    qn = np.linalg.norm(qt)
    if qn == 0:
        return base_sims
    tuned_sims = (matrix_t if eligible is None else matrix_t[eligible]) @ (qt / qn)
    sb, st = float(base_sims.std()), float(tuned_sims.std())
    if sb < 1e-9 or st < 1e-9:
        return base_sims
    z = ((base_sims - base_sims.mean()) / sb + (tuned_sims - tuned_sims.mean()) / st) / 2.0
    return (base_sims.mean() + sb * z).astype(np.float32)


_PROXIMITY_WINDOW = 20   # chapters — how far a chunk's source chapter can be from
                         # current_chapter before its proximity boost hits zero
_PROXIMITY_WEIGHT = 0.12 # kept small deliberately: a modest tie-breaker/boost,
                         # never enough to override a genuinely better semantic
                         # match from a chapter far away (author's explicit call —
                         # "blend both" rather than a hard chapter-window filter)


# Categories a search returns only when it names them (category="humor"). Keeps an
# unfiltered search (chapter prompts' corpus grounding) exactly as it was before
# they were indexed. Mirrors corpus/knowledge_index.py's OPT_IN_CATEGORIES.
_OPT_IN_CATEGORIES = ("humor", "mechanics")


def _default_search_rows(rows):
    """Row indexes an unfiltered search ranks (every row outside the opt-in
    categories), cached per loaded index; None when the index has no opt-in rows."""
    import numpy as np
    if _INDEX_CACHE.get("visible_mtime") != _INDEX_CACHE["mtime"]:
        idx = [i for i, r in enumerate(rows) if r[3] not in _OPT_IN_CATEGORIES]
        _INDEX_CACHE["visible"] = None if len(idx) == len(rows) else np.array(idx, dtype=np.int64)
        _INDEX_CACHE["visible_mtime"] = _INDEX_CACHE["mtime"]
    return _INDEX_CACHE["visible"]


def _prose_type_rows(rows, types=None):
    """{prose sample type: row indexes} for the loaded index (cached per load), or,
    given types, the sorted row indexes of those types as an array."""
    import numpy as np
    if _INDEX_CACHE.get("prose_mtime") != _INDEX_CACHE["mtime"]:
        by = {}
        for i, r in enumerate(rows):
            if r[3] == "prose":
                try:
                    t = (json.loads(r[6]) or {}).get("type") if r[6] else None
                except Exception:
                    t = None
                by.setdefault(t, []).append(i)
        _INDEX_CACHE.update(prose_types=by, prose_mtime=_INDEX_CACHE["mtime"])
    by = _INDEX_CACHE["prose_types"]
    if types is None:
        return by
    return np.array(sorted(i for t in types for i in by.get(t, [])), dtype=np.int64)


def prose_type_counts(types) -> dict:
    """How many indexed prose samples of each type there are (the Combat tab's search)."""
    matrix, rows = _load_index_matrix()
    if matrix is None:
        return {t: 0 for t in types}
    by = _prose_type_rows(rows)
    return {t: len(by.get(t, [])) for t in types}


def knowledge_search(query_text: str, top_k: int = 8, category: str = None, current_chapter: int = None,
                      novel_id: str = None, prose_types: list = None, chapter_from: int = None,
                      chapter_to: int = None) -> list:
    """Shared by the /knowledge-search endpoint AND generation-time grounding
    (generate.py's semantic corpus sampling, Dialogue Shaping) — one search
    implementation, two callers.

    current_chapter: when given, blends a chapter-proximity boost into the
    ranking — a chunk whose source chapter is near current_chapter (e.g. this
    story's chapter 3 favoring corpus material from around chapter 1-5 of any
    novel) ranks slightly higher than an equally-similar chunk from far away
    in that novel's story. Pure semantic similarity still dominates — this
    only reorders a wider candidate pool, it never filters anything out, and
    chunks with no chapter info (dialogue lines, etc.) just get zero boost
    rather than being penalized.

    novel_id: exact-match filter on the row's novel_id column — REQUIRED use
    case is category="project_system" (see build_project_systems_index.py),
    where novel_id holds the owning project_id and an unfiltered search would
    leak one project's power levels/relationships/etc. into another
    project's chapter prompt. Widens pool_size the same way category does,
    for the same reason: a single project's items are a small slice of the
    whole table and can easily fall outside an unfiltered top-N window.

    chapter_from / chapter_to: only chunks whose source chapter is in that range (either end may be left open).
    A chunk with no chapter is left out whenever a range is given. Filtered before ranking, like category."""
    import numpy as np
    matrix, rows = _load_index_matrix()
    if matrix is None:
        return []
    qvec = np.array(_embed_query(query_text), dtype=np.float32)
    qnorm = np.linalg.norm(qvec)
    if qnorm == 0:
        return []
    qvec = qvec / qnorm

    # FILTER BEFORE RANKING, not rank-then-filter — confirmed live this was a
    # real bug, not just a theoretical edge case: rank-then-filter took the
    # top pool_size*3 rows by raw cosine similarity ACROSS THE WHOLE MATRIX
    # first, then discarded everything outside the requested category. With
    # prose+dialogue alone making up ~74% of the ~66k-row matrix, a category
    # filter's own genuinely relevant rows routinely ranked in the
    # thousands — e.g. a real query's first "pattern" hit ranked #1452 and
    # first "blueprint" hit ranked #2102, both far outside even the widened
    # 900-row (pool_size=300 * 3) window, so category-filtered search
    # returned ZERO results despite good matches existing in the index.
    # Restricting the similarity computation to only the candidate rows
    # (category and/or novel_id) BEFORE computing top-K fixes this
    # correctly — the ranked pool is then 100% eligible rows, not a diluted
    # slice of the full matrix — and is cheaper too (smaller matmul).
    pool_size = max(top_k * 5, 40) if current_chapter is not None else top_k
    ranged = chapter_from is not None or chapter_to is not None

    def _in_range(ch):
        if not ranged:
            return True
        if ch is None:
            return False
        return (chapter_from is None or ch >= chapter_from) and (chapter_to is None or ch <= chapter_to)
    if prose_types:
        # Labelled prose samples of the given types only (combat_reaction, dialogue_threat...).
        eligible = _prose_type_rows(rows, prose_types)
        if ranged:
            eligible = np.array([i for i in eligible if _in_range(rows[i][4])], dtype=np.int64)
        if len(eligible) == 0:
            return []
        sims = np.zeros(len(rows), dtype=np.float32)
        sims[eligible] = _fuse_with_tuned(matrix[eligible] @ qvec, eligible, query_text)
        sub_order = np.argsort(-sims[eligible])[:min(len(eligible), pool_size * 3)]
        order = eligible[sub_order]
    elif category is not None or novel_id is not None or ranged:
        default_rows = None if category is not None else _default_search_rows(rows)
        default_set = set(default_rows.tolist()) if default_rows is not None else None
        eligible = np.array([i for i, r in enumerate(rows)
                             if (category is None or r[3] == category)
                             and (novel_id is None or r[1] == novel_id)
                             and _in_range(r[4])
                             and (default_set is None or i in default_set)], dtype=np.int64)
        if len(eligible) == 0:
            return []
        # Only matmul the eligible rows — cheaper than the full matrix, and
        # correct: `sims` stays indexed by the ORIGINAL row position (via
        # eligible[...]) so the sims[i] lookups in the loop below still work
        # unchanged for both this branch and the unfiltered one.
        sims = np.zeros(len(rows), dtype=np.float32)
        # Base + fine-tuned model merged (falls back to base alone when it can't be trusted — see _fuse_with_tuned)
        sims[eligible] = _fuse_with_tuned(matrix[eligible] @ qvec, eligible, query_text)
        sub_order = np.argsort(-sims[eligible])[:min(len(eligible), pool_size * 3)]
        order = eligible[sub_order]
    elif _default_search_rows(rows) is None:
        sims = _fuse_with_tuned(matrix @ qvec, None, query_text)
        order = np.argsort(-sims)[:min(len(sims), pool_size * 3)]
    else:
        # Opt-in categories (humor) sit outside an unfiltered search, so the rows it
        # ranks, and the pool the hybrid fusion normalises over, are exactly what
        # they were before those categories were indexed.
        eligible = _default_search_rows(rows)
        sims = np.zeros(len(rows), dtype=np.float32)
        sims[eligible] = _fuse_with_tuned(matrix[eligible] @ qvec, eligible, query_text)
        sub_order = np.argsort(-sims[eligible])[:min(len(eligible), pool_size * 3)]
        order = eligible[sub_order]
    candidates = []
    # Fuzzy near-duplicate filter — the corpus has thousands of genuinely
    # duplicate/near-duplicate rows (short generic lines like "Yes!" or
    # "Next!" re-extracted across many chapters/novels, plus paraphrased
    # variants that differ by only a word or a name) that rarely surfaced at
    # small top_k but became visible once callers started asking for more
    # results: near-identical lines filling several returned slots instead of
    # genuinely distinct passages. A plain exact-text check only catches
    # perfect duplicates, so this compares word-bigram shingle sets between
    # each candidate and every ALREADY-ACCEPTED one via Jaccard similarity —
    # catches "same line, one word changed" without needing an extra
    # embedding call or dependency. Kept to the accepted set only (bounded by
    # pool_size, not the whole candidate pool) so the O(n^2) comparison stays
    # cheap even at top_k=24+.
    accepted_shingles = []   # list of shingle sets for already-accepted candidates
    _DEDUP_JACCARD_THRESHOLD = 0.7

    def _shingles(s: str) -> set:
        words = s.split()
        if len(words) < 2:
            return {s} if s else set()
        return {f"{words[i]} {words[i+1]}" for i in range(len(words) - 1)}

    for i in order:
        row = rows[i]
        _id, row_novel_id, novel_title, cat, chapter, text, meta_json, _ = row
        if category and cat != category:
            continue
        if novel_id is not None and row_novel_id != novel_id:
            continue
        norm_text = " ".join((text or "").split()).lower()
        cand_shingles = _shingles(norm_text)
        is_near_dup = False
        if cand_shingles:
            for prior_shingles in accepted_shingles:
                union = cand_shingles | prior_shingles
                if not union:
                    continue
                jaccard = len(cand_shingles & prior_shingles) / len(union)
                if jaccard >= _DEDUP_JACCARD_THRESHOLD:
                    is_near_dup = True
                    break
        if is_near_dup:
            continue
        accepted_shingles.append(cand_shingles)
        sim = float(sims[i])
        if current_chapter is not None and chapter is not None:
            proximity = max(0.0, 1.0 - abs(chapter - current_chapter) / _PROXIMITY_WINDOW)
        else:
            proximity = 0.0
        candidates.append({
            "novel_id": row_novel_id, "novel_title": novel_title, "category": cat,
            "chapter": chapter, "text": text,
            "meta": json.loads(meta_json) if meta_json else {},
            "score": sim + _PROXIMITY_WEIGHT * proximity,
            "semantic_score": sim,
        })
        if len(candidates) >= pool_size:
            break
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates[:top_k]


class KnowledgeSearchRequest(BaseModel):
    query: str
    top_k: int = 8
    category: Optional[str] = None   # "reveal" | "scheme" | "symbol" | "glossary" | "prose" | "dialogue" | "mechanics" ...
    novel_id: Optional[str] = None
    chapter_from: Optional[int] = None   # source-chapter range; either end may be left open
    chapter_to: Optional[int] = None


@router.post("/knowledge-search")
def knowledge_search_endpoint(req: KnowledgeSearchRequest):
    if not req.query.strip():
        raise HTTPException(400, "query is required.")
    if not _KNOWLEDGE_DB.exists():
        raise HTTPException(404, "Knowledge index not built yet — run corpus/build_knowledge_index.py first.")
    try:
        results = knowledge_search(req.query.strip(), top_k=max(1, min(req.top_k, 50)), category=req.category,
                                   novel_id=req.novel_id or None, chapter_from=req.chapter_from, chapter_to=req.chapter_to)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Knowledge search failed: {str(e)[:200]}")
    return {"query": req.query, "results": results}

