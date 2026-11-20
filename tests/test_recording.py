import json
import os
import subprocess
import sys
import time

import pytest

from proofreel import Problem, recording


def test_a_folder_records_while_its_recorder_holds_the_lock(tmp_path):
    holder = subprocess.Popen([sys.executable, "-c", "import fcntl,sys,time; f=open(sys.argv[1],'w'); "
                               "fcntl.flock(f, fcntl.LOCK_EX); print('locked', flush=True); time.sleep(30)",
                               str(tmp_path / "recorder.lock")], stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline() == "locked\n"
    assert recording.recording(tmp_path)
    holder.kill()
    holder.wait()
    assert not recording.recording(tmp_path)


def test_a_pointer_to_a_recorder_that_never_started_is_cleared(home):
    folder = home / "sessions" / "x"
    folder.mkdir(parents=True)
    recording.POINTER.write_text(json.dumps({"dir": str(folder), "pid": 0}))
    assert recording.current() is None and not recording.POINTER.exists()
    (folder / "frames").mkdir()
    recording.POINTER.write_text(json.dumps({"dir": str(folder), "pid": 0}))
    assert recording.unstopped()["dir"] == str(folder)


def test_a_session_whose_recorder_is_dead_is_not_current_but_is_not_stopped(home):
    folder = home / "sessions" / "x"
    (folder / "frames").mkdir(parents=True)
    recording.POINTER.write_text(json.dumps({"dir": str(folder), "pid": 0}))
    assert recording.current() is None
    assert recording.unstopped()["dir"] == str(folder)
    recording.log("note", "nobody records")
    assert not (folder / "events.jsonl").exists()


def test_start_stops_a_session_whose_recorder_died_then_starts(home, monkeypatch):
    folder = home / "sessions" / "x"
    (folder / "frames").mkdir(parents=True)
    recording.POINTER.write_text(json.dumps({"dir": str(folder), "pid": 0}))
    stopped = []
    monkeypatch.setattr(recording, "stop", lambda error=None, **_: stopped.append((error, recording.POINTER.unlink())))

    class Began(Exception):
        pass

    def popen(*args, **kwargs):
        raise Began

    monkeypatch.setattr(recording.subprocess, "Popen", popen)
    with pytest.raises(Began):
        recording.start("y", "vnc", "", {}, run=None)
    assert stopped == [(recording.DIED, None)]


def test_start_refuses_while_a_recorder_is_alive(home, monkeypatch):
    folder = home / "sessions" / "x"
    (folder / "frames").mkdir(parents=True)
    recording.POINTER.write_text(json.dumps({"dir": str(folder), "pid": 0}))
    monkeypatch.setattr(recording, "recording", lambda f: True)
    with pytest.raises(Problem, match="A session is recording"):
        recording.start("y", "vnc", "", {}, run=None)


def test_stop_of_a_dead_recorder_does_not_signal_its_pid(home, monkeypatch):
    folder = home / "sessions" / "x"
    (folder / "frames").mkdir(parents=True)
    (folder / "session.json").write_text("{}")
    bystander = subprocess.Popen(["sleep", "30"])
    recording.POINTER.write_text(json.dumps({"dir": str(folder), "pid": bystander.pid}))
    monkeypatch.setattr("proofreel.render.render", lambda folder, **k: "rendered")
    try:
        assert recording.stop() == "rendered"
        assert bystander.poll() is None
    finally:
        bystander.kill()
        bystander.wait()


def test_clean_keeps_the_session_that_is_recording(home):
    old, live = home / "sessions" / "old", home / "sessions" / "live"
    for folder in (old, live):
        (folder / "frames").mkdir(parents=True)
    week_ago = time.time() - 8 * 86400
    for folder in (old, live):
        os.utime(folder, (week_ago, week_ago))
    recording.POINTER.write_text(json.dumps({"dir": str(live), "pid": 0}))
    assert recording.clean(7) == [old]
    assert live.exists() and not old.exists()


def test_a_session_is_found_by_its_folder_or_its_bare_name(tmp_path, monkeypatch):
    monkeypatch.setattr(recording, "SESSIONS", tmp_path)
    (tmp_path / "sign-in-1").mkdir()
    (tmp_path / "sign-in-1" / "session.json").write_text("{}")
    assert recording.session_folder("sign-in-1") == tmp_path / "sign-in-1"
    assert recording.session_folder(str(tmp_path / "sign-in-1")) == tmp_path / "sign-in-1"
    with pytest.raises(Problem, match="No session 'gone'"):
        recording.session_folder("gone")
