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
import re
import socket
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from . import HOME, Problem, guest

STATES = HOME / "states"
RUN = os.environ.get("PROOFREEL_VM", "pr-run")
CURRENT = HOME / f"{RUN}.json"
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,62}")
MACHINE = f"{RUN}.vm"
SSH_OPTS = ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
            "-o", "ConnectTimeout=5", "-o", "PubkeyAuthentication=no"]


def check_name(name, what="state"):
    """A state or run name: letters, digits, - and _. A backend names the run VM MACHINE, with a dot, so a run VM
    never has the name of a state."""
    if not NAME.fullmatch(name or ""):
        raise Problem(f"{what.capitalize()} name {name!r}: use letters, digits, - and _, up to 63 characters.")
    return name


class Run(dict):
    """The run VM: the record its backend made, plus state, backend, os, user, password, conditions, and an id that
    is new at each boot. Load it once and pass it on."""

    @classmethod
    def current(cls):
        if not CURRENT.exists():
            raise Problem("No run VM. Start one: proofreel vm up <state>.")
        return cls(json.loads(CURRENT.read_text()))

    @property
    def guest(self):
        return guest.of(self)

    @property
    def target(self):
        return f"{self['user']}@{self['ip']}"

    @property
    def _socket(self):
        return Path(tempfile.gettempdir()) / f"proofreel-{self['id'][:12]}"

    def _options(self, port_flag):
        return [*SSH_OPTS, "-o", f"ControlPath={self._socket}",
                *([port_flag, str(self["port"])] if self.get("port") else [])]

    def _shared(self):
        """One SSH connection for each boot, opened once and shared by every later command."""
        if not self._socket.exists():
            subprocess.run(["ssh", *self._options("-p"), "-o", "ControlMaster=yes", "-o", "ControlPersist=600", "-fN",
                            self.target], env=askpass(self["password"]), stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)

    def argv(self, command, tty=False):
        """The ssh command line for a guest command. With tty, the guest command ends when the connection does."""
        self._shared()
        return ["ssh", *self._options("-p"), "-o", "ControlMaster=no", *(["-tt"] if tty else []), self.target, command]

    def ssh(self, command, check=True, capture=True, timeout=None):
        return subprocess.run(self.argv(command), env=askpass(self["password"]), check=check, text=True,
                              capture_output=capture, stdin=subprocess.DEVNULL, timeout=timeout)

    def _scp(self, source, target):
        self._shared()
        subprocess.run(["scp", *self._options("-P"), "-o", "ControlMaster=no", "-q", "-r", source, target],
                       env=askpass(self["password"]), check=True, stdin=subprocess.DEVNULL)

    def forward(self, guest_port):
        """(host port, ssh process): while the process runs, 127.0.0.1:<host port> reaches 127.0.0.1:<guest_port>
        in the guest. It has its own connection, so the forward ends with the process."""
        with socket.socket() as free:
            free.bind(("127.0.0.1", 0))
            port = free.getsockname()[1]
        process = subprocess.Popen(
            ["ssh", *SSH_OPTS, *(["-p", str(self["port"])] if self.get("port") else []), "-N",
             "-o", "ExitOnForwardFailure=yes", "-L", f"127.0.0.1:{port}:127.0.0.1:{guest_port}", self.target],
            env=askpass(self["password"]), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        return port, process

    def upload(self, host, guest_path):
        self._scp(host, f"{self.target}:{guest_path}")

    def download(self, guest_path, host):
        self._scp(f"{self.target}:{guest_path}", host)

    def close(self):
        subprocess.run(["ssh", *self._options("-p"), "-O", "exit", self.target], capture_output=True, check=False)


def backend(name):
    from . import qemu, tart
    return {"tart": tart, "qemu": qemu}[name]


def state_info(name):
    path = STATES / f"{name}.json"
    if not path.exists():
        raise Problem(f"No state {name!r}. See: proofreel vm states.")
    info = json.loads(path.read_text())
    if missing := [key for key in ("backend", "os") if key not in info]:
        raise Problem(f"State {name} does not say its {' or '.join(missing)}. Add them to {path}, for example "
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
    raise Problem(error)


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


def start(info, name, fields):
    """Record the run VM that a backend booted, then wait for SSH."""
    run = Run({**fields, "id": uuid.uuid4().hex, "state": name, "backend": info["backend"], "os": info["os"],
               "user": info["user"], "password": info["password"], "conditions": info.get("conditions", [])})
    CURRENT.write_text(json.dumps(run))
    wait(lambda: run.ssh("exit 0", check=False, timeout=10).returncode == 0, 240, "SSH in the VM did not start.")
    if run.guest.desktop:
        wait(lambda: run.ssh(run.guest.desktop, check=False, timeout=10).returncode == 0, 180,
             f"The {run['os']} desktop did not start in the VM.")
    return run


def base(name, image, kind, system, user, password):
    """Make a state from an image: for tart an OCI image or a local VM, for qemu a disk file."""
    check_name(name)
    if backend(kind).exists(name):
        raise Problem(f"State {name!r} exists. Drop it first: proofreel vm drop {name}.")
    guest.of({"os": system})
    backend(kind).base(name, image)
    write_state(name, parent=str(image), backend=kind, os=system, user=user, password=password, warm=False)
    print(f"State {name} made from {image}.")


def up(name, display=None, memory=None, cpu=None, warmable=False):
    """Start a run VM from a state."""
    check_name(RUN, "run")
    info = state_info(name)
    down()
    HOME.mkdir(parents=True, exist_ok=True)
    run = start(info, name, backend(info["backend"]).up(name, info, display, memory, cpu, warmable))
    print(f"{RUN} is up from {name}{' (warm)' if info.get('warm') else ''}: vnc {run['vnc']}, ip {run['ip']}"
          f"{':' + str(run['port']) if run.get('port') else ''}.")
    from . import conditions
    for record in info.get("conditions", []):
        conditions.check(run, record)
    return run


def save(name, warm=False, note="", flow=None, values=None, conditions=None):
    """Save the run VM as a state, then keep it running. Warm keeps memory: apps stay open. The state keeps the
    conditions of the state the run VM came from, and the ones given."""
    check_name(name)
    run = Run.current()
    kind = run["backend"]
    parent = state_info(name).get("parent") if run["state"] == name else run["state"]
    kept = {c["name"]: c for c in [*run["conditions"], *(conditions or [])]}
    if not warm:
        run.guest.before_save(run)
    machine = backend(kind).save(name, run, warm)
    write_state(name, parent=parent, backend=kind, os=run["os"], user=run["user"], password=run["password"], warm=warm,
                note=note, flow=flow, values=values or {}, conditions=list(kept.values()),
                **({"machine": machine} if machine else {}))
    start(state_info(name), name, backend(kind).resume(name, run, warm))
    print(f"Saved state {name}{' (warm)' if warm else ''} from {run['state']}. {RUN} runs on.")


def down():
    """Stop the run VM. A recording on it stops first, with the reason, so its video and page are kept."""
    from . import recording
    if recording.current():
        recording.stop(error="The run VM was stopped (vm down) during the recording.")
    if CURRENT.exists():
        run = Run.current()
        run.close()
        if run.get("pid"):
            subprocess.run(["kill", str(run["pid"])], capture_output=True)
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
