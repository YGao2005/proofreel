"""The qemu backend: Windows 11 ARM and Linux VMs in QEMU, with HVF on Apple Silicon (KVM on Linux).

A state is a folder: disk.qcow2, vars.fd (the UEFI variables), and for a warm state memory.bin (the RAM and device
state, written by a migration to a file). A run VM starts from clones of these files (`cp -c`, APFS copy on write).

QEMU runs headless: no display window, no audio device, no clipboard, VNC (QEMU's own) and SSH on 127.0.0.1 only.
"""

import gzip
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from . import Problem
from .vm import HOME, MACHINE, alive, free_port, wait

FOLDER = HOME / "qemu"
DEFAULTS = {"memory": 4096, "cpu": 4, "display": "1440x900"}
FIRMWARE = Path(__file__).parent / "firmware" / "edk2-aarch64-code.fd.gz"


def folder(name):
    return FOLDER / name


def qmp_socket():
    # WHY: a Unix socket path holds at most 103 bytes, so the socket is in the temp folder, not in a deep PROOFREEL_HOME.
    return Path(tempfile.gettempdir()) / f"proofreel-qmp-{hashlib.sha256(str(folder(MACHINE)).encode()).hexdigest()[:12]}"


def exists(name):
    return (folder(name) / "disk.qcow2").exists()


def clone(source, target):
    subprocess.run(["cp", "-c" if platform.system() == "Darwin" else "--reflink=auto", str(source), str(target)],
                   check=True)


def need_qemu():
    """The path of qemu-system-aarch64. The qemu backend needs it and qemu-img on PATH."""
    missing = [tool for tool in ("qemu-system-aarch64", "qemu-img") if not shutil.which(tool)]
    if missing:
        raise Problem(f"The qemu backend needs {' and '.join(missing)} on PATH. Install QEMU: brew install qemu "
                      f"(macOS), or apt install qemu-system-arm qemu-utils (Debian and Ubuntu).")
    return shutil.which("qemu-system-aarch64")


def firmware():
    """(code, vars): proofreel's UEFI firmware, unpacked once into HOME, and QEMU's own empty variables file."""
    share = Path(need_qemu()).resolve().parent.parent / "share" / "qemu"
    packed = FIRMWARE.read_bytes()
    code = HOME / "firmware" / f"edk2-{hashlib.sha256(packed).hexdigest()[:12]}.fd"
    if not code.exists():
        code.parent.mkdir(parents=True, exist_ok=True)
        partial = code.with_suffix(f".{os.getpid()}")
        partial.write_bytes(gzip.decompress(packed))
        partial.replace(code)
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


def host_address(run):
    """User networking: the guest reaches the host's 127.0.0.1 at 10.0.2.2, and its connections come from 127.0.0.1."""
    return "127.0.0.1", "10.0.2.2", "127.0.0.1"


def up(name, info, display=None, memory=None, cpu=None, warmable=False, extra=()):
    run = folder(MACHINE)
    shutil.rmtree(run, ignore_errors=True)
    run.mkdir(parents=True)
    for file in ("disk.qcow2", "vars.fd"):
        clone(folder(name) / file, run / file)
    machine = {**DEFAULTS, **info.get("machine", {})}
    if not info.get("warm"):
        machine.update({k: v for k, v in (("memory", memory), ("cpu", cpu), ("display", display)) if v})
    if not re.fullmatch(r"\d{3,4}x\d{3,4}", machine["display"]):
        raise Problem(f"--display must be WIDTHxHEIGHT, for example 1440x900, not {machine['display']!r}.")
    return boot(machine, folder(name) / "memory.bin" if info.get("warm") else None, extra)


def boot(machine, memory_file=None, extra=()):
    run = folder(MACHINE)
    port, vnc = free_port(), free_port(5900)
    accel = "hvf" if platform.system() == "Darwin" else "kvm"
    args = ["qemu-system-aarch64", "-name", MACHINE, "-machine", "virt,gic-version=3", "-accel", accel, "-cpu", "host",
            "-smp", str(machine["cpu"]), "-m", str(machine["memory"]), "-nodefaults", "-display", "none",
            "-audio", "none", "-vnc", f"127.0.0.1:{vnc - 5900}",
            "-drive", f"if=pflash,format=raw,readonly=on,file={firmware()[0]}",
            "-drive", f"if=pflash,format=raw,file={run / 'vars.fd'}",
            "-device", "ramfb",
            "-fw_cfg", f"name=opt/org.proofreel/resolution,string={machine['display']}",
            "-device", "qemu-xhci", "-device", "usb-kbd", "-device", "usb-tablet",
            "-drive", f"if=none,id=disk,format=qcow2,discard=unmap,file={run / 'disk.qcow2'}",
            "-device", "nvme,drive=disk,serial=proofreel",
            "-netdev", f"user,id=net,hostfwd=tcp:127.0.0.1:{port}-:22", "-device", "virtio-net-pci,netdev=net",
            "-qmp", f"unix:{qmp_socket()},server=on,wait=off",
            *(["-incoming", f"file:{memory_file}"] if memory_file else []), *extra]
    with open(run / "qemu.log", "w") as out:
        proc = subprocess.Popen(args, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True)
    record = {"vm": MACHINE, "backend": "qemu", "pid": proc.pid, "ip": "127.0.0.1", "port": port,
              "screen": f"127.0.0.1::{vnc}", "screen_password": "", "qmp": str(qmp_socket()), "machine": machine}

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


def save(name, run, warm):
    memory = folder(MACHINE) / "memory.bin"
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
        clone(folder(MACHINE) / file, target / file)
    if warm:
        memory.rename(target / "memory.bin")
    return run["machine"]


def resume(name, run, warm):
    if warm:
        qmp(run, "cont")
        return {k: v for k, v in run.items() if k not in ("state", "user", "password")}
    return boot(run["machine"])


def stop():
    run = folder(MACHINE)
    if qmp_socket().exists():
        try:
            qmp({"qmp": str(qmp_socket())}, "quit")
        except (OSError, ValueError):
            pass
        time.sleep(1)
    qmp_socket().unlink(missing_ok=True)
    shutil.rmtree(run, ignore_errors=True)


def drop(name):
    shutil.rmtree(folder(name), ignore_errors=True)
