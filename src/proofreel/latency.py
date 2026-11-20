"""Input latency: how long the screen took to answer each click and key, read from the recorded frames.

For an input (a click at its press, a key or typing at its first key), the reference is the last frame that arrived
before it. The frames after it are compared with the reference in a region: REGION screen pixels around a click, the
whole screen for keys. Pixels that already changed in the BEFORE seconds before the input (a blinking caret, a
spinner) are masked. The first frame that differs is the answer. A frame was taken some time between its request
and its arrival, and the change came between the frame before and that one, so the latency is the middle of that
time and its error is half of it. The screen has settled when it shows no change for QUIET seconds.

measure() writes metrics/input.jsonl in the probe protocol: a span input/click or input/key for each answer, with
err and settle, and a mark with ok false for an input that got no change on the screen in LIMIT seconds.
"""

import json
from bisect import bisect_right
from pathlib import Path

from PIL import Image, ImageChops

INPUTS = {"click": "click", "double": "click", "right": "click", "key": "key", "type": "key", "tap": "key"}
REGION = (240, 150)
SMALL = {"click": (120, 75), "key": (192, 120)}
LEVEL = 24
PIXELS = 4
BEFORE, LIMIT, QUIET = 0.6, 2.0, 0.3


def picture(path, box, size):
    """The region of a frame, small and grey. JPEG decodes at a lower scale when that is enough, which is fast."""
    image = Image.open(path)
    full = image.size
    image.draft("L", (int(full[0] * size[0] / (box[2] - box[0])), int(full[1] * size[1] / (box[3] - box[1]))))
    k = image.size[0] / full[0]
    return image.convert("L").crop(tuple(int(v * k) for v in box)).resize(size)


def changes(a, b):
    """The pixels whose grey level moved more than LEVEL, as a black and white picture."""
    return ImageChops.difference(a, b).point(lambda v: 255 if v > LEVEL else 0)


def differs(a, b, mask):
    return ImageChops.subtract(changes(a, b), mask).histogram()[255] >= PIXELS


def region(event, kind, frame_size, scale):
    if kind == "key" or "x" not in event:
        return (0, 0, *frame_size)
    width, height = frame_size
    x, y = min(max(event["x"] * scale, 0), width - 1), min(max(event["y"] * scale, 0), height - 1)
    w, h = REGION[0] * scale / 2, REGION[1] * scale / 2
    return (max(0, int(x - w)), max(0, int(y - h)), min(width, int(x + w) + 1), min(height, int(y + h) + 1))


def answer(frames, taken, arrived, event, kind, scale):
    """The input's span or mark, or None when no frame came before it."""
    press = event["t"]
    base = bisect_right(arrived, press) - 1
    if base < 0:
        return None
    size = SMALL[kind]
    box = region(event, kind, Image.open(frames[base]).size, scale)
    look = lambda i: picture(frames[i], box, size)
    reference = look(base)
    mask = Image.new("L", size, 0)
    before, i = reference, base - 1
    while i >= 0 and taken[i] >= press - BEFORE:
        earlier = look(i)
        mask = ImageChops.lighter(mask, changes(earlier, before))
        before, i = earlier, i - 1
    first = last = None
    previous, i = reference, base + 1
    while i < len(frames) and taken[i] - press <= LIMIT + 3 and (
            taken[i] - press <= LIMIT if first is None else taken[i] - taken[last] <= QUIET):
        now = look(i)
        if differs(now, previous if first is not None else reference, mask):
            first = i if first is None else first
            last = i
        previous, i = now, i + 1
    line = {"m": f"input/{kind}", "label": event["text"]}
    if first is None:
        return {**line, "ok": False, "note": f"no change on the screen in {LIMIT:g} s", "a": round(press + LIMIT, 4)}
    since = max(taken[first - 1], press)
    latency = (since + taken[first]) / 2 - press
    return {**line, "d": round(latency, 3), "ok": True, "err": round((taken[first] - since) / 2, 3),
            "settle": round(taken[last] - press, 3), "a": round(press + latency, 4)}


def measure(folder, events, frames, requested, arrived, scale):
    """Write metrics/input.jsonl for every click and key of the session. Returns how many it measured."""
    taken = [(r + a) / 2 for r, a in zip(requested, arrived)]
    lines = [line for e in events if (kind := INPUTS.get(e["kind"]))
             and (line := answer(frames, taken, arrived, e, kind, scale))]
    if lines:
        out = Path(folder) / "metrics"
        out.mkdir(exist_ok=True)
        (out / "input.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))
    return len(lines)
