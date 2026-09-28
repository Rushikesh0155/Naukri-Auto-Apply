"""One-time sign-in.

Opens a real browser window. You sign in to Naukri yourself, including any OTP
or captcha, and the session is saved to storage_state.json so scheduled runs
can reuse it.

Nothing about your password is read, stored or typed by this script.

  python login.py          press Enter when you are done
  python login.py --wait   detects a finished sign-in on its own (the dashboard
                           uses this)
"""
import argparse
import sys
import time

from playwright.sync_api import sync_playwright

from common import (
    LOGIN_URL,
    PROFILE_URL,
    STATE_FILE,
    new_browser,
    new_context,
    page_state,
    setup_logging,
)

log = setup_logging()

BANNER = """
======================================================================
  A browser window is open. Sign in to Naukri there.
  Complete any OTP or captcha step until you land on your profile.
======================================================================
"""


def session_is_live(page):
    try:
        page.goto(PROFILE_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2500)
        return page_state(page) == "ok"
    except Exception:
        return False


def main(wait_mode, timeout_min):
    with sync_playwright() as p:
        browser = new_browser(p, visible=True)
        ctx = new_context(browser, with_session=False)
        page = ctx.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded")

        print(BANNER, flush=True)

        if wait_mode:
            # Poll in a second tab so the page you are typing into is left alone.
            probe = ctx.new_page()
            deadline = time.time() + timeout_min * 60
            log.info("Waiting up to %d minutes for you to finish signing in...", timeout_min)
            while time.time() < deadline:
                time.sleep(50)
                # Closing the window means giving up, so stop waiting for it.
                if not browser.is_connected() or page.is_closed():
                    log.error("Sign-in window was closed. Nothing saved.")
                    return 1
                if session_is_live(probe):
                    break
                remaining = int(deadline - time.time())
                if remaining % 30 < 6:
                    log.info("Still waiting... %ds left", remaining)
            else:
                log.error("Timed out. Nothing saved, start the sign-in again.")
                browser.close()
                return 1
            probe.close()
        else:
            input("\nPress Enter once you are logged in... ")
            if not session_is_live(page):
                log.error("Still on a login page. Session not saved.")
                browser.close()
                return 1

        ctx.storage_state(path=str(STATE_FILE))
        log.info("Session saved.")
        log.info("LOGIN OK, you can close the browser window.")
        browser.close()
        return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wait", action="store_true",
                    help="auto-detect a completed sign-in instead of waiting on Enter")
    ap.add_argument("--timeout", type=int, default=10,
                    help="minutes to wait in --wait mode")
    args = ap.parse_args()
    sys.exit(main(args.wait, args.timeout))
