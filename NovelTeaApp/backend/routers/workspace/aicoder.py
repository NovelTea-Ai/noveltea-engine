"""Workspace Assistant — an in-app IDE-style chat that talks to the same Claude
Code CLI subscription login already configured in Settings, with full read/write
access across the WHOLE project workspace root (not scoped to a single novel
project like every other agentic feature in this app). Meant to feel like
chatting with Claude Code inside VS Code, without leaving the app.

Safety: the CLI's own --allowedTools/--disallowedTools are the enforcement
mechanism (deny overrides allow). Credentials and VCS/build noise are always
denied regardless of what the user asks for.
"""
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


def _resolve_workspace_root() -> Optional[Path]:
    """The actual source-code workspace root (NovelTeaOS/, parent of both
    NovelTeaApp/ and the corpus/ data dir) — NOT config.CORPUS_PATH, which
    is only the data directory. Only resolvable when running from inside the
    NovelTeaOS checkout; a packaged exe run from an arbitrary install location
    has no source tree to edit, so this returns None and the feature reports
    itself unavailable rather than guessing at a wrong directory.

    When frozen (PyInstaller), __file__ resolves inside the temp _MEIPASS
    extraction dir, not the real source tree — use sys.executable's own
    location instead (mirrors config.py's _candidate_corpus_dirs), since the
    exe is built to dist/ under backend/, i.e. NovelTeaOS/NovelTeaApp/backend/dist/."""
    candidates = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        # backend/dist/NovelTeaEngine.exe -> backend/dist -> backend -> NovelTeaApp -> NovelTeaOS
        candidates.append(exe_dir.parent.parent.parent)
    else:
        here = Path(__file__).resolve()
        # backend/routers/workspace/aicoder.py -> workspace -> routers -> backend -> NovelTeaApp -> NovelTeaOS
        candidates.append(here.parent.parent.parent.parent.parent)
    for candidate in candidates:
        if (candidate / "NovelTeaApp").is_dir() and (candidate / "NovelTea Engine").is_dir():
            return candidate
    return None


WORKSPACE_ROOT = _resolve_workspace_root()

# Directories never listed, read, or granted to the agent — regardless of
# prompt content. Credentials (CLI account pool + any .env) and VCS/build/dep
# noise that would otherwise burn tool-call budget wandering through it.
_DENY_DIR_NAMES = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "build", "dist", "_backups", "accounts", ".claude",
}
_DENY_FILE_PATTERNS = (".env", ".env.", "credentials", ".pem", ".key")

# Shared app settings — the Nemotron key pool and model live here, same file the
# Settings page and the corpus scripts read.
CONFIG_FILE = Path.home() / ".noveltea-engine" / "config.json"


def _is_denied(rel_parts: tuple) -> bool:
    return any(part in _DENY_DIR_NAMES for part in rel_parts)


def _is_denied_file(name: str) -> bool:
    lname = name.lower()
    return any(lname == p or lname.startswith(p) for p in _DENY_FILE_PATTERNS)


def _require_workspace() -> Path:
    if WORKSPACE_ROOT is None:
        raise HTTPException(400, "Workspace Assistant is only available when NovelTea Engine is run from inside "
                                  "its own source checkout (NovelTeaOS/) — this install doesn't have one.")
    return WORKSPACE_ROOT


def _safe_resolve(rel_path: str) -> Path:
    """Resolve a client-supplied relative path against WORKSPACE_ROOT, refusing
    anything that escapes the root (..) or lands in a denied directory."""
    root = _require_workspace()
    rel_path = (rel_path or "").strip().lstrip("/\\")
    target = (root / rel_path).resolve() if rel_path else root
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(400, "Path escapes the workspace root.")
    rel_parts = target.relative_to(root).parts
    if _is_denied(rel_parts):
        raise HTTPException(403, "That path is not accessible to the Workspace Assistant.")
    return target


# ── Progress store (mirrors generate.py's pattern, kept local/independent) ──
_PROGRESS: dict[str, list] = {}
_PROGRESS_LOCK = threading.Lock()


def _progress_clear(session_id: str):
    with _PROGRESS_LOCK:
        _PROGRESS[session_id] = []


