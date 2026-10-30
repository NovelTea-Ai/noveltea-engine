"""System / network info for the NovelTea Engine launcher.
Exposes the port and corpus path for the boot screen. It never looks up or reports IP addresses or the machine name."""
import os
import sys
import json
import subprocess
import threading
import time
from pathlib import Path
from fastapi import APIRouter
from config import CORPUS_PATH

router = APIRouter()

PORT = 7432


def _count(path: Path, key: str = None):
    if not path.exists():
        return 0
    try:
        import json as _json
        d = _json.load(open(path, encoding="utf-8"))
        if isinstance(d, list):
            return len(d)
        if isinstance(d, dict):
            return len(d.get(key, [])) if key else len(d)
    except Exception:
        return 0
    return 0


@router.get("/brain")
def brain_graph():
    """Corpus data points for the interactive brain graphic: per-novel metrics
    (chapters, psych, reveals, prose, schemes, arcs, genome)."""
    import json as _json
    novels_dir = Path(CORPUS_PATH) / "novels"
    raw_dir = Path(CORPUS_PATH) / "raw"
    nodes = []
    totals = {"chapters": 0, "psych": 0, "reveals": 0, "prose": 0, "schemes": 0, "arcs": 0, "genomes": 0}
    if novels_dir.exists():
        for d in sorted(novels_dir.iterdir()):
            if not d.is_dir():
                continue
            deltas = len(list((d / "deltas_v3").glob("ch*.json"))) if (d / "deltas_v3").exists() else 0
            raw = raw_dir / d.name
            raw_ch = len(list(raw.glob("ch*.txt"))) if raw.exists() else 0
            psych = _count(d / "reader_psychology" / "chapters.json")
            reveals = _count(d / "reveals" / "log.json")
            prose = _count(d / "prose" / "samples.json")
            schemes = _count(d / "schemes" / "instances.json")
            arcs = _count(d / "timeline" / "arcs.json")
            gfile = d / "narrative_genome.json"
            gver, gpat = None, 0
            if gfile.exists():
                try:
                    g = _json.load(open(gfile, encoding="utf-8"))
                    gver = g.get("schema_version")
                    gpat = len(g.get("patterns", []))
                except Exception:
                    pass
            node = {
                "id": d.name,
                "chapters": deltas or raw_ch,
                "psych": psych, "reveals": reveals, "prose": prose,
                "schemes": schemes, "arcs": arcs,
                "genome_version": gver, "genome_patterns": gpat,
                "has_genome": gfile.exists(),
            }
            nodes.append(node)
            totals["chapters"] += node["chapters"]
            totals["psych"] += psych
            totals["reveals"] += reveals
            totals["prose"] += prose
            totals["schemes"] += schemes
            totals["arcs"] += arcs
            totals["genomes"] += 1 if gfile.exists() else 0
    return {"ok": True, "nodes": nodes, "totals": totals, "novel_count": len(nodes)}


@router.get("/info")
def system_info():
    return {
        "ok": True,
        "app": "NovelTea Engine",
        "port": PORT,
        "urls": {"local": f"http://localhost:{PORT}"},
        "corpus_path": str(CORPUS_PATH),
        "corpus_exists": Path(CORPUS_PATH).exists(),
    }


RESTART_HELPER_PS1 = r'''# NovelTea Engine restart helper - written and started by the app's Restart Server button.
# It is its own process, so it outlives the app: wait for the app to close, check that it really
# closed, start it again, check that it answers, then exit (the helper closes itself).
param(
    [string]$ParentPids,
    [string]$Exe,
    [string]$ArgsJson = '[]',
    [string]$WorkDir,
    [int]$Port = 7432,
    [string]$Log
)
$ErrorActionPreference = 'Continue'
function Say([string]$m) {
    try { Add-Content -Path $Log -Value ('[{0}] {1}' -f (Get-Date).ToString('HH:mm:ss'), $m) -Encoding UTF8 } catch {}
}
function Alive([int]$p) { return [bool](Get-Process -Id $p -ErrorAction SilentlyContinue) }
function PortOpen {
    try {
        $c = New-Object Net.Sockets.TcpClient
        $r = $c.BeginConnect('127.0.0.1', $Port, $null, $null)
        $ok = $r.AsyncWaitHandle.WaitOne(500) -and $c.Connected
        $c.Close()
        return $ok
    } catch { return $false }
}

$pids = @($ParentPids -split ',' | Where-Object { $_ } | ForEach-Object { [int]$_ })
Say ("restart helper started (pid {0}); waiting for the app to close: {1}" -f $PID, ($pids -join ', '))

# 1. wait until every app process is gone (a one-file exe is two processes); end any that linger
$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline -and @($pids | Where-Object { Alive $_ }).Count) { Start-Sleep -Milliseconds 300 }
$left = @($pids | Where-Object { Alive $_ })
if ($left.Count) {
    Say ("still running after 30s, ending: {0}" -f ($left -join ', '))
    $left | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}
Say 'the app is closed'

# 2. wait for its port to be released
$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline -and (PortOpen)) { Start-Sleep -Milliseconds 500 }
if (PortOpen) { Say ("port {0} is still in use - launching anyway" -f $Port) } else { Say ("port {0} is free" -f $Port) }

# 3. relaunch as a fresh instance (not as a child of the one that just closed), check, retry
Get-ChildItem env: | Where-Object { $_.Name -like '_PYI*' -or $_.Name -like '_MEI*' } | ForEach-Object { Remove-Item ("env:" + $_.Name) }
$env:PYINSTALLER_RESET_ENVIRONMENT = '1'
$exeArgs = @()
try {
    # keep only real strings: ConvertFrom-Json '[]' leaves a blank item that Start-Process rejects
    $parsed = ConvertFrom-Json -InputObject $ArgsJson
    foreach ($a in $parsed) { if ($a -is [string] -and $a) { $exeArgs += $a } }
} catch {}
$procName = [IO.Path]::GetFileNameWithoutExtension($Exe)
$isApp = $procName -notlike 'python*'
$up = $false
for ($attempt = 1; $attempt -le 3 -and -not $up; $attempt++) {
    Say ("launching the app (attempt {0})" -f $attempt)
    try {
        if ($exeArgs.Count) { Start-Process -FilePath $Exe -ArgumentList $exeArgs -WorkingDirectory $WorkDir -WindowStyle Hidden }
        else { Start-Process -FilePath $Exe -WorkingDirectory $WorkDir -WindowStyle Hidden }
    } catch { Say ("launch failed: {0}" -f $_.Exception.Message) }
    $deadline = (Get-Date).AddSeconds(120)
    $goneSince = $null
    while ((Get-Date) -lt $deadline -and -not $up) {
        Start-Sleep -Seconds 1
        try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 ("http://127.0.0.1:{0}/api/health" -f $Port) | Out-Null; $up = $true } catch {}
        if (-not $up -and $isApp) {
            # the app opened and then closed again (crashed on startup): don't wait out the whole timeout
            if (Get-Process -Name $procName -ErrorAction SilentlyContinue) { $goneSince = $null }
            elseif (-not $goneSince) { $goneSince = Get-Date }
            elseif (((Get-Date) - $goneSince).TotalSeconds -gt 15) { Say 'the app is not running - relaunching'; break }
        }
    }
}
if ($up) { Say 'the app is back up - helper closing' } else { Say 'GAVE UP: the app did not come back after 3 attempts' }
exit 0
'''


