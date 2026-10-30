import json
import uuid
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional
from config import CORPUS_PATH, BUNDLED_CORPUS

router = APIRouter()

_COVER_EXTS = {"jpg", "jpeg", "png", "webp", "gif"}

PROJECTS_FILE = CORPUS_PATH / "projects" / "registry.json"


def _load() -> list:
    if not PROJECTS_FILE.exists():
        PROJECTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        return []
    with open(PROJECTS_FILE, encoding="utf-8-sig") as f:
        data = json.load(f)
    return data if isinstance(data, list) else data.get("projects", [])


def _save(projects: list):
    PROJECTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROJECTS_FILE, "w", encoding="utf-8") as f:
        json.dump(projects, f, indent=2, ensure_ascii=False)


def _project_dir(project_id: str) -> Path:
    return CORPUS_PATH / "projects" / project_id


# Same recycle-bin root/TTL generate.py's interactive-session recycling uses
# (CORPUS_PATH / "_recycle_bin", 30-day sweep) — that sweep already walks every
# category subfolder generically, so a new "chapter_skeletons" category here gets
# the same 30-day auto-purge for free, no changes needed on that side. Added after
# a real incident: the plain chapter-delete button (this endpoint, via the Chapter
# Skeleton tab's "✕" button) has no undo at all — it overwrites project.json
# directly — and a stray click silently destroyed a freshly, correctly-generated
# chapter skeleton with zero trace anywhere, recovered only by luck from an
# unrelated interactive-session recycle bin entry. This makes that recoverable
# by design instead of by luck.
_RECYCLE_BIN_DIR = CORPUS_PATH / "_recycle_bin"


def _recycle_removed_chapters(project_id: str, old_chapters: list, new_chapters: list):
    """Diff old vs new chapter_skeletons by `number` and stash any chapter that
    disappeared into the recycle bin as its own JSON file — covers the delete
    button and any bulk replace that drops entries, but never an edit (the
    chapter's number stays present either way, so it's not treated as removed)."""
    if not isinstance(old_chapters, list) or not isinstance(new_chapters, list):
        return
    new_numbers = {c.get("number") for c in new_chapters if isinstance(c, dict)}
    removed = [c for c in old_chapters if isinstance(c, dict) and c.get("number") not in new_numbers]
    if not removed:
        return
    import time as _time
    bin_dir = _RECYCLE_BIN_DIR / "chapter_skeletons"
    bin_dir.mkdir(parents=True, exist_ok=True)
    ts = _time.strftime("%Y%m%d_%H%M%S")
    for ch in removed:
        name = f"{ts}_{project_id}_ch{ch.get('number', 'unknown')}_{uuid.uuid4().hex[:8]}.json"
        try:
            with open(bin_dir / name, "w", encoding="utf-8") as f:
                json.dump(ch, f, indent=2, ensure_ascii=False)
        except Exception:
            pass


