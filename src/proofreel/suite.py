"""Suites: many flows, each from a new clone of its saved state, published to one review page.

Every flow is read and parsed, and every state found, before the first VM starts. Then for each flow, the suite
starts a run VM from the flow's state (its `from <state>` line, or --state), runs the flow, stops a recording that
the flow left open, and stops the run VM, which deletes the clone. A journey that fails does not stop the suite.
Each journey goes to one review folder, so one page lists them all, with the checks and the verdict of each.
With repeat, each flow runs that many times, each time from a new clone. A journey whose verdict or any check result
differs between the runs is flaky, and a flaky journey is not a pass. With each_condition, each flow also runs for
each condition named (and `plain` for none): a journey of the flow with that condition, shown as its own journey.
"""

import json
import time
from pathlib import Path

from . import Problem, conditions, page, recording
from . import vm as vms

MARK = {"works": "PASS", "problem": "FAIL", "shown": "SHOWN"}
FLAKY = "FLAKY"


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
            if recording.unstopped():
                recording.stop(error=error or "The flow did not stop its recording; the suite stopped it.")
        except Exception as problem:
            error = error or f"The recording did not stop: {problem}"
        finally:
            vms.down()
    return session, error


def result(session, error, run_id):
    """What one run shows of its journey: its verdict, and the result of each check. The flow's ${RUN} of this run is
    left out of the check, because each run has its own."""
    if session and (Path(session) / "run.json").exists():
        run = json.loads((Path(session) / "run.json").read_text())
        return run["verdict"], [(e["text"].replace(run_id, "${RUN}"), bool(e.get("ok"))) for e in run["events"]
                                if e["kind"] == "check"]
    return "problem", []


def run(targets, load, play, execute, state=None, out=None, title=None, repeat=1, each_condition=()):
    """Run every flow repeat times and publish each run to out. load(path) reads a flow, play(steps, execute) runs
    it, and execute(words) runs one line. each_condition lists condition names, or plain for none. Returns (what page.add returns, with the new files of every run of this
    suite run, and a (mark, name, error) row for each journey)."""
    if repeat < 1:
        raise Problem("--repeat takes a number from 1.")
    paths = flow_files(targets)
    flows = [load(path) for path in paths]
    for steps in flows:
        steps.state = steps.state or state
        if not steps.state:
            raise Problem(f"{steps.name} names no state. Add a line from <state> to it, or give --state.")
        system = vms.state_info(steps.state)["os"]
        for condition in each_condition:
            if condition != "plain":
                conditions.record(condition, {}, system, recording=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    title = title or (Path(targets[0]).resolve().name if len(targets) == 1 and Path(targets[0]).is_dir() else "Suite")
    out = Path(out) if out else recording.SESSIONS / f"suite-{stamp}"
    suite = {"id": stamp, "title": title}
    rows, results, new = [], None, []
    for path, flow in zip(paths, flows):
        for condition in each_condition or [None]:
            plain = condition in (None, "plain")
            name = Path(flow.name).stem + ("" if plain else f" ({condition})")
            runs, ids = [], []
            for attempt in range(1, repeat + 1):
                steps = load(path)
                steps.state = flow.state
                if not plain:
                    steps.conditions = [*steps.conditions, condition]
                print(f"Journey {name} from {steps.state}" + (f", run {attempt} of {repeat}" if repeat > 1 else ""))
                runs.append(journey(steps, play, execute))
                ids.append(steps.run)
            seen = [result(*one, run_id) for one, run_id in zip(runs, ids)]
            passed = sum(verdict != "problem" for verdict, _ in seen)
            flaky = {"passed": passed, "of": repeat} if any(r != seen[0] for r in seen) else None
            for attempt, (session, error) in enumerate(runs, 1):
                fields = {"suite": suite, "journey": name, **({} if plain else {"condition": condition}),
                          **({"attempt": attempt, "attempts": repeat} if repeat > 1 else {}),
                          **({"flaky": flaky} if flaky else {})}
                label = ("" if plain else f" ({condition})") + (f" #{attempt}" if repeat > 1 else "")
                if session and (Path(session) / "run.json").exists():
                    if label:
                        fields["title"] = json.loads((Path(session) / "run.json").read_text())["title"] + label
                    results = page.publish(session, out, **fields)
                else:
                    run_id = f"{name.replace(' ', '')}-{stamp}" + (f"-{attempt}" if repeat > 1 else "")
                    results = page.add(out, page.stub(run_id, Path(flow.name).stem + label,
                                                      error or "The flow made no recording: add start and stop.", **fields))
                new += results[3]
            verdict = next(r["verdict"] for r in page.load_runs(out) if r["journey"] == name and r["suite"]["id"] == stamp)
            errors = [error for _, error in runs if error]
            mark = FLAKY if flaky else MARK[verdict]
            note = f"passed {passed} of {repeat} runs" if flaky else errors[0] if errors else None
            rows.append((mark, name, note))
            print(f"{mark}: {name}" + (f" ({note})" if note else ""))
    return (*results[:3], new), rows
