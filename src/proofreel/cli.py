"""proofreel: record an agent driving a screen as a review video and page.

  start <name> [--title T] [--about A] [--meta K=V] [--app NAME] [--probe NAME[:K=V,...]] [--condition NAME[:K=V,...]] [--full-motion]
                                                        Start recording. Every later action and check is logged. --app
                                                        names the app under test: its crash fails the run. --probe adds
                                                        a probe (none: no default probes). --condition applies a
                                                        condition that lasts one recording (slow-network); stop
                                                        removes it. Flow lines `probe <name>` and `condition <name>`
                                                        do the same.
  stop [--keep-frames] [--plain] [--width W]            Stop, then make session.mp4, index.html, and shots/. In a macOS
                                                        run VM, new crash and hang reports go to reports/ and the log.
  state <name>                                          Say where the app should be now. The waits and checks after
                                                        it, up to the next state, prove it. The page draws the states
                                                        of every run as one state machine.
  step <text> | note <text>                             Name the next part (a caption in the video), or add a note.
  click <x> <y> [--double|--right] | move <x> <y> | drag <x1> <y1> <x2> <y2> | type <text> | key <keys...>
                                                        The pointer glides in, as a hand does, so a hover lands.
  open <url>                                            Show the page in the browser of the run VM: the browser of a
                                                        `web` run, or the guest's (Linux: browse, macOS: open).
  hold <key> <seconds|down|up> | tap <key> [count]      Hold a key, or only press or release it; tap it count times.
                                                        A macOS run VM posts modifiers (fn, option, command, control,
                                                        shift; r... for the right key) in the guest.
  click-text <text> [--nth N] [--timeout S] [--if-shown] [--role R] [--in BOX]
                                                        Click the words: a button with this label in the AX tree of
                                                        a macOS run VM first, else the matched words on the screen.
  ax [--app NAME] [--find TEXT] [--json] | click-ax <label> [--role R] [--app NAME] [--nth N] [--timeout S]
                                                        Read the accessibility tree of a run VM, or click by label.
  wait-text <text> [seconds] | find [text]              Wait for words, or print the words on the screen.
  check text|no-text|ax|no-ax <text> [seconds]          A pass or fail on the page. Text checks wait up to seconds.
                                                        --in x,y,w,h or --in <element label> looks only there.
  check cmd|sh "<command>" [seconds] [--label L]        A command on the host (cmd) or in the run VM (sh) exits 0;
                                                        it runs again until it does or the seconds pass.
  check running <process>                               A process with this exact name runs in the run VM.
  check metric <series glob> <stat> --below N|--above N [--last S|--step] [--wait S]
                                                        A budget on what a probe measured: stat is mean, min, max,
                                                        p50, p90, p95, p99, last, count, or failed. The window is the
                                                        run, the last S seconds, or the part since the last step.
  stats [session] [--json] [--all]                      What the probes measured, in a few lines.
  probes                                                The probes, where they run, and what they can see.
  event <kind> <text> [--x X --y Y] [--ok|--fail] [--detail D] [--t T --end E]   Log what another tool did.
  shot <png>                                            Save the screen.
  run <flow> [--set NAME=VALUE]                         Run a flow file: one proofreel command per line. A line
                                                        `condition <name>` refuses a run VM whose state lacks it, or
                                                        applies a condition that lasts one recording.
  suite <flows or folders...> [--state S] [--set NAME=VALUE] [--out DIR] [--title T] [--repeat N] [--each-condition A,B]
                                                        Run each flow from a new clone of its saved VM state (a flow
                                                        line `from <state>`, or --state), and publish one page.
  render <session> [--plain] [--width W]                Make the video and page of a session again. A session is
                                                        its folder or its name in the sessions folder.
  publish <session> --out <dir>                         Add a run to a review folder: one page, every run, one URL.
  skill install [--to DIR]                              Copy the skill to ~/.agents/skills/proofreel (Codex, Antigravity,
                                                        and Cursor read it), or to DIR/proofreel for another agent.
  demo [dir]                                            Render a made-up session (no VNC needed).
  clean [--days 7]                                      Delete sessions older than this.
  vm image|base|up|save|build|states|conditions|drop|down|sh|put|get   VMs (Tart or QEMU) or the headless Chrome of
                                                        `vm up web`, their saved states, and the conditions a state
                                                        can fake (see: proofreel vm -h).

The screen is the run VM of `proofreel vm up`, or --vnc host::port (a browser: cdp://host:port) with --password, or
PROOFREEL_VNC.
"""

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