def _compute_project_health(project: dict) -> dict:
    """Compute planning_health and planning_progress from actual project content."""
    brief = project.get("creative_brief", {})
    arcs = project.get("arcs", [])
    chapters = project.get("chapter_skeletons", [])
    characters = project.get("character_list", [])
    world = project.get("world_bible", {})
    re = brief.get("reader_experience", {})
    themes = brief.get("themes", [])
    premise = brief.get("premise", "")

    # ── World Depth ──────────────────────────────────────────────────────────
    # Full score needs: world name, power tiers, factions, locations, rules
    world_score = 0
    if world.get("world_name"): world_score += 20
    if world.get("power_tiers") and len(world.get("power_tiers", [])) >= 2: world_score += 20
    if world.get("factions") and len(world.get("factions", [])) >= 2: world_score += 20
    if world.get("key_locations") and len(world.get("key_locations", [])) >= 2: world_score += 20
    if world.get("rules") and len(world.get("rules", [])) >= 2: world_score += 20

    # ── Character Depth ───────────────────────────────────────────────────────
    # Full score needs: 4+ characters with role + motivation + archetype
    if len(characters) == 0:
        char_score = 0
    else:
        detailed = sum(1 for c in characters if c.get("role") and c.get("motivation") and c.get("archetype"))
        char_score = min(100, int(detailed / max(1, len(characters)) * 100))
        if len(characters) >= 4: char_score = min(100, char_score + 20)

    # ── Arc Pacing ───────────────────────────────────────────────────────────
    # Full: 3+ arcs with chapters assigned; extra credit for 5+ arcs
    arc_score = 0
    if len(arcs) >= 1: arc_score = 40
    if len(arcs) >= 3: arc_score = 70
    arcs_with_chapters = sum(1 for a in arcs if a.get("chapters") and len(a.get("chapters", [])) > 0)
    if arcs_with_chapters >= 3: arc_score = min(100, arc_score + 30)

    # ── Power Scaling ────────────────────────────────────────────────────────
    # Full: power tiers defined with names + ranks; system description exists
    power_score = 0
    tiers = world.get("power_tiers", [])
    if len(tiers) >= 2: power_score = 40
    if len(tiers) >= 4: power_score = 70
    if project.get("power_system"): power_score = min(100, power_score + 30)

    # ── Mystery Density ──────────────────────────────────────────────────────
    # Proxy: reader_experience mystery score + schemes/mysteries in story_state
    mystery_rx = re.get("mystery", 0)
    state = project.get("story_state", {})
    open_mysteries = state.get("open_mysteries", 0)
    mystery_score = min(100, int(mystery_rx * 8) + min(20, open_mysteries * 10))

    # ── Comedy Balance ───────────────────────────────────────────────────────
    comedy_rx = re.get("comedy", 0)
    comedy_score = min(100, int(comedy_rx * 10))

    # ── Theme Consistency ────────────────────────────────────────────────────
    theme_score = 0
    if len(themes) >= 1: theme_score = 40
    if len(themes) >= 3: theme_score = 70
    if len(themes) >= 5: theme_score = 90
    if premise and len(themes) >= 3:
        theme_score = min(100, theme_score + 10)

    # ── Reader Hooks ─────────────────────────────────────────────────────────
    # Chapter skeletons with defined tension/hook; chapter count completeness
    target = project.get("target_chapters", 350)
    skeleton_pct = min(100, int(len(chapters) / max(1, target) * 100))
    hooked = sum(1 for c in chapters if c.get("tension") or c.get("hook") or c.get("key_event"))
    hook_quality = int(hooked / max(1, len(chapters)) * 100) if chapters else 0
    hook_score = min(100, int(skeleton_pct * 0.4 + hook_quality * 0.6))

    health = {
        "world_depth":        world_score,
        "character_depth":    char_score,
        "arc_pacing":         arc_score,
        "power_scaling":      power_score,
        "mystery_density":    mystery_score,
        "comedy_balance":     comedy_score,
        "theme_consistency":  theme_score,
        "reader_hooks":       hook_score,
    }

    # ── Planning Progress ────────────────────────────────────────────────────
    # 7 milestones worth ~14% each:
    has_premise    = bool(premise and len(premise) > 20)
    has_themes     = len(themes) >= 3
    has_arcs       = len(arcs) >= 3
    has_skeletons  = len(chapters) >= 10
    has_characters = len(characters) >= 4
    has_world      = world_score >= 60
    has_tagline    = bool(project.get("tagline", "").strip())

    milestone_pct = sum([has_premise, has_themes, has_arcs, has_skeletons, has_characters, has_world, has_tagline])
    planning_progress = round(milestone_pct / 7 * 100)

    overall_health = round(sum(health.values()) / len(health))

    return {
        "planning_health": health,
        "planning_progress": planning_progress,
        "health_score": overall_health,
    }


class CreateProjectRequest(BaseModel):
    id: Optional[str] = None
    title: str
    subtitle: Optional[str] = ""
    genre: str = "Cultivation, Fantasy"
    subgenres: list[str] = []
    genre_tags: list[str] = []
    audience: str = "16+"
    target_chapters: int = 350
    pov: str = "3rd Person Limited"
    status: str = "Planning"
    cover_emoji: str = "⚡"
    cover_gradient: str = "135deg, #1e1b4b, #312e81"
    tagline: str = ""
    premise: str = ""
    themes: list[str] = []
    cultural_dna: dict = {}
    story_dna: dict = {}
    inspiration_novels: list[str] = []
    protagonist_name: str = ""
    protagonist_archetype: str = ""
    power_system: str = ""
    setup_mode: str = "blueprint"
    creative_brief: dict = {}


@router.get("")
def list_projects():
    projects = _load()
    # Compute chapters_written, words_written, and tagline live from disk for
    # each project. tagline is genuinely LINKED to project.json now (not a
    # synced copy that can go stale again the next time some other code path
    # writes project.json's tagline without also touching the registry, e.g.
    # AI generation via _apply_field_patch in generate.py never syncs the
    # registry) — same reasoning as chapters_written/words_written below,
    # which are already computed live rather than trusted from the registry.
    for p in projects:
        pid = p.get("id", "")
        pf = CORPUS_PATH / "projects" / pid / "project.json"
        if pf.exists():
            try:
                p["tagline"] = json.loads(pf.read_text(encoding="utf-8")).get("tagline", "")
            except Exception:
                pass   # keep whatever the registry had rather than blank it on a transient read error
        gen_dir = CORPUS_PATH / "generated" / pid
        if gen_dir.exists():
            chapter_files = list(gen_dir.glob("ch*_generated.txt"))
            p["chapters_written"] = len(chapter_files)
            total_words = 0
            for cf in chapter_files:
                try:
                    text = cf.read_text(encoding="utf-8", errors="ignore")
                    total_words += len(text.split())
                except Exception:
                    pass
            p["words_written"] = total_words
        else:
            p["chapters_written"] = 0
            p["words_written"] = 0
    return projects


