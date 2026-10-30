"""Corpus Builder — add novels to the corpus and run the full extraction pipeline.

Wraps the existing corpus scripts (extract_v3.py, merge.py,
generate_genome.py) that live in the corpus dir, exposing them as orchestrated
jobs with a persistent queue. Runs each script as a subprocess FROM the corpus
directory so relative paths (raw/, novels/) resolve correctly.

No API key required: the scripts fall back to the Claude subscription CLI via
llm_client.py (added alongside them).

NOTE: This is the ONE sanctioned way the app writes into the corpus — it is the
corpus-building tool itself. Normal generation still never touches novels/.
"""
import json
import re
import sys
import time
import shutil
import threading
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from config import CORPUS_PATH

router = APIRouter()

RAW_DIR = CORPUS_PATH / "raw"
NOVELS_DIR = CORPUS_PATH / "novels"
QUEUE_FILE = CORPUS_PATH / "extraction_queue.json"

# ── Job registry (in-memory, mirrored to disk for the queue) ────────────────
class TimestampedLog(list):
    """A list that prefixes every appended line with a wall-clock HH:MM:SS stamp,
    so the console can show per-step timing without touching 30+ append sites.
    Lines already starting with a timestamp are left as-is."""
    def append(self, line):
        s = str(line)
        if not re.match(r"^\d{2}:\d{2}:\d{2} ", s):
            s = time.strftime("%H:%M:%S ") + s
        super().append(s)


_jobs = {}          # job_id -> {id, kind, novel, status, log[], started, finished, error}
_jobs_lock = threading.Lock()
_worker_running = False
_worker_thread = None   # the live queue-worker thread (for self-heal checks)


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s or "untitled"


def _python() -> str:
    """Interpreter to run pipeline scripts. When frozen, we still need a real
    python on PATH (the scripts are separate .py files, not bundled code)."""
    return sys.executable if not getattr(sys, "frozen", False) else (shutil.which("python") or "python")


def _script(name: str) -> Path:
    return CORPUS_PATH / name


def _load_queue() -> list:
    if QUEUE_FILE.exists():
        try:
            return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_queue(items: list):
    QUEUE_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


def _chapter_num(fname: str):
    """Integer chapter number from exactly 'chNN.txt' / 'chNN.json'.

    Anchored at BOTH ends on purpose. The old pattern only required a dot after
    the digits, so sidecars counted as chapters: 'ch51.claude.json' and
    'ch51.nemotron.json' made my_novel report 102 extracted against a real
    frontier of 100. Backups ('ch99.json.bak') and per-engine variants are not
    chapters and must never inflate a count.
    """
    import re as _re
    m = _re.match(r"ch0*([0-9]+)\.(?:txt|json|htm|html)$", fname, _re.I)
    return int(m.group(1)) if m else None


def _raw_chapter_nums(novel_id: str) -> set:
    raw = RAW_DIR / novel_id
    if not raw.exists():
        return set()
    return {n for n in (_chapter_num(f.name) for f in raw.glob("ch*.txt")) if n is not None}


def _extracted_chapter_nums(novel_id: str) -> set:
    dd = NOVELS_DIR / novel_id / "deltas_v3"
    if not dd.exists():
        return set()
    return {n for n in (_chapter_num(f.name) for f in dd.glob("ch*.json")) if n is not None}


def _next_chapter(novel_id: str):
    """Lowest raw chapter number that hasn't been extracted yet (None if all done)."""
    raw = _raw_chapter_nums(novel_id)
    if not raw:
        return None
    done = _extracted_chapter_nums(novel_id)
    todo = sorted(raw - done)
    return todo[0] if todo else None


def _extracted_through(novel_id: str) -> int:
    """Highest chapter N such that 1..N are ALL extracted — the real frontier.

    A bare file count is misleading the moment deltas are non-contiguous: an
    aborted run left ch5099-5105 extracted on a novel whose frontier is 226, so
    the count read 233 and looked like "extracted through 233" while ch227 had
    no delta at all. Counting files answers "how many"; this answers "how far".
    """
    done = _extracted_chapter_nums(novel_id)
    n = 0
    while (n + 1) in done:
        n += 1
    return n


def _held_chapter_nums(novel_id: str) -> tuple:
    """(usable, corrupt) chapter numbers actually present in raw/<novel>.

    A .htm of pure null bytes is a download that never completed (the size was
    allocated but the data never reached disk). It looks present but holds
    nothing, so it counts as a hole to refill, not as a chapter we have.
    """
    raw = RAW_DIR / novel_id
    if not raw.exists():
        return set(), set()
    usable, corrupt = set(), set()
    for f in raw.glob("ch*.txt"):
        n = _chapter_num(f.name)
        if n is not None:
            usable.add(n)
    for pat in ("ch*.htm", "ch*.html"):
        for f in raw.glob(pat):
            n = _chapter_num(f.name)
            if n is None:
                continue
            try:
                b = f.read_bytes()
            except OSError:
                continue
            if not b or b.count(0) == len(b):
                corrupt.add(n)
            else:
                usable.add(n)
    return usable, corrupt - usable


def _missing_chapter_nums(novel_id: str, upto: int | None = None) -> dict:
    """Chapter numbers with no usable file, within 1..(upto or highest held).

    `upto` lets the caller extend past what is on disk — a hole at the END of a
    novel is invisible otherwise, since the range is inferred from files present.
    """
    usable, corrupt = _held_chapter_nums(novel_id)
    held = usable | corrupt
    if not held and not upto:
        return {"missing": [], "corrupt": [], "usable": 0, "last": 0}
    hi = max(max(held) if held else 0, upto or 0)
    lo = min(held) if held else 1
    missing = sorted(set(range(lo, hi + 1)) - usable)
    return {
        "missing": missing,
        "corrupt": sorted(corrupt),
        "usable": len(usable),
        "last": hi,
    }


