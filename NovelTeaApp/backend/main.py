import os
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from routers.pre_generation import (antagonists, blueprints, castroster, conspiracy, fightplan, lore, reference_mechanics,
                                     sceneplan, timeline)
from routers.generation import generate, jobs
from routers.post_generation import engines
from routers.corpus_tools import corpus, corpus_builder, corpus_reader, corpus_wiki
from routers.workspace import aicoder, projectio, projects, server, settings, setup, system
from config import CORPUS_PATH

PORT = 7432


def _prevent_system_sleep():
    """Tell Windows this process needs the machine to stay awake — corpus
    extraction and chapter generation run long, unattended jobs (the Ollama
    comparison tests in this session took 10+ minutes per chapter across
    multiple LLM calls), and a cloud/remote-desktop PC's idle-sleep timer has
    no user input to reset it while that's running, so it was suspending the
    VM mid-job. SetThreadExecutionState with ES_CONTINUOUS persists until the
    process exits or explicitly clears it — no per-call renewal needed.
    ES_SYSTEM_REQUIRED stops the sleep/idle-shutdown; ES_DISPLAY_REQUIRED also
    stops the display from blanking, which some remote-desktop/cloud-PC agents
    treat as an activity signal in their own idle policy on top of Windows'."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ES_DISPLAY_REQUIRED = 0x00000002
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
        )
    except Exception:
        pass   # best-effort — never let this block the app from starting


_prevent_system_sleep()


def _resource_root() -> Path:
    """Root for bundled resources. When frozen by PyInstaller, files live under
    sys._MEIPASS; otherwise use the source tree relative to this file."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).parent


app = FastAPI(title="NovelTea Engine API", version="1.1.0")

# The app has no login: by default it listens on this computer only (127.0.0.1) and only pages served from this computer may call it.
# To reach it from a phone or another PC on purpose, set NOVELTEA_HOST=0.0.0.0 (and, if the page is served from another address,
# NOVELTEA_ALLOW_ORIGINS=https://that-address). Only do that on a network you trust: anyone who can reach the port can use the app.
import os as _os
HOST = _os.environ.get("NOVELTEA_HOST", "127.0.0.1")
_ORIGINS = [o.strip() for o in _os.environ.get("NOVELTEA_ALLOW_ORIGINS", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ORIGINS,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def _log_unhandled(request, exc):
    """An unhandled error used to reach the app as a bare "Internal Server Error": keep the traceback in server_errors.log and say what failed."""
    import traceback
    from fastapi.responses import JSONResponse
    try:
        from routers.generation.generate import CORPUS_PATH
        log = CORPUS_PATH / "server_errors.log"
        old = log.read_text(encoding="utf-8")[-200000:] if log.exists() else ""
        log.write_text(old + f"\n==== {request.method} {request.url.path}\n" + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)), encoding="utf-8")
    except Exception:
        pass
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {str(exc)[:300]}"})

# Pre-generation: the planning tabs
app.include_router(conspiracy.router, prefix="/api/conspiracy", tags=["conspiracy"])   # hidden scheme tree
app.include_router(antagonists.router, prefix="/api/antagonists", tags=["antagonists"])   # antagonists and obstacles plan
app.include_router(castroster.router, prefix="/api/castroster", tags=["castroster"])
app.include_router(lore.router, prefix="/api/lore", tags=["lore"])   # world lore (pre) and chapter cards (post)
app.include_router(timeline.router, prefix="/api/timeline", tags=["timeline"])   # chapter timeline from the hero's point of view
app.include_router(fightplan.router, prefix="/api/fightplan", tags=["fightplan"])   # a fight planned beat by beat against a word budget
app.include_router(sceneplan.router, prefix="/api/sceneplan", tags=["sceneplan"])   # every other kind of scene, planned the same way
app.include_router(blueprints.router, prefix="/api/blueprints", tags=["blueprints"])
app.include_router(reference_mechanics.router, prefix="/api/reference", tags=["reference"])   # the chosen novel's chapter mechanics

# Generation
app.include_router(generate.router, prefix="/api/generate", tags=["generate"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])   # background jobs + phone push notifications

# Post-generation
app.include_router(engines.router, prefix="/api/engines", tags=["engines"])   # chapter versions, save, restore

# Corpus (supplied by the user; nothing ships with the app)
app.include_router(corpus.router, prefix="/api/corpus", tags=["corpus"])
app.include_router(corpus_builder.router, prefix="/api/corpus-builder", tags=["corpus-builder"])
app.include_router(corpus_reader.router, prefix="/api/corpus-reader", tags=["corpus-reader"])
app.include_router(corpus_wiki.router, prefix="/api/corpus-wiki", tags=["corpus-wiki"])

# Workspace: projects, settings, system
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(projectio.router, prefix="/api/project-io", tags=["project-io"])   # import / export a whole project
app.include_router(settings.router, prefix="/api/settings", tags=["settings"])
app.include_router(setup.router, prefix="/api/setup", tags=["setup"])
app.include_router(system.router, prefix="/api/system", tags=["system"])
app.include_router(server.router, prefix="/api/server", tags=["server"])   # Server page: CPU/RAM + the app's own processes
app.include_router(aicoder.router, prefix="/api/aicoder", tags=["aicoder"])

# Serve uploaded project cover images. Mounted straight at the project
# directory root — each project's cover.<ext> lives at
# projects/<project_id>/cover.<ext> — so /project-covers/<id>/cover.<ext>
# matches exactly what projects.py's upload_cover_image() returns as cover_image.
_PROJECTS_DIR = CORPUS_PATH / "projects"
_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/project-covers", StaticFiles(directory=str(_PROJECTS_DIR)), name="project-covers")

# Serve generated media (chapter narration audio, etc.) — generated/<project_id>/chNNN_audio.wav
_GENERATED_DIR = CORPUS_PATH / "generated"
_GENERATED_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/generated-media", StaticFiles(directory=str(_GENERATED_DIR)), name="generated-media")


@app.get("/api/health")
def health():
    # pid: lets the Restart button tell the NEW instance from the old one still shutting down
    return {"status": "ok", "version": "1.1.0", "app": "NovelTea Engine", "pid": os.getpid()}


# ── Serve the built React UI (single-port app) ──────────────────────────────
# The launcher builds renderer/dist and copies it next to the backend as "webui".
_UI_DIR = _resource_root() / "webui"
if not _UI_DIR.exists():
    # dev fallback: serve straight from the renderer build output
    _alt = Path(__file__).parent.parent / "renderer" / "dist"
    if _alt.exists():
        _UI_DIR = _alt

if _UI_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(_UI_DIR / "assets")), name="assets")

    @app.get("/")
    def _index():
        return FileResponse(str(_UI_DIR / "index.html"))

    # SPA fallback — any non-API path returns index.html so client routing works
    @app.get("/{full_path:path}")
    def _spa(full_path: str):
        if full_path.startswith("api/"):
            return {"detail": "Not Found"}
        candidate = _UI_DIR / full_path
        if candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(_UI_DIR / "index.html"))


if __name__ == "__main__":
    # Retry binding for a few seconds: a Settings > Restart Server spawns this
    # process WHILE the old one still briefly holds the port (it exits shortly
    # after spawning us, but the exact timing isn't guaranteed) — without a
    # retry, a normal restart would occasionally crash on "address in use".
    import time as _time
    import errno
    for attempt in range(15):
        try:
            uvicorn.run(app, host=HOST, port=PORT, reload=False)
            break
        except OSError as e:
            if e.errno in (errno.EADDRINUSE, 10048) and attempt < 14:
                _time.sleep(0.5)
                continue
            raise
