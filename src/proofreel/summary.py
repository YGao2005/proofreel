"""What an agent reads after a run, instead of the frames: the checks that failed, and the words that appeared on the
screen and went from it in each step.

The text of the screen is saved at the start, before each `step` and `state`, and before `stop`, when an action
happened since the last time. Each save is one line of screens.jsonl in the session folder: {"t", "lines"}. A step
is the time between two saves. A browser screen gives its text exactly; any other screen is read by OCR.
"""

import json
import time
from pathlib import Path

from .session import CHIP, Session

FILE = "screens.jsonl"
SHOWN, GONE, WIDTH = 6, 4, 60


def saves(folder):
    path = Path(folder) / FILE
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def save(folder, lines, force=False):
    """Save the screen's text lines, when an action happened since the last save (or force)."""
    done = saves(folder)
    if not force and done and not any(e["kind"] in CHIP and e["t"] >= done[-1]["t"] for e in Session(folder).events()):
        return
    with open(Path(folder) / FILE, "a") as out:
        out.write(json.dumps({"t": time.time(), "lines": [line["text"] for line in lines]}) + "\n")


def short(text):
    return text if len(text) <= WIDTH else text[:WIDTH - 1] + "…"


def listed(prefix, texts, limit):
    if not texts:
        return ""
    more = f" (+{len(texts) - limit} more)" if len(texts) > limit else ""
    return f" {prefix} " + " | ".join(short(t) for t in texts[:limit]) + more


def steps(folder):
    """One line for each step in which the screen text changed."""
    events, rows, before = Session(folder).events(), [], []
    names = [e for e in events if e["kind"] == "step"]
    for number, now in enumerate(saves(folder)):
        if number:
            name = next((e["text"] for e in reversed(names) if e["t"] < now["t"]), "the run")
            seen = set(before)
            appeared = [t for t in now["lines"] if t not in seen]
            gone = [t for t in before if t not in set(now["lines"])]
            rows.append(f"{len(rows) + 1}. {name}:" + (listed("appeared:", appeared, SHOWN) + listed("gone:", gone, GONE)
                                                       or " the text did not change"))
        before = now["lines"]
    return rows


def text(folder):
    """The summary: the count of checks, each failed check with its detail, and the steps."""
    checks = [e for e in Session(folder).events() if e["kind"] == "check" and e.get("ok") is not None]
    failed = [e for e in checks if not e.get("ok")]
    out = [f"Checks: {len(checks) - len(failed)} pass, {len(failed)} fail."]
    out += [f"Fail: {e['text']}" + (f" ({e['detail']})" if e.get("detail") else "") for e in failed]
    if rows := steps(folder):
        out += ["Screen text by step:", *rows]
    return "\n".join(out)