def _progress_log(session_id: str, msg: str, kind: str = "info", data: dict = None):
    """Append one progress entry.

    `kind` drives how the UI renders it: info / warn / error / success, plus the
    structured tool kinds "tool" (a call started) and "tool_result" (what it
    returned). `data` carries the structured payload for those — tool name,
    arguments, stdout/stderr, and added/removed line counts for edits — so the
    chat can render an IDE-style transcript instead of a single status line.
    """
    with _PROGRESS_LOCK:
        entries = _PROGRESS.setdefault(session_id, [])
        entry = {"i": len(entries), "t": time.strftime("%H:%M:%S"), "msg": msg, "kind": kind}
        if data:
            entry["data"] = data
        entries.append(entry)
        if len(entries) > 500:
            del entries[:-400]
            for j, e in enumerate(entries):
                e["i"] = j


@router.get("/progress/{session_id}")
def get_progress(session_id: str, since: int = -1):
    with _PROGRESS_LOCK:
        entries = _PROGRESS.get(session_id, [])
        return {"entries": [e for e in entries if e["i"] > since]}


# ── Live subprocess tracking, so Abort can actually kill the CLI ──────────
_ACTIVE_PROCS: dict = {}
_ACTIVE_PROCS_LOCK = threading.Lock()
_ABORTED_KEYS: set = set()


def _kill_proc_tree(proc):
    try:
        if proc and proc.poll() is None:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
    except Exception:
        pass


def _abort_active_proc(session_id: str) -> bool:
    """Signal an abort. The Nemotron agent runs in-process rather than as a
    subprocess, so the flag alone is the abort mechanism — the tool-callback
    checks it between tool calls and raises _AbortedError. The subprocess kill
    below remains for any CLI-backed turn still in flight."""
    with _ACTIVE_PROCS_LOCK:
        proc = _ACTIVE_PROCS.get(session_id)
        _ABORTED_KEYS.add(session_id)
    if proc is None:
        return True
    _kill_proc_tree(proc)
    return True


class _AbortedError(RuntimeError):
    pass


# ── CLI plumbing (mirrors generate.py's _resolve_cli_argv/_cli_strip_env/_cli_model) ──

def _resolve_cli_argv() -> list:
    import shutil
    cli = shutil.which("claude")
    if not cli:
        raise RuntimeError("claude CLI not found in PATH. Install Claude Code (Settings → CLI Accounts).")
    if cli.lower().endswith((".cmd", ".bat")):
        node = shutil.which("node")
        cli_js = Path(cli).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
        if node and cli_js.exists():
            return [node, str(cli_js)]
    return [cli]


