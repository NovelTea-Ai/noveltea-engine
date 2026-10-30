"""Shared LLM client for the corpus pipeline.

Prefers the Anthropic API when ANTHROPIC_API_KEY is set; otherwise falls back to
the Claude Code CLI (subscription mode) — the same behaviour the NovelTea Engine app
uses. This lets corpus extraction/genome scripts run with no API credits.

Public API:
    call_llm(system, user, model=None, max_tokens=16000, temperature=0.3) -> str
    have_api_key() -> bool
    mode() -> "api" | "cli"
"""
import os
import threading
import glob
import json
import time
import shutil
import subprocess
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
DEFAULT_MODEL = "claude-sonnet-5-5"

# ── Account pool for CLI subscription rotation ──────────────────────────────
# The `claude` CLI authenticates from ~/.claude/.credentials.json. When an
# account hits its usage limit, we rotate in the next credential file from the
# pool so the pipeline keeps running on a fresh account.
LIVE_CRED = Path.home() / ".claude" / ".credentials.json"
# Pool lives next to the corpus scripts so it ships with the workspace.
ACCOUNTS_DIR = Path(__file__).parent / "accounts"

# Error signatures that mean "this account can't serve the request" — rotate to
# the next pooled account. Covers usage limits AND auth failures (expired/invalid
# token), since both mean the current account is unusable and another may work.
_LIMIT_SIGNATURES = (
    # usage / billing limits (subscription CLI uses "spending cap", "usage limit", etc.)
    "credit balance is too low", "usage limit", "rate limit", "limit reached",
    "spending cap", "spending limit", "cap reached", "reached your limit",
    "quota", "insufficient", "429", "too many requests", "resets",
    # auth failures (expired/invalid token, logged out)
    "invalid api key", "please run /login", "unauthorized", "401",
    "authentication", "not logged in", "expired",
)


def _pool_files():
    """Credential files available in the pool, sorted for stable ordering."""
    if not ACCOUNTS_DIR.exists():
        return []
    return sorted(glob.glob(str(ACCOUNTS_DIR / "*.json")))


def _cred_fingerprint(path):
    """A stable id for a credentials file (by accessToken tail) so we can tell
    which pool account is currently live and pick a different one."""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        tok = (d.get("claudeAiOauth", {}) or {}).get("accessToken", "")
        return tok[-24:] if tok else ""
    except Exception:
        return ""


def _token_expired(path) -> bool:
    """True if the credential file's OAuth access token is past its expiry.
    Installing an expired token causes a 401 that looks like a logout, so we
    NEVER rotate to a stale account."""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        exp = (d.get("claudeAiOauth", {}) or {}).get("expiresAt", 0) / 1000.0
        # small skew buffer
        return exp < (time.time() + 60)
    except Exception:
        return True


def _rotate_account(tried=None):
    """Swap the live credentials to a pool account NOT already tried this call AND
    whose token is still valid (never install an expired token — that 401s and
    looks like a logout). Returns the fingerprint switched to, or None."""
    tried = tried or set()
    pool = _pool_files()
    if not pool:
        return None
    live_fp = _cred_fingerprint(LIVE_CRED) if LIVE_CRED.exists() else ""
    for cand in pool:
        fp = _cred_fingerprint(cand)
        if not fp or fp in tried or fp == live_fp:
            continue
        if _token_expired(cand):
            print(f"  [account] skipping …{fp[-8:]} — token expired (re-add it via Settings)")
            continue
        try:
            LIVE_CRED.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cand, LIVE_CRED)
            print(f"  [account] rotated to pool account …{fp[-8:]}")
            return fp
        except Exception as e:
            print(f"  [account] failed to rotate to {cand}: {str(e)[:80]}")
    print("  [account] no usable pool account (all expired/tried) — run `claude /login`")
    return None


# ── Cancellation registry ────────────────────────────────────────────────────
# A caller with its own natural key (e.g. the Standard page's per-extraction
# request id) can pass abort_key= into call_llm() to get a REAL, working abort
# — not just a UI-side "stop waiting" — regardless of which engine ends up
# running. Each chain below registers whatever it can actually kill under this
# key for the live duration of its call (a Popen handle for the CLI-based
# engines, the urlopen()'d request object for the direct-HTTP engines) and
# deregisters it in a finally, so a stale entry can never outlive its call.
# None (the default, unchanged for every existing caller) means "can't be
# aborted from outside" — exactly today's behaviour.
import threading as _threading

_ABORT_REGISTRY: dict = {}          # abort_key -> killable handle (Popen | http.client response/connection-ish)
_ABORT_REGISTRY_LOCK = _threading.Lock()
_ABORTED_KEYS: set = set()          # keys flagged for abort — checked/cleared per attempt, same shape as generate.py's own


class CallAborted(Exception):
    """Raised (and left uncaught by the retry loops) when abort_call() was
    invoked for this call's key — a deliberate stop, not a transient failure,
    so it must never be retried/rotated like a network error would be."""


def _register_abortable(abort_key, handle):
    if abort_key is None:
        return
    with _ABORT_REGISTRY_LOCK:
        _ABORT_REGISTRY[abort_key] = handle


def _unregister_abortable(abort_key, handle):
    if abort_key is None:
        return
    with _ABORT_REGISTRY_LOCK:
        if _ABORT_REGISTRY.get(abort_key) is handle:
            del _ABORT_REGISTRY[abort_key]


def _check_aborted(abort_key):
    """Raise CallAborted if this key was flagged — call at each natural
    between-attempts checkpoint (registration was already killed by
    abort_call() itself; this catches the case where the kill raced a call
    that had already moved past its killable window, e.g. between retries)."""
    if abort_key is not None and abort_key in _ABORTED_KEYS:
        _ABORTED_KEYS.discard(abort_key)
        raise CallAborted(f"call aborted (key={abort_key})")


def abort_call(abort_key) -> bool:
    """Kill whatever is CURRENTLY registered under abort_key, if anything, and
    flag the key so a between-attempts checkpoint catches it even if nothing
    was registered at the exact moment this runs (e.g. abort lands during the
    gap between one attempt ending and the next Popen/urlopen starting).
    Returns True if a live handle was found and killed right now."""
    with _ABORT_REGISTRY_LOCK:
        handle = _ABORT_REGISTRY.get(abort_key)
        _ABORTED_KEYS.add(abort_key)
    if handle is None:
        return False
    try:
        if hasattr(handle, "kill"):          # subprocess.Popen
            handle.kill()
        elif hasattr(handle, "close"):       # http.client-like response/connection
            handle.close()
    except Exception:
        pass
    return True


_LIVE_STATUS_FILE = Path(__file__).parent / "_pipeline_live_status.json"


def write_live_status(job: str, **fields):
    """Best-effort 'what's happening right now' status, written right before
    an LLM call starts — so the app's Corpus Pipeline page/console can show
    real activity (which novel, what's actually being classified) instead of
    only a done/total count that updates once per batch. One shared file,
    keyed by job, so multiple pipeline scripts can coexist in it."""
    try:
        data = {}
        if _LIVE_STATUS_FILE.exists():
            try:
                data = json.loads(_LIVE_STATUS_FILE.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        data[job] = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), **fields}
        _LIVE_STATUS_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def have_api_key() -> bool:
    return bool(_API_KEY)


def mode() -> str:
    return "api" if have_api_key() else "cli"


# ── App Settings integration (Agent Engine + Gemini/Qoder pools) ─────────────
# The NovelTea Engine app saves its settings to ~/.noveltea-engine/config.json. The corpus
# pipeline reads the SAME file so the Settings page / top engine dropdown
# controls this pipeline too — whichever engine is explicitly selected there
# is exactly what runs here, no separate corpus-pipeline config needed:
#   generation.agent_engine → which engine runs extraction ("claude"|"gemini"|"qoder"|"kimi"|"nemotron"|"ollama")
#   models.gemini_cli       → gemini model id
#   gemini_key_pool / _index → free API keys, rotated on rate-limit
#   models.qoder             → qoder model tier (lite|efficient|performance|ultimate|auto)
#   qoder_token_pool / _index → Personal Access Tokens, rotated on billing failure

APP_CONFIG = Path.home() / ".noveltea-engine" / "config.json"


