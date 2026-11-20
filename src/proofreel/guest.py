"""What differs between guest systems. Each state names its system (`os`): macos, linux, or windows.

A guest owns the jobs that only some systems have, or that each system does in its own way: crash reports, a step
before a cold save, modifier keys that its VNC server sends differently or cannot send, the accessibility tree,
helpers that run in the guest and the plugin helpers built for it, how to find a running process, and the folder and shell for plugins (`home`,
`script`, `run_script`). A new system, or a new
job for one, is a change in this file only.
"""

import shlex
import shutil
import time
from pathlib import Path

from . import Problem, crash, swift_tool

TAP_PRESS, TAP_GAP = 0.07, 0.11


def powershell(command):
    """A PowerShell command line that works from Windows OpenSSH's default shell (cmd)."""
    return f'powershell -NoProfile -ExecutionPolicy Bypass -Command "{command}"'


class Guest:
    name = ""
    keys = {}
    home = ""
    ax = False
    desktop = ""

    def script(self, step):
        """The file name of a plugin step's script on this system."""
        return f"{step}.sh"

    def run_script(self, folder, step, values):
        """The shell command that runs a plugin step in its folder, with its values in the environment."""
        env = " ".join(f"{k}={shlex.quote(str(v))}" for k, v in values.items())
        return f"cd {shlex.quote(folder)} && {env} sh {self.script(step)}"

    def fresh_folder(self, path):
        """The shell command that makes an empty folder at path, removing what was there."""
        return f"mkdir -p {shlex.quote(path.rsplit('/', 1)[0])} && rm -rf {shlex.quote(path)}"

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

    def build(self, folder):
        """Build the helpers of a plugin's staged copy on the host, before it goes to the guest."""

    def running(self, run, process):
        """A process with this exact name runs in the run VM."""
        return run.ssh(f"pgrep -x {shlex.quote(process)}", check=False, timeout=30).returncode == 0


class MacOS(Guest):
    name = "macos"
    # WHY: SSH is up before the desktop; an app opened then fails ("Launch failed", RBS code 5).
    desktop = "pgrep -xq Dock && pgrep -xq Finder"
    # WHY: the VNC server of a Tart macOS guest sends the X11 Meta keys as Option and the Alt keys as Command.
    keys = {"option": "meta", "roption": "rmeta", "command": "alt", "rcommand": "ralt"}
    # WHY: VNC has no Fn key, and a tap sent over VNC loses its timing. keys.swift posts these in the guest.
    modifiers = {"fn", "option", "roption", "command", "rcommand", "control", "rcontrol", "shift", "rshift"}
    home = "/Users/Shared/proofreel"
    ax = True

    target = ("-target", "arm64-apple-macos14")

    def mark(self, run):
        crash.mark(run)

    def build(self, folder):
        """Each <name>.swift becomes the binary <name> next to it. With no swiftc on the host, it is left out, and the
        plugin's script says so."""
        if shutil.which("swiftc"):
            for source in Path(folder).glob("*.swift"):
                shutil.copy(swift_tool(source.resolve(), *self.target), source.with_suffix(""))

    def harvest(self, run, folder, app, started):
        return crash.harvest(run, folder, app, started)

    def helper(self, run, source, *args, timeout=60):
        """Run a Swift helper of this package in the run VM over SSH. It is compiled on the host, and copied to the
        guest the first time. A process that SSH starts has the Accessibility permission of sshd-keygen-wrapper."""
        binary = swift_tool(source, *self.target)
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
    home = "/var/tmp/proofreel"


class Windows(Guest):
    name = "windows"
    home = "C:/ProgramData/proofreel"

    def script(self, step):
        return f"{step}.ps1"

    def run_script(self, folder, step, values):
        env = "".join(f"$env:{k} = '{str(v).replace(chr(39), chr(39) * 2)}'; " for k, v in values.items())
        return powershell(f"Set-Location '{folder}'; {env}& .\\{self.script(step)}; exit $LASTEXITCODE")

    def fresh_folder(self, path):
        return powershell(f"Remove-Item -Recurse -Force -ErrorAction SilentlyContinue '{path}'; "
                          f"New-Item -ItemType Directory -Force '{path.rsplit('/', 1)[0]}' | Out-Null")
    desktop = powershell("if (Get-Process explorer -ErrorAction SilentlyContinue) { exit 0 } exit 1")

    def running(self, run, process):
        name = process.removesuffix(".exe").replace("'", "''")
        return run.ssh(powershell(f"if (Get-Process -Name '{name}' -ErrorAction SilentlyContinue) {{ exit 0 }} exit 1"),
                       check=False, timeout=30).returncode == 0

    def before_save(self, run):
        # WHY: Windows keeps the last screen size and scales it to a new one. With none saved, it fills the screen.
        run.ssh(r"reg delete HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers\Configuration /f", check=False)


GUESTS = {guest.name: guest for guest in (MacOS(), Linux(), Windows())}


def of(info):
    """The guest of a state or a run VM record."""
    if info.get("os") not in GUESTS:
        raise Problem(f"Unknown guest system {info.get('os')!r}. Use one of: {', '.join(GUESTS)}.")
    return GUESTS[info["os"]]
