"""
Server page backend — live CPU / memory / disk / network, plus a list of the
processes THIS APP is responsible for (so a stale one eating RAM or CPU can be
ended from the UI).

"Belongs to the app" is deliberately narrow — nothing else on the machine is ever
listed or killable:
  * this server itself (protected — cannot be ended from here)
  * any process the server spawned (CLI engines, agent shells, ...), found as
    descendants of the server process
  * NovelTea Engine script processes: python.exe whose command line points into the
    corpus folder. Pipeline jobs are launched through WMI (see corpus.py) so they
    are NOT children of the server — they can only be found by command line
  * Ollama and its model runners (the app depends on it for embeddings/local LLM)
  * older NovelTeaEngine.exe instances left over from a previous launch (flagged stale)

Kill requests are re-checked against that same list at the moment of the request,
so the endpoint cannot be used to end an arbitrary PID.
"""
import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Optional

import psutil
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import CORPUS_PATH

router = APIRouter()

SERVER_PORT = 7432
OLLAMA_URL = "http://127.0.0.1:11434"   # not "localhost": ~2s per call on Windows (IPv6 attempt first)

# A process that has done no CPU work for this long is reported idle / stale.
IDLE_AFTER_S = 120
STALE_AFTER_S = 15 * 60
SAMPLE_EVERY_S = 15

_NCPU = psutil.cpu_count(logical=True) or 1

# Friendly names for scripts the app launches (pipeline labels are added from corpus.py at call time).
_EXTRA_SCRIPT_LABELS = {
    "repair_style_dna.py": "Style DNA repair",
    "extract_v3.py": "Corpus extraction",
    "extract_batch.py": "Corpus extraction (batch)",
    "merge.py": "Corpus merge",
    "refresh_style_dna_evolution.py": "Style DNA aggregate rebuild",
    "train.py": "Embedding fine-tune",
}
_SCRIPT_LABELS: dict = {}


# ── process bookkeeping ────────────────────────────────────────────────────────
_lock = threading.Lock()
_procs: dict = {}      # pid -> psutil.Process (kept between polls so cpu_percent has a baseline)
_state: dict = {}      # pid -> {"cpu_total": float, "last_active": float, "first_seen": float, "create": float}
_sampler_started = False


def _script_labels() -> dict:
    if not _SCRIPT_LABELS:
        _SCRIPT_LABELS.update(_EXTRA_SCRIPT_LABELS)
        try:
            from routers.corpus_tools.corpus import _PIPELINE_JOBS
            for job in _PIPELINE_JOBS.values():
                _SCRIPT_LABELS[Path(job["script"].replace("\\", "/")).name] = job["label"]
        except Exception:
            pass
    return _SCRIPT_LABELS


def _server_pids() -> set:
    """This server's own process ids. Frozen exe: a bootloader parent plus the real
    process share the exe name — both are 'the server'."""
    me = psutil.Process(os.getpid())
    pids = {me.pid}
    if getattr(sys, "frozen", False):
        try:
            p = me
            while p.parent() is not None and p.parent().name().lower() == me.name().lower():
                p = p.parent()
                pids.add(p.pid)
        except Exception:
            pass
    return pids


def _corpus_marks() -> list:
    marks = [str(CORPUS_PATH).lower()]
    try:
        marks.append(str(Path(__file__).resolve().parent.parent.parent).lower())   # backend dir (dev mode)
    except Exception:
        pass
    return [m for m in marks if m]


