"""The session folder: the one owner of its format. It reads and logs, and it never imports VM code.

  session.json  {"version": 2, "title", "about", "meta", "app", "conditions", "os", "run", "started", "error"}
  events.jsonl  one event per line: {"t", "end"?, "kind", "text", "x"?, "y"?, "x2"?, "y2"?, "ok"?, "detail"?}.
                [t, end] is when the action affected the screen: a click's press; the first and last key of type,
                key, hold, and tap; a drag's press and release; a wait's or check's first look and its verdict.
  frames/*.jpg  the screen, in name order
  times.txt     "<request> <arrival>": the unix times when each frame was asked for and when it came
  screen.txt    "<width> <height>": the pixel space of event x and y (frames may be smaller)

A `state` event names where the app should be. The waits and checks after it, up to the next state, are its checks.

A folder that an older proofreel wrote is upgraded as it is read, and never written back.
"""

import json
import re
import subprocess
import time
from pathlib import Path

from . import Problem

VERSION = 2
POINTER = {"click", "double", "right", "move", "drag"}
CAMERA = {"click", "double", "right", "drag", "type"}
RING = {"click", "double", "right", "drag"}
CHIP = {"click", "double", "right", "drag", "type", "key", "hold", "tap", "open", "wait", "check"}
VERDICT = {"wait", "check"}
ACTS = CHIP - VERDICT
ROW = {"state", "step", "note", "wait", "check"}
HIDDEN = {"move"}
CLICK_LEAD = 0.3


def revision(cwd=None):
    """The git commit of the project in cwd, with a note when a tracked file has changes: "1a2b3c4" or "1a2b3c4,
    uncommitted changes". None outside a git repo."""
    git = lambda *args: subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10)
    try:
        head = git("rev-parse", "--short", "HEAD")
        if head.returncode:
            return None
        return head.stdout.strip() + (", uncommitted changes" if git("status", "--porcelain", "--untracked-files=no").stdout.strip() else "")
    except (OSError, subprocess.TimeoutExpired):
        return None


def moment(event):
    """When the event shows: the verdict of a wait or check, the start of anything else."""
    return event.get("end", event["t"]) if event["kind"] in VERDICT else event["t"]


def upgrade(event):
    """A version 1 event as version 2. Version 1 logged a click before its approach (CLICK_LEAD s early), gave type
    and hold a dur, a drag no end, and a wait the time of its verdict plus how long it waited."""
    event = dict(event)
    if event["kind"] in ("click", "double", "right"):
        event["t"] += CLICK_LEAD
    if "dur" in event:
        event["end"] = event["t"] + event.pop("dur")
    if event["kind"] == "drag":
        event.setdefault("end", event["t"] + 0.6)
    waited = event.pop("waited", None)
    if event["kind"] == "wait":
        if waited is None and (m := re.search(r"after ([\d.]+) s", event.get("detail", ""))):
            waited = float(m[1])
        if waited:
            event["end"], event["t"] = event["t"], event["t"] - waited
    return event


def visits(events, error="", end=None):
    """The run's path through its states: one visit for each state event, until the next one or end. A visit
    passes (ok True) when all its waits and checks pass. It fails when one fails or the run stopped in it. With no
    waits or checks, ok is None: the run said it got there, and nothing checked it."""
    marks = [e for e in events if e["kind"] == "state"]
    path = []
    for i, mark in enumerate(marks):
        until = marks[i + 1]["t"] if i + 1 < len(marks) else end
        checks = [e for e in events if e["kind"] in VERDICT and mark["t"] <= e["t"] and (until is None or e["t"] < until)]
        ok = all(e.get("ok") for e in checks) if checks else None
        if error and i == len(marks) - 1:
            ok = False
        path.append({"name": mark["text"], "t": mark["t"], "end": until, "ok": ok})
    return path


def path_line(path):
    """A run's path in one line, for the agent: States: Home ok → Sign in FAIL."""
    words = {True: "ok", False: "FAIL", None: "not checked"}
    return "States: " + " → ".join(f"{v['name']} {words[v['ok']]}" for v in path)


class Session:
    def __init__(self, folder):
        self.folder = Path(folder)

    @property
    def info(self):
        path = self.folder / "session.json"
        info = json.loads(path.read_text()) if path.exists() else {}
        if info.get("version", 1) > VERSION:
            raise Problem(f"{self.folder.name} was made by a newer proofreel (format {info['version']}). Update it.")
        return info

    def events(self):
        """Every event as version 2, in time order."""
        path = self.folder / "events.jsonl"
        events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
        if self.info.get("version", 1) < 2:
            events = [upgrade(event) for event in events]
        return sorted(events, key=lambda event: event["t"])

    def frames(self):
        """(paths, request times, arrival times), in time order. A version 1 folder has request times only."""
        paths = sorted((self.folder / "frames").glob("*.jpg"))
        rows = [line.split() for line in (self.folder / "times.txt").read_text().splitlines() if line.strip()]
        rows = sorted((float(row[0]), float(row[-1]), path) for row, path in zip(rows, paths))
        if not rows:
            raise Problem(f"No frames in {self.folder / 'frames'}.")
        return [row[2] for row in rows], [row[0] for row in rows], [row[1] for row in rows]

    def screen_width(self):
        path = self.folder / "screen.txt"
        return int(path.read_text().split()[0]) if path.exists() else None

    def log(self, kind, text, t=None, end=None, **fields):
        """Add one event. end is left out when the event has no length."""
        t = t or time.time()
        event = {"t": t, **({"end": end} if end and end - t >= 0.01 else {}), "kind": kind, "text": text, **fields}
        with open(self.folder / "events.jsonl", "a") as out:
            out.write(json.dumps(event) + "\n")
