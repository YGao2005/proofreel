import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

from proofreel import plugins, probes

FOLDER = Path(probes.__file__).parent / "processes"
spec = importlib.util.spec_from_file_location("procs", FOLDER / "procs.py")
procs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(procs)


def fake_proc(root, table, busy=0, idle=0):
    """A made-up /proc: table is {pid: (parent, name, argv0, cpu ticks, pss kB or None for no smaps_rollup)}."""
    for pid, (parent, name, argv0, cpu, pss) in table.items():
        folder = root / str(pid)
        folder.mkdir(parents=True, exist_ok=True)
        fields = ["S", parent] + [0] * 9 + [cpu - cpu // 3, cpu // 3] + [0] * 6 + [pid * 7] + [0] * 30
        (folder / "stat").write_text(f"{pid} ({name}) {' '.join(map(str, fields))}\n")
        (folder / "cmdline").write_bytes(argv0.encode() + b"\0--flag\0" if argv0 else b"")
        (folder / "statm").write_text(f"9000 {2048 // procs.PAGE_KB} 0 0 0 0 0\n")
        if pss is not None:
            (folder / "smaps_rollup").write_text(f"Rss:  9999 kB\nPss:  {pss} kB\n")
    (root / "stat").write_text(f"cpu  {busy} 0 0 {idle} 0 0 0 0 0 0\ncpu0 1 2 3 4\n")
    (root / "meminfo").write_text("MemTotal:  4000000 kB\nMemFree:  100 kB\nMemAvailable:  2976000 kB\n")
    (root / "self").mkdir(exist_ok=True)
    return root


TABLE = {
    1: (0, "systemd", "/sbin/init", 50, None),
    2: (0, "kthreadd", "", 0, None),
    100: (1, "acme-notes", "/opt/acme/acme-notes", 100, 100_000),
    101: (100, "acme-notes", "/opt/acme/acme-notes", 20, 50_000),
    102: (101, "helper", "/opt/acme/helper", 0, 10_240),
    200: (1, "Xorg", "/usr/bin/Xorg", 10, None),
}


def test_reads_each_process_with_pss_or_else_rss_and_the_system(tmp_path):
    found = procs.processes(fake_proc(tmp_path, TABLE, busy=300, idle=700))
    assert found[(100, 700)] == (1, "acme-notes", "acme-notes", 100, 100_000)
    assert found[(200, 1400)][4] == 2048 and found[(2, 14)][2] == ""
    assert procs.system(tmp_path) == (300, 1000, 1000.0)


def test_the_app_is_each_process_by_that_name_and_all_under_it(tmp_path):
    found = procs.processes(fake_proc(tmp_path, TABLE))
    assert {pid for pid, _ in procs.app_tree(found, "acme-notes")} == {100, 101, 102}
    assert {pid for pid, _ in procs.app_tree(found, "/opt/acme/helper")} == set()
    assert {pid for pid, _ in procs.app_tree(found, "helper")} == {102}
    assert procs.app_tree(found, "") == set() and procs.app_tree(found, "nothing") == set()
    long = {(7, 1): (1, "acme-notes-desk", "acme-notes-desk", 0, 0)}
    assert procs.app_tree(long, "acme-notes-desktop") == {(7, 1)}


def test_cpu_is_the_ticks_used_between_two_reads_as_a_percent_of_one_core(tmp_path):
    before = procs.processes(fake_proc(tmp_path / "a", TABLE))
    later = {**TABLE, 100: (1, "acme-notes", "/opt/acme/acme-notes", 250, 100_000),
             101: (100, "acme-notes", "/opt/acme/acme-notes", 70, 50_000), 300: (1, "indexer", "/usr/bin/indexer", 40, None)}
    del later[102]
    now = procs.processes(fake_proc(tmp_path / "b", later))
    lines, found = procs.sample(before, now, seconds=2.0, tick=100, app="acme-notes")
    assert found and dict(lines) == {"cpu/app": 100.0, "mem/app": 150_000 / 1024, "app/procs": 2}
    assert procs.sample(before, now, seconds=2.0, tick=100, app="nothing") == ([], False)


def test_a_reused_pid_counts_as_a_new_process_and_a_dropped_counter_as_no_cpu():
    before = {(5, 10): (1, "app", "app", 900, 0), (6, 11): (1, "app", "app", 900, 0)}
    now = {(5, 99): (1, "app", "app", 30, 0), (6, 11): (1, "app", "app", 100, 0)}
    assert dict(procs.sample(before, now, seconds=1.0, tick=100, app="app")[0])["cpu/app"] == 30.0


def test_lines_carry_the_probe_clock():
    out = procs.Lines(io.StringIO())
    out.measures([("cpu/app", 1.234), ("mem/app", 5)], t=7.5)
    assert [json.loads(line) for line in out.out.getvalue().splitlines()] == [
        {"m": "cpu/app", "v": 1.23, "t": 7.5}, {"m": "mem/app", "v": 5, "t": 7.5}]


def test_the_probe_is_on_by_default_in_vm_runs_only():
    info = plugins.manifest("probe", FOLDER)
    assert info["where"] == "guest" and info["default"] and info["fidelity"] and info["privacy"]
    assert {"cpu/app", "mem/app", "cpu/system"} <= set(info["tracks"])
    assert "processes" in [p["name"] for p in probes.select([], {"os": "linux"})]
    assert "processes" not in [p["name"] for p in probes.select([], None)]


PS = """  1     0     0:01.50   1200 Mon Nov 16 09:00:00 2026 /sbin/launchd
 50     1  1:02:03.25 200000 Thu Nov 19 10:00:00 2026 /Applications/Acme Notes.app/Contents/MacOS/Acme Notes
 51    50     0:00.40  30000 Thu Nov 19 10:00:01 2026 /Applications/Acme Notes.app/Contents/Frameworks/helper
bad row
"""


def test_ps_rows_become_processes_keyed_by_pid_and_start_with_cpu_in_hundredths():
    found = procs.ps_processes(PS)
    assert len(found) == 3
    assert found[(50, "Thu Nov 19 10:00:00 2026")] == (1, "Acme Notes", "Acme Notes", 372325.0, 200000)
    assert found[(51, "Thu Nov 19 10:00:01 2026")][3] == 40.0
    assert {pid for pid, _ in procs.app_tree(found, "Acme Notes")} == {50, 51}


def test_the_probe_says_ready_first_and_an_app_that_is_not_there_gives_no_app_lines():
    env = {**os.environ, "INTERVAL": "0.1", "PROOFREEL_APP": "no-such-app-anywhere"}
    child = subprocess.Popen([sys.executable, "-u", str(FOLDER / "procs.py")], env=env, stdout=subprocess.PIPE, text=True)
    try:
        lines = [json.loads(child.stdout.readline()) for _ in range(5)]
    finally:
        child.kill()
        child.wait()
    assert lines[0] == {"ready": True}
    assert all(line.get("m") not in ("cpu/app", "mem/app", "app/procs") for line in lines)
    assert any(line.get("m") == "mem/system" or "meta" in line for line in lines)
