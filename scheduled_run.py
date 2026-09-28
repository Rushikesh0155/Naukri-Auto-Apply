"""Run the normal profile refresh and any explicitly enabled job applications."""
import subprocess
import sys

from common import ROOT, load_config


def main():
    update = subprocess.run([sys.executable, "update_profile.py"], cwd=ROOT)
    if not load_config()["autoApply"]["enabled"]:
        return update.returncode
    apply = subprocess.run([sys.executable, "auto_apply.py"], cwd=ROOT)
    return apply.returncode or update.returncode


if __name__ == "__main__":
    sys.exit(main())