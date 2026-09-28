"""Local control panel for Naukri Autopilot.

Python standard library only, no extra dependencies and no build step. Binds to
127.0.0.1 so it is reachable only from this machine.

  dashboard.bat                      start it and open the browser
  .venv\\Scripts\\python.exe server.py  start it manually (default port 8777)
"""
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from common import (
    ACTIONS,
    ACTION_KEYS,
    HEADLINE_MAX,
    HEADLINE_SLOTS,
    ROOT,
    RUN_LOG,
    SHOT_DIR,
    STATE_FILE,
    clean_headlines,
    clean_terms,
    list_resumes,
    load_config,
    load_history,
    resume_path,
    retry_unlink,
    save_config,
)
from windows_tasks import (
    autostart_on,
    autostart_set,
    schedule_info,
    schedule_install,
    schedule_uninstall,
)

WEB_DIR = ROOT / "web"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

PORT = int(os.getenv("DASHBOARD_PORT", "8777"))

# /settings still resolves, so an old bookmark lands on Configuration.
PAGES = ("/", "/captures", "/history", "/configuration", "/settings",
         "/guidelines", "/about")

RANGES = {"7d": 7, "1m": 30, "3m": 90}

# Only this machine's own dashboard may drive the API. The Host check stops DNS
# rebinding (a web page pointing its own domain at 127.0.0.1), and requiring a
# JSON content type on POST forces a CORS preflight that this server never
# approves, so no other site can trigger a run, a schedule change or a delete.
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
MAX_BODY = 64 * 1024

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'none'"
    ),
}

# Child processes get no console of their own, and their own process group so
# Stop can take the whole tree down.
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}


