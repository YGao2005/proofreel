import json
from pathlib import Path

import pytest

from proofreel import Problem, cli, page, recording, suite, tart
from proofreel import vm as vms


def flows(tmp_path, **texts):
    folder = tmp_path / "flows"
    folder.mkdir()
    for name, text in texts.items():
        (folder / f"{name}.flow").write_text(text)
    return folder


def test_a_flow_names_its_state_once(tmp_path):
    path = tmp_path / "f.flow"
    path.write_text("from warm-app\nnote hi\n")
    assert cli.load_flow(path, {}).state == "warm-app"
    path.write_text("from a\nfrom b\n")
    with pytest.raises(Problem, match="f.flow:2: Write one line from <state>"):
        cli.load_flow(path, {})


def test_run_refuses_a_run_vm_from_another_state(home, tmp_path):
    path = tmp_path / "f.flow"
    path.write_text("from warm-app\nnote hi\n")
    vms.CURRENT.write_text(json.dumps({"id": "r", "state": "clean", "conditions": []}))
    with pytest.raises(Problem, match="starts from saved state warm-app, and the run VM is from clean"):
        cli.run_flow(path, {})


@pytest.fixture
def fake_vms(home, monkeypatch):
    """vm up writes a run record from the state (a state named broken does not start); vm down counts and clears."""
    for name in ("warm", "broken"):
        vms.write_state(name, backend="qemu", os="linux", user="u", password="p")
    calls = []

    def up(state, *args, **kwargs):
        calls.append(f"up {state}")
        if state == "broken":
            raise Problem("SSH in the VM did not start.")
        vms.CURRENT.write_text(json.dumps({"id": state, "state": state, "conditions": []}))

    def down():
        calls.append("down")
        vms.CURRENT.unlink(missing_ok=True)

    monkeypatch.setattr(vms, "up", up)
    monkeypatch.setattr(vms, "down", down)
    return calls


@pytest.fixture
def fake_recording(home, monkeypatch, alive):
    """start makes a session folder; stop writes its run.json from the logged checks and the error."""
    def stop(error=None, **_):
        folder = Path(recording.current()["dir"])
        events = [json.loads(line) for line in (folder / "events.jsonl").read_text().splitlines()] \
            if (folder / "events.jsonl").exists() else []
        verdict = page.verdict({"error": error}, events)
        (folder / "run.json").write_text(json.dumps({**page.stub(folder.name, folder.name, error or ""),
                                                     "verdict": verdict, "video": True, "events": events}))
        (folder / "session.mp4").write_bytes(b"mp4")
        recording.POINTER.unlink()
        return "stopped"

    def execute(words):
        match words[0]:
            case "start":
                folder = recording.SESSIONS / words[1]
                (folder / "frames").mkdir(parents=True)
                recording.POINTER.write_text(json.dumps({"dir": str(folder), "pid": 0}))
            case "stop":
                stop()
            case "check":
                recording.log("check", words[2], ok=words[2] == "good")
                return 0 if words[2] == "good" else 1
            case "boom":
                raise Problem("The VNC screen sent no frame in 3 tries.")

    monkeypatch.setattr(recording, "stop", stop)
    return execute


def test_a_suite_runs_each_flow_on_a_new_clone_and_a_failure_does_not_stop_it(tmp_path, fake_vms, fake_recording,
                                                                                monkeypatch):
    folder = flows(tmp_path,
                   a_fails="start a\ncheck text bad\nnote boom\nnote never\nstop\n",
                   b_passes="start b\ncheck text good\nstop\n",
                   c_no_vm="from broken\nstart c\nstop\n",
                   d_no_stop="start d\ncheck text good\n")

    def execute(words):
        return fake_recording(["boom"] if words == ["note", "boom"] else words)

    out = tmp_path / "review"
    load = lambda path: cli.load_flow(path, {})
    (page_path, files, count, new), rows = suite.run([folder], load, cli.play, execute, state="warm", out=out)
    assert [(mark, name) for mark, name, _ in rows] == [("FAIL", "a_fails"), ("PASS", "b_passes"),
                                                        ("FAIL", "c_no_vm"), ("FAIL", "d_no_stop")]
    assert "no frame" in rows[0][2] and rows[2][2] == "SSH in the VM did not start."
    assert fake_vms == ["up warm", "down", "up warm", "down", "up broken", "down", "up warm", "down"]
    runs = page.load_runs(out)
    assert count == 4 and {r["suite"]["title"] for r in runs} == {"flows"}
    assert runs[2]["video"] is False and runs[2]["error"] == "SSH in the VM did not start."
    assert "did not stop its recording" in runs[3]["error"]
    assert sorted(files) == sorted(new) == ["runs/a/session.mp4", "runs/b/session.mp4", "runs/d/session.mp4"]
    assert page_path == out / "index.html"