def _cli_strip_env() -> dict:
    return {k: v for k, v in os.environ.items()
            if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_API_KEY")}


def _cli_model() -> str:
    """Reuses the same Settings > models.anthropic value as every other
    Claude CLI call in the app, so this page follows the model picked there."""
    from config import CONFIG_FILE
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            m = (cfg.get("models") or {}).get("anthropic", "")
            if m:
                return m
    except Exception:
        pass
    return "claude-haiku-4-5-20251001"


def _claude_cli_available() -> bool:
    import shutil
    return shutil.which("claude") is not None


# ── Sessions: each browser chat maps to one CLI --resume session ──────────
# Keyed by a client-generated session_id (persisted in localStorage on the
# frontend) so refreshing the page / navigating away and back continues the
# same CLI conversation instead of starting cold every time.
_SESSIONS: dict = {}
_SESSIONS_LOCK = threading.Lock()

_SYSTEM_PROMPT = (
    "You are Claude Code, an AI coding assistant with full read/write access to this workspace, "
    "running inside the NovelTea Engine desktop app's own 'Workspace Assistant' page — functionally "
    "identical to a Claude Code CLI session in VS Code's integrated terminal. "
    "You may read, search, edit, and create files anywhere in the workspace, and run shell commands "
    "(build tools, git, tests, npm, python, etc). Explain what you're doing as you go, keep responses "
    "focused and practical, and prefer making the actual edit over describing it when the user asks for "
    "a change to be made."
)


WORKSPACE_SYSTEM_PROMPT = """You are a workspace assistant with direct access to the user's project.

Tools:
  grep_files  — search file CONTENTS by regex. Use this first to locate things.
  glob_files  — find files by NAME pattern (e.g. "*.py").
  read_file   — read a whole file once you know which one you need.
  list_files  — list a directory.
  edit_file   — replace an exact, unique substring. PREFER THIS for changing part
                of a file; it cannot silently discard the rest of the file.
  write_file  — replace an ENTIRE file. Only for new files or full rewrites.
  exec_bash_command — allowlisted shell commands (ls, cat, git, python…).

Work like an engineer: search before you read, read before you edit, and make the
smallest change that does the job. Never invent file paths or contents — if you
have not read it, say so. Report what you changed and why, concisely."""


def _trim_args(args: dict) -> dict:
    """Tool arguments safe to show in the transcript — long file bodies clipped."""
    out = {}
    for k, v in (args or {}).items():
        if isinstance(v, str):
            out[k] = v if len(v) <= 400 else v[:400] + f"… (+{len(v) - 400} chars)"
        else:
            out[k] = v
    return out


def _tool_summary(name: str, p: dict) -> str:
    """One-line result summary for the collapsed view of a tool call."""
    if name == "exec_bash_command":
        rc = p.get("exit_code")
        out = (p.get("stdout") or "").strip().splitlines()
        return f"exit {rc}" + (f", {len(out)} lines" if out else ", no output")
    if name in ("write_file", "edit_file"):
        a, r = p.get("added"), p.get("removed")
        if a is None and r is None:
            return "written" if p.get("created") else "updated"
        return f"+{a or 0} -{r or 0}"
    if name == "read_file":
        return f"{p.get('bytes', 0):,} bytes"
    if name in ("grep_files", "glob_files"):
        n = p.get("count") or 0
        return f"{n} match{'es' if n != 1 else ''}" + (" (truncated)" if p.get("truncated") else "")
    if name == "list_files":
        return f"{p.get('count', 0)} entries"
    return "done"


def _nemotron_api_key() -> str:
    """Active key from the Nemotron pool in Settings."""
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
        pool = cfg.get("nemotron_key_pool") or []
        if not pool:
            return ""
        idx = cfg.get("nemotron_key_pool_index", 0) % len(pool)
        return pool[idx].get("api_key", "")
    except (OSError, ValueError, KeyError, TypeError):
        return ""


def _nemotron_ready() -> bool:
    return bool(_nemotron_api_key())


def _read_cfg() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
    except (OSError, ValueError):
        return {}


# ── Ollama (local models) ────────────────────────────────────────────────────
# Ollama serves an OpenAI-shaped API on /v1, the same surface the Nemotron agent
# already speaks, so the identical agent loop drives it. The key is ignored by
# Ollama but the Authorization header is still sent, so any placeholder works.
OLLAMA_DEFAULT_ENDPOINT = "http://127.0.0.1:11434/v1"
_OLLAMA_PLACEHOLDER_KEY = "ollama"


def _ollama_endpoint() -> str:
    return (_read_cfg().get("ollama_endpoint") or OLLAMA_DEFAULT_ENDPOINT).rstrip("/")


def _ollama_tags() -> list:
    """Models installed locally. Empty list also means "daemon not running"."""
    import urllib.error
    import urllib.request
    base = _ollama_endpoint()
    base = base[:-3] if base.endswith("/v1") else base
    try:
        with urllib.request.urlopen(f"{base}/api/tags", timeout=4) as r:
            return json.loads(r.read().decode("utf-8")).get("models") or []
    except (urllib.error.URLError, OSError, ValueError):
        return []


def _ollama_model() -> str:
    """Configured model, else whichever is installed — so it works before setup."""
    configured = (_read_cfg().get("models") or {}).get("ollama")
    tags = _ollama_tags()
    names = [m.get("name") for m in tags if m.get("name")]
    if configured and (configured in names or not names):
        return configured
    return names[0] if names else ""


def _ollama_ready() -> bool:
    return bool(_ollama_model())


def _run_ollama(session_id: str, prompt: str, cwd: Path, timeout: int = 600):
    """One turn of the workspace conversation, driven by a local Ollama model.

    Nothing leaves this machine. The model must support tool calling, or the
    agent gets no tools back and can only talk about the work instead of doing it.
    """
    model = _ollama_model()
    if not model:
        raise RuntimeError(
            "No local Ollama model found — is `ollama serve` running? "
            "Pull one with e.g. `ollama pull qwen2.5-coder`."
        )
    return _run_openai_agent(session_id, prompt, cwd,
                             _OLLAMA_PLACEHOLDER_KEY, _ollama_endpoint(), model)


def _run_nemotron(session_id: str, prompt: str, cwd: Path, timeout: int = 600):
    """One turn of the workspace conversation, driven by the Nemotron agent."""
    from services.nemotron_agent import DEFAULT_ENDPOINT, DEFAULT_MODEL

    api_key = _nemotron_api_key()
    if not api_key:
        raise RuntimeError(
            "No Nemotron API key pooled — add one in Settings → Nemotron Key Pool."
        )
    cfg = _read_cfg()
    model = (cfg.get("models") or {}).get("nemotron") or DEFAULT_MODEL
    endpoint = cfg.get("nemotron_endpoint") or DEFAULT_ENDPOINT
    return _run_openai_agent(session_id, prompt, cwd, api_key, endpoint, model)


KIMI_DEFAULT_MODEL = "moonshotai/kimi-k3"


def _kimi_model() -> str:
    """Settings → Kimi K3 Model; an old Kimi Code CLI alias there isn't an NVIDIA id."""
    m = (_read_cfg().get("models") or {}).get("kimi") or ""
    return m if m.startswith("moonshotai/") else KIMI_DEFAULT_MODEL


def _run_kimi(session_id: str, prompt: str, cwd: Path, timeout: int = 600):
    """One turn driven by Kimi K3: the same agent and tools as Nemotron, on NVIDIA's API
    with the same pooled nvapi- key, just a different model id."""
    from services.nemotron_agent import DEFAULT_ENDPOINT

    api_key = _nemotron_api_key()
    if not api_key:
        raise RuntimeError(
            "No NVIDIA API key pooled — Kimi K3 uses the Nemotron Key Pool in Settings."
        )
    endpoint = _read_cfg().get("nemotron_endpoint") or DEFAULT_ENDPOINT
    return _run_openai_agent(session_id, prompt, cwd, api_key, endpoint, _kimi_model(),
                             max_tokens=16384)


def _run_colibri(session_id: str, prompt: str, cwd: Path, timeout: int = 600):
    """One turn driven by a local Colibrì model (CPU-only). Same agent and file tools as the other
    engines; the tools are declared and called in Qwen's own text format (tool_format="qwen_xml"),
    because the gateway has no tool support for Qwen. Starts the gateway if it isn't up. Slow by
    nature — every prompt token costs seconds — so the HTTP timeout is generous."""
    from services import colibri_server as cs
    if not cs.available():
        raise RuntimeError(cs.unavailable_reason())
    _progress_log(session_id, "Colibrì: starting the local model…" if not cs.running() else "Colibrì: model is up")
    model_id = cs.ensure_running()
    return _run_openai_agent(session_id, prompt, cwd, cs.PLACEHOLDER_KEY, cs.endpoint(), model_id,
                             max_tokens=2048, tool_format="qwen_xml", request_timeout=3600)


def _run_openai_agent(session_id: str, prompt: str, cwd: Path,
                      api_key: str, endpoint: str, model: str, max_tokens: int = 8192,
                      use_tools: bool = True, system_prompt: Optional[str] = None,
                      request_timeout: Optional[int] = None, tool_format: str = "openai"):
    """
    Drive one turn against any OpenAI-shaped /chat/completions endpoint.

    Unlike the Claude CLI path there is no `--resume`: the agent keeps its own
    message history in-process, so the session dict holds the live agent object
    and multi-turn context survives as long as the backend does.
    """
    from services.nemotron_agent import NemotronAgent

    with _SESSIONS_LOCK:
        sess = _SESSIONS.setdefault(session_id, {"agent": None, "touched": time.time()})
        agent = sess.get("agent")

    if agent is None or agent.model != model:
        agent = NemotronAgent(
            api_key=api_key,
            api_endpoint=endpoint,
            model=model,
            cwd=str(cwd),
            file_roots=[cwd],
            confirm=None,  # the UI has no per-command prompt; the allowlist governs
            system_prompt=system_prompt or WORKSPACE_SYSTEM_PROMPT,
            max_tokens=max_tokens,
            use_tools=use_tools,
            tool_format=tool_format,
        )
        if request_timeout:
            agent.REQUEST_TIMEOUT = request_timeout
        with _SESSIONS_LOCK:
            _SESSIONS[session_id]["agent"] = agent

    def _on_tool(call: dict, result: dict):
        """Emit a structured record of one tool call for the chat transcript."""
        if session_id in _ABORTED_KEYS:
            raise _AbortedError()

        name = (call or {}).get("name") or "tool"
        args = (call or {}).get("args") or {}
        result = result if isinstance(result, dict) else {}

        # Human-readable one-liner: what was invoked, on what.
        target = (args.get("path") or args.get("pattern") or args.get("cmd") or "")
        label = f"{name} {target}".strip()
        _progress_log(session_id, label[:200], "tool",
                      {"tool": name, "args": _trim_args(args), "target": str(target)[:300]})

        if result.get("error"):
            _progress_log(session_id, str(result["error"])[:300], "tool_result",
                          {"tool": name, "ok": False, "error": str(result["error"])[:600]})
            return

        payload = {"tool": name, "ok": True}

        if name == "exec_bash_command":
            payload["stdout"] = (result.get("stdout") or "")[:4000]
            payload["stderr"] = (result.get("stderr") or "")[:2000]
            payload["exit_code"] = result.get("exit_code")
            payload["cwd"] = result.get("cwd")
        elif name in ("write_file", "edit_file"):
            # Green/red line counts so the UI can render it like a diff.
            payload["path"] = result.get("path")
            payload["added"] = result.get("added_lines")
            payload["removed"] = result.get("removed_lines")
            payload["created"] = result.get("created")
        elif name == "read_file":
            payload["path"] = result.get("path")
            payload["bytes"] = result.get("bytes")
        elif name in ("grep_files", "glob_files"):
            payload["count"] = result.get("match_count", result.get("count"))
            payload["truncated"] = result.get("truncated")
            payload["matches"] = (result.get("matches") or result.get("files") or [])[:20]
        elif name == "list_files":
            payload["path"] = result.get("path")
            payload["count"] = len(result.get("entries") or [])

        _progress_log(session_id, _tool_summary(name, payload), "tool_result", payload)

    # Opt into the structured (call, result) callback form — the legacy form
    # passes only a bash command string, so file tools would report nothing.
    _on_tool._wants_call = True

    t0 = time.time()
    reply = agent.send(prompt, on_command=_on_tool)
    seconds = time.time() - t0
    if not (reply or "").strip():
        raise RuntimeError(f"empty response from the {model} agent")
    u = agent.usage
    estimated = not u["completion"]   # provider sent no usage block: ~4 characters a token
    completion = u["completion"] or max(1, round(len(reply) / 4))
    model_s = u["model_seconds"] or seconds
    stats = {
        "seconds": round(seconds, 2),
        "model_seconds": round(model_s, 2),
        "completion_tokens": completion,
        "prompt_tokens": u["prompt"],
        "tokens_per_sec": round(completion / model_s, 1) if model_s > 0 else None,
        "calls": u["calls"],
        "estimated": estimated,
        "model": model,
    }
    return reply, stats


class ChatRequest(BaseModel):
    session_id: str
    message: str


ASSISTANT_ENGINES = ("kimi", "nemotron", "ollama", "colibri")
# The Workspace Assistant's own engine picker. Kept in its own file, not config.json, so it
# never races the main settings writers. Absent = follow the system Agent Engine as before.
ENGINE_OVERRIDE_FILE = CONFIG_FILE.parent / "aicoder_engine.json"


def _engine_override() -> str:
    try:
        e = json.loads(ENGINE_OVERRIDE_FILE.read_text(encoding="utf-8")).get("engine", "")
    except Exception:
        return ""
    return e if e in ASSISTANT_ENGINES else ""


def _colibri_available() -> bool:
    try:
        from services import colibri_server as cs
        return cs.available()
    except Exception:  # noqa: BLE001 - a broken install mustn't break /status
        return False


def _colibri_model_name() -> str:
    try:
        from services import colibri_server as cs
        return os.path.basename(cs.model_path())
    except Exception:  # noqa: BLE001
        return ""


def _assistant_engine() -> str:
    """Which engine backs the Workspace Assistant: its own dropdown's choice if set,
    otherwise the system setting as below.

    The assistant runs on a direct API rather than a CLI, so it honours the
    Settings engine choice only where it has an implementation: Ollama or Kimi K3
    when selected, Nemotron for everything else.
    """
    override = _engine_override()
    if override:
        return override
    picked = (_read_cfg().get("generation") or {}).get("agent_engine", "")
    return picked if picked in ("ollama", "kimi", "colibri") else "nemotron"


class EngineRequest(BaseModel):
    engine: str


@router.post("/engine")
def set_engine(req: EngineRequest):
    """The Workspace Assistant's engine dropdown: overrides the system Agent Engine for
    this page only. Takes effect on the next message."""
    if req.engine not in ASSISTANT_ENGINES:
        raise HTTPException(400, f"engine must be one of {', '.join(ASSISTANT_ENGINES)}")
    ENGINE_OVERRIDE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = ENGINE_OVERRIDE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"engine": req.engine}), encoding="utf-8")
    os.replace(tmp, ENGINE_OVERRIDE_FILE)
    return status()


