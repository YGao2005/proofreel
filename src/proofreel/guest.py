"""What differs between guest systems. Each state names its system (`os`): macos, linux, or windows.

A guest owns the jobs that only some systems have: crash reports, a step before a cold save, modifier keys that its
VNC server sends differently or cannot send, the accessibility tree, helpers that run in the guest, and the guest
folder for conditions. A new system, or a new
job for one, is a change in this file only.
"""

import shlex
import time

from . import Problem, crash, swift_tool

TAP_PRESS, TAP_GAP = 0.07, 0.11


class Guest:
    name = ""
    keys = {}
    conditions = ""
    ax = False
    desktop = ""

    def mark(self, run):
        """Mark the session start, so harvest finds only the reports made after it."""

    def harvest(self, run, folder, app, started):
        """The log events for the crash and hang reports made since the mark."""
        return []

    def before_save(self, run):
        """Make the guest ready to stop for a cold save."""

    def hold(self, run, screen, key, seconds):
        """Hold the key. This and tap and press return (first press, last release) in host time."""
        return screen.hold(key, seconds)

    def tap(self, run, screen, key, count):
        """Press and release the key count times, TAP_PRESS seconds down and TAP_GAP seconds apart."""
        return screen.tap(key, count, TAP_PRESS, TAP_GAP)

    def press(self, run, screen, key, down):
        """Only press the key down, or only release it."""
        return screen.press(key, down)


class MacOS(Guest):
    name = "macos"
    # WHY: SSH is up before the desktop; an app opened then fails ("Launch failed", RBS code 5).
    desktop = "pgrep -xq Dock && pgrep -xq Finder"
    # WHY: the VNC server of a Tart macOS guest sends the X11 Meta keys as Option and the Alt keys as Command.
    keys = {"option": "meta", "roption": "rmeta", "command": "alt", "rcommand": "ralt"}
    # WHY: VNC has no Fn key, and a tap sent over VNC loses its timing. keys.swift posts these in the guest.
    modifiers = {"fn", "option", "roption", "command", "rcommand", "control", "rcontrol", "shift", "rshift"}
    conditions = "/Users/Shared/proofreel/conditions"
    ax = True

    def mark(self, run):
        crash.mark(run)

    def harvest(self, run, folder, app, started):
        return crash.harvest(run, folder, app, started)

    def helper(self, run, source, *args, timeout=60):
        """Run a Swift helper of this package in the run VM over SSH. It is compiled on the host, and copied to the
        guest the first time. A process that SSH starts has the Accessibility permission of sshd-keygen-wrapper."""
        binary = swift_tool(source, "-target", "arm64-apple-macos14")
        command = shlex.join([f"./.{binary.name}", *args])
        result = run.ssh(command, check=False, timeout=timeout)
        if result.returncode == 127:
            run.upload(str(binary), f".{binary.name}")
            result = run.ssh(command, check=False, timeout=timeout)
        return result

    def keys_helper(self, run, *args, timeout=30):
        """Returns the host times around the helper: the keys happen in between, within the SSH round trip."""
        started = time.time()
        result = self.helper(run, "keys.swift", *args, timeout=timeout)
        if result.returncode:
            raise Problem(f"Keys: {result.stderr.strip() or f'the helper failed ({result.returncode})'}")
        return started, time.time()

    def hold(self, run, screen, key, seconds):
        if key not in self.modifiers:
            return super().hold(run, screen, key, seconds)
        return self.keys_helper(run, "hold", key, f"{seconds:g}", timeout=seconds + 30)

    def tap(self, run, screen, key, count):
        if key not in self.modifiers:
            return super().tap(run, screen, key, count)
        return self.keys_helper(run, "tap", key, str(count), f"{TAP_PRESS * 1000:g}", f"{TAP_GAP * 1000:g}",
                         timeout=count * (TAP_PRESS + TAP_GAP) + 30)

    def press(self, run, screen, key, down):
        if key not in self.modifiers:
            return super().press(run, screen, key, down)
        return self.keys_helper(run, "down" if down else "up", key)


class Linux(Guest):
    name = "linux"
    desktop = "pgrep -x xfce4-panel >/dev/null || pgrep -x gnome-shell >/dev/null"
    conditions = "/var/tmp/proofreel/conditions"


class Windows(Guest):
    name = "windows"
    desktop = 'powershell -NoProfile -Command "if (Get-Process explorer -ErrorAction SilentlyContinue) { exit 0 } exit 1"'

    def before_save(self, run):
        # WHY: Windows keeps the last screen size and scales it to a new one. With none saved, it fills the screen.
        run.ssh(r"reg delete HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers\Configuration /f", check=False)


GUESTS = {guest.name: guest for guest in (MacOS(), Linux(), Windows())}


def of(info):
    """The guest of a state or a run VM record."""
    if info.get("os") not in GUESTS:
        raise Problem(f"Unknown guest system {info.get('os')!r}. Use one of: {', '.join(GUESTS)}.")
    return GUESTS[info["os"]]
