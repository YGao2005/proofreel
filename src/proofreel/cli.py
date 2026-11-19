"""proofreel: record an agent driving a screen as a review video and page.

  start <name> [--title T] [--about A] [--meta K=V] [--app NAME]   Start recording. Every later action and check is
                                                        logged. --app names the app under test: its crash fails the run.
  stop [--keep-frames] [--plain] [--width W]            Stop, then make session.mp4, index.html, and shots/. In a macOS
                                                        run VM, new crash and hang reports go to reports/ and the log.
  step <text> | note <text>                             Name the next part (a caption in the video), or add a note.
  click <x> <y> [--double|--right] | move <x> <y> | drag <x1> <y1> <x2> <y2> | type <text> | key <keys...>
  hold <key> <seconds>                                  Hold a key down, such as option (Left Option in a macOS VM).
  click-text <text> [--nth N] [--timeout S] [--if-shown]   Find the words on the screen, then click them.
  ax [--app NAME] [--find TEXT] [--json] | click-ax <label> [--role R] [--app NAME] [--nth N] [--timeout S]
                                                        Read the accessibility tree of a run VM, or click by label.
  wait-text <text> [seconds] | find [text]              Wait for words, or print the words on the screen.
  check text|no-text|ax|no-ax <text> [seconds] | check cmd <shell command> --label L   A pass or fail on the page.
  event <kind> <text> [--x X --y Y] [--ok|--fail] [--detail D]   Log an action that another tool did.
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
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import HOME, ax, conditions, guest
from . import vm as vms
from .screen import Screen, center, find, screen_text, wait_for

SESSIONS = Path(os.environ.get("PROOFREEL_SESSIONS", HOME / "sessions"))
ACTIVE = HOME / f"{vms.RUN}-session.json"


def target(args):
    """The screen: (VNC server, password, guest). The guest is None for a screen that is not the run VM."""
    if getattr(args, "vnc", None):
        return args.vnc, args.password, None
    if os.environ.get("PROOFREEL_VNC"):
        return os.environ["PROOFREEL_VNC"], os.environ.get("PROOFREEL_PASSWORD"), None
    if vms.CURRENT.exists():
        run = vms.current()
        return run["vnc"], run["vnc_password"], guest.of(run)
    sys.exit("No screen. Use --vnc host::port, PROOFREEL_VNC, or proofreel vm up <state>.")


def active():
    return json.loads(ACTIVE.read_text()) if ACTIVE.exists() else None


def log(kind, text, t=None, **fields):
    session = active()
    if session:
        with open(Path(session["dir"]) / "events.jsonl", "a") as out:
            out.write(json.dumps({"t": t or time.time(), "kind": kind, "text": text, **fields}) + "\n")


def start(args):
    if active():
        sys.exit(f"A session is recording: {active()['dir']}. Stop it first.")
    server, password, system = target(args)
    folder = SESSIONS / f"{args.name}-{time.strftime('%Y%m%d-%H%M%S')}"
    folder.mkdir(parents=True)
    meta = dict(item.split("=", 1) for item in args.meta)
    faked = []
    if system:
        run = vms.current()
        meta.setdefault("from state", run["state"])
        faked = run["conditions"]
        if faked:
            meta.setdefault("conditions", ", ".join(conditions.names(faked)))
        system.mark()
    meta.setdefault("", time.strftime("%Y-%m-%d %H:%M"))
    (folder / "session.json").write_text(json.dumps({"title": args.title or args.name, "about": args.about,
                                                    "meta": meta, "app": args.app, "conditions": faked,
                                                    "os": system.name if system else None,
                                                    "started": time.time()}))
    recorder = subprocess.Popen([sys.executable, "-m", "proofreel.capture", str(folder), server, password or "",
                                 str(args.fps), str(args.reduce)], stdout=open(folder / "recorder.log", "w"),
                                stderr=subprocess.STDOUT, start_new_session=True)
    ACTIVE.write_text(json.dumps({"dir": str(folder), "recorder": recorder.pid}))
    time.sleep(1.5)
    print(f"Recording {folder}")


def stop(plain=False, width=None, keep_frames=False, error=None):
    session = active()
    if not session:
        sys.exit("No session is recording.")
    subprocess.run(["kill", str(session["recorder"])], capture_output=True)
    folder = Path(session["dir"])
    for _ in range(50):
        if subprocess.run(["kill", "-0", str(session["recorder"])], capture_output=True).returncode:
            break
        time.sleep(0.1)
    ACTIVE.unlink()
    info = json.loads((folder / "session.json").read_text())
    if info.get("os"):
        with open(folder / "events.jsonl", "a") as out:
            for event in guest.GUESTS[info["os"]].harvest(folder, info.get("app"), info.get("started", 0)):
                out.write(json.dumps(event) + "\n")
    if error:
        (folder / "session.json").write_text(json.dumps({**info, "error": error}))
    from .render import render
    verdict, length, real, size = render(folder, framed=not plain, width=width)
    if not keep_frames:
        shutil.rmtree(folder / "frames", ignore_errors=True)
    print(f"{verdict}. {real:.0f} s of screen in a {length:.0f} s video, {size:.1f} MB. Page: {folder / 'index.html'}")


def check(args, screen):
    if args.kind in ("text", "no-text", "ax", "no-ax"):
        text, present = args.args[0], not args.kind.startswith("no-")
        seconds = float(args.args[1]) if len(args.args) > 1 else (10 if present else 0)
        if args.kind.endswith("ax"):
            found = ax.wait_for(screen, text, seconds, present, app=args.app, role=args.role)
            return bool(found) == present, f'"{text}" is {"" if present else "not "}in the accessibility tree', ""
        found = wait_for(screen, text, seconds, present=present)
        return bool(found) == present, f'"{text}" is {"" if present else "not "}on the screen', ""
    if args.kind == "cmd":
        command = " ".join(args.args)
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        detail = (result.stdout + result.stderr).strip()[-400:]
        return result.returncode == 0, args.label or command, detail
    sys.exit(f"Unknown check {args.kind!r}.")


def expand(line, values):
    def value(match):
        name, default = match["name"], match["default"]
        if name in values:
            return values[name]
        if default is not None:
            return default
        raise SystemExit(f"No value for ${{{name}}}. Pass --set {name}=...")
    return re.sub(r"\$\{(?P<name>\w+)(?::-(?P<default>[^}]*))?\}", value, line)


def needed(text):
    """The conditions a flow declares with `condition <name>` lines."""
    return [words[1] for words in map(lambda line: shlex.split(line, comments=True), text.splitlines())
            if len(words) > 1 and words[0] == "condition"]


def run_flow(path, values):
    path = Path(path)
    text = path.read_text()
    if wanted := needed(text):
        run = vms.current() if vms.CURRENT.exists() else {}
        state, have = run.get("state"), run.get("conditions", [])
        if gaps := conditions.missing(wanted, have):
            sys.exit(f"{path.name} needs condition {', '.join(gaps)}, and the run VM's state {state or '(none)'} has "
                     f"{', '.join(conditions.names(have)) or 'no conditions'}. Make a state with it: proofreel vm "
                     f"build <state> --from <base> {' '.join('--condition ' + g for g in gaps)}.")
    for number, raw in enumerate(text.splitlines(), 1):
        words = shlex.split(expand(raw, values), comments=True)
        if not words or words[0] == "condition":
            continue
        print(f"{path.name}:{number}: {' '.join(words)}")
        try:
            main(words)
        except SystemExit as stop_flow:
            if stop_flow.code in (0, None):
                continue
            if words[0] == "check":
                continue
            if active():
                stop(error=f"{path.name}:{number}: {' '.join(words)}: {stop_flow.code}")
            raise


def parser():
    p = argparse.ArgumentParser(prog="proofreel", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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
    s.add_argument("seconds", type=float)
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
    s.add_argument("dir", nargs="?", default=str(SESSIONS / "demo"))
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
                sys.exit("Give --flow, --condition, or both.")
            values = dict(v.split("=", 1) for v in a.set)
            for name in a.condition:
                conditions.resolve(conditions.fits(name, vms.state_info(a.parent)["os"]), values)
            vms.up(a.parent, warmable=a.warm)
            applied = [conditions.apply(name, values) for name in a.condition]
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
        case "sh": sys.exit(vms.ssh(shlex.join(a.cmd) if len(a.cmd) > 1 else a.cmd[0], check=False,
                                    capture=False).returncode)
        case "put": vms.put(a.host, a.guest)
        case "get": vms.get(a.guest, a.host)


def main(argv=None):
    if argv is not None:
        return command(argv)
    try:
        return command(None)
    finally:
        from vncdotool import api
        api.shutdown()


def command(argv):
    a = parser().parse_args(argv)
    HOME.mkdir(parents=True, exist_ok=True)
    match a.command:
        case "start": return start(a)
        case "stop": return stop(a.plain, a.width, a.keep_frames)
        case "step" | "note": return log(a.command, a.text)
        case "event":
            fields = {k: v for k, v in (("x", a.x), ("y", a.y), ("ok", a.ok), ("detail", a.detail)) if v is not None}
            return log(a.kind, a.text, **fields)
        case "run": return run_flow(a.flow, dict(v.split("=", 1) for v in a.set))
        case "render":
            from .render import render
            verdict, length, real, size = render(a.dir, framed=not a.plain, width=a.width)
            return print(f"{verdict}. {real:.0f} s in a {length:.0f} s video, {size:.1f} MB. Page: {Path(a.dir) / 'index.html'}")
        case "publish":
            from .page import CAPABILITIES, publish
            page, files, runs = publish(a.session, a.out)
            return print(json.dumps({"page": str(page.resolve()), "runs": runs, "files": files,
                                     "capabilities": CAPABILITIES}, indent=2))
        case "demo":
            from .demo import demo
            return demo(Path(a.dir), a.broken)
        case "clean": return clean(a.days)
        case "vm": return vm(a)
        case "check" if a.kind == "cmd":
            ok, label, detail = check(a, None)
            log("check", label, ok=ok, detail=detail)
            print(("Pass: " if ok else "Fail: ") + label)
            return sys.exit(0 if ok else 1)
    server, password, system = target(a)
    if (a.command in ("ax", "click-ax") or a.command == "check" and a.kind.endswith("ax")) and not (system and system.ax):
        sys.exit("AX reads a macOS run VM over SSH (proofreel vm up <state>), not a --vnc screen or another system.")
    with Screen(server, password, system.keys if system else None) as screen:
        act(a, screen)


def act(a, screen):
    match a.command:
        case "click":
            label = a.label or f"click {a.x}, {a.y}"
            kind = "double" if a.double else "right" if a.right else "click"
            log(kind, label, x=a.x, y=a.y)
            screen.click(a.x, a.y, button=3 if a.right else 1, count=2 if a.double else 1)
        case "move":
            log("move", f"move {a.x}, {a.y}", x=a.x, y=a.y)
            screen.move(a.x, a.y)
        case "drag":
            log("drag", f"drag {a.x1}, {a.y1} to {a.x2}, {a.y2}", x=a.x1, y=a.y1, x2=a.x2, y2=a.y2)
            screen.drag(a.x1, a.y1, a.x2, a.y2)
        case "type":
            started = time.time()
            screen.type(a.text)
            log("type", f'type "{a.text}"', t=started, dur=round(time.time() - started, 2))
        case "key":
            log("key", " ".join(a.keys))
            screen.key(*a.keys)
        case "hold":
            log("hold", f"hold {a.key} for {a.seconds:g} s", dur=a.seconds)
            screen.hold(a.key, a.seconds)
        case "shot": screen.capture(a.text)
        case "find":
            lines = find(screen, a.text) if a.text else screen_text(screen)
            for line in lines:
                print(f"{center(line)[0]:5} {center(line)[1]:5}  {line['text']}")
            if a.text and not lines:
                sys.exit(1)
        case "wait-text":
            started = time.time()
            ok = bool(wait_for(screen, a.text, a.seconds))
            log("wait", f'wait for "{a.text}"', ok=ok, waited=round(time.time() - started, 1),
                detail=f"seen after {time.time() - started:.1f} s" if ok else f"not seen in {a.seconds:.0f} s")
            if not ok:
                sys.exit(f'"{a.text}" did not show in {a.seconds:.0f} s.')
        case "click-text":
            lines = wait_for(screen, a.text, a.timeout)
            if len(lines) < a.nth:
                if a.if_shown:
                    return
                sys.exit(f'"{a.text}" is not on the screen.')
            x, y = center(lines[a.nth - 1])
            log("click", f'click "{a.text}"', x=x, y=y)
            screen.click(x, y)
        case "ax":
            if a.json:
                return print(json.dumps(ax.tree(a.app), indent=1, ensure_ascii=False))
            found = ax.matches(ax.elements(screen, a.app), a.find) if a.find else ax.elements(screen, a.app)
            for element in found:
                print(ax.describe(element, indent=not a.find))
            if a.find and not found:
                sys.exit(1)
        case "click-ax":
            found = ax.wait_for(screen, a.label, a.timeout, app=a.app, role=a.role)
            if len(found) < a.nth:
                sys.exit(f'"{a.label}" is not in the accessibility tree.')
            x, y = found[a.nth - 1]["x"], found[a.nth - 1]["y"]
            log("click", f'click "{a.label}"', x=x, y=y)
            screen.click(x, y)
        case "check":
            ok, label, detail = check(a, screen)
            log("check", label, ok=ok, detail=detail)
            print(("Pass: " if ok else "Fail: ") + label + (f" ({detail})" if detail and not ok else ""))
            if not ok:
                sys.exit(1)


def clean(days):
    cutoff = time.time() - max(days, 1) * 86400
    recording = (active() or {}).get("dir")
    for folder in SESSIONS.glob("*/") if SESSIONS.exists() else []:
        if str(folder.resolve()) != str(Path(recording or "/").resolve()) and folder.stat().st_mtime < cutoff:
            shutil.rmtree(folder)
            print(f"Deleted {folder}")


if __name__ == "__main__":
    main()