def _spawn_restart_helper() -> bool:
    """Start the restart helper as its OWN process (a small PowerShell script) that outlives this
    one. The old way — this process launching a copy of itself and then exiting — started the new
    instance while the old one was still shutting down and never checked that it came up. The
    helper waits for this app to be fully gone, relaunches it, waits for /api/health, and exits."""
    home = Path.home() / ".noveltea-engine"
    home.mkdir(parents=True, exist_ok=True)
    script, log = home / "restart_helper.ps1", home / "restart.log"
    script.write_text(RESTART_HELPER_PS1, encoding="utf-8-sig")   # BOM: PowerShell 5.1 reads UTF-8 right

    pids = [os.getpid()]
    try:   # a one-file exe is a bootloader process plus the real one — both must be gone first
        import psutil
        parent = psutil.Process().parent()
        if parent is not None and parent.pid != os.getpid() and \
                os.path.normcase(parent.exe() or "") == os.path.normcase(sys.executable):
            pids.append(parent.pid)
    except Exception:
        pass

    if getattr(sys, "frozen", False):
        exe, exe_args, workdir = sys.executable, [], str(Path(sys.executable).parent)
    else:   # dev mode: run `python main.py` the way it was started
        exe, exe_args, workdir = sys.executable, list(sys.argv), str(Path(__file__).parent.parent.parent)

    args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
            "-ParentPids", ",".join(str(p) for p in pids), "-Exe", exe,
            "-ArgsJson", json.dumps(exe_args), "-WorkDir", workdir, "-Port", str(PORT), "-Log", str(log)]
    env = {k: v for k, v in os.environ.items() if not k.startswith(("_PYI", "_MEI"))}
    log.write_text("", encoding="utf-8")
    # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP (+ breakaway from this app's job if allowed).
    # Not DETACHED_PROCESS: PowerShell started that way with a closed stdin exits without running.
    flags = 0x08000000 | 0x00000200
    kw = dict(env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
              close_fds=True)
    try:
        subprocess.Popen(args, creationflags=flags | 0x01000000, **kw)
    except OSError:
        subprocess.Popen(args, creationflags=flags, **kw)
    return True


def _do_restart():
    """Restart: hand over to the helper process, then exit this one. Runs in a background thread
    with a short delay so the HTTP response for the /restart request can actually reach the client
    before the process dies — an immediate exit would drop the in-flight response and read as a
    crash instead of a deliberate restart."""
    time.sleep(0.6)
    try:
        if _spawn_restart_helper():
            os._exit(0)   # the helper takes it from here
    except Exception:
        pass   # helper couldn't start — fall back to the old direct relaunch below
    try:
        if getattr(sys, "frozen", False):
            # Packaged exe: relaunch the same .exe file, detached from this
            # process so it survives our exit. No console window (matches
            # how the exe is normally started).
            exe = sys.executable
            creationflags = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW
            subprocess.Popen([exe], cwd=str(Path(exe).parent), creationflags=creationflags,
                             close_fds=True)
        else:
            # Dev mode: relaunch `python main.py` the same way it was started.
            creationflags = 0x00000008 | 0x08000000
            subprocess.Popen([sys.executable] + sys.argv, cwd=str(Path(__file__).parent.parent.parent),
                             creationflags=creationflags, close_fds=True)
    except Exception:
        pass  # if spawning the replacement fails, still exit below rather than hang forever
    os._exit(0)   # hard exit — uvicorn has no clean async shutdown path reachable from here


@router.post("/restart")
def restart_server():
    """Restart the whole app process (used by Settings > Restart Server).
    Spawns a fresh instance bound to the same port, then this process exits —
    the frontend should poll /api/health afterward and reload once it's back."""
    threading.Thread(target=_do_restart, daemon=True).start()
    return {"ok": True, "message": "Restarting…", "pid": os.getpid()}