# ── the demo project that ships with the repository (demo/the_lantern_court) ──────────────────────────
DEMO_ID = "the_lantern_court"


@router.post("/demo/install")
def install_demo():
    """Copy the bundled, fictional demo project (a planned novel with one written chapter) into the workspace. Safe to call twice."""
    import shutil
    projects = _load()
    existing = next((p for p in projects if p.get("id") == DEMO_ID), None)
    if existing:
        return {"ok": True, "already": True, "id": DEMO_ID}
    src = BUNDLED_CORPUS.parent / "demo" / DEMO_ID
    if not (src / "project.json").exists():
        raise HTTPException(404, "The demo project is not in this copy of the repository (demo/the_lantern_court is missing).")
    dst = _project_dir(DEMO_ID)
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.name == "generated":
            continue
        if f.is_file():
            shutil.copy2(f, dst / f.name)
        elif f.is_dir():
            shutil.copytree(f, dst / f.name, dirs_exist_ok=True)
    gen_src = src / "generated"
    if gen_src.exists():
        shutil.copytree(gen_src, CORPUS_PATH / "generated" / DEMO_ID, dirs_exist_ok=True)
    proj = json.loads((dst / "project.json").read_text(encoding="utf-8"))
    projects.append({
        "id": DEMO_ID, "title": proj.get("title", "The Lantern Court"), "subtitle": proj.get("subtitle", "Demo project"),
        "genre": proj.get("genre", ""), "status": proj.get("status", "Planning"), "target_chapters": proj.get("target_chapters", 120),
        "chapters_written": 0, "planning_progress": 0, "health_score": 0, "cover_emoji": proj.get("cover_emoji", "🏮"),
        "cover_gradient": proj.get("cover_gradient", "135deg, #1e1b4b, #312e81"), "tagline": proj.get("tagline", ""), "last_edited": "",
    })
    _save(projects)
    return {"ok": True, "already": False, "id": DEMO_ID}


@router.post("")
def create_project(req: CreateProjectRequest):
    projects = _load()

    # Auto-generate ID if not provided
    if not req.id:
        slug = req.title.lower().replace(" ", "_")
        slug = "".join(c for c in slug if c.isalnum() or c == "_")[:32]
        req.id = f"{slug}_{uuid.uuid4().hex[:6]}"

    if any(p["id"] == req.id for p in projects):
        raise HTTPException(400, f"Project '{req.id}' already exists")

    project = req.model_dump()
    project["chapters_written"] = 0
    project["planning_progress"] = 0
    project["health_score"] = 0
    project["last_edited"] = ""
    project["arcs"] = []
    project["chapter_skeletons"] = []
    project["story_state"] = {
        "active_mysteries": 0,
        "active_schemes": 0,
        "running_gags": 0,
        "foreshadowing": 0,
        "unresolved_goals": 0,
        "relationships_changing": 0,
        "villain_plans": 0,
        "reader_tension": 0,
        "target_ending_tension": 92,
    }
    project["planning_health"] = {
        "world_depth": 0, "character_depth": 0, "arc_pacing": 0,
        "power_scaling": 0, "mystery_density": 0, "comedy_balance": 0,
        "theme_consistency": 0, "reader_hooks": 0,
    }
    if req.creative_brief:
        project["creative_brief"] = req.creative_brief
    else:
        project["creative_brief"] = {
            "premise": req.premise,
            "themes": req.themes,
            "reader_experience": req.story_dna,
            "cultural_blend": req.cultural_dna,
        }

    # Create project directory
    pdir = _project_dir(req.id)
    pdir.mkdir(parents=True, exist_ok=True)
    with open(pdir / "project.json", "w", encoding="utf-8") as f:
        json.dump(project, f, indent=2, ensure_ascii=False)

    projects.append({
        "id": req.id,
        "title": req.title,
        "subtitle": req.subtitle,
        "genre": req.genre,
        "status": req.status,
        "target_chapters": req.target_chapters,
        "chapters_written": 0,
        "planning_progress": 0,
        "health_score": 0,
        "cover_emoji": req.cover_emoji,
        "cover_gradient": req.cover_gradient,
        "tagline": req.tagline,
        "last_edited": "",
    })
    _save(projects)
    return project


