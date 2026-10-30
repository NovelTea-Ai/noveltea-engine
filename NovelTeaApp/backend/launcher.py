"""NovelTea Engine single-file launcher.

Starts the FastAPI backend (which also serves the built React UI), prints a banner, and opens
the browser. Packaged into one .exe with PyInstaller.

Run:  NovelTeaEngine.exe          (does NOT open a browser — the app's own
                                  window/webui, or a device on the LAN, is
                                  how it's normally used; auto-opening a
                                  desktop Chrome tab on every relaunch was
                                  confirmed unwanted, asked to be closed
                                  repeatedly during a dev session)
      NovelTeaEngine.exe --browser  (opt back in to the old auto-open behavior)
"""
import os
import sys
import time
import threading
import webbrowser
import urllib.request
from pathlib import Path

PORT = 7432

# Ensure UTF-8 console output on Windows (box-drawing chars in the banner)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def _wait_online(timeout=25):
    url = f"http://127.0.0.1:{PORT}/api/health"
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def _banner():
    bar = "=" * 58
    lines = [
        "",
        "  " + bar,
        "     ✦  N O V E L M I N D . A I",
        "        Novel Creation Engine",
        "  " + bar,
        f"     Local : http://localhost:{PORT}",
        "  " + bar,
        "",
        "  This app listens on this computer only (set NOVELTEA_HOST to change that; see the README).",
        "  Press Ctrl+C to stop.",
        "",
    ]
    out = "\n".join(lines)
    try:
        print(out)
    except Exception:
        # Absolute fallback: strip non-ASCII
        print(out.encode("ascii", "replace").decode())


def _silence_proactor_connection_reset_spam():
    """Windows' asyncio ProactorEventLoop logs a full traceback every time a
    client (a closed browser tab, a page refresh, a dropped progress-poll
    connection — all routine, not application bugs) resets a TCP connection
    before the transport finishes tearing it down. Harmless but floods the
    console with hundreds of identical
    'Exception in callback _ProactorBasePipeTransport._call_connection_lost'
    tracebacks over a normal session. Windows-only issue — SelectorEventLoop
    (Linux/Mac) doesn't have it, so this only patches on win32."""
    if sys.platform != "win32":
        return
    try:
        from asyncio.proactor_events import _ProactorBasePipeTransport
        orig = _ProactorBasePipeTransport._call_connection_lost

        def _quiet_call_connection_lost(self, exc):
            try:
                orig(self, exc)
            except ConnectionResetError:
                pass

        _ProactorBasePipeTransport._call_connection_lost = _quiet_call_connection_lost
    except Exception:
        pass  # best-effort — worst case the original noisy behaviour remains


def main():
    open_browser = "--browser" in sys.argv

    # Import the app after path setup so PyInstaller bundles it
    if getattr(sys, "frozen", False):
        # Bundled resources root
        os.chdir(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)))
    _silence_proactor_connection_reset_spam()
    import uvicorn
    from main import app  # noqa: E402

    # Start uvicorn in a background thread so we can print the banner + open browser
    config = uvicorn.Config(app, host=os.environ.get("NOVELTEA_HOST", "127.0.0.1"), port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()

    if _wait_online():
        _banner()
        if open_browser:
            webbrowser.open(f"http://localhost:{PORT}")
    else:
        print("  [!] Backend failed to start within timeout.")

    try:
        while t.is_alive():
            t.join(0.5)
    except KeyboardInterrupt:
        print("\n  Shutting down NovelTea Engine …")
        server.should_exit = True


if __name__ == "__main__":
    main()