# ── Novel discovery ─────────────────────────────────────────────────────────
@router.get("/novels")
def list_corpus_novels():
    """List novels in the corpus with chapter/extraction counts + next chapter to extract."""
    out = []
    if NOVELS_DIR.exists():
        for d in sorted(NOVELS_DIR.iterdir()):
            if not d.is_dir():
                continue
            raw = RAW_DIR / d.name
            # Counted via _chapter_num, not len(glob): a bare glob also matches
            # sidecars like 'ch51.claude.json', which are not chapters.
            raw_ch = len(_raw_chapter_nums(d.name))
            # unconverted uploads — invisible to extraction until the convert step runs
            htm = (len(list(raw.glob("*.htm"))) + len(list(raw.glob("*.html")))) if raw.exists() else 0
            deltas = len(_extracted_chapter_nums(d.name))
            genome = (d / "narrative_genome.json").exists()
            rolling_summary = (d / "rolling_summary.json").exists()
            out.append({
                "id": d.name,
                "raw_chapters": raw_ch,
                "raw_html": htm,
                "extracted": deltas,
                # How MANY deltas exist vs how FAR extraction actually reaches.
                # They diverge whenever deltas are non-contiguous (an aborted run
                # on my_novel left ch5099-5105 extracted while the
                # frontier was 226, so "233 extracted" read as "through ch233"
                # even though ch227 had no delta). Show both, never one as the other.
                "extracted_through": _extracted_through(d.name),
                "has_genome": genome,
                "has_rolling_summary": rolling_summary,
                # next_chapter = next chapter to EXTRACT (can lag far behind the
                # raw files). next_raw = next free chN.* slot in raw/, which is
                # what "add chapters" needs for numbering.
                "next_chapter": _next_chapter(d.name),
                "next_raw": _next_raw_index(raw) if raw.exists() else 1,
            })
    # also surface raw-only novels not yet in novels/
    if RAW_DIR.exists():
        known = {n["id"] for n in out}
        for d in sorted(RAW_DIR.iterdir()):
            if d.is_dir() and d.name not in known:
                raw_ch = len(list(d.glob("ch*.txt")))
                htm = len(list(d.glob("*.htm"))) + len(list(d.glob("*.html")))
                out.append({"id": d.name, "raw_chapters": raw_ch, "raw_html": htm,
                            "extracted": 0, "has_genome": False, "has_rolling_summary": False,
                            "next_chapter": _next_chapter(d.name)})
    return {"novels": out}


# ── Add a novel: create its raw folder and accept plain-text chapters you have the right to use ───────
class NewNovelRequest(BaseModel):
    title: str
    novel_id: str = ""


@router.post("/novel/create")
def create_corpus_novel(req: NewNovelRequest):
    nid = req.novel_id.strip() or _slug(req.title)
    nid = _slug(nid)
    raw = RAW_DIR / nid
    if raw.exists() and any(raw.iterdir()):
        raise HTTPException(400, f"'{nid}' already has raw files.")
    raw.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "novel_id": nid, "raw_dir": str(raw)}


@router.post("/novel/{novel_id}/upload")
async def upload_chapters(novel_id: str, files: list[UploadFile] = File(...)):
    """Upload plain-text (.txt) chapter files into raw/<novel_id>/."""
    nid = _slug(novel_id)
    raw = RAW_DIR / nid
    raw.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        name = Path(f.name if hasattr(f, "name") else f.filename).name
        if not name:
            continue
        ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
        if ext != "txt":
            continue
        dest = raw / name
        content = await f.read()
        dest.write_bytes(content)
        saved.append(name)
    return {"ok": True, "novel_id": nid, "saved": saved, "count": len(saved)}


def _next_raw_index(raw: Path) -> int:
    """Highest chN.* already in raw/<novel>/ plus one."""
    n = 0
    for f in list(raw.glob("ch*.htm")) + list(raw.glob("ch*.html")) + list(raw.glob("ch*.txt")):
        m = re.match(r"ch(\d+)", f.stem, re.I)
        if m:
            n = max(n, int(m.group(1)))
    return n + 1


# ── Job runner ──────────────────────────────────────────────────────────────
def _new_job(kind: str, novel: str) -> str:
    jid = f"{kind}_{novel}_{int(time.time()*1000)}"
    with _jobs_lock:
        _jobs[jid] = {"id": jid, "kind": kind, "novel": novel, "status": "queued",
                      "log": TimestampedLog(), "started": None, "finished": None, "error": None}
    return jid


_NUMPY_PY = None


def _python_with_numpy(py: str) -> list:
    """The author-brain scripts need numpy; the python on PATH may not have it (here 3.14 has none, 3.12 does). Found once."""
    global _NUMPY_PY
    if _NUMPY_PY is None:
        import subprocess as _sp
        for cand in ([py], ["py", "-3.12"], ["py", "-3"]):
            try:
                if _sp.run(cand + ["-c", "import numpy"], capture_output=True, timeout=60).returncode == 0:
                    _NUMPY_PY = cand
                    break
            except Exception:
                continue
        _NUMPY_PY = _NUMPY_PY or []
    return _NUMPY_PY


def _refresh_author_brain(job: dict, py: str, novel: str):
    """The author's brain (the author's plan notes, read by the Conspiracy, Arc planner and Timeline): author_brain_claude.py rebuilds the
    Python + semantic pass (seconds), then, when this novel's author notes are missing or 20+ chapters old, runs Claude Code headless with
    grep / read / the filtered knowledge search to write them, and folds them in. The knowledge-index rows are then refreshed so the
    planners find it. Never fails the job."""
    if job.get("aborted"):
        return
    npy = _python_with_numpy(py)
    if not npy:
        job["log"].append("  ⚠ author brain skipped: no python with numpy found (py -3.12 has it on this machine)")
        return
    f = NOVELS_DIR / novel / "author_brain.json"
    before = f.stat().st_mtime if f.exists() else None
    if not _run_cmd(job, npy + [str(_script("author_brain_claude.py")), "--novel", novel], "author brain (Python + semantic, then Claude's notes)"):
        job["log"].append("  ⚠ author brain not fully refreshed (the next run retries); the job itself is fine")
    after = f.stat().st_mtime if f.exists() else None
    if after and after != before and not job.get("aborted"):
        _run_cmd(job, [py, str(_script("build_knowledge_index.py")), novel], "index the author brain")


def _run_cmd(job: dict, args: list, label: str, on_line=None) -> bool:
    """Run one pipeline command from the corpus dir, streaming output into the job log."""
    import os as _os
    # If the job was already aborted, don't even start.
    if job.get("aborted"):
        return False
    job["log"].append(f"$ {label}")
    # Force unbuffered Python output so the console streams live (not dumped at the end)
    if args and args[0] and "python" in str(args[0]).lower() and "-u" not in args:
        args = [args[0], "-u"] + list(args[1:])
    env = {**_os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    if job.get("force_engine"):
        env["NM_FORCE_ENGINE"] = job["force_engine"]        # process-level pin: the app's settings file is not touched
    if not any("extract_v3" in str(x) for x in args):       # a finishing step: its one agent takes the LAST pooled key
        env["NM_NEM_SLOT_START"] = "3"
    env["NM_STEP_LABEL"] = label.split(" (")[0][:40]        # shown on each Nemotron call line (which step is calling)
    try:
        proc = subprocess.Popen(
            args, cwd=str(CORPUS_PATH),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            bufsize=1, env=env,
        )
        job["_proc"] = proc   # expose so /abort can kill it
        job.setdefault("_procs", set()).add(proc)     # the finishing steps run side by side: Abort must reach each one
        for line in proc.stdout:
            if job.get("aborted"):
                _kill_proc(proc)
                job["log"].append("  ⛔ aborted")
                return False
            line = line.rstrip()
            if line:
                job["log"].append(line)
                if len(job["log"]) > 400:
                    del job["log"][:-400]
                if on_line is not None:
                    try:
                        on_line(line)
                    except Exception:
                        pass
        proc.wait()
        if job.get("aborted"):
            return False
        if proc.returncode != 0:
            job["error"] = f"{label} exited {proc.returncode}"
            return False
        return True
    except Exception as e:
        job["error"] = f"{label} failed: {str(e)[:200]}"
        return False
    finally:
        job["_proc"] = None
        try:
            job.get("_procs", set()).discard(proc)
        except Exception:
            pass


def _kill_proc(proc):
    """Terminate a subprocess and its children (extract/merge scripts)."""
    try:
        if proc and proc.poll() is None:
            if sys.platform == "win32":
                # taskkill the whole tree so child claude CLI dies too
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               capture_output=True)
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
    except Exception:
        pass