def _app_config() -> dict:
    try:
        return json.loads(APP_CONFIG.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


_ENGINES = ("claude", "gemini", "qoder", "kimi", "nemotron", "ollama", "codex")


def _agent_engine() -> str:
    # NM_FORCE_ENGINE pins THIS process to one engine, whatever the app's dropdown / settings file say (a "Nemotron only" run). It is a
    # process-level override: nothing is written to the shared settings file, so the app and other jobs keep their own selection.
    forced = os.environ.get("NM_FORCE_ENGINE", "").strip().lower()
    if forced in _ENGINES:
        return forced
    eng = (_app_config().get("generation", {}) or {}).get("agent_engine", "claude")
    return eng if eng in ("claude", "gemini", "qoder", "kimi", "nemotron", "ollama", "codex") else "claude"


def current_model_label(nemotron_model: str = None) -> str:
    """Best-effort 'engine:model' label of what call_llm() would actually use
    right now — mirrors its own resolution logic without making a call. For
    live-status/UI display, so the author can see which model is doing the
    work instead of only which engine is configured."""
    engine = _agent_engine()
    if engine == "nemotron":
        return f"nemotron:{nemotron_model or _nemotron_model()}"
    if engine == "claude":
        return f"claude:{_settings_claude_model() or DEFAULT_MODEL}"
    if engine == "gemini":
        return f"gemini:{_gemini_model()}"
    if engine == "qoder":
        return f"qoder:{_qoder_model()}"
    if engine == "kimi":
        return f"kimi:{_kimi_model()}"
    if engine == "codex":
        return f"codex:{_codex_model()}"
    if engine == "ollama":
        return f"ollama:{_ollama_model()}"
    return engine


def engine_batch_size(nemotron: int, other: int) -> int:
    """Batch size follows whichever engine is CURRENTLY selected (Settings/top
    dropdown), not one fixed constant — Nemotron was tested less reliable at
    larger batches than Claude has run at for a long time, so it gets a
    smaller batch by default; every other engine keeps the caller's own
    tuned value."""
    return nemotron if _agent_engine() == "nemotron" else other


GEMINI_DEFAULT_MODEL = "gemini-3.5-flash"   # @google/gemini-cli 0.61's own DEFAULT_GEMINI_FLASH_MODEL


def _gemini_model() -> str:
    return (_app_config().get("models", {}) or {}).get("gemini_cli") or GEMINI_DEFAULT_MODEL


def _settings_claude_model() -> str:
    """The CLI Model picked in Settings (models.anthropic). When set, it wins
    over the per-script hardcoded models — the user picked it for a reason."""
    return (_app_config().get("models", {}) or {}).get("anthropic", "")


# ── Gemini pool: Google accounts (signed in, like the Claude/Codex pools) + API keys ──────────
# Confirmed against @google/gemini-cli 0.61 (its own source + live runs, 2026-09-29):
#   * GEMINI_CLI_HOME relocates the CLI's whole home -- it reads/writes <home>\.gemini\oauth_creds.json
#     (the login) and google_accounts.json (which Google account it is).
#   * GOOGLE_GENAI_USE_GCA=true selects "Login with Google"; GEMINI_API_KEY selects an API key.
# So unlike the Claude/Codex pools, nothing is copied over one live login file: every pooled account
# keeps its OWN home folder and each call just points GEMINI_CLI_HOME at it. Parallel calls (Delta
# Upgrade runs 4 at once) can't trample each other, and signing in from Settings writes straight
# into a new account folder. Folders live under accounts\ -- the tree every agent engine is denied.
#   * With no usable login the CLI asks "...browser. Do you want to continue? [Y/n]" and would wait
#     forever. run_gemini() answers "n" the moment that appears (the CLI then exits in ~2s), marks
#     the account as needing a fresh sign-in, and the caller rotates on -- never a 15-minute hang.
# Rotation order: every usable Google account, then every API key; one shared index for both.
GEMINI_ACCOUNTS_DIR = ACCOUNTS_DIR / "gemini"
_GEMINI_KEYS_HOME = GEMINI_ACCOUNTS_DIR / "_api_keys"   # neutral home for key calls: no login can override the key
_GEMINI_CONSENT = "[Y/n]"
_GEMINI_CFG_LOCK = _threading.Lock()


class GeminiLoginRequired(RuntimeError):
    """The active Google account has no usable login (never signed in, or its sign-in was revoked)."""


def _gemini_update_config(mutate):
    """Read-modify-write ~/.noveltea-engine/config.json atomically (the app and pipeline both write it)."""
    with _GEMINI_CFG_LOCK:
        cfg = _app_config()
        mutate(cfg)
        tmp = APP_CONFIG.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        os.replace(tmp, APP_CONFIG)
        return cfg


def gemini_accounts() -> list:
    """Pooled Google-account homes that hold a login, sorted by name."""
    if not GEMINI_ACCOUNTS_DIR.exists():
        return []
    return sorted(p for p in GEMINI_ACCOUNTS_DIR.iterdir()
                  if p.is_dir() and not p.name.startswith("_") and (p / ".gemini" / "oauth_creds.json").exists())


def gemini_account_email(home) -> str:
    try:
        d = json.loads((Path(home) / ".gemini" / "google_accounts.json").read_text(encoding="utf-8"))
        return d.get("active") or ""
    except Exception:
        return ""


def gemini_slots(cfg: dict = None) -> list:
    """Every pooled way to call Gemini, in rotation order: accounts first, then API keys."""
    cfg = _app_config() if cfg is None else cfg
    needs = set(cfg.get("gemini_needs_login") or [])
    slots = [{"kind": "account", "name": p.name, "home": str(p), "email": gemini_account_email(p),
              "needs_login": p.name in needs} for p in gemini_accounts()]
    for i, k in enumerate(cfg.get("gemini_key_pool") or []):
        if isinstance(k, dict) and k.get("api_key"):
            slots.append({"kind": "key", "name": k.get("label") or f"key {i + 1}", "key": k["api_key"],
                          "key_index": i, "needs_login": False})
    return slots


def _gemini_usable(slots: list) -> list:
    return [s for s in slots if not s["needs_login"]]


def gemini_active_slot(cfg: dict = None):
    cfg = _app_config() if cfg is None else cfg
    usable = _gemini_usable(gemini_slots(cfg))
    return usable[cfg.get("gemini_slot_index", 0) % len(usable)] if usable else None


def gemini_use_slot(kind: str, name: str = None, key_index: int = None) -> bool:
    """Make this account (by folder name) or key (by position in gemini_key_pool -- labels can
    repeat) the active one. Settings' "Use" button."""
    def _m(cfg):
        usable = _gemini_usable(gemini_slots(cfg))
        for i, s in enumerate(usable):
            if s["kind"] == kind and (s.get("key_index") == key_index if kind == "key" else s["name"] == name):
                cfg["gemini_slot_index"] = i
                return
        raise ValueError(f"no usable Gemini {kind} {name if kind == 'account' else key_index!r}")
    try:
        _gemini_update_config(_m)
        return True
    except ValueError:
        return False


def gemini_rotate(reason: str = "") -> bool:
    """Advance to the next usable account/key. False if there's nothing else to rotate to."""
    moved = {}

    def _m(cfg):
        usable = _gemini_usable(gemini_slots(cfg))
        if len(usable) < 2:
            return
        cfg["gemini_slot_index"] = (cfg.get("gemini_slot_index", 0) + 1) % len(usable)
        moved["to"] = usable[cfg["gemini_slot_index"]]
    try:
        _gemini_update_config(_m)
    except Exception as e:
        print(f"  [account] gemini rotation failed: {str(e)[:80]}")
        return False
    if moved:
        s = moved["to"]
        print(f"  [account] gemini{' (' + reason + ')' if reason else ''} -> {s['kind']} \"{s['name']}\"")
    return bool(moved)


def gemini_mark_needs_login(name: str, needs: bool = True):
    def _m(cfg):
        cur = set(cfg.get("gemini_needs_login") or [])
        cur.add(name) if needs else cur.discard(name)
        cfg["gemini_needs_login"] = sorted(cur)
    _gemini_update_config(_m)


def gemini_apply_auth(env: dict):
    """Point `env` at the active account/key. Returns that slot (None = nothing pooled; an
    ambient GEMINI_API_KEY is used if one is set)."""
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_GCA", "GOOGLE_GENAI_USE_VERTEXAI", "GEMINI_CLI_HOME",
              "GEMINI_FORCE_ENCRYPTED_FILE_STORAGE"):
        env.pop(k, None)
    env["GEMINI_CLI_TRUST_WORKSPACE"] = "true"   # headless CLI exits 55 without this
    # Keep every login in its own home's oauth_creds.json -- the per-account folders ARE the pool.
    # (The CLI only moves Google logins into the OS credential store when that encrypted-storage
    # variable is set; this pins the plain-file behaviour no matter what the PC has set.)
    env["GEMINI_FORCE_FILE_STORAGE"] = "true"
    s = gemini_active_slot()
    if s is None:
        k = os.environ.get("GEMINI_API_KEY", "").strip()
        if k:
            env["GEMINI_API_KEY"] = k
        return None
    if s["kind"] == "account":
        env["GOOGLE_GENAI_USE_GCA"] = "true"
        env["GEMINI_CLI_HOME"] = s["home"]
    else:
        _GEMINI_KEYS_HOME.mkdir(parents=True, exist_ok=True)
        env["GEMINI_API_KEY"] = s["key"]
        env["GEMINI_CLI_HOME"] = str(_GEMINI_KEYS_HOME)
    return s


def gemini_pool_size() -> int:
    return len(_gemini_usable(gemini_slots()))


def gemini_is_limit_error(msg: str) -> bool:
    m = (msg or "").lower()
    return any(s in m for s in ("rate limit", "quota", "resource_exhausted", "429", "too many requests"))


def _gemini_kill_tree(pid: int):
    # npx -> gemini.js -> a relaunched node with a bigger heap: killing only the first leaves the rest
    # holding stdout open, so a plain timeout never returns (seen live). Take the whole tree down.
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=20)
        else:
            os.killpg(pid, 9)
    except Exception:
        pass


def run_gemini(args: list, env: dict, timeout: int = 900, cwd=None, abort_key=None, slot=None):
    """Run the Gemini CLI once. -> object with .returncode/.stdout/.stderr (subprocess.run shape).
    Raises GeminiLoginRequired (after marking the account) if it asks to sign in, and
    subprocess.TimeoutExpired after killing the whole process tree on timeout."""
    class _R:
        pass
    flags = 0x08000000 if os.name == "nt" else 0
    # stdin stays an OPEN pipe: the CLI only briefly waits for piped input before running -p, and an
    # open pipe is what lets us answer the sign-in question (a closed stdin makes it hang on EOF).
    proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=env, cwd=str(cwd) if cwd else None, creationflags=flags,
                            start_new_session=(os.name != "nt"))
    _register_abortable(abort_key, proc)
    out, err, asked = [], [], []

    def _pump(stream, sink, watch):
        while True:
            chunk = stream.read1(4096) if hasattr(stream, "read1") else stream.read(4096)
            if not chunk:
                break
            sink.append(chunk)
            if watch and not asked and _GEMINI_CONSENT in b"".join(sink[-3:]).decode("utf-8", "replace"):
                asked.append(True)
                try:
                    proc.stdin.write(b"n\n")
                    proc.stdin.flush()
                except Exception:
                    pass
    threads = [_threading.Thread(target=_pump, args=(proc.stdout, out, True), daemon=True),
               _threading.Thread(target=_pump, args=(proc.stderr, err, True), daemon=True)]
    for t in threads:
        t.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _gemini_kill_tree(proc.pid)
        raise
    finally:
        _unregister_abortable(abort_key, proc)
        for t in threads:
            t.join(timeout=5)
    _check_aborted(abort_key)
    r = _R()
    r.returncode = proc.returncode
    r.stdout = b"".join(out).decode("utf-8", "replace")
    r.stderr = b"".join(err).decode("utf-8", "replace")
    if asked:
        if slot and slot.get("kind") == "account":
            gemini_mark_needs_login(slot["name"])
            raise GeminiLoginRequired(f"Gemini account \"{slot['name']}\" needs to sign in again (Settings → CLI Accounts → Gemini)")
        raise GeminiLoginRequired("Gemini CLI wants a Google sign-in — add a Gemini account or API key in Settings")
    return r


def _gemini_entry_js():
    """The CLI's real entry script. On Windows `gemini` and `npx` are .cmd batch shims, and a
    batch file cuts a command-line argument off at its first line break -- measured 2026-09-29:
    a 3-line -p prompt arrived as just its first line through a .cmd, intact through node
    directly. Every Gemini prompt here is many lines, so the CLI is run as `node gemini.js`."""
    gem = shutil.which("gemini")
    if gem:
        js = Path(gem).parent / "node_modules" / "@google" / "gemini-cli" / "bundle" / "gemini.js"
        if js.exists():
            return js
    cache = Path(os.environ.get("LOCALAPPDATA", "")) / "npm-cache" / "_npx"
    found = sorted(cache.glob("*/node_modules/@google/gemini-cli/bundle/gemini.js"),
                   key=lambda p: p.stat().st_mtime, reverse=True) if cache.exists() else []
    return found[0] if found else None


def _gemini_argv() -> list:
    js, node = _gemini_entry_js(), shutil.which("node")
    if js and node:
        return [node, str(js)]
    gem = shutil.which("gemini")
    if gem:
        return [gem]
    npx = shutil.which("npx")
    if npx:
        return [npx, "-y", "@google/gemini-cli"]
    raise RuntimeError("Gemini CLI not found (npm install -g @google/gemini-cli)")