@router.get("/status")
def status():
    engine = _assistant_engine()
    if engine == "ollama":
        model = _ollama_model()
        ready = bool(model)
        note = "" if ready else "Ollama is not running, or no model is pulled."
    elif engine == "colibri":
        from services import colibri_server as cs
        model = os.path.basename(cs.model_path())
        ready = cs.available()
        note = "" if ready else cs.unavailable_reason()
    elif engine == "kimi":
        model = _kimi_model()
        ready = _nemotron_ready()
        note = "" if ready else "No NVIDIA API key pooled (Kimi K3 uses the Nemotron Key Pool)."
    else:
        model = (_read_cfg().get("models") or {}).get("nemotron", "")
        ready = _nemotron_ready()
        note = "" if ready else "No Nemotron API key pooled."
    return {
        "workspace_available": WORKSPACE_ROOT is not None,
        "workspace_root": str(WORKSPACE_ROOT) if WORKSPACE_ROOT else None,
        # The UI gates the chat box on cli_ready. These engines are direct-API,
        # so readiness means "reachable and configured", not "a CLI exists".
        "cli_ready": ready,
        "engine": engine,
        "model": model,
        "note": note,
        "overridden": bool(_engine_override()),
        # for the page's dropdown: which of its three engines can run right now
        "engines": {
            "kimi": {"available": _nemotron_ready(), "model": _kimi_model()},
            "nemotron": {"available": _nemotron_ready(),
                         "model": (_read_cfg().get("models") or {}).get("nemotron", "")},
            "ollama": {"available": _ollama_ready(), "model": _ollama_model()},
            "colibri": {"available": _colibri_available(), "model": _colibri_model_name()},
        },
    }


