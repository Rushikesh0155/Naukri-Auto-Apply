"""Apply to matching Naukri jobs using the saved browser session.

Only Naukri-hosted applications are considered. Required unanswered form fields,
login challenges, and bot-protection pages stop or skip the application.
"""
import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from playwright.sync_api import sync_playwright

from common import (
    AUTO_APPLY_DAILY_CAP,
    DATA_DIR,
    STATE_FILE,
    headful,
    load_config,
    new_browser,
    new_context,
    prune_screenshots,
    setup_logging,
    shot,
)

log = setup_logging()
APPLICATIONS_FILE = DATA_DIR / "applications.jsonl"
JOB_URL_RE = re.compile(r"/job-listings-[^?#]+", re.I)
APPLY_LABEL_RE = re.compile(r"^(apply|apply now)$", re.I)
SUBMIT_LABEL_RE = re.compile(r"^(apply|apply now|submit|submit application)$", re.I)
CHALLENGE_MARKERS = (
    "access denied",
    "verify you are human",
    "captcha",
    "security check",
    "unusual traffic",
)
SUCCESS_MARKERS = (
    "application submitted",
    "successfully applied",
    "you have applied",
    "application has been sent",
)


def clean_job_url(url):
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def is_naukri_url(url):
    host = (urlsplit(url).hostname or "").lower()
    return host == "naukri.com" or host.endswith(".naukri.com")


def search_url(title, location):
    title_slug = quote("-".join(title.split()).lower(), safe="-")
    location_slug = quote("-".join(location.split()).lower(), safe="-")
    return f"https://www.naukri.com/{title_slug}-jobs-in-{location_slug}"


def matches_job(text, titles, locations, exclusions):
    folded = text.casefold()
    return (
        any(term.casefold() in folded for term in titles)
        and any(term.casefold() in folded for term in locations)
        and not any(term.casefold() in folded for term in exclusions)
    )


def read_applications():
    records = []
    try:
        with APPLICATIONS_FILE.open("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if isinstance(item, dict):
                    records.append(item)
    except FileNotFoundError:
        pass
    return records


def record_application(url, title, status, detail=""):
    DATA_DIR.mkdir(exist_ok=True)
    item = {
        "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "url": clean_job_url(url),
        "title": title[:200],
        "status": status,
        "detail": detail[:300],
    }
    with APPLICATIONS_FILE.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(item, ensure_ascii=False) + "\n")
    return item


def challenge_state(page):
    host = (urlsplit(page.url).hostname or "").lower()
    if host and not (host == "naukri.com" or host.endswith(".naukri.com")):
        return "external"
    if "nlogin" in page.url or "login" in page.url:
        return "login"
    try:
        body = page.locator("body").inner_text(timeout=3000).casefold()
    except Exception:
        body = ""
    if any(marker in body for marker in CHALLENGE_MARKERS):
        return "blocked"
    return "ok"


def collect_jobs(page, titles, locations, exclusions):
    found = {}
    for title in titles:
        for location in locations:
            url = search_url(title, location)
            log.info("Searching: %s in %s", title, location)
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3500)
            state = challenge_state(page)
            if state != "ok":
                raise RuntimeError(f"Search stopped: Naukri returned {state}.")
            links = page.locator("a[href*='/job-listings-']")
            for index in range(min(links.count(), 100)):
                link = links.nth(index)
                href = link.get_attribute("href")
                if not href:
                    continue
                absolute_url = urljoin(page.url, href)
                if not is_naukri_url(absolute_url):
                    continue
                job_url = clean_job_url(absolute_url)
                try:
                    text = link.evaluate("""node => {
                      let item = node;
                      for (let i = 0; i < 6 && item; i++, item = item.parentElement) {
                        if (item.matches('article, [data-job-id], .srp-jobtuple-wrapper'))
                          return item.innerText || node.innerText || '';
                      }
                      return node.parentElement?.parentElement?.innerText || node.innerText || '';
                    }""")
                except Exception:
                    text = link.inner_text(timeout=1000)
                if job_url and matches_job(text, titles, locations, exclusions):
                    found.setdefault(job_url, " ".join(text.split()))
    return found


def already_applied(page):
    try:
        badges = page.get_by_text("Applied", exact=True)
        for index in range(badges.count()):
            if badges.nth(index).is_visible():
                return True
        body = page.locator("body").inner_text(timeout=3000).casefold()
        return "you have already applied" in body or "application already submitted" in body
    except Exception:
        return False


def unanswered_required_fields(page):
    return page.evaluate("""() => {
      const visible = element => !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
      const roots = [...document.querySelectorAll('[role="dialog"], .modal, form')].filter(visible);
      const root = roots[0] || document;
      const fields = [...root.querySelectorAll('input, select, textarea')]
        .filter(field => visible(field) && (field.required || field.getAttribute('aria-required') === 'true'));
      const unanswered = [];
      const radios = new Set();
      for (const field of fields) {
        if (field.type === 'radio') {
          if (!radios.has(field.name)) {
            radios.add(field.name);
            if (![...root.querySelectorAll('input[type="radio"]')].some(radio => radio.name === field.name && radio.checked))
              unanswered.push(field.name || 'radio question');
          }
        } else if (field.type === 'checkbox') {
          if (!field.checked) unanswered.push(field.name || 'required checkbox');
        } else if (field.type !== 'file' && !String(field.value || '').trim()) {
          unanswered.push(field.getAttribute('aria-label') || field.name || field.placeholder || 'required field');
        } else if (field.type === 'file' && !field.files?.length) {
          unanswered.push(field.name || 'required file');
        }
      }
      return unanswered;
    }""")


