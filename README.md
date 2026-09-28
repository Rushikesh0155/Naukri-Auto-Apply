# Naukri Autopilot for Windows

Keeps your Naukri profile looking fresh, so recruiters keep finding you.

Here is the problem it solves. Naukri sorts recruiter searches by when a profile
was last updated, so if yours has not changed in a week it quietly slides down
the list. Doesn't matter how good it is.

The fix is to open Naukri and change something small. Takes a minute, and it is
very easy to forget. So this does it for you, every day, and saves a screenshot
each time so you can see it actually happened.

It all runs on your PC. No account to make, no server, nothing uploaded
anywhere.

---

## Requirements

- A PC running Windows 10 or 11
- Python 3.9 or newer. Check with `py --version`. If it is missing, get it
  from [python.org](https://www.python.org/downloads/) and tick
  "Add python.exe to PATH" in the installer
- A Naukri account and your resume as a PDF

About 400 MB of disk, mostly the browser it downloads once.

---

## Before you unzip

Windows marks anything that came from the internet, and that mark makes it
block files inside the zip. Clear it once and you will not see a single
warning:

**Right-click the zip, pick Properties, tick Unblock at the bottom, press OK.**
Then extract it.

If you already extracted it and Windows complains, delete the extracted folder,
unblock the zip, and extract it again.

Keep the folder somewhere reasonably short, like your Desktop or
`C:\NaukriAutopilot`. Buried ten folders deep, Windows runs out of path length
partway through setup.

The first time you run `setup.bat`, Windows may show a blue "Windows protected
your PC" box, because the file is new and unsigned. Click **More info**, then
**Run anyway**.

---

## Set it up with an AI

Let an AI do the setup for you. Paste this into an assistant that can run commands
on your PC, like Claude Code or Cursor, and it does the work and only hands you
the parts it can't, like signing in. A regular chat AI works too, it just gives
you commands to paste. The same prompt is on the guide page in the dashboard.

```text
Help me install Naukri Autopilot, a tool on my PC that keeps my Naukri profile fresh by re-uploading my resume and rotating my headline on a schedule.

If you can run commands on my PC, do the setup yourself. If you can't, give me one exact command at a time to paste into Command Prompt, and wait for the result before moving on. Only ask me to do the things you can't do. Keep your messages short.

Setup:
1. Find the Naukri Autopilot folder (ask me where it is if you can't find it) and work from inside it.
2. Check that Python 3.9 or newer is installed with py --version. If it isn't, tell me how to get it from python.org, and remind me to tick "Add python.exe to PATH" in the installer.
3. Run setup.bat. The first time takes a few minutes.
4. Make sure there's a resume PDF in the Resume folder. If there isn't one, ask me to add it.
5. Run dashboard.bat. The dashboard opens at http://127.0.0.1:8777.
6. Ask me to press "Sign in to Naukri" and log in myself in the window that opens.
7. Ask me to press "Run update", then confirm with me that my Naukri profile shows updated today.
8. Ask me to set the schedule to 24 hours on the Configuration page.

Rules:
- Never ask for my Naukri password or OTP. I type those myself.
- If something fails, read the error, fix it if you can, and explain in one line what went wrong.
- Don't change any files except what setup needs.

After that, stay on to help with things like a failed run or an expired session.
```

---

## Setup

**1. Run the setup.** Double-click `setup.bat` in File Explorer.

This sets up a private Python environment and downloads the browser it drives.
Takes a few minutes the first time. You can run it again safely if anything
looks off.

**2. Put your resume in the `Resume` folder.** A PDF, the same one you want on
your profile.

**3. Start the dashboard.** Double-click `dashboard.bat`.

Your browser opens at `http://127.0.0.1:8777`.

The first time, Home is a short setup checklist that walks you through the rest:
resume, sign in, a test run, then a schedule. The steps below are the same thing
in more detail.

**4. Sign in.** Press **Sign in to Naukri** on the Home page. A browser window
opens and you log in yourself, OTP and all. Only the session gets saved. Your
password is never read, stored or typed by this tool.

**5. Do one run.** Press **Run update**, give it about a minute, then open your
Naukri profile and check it says "last updated: Today". Once you have seen that
work, you can trust the schedule.

**6. Pick a schedule.** Configuration page, choose 24 hours.

There is a short guide in the dashboard, under Configuration. It pops up the first
time you open the page, has the AI setup prompt, and answers most of what comes up later.

---

## Everyday use

You do not need to keep the dashboard open. Runs happen on their own.

Open `dashboard.bat` when you want to check on it, change something, or run one
by hand.

Turn on **Start on login** on the Configuration page and the dashboard will always
be there at `http://127.0.0.1:8777`.

### Auto-apply jobs

Auto-apply is separate from profile refresh and is **off by default**. In
Configuration, add job titles or keywords, locations, and optional exclusion
terms, save them, then enable **Submit matching applications**. Use **Preview
jobs** on Home to inspect matching listings without submitting. **Apply jobs
now** starts a real run; scheduled profile runs also apply when the setting is
enabled.

Runs submit at most 10 applications per local calendar day and do not revisit
jobs already submitted. If a listing asks a required question the tool cannot
answer from the page, it skips that application rather than guessing. Only
Naukri-hosted listings are considered; external application links, login
challenges, and bot-protection pages are not handled. Naukri can change its
page layout, so preview the results and check the run output before relying on
scheduled submissions. The application history is kept locally in
`data/applications.jsonl`.

---

## The pages

| Page | What it is for |
|---|---|
| Home | Run now, status, a chart of every run, latest captures, recent activity |
| Captures | A screenshot from every run |
| History | The full run log |
| Configuration | Profile updates, auto-apply filters, schedule, theme, and the guide |
| About | What this is |

---

## Troubleshooting

**"Not set up yet"**. Run `setup.bat` first.

**"Python is not installed"** when it is. The installer probably skipped adding
it to your PATH. Reinstall from python.org and tick "Add python.exe to PATH" on
the first screen.

**Setup stops partway with a path error**. The folder is too deep. Move it
somewhere shorter, like your Desktop, and run `setup.bat` again.

**Port already in use**. Something else has taken port 8777. Add
`DASHBOARD_PORT=8788` to your `.env` file.

**A run failed**. Open the Captures page. Every failure saves a screenshot of
the page it was looking at, which usually makes the reason obvious straight away.

**"Sign in needed"**. Sessions run out every few weeks. Press **Sign in to
Naukri** again and you are done.

**"Access Denied"**. That is Naukri's bot protection, not your login. Leave it
a few hours and try again.

**Nothing ran overnight**. Usually your PC was asleep or off. Runs only fire
while you are logged in, and a missed slot catches up shortly after you are back.

---

## Removing it

1. Set the schedule to **Off** on the Configuration page
2. Turn off **Start on login**
3. Delete this folder

Those two switches remove the only things installed outside this folder, which
are two entries in Windows Task Scheduler.

---

## Your data

Everything stays in this folder:

- `Resume/` your resume
- `storage_state.json` your Naukri session cookies
- `config.json` your settings
- `data/runs.jsonl` one line per run, which the Home chart reads
- `logs/`, `screenshots/` run history

Nothing is sent anywhere except to Naukri itself. The dashboard only listens on
`127.0.0.1`, which is reachable from your machine alone, and it refuses requests
from any other website.

If you share this folder with anyone, leave out `storage_state.json`. It is
your logged-in Naukri session.

---