class SaveLogRequest(BaseModel):
    content: str
    label: str = ""


@router.post("/save-log")
def save_log(req: SaveLogRequest):
    """Writes the Engine Console's current log to workspace_root/debug_logs/
    so the user can hand it to the Workspace Assistant (or read it directly)
    later — the console itself only keeps the current session in memory."""
    root = _require_workspace()
    out_dir = root / "debug_logs"
    out_dir.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    safe_label = "".join(c for c in (req.label or "") if c.isalnum() or c in "-_")[:40]
    fname = f"console_log_{stamp}" + (f"_{safe_label}" if safe_label else "") + ".txt"
    path = out_dir / fname
    path.write_text(req.content or "", encoding="utf-8")
    return {"ok": True, "path": str(path.relative_to(root))}


@router.get("/ollama-models")
def ollama_models():
    """Locally installed Ollama models, for the Settings picker."""
    tags = _ollama_tags()
    return {
        "running": bool(tags),
        "endpoint": _ollama_endpoint(),
        "current": _ollama_model(),
        "models": [
            {"name": m.get("name"), "size": m.get("size"),
             "family": ((m.get("details") or {}).get("family") or "")}
            for m in tags if m.get("name")
        ],
    }


# ── Colibrì (local CPU engine): settings-page controls ──────────────────────
# The gateway is started on demand by the first request that needs it; these let Settings show its
# state, pre-load the model, and free its RAM.