from . import HOME, Problem, __version__, ax, conditions, emulation, flow, guest, image, metrics, plugins, probes, recording, session, summary
from .recording import log
from . import vm as vms
from .screen import center, connect, find, fold, inside, matches, poll, screen_text, wait_for


SHORT = """proofreel: record an app run as a review video and page. `proofreel help all` lists every command.

A web app, in four commands:
  vm up web                     Start a headless browser.
  open <url>                    Show a page. `find [text]` prints the words on the screen and where to click.
  suite <flow> --out DIR        Run the flow in a new browser and publish its review page. Prints the result.
  vm down                       Stop the browser.

A flow is a file with one command on each line. Start it with `from web`. These lines go in it:
  start <name> --title T --about A      Begin the recording. `stop` ends it.
  state <place> | step <text>           Say where the app is, and name the part that follows.
  click-text <text> | type <text> | key <keys> | click <x> <y> | move <x> <y>
  wait-text <text> [seconds]            Wait for words on the screen.
  check text|no-text <text> [seconds]   A pass or fail on what the screen shows. --in x,y,w,h looks in one box.
  check metric net/* p95 --below N      A budget on a measure.

To explore step by step, run those lines one at a time after `start`, then `stop`. `${NAME:-default}` in a flow
takes its value from `--set NAME=VALUE`. A native app or another system runs in a VM: `proofreel vm states`.
"""


def target(args):
    """The screen: (VNC server, password, run VM). The run VM is None for a screen that is not one."""
    if getattr(args, "vnc", None):
        return args.vnc, args.password, None
    if os.environ.get("PROOFREEL_VNC"):
        return os.environ["PROOFREEL_VNC"], os.environ.get("PROOFREEL_PASSWORD"), None
    if vms.CURRENT.exists():
        run = vms.Run.current()
        return run["screen"], run["screen_password"], run
    raise Problem("No screen. Use --vnc host::port, PROOFREEL_VNC, or proofreel vm up <state> (a web app: proofreel vm up web).")


def start(args):
    server, password, run = target(args)
    meta = dict(item.split("=", 1) for item in args.meta)
    if args.condition and not run:
        raise Problem("A condition needs a run VM: proofreel vm up <state>.")
    faked = [*(run["conditions"] if run else []),
             *(conditions.record(*plugins.spec(item), run["os"], recording=True) for item in args.condition)]
    if args.full_motion and not (run and run["os"] == "web"):
        raise Problem("--full-motion is for a web run: proofreel vm up web.")
    web = bool(run and run["os"] == "web")
    if run:
        meta.setdefault("from state", run["state"])
    if web and not args.full_motion:
        meta.setdefault("motion", "reduced")
    if source := session.revision():
        meta.setdefault("commit", source)
    info = {"title": args.title or args.name, "about": args.about, "meta": meta, "app": args.app, "conditions": faked,
            "probes": probes.select(args.probe, run),
            **({"emulate": emulation.commands(not args.full_motion, [c for c in faked if c.get("recording")])} if web else {})}
    print(f"Recording {recording.start(args.name, server, password, info, args.fps, args.reduce, run)}")


def stop(**options):
    """Exit 1 when a budget that waited for the end of the run failed."""
    folder = Path(recording.unstopped()["dir"]) if recording.unstopped() else None
    print(recording.stop(**options))
    print(summary.text(folder))
    run = json.loads((folder / "run.json").read_text())
    return 1 if any(e.get("late") and not e.get("ok") for e in run["events"]) else 0


def check(args, screen, run):
    if args.kind in ("text", "no-text", "ax", "no-ax"):
        text, present = args.args[0], not args.kind.startswith("no-")
        seconds = float(args.args[1]) if len(args.args) > 1 else (10 if present else 0)
        if args.kind.endswith("ax"):
            found = ax.wait_for(run, screen, text, seconds, present, app=args.app, role=args.role)
            return bool(found) == present, f'"{text}" is {"" if present else "not "}in the accessibility tree', ""
        found = wait_for(screen, text, seconds, present=present, within=scope(args.within, screen, run))
        where = f" in {args.within}" if args.within else ""
        ok = bool(found) == present
        return ok, f'"{text}" is {"" if present else "not "}on the screen{where}', "" if ok else shown(screen)
    if args.kind in ("sh", "running"):
        run = run or vms.Run.current()
    if args.kind in ("cmd", "sh"):
        if len(args.args) > 2:
            raise Problem(f'check {args.kind} takes one command and seconds. Quote the command: check {args.kind} "a b c" 10.')
        command, seconds = args.args[0], float(args.args[1]) if len(args.args) > 1 else 0
        end = time.time() + seconds
        while True:
            if args.kind == "cmd":
                result = subprocess.run(command, shell=True, capture_output=True, text=True)
            else:
                result = run.ssh(command, check=False)
            if result.returncode == 0 or time.time() >= end:
                break
            time.sleep(1)
        detail = (result.stdout + result.stderr).strip()[-400:]
        return result.returncode == 0, args.label or command, detail
    if args.kind == "running":
        name = args.args[0]
        return run.guest.running(run, name), args.label or f"{name} is running", ""
    if args.kind == "metric":
        return metric(args)
    raise Problem(f"Unknown check {args.kind!r}.")


