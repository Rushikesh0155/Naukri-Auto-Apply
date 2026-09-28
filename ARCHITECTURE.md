# How it works

Naukri Autopilot for Windows.

For anyone who wants to read the code. You do not need any of this to use the
tool, it is just here if you are curious.

## The idea

Naukri sorts recruiter search by "last updated". Re-uploading the same resume
resets that timestamp without changing anything on your profile. Everything else
here is plumbing around that.

## The pieces

| File | Purpose |
|---|---|
| `update_profile.py` | one run: open the profile, do the enabled nudges, screenshot, log |
| `auto_apply.py` | search configured Naukri jobs, apply within the daily cap, record outcomes |
| `scheduled_run.py` | run the profile refresh and enabled auto-apply together |
| `login.py` | one-time sign-in, saves the session |
| `common.py` | paths, config, logging, screenshots, browser setup |
| `server.py` | the dashboard backend, standard library only |
| `web/` | the dashboard page: `index.html`, `styles.css`, `app.js`, `theme.js` |
| `data/runs.jsonl` | one line per run, the history the Home chart reads |
| `setup.bat` | first-run installer |
| `dashboard.bat` | starts the control panel |
| `windows_tasks.py` | installs or removes the scheduled run and start on login |

## A run, step by step

```
update_profile.py
  → launch a real browser, parked off-screen
  → load saved cookies
  → open the profile page
  → classify it: ok / blocked / login, and bail early on the last two
  → neutralise the survey overlay
  → for each enabled action:
        · rotate the headline
        · re-upload the resume
  → screenshot, re-save refreshed cookies, log the result
  → exit
```

When auto-apply is enabled, `scheduled_run.py` runs `auto_apply.py` after the
profile refresh. The job worker searches configured title/location pairs,
filters exclusions, and records outcomes in `data/applications.jsonl`. It
deduplicates submitted or uncertain applications and stops at 10 submissions
per local day. Required unanswered form fields are skipped; the worker does not
invent answers. The dashboard can run a search-only preview separately.

## Why headed, not headless

Naukri sits behind Akamai, which blocks headless browsers outright. Every
headless variant tested gets an "Access Denied" page; a headed browser passes.
So a real browser opens, parked off the side of the desktop where nobody sees
it. `HEADFUL=1` brings it on screen.

Where to park it is measured rather than hardcoded. `common.offscreen_args()`
reads the virtual desktop bounds through `GetSystemMetrics` and puts the window
just past the right edge, because a fixed negative position lands in plain view
on a machine whose second monitor sits to the left.

The browser setup.bat downloads is tried first, then Microsoft Edge, then
Chrome. Edge is the safety net: it ships with Windows 10 and 11 and is the same
Chromium underneath. The fallback exists because a downloaded Chrome for
Testing build whose side-by-side manifest Windows will not activate fails to
start with a bare "spawn UNKNOWN", and retrying the same binary never helps.

The block page keeps the requested URL, so a URL-only check would report it as a
healthy profile page. `common.page_state()` reads the body instead.

## Why the headline rotates

Naukri normalises whitespace before storing, so re-saving one headline stores
what was already there and registers as no change. Rotating between two or more
genuinely different variants means every run writes something the server has to
change.

After saving, the run reloads the profile and reads the headline back. If it
does not match what was written, the action fails loudly rather than quietly
doing nothing.

## The survey overlay

Naukri floats a satisfaction survey whose backdrop swallows clicks on the
headline edit control. Removing the nodes does not stick because React re-mounts
them, so a stylesheet rule is injected before the page hydrates. Clicks then
escalate: normal, forced, then a synthetic event.

## Scheduling

`windows_tasks.py` registers two Task Scheduler tasks for the current user,
neither of which needs admin rights: `Naukri Autopilot Update` on a 12, 24 or
48 hour repeat (through `scheduled_run.py`), and `Naukri Autopilot Dashboard`
on a logon trigger when start on login is switched on.