# Top-level v3 keys that the LLM (not the programmatic pass) is responsible for.
# A delta missing most of these is a failed extraction worth redoing.
# Must stay in sync with extract_v3.py's LLM_FIELDS. This previously listed only
# 9 of the 25 schema fields, so the validation round reported "9/9 OK" while
# character_voice_samples / narrative_voice_analysis / scene_structure_patterns /
# power_curve_notes / antagonist_template_instances sat empty — it could not
# repair gaps it never inspected.
_V3_LLM_KEYS = [
    "chapter_title", "title_function", "chapter_function", "summary",
    "arc_label_suggestion", "arc_boundary_signal", "arc_notes",
    "new_characters", "new_locations", "new_factions", "new_glossary_terms",
    "facts", "timeline_events", "humor_instances", "scheme_instances",
    "knowledge_state", "antagonist_template_instances", "power_curve_notes",
    "reveals", "reader_psychology", "author_intent", "prose_samples",
    "character_voice_samples", "scene_structure_patterns", "narrative_voice_analysis",
]


def _delta_quality(path: Path, chapter_text: str = "") -> tuple:
    """Return (ok, filled, total, reason). A delta is 'ok' if it parses, fills a
    reasonable share of the LLM fields, AND those fields aren't obviously poor."""
    if not path.exists():
        return (False, 0, len(_V3_LLM_KEYS), "missing")
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return (False, 0, len(_V3_LLM_KEYS), f"unparseable ({str(e)[:40]})")
    _e = lambda v: v in (None, "", [], {})
    filled = sum(1 for k in _V3_LLM_KEYS if not _e(d.get(k)))
    problems = []
    # summary is the single most important field
    summ = str(d.get("summary") or "").strip()
    if not summ:
        problems.append("no summary")
    elif len(summ) < 60:
        problems.append("weak summary")
    # No-gaps policy: every schema field must be populated. A delta that fills
    # only some of them is sent for targeted repair rather than accepted, so
    # voice/structure fields can't silently stay empty across a whole run.
    #
    # Exception: fields the model explicitly confirmed absent ("none" answers,
    # recorded in confirmed_empty by extract_v3). Those were inspected and ruled
    # on — repairing them just re-derives the same empty list, which previously
    # cost two repair calls plus a full re-extract per chapter for zero gain.
    confirmed = set(d.get("confirmed_empty") or [])
    empty_keys = [k for k in _V3_LLM_KEYS if _e(d.get(k)) and k not in confirmed]
    if empty_keys:
        shown = ", ".join(empty_keys[:6]) + ("…" if len(empty_keys) > 6 else "")
        problems.append(f"{filled}/{len(_V3_LLM_KEYS)} fields (empty: {shown})")
    # poor structured fields on a substantial chapter
    big = len(chapter_text) > 3000
    if big and _e(d.get("reveals")) and _e(d.get("facts")):
        problems.append("no facts/reveals")
    rp = d.get("reader_psychology")
    if isinstance(rp, dict) and sum(1 for v in rp.values() if not _e(v)) < 2 and not _e(rp):
        problems.append("thin reader_psychology")
    ok = len(problems) == 0
    reason = "" if ok else ("poor: " + ", ".join(problems))
    return (ok, filled, len(_V3_LLM_KEYS), reason)


# Core narrative fields whose item counts measure how much was actually
# extracted. Field-count alone can't see the difference between a delta with 20
# facts and one with 10 — both "fill" the key — so a re-extract that halved the
# plot content used to be accepted as an improvement.
_CONTENT_KEYS = [
    "facts", "timeline_events", "reveals", "knowledge_state",
    "prose_samples", "character_voice_samples", "humor_instances",
    "new_characters", "new_locations", "new_factions", "new_glossary_terms",
]