# --------------------------------------------------------------------------
# Job runner, one child process at a time, output buffered for polling
# --------------------------------------------------------------------------
class Job:
    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.kind = None
        self.lines = []
        self.exit_code = None
        self.started = None

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, kind, argv):
        with self.lock:
            if self.running:
                return False, "Something is already running."
            self.kind = kind
            self.lines = []
            self.exit_code = None
            self.started = time.time()
            # The child writes UTF-8 whatever the console code page says, and
            # is read back as UTF-8, so a headline or a file name with an
            # accent in it cannot end a run with a UnicodeDecodeError.
            env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
            self.proc = subprocess.Popen(
                argv, cwd=str(ROOT), stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, bufsize=1, env=env,
                text=True, encoding="utf-8", errors="replace",
                # Its own process group, so Stop can take down the whole tree
                # without touching the dashboard, and no console flashes up.
                creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
            )
        threading.Thread(target=self._pump, daemon=True).start()
        return True, None

    def _pump(self):
        proc = self.proc
        for line in proc.stdout:
            with self.lock:
                self.lines.append(line.rstrip("\n"))
                if len(self.lines) > 2000:      # keep the buffer bounded
                    del self.lines[:500]
        proc.wait()
        with self.lock:
            self.exit_code = proc.returncode

    def stop(self):
        """Kill the run and everything it started.

        terminate() on its own only ends the Python process. The browser it
        launched is a child of that, and Chromium spawns children of its own,
        so killing just the parent leaves a headed Chromium running with
        nothing driving it. taskkill /T walks the whole tree.
        """
        if not self.running:
            return False
        try:
            subprocess.run(
                ["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                capture_output=True, timeout=20,
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception:
            pass
        try:
            # Covers the case where taskkill is not available for some reason,
            # and reaps the process either way.
            self.proc.terminate()
            self.proc.wait(timeout=10)
        except Exception:
            pass
        return True

    def snapshot(self, since=0):
        with self.lock:
            return {
                "kind": self.kind,
                "running": self.running,
                "exitCode": self.exit_code,
                "startedAt": self.started,
                "total": len(self.lines),
                "lines": self.lines[since:],
            }


JOB = Job()


# --------------------------------------------------------------------------
# Status probes
# --------------------------------------------------------------------------
# autostart_on() and schedule_info() both read Task Scheduler directly, from
# windows_tasks. Nothing is cached, so the dashboard always shows what is
# really registered rather than what it last set.

TS = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"


def tail(path, n):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()[-n:]
    except FileNotFoundError:
        return []


def last_run_info():
    lines = tail(RUN_LOG, 4000)
    result = {"at": None, "status": "never", "detail": None,
              "headline": None, "resume": None}
    for line in reversed(lines):
        if ("RUN OK" in line or "RUN FAILED" in line
                or "Session expired" in line or "Access Denied page" in line):
            m = re.match(TS, line)
            result["at"] = m.group(1) if m else None
            if "RUN OK" in line:
                result["status"] = "ok"
                for key in ("headline", "resume"):
                    m2 = re.search(rf"{key}=(yes|no|skip)", line)
                    result[key] = m2.group(1) if m2 else "no"
                if any(v == "no" for v in (result["headline"], result["resume"])):
                    result["status"] = "partial"
            elif "Access Denied page" in line:
                result["status"] = "blocked"
            elif "Session expired" in line:
                result["status"] = "expired"
            else:
                result["status"] = "failed"
            result["detail"] = line.split("  ", 2)[-1].strip()
            break
    return result


def session_info():
    if not STATE_FILE.exists():
        return {"saved": False, "savedAt": None, "ageDays": None}
    ts = STATE_FILE.stat().st_mtime
    return {
        "saved": True,
        "savedAt": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M"),
        "ageDays": round((time.time() - ts) / 86400, 1),
    }


def build_status():
    sched = schedule_info()
    last = last_run_info()

    next_run = None
    if sched["installed"] and sched["hours"] and last["at"]:
        try:
            nxt = datetime.strptime(last["at"], "%Y-%m-%d %H:%M:%S") + timedelta(
                hours=sched["hours"])
            next_run = nxt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            pass

    cfg = load_config()
    try:
        pdf = resume_path(cfg)
        resume = {"name": pdf.name, "kb": round(pdf.stat().st_size / 1024)}
    except SystemExit as e:
        resume = {"name": None, "error": str(e)}
    if not cfg["actions"]["resume"]:
        resume["disabled"] = True

    return {
        "session": session_info(),
        "schedule": sched,
        "lastRun": last,
        # Onboarding's test run step: has any run on this PC ever worked.
        "everWorked": last["status"] in ("ok", "partial")
            or any(r.get("status") in ("ok", "partial") for r in load_history()),
        "nextRun": next_run,
        "resume": resume,
        "config": cfg,
        "actions": ACTIONS,
        "resumeChoices": [f.name for f in list_resumes()],
        "headlineMax": HEADLINE_MAX,
        "headlineSlots": HEADLINE_SLOTS,
        "autostart": autostart_on(),
        "job": JOB.snapshot(since=10**9),   # metadata only, no lines
    }


def screenshots():
    if not SHOT_DIR.exists():
        return []
    files = sorted(SHOT_DIR.glob("*.png"), key=lambda f: f.stat().st_mtime,
                   reverse=True)
    return [
        {
            "name": f.name,
            "at": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
            "failed": any(m in f.name for m in ("failed", "expired", "blocked")),
        }
        for f in files[:40]
    ]


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass  # runs.log is the real log

    def end_headers(self):
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        super().end_headers()

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def trusted(self, post=False):
        """Refuse anything that is not this dashboard talking to itself."""
        if self.headers.get("Host", "") not in ALLOWED_HOSTS:
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://{h}" for h in ALLOWED_HOSTS}:
            return False
        if post:
            ctype = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if ctype != "application/json":
                return False
        return True

    def send_file(self, path: Path):
        if not path.is_file():
            return self.send_json({"error": "not found"}, 404)
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type",
                         MIME.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if n <= 0 or n > MAX_BODY:
            return {}
        try:
            data = json.loads(self.rfile.read(n))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def do_GET(self):
        if not self.trusted():
            return self.send_json({"error": "forbidden"}, 403)
        u = urlparse(self.path)
        q = parse_qs(u.query)
        p = u.path

        def num(key, default, lo, hi):
            try:
                return max(lo, min(hi, int(q.get(key, [default])[0])))
            except ValueError:
                return default

        # Client-routed pages all serve the same shell, so a reload or deep
        # link on any of them lands somewhere real instead of a 404.
        if p in PAGES:
            return self.send_file(WEB_DIR / "index.html")
        if p in ("/app.js", "/styles.css", "/theme.js"):
            return self.send_file(WEB_DIR / p.lstrip("/"))
        if p == "/api/status":
            return self.send_json(build_status())
        if p == "/api/job":
            return self.send_json(JOB.snapshot(num("since", 0, 0, 10**9)))
        if p == "/api/logs":
            return self.send_json({"lines": tail(RUN_LOG, num("n", 200, 1, 5000))})
        if p == "/api/screenshots":
            return self.send_json({"items": screenshots()})
        if p == "/api/activity":
            key = q.get("range", ["7d"])[0]
            days = RANGES.get(key, 7)
            runs = load_history(days)
            return self.send_json({
                "range": key if key in RANGES else "7d",
                "days": days,
                "runs": runs,
                "ok": sum(1 for r in runs if r.get("status") in ("ok", "partial")),
                "failed": sum(1 for r in runs if r.get("status") not in ("ok", "partial")),
            })
        if p.startswith("/screenshots/"):
            return self.send_file(SHOT_DIR / Path(p).name)   # .name strips traversal
        return self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        if not self.trusted(post=True):
            # Drain the body so the keep-alive connection stays in sync.
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if 0 < n <= MAX_BODY:
                    self.rfile.read(n)
            except ValueError:
                pass
            return self.send_json({"error": "forbidden"}, 403)
        p = urlparse(self.path).path
        body = self.read_json()

        if p == "/api/run":
            kind = body.get("kind", "update")
            argv = {
                "update": [str(PYTHON), "update_profile.py"],
                "dry": [str(PYTHON), "update_profile.py", "--dry-run"],
                "apply": [str(PYTHON), "auto_apply.py"],
                "apply-dry": [str(PYTHON), "auto_apply.py", "--dry-run"],
                "login": [str(PYTHON), "login.py", "--wait"],
            }.get(kind)
            if argv is None:
                return self.send_json({"error": f"unknown kind {kind!r}"}, 400)
            ok, err = JOB.start(kind, argv)
            return self.send_json({"ok": ok, "error": err}, 200 if ok else 409)

        if p == "/api/stop":
            return self.send_json({"ok": JOB.stop()})

        if p == "/api/config":
            cfg = load_config()
            was_auto_apply_enabled = cfg["autoApply"]["enabled"]
            incoming = body.get("actions") or {}
            for k in ACTION_KEYS:
                if isinstance(incoming.get(k), bool):
                    cfg["actions"][k] = incoming[k]
            if "headlines" in body:
                cfg["headlines"] = clean_headlines(body["headlines"])
                cfg["headlineIndex"] = (
                    cfg["headlineIndex"] % len(cfg["headlines"])
                    if cfg["headlines"] else 0
                )
            if "resume" in body:
                pick = body["resume"]
                names = [f.name for f in list_resumes()]
                if pick in (None, ""):
                    cfg["resume"] = None
                elif pick in names:            # allowlist, so no path can escape
                    cfg["resume"] = pick
                else:
                    return self.send_json({"error": f"unknown resume {pick!r}"}, 400)
            if isinstance(body.get("autoApply"), dict):
                incoming_auto = body["autoApply"]
                auto_apply = cfg["autoApply"]
                if isinstance(incoming_auto.get("enabled"), bool):
                    auto_apply["enabled"] = incoming_auto["enabled"]
                for key in ("titles", "locations", "exclude"):
                    if key in incoming_auto:
                        auto_apply[key] = clean_terms(incoming_auto[key])
                if auto_apply["enabled"] and (not auto_apply["titles"] or not auto_apply["locations"]):
                    return self.send_json({
                        "error": "Auto-apply needs at least one title and one location."
                    }, 400)
            if not was_auto_apply_enabled and cfg["autoApply"]["enabled"]:
                current_schedule = schedule_info()
                if current_schedule["installed"] and current_schedule["hours"]:
                    ok, output = schedule_install(current_schedule["hours"])
                    if not ok:
                        return self.send_json({
                            "error": f"Could not update the scheduled task: {output}"
                        }, 500)
            save_config(cfg)
            return self.send_json({"ok": True, "config": cfg})

        if p == "/api/schedule":
            hours = body.get("hours")
            # Still an allowlist, and the only values that reach Task
            # Scheduler are these four.
            if hours in (0, "0", "off", None):
                ok, output = schedule_uninstall()
            elif str(hours) in ("12", "24", "48"):
                ok, output = schedule_install(int(hours))
            else:
                return self.send_json({"error": "hours must be 12, 24, 48 or 0"}, 400)
            return self.send_json({
                "ok": ok,
                "output": output,
                "schedule": schedule_info(),
            })

        if p == "/api/autostart":
            autostart_set(bool(body.get("on")))
            return self.send_json({"ok": True, "on": autostart_on()})

        if p == "/api/screenshots/delete":
            names = body.get("names")
            if not isinstance(names, list) or not names or len(names) > 200:
                return self.send_json({"error": "names required"}, 400)
            gone, kept = 0, 0
            for raw in names:
                # .name strips traversal, and the suffix check keeps this from
                # reaching anything that is not a capture.
                f = SHOT_DIR / Path(str(raw)).name
                if f.suffix.lower() == ".png" and f.is_file():
                    # Windows locks a file the browser is still fetching, so
                    # this retries briefly rather than reporting a failure for
                    # a capture that is about to be deletable.
                    if retry_unlink(f):
                        gone += 1
                    else:
                        kept += 1
                else:
                    kept += 1
            return self.send_json({"ok": True, "deleted": gone, "skipped": kept})

        return self.send_json({"error": "not found"}, 404)


class Dashboard(ThreadingHTTPServer):
    # Not the usual SO_REUSEADDR. On Windows that option does not mean "reuse
    # a port in TIME_WAIT" as it does elsewhere, it means a second socket may
    # bind a port another socket is actively listening on. With it left on,
    # starting the dashboard twice quietly leaves two servers fighting over
    # the same port instead of the second one refusing to start.
    allow_reuse_address = False


def already_listening():
    """True if something already holds the dashboard port."""
    with socket.socket() as s:
        s.settimeout(0.6)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def main():
    # Two helpers for dashboard.bat, so the batch file never has to parse .env
    # or read netstat. Both keep the port logic in exactly one place.
    if "--print-port" in sys.argv:
        print(PORT)
        return
    if "--probe" in sys.argv:
        raise SystemExit(0 if already_listening() else 1)

    # Checked before binding as well as after, because a refused bind is not
    # the only way this goes wrong and the message is the same either way.
    if already_listening():
        print(f"Port {PORT} is already in use. The dashboard may already be running:")
        print(f"  http://127.0.0.1:{PORT}")
        print("Or set DASHBOARD_PORT in .env to use another port.")
        raise SystemExit(1)
    try:
        srv = Dashboard(("127.0.0.1", PORT), Handler)
    except OSError:
        print(f"Port {PORT} is already in use. The dashboard may already be running:")
        print(f"  http://127.0.0.1:{PORT}")
        print("Or set DASHBOARD_PORT in .env to use another port.")
        raise SystemExit(1)
    print(f"Naukri Autopilot  ->  http://127.0.0.1:{PORT}")
    print("Ctrl-C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