def _colibri_procs() -> dict:
    """pid -> (psutil.Process, label) for the local Colibrì model server: its gateway
    (python running openai_server.py from the Colibrì install, or the pid the app recorded), the
    engine exe it spawned (this is what holds the model in RAM), and the `py` launcher above it.
    Found by command line, not by folder, because Colibrì lives outside the app's own tree."""
    try:
        from services import colibri_server as cs
        inst = cs.install_dir()
        inst_s = str(inst).lower() if inst else ""
        recorded = cs._state().get("pid")
    except Exception:
        return {}
    found = {}
    for p in psutil.process_iter(["pid", "name"]):
        try:
            n = (p.info.get("name") or "").lower()
            if not n.startswith(("python", "py.")):
                continue
            args = [a.strip('"') for a in (p.cmdline() or [])]
            script = next((a for a in args if a.lower().endswith("openai_server.py")), None)
            if not script:
                continue
            if not ((inst_s and script.lower().startswith(inst_s)) or p.pid == recorded):
                continue   # some other openai_server.py — not ours
            found[p.pid] = (p, "Colibrì gateway (local model server)")
            for c in p.children(recursive=True):
                cn = (c.name() or "").lower()
                found.setdefault(c.pid, (c, f"Colibrì engine ({cn}) — holds the model in RAM"
                                         if cn not in ("conhost.exe",) else "console host"))
            par = p.parent()
            if par is not None and (par.name() or "").lower().startswith("py."):
                found.setdefault(par.pid, (par, "Colibrì launcher (py)"))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found


def _classify(p: "psutil.Process", server_pids: set, descendants: set, marks: list, colibri: dict = None):
    """(category, label, protected) if p belongs to the app, else None."""
    if colibri and p.pid in colibri:
        return ("colibri", colibri[p.pid][1], False)
    try:
        name = (p.name() or "").lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None
    if p.pid in server_pids:
        return ("server", "NovelTea Engine server (this app)", True)
    if name.startswith("ollama") or name == "llama-server.exe":
        try:
            exe = (p.exe() or "").lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            exe = ""
        if name.startswith("ollama") or "ollama" in exe:
            role = ("Ollama tray app" if "app" in name else
                    "Ollama model runner" if name != "ollama.exe" else "Ollama server")
            return ("ollama", role, False)
    if name == "novelteaengine.exe":
        # Only the packaged app may call another exe instance "older": it knows it is THE app.
        # A server run from source (dev, or a test) must never treat the real running app as
        # leftover — that would let "End all stale" end the live app (it did, once, in testing).
        if getattr(sys, "frozen", False):
            return ("stale_app", "Older NovelTea Engine instance", False)
        return None
    try:
        cmd = " ".join(p.cmdline() or []).lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        cmd = ""
    if name in ("python.exe", "pythonw.exe") and any(m in cmd for m in marks):
        script = next((Path(a.strip('"')).name for a in (p.cmdline() or []) if a.lower().endswith(".py")), None)
        label = _script_labels().get(script) if script else None
        return ("script", label or (f"NovelTea Engine script: {script}" if script else "NovelTea Engine Python process"), False)
    if p.pid in descendants:
        if name in ("conhost.exe",):
            return None   # console plumbing, not interesting
        if name in ("claude.exe", "codex.exe") or name.startswith(("claude", "codex")):
            return ("cli", "CLI engine (" + name.replace(".exe", "") + ")", False)
        if name in ("bash.exe", "sh.exe"):
            return ("agent", "Agent shell", False)
        return ("child", f"Spawned by the app ({name})", False)
    return None


def _app_processes() -> list:
    """Every live process that belongs to the app, as psutil.Process objects with a classification."""
    server_pids = _server_pids()
    descendants = set()
    for sp in server_pids:
        try:
            descendants.update(c.pid for c in psutil.Process(sp).children(recursive=True))
        except Exception:
            pass
    marks = _corpus_marks()
    colibri = _colibri_procs()
    interesting = ("python", "pythonw", "cmd", "node", "claude", "codex", "bash", "sh", "ollama", "llama-server", "noveltea")
    out = []
    for p in psutil.process_iter(["pid", "name"]):
        n = (p.info.get("name") or "").lower()
        if not (n.startswith(interesting) or p.pid in descendants or p.pid in server_pids or p.pid in colibri):
            continue
        if n == "cmd.exe":
            continue   # job launch wrappers — killed together with their python child, not listed
        try:
            cls = _classify(p, server_pids, descendants, marks, colibri)
            if cls is None:
                continue
            with _lock:
                cached = _procs.get(p.pid)
                if cached is None or cached.create_time() != p.create_time():
                    _procs[p.pid] = p
                    cached = p
                    cached.cpu_percent(None)   # establish a baseline for the next reading
            out.append((cached, cls))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue   # exited (or is off-limits) between listing and inspecting it
    return out