def _delta_content_score(path: Path) -> int:
    """Total items across the core narrative lists — a proxy for how much real
    content a delta carries, used to compare two candidate extractions."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return -1
    total = 0
    for k in _CONTENT_KEYS:
        v = d.get(k)
        if isinstance(v, list):
            total += len(v)
        elif isinstance(v, dict):
            total += sum(1 for x in v.values() if x not in (None, "", [], {}))
    return total


def _validate_and_fix(job: dict, py: str, novel: str, start: int, end: int, max_retries: int = 2):
    """Validation round: inspect each extracted delta and re-extract the ones that
    came out empty/thin. Logs a per-chapter report to the job console."""
    deltas_dir = NOVELS_DIR / novel / "deltas_v3"
    raw_dir = RAW_DIR / novel
    job["log"].append(f"$ validation round (ch{start}-{end})")

    def _raw_text(ch):
        rf = raw_dir / f"ch{ch}.txt"
        try:
            return rf.read_text(encoding="utf-8", errors="ignore") if rf.exists() else ""
        except Exception:
            return ""

    failed = []
    for ch in range(start, end + 1):
        f = deltas_dir / f"ch{ch}.json"
        ok, filled, total, reason = _delta_quality(f, _raw_text(ch))
        if ok:
            job["log"].append(f"  ch{ch}: OK ({filled}/{total} fields)")
        else:
            job["log"].append(f"  ch{ch}: FAILED — {reason} → targeted repair")
            failed.append(ch)

    import time as _time
    for idx, ch in enumerate(failed):
        if job.get("aborted"):
            job["log"].append("  ⛔ validation aborted")
            return
        delta_path = deltas_dir / f"ch{ch}.json"
        fixed = False
        # If the delta is MISSING entirely, targeted repair is pointless — go
        # straight to full extraction. Only present-but-thin deltas get repaired.
        if delta_path.exists():
            for attempt in range(1, max_retries + 1):
                job["log"].append(f"  repairing ch{ch} (targeted, attempt {attempt}/{max_retries})…")
                _run_cmd(job, [py, str(_script("extract_v3.py")), "--novel", novel,
                               "--repair", "--chapter", str(ch)],
                         f"repair ch{ch}")
                ok, filled, total, reason = _delta_quality(delta_path, _raw_text(ch))
                if ok:
                    job["log"].append(f"  ch{ch}: FIXED ({filled}/{total} fields)")
                    fixed = True
                    break
                else:
                    job["log"].append(f"  ch{ch}: still {reason}")
        if not fixed:
            label = "full re-extract" if delta_path.exists() else "extract (was missing)"
            job["log"].append(f"  ch{ch}: {label}…")
            # A full re-extract can come back WORSE (fewer facts/reveals) while
            # still filling one more field. Keep a copy and restore it if the
            # fresh attempt carries less actual content.
            backup = None
            if delta_path.exists():
                backup = delta_path.with_suffix(".json.prev")
                try:
                    shutil.copy2(delta_path, backup)
                except OSError:
                    backup = None
            before_score = _delta_content_score(delta_path) if backup else -1

            _run_cmd(job, [py, str(_script("extract_v3.py")), "--novel", novel,
                           "--start", str(ch), "--end", str(ch)],
                     f"{label} ch{ch}")

            if backup and backup.exists():
                after_score = _delta_content_score(delta_path)
                if after_score < before_score:
                    try:
                        shutil.copy2(backup, delta_path)
                        job["log"].append(
                            f"  ch{ch}: re-extract was thinner "
                            f"({after_score} vs {before_score} items) — kept original")
                    except OSError:
                        pass
                try:
                    backup.unlink()
                except OSError:
                    pass
            ok, filled, total, reason = _delta_quality(delta_path, _raw_text(ch))
            if ok:
                job["log"].append(f"  ch{ch}: FIXED ({filled}/{total} fields)")
            else:
                job["log"].append(f"  ⚠ ch{ch}: still {reason} (kept best effort; API key would improve quality)")
        # Small gap between chapters so a big validation round doesn't hammer the
        # subscription CLI into throttling.
        if idx < len(failed) - 1:
            _time.sleep(2)
    if not failed:
        job["log"].append("  ✓ all chapters passed validation")
    else:
        job["log"].append(f"  validation done: {len(failed)} re-extracted")


def _merged_chapters(novel: str) -> set:
    """Chapter numbers that actually landed in the merged wiki brain. reader_psychology alone is not enough: a chapter whose delta has no
    reader psychology leaves no entry there, was judged "unmerged" and got merged again on every run (its records multiplying). So a
    chapter also counts when it has timeline events or narrative-tracking entries."""
    out: set = set()
    for rel in ("reader_psychology/chapters.json", "timeline/events.json", "narrative/pov_tracking.json"):
        f = NOVELS_DIR / novel / rel
        if not f.exists():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            out |= {r.get("chapter") for r in data if isinstance(r, dict) and r.get("chapter")}
        except Exception:
            pass
    return out


def _verify_merge(job: dict, py: str, novel: str, start: int, end: int, max_retries: int = 2):
    """Post-merge verification: confirm every chapter that had a delta actually
    made it into the brain. Re-merge any that silently didn't (the gap you can
    otherwise only find by hand)."""
    deltas_dir = NOVELS_DIR / novel / "deltas_v3"
    job["log"].append(f"$ verify merge (ch{start}-{end})")
    # Chapters we expected to merge = those with a delta on disk in range.
    expected = [ch for ch in range(start, end + 1) if (deltas_dir / f"ch{ch}.json").exists()]
    if not expected:
        job["log"].append("  (no deltas in range to verify)")
        return
    in_brain = _merged_chapters(novel)
    missing = [ch for ch in expected if ch not in in_brain]
    for ch in expected:
        if ch in in_brain:
            job["log"].append(f"  ch{ch}: in brain ✓")
        else:
            job["log"].append(f"  ch{ch}: NOT in brain → re-merge")
    # Re-merge any that didn't land, one at a time, and re-check.
    for ch in missing:
        fixed = False
        for attempt in range(1, max_retries + 1):
            job["log"].append(f"  re-merging ch{ch} (attempt {attempt}/{max_retries})…")
            _run_cmd(job, [py, str(_script("merge.py")), "--novel", novel,
                           str(deltas_dir / f"ch{ch}.json")],
                     f"re-merge ch{ch}")
            if ch in _merged_chapters(novel):
                job["log"].append(f"  ch{ch}: FIXED — now in brain")
                fixed = True
                break
        if not fixed:
            # Re-merge kept failing → the DELTA is likely malformed. Chain the
            # targeted fix: re-extract the source delta, then merge it again.
            job["log"].append(f"  ch{ch}: re-merge failed → re-extracting source delta, then merging")
            _run_cmd(job, [py, str(_script("extract_v3.py")), "--novel", novel,
                           "--start", str(ch), "--end", str(ch)],
                     f"re-extract ch{ch} (bad delta)")
            _run_cmd(job, [py, str(_script("merge.py")), "--novel", novel,
                           str(deltas_dir / f"ch{ch}.json")],
                     f"merge fresh ch{ch}")
            if ch in _merged_chapters(novel):
                job["log"].append(f"  ch{ch}: FIXED via re-extract + merge")
            else:
                job["log"].append(f"  ⚠ ch{ch}: still not in brain (check ch{ch}.json manually)")
    if not missing:
        job["log"].append("  ✓ all merged chapters verified in brain")
    else:
        job["log"].append(f"  verify done: {len(missing)} chapters repaired")


def _verify_genome(job: dict, py: str, novel: str, max_retries: int = 1) -> bool:
    """Post-genome verification: confirm narrative_genome.json exists, is valid,
    has patterns, and is newer than the last brain merge (not stale). Regenerate
    once if it's missing/broken/stale."""
    gfile = NOVELS_DIR / novel / "narrative_genome.json"
    brain = NOVELS_DIR / novel / "reader_psychology" / "chapters.json"
    job["log"].append("$ verify genome")

    def _check():
        if not gfile.exists():
            return False, "genome file missing"
        try:
            g = json.loads(gfile.read_text(encoding="utf-8"))
        except Exception as e:
            return False, f"genome unparseable ({str(e)[:40]})"
        pats = g.get("patterns", []) if isinstance(g, dict) else []
        if not pats:
            return False, "genome has no patterns"
        # stale = the generator's own rule (it skips until the novel has grown by 15 chapters or 20%), not file times
        try:
            r = subprocess.run([_python(), "-c", f"import sys, generate_genome as g; sys.exit(1 if g.is_stale({novel!r}) else 0)"],
                               cwd=str(CORPUS_PATH), capture_output=True, timeout=60)
            if r.returncode == 1:
                return False, "genome is stale (the novel has grown enough to regenerate it)"
            if r.returncode == 0:
                return True, f"{len(pats)} patterns, current"
        except Exception:
            pass
        if brain.exists() and gfile.stat().st_mtime < brain.stat().st_mtime - 1:
            return False, "genome is stale (older than last merge)"
        return True, f"{len(pats)} patterns, current"

    ok, reason = _check()
    if ok:
        job["log"].append(f"  ✓ genome verified — {reason}")
        return True
    for attempt in range(1, max_retries + 1):
        job["log"].append(f"  genome {reason} → regenerating (attempt {attempt}/{max_retries})…")
        _run_cmd(job, [py, str(_script("generate_genome.py")), "--novel", novel], "regenerate genome")
        ok, reason = _check()
        if ok:
            job["log"].append(f"  ✓ genome fixed — {reason}")
            return True
    job["log"].append(f"  ⚠ genome still {reason} after retry")
    return False