@router.get("/colibri")
def colibri_status():
    from services import colibri_server as cs
    return cs.status()


@router.post("/colibri/start")
def colibri_start():
    """Start loading the model in the background; the page polls GET /colibri for `running`."""
    from services import colibri_server as cs
    if not cs.available():
        raise HTTPException(400, cs.unavailable_reason())
    if cs.running() or cs.status().get("starting"):
        return {"ok": True, "already": True}

    def _go():
        try:
            cs.start(wait=True)
        except Exception as e:  # noqa: BLE001 - surfaced through the server log, status shows not running
            print(f"  [colibri] start failed: {e}")
    threading.Thread(target=_go, daemon=True).start()
    return {"ok": True}


@router.post("/colibri/stop")
def colibri_stop():
    from services import colibri_server as cs
    return {"ok": True, "stopped": cs.stop()}


@router.post("/chat")
def chat(req: ChatRequest):
    root = _require_workspace()
    engine = _assistant_engine()

    if engine == "ollama":
        if not _ollama_ready():
            raise HTTPException(
                400,
                "No local Ollama model available — start Ollama and pull a model "
                "(e.g. `ollama pull qwen2.5-coder`), then pick it in Settings → Ollama Model.",
            )
        runner, label = _run_ollama, f"Ollama ({_ollama_model()})"
    elif engine == "colibri":
        from services import colibri_server as cs
        if not cs.available():
            raise HTTPException(400, f"Colibrì isn't set up: {cs.unavailable_reason()}")
        runner, label = _run_colibri, f"Colibrì ({os.path.basename(cs.model_path())}, local CPU)"
    elif engine == "kimi":
        if not _nemotron_ready():
            raise HTTPException(
                400,
                "No NVIDIA API key configured — Kimi K3 uses Settings → CLI Accounts → Nemotron Key Pool.",
            )
        runner, label = _run_kimi, f"Kimi K3 ({_kimi_model()})"
    else:
        if not _nemotron_ready():
            raise HTTPException(
                400,
                "No Nemotron API key configured — add one in Settings → CLI Accounts → Nemotron Key Pool.",
            )
        runner, label = _run_nemotron, "Nemotron"

    with _SESSIONS_LOCK:
        sess = _SESSIONS.setdefault(req.session_id, {"agent": None, "touched": time.time()})
        sess["touched"] = time.time()

    _progress_clear(req.session_id)
    _progress_log(req.session_id, f"🤖 {label} is working…")
    try:
        text, stats = runner(req.session_id, req.message, root)
    except _AbortedError:
        _progress_log(req.session_id, "⏹ Aborted by user", "warn")
        raise HTTPException(499, "Aborted by user")
    except Exception as e:
        _progress_log(req.session_id, f"✗ {str(e)[:200]}", "error")
        raise HTTPException(502, f"Workspace Assistant failed: {str(e)[:300]}")

    _progress_log(req.session_id, "✓ Response ready", "success")
    return {"ok": True, "reply": text, "stats": stats}