def _sample_once():
    """Note, per app process, whether it did any CPU work since the last sample."""
    now = time.time()
    try:
        procs = _app_processes()
    except Exception:
        return
    live = set()
    for p, _cls in procs:
        try:
            t = p.cpu_times()
            total = t.user + t.system
        except Exception:
            continue
        live.add(p.pid)
        with _lock:
            st = _state.get(p.pid)
            if st is None or st["create"] != p.create_time():
                _state[p.pid] = {"cpu_total": total, "last_active": now, "first_seen": now, "create": p.create_time()}
            else:
                if total - st["cpu_total"] > 0.02 * SAMPLE_EVERY_S / 15:   # >~0.13% of one core
                    st["last_active"] = now
                st["cpu_total"] = total
    with _lock:
        for pid in [k for k in _state if k not in live]:
            _state.pop(pid, None)
            _procs.pop(pid, None)


def _sampler_loop():
    while True:
        _sample_once()
        time.sleep(SAMPLE_EVERY_S)


def start_sampler():
    global _sampler_started
    if _sampler_started:
        return
    _sampler_started = True
    threading.Thread(target=_sampler_loop, name="server-sampler", daemon=True).start()


start_sampler()


# ── system metrics ─────────────────────────────────────────────────────────────
class _PerfInfo(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD)] + [(n, ctypes.c_size_t) for n in (
        "CommitTotal", "CommitLimit", "CommitPeak", "PhysicalTotal", "PhysicalAvailable", "SystemCache",
        "KernelTotal", "KernelPaged", "KernelNonpaged", "PageSize", "HandleCount", "ProcessCount", "ThreadCount")]


def _perf_info() -> dict:
    """Windows' own commit / cache / pool figures — the same ones Task Manager shows."""
    try:
        pi = _PerfInfo()
        pi.cb = ctypes.sizeof(pi)
        if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(pi), pi.cb):
            return {}
        ps = pi.PageSize
        return {"committed": pi.CommitTotal * ps, "commit_limit": pi.CommitLimit * ps, "cached": pi.SystemCache * ps,
                "paged_pool": pi.KernelPaged * ps, "nonpaged_pool": pi.KernelNonpaged * ps}
    except Exception:
        return {}


_rates = {"t": None, "disk": None, "net": None}


def _clients() -> list:
    """Remote machines currently connected to this server's port."""
    seen: dict = {}
    try:
        for c in psutil.net_connections(kind="tcp"):
            if c.status == psutil.CONN_ESTABLISHED and c.laddr and c.laddr.port == SERVER_PORT and c.raddr:
                ip = c.raddr.ip
                seen[ip] = seen.get(ip, 0) + 1
    except Exception:
        return []
    out = []
    for ip, n in sorted(seen.items()):
        kind = "this PC" if ip in ("127.0.0.1", "::1") else ("Tailscale" if ip.startswith("100.") else "LAN")
        out.append({"ip": ip, "connections": n, "kind": kind})
    return out


