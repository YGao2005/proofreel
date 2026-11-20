"""The processes probe: the app's process tree, and the rest of the guest, once each INTERVAL seconds. Linux reads
/proc. macOS reads ps."""
import json
import os
import subprocess
import sys
import time

MAC = sys.platform == "darwin"
PAGE_KB = os.sysconf("SC_PAGE_SIZE") // 1024


def processes(root="/proc"):
    """{(pid, start ticks): (parent pid, name, argv0, CPU ticks, memory kB)}. A process that ends while it is read is
    left out. Memory is PSS when it can be read (it shares the pages between processes), else RSS."""
    found = {}
    for name in filter(str.isdigit, os.listdir(root)):
        folder = f"{root}/{name}"
        try:
            with open(f"{folder}/stat") as stat:
                head, _, tail = stat.read().rpartition(")")
            fields = tail.split()
            with open(f"{folder}/cmdline", "rb") as cmdline:
                argv0 = cmdline.read().split(b"\0", 1)[0].decode(errors="replace")
            memory = pss(folder)
            if memory is None:
                with open(f"{folder}/statm") as statm:
                    memory = int(statm.read().split()[1]) * PAGE_KB
        except (OSError, IndexError, ValueError):
            continue
        found[(int(name), int(fields[19]))] = (int(fields[1]), head.split("(", 1)[1], os.path.basename(argv0),
                                               int(fields[11]) + int(fields[12]), memory)
    return found


def ps_seconds(text):
    """CPU time from ps, [[H:]M:]S.ss, in seconds."""
    seconds = 0.0
    for part in text.split(":"):
        seconds = seconds * 60 + float(part)
    return seconds


def ps_processes(text):
    """processes() for the output of ps -axo pid=,ppid=,cputime=,rss=,lstart=,comm=. A process is keyed by its pid and
    start time. CPU is in hundredths of a second (the tick of the macOS probe), memory is RSS."""
    found = {}
    for row in text.splitlines():
        fields = row.split(None, 9)
        try:
            name = os.path.basename(fields[9])
            found[(int(fields[0]), " ".join(fields[4:9]))] = (int(fields[1]), name, name, ps_seconds(fields[2]) * 100,
                                                              int(fields[3]))
        except (IndexError, ValueError):
            continue
    return found


def pss(folder):
    try:
        with open(f"{folder}/smaps_rollup") as rollup:
            return next(int(line.split()[1]) for line in rollup if line.startswith("Pss:"))
    except (OSError, StopIteration, ValueError):
        return None


def read():
    if MAC:
        out = subprocess.run(["ps", "-axo", "pid=,ppid=,cputime=,rss=,lstart=,comm="], capture_output=True, text=True)
        return ps_processes(out.stdout)
    return processes()


def system(root="/proc"):
    """(busy ticks, all ticks) of all cores, and the memory in use in MB."""
    with open(f"{root}/stat") as stat:
        ticks = [int(n) for n in stat.readline().split()[1:9]]
    with open(f"{root}/meminfo") as meminfo:
        info = {line.split(":")[0]: int(line.split()[1]) for line in meminfo}
    return sum(ticks) - ticks[3] - ticks[4], sum(ticks), (info["MemTotal"] - info["MemAvailable"]) / 1024


def app_tree(found, app):
    """The keys of the app's processes: each one named app (its short name, or its first argument's file name), and
    every process under one."""
    children = {}
    for key, (parent, *_) in found.items():
        children.setdefault(parent, []).append(key)
    todo = [key for key, (_, name, argv0, *_) in found.items() if app and (name == app[:15] or argv0 == app)]
    seen = set()
    while todo:
        key = todo.pop()
        if key not in seen:
            seen.add(key)
            todo += children.get(key[0], [])
    return seen


def sample(before, now, seconds, tick, app):
    """The measures between two reads of processes(), seconds apart: the app's CPU as a % of one core (a process that
    is new, or whose count went back, starts from zero), its memory in MB, and how many processes it has."""
    tree = app_tree(now, app)
    if not tree:
        return [], False
    cpu = sum(max(0, now[key][3] - before[key][3]) if key in before else now[key][3] for key in tree)
    return [("cpu/app", cpu / tick / seconds * 100), ("mem/app", sum(now[key][4] for key in tree) / 1024),
            ("app/procs", len(tree))], True


class Lines:
    """Prints the protocol: each measure with the probe's clock t."""

    def __init__(self, out=sys.stdout):
        self.out = out

    def say(self, line):
        self.out.write(json.dumps(line) + "\n")
        self.out.flush()

    def measures(self, lines, t):
        for m, v in lines:
            self.say({"m": m, "v": round(v, 2), "t": round(t, 4)})


def main():
    app, interval = os.environ.get("PROOFREEL_APP", ""), float(os.environ.get("INTERVAL") or 1)
    tick = 100 if MAC else os.sysconf("SC_CLK_TCK")
    out = Lines()
    out.say({"ready": True})
    out.say({"meta": {"app": app or "none: give start --app", "cores": os.cpu_count() or 1}})
    before = then = ticks = running = None
    while True:
        now, total, at = read(), None if MAC else system(), time.monotonic()
        lines, found = sample(before or now, now, at - (then or 0), tick, app)
        if before is None:
            lines = [line for line in lines if not line[0].startswith("cpu/")]
        elif total:
            lines.append(("cpu/system", (total[0] - ticks[0]) / max(1, total[1] - ticks[1]) * 100))
        if total:
            lines.append(("mem/system", total[2]))
        out.measures(lines, at)
        if app and running is not None and found != running:
            out.say({"m": "app/start" if found else "app/exit", "t": round(at, 4)})
        before, then, ticks, running = now, at, total and total[:2], found
        time.sleep(interval)


if __name__ == "__main__":
    main()