def _gemini_available() -> bool:
    """The CLI can run AND there's something to sign it in with (a pooled account/key, or an
    ambient GEMINI_API_KEY) -- without one every call would just ask to sign in."""
    cli = shutil.which("gemini") is not None or shutil.which("npx") is not None
    return cli and (gemini_pool_size() > 0 or bool(os.environ.get("GEMINI_API_KEY", "").strip()))


def _qoder_model() -> str:
    return (_app_config().get("models", {}) or {}).get("qoder") or "efficient"


def _qoder_pool() -> list:
    return _app_config().get("qoder_token_pool", []) or []


def _qoder_active_token() -> str:
    pool = _qoder_pool()
    if not pool:
        return os.environ.get("QODER_PERSONAL_ACCESS_TOKEN", "").strip()
    idx = _app_config().get("qoder_token_pool_index", 0) % len(pool)
    return pool[idx].get("token", "")


def _qoder_rotate_token():
    """Advance the shared pool index (persisted to the app config, atomically)
    so the NEXT call — here or in the app — uses a different token."""
    cfg = _app_config()
    pool = cfg.get("qoder_token_pool", []) or []
    if len(pool) < 2:
        return False
    cfg["qoder_token_pool_index"] = (cfg.get("qoder_token_pool_index", 0) + 1) % len(pool)
    try:
        tmp = APP_CONFIG.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        os.replace(tmp, APP_CONFIG)
        print(f"  [account] rotated to qoder pool token #{cfg['qoder_token_pool_index'] + 1}")
        return True
    except Exception as e:
        print(f"  [account] qoder token rotation failed: {str(e)[:80]}")
        return False


def _qoder_cli_path():
    """The pip package's own _bundled/qodercli.exe is NOT what corpus-pipeline
    users are expected to have — same "install it yourself" story as the app's
    packaged exe. Prefer a system install on PATH; None falls through to the
    SDK's own bundled-binary lookup, which IS present in a plain pip install
    (unlike the PyInstaller-packaged app, this script runs from source)."""
    return shutil.which("qodercli")


def _qoder_available() -> bool:
    try:
        import qoder_agent_sdk  # noqa: F401
    except ImportError:
        return False
    return bool(_qoder_active_token())


def _is_qoder_billing_error(msg: str) -> bool:
    m = (msg or "").lower()
    return any(s in m for s in ("forbidden", "code\":\"112\"", "pricing", "quota", "429",
                                 "too many requests", "insufficient", "no active plan"))


def _kimi_model() -> str:
    """Confirmed real aliases (kimi-code/docs/en/kimi-code/models.html):
    k3 (flagship, 1M ctx), kimi-for-coding (K2.7 Code, 256k, default),
    kimi-for-coding-highspeed (6x speed / 3x quota)."""
    return (_app_config().get("models", {}) or {}).get("kimi") or "kimi-for-coding"


def _kimi_pool() -> list:
    return _app_config().get("kimi_key_pool", []) or []


def _kimi_active_key() -> str:
    pool = _kimi_pool()
    if not pool:
        return ""
    idx = _app_config().get("kimi_key_pool_index", 0) % len(pool)
    return pool[idx].get("api_key", "")


def _kimi_rotate_key():
    cfg = _app_config()
    pool = cfg.get("kimi_key_pool", []) or []
    if len(pool) < 2:
        return False
    cfg["kimi_key_pool_index"] = (cfg.get("kimi_key_pool_index", 0) + 1) % len(pool)
    try:
        tmp = APP_CONFIG.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        os.replace(tmp, APP_CONFIG)
        print(f"  [account] rotated to kimi pool key #{cfg['kimi_key_pool_index'] + 1}")
        return True
    except Exception as e:
        print(f"  [account] kimi key rotation failed: {str(e)[:80]}")
        return False


def _kimi_cli_path():
    return shutil.which("kimi")


def _kimi_config_path():
    return Path.home() / ".kimi-code" / "config.toml"


def _kimi_write_provider_key(key: str):
    """Kimi has no env-var auth path — api_key is a direct config.toml field
    (confirmed via --help and the providers doc). Preserves the rest of the
    file; only replaces/adds the [providers.kimi] block."""
    if not key:
        return
    import re as _re
    cfg_path = _kimi_config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = cfg_path.read_text(encoding="utf-8") if cfg_path.exists() else ""
    except Exception:
        existing = ""
    block_re = _re.compile(r"\[providers\.kimi\].*?(?=\n\[|\Z)", _re.DOTALL)
    new_block = f'[providers.kimi]\ntype = "kimi"\nbase_url = "https://api.moonshot.ai/v1"\napi_key = "{key}"\n'
    if block_re.search(existing):
        updated = block_re.sub(new_block.rstrip("\n"), existing)
    else:
        updated = existing.rstrip("\n") + ("\n\n" if existing.strip() else "") + new_block
    cfg_path.write_text(updated, encoding="utf-8")


def _kimi_available() -> bool:
    if not _kimi_cli_path():
        return False
    if _kimi_active_key():
        return True
    try:
        return _kimi_config_path().exists() and len(_kimi_config_path().read_text(encoding="utf-8").strip()) > 200
    except Exception:
        return False


# ── Nemotron (NVIDIA) ────────────────────────────────────────────────────────
# Unlike the other engines this is a direct OpenAI-compatible HTTPS call, not a
# CLI subprocess — so there is no binary to install and no command-line length
# cap to work around. Model/endpoint must agree: the ":free" suffix is
# OpenRouter-only and 404s against NVIDIA's endpoint (verified live).

NEMOTRON_DEFAULT_ENDPOINT = "https://integrate.api.nvidia.com/v1"
NEMOTRON_DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"

# When True, a reply that isn't clean JSON is handed back as-is instead of re-asking the
# model the same question (the Claude CLI's "blunter reprompt" retry, Nemotron's re-send on
# the next pooled key). Callers that set it (upgrade_deltas.py) salvage the JSON themselves --
# the data is usually in there, just wrapped in reasoning prose or cut off at the end, and
# re-running a 3-10 minute call to get it again is the single biggest waste in that job.
NO_BAD_JSON_RETRY = False


def _nemotron_model() -> str:
    return (_app_config().get("models", {}) or {}).get("nemotron") or NEMOTRON_DEFAULT_MODEL


def _nemotron_endpoint() -> str:
    return _app_config().get("nemotron_endpoint") or NEMOTRON_DEFAULT_ENDPOINT


def _nemotron_pool() -> list:
    return _app_config().get("nemotron_key_pool", []) or []


# ── Nvidia only: one pooled key per parallel worker ──────────────────────────────────────────────────────────────────
# A job that runs several Nemotron calls at once (the four extraction groups, or Chapter Mechanics / Delta Upgrade
# workers) pins each worker thread to its own key of the pool, so N keys carry N calls at the same time instead of every
# call queuing on the one shared "active" key. A thread that never pins keeps the old behaviour (the shared active key,
# rotated on a 429). Nothing here is read by any other engine.
_NEM_SLOT = _threading.local()
# A finishing step (conflicts, rolling summary, genome) runs beside an extraction: the Corpus Builder starts it with
# NM_NEM_SLOT_START=<last key>, so its one agent sits on the key the fewest extraction agents are using.
try:
    _NEM_SLOT_COUNTER = [int(os.environ.get("NM_NEM_SLOT_START", "0"))]
except ValueError:
    _NEM_SLOT_COUNTER = [0]
_NEM_COOL: dict = {}                     # pool index -> time.time() until which that key just answered 429
_NEM_COOL_LOCK = _threading.Lock()
NEM_COOLDOWN_S = 20


def nemotron_pool_size() -> int:
    return len(_nemotron_pool())


def nemotron_parallel_slots(want: int) -> int:
    """How many calls can run at once on Nvidia without sharing a key: min(want, keys in the pool); 1 for any other engine."""
    if _agent_engine() != "nemotron":
        return 1
    return max(1, min(want, nemotron_pool_size()))


def pin_nemotron_slot(slot: int = None):
    """Pin the CALLING thread to one pooled key (slot % pool size). No argument: the next free slot, round-robin across
    threads. Safe to call on any engine (it only affects Nemotron calls)."""
    if slot is None:
        with _NEM_COOL_LOCK:
            slot = _NEM_SLOT_COUNTER[0]
            _NEM_SLOT_COUNTER[0] += 1
    _NEM_SLOT.slot = slot


def ensure_nemotron_slot():
    """Pin the calling thread to its own pooled key once (a pool worker calls this at the top of every task; later calls
    keep the slot it already has). Only matters on Nvidia."""
    if getattr(_NEM_SLOT, "slot", None) is None:
        pin_nemotron_slot()


def unpin_nemotron_slot():
    _NEM_SLOT.slot = None


def _nemotron_key_for(attempt: int):
    """(pool index, key) for this thread's attempt-th try. Pinned thread: its own key first, then the following ones,
    skipping keys that answered 429 within NEM_COOLDOWN_S (unless every key is cooling). Unpinned: the shared active key."""
    pool = _nemotron_pool()
    slot = getattr(_NEM_SLOT, "slot", None)
    if not pool:
        return None, ""
    if slot is None:
        idx = _app_config().get("nemotron_key_pool_index", 0) % len(pool)
        return None, pool[idx].get("api_key", "")
    order = [(slot + i) % len(pool) for i in range(len(pool))]      # own key first, then the following ones
    now = time.time()
    with _NEM_COOL_LOCK:
        warm = [i for i in order if _NEM_COOL.get(i, 0) <= now]
    pick = warm or order                                             # every key cooling: fall back to the plain order
    i = pick[attempt % len(pick)]
    return i, pool[i].get("api_key", "")


def _nemotron_active_key() -> str:
    pool = _nemotron_pool()
    if not pool:
        return ""
    idx = _app_config().get("nemotron_key_pool_index", 0) % len(pool)
    return pool[idx].get("api_key", "")


def _nemotron_rotate_key():
    """Advance the shared pool index (persisted atomically), same as the other pools."""
    cfg = _app_config()
    pool = cfg.get("nemotron_key_pool", []) or []
    if len(pool) < 2:
        return
    cfg["nemotron_key_pool_index"] = (cfg.get("nemotron_key_pool_index", 0) + 1) % len(pool)
    try:
        tmp = APP_CONFIG.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp, APP_CONFIG)
    except Exception:
        pass


def _nemotron_available() -> bool:
    return bool(_nemotron_active_key())


