"""The metrics of a session folder: what its probes measured, on the host clock.

metrics/<probe>.jsonl holds the lines a probe printed (see probes), each with "a", the unix time it arrived. A line
with its own "t" goes onto the host clock by the probe's offset: the smallest (a - t) over its lines, as NTP does, so
lines that come late in a burst do not move it. A sample counts its value v, a span its length d. stat() gives one
number for a series glob in a time window, check() is one budget, summary() is the few lines that `stats` and
`stop` print, and page() is what the review page draws.
"""

import fnmatch
import json
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import Problem

STATS = ("mean", "min", "max", "p50", "p90", "p95", "p99", "last", "count", "failed")
AFTER = ("input/",)
TRACKS = {"input/click": {"label": "Click latency", "better": "lower"},
          "input/key": {"label": "Key latency", "better": "lower"}}
LIMIT = 200_000
CAPS = (600, 2000, 1000)
SHOWN = ("label", "unit", "better", "max", "bands")
INFO = ("label", "phases", "n")


@dataclass
class Measure:
    probe: str
    m: str
    t: float
    a: float
    v: float | None
    d: float | None
    ok: bool | None
    info: dict = field(default_factory=dict)

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


def clean(text):
    """Text for the page: a URL's query and fragment can hold secrets, so they are cut."""
    return re.sub(r"[?#]\S*", "", str(text))[:160]


def short(value):
    return float(f"{value:.4g}")


def curve(points, video, n):
    """Samples [(t, v)] as they are when there are at most n, else as at most n bins of equal video time, so a
    sped-up stretch keeps its spikes: [t, mean] for a bin of one value, [t, mean, lo, hi] for more."""
    if len(points) <= n:
        return [[round(t, 3), short(v)] for t, v in points]
    at = [video(t) for t, _ in points]
    first, width = at[0], (at[-1] - at[0]) / n or 1
    bins = {}
    for (t, v), x in zip(points, at):
        bins.setdefault(min(n - 1, int((x - first) / width)), []).append((t, v))
    out = []
    for _, group in sorted(bins.items()):
        values = [v for _, v in group]
        low, high = min(values), max(values)
        out.append([round(sum(t for t, _ in group) / len(group), 3), short(sum(values) / len(values))]
                   + ([short(low), short(high)] if high > low else []))
    return out


def span(x, start):
    """[start, d, ok, label, phases, status], with the empty ones at the end left out."""
    phases = x.info.get("phases")
    status = (x.info.get("n") or {}).get("status") if isinstance(x.info.get("n"), dict) else None
    row = [round(x.t - start - x.d, 3), short(x.d), x.ok, clean(x.info["label"]) if x.info.get("label") else None,
           {k: short(v) for k, v in phases.items()} if isinstance(phases, dict) else None, status]
    while row[-1] is None and len(row) > 3:
        row.pop()
    return row


