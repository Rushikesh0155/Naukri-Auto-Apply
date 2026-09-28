"""Refresh the Naukri profile so its "last updated" stamp resets.

Two independent nudges, whichever are enabled in the dashboard:
  1. Resume re-upload   uploads the same PDF again
  2. Headline rotation  writes the next headline from your list

They are independent on purpose. If Naukri changes the markup of one section,
the other still refreshes the timestamp and the run is not a total loss.
"""
import argparse
import sys
from datetime import datetime

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from common import (
    OVERLAY_CSS,
    PROFILE_URL,
    STATE_FILE,
    headful,
    load_config,
    new_browser,
    prune_history,
    record_run,
    new_context,
    page_state,
    prune_screenshots,
    resume_path,
    save_config,
    setup_logging,
    shot,
)

log = setup_logging()

# Naukri reshuffles its markup fairly often, so every element is looked up
# through a list of candidates rather than one brittle selector.
HEADLINE_EDIT = [
    "#lazyResumeHead span.edit",
    "#resumeHeadline span.edit",
    "[id*='resumeHeadline'] span.edit",
    "span.edit.icon",
]
HEADLINE_TEXTAREA = [
    "#resumeHeadlineTxt",
    "textarea[id*='resumeHeadline']",
    "form textarea",
]
SAVE_BUTTON = [
    "button[type='submit']:has-text('Save')",
    "button:has-text('Save')",
    ".btn-dark-ot:has-text('Save')",
]
FILE_INPUT = [
    "input#attachCV",
    "input[type='file'][id*='attach']",
    "input[type='file']",
]


def dismiss_overlays(page):
    """Belt and braces. The same CSS is installed as an init script already,
    so this only matters if that lost a race."""
    try:
        page.add_style_tag(content=OVERLAY_CSS)
    except Exception:
        pass


def click_through(locator):
    """Click, escalating past anything that intercepts.

    A plain click waits on hit-testing, which the survey backdrop can cost
    several seconds even when it eventually succeeds. So the plain attempt is
    kept short, then forced, then dispatched directly.
    """
    try:
        locator.click(timeout=4000)
        return
    except Exception:
        pass
    try:
        locator.click(timeout=4000, force=True)
        return
    except Exception:
        pass
    locator.dispatch_event("click", timeout=5000)


def first_visible(page, selectors, timeout=6000):
    """Return the first selector in the list that resolves to a visible node."""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=timeout)
            return loc
        except PWTimeout:
            continue
        except Exception:
            continue
    return None


# Reads the headline as the page displays it, so verification never has to
# reopen the edit dialog. Reopening was the step that used to fail.
READ_HEADLINE_JS = """() => {
  const box = document.querySelector('#lazyResumeHead')
           || document.querySelector('[id*="resumeHeadline"]');
  if (!box) return null;
  const lines = box.innerText.split('\\n').map(s => s.trim()).filter(Boolean);
  const found = lines.filter(l => l.length > 40).sort((a, b) => b.length - a.length)[0];
  return found || null;
}"""

norm = lambda t: " ".join((t or "").split())


def read_headline(page):
    try:
        return page.evaluate(READ_HEADLINE_JS)
    except Exception:
        return None


