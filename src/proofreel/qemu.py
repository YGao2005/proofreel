"""The qemu backend: Windows 11 ARM and Linux VMs in QEMU, with HVF on Apple Silicon (KVM on Linux).

A state is a folder: disk.qcow2, vars.fd (the UEFI variables), and for a warm state memory.bin (the RAM and device
state, written by a migration to a file). A run VM starts from clones of these files (`cp -c`, APFS copy on write).

QEMU runs headless: no display window, no audio device, no clipboard, VNC (QEMU's own) and SSH on 127.0.0.1 only.
"""

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from . import Problem
from .vm import HOME, RUN, wait

FOLDER = HOME / "qemu"
MACHINE = {"memory": 4096, "cpu": 4, "display": "1440x900"}
CUSTOM_FIRMWARE = HOME / "firmware" / "edk2-aarch64-code.fd"


def folder(name):
    return FOLDER / name


def exists(name):
    return (folder(name) / "disk.qcow2").exists()


def clone(source, target):
    subprocess.run(["cp", "-c" if platform.system() == "Darwin" else "--reflink=auto", str(source), str(target)],
                   check=True)


def firmware():
    binary = shutil.which("qemu-system-aarch64")
    if not binary:
        raise Problem("The qemu backend needs qemu-system-aarch64 on PATH: brew install qemu.")
    share = Path(binary).resolve().parent.parent / "share" / "qemu"
    code = CUSTOM_FIRMWARE if CUSTOM_FIRMWARE.exists() else share / "edk2-aarch64-code.fd"
    return code, share / "edk2-arm-vars.fd"


def base(name, image):
    info = json.loads(subprocess.run(["qemu-img", "info", "--output", "json", str(image)], check=True,
                                     capture_output=True, text=True).stdout)
    folder(name).mkdir(parents=True)
    if info["format"] == "qcow2" and "backing-filename" not in info:
        clone(image, folder(name) / "disk.qcow2")
    else:
        subprocess.run(["qemu-img", "convert", "-O", "qcow2", str(image), str(folder(name) / "disk.qcow2")],
                       check=True)
    clone(firmware()[1], folder(name) / "vars.fd")


def free_port(first=0):
    for port in range(first, first + 100) if first else [0]:
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise Problem("No free local port.")


def up(name, info, display=None, memory=None, cpu=None, warmable=False):
    run = folder(RUN)
    shutil.rmtree(run, ignore_errors=True)
    run.mkdir(parents=True)
    for file in ("disk.qcow2", "vars.fd"):
        clone(folder(name) / file, run / file)
    machine = {**MACHINE, **info.get("machine", {})}
    if not info.get("warm"):
        machine.update({k: v for k, v in (("memory", memory), ("cpu", cpu), ("display", display)) if v})
    if not re.fullmatch(r"\d{3,4}x\d{3,4}", machine["display"]):
        raise Problem(f"--display must be WIDTHxHEIGHT, for example 1440x900, not {machine['display']!r}.")
    if not CUSTOM_FIRMWARE.exists():
        print(f"The screen is at most 1024x768, not {machine['display']}: the stock UEFI firmware has no other "
              f"modes. To get it, run firmware/build.sh from the proofreel repo.", file=sys.stderr)
    return boot(machine, folder(name) / "memory.bin" if info.get("warm") else None)


def boot(machine, memory_file=None):
    run = folder(RUN)
    port, vnc = free_port(), free_port(5900)
    accel = "hvf" if platform.system() == "Darwin" else "kvm"
    args = ["qemu-system-aarch64", "-name", RUN, "-machine", "virt,gic-version=3", "-accel", accel, "-cpu", "host",
            "-smp", str(machine["cpu"]), "-m", str(machine["memory"]), "-nodefaults", "-display", "none",
            "-audio", "none", "-vnc", f"127.0.0.1:{vnc - 5900}",
            "-drive", f"if=pflash,format=raw,readonly=on,file={firmware()[0]}",
            "-drive", f"if=pflash,format=raw,file={run / 'vars.fd'}",
            "-device", "ramfb", *(["-fw_cfg", f"name=opt/org.proofreel/resolution,string={machine['display']}"]
                                  if CUSTOM_FIRMWARE.exists() else []),
            "-device", "qemu-xhci", "-device", "usb-kbd", "-device", "usb-tablet",
            "-drive", f"if=none,id=disk,format=qcow2,discard=unmap,file={run / 'disk.qcow2'}",
            "-device", "nvme,drive=disk,serial=proofreel",
            "-netdev", f"user,id=net,hostfwd=tcp:127.0.0.1:{port}-:22", "-device", "virtio-net-pci,netdev=net",
            "-qmp", f"unix:{run / 'qmp.sock'},server=on,wait=off",
            *(["-incoming", f"file:{memory_file}"] if memory_file else [])]
    with open(run / "qemu.log", "w") as out:
        proc = subprocess.Popen(args, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True)
    record = {"vm": RUN, "backend": "qemu", "pid": proc.pid, "ip": "127.0.0.1", "port": port,
              "vnc": f"127.0.0.1::{vnc}", "vnc_password": "", "qmp": str(run / "qmp.sock"), "machine": machine}

    def running():
        if not alive(proc.pid):
            raise Problem(f"QEMU stopped. See {run / 'qemu.log'}.")
        try:
            status = qmp(record, "query-status")["status"]
        except OSError:
            return False
        if status == "paused":
            qmp(record, "cont")
        return status == "running"

    wait(running, 300, f"The VM did not start. See {run / 'qemu.log'}.")
    return record


def qmp(run, command, **arguments):
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(30)
        s.connect(run["qmp"])
        stream = s.makefile("rw")
        stream.readline()
        for message in ({"execute": "qmp_capabilities"}, {"execute": command, "arguments": arguments}):
            stream.write(json.dumps(message) + "\n")
            stream.flush()
            while "event" in (reply := json.loads(stream.readline())):
                pass
    if "error" in reply:
        raise Problem(f"QEMU {command}: {reply['error']['desc']}")
    return reply["return"]


def alive(pid):
    try:
        if os.waitpid(pid, os.WNOHANG)[0]:
            return False
    except ChildProcessError:
        pass
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def save(name, run, warm):
    memory = folder(RUN) / "memory.bin"
    memory.unlink(missing_ok=True)
    if warm:
        qmp(run, "stop")
        qmp(run, "migrate", uri=f"file:{memory}")
        done = wait(lambda: (m := qmp(run, "query-migrate")).get("status") in ("completed", "failed") and m, 600,
                    "The memory did not save.")
        if done["status"] != "completed":
            raise Problem(f"The memory did not save: {done.get('error-desc', 'the migration failed')}.")
    else:
        qmp(run, "system_powerdown")
        wait(lambda: not alive(run["pid"]), 180, "The VM did not shut down.")
    target = folder(name)
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    for file in ("disk.qcow2", "vars.fd"):
        clone(folder(RUN) / file, target / file)
    if warm:
        memory.rename(target / "memory.bin")
    return run["machine"]


def resume(name, run, warm):
    if warm:
        qmp(run, "cont")
        return {k: v for k, v in run.items() if k not in ("state", "user", "password")}
    return boot(run["machine"])


def stop():
    run = folder(RUN)
    if (run / "qmp.sock").exists():
        try:
            qmp({"qmp": str(run / "qmp.sock")}, "quit")
        except (OSError, ValueError):
            pass
        time.sleep(1)
    shutil.rmtree(run, ignore_errors=True)


def drop(name):
    shutil.rmtree(folder(name), ignore_errors=True)
