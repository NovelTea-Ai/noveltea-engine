"""Background jobs and phone notifications.

A long job (narrating a chapter, writing the next interview part) used to run inside one HTTP request that the
phone had to hold open for minutes. iOS cuts that connection as soon as you switch apps, so the phone reported a
failure while the PC carried on. Now the phone starts a job, gets its id back at once, and asks how it is going in
short calls; nothing is held open, so nothing is cut. When a job finishes, every phone that switched notifications
on gets a push notification (Web Push, from the app added to the Home Screen over HTTPS).

Jobs live in memory and in ~/.noveltea-engine/jobs/<id>.json, so a finished job's result can still be collected after
the phone comes back (or after the app restarts).
"""
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

_HOME = Path.home() / ".noveltea-engine"
_JOB_DIR = _HOME / "jobs"
_JOBS: dict = {}
_LOCK = threading.Lock()


# ── jobs ──────────────────────────────────────────────────────────────────────

def _save(job: dict):
    try:
        _JOB_DIR.mkdir(parents=True, exist_ok=True)
        (_JOB_DIR / f"{job['id']}.json").write_text(json.dumps(job, default=str), encoding="utf-8")
    except Exception:
        pass


def _load(job_id: str) -> Optional[dict]:
    with _LOCK:
        if job_id in _JOBS:
            return _JOBS[job_id]
    p = _JOB_DIR / f"{job_id}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _latest_progress(project_id: str, since: float) -> str:
    """The newest console line this project wrote since the job started (its live progress)."""
    try:
        from routers.generation.generate import _PROGRESS, _PROGRESS_LOCK
        with _PROGRESS_LOCK:
            entries = list(_PROGRESS.get(project_id, []))
        return entries[-1]["msg"] if entries else ""
    except Exception:
        return ""


def _start(kind: str, project_id: str, chapter: int, title: str, fn) -> dict:
    job = {"id": uuid.uuid4().hex[:16], "kind": kind, "project_id": project_id, "chapter": chapter,
           "title": title, "status": "running", "started": time.time(), "finished": None,
           "result": None, "error": None}
    with _LOCK:
        _JOBS[job["id"]] = job
    _save(job)

    def run():
        try:
            job["result"] = fn()
            job["status"] = "done"
        except HTTPException as e:
            job["status"] = "error"
            job["error"] = str(e.detail)[:500]
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e)[:500]
        job["finished"] = time.time()
        _save(job)
        try:
            _notify_job(job)
        except Exception:
            pass

    threading.Thread(target=run, daemon=True, name=f"job-{kind}-{job['id']}").start()
    return job


def _public(job: dict) -> dict:
    out = {k: job.get(k) for k in ("id", "kind", "project_id", "chapter", "title", "status", "started", "finished", "error")}
    out["elapsed"] = round((job.get("finished") or time.time()) - (job.get("started") or time.time()), 1)
    if job.get("status") == "running":
        out["progress"] = _latest_progress(job.get("project_id", ""), job.get("started") or 0)
    if job.get("status") == "done":
        out["result"] = job.get("result")
    return out


@router.post("/narrate")
def job_narrate(req: dict):
    """Start narrating a chapter in the background. Body: the same as /api/generate/narrate."""
    from routers.generation.generate import NarrateChapterRequest, narrate_chapter
    r = NarrateChapterRequest(**req)
    job = _start("narrate", r.project_id, r.chapter_number, f"Chapter {r.chapter_number} narration",
                 lambda: narrate_chapter(r))
    return _public(job)


@router.post("/chapter-interactive")
def job_chapter_interactive(req: dict):
    """Start the next interview step in the background. Body: the same as /api/generate/chapter-interactive."""
    from routers.generation.generate import InteractiveChapterRequest, chapter_interactive
    r = InteractiveChapterRequest(**req)
    job = _start("interview", r.project_id, r.chapter_number, f"Chapter {r.chapter_number} interview",
                 lambda: chapter_interactive(r))
    return _public(job)


@router.get("/{job_id}")
def job_status(job_id: str):
    job = _load(job_id)
    if not job:
        raise HTTPException(404, "No such job")
    return _public(job)


# ── push notifications ────────────────────────────────────────────────────────

_VAPID_FILE = _HOME / "vapid.json"
_SUBS_FILE = _HOME / "push_subscriptions.json"
_SUBS_LOCK = threading.Lock()


