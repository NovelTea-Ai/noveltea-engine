import json
import time
import shutil
import base64
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from config import CORPUS_PATH

router = APIRouter()

CONFIG_FILE = Path.home() / ".noveltea-engine" / "config.json"

# CLI subscription account pool (rotated by llm_client on limit).
LIVE_CRED = Path.home() / ".claude" / ".credentials.json"
ACCOUNTS_DIR = Path(CORPUS_PATH) / "accounts"

# Codex CLI's own account pool — same rotate-on-limit pattern as Claude's
# above, adapted to Codex's actual auth shape: ONE file (~/.codex/auth.json),
# not a directory tree, confirmed live via a real `codex login`/`codex doctor`
# session — {"auth_mode", "OPENAI_API_KEY", "tokens": {"id_token",
# "access_token", "refresh_token", "account_id"}, "last_refresh"}. No
# plaintext expiry field exists (unlike Claude's expiresAt) — the id_token is
# a JWT whose payload carries a standard "exp" claim, decoded WITHOUT
# signature verification below (same trust model as reading Claude's
# plaintext expiresAt: this app already trusts its own local credential
# files, it never needs to verify them against the issuer).
CODEX_LIVE_AUTH = Path.home() / ".codex" / "auth.json"
CODEX_ACCOUNTS_DIR = Path(CORPUS_PATH) / "codex_accounts"


def _jwt_claim(token: str, claim: str):
    """Decode one claim from a JWT's payload segment, no signature check —
    this app only ever reads tokens it already trusts (its own local
    ~/.codex/auth.json), the same way _cred_fp below reads Claude's plaintext
    OAuth fields without verifying them either."""
    try:
        payload_b64 = token.split(".")[1]
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return payload.get(claim)
    except Exception:
        return None


def _codex_fp(path: Path) -> str:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        tok = (d.get("tokens", {}) or {}).get("access_token", "")
        return tok[-8:] if tok else ""
    except Exception:
        return ""


def _codex_token_expired(path: Path) -> bool:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        id_token = (d.get("tokens", {}) or {}).get("id_token", "")
        exp = _jwt_claim(id_token, "exp") or 0
        return exp < (time.time() + 60)
    except Exception:
        return True


def _cred_fp(path: Path) -> str:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        tok = (d.get("claudeAiOauth", {}) or {}).get("accessToken", "")
        return tok[-8:] if tok else ""
    except Exception:
        return ""


