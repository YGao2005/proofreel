"""The chrome backend: a headless Chrome on the host, for a web app. No VM and no SSH.

A state is a Chrome profile folder (cookies and storage, so a signed-in state). The built-in state `web` has none: it
starts empty. A run starts from a throwaway copy of the state's profile. Chrome has no window and no sound, and its
DevTools port listens on 127.0.0.1 only. The run record's `screen` is `cdp://127.0.0.1:<port>` (see cdp.py).
PROOFREEL_CHROME_FLAGS adds flags to Chrome's command line.

Chrome outlives the command that starts it, so a watchdog (idle.py) starts with it and ends it after PROOFREEL_IDLE
seconds (default 30 min) with no proofreel command and no recording (the beat file).
"""

import json
import os
import platform
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import Problem, vm
from .cdp import WebScreen, close_browser
from .vm import HOME, MACHINE, alive, free_port

FOLDER = HOME / "chrome"
SIZE = "1440x900"
FLUSH_SECONDS = 6
IDLE_SECONDS = 1800
PLAYWRIGHT = Path.home() / ("Library/Caches" if platform.system() == "Darwin" else ".cache") / "ms-playwright"
GOOGLE_CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
SKIP = shutil.ignore_patterns("Singleton*", "DevToolsActivePort")


def folder(name):
    return FOLDER / name


def pidfile():
    return FOLDER / f"{MACHINE}.pid"


def beat():
    return FOLDER / f"{MACHINE}.beat"


def idle_seconds():
    try:
        return float(os.environ.get("PROOFREEL_IDLE", IDLE_SECONDS))
    except ValueError:
        raise Problem(f"PROOFREEL_IDLE={os.environ['PROOFREEL_IDLE']} is not a number of seconds.") from None


def find_chrome():
    """The Chrome to run: PROOFREEL_CHROME, the newest Chromium of Playwright, Google Chrome, then one on PATH."""
    if given := os.environ.get("PROOFREEL_CHROME"):
        if not os.access(given, os.X_OK):
            raise Problem(f"PROOFREEL_CHROME={given} is not a program.")
        return given
    builds = sorted(PLAYWRIGHT.glob("chromium-*"), key=lambda p: int(p.name.split("-")[1]), reverse=True)
    for path in [*(p for b in builds for p in [*b.glob("chrome-*/chrome"), *b.glob("chrome-*/*/Contents/MacOS/*")]),
                 GOOGLE_CHROME]:
        if os.access(path, os.X_OK):
            return str(path)
    for name in ("chromium", "google-chrome", "chromium-browser"):
        if found := shutil.which(name):
            return found
    raise Problem("No Chrome found. Install Chrome, or: pip install playwright && playwright install chromium")


def exists(name):
    return folder(name).exists()


def base(name, image):
    raise Problem("The chrome backend has no base image. Start from the built-in state: proofreel vm up web.")


def up(name, info, display=None, memory=None, cpu=None, warmable=False):
    if warmable:
        raise Problem("A browser state cannot be warm: it keeps cookies and storage, not open pages.")
    size = display or SIZE
    if not re.fullmatch(r"\d{3,4}x\d{3,4}", size):
        raise Problem(f"--display must be WIDTHxHEIGHT, for example 1440x900, not {size!r}.")
    stop()
    if info.get("builtin"):
        folder(MACHINE).mkdir(parents=True)
    elif exists(name):
        shutil.copytree(folder(name), folder(MACHINE), symlinks=True, ignore=SKIP)
    else:
        raise Problem(f"The profile of state {name} is missing: {folder(name)}.")
    return boot(size)


