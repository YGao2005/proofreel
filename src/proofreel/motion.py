"""Time and motion of a review video.

All times are seconds from the first frame. All positions are in frame pixels.
"""

import math
from bisect import bisect_right
from dataclasses import dataclass

FPS = 24
FAST = 8
POINTED = {"click", "double", "right", "move", "drag"}
FOCUSED = {"click", "double", "right", "drag", "type"}
ZOOM = 1.7
LEAD, HOLD, BRIDGE = 1.0, 1.6, 1.6
FAR = 0.45


def ease(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def busy_spans(changes, events):
    """Real time that plays at 1x: around each screen change and each action. The rest plays at FAST."""
    spans = [(t - 0.4, t + 1.0) for t in changes]
    spans += [(e["t"] - 1.2, e["t"] + 2.0) for e in events if e["kind"] not in ("move", "note")]
    return sorted(spans)


def timeline(spans, end, fps=FPS, fast=FAST):
    """The real time shown in each video frame, and its speed. Speed ramps, so a jump to FAST is never a cut."""
    starts = [a for a, _ in spans]
    frames, now, speed = [], 0.0, 1.0

    def busy(a, b):
        i = bisect_right(starts, b)
        return any(spans[j][1] >= a for j in range(max(0, i - 8), i))

    while now < end:
        frames.append((now, speed))
        target = 1.0 if busy(now, now + speed * 0.4) else fast
        speed += (target - speed) * (0.5 if target < speed else 0.12)
        now += speed / fps
    return frames


@dataclass
class Point:
    t: float
    x: float
    y: float


class Pointer:
    """The drawn pointer. It rests at its last action and moves to the next one along a slight arc."""

    def __init__(self, events, size):
        self.width = size[0]
        self.points = [Point(-1.0, size[0] / 2, size[1] / 2)]
        for e in events:
            if e["kind"] in POINTED:
                self.points.append(Point(e["t"], e["x"], e["y"]))
            if e["kind"] == "drag":
                self.points.append(Point(e["t"] + e.get("hold", 0.6), e["x2"], e["y2"]))
        self.times = [p.t for p in self.points]

    def at(self, now):
        i = bisect_right(self.times, now)
        a = self.points[i - 1]
        if i == len(self.points):
            return a.x, a.y
        b = self.points[i]
        distance = math.hypot(b.x - a.x, b.y - a.y)
        glide = min(b.t - a.t, 0.35 + 0.45 * min(1.0, distance / self.width))
        k = ease(1 - (b.t - now) / glide) if glide > 0 else 1.0
        cx = (a.x + b.x) / 2 - (b.y - a.y) * 0.12
        cy = (a.y + b.y) / 2 + (b.x - a.x) * 0.12
        x = (1 - k) ** 2 * a.x + 2 * (1 - k) * k * cx + k * k * b.x
        y = (1 - k) ** 2 * a.y + 2 * (1 - k) * k * cy + k * k * b.y
        return x, y


class Camera:
    """Where the video looks. It zooms in before an action, pans to the next action when it is near in time and
    space, and zooms out when nothing happens. A critically damped spring moves it, so it never jumps."""

    def __init__(self, events, pointer, size, zoom=ZOOM):
        self.size, self.zoom = size, zoom
        self.groups = []
        diagonal = math.hypot(*size)
        for e in events:
            if e["kind"] not in FOCUSED:
                continue
            x, y = pointer.at(e["t"]) if e["kind"] == "type" else (e["x"], e["y"])
            last = self.groups[-1] if self.groups else None
            if last and e["t"] - LEAD - last[-1][0] - HOLD < BRIDGE and \
                    math.hypot(x - last[-1][1], y - last[-1][2]) < FAR * diagonal:
                last.append((e["t"], x, y))
            else:
                self.groups.append([(e["t"], x, y)])
        self.state = [size[0] / 2, size[1] / 2, 1.0]
        self.velocity = [0.0, 0.0, 0.0]

    def target(self, now):
        for group in self.groups:
            if group[0][0] - LEAD <= now <= group[-1][0] + HOLD:
                current = group[0]
                for point in group:
                    if point[0] - 0.55 <= now:
                        current = point
                return current[1], current[2], self.zoom
        return self.size[0] / 2, self.size[1] / 2, 1.0

    def step(self, now, dt):
        """Move toward the target of `now` by one frame. Returns the view box (left, top, width, height)."""
        goal = self.target(now)
        for i, smooth in enumerate((0.32, 0.32, 0.38)):
            self.state[i], self.velocity[i] = smooth_damp(self.state[i], goal[i], self.velocity[i], smooth, dt)
        cx, cy, z = self.state
        z = max(1.0, z)
        w, h = self.size[0] / z, self.size[1] / z
        left = min(max(cx - w / 2, 0.0), self.size[0] - w)
        top = min(max(cy - h / 2, 0.0), self.size[1] - h)
        return left, top, w, h


def smooth_damp(current, target, velocity, smooth_time, dt):
    """A critically damped spring step (as in Game Programming Gems 4, 1.10)."""
    omega = 2.0 / smooth_time
    x = omega * dt
    decay = 1.0 / (1.0 + x + 0.48 * x * x + 0.235 * x * x * x)
    change = current - target
    temp = (velocity + omega * change) * dt
    velocity = (velocity - omega * temp) * decay
    return target + (change + temp) * decay, velocity
