"""Drive a VNC screen as a person does, and read its text.

Coordinates are screen pixels of the VNC framebuffer (on a Retina macOS guest, 2x the points).
"""

import json
import platform
import shutil
import subprocess
import tempfile
import time
from importlib import resources
from pathlib import Path

from vncdotool import api

from . import __version__

SHIFTED = dict(zip('~!@#$%^&*()_+{}|:"<>?', "`1234567890-=[]\\;',./"))
HOME = Path.home() / ".proofreel"


class Screen:
    def __init__(self, server, password=None):
        self.server, self.password = server, password

    def __enter__(self):
        self.client = api.connect(self.server, password=self.password or None, timeout=30)
        return self

    def __exit__(self, *_):
        self.client.disconnect()

    def move(self, x, y):
        self.client.mouseMove(x, y)

    def click(self, x, y, button=1, count=1):
        """Approach the target, rest, then press: some apps need hover before a click."""
        self.client.mouseMove(x - 6, y - 6)
        time.sleep(0.15)
        self.client.mouseMove(x, y)
        time.sleep(0.15)
        for _ in range(count):
            self.client.mousePress(button)

    def drag(self, x1, y1, x2, y2, steps=12):
        self.client.mouseMove(x1, y1)
        self.client.mouseDown(1)
        time.sleep(0.2)
        for i in range(1, steps + 1):
            self.client.mouseMove(x1 + (x2 - x1) * i // steps, y1 + (y2 - y1) * i // steps)
            time.sleep(0.03)
        time.sleep(0.2)
        self.client.mouseUp(1)

    def type(self, text, delay=0.04):
        for char in text:
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
            self.client.keyPress(key)
            time.sleep(delay)

    def key(self, *keys):
        for key in keys:
            self.client.keyPress(key)
            time.sleep(0.05)

    def capture(self, path):
        """A full frame. captureScreen waits for an update, and some servers send none on a still screen."""
        self.client.refreshScreen(incremental=False)
        self.client.screen.save(str(path))


def ocr_helper():
    """Apple Vision text recognition on macOS (compiled once), else Tesseract."""
    if platform.system() == "Darwin" and shutil.which("swiftc"):
        binary = HOME / f"bin/proofreel-ocr-{__version__}"
        source = resources.files("proofreel").joinpath("ocr.swift")
        if not binary.exists():
            binary.parent.mkdir(parents=True, exist_ok=True)
            with resources.as_file(source) as path:
                subprocess.run(["swiftc", "-O", str(path), "-o", str(binary)], check=True, capture_output=True)
        return [str(binary)]
    if shutil.which("tesseract"):
        return None
    raise SystemExit("Text recognition needs macOS (swiftc) or tesseract on PATH.")


def read_text(png):
    """The text lines in a screenshot: [{text, x, y, w, h}] in pixels, top to bottom."""
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
        line = lines.setdefault(key, {"text": "", "x": x, "y": y, "r": x + w, "b": y + h})
        line["text"] = (line["text"] + " " + cols[11]).strip()
        line["r"], line["b"] = max(line["r"], x + w), max(line["b"], y + h)
        line["y"] = min(line["y"], y)
    return [{"text": v["text"], "x": v["x"], "y": v["y"], "w": v["r"] - v["x"], "h": v["b"] - v["y"]}
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
            joined.append({**line, "text": f"{line['text']} {below['text']}"})
    return lines + joined


def find(screen, text):
    """Lines that are the text, then lines that contain it. Case is ignored. A phrase may wrap onto a second line."""
    lines = wrapped(screen_text(screen))
    want = text.lower().strip()
    exact = [line for line in lines if line["text"].strip().lower() == want]
    return exact + [line for line in lines if want in line["text"].lower() and line not in exact]


def wait_for(screen, text, seconds, present=True):
    end = time.time() + seconds
    while True:
        found = find(screen, text)
        if bool(found) == present or time.time() > end:
            return found
        time.sleep(0.8)


def center(line):
    return line["x"] + line["w"] // 2, line["y"] + line["h"] // 2