def _cred_refresh_fp(path: Path) -> str:
    """Fingerprint of the REFRESH token, not the access token — the access
    token (and _cred_fp's fingerprint of it) changes every time Claude Code
    silently refreshes its own live credential file in place (normal OAuth
    behavior, no user action), but the refresh token identifying WHICH
    account this is stays the same until that refresh token itself expires
    (refreshTokenExpiresAt, a much longer horizon than expiresAt). Used to
    recognize "this pool snapshot and the live file are the same account,
    just out of sync" even after the access token has rotated underneath."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        tok = (d.get("claudeAiOauth", {}) or {}).get("refreshToken", "")
        return tok[-8:] if tok else ""
    except Exception:
        return ""


def _resync_expired_pool_accounts():
    """Self-heals the exact gap that made EXPIRED accounts require a manual
    re-login + 'Add Current Account' click: Claude Code refreshes its OWN
    live ~/.claude/.credentials.json access token in place on a normal
    schedule (no user action) — but each pool snapshot in ACCOUNTS_DIR is a
    point-in-time COPY that never gets that refresh, so it silently drifts
    stale and _token_expired() correctly (but unhelpfully) starts reporting
    it as EXPIRED even though the account itself is still perfectly logged
    in. Matches pool snapshots to the live file by REFRESH token (stable
    across access-token rotations, unlike _cred_fp's access-token
    fingerprint) and re-copies the live file over any stale, matching
    snapshot whose expiry the live file's is actually later than — so an
    account that's still validly logged in never shows EXPIRED, and the
    user is never sent back to a manual re-login for a token that already
    quietly renewed itself. Best-effort: any failure here just leaves the
    snapshot as it was, same as before this existed."""
    if not LIVE_CRED.exists() or not ACCOUNTS_DIR.exists():
        return
    try:
        live_refresh_fp = _cred_refresh_fp(LIVE_CRED)
        if not live_refresh_fp:
            return
        live_exp = json.loads(LIVE_CRED.read_text(encoding="utf-8")).get("claudeAiOauth", {}).get("expiresAt", 0)
        live_access_fp = _cred_fp(LIVE_CRED)
        for f in ACCOUNTS_DIR.glob("*.json"):
            try:
                if _cred_refresh_fp(f) != live_refresh_fp:
                    continue   # different account — never touch
                snap = json.loads(f.read_text(encoding="utf-8"))
                snap_exp = snap.get("claudeAiOauth", {}).get("expiresAt", 0)
                # Copy when the live file is genuinely newer, OR when its access
                # token has simply rotated (same refresh token, different access
                # token). The previous "live_exp > snap_exp" test alone missed the
                # common case where Claude Code refreshed the access token but the
                # new expiry was NOT numerically greater than the snapshot's — the
                # snapshot then stayed permanently stale and the account showed as
                # inactive even though it was the account actually in use.
                rotated = bool(live_access_fp) and _cred_fp(f) != live_access_fp
                if live_exp > snap_exp or rotated:
                    shutil.copy2(LIVE_CRED, f)
            except Exception:
                continue   # one bad snapshot must never block resyncing the rest
    except Exception:
        pass   # never let this best-effort sync break the caller


def _load_config() -> dict:
    """Tolerant read: a save in another thread/process must never 500 a reader.
    (The old truncate-then-write save left a brief empty-file window.)"""
    if not CONFIG_FILE.exists():
        return {}
    import time
    for attempt in range(3):
        try:
            with open(CONFIG_FILE, encoding="utf-8-sig") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            time.sleep(0.05 * (attempt + 1))   # mid-write — retry briefly
    return {}


def _save_config(cfg: dict):
    """Atomic write: dump to a temp file then os.replace, so readers only ever
    see the old complete file or the new complete file — never a torn write."""
    import os
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_FILE)


class ApiKeyRequest(BaseModel):
    provider: str          # "anthropic" | "openai" | "openrouter"
    api_key: str
    model: Optional[str] = None


@router.get("")
def get_settings():
    cfg = _load_config()
    keys = cfg.get("api_keys", {})
    # Mask keys for display — return last 6 chars only
    masked = {k: ("..." + v[-6:]) if v else "" for k, v in keys.items()}
    return {
        "corpus_path": cfg.get("corpus_path") or str(CORPUS_PATH),      # the folder in use (the bundled empty corpus folder by default)
        "api_keys": masked,
        "models": cfg.get("models", {}),
        "generation": cfg.get("generation", {
            "default_provider": "anthropic",
            "temperature": 0.85,
            "max_tokens": 4096,
        }),
    }


@router.post("/api-key")
def save_api_key(req: ApiKeyRequest):
    cfg = _load_config()
    if "api_keys" not in cfg:
        cfg["api_keys"] = {}
    cfg["api_keys"][req.provider] = req.api_key
    if req.model:
        if "models" not in cfg:
            cfg["models"] = {}
        cfg["models"][req.provider] = req.model
    _save_config(cfg)
    return {"ok": True, "provider": req.provider}


@router.delete("/api-key/{provider}")
def delete_api_key(provider: str):
    cfg = _load_config()
    cfg.get("api_keys", {}).pop(provider, None)
    _save_config(cfg)
    return {"ok": True}


class ModelRequest(BaseModel):
    provider: str
    model: str


@router.post("/model")
def save_model(req: ModelRequest):
    """Set the model for a provider WITHOUT touching its API key — used by the
    CLI-subscription page (models.anthropic drives the `claude -p` model too)."""
    cfg = _load_config()
    cfg.setdefault("models", {})[req.provider] = req.model
    _save_config(cfg)
    return {"ok": True, "provider": req.provider, "model": req.model}


class GenerationSettingsRequest(BaseModel):
    default_provider: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    grep_mode: Optional[str] = None   # fast | targeted | agentic | compare
    agent_engine: Optional[str] = None          # claude | codex | gemini | nemotron | kimi | ollama — which CLI powers agentic features
    agent_engine_failover: Optional[bool] = None  # if the primary engine fails mid-task, retry on the next available engine instead of erroring out.
    verbatim_splice: Optional[bool] = None  # mechanical verbatim-corpus-fragment skeleton, default for chapter generation
    split_extraction: Optional[bool] = None  # corpus extraction across 4 smaller LLM calls instead of 1
    extraction_schema: Optional[str] = None  # "v3" | "v4": v4 = the same 4 calls also extract the Chapter Mechanics


@router.post("/generation")
def save_generation_settings(req: GenerationSettingsRequest):
    cfg = _load_config()
    if "generation" not in cfg:
        cfg["generation"] = {}
    if req.default_provider is not None:
        cfg["generation"]["default_provider"] = req.default_provider
    if req.temperature is not None:
        cfg["generation"]["temperature"] = req.temperature
    if req.max_tokens is not None:
        cfg["generation"]["max_tokens"] = req.max_tokens
    if req.grep_mode is not None and req.grep_mode in ("fast", "targeted", "agentic", "compare"):
        cfg["generation"]["grep_mode"] = req.grep_mode
    if req.agent_engine is not None and req.agent_engine in ("claude", "codex", "gemini", "nemotron", "kimi", "ollama", "colibri"):
        cfg["generation"]["agent_engine"] = req.agent_engine
    if req.agent_engine_failover is not None:
        cfg["generation"]["agent_engine_failover"] = req.agent_engine_failover
    if req.verbatim_splice is not None:
        cfg["generation"]["verbatim_splice"] = req.verbatim_splice
    if req.split_extraction is not None:
        cfg["generation"]["split_extraction"] = req.split_extraction
    if req.extraction_schema is not None and req.extraction_schema in ("v3", "v4"):
        cfg["generation"]["extraction_schema"] = req.extraction_schema
    _save_config(cfg)
    return {"ok": True}


@router.get("/agent-engines")
def list_agent_engines():
    """Which agent CLIs are actually usable right now, for the Settings UI to
    grey out an engine it can't run instead of letting the user pick a dead
    option. Detection mirrors generate.py's _claude_cli_available /
    _nemotron_cli_available / _ollama_cli_available."""
    import shutil
    claude_ok = shutil.which("claude") is not None
    codex_ok = shutil.which("codex") is not None and CODEX_LIVE_AUTH.exists()
    cfg = _load_config()
    # gemini: CLI runnable AND a pooled Google account or API key (llm_client owns the pool)
    gemini_cli_ok = shutil.which("gemini") is not None or shutil.which("npx") is not None
    gemini_ok = _gemini_lc()._gemini_available()
    # nemotron: no CLI binary, just key presence
    nemotron_pool = cfg.get("nemotron_key_pool", []) or []
    nemotron_ok = bool(nemotron_pool)
    # kimi: shares the Nemotron NVIDIA key pool (same nvapi- key, different model ID)
    kimi_ok = nemotron_ok
    # ollama
    from routers.workspace.aicoder import _ollama_tags  # noqa: PLC0415 - avoids an import cycle at module load
    ollama_models = [m.get("name") for m in _ollama_tags() if m.get("name")]
    ollama_ok = bool(ollama_models)
    # colibri: local CPU engine — needs an install + a model container, not a running server (the
    # app starts the gateway on demand)
    try:
        from services import colibri_server as _cs  # noqa: PLC0415
        colibri_ok, colibri_note = _cs.available(), _cs.unavailable_reason()
    except Exception as e:  # noqa: BLE001
        colibri_ok, colibri_note = False, f"Colibrì support failed to load: {e}"
    notes = {}
    if not claude_ok:
        notes["claude"] = "claude CLI not found in PATH"
    if not codex_ok:
        notes["codex"] = ("codex CLI not found in PATH (npm install -g @openai/codex)" if not shutil.which("codex")
                           else "not signed in — run `codex login` (Settings → CLI Accounts → Codex)")
    if not gemini_ok:
        if not gemini_cli_ok:
            notes["gemini"] = "Gemini CLI not found (npm install -g @google/gemini-cli)"
        else:
            notes["gemini"] = "no Google account or API key yet (Settings → CLI Accounts → Gemini)"
    if not nemotron_ok:
        notes["nemotron"] = "no NVIDIA API key pooled (Settings → CLI Accounts → Nemotron Key Pool)"
    if not kimi_ok:
        notes["kimi"] = "no NVIDIA API key pooled (Settings → CLI Accounts → Nemotron Key Pool; Kimi K3 uses the same pool)"
    if not ollama_ok:
        ollama_note = ("Ollama not reachable on " + (cfg.get("ollama_endpoint") or "http://127.0.0.1:11434/v1")
                       + " — start it, then `ollama pull qwen2.5-coder`")
        notes["ollama"] = ollama_note
    return {
        "claude": {"available": claude_ok, "note": notes.get("claude", "")},
        "codex": {"available": codex_ok, "note": notes.get("codex", "")},
        "gemini": {"available": gemini_ok, "note": notes.get("gemini", "")},
        "nemotron": {"available": nemotron_ok, "note": notes.get("nemotron", "")},
        "kimi": {"available": kimi_ok, "note": notes.get("kimi", "")},
        "ollama": {"available": ollama_ok, "note": notes.get("ollama", ""), "models": ollama_models},
        "colibri": {"available": colibri_ok, "note": colibri_note},
        "current": (cfg.get("generation", {}) or {}).get("agent_engine", "claude"),
        "failover": bool((cfg.get("generation", {}) or {}).get("agent_engine_failover", False)),
    }


# ── Nemotron API key pool ────────────────────────────────────────────────────
# Keys for the Nemotron bash agent (nemotron_agent.py), read by the agent and
# the standalone CLI. Same rotation-on-rate-limit shape as the pools above.
# Also used by the Kimi K3 agent (model "moonshotai/kimi-k3") — one NVIDIA key, both models.
# NOTE: model ID and endpoint are paired — "nvidia/nemotron-3-ultra-550b-a55b:free"
# is OpenRouter-only syntax and 404s on NVIDIA's own endpoint (verified live).


class AddNemotronKeyRequest(BaseModel):
    api_key: str
    label: Optional[str] = None


def _nemotron_pool(cfg: dict) -> list:
    return cfg.get("nemotron_key_pool", []) or []


@router.get("/nemotron-keys")
def list_nemotron_keys():
    cfg = _load_config()
    pool = _nemotron_pool(cfg)
    idx = cfg.get("nemotron_key_pool_index", 0) % max(len(pool), 1)
    return {
        "keys": [{"label": k.get("label", ""), "masked": ("..." + k["api_key"][-6:]) if k.get("api_key") else ""}
                 for k in pool],
        "active_index": idx if pool else -1,
    }


@router.post("/nemotron-keys/add")
def add_nemotron_key(req: AddNemotronKeyRequest):
    key = (req.api_key or "").strip()
    if not key:
        raise HTTPException(400, "API key required.")
    cfg = _load_config()
    pool = _nemotron_pool(cfg)
    if any(k.get("api_key") == key for k in pool):
        return {"ok": True, "already_pooled": True}
    label = (req.label or f"key_{len(pool) + 1}").strip()
    pool.append({"label": label, "api_key": key})
    cfg["nemotron_key_pool"] = pool
    _save_config(cfg)
    return {"ok": True, "label": label, "count": len(pool)}


@router.post("/nemotron-keys/remove/{index}")
def remove_nemotron_key(index: int):
    cfg = _load_config()
    pool = _nemotron_pool(cfg)
    if 0 <= index < len(pool):
        pool.pop(index)
        cfg["nemotron_key_pool"] = pool
        if cfg.get("nemotron_key_pool_index", 0) >= len(pool):
            cfg["nemotron_key_pool_index"] = 0
        _save_config(cfg)
    return {"ok": True, "count": len(pool)}


# ── Gemini CLI: Google-account pool + API-key pool ────────────────────────────
# Same idea as the Claude and Codex pools above (sign in once per account, rotate to the next when
# one hits its limit), but the pool itself -- which account/key is live, rotation, the per-account
# homes -- lives in corpus/llm_client.py so the app and the corpus pipeline share ONE pool.
# Each Google account keeps its own Gemini CLI home (accounts/gemini/<name>/.gemini/oauth_creds.json);
# a call just points GEMINI_CLI_HOME at it, so nothing is ever copied over a live login.
import os as _os
import re as _re
import subprocess as _sp
import sys as _sys
import threading as _thr


def _gemini_lc():
    _sys.path.insert(0, str(CORPUS_PATH))
    import llm_client  # noqa: PLC0415
    return llm_client


def _gemini_safe_name(raw: str) -> str:
    s = _re.sub(r"[^A-Za-z0-9._-]+", "_", (raw or "").strip()).strip("._-")
    return s[:60]


class AddGeminiKeyRequest(BaseModel):
    api_key: str
    label: Optional[str] = None


class GeminiUseRequest(BaseModel):
    kind: str                         # "account" | "key"
    name: Optional[str] = None        # account folder name
    key_index: Optional[int] = None   # position in gemini_key_pool


class GeminiLoginRequest(BaseModel):
    label: Optional[str] = None       # name for the new account (default: from its Google email)
    relogin: Optional[str] = None     # an existing account that needs to sign in again


@router.get("/gemini-accounts")
def list_gemini_accounts():
    """Everything the Settings Gemini section shows: pooled Google accounts, pooled API keys,
    which one is live, and whether the CLI is installed (a global install is much faster
    than the npx fallback, which re-resolves the package on every call)."""
    lc = _gemini_lc()
    cfg = _load_config()
    active = lc.gemini_active_slot(cfg)
    accounts = [{"name": s["name"], "email": s["email"], "needs_login": s["needs_login"],
                 "is_active": bool(active) and active["kind"] == "account" and active["name"] == s["name"]}
                for s in lc.gemini_slots(cfg) if s["kind"] == "account"]
    keys = []
    for i, k in enumerate(cfg.get("gemini_key_pool") or []):
        if not isinstance(k, dict) or not k.get("api_key"):
            continue
        keys.append({"index": i, "label": k.get("label") or f"key {i + 1}", "masked": "..." + k["api_key"][-6:],
                     "is_active": bool(active) and active["kind"] == "key" and active.get("key_index") == i})
    return {"accounts": accounts, "keys": keys,
            "cli": {"global": shutil.which("gemini") is not None, "npx": shutil.which("npx") is not None},
            "model": lc._gemini_model(), "login": _gemini_login_public()}


@router.post("/gemini-accounts/use")
def use_gemini_account(req: GeminiUseRequest):
    lc = _gemini_lc()
    if req.kind == "account":
        ok = lc.gemini_use_slot("account", name=req.name)
    elif req.kind == "key":
        ok = lc.gemini_use_slot("key", key_index=req.key_index)
        if ok:   # the direct Gemini API provider (non-agentic generation) reads this index
            cfg = _load_config()
            cfg["gemini_key_pool_index"] = req.key_index
            _save_config(cfg)
    else:
        raise HTTPException(400, "kind must be 'account' or 'key'")
    if not ok:
        raise HTTPException(404, "No usable Gemini account/key by that name (it may need to sign in again).")
    return {"ok": True}


@router.post("/gemini-accounts/remove/{name}")
def remove_gemini_account(name: str):
    lc = _gemini_lc()
    safe = _gemini_safe_name(name)
    target = lc.GEMINI_ACCOUNTS_DIR / safe
    if not safe or safe.startswith("_") or target.resolve().parent != lc.GEMINI_ACCOUNTS_DIR.resolve() or not target.is_dir():
        raise HTTPException(404, "No such Gemini account.")
    shutil.rmtree(target, ignore_errors=True)
    lc.gemini_mark_needs_login(safe, False)
    return {"ok": True}


@router.post("/gemini-keys/add")
def add_gemini_key(req: AddGeminiKeyRequest):
    key = (req.api_key or "").strip()
    if not key:
        raise HTTPException(400, "API key required.")
    cfg = _load_config()
    pool = cfg.get("gemini_key_pool", []) or []
    if any(k.get("api_key") == key for k in pool):
        return {"ok": True, "already_pooled": True}
    label = (req.label or f"key_{len(pool) + 1}").strip()
    pool.append({"label": label, "api_key": key})
    cfg["gemini_key_pool"] = pool
    _save_config(cfg)
    return {"ok": True, "label": label, "count": len(pool)}


@router.post("/gemini-keys/remove/{index}")
def remove_gemini_key(index: int):
    cfg = _load_config()
    pool = cfg.get("gemini_key_pool", []) or []
    if 0 <= index < len(pool):
        pool.pop(index)
        cfg["gemini_key_pool"] = pool
        if cfg.get("gemini_key_pool_index", 0) >= len(pool):
            cfg["gemini_key_pool_index"] = 0
        _save_config(cfg)
    return {"ok": True, "count": len(pool)}


# Headless "Sign in with Google" -- same shape as the headless `codex login` further down: start
# the CLI hidden, surface the sign-in URL, poll for completion. Confirmed against the real CLI
# (0.61): run headless with GOOGLE_GENAI_USE_GCA=true and a home that has no login, it prints
# "Opening authentication page in your browser. Do you want to continue? [Y/n]:", then after "y"
# prints "Otherwise navigate to:\n\n<url>" and opens the browser itself; once the browser flow
# finishes it writes <home>\.gemini\oauth_creds.json (+ google_accounts.json with the email).
# The home is a fresh folder, so the login lands directly in the pool -- no "add current account".
_GEMINI_LOGIN = {"proc": None, "output": "", "status": "idle", "url": None, "home": None,
                 "label": None, "relogin": None, "account": None, "stash": None}
_GEMINI_LOGIN_LOCK = _thr.Lock()


def _gemini_login_public() -> dict:
    return {k: _GEMINI_LOGIN[k] for k in ("status", "url", "account")} | {"output": _GEMINI_LOGIN["output"][-3000:]}


def _gemini_kill(proc):
    if proc is not None and proc.poll() is None:
        try:
            _sp.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=20)
        except Exception:
            pass


def _gemini_login_finish(ok: bool, note: str = ""):
    """Runs once, from the watcher thread: kill the CLI, move the new login into its pool
    folder (or restore the old login if a re-sign-in failed/was cancelled)."""
    lc = _gemini_lc()
    st = _GEMINI_LOGIN
    _gemini_kill(st["proc"])
    home = Path(st["home"])
    if st["relogin"]:
        creds = home / ".gemini" / "oauth_creds.json"
        if ok:
            if st["stash"]:
                Path(st["stash"]).unlink(missing_ok=True)
            lc.gemini_mark_needs_login(st["relogin"], False)
            st["account"] = st["relogin"]
        elif st["stash"] and Path(st["stash"]).exists():
            creds.unlink(missing_ok=True)
            Path(st["stash"]).rename(creds)
    elif ok:
        email = lc.gemini_account_email(home)
        base = _gemini_safe_name(st["label"] or email.split("@")[0] or "google") or "google"
        name, n = base, 2
        while (lc.GEMINI_ACCOUNTS_DIR / name).exists():
            name, n = f"{base}_{n}", n + 1
        for _ in range(20):   # Windows can hold the folder for a moment after the kill
            try:
                home.rename(lc.GEMINI_ACCOUNTS_DIR / name)
                break
            except OSError:
                time.sleep(0.5)
        else:
            ok, note = False, "signed in, but couldn't move the new login into the pool folder"
        if ok:
            st["account"] = name
            lc.gemini_mark_needs_login(name, False)
    else:
        shutil.rmtree(home, ignore_errors=True)
    if note:
        st["output"] += f"\n[{note}]"
    st["status"] = "success" if ok else ("idle" if note == "cancelled" else "failed")
    st["proc"] = None


def _gemini_login_watch(proc, home: Path):
    st = _GEMINI_LOGIN
    creds = home / ".gemini" / "oauth_creds.json"
    answered = False
    buf = b""

    def _pump():
        nonlocal buf, answered
        while True:
            chunk = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(4096)
            if not chunk:
                break
            buf += chunk
            text = buf.decode("utf-8", "replace")
            st["output"] = text
            if not answered and "[Y/n]" in text:
                answered = True
                try:
                    proc.stdin.write(b"y\n")
                    proc.stdin.flush()
                except Exception:
                    pass
            # Re-search every read, not just until first found: a chunk boundary landing mid-URL would
            # otherwise lock in a truncated link forever (confirmed live as exactly this bug in the
            # Claude login reader below, same "only set it once" gate) -- \S+ is greedy, so the match
            # keeps growing to the real full URL as more of it arrives, then stops changing once real
            # whitespace ends it.
            m = _re.search(r"navigate to:\s*(https://\S+)", text)
            if m:
                st["url"] = m.group(1)
    _thr.Thread(target=_pump, daemon=True).start()
    t0, got = time.time(), None
    while st["status"] == "running":
        if creds.exists() and got is None:
            got = time.time()
        # once the login file exists, give the CLI a moment to also write which account it is
        if got and ((home / ".gemini" / "google_accounts.json").exists() or time.time() - got > 15 or proc.poll() is not None):
            with _GEMINI_LOGIN_LOCK:
                if st["status"] == "running":
                    _gemini_login_finish(True)
            return
        if proc.poll() is not None and not creds.exists():
            time.sleep(1)   # the file write can trail the exit by a moment
            if not creds.exists():
                with _GEMINI_LOGIN_LOCK:
                    if st["status"] == "running":
                        _gemini_login_finish(False, f"CLI exited ({proc.returncode}) before a sign-in finished")
                return
        if time.time() - t0 > 600:
            with _GEMINI_LOGIN_LOCK:
                if st["status"] == "running":
                    _gemini_login_finish(False, "timed out after 10 minutes waiting for the browser sign-in")
            return
        time.sleep(0.5)


@router.post("/gemini-accounts/login")
def launch_gemini_login(req: GeminiLoginRequest):
    lc = _gemini_lc()
    with _GEMINI_LOGIN_LOCK:
        if _GEMINI_LOGIN["status"] == "running":
            raise HTTPException(409, "A Gemini sign-in is already in progress — finish or cancel it first.")
        try:
            argv = lc._gemini_argv()
        except RuntimeError as e:
            raise HTTPException(400, str(e))
        lc.GEMINI_ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
        stash = None
        if req.relogin:
            home = lc.GEMINI_ACCOUNTS_DIR / _gemini_safe_name(req.relogin)
            if not home.is_dir():
                raise HTTPException(404, "No such Gemini account.")
            creds = home / ".gemini" / "oauth_creds.json"
            if creds.exists():   # keep the old login aside until the new one actually lands
                stash = str(creds.with_suffix(".json.old"))
                Path(stash).unlink(missing_ok=True)
                creds.rename(stash)
        else:
            home = lc.GEMINI_ACCOUNTS_DIR / f"_signin_{int(time.time())}"
            home.mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in _os.environ.items()
               if k not in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI", "GEMINI_FORCE_ENCRYPTED_FILE_STORAGE",
                            "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_API_KEY")}
        # same auth/storage pinning as llm_client.gemini_apply_auth, so the login lands as a plain
        # oauth_creds.json inside this account's own folder
        env.update({"GOOGLE_GENAI_USE_GCA": "true", "GEMINI_CLI_HOME": str(home), "GEMINI_CLI_TRUST_WORKSPACE": "true",
                    "GEMINI_FORCE_FILE_STORAGE": "true"})
        proc = _sp.Popen(argv + ["--output-format", "json", "-p", "Reply with the single word OK."],
                         stdin=_sp.PIPE, stdout=_sp.PIPE, stderr=_sp.STDOUT, env=env,
                         creationflags=0x08000000 if _os.name == "nt" else 0)
        _GEMINI_LOGIN.update(proc=proc, output="", status="running", url=None, home=str(home),
                             label=req.label, relogin=_gemini_safe_name(req.relogin) if req.relogin else None,
                             account=None, stash=stash)
    _thr.Thread(target=_gemini_login_watch, args=(proc, home), daemon=True).start()
    return {"ok": True, "message": "Gemini sign-in started — waiting for the Google sign-in link…"}


@router.get("/gemini-accounts/login/status")
def gemini_login_status():
    return _gemini_login_public()


@router.post("/gemini-accounts/login/cancel")
def cancel_gemini_login():
    with _GEMINI_LOGIN_LOCK:
        if _GEMINI_LOGIN["status"] == "running":
            _gemini_login_finish(False, "cancelled")
        _GEMINI_LOGIN["status"] = "idle"
    return {"ok": True}


# ── CLI subscription account pool ────────────────────────────────────────────
# The `claude` CLI authenticates from ~/.claude/.credentials.json. Users can add
# multiple accounts to a pool; llm_client rotates to the next one when the current
# account hits its usage limit, so the corpus pipeline keeps running.

class AddAccountRequest(BaseModel):
    label: Optional[str] = None


def _safe_join(base: Path, subpath: str) -> Path:
    """Prevent path traversal by ensuring the resolved path stays within base."""
    # Resolve the full path
    resolved = (base / subpath).resolve()
    # Ensure it's still within the base directory
    if not resolved.is_relative_to(base.resolve()):
        raise ValueError("Attempted path traversal")
    return resolved


@router.get("/accounts")
def list_accounts():
    """List pooled accounts, which is live, and whether each token is still valid."""
    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    _resync_expired_pool_accounts()   # self-heal stale snapshots before reporting EXPIRED — see docstring
    # Identity is matched on the REFRESH token, not the access token. Claude Code
    # auto-refreshes the access token in the live file on its own schedule, so an
    # access-token comparison drifts out of sync within minutes and made the
    # genuinely-live pooled account render as inactive ("nothing is ACTIVE") even
    # though it was working. The refresh token is the stable account identity —
    # same reasoning _resync_expired_pool_accounts already relies on.
    live_refresh_fp = _cred_refresh_fp(LIVE_CRED) if LIVE_CRED.exists() else ""
    live_fp = _cred_fp(LIVE_CRED) if LIVE_CRED.exists() else ""
    accounts = []
    for f in sorted(ACCOUNTS_DIR.glob("*.json")):
        fp = _cred_fp(f)
        refresh_fp = _cred_refresh_fp(f)
        # Prefer the stable refresh-token identity; fall back to the access-token
        # fingerprint only for legacy snapshots that have no refresh token.
        if live_refresh_fp and refresh_fp:
            is_live = refresh_fp == live_refresh_fp
        else:
            is_live = bool(fp) and fp == live_fp
        accounts.append({
            "name": f.stem,
            "fingerprint": fp,
            "is_live": is_live,
            # A pooled snapshot that IS the live account is never "expired" —
            # the live file renews itself, so its snapshot should not be
            # reported stale while it's the account actually in use.
            "expired": (not is_live) and _token_expired(f),
        })
    return {
        "accounts": accounts,
        "live_fingerprint": live_fp,
        "live_refresh_fingerprint": live_refresh_fp,
        "logged_in": LIVE_CRED.exists(),
    }


def _token_expired(path: Path) -> bool:
    import time as _t
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        exp = (d.get("claudeAiOauth", {}) or {}).get("expiresAt", 0) / 1000.0
        return exp < (_t.time() + 60)
    except Exception:
        return True


@router.post("/accounts/add")
def add_account(req: AddAccountRequest):
    """Snapshot the CURRENT logged-in account (~/.claude/.credentials.json) into
    the pool. Flow: `claude /login` to an account in a terminal, click Add Account,
    repeat for each account you want in the rotation."""
    if not LIVE_CRED.exists():
        raise HTTPException(400, "No Claude login found. Run `claude /login` in a terminal first.")
    fp = _cred_fp(LIVE_CRED)
    if not fp:
        raise HTTPException(400, "Current credentials file is not a valid Claude login.")
    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    # Avoid duplicates: if this account (by fingerprint) is already pooled, keep it.
    for f in ACCOUNTS_DIR.glob("*.json"):
        if _cred_fp(f) == fp:
            return {"ok": True, "already_pooled": True, "name": f.stem}
    label = (req.label or f"account_{int(time.time())}").strip().replace(" ", "_")
    # sanitize
    label = "".join(c for c in label if c.isalnum() or c in "_-") or f"account_{int(time.time())}"
    dest = ACCOUNTS_DIR / f"{label}.json"
    try:
        shutil.copy2(LIVE_CRED, dest)
    except Exception as e:
        raise HTTPException(500, f"Failed to copy credentials: {str(e)}")
    return {"ok": True, "name": label, "fingerprint": fp}


@router.post("/accounts/remove/{name}")
def remove_account(name: str):
    # Prevent path traversal
    try:
        f = _safe_join(ACCOUNTS_DIR, f"{name}.json")
    except ValueError:
        raise HTTPException(400, "Invalid account name")
    if f.exists():
        f.unlink()
    return {"ok": True}


@router.post("/accounts/use/{name}")
def use_account(name: str):
    """Manually switch the live login to a specific pooled account."""
    # Prevent path traversal
    try:
        f = _safe_join(ACCOUNTS_DIR, f"{name}.json")
    except ValueError:
        raise HTTPException(400, "Invalid account name")
    if not f.exists():
        raise HTTPException(404, f"Account '{name}' not in pool")
    LIVE_CRED.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(f, LIVE_CRED)
    except Exception as e:
        raise HTTPException(500, f"Failed to switch account: {str(e)}")
    return {"ok": True, "now_live": name, "fingerprint": _cred_fp(f)}


# ── Claude login, run headless (no terminal window) ──────────────────────────
# `/login` (the slash-command) only works INSIDE claude's interactive REPL —
# confirmed live: piping input to `claude` returns "/login isn't available in
# this environment", so it can't be driven as a plain subprocess. But
# `claude auth login` is a genuine one-shot CLI subcommand (confirmed live:
# same URL-in-stdout shape as `codex login`) — it opens the browser itself and
# prints the auth URL as a fallback, then shows "Paste code here if prompted"
# — some OAuth code-exchange paths need that code typed/pasted back, others
# complete on their own via a local callback. This handles BOTH: the reader
# thread watches for either a success/failure signal OR the paste prompt, and
# /accounts/login/submit-code below feeds a pasted code to the still-running
# process's stdin if it's waiting on one.
_CLAUDE_LOGIN_STATE = {"proc": None, "output": "", "status": "idle", "url": None, "awaiting_code": False}


def _claude_login_reader(proc):
    """Same shape as _codex_login_reader — see its comment. Additionally
    watches for the "paste code" prompt, since Claude's flow (unlike Codex's)
    may not complete on its own.

    BUG FIXED 2026-09-30 (this is why a remote-device login never showed the
    paste box): `claude auth login` prints "Paste code here if prompted > "
    as an inline PROMPT with no trailing newline — confirmed live, captured
    verbatim. `for line in proc.stdout:` is a line-buffered iterator: it
    can't yield anything until a '\\n' arrives, so that prompt sat in the
    pipe forever and awaiting_code never flipped true. A local user had a
    workaround (run `claude auth login` in a real terminal on the server
    instead, then Add Account) — a remote user has no server terminal, so
    for them the login genuinely had no way to complete. Fixed by reading
    raw chunks (no newline requirement) and checking the running buffer."""
    import re as _re
    url_re = _re.compile(r'https://\S+')
    try:
        buf, scanned = "", 0
        while True:
            chunk = proc.stdout.read(1)   # text-mode pipe -- 1 char at a time, cheap for a login's tiny output
            if not chunk:
                break
            buf += chunk
            _CLAUDE_LOGIN_STATE["output"] = buf
            # Re-search (don't gate on "already found") every char: reading one byte at a time means
            # the very first search sees only "https://c" and a one-shot "set it once" guard locked
            # that truncated fragment in forever (confirmed live: the link showed as "https://c/").
            # \S+ is greedy, so re-running this just keeps extending the SAME match until real
            # whitespace ends the URL, then further reads don't change it (no new "https://" after it).
            m = url_re.search(buf)
            if m:
                _CLAUDE_LOGIN_STATE["url"] = m.group(0)
            # Only the NOT-yet-scanned tail (with a little overlap so the phrase can't be missed by
            # landing split across two single-char reads) -- submit_claude_login_code clears
            # awaiting_code the moment a code is sent, and the phrase is still sitting in `buf`
            # further back, so scanning the whole buffer every time would immediately flip it back
            # on for no reason. A genuinely new prompt (wrong code, try again) is past `scanned`.
            tail = buf[max(0, scanned - 15):].lower()
            if "paste code" in tail or "paste the code" in tail:
                _CLAUDE_LOGIN_STATE["awaiting_code"] = True
            scanned = len(buf)
        proc.wait()
        out = _CLAUDE_LOGIN_STATE["output"]
        if proc.returncode == 0 and ("success" in out.lower() or "logged in" in out.lower()):
            _CLAUDE_LOGIN_STATE["status"] = "success"
        else:
            _CLAUDE_LOGIN_STATE["status"] = "failed"
        _CLAUDE_LOGIN_STATE["awaiting_code"] = False
    except Exception as e:
        _CLAUDE_LOGIN_STATE["status"] = "failed"
        _CLAUDE_LOGIN_STATE["awaiting_code"] = False
        _CLAUDE_LOGIN_STATE["output"] += f"\n[reader error] {e}"


@router.post("/accounts/login")
def launch_login():
    """Start `claude auth login` as a hidden background process (no terminal
    window) and return immediately. The frontend polls /accounts/login/status
    for the auth URL and completion, and — if the flow needs it — submits a
    pasted-back code via /accounts/login/submit-code."""
    import subprocess, shutil as _sh, sys as _sys, threading

    old = _CLAUDE_LOGIN_STATE.get("proc")
    if old is not None and old.poll() is None:
        raise HTTPException(409, "A Claude login is already in progress. Complete or cancel it first.")

    cli = _sh.which("claude")
    if not cli:
        raise HTTPException(400, "claude CLI not found in PATH.")
    try:
        popen_kwargs = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
        if _sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        proc = subprocess.Popen([cli, "auth", "login"], **popen_kwargs)
    except Exception as e:
        raise HTTPException(500, f"Could not launch login: {str(e)[:200]}")

    _CLAUDE_LOGIN_STATE["proc"] = proc
    _CLAUDE_LOGIN_STATE["output"] = ""
    _CLAUDE_LOGIN_STATE["status"] = "running"
    _CLAUDE_LOGIN_STATE["url"] = None
    _CLAUDE_LOGIN_STATE["awaiting_code"] = False
    threading.Thread(target=_claude_login_reader, args=(proc,), daemon=True).start()
    return {"ok": True, "launched": True, "message": "Claude login started — waiting for the auth URL…"}


@router.get("/accounts/login/status")
def claude_login_status():
    """Polled by the Settings page while a headless `claude auth login`
    (started above) is in flight."""
    return {
        "status": _CLAUDE_LOGIN_STATE["status"],
        "url": _CLAUDE_LOGIN_STATE["url"],
        "awaiting_code": _CLAUDE_LOGIN_STATE["awaiting_code"],
        "output": _CLAUDE_LOGIN_STATE["output"][-4000:],
    }


class SubmitCodeRequest(BaseModel):
    code: str


@router.post("/accounts/login/submit-code")
def submit_claude_login_code(req: SubmitCodeRequest):
    """Feed a pasted-back auth code to the in-flight `claude auth login`
    process's stdin — only meaningful while awaiting_code is true."""
    proc = _CLAUDE_LOGIN_STATE.get("proc")
    if proc is None or proc.poll() is not None:
        raise HTTPException(400, "No Claude login is currently waiting for a code.")
    code = (req.code or "").strip()
    if not code:
        raise HTTPException(400, "Code is required.")
    try:
        proc.stdin.write(code + "\n")
        proc.stdin.flush()
    except Exception as e:
        raise HTTPException(500, f"Could not submit code: {str(e)[:200]}")
    _CLAUDE_LOGIN_STATE["awaiting_code"] = False
    return {"ok": True}