def shown(screen):
    """What the screen shows, as detail for a failed text check."""
    return "The screen showed: " + summary.listed("", [line["text"] for line in screen_text(screen)], 12).strip()


def metric(args):
    active = recording.current()
    if not active:
        raise Problem("check metric needs a recording: its probes measure while it records.")
    folder = Path(active["dir"])
    if args.last:
        since, window = time.time() - args.last, f"the last {args.last:g} s"
    elif args.step:
        from .session import Session
        steps = [e["t"] for e in Session(folder).events() if e["kind"] in ("step", "state")]
        since, window = (steps[-1] if steps else None), "this step"
    else:
        since, window = None, "the run"
    if args.args[0].startswith(metrics.AFTER):
        return metrics.pending(args.args[0], args.args[1], args.below, args.above, since, time.time(), window)
    return metrics.check(folder, args.args[0], args.args[1], args.below, args.above, since, window, args.wait)


def parse(words):
    """The command's arguments, checked as far as they can be before it runs: a flow parses every line first."""
    a = parser().parse_args(words)
    if a.command == "check" and a.kind == "metric":
        if len(a.args) != 2 or a.args[1] not in metrics.STATS:
            raise Problem(f"Write: check metric <series glob> <stat> --below N. A stat is one of {', '.join(metrics.STATS)}.")
        if (a.below is None) == (a.above is None):
            raise Problem("check metric takes one of --below N or --above N.")
    return a


def scope(where, screen, run):
    """The box that --in names, as a function: x,y,w,h in screen pixels, or the label of an element in the
    accessibility tree (a macOS run VM). None when --in is not given."""
    if not where:
        return None
    parts = where.split(",")
    if len(parts) == 4 and all(part.strip().isdigit() for part in parts):
        box = [int(part) for part in parts]
        return lambda: box

    def element():
        if not (run and run.guest.ax):
            raise Problem(f'--in "{where}" names an element, and only a macOS run VM has the accessibility tree. '
                          f"Give a box in pixels: --in x,y,w,h.")
        found = ax.matches(ax.elements(run, screen), where)
        if not found:
            raise Problem(f'No element "{where}" is in the accessibility tree.')
        return found[0]["box"]
    return element


def locate(a, screen, run):
    """The click points of click-text. In a macOS run VM, buttons labeled exactly the text in the accessibility tree
    come first, when there are at least --nth of them; else the matched words on the screen. With --role, only
    elements with that role in the tree."""
    within = scope(a.within, screen, run)
    tree = bool(run and run.guest.ax)
    if a.role and not tree:
        raise Problem("--role reads the accessibility tree, and only a macOS run VM has it. Leave out --role.")
    want = fold(a.text)

    def look():
        nonlocal tree
        box = within() if within else None
        if tree:
            try:
                found = [e for e in ax.matches(ax.elements(run, screen), a.text, a.role or "button")
                         if box is None or inside((e["x"], e["y"]), box)]
            except Exception as error:
                if a.role:
                    raise Problem(f"The accessibility tree could not be read: {error}")
                tree, found = False, []
                log("note", f"The accessibility tree could not be read ({error}), so click-text reads the screen.")
            if not a.role:
                found = [e for e in found if any(fold(name) == want for name in ax.names(e))]
            if a.role or len(found) >= a.nth:
                return [(e["x"], e["y"]) for e in found]
        return [center(match) for match in matches(screen_text(screen), a.text, box)]
    return poll(look, a.timeout)


