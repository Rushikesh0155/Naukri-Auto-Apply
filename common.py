"""Shared config, paths, logging and browser setup.

Every path here is derived from this file's own location, so the folder can
live anywhere and be renamed freely.
"""
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "storage_state.json"
CONFIG_FILE = ROOT / "config.json"
LOG_DIR = ROOT / "logs"
SHOT_DIR = ROOT / "screenshots"
RUN_LOG = LOG_DIR / "runs.log"
RESUME_DIR = ROOT / "Resume"
DATA_DIR = ROOT / "data"
HISTORY_FILE = DATA_DIR / "runs.jsonl"

PROFILE_URL = "https://www.naukri.com/mnjuser/profile"
LOGIN_URL = "https://www.naukri.com/nlogin/login"

load_dotenv(ROOT / ".env")


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------
# Windows keeps a lock on an open file, so a rewrite can land while the
# dashboard still has the old handle open, and a delete can fail outright
# while a screenshot is being served or a virus scanner is reading it. Both
# clear in milliseconds, so a short retry is all it takes.
RETRIES = 12
RETRY_WAIT = 0.08


def atomic_write(path: Path, text: str):
    """Write through a temporary file in the same folder, then swap it in.

    os.replace is atomic, so a reader sees either the whole old file or the
    whole new one and never a half-written one. That is the path taken
    virtually always.

    Windows can refuse the swap outright, though. A file another handle has
    open cannot be replaced unless that handle allowed delete sharing, and
    Python's open() does not, so a reader holding config.json blocks the
    rename for as long as it is open. Overwriting in place is still allowed,
    because ordinary readers do share write access. So after the retries are
    spent the content is written straight into the file rather than lost.
    That gives up atomicity for this one write, which is the right trade:
    these files are small and rewritten whole, and failing here would turn a
    headline rotation that actually worked into a failed run.
    """
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    for _ in range(RETRIES):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:           # someone still has it open
            time.sleep(RETRY_WAIT)
    try:
        path.write_text(text, encoding="utf-8", newline="\n")
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def retry_unlink(path: Path):
    """Delete, giving a held handle a moment to clear. True if it is gone."""
    for _ in range(RETRIES):
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return True
        except PermissionError:
            time.sleep(RETRY_WAIT)
    return not path.exists()


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
def setup_logging():
    LOG_DIR.mkdir(exist_ok=True)
    SHOT_DIR.mkdir(exist_ok=True)
    # The Windows console is cp1252, which cannot print every character a
    # headline or a file name might hold. Without this a single accent in a
    # log line ends the run with a UnicodeEncodeError.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass                          # pythonw has no console at all
    # Scheduled runs are launched with pythonw, which has no stdout at all, so
    # the console handler is only added when there is somewhere to write to.
    # The log file is always written either way.
    handlers = [logging.FileHandler(RUN_LOG, encoding="utf-8")]
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )
    return logging.getLogger("naukri")


# --------------------------------------------------------------------------
# What a run can do
# --------------------------------------------------------------------------
ACTIONS = [
    {
        "key": "resume",
        "label": "Resume re-upload",
        "detail": "Uploads the same PDF again. This is the one that does the "
                  "work, so leave it on.",
        "caveat": None,
    },
    {
        "key": "headline",
        "label": "Headline rotation",
        "detail": "Works through your list of headlines, one per run. Each one "
                  "is a real change, so Naukri actually registers it.",
        "caveat": "You need at least two. With one, Naukri just stores what was "
                  "already there and nothing happens.",
    },
]
ACTION_KEYS = [a["key"] for a in ACTIONS]

HEADLINE_MAX = 250          # Naukri rejects anything longer
HEADLINE_SLOTS = 6
AUTO_APPLY_DAILY_CAP = 10
AUTO_APPLY_TERM_SLOTS = 10

DEFAULT_CONFIG = {
    "actions": {"resume": True, "headline": False},
    "resume": None,
    "headlines": [],
    "headlineIndex": 0,
    "autoApply": {
        "enabled": False,
        "titles": [],
        "locations": [],
        "exclude": [],
    },
}


