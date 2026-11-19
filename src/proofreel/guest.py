"""What differs between guest systems. Each state names its system (`os`): macos, linux, or windows.

A guest owns the jobs that only some systems have: crash reports, a step before a cold save, modifier keys that its
VNC server sends differently or cannot send, the accessibility tree, helpers that run in the guest, and the guest
folder for conditions. A new system, or a new
job for one, is a change in this file only.
"""

import shlex
import sys

from . import crash, swift_tool, vm

TAP_PRESS, TAP_GAP = 0.07, 0.11


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

    def hold(self, screen, key, seconds):
        screen.hold(key, seconds)

    def tap(self, screen, key, count):
        """Press and release the key count times, TAP_PRESS seconds down and TAP_GAP seconds apart."""
        screen.tap(key, count, TAP_PRESS, TAP_GAP)

    def press(self, screen, key, down):
        """Only press the key down, or only release it."""
        screen.press(key, down)


class MacOS(Guest):
    name = "macos"
    # WHY: the VNC server of a Tart macOS guest sends the X11 Meta keys as Option and the Alt keys as Command.
    keys = {"option": "meta", "roption": "rmeta", "command": "alt", "rcommand": "ralt"}
    # WHY: VNC has no Fn key, and a tap sent over VNC loses its timing. keys.swift posts these in the guest.
    modifiers = {"fn", "option", "roption", "command", "rcommand", "control", "rcontrol", "shift", "rshift"}
    conditions = "/Users/Shared/proofreel/conditions"
    ax = True

    def mark(self):
        crash.mark()

    def harvest(self, folder, app, started):
        return crash.harvest(folder, app, started)

    def helper(self, source, *args, timeout=60):
        """Run a Swift helper of this package in the run VM over SSH. It is compiled on the host, and copied to the
        guest the first time. A process that SSH starts has the Accessibility permission of sshd-keygen-wrapper."""
        binary = swift_tool(source, "-target", "arm64-apple-macos14")
        command = shlex.join([f"./.{binary.name}", *args])
        result = vm.ssh(command, check=False, timeout=timeout)
        if result.returncode == 127:
            vm.put(str(binary), f".{binary.name}")
            result = vm.ssh(command, check=False, timeout=timeout)
        return result

    def keys_helper(self, *args, timeout=30):
        result = self.helper("keys.swift", *args, timeout=timeout)
        if result.returncode:
            sys.exit(f"Keys: {result.stderr.strip() or f'the helper failed ({result.returncode})'}")

    def hold(self, screen, key, seconds):
        if key not in self.modifiers:
            return super().hold(screen, key, seconds)
        self.keys_helper("hold", key, f"{seconds:g}", timeout=seconds + 30)

    def tap(self, screen, key, count):
        if key not in self.modifiers:
            return super().tap(screen, key, count)
        self.keys_helper("tap", key, str(count), f"{TAP_PRESS * 1000:g}", f"{TAP_GAP * 1000:g}",
                         timeout=count * (TAP_PRESS + TAP_GAP) + 30)

    def press(self, screen, key, down):
        if key not in self.modifiers:
            return super().press(screen, key, down)
        self.keys_helper("down" if down else "up", key)


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