def run_check(args, screen, run=None):
    """Record the check and return 1 when it fails. A check that cannot run is a failed check, with the reason."""
    started = time.time()
    try:
        ok, label, detail, *fields = check(args, screen, run)
    except Problem as problem:
        ok, label, detail, fields = False, f"check {args.kind} {' '.join(args.args)}", f"The check could not run: {problem}", []
    log("check", label, t=started, end=time.time(), ok=ok, detail=detail, **(fields[0] if fields else {}))
    if ok is None:
        print(f"Pending: {label} ({detail})")
        return 0
    print(("Pass: " if ok else "Fail: ") + label + (f" ({detail})" if detail and not ok else ""))
    return 0 if ok else 1


def published(page, files, runs, new):
    """Write artifact.json next to the page (what an Artifact tool needs: the page, every file it uses, and its
    runtime capabilities) and return one line for the person or agent. Only an agent with that tool reads the file."""
    from .page import CAPABILITIES
    data = Path(page).parent / "artifact.json"
    data.write_text(json.dumps({"page": str(page.resolve()), "runs": runs, "files": files, "new": new,
                                "capabilities": CAPABILITIES}, indent=2))
    return f"Page: {page.resolve()} ({len(files)} files). For an Artifact tool: {data.resolve()}"


def load_flow(path, values):
    return flow.load(path, values, parse=parse)


def run_flow(path, values):
    return play(load_flow(path, values))


def play(steps, execute=None):
    """Run a loaded flow on the screen, once the run VM is from its saved state and has its conditions. execute runs
    one line (default: command); a `start` line gets the flow's probes and its conditions that last one recording."""
    run = vms.Run.current() if vms.CURRENT.exists() else {}
    state, have = run.get("state"), run.get("conditions", [])
    if steps.state and steps.state != state:
        raise Problem(f"{steps.name} starts from saved state {steps.state}, and the run VM is from {state or '(none)'}. "
                      f"Start it: proofreel vm up {steps.state}. Or run it in a suite: proofreel suite {steps.name}.")
    kept, applied = conditions.split(steps.conditions, run.get("os"))
    if gaps := conditions.missing(kept, have):
        raise Problem(f"{steps.name} needs condition {', '.join(gaps)}, and the run VM's state {state or '(none)'} "
                      f"has {', '.join(conditions.names(have)) or 'no conditions'}. Make a state with it: proofreel "
                      f"vm build <state> --from <base> {' '.join('--condition ' + g for g in gaps)}.")
    added = [f"--probe={p}" for p in steps.probes] + [f"--condition={c}" for c in applied] + \
        ([f"--meta=flow={steps.name} {steps.digest}"] if steps.digest else [])
    line = execute or command
    return flow.run(steps, lambda words: line(words + added if words[0] == "start" else words),
                    abort=lambda message: stop(error=message) if recording.unstopped() else None)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Problem(f"{self.prog}: {message}")


