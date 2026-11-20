"""Suites: many flows, each from a new clone of its saved state, published to one review page.

Every flow is read and parsed, and every state found, before the first VM starts. Then for each flow, the suite
starts a run VM from the flow's state (its `from <state>` line, or --state), runs the flow, stops a recording that
the flow left open, and stops the run VM, which deletes the clone. A journey that fails does not stop the suite.
Each journey goes to one review folder, so one page lists them all, with the checks and the verdict of each.
"""

import time
from pathlib import Path

from . import Problem, page, recording
from . import vm as vms

MARK = {"works": "PASS", "problem": "FAIL", "shown": "SHOWN"}


def flow_files(targets):
    """The flow files: each file given, and the .flow files of each folder given, in name order."""
    files = []
    for target in map(Path, targets):
        if target.is_dir():
            files += sorted(target.glob("*.flow"))
        elif target.is_file():
            files.append(target)
        else:
            raise Problem(f"No flow file or folder {target}.")
    if not files:
        raise Problem(f"No .flow files in {', '.join(map(str, targets))}.")
    return files


def journey(steps, play, execute):
    """Run one flow on a new run VM. Returns (session folder or None, error or None)."""
    session, error = None, None

    def line(words):
        nonlocal session
        try:
            return execute(words)
        finally:
            if words[0] == "start" and (active := recording.current()):
                session = active["dir"]

    try:
        vms.up(steps.state)
        play(steps, line)
    except Exception as problem:
        error = str(problem) or type(problem).__name__
    finally:
        try:
            if recording.current():
                recording.stop(error=error or "The flow did not stop its recording; the suite stopped it.")
        except Exception as problem:
            error = error or f"The recording did not stop: {problem}"
        finally:
            vms.down()
    return session, error


def run(targets, load, play, execute, state=None, out=None, title=None):
    """Run every flow and publish each journey to out. load(path) reads a flow, play(steps, execute) runs it, and
    execute(words) runs one line. Returns (what page.add returns, with the new files of every journey of this suite
    run, and a (mark, name, error) row for each journey)."""
    flows = [load(path) for path in flow_files(targets)]
    for steps in flows:
        steps.state = steps.state or state
        if not steps.state:
            raise Problem(f"{steps.name} names no state. Add a line from <state> to it, or give --state.")
        vms.state_info(steps.state)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    title = title or (Path(targets[0]).resolve().name if len(targets) == 1 and Path(targets[0]).is_dir() else "Suite")
    out = Path(out) if out else recording.SESSIONS / f"suite-{stamp}"
    suite = {"id": stamp, "title": title}
    rows, result, new = [], None, []
    for steps in flows:
        print(f"Journey {steps.name} from {steps.state}")
        session, error = journey(steps, play, execute)
        name = Path(steps.name).stem
        if session and (Path(session) / "run.json").exists():
            run_id = Path(session).name
            result = page.publish(session, out, suite=suite, journey=name)
        else:
            run_id = f"{name}-{stamp}"
            result = page.add(out, page.stub(run_id, name, error or "The flow made no recording: add start and stop.",
                                             suite=suite, journey=name))
        new += result[3]
        verdict = next(r["verdict"] for r in page.load_runs(out) if r["id"] == run_id)
        rows.append((MARK[verdict], name, error))
        print(f"{MARK[verdict]}: {name}" + (f" ({error})" if error else ""))
    return (*result[:3], new), rows
