"""The processes probe on Linux: the app's process tree and the system, from /proc, once each INTERVAL seconds."""
import json
import os
import sys
import time

TOP = 3
TOP_MIN = 10.0
TOP_NAMES = 16
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


def pss(folder):
    try:
        with open(f"{folder}/smaps_rollup") as rollup:
            return next(int(line.split()[1]) for line in rollup if line.startswith("Pss:"))
    except (OSError, StopIteration, ValueError):
        return None


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


def sample(before, now, seconds, tick, app, me=None):
    """The measures between two reads of processes(), seconds apart. CPU is % of one core."""
    used = {key: (cpu - before[key][3] if key in before else cpu) / tick / seconds * 100
            for key, (_, _, _, cpu, _) in now.items() if key[0] != me}
    tree = app_tree(now, app)
    lines = []
    if tree:
        lines += [("cpu/app", sum(used[key] for key in tree if key in used)),
                  ("mem/app", sum(now[key][4] for key in tree) / 1024), ("app/procs", len(tree))]
    others = {}
    for key, cpu in used.items():
        if key not in tree:
            others[now[key][1]] = others.get(now[key][1], 0) + cpu
    lines.append(("cpu/other", sum(others.values())))
    top = sorted(((cpu, name) for name, cpu in others.items() if cpu >= TOP_MIN), reverse=True)[:TOP]
    return lines + [(f"cpu/top/{name}", cpu) for cpu, name in top], bool(tree)


class Lines:
    """Prints the protocol: measures with the probe's clock t, at most TOP_NAMES top-process series."""

    def __init__(self, out=sys.stdout):
        self.out, self.names = out, set()

    def say(self, line):
        self.out.write(json.dumps(line) + "\n")
        self.out.flush()

    def measures(self, lines, t):
        for m, v in lines:
            if m.startswith("cpu/top/"):
                if m not in self.names and len(self.names) >= TOP_NAMES:
                    continue
                self.names.add(m)
            self.say({"m": m, "v": round(v, 2), "t": round(t, 4)})


def main():
    app, interval = os.environ.get("PROOFREEL_APP", ""), float(os.environ.get("INTERVAL") or 1)
    tick, cores, me = os.sysconf("SC_CLK_TCK"), os.cpu_count() or 1, os.getpid()
    out = Lines()
    out.say({"ready": True})
    out.say({"meta": {"app": app or "none: give start --app", "cores": cores}})
    before = then = ticks = running = None
    while True:
        now, (busy, total, memory), at = processes(), system(), time.monotonic()
        lines, found = sample(before or now, now, at - (then or 0), tick, app, me)
        if before is None:
            lines = [line for line in lines if not line[0].startswith("cpu/")]
        else:
            lines.append(("cpu/system", (busy - ticks[0]) / max(1, total - ticks[1]) * 100))
        out.measures(lines + [("mem/system", memory)], at)
        if app and running is not None and found != running:
            out.say({"m": "app/start" if found else "app/exit", "t": round(at, 4)})
        before, then, ticks, running = now, at, (busy, total), found
        time.sleep(interval)

if __name__ == "__main__":
    main()
