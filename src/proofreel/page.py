"""The review page. One template for a single run and for a run history published to one URL.

The page draws itself from embedded run data. The timeline shows the states, steps, and checks; the actions between
them fold under one line. When the runs have states, the state machine view (machine.js) joins them into one graph. On claude.ai, the artifact's own comments work on any row, and the page adds a shared
Approve / Needs work review and questions about the current frame. Opened as a plain file, it is a static page.
"""

import fcntl
import html
import json
import shutil
import time
from importlib import resources
from pathlib import Path

from . import Problem, metrics
from .session import CHIP, HIDDEN, ROW, VERDICT, moment, visits

VERSION = 2

CAPABILITIES = {"db": {}, "user": {"scopes": ["profile"]}, "sample": {"images": True}}

ASSETS = resources.files("proofreel")
SCRIPTS = ("machine.js", "tracks.js", "page.js")
CURVES = 6


def verdict(info, events):
    """works, problem (a failed check or a stopped run), or shown (no checks)."""
    checks = [e for e in events if e["kind"] == "check"]
    if info.get("error") or any(not e.get("ok") for e in checks):
        return "problem"
    return "works" if checks else "shown"


def run_data(folder, info, events, length, real, clock, camera, measured=None):
    """The page's data for one run (version 2). Times are seconds from the first frame. measured is what
    metrics.page() packed."""
    checks = [e for e in events if e["kind"] == "check"]
    passed = sum(1 for e in checks if e.get("ok"))
    meta = [f"{k} {v}" for k, v in (info.get("meta") or {}).items() if k and k != "conditions" and v]
    meta += [f"conditions {', '.join(map(condition, info['conditions']))}" if info.get("conditions") else "",
             f"{passed}/{len(checks)} checks pass" if checks else "", f"{real:.0f} s of screen in a {length:.0f} s video"]
    started = info.get("started")
    keep = ("t", "dur", "kind", "text", "ok", "detail", "shot", "row", "chip", "late")
    return {"version": VERSION, "id": folder.name, "title": info.get("title") or folder.name,
            "about": info.get("about", ""), "error": info.get("error", ""), "verdict": verdict(info, events),
            "meta": [m for m in meta if m], "base": "", "length": round(length, 2), "real": round(real, 2),
            "overlay": True, "camera": camera,
            "when": time.strftime("%Y-%m-%d %H:%M", time.localtime(started)) if started else
            (info.get("meta") or {}).get("", ""), "clock": clock.knots,
            "states": visits(events, info.get("error", ""), round(real, 2)),
            "events": [{k: e[k] for k in keep if k in e} for e in map(shown, events) if e],
            **({"metrics": measured} if measured and (measured["series"] or measured["budgets"]) else {})}


def condition(record):
    """A condition as the meta line names it, with its values when it lasted this recording only."""
    # WHY: a state's values can be host paths, such as DMG.
    values = " ".join(f"{k}={v}" for k, v in record.get("values", {}).items()) if record.get("recording") else ""
    return f"{record['name']} ({values})" if values else record["name"]


def shown(event):
    """An event as the page lists it: at its moment, as a key row or a folded action; a move is not listed."""
    if event["kind"] in HIDDEN:
        return None
    page = {**event, "t": moment(event), "row": "key" if event["kind"] in ROW else "fold"}
    if event["kind"] in CHIP:
        page["chip"] = True
        if event["kind"] not in VERDICT and event.get("end", event["t"]) - event["t"] >= 0.05:
            page["dur"] = round(event["end"] - event["t"], 2)
    return page


def upgrade(run):
    """A run that an older proofreel published (version 1), as version 2. Its clock comes from the video time that
    version 1 gave each event."""
    if run.get("version", 1) > VERSION:
        raise Problem(f"Run {run['id']} was made by a newer proofreel (format {run['version']}). Update proofreel.")
    if run.get("version", 1) == VERSION:
        return run
    knots = [[0.0, 0.0]]
    for e in sorted(run["events"], key=lambda e: e["t"]):
        if "v" in e and e["t"] > knots[-1][0] and e["v"] > knots[-1][1]:
            knots.append([e["t"], e["v"]])
    events = [e if "row" in e else shown(e) for e in run["events"]]
    old = {k: run[k] for k in run if k not in ("verdict_css", "fast")}
    return {**old, "version": VERSION, "verdict": run["verdict"].lower(), "clock": knots,
            "events": [{k: v for k, v in e.items() if k != "v"} for e in events if e]}


def load_runs(out):
    """The runs of a review folder (runs.json), as version 2."""
    path = Path(out) / "runs.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    runs = data if isinstance(data, list) else data["runs"]
    if not isinstance(data, list) and data.get("version", 1) > VERSION:
        raise Problem(f"{path} was made by a newer proofreel (format {data['version']}). Update proofreel.")
    return [upgrade(run) for run in runs]


def document(runs):
    data = json.dumps(runs).replace("</", "<\\/")
    title = html.escape(runs[-1]["title"])
    return f"""<title>{title}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=IBM+Plex+Mono&display=swap">
<style>{ASSETS.joinpath('page.css').read_text()}</style>
<div class="wrap"><main id="app"></main><footer>Made with <a href="https://github.com/YGao2005/proofreel">proofreel</a>.</footer></div>
<script type="application/json" id="runs">{data}</script>
<script>{''.join(ASSETS.joinpath(name).read_text() for name in SCRIPTS)}</script>
"""


def write(folder, info, events, length, real, clock, camera, measured=None):
    """Write run.json and index.html, and return the run data."""
    run = run_data(folder, info, events, length, real, clock, camera, measured)
    (folder / "run.json").write_text(json.dumps(run))
    (folder / "index.html").write_text(document([run]))
    return run


def publish(session, out):
    """Add a session to a review folder that holds every run of one journey, for one artifact URL. Returns the
    files of this run (published path -> source) for the Artifact tool, and the page path."""
    session, out = Path(session), Path(out)
    run = upgrade(json.loads((session / "run.json").read_text()))
    target = out / "runs" / run["id"]
    if target.exists():
        shutil.rmtree(target)
    (target / "shots").mkdir(parents=True)
    for name in ("session.mp4", "poster.jpg"):
        if (session / name).exists():
            shutil.copy2(session / name, target / name)
    for shot in (session / "shots").glob("*.jpg"):
        shutil.copy2(shot, target / "shots" / shot.name)
    with open(out / "runs.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        manifest = out / "runs.json"
        if manifest.exists() and isinstance(json.loads(manifest.read_text()), list):
            shutil.copy2(manifest, out / "runs.v1.json")
        runs = [r for r in load_runs(out) if r["id"] != run["id"]] + [{**run, "base": f"runs/{run['id']}/"}]
        runs = [stats_only(r) for r in runs[:-CURVES]] + runs[-CURVES:]
        atomic(manifest, json.dumps({"version": VERSION, "runs": runs}))
        page = out / "index.html"
        atomic(page, document(runs))
    files = {str(p.relative_to(out)): str(p.resolve()) for p in sorted(target.rglob("*")) if p.is_file()}
    return page, files, len(runs)


def stats_only(run):
    """An older run keeps the numbers of its metrics, not their curves, so the page of a long history stays small."""
    if "metrics" not in run:
        return run
    return {**run, "metrics": {**run["metrics"], "series": [metrics.stats_only(s) for s in run["metrics"]["series"]]}}


def atomic(path, text):
    """Write the whole file or nothing: a reader never sees half of it."""
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text)
    temp.replace(path)
