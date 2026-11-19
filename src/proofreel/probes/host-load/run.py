"""Host load once a second: the host's CPU and this VM's, as a share of all cores, the rest, and the load average."""
import json
import os
import subprocess
import sys
import time

CORES = os.cpu_count() or 1
VM = int(os.environ.get("PROOFREEL_VM_PID") or 0)


def seconds(text):
    """ps TIME: [days-][hours:]minutes:seconds."""
    days, _, rest = text.rpartition("-")
    total = sum(float(part) * 60 ** i for i, part in enumerate(reversed(rest.split(":"))))
    return total + (int(days) * 86400 if days else 0)


def processes():
    """{pid: (parent pid, CPU seconds so far)}."""
    found = {}
    if sys.platform.startswith("linux"):
        tick = os.sysconf("SC_CLK_TCK")
        for name in filter(str.isdigit, os.listdir("/proc")):
            try:
                fields = open(f"/proc/{name}/stat").read().rsplit(")", 1)[1].split()
            except OSError:
                continue
            found[int(name)] = (int(fields[1]), (int(fields[11]) + int(fields[12])) / tick)
        return found
    for row in subprocess.run(["ps", "-A", "-o", "pid=,ppid=,time="], capture_output=True, text=True).stdout.splitlines():
        parts = row.split()
        if len(parts) == 3:
            found[int(parts[0])] = (int(parts[1]), seconds(parts[2]))
    return found


def tree(found, root):
    children = {}
    for pid, (parent, _) in found.items():
        children.setdefault(parent, []).append(pid)
    seen, todo = set(), [root]
    while todo:
        pid = todo.pop()
        if pid in found and pid not in seen:
            seen.add(pid)
            todo += children.get(pid, [])
    return seen


def say(m, v):
    print(json.dumps({"m": m, "v": round(v, 2)}), flush=True)


print(json.dumps({"ready": True}), flush=True)
before, then = processes(), time.monotonic()
while True:
    time.sleep(1)
    now, at = processes(), time.monotonic()
    share = (at - then) * CORES / 100
    used = {pid: max(0.0, cpu - before[pid][1]) if pid in before else cpu for pid, (_, cpu) in now.items()}
    total = min(100.0, sum(used.values()) / share)
    say("host/cpu", total)
    if VM:
        vm = min(total, sum(used[pid] for pid in tree(now, VM)) / share)
        say("host/vm-cpu", vm)
        say("host/other-cpu", total - vm)
    say("host/load", os.getloadavg()[0])
    before, then = now, at
