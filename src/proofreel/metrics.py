"""The metrics of a session folder: what its probes measured, on the host clock.

metrics/<probe>.jsonl holds the lines a probe printed (see probes), each with "a", the unix time it arrived. A line
with its own "t" goes onto the host clock by the probe's offset: the smallest (a - t) over its lines, as NTP does, so
lines that come late in a burst do not move it. A sample counts its value v, a span its length d. stat() gives one
number for a series glob in a time window, check() is one budget, and summary() is the few lines that `stats` and
`stop` print.
"""

import fnmatch
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path

from . import Problem

STATS = ("mean", "min", "max", "p50", "p90", "p95", "p99", "last", "count", "failed")


@dataclass
class Measure:
    probe: str
    m: str
    t: float
    a: float
    v: float | None
    d: float | None
    ok: bool | None

    @property
    def value(self):
        return self.d if self.d is not None else self.v

    @property
    def kind(self):
        return "span" if self.d is not None else "sample" if self.v is not None else "mark"


def percentile(values, q):
    """Linear between the two nearest ranks."""
    values = sorted(values)
    at = (len(values) - 1) * q / 100
    low = math.floor(at)
    return values[low] + (values[min(low + 1, len(values) - 1)] - values[low]) * (at - low)


def number(value):
    return f"{value:.3g}" if abs(value) < 1000 else f"{value:.0f}"


class Metrics:
    def __init__(self, measures, tracks, status):
        self.measures = sorted(measures, key=lambda x: x.t)
        self.tracks, self.status = tracks, status

    def series(self):
        return list(dict.fromkeys(x.m for x in self.measures))

    def select(self, glob, since=None, until=None):
        return [x for x in self.measures if fnmatch.fnmatchcase(x.m, glob)
                and (since is None or x.t >= since) and (until is None or x.t <= until)]

    def stat(self, glob, stat, since=None, until=None):
        """One number, or None when the window has nothing to count."""
        if stat not in STATS:
            raise Problem(f"Unknown stat {stat!r}. Use one of: {', '.join(STATS)}.")
        chosen = self.select(glob, since, until)
        if stat == "count":
            return len(chosen)
        if stat == "failed":
            return sum(1 for x in chosen if x.ok is False)
        values = [x.value for x in chosen if x.value is not None]
        if not values:
            return None
        if stat == "last":
            return values[-1]
        if stat == "mean":
            return sum(values) / len(values)
        return {"min": min, "max": max}[stat](values) if stat in ("min", "max") else percentile(values, int(stat[1:]))

    @property
    def high_water(self):
        """When the newest line arrived."""
        return max((x.a for x in self.measures), default=0)

    def track(self, m):
        return next((track for glob, track in self.tracks.items() if fnmatch.fnmatchcase(m, glob)), {})

    def unit(self, m, kind):
        return "s" if kind == "span" else self.track(m).get("unit", "")

    def line(self, m):
        """One series in one line: what it is, and the numbers that say most about it."""
        chosen = self.select(m)
        kind, label = chosen[-1].kind, self.track(m).get("label", m)
        unit = self.unit(m, kind)
        unit = ("" if unit in ("%", "") else " ") + unit
        if kind == "mark":
            return f"{label}: {len(chosen)} marks"
        get = lambda stat: number(self.stat(m, stat)) + unit
        if kind == "span":
            failed = self.stat(m, "failed")
            return (f"{label}: {len(chosen)} spans, p50 {get('p50')}, p95 {get('p95')}, max {get('max')}"
                    + (f", {failed} failed" if failed else ""))
        return f"{label}: mean {get('mean')}, p95 {get('p95')}, max {get('max')}"

    def summary(self, limit=12):
        """At most limit lines: a probe that did not work, then each series."""
        lines = [f"Probe {name} {s['status']}: {s.get('note') or 'no lines'}"
                 for name, s in self.status.items() if s.get("status") not in ("ok", None)]
        lines += [self.line(m) for m in self.series()]
        if len(lines) > limit:
            lines = lines[:limit - 1] + [f"... and {len(lines) - limit + 1} more (proofreel stats --all)"]
        return lines


def load(folder):
    folder = Path(folder)
    info_path = folder / "session.json"
    info = json.loads(info_path.read_text()) if info_path.exists() else {}
    tracks = {glob: track for probe in info.get("probes") or [] for glob, track in probe.get("tracks", {}).items()}
    status_path = folder / "metrics" / "probes.json"
    status = json.loads(status_path.read_text()) if status_path.exists() else {}
    measures = []
    for path in sorted((folder / "metrics").glob("*.jsonl")):
        lines = []
        for raw in path.read_text().splitlines():
            try:
                lines.append(json.loads(raw))
            except ValueError:
                continue
        offsets = [line["a"] - line["t"] for line in lines if "t" in line]
        offset = min(offsets, default=0)
        measures += [Measure(path.stem, line["m"], line["t"] + offset if "t" in line else line["a"], line["a"],
                             line.get("v"), line.get("d"), line.get("ok")) for line in lines if "m" in line]
    return Metrics(measures, tracks, status)


def check(folder, glob, stat, below=None, above=None, since=None, window="the run", wait=2.0):
    """One budget, as (ok, label, detail). It waits up to wait s for a line that came after it began, so it judges
    the screen as it is now. With no data in the window, it cannot run."""
    if (below is None) == (above is None):
        raise Problem("check metric takes one of --below N or --above N.")
    asked = time.time()
    while True:
        metrics = load(folder)
        if metrics.high_water >= asked or time.time() >= asked + wait:
            break
        time.sleep(0.25)
    label = f"{glob} {stat} {'below ' + number(below) if below is not None else 'above ' + number(above)} in {window}"
    value = metrics.stat(glob, stat, since, asked)
    if value is None:
        probes = ", ".join(f"{n} {s.get('status')}" for n, s in metrics.status.items()) or "no probe status yet"
        raise Problem(f"No {glob} data in {window}. Series: {', '.join(metrics.series()) or 'none'}. ({probes})")
    ok = value < below if below is not None else value > above
    unit = metrics.unit(metrics.select(glob)[-1].m, metrics.select(glob)[-1].kind) if stat not in ("count", "failed") else ""
    return ok, label, f"{stat} {number(value)}{'' if unit in ('%', '') else ' '}{unit}"
