"""proofreel: record an agent driving a screen as a review video and page.

  start <name> [--title T] [--about A] [--meta K=V] [--app NAME]   Start recording. Every later action and check is
                                                        logged. --app names the app under test: its crash fails the run.
  stop [--keep-frames] [--plain] [--width W]            Stop, then make session.mp4, index.html, and shots/. In a macOS
                                                        run VM, new crash and hang reports go to reports/ and the log.
  step <text> | note <text>                             Name the next part (a caption in the video), or add a note.
  click <x> <y> [--double|--right] | move <x> <y> | drag <x1> <y1> <x2> <y2> | type <text> | key <keys...>
  hold <key> <seconds|down|up> | tap <key> [count]      Hold a key, or only press or release it; tap it count times.
                                                        A macOS run VM posts modifiers (fn, option, command, control,
                                                        shift; r... for the right key) in the guest.
  click-text <text> [--nth N] [--timeout S] [--if-shown]   Find the words on the screen, then click them.
  ax [--app NAME] [--find TEXT] [--json] | click-ax <label> [--role R] [--app NAME] [--nth N] [--timeout S]
                                                        Read the accessibility tree of a run VM, or click by label.
  wait-text <text> [seconds] | find [text]              Wait for words, or print the words on the screen.
  check text|no-text|ax|no-ax <text> [seconds] | check cmd <shell command> --label L   A pass or fail on the page.
  event <kind> <text> [--x X --y Y] [--ok|--fail] [--detail D] [--t T --end E]   Log what another tool did.
  shot <png>                                            Save the screen.
  run <flow> [--set NAME=VALUE]                         Run a flow file: one proofreel command per line. A line
                                                        `condition <name>` refuses a run VM whose state lacks it.
  render <dir> [--plain] [--width W]                    Make the video and page of a session folder again.
  publish <session> --out <dir>                         Add a run to a review folder: one page, every run, one URL.
  demo [dir]                                            Render a made-up session (no VNC needed).
  clean [--days 7]                                      Delete sessions older than this.
  vm base|up|save|build|states|conditions|drop|down|sh|put|get   VMs (Tart or QEMU), their saved states, and the
                                                        conditions a state can fake (see: proofreel vm -h).

The screen is the run VM of `proofreel vm up`, or --vnc host::port with --password, or PROOFREEL_VNC.
"""

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

from . import HOME, Problem, ax, conditions, flow, guest, recording
from .recording import log
from . import vm as vms
from .screen import Screen, center, find, screen_text, wait_for



def target(args):
    """The screen: (VNC server, password, run VM). The run VM is None for a screen that is not one."""
    if getattr(args, "vnc", None):
        return args.vnc, args.password, None
    if os.environ.get("PROOFREEL_VNC"):
        return os.environ["PROOFREEL_VNC"], os.environ.get("PROOFREEL_PASSWORD"), None
    if vms.CURRENT.exists():
        run = vms.Run.current()
        return run["vnc"], run["vnc_password"], run
    raise Problem("No screen. Use --vnc host::port, PROOFREEL_VNC, or proofreel vm up <state>.")


def start(args):
    server, password, run = target(args)
    meta = dict(item.split("=", 1) for item in args.meta)
    faked = run["conditions"] if run else []
    if run:
        meta.setdefault("from state", run["state"])
    info = {"title": args.title or args.name, "about": args.about, "meta": meta, "app": args.app, "conditions": faked}
    print(f"Recording {recording.start(args.name, server, password, info, args.fps, args.reduce, run)}")


def stop(**options):
    print(recording.stop(**options))