def test_a_journey_that_differs_between_runs_is_flaky_and_not_a_pass(tmp_path, fake_vms, fake_recording):
    folder = flows(tmp_path, steady="start steady\ncheck text good\nstop\n", odd="start odd\ncheck text MAYBE\nstop\n")
    runs = {"steady": 0, "odd": 0}

    def execute(words):
        if words[0] == "start":
            runs[words[1]] += 1
            words = [words[0], f"{words[1]}-{runs[words[1]]}"]
        if words[:2] == ["check", "text"] and words[2] == "MAYBE":
            words = ["check", "text", "good" if runs["odd"] != 2 else "bad"]
        return fake_recording(words)

    out = tmp_path / "review"
    _, rows = suite.run([folder], lambda path: cli.load_flow(path, {}), cli.play, execute, state="warm", out=out, repeat=3)
    assert rows == [("FLAKY", "odd", "passed 2 of 3 runs"), ("PASS", "steady", None)]
    found = page.load_runs(out)
    assert [(r["title"], r["verdict"], r.get("flaky")) for r in found if r["journey"] == "odd"] == [
        ("odd-1 #1", "works", {"passed": 2, "of": 3}), ("odd-2 #2", "problem", {"passed": 2, "of": 3}),
        ("odd-3 #3", "works", {"passed": 2, "of": 3})]
    assert all("flaky" not in r and r["attempts"] == 3 for r in found if r["journey"] == "steady")
    assert fake_vms.count("up warm") == 6


def test_each_repeat_reads_the_flow_again_and_a_run_id_in_a_check_is_not_a_difference(tmp_path, fake_vms, fake_recording):
    folder = flows(tmp_path, a="start a\ncheck text good\ncheck text ${RUN}\nstop\n")
    ids = []

    def execute(words):
        if words[0] == "start":
            words = [words[0], f"a-{len(ids) + 1}"]
            ids.append(None)
        if words[:2] == ["check", "text"] and words[2] != "good":
            ids[-1] = words[2]
            recording.log("check", words[2], ok=True)
            return 0
        return fake_recording(words)

    _, rows = suite.run([folder], lambda path: cli.load_flow(path, {}), cli.play, execute, state="warm",
                        out=tmp_path / "review", repeat=3)
    assert rows == [("PASS", "a", None)] and len(set(ids)) == 3 and all(len(run) == 8 for run in ids)


def test_a_suite_reads_every_flow_and_finds_every_state_before_a_vm_starts(tmp_path, fake_vms, fake_recording):
    folder = flows(tmp_path, a="from warm\nnote one\n", b="note two\n")
    with pytest.raises(Problem, match="b.flow names no state"):
        suite.run([folder], lambda path: cli.load_flow(path, {}), cli.play, fake_recording)
    with pytest.raises(Problem, match="No state 'gone'"):
        suite.run([folder], lambda path: cli.load_flow(path, {}), cli.play, fake_recording, state="gone")
    assert fake_vms == []


def test_a_warm_state_boots_with_no_host_audio(home, monkeypatch):
    monkeypatch.setattr(tart, "HOME", home)
    started = []
    monkeypatch.setattr(tart.subprocess, "Popen", lambda args, **_: started.append(args) or type("P", (), {"pid": 1}))
    monkeypatch.setattr(tart, "wait", lambda test, seconds, error: {"host": "h", "port": "1", "pw": "x"})
    for suspendable in (True, False):
        tart.boot(suspendable)
    assert all("--no-audio" in args for args in started)
    assert ["--suspendable" in args for args in started] == [True, False]


def test_a_suite_journey_gets_the_flows_probes_and_recording_conditions_at_start(home, tmp_path):
    vms.CURRENT.write_text(json.dumps({"state": "warm", "conditions": []}))
    path = tmp_path / "f.flow"
    path.write_text("from warm\nprobe host-load\ncondition slow-network:profile=edge\nstart x\nnote hi\n")
    ran = []
    cli.play(cli.load_flow(path, {}), lambda words: ran.append(words))
    digest = cli.load_flow(path, {}).digest
    assert ran == [["start", "x", "--probe=host-load", "--condition=slow-network:profile=edge", f"--meta=flow=f.flow {digest}"],
                   ["note", "hi"]]
