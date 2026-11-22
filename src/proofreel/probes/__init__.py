"""Probes: what a session measures while it records, such as the host's load, an app's CPU, or request times.

A probe is a plugin (see plugins.py): probe.toml and scripts. `where` says where it runs: on the host (run.py, run
with this Python) or in the guest (run.sh or run.ps1, over SSH). `default = true` turns it on for every recording on
its systems. `privacy` says what it can see. [tracks."<series glob>"] tells the page and `stats` how to show a series:
label, unit, better ("lower" or "higher"), max, and bands (values the page draws a guide line at). A host probe with
`tunnel = <guest port>` gets PROOFREEL_TUNNEL, a host port on 127.0.0.1 that reaches that port on the guest's
127.0.0.1 while it runs. On `web`, the browser is on the host: it is the browser's own DevTools port.
`default`, `extras`, and `tunnel` may be a table by system (`default = {web = true}`).

The protocol: a probe prints one JSON object on each line.
  {"m": "cpu/app", "v": 42}                               a sample of the series cpu/app
  {"m": "net/GET api.x", "d": 0.31, "ok": true, ...}      a span: something that took d seconds and ended then
  {"m": "app/launched"}                                   a mark
  "t", optional on each: when, in the probe's own steady clock. Without it, the time the line reached the host counts.
  {"ready": true}   {"unavailable": "<why>"}   {"meta": {...}}   control lines
`start` waits up to SETTLE seconds, so a page that opens at once is measured: until each probe says ready or
unavailable, says {"meta": {"waiting": "<for what>"}}, or prints a measure.
The recorder keeps each measure in metrics/<probe>.jsonl with "a", the unix time it arrived, and the probe's status
in metrics/probes.json. A line over a limit (LINE bytes, RATE lines a second, SERIES ids) is counted and dropped;
control lines skip the rate limit.

More manifest fields:
  extras = "<command>"   a command it needs. Without it, the probe is unavailable, with the command that installs it.
  port = true            the host gives it a free port, in PROOFREEL_PORT.
  setup = true           guest start and stop scripts change the run VM for the recording (a proxy, a trusted CA).
                         A guest with no shell (`web`) has nothing to change, so it runs no scripts.
                         start runs once the host run runs; stop must work after a start that stopped half way.
                         Each reset is written to the run record before its start, so plugins.undo() undoes it
                         after a crash: at the next start, at `vm save`, and at `stop`.
A host probe for a run VM gets PROOFREEL_BIND (the address to listen on), PROOFREEL_HOST_FOR_GUEST (that address as
the guest sees it), and PROOFREEL_GUEST_IP (the guest as the host sees it); start and stop get PROOFREEL_PORT and
PROOFREEL_HOST_FOR_GUEST.
"""

import importlib.metadata
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from .. import Problem, plugins
from ..vm import free_port

LINE = 16_384
RATE = 200
SERIES = 64
SETTLE = 3
CONTROL = ("ready", "unavailable", "meta")


def per(info, key, system):
    """A manifest field for one system: the field itself, or its entry for the system when it is a table."""
    value = info.get(key)
    return value.get(system) if isinstance(value, dict) else value


def packages(info):
    """The pip packages or commands a probe needs, on any system."""
    value = info.get("extras")
    return list(value.values()) if isinstance(value, dict) else [value] if value else []


def select(requested, run):
    """The probes for a recording: those on by default for the run VM's system (host probes alone for a screen
    with no run VM), plus each requested one ("name" or "name:KEY=VALUE,KEY=VALUE"). "none" turns the defaults off."""
    system = run["os"] if run else None
    chosen = {} if "none" in requested else {
        name: {} for name in plugins.known("probe")
        if per(info := manifest(name), "default", system) and usable(info, system, quiet=True)}
    for item in requested:
        if item != "none":
            name, given = plugins.spec(item)
            chosen[name] = given
    records = []
    for name, given in chosen.items():
        source = plugins.find("probe", name)
        info = plugins.manifest("probe", source)
        usable(info, system)
        record = {"name": info["name"], "version": info["version"], "where": info["where"], "source": str(source),
                  "values": plugins.resolve(info, given), "tracks": info.get("tracks", {}),
                  "setup": bool(info.get("setup")) and (run is None or run.guest.shell),
                  "tunnel": per(info, "tunnel", system)}
        if info.get("port"):
            record["port"] = free_port(0, run.host_address[0] if run else "127.0.0.1")
        if (extra := per(info, "extras", system)) and not installed(extra):
            record["unavailable"] = f"{extra} is not installed. Install it: pip install {extra}"
        records.append(record)
    return records


