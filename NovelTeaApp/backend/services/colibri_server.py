"""Colibrì (local, CPU-only LLM engine) as a NovelTea Engine engine.

Colibrì ships an OpenAI-compatible gateway (openai_server.py). This module finds an install and
a model container, starts that gateway on demand, and reports its state — the same shape as the
Ollama support, except Colibrì isn't a system service, so the app has to run it.

Text-only on purpose: Qwen3.6 has no native tool-calling format and, through the gateway's
COLI_TOOL_FALLBACK, copied the prompt's placeholder literally (a tool call named
"{function-name}<arg_key>read_file…") — measured live, ~4 min per request. So the app uses it for
plain generation and chat, never for file-tool loops.

Settings (~/.noveltea-engine/config.json):
  colibri_dir     install directory holding openai_server.py   (default: auto-detect)
  colibri_port    gateway port                                  (default 8765)
  models.colibri  absolute path of the model container         (default: first one found)
  colibri_model_roots  extra folders to scan for model containers
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

CONFIG_FILE = Path.home() / ".noveltea-engine" / "config.json"
STATE_FILE = Path.home() / ".noveltea-engine" / "colibri_server.json"
LOG_FILE = Path.home() / ".noveltea-engine" / "colibri_server.log"
DEFAULT_PORT = 8765
START_TIMEOUT = 600        # seconds: a big container can take minutes to map
PLACEHOLDER_KEY = "colibri"   # the gateway has no key unless started with --api-key

# Windows process-creation flags
_NO_WINDOW = 0x08000000
_NEW_GROUP = 0x00000200
_BREAKAWAY = 0x01000000


def _cfg() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
    except (OSError, ValueError):
        return {}


def port() -> int:
    try:
        return int(_cfg().get("colibri_port") or DEFAULT_PORT)
    except (TypeError, ValueError):
        return DEFAULT_PORT


def endpoint() -> str:
    return f"http://127.0.0.1:{port()}/v1"


# ── install + models ─────────────────────────────────────────────────────────
def install_dir() -> Optional[Path]:
    """Directory holding openai_server.py: the configured one, else the usual places."""
    configured = _cfg().get("colibri_dir")
    candidates = [Path(configured)] if configured else []
    candidates += [Path(r"C:\colibri-src\c"), Path(r"C:\colibri"),
                   Path.home() / "colibri", Path.home() / "colibri-src" / "c"]
    for c in candidates:
        try:
            if (c / "openai_server.py").is_file():
                return c
        except OSError:
            continue
    return None


def _is_model_dir(p: Path) -> bool:
    try:
        return (p / "config.json").is_file() and any(p.glob("*.safetensors"))
    except OSError:
        return False


def _dir_size(p: Path) -> int:
    total = 0
    try:
        for f in p.glob("*.safetensors"):
            try:
                total += f.stat().st_size
            except OSError:
                pass
    except OSError:
        pass
    return total


def list_models() -> list:
    """Model containers on this PC: any folder with config.json + *.safetensors directly under
    a scan root (C:\\ top level, ~/Models, and colibri_model_roots)."""
    roots = [Path("C:/"), Path.home() / "Models"] + [Path(r) for r in (_cfg().get("colibri_model_roots") or [])]
    seen, out = set(), []
    for root in roots:
        try:
            children = [c for c in root.iterdir() if c.is_dir()]
        except OSError:
            continue
        for c in children:
            if str(c).lower() in seen or not _is_model_dir(c):
                continue
            seen.add(str(c).lower())
            kind = ""
            try:
                kind = (json.loads((c / "config.json").read_text(encoding="utf-8")).get("model_type") or "")
            except (OSError, ValueError):
                pass
            out.append({"path": str(c), "name": c.name, "size": _dir_size(c), "model_type": kind})
    return sorted(out, key=lambda m: m["name"].lower())


def model_path() -> str:
    """Configured model container, else the only/first one found."""
    configured = (_cfg().get("models") or {}).get("colibri")
    if configured and _is_model_dir(Path(configured)):
        return configured
    found = list_models()
    return found[0]["path"] if found else ""


def available() -> bool:
    return install_dir() is not None and bool(model_path())


def unavailable_reason() -> str:
    if install_dir() is None:
        return "Colibrì not found (looked for openai_server.py in C:\\colibri-src\\c and C:\\colibri) — set colibri_dir in config"
    if not model_path():
        return "no Colibrì model container found (a folder with config.json + .safetensors under C:\\ or ~/Models)"
    return ""


# ── the gateway process ──────────────────────────────────────────────────────
def _get_json(path: str, timeout: float = 3):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port()}{path}", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def served_model_id() -> str:
    data = _get_json("/v1/models")
    try:
        return data["data"][0]["id"]
    except (TypeError, KeyError, IndexError):
        return ""


def running() -> bool:
    h = _get_json("/health")
    return bool(h and h.get("status") == "ok")


def _pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"], capture_output=True, text=True,
                             timeout=10, creationflags=_NO_WINDOW).stdout
        return str(int(pid)) in out
    except Exception:  # noqa: BLE001
        return False


def status() -> dict:
    st = _state()
    up = running()
    return {
        # the gateway process exists but isn't answering yet: the model is still loading
        "starting": (not up) and _pid_alive(st.get("pid")),
        "installed": install_dir() is not None,
        "install_dir": str(install_dir() or ""),
        "models": list_models(),
        "model": model_path(),
        "port": port(),
        "endpoint": endpoint(),
        "running": up,
        # which container the running gateway was started with (None if we didn't start it)
        "running_model": st.get("model") if up else None,
        "model_id": served_model_id() if up else "",
        "pid": st.get("pid") if up else None,
        "note": unavailable_reason(),
    }


def _python() -> list:
    """A Python 3 to run the (dependency-free) gateway. The app itself may be a frozen exe, so
    sys.executable is no use."""
    if shutil.which("py"):
        return ["py", "-3"]
    for name in ("python", "python3"):
        if shutil.which(name):
            return [name]
    raise RuntimeError("Python 3 not found — Colibrì's gateway (openai_server.py) needs it")


def _kill_tree(pid: int) -> None:
    if not pid:
        return
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=20,
                       creationflags=_NO_WINDOW)
    except Exception:  # noqa: BLE001 - best effort
        pass


def stop() -> bool:
    """Stop the gateway this app started (and its engine child). Returns True if one was stopped."""
    st = _state()
    pid = st.get("pid")
    was_up = running()
    if pid:
        _kill_tree(int(pid))
    try:
        STATE_FILE.unlink()
    except OSError:
        pass
    for _ in range(20):
        if not running():
            break
        time.sleep(0.5)
    return was_up and not running()


def start(wait: bool = True) -> dict:
    """Start the gateway on the chosen model — CPU-only (the GPU variables are stripped: the
    680M was measured slower for this). Reuses a gateway that's already serving that model;
    restarts one that's serving a different model."""
    inst = install_dir()
    if inst is None or not model_path():
        raise RuntimeError(unavailable_reason())
    model = model_path()
    st = _state()
    if running():
        if os.path.normcase(st.get("model", "")) == os.path.normcase(model):
            return status()
        stop()   # a different model (or one this app didn't start): replace it
        if running():
            raise RuntimeError(f"Port {port()} is in use by something that isn't this app's Colibrì gateway")

    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("_PYI", "_MEI", "COLI_CUDA", "COLI_GPU", "CUDA_", "COLI_HIP"))}
    env["PYTHONIOENCODING"] = "utf-8"
    args = _python() + [str(inst / "openai_server.py"), "--model", model, "--port", str(port()),
                        "--max-tokens", str(int(_cfg().get("colibri_max_tokens") or 2048))]
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log = open(LOG_FILE, "w", encoding="utf-8")
    flags = _NO_WINDOW | _NEW_GROUP
    common = dict(cwd=str(inst), env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                  close_fds=True)
    try:
        proc = subprocess.Popen(args, creationflags=flags | _BREAKAWAY, **common)
    except OSError:
        proc = subprocess.Popen(args, creationflags=flags, **common)
    log.close()
    STATE_FILE.write_text(json.dumps({"pid": proc.pid, "model": model, "port": port(),
                                      "started": time.strftime("%Y-%m-%dT%H:%M:%S")}), encoding="utf-8")
    if wait:
        deadline = time.time() + START_TIMEOUT
        while time.time() < deadline:
            if running():
                return status()
            if proc.poll() is not None:
                tail = ""
                try:
                    tail = LOG_FILE.read_text(encoding="utf-8", errors="replace")[-400:]
                except OSError:
                    pass
                raise RuntimeError(f"Colibrì gateway exited while starting (code {proc.returncode}): {tail}")
            time.sleep(1.5)
        raise RuntimeError(f"Colibrì gateway didn't answer within {START_TIMEOUT}s — see {LOG_FILE}")
    return status()


def ensure_running() -> str:
    """Start the gateway if needed; returns the model id to put in requests."""
    if not running() or os.path.normcase(_state().get("model", "")) != os.path.normcase(model_path()):
        start(wait=True)
    mid = served_model_id()
    if not mid:
        raise RuntimeError("Colibrì gateway is up but reports no model")
    return mid
