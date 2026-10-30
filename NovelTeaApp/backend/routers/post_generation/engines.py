import sys
import os
import json
import subprocess
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from config import NOVELS_PATH, CORPUS_PATH

router = APIRouter()

SCRIPTS_DIR = CORPUS_PATH.parent / "NovelTea Engine"

# Force UTF-8 for all child processes regardless of Windows console codepage
_SCRIPT_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}


def run_script(script: str, args: list) -> dict:
    script_path = SCRIPTS_DIR / script
    if not script_path.exists():
        raise HTTPException(404, f"Script {script} not found at {script_path}")
    result = subprocess.run(
        [sys.executable, str(script_path)] + args,
        capture_output=True, text=True, encoding="utf-8",
        cwd=str(SCRIPTS_DIR), env=_SCRIPT_ENV,
    )
    if result.returncode != 0:
        raise HTTPException(500, f"Script failed: {result.stderr}")
    return {"stdout": result.stdout, "stderr": result.stderr}


class PlanRequest(BaseModel):
    novel_id: str
    chapter_number: int
    arc_override: str = None
    function_override: str = None


class GenerateRequest(BaseModel):
    novel_id: str
    chapter_number: int
    use_existing_plan: bool = False


class ExtractRequest(BaseModel):
    novel_id: str
    start_chapter: int
    end_chapter: int


class ValidateRequest(BaseModel):
    novel_id: str


@router.post("/plan")
def plan_chapter(req: PlanRequest):
    """Run planner.py to create a chapter plan."""
    args = [req.novel_id, str(req.chapter_number)]
    if req.arc_override:
        args += ["--arc", req.arc_override]
    if req.function_override:
        args += ["--function", req.function_override]
    result = run_script("planner.py", args)

    # Try to return the generated plan file
    plan_path = NOVELS_PATH / req.novel_id / f"plan_ch{req.chapter_number}.json"
    if plan_path.exists():
        with open(plan_path, encoding="utf-8") as f:
            return {"plan": json.load(f), "logs": result["stdout"]}
    return {"plan": None, "logs": result["stdout"]}


@router.post("/generate")
def generate_chapter(req: GenerateRequest):
    """Run generator.py to write a chapter."""
    args = ["--novel", req.novel_id, "--chapter", str(req.chapter_number)]
    result = run_script("generator.py", args)

    # Return path to generated file
    gen_path = CORPUS_PATH / "generated" / req.novel_id / f"ch{req.chapter_number:03d}_generated.txt"
    generated_text = None
    if gen_path.exists():
        with open(gen_path, encoding="utf-8") as f:
            generated_text = f.read()

    return {"text": generated_text, "logs": result["stdout"]}


@router.post("/extract")
def extract_chapters(req: ExtractRequest):
    """Run extract_v3.py for a range of chapters."""
    args = ["--novel", req.novel_id, "--start", str(req.start_chapter), "--end", str(req.end_chapter)]
    result = run_script("extract_v3.py", args)
    return {"logs": result["stdout"], "errors": result["stderr"]}


@router.post("/validate")
def validate_novel(req: ValidateRequest):
    """Run validate.py to check continuity."""
    args = [req.novel_id]
    result = run_script("validate.py", args)

    # Parse conflict report if it exists
    conflicts_path = NOVELS_PATH / req.novel_id / "conflicts.json"
    conflicts = None
    if conflicts_path.exists():
        with open(conflicts_path, encoding="utf-8") as f:
            conflicts = json.load(f)

    return {"conflicts": conflicts, "logs": result["stdout"]}


@router.get("/plan/{novel_id}/{chapter_number}")
def get_plan(novel_id: str, chapter_number: int):
    """Retrieve an existing chapter plan."""
    plan_path = NOVELS_PATH / novel_id / f"plan_ch{chapter_number}.json"
    if not plan_path.exists():
        raise HTTPException(404, f"No plan found for chapter {chapter_number}")
    with open(plan_path, encoding="utf-8") as f:
        return json.load(f)


