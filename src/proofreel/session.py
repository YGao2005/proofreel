"""The session folder: the one owner of its format. It reads and logs, and it never imports VM code.

  session.json  {"version": 2, "title", "about", "meta", "app", "conditions", "os", "run", "started", "error"}
  events.jsonl  one event per line: {"t", "end"?, "kind", "text", "x"?, "y"?, "x2"?, "y2"?, "ok"?, "detail"?}.
                [t, end] is when the action affected the screen: a click's press; the first and last key of type,
                key, hold, and tap; a drag's press and release; a wait's or check's first look and its verdict.
  frames/*.jpg  the screen, in name order
  times.txt     "<request> <arrival>": the unix times when each frame was asked for and when it came
  screen.txt    "<width> <height>": the pixel space of event x and y (frames may be smaller)

A folder that an older proofreel wrote is upgraded as it is read, and never written back.
"""

import json
import re
import time
from pathlib import Path

from . import Problem

VERSION = 2
POINTER = {"click", "double", "right", "move", "drag"}
CAMERA = {"click", "double", "right", "drag", "type"}
RING = {"click", "double", "right", "drag"}
CHIP = {"click", "double", "right", "drag", "type", "key", "hold", "tap", "open", "wait", "check"}
VERDICT = {"wait", "check"}
ROW = {"step", "note", "wait", "check"}
HIDDEN = {"move"}
CLICK_LEAD = 0.3


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
