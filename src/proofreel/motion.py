"""Time and motion of a review video.

All times are seconds from the first frame. All positions are in frame pixels.
"""

import math
from bisect import bisect_right
from dataclasses import dataclass

from .session import CAMERA, POINTER, VERDICT

FPS = 30
FAST = 8
MOST = 96
ZOOM = 1.25
LEAD, HOLD, BRIDGE = 1.0, 1.6, 1.6
FAR = 0.45


def ease(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


WAITING = 3


def spans(changes, events):
    """Real time by how fast it plays: 1x around each action; WAITING while the agent waits for the screen (model
    output, animations); 1x around other screen changes; FAST for the rest."""
    actions, waits, shown = [], [], [(t - 0.4, t + 1.0) for t in changes]
    for e in events:
        end = e.get("end", e["t"])
        if e["kind"] in VERDICT and end - e["t"] > 1.5:
            waits.append((e["t"] + 0.6, end - 0.4))
        if e["kind"] == "wait":
            shown.append((end - 0.4, end + 1.6))
        elif e["kind"] == "check":
            actions.append((end - 1.2, end + 2.0))
        elif e["kind"] not in ("move", "note"):
            actions.append((e["t"] - 1.2, end + 2.0))
    return sorted(actions), sorted(waits), sorted(shown)


def _any(spans_, a, b):
    i = bisect_right([s for s, _ in spans_], b)
    return any(spans_[j][1] >= a for j in range(max(0, i - 8), i))


def fit(spans_, end, target=None, fps=FPS):
    """The plan of `timeline`. Past `target` s, busy time plays up to 2.5x faster, then idle time plays faster than
    FAST (up to MOST) until the video fits: a long stall costs seconds of video, not minutes."""
    plan = timeline(spans_, end, fps=fps)
    if not target or len(plan) / fps <= target:
        return plan
    base, fast = min(2.5, len(plan) / fps / target), FAST
    plan = timeline(spans_, end, fps=fps, base=base)
    for _ in range(4):
        over = len(plan) / fps - target
        idle = sum(speed > 0.9 * fast for _, speed in plan) / fps
        if over <= 1 or fast >= MOST or idle <= 1:
            break
        fast = min(MOST, fast * idle / max(1.0, idle - over))
        plan = timeline(spans_, end, fps=fps, fast=fast, base=base)
    return plan


def timeline(spans_, end, fps=FPS, fast=FAST, base=1.0):
    """The real time shown in each video frame, and its speed. Speed ramps, so a jump to FAST is never a cut."""
    actions, waits, shown = spans_
    frames, now, speed = [], 0.0, 1.0
    while now < end:
        frames.append((now, speed))
        ahead = now + speed * 0.4
        if _any(actions, now, ahead):
            target = base
        elif _any(waits, now, ahead):
            target = WAITING * base
        elif _any(shown, now, ahead):
            target = base
        else:
            target = max(fast, base)
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
            if e["kind"] in POINTER:
                self.points.append(Point(e["t"], e["x"], e["y"]))
            if e["kind"] == "drag":
                self.points.append(Point(e.get("end", e["t"] + 0.6), e["x2"], e["y2"]))
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
            if e["kind"] not in CAMERA:
                continue
            x, y = pointer.at(e["t"]) if e["kind"] == "type" else (e["x"], e["y"])
            last = self.groups[-1] if self.groups else None
            end = e.get("end", e["t"])
            if last and e["t"] - LEAD - last[-1][3] - HOLD < BRIDGE and \
                    math.hypot(x - last[-1][1], y - last[-1][2]) < FAR * diagonal:
                last.append((e["t"], x, y, end))
            else:
                self.groups.append([(e["t"], x, y, end)])
        self.state = [size[0] / 2, size[1] / 2, 1.0]
        self.velocity = [0.0, 0.0, 0.0]

    def target(self, now):
        for group in self.groups:
            if group[0][0] - LEAD <= now <= group[-1][3] + HOLD:
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