# ── Build button: rebuild frontend + backend exe, then relaunch ────────────
# Build-NovelTea.ps1 (next to build-all.bat) does the work. It runs as a DETACHED process because
# it has to stop this very app to rebuild the exe, then starts it again; this endpoint only starts
# it, and /build/status reads the progress file it writes.

def _app_dir() -> Optional[Path]:
    return (WORKSPACE_ROOT / "NovelTeaApp") if WORKSPACE_ROOT else None


def _build_status() -> dict:
    app = _app_dir()
    if not app:
        return {"state": "unavailable"}
    try:
        st = json.loads((app / "backend" / "build_status.json").read_text(encoding="utf-8-sig"))
    except Exception:
        st = {"state": "idle"}
    try:
        lines = (app / "backend" / "build_button.log").read_text(encoding="utf-8", errors="replace").splitlines()
        st["log"] = lines[-40:]
    except Exception:
        st["log"] = []
    return st


@router.get("/build/status")
def build_status():
    return _build_status()


@router.post("/build")
def build():
    app = _app_dir()
    script = app / "Build-NovelTea.ps1" if app else None
    if not script or not script.is_file():
        raise HTTPException(400, "Build-NovelTea.ps1 not found — the Build button only works from the NovelTeaOS checkout.")
    st = _build_status()
    if st.get("state") == "running":
        try:
            age = time.time() - time.mktime(time.strptime(st.get("updated", ""), "%Y-%m-%dT%H:%M:%S"))
        except Exception:
            age = 0
        if age < 20 * 60:
            raise HTTPException(409, f"A build is already running: {st.get('step', '')}")
    import os
    import subprocess
    # Drop PyInstaller's own variables so the relaunched exe starts clean, not as a child of this one.
    env = {k: v for k, v in os.environ.items() if not k.startswith(("_PYI", "_MEI"))}
    args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP. Not DETACHED_PROCESS: tested, PowerShell started
    # detached with stdin closed exits 0 at once without running the script.
    flags = 0x08000000 | 0x00000200
    # The script's own stdout/stderr go to build_spawn.log, so a failure before it starts
    # writing its log (PowerShell refusing to start, a policy block…) is still visible.
    spawn_log = open(app / "backend" / "build_spawn.log", "w", encoding="utf-8")
    common = dict(cwd=str(app), env=env, close_fds=True, stdin=subprocess.DEVNULL,
                  stdout=spawn_log, stderr=subprocess.STDOUT)
    try:
        proc = subprocess.Popen(args, creationflags=flags | 0x01000000, **common)   # + CREATE_BREAKAWAY_FROM_JOB
        how = "breakaway"
    except OSError as e:
        spawn_log.write(f"breakaway refused ({e}); starting inside the app's job\n")
        spawn_log.flush()
        proc = subprocess.Popen(args, creationflags=flags, **common)
        how = "in-job"
    spawn_log.close()
    return {"ok": True, "pid": proc.pid, "spawn": how}