Both are registered from task XML handed to `schtasks /Create /XML`, not from
the command flags, because the flags cannot express the three settings that
matter. `MultipleInstancesPolicy` is `IgnoreNew`, so a slow run never has a
second one stacked on top of it. `StartWhenAvailable` is true, so a slot missed
to sleep or a shutdown runs shortly after you are back instead of being
skipped. `LogonType` is `InteractiveToken`, because the browser is headed and
needs a real desktop to open a window on, which also means runs only fire while
you are logged in.

The XML file is written as UTF-16, which is what schtasks expects, and the
action runs `pythonw.exe` so no console window appears.

Two things to leave alone. The logon trigger carries a `<UserId>`: without one
it means "when anybody logs on", which only an administrator may register, and
it fails with a bare "Access is denied". And reading the interval back has to
accept every ISO 8601 spelling, because Task Scheduler rewrites what it is
given into its own shortest form: `PT24H` comes back as `P1D` and `PT48H` as
`P2D`, so matching only `PT..H` would report a working daily schedule as having
no interval.

## Run history and the chart

Every real run appends one JSON line to `data/runs.jsonl`: when it started, how
it ended (`ok`, `partial`, `failed`, `expired`, `blocked`), what each nudge did,
how long it took, and which platform it ran on (`naukri` for now; older lines
without the field count as Naukri). Sign-in checks are not recorded, since they change nothing.

It is kept apart from `runs.log` on purpose, so the chart never depends on
parsing human-readable log text. A torn last line is skipped rather than
breaking the read, and anything older than 120 days is pruned after each run.

`/api/activity?range=7d|1m|3m` returns the runs in that window. The Home chart
plots one dot per platform per day, that day's most recent run, by date across
and time of day up, 00:00 at the bottom. Dots are green for worked and red for
failed; the tooltip shows that run and lists any earlier runs from the same day
with their own coloured dots. Each platform gets one soft dotted line joining its
days (a monotone curve, so it never loops or overshoots a dot), drawn in the page
ink colour at low opacity. It draws in from the left on load, dots shrink on the
longer ranges, and each dot has a larger invisible hover target. It is a
hand-built SVG, nothing fetched. Configuration lists the platforms; when a second
one lands it gets its own line, and how the lines tell apart is decided then.

## Onboarding

Until setup is finished, Home shows a four step checklist instead of the
dashboard: add a resume, sign in, do a test run, pick a schedule. Each step is
worked out from `/api/status`, so it goes green on its own (resume found,
session saved and not expired, `everWorked` true, schedule installed).
`everWorked` is true when any run in `data/runs.jsonl`, or the last one in
`runs.log`, ended `ok` or `partial`.

Only the current step is active, and its button (Sign in, Run it, or the
12/24/48h schedule choice) sits inside the step. While a job runs the step shows
a spinner instead. A failed test run explains itself under the step: blocked,
failed (with a link to Captures), or expired, which sends you back to sign in.

When all four are done the checklist becomes a "You're all set" card, and
"Go to dashboard" stores `naukri-onboarded` in localStorage. Anyone who opens
the page already fully set up gets that flag silently and never sees the
checklist. "Skip setup for now" sets it too. Pausing the schedule later does not
bring it back.

## Motion

Cards, panels, setting blocks, guide steps and the About
text fade and rise in as they scroll into view, staggered in threes. Guide and
About have the slow drifting colour blobs behind the heading, the New here? card
lifts on hover (using `translate`, so it never fights the reveal), stat values pop on
first load, and the About pull quote grows its accent bar. The reveal class is
added by script with a 1.2s backstop, so nothing stays hidden if an observer
never fires, and all of it is off under reduced motion. The Home cards animate
once only, not on every 8s refresh.

## Windows specifics

Four things behave differently here and are handled rather than hoped about.

**Encoding.** The console code page is not UTF-8, so child processes are
started with `PYTHONIOENCODING=utf-8` and their output is read back as UTF-8
with `errors="replace"`. `setup_logging` reconfigures stdout the same way.
Without it a single accent in a headline or a resume file name ends a run with
a `UnicodeEncodeError`. Config and history are read and written as UTF-8
explicitly, never the machine default.