def _verify_rolling_summary(job: dict, py: str, novel: str, max_retries: int = 1) -> bool:
    """Post-rolling-summary verification — same shape as _verify_genome above:
    confirm rolling_summary.json exists, is valid, has non-empty text, and has
    actually caught up to the last merged chapter (not stale). Regenerate once
    if missing/broken/behind."""
    rfile = NOVELS_DIR / novel / "rolling_summary.json"
    brain = NOVELS_DIR / novel / "reader_psychology" / "chapters.json"
    job["log"].append("$ verify rolling summary")

    def _check():
        if not rfile.exists():
            return False, "rolling summary file missing"
        try:
            r = json.loads(rfile.read_text(encoding="utf-8"))
        except Exception as e:
            return False, f"rolling summary unparseable ({str(e)[:40]})"
        if not isinstance(r, dict) or not (r.get("summary") or "").strip():
            return False, "rolling summary is empty"
        folded = r.get("last_chapter_folded", 0)
        merged = _merged_chapters(novel)
        fs = r.get("folded_chapters")
        if isinstance(fs, list):
            missing = sorted(set(merged) - {int(x) for x in fs})
            if missing:
                return False, f"behind — {len(missing)} merged chapter(s) not folded in (ch{missing[0]}...)"
            return True, f"current - {len(fs)} chapters folded"
        latest = max(merged, default=0)
        if latest and folded < latest:
            return False, f"behind — folded through ch{folded}, brain has ch{latest}"
        return True, f"current through ch{folded}"

    ok, reason = _check()
    if ok:
        job["log"].append(f"  ✓ rolling summary verified — {reason}")
        return True
    for attempt in range(1, max_retries + 1):
        job["log"].append(f"  rolling summary {reason} → updating (attempt {attempt}/{max_retries})…")
        _run_cmd(job, [py, str(_script("update_rolling_summary.py")), "--novel", novel], "update rolling summary")
        ok, reason = _check()
        if ok:
            job["log"].append(f"  ✓ rolling summary fixed — {reason}")
            return True
    job["log"].append(f"  ⚠ rolling summary still {reason} after retry")
    return False


def _catchup_unfinished(job: dict, py: str, novel: str, steps: dict):
    """PRE-FLIGHT: an aborted earlier run can leave extracted deltas that never
    made it into the brain, and a genome built from that incomplete brain.
    Merge those orphans (and refresh a stale genome) BEFORE the normal routine,
    so every run starts from a consistent corpus state."""
    import re as _re
    job["log"].append("$ pre-flight: checking for unmerged / ungenomed leftovers")
    deltas_dir = NOVELS_DIR / novel / "deltas_v3"
    have = []
    if deltas_dir.exists():
        for f in deltas_dir.glob("ch*.json"):
            m = _re.match(r"ch(\d+)\.json$", f.name)
            if m:
                have.append(int(m.group(1)))
    if not have:
        job["log"].append("  (no prior deltas — nothing to catch up)")
        return

    in_brain = _merged_chapters(novel)
    orphans = sorted(ch for ch in have if ch not in in_brain)
    if orphans:
        shown = ", ".join(f"ch{c}" for c in orphans[:15]) + (" …" if len(orphans) > 15 else "")
        job["log"].append(f"  found {len(orphans)} extracted-but-unmerged chapters: {shown}")
        files = [str(deltas_dir / f"ch{ch}.json") for ch in orphans]
        _run_cmd(job, [py, str(_script("merge.py")), "--novel", novel] + files,
                 f"catch-up merge ({len(orphans)} orphan deltas)")
        still = [ch for ch in orphans if ch not in _merged_chapters(novel)]
        if still:
            job["log"].append(f"  ⚠ still unmerged after catch-up: {still} — verify step will retry")
        else:
            job["log"].append("  ✓ all orphan deltas merged")
        # every merge is followed by a conflict review + auto-fix
        _run_cmd(job, [py, str(_script("resolve_conflicts.py")), "--novel", novel],
                 "resolve conflicts (post catch-up merge)")

    # Genome staleness — only refresh NOW if this job's own genome step won't.
    gfile = NOVELS_DIR / novel / "narrative_genome.json"
    brain = NOVELS_DIR / novel / "reader_psychology" / "chapters.json"
    stale = brain.exists() and (
        not gfile.exists() or gfile.stat().st_mtime < brain.stat().st_mtime - 1)
    if stale and not steps.get("genome"):
        job["log"].append("  genome missing/stale → refreshing now")
        _run_cmd(job, [py, str(_script("generate_genome.py")), "--novel", novel],
                 "catch-up genome refresh")
    elif stale:
        job["log"].append("  genome is stale — this job's genome step will refresh it")
    elif not orphans:
        job["log"].append("  ✓ nothing to catch up — brain and genome are consistent")


# ── Finishing steps run beside the extraction, not after it ──
# What each step needs: the ROLLING SUMMARY reads only the chapter deltas (extraction + validation done is enough); conflicts and
# the genome read the merged brain. So after validation the rolling summary starts at once, in the background, while the merge and
# its conflicts/genome chain run; and that chain, too, runs in the background so the queue can start the NEXT range's extraction
# straight away. The brain lock keeps two ranges' merges from overlapping the previous range's conflicts/genome.
_BRAIN_LOCKS: dict = {}       # novel -> Lock held from a range's merge until its conflicts + genome are done
_RS_LOCKS: dict = {}          # novel -> Lock: one rolling-summary run at a time (its folds are sequential by nature)
_TAILS: dict = {}             # novel -> the finalizer thread of the latest range (alive while its finishing steps run)
_locks_guard = threading.Lock()
_ACTIVE: dict = {}            # novel -> how many pipeline jobs of that novel are in flight (several can overlap now)
_QLOCK = threading.RLock()    # the queue file is read-modified-written from several job threads
_EARLY_EVERY = 5              # a rolling summary starts early after this many newly saved chapters


def _early_rolling_summary(job: dict, py: str, novel: str, saved: int, tails: list):
    """Fold the chapters saved so far into the rolling summary while the extraction is still running (it only reads the chapter
    files). One at a time per novel: if one is already running, this one is skipped - the next trigger or the end-of-job run covers it."""
    lock = _novel_lock(_RS_LOCKS, novel)
    if not lock.acquire(blocking=False):
        return

    def _go():
        try:
            _run_cmd(job, [py, str(_script("update_rolling_summary.py")), "--novel", novel],
                     f"update rolling summary (early, {saved} chapters saved)")
        finally:
            lock.release()
    th = threading.Thread(target=_go, daemon=True)
    th.start()
    tails.append(("early rolling summary", th, {"ok": True}))      # joined before the job closes; its outcome never fails the job