def clean_headlines(values):
    """Trim, drop blanks and duplicates, enforce the length and slot caps."""
    out = []
    for v in values or []:
        if not isinstance(v, str):
            continue
        # Naukri collapses whitespace itself, so two variants differing only by
        # spacing would be the same stored value.
        v = " ".join(v.split())[:HEADLINE_MAX]
        if v and v not in out:
            out.append(v)
    return out[:HEADLINE_SLOTS]


def clean_terms(values):
    """Normalize a short list of job-search terms."""
    out = []
    if not isinstance(values, (list, tuple)):
        return out
    for value in values:
        if not isinstance(value, str):
            continue
        value = " ".join(value.split())[:80]
        if value and value.casefold() not in {term.casefold() for term in out}:
            out.append(value)
    return out[:AUTO_APPLY_TERM_SLOTS]


def load_config():
    """Config always comes back complete, whatever is on disk."""
    cfg = {
        "actions": dict(DEFAULT_CONFIG["actions"]),
        "resume": None,
        "headlines": [],
        "headlineIndex": 0,
        "autoApply": dict(DEFAULT_CONFIG["autoApply"]),
    }
    try:
        # Always UTF-8, never the machine's code page, or a headline with an
        # accent in it would come back as mojibake or refuse to read at all.
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, UnicodeDecodeError):
        return cfg
    for k in ACTION_KEYS:
        if isinstance(raw.get("actions", {}).get(k), bool):
            cfg["actions"][k] = raw["actions"][k]
    if isinstance(raw.get("resume"), str) and raw["resume"].strip():
        cfg["resume"] = raw["resume"].strip()
    cfg["headlines"] = clean_headlines(raw.get("headlines"))
    idx = raw.get("headlineIndex")
    if isinstance(idx, int) and cfg["headlines"]:
        cfg["headlineIndex"] = idx % len(cfg["headlines"])
    auto_apply = raw.get("autoApply")
    if isinstance(auto_apply, dict):
        if isinstance(auto_apply.get("enabled"), bool):
            cfg["autoApply"]["enabled"] = auto_apply["enabled"]
        for key in ("titles", "locations", "exclude"):
            cfg["autoApply"][key] = clean_terms(auto_apply.get(key))
    return cfg


def save_config(cfg):
    # ensure_ascii keeps a non-ASCII headline readable in the file itself
    # rather than escaped into \uXXXX soup.
    atomic_write(CONFIG_FILE, json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
    return cfg


# --------------------------------------------------------------------------
# Resume
# --------------------------------------------------------------------------
def list_resumes():
    """Every resume file in Resume/, newest first."""
    if not RESUME_DIR.is_dir():
        return []
    files = [f for f in RESUME_DIR.iterdir()
             if f.suffix.lower() in (".pdf", ".doc", ".docx")]
    return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)


def resume_path(cfg=None):
    """Resolution order: config.json -> RESUME_PATH in .env -> the lone file in
    Resume/. A config entry naming a missing file falls through rather than
    failing, so a deleted resume cannot wedge every future run."""
    cfg = cfg or load_config()

    if cfg.get("resume"):
        chosen = Path(cfg["resume"]).expanduser()
        if not chosen.is_absolute():
            chosen = RESUME_DIR / cfg["resume"]
        if chosen.is_file():
            return chosen

    env = os.getenv("RESUME_PATH", "").strip()
    if env:
        path = Path(env).expanduser()
        if path.is_file():
            return path

    found = list_resumes()
    if len(found) == 1:
        return found[0]
    if not found:
        raise SystemExit("No resume in Resume/. Add your PDF there first.")
    raise SystemExit("Resume/ holds several files. Pick one in the dashboard.")


# --------------------------------------------------------------------------
# Run history
# --------------------------------------------------------------------------
# One JSON object per line, appended at the end of every real run. It is what
# the activity chart reads, and it is kept apart from runs.log so the chart
# never depends on parsing human-readable log text.
HISTORY_KEEP_DAYS = 120