def _http_post_json(url: str, payload: dict, headers: dict, timeout: int, abort_key=None):
    """POST JSON via http.client (not urllib.request.urlopen) so the live
    HTTPConnection can be REGISTERED for abort_call() to close from another
    thread — urlopen() gives no handle back until it already has a full
    response, so a request stuck server-side (NVIDIA/Ollama sitting on a
    request, no fast 5xx) could never actually be killed, only ignored.
    Returns (status, body_bytes). Raises whatever the connection raises
    (including CallAborted, via a closed-socket error translated below)."""
    import http.client
    import urllib.parse

    parsed = urllib.parse.urlparse(url)
    conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    conn = conn_cls(parsed.hostname, parsed.port, timeout=timeout)
    _register_abortable(abort_key, conn)
    try:
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        conn.request("POST", path, body=json.dumps(payload).encode("utf-8"), headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        return resp.status, body
    except (ConnectionError, OSError) as e:
        # abort_call() closing the socket surfaces here as a plain connection
        # error — check the flag to tell a deliberate abort apart from a real
        # network failure so the retry loop doesn't treat a cancel as transient.
        _check_aborted(abort_key)
        raise
    finally:
        _unregister_abortable(abort_key, conn)
        try:
            conn.close()
        except Exception:
            pass


_NEM_TIMEOUT = threading.local()


def nemotron_timeout_s() -> int:
    """Read timeout (seconds) for a Nemotron request on THIS thread: the default 300, or what set_nemotron_timeout chose.
    A request Nvidia sits on without answering is only abandoned and retried when this runs out."""
    return int(getattr(_NEM_TIMEOUT, "s", None) or 300)


def set_nemotron_timeout(seconds=None):
    """Set (or, with None, clear) this thread's Nemotron read timeout. The Corpus Builder's part queue gives its small calls
    (voice / prose / world) a shorter one so a stalled request is retried after minutes, not after the full five."""
    _NEM_TIMEOUT.s = seconds


def _nemotron_who() -> str:
    """Which agent is making this call: its number, the pooled key it is pinned to, and (when the Corpus Builder started this
    script as one of its steps) the step - so a console line can be traced to an agent."""
    try:
        slot = getattr(_NEM_SLOT, "slot", None)
        size = max(1, nemotron_pool_size())
        who = f"agent {slot + 1} - key {slot % size + 1}" if slot is not None else f"unpinned - key {_app_config().get('nemotron_key_pool_index', 0) % size + 1}"
        step = os.environ.get("NM_STEP_LABEL", "")
        return who + (f" - {step}" if step else "")
    except Exception:
        return "agent ?"


def _call_nemotron(system: str, user: str, model: str = None, required_keys=None, abort_key=None) -> str:
    """Corpus extraction via the NVIDIA Nemotron API, with the same JSON-contract
    discipline as the Gemini/Qoder/Kimi paths. Rotates the key pool on 401/403/429
    and retries transient 5xx (NVIDIA sheds load with a 503 'ResourceExhausted')."""
    nmodel = model or _nemotron_model()
    endpoint = _nemotron_endpoint().rstrip("/")
    print(f"  [model] Nemotron -> {nmodel}  [{_nemotron_who()}]")

    if ":free" in nmodel and "openrouter" not in endpoint:
        raise RuntimeError(
            f"Nemotron model '{nmodel}' uses the ':free' suffix, which only resolves on "
            f"OpenRouter. Drop the suffix, or set nemotron_endpoint to OpenRouter."
        )

    if not required_keys:
        required_keys = _schema_keys_from_prompt(system)
    keys_line = ""
    if required_keys:
        keys_line = (
            " The JSON object MUST use EXACTLY these top-level keys (do not rename them, "
            "do not invent your own schema): " + ", ".join(required_keys) + "."
        )
    contract = (
        "OUTPUT FORMAT — ABSOLUTELY MANDATORY: Return ONLY a single raw JSON object. "
        "Your entire reply MUST begin with the character '{' and end with '}'. "
        "Do NOT write any sentence, heading, bullet list, markdown fence, or summary. "
        "Do NOT say what you did. Follow the schema in the instructions above EXACTLY."
        + keys_line
    )

    messages = [
        {"role": "system", "content": system + "\n\n" + contract},
        {"role": "user", "content": user + "\n\nBegin your reply with '{' immediately."},
    ]

    last_err = ""
    # One attempt per pooled key, so a rate-limited key rotates to the next.
    for _try in range(max(len(_nemotron_pool()), 1)):
        _check_aborted(abort_key)
        key_idx, api_key = _nemotron_key_for(_try)
        if not api_key:
            raise RuntimeError(
                "No Nemotron API key pooled (app Settings → CLI Accounts → Nemotron Key Pool)."
            )

        payload = {
            "model": nmodel,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 16000,
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        out = ""
        for attempt in range(4):
            _check_aborted(abort_key)
            try:
                status, raw_body = _http_post_json(
                    f"{endpoint}/chat/completions", payload, headers, timeout=nemotron_timeout_s(), abort_key=abort_key,
                )
                if status != 200:
                    detail = raw_body.decode("utf-8", errors="replace")[:200]
                    last_err = f"HTTP {status} {detail}"
                    if status in (500, 502, 503, 504) and attempt < 3:
                        time.sleep(2 ** attempt)
                        continue
                    break
                body = json.loads(raw_body.decode("utf-8"))
                out = (body["choices"][0]["message"].get("content") or "").strip()
                break
            except CallAborted:
                raise
            except Exception as e:
                last_err = str(e)
                if attempt < 3:
                    time.sleep(2 ** attempt)
                    continue
                break

        if not out:
            # Auth/rate failures are worth retrying on a different pooled key.
            if any(s in last_err for s in ("401", "403", "429")):
                print(f"  [llm] Nemotron key failed ({last_err[:60]}) — rotating pool")
                if key_idx is None:
                    _nemotron_rotate_key()          # unpinned: the shared active key moves on (as before)
                else:
                    with _NEM_COOL_LOCK:             # pinned worker: rest this key briefly, try the next one
                        _NEM_COOL[key_idx] = time.time() + NEM_COOLDOWN_S
                continue
            raise RuntimeError(f"Nemotron call failed: {last_err[:200]}")

        # Nemotron reasoning models wrap their chain-of-thought in ``` blocks.
        if "```" in out:
            out = out.split("```")[-1].strip()

        text = _extract_json_text(out)
        if text:
            return text
        if NO_BAD_JSON_RETRY:
            return out   # caller salvages it -- don't re-send the same request on the next key
        last_err = f"no JSON object in response: {out[:120]}"

    raise RuntimeError(f"Nemotron call failed: {last_err[:200]}")


# ── Ollama ───────────────────────────────────────────────────────────────────
# Ollama provides local LLM inference via a simple HTTP API. It runs on
# localhost:11434 by default and supports various models like llama3, mistral, gemma, etc.
# No API key is required for local instances, but we support key pools for consistency
# with other engines (useful for remote Ollama instances with auth).

OLLAMA_DEFAULT_HOST = "http://127.0.0.1:11434"   # not "localhost": ~2s per call on Windows (IPv6 attempt first; Ollama listens on IPv4 only)
OLLAMA_DEFAULT_MODEL = "gemma3:12b"  # Using Gemma as preferred per user request


def _ollama_model() -> str:
    return (_app_config().get("models", {}) or {}).get("ollama") or OLLAMA_DEFAULT_MODEL


def _ollama_host() -> str:
    return _app_config().get("ollama_host") or OLLAMA_DEFAULT_HOST


def _ollama_pool() -> list:
    return _app_config().get("ollama_key_pool", []) or []


def _ollama_active_key() -> str:
    pool = _ollama_pool()
    if not pool:
        return ""  # Local Ollama doesn't require auth by default
    idx = _app_config().get("ollama_key_pool_index", 0) % len(pool)
    return pool[idx].get("api_key", "")


def _ollama_rotate_key():
    """Advance the shared pool index (persisted to the app config, atomically)
    so the NEXT call — here or in the app — uses a different key."""
    cfg = _app_config()
    pool = cfg.get("ollama_key_pool", []) or []
    if len(pool) < 2:
        return False
    cfg["ollama_key_pool_index"] = (cfg.get("ollama_key_pool_index", 0) + 1) % len(pool)
    try:
        tmp = APP_CONFIG.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        os.replace(tmp, APP_CONFIG)
        print(f"  [account] rotated to ollama pool key #{cfg['ollama_key_pool_index'] + 1}")
        return True
    except Exception as e:
        print(f"  [account] ollama key rotation failed: {str(e)[:80]}")
        return False


def _ollama_available() -> bool:
    """Check if Ollama is running and accessible."""
    try:
        import urllib.request
        import urllib.error
        host = _ollama_host().rstrip("/")
        req = urllib.request.Request(f"{host}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.getcode() == 200
    except Exception:
        return False


def _call_ollama(system: str, user: str, model: str = None, required_keys=None, abort_key=None) -> str:
    """Corpus extraction via the Ollama API, with the same JSON-contract
    discipline as other paths. Uses local Ollama instance by default."""
    omodel = model or _ollama_model()
    host = _ollama_host().rstrip("/")
    print(f"  [model] Ollama -> {omodel}")

    if not required_keys:
        required_keys = _schema_keys_from_prompt(system)
    keys_line = ""
    if required_keys:
        keys_line = (
            " The JSON object MUST use EXACTLY these top-level keys (do not rename them, "
            "do not invent your own schema): " + ", ".join(required_keys) + "."
        )
    contract = (
        "OUTPUT FORMAT — ABSOLUTELY MANDATORY: Return ONLY a single raw JSON object. "
        "Your entire reply MUST begin with the character '{' and end with '}'. "
        "Do NOT write any sentence, heading, bullet list, markdown fence, or summary. "
        "Do NOT say what you did. Follow the schema in the instructions above EXACTLY."
        + keys_line
    )

    messages = [
        {"role": "system", "content": system + "\n\n" + contract},
        {"role": "user", "content": user + "\n\nBegin your reply with '{' immediately."},
    ]

    payload = {
        "model": omodel,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": 16000,
        }
    }

    # Add API key if provided (for remote Ollama instances with auth)
    headers = {"Content-Type": "application/json"}
    api_key = _ollama_active_key()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    _check_aborted(abort_key)
    try:
        status, raw_body = _http_post_json(f"{host}/api/chat", payload, headers, timeout=300, abort_key=abort_key)
    except CallAborted:
        raise
    except Exception as e:
        raise RuntimeError(f"Ollama call failed: {str(e)[:200]}")
    if status != 200:
        raise RuntimeError(f"Ollama call failed: HTTP {status} {raw_body.decode('utf-8', errors='replace')[:200]}")
    body = json.loads(raw_body.decode("utf-8"))
    out = (body.get("message", {}).get("content") or "").strip()

    # Extract JSON from response (same as other engines)
    text = _extract_json_text(out)
    if text:
        return text
    # If no JSON found, return the raw output (will be handled by caller's quality check)
    return out


def _is_kimi_billing_error(msg: str) -> bool:
    m = (msg or "").lower()
    return any(s in m for s in ("membership", "quota", "rate limit", "429", "too many requests",
                                 "insufficient", "unable to verify", "no active", "unauthorized", "401"))


def _call_api(system: str, user: str, model: str = None,
              max_tokens: int = 16000, temperature: float = 0.3) -> str:
    import anthropic
    print(f"  [model] Anthropic API -> {model or DEFAULT_MODEL}")
    client = anthropic.Anthropic(api_key=_API_KEY)
    resp = client.messages.create(
        model=model or DEFAULT_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
    )
    return resp.content[0].text


def _schema_keys_from_prompt(system: str) -> list:
    """Best-effort: pull the required top-level JSON keys out of a schema prompt.
    Matches lines like 'summary  — 2-5 sentences' or 'new_characters — array of'."""
    import re as _re
    keys = []
    for m in _re.finditer(r"(?m)^([a-z_][a-z0-9_]{2,40})\s+[—\-]", system):
        k = m.group(1)
        if k not in keys:
            keys.append(k)
    return keys


def _cli_argv():
    """Argv prefix for the Claude CLI. On Windows `claude` resolves to an npm
    .CMD shim, and cmd.exe TRUNCATES any argument at its first newline — which
    silently drops all but the FIRST LINE of a multi-line --system-prompt (i.e.
    the entire extraction schema). Bypass the shim via node + cli.js directly."""
    cli = shutil.which("claude")
    if not cli:
        raise RuntimeError(
            "No ANTHROPIC_API_KEY and 'claude' CLI not found in PATH. "
            "Install Claude Code (subscription) or set an API key."
        )
    if cli.lower().endswith((".cmd", ".bat")):
        pkg = Path(cli).parent / "node_modules" / "@anthropic-ai" / "claude-code"
        # Newer claude-code ships a NATIVE bin/claude.exe; older versions shipped
        # cli.js to run under node. Prefer the real executable, then the js
        # entrypoint — anything but the .CMD shim.
        #
        # Why this matters: going through the shim means cmd.exe parses the
        # command line, and cmd.exe caps it at 8191 chars (NOT the 32767 of
        # CreateProcess). Our --system-prompt is ~8.7 KB, so the call dies with
        # "The command line is too long." and every chapter silently fails over
        # to the fallback engine. When this lookup missed, the bypass was dead
        # code and Claude could never be used on Windows at all.
        exe = pkg / "bin" / "claude.exe"
        if exe.exists():
            return [str(exe)]
        node = shutil.which("node")
        for cand in (pkg / "cli.js", pkg / "cli-wrapper.cjs"):
            if node and cand.exists():
                return [node, str(cand)]
    return [cli]


def _run_subprocess_abortable(args, input_text=None, timeout=900, env=None, creationflags=0, abort_key=None):
    """subprocess.run-alike, but via Popen so the live process can be
    registered for abort_call() to actually kill — subprocess.run() gives no
    handle back until the process has already exited, so a stuck CLI call
    (Claude/Gemini/Kimi) could never really be aborted, only ignored while it
    kept running server-side. Returns an object with the same .returncode/
    .stdout/.stderr shape subprocess.run's CompletedProcess has. Raises
    subprocess.TimeoutExpired on timeout, CallAborted if abort_call() fired."""
    class _Result:
        pass
    proc = subprocess.Popen(
        args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", env=env, creationflags=creationflags,
    )
    _register_abortable(abort_key, proc)
    try:
        stdout, stderr = proc.communicate(input=input_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.communicate(timeout=5)
        except Exception:
            pass
        raise
    finally:
        _unregister_abortable(abort_key, proc)
    if abort_key is not None and proc.returncode < 0:
        # kill() gives a negative returncode on POSIX; on Windows kill() still
        # leaves a nonzero code but abort_call() already flagged the key, so
        # the explicit check below (not this branch) is what actually catches
        # a Windows-killed abort. Kept for the POSIX case, harmless elsewhere.
        _check_aborted(abort_key)
    _check_aborted(abort_key)
    r = _Result()
    r.returncode, r.stdout, r.stderr = proc.returncode, stdout, stderr
    return r


CLI_EFFORTS = ("low", "medium", "high", "xhigh", "max")   # the Claude Code CLI's --effort levels


def _call_cli(system: str, user: str, model: str = None, required_keys=None, abort_key=None,
              effort: str = None) -> str:
    """Subscription fallback via the Claude Code CLI (no API key needed).
    effort: one of CLI_EFFORTS, passed as --effort (None = the CLI's own default)."""
    cli_argv = _cli_argv()
    # The CLI is an agent and tends to invent its own analysis schema, ignoring the
    # exact keys the caller asked for. Pin the required top-level keys explicitly.
    if not required_keys:
        required_keys = _schema_keys_from_prompt(system)
    # Pass the full model id straight through — the CLI accepts ids like
    # claude-fable-5 directly. The old sonnet/haiku/opus alias mapping silently
    # downgraded anything it didn't recognize (e.g. Fable) to sonnet.
    cli_model = model or DEFAULT_MODEL
    effort_args = ["--effort", effort] if effort in CLI_EFFORTS else []
    print(f"  [model] Claude Code CLI (subscription) -> {cli_model}" + (f" (effort {effort})" if effort_args else ""))
    # The corpus extractors expect a raw JSON object back. The CLI tends to
    # summarise its work instead ("I've created a comprehensive analysis…"), so we
    # (a) put the contract in the system prompt AND at the end of the user message,
    # and (b) retry once with a blunter reprompt if no JSON object comes back.
    keys_line = ""
    if required_keys:
        keys_line = (
            " The JSON object MUST use EXACTLY these top-level keys (do not rename them, "
            "do not invent your own schema, do not add keys like 'characters' or 'plot_points'): "
            + ", ".join(required_keys) + "."
        )
    contract = (
        "OUTPUT FORMAT — ABSOLUTELY MANDATORY: Return ONLY a single raw JSON object. "
        "Your entire reply MUST begin with the character '{' and end with '}'. "
        "Do NOT write any sentence, heading, bullet list, markdown fence, or summary. "
        "Do NOT say what you did. Follow the schema in the instructions above EXACTLY."
        + keys_line
    )
    cli_system = system + "\n\n" + contract

    # CRITICAL: the `claude` CLI uses ANTHROPIC_API_KEY from the environment if set,
    # which bills that key's (possibly dead) balance instead of the subscription
    # login. When falling back to CLI mode we want the SUBSCRIPTION, so strip the
    # key from the subprocess env — this makes the CLI use `claude /login` creds.
    import os as _os
    _cli_env = {k: v for k, v in _os.environ.items()
                if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_API_KEY")}

    def _run(user_text):
        import time as _time
        last_err = ""
        rotations = 0
        timeouts = 0
        _tried_fps = set()
        max_rotations = max(1, len(_pool_files()))
        # Retry with backoff + account rotation. Two failure modes:
        #  - transient throttle → back off and retry the same account
        #  - account limit hit  → rotate to the next pool account and retry
        for attempt in range(8):
            _check_aborted(abort_key)
            # Since the full multi-line schema now reaches the model (shim fix),
            # extractions run longer — allow 15 min and treat a timeout as a
            # TRANSIENT failure (retry) instead of killing the whole chapter.
            try:
                # CREATE_NO_WINDOW: give node its OWN hidden console. Sharing the
                # parent console (or having none) intermittently crashes node at
                # startup with "Assertion failed: process_title" (libuv race).
                _flags = 0x08000000 if os.name == "nt" else 0
                result = _run_subprocess_abortable(
                    cli_argv + ["-p", "--output-format", "text", "--model", cli_model, *effort_args,
                                "--system-prompt", cli_system],
                    input_text=user_text, timeout=900, env=_cli_env, creationflags=_flags,
                    abort_key=abort_key,
                )
            except subprocess.TimeoutExpired:
                last_err = "CLI call timed out (900s)"
                timeouts += 1
                if timeouts < 2 and attempt < 7:   # at most one timeout retry
                    print(f"  [llm] {last_err} — retrying...")
                    continue
                break
            except CallAborted:
                raise
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
            last_err = (result.stderr.strip() or result.stdout.strip()
                        or f"exit {result.returncode}, no output").strip()
            el = last_err.lower()
            limit_hit = any(sig in el for sig in _LIMIT_SIGNATURES)
            transient = result.returncode != 0 and (
                not last_err or any(t in el for t in
                                    ("rate", "overload", "429", "timeout", "busy", "try again", "limit",
                                     "assertion failed", "process_title"))   # node startup race — retry
            )
            # Account limit/auth failure → rotate to an untried pool account.
            if limit_hit and rotations < max_rotations:
                cur_fp = _cred_fingerprint(LIVE_CRED)
                if cur_fp:
                    _tried_fps.add(cur_fp)   # this account just failed — don't reuse
                switched = _rotate_account(tried=_tried_fps)
                rotations += 1
                if switched:
                    _tried_fps.add(switched)
                    _time.sleep(1)
                    continue
                # every pool account exhausted — fall through to backoff/give up
            if attempt < 7 and transient:
                _time.sleep(min(30, 5 * (attempt + 1)))
                continue
            break
        raise RuntimeError(f"claude CLI error: {last_err[:300] or 'empty response after retries'}")

    def _extract_json(out):
        import re as _re
        if out.startswith("{"):
            return out
        m = _re.search(r"```(?:json)?\s*(\{.*\})\s*```", out, _re.DOTALL)
        if m:
            return m.group(1).strip()
        i, j = out.find("{"), out.rfind("}")
        if i != -1 and j > i:
            return out[i:j + 1]
        return None

    import json as _json

    def _quality_ok(js_text):
        """A CLI JSON is 'good enough' if it parses AND fills a reasonable share of
        the required keys (the CLI often returns valid-but-empty objects)."""
        if not required_keys:
            return True
        try:
            d = _json.loads(js_text)
        except Exception:
            return False
        filled = sum(1 for k in required_keys if d.get(k) not in (None, "", [], {}))
        # need at least ~40% of the requested keys populated
        return filled >= max(1, int(len(required_keys) * 0.4))

    user_with_contract = f"{user}\n\n{contract}"
    out = _run(user_with_contract)
    js = _extract_json(out)
    # Retry once if we got nothing parseable OR a valid-but-empty (wrong-schema) object --
    # unless the caller salvages JSON itself (NO_BAD_JSON_RETRY), where an honest empty
    # answer ("nothing more to add") is a real result, not something to re-ask.
    if not NO_BAD_JSON_RETRY and (js is None or not _quality_ok(js)):
        retry_user = (
            f"{user}\n\nYour previous reply did not follow the required schema "
            f"(it was empty, prose, or used the wrong keys). {contract}\n"
            "Fill in every key with real extracted content from the chapter. "
            "Begin your reply with '{' right now."
        )
        out2 = _run(retry_user)
        js2 = _extract_json(out2)
        if js2 is not None and (_quality_ok(js2) or js is None):
            js = js2
    return js if js is not None else out


def _extract_json_text(out: str):
    import re as _re
    if out.startswith("{"):
        return out
    m = _re.search(r"```(?:json)?\s*(\{.*\})\s*```", out, _re.DOTALL)
    if m:
        return m.group(1).strip()
    i, j = out.find("{"), out.rfind("}")
    if i != -1 and j > i:
        return out[i:j + 1]
    return None


def _json_quality_ok(js_text: str, required_keys) -> bool:
    if not required_keys:
        return True
    try:
        d = json.loads(js_text)
    except Exception:
        return False
    filled = sum(1 for k in required_keys if d.get(k) not in (None, "", [], {}))
    return filled >= max(1, int(len(required_keys) * 0.4))


def _call_gemini_cli(system: str, user: str, model: str = None, required_keys=None, abort_key=None) -> str:
    """Corpus extraction via the Gemini CLI, using the shared Settings key pool.
    Same JSON-contract discipline as the Claude CLI path (schema keys pinned,
    brace-extraction, one blunter retry on empty/wrong-schema output); rotates
    to the next pooled free key on a rate-limit/quota error."""
    argv = _gemini_argv()
    gmodel = _gemini_model()
    print(f"  [model] Gemini CLI -> {gmodel}")
    if not required_keys:
        required_keys = _schema_keys_from_prompt(system)
    keys_line = ""
    if required_keys:
        keys_line = (
            " The JSON object MUST use EXACTLY these top-level keys (do not rename them, "
            "do not invent your own schema): " + ", ".join(required_keys) + "."
        )
    contract = (
        "OUTPUT FORMAT — ABSOLUTELY MANDATORY: Return ONLY a single raw JSON object. "
        "Your entire reply MUST begin with the character '{' and end with '}'. "
        "Do NOT write any sentence, heading, bullet list, markdown fence, or summary. "
        "Do NOT say what you did. Follow the schema in the instructions above EXACTLY."
        + keys_line
    )

    def _run(user_text):
        last_err = ""
        rotations = 0
        pool_size = max(gemini_pool_size(), 1)
        for attempt in range(4 + pool_size):
            _check_aborted(abort_key)
            env = {k: v for k, v in os.environ.items()
                   if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_API_KEY")}
            slot = gemini_apply_auth(env)
            # No --system-prompt flag exists — fold system into the prompt text.
            # Order matters: task in the middle, format contract LAST — ending
            # with anything else makes the CLI reply conversationally
            # ("Acknowledged, ready to assist…") instead of doing the task.
            full_prompt = (f"{system}\n\n---\n\nTASK (do this now, in this reply):\n{user_text}"
                           f"\n\n---\n\n{contract} Begin your reply with '{{' immediately.")
            try:
                result = run_gemini(argv + ["--output-format", "json", "--model", gmodel, "-p", full_prompt],
                                    env, timeout=900, abort_key=abort_key, slot=slot)
            except GeminiLoginRequired as e:
                last_err = str(e)
                print(f"  [account] {last_err}")
                if rotations < pool_size - 1 and gemini_rotate("needs sign-in"):
                    rotations += 1
                    continue
                break
            except subprocess.TimeoutExpired:
                last_err = "gemini CLI call timed out (900s)"
                if NO_BAD_JSON_RETRY:
                    break      # the caller salvages/requeues -- don't burn another 15 minutes on the same call
                print(f"  [llm] {last_err} — retrying...")
                continue
            except CallAborted:
                raise
            try:
                envelope = json.loads(result.stdout.strip())
            except Exception:
                envelope = None
            if isinstance(envelope, dict) and not envelope.get("error"):
                text = (envelope.get("response") or envelope.get("text") or "").strip()
                if text:
                    return text
                last_err = "empty response in successful envelope"
            else:
                err_obj = envelope.get("error") if isinstance(envelope, dict) else None
                last_err = ((err_obj.get("message") if isinstance(err_obj, dict) else None)
                            or result.stderr.strip() or result.stdout.strip()
                            or f"exit {result.returncode}, no output").strip()
            if gemini_is_limit_error(last_err):
                if rotations < pool_size - 1 and gemini_rotate("limit reached"):
                    rotations += 1
                    continue
                break      # every account/key is at its limit -- retrying now just fails again
            if attempt < 3:
                time.sleep(min(20, 5 * (attempt + 1)))
                continue
            break
        raise RuntimeError(f"gemini CLI error: {last_err[:300] or 'empty response after retries'}")

    out = _run(user)
    js = _extract_json_text(out)
    if js is None and NO_BAD_JSON_RETRY:
        return out      # caller salvages the reply itself
    if not NO_BAD_JSON_RETRY and (js is None or not _json_quality_ok(js, required_keys)):
        retry_user = (
            f"{user}\n\nYour previous reply did not follow the required schema "
            f"(it was empty, prose, or used the wrong keys). {contract}\n"
            "Fill in every key with real extracted content from the chapter. "
            "Begin your reply with '{' right now."
        )
        out2 = _run(retry_user)
        js2 = _extract_json_text(out2)
        if js2 is not None and (_json_quality_ok(js2, required_keys) or js is None):
            js = js2
    return js if js is not None else out


def _call_qoder_agent(system: str, user: str, model: str = None, required_keys=None, abort_key=None) -> str:
    """Corpus extraction via the Qoder Agent SDK (native Python async package,
    not a subprocess CLI), using the shared Settings token pool. Same
    JSON-contract discipline as the Gemini/Claude paths; rotates to the next
    pooled token on a billing/quota error (confirmed live: a token without an
    active paid Qoder plan authenticates fine but every query fails with
    'Qoder API error: FORBIDDEN - code 112', pointing to qoder.com/pricing)."""
    import anyio
    from qoder_agent_sdk import AssistantMessage, QoderAgentOptions, ResultMessage, TextBlock, query
    from qoder_agent_sdk.auth import AccessTokenAuthOptions
    from qoder_agent_sdk._internal.query import ControlProtocolError

    qmodel = _qoder_model()
    print(f"  [model] Qoder Agent SDK -> {qmodel}")
    if not required_keys:
        required_keys = _schema_keys_from_prompt(system)
    keys_line = ""
    if required_keys:
        keys_line = (
            " The JSON object MUST use EXACTLY these top-level keys (do not rename them, "
            "do not invent your own schema): " + ", ".join(required_keys) + "."
        )
    contract = (
        "OUTPUT FORMAT — ABSOLUTELY MANDATORY: Return ONLY a single raw JSON object. "
        "Your entire reply MUST begin with the character '{' and end with '}'. "
        "Do NOT write any sentence, heading, bullet list, markdown fence, or summary. "
        "Do NOT say what you did. Follow the schema in the instructions above EXACTLY."
        + keys_line
    )

    # A live SDK query() has no external handle to register (it's an async
    # generator inside anyio.run, not a killable process/socket), so abort
    # works via a cancel scope the query loop itself checks each message —
    # cancel_event is set by abort_call() closing this "handle" (a duck-typed
    # object with .close() so _register_abortable/_unregister_abortable need
    # no special-casing for this engine).
    class _CancelHandle:
        def __init__(self):
            self.event = _threading.Event()
        def close(self):
            self.event.set()

    async def _one_call(user_text: str, token: str, cancel_handle) -> tuple:
        full_prompt = (f"{system}\n\n---\n\nTASK (do this now, in this reply):\n{user_text}"
                       f"\n\n---\n\n{contract} Begin your reply with '{{' immediately.")
        options = QoderAgentOptions(
            auth=AccessTokenAuthOptions(access_token=token) if token else None,
            model=qmodel, allowed_tools=[], permission_mode="default",
            max_turns=3, cli_path=_qoder_cli_path(),
        )
        text = ""
        err = None
        aborted = False
        try:
            with anyio.fail_after(900):
                async for message in query(prompt=full_prompt, options=options):
                    if cancel_handle.event.is_set():
                        aborted = True
                        break
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                text += block.text
                    elif isinstance(message, ResultMessage):
                        if message.is_error:
                            err = (message.result or text or f"subtype={message.subtype}").strip()
        except ControlProtocolError as e:
            err = (text or str(e)).strip()
        if aborted:
            raise CallAborted(f"call aborted (key={abort_key})")
        return text.strip(), err

    def _run(user_text):
        last_err = ""
        tokens_tried = 0
        pool_size = max(len(_qoder_pool()), 1)
        for attempt in range(4):
            _check_aborted(abort_key)
            token = _qoder_active_token()
            cancel_handle = _CancelHandle()
            _register_abortable(abort_key, cancel_handle)
            try:
                text, err = anyio.run(_one_call, user_text, token, cancel_handle)
            except CallAborted:
                raise
            except TimeoutError:
                last_err = "qoder call timed out (900s)"
                print(f"  [llm] {last_err} — retrying...")
                continue
            except Exception as e:
                last_err = str(e)
            else:
                if not err and text:
                    return text
                last_err = err or "empty response"
            finally:
                _unregister_abortable(abort_key, cancel_handle)
            if _is_qoder_billing_error(last_err):
                if tokens_tried < pool_size - 1 and _qoder_rotate_token():
                    tokens_tried += 1
                    continue
            if attempt < 3:
                time.sleep(min(20, 5 * (attempt + 1)))
                continue
        raise RuntimeError(f"qoder agent error: {last_err[:300] or 'empty response after retries'}")

    out = _run(user)
    js = _extract_json_text(out)
    if js is None or not _json_quality_ok(js, required_keys):
        retry_user = (
            f"{user}\n\nYour previous reply did not follow the required schema "
            f"(it was empty, prose, or used the wrong keys). {contract}\n"
            "Fill in every key with real extracted content from the chapter. "
            "Begin your reply with '{' right now."
        )
        out2 = _run(retry_user)
        js2 = _extract_json_text(out2)
        if js2 is not None and (_json_quality_ok(js2, required_keys) or js is None):
            js = js2
    return js if js is not None else out


def _call_kimi_cli(system: str, user: str, model: str = None, required_keys=None, abort_key=None) -> str:
    """Corpus extraction via the Kimi Code CLI, using the shared Settings key
    pool written into ~/.kimi-code/config.toml before each attempt (no env-var
    auth path exists). Same JSON-contract discipline as the Gemini/Qoder paths.

    Confirmed live via --help and a real (membership-rejected) call:
      • prompt goes in as `-p "text"` (argv value) — hits the SAME OS
        command-line length cap as Gemini ("Argument list too long", confirmed
        live with a 40k-char prompt). Same fix: prompts over a threshold are
        written to a temp file with a short -p instruction to read it.
      • --output-format stream-json's EXACT envelope shape could not be
        confirmed against a real success response (every live attempt hit a
        membership-verification wall). Best-effort parse below.
      • --yolo/--auto/--plan are ALL REJECTED in combination with --prompt
        ("Cannot combine --prompt with --yolo") — none are passed."""
    kimi_bin = _kimi_cli_path()
    if not kimi_bin:
        raise RuntimeError("kimi CLI not found on PATH. Install: npm install -g @moonshot-ai/kimi-code")
    kmodel = _kimi_model()
    print(f"  [model] Kimi Code CLI -> {kmodel}")
    if not required_keys:
        required_keys = _schema_keys_from_prompt(system)
    keys_line = ""
    if required_keys:
        keys_line = (
            " The JSON object MUST use EXACTLY these top-level keys (do not rename them, "
            "do not invent your own schema): " + ", ".join(required_keys) + "."
        )
    contract = (
        "OUTPUT FORMAT — ABSOLUTELY MANDATORY: Return ONLY a single raw JSON object. "
        "Your entire reply MUST begin with the character '{' and end with '}'. "
        "Do NOT write any sentence, heading, bullet list, markdown fence, or summary. "
        "Do NOT say what you did. Follow the schema in the instructions above EXACTLY."
        + keys_line
    )

    def _run(user_text):
        full_prompt = (f"{system}\n\n---\n\nTASK (do this now, in this reply):\n{user_text}"
                       f"\n\n---\n\n{contract} Begin your reply with '{{' immediately.")
        prompt_file = None
        if len(full_prompt) > 6000:
            import tempfile, uuid as _uuid
            prompt_file = Path(tempfile.gettempdir()) / f"noveltea_kimi_prompt_{_uuid.uuid4().hex}.txt"
            prompt_file.write_text(full_prompt, encoding="utf-8")
            cold_prompt = (f"Read the file at this EXACT path first, then do exactly what it says — it "
                           f"contains your full task and instructions: {prompt_file}")
        else:
            cold_prompt = full_prompt

        last_err = ""
        keys_tried = 0
        pool_size = max(len(_kimi_pool()), 1)
        flags = 0x08000000 if os.name == "nt" else 0
        try:
            for attempt in range(4):
                _check_aborted(abort_key)
                key = _kimi_active_key()
                if key:
                    _kimi_write_provider_key(key)
                args = [kimi_bin, "-p", cold_prompt, "--output-format", "stream-json", "-m", kmodel]
                try:
                    result = _run_subprocess_abortable(
                        args, timeout=900, creationflags=flags, abort_key=abort_key,
                    )
                except subprocess.TimeoutExpired:
                    last_err = "kimi CLI call timed out (900s)"
                    print(f"  [llm] {last_err} — retrying...")
                    continue
                except CallAborted:
                    raise

                out = result.stdout.strip()
                text = ""
                parsed_any = False
                for line in (out.splitlines() if out else []):
                    line = line.strip()
                    if not line or not line.startswith("{"):
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    parsed_any = True
                    for key_name in ("result", "response", "text", "content"):
                        v = obj.get(key_name)
                        if isinstance(v, str) and v:
                            text += v
                if not parsed_any and out.startswith("{"):
                    try:
                        obj = json.loads(out)
                        parsed_any = True
                        for key_name in ("result", "response", "text", "content"):
                            v = obj.get(key_name)
                            if isinstance(v, str) and v:
                                text += v
                    except Exception:
                        pass
                if not parsed_any:
                    text = out

                if result.returncode == 0 and text.strip():
                    return text.strip()

                last_err = (result.stderr.strip() or out or f"exit {result.returncode}, no output").strip()
                if _is_kimi_billing_error(last_err):
                    if keys_tried < pool_size - 1 and _kimi_rotate_key():
                        keys_tried += 1
                        continue
                if attempt < 3:
                    time.sleep(min(20, 5 * (attempt + 1)))
                    continue
            raise RuntimeError(f"kimi CLI error: {last_err[:300] or 'empty response after retries'}")
        finally:
            if prompt_file is not None:
                prompt_file.unlink(missing_ok=True)

    out = _run(user)
    js = _extract_json_text(out)
    if js is None or not _json_quality_ok(js, required_keys):
        retry_user = (
            f"{user}\n\nYour previous reply did not follow the required schema "
            f"(it was empty, prose, or used the wrong keys). {contract}\n"
            "Fill in every key with real extracted content from the chapter. "
            "Begin your reply with '{' right now."
        )
        out2 = _run(retry_user)
        js2 = _extract_json_text(out2)
        if js2 is not None and (_json_quality_ok(js2, required_keys) or js is None):
            js = js2
    return js if js is not None else out


# ── Codex CLI (OpenAI) ───────────────────────────────────────────────────────
# Confirmed live against a real install (npm install -g @openai/codex,
# codex-cli 0.153.4, Windows): `codex exec [PROMPT]` is the non-interactive
# entry point; `--output-last-message <FILE>` writes JUST the final response
# text to a file (no stdout-scraping needed, unlike every other CLI engine in
# this file — a real, clean win over Kimi/Gemini/Qoder's JSONL/marker
# parsing); `--skip-git-repo-check` is required since NovelTea Engine's working
# dirs aren't git repos; `--sandbox read-only` + exec's own default
# `approval: never` (confirmed live — passing --ask-for-approval to `exec`
# itself is REJECTED, "unexpected argument", because exec is non-interactive
# by construction and never asks) keep it fully unattended. Auth lives at
# ~/.codex/auth.json (ChatGPT OAuth) or an OPENAI_API_KEY field in the same
# file — see settings.py's Codex account-pool endpoints for the same
# rotate-on-limit pool pattern Claude's ~/.claude/.credentials.json pool uses,
# adapted to Codex's one-file auth shape.

CODEX_LIVE_AUTH = Path.home() / ".codex" / "auth.json"
CODEX_ACCOUNTS_DIR = Path(__file__).parent / "codex_accounts"
CODEX_DEFAULT_MODEL = "gpt-5.6-terra"   # confirmed live as `codex exec`'s current default; -m overrides per Settings


def _codex_cli_path():
    return shutil.which("codex")


def _codex_model() -> str:
    return (_app_config().get("models", {}) or {}).get("codex") or CODEX_DEFAULT_MODEL


def _codex_pool_files():
    if not CODEX_ACCOUNTS_DIR.exists():
        return []
    return sorted(glob.glob(str(CODEX_ACCOUNTS_DIR / "*.json")))


def _codex_fp(path) -> str:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        tok = (d.get("tokens", {}) or {}).get("access_token", "")
        return tok[-8:] if tok else ""
    except Exception:
        return ""


def _codex_jwt_claim(token: str, claim: str):
    try:
        import base64 as _b64
        payload_b64 = token.split(".")[1]
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(_b64.urlsafe_b64decode(padded))
        return payload.get(claim)
    except Exception:
        return None


def _codex_token_expired(path) -> bool:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        id_token = (d.get("tokens", {}) or {}).get("id_token", "")
        exp = _codex_jwt_claim(id_token, "exp") or 0
        return exp < (time.time() + 60)
    except Exception:
        return True


def _codex_rotate_account(tried=None):
    """Same shape as _rotate_account() (Claude) above — swap the live
    ~/.codex/auth.json for a pooled account not already tried this call and
    whose token is still valid."""
    tried = tried or set()
    pool = _codex_pool_files()
    if not pool:
        return None
    live_fp = _codex_fp(CODEX_LIVE_AUTH) if CODEX_LIVE_AUTH.exists() else ""
    for cand in pool:
        fp = _codex_fp(cand)
        if not fp or fp in tried or fp == live_fp:
            continue
        if _codex_token_expired(cand):
            print(f"  [account] skipping codex …{fp[-8:]} — token expired (re-add it via Settings)")
            continue
        try:
            CODEX_LIVE_AUTH.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cand, CODEX_LIVE_AUTH)
            print(f"  [account] rotated to codex pool account …{fp[-8:]}")
            return fp
        except Exception as e:
            print(f"  [account] failed to rotate to {cand}: {str(e)[:80]}")
    print("  [account] no usable codex pool account (all expired/tried) — run `codex login`")
    return None


def _codex_available() -> bool:
    return bool(_codex_cli_path()) and CODEX_LIVE_AUTH.exists()


# Same shape as _LIMIT_SIGNATURES (Claude) above — error text that means
# "this Codex account can't serve the request right now," rotate to the next
# pooled one. Not yet confirmed live against a real rate-limited response
# (no account here has been pushed to its cap) — kept close to Claude's own
# signature list plus OpenAI's documented error strings, flagged for
# adjustment once a real limit response is seen.
_CODEX_LIMIT_SIGNATURES = (
    "rate limit", "rate_limit", "quota", "insufficient_quota", "429",
    "too many requests", "usage limit", "resets", "billing",
    "invalid_api_key", "unauthorized", "401", "not logged in", "expired",
)


def _is_codex_limit_error(msg: str) -> bool:
    m = (msg or "").lower()
    return any(s in m for s in _CODEX_LIMIT_SIGNATURES)


def _call_codex_cli(system: str, user: str, model: str = None, required_keys=None, abort_key=None,
                    want_json: bool = True) -> str:
    """Corpus extraction / app generation via the Codex CLI's non-interactive
    `exec` mode. See the module comment above for every flag's confirmed-live
    reasoning. Unlike Kimi/Gemini/Qoder, the response is read from
    --output-last-message's OWN file, not scraped from stdout — codex exec's
    stdout is a full session transcript (banner + turn markers + token
    count), not a clean payload, but -o writes just the final text.

    want_json: True (default) preserves this function's original behavior —
    every corpus-extraction caller wants a bare JSON object back, whether or
    not it happens to pass explicit required_keys (many just describe the
    schema in `system` prose and rely on _schema_keys_from_prompt/the model
    reading it). False is for callers that want PLAIN PROSE back — e.g.
    NovelTeaApp's generate.py routes many "write me text" endpoints (voice
    fix, shorten chapter, chapter drafting, ...) through this same function
    once Codex is the selected engine, and forcing "reply must begin with '{'
    and end with '}'" onto a prompt that explicitly asked for "ONLY the full
    rewritten chapter text, no markdown fences" made the model wrap its prose
    in a JSON object anyway (confirmed live: a voice-fix rewrite came back as
    literal {"rewritten_chapter": "..."} text pasted into the editor instead
    of the chapter prose itself). Every other engine's plain CLI passthrough
    (_call_gemini_cli/_call_kimi_cli/_run_qoder_agent) never had this problem
    because none of them impose a competing contract in the first place —
    want_json=False brings Codex in line with how those already behave.

    Also auto-detects the <<<DECISION>>>/<<<END>>> marker convention
    (NovelTeaApp's Interactive field-survey flow) and treats it the same as
    want_json=False regardless of what the caller passed — that convention
    IS json (between the markers), but forcing a bare-object contract on top
    of it, or letting _extract_json_text strip the markers afterward, breaks
    the caller's own parser either way (confirmed live separately)."""
    codex_bin = _codex_cli_path()
    if not codex_bin:
        raise RuntimeError("codex CLI not found on PATH. Install: npm install -g @openai/codex")
    cmodel = model or _codex_model()
    print(f"  [model] Codex CLI -> {cmodel}")
    wants_markers = "<<<DECISION>>>" in system or "<<<DECISION>>>" in user
    want_json = want_json and not wants_markers
    if not required_keys:
        required_keys = [] if not want_json else _schema_keys_from_prompt(system)
    keys_line = ""
    if required_keys:
        keys_line = (
            " The JSON object MUST use EXACTLY these top-level keys (do not rename them, "
            "do not invent your own schema): " + ", ".join(required_keys) + "."
        )
    contract = (
        "" if not want_json else
        "OUTPUT FORMAT — ABSOLUTELY MANDATORY: Return ONLY a single raw JSON object. "
        "Your entire reply MUST begin with the character '{' and end with '}'. "
        "Do NOT write any sentence, heading, bullet list, markdown fence, or summary. "
        "Do NOT say what you did. Follow the schema in the instructions above EXACTLY."
        + keys_line
    )

    def _run(user_text):
        full_prompt = (f"{system}\n\n---\n\nTASK (do this now, in this reply):\n{user_text}"
                       + (f"\n\n---\n\n{contract} Begin your reply with '{{' immediately." if contract else ""))
        import tempfile, uuid as _uuid
        out_file = Path(tempfile.gettempdir()) / f"noveltea_codex_out_{_uuid.uuid4().hex}.txt"
        last_err = ""
        accounts_tried = 0
        pool_size = max(len(_codex_pool_files()), 1)
        flags = 0x08000000 if os.name == "nt" else 0
        try:
            for attempt in range(4):
                _check_aborted(abort_key)
                # Prompt goes via STDIN ("-"), never argv — confirmed live this
                # matters on Windows: passing a unicode em-dash (the contract
                # string above uses one) as an argv element gets silently
                # mangled through the OS's argv encoding before Codex ever
                # sees it (confirmed live: "OUTPUT FORMAT — ABSOLUTELY" arrived
                # as "OUTPUT FORMAT ? ABSOLUTELY", and the model responded
                # with an empty {} to the corrupted instruction). `codex exec`
                # explicitly documents reading the prompt from stdin when "-"
                # is passed (see --help) — stdin goes through the same
                # text=True/encoding="utf-8" pipe _run_subprocess_abortable
                # already opens, so this sidesteps the whole argv-encoding
                # class of bug instead of patching around it.
                args = [codex_bin, "exec", "--skip-git-repo-check", "--sandbox", "read-only",
                       "-m", cmodel, "--output-last-message", str(out_file), "-"]
                try:
                    result = _run_subprocess_abortable(args, input_text=full_prompt, timeout=900,
                                                       creationflags=flags, abort_key=abort_key)
                except subprocess.TimeoutExpired:
                    last_err = "codex CLI call timed out (900s)"
                    print(f"  [llm] {last_err} — retrying...")
                    continue
                except CallAborted:
                    raise

                text = ""
                if out_file.exists():
                    try:
                        text = out_file.read_text(encoding="utf-8", errors="ignore").strip()
                    except Exception:
                        text = ""
                    out_file.unlink(missing_ok=True)

                if result.returncode == 0 and text:
                    return text

                last_err = (result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}, no output").strip()
                if _is_codex_limit_error(last_err):
                    if accounts_tried < pool_size - 1 and _codex_rotate_account():
                        accounts_tried += 1
                        continue
                if attempt < 3:
                    time.sleep(min(20, 5 * (attempt + 1)))
                    continue
            raise RuntimeError(f"codex CLI error: {last_err[:300] or 'empty response after retries'}")
        finally:
            out_file.unlink(missing_ok=True)

    out = _run(user)
    if not want_json:
        # Return verbatim. For the marker convention, _extract_json_text
        # would strip everything outside the outermost { }, silently deleting
        # the <<<DECISION>>>/<<<END>>> the caller's own regex depends on. For
        # plain want_json=False callers (prose rewrites — voice fix, shorten
        # chapter, chapter drafting, ...), the response already IS the answer
        # verbatim; running it through JSON extraction/repair machinery makes
        # no sense for text that was never meant to be JSON in the first
        # place. No retry loop here either: that loop's retry prompt is
        # itself contract-specific ("Begin your reply with '{' right now"),
        # which would reintroduce the exact collision this branch avoids.
        return out
    js = _extract_json_text(out)
    if js is None or not _json_quality_ok(js, required_keys):
        retry_user = (
            f"{user}\n\nYour previous reply did not follow the required schema "
            f"(it was empty, prose, or used the wrong keys). {contract}\n"
            "Fill in every key with real extracted content from the chapter. "
            "Begin your reply with '{' right now."
        )
        out2 = _run(retry_user)
        js2 = _extract_json_text(out2)
        if js2 is not None and (_json_quality_ok(js2, required_keys) or js is None):
            js = js2
    return js if js is not None else out


def call_llm(system: str, user: str, model: str = None,
             max_tokens: int = 16000, temperature: float = 0.3,
             required_keys=None, nemotron_model: str = None, abort_key=None, effort: str = None) -> str:
    """Return the model's text response. The engine is whichever is explicitly
    selected in Settings/the top dropdown (generation.agent_engine) — Claude,
    Gemini, Qoder, Kimi, Nemotron, or Ollama. No cross-engine failover: each
    engine still retries/rotates within its OWN pool on a transient error, but
    a hard failure on the selected engine raises rather than silently swapping
    to a different one. (Cross-engine failover was tried and removed — it
    could stack multiple engines' retry/backoff loops on a single call, e.g.
    Nemotron 404s -> falls to Claude -> Claude is ALSO rate-limited and retries
    8 times with growing backoff before giving up, which looked like the whole
    pipeline had silently stalled with zero progress for minutes.)
    required_keys: optional list of top-level JSON keys the answer must contain —
    used to detect and retry thin/wrong-schema CLI responses.
    nemotron_model: optional explicit model id, used ONLY when the Nemotron
    chain actually runs — lets a specific CALLER (e.g. the corpus classification
    scripts, which need speed over depth for a simple fixed-category pick) pin
    a smaller/faster Nemotron tier without touching models.nemotron in Settings,
    which stays the author's own choice for chapter generation/dialogue shaping.
    None (the default) falls back to whatever Settings has configured, same as
    before this parameter existed.
    abort_key: optional — if given, a concurrent abort_call(abort_key) from
    another thread will actually kill the in-flight subprocess/connection for
    whichever chain ends up running (CLI engines: Popen kill; Nemotron/Ollama:
    socket close; Qoder: cooperative cancel) and raise CallAborted out of this
    call. None (the default, every existing caller) means unabortable, exactly
    today's behaviour — this is purely additive."""
    # Settings is the authority on the Claude model: the CLI Model picked in the
    # app overrides the per-script hardcoded models (which are only fallbacks).
    #
    # This used to be resolved ONCE up front, gated on `_agent_engine() ==
    # "claude"` — but that reflects the CONFIGURED primary engine, not which
    # chain ends up actually running. During failover, _agent_engine() still
    # returns "claude" even while _nemotron_chain() is what executes, so the
    # claude-sonnet-4-6 string rode along into Nemotron and 404'd every
    # failover attempt (confirmed live: "Nemotron -> claude-sonnet-4-6").
    #
    # Fix: each chain resolves its own model. _claude_chain uses the Settings
    # value regardless of which engine is primary — it only runs when Claude is
    # the chain actually executing. The other chains ignore `model` outright
    # (Gemini/Qoder/Kimi resolve their own from Settings; Nemotron receives
    # None here and does the same), so a claude-* id can no longer leak in.
    claude_model = _settings_claude_model() or model

    def _claude_chain():
        if have_api_key():
            try:
                return _call_api(system, user, claude_model, max_tokens, temperature)
            except Exception as e:
                # If the API fails for a billing / credit / auth / rate reason, fall back
                # to the Claude subscription CLI instead of failing the whole job.
                msg = str(e).lower()
                fallback_triggers = (
                    "credit balance", "billing", "quota", "insufficient",
                    "401", "403", "429", "authentication", "permission",
                    "rate limit", "overloaded", "invalid_request_error",
                )
                if any(t in msg for t in fallback_triggers):
                    print(f"  [llm] API error ({str(e)[:80]}) — falling back to Claude subscription CLI")
                    return _call_cli(system, user, claude_model, required_keys=required_keys, abort_key=abort_key,
                                     effort=effort)
                raise
        # effort only reaches the CLI: it's the CLI's --effort flag, the API call above doesn't send one.
        return _call_cli(system, user, claude_model, required_keys=required_keys, abort_key=abort_key, effort=effort)

    def _gemini_chain():
        # Gemini ignores the `model` argument entirely and resolves its own
        # from Settings — no claude-* leak risk here.
        return _call_gemini_cli(system, user, None, required_keys=required_keys, abort_key=abort_key)

    def _qoder_chain():
        # Ignores the arg and resolves _qoder_model() from Settings.
        return _call_qoder_agent(system, user, None, required_keys=required_keys, abort_key=abort_key)

    def _kimi_chain():
        # Ignores the arg and resolves _kimi_model() from Settings.
        return _call_kimi_cli(system, user, None, required_keys=required_keys, abort_key=abort_key)

    def _codex_chain():
        # Ignores the arg and resolves _codex_model() from Settings.
        return _call_codex_cli(system, user, None, required_keys=required_keys, abort_key=abort_key)

    def _nemotron_chain():
        # nemotron_model (if the caller passed one) pins a specific tier for
        # THIS call only — otherwise None => _call_nemotron resolves
        # models.nemotron from Settings, same as before this param existed.
        return _call_nemotron(system, user, nemotron_model, required_keys=required_keys, abort_key=abort_key)

    def _ollama_chain():
        # None => _call_ollama resolves models.ollama from Settings. Must NOT
        # forward `model`: on a Claude->Ollama failover that still holds the
        # claude-* id, which would not work against Ollama endpoint.
        return _call_ollama(system, user, None, required_keys=required_keys, abort_key=abort_key)

    chains = {"claude": _claude_chain, "gemini": _gemini_chain, "qoder": _qoder_chain,
              "kimi": _kimi_chain, "codex": _codex_chain, "nemotron": _nemotron_chain, "ollama": _ollama_chain}
    available = {"claude": True, "gemini": _gemini_available(), "qoder": _qoder_available(),
                 "kimi": _kimi_available(), "codex": _codex_available(),
                 "nemotron": _nemotron_available(), "ollama": _ollama_available()}

    engine = _agent_engine()
    if not available.get(engine, False):
        print(f"  [llm] {engine} engine selected but not available — using claude")
        engine = "claude"

    _check_aborted(abort_key)
    return chains[engine]()