@router.post("/accounts/login/cancel")
def cancel_claude_login():
    """Kill an in-flight headless claude login."""
    proc = _CLAUDE_LOGIN_STATE.get("proc")
    if proc is not None and proc.poll() is None:
        proc.kill()
    _CLAUDE_LOGIN_STATE["status"] = "idle"
    _CLAUDE_LOGIN_STATE["proc"] = None
    _CLAUDE_LOGIN_STATE["awaiting_code"] = False
    return {"ok": True}


# ── Codex CLI account pool — same shape as the Claude pool above ────────────

@router.get("/codex-accounts")
def list_codex_accounts():
    """List pooled Codex accounts, which is live, and whether each token is
    still valid. Mirrors list_accounts() above exactly."""
    CODEX_ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    live_fp = _codex_fp(CODEX_LIVE_AUTH) if CODEX_LIVE_AUTH.exists() else ""
    accounts = []
    for f in sorted(CODEX_ACCOUNTS_DIR.glob("*.json")):
        fp = _codex_fp(f)
        accounts.append({
            "name": f.stem,
            "fingerprint": fp,
            "is_live": bool(fp) and fp == live_fp,
            "expired": _codex_token_expired(f),
        })
    return {
        "accounts": accounts,
        "live_fingerprint": live_fp,
        "logged_in": CODEX_LIVE_AUTH.exists(),
    }


