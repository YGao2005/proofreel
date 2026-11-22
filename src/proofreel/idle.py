"""The idle watchdog of a run browser: `python -m proofreel.idle <chrome folder> <idle seconds> <run record>`.

chrome.boot starts it beside Chrome, in the same session. Every proofreel command that uses the run, and the
recorder while it records, touch the beat file. The watchdog ends the run browser when the beat is older than
the idle time, or when Chrome has died. It leaves when the run's pid file is gone or names another Chrome (vm down,
or a newer run). It ends only the Chrome of its own profile folder.
"""

import json
import os
import shutil
import sys
import time
from pathlib import Path

from . import chrome, vm
from .vm import alive

POLL = 1


def stopped(address, message):
    """Mark the run record of this browser, so the next command says why it stopped."""
    if vm.CURRENT.exists():
        record = json.loads(vm.CURRENT.read_text())
        if record.get("screen") == address:
            temp = vm.CURRENT.with_suffix(".tmp")
            temp.write_text(json.dumps({**record, "stopped": message}))
            temp.replace(vm.CURRENT)


def watch(idle):
    """Run until the browser ends. The pid file says which Chrome this watchdog guards."""
    mine = chrome.pidfile().read_text()
    pid, address = mine.split()
    beat = chrome.beat()
    gone = 0
    while True:
        time.sleep(POLL)
        if not chrome.pidfile().exists() or chrome.pidfile().read_text() != mine:
            return
        gone = 0 if alive(int(pid)) else gone + 1
        quiet = time.time() - beat.stat().st_mtime if beat.exists() else 0
        if gone > 1 or quiet > idle:
            break
    minutes = f"{idle / 60:g} min" if idle >= 60 else f"{idle:g} s"
    stopped(address, f"The browser stopped after {minutes} with no proofreel command. Start it again: proofreel vm up web."
            if gone <= 1 else "The browser closed. Start it again: proofreel vm up web.")
    chrome.quit_chrome()
    shutil.rmtree(chrome.folder(vm.MACHINE), ignore_errors=True)
    beat.unlink(missing_ok=True)


if __name__ == "__main__":
    chrome.FOLDER = Path(sys.argv[1])
    vm.CURRENT = Path(sys.argv[3])
    watch(float(sys.argv[2]))