def boot(size=SIZE):
    """Start Chrome on the run profile, and return the run record once its DevTools port answers."""
    for lock in folder(MACHINE).glob("Singleton*"):
        lock.unlink()
    idle = idle_seconds()
    port = free_port()
    log = FOLDER / f"{MACHINE}.log"
    args = [find_chrome(), "--headless=new", "--remote-debugging-address=127.0.0.1", f"--remote-debugging-port={port}",
            f"--user-data-dir={folder(MACHINE)}", f"--window-size={size.replace('x', ',')}",
            "--force-device-scale-factor=1", "--mute-audio", "--hide-scrollbars", "--no-first-run",
            "--no-default-browser-check", *shlex.split(os.environ.get("PROOFREEL_CHROME_FLAGS", "")), "about:blank"]
    with open(log, "w") as out:
        proc = subprocess.Popen(args, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True)
    address = f"cdp://127.0.0.1:{port}"
    pidfile().write_text(f"{proc.pid} {address}")
    beat().touch()
    subprocess.Popen([sys.executable, "-m", "proofreel.idle", str(FOLDER), str(idle), str(vm.CURRENT)],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    deadline = time.time() + 30
    while True:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as answer:
                json.load(answer)
            break
        except (OSError, ValueError):
            if not alive(proc.pid) or time.time() > deadline:
                raise Problem(f"Chrome did not start: {log.read_text().strip()[-400:] or 'no output'} (see {log}). "
                              f"Flags for Chrome, such as --no-sandbox in a container, go in PROOFREEL_CHROME_FLAGS.") from None
            time.sleep(0.1)
    with WebScreen(address) as screen:
        screen.fit(*map(int, size.split("x")))
    return {"vm": MACHINE, "pid": proc.pid, "screen": address, "screen_password": "", "size": size, "beat": str(beat())}


def host_address(run):
    """Chrome runs on the host: it reaches the host, and the host sees it, at 127.0.0.1."""
    return "127.0.0.1", "127.0.0.1", "127.0.0.1"


def mine(pid):
    """True when the process is a Chrome that runs on the run profile (a pid in an old pid file may be another's)."""
    said = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout
    return f"--user-data-dir={folder(MACHINE)}" in said


def end_helpers():
    """Kill what is left of the run's Chrome (its helpers can outlive it), found by the profile folder in its flags."""
    flag = f"--user-data-dir={folder(MACHINE)}"
    subprocess.run(["pkill", "-KILL", "-f", "--", flag], check=False)
    end = time.time() + 3
    while time.time() < end and not subprocess.run(["pgrep", "-f", "--", flag], capture_output=True).returncode:
        time.sleep(0.05)


def quit_chrome():
    """End the run's Chrome. It is asked to close itself first, so it writes its cookies and storage through its
    helpers; then SIGTERM, then SIGKILL for one that hangs. Last, its helpers."""
    if not pidfile().exists():
        return
    pid, address = pidfile().read_text().split()
    pid = int(pid)
    if alive(pid) and mine(pid):
        for step, seconds in ((lambda: close_browser(address), 10), (lambda: os.kill(pid, signal.SIGTERM), 5),
                              (lambda: os.kill(pid, signal.SIGKILL), 3)):
            step()
            end = time.time() + seconds
            while alive(pid) and time.time() < end:
                time.sleep(0.05)
            if not alive(pid):
                break
    end_helpers()
    pidfile().unlink()
    beat().unlink(missing_ok=True)


def save(name, run, warm):
    if warm:
        raise Problem("A browser state cannot be warm: it keeps cookies and storage, not open pages.")
    # WHY: Chrome writes localStorage up to 5 s after a change and does not flush it when a headless browser closes.
    time.sleep(FLUSH_SECONDS)
    quit_chrome()
    shutil.rmtree(folder(name), ignore_errors=True)
    shutil.copytree(folder(MACHINE), folder(name), symlinks=True, ignore=SKIP)


def resume(name, run, warm):
    return boot(run["size"])


def stop():
    quit_chrome()
    shutil.rmtree(folder(MACHINE), ignore_errors=True)


def drop(name):
    shutil.rmtree(folder(name), ignore_errors=True)
