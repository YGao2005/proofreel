import importlib.util
import io
import json
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
    values = dict(lines)
    assert found and values["cpu/app"] == 100.0 and values["app/procs"] == 2
    assert values["mem/app"] == 150_000 / 1024
    assert values["cpu/other"] == 20.0 and values["cpu/top/indexer"] == 20.0
    assert not any(m.startswith("cpu/top/Xorg") for m in values)


def test_a_reused_pid_counts_as_a_new_process_and_the_probe_leaves_itself_out():
    before = {(5, 10): (1, "old", "old", 900, 0), (6, 11): (1, "me", "me", 0, 0)}
    now = {(5, 99): (1, "new", "new", 30, 0), (6, 11): (1, "me", "me", 500, 0)}
    lines, found = procs.sample(before, now, seconds=1.0, tick=100, app="", me=6)
    assert dict(lines) == {"cpu/other": 30.0, "cpu/top/new": 30.0} and not found


def test_lines_carry_the_probe_clock_and_top_names_stop_at_the_limit():
    out = procs.Lines(io.StringIO())
    for n in range(procs.TOP_NAMES + 4):
        out.measures([("cpu/other", 1), (f"cpu/top/p{n}", 50)], t=n)
    lines = [json.loads(line) for line in out.out.getvalue().splitlines()]
    assert len({line["m"] for line in lines if line["m"].startswith("cpu/top/")}) == procs.TOP_NAMES
    assert all("t" in line for line in lines)


def test_the_probe_is_on_by_default_in_vm_runs_only():
    info = plugins.manifest("probe", FOLDER)
    assert info["where"] == "guest" and info["default"] and info["fidelity"] and info["privacy"]
    assert {"cpu/app", "mem/app", "cpu/system"} <= set(info["tracks"])
    assert "processes" in [p["name"] for p in probes.select([], {"os": "linux"})]
    assert "processes" not in [p["name"] for p in probes.select([], None)]


def test_a_macos_guest_builds_each_swift_file_of_a_staged_plugin(tmp_path, monkeypatch):
    from proofreel import guest
    (tmp_path / "procs.swift").write_text("print(1)\n")
    built = tmp_path / "built"
    built.write_text("binary")
    monkeypatch.setattr(guest.shutil, "which", lambda name: "/usr/bin/swiftc")
    monkeypatch.setattr(guest, "swift_tool", lambda source, *flags: built if flags == guest.MacOS.target else None)
    guest.GUESTS["linux"].build(tmp_path)
    assert not (tmp_path / "procs").exists()
    guest.GUESTS["macos"].build(tmp_path)
    assert (tmp_path / "procs").read_text() == "binary"