@router.get("/metrics")
def metrics():
    now = time.time()
    vm = psutil.virtual_memory()
    perf = _perf_info()
    disk_at = next((str(p) for p in (CORPUS_PATH, *CORPUS_PATH.parents) if p.exists()), os.path.abspath(os.sep))   # works on any OS
    disk = psutil.disk_usage(disk_at)
    dio, nio = psutil.disk_io_counters(), psutil.net_io_counters()
    read_bps = write_bps = sent_bps = recv_bps = 0.0
    if _rates["t"] is not None and now > _rates["t"]:
        dt = now - _rates["t"]
        if dio and _rates["disk"]:
            read_bps = (dio.read_bytes - _rates["disk"][0]) / dt
            write_bps = (dio.write_bytes - _rates["disk"][1]) / dt
        if nio and _rates["net"]:
            sent_bps = (nio.bytes_sent - _rates["net"][0]) / dt
            recv_bps = (nio.bytes_recv - _rates["net"][1]) / dt
    _rates.update(t=now, disk=(dio.read_bytes, dio.write_bytes) if dio else None,
                  net=(nio.bytes_sent, nio.bytes_recv) if nio else None)
    freq = psutil.cpu_freq()
    per_core = psutil.cpu_percent(percpu=True)
    return {
        "ts": now,
        "cpu": {"percent": round(sum(per_core) / len(per_core), 1) if per_core else 0.0, "per_core": per_core,
                "cores": psutil.cpu_count(logical=False), "threads": _NCPU,
                "mhz": round(freq.current) if freq else None},
        "memory": {"total": vm.total, "used": vm.total - vm.available, "available": vm.available,
                   "percent": round((vm.total - vm.available) / vm.total * 100, 1), **perf},
        "disk": {"path": disk and str(CORPUS_PATH)[:3], "total": disk.total, "used": disk.used, "percent": disk.percent,
                 "read_bps": max(read_bps, 0), "write_bps": max(write_bps, 0)},
        "network": {"sent_bps": max(sent_bps, 0), "recv_bps": max(recv_bps, 0)},
        "boot_time": psutil.boot_time(),
        "server": {"pid": os.getpid(), "started": psutil.Process(os.getpid()).create_time()},
        "clients": _clients(),
    }


# ── the app's own process list ─────────────────────────────────────────────────
def _row(p: "psutil.Process", cls: tuple, now: float) -> Optional[dict]:
    category, label, protected = cls
    try:
        with p.oneshot():
            mem = p.memory_info().rss
            cpu = p.cpu_percent(None) / _NCPU   # share of the WHOLE machine, like Task Manager
            create = p.create_time()
            cmd = " ".join(p.cmdline() or [])
            threads = p.num_threads()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None
    with _lock:
        st = _state.get(p.pid)
    idle_for = (now - st["last_active"]) if st else 0.0
    idle = idle_for >= IDLE_AFTER_S
    stale = False
    reason = ""
    if category == "stale_app":
        stale, reason = True, "Left over from an earlier launch of the app"
    elif category in ("script", "child", "agent", "cli") and idle_for >= STALE_AFTER_S:
        stale, reason = True, f"No CPU activity for {int(idle_for // 60)} min"
    return {"pid": p.pid, "name": p.name(), "category": category, "label": label, "protected": protected,
            "cpu_percent": round(cpu, 1), "memory_bytes": mem, "threads": threads,
            "started": create, "uptime_s": int(now - create), "idle": idle, "idle_for_s": int(idle_for),
            "stale": stale, "stale_reason": reason, "command": cmd[:260]}


@router.get("/processes")
def processes():
    now = time.time()
    rows = []
    for p, cls in _app_processes():
        r = _row(p, cls, now)
        if r:
            rows.append(r)
    order = {"server": 0, "ollama": 1, "colibri": 1, "script": 2, "cli": 3, "agent": 3, "child": 4, "stale_app": 5}
    rows.sort(key=lambda r: (order.get(r["category"], 9), -r["memory_bytes"]))
    return {"ts": now, "processes": rows,
            "totals": {"memory_bytes": sum(r["memory_bytes"] for r in rows),
                       "cpu_percent": round(sum(r["cpu_percent"] for r in rows), 1),
                       "count": len(rows), "stale": sum(1 for r in rows if r["stale"])}}