@router.get("/generated/{novel_id}")
def list_generated(novel_id: str):
    """List all generated chapters for a novel."""
    gen_dir = CORPUS_PATH / "generated" / novel_id
    if not gen_dir.exists():
        return {"chapters": []}
    chapters = []
    for f in sorted(gen_dir.glob("ch*_generated.txt")):
        try:
            num = int(f.stem.split("_")[0][2:])
        except Exception:
            num = 0
        # Check if influences file exists alongside
        has_influences = (gen_dir / f.name.replace("_generated.txt", "_influences.json")).exists()
        chapters.append({"number": num, "filename": f.name, "size": f.stat().st_size, "has_influences": has_influences})
    return {"chapters": chapters}


@router.get("/generated/{novel_id}/{chapter_number}/influences")
def get_influences(novel_id: str, chapter_number: int):
    """Return corpus influences for a generated chapter."""
    inf_path = CORPUS_PATH / "generated" / novel_id / f"ch{chapter_number:03d}_influences.json"
    if not inf_path.exists():
        return {"influences": []}
    with open(inf_path, encoding="utf-8") as f:
        return {"influences": json.load(f)}


# ── Chapter versions: regenerating a chapter archives the old text into
#    _versions/chNNN_vK.txt; these endpoints list / read / restore them. ──

def _versions_dir(novel_id: str) -> Path:
    return CORPUS_PATH / "generated" / novel_id / "_versions"


@router.get("/generated/{novel_id}/{chapter_number}/versions")
def list_chapter_versions(novel_id: str, chapter_number: int):
    import re, time
    vdir = _versions_dir(novel_id)
    out = []
    if vdir.exists():
        for f in vdir.glob(f"ch{chapter_number:03d}_v*.txt"):
            m = re.search(r"_v(\d+)\.txt$", f.name)
            if not m:
                continue
            st = f.stat()
            out.append({"v": int(m.group(1)), "size": st.st_size,
                        "words": st.st_size // 5,
                        "modified": time.strftime("%m-%d %H:%M", time.localtime(st.st_mtime))})
    out.sort(key=lambda x: -x["v"])
    return {"versions": out}


@router.delete("/generated/{novel_id}/{chapter_number}/versions")
def clear_chapter_versions(novel_id: str, chapter_number: int):
    """Delete every archived version of one chapter. The current text is
    untouched; only the _versions/chNNN_vK.txt copies go."""
    vdir = _versions_dir(novel_id)
    removed = 0
    if vdir.exists():
        for f in vdir.glob(f"ch{chapter_number:03d}_v*.txt"):
            f.unlink(missing_ok=True)
            removed += 1
    return {"ok": True, "removed": removed}


@router.get("/generated/{novel_id}/{chapter_number}/version/{v}")
def get_chapter_version(novel_id: str, chapter_number: int, v: int):
    p = _versions_dir(novel_id) / f"ch{chapter_number:03d}_v{v}.txt"
    if not p.exists():
        raise HTTPException(404, f"Chapter {chapter_number} v{v} not found")
    return {"chapter": chapter_number, "v": v, "text": p.read_text(encoding="utf-8")}


@router.post("/generated/{novel_id}/{chapter_number}/version/{v}/restore")
def restore_chapter_version(novel_id: str, chapter_number: int, v: int):
    """Make an archived version current. The current text is archived first,
    so restoring is itself undoable."""
    import shutil
    vdir = _versions_dir(novel_id)
    src = vdir / f"ch{chapter_number:03d}_v{v}.txt"
    if not src.exists():
        raise HTTPException(404, f"Chapter {chapter_number} v{v} not found")
    gen_path = CORPUS_PATH / "generated" / novel_id / f"ch{chapter_number:03d}_generated.txt"
    archived = None
    if gen_path.exists():
        vdir.mkdir(exist_ok=True)
        archived = len(list(vdir.glob(f"ch{chapter_number:03d}_v*.txt"))) + 1
        shutil.move(str(gen_path), str(vdir / f"ch{chapter_number:03d}_v{archived}.txt"))
    shutil.copy2(src, gen_path)
    try:
        from routers.generation.generate import _index_chapter_async
        _index_chapter_async(novel_id, chapter_number)
    except Exception:
        pass
    return {"ok": True, "restored": v, "previous_archived_as": archived}