def _novel_lock(table: dict, novel: str) -> threading.Lock:
    with _locks_guard:
        return table.setdefault(novel, threading.Lock())


def _pipeline(job_id: str, novel: str, steps: dict, start: int, end: int, drained_evt=None):
    job = _jobs[job_id]
    job["status"] = "running"
    job["started"] = time.time()
    if steps.get("nemotron_only"):
        job["force_engine"] = "nemotron"
        job["log"].append("Nemotron only: every step of this job runs on Nemotron (the dropdown / settings engine is ignored)")
    with _locks_guard:
        _ACTIVE[novel] = _ACTIVE.get(novel, 0) + 1
    py = _python()
    ok = True
    tails: list = []                       # (name, thread, result dict) for every background piece of this job
    brain_lock = _novel_lock(_BRAIN_LOCKS, novel)
    holding_brain = False

    try:
        # PRE-FLIGHT: finish any leftovers from an aborted earlier run first. Skipped while the previous range's own
        # finishing steps are still running - they are not leftovers, and running them twice would collide.
        prev = _TAILS.get(novel)
        if _ACTIVE.get(novel, 0) > 1:
            job["log"].append("$ pre-flight skipped: another range of this novel is still being processed (its chapters are not leftovers)")
        elif prev is not None and prev.is_alive():
            job["log"].append("$ pre-flight skipped: the previous range's finishing steps are still running in the background")
        else:
            try:
                if not job.get("aborted"):
                    _catchup_unfinished(job, py, novel, steps)
            except Exception as e:
                job["log"].append(f"  ⚠ pre-flight check failed: {str(e)[:120]} — continuing")

        if ok and steps.get("extract"):
            # --skip-existing: an interrupted range can be re-run without re-extracting
            # finished chapters; the validation round still repairs poor-quality ones.
            saved = {"n": 0, "next": _EARLY_EVERY}
            ok_re = re.compile(r"\[OK\] .*deltas_v3[\\/]ch\d+\.json")

            def _extract_line(line):
                if drained_evt is not None and "agents free for the next range" in line:
                    drained_evt.set()                              # the queue worker may start the next range now
                if steps.get("rolling_summary") and ok_re.search(line):
                    saved["n"] += 1
                    if saved["n"] >= saved["next"]:
                        saved["next"] += _EARLY_EVERY
                        _early_rolling_summary(job, py, novel, saved["n"], tails)

            ok = _run_cmd(job, [py, str(_script("extract_v3.py")), "--novel", novel,
                                "--start", str(start), "--end", str(end), "--skip-existing"],
                          f"extract v3 (ch{start}-{end})", on_line=_extract_line)
            # ── Validation round: check each delta, re-extract any that came out
            #    empty/thin (common when the subscription CLI returns a stub). ──
            if ok:
                _validate_and_fix(job, py, novel, start, end)

        # ── Rolling summary: needs only the deltas, so it starts NOW and runs beside the merge. ──
        if ok and steps.get("rolling_summary") and not job.get("aborted"):
            rs_res = {"ok": True}

            def _rolling():
                lock = _novel_lock(_RS_LOCKS, novel)
                with lock:
                    # Runs on the WHOLE novel each call (not just this range) since it's incremental internally -
                    # update_rolling_summary.py reads its own last_chapter_folded checkpoint and only folds in
                    # what's actually new.
                    r = _run_cmd(job, [py, str(_script("update_rolling_summary.py")), "--novel", novel],
                                 "update rolling summary")
                    if r:
                        r = _verify_rolling_summary(job, py, novel) is not False
                    rs_res["ok"] = bool(r)
            th = threading.Thread(target=_rolling, daemon=True)
            th.start()
            tails.append(("rolling summary", th, rs_res))

        if ok and steps.get("merge"):
            # Wait for the previous range's conflicts/genome (they read the brain this merge is about to change).
            if not brain_lock.acquire(blocking=False):
                job["log"].append("  (waiting for the previous range's conflicts / genome to finish before merging)")
                brain_lock.acquire()
            holding_brain = True
            # Only merge the deltas for the requested chapter range, ALWAYS with
            # --novel, and only chapters NOT already in the brain — re-merging a
            # merged chapter duplicates append-only aggregates.
            deltas_dir = NOVELS_DIR / novel / "deltas_v3"
            in_brain = _merged_chapters(novel)
            wanted, already = [], []
            for ch in range(start, end + 1):
                f = deltas_dir / f"ch{ch}.json"
                if f.exists():
                    (already if ch in in_brain else wanted).append(f)
            if already:
                job["log"].append(f"  skipping {len(already)} already-merged chapters in range")
            if wanted:
                ok = _run_cmd(job, [py, str(_script("merge.py")), "--novel", novel] + [str(d) for d in wanted],
                              f"merge ch{start}-{end} ({len(wanted)} deltas) into {novel}")
                # ── Verify merge: confirm each chapter actually landed in the brain,
                #    re-merge any that silently didn't. ──
                if ok:
                    _verify_merge(job, py, novel, start, end)
            else:
                job["log"].append(f"(no deltas for ch{start}-{end} to merge)")

            # ── Conflicts + genome: in the background, holding the brain lock, so the next range can start extracting. ──
            if ok and not job.get("aborted"):
                ch_res = {"ok": True}

                def _chain():
                    try:
                        # auto-merge near-miss entity names (LLM adjudicates ambiguous pairs), relink humor callbacks, prune notes
                        _run_cmd(job, [py, str(_script("resolve_conflicts.py")), "--novel", novel], "resolve conflicts")
                        # the index updates read the merged + conflict-resolved brain: start them now, beside the genome and the
                        # rolling summary, instead of after the slowest of those finishes
                        if not job.get("aborted"):
                            try:
                                _notify_pipeline_new_data(job, novel)
                            except Exception as e:
                                job["log"].append(f"  ⚠ could not notify the pipeline of new data: {str(e)[:100]}")
                        if steps.get("genome") and not job.get("aborted"):
                            g = _run_cmd(job, [py, str(_script("generate_genome.py")), "--novel", novel], "generate genome")
                            # ── Verify genome: exists, valid, has patterns, not stale. Regenerate if not. ──
                            if g:
                                _verify_genome(job, py, novel)
                            ch_res["ok"] = bool(g)
                            _refresh_author_brain(job, py, novel)
                    except Exception as e:
                        ch_res["ok"] = False
                        job["log"].append(f"  ⚠ finishing steps failed: {str(e)[:150]}")
                    finally:
                        brain_lock.release()
                th = threading.Thread(target=_chain, daemon=True)
                th.start()
                holding_brain = False               # the chain thread releases it
                tails.append(("conflicts + genome", th, ch_res))
        elif ok and steps.get("genome") and not job.get("aborted"):
            # no merge in this job: the genome step alone (kept as before)
            ok = _run_cmd(job, [py, str(_script("generate_genome.py")), "--novel", novel], "generate genome")
            if ok:
                _verify_genome(job, py, novel)
    finally:
        if holding_brain:
            brain_lock.release()

    def _finalize():
        all_ok = ok
        for name, th, res in tails:
            th.join()
            if not res.get("ok", True):
                all_ok = False
        if job.get("aborted"):
            job["status"] = "aborted"
        else:
            job["status"] = "done" if all_ok else "error"
        job["finished"] = time.time()
        with _locks_guard:
            _ACTIVE[novel] = max(0, _ACTIVE.get(novel, 1) - 1)
        _sync_queue_status(job)
        # Phone alert (Web Push, same channel as the narration jobs): one message when the pipeline job is completely finished
        try:
            from routers.generation.jobs import push_all
            mins = max(1, round((job["finished"] - (job.get("started") or job["finished"])) / 60))
            more = sum(1 for it in _load_queue() if it.get("status") == "pending")
            tail = f" {more} more in the queue." if more else ""
            title = {"done": "Corpus Builder finished", "aborted": "Corpus Builder aborted"}.get(job["status"], "Corpus Builder failed")
            body = f"{novel} ch{start}-{end}: {job['status']} in {mins} min." + tail
            if job["status"] == "error" and job.get("error"):
                body += f" {str(job['error'])[:80]}"
            push_all(title, body, "/", "corpus-builder")
        except Exception as e:
            job["log"].append(f"  (phone alert not sent: {str(e)[:80]})")

    fin = threading.Thread(target=_finalize, daemon=True)
    _TAILS[novel] = fin
    fin.start()
    # The queue worker moves on to the next range now; this job stays "running" until its background steps are done.