def _kill_tree(p: "psutil.Process"):
    kids = []
    try:
        kids = p.children(recursive=True)
    except Exception:
        pass
    for k in kids:
        try:
            k.kill()
        except Exception:
            pass
    p.kill()
    psutil.wait_procs(kids + [p], timeout=5)


class KillRequest(BaseModel):
    pid: int


def _end_one(pid: int) -> dict:
    """End one app-owned process (and its children). Re-validates membership NOW."""
    match = next(((p, cls) for p, cls in _app_processes() if p.pid == pid), None)
    if match is None:
        raise HTTPException(403, "That process isn't one this app started — refusing to end it.")
    p, (category, label, protected) = match
    if protected:
        raise HTTPException(400, "That's the server you're using right now — it can't be ended from here.")
    try:
        freed = p.memory_info().rss
        target = p
        # Pipeline jobs run inside a cmd.exe wrapper (see corpus.py _launch_pipeline_job) — end the wrapper too,
        # otherwise it lingers.
        parent = p.parent()
        if parent is not None and parent.name().lower() == "cmd.exe" and category == "script":
            target = parent
        _kill_tree(target)
    except psutil.NoSuchProcess:
        return {"pid": pid, "label": label, "freed_bytes": 0, "already_gone": True}
    except psutil.AccessDenied:
        raise HTTPException(403, "Windows refused to end that process (access denied).")
    return {"pid": pid, "label": label, "freed_bytes": freed}


@router.post("/processes/kill")
def kill_process(req: KillRequest):
    r = _end_one(req.pid)
    return {"ok": True, **r}


@router.post("/processes/kill-stale")
def kill_stale():
    now = time.time()
    results, errors = [], []
    for p, cls in _app_processes():
        row = _row(p, cls, now)
        if row and row["stale"] and not row["protected"]:
            try:
                results.append(_end_one(row["pid"]))
            except HTTPException as e:
                errors.append({"pid": row["pid"], "error": e.detail})
    return {"ok": True, "ended": results, "errors": errors, "freed_bytes": sum(r["freed_bytes"] for r in results)}


@router.post("/colibri/unload")
def colibri_unload():
    """Free the local Colibrì model's RAM: stop its gateway and engine. Same idea as unloading
    Ollama's models — the next Colibrì request (or Start in Settings) loads it again. Also sweeps
    a gateway left running by an earlier session of the app (its pid file may be gone)."""
    from services import colibri_server as cs
    procs = _colibri_procs()
    was_loaded = bool(procs) or cs.running()
    model = cs.served_model_id() if cs.running() else ""
    freed = 0
    for p, _label in procs.values():
        try:
            freed += p.memory_info().rss
        except Exception:
            pass
    cs.stop()   # the gateway this app recorded, and its engine child
    for p, _label in _colibri_procs().values():   # anything still alive (orphans)
        try:
            _kill_tree(p)
        except Exception:
            pass
    left = _colibri_procs()
    return {"ok": True, "was_loaded": was_loaded, "unloaded": [model or "Colibrì model"] if was_loaded else [],
            "freed_bytes": freed, "still_running": bool(left)}


@router.post("/ollama/unload")
def ollama_unload():
    """Ask Ollama to drop every loaded model from memory (keep_alive 0) — frees the RAM
    without ending Ollama itself, and the models reload on the next request."""
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/ps", timeout=5) as r:
            loaded = [m.get("name") for m in json.loads(r.read()).get("models", [])]
    except Exception as e:
        raise HTTPException(502, f"Ollama isn't reachable ({str(e)[:100]}).")
    unloaded = []
    for name in loaded:
        is_embed = "embed" in name.lower()
        url = f"{OLLAMA_URL}/api/embed" if is_embed else f"{OLLAMA_URL}/api/generate"
        body = ({"model": name, "input": "", "keep_alive": 0} if is_embed else {"model": name, "keep_alive": 0})
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=30).read()
            unloaded.append(name)
        except Exception:
            pass
    return {"ok": True, "unloaded": unloaded, "was_loaded": loaded}
