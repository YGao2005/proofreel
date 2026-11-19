"""Make the review video, thumbnails, and page of a session folder.

A session folder holds:
  session.json   {"title", "about", "meta": {label: value}, "error"}
  events.jsonl   one action per line: {"t": unix time, "kind", "text", "x", "y", "ok", "detail"}
  frames/*.jpg   the screen, in name order
  times.txt      the unix time of each frame, one per line
  screen.txt     "<width> <height>": the pixel space of event x and y (frames may be smaller)
"""

import json
import multiprocessing
import re
import os
import subprocess
import sys
from bisect import bisect_right
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from . import draw, page
from .motion import FAST, FPS, Camera, Pointer, ease, fit, spans

CHANGED = 1.5
INSET = 0.88
CHIP_KINDS = {"click", "double", "right", "drag", "type", "key", "open", "scroll", "wait", "check"}
SHOT_KINDS = CHIP_KINDS - {"scroll"}


def load(folder):
    info = json.loads((folder / "session.json").read_text()) if (folder / "session.json").exists() else {}
    log = folder / "events.jsonl"
    events = [json.loads(line) for line in log.read_text().splitlines() if line.strip()] if log.exists() else []
    frames = sorted((folder / "frames").glob("*.jpg"))
    times = [float(t) for t in (folder / "times.txt").read_text().split()][: len(frames)]
    pairs = sorted(zip(times, frames[: len(times)]))
    times, frames = [t for t, _ in pairs], [f for _, f in pairs]
    if not frames:
        sys.exit(f"No frames in {folder / 'frames'}")
    return info, events, frames, times


def screen_changes(frames, times, start):
    changes, before = [], None
    for path, t in zip(frames, times):
        small = Image.open(path).convert("L").resize((96, 64))
        if before is not None and ImageStat.Stat(ImageChops.difference(small, before)).mean[0] > CHANGED:
            changes.append(t - start)
        before = small
    return changes


def relative(events, start, scale):
    out = []
    for e in events:
        e = dict(e, t=e["t"] - start)
        if e["kind"] == "wait" and "waited" not in e and (m := re.search(r"after ([\d.]+) s", e.get("detail", ""))):
            e["waited"] = float(m[1])
        for key in ("x", "y", "x2", "y2"):
            if key in e:
                e[key] = e[key] * scale
        out.append(e)
    return out


def chip_text(e):
    if e["kind"] == "check":
        return ("Pass: " if e.get("ok") else "Fail: ") + e["text"]
    if e["kind"] == "key":
        return draw.keys_label(e["text"].removeprefix("key "))
    return e["text"]


class Scene:
    """Draws one video frame: the screen in its frame, the camera view, the pointer, rings, and labels."""

    def __init__(self, size, out_size, events, framed):
        self.events = events
        self.out = out_size
        self.ui = out_size[0] / 1440
        inset = INSET if framed else 1.0
        self.k = inset * min(out_size[0] / size[0], out_size[1] / size[1])
        self.screen = (int(size[0] * self.k) // 2 * 2, int(size[1] * self.k) // 2 * 2)
        self.offset = ((out_size[0] - self.screen[0]) // 2, (out_size[1] - self.screen[1]) // 2)
        self.framed = framed
        if framed:
            radius = int(12 * self.ui)
            box = (*self.offset, self.offset[0] + self.screen[0], self.offset[1] + self.screen[1])
            self.backdrop = draw.backdrop(out_size, box, radius)
            self.mask = draw.rounded_mask(self.screen, radius)
        canvas_events = [self._event_to_canvas(e) for e in events]
        self.pointer = Pointer(canvas_events, out_size)
        self.camera = Camera(canvas_events, self.pointer, out_size)
        self.steps = [e for e in events if e["kind"] == "step"]
        self.chips = [e for e in events if e["kind"] in CHIP_KINDS]
        self.clicks = [e for e in canvas_events if e["kind"] in ("click", "double", "right", "drag")]

    def _event_to_canvas(self, e):
        e = dict(e)
        for kx, ky in (("x", "y"), ("x2", "y2")):
            if kx in e:
                e[kx] = self.offset[0] + e[kx] * self.k
                e[ky] = self.offset[1] + e[ky] * self.k
        return e

    def compose(self, frame):
        screen = frame.resize(self.screen, Image.LANCZOS) if frame.size != self.screen else frame
        if not self.framed:
            return screen.convert("RGBA")
        canvas = self.backdrop.copy()
        canvas.paste(screen, self.offset, self.mask)
        return canvas

    def render(self, canvas, now, speed, box):
        left, top, w, h = box
        z = self.out[0] / w
        if z > 1.001:
            view = canvas.resize(self.out, Image.BICUBIC, box=(left, top, left + w, top + h))
        else:
            view = canvas.copy()
        to_view = lambda x, y: ((x - left) * z, (y - top) * z)
        self._rings(view, now, z, to_view)
        self._pointer(view, now, z, to_view)
        self._labels(view, now, speed)
        return view.convert("RGB")

    def _rings(self, view, now, z, to_view):
        for e in self.clicks:
            age = now - e["t"]
            if 0 <= age < 0.55:
                k = ease(age / 0.55)
                sprite, half = draw.ring((6 + 30 * k) * self.ui * z ** 0.5, 1 - k, self.ui)
                x, y = to_view(e["x"], e["y"])
                draw.paste(view, sprite, x - half, y - half)

    def _pointer(self, view, now, z, to_view):
        pressed = any(0 <= now - e["t"] < 0.16 for e in self.clicks)
        x, y = to_view(*self.pointer.at(now))
        scale = round(1.25 * self.ui * z ** 0.6, 2)
        sprite, pad = draw.pointer(scale, pressed)
        draw.paste(view, sprite, x - pad, y - pad)

    def _labels(self, view, now, speed):
        ui = self.ui
        margin = int(24 * ui)
        step_index = bisect_right([s["t"] for s in self.steps], now) - 1
        if step_index >= 0:
            step = self.steps[step_index]
            alpha = ease((now - step["t"]) / 0.3)
            sprite = draw.pill(step["text"], int(22 * ui), lead=str(step_index + 1))
            draw.paste(view, sprite, (self.out[0] - sprite.width) / 2, self.out[1] - sprite.height - margin, alpha)
        recent = [e for e in self.chips if 0 <= now - e["t"] < 1.8 + e.get("dur", 0)]
        if recent:
            e = recent[-1]
            age = now - e["t"]
            alpha = ease(age / 0.15) * (1 - ease((age - 1.5 - e.get("dur", 0)) / 0.3))
            color = {True: draw.PASS + (235,), False: draw.FAIL + (235,)}.get(e.get("ok") if e["kind"] in ("check", "wait") else None,
                                                                                draw.INK + (215,))
            sprite = draw.pill(chip_text(e), int(18 * ui), fill=color)
            draw.paste(view, sprite, self.out[0] - sprite.width - margin, margin, alpha)
        clock = draw.pill(draw.clock(now), int(15 * ui), fill=draw.INK + (150,))
        draw.paste(view, clock, margin, margin, 0.9)
        if speed > 1.3:
            badge = draw.pill(f"{speed:.0f}x speed" if speed >= 2 else f"{speed:.1f}x speed", int(15 * ui), fill=draw.INK + (190,))
            draw.paste(view, badge, margin + clock.width + int(8 * ui), margin, min(1.0, (speed - 1.3) / 1.5))


def even(n):
    return int(n) // 2 * 2


_worker = {}


def _init(frames, size, out_size, events, framed):
    _worker.update(frames=frames, size=size, scene=Scene(size, out_size, events, framed), cached=(None, None))


def _frame(job):
    index, now, speed, box = job
    scene = _worker["scene"]
    if _worker["cached"][0] != index:
        image = Image.open(_worker["frames"][index]).convert("RGB")
        if image.size != _worker["size"]:
            image = image.resize(_worker["size"])
        _worker["cached"] = (index, scene.compose(image))
    canvas = _worker["cached"][1]
    return (scene.render(canvas, now, speed, box).tobytes(),
            scene.render(canvas, now, speed, (0, 0, *scene.out)).tobytes())


def encoder(path, size, crf):
    return subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{size[0]}x{size[1]}",
         "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-tune", "animation",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)], stdin=subprocess.PIPE)