def installed(package):
    """True when the pip package is installed in this Python, the one that runs host probes."""
    try:
        importlib.metadata.distribution(package)
        return True
    except importlib.metadata.PackageNotFoundError:
        return False


def tool(command):
    """The path of a command next to this Python (a venv) or on PATH, or None."""
    return shutil.which(command, path=os.pathsep.join([str(Path(sys.executable).parent), os.environ.get("PATH", "")]))


def manifest(name):
    return plugins.manifest("probe", plugins.find("probe", name))


def usable(info, system, quiet=False):
    """A guest probe, or one that sets up the guest, needs a run VM of one of its systems. A host probe works with any
    screen."""
    if info["where"] == "host" and not info.get("setup") and (system is None or system in info["os"]):
        return True
    if (info["where"] == "guest" or info.get("setup")) and system in info["os"]:
        return True
    if quiet:
        return False
    where = "a run VM (proofreel vm up)" if system is None else f"{', '.join(info['os'])}, and the VM is {system}"
    raise Problem(f"Probe {info['name']} works on {where}.")


def prepare(records, run):
    """Copy each guest probe, and each probe that sets up the guest, into the run VM, before the recorder starts."""
    for record in records:
        if (record["where"] == "guest" or record.get("setup")) and not record.get("unavailable"):
            plugins.stage(run, "probe", record["source"], record["values"])


def begin(records, run):
    """Run each probe's guest start, once the recorder runs its host side. Its reset goes into the run record first.
    A start that fails is undone, with every start before it."""
    for record in records:
        if record.get("setup") and not record.get("unavailable"):
            values = {**record["values"], "PROOFREEL_PORT": str(record.get("port") or ""),
                      "PROOFREEL_HOST_FOR_GUEST": run.host_address[1]}
            plugins.pending(run, "probe", record["name"], "stop", values)
            code, output = plugins.script(run, "probe", record["name"], "start", values, timeout=90)
            if code:
                failed = plugins.failed(plugins.undo(run))
                raise Problem(f"Probe {record['name']}: its start in the run VM failed: {output[-400:] or code}"
                              + "".join(f" {line}" for line in failed))


def process(record, folder, info, run, tunnel=None):
    """(command line, environment) of a probe. A probe is told its values and where it runs, never the password."""
    told = {**record["values"], "PROOFREEL_APP": info.get("app") or "", "PROOFREEL_OS": (run or {}).get("os") or ""}
    if record["where"] == "host":
        bind, seen, guest_ip = run.host_address if run else ("127.0.0.1", "", "")
        return ([sys.executable, "-u", str(Path(record["source"]) / "run.py")],
                {**os.environ, **told, "PROOFREEL_SESSION": str(folder),
                 "PROOFREEL_VM_PID": str((run or {}).get("pid") or ""), "PROOFREEL_PORT": str(record.get("port") or ""),
                 "PROOFREEL_BIND": bind, "PROOFREEL_HOST_FOR_GUEST": seen, "PROOFREEL_GUEST_IP": guest_ip,
                 "PROOFREEL_TUNNEL": str(tunnel or "")})
    from ..vm import askpass
    script = run.guest.run_script(plugins.folder(run, "probe", record["name"]), "run", told)
    return run.argv(script, tty=True), {**os.environ, **askpass(run["password"])}


