"""Project import and export.

One portable bundle format ("noveltea-project", version 1) shared by NovelTea Engine and any app that reads the same format, so a project made in one opens in the other.

Export (GET /api/project-io/export/{id}?format=bundle|markdown|txt):
  bundle    a .noveltea.zip with the whole project: project.json, its side files (summaries, memory, gag ledger, cover), the chapters,
            their version history, and a manifest with a SHA-256 of every file.
  markdown / txt   the manuscript only (chapters in order).

Import (POST /api/project-io/import/preview, then /import/commit): accepts a bundle (.zip), or a manuscript (.txt, .md, .docx) which is
split into chapters on "Chapter N" headings. The upload is treated as hostile: size and file-count limits, no unsafe paths or symlinks,
only known file names and types, checksums verified, project.json checked, and every write rolled back if anything fails. An import
always creates a NEW project (it never overwrites an existing one) with a new id.
"""
import hashlib
import io
import json
import re
import shutil
import time
import uuid
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from config import CORPUS_PATH

router = APIRouter()

APP_NAME = "NovelTea Engine"
FORMAT = "noveltea-project"
FORMAT_VERSION = 1

MAX_UPLOAD = 300 * 1024 * 1024        # the uploaded file
MAX_UNPACKED = 800 * 1024 * 1024      # everything inside a bundle, unpacked
MAX_FILES = 20000
MAX_PROJECT_JSON = 80 * 1024 * 1024
MAX_SIDE_FILE = 60 * 1024 * 1024
MAX_CHAPTER = 5 * 1024 * 1024
TMP_TTL = 3600                        # seconds a previewed upload is kept

_ROOT_FILE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,79}\.(json|md|txt|png|jpg|jpeg|webp|gif)$")
_SKIP_ROOT = re.compile(r"(\.backup|\.bak|\.tmp$|^_agent_backups|^_shaping|^project\.json$)", re.I)
_GEN = re.compile(r"^generated/(ch\d{1,5}_generated\.txt|ch\d{1,5}_parts\.json|ch\d{1,5}_influences\.json)$")
_VER = re.compile(r"^generated/_versions/ch\d{1,5}_v\d{1,4}\.txt$")
_CH_FILE = re.compile(r"^ch(\d{1,5})_generated\.txt$")


# ── places ─────────────────────────────────────────────────────────────────────

def _projects_dir() -> Path:
    return CORPUS_PATH / "projects"


def _generated_dir() -> Path:
    return CORPUS_PATH / "generated"


def _tmp_dir() -> Path:
    d = CORPUS_PATH / "_import_tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")
    return (s or "project")[:32]


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _registry():
    from routers.workspace import projects as P
    return P


# ── export ─────────────────────────────────────────────────────────────────────

def _load_project(pid: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,80}", pid or ""):
        raise HTTPException(400, "Bad project id.")
    f = _projects_dir() / pid / "project.json"
    if not f.exists():
        raise HTTPException(404, f"Project {pid} not found.")
    return json.loads(f.read_text(encoding="utf-8-sig"))


def _chapters_of(pid: str) -> list:
    """[(number, text)] of the written chapters, in order."""
    gdir = _generated_dir() / pid
    out = []
    if gdir.exists():
        for f in gdir.iterdir():
            m = _CH_FILE.match(f.name)
            if m and f.is_file():
                out.append((int(m.group(1)), f.read_text(encoding="utf-8-sig", errors="replace")))
    return sorted(out)


def _titles(project: dict) -> dict:
    t = {}
    for c in project.get("chapter_skeletons") or []:
        if isinstance(c, dict) and isinstance(c.get("number"), int) and str(c.get("title") or "").strip():
            t[c["number"]] = str(c["title"]).strip()
    return t