def parser():
    p = Parser(prog="proofreel", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"proofreel {__version__}")
    p.add_argument("--vnc")
    p.add_argument("--password")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("help", help="the short help; `help all` lists every command")
    s.add_argument("topic", nargs="?", choices=["all"])
    s = sub.add_parser("start")
    s.add_argument("name")
    s.add_argument("--title")
    s.add_argument("--about", default="")
    s.add_argument("--meta", action="append", default=[])
    s.add_argument("--app", help="the app under test (process name or bundle ID): its crash or hang fails the run")
    s.add_argument("--fps", type=float, default=30)
    s.add_argument("--reduce", type=int, default=0, help="keep 1/N of the pixels per side (0 = at most 1920 px wide)")
    s.add_argument("--probe", action="append", default=[])
    s.add_argument("--condition", action="append", default=[])
    s.add_argument("--full-motion", action="store_true", help="web: keep the page's animations (the default is prefers-reduced-motion)")
    s = sub.add_parser("stop")
    s.add_argument("--keep-frames", action="store_true")
    s.add_argument("--plain", action="store_true")
    s.add_argument("--width", type=int)
    for name in ("state", "step", "note", "type", "shot", "wait-text", "find", "click-text"):
        s = sub.add_parser(name)
        s.add_argument("text", nargs="?" if name == "find" else None)
        if name in ("wait-text", "find", "click-text"):
            s.add_argument("--in", dest="within", help="look only in this box: x,y,w,h in pixels, or an element label")
        if name == "wait-text":
            s.add_argument("seconds", nargs="?", type=float, default=30)
        if name == "click-text":
            s.add_argument("--nth", type=int, default=1)
            s.add_argument("--timeout", type=float, default=10)
            s.add_argument("--if-shown", action="store_true")
            s.add_argument("--role", help="click only an element with this role in the accessibility tree")
    s = sub.add_parser("ax")
    s.add_argument("--app")
    s.add_argument("--find")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("click-ax")
    s.add_argument("label")
    s.add_argument("--role")
    s.add_argument("--app")
    s.add_argument("--nth", type=int, default=1)
    s.add_argument("--timeout", type=float, default=10)
    s = sub.add_parser("open")
    s.add_argument("url")
    s = sub.add_parser("click")
    s.add_argument("x", type=int)
    s.add_argument("y", type=int)
    s.add_argument("--double", action="store_true")
    s.add_argument("--right", action="store_true")
    s.add_argument("--label")
    s = sub.add_parser("move")
    s.add_argument("x", type=int)
    s.add_argument("y", type=int)
    s = sub.add_parser("drag")
    for name in ("x1", "y1", "x2", "y2"):
        s.add_argument(name, type=int)
    s = sub.add_parser("key")
    s.add_argument("keys", nargs="+")
    s = sub.add_parser("hold")
    s.add_argument("key")
    s.add_argument("seconds", help="seconds, or down or up: only press or release the key")
    s = sub.add_parser("tap")
    s.add_argument("key")
    s.add_argument("count", type=int, nargs="?", default=1)
    s = sub.add_parser("check")
    s.add_argument("kind", choices=["text", "no-text", "ax", "no-ax", "cmd", "sh", "running", "metric"])
    s.add_argument("args", nargs="+")
    s.add_argument("--in", dest="within", help="text checks: look only in this box (x,y,w,h) or element (a label)")
    s.add_argument("--label")
    s.add_argument("--below", type=float)
    s.add_argument("--above", type=float)
    s.add_argument("--last", type=float)
    s.add_argument("--step", action="store_true")
    s.add_argument("--wait", type=float, default=2.0)
    s.add_argument("--app")
    s.add_argument("--role")
    s = sub.add_parser("event")
    s.add_argument("kind")
    s.add_argument("text")
    s.add_argument("--x", type=int)
    s.add_argument("--y", type=int)
    s.add_argument("--ok", action="store_const", const=True, dest="ok")
    s.add_argument("--fail", action="store_const", const=False, dest="ok")
    s.add_argument("--detail")
    s.add_argument("--t", type=float, help="when it happened (unix seconds); default now")
    s.add_argument("--end", type=float, help="when it ended, for an action that takes time")
    s = sub.add_parser("run")
    s.add_argument("flow")
    s.add_argument("--set", action="append", default=[])
    s = sub.add_parser("suite", help="run flows, each from a new clone of its saved state, into one review page")
    s.add_argument("flows", nargs="+", help="flow files, or folders of .flow files")
    s.add_argument("--state", help="the state of each flow that has no line from <state>")
    s.add_argument("--set", action="append", default=[])
    s.add_argument("--out", help="the review folder (default: a new suite folder in the sessions folder)")
    s.add_argument("--title")
    s.add_argument("--repeat", type=int, default=1, help="run each flow N times; a journey that differs between runs is flaky")
    s.add_argument("--each-condition", default="", help="run each flow once for each condition in this list (plain: none), "
                   "such as plain,phone,dark")
    s = sub.add_parser("ci", help="helpers for CI (see docs/ci.md)")
    s.add_argument("args", nargs=argparse.REMAINDER)
    s = sub.add_parser("render")
    s.add_argument("dir")
    s.add_argument("--plain", action="store_true")
    s.add_argument("--width", type=int)
    s = sub.add_parser("publish", help="add a session to a review folder (all runs of one journey) for one artifact URL")
    s.add_argument("session")
    s.add_argument("--out", required=True, help="the review folder; keep it the same for every run of this journey")
    s = sub.add_parser("demo")
    s.add_argument("dir", nargs="?", default=str(recording.SESSIONS / "demo"))
    s.add_argument("--broken", action="store_true", help="type the name wrong, so the last check fails")
    s = sub.add_parser("skill", help="copy the agent skill where a coding agent reads it")
    s.add_argument("action", choices=["install"])
    s.add_argument("--to", help="a folder; the skill goes to DIR/proofreel (default: ~/.agents/skills)")
    s = sub.add_parser("stats")
    s.add_argument("session", nargs="?")
    s.add_argument("--json", action="store_true")
    s.add_argument("--all", action="store_true")
    sub.add_parser("probes")
    s = sub.add_parser("clean")
    s.add_argument("--days", type=float, default=7)
    s = sub.add_parser("vm")
    vm = s.add_subparsers(dest="action", required=True)
    v = vm.add_parser("base", help="make a state from a Tart image or a QEMU disk (qcow2)")
    v.add_argument("name")
    v.add_argument("image")
    v.add_argument("--backend", choices=["tart", "qemu"], default="tart")
    v.add_argument("--os", choices=[name for name, g in guest.GUESTS.items() if g.shell], default="macos",
                   help="the guest system")
    v.add_argument("--user", default="admin")
    v.add_argument("--guest-password", default="admin")
    v = vm.add_parser("image", help="make the Linux browser state from nothing (Debian, Xfce, Chromium)")
    v.add_argument("name", nargs="?", default="linux")
    v = vm.add_parser("up", help="start the run VM from a state")
    v.add_argument("state")
    v.add_argument("--display")
    v.add_argument("--memory", type=int)
    v.add_argument("--cpu", type=int)
    v.add_argument("--warmable", action="store_true", help="allow save --warm later (Tart: turns off audio)")
    v = vm.add_parser("save", help="save the run VM as a state")
    v.add_argument("state")
    v.add_argument("--warm", action="store_true", help="keep memory: apps stay open")
    v.add_argument("--note", default="")
    v = vm.add_parser("build", help="start from a state, apply conditions, run a flow, save the result as a state")
    v.add_argument("state")
    v.add_argument("--from", dest="parent", required=True)
    v.add_argument("--flow")
    v.add_argument("--condition", action="append", default=[], help="a condition to fake (see: proofreel vm conditions)")
    v.add_argument("--set", action="append", default=[])
    v.add_argument("--warm", action="store_true")
    v.add_argument("--note", default="")
    vm.add_parser("states", help="list the states as a tree")
    vm.add_parser("conditions", help="list the conditions a state can fake")
    v = vm.add_parser("drop", help="delete a state")
    v.add_argument("state")
    vm.add_parser("down", help="stop and delete the run VM")
    v = vm.add_parser("sh", help="run a shell command in the run VM")
    v.add_argument("cmd", nargs=argparse.REMAINDER)
    v = vm.add_parser("put", help="copy a file into the run VM")
    v.add_argument("host")
    v.add_argument("guest")
    v = vm.add_parser("get", help="copy a file out of the run VM")
    v.add_argument("guest")
    v.add_argument("host")
    return p