def visible_submit_button(page, root):
    for button in root.get_by_role("button").all():
        try:
            if button.is_visible() and SUBMIT_LABEL_RE.fullmatch((button.inner_text() or "").strip()):
                return button
        except Exception:
            continue
    return None


def apply_to_job(page, url, summary, dry_run=False):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    state = challenge_state(page)
    if state != "ok":
        return state, f"Job page returned {state}"
    if already_applied(page):
        return "already-applied", "Naukri indicates this job was already applied to"

    title = " ".join(summary.splitlines()[0].split())[:200] or urlsplit(url).path
    button = None
    for candidate in page.get_by_role("button", name=APPLY_LABEL_RE).all():
        try:
            if candidate.is_visible() and candidate.is_enabled():
                button = candidate
                break
        except Exception:
            continue
    if button is None:
        for candidate in page.get_by_role("link", name=APPLY_LABEL_RE).all():
            try:
                if candidate.is_visible() and candidate.is_enabled():
                    target = candidate.get_attribute("href") or ""
                    if is_naukri_url(urljoin(page.url, target)):
                        button = candidate
                        break
            except Exception:
                continue
    if button is None:
        return "skipped", "No Naukri-hosted Apply button found"
    if dry_run:
        return "preview", "Would click the Naukri-hosted Apply button"

    button.click(timeout=8000)
    page.wait_for_timeout(2500)
    state = challenge_state(page)
    if state != "ok":
        return state, f"Application stopped: page returned {state}"

    body = page.locator("body").inner_text(timeout=3000).casefold()
    if any(marker in body for marker in SUCCESS_MARKERS):
        return "applied", "Naukri confirmed the application"
    if already_applied(page):
        return "applied", "Naukri shows the Applied status"

    form_roots = page.locator("[role='dialog']:visible, .modal:visible, form:visible")
    if not form_roots.count():
        return "uncertain", "Apply was clicked, but no application form or confirmation appeared"

    unanswered = unanswered_required_fields(page)
    if unanswered:
        return "skipped", "Required unanswered field(s): " + ", ".join(unanswered[:5])

    submit = visible_submit_button(page, form_roots.first)
    if submit is not None:
        submit.click(timeout=8000)
        page.wait_for_timeout(2500)
        state = challenge_state(page)
        if state != "ok":
            return state, f"Submission result uncertain; page returned {state}"
        body = page.locator("body").inner_text(timeout=3000).casefold()
        if any(marker in body for marker in SUCCESS_MARKERS):
            return "applied", "Naukri confirmed the application"
        return "uncertain", "Submitted, but confirmation was not detected"

    if page.locator("[role='dialog']:visible, .modal:visible").count():
        return "skipped", "Application form needs manual review"
    return "uncertain", "Apply was clicked, but Naukri did not show a confirmation"


def run(dry_run=False):
    cfg = load_config()["autoApply"]
    titles = cfg["titles"]
    locations = cfg["locations"]
    exclusions = cfg["exclude"]
    if not titles or not locations:
        log.error("Auto-apply needs at least one job title and one location in Configuration.")
        return 5
    if not dry_run and not cfg["enabled"]:
        log.error("Auto-apply is off. Enable it in Configuration first.")
        return 5
    if not STATE_FILE.exists():
        log.error("No saved session. Sign in from the dashboard first.")
        return 2

    previous = read_applications()
    seen = {item.get("url") for item in previous
            if item.get("status") in ("applied", "uncertain", "already-applied")}
    today = date.today().isoformat()
    submitted_today = sum(
        1 for item in previous
        if item.get("at", "").startswith(today)
        and item.get("status") in ("applied", "uncertain")
    )
    remaining = max(0, AUTO_APPLY_DAILY_CAP - submitted_today)
    if not dry_run and remaining == 0:
        log.info("Daily application cap reached (%d/%d).", submitted_today, AUTO_APPLY_DAILY_CAP)
        return 0

    started = datetime.now()
    try:
        with sync_playwright() as playwright:
            browser = new_browser(playwright, visible=headful())
            context = new_context(browser)
            page = context.new_page()
            try:
                jobs = collect_jobs(page, titles, locations, exclusions)
                log.info("Found %d matching job listing(s).", len(jobs))
                for url, summary in jobs.items():
                    if url in seen:
                        continue
                    if not dry_run and remaining <= 0:
                        log.info("Daily application cap reached (%d).", AUTO_APPLY_DAILY_CAP)
                        break
                    status, detail = apply_to_job(page, url, summary, dry_run=dry_run)
                    title = " ".join(summary.splitlines()[0].split())[:200]
                    log.info("%s: %s (%s)", status.upper(), title or url, detail)
                    if status == "uncertain":
                        shot(page, "auto-apply-uncertain")
                    if status not in ("preview",):
                        record_application(url, title, status, detail)
                    if status in ("applied", "uncertain"):
                        remaining -= 1
                    if status in ("blocked", "login", "external"):
                        shot(page, f"auto-apply-{status}")
                        log.error("Stopped applying because the session/page is %s.", status)
                        return 4 if status == "blocked" else 3
                context.storage_state(path=str(STATE_FILE))
            finally:
                browser.close()
                prune_screenshots()
        log.info("Auto-apply run complete%s.", " (preview only)" if dry_run else "")
        return 0
    except Exception as error:
        log.error("AUTO-APPLY FAILED, %s: %s", type(error).__name__, error)
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="search and show candidates without applying")
    sys.exit(run(dry_run=parser.parse_args().dry_run))