def _notify_pipeline_new_data(job: dict, novel: str):
    """Thread Typing / Symbol Filtering build their processing queue ONCE at
    startup — new reveals/schemes/knowledge_state records this run's merge
    step just added for `novel` would otherwise sit unprocessed until
    someone happened to manually restart those jobs. If either is currently
    running, restart it (kill + fresh launch) so its queue picks up the new
    data immediately. Never auto-STARTS a job that's stopped — that's the
    author's own call, made from the Corpus Pipeline page. Best-effort: a
    failure here must never fail the corpus-builder run that already
    completed successfully."""
    try:
        from routers.corpus_tools.corpus import _PIPELINE_JOBS, _running_pipeline_pid, _launch_pipeline_job, _stop_pipeline_job

        # Symbol candidates come from a separate regex harvest corpus_builder
        # never runs on its own — without this, restarting Symbol Filtering
        # would find nothing new for THIS novel to actually filter.
        try:
            subprocess.run([_python(), str(_script("extract_symbols_regex.py")), novel],
                           cwd=str(CORPUS_PATH), capture_output=True, text=True, timeout=120)
        except Exception as e:
            job["log"].append(f"  ⚠ symbol-candidate harvest for {novel} failed: {str(e)[:120]}")

        # V4 Phase 4 — semantic search index. Scoped to just THIS novel and
        # incremental (build_knowledge_index.py's existing_keys() skips
        # anything already embedded), so this only pays for the genuinely
        # new chapters' worth of chunks — a handful of records, not the
        # 4-8-hour full-corpus cost. Blocking/synchronous like the symbol
        # harvest above; a few dozen embedding calls at ~1-2s each is well
        # within this timeout.
        try:
            result = subprocess.run([_python(), str(_script("build_knowledge_index.py")), novel],
                                    cwd=str(CORPUS_PATH), capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                job["log"].append(f"  🔎 semantic index updated for {novel}")
        except Exception as e:
            job["log"].append(f"  ⚠ semantic index update for {novel} failed: {str(e)[:120]}")

        # Humor index (the Pipeline tab's Humor Index (nomic) job), scoped to THIS
        # novel the same way: merge.py just appended its new chapters' humor beats
        # to humor/instances.json, and build_humor_index.py only embeds beats it
        # hasn't indexed yet (batched), refreshing the gag-family info on the rest.
        try:
            result = subprocess.run([_python(), str(_script("build_humor_index.py")), novel],
                                    cwd=str(CORPUS_PATH), capture_output=True, text=True, timeout=600)
            if result.returncode == 0:
                job["log"].append(f"  😂 humor index updated for {novel}")
        except Exception as e:
            job["log"].append(f"  ⚠ humor index update for {novel} failed: {str(e)[:120]}")

        # Chapter Mechanics (V4): chapters extracted with the V4 schema already carry their mechanics inside the delta;
        # this step (Python only, no LLM calls) stitches the novel's set-piece runs and indexes the new chapters'
        # mechanics for search. Chapters the extraction could not fill stay on the Pipeline tab's Chapter Mechanics card.
        try:
            result = subprocess.run([_python(), str(_script("build_mechanics_deltas.py")), "--runs-only", "--novel", novel],
                                    cwd=str(CORPUS_PATH), capture_output=True, text=True, timeout=900)
            if result.returncode == 0:
                job["log"].append(f"  🧩 chapter mechanics: runs stitched and indexed for {novel}")
        except Exception as e:
            job["log"].append(f"  ⚠ chapter mechanics update for {novel} failed: {str(e)[:120]}")

        # V4 Phase 6 — character roster (Steps 1+1.5). Scoped to just THIS
        # novel, same reasoning as the semantic index above: any characters
        # new chapters introduced get picked up (Step 1 always re-derives
        # facts/voice_samples fresh from entities/, so a new character or an
        # edited one is caught for free), and Step 1.5's semantic enrichment
        # is incremental via enrichment_attempted (see
        # build_character_roster.py) so this only pays embedding-call cost
        # for characters genuinely new since the last run, not the whole
        # novel's roster every time. Longer timeout than the knowledge index
        # call — Step 1.5 makes 2 embedding calls per NEW character, which
        # can exceed 300s if a novel gained many characters in one run
        # (a big multi-chapter batch introducing several new named characters
        # at once), where the knowledge index's per-chunk embedding cost
        # stays small and uniform by comparison.
        try:
            result = subprocess.run([_python(), str(_script("build_character_roster.py")), novel],
                                    cwd=str(CORPUS_PATH), capture_output=True, text=True, timeout=900)
            if result.returncode == 0:
                job["log"].append(f"  🎭 character roster updated for {novel}")
        except Exception as e:
            job["log"].append(f"  ⚠ character roster update for {novel} failed: {str(e)[:120]}")

        # The builder's OWN finishing steps (rolling summary, genome) are running the same scripts the Pipeline cards use:
        # _running_pipeline_pid would find them and the restart below would kill them (that ended a job in "error"). Leave those.
        own = set()
        for pr in list(job.get("_procs") or []):
            try:
                if pr.poll() is None:
                    own.add(" ".join(str(x) for x in (pr.args if isinstance(pr.args, (list, tuple)) else [pr.args])))
            except Exception:
                pass
        for job_key in _PIPELINE_JOBS:
            if any(_PIPELINE_JOBS[job_key]["script"] in a for a in own):
                job["log"].append(f"  ({_PIPELINE_JOBS[job_key]['label']}: this job's own step is running - not restarted)")
                continue
            if _running_pipeline_pid(_PIPELINE_JOBS[job_key]["script"]) is not None:
                _stop_pipeline_job(job_key)
                time.sleep(0.5)
                _launch_pipeline_job(job_key)
                job["log"].append(f"  ↻ restarted {_PIPELINE_JOBS[job_key]['label']} to pick up {novel}'s new records")
    except Exception as e:
        job["log"].append(f"  ⚠ could not refresh classification pipeline queue: {str(e)[:120]}")


def _sync_queue_status(job: dict):
    with _QLOCK:
        items = _load_queue()
        for it in items:
            if it.get("job_id") == job["id"]:
                it["status"] = job["status"]
                it["error"] = job.get("error")
        _save_queue(items)


class RunRequest(BaseModel):
    novel_id: str
    nemotron_only: bool = False      # pin every step of this job to Nemotron, whatever the dropdown / settings say
    convert: bool = True
    extract: bool = True
    merge: bool = True
    rolling_summary: bool = True
    genome: bool = True
    start: int = 1
    end: int = 50


@router.post("/run")
def run_pipeline(req: RunRequest):
    """Start a pipeline job for one novel (runs in a background thread)."""
    novel = _slug(req.novel_id)
    steps = {"convert": req.convert, "extract": req.extract,
             "merge": req.merge, "rolling_summary": req.rolling_summary, "genome": req.genome,
             "nemotron_only": req.nemotron_only}
    jid = _new_job("pipeline", novel)
    t = threading.Thread(target=_pipeline, args=(jid, novel, steps, req.start, req.end), daemon=True)
    t.start()
    return {"ok": True, "job_id": jid}


def _job_public(job: dict) -> dict:
    """Job dict safe for JSON — drops the live Popen handle.

    `now` is the server's own clock at response time. The UI timer subtracts it
    from the browser clock to cancel out any skew between the two machines —
    without it, a client whose clock differs shows a wrong (or negative)
    elapsed time, since `started` is stamped server-side.
    """
    out = {k: v for k, v in job.items() if k not in ("_proc", "_procs", "_tail")}
    out["now"] = time.time()
    return out


@router.get("/job/{job_id}")
def job_status(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return _job_public(job)


@router.get("/jobs")
def all_jobs():
    with _jobs_lock:
        return {"jobs": [_job_public(j) for j in
                         sorted(_jobs.values(), key=lambda j: j.get("started") or 0, reverse=True)]}


@router.post("/job/{job_id}/abort")
def abort_job(job_id: str):
    """Abort a running pipeline job: kill its current subprocess and stop the loop."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    job["aborted"] = True
    procs = set(job.get("_procs") or [])
    if job.get("_proc") is not None:
        procs.add(job["_proc"])
    for proc in procs:
        _kill_proc(proc)
    if procs:
        job["log"].append("  ⛔ abort requested — stopping")
    return {"ok": True, "aborted": True}


# ── Persistent extraction queue ─────────────────────────────────────────────
class QueueItem(BaseModel):
    novel_id: str
    nemotron_only: bool = False
    start: int = 1
    end: int = 50
    convert: bool = True
    extract: bool = True
    merge: bool = True
    rolling_summary: bool = True
    genome: bool = True


@router.get("/queue")
def get_queue():
    return {"queue": _load_queue()}


@router.post("/queue/add")
def queue_add(item: QueueItem):
    items = _load_queue()
    entry = item.model_dump()
    entry["novel_id"] = _slug(entry["novel_id"])
    entry["id"] = f"q_{int(time.time()*1000)}"
    entry["status"] = "pending"
    entry["job_id"] = None
    items.append(entry)
    _save_queue(items)
    return {"ok": True, "item": entry}


@router.post("/queue/remove/{item_id}")
def queue_remove(item_id: str):
    items = [i for i in _load_queue() if i.get("id") != item_id]
    _save_queue(items)
    return {"ok": True}


def _queue_worker():
    """Dispatch the queued ranges. Each one runs in its own thread; the next is started as soon as the current one has handed out
    its LAST extraction part (the agents that finish early would otherwise sit idle until the slowest part is done) or has ended,
    whichever comes first. At most two ranges are ever extracting at once."""
    global _worker_running
    _worker_running = True
    try:
        while True:
            with _QLOCK:
                items = _load_queue()
                nxt = next((i for i in items if i.get("status") == "pending"), None)
                if not nxt:
                    break
                nxt["status"] = "running"
                jid = _new_job("pipeline", nxt["novel_id"])
                nxt["job_id"] = jid
                _save_queue(items)
            drained = threading.Event()
            steps = {"convert": nxt.get("convert", True), "extract": nxt.get("extract", True),
                     "merge": nxt.get("merge", True), "rolling_summary": nxt.get("rolling_summary", True),
                     "genome": nxt.get("genome", True), "nemotron_only": bool(nxt.get("nemotron_only", False))}

            def _run(jid=jid, nxt=nxt, steps=steps, drained=drained):
                try:
                    _pipeline(jid, nxt["novel_id"], steps, nxt.get("start", 1), nxt.get("end", 50), drained_evt=drained)
                except Exception as e:
                    # Never let one bad item wedge the whole queue.
                    j = _jobs.get(jid)
                    if j:
                        j["status"] = "error"
                        j["error"] = str(e)[:200]
                        with _locks_guard:
                            _ACTIVE[nxt["novel_id"]] = max(0, _ACTIVE.get(nxt["novel_id"], 1) - 1)
                    with _QLOCK:
                        its = _load_queue()
                        for it in its:
                            if it.get("job_id") == jid:
                                it["status"] = "error"
                        _save_queue(its)
                finally:
                    drained.set()                                   # ended (or never queued parts): the next range may start

            th = threading.Thread(target=_run, daemon=True)
            th.start()
            drained.wait()
            # mark done/error already synced via _sync_queue_status
    finally:
        _worker_running = False


@router.post("/queue/run")
def queue_run():
    """Process all pending queue items sequentially in the background."""
    global _worker_running, _worker_thread
    # Self-heal: trust the live thread, not a possibly-stuck flag. If the flag says
    # running but no thread is actually alive, start a fresh worker.
    alive = _worker_thread is not None and _worker_thread.is_alive()
    if _worker_running and alive:
        return {"ok": True, "already_running": True}
    _worker_running = False
    _worker_thread = threading.Thread(target=_queue_worker, daemon=True)
    _worker_thread.start()
    return {"ok": True, "started": True}