def check(args, screen, run):
    if args.kind in ("text", "no-text", "ax", "no-ax"):
        text, present = args.args[0], not args.kind.startswith("no-")
        seconds = float(args.args[1]) if len(args.args) > 1 else (10 if present else 0)
        if args.kind.endswith("ax"):
            found = ax.wait_for(run, screen, text, seconds, present, app=args.app, role=args.role)
            return bool(found) == present, f'"{text}" is {"" if present else "not "}in the accessibility tree', ""
        found = wait_for(screen, text, seconds, present=present)
        return bool(found) == present, f'"{text}" is {"" if present else "not "}on the screen', ""
    if args.kind == "cmd":
        command = " ".join(args.args)
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        detail = (result.stdout + result.stderr).strip()[-400:]
        return result.returncode == 0, args.label or command, detail
    raise Problem(f"Unknown check {args.kind!r}.")


def run_check(args, screen, run=None):
    """Record the check and return 1 when it fails. A check that cannot run is a failed check, with the reason."""
    started = time.time()
    try:
        ok, label, detail = check(args, screen, run)
    except Problem as problem:
        ok, label, detail = False, f"check {args.kind} {' '.join(args.args)}", f"The check could not run: {problem}"
    log("check", label, t=started, end=time.time(), ok=ok, detail=detail)
    print(("Pass: " if ok else "Fail: ") + label + (f" ({detail})" if detail and not ok else ""))
    return 0 if ok else 1


def run_flow(path, values):
    steps = flow.load(path, values, parse=lambda words: parser().parse_args(words))
    if steps.conditions:
        run = vms.Run.current() if vms.CURRENT.exists() else {}
        state, have = run.get("state"), run.get("conditions", [])
        if gaps := conditions.missing(steps.conditions, have):
            raise Problem(f"{steps.name} needs condition {', '.join(gaps)}, and the run VM's state {state or '(none)'} "
                          f"has {', '.join(conditions.names(have)) or 'no conditions'}. Make a state with it: proofreel "
                          f"vm build <state> --from <base> {' '.join('--condition ' + g for g in gaps)}.")
    return flow.run(steps, command, abort=lambda message: stop(error=message) if recording.current() else None)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Problem(f"{self.prog}: {message}")