def _bundle_bytes(pid: str) -> tuple:
    project = _load_project(pid)
    pdir = _projects_dir() / pid
    gdir = _generated_dir() / pid
    files = {"project.json": json.dumps(project, indent=2, ensure_ascii=False).encode("utf-8")}
    for f in sorted(pdir.iterdir()):
        if f.is_file() and _ROOT_FILE.match(f.name) and not _SKIP_ROOT.search(f.name) and f.stat().st_size <= MAX_SIDE_FILE:
            files[f.name] = f.read_bytes()
    words = chapters = 0
    if gdir.exists():
        for f in sorted(gdir.iterdir()):
            if f.is_file() and (_GEN.match("generated/" + f.name)) and f.stat().st_size <= MAX_CHAPTER:
                b = f.read_bytes()
                files["generated/" + f.name] = b
                if _CH_FILE.match(f.name):
                    chapters += 1
                    words += len(b.decode("utf-8", "ignore").split())
        vdir = gdir / "_versions"
        if vdir.exists():
            for f in sorted(vdir.iterdir()):
                if f.is_file() and _VER.match("generated/_versions/" + f.name) and f.stat().st_size <= MAX_CHAPTER:
                    files["generated/_versions/" + f.name] = f.read_bytes()
    manifest = {
        "format": FORMAT, "formatVersion": FORMAT_VERSION, "app": APP_NAME,
        "exportedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "title": str(project.get("title") or pid), "chapters": chapters, "words": words,
        "files": [{"path": p, "bytes": len(b), "sha256": _sha(b)} for p, b in files.items()],
    }
    readme = (f"This is a {FORMAT} bundle (format version {FORMAT_VERSION}) exported from {APP_NAME}.\n"
              "Open NovelTea Engine, press Import project on the dashboard, and choose this file.\n"
              "project.json is the project; generated/ holds the written chapters; manifest.json lists every file with a SHA-256.\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p, b in files.items():
            z.writestr(p, b)
        z.writestr("README.txt", readme)
        z.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
    return buf.getvalue(), project, manifest


def _manuscript(pid: str, fmt: str) -> tuple:
    project = _load_project(pid)
    chapters = _chapters_of(pid)
    if not chapters:
        raise HTTPException(400, "This project has no written chapters to export yet.")
    titles = _titles(project)
    title = str(project.get("title") or pid)
    parts = []
    if fmt == "markdown":
        parts.append(f"# {title}\n")
        for n, text in chapters:
            t = titles.get(n)
            parts.append(f"\n## Chapter {n}" + (f": {t}" if t else "") + "\n\n" + text.strip() + "\n")
    else:
        parts.append(title + "\n" + "=" * len(title) + "\n")
        for n, text in chapters:
            t = titles.get(n)
            h = f"Chapter {n}" + (f": {t}" if t else "")
            parts.append("\n\n" + h + "\n" + "-" * len(h) + "\n\n" + text.strip() + "\n")
    return "".join(parts).encode("utf-8"), title


@router.get("/export/{project_id}")
def export_project(project_id: str, format: str = "bundle"):
    fmt = (format or "bundle").lower()
    if fmt not in ("bundle", "markdown", "md", "txt"):
        raise HTTPException(400, "format must be bundle, markdown or txt.")
    if fmt == "bundle":
        data, project, _ = _bundle_bytes(project_id)
        name = f"{_slug(project.get('title') or project_id)}.noveltea.zip"
        return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})
    fmt = "markdown" if fmt in ("markdown", "md") else "txt"
    data, title = _manuscript(project_id, fmt)
    name = f"{_slug(title)}.{'md' if fmt == 'markdown' else 'txt'}"
    return Response(data, media_type="text/plain; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ── import: reading and checking an upload ─────────────────────────────────────

def _bad(msg: str):
    raise HTTPException(400, msg)


def _read_zip_member(z: zipfile.ZipFile, info: zipfile.ZipInfo, cap: int) -> bytes:
    if info.file_size > cap:
        _bad(f"{info.filename} is too large ({info.file_size // 1024} KB).")
    with z.open(info) as f:
        b = f.read(cap + 1)
    if len(b) > cap:
        _bad(f"{info.filename} is larger than its header says.")
    return b


def _analyse_bundle(data: bytes) -> dict:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        _bad("That file is not a valid zip.")
    infos = [i for i in z.infolist() if not i.is_dir()]
    if len(infos) > MAX_FILES:
        _bad(f"Too many files in the bundle ({len(infos)}).")
    if sum(i.file_size for i in infos) > MAX_UNPACKED:
        _bad("The bundle is too large once unpacked.")
    names = {}
    for i in infos:
        n = i.filename.replace("\\", "/")
        parts = n.split("/")
        if n.startswith("/") or ".." in parts or re.match(r"^[A-Za-z]:", n) or "\x00" in n or "" in parts[:-1]:
            _bad(f"Unsafe file name in the bundle: {n[:80]}")
        if (i.external_attr >> 16) & 0o170000 == 0o120000:
            _bad(f"The bundle contains a symbolic link ({n[:80]}), which is not allowed.")
        names[n] = i
    prefix = ""
    if "project.json" not in names:
        cands = [n for n in names if n.endswith("/project.json") and n.count("/") <= 2]
        if len(cands) != 1:
            _bad("No project.json found: this does not look like a project bundle.")
        prefix = cands[0][:-len("project.json")]
    rel = {n[len(prefix):]: i for n, i in names.items() if n.startswith(prefix)}

    manifest = None
    if "manifest.json" in rel:
        try:
            manifest = json.loads(_read_zip_member(z, rel["manifest.json"], 20 * 1024 * 1024).decode("utf-8-sig"))
        except ValueError:
            _bad("manifest.json is not valid JSON.")
        if isinstance(manifest, dict):
            if manifest.get("format") not in (None, FORMAT):
                _bad(f"This bundle is a different format ({str(manifest.get('format'))[:40]}).")
            try:
                v = int(manifest.get("formatVersion") or 1)
            except (TypeError, ValueError):
                v = 1
            if v > FORMAT_VERSION:
                _bad(f"This bundle uses a newer format (version {v}). Update the app to import it.")
        else:
            manifest = None

    warnings = []
    pj = _read_zip_member(z, rel["project.json"], MAX_PROJECT_JSON)
    try:
        project = json.loads(pj.decode("utf-8-sig"))
    except ValueError:
        _bad("project.json is not valid JSON.")
    if not isinstance(project, dict) or not isinstance(project.get("title"), str) or not project["title"].strip():
        _bad("project.json has no title: this is not a project file.")

    root_files, generated, skipped = {}, {}, []
    for r, info in rel.items():
        if r in ("project.json", "manifest.json", "README.txt"):
            continue
        if "/" not in r and _ROOT_FILE.match(r) and not _SKIP_ROOT.search(r):
            root_files[r] = _read_zip_member(z, info, MAX_SIDE_FILE)
        elif _GEN.match(r) or _VER.match(r):
            generated[r] = _read_zip_member(z, info, MAX_CHAPTER)
        else:
            skipped.append(r)

    if manifest:                                     # every file named in the manifest must match its checksum
        for ent in manifest.get("files") or []:
            if not isinstance(ent, dict) or not isinstance(ent.get("path"), str):
                continue
            p, want = ent["path"], str(ent.get("sha256") or "")
            if not want:
                continue
            blob = pj if p == "project.json" else root_files.get(p) if p in root_files else generated.get(p)
            if blob is None:
                warnings.append(f"{p} is listed in the manifest but not in the bundle.")
            elif _sha(blob) != want:
                _bad(f"{p} does not match its checksum: the bundle is damaged or was edited.")
    else:
        warnings.append("No manifest: the files could not be checked against checksums.")

    chapters = [p for p in generated if _CH_FILE.match(p.split("/")[-1])]
    words = sum(len(generated[p].decode("utf-8", "ignore").split()) for p in chapters)
    return {
        "kind": "bundle", "project": project, "root_files": root_files, "generated": generated,
        "summary": {
            "kind": "bundle", "title": project["title"].strip()[:200], "genre": str(project.get("genre") or "")[:80],
            "chapters": len(chapters), "words": words, "planned_chapters": len(project.get("chapter_skeletons") or []),
            "characters": len(project.get("character_list") or []), "arcs": len(project.get("arcs") or []),
            "files": 1 + len(root_files) + len(generated), "source_app": (manifest or {}).get("app"),
            "exported_at": (manifest or {}).get("exportedAt"), "skipped": skipped[:20], "skipped_count": len(skipped), "warnings": warnings,
        },
    }


_CH_HEAD = re.compile(r"^[ \t]*(?:#{1,6}[ \t]*)?(?:chapter|chap\.?|ch\.?)[ \t]+(?:\d{1,5}|[ivxlcdm]{1,8})\b[ \t]*[:.\-–—]?[ \t]*(.*)$",
                      re.I | re.M)


def _docx_text(data: bytes) -> str:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        info = z.getinfo("word/document.xml")
    except (zipfile.BadZipFile, KeyError):
        _bad("That .docx file could not be read.")
    xml = _read_zip_member(z, info, 80 * 1024 * 1024).decode("utf-8", "replace")
    paras = []
    for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        text = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S))
        text = (text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'"))
        paras.append(text)
    return "\n".join(paras)


def _analyse_manuscript(data: bytes, ext: str, filename: str) -> dict:
    if ext == "docx":
        text = _docx_text(data)
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    if len(text.split()) < 20:
        _bad("That file has almost no text.")
    heads = list(_CH_HEAD.finditer(text))
    chapters = []        # [(title, body)]
    if heads:
        pre = text[:heads[0].start()].strip()
        if len(pre.split()) >= 200:
            chapters.append(("Opening", pre))
        for i, m in enumerate(heads):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
            body = text[m.end():end].strip()
            if body:
                chapters.append((m.group(1).strip(" .:-"), body))
    if not chapters:
        chapters = [("", text.strip())]
    stem = Path(filename).stem.replace("_", " ").strip() or "Imported manuscript"
    n = len(chapters)
    project = {
        "title": stem[:120], "subtitle": "", "genre": "", "subgenres": [], "genre_tags": [], "audience": "", "target_chapters": max(n, 1),
        "pov": "", "status": "Writing", "cover_emoji": "📖", "cover_gradient": "135deg, #1e1b4b, #312e81", "tagline": "", "premise": "",
        "themes": [], "story_dna": {}, "setup_mode": "manual", "creative_brief": {"premise": "", "themes": [], "reader_experience": {}},
        "arcs": [], "character_list": [], "chapter_skeletons": [{"number": i + 1, "title": t} for i, (t, _) in enumerate(chapters) if t],
    }
    generated = {f"generated/ch{i + 1:03d}_generated.txt": b.encode("utf-8") for i, (_, b) in enumerate(chapters)}
    words = sum(len(b.split()) for _, b in chapters)
    return {
        "kind": "manuscript", "project": project, "root_files": {}, "generated": generated,
        "summary": {
            "kind": "manuscript", "title": project["title"], "genre": "", "chapters": n, "words": words, "planned_chapters": 0, "characters": 0,
            "arcs": 0, "files": len(generated), "source_app": None, "exported_at": None, "skipped": [], "skipped_count": 0,
            "warnings": ([] if heads else ["No 'Chapter N' headings were found, so the whole text became one chapter."]),
        },
    }


def _analyse(data: bytes, ext: str, filename: str) -> dict:
    if ext == "zip":
        return _analyse_bundle(data)
    return _analyse_manuscript(data, ext, filename)


# ── import: preview then commit ────────────────────────────────────────────────

def _purge_tmp():
    cutoff = time.time() - TMP_TTL
    for f in _tmp_dir().iterdir():
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


@router.post("/import/preview")
async def import_preview(file: UploadFile = File(...)):
    name = Path(file.filename or "upload").name
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if ext not in ("zip", "txt", "md", "docx"):
        raise HTTPException(400, "Choose a project bundle (.zip) or a manuscript (.txt, .md or .docx).")
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "That file is too large to import.")
    plan = _analyse(data, ext, name)                 # raises a 400 with a plain message if the file is not acceptable
    _purge_tmp()
    token = uuid.uuid4().hex
    (_tmp_dir() / f"{token}.bin").write_bytes(data)
    (_tmp_dir() / f"{token}.json").write_text(json.dumps({"ext": ext, "name": name}), encoding="utf-8")
    return {"ok": True, "token": token, **plan["summary"]}


