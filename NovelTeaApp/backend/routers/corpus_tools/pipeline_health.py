"""
Pipeline health — what a card's ⟳ does beyond recounting: find out WHY a job is stuck, repair what is safe to repair, and
say plainly what is left for the author.

A job that "starts, closes and stays on the same percentage" has one of a few causes, each told apart here from the job's
own log (the launcher overwrites <job>.log / <job>.err.log on every start, so they always hold the last run):
  - the engine refused it (rate limit 429, a usage / weekly limit, a credit or key problem): the job skips what it could
    not do and exits, so the bar does not move. A tiny test call to the engine in use says whether it answers NOW.
  - the card and the job disagree about what is pending (the job's own worklist is stale): "nothing to do", yet the bar is
    not full. Repaired here, free.
  - it crashed (a traceback in the error log).
  - it is running but nothing has moved for a long time (stalled).
  - it simply has work left and was never started again.
Free repairs are applied during the check; anything that costs engine time or needs a choice (switch engine, start) is
offered as an action button, never done unasked.
"""
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

_LIMIT = re.compile(r"\b429\b|rate.?limit|too many requests|usage limit|weekly limit|hit your limit|limit reached|quota|"
                    r"credit balance|overloaded|insufficient", re.I)
_AUTH = re.compile(r"\b401\b|\b403\b|unauthori[sz]ed|invalid[^.\n]{0,20}api key|no api key|api key[^.\n]{0,20}(missing|not set)", re.I)
_NOTHING = re.compile(r"nothing to (classify|do|index|build|check)|checking 0 |\b0 chapter\(s\)|0 new chunk|no candidates", re.I)
_DONE = re.compile(r"^\s*DONE\b|\ball done\b|complete\.?\s*$", re.I | re.M)
_RESETS = re.compile(r"resets?\s+([A-Za-z]{3,9})\s+(\d{1,2})(?:,\s*(\d{1,2})(?::(\d\d))?\s*([ap]m))?", re.I)
_PROGRESS = re.compile(r"\[(\d+)/(\d+)\][^\n]*\((\d+)s\)")
_MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

STALL_MIN = 25          # running, but no log line and no live update for this long
_PROBE_CACHE: dict = {}
_PROBE_TTL = 90


def _tail(path: Path, n: int = 120) -> tuple:
    """(last n lines, mtime) of a log; ([], 0) when absent. Logs are cmd-redirected, so decode leniently."""
    try:
        raw = path.read_bytes()[-60000:]
        return raw.decode("utf-8", errors="replace").splitlines()[-n:], path.stat().st_mtime
    except Exception:
        return [], 0


def _first_line(path: Path) -> str:
    try:
        with open(path, "rb") as f:
            return f.readline(600).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _reset_passed(line: str) -> Optional[bool]:
    """True/False when the limit message names a reset time ('resets Oct 5, 3pm') that is past / still ahead; None if unclear."""
    m = _RESETS.search(line or "")
    if not m or m.group(1)[:3].lower() not in _MONTHS:
        return None
    try:
        hour = int(m.group(3) or 0) % 12 + (12 if (m.group(5) or "").lower() == "pm" else 0)
        t = time.mktime((time.localtime().tm_year, _MONTHS[m.group(1)[:3].lower()], int(m.group(2)), hour, int(m.group(4) or 0), 0, 0, 0, -1))
        return t < time.time()
    except Exception:
        return None


def _probe_engine(corpus: Path) -> dict:
    """One tiny call to the engine the jobs use right now: does it answer? Cached ~90 s; never blocks longer than 40 s."""
    c = _PROBE_CACHE.get("probe")
    if c and time.time() - c["at"] < _PROBE_TTL:
        return c["res"]
    res = {"ok": False, "engine": "?", "why": "not tested"}
    try:
        if str(corpus) not in sys.path:
            sys.path.insert(0, str(corpus))
        import llm_client as L
        res["engine"] = L.current_model_label()
        out: dict = {}

        def call():
            try:
                out["text"] = L.call_llm(system="Reply with the single word OK.", user="ping", max_tokens=16, temperature=0)
            except Exception as e:
                out["err"] = str(e)
        t = threading.Thread(target=call, daemon=True)
        t.start()
        t.join(40)
        if t.is_alive():
            res.update(ok=False, why="no answer within 40 s (the engine is busy or retrying)")
        elif "err" in out:
            res.update(ok=False, why=out["err"][:220], limited=bool(_LIMIT.search(out["err"])))
        else:
            res.update(ok=True, why="answered")
    except Exception as e:
        res.update(ok=False, why=f"could not test the engine: {str(e)[:160]}")
    _PROBE_CACHE["probe"] = {"at": time.time(), "res": res}
    return res


