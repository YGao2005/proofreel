"""Probes: what a session measures while it records, such as the host's load, an app's CPU, or request times.

A probe is a plugin (see plugins.py): probe.toml and scripts. `where` says where it runs: on the host (run.py, run
with this Python) or in the guest (run.sh or run.ps1, over SSH). `default = true` turns it on for every recording on
its systems. `privacy` says what it can see. [tracks."<series glob>"] tells the page and `stats` how to show a series:
label, unit, better ("lower" or "higher"), max, and bands (values the page draws a guide line at). A host probe with
`tunnel = <guest port>` gets PROOFREEL_TUNNEL, a host port on 127.0.0.1 that reaches that port on the guest's
127.0.0.1 while it runs.

The protocol: a probe prints one JSON object on each line.
  {"m": "cpu/app", "v": 42}                               a sample of the series cpu/app
  {"m": "net/GET api.x", "d": 0.31, "ok": true, ...}      a span: something that took d seconds and ended then
  {"m": "app/launched"}                                   a mark
  "t", optional on each: when, in the probe's own steady clock. Without it, the time the line reached the host counts.
  {"ready": true}   {"unavailable": "<why>"}   {"meta": {...}}   control lines
The recorder keeps each measure in metrics/<probe>.jsonl with "a", the unix time it arrived, and the probe's status
in metrics/probes.json. A line over a limit (LINE bytes, RATE lines a second, SERIES ids) is counted and dropped;
control lines skip the rate limit.

More manifest fields:
  extras = "<command>"   a command it needs. Without it, the probe is unavailable, with the command that installs it.
  port = true            the host gives it a free port, in PROOFREEL_PORT.
  setup = true           guest start and stop scripts change the run VM for the recording (a proxy, a trusted CA).
                         start runs once the host run runs; stop must work after a start that stopped half way.
                         Each reset is written to the run record before its start, so recover() undoes it after a
                         crash: at the next start and at `vm save`.
A host probe for a run VM gets PROOFREEL_BIND (the address to listen on), PROOFREEL_HOST_FOR_GUEST (that address as
the guest sees it), and PROOFREEL_GUEST_IP (the guest as the host sees it); start and stop get PROOFREEL_PORT and
PROOFREEL_HOST_FOR_GUEST.
"""

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
CONTROL = ("ready", "unavailable", "meta")


def select(requested, run):
    """The probes for a recording: those on by default for the run VM's system (host probes alone for a screen
    with no run VM), plus each requested one ("name" or "name:KEY=VALUE,KEY=VALUE"). "none" turns the defaults off."""
    system = run["os"] if run else None
    chosen = {} if "none" in requested else {
        name: {} for name in plugins.known("probe")
        if (info := manifest(name)).get("default") and usable(info, system, quiet=True)}
    for item in requested:
        if item != "none":
            name, _, pairs = item.partition(":")
            chosen[name] = dict(pair.split("=", 1) for pair in pairs.split(",") if pair)
    records = []
    for name, given in chosen.items():
        source = plugins.find("probe", name)
        info = plugins.manifest("probe", source)
        usable(info, system)
        record = {"name": info["name"], "version": info["version"], "where": info["where"], "source": str(source),
                  "values": plugins.resolve(info, given), "tracks": info.get("tracks", {}),
                  "setup": bool(info.get("setup")), "tunnel": info.get("tunnel")}
        if info.get("port"):
            record["port"] = free_port(0, run.host_address[0] if run else "127.0.0.1")
        if info.get("extras") and not tool(info["extras"]):
            record["unavailable"] = f"{info['extras']} is not installed. Install it: pip install {info['extras']}"
        records.append(record)
    return records


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
            resets(lambda pending: [*pending, {"name": record["name"], "values": values}])
            code, output = plugins.script(run, "probe", record["name"], "start", values, timeout=90)
            if code:
                failed = recover(run)
                raise Problem(f"Probe {record['name']}: its start in the run VM failed: {output[-400:] or code}"
                              + "".join(f" {line}" for line in failed))


def resets(change=None):
    """The run record's pending resets, after an optional change to them."""
    from ..vm import CURRENT
    record = json.loads(CURRENT.read_text())
    if change:
        record["pending"] = change(record.get("pending", []))
        CURRENT.write_text(json.dumps(record))
    return record.get("pending", [])


def recover(run):
    """Run the pending resets, last first, and clear them. Returns a line for each reset that failed."""
    failed = []
    for reset in reversed(resets()):
        code, output = plugins.script(run, "probe", reset["name"], "stop", reset["values"], timeout=90)
        if code:
            failed.append(f"Probe {reset['name']}: its stop in the run VM failed: {output[-400:] or code}")
    resets(lambda pending: [])
    return failed


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
    return started


def finish(folder, started):
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
