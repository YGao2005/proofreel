import json

import pytest

from proofreel import cli, conditions, crash, vm


def write_condition(folder, folder_name="fake-thing", **fields):
    path = folder / folder_name
    path.mkdir()
    manifest = {"name": folder_name, "version": 1, "os": ["macos"], "fakes": "a thing", "applies": "a script", "checks": "a probe",
                "fidelity": "no radio", **fields}
    lines = [f"{k} = {json.dumps(v)}" for k, v in manifest.items() if k != "values"]
    if "values" in fields:
        lines += ["[values]", *(f"{k} = {json.dumps(v)}" for k, v in fields["values"].items())]
    (path / "condition.toml").write_text("\n".join(lines) + "\n")
    for script in ("apply.sh", "check.sh"):
        (path / script).write_text("#!/bin/sh\n")
    return path


def test_every_shipped_condition_has_a_full_manifest():
    assert {"bluetooth-headset-call-mode", "no-microphone", "offline", "run-from-dmg",
            "quarantined-download"} <= set(conditions.known())
    for name in conditions.known():
        info = conditions.manifest(conditions.folder(name))
        assert all(info[field] for field in conditions.FIELDS)


def test_a_manifest_needs_every_field_its_folder_name_and_both_scripts(tmp_path):
    with pytest.raises(ValueError, match="fidelity"):
        conditions.manifest(write_condition(tmp_path, "a", fidelity=""))
    with pytest.raises(ValueError, match="must match"):
        conditions.manifest(write_condition(tmp_path, "b", name="other"))
    path = write_condition(tmp_path, "c")
    (path / "check.sh").unlink()
    with pytest.raises(ValueError, match="check.sh"):
        conditions.manifest(path)


def test_a_condition_refuses_a_run_vm_of_another_system(tmp_path, monkeypatch):
    monkeypatch.setattr(vm, "CURRENT", tmp_path / "run.json")
    (tmp_path / "run.json").write_text(json.dumps({"state": "s", "os": "linux", "conditions": []}))
    monkeypatch.setattr(vm, "ssh", lambda *a, **k: pytest.fail("nothing runs in the guest"))
    with pytest.raises(SystemExit, match="works on macos, and the VM is linux"):
        conditions.apply("offline", {})
    with pytest.raises(ValueError, match="unknown systems"):
        conditions.manifest(write_condition(tmp_path, os=["beos"]))


def test_values_take_the_default_and_a_value_with_no_default_is_required(tmp_path):
    info = conditions.manifest(write_condition(tmp_path, values={"RATE": "24000", "DMG": ""}))
    assert conditions.resolve(info, {"DMG": "/x.dmg", "OTHER": "1"}) == {"RATE": "24000", "DMG": "/x.dmg"}
    with pytest.raises(SystemExit, match="DMG"):
        conditions.resolve(info, {})


def test_a_flow_names_its_conditions_and_a_state_must_have_them():
    flow = "# a flow\ncondition offline\nstart x --title 'condition offline'\ncondition no-microphone # why\n"
    assert cli.needed(flow) == ["offline", "no-microphone"]
    state = [{"name": "offline", "version": 1}]
    assert conditions.missing(["offline", "no-microphone"], state) == ["no-microphone"]


def test_run_refuses_a_state_without_the_flow_condition(tmp_path, monkeypatch):
    monkeypatch.setattr(vm, "STATES", tmp_path)
    monkeypatch.setattr(vm, "CURRENT", tmp_path / "run.json")
    (tmp_path / "run.json").write_text(json.dumps({"state": "plain", "conditions": [{"name": "offline", "version": 1}]}))
    ran = []
    monkeypatch.setattr(cli, "main", lambda words: ran.append(words))
    flow = tmp_path / "f.flow"
    flow.write_text("condition bluetooth-headset-call-mode\nnote hello\n")
    with pytest.raises(SystemExit, match="needs condition bluetooth-headset-call-mode.*has offline"):
        cli.run_flow(flow, {})
    assert ran == []
    flow.write_text("condition offline\nnote hello\n")
    cli.run_flow(flow, {})
    assert ran == [["note", "hello"]]