def _eta(out_lines: list, first: str) -> Optional[str]:
    """'~5 h left' from the run's own '[k/N] ... built (123s)' lines (jobs that print them) and its worker count."""
    hits = [m for m in (_PROGRESS.search(l) for l in out_lines) if m]
    if len(hits) < 4:
        return None
    k, n = int(hits[-1].group(1)), int(hits[-1].group(2))
    secs = [int(m.group(3)) for m in hits[-12:]]
    w = re.search(r"(\d+) worker", first or "")
    workers = int(w.group(1)) if w else 1
    left = max(0, n - k) * (sum(secs) / len(secs)) / max(1, workers)
    return f"about {left / 3600:.1f} h" if left >= 5400 else f"about {max(1, round(left / 60))} min"


def _newer(path: Path, than: float) -> bool:
    try:
        return path.stat().st_mtime > than
    except Exception:
        return False


def _script_changed_since(job_key: str, corpus: Path, when: float) -> bool:
    """True when the job's own script file was edited after `when` (the time of its last log write)."""
    try:
        from routers.corpus_tools.corpus import _PIPELINE_JOBS
        script = _PIPELINE_JOBS[job_key]["script"]
    except Exception:
        return False
    return bool(when) and _newer(corpus / script, when)


def _f(level: str, text: str, action: Optional[dict] = None, fixed: bool = False) -> dict:
    return {"level": level, "text": text, "action": action, "fixed": fixed}


def _run_py(corpus: Path, script: str, *args, timeout: int = 90) -> tuple:
    exe = __import__("shutil").which("python") or sys.executable
    try:
        r = subprocess.run([exe, script, *args], cwd=str(corpus), capture_output=True, text=True, timeout=timeout,
                           creationflags=0x08000000 if sys.platform == "win32" else 0)
        return r.returncode == 0, (r.stdout or r.stderr or "").strip()
    except Exception as e:
        return False, str(e)


def repair_worklists(job_key: str, running: bool, corpus: Path) -> list:
    """Free repair, run BEFORE the card is counted (its counts depend on it): rebuild the Empty-field Check / Delta Upgrade
    worklists from the registry's per-chapter records when they have drifted. Skipped while the job runs (it is reading them)."""
    if running or job_key not in ("empty_check", "delta_upgrade"):
        return []
    ok, msg = _run_py(corpus, "delta_audit.py", "--refresh-candidates")
    if not ok:
        return [_f("warn", f"Could not rebuild the job's worklist: {msg[:160]}")]
    try:
        a, b = json.loads(msg.splitlines()[-1])["resolve" if job_key == "empty_check" else "upgrade"]
    except Exception:
        return []
    if a == b:
        return []
    return [_f("info", f"The job's own worklist was out of date ({a} chapters listed, {b} now qualify) — rebuilt from the current chapter "
                       "records. A stale list is why a job can say 'nothing to do', close at once and leave the bar where it was.", fixed=True)]