def install_skill(to):
    """Copy the skill folder to to/proofreel, over an older copy. Returns the new folder."""
    import shutil
    here = Path(__file__).parent
    source = next((p for p in (here / "skill", here.parents[1] / "skills" / "proofreel") if (p / "SKILL.md").exists()), None)
    if not source:
        raise Problem("The skill files are missing from this install.")
    target = Path(to or Path.home() / ".agents" / "skills").expanduser() / "proofreel"
    shutil.copytree(source, target, dirs_exist_ok=True)
    return target


def stats(a):
    folder = recording.session_folder(a.session) if a.session else Path((recording.current() or {}).get("dir") or newest())
    found = metrics.load(folder)
    if a.json:
        return print(json.dumps({"series": {m: {stat: found.stat(m, stat) for stat in metrics.STATS}
                                            for m in found.series()}, "probes": found.status}, indent=1))
    lines = found.summary(limit=10_000 if a.all else 12)
    print("\n".join(lines) if lines else f"No metrics in {folder}.")


def newest():
    folders = sorted(recording.SESSIONS.glob("*/session.json"), key=lambda p: p.stat().st_mtime)
    if not folders:
        raise Problem("No sessions. Name one: proofreel stats <session folder>.")
    return folders[-1].parent


def list_probes():
    for name, source in plugins.known("probe").items():
        info = probes.manifest(name)
        print(f"{name}  ({info['where']}{', on by default' + (' on ' + ', '.join(info['default']) if isinstance(info['default'], dict) else '') if info.get('default') else ''}; {', '.join(info['os'])}"
              f"{'; ' + source if source else ''})\n  sees: {info['privacy']}\n  fidelity: {info['fidelity']}"
              + (f"\n  needs: pip install {' or '.join(probes.packages(info))}" if probes.packages(info) else ""))