def parser():
    p = Parser(prog="proofreel", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--vnc")
    p.add_argument("--password")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("start")
    s.add_argument("name")
    s.add_argument("--title")
    s.add_argument("--about", default="")
    s.add_argument("--meta", action="append", default=[])
    s.add_argument("--app", help="the app under test (process name or bundle ID): its crash or hang fails the run")
    s.add_argument("--fps", type=float, default=30)
    s.add_argument("--reduce", type=int, default=0, help="keep 1/N of the pixels per side (0 = at most 1920 px wide)")
    s = sub.add_parser("stop")
    s.add_argument("--keep-frames", action="store_true")
    s.add_argument("--plain", action="store_true")
    s.add_argument("--width", type=int)
    for name in ("step", "note", "type", "shot", "wait-text", "find", "click-text"):
        s = sub.add_parser(name)
        s.add_argument("text", nargs="?" if name == "find" else None)
        if name == "wait-text":
            s.add_argument("seconds", nargs="?", type=float, default=30)
        if name == "click-text":
            s.add_argument("--nth", type=int, default=1)
            s.add_argument("--timeout", type=float, default=10)
            s.add_argument("--if-shown", action="store_true")
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
    s.add_argument("kind", choices=["text", "no-text", "ax", "no-ax", "cmd"])
    s.add_argument("args", nargs="+")
    s.add_argument("--label")
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
    s = sub.add_parser("clean")
    s.add_argument("--days", type=float, default=7)
    s = sub.add_parser("vm")
    vm = s.add_subparsers(dest="action", required=True)
    v = vm.add_parser("base", help="make a state from a Tart image or a QEMU disk (qcow2)")
    v.add_argument("name")
    v.add_argument("image")
    v.add_argument("--backend", choices=["tart", "qemu"], default="tart")
    v.add_argument("--os", choices=list(guest.GUESTS), default="macos", help="the guest system")
    v.add_argument("--user", default="admin")
    v.add_argument("--guest-password", default="admin")
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


def vm(a):
    match a.action:
        case "base": vms.base(a.name, a.image, a.backend, a.os, a.user, a.guest_password)
        case "up": vms.up(a.state, a.display, a.memory, a.cpu, a.warmable)
        case "save": vms.save(a.state, a.warm, a.note)
        case "build":
            if not (a.flow or a.condition):
                raise Problem("Give --flow, --condition, or both.")
            values = dict(v.split("=", 1) for v in a.set)
            for name in a.condition:
                conditions.resolve(conditions.fits(name, vms.state_info(a.parent)["os"]), values)
            run = vms.up(a.parent, warmable=a.warm)
            applied = [conditions.apply(run, name, values) for name in a.condition]
            if a.flow:
                run_flow(a.flow, values)
            vms.save(a.state, a.warm, a.note, flow=str(Path(a.flow).resolve()) if a.flow else None, values=values,
                     conditions=applied)
        case "states": vms.states()
        case "conditions":
            for name in conditions.known():
                info = conditions.manifest(conditions.folder(name))
                values = " ".join(f"{k}={v or '...'}" for k, v in info["values"].items())
                print(f"{name}  ({', '.join(info['os'])}){'  ' + values if values else ''}\n  {info['fakes']}\n"
                      f"  Not faked: {info['fidelity']}")
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


def command(argv):
    """Run one command. Returns 1 for a failed check or a query that found nothing."""
    a = parser().parse_args(argv)
    HOME.mkdir(parents=True, exist_ok=True)
    match a.command:
        case "start": return start(a)
        case "stop": return stop(plain=a.plain, width=a.width, keep_frames=a.keep_frames)
        case "step" | "note": return log(a.command, a.text)
        case "event":
            fields = {k: v for k, v in (("x", a.x), ("y", a.y), ("ok", a.ok), ("detail", a.detail)) if v is not None}
            return log(a.kind, a.text, a.t, a.end, **fields)
        case "run": return run_flow(a.flow, dict(v.split("=", 1) for v in a.set))
        case "render":
            from .render import render
            return print(render(a.dir, framed=not a.plain, width=a.width))
        case "publish":
            from .page import CAPABILITIES, publish
            page, files, runs = publish(a.session, a.out)
            return print(json.dumps({"page": str(page.resolve()), "runs": runs, "files": files,
                                     "capabilities": CAPABILITIES}, indent=2))
        case "demo":
            from .demo import demo
            return demo(Path(a.dir), a.broken)
        case "clean":
            for folder in recording.clean(a.days):
                print(f"Deleted {folder}")
        case "vm": return vm(a)
        case "check" if a.kind == "cmd":
            return run_check(a, None)
    server, password, run = target(a)
    if (a.command in ("ax", "click-ax") or a.command == "check" and a.kind.endswith("ax")) and not (run and run.guest.ax):
        problem = "AX reads a macOS run VM over SSH (proofreel vm up <state>), not a --vnc screen or another system."
        if a.command == "check":
            log("check", f"check {a.kind} {' '.join(a.args)}", ok=False, detail=f"The check could not run: {problem}")
            return 1
        raise Problem(problem)
    with Screen(server, password, run.guest.keys if run else None) as screen:
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
        case "shot": screen.capture(a.text)
        case "find":
            lines = find(screen, a.text) if a.text else screen_text(screen)
            for line in lines:
                print(f"{center(line)[0]:5} {center(line)[1]:5}  {line['text']}")
            return 1 if a.text and not lines else 0
        case "wait-text":
            started = time.time()
            ok = bool(wait_for(screen, a.text, a.seconds))
            log("wait", f'wait for "{a.text}"', t=started, end=time.time(), ok=ok,
                detail=f"seen after {time.time() - started:.1f} s" if ok else f"not seen in {a.seconds:.0f} s")
            if not ok:
                raise Problem(f'"{a.text}" did not show in {a.seconds:.0f} s.')
        case "click-text":
            lines = wait_for(screen, a.text, a.timeout)
            if len(lines) < a.nth:
                if a.if_shown:
                    return
                raise Problem(f'"{a.text}" is not on the screen.')
            x, y = center(lines[a.nth - 1])
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
