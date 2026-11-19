"""Mac and Linux VMs with Tart, and named states to start them from.

A state is a saved VM: a clean OS, an app installed with no permissions, a user mid-onboarding. `up` clones a state
into a throwaway run VM in seconds (APFS copy on write), so each test starts from the same place. A warm state is
saved while it runs (memory too), so `up` resumes it with the apps already open. A state built by a flow records the
flow, so `build` makes it again when the app changes.

A run VM is headless and isolated from the host: no window, no audio device, no shared clipboard. Nothing it does
shows or plays on the host.
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HOME = Path(os.environ.get("PROOFREEL_HOME", Path.home() / ".proofreel"))
STATES = HOME / "states"
RUN = os.environ.get("PROOFREEL_VM", "pr-run")
CURRENT = HOME / f"{RUN}.json"
PREFIX = "pr-"
SSH_OPTS = ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
            "-o", "ConnectTimeout=5", "-o", "PubkeyAuthentication=no"]


def tart(*args, check=True, capture=True):
    return subprocess.run(["tart", *args], check=check, text=True, capture_output=capture)


def vms():
    return {vm["Name"]: vm for vm in json.loads(tart("list", "--format", "json").stdout)}


def current():
    if not CURRENT.exists():
        sys.exit(f"No run VM. Start one: proofreel vm up <state>.")
    return json.loads(CURRENT.read_text())


def state_info(name):
    path = STATES / f"{name}.json"
    if not path.exists():
        sys.exit(f"No state {name!r}. See: proofreel vm states.")
    return json.loads(path.read_text())


def write_state(name, **info):
    STATES.mkdir(parents=True, exist_ok=True)
    (STATES / f"{name}.json").write_text(json.dumps({"name": name, "created": time.strftime("%Y-%m-%d %H:%M"), **info},
                                                   indent=2))


def wait(test, seconds, error):
    end = time.time() + seconds
    while time.time() < end:
        try:
            if result := test():
                return result
        except subprocess.TimeoutExpired:
            pass
        time.sleep(2)
    sys.exit(error)


def askpass(password):
    script = HOME / "askpass.sh"
    script.write_text(f"#!/bin/sh\necho {json.dumps(password)}\n")
    script.chmod(0o700)
    return {**os.environ, "SSH_ASKPASS": str(script), "SSH_ASKPASS_REQUIRE": "force", "DISPLAY": ":0"}


def ssh(command, check=True, capture=True, timeout=None, run=None):
    run = run or current()
    return subprocess.run(["ssh", *SSH_OPTS, f"{run['user']}@{run['ip']}", command], env=askpass(run["password"]),
                          check=check, text=True, capture_output=capture, stdin=subprocess.DEVNULL, timeout=timeout)


def scp(source, target, run=None):
    run = run or current()
    subprocess.run(["scp", *SSH_OPTS, "-q", source, target], env=askpass(run["password"]), check=True,
                   stdin=subprocess.DEVNULL)


def base(name, image, user="admin", password="admin"):
    """Make a state from an OCI image or a local VM, such as ghcr.io/cirruslabs/macos-tahoe-vanilla:26.0."""
    if PREFIX + name in vms():
        sys.exit(f"State {name!r} exists. Drop it first: proofreel vm drop {name}.")
    tart("clone", image, PREFIX + name, capture=False)
    write_state(name, parent=image, user=user, password=password, warm=False)
    print(f"State {name} made from {image}.")


def up(name, display=None, memory=None, cpu=None, warmable=False):
    """Start a run VM from a state."""
    info = state_info(name)
    down()
    tart("clone", PREFIX + name, RUN)
    settings = [*(["--display", display] if display else []), *(["--memory", str(memory)] if memory else []),
                *(["--cpu", str(cpu)] if cpu else [])]
    if settings and not info.get("warm"):
        tart("set", RUN, *settings)
    boot(info, name, warmable or info.get("warm"))
    print(f"{RUN} is up from {name}{' (warm)' if info.get('warm') else ''}: vnc {current()['vnc']}, ip {current()['ip']}.")


def boot(info, name, suspendable=False):
    HOME.mkdir(parents=True, exist_ok=True)
    log = HOME / f"{RUN}.log"
    args = ["tart", "run", RUN, "--no-graphics", "--vnc-experimental", "--no-clipboard",
            *(["--suspendable"] if suspendable else ["--no-audio"])]
    with open(log, "w") as out:
        proc = subprocess.Popen(args, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True)
    url = wait(lambda: re.search(r"vnc://:(?P<pw>[^@]*)@(?P<host>[^:]+):(?P<port>\d+)", log.read_text()), 90,
               f"Tart printed no VNC address. See {log}.")
    ip = wait(lambda: tart("ip", RUN, "--wait", "5", check=False).stdout.strip(), 180, "The VM got no IP address.")
    run = {"vm": RUN, "state": name, "pid": proc.pid, "ip": ip, "vnc": f"{url['host']}::{url['port']}",
           "vnc_password": url["pw"], "user": info.get("user", "admin"), "password": info.get("password", "admin"),
           "suspendable": bool(suspendable)}
    CURRENT.write_text(json.dumps(run))
    wait(lambda: ssh("true", check=False, timeout=10, run=run).returncode == 0, 240, "SSH in the VM did not start.")


def save(name, warm=False, note="", flow=None, values=None):
    """Save the run VM as a state, then keep it running. Warm keeps memory: apps stay open."""
    run = current()
    if PREFIX + name in vms():
        tart("delete", PREFIX + name)
    if warm and not run.get("suspendable"):
        sys.exit("This run VM cannot keep its memory. Start it with: proofreel vm up <state> --warmable.")
    if warm:
        tart("suspend", RUN)
    else:
        ssh("sudo -S shutdown -h now <<< " + json.dumps(run["password"]), check=False, timeout=20)
        wait(lambda: vms().get(RUN, {}).get("State") == "stopped", 120, "The VM did not shut down.")
    wait(lambda: vms().get(RUN, {}).get("State") in ("stopped", "suspended"), 60, "The VM did not stop.")
    tart("clone", RUN, PREFIX + name)
    write_state(name, parent=run["state"], user=run["user"], password=run["password"], warm=warm, note=note,
                flow=flow, values=values or {})
    boot(state_info(name), name, run.get("suspendable"))
    print(f"Saved state {name}{' (warm)' if warm else ''} from {run['state']}. {RUN} runs on.")


def down():
    if CURRENT.exists():
        run = json.loads(CURRENT.read_text())
        for pid in (run.get("recorder"), run.get("pid")):
            if pid:
                subprocess.run(["kill", str(pid)], capture_output=True)
        CURRENT.unlink()
    if RUN in vms():
        tart("stop", RUN, check=False)
        tart("delete", RUN)


def drop(name):
    if PREFIX + name in vms():
        tart("delete", PREFIX + name)
    (STATES / f"{name}.json").unlink(missing_ok=True)


def states():
    """The states as a tree: each under the state it was made from."""
    infos = {p.stem: json.loads(p.read_text()) for p in sorted(STATES.glob("*.json"))} if STATES.exists() else {}
    children = {}
    for name, info in infos.items():
        children.setdefault(info.get("parent") if info.get("parent") in infos else None, []).append(name)

    def show(name, depth):
        info = infos[name]
        tags = [t for t in ("warm" if info.get("warm") else "", f"flow {info['flow']}" if info.get("flow") else "") if t]
        print(f"{'  ' * depth}{name}  {info['created']}{'  [' + ', '.join(tags) + ']' if tags else ''}"
              f"{'  ' + info['note'] if info.get('note') else ''}")
        for child in children.get(name, []):
            show(child, depth + 1)

    for root in children.get(None, []):
        show(root, 0)