@router.post("/codex-accounts/add")
def add_codex_account(req: AddAccountRequest):
    """Snapshot the CURRENT logged-in Codex account (~/.codex/auth.json) into
    the pool. Flow: `codex login` to an account in a terminal, click Add
    Account, repeat for each account you want in the rotation. Mirrors
    add_account() above exactly."""
    if not CODEX_LIVE_AUTH.exists():
        raise HTTPException(400, "No Codex login found. Run `codex login` in a terminal first.")
    fp = _codex_fp(CODEX_LIVE_AUTH)
    if not fp:
        raise HTTPException(400, "Current auth.json is not a valid Codex login.")
    CODEX_ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    for f in CODEX_ACCOUNTS_DIR.glob("*.json"):
        if _codex_fp(f) == fp:
            return {"ok": True, "already_pooled": True, "name": f.stem}
    label = (req.label or f"account_{int(time.time())}").strip().replace(" ", "_")
    label = "".join(c for c in label if c.isalnum() or c in "_-") or f"account_{int(time.time())}"
    dest = CODEX_ACCOUNTS_DIR / f"{label}.json"
    try:
        shutil.copy2(CODEX_LIVE_AUTH, dest)
    except Exception as e:
        raise HTTPException(500, f"Failed to copy Codex auth: {str(e)}")
    return {"ok": True, "name": label, "fingerprint": fp}