def pick(chosen, cap, slowest=True):
    """At most cap measures in time order: every failed one first, then the slowest, then a spread over the run."""
    if len(chosen) <= cap:
        return chosen
    failed = [x for x in chosen if x.ok is False][:cap]
    rest = [x for x in chosen if x.ok is not False]
    room = cap - len(failed)
    slow = sorted(rest, key=lambda x: -(x.d or 0))[:room // 2] if slowest else []
    taken = {id(x) for x in slow}
    left = [x for x in rest if id(x) not in taken]
    k = room - len(slow)
    spread = [left[i * len(left) // k] for i in range(k)] if k else []
    return sorted(failed + slow + spread, key=lambda x: x.t)


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
        kinds = {x.kind for x in chosen}
        kind = "span" if "span" in kinds else "sample" if "sample" in kinds else "mark"
        label = self.track(m).get("label", m)
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

    def page(self, start, end, video, events=(), limit=LIMIT):
        """What the review page draws, at most limit bytes as JSON: each series with its stats and its curve, spans,
        or marks, in seconds from start (the first frame) up to end; the budgets that `check metric` judged; and
        each probe's status. video(t) is the run's clock. Too much data gets fewer spans and marks, then fewer bins
        too, then stats alone."""
        by = {}
        for x in self.measures:
            by.setdefault(x.m, []).append(x)
        budgets = [{**e["budget"], "ok": e.get("ok"), "detail": e.get("detail", ""), "t": round(e["t"], 3),
                    "series": [clean(m) for m in by if fnmatch.fnmatchcase(m, e["budget"]["glob"])]}
                   for e in events if "budget" in e]
        probes = {name: {"status": s.get("status"), "note": clean(s.get("note") or "")} for name, s in self.status.items()}
        caps = CAPS
        while True:
            series = [self.packed(m, chosen, start, end, video, caps) for m, chosen in by.items()]
            data = {"series": series, "budgets": budgets, "probes": probes}
            if len(json.dumps(data)) <= limit:
                return data
            if caps[0] < 16:
                return {**data, "series": [stats_only(s) for s in series]}
            caps = (caps[0] if caps[1] == CAPS[1] else caps[0] // 2, caps[1] // 2, caps[2] // 2)

    def packed(self, m, chosen, start, end, video, caps):
        kinds = {x.kind for x in chosen}
        kind = "span" if "span" in kinds else "sample" if "sample" in kinds else "mark"
        track = self.track(m)
        values = sorted(x.value for x in chosen if x.value is not None)
        stats = {"count": len(chosen), "failed": sum(1 for x in chosen if x.ok is False)}
        if values:
            stats.update(p50=short(percentile(values, 50)), p95=short(percentile(values, 95)), max=short(values[-1]))
        out = {"m": clean(m), "kind": kind, "unit": self.unit(m, kind),
               **{k: track[k] for k in SHOWN if k in track and k != "unit"}, "stats": stats}
        inside = [x for x in chosen if 0 <= x.t - start <= end]
        if kind == "sample":
            out["points"] = curve([(x.t - start, x.v) for x in inside if x.v is not None], video, caps[0])
        elif kind == "span":
            kept = pick([x for x in inside if x.d is not None], caps[1])
            out["spans"] = [span(x, start) for x in kept]
            out["more"] = len(inside) - len(kept)
        else:
            kept = pick(inside, caps[2], slowest=False)
            out["marks"] = [[round(x.t - start, 3), x.ok] + ([clean(x.info["label"])] if x.info.get("label") else [])
                            for x in kept]
            out["more"] = len(inside) - len(kept)
        return out

    def summary(self, limit=12):
        """At most limit lines: a probe that did not work, then each series."""
        lines = [f"Probe {name} {s['status']}: {s.get('note') or 'no lines'}"
                 for name, s in self.status.items() if s.get("status") not in ("ok", None)]
        lines += [self.line(m) for m in self.series()]
        if len(lines) > limit:
            lines = lines[:limit - 1] + [f"... and {len(lines) - limit + 1} more (proofreel stats --all)"]
        return lines


def stats_only(series):
    return {k: v for k, v in series.items() if k not in ("points", "spans", "marks", "more")}


def load(folder):
    folder = Path(folder)
    info_path = folder / "session.json"
    info = json.loads(info_path.read_text()) if info_path.exists() else {}
    tracks = {**TRACKS, **{glob: track for probe in info.get("probes") or [] for glob, track in probe.get("tracks", {}).items()}}
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
                             line.get("v"), line.get("d"), line.get("ok"), {k: line[k] for k in INFO if k in line})
                     for line in lines if "m" in line]
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
    return (ok, label, f"{stat} {number(value)}{'' if unit in ('%', '') else ' '}{unit}",
            {"budget": {"glob": glob, "stat": stat, "below": below, "above": above}})


def pending(glob, stat, below, above, since, until, window):
    """A budget on a series that is measured after the run (AFTER): its check waits to be decided at stop."""
    label = f"{glob} {stat} {'below ' + number(below) if below is not None else 'above ' + number(above)} in {window}"
    budget = {"glob": glob, "stat": stat, "below": below, "above": above}
    return None, label, "decided when the run stops", {"budget": budget,
                                                       "pending": {**budget, "since": since, "until": until}}


def decide(folder, events):
    """The events with each pending budget decided from the metrics as they are now. A decided check has late."""
    found = load(folder)
    out = []
    for event in events:
        if "pending" in event:
            p = event["pending"]
            value = found.stat(p["glob"], p["stat"], p["since"], p["until"])
            event = {k: v for k, v in event.items() if k != "pending"}
            if value is None:
                event.update(ok=False, late=True, detail=f"No {p['glob']} data was measured.")
            else:
                ok = value < p["below"] if p["below"] is not None else value > p["above"]
                unit = "" if p["stat"] in ("count", "failed") else " s"
                event.update(ok=ok, late=True, detail=f"{p['stat']} {number(value)}{unit}, measured after the run")
        out.append(event)
    return out
