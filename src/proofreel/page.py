"""The review page. One template for a single run and for a run history published to one URL.

The page draws itself from embedded run data. The list shows the steps and checks; the actions between them fold
under one line. On claude.ai, the artifact's own comments work on any row, and the page adds a shared
Approve / Needs work review and questions about the current frame. Opened as a plain file, it is a static page.
"""

import html
import json
import shutil
from importlib import resources
from pathlib import Path

from .motion import FAST
from .session import HIDDEN, ROW, moment

CAPABILITIES = {"db": {}, "user": {"scopes": ["profile"]}, "sample": {"images": True}}

ASSETS = resources.files("proofreel")


def verdict(info, events):
    checks = [e for e in events if e["kind"] == "check"]
    failed = [e for e in checks if not e.get("ok")]
    if failed or info.get("error"):
        return "Problem", "bad", checks, failed
    return ("Works", "ok", checks, failed) if checks else ("Shown", "info", checks, failed)


def run_data(folder, info, events, length, real):
    label, css, checks, failed = verdict(info, events)
    meta = [f"{k} {v}" if k else str(v) for k, v in (info.get("meta") or {}).items() if v]
    meta += [f"{len(checks) - len(failed)}/{len(checks)} checks pass" if checks else "",
             f"{real:.0f} s of screen in a {length:.0f} s video"]
    keep = ("t", "v", "kind", "text", "ok", "detail", "shot", "row")
    return {"id": folder.name, "title": info.get("title") or folder.name, "about": info.get("about", ""),
            "error": info.get("error", ""), "verdict": label, "verdict_css": css, "meta": [m for m in meta if m],
            "when": (info.get("meta") or {}).get("", ""), "fast": FAST, "base": "",
            "wide": (folder / "session-wide.mp4").exists(),
            "events": [{k: e[k] for k in keep if k in e} for e in map(shown, events) if e]}


def shown(event):
    """An event as the page lists it: at its moment, as a key row or a folded action; a move is not listed."""
    if event["kind"] in HIDDEN:
        return None
    return {**event, "t": moment(event), "row": "key" if event["kind"] in ROW else "fold"}


def upgrade_run(run):
    """A run that an older proofreel published, as this page reads it."""
    events = [e if "row" in e else shown(e) for e in run["events"]]
    return {**run, "events": [e for e in events if e]}


def document(runs):
    data = json.dumps(runs).replace("</", "<\\/")
    title = html.escape(runs[-1]["title"])
    return f"""<title>{title}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&family=IBM+Plex+Mono&display=swap">
<style>{ASSETS.joinpath('page.css').read_text()}</style>
<div class="wrap"><main id="app"></main><footer>Made with <a href="https://github.com/YGao2005/proofreel">proofreel</a>.</footer></div>
<script type="application/json" id="runs">{data}</script>
<script>{ASSETS.joinpath('page.js').read_text()}</script>
"""


def write(folder, info, events, length, real):
    run = run_data(folder, info, events, length, real)
    (folder / "run.json").write_text(json.dumps(run))
    (folder / "index.html").write_text(document([run]))
    return run["verdict"]


def publish(session, out):
    """Add a session to a review folder that holds every run of one journey, for one artifact URL. Returns the
    files of this run (published path -> source) for the Artifact tool, and the page path."""
    session, out = Path(session), Path(out)
    run = json.loads((session / "run.json").read_text())
    target = out / "runs" / run["id"]
    if target.exists():
        shutil.rmtree(target)
    (target / "shots").mkdir(parents=True)
    for name in ("session.mp4", "session-wide.mp4", "poster.jpg"):
        if (session / name).exists():
            shutil.copy2(session / name, target / name)
    for shot in (session / "shots").glob("*.jpg"):
        shutil.copy2(shot, target / "shots" / shot.name)
    manifest = out / "runs.json"
    runs = [upgrade_run(r) for r in (json.loads(manifest.read_text()) if manifest.exists() else [])
            if r["id"] != run["id"]]
    runs.append({**run, "base": f"runs/{run['id']}/"})
    manifest.write_text(json.dumps(runs))
    page = out / "index.html"
    page.write_text(document(runs))
    files = {str(p.relative_to(out)): str(p.resolve()) for p in sorted(target.rglob("*")) if p.is_file()}
    return page, files, len(runs)