def vm(a):
    match a.action:
        case "image": image.make(a.name)
        case "base": vms.base(a.name, a.image, a.backend, a.os, a.user, a.guest_password)
        case "up": vms.up(a.state, a.display, a.memory, a.cpu, a.warmable)
        case "save": vms.save(a.state, a.warm, a.note)
        case "build":
            if not (a.flow or a.condition):
                raise Problem("Give --flow, --condition, or both.")
            values = dict(v.split("=", 1) for v in a.set)
            system = vms.state_info(a.parent)["os"]
            applied = [conditions.record(name, values, system, recording=False) for name in a.condition]
            run = vms.up(a.parent, warmable=a.warm)
            for each in applied:
                conditions.apply(run, each)
            if a.flow:
                run_flow(a.flow, values)
            vms.save(a.state, a.warm, a.note, flow=str(Path(a.flow).resolve()) if a.flow else None, values=values,
                     conditions=applied)
        case "states": vms.states()
        case "conditions":
            for name, source in plugins.known("condition").items():
                info = plugins.manifest("condition", plugins.find("condition", name))
                values = " ".join(f"{k}={v or '...'}" for k, v in info["values"].items())
                lasts = "; one recording" if conditions.lasts_one_recording(info, "web" if info["os"] == ["web"] else "") else ""
                profiles = f"\n  Profiles: {', '.join(info['profiles'])}" if info["profiles"] else ""
                print(f"{name}  ({', '.join(info['os'])}{lasts}{', ' + source if source else ''})"
                      f"{'  ' + values if values else ''}\n  {info['fakes']}{profiles}\n  Not faked: {info['fidelity']}")
        case "drop": vms.drop(a.state)
        case "down": vms.down()
        case "sh": return vms.Run.current().ssh(shlex.join(a.cmd) if len(a.cmd) > 1 else a.cmd[0], check=False,
                                                capture=False).returncode
        case "put": vms.Run.current().upload(a.host, a.guest)
        case "get": vms.Run.current().download(a.guest, a.host)


def main(argv=None):
    """The only exit: 0 done, 1 a failed check (or nothing found), 2 a problem, with its message."""
    try:
        code = command(argv)
    except Problem as problem:
        print(f"proofreel: {problem}", file=sys.stderr)
        code = 2
    finally:
        from vncdotool import api
        api.shutdown()
    sys.exit(code or 0)


def watch(a, force=False):
    """Save the text of the screen for the summary. A screen that cannot be read leaves no save and a warning: the
    run goes on, and the summary has no line for that step."""
    if active := recording.current():
        try:
            server, password, run = target(a)
            with connect(server, password, run.guest.keys if run else None) as screen:
                summary.save(active["dir"], screen_text(screen), force)
        except Exception as error:
            print(f"proofreel: could not read the screen text for the summary ({error}).", file=sys.stderr)


def command(argv):
    """Run one command. Returns 1 for a failed check or a query that found nothing."""
    a = parse(argv)
    HOME.mkdir(parents=True, exist_ok=True)
    if a.command in ("state", "step", "stop"):
        watch(a)
    match a.command:
        case "help": return print(__doc__.strip() if a.topic else SHORT.strip())
        case "start":
            code = start(a)
            watch(a, force=True)
            return code
        case "stop": return stop(plain=a.plain, width=a.width, keep_frames=a.keep_frames)
        case "state" | "step" | "note": return log(a.command, a.text)
        case "event":
            fields = {k: v for k, v in (("x", a.x), ("y", a.y), ("ok", a.ok), ("detail", a.detail)) if v is not None}
            if a.kind == "check":
                fields["reported"] = True
            return log(a.kind, a.text, a.t, a.end, **fields)
        case "run": return run_flow(a.flow, dict(v.split("=", 1) for v in a.set))
        case "suite":
            from . import suite
            values = dict(v.split("=", 1) for v in a.set)
            result, rows = suite.run(a.flows, lambda path: load_flow(path, values), play, command, a.state, a.out,
                                     a.title, a.repeat, [c for c in a.each_condition.split(",") if c])
            print(published(*result))
            return 1 if any(mark in ("FAIL", "FLAKY") for mark, _, _ in rows) else 0
        case "ci":
            from . import ci
            return ci.main(a.args)
        case "render":
            from .render import render
            return print(render(recording.session_folder(a.dir), framed=not a.plain, width=a.width))
        case "publish":
            from .page import publish
            return print(published(*publish(recording.session_folder(a.session), a.out)))
        case "skill":
            folder = install_skill(a.to)
            return print(f"Wrote {folder}/SKILL.md\n"
                  "Codex, Antigravity, and Cursor read .agents/skills in a project and ~/.agents/skills.\n"
                  "Another agent: tell it to follow the skill at the path above.")
        case "demo":
            from .demo import demo
            return demo(Path(a.dir), a.broken)
        case "clean":
            for folder in recording.clean(a.days):
                print(f"Deleted {folder}")
        case "vm": return vm(a)
        case "stats": return stats(a)
        case "probes": return list_probes()
        case "check" if a.kind in ("cmd", "sh", "running", "metric"):
            return run_check(a, None)
    server, password, run = target(a)
    if (a.command in ("ax", "click-ax") or a.command == "check" and a.kind.endswith("ax")) and not (run and run.guest.ax):
        problem = "AX reads a macOS run VM over SSH (proofreel vm up <state>), not a --vnc screen or another system."
        if a.command == "check":
            log("check", f"check {a.kind} {' '.join(a.args)}", ok=False, detail=f"The check could not run: {problem}")
            return 1
        raise Problem(problem)
    with connect(server, password, run.guest.keys if run else None) as screen:
        return act(a, screen, run)


