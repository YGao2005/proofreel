"""The tart backend: macOS and Linux VMs in Tart (Apple Virtualization). A state is a Tart VM named pr-<state>."""

import json
import re
import shutil
import subprocess
import sys

from .vm import HOME, RUN, ssh, wait

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
    tart("clone", PREFIX + name, RUN)
    settings = [*(["--display", display] if display else []), *(["--memory", str(memory)] if memory else []),
                *(["--cpu", str(cpu)] if cpu else [])]
    if settings and not info.get("warm"):
        tart("set", RUN, *settings)
    return boot(warmable or info.get("warm"))


def boot(suspendable=False):
    log = HOME / f"{RUN}.log"
    args = ["tart", "run", RUN, "--no-graphics", "--vnc-experimental", "--no-clipboard",
            *(["--suspendable"] if suspendable else ["--no-audio"])]
    with open(log, "w") as out:
        proc = subprocess.Popen(args, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True)
    url = wait(lambda: re.search(r"vnc://:(?P<pw>[^@]*)@(?P<host>[^:]+):(?P<port>\d+)", log.read_text()), 90,
               f"Tart printed no VNC address. See {log}.")
    ip = wait(lambda: tart("ip", RUN, "--wait", "5", check=False).stdout.strip(), 180, "The VM got no IP address.")
    return {"vm": RUN, "pid": proc.pid, "ip": ip, "vnc": f"{url['host']}::{url['port']}", "vnc_password": url["pw"],
            "suspendable": bool(suspendable)}


def save(name, run, warm):
    if exists(name):
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


def resume(name, run, warm):
    return boot(run.get("suspendable"))


def stop():
    if shutil.which("tart") and RUN in vms():
        tart("stop", RUN, check=False)
        tart("delete", RUN)


def drop(name):
    if exists(name):
        tart("delete", PREFIX + name)