**No console.** Scheduled runs are launched with `pythonw.exe`, which has no
stdout at all, so the logging stream handler is only attached when there is
somewhere to write to. The log file is always written either way.

**File locking.** Windows keeps a lock on an open file, so `config.json` and
`data/runs.jsonl` are rewritten through a temporary file and `os.replace`,
which is atomic, and deletes retry briefly before giving up. A capture the
dashboard happens to be serving is left for the next prune rather than failing
the run.

**Killing a run.** `terminate()` ends only the Python process and leaves the
browser it launched running with nothing driving it, so Stop shells out to
`taskkill /T /F` and takes down the whole tree.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | at least one nudge landed |
| 1 | everything enabled failed |
| 2 | no saved session |
| 3 | session expired |
| 4 | blocked by bot protection |
| 5 | every action switched off |
| 6 | resume re-upload is on but there is no resume to pick |

## The dashboard

Six pages behind a small history-API router. The guide is deliberately not in
the top nav: a first run modal offers it once, keyed on `naukri-seen-guide` in
localStorage, and after that it lives behind the help box on Configuration.
Its first section is a copy-paste setup prompt for any AI chat, the same text as
in the README, so keep the two in sync. The
modal carries a "Don't show this again" checkbox, ticked by default. Unticking
it means the modal comes back next time.

Theme follows the shared three state pattern: light, dark, and system, where
system means no `data-theme` attribute so the media query decides. The saved
choice is applied by `web/theme.js`, loaded in `<head>` before first paint, keyed
`naukri-theme`. It is a file rather than an inline script so the page can run
under a strict Content Security Policy.

## Security

The dashboard can start runs, change the schedule and edit what gets written to
your Naukri profile, so it only answers the page it serves itself.

- It binds to `127.0.0.1`, never the network.
- Every request must carry a `Host` of `127.0.0.1:PORT` or `localhost:PORT`.
  That blocks DNS rebinding, where a website points its own domain at your
  machine to reach the local server.
- A request with an `Origin` from anywhere else is refused.
- POST requests must be `application/json`. Browsers will not send that
  cross-site without a CORS preflight, and the server never approves one, so no
  other site can trigger a run, a schedule change or a delete.
- Bodies over 64 KB are ignored, numbers in query strings are clamped, run kinds,
  schedule hours and resume names are allowlists, and capture paths are reduced
  to a bare `.png` file name inside `screenshots/`.
- Only `index.html`, `app.js`, `styles.css`, `theme.js` and captures are
  served. `storage_state.json`, `config.json` and `.env` are never reachable.
- Responses carry a strict Content Security Policy (scripts from itself only),
  `X-Frame-Options: DENY`, `nosniff` and `no-referrer`.
- Anything rendered from files or logs is HTML-escaped, quotes included.
- No `shell=True` anywhere; subprocesses get fixed argument lists.

Passwords are never read, typed or stored. You sign in yourself in a real
browser window, and only the resulting session cookies are saved locally.


```
browser  ──HTTP──>  server.py (127.0.0.1 only, standard library)
                      ├── GET  /api/status       session, schedule, last run, config
                      ├── GET  /api/job          incremental output of the running child
                      ├── GET  /api/logs         tail of runs.log
                      ├── GET  /api/screenshots  capture listing
                      ├── GET  /api/activity     runs for the chart, 7d | 1m | 3m
                      ├── POST /api/run          {kind: update | dry | login}
                      ├── POST /api/config       settings
                      ├── POST /api/schedule     {hours: 12 | 24 | 48 | 0}
                      ├── POST /api/autostart    {on: true | false}
                      └── POST /api/screenshots/delete
```

One child process at a time. Output is buffered in memory and polled with a
cursor. The server returns the same shell for every page path, so a deep link or
a reload always lands somewhere real.
