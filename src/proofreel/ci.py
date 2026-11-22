"""Helpers for CI: read the verdict of each journey from a review folder.

The exit code of `proofreel suite` is not the verdict. The verdict of each journey is in runs.json, and a journey
that has no checks is "shown", not "works": a report must not call it a pass.
"""

import argparse
from pathlib import Path

from . import Problem, page

LABEL = {"works": "works", "problem": "problem", "shown": "no checks"}


def journeys(out):
    """One dict for each journey of the review folder: id, title, verdict, error, failed checks, seconds."""
    rows = []
    for run in page.load_runs(out):
        failed = [{"text": e["text"], "detail": e.get("detail", "")} for e in run["events"]
                  if e.get("kind") == "check" and e.get("ok") is False]
        rows.append({"id": run["id"], "title": run["title"], "verdict": run["verdict"], "error": run.get("error", ""),
                     "failed": failed, "seconds": run["length"], "poster": f"runs/{run['id']}/poster.jpg"
                     if run.get("video") is not False else None})
    return rows


def check(out):
    """Print one line for each journey. Returns 1 when a journey has a problem or there are no journeys, else 0."""
    rows = journeys(out)
    for row in rows:
        print(f"{LABEL[row['verdict']].upper()}: {row['title']}")
        if row["verdict"] == "shown":
            print(f"::warning::{row['title']} has no checks, so it proves nothing. Add check lines to its flow.")
    if not rows:
        print("No journeys in the review folder.")
    return 1 if not rows or any(r["verdict"] == "problem" for r in rows) else 0


def main(argv):
    p = argparse.ArgumentParser(prog="proofreel ci", description="Helpers for CI.")
    sub = p.add_subparsers(dest="action", required=True)
    s = sub.add_parser("check", help="print the verdicts of a review folder; exit 1 if a journey has a problem")
    s.add_argument("dir")
    try:
        a = p.parse_args(argv)
    except SystemExit as stop:
        raise Problem("Usage: proofreel ci check <review folder>") from stop
    return check(Path(a.dir))