@router.get("/{project_id}")
def get_project(project_id: str):
    pdir = _project_dir(project_id)
    pfile = pdir / "project.json"
    if pfile.exists():
        with open(pfile, encoding="utf-8") as f:
            project = json.load(f)
    else:
        projects = _load()
        project = next((p for p in projects if p["id"] == project_id), None)
        if not project:
            raise HTTPException(404, f"Project {project_id} not found")

    # Always recompute health scores from actual content
    computed = _compute_project_health(project)
    project.update(computed)
    return project


@router.patch("/{project_id}")
def update_project(project_id: str, data: dict):
    pdir = _project_dir(project_id)
    pfile = pdir / "project.json"
    if pfile.exists():
        with open(pfile, encoding="utf-8") as f:
            project = json.load(f)
        if "chapter_skeletons" in data:
            _recycle_removed_chapters(project_id, project.get("chapter_skeletons"), data["chapter_skeletons"])
        project.update(data)
        with open(pfile, "w", encoding="utf-8") as f:
            json.dump(project, f, indent=2, ensure_ascii=False)

    # Also update registry summary
    projects = _load()
    for p in projects:
        if p["id"] == project_id:
            for k in ["title","status","chapters_written","planning_progress","health_score","last_edited",
                      "cover_emoji","cover_gradient","cover_image","tagline"]:
                if k in data:
                    p[k] = data[k]
    _save(projects)
    return {"ok": True}


def save_cover_image(project_id: str, content: bytes, ext: str) -> str:
    """Write cover image bytes to projects/<id>/cover.<ext> (any previous
    cover image is replaced — at most one file on disk per project,
    regardless of extension), then save the resulting URL into project.json
    + registry as cover_image. Shared by the manual upload endpoint below
    and generate.py's AI cover-generation endpoint, so both paths stay in
    sync with the same storage/serving convention."""
    pdir = _project_dir(project_id)
    if not (pdir / "project.json").exists():
        raise HTTPException(404, f"Project {project_id} not found")
    if ext not in _COVER_EXTS:
        raise HTTPException(400, f"Unsupported image type '.{ext}'. Use: {', '.join(sorted(_COVER_EXTS))}.")

    # remove any previously uploaded/generated cover (possibly a different
    # extension) before writing the new one, so old files don't accumulate
    for old in pdir.glob("cover.*"):
        old.unlink(missing_ok=True)

    dest = pdir / f"cover.{ext}"
    dest.write_bytes(content)

    # cache-bust so the browser doesn't keep showing a stale cached image
    # after a re-upload/regeneration replaces the same filename
    cover_url = f"/project-covers/{project_id}/cover.{ext}?v={uuid.uuid4().hex[:8]}"

    pfile = pdir / "project.json"
    with open(pfile, encoding="utf-8") as f:
        project = json.load(f)
    project["cover_image"] = cover_url
    with open(pfile, "w", encoding="utf-8") as f:
        json.dump(project, f, indent=2, ensure_ascii=False)

    projects = _load()
    for p in projects:
        if p["id"] == project_id:
            p["cover_image"] = cover_url
    _save(projects)

    return cover_url


@router.post("/{project_id}/cover-image")
async def upload_cover_image(project_id: str, file: UploadFile = File(...)):
    """Upload a custom front-cover image for a project. See save_cover_image()
    for the storage/serving convention."""
    name = Path(file.filename or "").name
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if ext not in _COVER_EXTS:
        raise HTTPException(400, f"Unsupported image type '.{ext}'. Use: {', '.join(sorted(_COVER_EXTS))}.")

    content = await file.read()
    max_bytes = 8 * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(400, "Image too large (max 8MB).")

    cover_url = save_cover_image(project_id, content, ext)
    return {"ok": True, "cover_image": cover_url}


@router.delete("/{project_id}/cover-image")
def remove_cover_image(project_id: str):
    """Revert to the emoji+gradient cover — deletes the uploaded file and
    clears cover_image from project.json + registry."""
    pdir = _project_dir(project_id)
    if not (pdir / "project.json").exists():
        raise HTTPException(404, f"Project {project_id} not found")
    for old in pdir.glob("cover.*"):
        old.unlink(missing_ok=True)

    pfile = pdir / "project.json"
    with open(pfile, encoding="utf-8") as f:
        project = json.load(f)
    project.pop("cover_image", None)
    with open(pfile, "w", encoding="utf-8") as f:
        json.dump(project, f, indent=2, ensure_ascii=False)

    projects = _load()
    for p in projects:
        if p["id"] == project_id:
            p.pop("cover_image", None)
    _save(projects)

    return {"ok": True}


@router.delete("/{project_id}")
def delete_project(project_id: str):
    projects = _load()
    projects = [p for p in projects if p["id"] != project_id]
    _save(projects)
    return {"ok": True}