@router.get("/generated/{novel_id}/{chapter_number}")
def get_generated(novel_id: str, chapter_number: int):
    """Retrieve a generated chapter."""
    gen_path = CORPUS_PATH / "generated" / novel_id / f"ch{chapter_number:03d}_generated.txt"
    if not gen_path.exists():
        raise HTTPException(404, f"No generated chapter {chapter_number} found")
    with open(gen_path, encoding="utf-8") as f:
        return {"chapter": chapter_number, "text": f.read()}


class SaveChapterRequest(BaseModel):
    text: str


@router.post("/generated/{novel_id}/{chapter_number}/save")
def save_generated(novel_id: str, chapter_number: int, req: SaveChapterRequest):
    """Save edited chapter text back to disk."""
    gen_dir = CORPUS_PATH / "generated" / novel_id
    gen_dir.mkdir(parents=True, exist_ok=True)
    gen_path = gen_dir / f"ch{chapter_number:03d}_generated.txt"
    # Any narration audio was synthesized from the PREVIOUS text — once the
    # text changes (e.g. after Shorten or a manual edit), that audio no
    # longer matches and would otherwise keep being served as-is by
    # narrate-status's auto-restore. Confirmed live: a chapter shortened from
    # 3553 to 1865 words still had Aug-10 audio from an even earlier draft
    # sitting there, silently mismatched. Only delete on an ACTUAL change —
    # a no-op save (re-submitting identical text) shouldn't cost the audio.
    old_text = gen_path.read_text(encoding="utf-8") if gen_path.exists() else None
    with open(gen_path, "w", encoding="utf-8") as f:
        f.write(req.text)
    if old_text is not None and old_text != req.text:
        audio_path = gen_dir / f"ch{chapter_number:03d}_audio.wav"
        audio_path.unlink(missing_ok=True)
    if old_text != req.text:
        try:      # a new version of the chapter: it re-indexes itself (nomic) in the background
            from routers.generation.generate import _index_chapter_async
            _index_chapter_async(novel_id, chapter_number)
        except Exception:
            pass
    return {"ok": True, "chapter": chapter_number, "size": len(req.text)}