def record_run(status, started, headline=None, resume=None, detail=None, platform="naukri"):
    """Append one run. Never raises, a failed write must not fail a run."""
    try:
        DATA_DIR.mkdir(exist_ok=True)
        rec = {
            "at": started.strftime("%Y-%m-%d %H:%M:%S"),
            "platform": platform,         # one chart line per platform
            "status": status,             # ok, partial, failed, expired, blocked
            "headline": headline,         # yes, no, skip
            "resume": resume,
            "seconds": round((datetime.now() - started).total_seconds()),
            "detail": detail,
        }
        with open(HISTORY_FILE, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def load_history(days=None):
    """Runs newest last. `days` limits it to that many days back from today."""
    if not HISTORY_FILE.exists():
        return []
    cutoff = None
    if days:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    out = []
    with open(HISTORY_FILE, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except ValueError:
                continue                  # a torn last line should not hide the rest
            if not isinstance(rec, dict) or not isinstance(rec.get("at"), str):
                continue
            if cutoff and rec["at"][:10] < cutoff:
                continue
            out.append(rec)
    out.sort(key=lambda r: r["at"])
    return out


def prune_history():
    """Drop anything older than the longest chart range, plus a margin."""
    try:
        keep = load_history(HISTORY_KEEP_DAYS)
        atomic_write(
            HISTORY_FILE,
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in keep),
        )
    except Exception:
        pass


# --------------------------------------------------------------------------
# Screenshots
# --------------------------------------------------------------------------
def stamp():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def shot(page, name):
    """Best-effort screenshot; never let it break a run."""
    try:
        SHOT_DIR.mkdir(exist_ok=True)
        path = SHOT_DIR / f"{stamp()}-{name}.png"
        page.screenshot(path=str(path), full_page=False)
        return path
    except Exception:
        return None


def prune_screenshots(keep=40):
    try:
        files = sorted(SHOT_DIR.glob("*.png"), key=lambda f: f.stat().st_mtime)
        for f in files[:-keep]:
            # One the dashboard happens to be serving right now is locked, so
            # it is left for the next prune rather than failing this one.
            retry_unlink(f)
    except Exception:
        pass


# --------------------------------------------------------------------------
# Browser
# --------------------------------------------------------------------------
VIEWPORT = {"width": 1440, "height": 900}
LOCALE = "en-IN"
TIMEZONE = "Asia/Kolkata"

# Naukri sits behind Akamai, which blocks headless Chromium outright. Every
# headless variant gets an "Access Denied" page while a headed browser passes,
# so runs always launch headed and park the window off the side of the desktop.
BASE_ARGS = [
    "--disable-blink-features=AutomationControlled",
    # Windows tells Chromium when a window is completely covered or off-screen
    # and Chromium then stops drawing it, which would leave every screenshot
    # blank and stall the page. These three keep a parked window rendering.
    "--disable-features=CalculateNativeWinOcclusion",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
]


def offscreen_args():
    """Park the window past the right edge of the whole desktop.

    A fixed negative position is not safe here: with a second monitor
    arranged to the left, the desktop extends into negative coordinates and a
    window parked at -3000 can land in plain view. So the real bounds are
    measured first and the window goes just past the right edge, which is
    outside the desktop whatever the monitor arrangement.
    """
    left, top = 6000, 0
    try:
        import ctypes

        user32 = ctypes.windll.user32
        try:
            user32.SetProcessDPIAware()   # measure in real pixels, not scaled
        except Exception:
            pass
        SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
        SM_CXVIRTUALSCREEN = 78
        x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        if width > 0:
            left = x + width + 200
            top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    except Exception:
        pass                              # the fallback is already off-screen
    return [f"--window-position={left},{top}", "--window-size=1440,900"]

BLOCK_MARKERS = ("access denied", "you don't have permission", "errors.edgesuite.net")

# Naukri floats a survey over the profile whose backdrop swallows clicks.
# Deleting the nodes does not stick because React re-mounts them, so a
# stylesheet rule is used, installed before the page hydrates.
OVERLAY_CSS = (
    '#ni-desktop-nps-profile,#ni-desktop-nps,.md__backdrop,[class*="nps-widget"]'
    "{display:none!important;pointer-events:none!important}"
)
OVERLAY_INIT = """
(() => {
  const css = %r;
  const inject = () => {
    if (document.getElementById('__nk_overlay_kill')) return;
    const el = document.createElement('style');
    el.id = '__nk_overlay_kill';
    el.textContent = css;
    (document.head || document.documentElement).appendChild(el);
  };
  inject();
  document.addEventListener('DOMContentLoaded', inject);
})();
""" % OVERLAY_CSS


def headful():
    return os.getenv("HEADFUL", "0").strip() in ("1", "true", "True", "yes")


# The browser setup.bat downloads is the first choice, so a run behaves the
# same on every machine. Edge is the safety net: it ships with Windows 10 and
# 11, it is the same Chromium underneath, and it costs nothing to fall back to
# when the downloaded build will not start. That does happen. A Chrome for
# Testing build whose side-by-side manifest Windows refuses to activate fails
# with a bare "spawn UNKNOWN" and no amount of retrying the same binary helps.
BROWSER_CHANNELS = [
    (None, "the downloaded browser"),
    ("msedge", "Microsoft Edge"),
    ("chrome", "Google Chrome"),
]


def new_browser(p, visible=False):
    """A headed browser, off-screen unless the caller needs it visible.

    Headed is not a preference. Naukri sits behind Akamai, which serves an
    Access Denied page to every headless build, so the window is real and
    simply parked where nobody looks.
    """
    args = BASE_ARGS + ([] if visible else offscreen_args())
    first_error = None
    for channel, label in BROWSER_CHANNELS:
        try:
            kw = {"headless": False, "args": args}
            if channel:
                kw["channel"] = channel
            browser = p.chromium.launch(**kw)
            if channel:
                logging.getLogger("naukri").info("Using %s.", label)
            return browser
        except Exception as e:
            if first_error is None:
                first_error = e
    raise RuntimeError(
        "No browser would start. Run setup.bat again to reinstall it. "
        f"({type(first_error).__name__})"
    )


def check_browser():
    """Work out which browser a run will actually use, and say so.

    setup.bat calls this at the end. The downloaded browser does not start on
    every machine, and without this the only sign of that is a line in the log
    long after setup looked like it went fine.

    Never raises and never fails setup. The worst case is a warning that turns
    out to be wrong, which is still better than silence.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("Could not load Playwright to check the browser.")
        return None

    try:
        with sync_playwright() as p:
            for channel, label in BROWSER_CHANNELS:
                try:
                    kw = {"headless": False, "args": BASE_ARGS + offscreen_args()}
                    if channel:
                        kw["channel"] = channel
                    p.chromium.launch(**kw).close()
                    if channel is None:
                        print("Browser check: the downloaded browser works.")
                    else:
                        print(f"Browser check: falling back to {label}.")
                        print("The downloaded one will not start on this PC.")
                        print("That is fine, runs work exactly the same.")
                    return channel
                except Exception:
                    continue
    except Exception:
        pass
    # No browser at all is worth flagging now rather than at the first
    # scheduled run, which nobody is watching.
    print("Browser check: no browser would start.")
    print("Runs will fail until this is sorted. Try running setup.bat again.")
    return False


def new_context(browser, with_session=True):
    kw = {"viewport": VIEWPORT, "locale": LOCALE, "timezone_id": TIMEZONE}
    if with_session:
        kw["storage_state"] = str(STATE_FILE)
    ctx = browser.new_context(**kw)
    ctx.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    )
    ctx.add_init_script(OVERLAY_INIT)
    return ctx


def page_state(page):
    """Classify what actually loaded: 'ok', 'blocked' or 'login'.

    Checking the URL alone is not enough. The block page keeps the requested
    URL, so a URL-only test reports it as a healthy profile page.
    """
    if "login" in page.url.lower():
        return "login"
    try:
        body = page.inner_text("body")[:400].lower()
    except Exception:
        return "ok"
    if any(m in body for m in BLOCK_MARKERS):
        return "blocked"
    return "ok"