@router.post("/codex-accounts/remove/{name}")
def remove_codex_account(name: str):
    try:
        f = _safe_join(CODEX_ACCOUNTS_DIR, f"{name}.json")
    except ValueError:
        raise HTTPException(400, "Invalid account name")
    if f.exists():
        f.unlink()
    return {"ok": True}


@router.post("/codex-accounts/use/{name}")
def use_codex_account(name: str):
    """Manually switch the live Codex login to a specific pooled account."""
    try:
        f = _safe_join(CODEX_ACCOUNTS_DIR, f"{name}.json")
    except ValueError:
        raise HTTPException(400, "Invalid account name")
    if not f.exists():
        raise HTTPException(404, f"Account '{name}' not in pool")
    CODEX_LIVE_AUTH.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(f, CODEX_LIVE_AUTH)
    except Exception as e:
        raise HTTPException(500, f"Failed to switch account: {str(e)}")
    return {"ok": True, "now_live": name, "fingerprint": _codex_fp(f)}


# ── Codex login, run headless (no terminal window) ──────────────────────────
# Unlike Claude's `/login` (a slash-command that only works inside Claude's
# own interactive session — confirmed live: piping input to `claude` gives
# "/login isn't available in this environment"), `codex login` is a normal
# one-shot CLI command: it starts a local OAuth callback server, prints the
# auth URL to stdout, tries to open the user's browser itself, and exits
# 0/prints "Successfully logged in" once the browser flow completes. That
# means it can run as a plain background subprocess with no visible console —
# this module just needs to capture its stdout (for the auth URL, as a
# fallback if the browser didn't auto-open) and watch for it to finish.
#
# One login flow at a time — a module-level dict, not per-session state,
# since Settings is a singleton page and only one `codex login` should ever
# be in flight. Read/written only from the request thread and the one reader
# thread below; no lock needed since each field is only ever touched by one
# side at a time (reader thread writes output/status, main thread only reads
# them once started, or writes fresh state before starting a new one).
_CODEX_LOGIN_STATE = {"proc": None, "output": "", "status": "idle", "url": None}


