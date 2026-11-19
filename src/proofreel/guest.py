"""What differs between guest systems. Each state names its system (`os`): macos, linux, or windows.

A guest owns the jobs that only some systems have: crash reports, a step before a cold save, modifier keys that its
VNC server sends differently, the accessibility tree, and the guest folder for conditions. A new system, or a new
job for one, is a change in this file only.
"""

import sys

from . import crash, vm


class Guest:
    name = ""
    keys = {}
    conditions = ""
    ax = False

    def mark(self):
        """Mark the session start, so harvest finds only the reports made after it."""

    def harvest(self, folder, app, started):
        """The log events for the crash and hang reports made since the mark."""
        return []

    def before_save(self, run):
        """Make the guest ready to stop for a cold save."""


class MacOS(Guest):
    name = "macos"
    # WHY: the VNC server of a Tart macOS guest sends the X11 Meta keys as Option and the Alt keys as Command.
    keys = {"option": "meta", "roption": "rmeta", "command": "alt", "rcommand": "ralt"}
    conditions = "/Users/Shared/proofreel/conditions"
    ax = True

    def mark(self):
        crash.mark()

    def harvest(self, folder, app, started):
        return crash.harvest(folder, app, started)


class Linux(Guest):
    name = "linux"
    conditions = "/var/tmp/proofreel/conditions"


class Windows(Guest):
    name = "windows"

    def before_save(self, run):
        # WHY: Windows keeps the last screen size and scales it to a new one. With none saved, it fills the screen.
        vm.ssh(r"reg delete HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers\Configuration /f", check=False,
               run=run)


GUESTS = {guest.name: guest for guest in (MacOS(), Linux(), Windows())}


def of(info):
    """The guest of a state or a run VM record."""
    if info.get("os") not in GUESTS:
        sys.exit(f"Unknown guest system {info.get('os')!r}. Use one of: {', '.join(GUESTS)}.")
    return GUESTS[info["os"]]