class Probe:
    """One running probe: its process, and a thread that keeps its lines."""

    def __init__(self, record, folder, info, run):
        self.name, self.status, self.note = record["name"], "starting", ""
        self.counts = {"kept": 0, "size": 0, "rate": 0, "series": 0, "bad": 0}
        self.settled = threading.Event()
        self.out = open(Path(folder) / "metrics" / f"{self.name}.jsonl", "a")
        port, self.tunnel = run.forward(record["tunnel"]) if record.get("tunnel") and run else (None, None)
        argv, env = process(record, folder, info, run, port)
        self.process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        stdin=subprocess.DEVNULL, env=env)
        self.thread = threading.Thread(target=self.pump, daemon=True)
        self.thread.start()

    def pump(self):
        series, second, in_second = set(), 0, 0
        for raw in self.process.stdout:
            arrived = time.time()
            if int(arrived) != second:
                second, in_second = int(arrived), 0
            in_second += 1
            if len(raw) > LINE:
                self.counts["size"] += 1
            elif (line := parse(raw)) is None:
                self.counts["bad"] += 1
            elif control := next((k for k in CONTROL if k in line), None):
                self.control(control, line[control])
            elif in_second > RATE:
                self.counts["rate"] += 1
            elif line["m"] not in series and len(series) >= SERIES:
                self.counts["series"] += 1
            else:
                series.add(line["m"])
                self.settled.set()
                self.status = "ok" if self.status == "starting" else self.status
                self.out.write(json.dumps({**line, "a": round(arrived, 4)}) + "\n")
                self.out.flush()
                self.counts["kept"] += 1

    def control(self, kind, value):
        if kind == "ready" and self.status == "starting":
            self.status = "ok"
        elif kind == "unavailable":
            self.status, self.note = "unavailable", str(value)[:400]
        elif kind == "meta" and isinstance(value, dict):
            self.note = json.dumps(value)[:400]
        if kind != "meta" or (isinstance(value, dict) and "waiting" in value):
            self.settled.set()

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.thread.join(timeout=3)
        self.out.close()
        if self.tunnel:
            self.tunnel.kill()
            self.tunnel.wait()
        if self.status == "starting":
            self.status, self.note = "silent", self.note or f"exit {self.process.returncode}, and no line"
        return {"status": self.status, "note": self.note, **self.counts}


def parse(raw):
    """A line of the protocol, or None. A measure has a series id m, and a finite v or d when it has one."""
    try:
        line = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(line, dict):
        return None
    if any(k in line for k in CONTROL):
        return line
    if not isinstance(line.get("m"), str) or not line["m"] or len(line["m"]) > 200:
        return None
    for key in ("v", "d", "t"):
        if key in line and not (isinstance(line[key], (int, float)) and not isinstance(line[key], bool)
                                and math.isfinite(line[key])):
            return None
    return line


def launch(folder):
    """Start the session's probes. Called in the recorder, so they live and end with it."""
    folder = Path(folder)
    info = json.loads((folder / "session.json").read_text())
    if not info.get("probes"):
        return []
    from .. import vm
    run = vm.Run.current() if info.get("run") and vm.CURRENT.exists() else None
    (folder / "metrics").mkdir(exist_ok=True)
    started = []
    for record in info["probes"]:
        if record.get("unavailable"):
            write_status(folder, {record["name"]: {"status": "unavailable", "note": record["unavailable"]}})
            continue
        try:
            started.append(Probe(record, folder, info, run))
        except OSError as error:
            write_status(folder, {record["name"]: {"status": "failed", "note": str(error)}})
    threading.Thread(target=settle, args=(folder, started), daemon=True).start()
    return started


def settle(folder, started):
    """Write metrics/settled once every probe is settled, or after SETTLE seconds. The recorder runs it in a thread."""
    end = time.monotonic() + SETTLE
    for probe in started:
        probe.settled.wait(max(0.0, end - time.monotonic()))
    (Path(folder) / "metrics" / "settled").touch()


def wait_settled(folder):
    """Called by `start`: wait for the recorder's probes to settle."""
    end = time.monotonic() + SETTLE + 2
    while not (Path(folder) / "metrics" / "settled").exists() and time.monotonic() < end:
        time.sleep(0.05)


def finish(folder, started):
    if started:
        write_status(folder, {probe.name: probe.stop() for probe in started})


def write_status(folder, status):
    path = Path(folder) / "metrics" / "probes.json"
    old = json.loads(path.read_text()) if path.exists() else {}
    path.write_text(json.dumps({**old, **status}, indent=1))


def end_group(pid):
    """Kill whatever a recorder left behind: it leads its own process group, and its probes are in it."""
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