@router.post("/abandon/{session_id}")
def abandon(session_id: str):
    killed = _abort_active_proc(session_id)
    return {"ok": True, "process_killed": killed}


# ── File tree + file read (right-hand browser panel) ───────────────────────

@router.get("/tree")
def get_tree(path: str = ""):
    """List one directory level under WORKSPACE_ROOT (lazy-expand tree — the
    frontend calls this again for each folder the user expands, rather than
    walking the whole tree up front, which would be slow and wasteful on a
    real code+data workspace this size)."""
    target = _safe_resolve(path)
    if not target.is_dir():
        raise HTTPException(400, "Not a directory.")
    root = _require_workspace()
    entries = []
    try:
        for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if child.name.startswith(".") and child.name not in (".claude",):
                # dotfiles hidden except the one we explicitly deny-list above
                # (kept out of the listing entirely, not just greyed out)
                continue
            rel_parts = child.relative_to(root).parts
            if _is_denied(rel_parts):
                continue
            if child.is_file() and _is_denied_file(child.name):
                continue
            entries.append({
                "name": child.name,
                "path": str(child.relative_to(root)).replace("\\", "/"),
                "is_dir": child.is_dir(),
                "size": child.stat().st_size if child.is_file() else None,
            })
    except PermissionError:
        pass
    return {"path": path, "entries": entries}


@router.get("/file")
def get_file(path: str):
    target = _safe_resolve(path)
    if not target.is_file():
        raise HTTPException(400, "Not a file.")
    if _is_denied_file(target.name):
        raise HTTPException(403, "That file is not accessible to the Workspace Assistant.")
    try:
        size = target.stat().st_size
        if size > 1_500_000:
            raise HTTPException(400, "File too large to preview here (1.5MB limit).")
        text = target.read_text(encoding="utf-8", errors="replace")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Could not read file: {str(e)[:200]}")
    return {"path": path, "text": text, "size": size}