def _vapid() -> dict:
    """The server's push key pair, made once and kept in ~/.noveltea-engine/vapid.json (never sent anywhere but here)."""
    if _VAPID_FILE.exists():
        try:
            return json.loads(_VAPID_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    import base64
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    raw = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    pub = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    data = {"private_pem": pem, "public_key": pub}
    _HOME.mkdir(parents=True, exist_ok=True)
    _VAPID_FILE.write_text(json.dumps(data), encoding="utf-8")
    return data


def _subs() -> list:
    try:
        return json.loads(_SUBS_FILE.read_text(encoding="utf-8")) if _SUBS_FILE.exists() else []
    except Exception:
        return []


def _save_subs(subs: list):
    _HOME.mkdir(parents=True, exist_ok=True)
    _SUBS_FILE.write_text(json.dumps(subs), encoding="utf-8")


PHONE_HTTPS_PORT = 8443     # `tailscale serve --bg --https=8443 http://127.0.0.1:7432` puts the app on this port
_phone_url_cache: dict = {}


def phone_url() -> str:
    """The app's HTTPS address on the Tailscale network (what the phone opens and adds to its Home Screen)."""
    if "url" in _phone_url_cache:
        return _phone_url_cache["url"]
    import shutil
    import subprocess
    exe = shutil.which("tailscale") or r"C:\Program Files\Tailscale\tailscale.exe"
    url = ""
    try:
        out = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        dns = (json.loads(out.stdout).get("Self") or {}).get("DNSName", "").rstrip(".")
        if dns:
            url = f"https://{dns}:{PHONE_HTTPS_PORT}"
    except Exception:
        pass
    _phone_url_cache["url"] = url
    return url


@router.get("/push/key")
def push_key():
    return {"public_key": _vapid()["public_key"], "subscriptions": len(_subs()), "phone_url": phone_url()}


class PushSub(BaseModel):
    subscription: dict
    label: Optional[str] = None


@router.post("/push/subscribe")
def push_subscribe(req: PushSub):
    ep = (req.subscription or {}).get("endpoint")
    if not ep:
        raise HTTPException(400, "No endpoint in the subscription")
    with _SUBS_LOCK:
        subs = [s for s in _subs() if s.get("subscription", {}).get("endpoint") != ep]
        subs.append({"subscription": req.subscription, "label": req.label or "", "added": time.time()})
        _save_subs(subs)
    return {"ok": True, "subscriptions": len(subs)}


@router.post("/push/unsubscribe")
def push_unsubscribe(req: PushSub):
    ep = (req.subscription or {}).get("endpoint")
    with _SUBS_LOCK:
        subs = [s for s in _subs() if s.get("subscription", {}).get("endpoint") != ep]
        _save_subs(subs)
    return {"ok": True, "subscriptions": len(subs)}


def push_all(title: str, body: str, url: str = "/", tag: str = "noveltea") -> int:
    """Send a notification to every subscribed phone. Subscriptions the push service says are gone are dropped."""
    sent, _errors = _push_all(title, body, url, tag)
    return sent


def _push_contact() -> str:
    """The VAPID 'sub' contact. Apple rejects a mailto at localhost (BadJwtToken) and the library wants a bare https
    origin (no port), so it is this PC's own Tailscale name."""
    u = phone_url()
    host = u.split("//", 1)[-1].split(":", 1)[0].split("/", 1)[0] if u else ""
    return f"https://{host}" if host else "https://noveltea.invalid"


def _push_all(title: str, body: str, url: str, tag: str):
    from pywebpush import webpush, WebPushException
    from py_vapid import Vapid
    key = Vapid.from_pem(_vapid()["private_pem"].encode())     # the PEM string itself is not accepted as a key
    claims_sub = _push_contact()
    sent, keep, errors = 0, [], []
    with _SUBS_LOCK:
        subs = _subs()
    for s in subs:
        try:
            webpush(subscription_info=s["subscription"],
                    data=json.dumps({"title": title, "body": body, "url": url, "tag": tag}),
                    vapid_private_key=key, vapid_claims={"sub": claims_sub}, ttl=3600)
            sent += 1
            keep.append(s)
        except WebPushException as e:
            resp = getattr(e, "response", None)
            code = getattr(resp, "status_code", 0)
            errors.append(f"{code} {(getattr(resp, 'text', '') or str(e))[:120]}")
            if code not in (404, 410):          # 404/410: the phone unsubscribed; drop it
                keep.append(s)
        except Exception as e:
            errors.append(f"{type(e).__name__}: {str(e)[:120]}")
            keep.append(s)
    if len(keep) != len(subs):
        with _SUBS_LOCK:
            _save_subs(keep)
    return sent, errors


@router.post("/push/test")
def push_test():
    sent, errors = _push_all("NovelTea Engine", "Notifications are working.", "/", "noveltea-test")
    return {"ok": not errors, "sent": sent, "errors": errors}


def _notify_job(job: dict):
    secs = int((job.get("finished") or time.time()) - (job.get("started") or time.time()))
    took = f"{secs // 60}:{secs % 60:02d}"
    res = job.get("result") or {}
    if job["status"] == "error":
        title, body = f"{job['title']} failed", (job.get("error") or "")[:140]
    elif job["kind"] == "narrate":
        title, body = "Narration ready", f"Chapter {job['chapter']} narrated in {took}."
    elif res.get("done"):
        title, body = "Chapter written", f"Chapter {job['chapter']} is complete ({took})."
    elif res.get("in_flight"):
        return
    else:
        n = res.get("parts_so_far")
        title = f"Part {n} written" if n else "Interview ready"
        body = (res.get("question") or "Your choice is needed.")[:140]
    push_all(title, body, url="/", tag=f"noveltea-{job['kind']}-{job['chapter']}")