IPS_HEADER = {"app_name": "Sample", "timestamp": "2026-11-19 09:02:36.00 +0000", "bundleID": "dev.example.sample",
              "bug_type": "309", "name": "Sample"}
IPS_BODY = {
    "procName": "Sample", "captureTime": "2026-11-19 09:02:35.7347 +0000",
    "exception": {"type": "EXC_CRASH", "signal": "SIGABRT"}, "asi": {"libsystem_c.dylib": ["abort() called"]},
    "faultingThread": 1,
    "usedImages": [{"name": "libsystem_kernel.dylib"}, {"name": "Sample"}, {"name": "AVFAudio"}],
    "threads": [{"frames": [{"imageIndex": 1, "imageOffset": 4096}]},
                {"triggered": True, "frames": [{"imageIndex": 0, "symbol": "__pthread_kill", "symbolLocation": 8},
                                               {"imageIndex": 1, "imageOffset": 65536}]}],
    "lastExceptionBacktrace": [{"imageIndex": 2, "symbol": "AVAudioEngineImpl::InstallTapOnNode", "symbolLocation": 1556},
                               {"imageIndex": 1, "symbol": "Recorder.start()", "symbolLocation": 624}],
}


def ips(header=IPS_HEADER, body=IPS_BODY):
    return json.dumps(header) + "\n" + json.dumps(body, indent=2)


def test_a_crash_report_gives_the_process_exception_and_top_frames():
    report = crash.parse("Sample-2026-11-19-090240.ips", ips())
    assert (report["kind"], report["process"], report["bundle"]) == ("crash", "Sample", "dev.example.sample")
    assert report["time"] == pytest.approx(1795078955.7347)
    lines = report["summary"].splitlines()
    assert lines[:3] == ["Sample: EXC_CRASH (SIGABRT)", "abort() called", "Thread 1 crashed:"]
    assert "  0 libsystem_kernel.dylib  __pthread_kill + 8" in lines
    assert "  1 Sample  0x10000" in lines
    assert "  0 AVFAudio  AVAudioEngineImpl::InstallTapOnNode + 1556" in lines


def test_a_simulated_crash_and_other_report_types_are_not_crashes():
    assert crash.parse("x.ips", ips({**IPS_HEADER, "is_simulated": 1}))["kind"] == "report"
    assert crash.parse("x.ips", ips({**IPS_HEADER, "bug_type": "298"}, {"memoryStatus": {}}))["kind"] == "report"


def test_a_hang_report_gives_the_process_and_duration():
    text = "Date/Time:        2026-11-19 09:02:35.734 +0000\nDuration:         5.12s\nProcess:          Sample [812]\n"
    report = crash.parse("Sample_2026-11-19-090240.hang", text)
    assert (report["kind"], report["process"], report["summary"]) == ("hang", "Sample", "Sample hang, 5.12s")


def test_only_the_app_under_test_fails_the_run_and_a_clean_run_says_so():
    app_crash = crash.parse("a.ips", ips())
    other = {**app_crash, "process": "helperd", "bundle": "com.example.helperd"}
    start, end = 1795078900.0, 1795079000.0
    events = crash.events([app_crash, other], "Sample", start, end)
    assert [(e["kind"], e.get("ok")) for e in events] == [("check", False), ("note", None)]
    assert events[0]["text"] == "Sample did not crash" and events[0]["t"] == pytest.approx(1795078955.7347)
    assert crash.events([other], "Sample", start, end)[-1] == {
        "t": end, "kind": "check", "text": "Sample did not crash or hang", "ok": True,
        "detail": "1 other report(s) in the guest"}
    assert [e["ok"] for e in crash.events([other], None, start, end)] == [False]