class CommitRequest(BaseModel):
    token: str
    title: Optional[str] = None


def _new_id(title: str) -> str:
    for _ in range(20):
        pid = f"{_slug(title)}_{uuid.uuid4().hex[:6]}"
        if not (_projects_dir() / pid).exists() and not (_generated_dir() / pid).exists():
            return pid
    raise HTTPException(500, "Could not choose a free project id.")


@router.post("/import/commit")
def import_commit(req: CommitRequest):
    if not re.fullmatch(r"[0-9a-f]{32}", req.token or ""):
        raise HTTPException(400, "Bad import token.")
    tdir = _tmp_dir()
    binf, metaf = tdir / f"{req.token}.bin", tdir / f"{req.token}.json"
    if not binf.exists() or not metaf.exists():
        raise HTTPException(404, "That import expired. Choose the file again.")
    meta = json.loads(metaf.read_text(encoding="utf-8"))
    plan = _analyse(binf.read_bytes(), meta["ext"], meta["name"])        # checked again before anything is written
    project = plan["project"]
    old_id = str(project.get("id") or "")
    if (req.title or "").strip():
        project["title"] = req.title.strip()[:200]
    new_id = _new_id(project["title"])
    project["id"] = new_id
    project.pop("_agent_backups", None)
    if isinstance(project.get("cover_image"), str) and old_id:
        project["cover_image"] = project["cover_image"].replace(old_id, new_id)

    pdir, gdir = _projects_dir() / new_id, _generated_dir() / new_id
    try:
        pdir.mkdir(parents=True)
        (pdir / "project.json").write_text(json.dumps(project, indent=2, ensure_ascii=False), encoding="utf-8")
        for name, b in plan["root_files"].items():
            (pdir / name).write_bytes(b)
        if plan["generated"]:
            for rel, b in plan["generated"].items():
                dest = gdir / rel[len("generated/"):]
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b)
        P = _registry()
        projects = P._load()
        projects.append({
            "id": new_id, "title": project["title"], "subtitle": project.get("subtitle", ""), "genre": project.get("genre", ""),
            "status": project.get("status", "Planning"), "target_chapters": project.get("target_chapters", 0), "chapters_written": 0,
            "planning_progress": 0, "health_score": 0, "cover_emoji": project.get("cover_emoji", "📖"),
            "cover_gradient": project.get("cover_gradient", "135deg, #1e1b4b, #312e81"), "tagline": project.get("tagline", ""),
            "last_edited": "",
            **({"cover_image": project["cover_image"]} if project.get("cover_image") else {}),
        })
        P._save(projects)
    except Exception as e:                           # all or nothing: leave nothing behind
        shutil.rmtree(pdir, ignore_errors=True)
        shutil.rmtree(gdir, ignore_errors=True)
        raise HTTPException(500, f"The import failed and was undone ({type(e).__name__}: {str(e)[:120]}).")
    for f in (binf, metaf):
        try:
            f.unlink()
        except OSError:
            pass
    s = plan["summary"]
    return {"ok": True, "id": new_id, "title": project["title"], "chapters": s["chapters"], "words": s["words"], "kind": s["kind"]}