def video(folder, events, frames, times, start, end, framed, width, crf, target):
    """Writes session.mp4, which zooms in on each action, and session-wide.mp4, which shows the whole screen."""
    first = Image.open(frames[-1])
    screen_w = first.width / INSET if framed else first.width
    out_w = even(width or min(1920, max(1280, screen_w)))
    out_size = (out_w, even(out_w * first.height / first.width))
    plan = fit(spans(screen_changes(frames, times, start), events), end, target)
    scene = Scene(first.size, out_size, events, framed)
    real = [t - start for t in times]
    jobs = [(max(0, bisect_right(real, now) - 1), now, speed, scene.camera.step(now, 1 / FPS)) for now, speed in plan]
    zoomed, wide = encoder(folder / "session.mp4", out_size, crf), encoder(folder / "session-wide.mp4", out_size, crf)
    workers = max(1, min(8, (os.cpu_count() or 2) - 1))
    with multiprocessing.get_context("spawn").Pool(workers, _init, (frames, first.size, out_size, events, framed)) as pool:
        for near, far in pool.imap(_frame, jobs, chunksize=12):
            zoomed.stdin.write(near)
            wide.stdin.write(far)
    for ffmpeg in (zoomed, wide):
        ffmpeg.stdin.close()
        if ffmpeg.wait():
            sys.exit("ffmpeg failed")
    starts = [now for now, _ in plan]
    for e in events:
        e["v"] = min(bisect_right(starts, e["t"]), len(starts)) / FPS
    poster = Image.open(frames[len(frames) // 2]).convert("RGB")
    poster.thumbnail((1280, 1280))
    poster.save(folder / "poster.jpg", quality=82)
    return len(plan) / FPS


def shots(folder, events, frames, times, start):
    out = folder / "shots"
    out.mkdir(exist_ok=True)
    real = [t - start for t in times]
    for n, e in enumerate(events):
        if e["kind"] not in SHOT_KINDS:
            continue
        after = e["t"] + (0.2 if e["kind"] == "check" else 1.0)
        index = max(0, min(len(frames) - 1, bisect_right(real, after) - 1))
        image = Image.open(frames[index]).convert("RGB")
        image.thumbnail((640, 640))
        image.save(out / f"{n}.jpg", quality=78)
        e["shot"] = f"shots/{n}.jpg"


def render(folder, framed=True, width=None, crf=20, target=30):
    folder = Path(folder)
    info, events, frames, times = load(folder)
    start = times[0]
    screen_file = folder / "screen.txt"
    screen_w = int(screen_file.read_text().split()[0]) if screen_file.exists() else Image.open(frames[-1]).width
    scale = Image.open(frames[-1]).width / screen_w
    rel = relative(events, start, scale)
    end = max(times[-1] - start, max((e["t"] for e in rel), default=0) + 2.0)
    length = video(folder, rel, frames, times, start, end, framed, width, crf, target)
    shots(folder, rel, frames, times, start)
    verdict = page.write(folder, info, rel, length, end)
    size = (folder / "session.mp4").stat().st_size / 1e6
    return verdict, length, end, size