def act(a, screen, run):
    system = run.guest if run else guest.Guest()
    match a.command:
        case "click":
            label = a.label or f"click {a.x}, {a.y}"
            kind = "double" if a.double else "right" if a.right else "click"
            log(kind, label, *screen.click(a.x, a.y, button=3 if a.right else 1, count=2 if a.double else 1),
                x=a.x, y=a.y)
        case "move":
            log("move", f"move {a.x}, {a.y}", *screen.move(a.x, a.y), x=a.x, y=a.y)
        case "drag":
            log("drag", f"drag {a.x1}, {a.y1} to {a.x2}, {a.y2}", *screen.drag(a.x1, a.y1, a.x2, a.y2),
                x=a.x1, y=a.y1, x2=a.x2, y2=a.y2)
        case "type":
            log("type", f'type "{a.text}"', *screen.type(a.text))
        case "key":
            log("key", " ".join(a.keys), *screen.key(*a.keys))
        case "hold" if a.seconds in ("down", "up"):
            log("hold", f"{'press' if a.seconds == 'down' else 'release'} {a.key}",
                *system.press(run, screen, a.key, a.seconds == "down"))
        case "hold":
            try:
                seconds = float(a.seconds)
            except ValueError:
                raise Problem(f"hold takes seconds, down, or up, not {a.seconds!r}.")
            log("hold", f"hold {a.key} for {seconds:g} s", *system.hold(run, screen, a.key, seconds))
        case "tap":
            log("tap", f"tap {a.key}" + (f" {a.count} times" if a.count > 1 else ""),
                *system.tap(run, screen, a.key, a.count))
        case "open":
            if not a.url.startswith(("http://", "https://", "file://", "about:")):
                raise Problem(f"open takes a URL that starts with http://, https://, or file://, not {a.url!r}.")
            log("open", f"open {a.url}", *system.open(run, screen, a.url))
        case "shot": screen.capture(a.text)
        case "find":
            lines = find(screen, a.text, scope(a.within, screen, run)) if a.text else screen_text(screen)
            for line in lines:
                print(f"{center(line)[0]:5} {center(line)[1]:5}  {line['text']}")
            return 1 if a.text and not lines else 0
        case "wait-text":
            started = time.time()
            ok = bool(wait_for(screen, a.text, a.seconds, within=scope(a.within, screen, run)))
            log("wait", f'wait for "{a.text}"', t=started, end=time.time(), ok=ok,
                detail=f"seen after {time.time() - started:.1f} s" if ok else f"not seen in {a.seconds:.0f} s")
            if not ok:
                raise Problem(f'"{a.text}" did not show in {a.seconds:.0f} s.')
        case "click-text":
            points = locate(a, screen, run)
            if len(points) < a.nth:
                if a.if_shown:
                    return
                raise Problem(f'"{a.text}" is not on the screen.')
            x, y = points[a.nth - 1]
            log("click", f'click "{a.text}"', *screen.click(x, y), x=x, y=y)
        case "ax":
            if a.json:
                return print(json.dumps(ax.tree(run, a.app), indent=1, ensure_ascii=False))
            found = ax.matches(ax.elements(run, screen, a.app), a.find) if a.find else ax.elements(run, screen, a.app)
            for element in found:
                print(ax.describe(element, indent=not a.find))
            return 1 if a.find and not found else 0
        case "click-ax":
            found = ax.wait_for(run, screen, a.label, a.timeout, app=a.app, role=a.role)
            if len(found) < a.nth:
                raise Problem(f'"{a.label}" is not in the accessibility tree.')
            x, y = found[a.nth - 1]["x"], found[a.nth - 1]["y"]
            log("click", f'click "{a.label}"', *screen.click(x, y), x=x, y=y)
        case "check":
            return run_check(a, screen, run)


if __name__ == "__main__":
    main()
