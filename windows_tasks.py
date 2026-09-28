"""Scheduling and start-on-login, through Windows Task Scheduler.

Two tasks, both registered for the current user only, both needing no admin
rights:

  Naukri Autopilot Update      every 12, 24 or 48 hours
  Naukri Autopilot Dashboard   at logon, if start on login is switched on

Both are registered from task XML rather than the schtasks command flags,
because the flags cannot express the settings that matter here: catching up a
missed start, never stacking two runs, and running on the interactive desktop.

  python windows_tasks.py install 24
  python windows_tasks.py status
  python windows_tasks.py uninstall
  python windows_tasks.py autostart on|off|status
"""
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHONW = ROOT / ".venv" / "Scripts" / "pythonw.exe"

UPDATE_TASK = "Naukri Autopilot Update"
DASHBOARD_TASK = "Naukri Autopilot Dashboard"

ALLOWED_HOURS = (12, 24, 48)

# Keeps a console window from flashing up every time the dashboard polls.
CREATE_NO_WINDOW = 0x08000000


def _run(args):
    """schtasks with a fixed argument list. Never a shell, never a window.

    Output comes back as bytes because the console code page is not UTF-8 and
    a folder name with an accent in it would otherwise raise part way through
    a decode.
    """
    return subprocess.run(
        args,
        capture_output=True,
        timeout=30,
        creationflags=CREATE_NO_WINDOW,
    )