def rotate_headline(page, cfg):
    """Write the next headline variant from the list.

    Rotation is what makes this work at all. Re-saving a single headline is a
    no-op, because Naukri normalises the value and stores what was already
    there. Two or more genuinely different variants mean every run writes a
    value the server has to change.
    """
    variants = cfg.get("headlines") or []
    if len(variants) < 2:
        raise RuntimeError(
            "headline rotation needs at least two variants, add them on the "
            "Configuration page"
        )

    idx = cfg.get("headlineIndex", 0) % len(variants)
    target = variants[idx]

    live = norm(read_headline(page))
    if live and norm(target) == live:
        idx = (idx + 1) % len(variants)
        target = variants[idx]
        log.info("Variant %d already live, using the next one.", idx)

    dismiss_overlays(page)
    edit = first_visible(page, HEADLINE_EDIT)
    if edit is None:
        raise RuntimeError("headline edit control not found")
    click_through(edit)
    page.wait_for_timeout(1200)

    box = first_visible(page, HEADLINE_TEXTAREA)
    if box is None:
        raise RuntimeError("headline dialog did not open (no textarea)")
    box.fill(target)

    save = first_visible(page, SAVE_BUTTON)
    if save is None:
        raise RuntimeError("save button not found in the headline dialog")
    click_through(save)
    page.wait_for_timeout(2500)

    # Confirm it actually stuck. Assuming a save means a change is how a
    # silent no-op could go unnoticed for days.
    page.goto(PROFILE_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    after = norm(read_headline(page))
    if after != norm(target):
        raise RuntimeError(
            f"headline did not persist (wanted {len(norm(target))} chars, "
            f"page shows {len(after or '')})"
        )

    cfg["headlineIndex"] = (idx + 1) % len(variants)
    save_config(cfg)
    log.info("Headline set to variant %d of %d and verified on the page.",
             idx + 1, len(variants))


def rotate_headline_resilient(page, cfg):
    """One retry after a reload. The failure mode is a mid-flight re-render."""
    try:
        rotate_headline(page, cfg)
        return
    except Exception as e:
        log.warning("Headline attempt 1 failed (%s); retrying once.", e)
    page.goto(PROFILE_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    rotate_headline(page, cfg)


def reupload_resume(page, pdf):
    inp = None
    for sel in FILE_INPUT:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="attached", timeout=6000)
            inp = loc
            break
        except Exception:
            continue
    if inp is None:
        raise RuntimeError("resume file input not found")

    inp.set_input_files(str(pdf))
    page.wait_for_timeout(8000)
    log.info("Resume re-uploaded: %s", pdf.name)


def run(dry_run=False):
    if not STATE_FILE.exists():
        log.error("No saved session. Sign in from the dashboard first.")
        return 2

    cfg = load_config()
    want = cfg["actions"]
    if not dry_run and not any(want.values()):
        log.error("Every action is switched off. Enable one on the Configuration page.")
        return 5

    started = datetime.now()
    pdf = None
    if want["resume"] and not dry_run:
        try:
            pdf = resume_path(cfg)
        except SystemExit as e:
            # Logged and recorded like any other failure, so a scheduled run
            # with no resume shows up on the dashboard instead of vanishing.
            log.error("RUN FAILED, no resume to upload. %s", e)
            record_run("failed", started, detail=str(e))
            return 6
    log.info("Actions: %s", ", ".join(k for k, v in want.items() if v) or "none")

    try:
        return _session(dry_run, cfg, want, pdf, started)
    except Exception as e:
        # Network down, Naukri not loading, the browser failing to start. None
        # of these should end in a bare traceback the dashboard cannot read.
        why = f"{type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}"
        if dry_run:
            log.error("Sign-in check could not finish. %s", why)
            return 1
        log.error("RUN FAILED, %s", why)
        record_run("failed", started, detail=type(e).__name__)
        prune_history()
        return 1


def _session(dry_run, cfg, want, pdf, started):
    ok_headline = ok_resume = False

    with sync_playwright() as p:
        browser = new_browser(p, visible=headful())
        ctx = new_context(browser)
        page = ctx.new_page()
        try:
            page.goto(PROFILE_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)

            state = page_state(page)
            if state == "blocked":
                shot(page, "blocked")
                log.error(
                    "Naukri's edge served an Access Denied page. This is bot "
                    "detection, not a login problem. See the Guidelines page."
                )
                if not dry_run:
                    record_run("blocked", started, detail="Access Denied page")
                return 4
            if state == "login":
                shot(page, "session-expired")
                log.error("Session expired. Sign in again from the dashboard.")
                if not dry_run:
                    record_run("expired", started, detail="bounced to login")
                return 3

            dismiss_overlays(page)
            log.info("Logged in, profile page loaded.")
            if dry_run:
                shot(page, "dry-run")
                log.info("Sign-in check only, no edits made.")
                return 0

            if want["headline"]:
                try:
                    rotate_headline_resilient(page, cfg)
                    ok_headline = True
                except Exception as e:
                    log.warning("Headline rotation failed: %s", e)
                    shot(page, "headline-failed")

            if want["resume"]:
                try:
                    page.goto(PROFILE_URL, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(4000)
                    dismiss_overlays(page)
                    reupload_resume(page, pdf)
                    ok_resume = True
                except Exception as e:
                    log.warning("Resume re-upload failed: %s", e)
                    shot(page, "resume-failed")

            shot(page, "after-update")
            # Cookies rotate, so persisting them here stretches the session.
            ctx.storage_state(path=str(STATE_FILE))
        finally:
            browser.close()
            prune_screenshots()

    def mark(enabled, ok):
        return "yes" if ok else ("skip" if not enabled else "no")

    h = mark(want["headline"], ok_headline)
    r = mark(want["resume"], ok_resume)

    if ok_headline or ok_resume:
        log.info("RUN OK  (headline=%s, resume=%s)", h, r)
        record_run("partial" if "no" in (h, r) else "ok", started, h, r)
        prune_history()
        return 0

    log.error("RUN FAILED, nothing went through. See the Captures page.")
    record_run("failed", started, h, r, detail="nothing went through")
    prune_history()
    return 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="only verify the saved session; make no edits")
    sys.exit(run(dry_run=ap.parse_args().dry_run))
