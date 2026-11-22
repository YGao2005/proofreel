"""The tart backend: macOS and Linux VMs in Tart (Apple Virtualization). A state is a Tart VM named pr-<state>."""

import json
import re
import shutil
import subprocess

from . import Problem
from .vm import HOME, MACHINE, wait

PREFIX = "pr-"


def tart(*args, check=True, capture=True):
    return subprocess.run(["tart", *args], check=check, text=True, capture_output=capture)


def vms():
    return {vm["Name"]: vm for vm in json.loads(tart("list", "--format", "json").stdout)}


def exists(name):
    return PREFIX + name in vms()


def base(name, image):
    tart("clone", image, PREFIX + name, capture=False)


def up(name, info, display=None, memory=None, cpu=None, warmable=False):
    tart("clone", PREFIX + name, MACHINE)
    settings = [*(["--display", display] if display else []), *(["--memory", str(memory)] if memory else []),
                *(["--cpu", str(cpu)] if cpu else [])]
    if settings and not info.get("warm"):
        tart("set", MACHINE, *settings)
    return boot(warmable or info.get("warm"))


def boot(suspendable=False):
    log = HOME / f"{MACHINE}.log"
    # WHY: Tart 2.41 gives a suspendable VM a sinkless speaker and no microphone; --no-audio keeps that if Tart changes.
    args = ["tart", "run", MACHINE, "--no-graphics", "--vnc-experimental", "--no-clipboard", "--no-audio",
            *(["--suspendable"] if suspendable else [])]
    with open(log, "w") as out:
        proc = subprocess.Popen(args, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True)
    url = wait(lambda: re.search(r"vnc://:(?P<pw>[^@]*)@(?P<host>[^:]+):(?P<port>\d+)", log.read_text()), 90,
               f"Tart printed no VNC address. See {log}.")
    ip = wait(lambda: tart("ip", MACHINE, "--wait", "5", check=False).stdout.strip(), 180, "The VM got no IP address.")
    return {"vm": MACHINE, "pid": proc.pid, "ip": ip, "screen": f"{url['host']}::{url['port']}", "screen_password": url["pw"],
            "suspendable": bool(suspendable)}


def host_address(run):
    """Shared networking: the host is the first address of the guest's subnet, on the bridge."""
    host = run["ip"].rsplit(".", 1)[0] + ".1"
    return host, host, run["ip"]


def save(name, run, warm):
    if exists(name):
        tart("delete", PREFIX + name)
    if warm and not run.get("suspendable"):
        raise Problem("This run VM cannot keep its memory. Start it with: proofreel vm up <state> --warmable.")
    if warm:
        tart("suspend", MACHINE)
    else:
        run.ssh("sudo -S shutdown -h now <<< " + json.dumps(run["password"]), check=False, timeout=20)
        wait(lambda: vms().get(MACHINE, {}).get("State") == "stopped", 120, "The VM did not shut down.")
    wait(lambda: vms().get(MACHINE, {}).get("State") in ("stopped", "suspended"), 60, "The VM did not stop.")
    tart("clone", MACHINE, PREFIX + name)


def resume(name, run, warm):
    return boot(run.get("suspendable"))


def stop():
    if shutil.which("tart") and MACHINE in vms():
        tart("stop", MACHINE, check=False)
        tart("delete", MACHINE)


def drop(name):
    if exists(name):
        tart("delete", PREFIX + name)