def _text(raw):
    """Decode schtasks output without ever raising.

    /Query /XML hands back UTF-16 on some builds and UTF-8 on others, so the
    BOM decides and anything undecodable is replaced rather than fatal.
    """
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    if raw[:3] == b"\xef\xbb\xbf":
        return raw[3:].decode("utf-8", errors="replace")
    for enc in ("utf-8", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _xml_escape(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# --------------------------------------------------------------------------
# Task XML
# --------------------------------------------------------------------------
# No <UserId> on the principal on purpose. schtasks fills in whoever is
# registering, which avoids having to spell out a domain and user name that
# may not be ASCII.
#
# InteractiveToken is what makes the headed browser possible: the run needs a
# real desktop to open a window on, so the task only fires while you are
# logged on.
_HEAD = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.3" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{desc}</Description>
  </RegistrationInfo>
  <Triggers>
{triggers}
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>{limit}</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{command}</Command>
      <Arguments>{arguments}</Arguments>
      <WorkingDirectory>{workdir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""

# No <Duration> under Repetition means repeat forever, which is what an
# open-ended schedule wants. StartWhenAvailable above is what makes a slot
# missed to sleep or a shutdown run shortly after you are back, instead of
# being skipped until the next one.
_TIME_TRIGGER = """    <TimeTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
      <Repetition>
        <Interval>PT{hours}H</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
    </TimeTrigger>"""

# The UserId here is not optional. A logon trigger without one means "when
# anybody logs on", which only an administrator may register, so leaving it
# out fails with a bare "Access is denied" on a normal account. Naming the
# current user scopes it to this login and needs no admin rights at all.
_LOGON_TRIGGER = """    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{user}</UserId>
      <Delay>PT30S</Delay>
    </LogonTrigger>"""


def current_user():
    """The current account, as a SID where possible.

    A SID sidesteps every question about domain prefixes and non-ASCII user
    names. The readable form is the fallback for the rare case where whoami
    is missing or unreadable.
    """
    try:
        out = _run(["whoami", "/user", "/fo", "csv", "/nh"])
        if out.returncode == 0:
            # "DOMAIN\\user","S-1-5-21-..."
            fields = _text(out.stdout).strip().strip('"').split('","')
            if len(fields) == 2 and fields[1].startswith("S-"):
                return fields[1]
    except Exception:
        pass
    import os

    domain = os.environ.get("USERDOMAIN", "")
    name = os.environ.get("USERNAME", "")
    return f"{domain}\\{name}" if domain else name


def _task_xml(desc, triggers, script, limit):
    return _HEAD.format(
        desc=_xml_escape(desc),
        triggers=triggers,
        limit=limit,
        command=_xml_escape(PYTHONW),
        arguments=_xml_escape(script),
        workdir=_xml_escape(ROOT),
    )


def _register(name, xml):
    """Write the XML and hand it to schtasks.

    The file is UTF-16 with a BOM because schtasks rejects a task file it
    cannot read as Unicode. It is removed again straight after, and the
    delete is best effort so a virus scanner holding the handle open for a
    moment cannot fail a registration that already succeeded.
    """
    fd = tempfile.NamedTemporaryFile(
        mode="w", suffix=".xml", delete=False, encoding="utf-16"
    )
    try:
        fd.write(xml)
        fd.close()
        out = _run(["schtasks", "/Create", "/TN", name, "/XML", fd.name, "/F"])
        if out.returncode != 0:
            return False, _text(out.stdout + out.stderr).strip()
        return True, ""
    finally:
        try:
            Path(fd.name).unlink()
        except OSError:
            pass


def _delete(name):
    out = _run(["schtasks", "/Delete", "/TN", name, "/F"])
    return out.returncode == 0


def _query_xml(name):
    """The task's XML, or None when there is no such task."""
    out = _run(["schtasks", "/Query", "/TN", name, "/XML", "ONE"])
    if out.returncode != 0:
        return None
    return _text(out.stdout)


def _exists(name):
    return _run(["schtasks", "/Query", "/TN", name]).returncode == 0


# --------------------------------------------------------------------------
# The scheduled update
# --------------------------------------------------------------------------
def schedule_install(hours):
    try:
        hours = int(hours)
    except (TypeError, ValueError):
        return False, "Interval must be 12, 24 or 48 hours."
    if hours not in ALLOWED_HOURS:
        return False, "Interval must be 12, 24 or 48 hours."
    if not PYTHONW.is_file():
        return False, "Not set up yet. Run setup.bat first."

    # First slot is one interval out, so switching the schedule on does not
    # immediately fire a run the moment you pick it.
    start = (datetime.now() + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    xml = _task_xml(
        desc=f"Keeps your Naukri profile fresh, every {hours} hours.",
        triggers=_TIME_TRIGGER.format(start=start, hours=hours),
        script="scheduled_run.py",
        limit="PT1H",
    )
    ok, err = _register(UPDATE_TASK, xml)
    if not ok:
        return False, err or "Could not create the scheduled task."
    return True, f"Installed: runs every {hours}h."


def schedule_uninstall():
    _delete(UPDATE_TASK)
    return True, "Removed."


def duration_hours(text):
    """Hours in an ISO 8601 duration, or None if it does not look like one.

    Task Scheduler rewrites what it is given into its own shortest form, so
    the PT24H that went in reads back as P1D and PT48H as P2D. Reading only
    the PT..H spelling would report a perfectly good 24 hour schedule as
    installed with no interval.
    """
    m = re.fullmatch(
        r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?",
        (text or "").strip(),
    )
    if not m or not any(m.groups()):
        return None
    days, hours, minutes, seconds = (int(g or 0) for g in m.groups())
    total = days * 24 + hours + minutes / 60 + seconds / 3600
    return round(total) if total else None


def schedule_info():
    """Interval in hours if the task is registered, else None."""
    try:
        xml = _query_xml(UPDATE_TASK)
        if xml is None:
            return {"installed": False, "hours": None}
        m = re.search(r"<Interval>([^<]+)</Interval>", xml)
        return {"installed": True,
                "hours": duration_hours(m.group(1)) if m else None}
    except Exception:
        return {"installed": False, "hours": None}


# --------------------------------------------------------------------------
# Start on login
# --------------------------------------------------------------------------
def autostart_on():
    try:
        return _exists(DASHBOARD_TASK)
    except Exception:
        return False


def autostart_set(on):
    if not on:
        _delete(DASHBOARD_TASK)
        return False
    if not PYTHONW.is_file():
        return False
    # No time limit: the dashboard is meant to sit there until you log out.
    xml = _task_xml(
        desc="Starts the Naukri Autopilot dashboard when you log in.",
        triggers=_LOGON_TRIGGER.format(user=_xml_escape(current_user())),
        script="server.py",
        limit="PT0S",
    )
    _register(DASHBOARD_TASK, xml)
    return autostart_on()


# --------------------------------------------------------------------------
# Command line, for anyone who would rather not use the dashboard
# --------------------------------------------------------------------------
def _main(argv):
    cmd = argv[0] if argv else "status"
    if cmd == "install":
        ok, msg = schedule_install(argv[1] if len(argv) > 1 else 24)
        print(msg)
        return 0 if ok else 1
    if cmd == "uninstall":
        print(schedule_uninstall()[1])
        return 0
    if cmd == "status":
        info = schedule_info()
        print(f"Runs every {info['hours']}h." if info["installed"] else "Not installed.")
        print("Start on login:", "on" if autostart_on() else "off")
        return 0
    if cmd == "autostart":
        arg = argv[1] if len(argv) > 1 else "status"
        if arg in ("on", "off"):
            print("on" if autostart_set(arg == "on") else "off")
        else:
            print("on" if autostart_on() else "off")
        return 0
    print("usage: python windows_tasks.py install 12|24|48 | status | uninstall"
          " | autostart on|off|status", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
