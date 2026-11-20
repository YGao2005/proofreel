"""Drive a VNC screen as a person does, and read its text.

Coordinates are screen pixels of the VNC framebuffer (on a Retina macOS guest, 2x the points).
"""

import json
import platform
import shutil
import subprocess
import tempfile
import time
import unicodedata
from pathlib import Path

from vncdotool import api
from vncdotool.client import KEYMAP

from . import Problem, swift_tool

SHIFTED = dict(zip('~!@#$%^&*()_+{}|:"<>?', "`1234567890-=[]\\;',./"))
GLIDE, GLIDE_STEPS, GLIDE_SECONDS = (40, 24), 10, 0.15
FRAME_WAITS = (2, 4, 8)


class Screen:
    def __init__(self, server, password=None, keys=None):
        """keys: key names that this screen's VNC server needs as other names (see guest.py)."""
        self.server, self.password, self.keys = server, password, keys or {}
        self.fresh = False

    def __enter__(self):
        self.connect()
        return self

    def connect(self):
        self.client = api.connect(self.server, password=self.password or None, timeout=30)

    def __exit__(self, *_):
        self.client.disconnect()

    def approach(self, x, y, rest):
        """Glide in from a little way off in small steps, then rest, as a hand does. A pointer that jumps into a small
        target can miss its hover: AppKit tracking areas (SwiftUI onHover) see no mouse-entered."""
        x0, y0 = max(0, x - GLIDE[0]), max(0, y - GLIDE[1])
        for i in range(1, GLIDE_STEPS + 1):
            self.client.mouseMove(x0 + (x - x0) * i // GLIDE_STEPS, y0 + (y - y0) * i // GLIDE_STEPS)
            time.sleep(GLIDE_SECONDS / GLIDE_STEPS)
        arrived = time.time()
        time.sleep(rest)
        return arrived

    def move(self, x, y):
        return self.approach(x, y, rest=0.3), None

    def click(self, x, y, button=1, count=1):
        """Approach the target, press, then rest: some apps need hover before a click, and keys sent at once after a
        click that moves the focus can be lost (Chromium on Linux drops the first one)."""
        self.approach(x, y, rest=0.15)
        pressed = time.time()
        for _ in range(count):
            self.client.mousePress(button)
        released = time.time()
        time.sleep(0.2)
        return pressed, released

    def drag(self, x1, y1, x2, y2, steps=12):
        self.client.mouseMove(x1, y1)
        self.client.mouseDown(1)
        pressed = time.time()
        time.sleep(0.2)
        for i in range(1, steps + 1):
            self.client.mouseMove(x1 + (x2 - x1) * i // steps, y1 + (y2 - y1) * i // steps)
            time.sleep(0.03)
        time.sleep(0.2)
        self.client.mouseUp(1)
        return pressed, time.time()

    def type(self, text, delay=0.04):
        first = last = time.time()
        for index, char in enumerate(text):
            if char == " ":
                key = "space"
            elif char == "\n":
                key = "enter"
            elif char.isupper():
                key = f"shift-{char}"
            elif char in SHIFTED:
                key = f"shift-{SHIFTED[char]}"
            else:
                key = char
            last = time.time()
            first = last if index == 0 else first
            self.client.keyPress(key)
            time.sleep(delay)
        return first, last

    def name(self, keys):
        """A key or a combo such as command-a, in the names that this screen's VNC server needs."""
        parts = [self.keys.get(part, part) for part in keys.split("-")] if keys != "-" else ["-"]
        if unknown := [part for part in parts if len(part) != 1 and part not in KEYMAP]:
            names = sorted(k for k in KEYMAP if len(k) > 1 and not k.startswith("k") and not k[1:].isdigit() or
                           k in [f"f{n}" for n in range(1, 13)])
            raise Problem(f"Unknown key {unknown[0]!r}. Use a letter, a symbol, or one of: {', '.join(names)}.")
        return "-".join(parts)

    def key(self, *keys):
        names = [self.name(key) for key in keys]
        first = last = time.time()
        for index, name in enumerate(names):
            last = time.time()
            first = last if index == 0 else first
            self.client.keyPress(name)
            time.sleep(0.05)
        return first, last

    def hold(self, key, seconds):
        pressed, _ = self.press(key, True)
        time.sleep(seconds)
        released, _ = self.press(key, False)
        return pressed, released

    def tap(self, key, count, press, gap):
        first = None
        for index in range(count):
            if index:
                time.sleep(gap)
            pressed, _ = self.press(key, True)
            first = first or pressed
            time.sleep(press)
            released, _ = self.press(key, False)
        return first, released

    def press(self, key, down):
        name = self.name(key)
        at = time.time()
        (self.client.keyDown if down else self.client.keyUp)(name)
        return at, None

    def size(self):
        """The framebuffer size in pixels. pause(0) waits for the connection, which sets it."""
        self.client.pause(0)
        return self.client.protocol.width, self.client.protocol.height

    def capture(self, path):
        """A full frame. Apple Virtualization's VNC server (Tart and UTM macOS guests) answers a full-frame request
        on a connection only once while the screen stays still, as it does with a menu or a file dialog open. A new
        connection always gets a frame, so after a request that gets nothing, each capture uses a new connection."""
        error = None
        for wait in FRAME_WAITS:
            try:
                if self.fresh or error:
                    self.reconnect()
                self.client.timeout = wait
                self.client.refreshScreen(incremental=False)
                break
            except Exception as problem:
                self.fresh, error = True, problem
                time.sleep(wait / 4)
        else:
            raise Problem(f"The VNC screen {self.server} sent no frame in {len(FRAME_WAITS)} tries ({error!r}). "
                          f"Check that the VM runs (proofreel vm up <state>), then run the step again.")
        self.client.timeout = 30
        self.client.screen.save(str(path))

    def reconnect(self):
        """Drop the connection, with any late answer on it, and open a new one."""
        try:
            self.client.disconnect()
        except Exception:
            pass
        self.connect()


def ocr_helper():
    """Apple Vision text recognition on macOS (compiled once), else Tesseract."""
    if platform.system() == "Darwin" and shutil.which("swiftc"):
        return [str(swift_tool("ocr.swift"))]
    if shutil.which("tesseract"):
        return None
    raise Problem("Text recognition needs macOS (swiftc) or tesseract on PATH.")


def read_text(png):
    """The text lines in a screenshot: [{text, x, y, w, h, words: [{text, x, y, w, h}]}] in pixels, top to bottom."""
    helper = ocr_helper()
    if helper:
        lines = json.loads(subprocess.run([*helper, str(png)], check=True, capture_output=True, text=True).stdout)
    else:
        lines = _tesseract(png)
    return sorted(lines, key=lambda line: (line["y"], line["x"]))


def _tesseract(png):
    out = subprocess.run(["tesseract", str(png), "-", "tsv"], check=True, capture_output=True, text=True).stdout
    lines = {}
    for row in out.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or not cols[11].strip():
            continue
        key = tuple(cols[2:5])
        x, y, w, h = (int(v) for v in cols[6:10])
        line = lines.setdefault(key, {"text": "", "x": x, "y": y, "r": x + w, "b": y + h, "words": []})
        line["text"] = (line["text"] + " " + cols[11]).strip()
        line["words"].append({"text": cols[11], "x": x, "y": y, "w": w, "h": h})
        line["r"], line["b"] = max(line["r"], x + w), max(line["b"], y + h)
        line["y"] = min(line["y"], y)
    return [{"text": v["text"], "x": v["x"], "y": v["y"], "w": v["r"] - v["x"], "h": v["b"] - v["y"], "words": v["words"]}
            for v in lines.values()]


def screen_text(screen):
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "screen.png"
        screen.capture(png)
        return read_text(png)


def wrapped(lines):
    """The lines, plus each line joined with the line under it, so a phrase that wraps can be found."""
    joined = []
    for line, below in zip(lines, lines[1:]):
        if 0 < below["y"] - line["y"] < 2 * line["h"] and abs(below["x"] - line["x"]) < 3 * line["h"]:
            joined.append({**line, "text": f"{line['text']} {below['text']}",
                           "words": line.get("words", []) + below.get("words", [])})
    return lines + joined


# WHY: Apple Vision can read Latin words as Cyrillic or Greek letters that look the same ("Acme" as "Асте"), even with
# English as its only language (a lower-case "т" for "m"). Matching folds both sides, so the look of the text decides.
LOOKALIKE = str.maketrans("аВсеЕһіјКМНорРСТтхуАΑΒΕΗΙΚΜΝΟΡΤΧΥΖνοτ", "aBceEhijKMHopPCTmxyAABEHIKMNOPTXYZvot")


def fold(text):
    return unicodedata.normalize("NFKC", text).translate(LOOKALIKE).lower().strip()


def inside(point, box):
    return box[0] <= point[0] < box[0] + box[2] and box[1] <= point[1] < box[1] + box[3]


def matches(lines, text, box=None):
    """Lines that are the text, then lines that contain it, cut to the words that hold it. Case and look-alike
    letters are ignored. A phrase may wrap onto a second line. box (x, y, w, h) keeps the matches in it."""
    lines = wrapped(lines)
    want = fold(text)
    exact = [line for line in lines if fold(line["text"]) == want]
    found = exact + [narrowed(line, want) for line in lines if want in fold(line["text"]) and line not in exact]
    return [match for match in found if box is None or inside(center(match), box)]


def narrowed(line, want):
    """The line cut to the words that hold the text, so a click on "Try again" in "Wrong password. Try again"
    lands on the button. A line with no word boxes stays whole."""
    words, starts, at = line.get("words") or [], [], 0
    for word in words:
        starts.append(at)
        at += len(fold(word["text"])) + 1
    start = " ".join(fold(word["text"]) for word in words).find(want)
    hit = [w for w, s in zip(words, starts) if start >= 0 and s < start + len(want) and s + len(fold(w["text"])) > start]
    if not hit:
        return line
    x, y = min(w["x"] for w in hit), min(w["y"] for w in hit)
    return {**line, "text": " ".join(w["text"] for w in hit), "x": x, "y": y,
            "w": max(w["x"] + w["w"] for w in hit) - x, "h": max(w["y"] + w["h"] for w in hit) - y}


def find(screen, text, within=None):
    """matches() on the screen now. within() gives the box to look in, or raises Problem when it has none."""
    return matches(screen_text(screen), text, within() if within else None)


def poll(look, seconds, present=True):
    """Call look() until it finds something (or nothing, when present is False) or the seconds pass. A Problem from
    look() counts as nothing found until the end, when it is raised: a box that is not there is not a pass."""
    end = time.time() + seconds
    while True:
        missing = None
        try:
            found = look()
        except Problem as problem:
            found, missing = [], problem
        if bool(found) == present and not missing or time.time() > end:
            if missing:
                raise missing
            return found
        time.sleep(0.8)


def wait_for(screen, text, seconds, present=True, within=None):
    return poll(lambda: find(screen, text, within), seconds, present)


def center(line):
    return line["x"] + line["w"] // 2, line["y"] + line["h"] // 2
