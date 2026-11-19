"""Named VM states, and the run VM that starts from one.

A state is a saved VM: a clean OS, an app installed with no permissions, a user mid-onboarding. `up` clones a state
into a throwaway run VM in seconds (APFS copy on write), so each test starts from the same place. A warm state is
saved while it runs (memory too), so `up` resumes it with the apps already open. A state built by a flow records the
flow, so `build` makes it again when the app changes.

Each state names its backend, `tart` (macOS and Linux guests) or `qemu` (Windows 11 ARM and Linux guests), and its
guest system (`os`, see guest.py). A backend module has exists, base, up, save, resume, stop, and drop. This module
keeps the state files, the run record, and SSH.

A run VM is headless and isolated from the host: no window, no audio device, no shared clipboard. Nothing it does
shows or plays on the host.
"""

import json
import os
import subprocess
import sys
import time

from . import HOME, guest

STATES = HOME / "states"
RUN = os.environ.get("PROOFREEL_VM", "pr-run")
CURRENT = HOME / f"{RUN}.json"
SSH_OPTS = ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
            "-o", "ConnectTimeout=5", "-o", "PubkeyAuthentication=no"]


def backend(name):
    from . import qemu, tart
    return {"tart": tart, "qemu": qemu}[name]


def current():
    if not CURRENT.exists():
        sys.exit("No run VM. Start one: proofreel vm up <state>.")
    return json.loads(CURRENT.read_text())


def state_info(name):
    path = STATES / f"{name}.json"
    if not path.exists():
        sys.exit(f"No state {name!r}. See: proofreel vm states.")
    info = json.loads(path.read_text())
    if missing := [key for key in ("backend", "os") if key not in info]:
        sys.exit(f"State {name} does not say its {' or '.join(missing)}. Add them to {path}, for example "
                 f'"backend": "tart", "os": "macos".')
    return info


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
    """The environment that gives ssh the guest password. The password stays in this environment, never on disk, so
    run VMs with different passwords can work at the same time."""
    script = HOME / "askpass.sh"
    if not script.exists():
        HOME.mkdir(parents=True, exist_ok=True)
        script.write_text('#!/bin/sh\nprintf "%s\\n" "$PROOFREEL_GUEST_PASSWORD"\n')
        script.chmod(0o700)
    return {**os.environ, "SSH_ASKPASS": str(script), "SSH_ASKPASS_REQUIRE": "force", "DISPLAY": ":0",
            "PROOFREEL_GUEST_PASSWORD": password}


def ssh(command, check=True, capture=True, timeout=None, run=None):
    run = run or current()
    port = ["-p", str(run["port"])] if run.get("port") else []
    return subprocess.run(["ssh", *SSH_OPTS, *port, f"{run['user']}@{run['ip']}", command],
                          env=askpass(run["password"]), check=check, text=True, capture_output=capture,
                          stdin=subprocess.DEVNULL, timeout=timeout)


def scp(source, target, run=None):
    run = run or current()
    port = ["-P", str(run["port"])] if run.get("port") else []
    subprocess.run(["scp", *SSH_OPTS, *port, "-q", "-r", source, target], env=askpass(run["password"]), check=True,
                   stdin=subprocess.DEVNULL)


def put(host, guest):
    run = current()
    scp(host, f"{run['user']}@{run['ip']}:{guest}", run)


def get(guest, host):
    run = current()
    scp(f"{run['user']}@{run['ip']}:{guest}", host, run)


def start(info, name, run):
    """Record the run VM, then wait for SSH."""
    run = {**run, "state": name, "backend": info["backend"], "os": info["os"], "user": info["user"],
           "password": info["password"], "conditions": info.get("conditions", [])}
    CURRENT.write_text(json.dumps(run))
    wait(lambda: ssh("exit 0", check=False, timeout=10, run=run).returncode == 0, 240, "SSH in the VM did not start.")
    return run


def base(name, image, kind, system, user, password):
    """Make a state from an image: for tart an OCI image or a local VM, for qemu a disk file."""
    if backend(kind).exists(name):
        sys.exit(f"State {name!r} exists. Drop it first: proofreel vm drop {name}.")
    guest.of({"os": system})
    backend(kind).base(name, image)
    write_state(name, parent=str(image), backend=kind, os=system, user=user, password=password, warm=False)
    print(f"State {name} made from {image}.")


def up(name, display=None, memory=None, cpu=None, warmable=False):
    """Start a run VM from a state."""
    info = state_info(name)
    down()
    HOME.mkdir(parents=True, exist_ok=True)
    run = start(info, name, backend(info["backend"]).up(name, info, display, memory, cpu, warmable))
    print(f"{RUN} is up from {name}{' (warm)' if info.get('warm') else ''}: vnc {run['vnc']}, ip {run['ip']}"
          f"{':' + str(run['port']) if run.get('port') else ''}.")
    from . import conditions
    for record in info.get("conditions", []):
        conditions.check(record)


def save(name, warm=False, note="", flow=None, values=None, conditions=None):
    """Save the run VM as a state, then keep it running. Warm keeps memory: apps stay open. The state keeps the
    conditions of the state the run VM came from, and the ones given."""
    run = current()
    kind = run["backend"]
    parent = state_info(name).get("parent") if run["state"] == name else run["state"]
    kept = {c["name"]: c for c in [*run["conditions"], *(conditions or [])]}
    if not warm:
        guest.of(run).before_save(run)
    machine = backend(kind).save(name, run, warm)
    write_state(name, parent=parent, backend=kind, os=run["os"], user=run["user"], password=run["password"], warm=warm,
                note=note, flow=flow, values=values or {}, conditions=list(kept.values()),
                **({"machine": machine} if machine else {}))
    start(state_info(name), name, backend(kind).resume(name, run, warm))
    print(f"Saved state {name}{' (warm)' if warm else ''} from {run['state']}. {RUN} runs on.")


def down():
    run = json.loads(CURRENT.read_text()) if CURRENT.exists() else {}
    for pid in (run.get("recorder"), run.get("pid")):
        if pid:
            subprocess.run(["kill", str(pid)], capture_output=True)
    CURRENT.unlink(missing_ok=True)
    for kind in ("tart", "qemu"):
        backend(kind).stop()


def drop(name):
    """Delete a state. A state with no file (a build that stopped half way) is deleted from every backend."""
    path = STATES / f"{name}.json"
    for kind in [state_info(name)["backend"]] if path.exists() else ["tart", "qemu"]:
        backend(kind).drop(name)
    path.unlink(missing_ok=True)


def states():
    """The states as a tree: each under the state it was made from."""
    infos = {p.stem: json.loads(p.read_text()) for p in sorted(STATES.glob("*.json"))} if STATES.exists() else {}
    def loops(name):
        seen, step = set(), infos[name].get("parent")
        while step in infos and step not in seen:
            seen.add(step)
            step = infos[step].get("parent")
        return name in seen

    children = {}
    for name, info in infos.items():
        children.setdefault(info.get("parent") if info.get("parent") in infos and not loops(name) else None,
                            []).append(name)

    def show(name, depth):
        info = infos[name]
        tags = [t for t in ("warm" if info.get("warm") else "", f"flow {info['flow']}" if info.get("flow") else "",
                            ", ".join(c["name"] for c in info.get("conditions", [])),
                            info.get("os", "")) if t]
        print(f"{'  ' * depth}{name}  {info['created']}{'  [' + ', '.join(tags) + ']' if tags else ''}"
              f"{'  ' + info['note'] if info.get('note') else ''}")
        for child in children.get(name, []):
            show(child, depth + 1)

    for root in children.get(None, []):
        show(root, 0)