def diagnose(job_key: str, label: str, entry: dict, running: bool, live: Optional[dict], corpus: Path, fix: bool = True,
             pre: Optional[list] = None) -> dict:
    """The health report for one job card. entry = the card's freshly counted values (done / total / novels)."""
    done, total = entry.get("done", 0), entry.get("total", 0)
    left = max(0, total - done)
    out_lines, out_m = _tail(corpus / f"{job_key}.log")
    err_lines, err_m = _tail(corpus / f"{job_key}.err.log")
    first = _first_line(corpus / f"{job_key}.log")
    finds: list = []
    now = time.time()
    live_ts = 0
    try:
        live_ts = time.mktime(time.strptime((live or {}).get("ts", ""), "%Y-%m-%d %H:%M:%S"))
    except Exception:
        pass
    last_move = max(out_m, err_m, live_ts)
    text_out, text_err = "\n".join(out_lines), "\n".join(err_lines)
    limit_lines = [l for l in out_lines + err_lines if _LIMIT.search(l)]
    crash = "Traceback" in text_err or bool(re.search(r"^\w*(Error|Exception):", text_err, re.M))
    verdict, level = "", "ok"

    finds.extend(pre or [])

    if total and done >= total and not running:
        verdict, level = "Complete — nothing left to do", "ok"
    elif running:
        idle = (now - last_move) / 60 if last_move else 0
        waits = [l for l in out_lines[-40:] if re.search(r"waiting \d+s|rotating pool", l)]
        if idle > STALL_MIN:
            verdict, level = f"Looks stalled — no activity for {int(idle)} min", "error"
            finds.append(_f("error", f"Running, but its log and live status have not changed for {int(idle)} minutes. Restart it.",
                            {"id": "restart", "label": "↻ Restart"}))
        else:
            verdict, level = "Working" + (" (waiting on the engine's rate limit)" if waits else ""), "working"
            eta = _eta(out_lines, first)
            if waits:
                finds.append(_f("info", "The engine keeps answering 'too many requests'; each call waits and retries by itself, so the job "
                                "still moves, just slowly." + (f" Estimated {eta} to finish." if eta else "") +
                                " Switching the engine in the top bar speeds it up."))
            elif eta:
                finds.append(_f("info", f"Estimated {eta} to finish."))
    else:
        # stopped with work left: why did the last run end?
        if crash and _script_changed_since(job_key, corpus, err_m):
            # the error log is the LAST run's, and it keeps saying "crashed" until the job runs again - even after the script was fixed
            lastline = next((l for l in reversed(err_lines) if l.strip()), "")
            verdict, level = "Ready - fixed since its last crash", "warn"
            finds.append(_f("warn", f"The last run crashed ({lastline[:120]}), but the script has been changed since then, so that error "
                            f"is out of date. Start it to finish the {left:,} left.", {"id": "restart", "label": f"▶ Start ({left:,} left)"}))
        elif crash:
            lastline = next((l for l in reversed(err_lines) if l.strip()), "")
            verdict, level = "Crashed on its last run", "error"
            finds.append(_f("error", f"The last run crashed: {lastline[:200]}", {"id": "restart", "label": "▶ Start again"}))
        elif limit_lines:
            ev = limit_lines[-1].strip()
            passed = _reset_passed(ev)
            probe = _probe_engine(corpus) if fix else None
            if probe and probe["ok"]:
                verdict, level = "Ready — the engine answers again", "warn"
                finds.append(_f("warn", f"The last run stopped on an engine limit ({ev[:110]}…), but {probe['engine']} answers a test call now"
                                + (" (that limit has reset)" if passed else "") + f". Start will finish the {left:,} left.",
                                {"id": "restart", "label": f"▶ Start ({left:,} left)"}))
            elif probe:
                verdict, level = f"Engine limited — {probe['engine']}", "error"
                finds.append(_f("error", f"{probe['engine']} refuses a test call right now: {probe['why']}. Every start would hit the same wall "
                                "and close with the bar unmoved. Switch the engine in the top bar (or wait for the limit to reset), then Start.",
                                {"id": "restart", "label": "▶ Start after switching"}))
            else:
                verdict, level = "Last run stopped on an engine limit", "warn"
                finds.append(_f("warn", f"Last run: {ev[:160]}"))
        elif _AUTH.search(text_out + text_err):
            verdict, level = "Engine key problem", "error"
            finds.append(_f("error", "The last run was refused for a key / permission reason: "
                            + next((l.strip() for l in (out_lines + err_lines) if _AUTH.search(l)), "")[:160]))
        elif _NOTHING.search(text_out) and left and job_key in ("empty_check", "delta_upgrade") and _newer(corpus / "delta_quality.json", out_m):
            # the 'nothing to do' came from a run that predates the current worklist (rebuilt since): it is evidence of the old list
            verdict, level = f"Ready — {left:,} chapter(s) are on the job's list now", "warn"
            finds.append(_f("warn", "The last run found nothing to do, but that was before the worklist was rebuilt. The job will pick up "
                            f"the {left:,} remaining chapter(s) now.", {"id": "restart", "label": f"▶ Start ({left:,} left)"}))
        elif _NOTHING.search(text_out) and left:
            verdict, level = "Counts disagree with the job", "warn"
            finds.append(_f("warn", f"The card counts {left:,} left, but the job found nothing it was allowed to do. Its own selection rules "
                            "exclude them (or they cannot be processed); they will keep the bar below 100% until they are excluded from the count."))
        elif left:
            verdict, level = f"Stopped with {left:,} left", "warn"
            finds.append(_f("warn", f"Not running, {left:,} items to go" + (", last run ended normally" if _DONE.search(text_out) else "") + ".",
                            {"id": "restart", "label": f"▶ Start ({left:,} left)"}))
        else:
            verdict, level = "Idle", "ok"
        if (not out_lines) and (not err_lines) and left:
            finds.append(_f("info", "No log from a previous run — it has not been started since the log was cleared."))
    if job_key == "delta_upgrade":
        try:
            st = json.loads((corpus / "upgrade_deltas_state.json").read_text(encoding="utf-8"))
            failed = {f"{nv} ch{ch}": why for nv, s in st.items() for ch, why in (s.get("failed") or {}).items()}
            if failed and not running:
                finds.append(_f("info", f"{len(failed)} chapter(s) failed on an earlier run and are retried next time: "
                                + ", ".join(list(failed)[:5]) + ("…" if len(failed) > 5 else "") + "."))
        except Exception:
            pass
    return {"verdict": verdict, "level": level, "findings": finds, "checked_at": now}