@router.delete("/generated/{novel_id}/{chapter_number}")
def delete_generated(novel_id: str, chapter_number: int):
    """ABSOLUTE delete for a generated chapter's TEXT — removes every trace of what was written, all its versions
    included, but NOT its plan (chapter_skeletons and the arcs' chapter lists stay). Confirmed live this was NOT the
    case before: project.json's chapters_written,
    discovery_scanned, and every chapter-tagged entry in facts_log/
    location_map/critique_notes/revision_checklist all silently kept
    referencing a chapter number whose files no longer existed — a real
    project ended up with chapters_written=3 and only 2 chapter files on
    disk. Also fixes a second, separate bug: the .bak filename pattern
    checked here (_generated.bak.txt) never matched the ACTUAL suffix order
    files on disk use (_generated.txt.bak) — that file was never actually
    being cleaned up.

    Deliberately does NOT touch character_list/systems/world_bible entities
    whose first_chapter equals this chapter — those are real story content
    Discovery pulled out of the chapter's prose; deleting the chapter's
    generated text shouldn't retroactively delete a character or technique
    that may still matter to the story or get referenced by a later,
    still-existing chapter (author's explicit call)."""
    gen_dir = CORPUS_PATH / "generated" / novel_id
    prefix = f"ch{chapter_number:03d}"

    deleted = []
    for suffix in ["_generated.txt", "_generated.txt.bak", "_generated.bak.txt", "_influences.json", "_audio.wav",
                   "_parts.json", "_voice.json"]:
        p = gen_dir / f"{prefix}{suffix}"
        if p.exists():
            p.unlink()
            deleted.append(p.name)

    # Any narration audio of this chapter, whatever its exact name (ch{N}_audio.wav, ch{N}_audio_*.wav/.mp3, ...)
    for p in gen_dir.glob(f"{prefix}_audio*"):
        if p.is_file() and p.name not in deleted:
            p.unlink()
            deleted.append(p.name)

    # Version archive — every "ch{N}_v*.txt" (plus the BROKEN_*/pre_split_*
    # style one-off archive names this project has accumulated) belongs to
    # THIS chapter number specifically and has no reason to survive it being
    # deleted. Matched by prefix, not an exact suffix list, since archive
    # naming has grown ad-hoc over time (v1..v11, _pre_split, _BROKEN_*).
    versions_dir = gen_dir / "_versions"
    if versions_dir.exists():
        for p in versions_dir.glob(f"{prefix}_*"):
            p.unlink()
            deleted.append(f"_versions/{p.name}")

    # Remove from chapter_summaries.json
    summaries_file = CORPUS_PATH / "projects" / novel_id / "chapter_summaries.json"
    if summaries_file.exists():
        try:
            with open(summaries_file, encoding="utf-8") as f:
                summ = json.load(f)
            summ = [s for s in summ if s.get("chapter") != chapter_number]
            with open(summaries_file, "w", encoding="utf-8") as f:
                json.dump(summ, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    # Everything else lives in project.json — one read/patch/write covers
    # every chapter-tagged field the rest of the app has grown over time,
    # rather than hand-listing them here and drifting out of sync again the
    # next time a new one is added.
    cleaned_fields = []
    project_file = CORPUS_PATH / "projects" / novel_id / "project.json"
    if project_file.exists():
        try:
            with open(project_file, encoding="utf-8") as f:
                project = json.load(f)

            # Simple chapter-tagged lists: drop any entry whose "chapter" key
            # matches. Every one of these is optional/lazily-created, so a
            # missing key is a no-op, not an error.
            for field in ("facts_log", "location_map", "facts_contradictions",
                         "location_map_contradictions", "revision_checklist", "critique_notes"):
                items = project.get(field)
                if isinstance(items, list):
                    before = len(items)
                    items = [it for it in items if not (isinstance(it, dict) and it.get("chapter") == chapter_number)]
                    if len(items) != before:
                        project[field] = items
                        cleaned_fields.append(field)

            # The chapter's PLAN is deliberately kept: chapter_skeletons and each arc's chapter list describe what the
            # chapter should be, not the text that was written. Deleting a chapter (the bin in the Reader) used to remove
            # them too, which left a chapter with no plan to write it from again (reported 2026-10-07: "it ended up
            # deleting the chapter skeleton as well"). Only the written text and everything derived from it goes.

            # discovery_scanned is a dict keyed by chapter number AS A STRING
            # (JSON object keys are always strings) — pop, don't filter.
            disc = project.get("discovery_scanned")
            if isinstance(disc, dict) and str(chapter_number) in disc:
                disc.pop(str(chapter_number), None)
                project["discovery_scanned"] = disc
                cleaned_fields.append("discovery_scanned")

            # chapters_written is a bare COUNT, not a list — the only value
            # that's actually correct after a delete is however many chapter
            # files genuinely remain on disk, not "count - 1" (a delete of a
            # chapter that was never the most recent, or a project that was
            # already drifted before this fix existed, both make blind
            # decrementing wrong). Recompute from the real files.
            remaining = 0
            if gen_dir.exists():
                remaining = sum(1 for _ in gen_dir.glob("ch*_generated.txt"))
            if project.get("chapters_written") != remaining:
                project["chapters_written"] = remaining
                cleaned_fields.append("chapters_written")

            if cleaned_fields:
                with open(project_file, "w", encoding="utf-8") as f:
                    json.dump(project, f, indent=2, ensure_ascii=False)
        except Exception:
            pass  # project.json cleanup is best-effort — the chapter's own files are already gone either way

    return {"ok": True, "deleted": deleted, "cleaned_fields": cleaned_fields}