def _codex_login_reader(proc):
    """Runs in a background thread: streams the child's stdout into
    _CODEX_LOGIN_STATE so /codex-accounts/login/status can report progress
    without ever blocking on the subprocess itself."""
    import re as _re
    url_re = _re.compile(r'https://\S+')
    try:
        for line in proc.stdout:
            _CODEX_LOGIN_STATE["output"] += line
            if _CODEX_LOGIN_STATE["url"] is None:
                m = url_re.search(line)
                if m:
                    _CODEX_LOGIN_STATE["url"] = m.group(0)
        proc.wait()
        out = _CODEX_LOGIN_STATE["output"]
        if proc.returncode == 0 and "success" in out.lower():
            _CODEX_LOGIN_STATE["status"] = "success"
        else:
            _CODEX_LOGIN_STATE["status"] = "failed"
    except Exception as e:
        _CODEX_LOGIN_STATE["status"] = "failed"
        _CODEX_LOGIN_STATE["output"] += f"\n[reader error] {e}"


@router.post("/codex-accounts/login")
def launch_codex_login():
    """Start `codex login` as a hidden background process (no terminal
    window) and return immediately. The frontend polls
    /codex-accounts/login/status for the auth URL and completion —
    same OAuth flow as before, just without a visible console."""
    import subprocess, shutil as _sh, sys as _sys, threading

    old = _CODEX_LOGIN_STATE.get("proc")
    if old is not None and old.poll() is None:
        raise HTTPException(409, "A Codex login is already in progress. Complete or cancel it first.")

    cli = _sh.which("codex")
    if not cli:
        raise HTTPException(400, "codex CLI not found in PATH.")
    try:
        popen_kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)
        if _sys.platform == "win32":
            # CREATE_NO_WINDOW — no console flash at all, unlike the old
            # `cmd /c start` approach which always popped a visible window.
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        proc = subprocess.Popen([cli, "login"], **popen_kwargs)
    except Exception as e:
        raise HTTPException(500, f"Could not launch login: {str(e)[:200]}")

    _CODEX_LOGIN_STATE["proc"] = proc
    _CODEX_LOGIN_STATE["output"] = ""
    _CODEX_LOGIN_STATE["status"] = "running"
    _CODEX_LOGIN_STATE["url"] = None
    threading.Thread(target=_codex_login_reader, args=(proc,), daemon=True).start()
    return {"ok": True, "launched": True, "message": "Codex login started — waiting for the auth URL…"}


@router.get("/codex-accounts/login/status")
def codex_login_status():
    """Polled by the Settings page while a headless `codex login` (started
    above) is in flight — reports the auth URL as soon as it's parsed from
    the CLI's own stdout, and the final success/failure once the browser
    flow completes and the process exits."""
    return {
        "status": _CODEX_LOGIN_STATE["status"],
        "url": _CODEX_LOGIN_STATE["url"],
        "output": _CODEX_LOGIN_STATE["output"][-4000:],   # tail only — a stuck/looping CLI shouldn't grow this unbounded in the response
    }


@router.post("/codex-accounts/login/cancel")
def cancel_codex_login():
    """Kill an in-flight headless codex login (e.g. the user closed the
    browser tab without finishing, or wants to abandon and retry)."""
    proc = _CODEX_LOGIN_STATE.get("proc")
    if proc is not None and proc.poll() is None:
        proc.kill()
    _CODEX_LOGIN_STATE["status"] = "idle"
    _CODEX_LOGIN_STATE["proc"] = None
    return {"ok": True}


# Corpus Builder — add novels + run the extraction pipeline