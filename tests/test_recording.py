import json
import os
import subprocess
import sys
import time

from proofreel import recording


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
    assert recording.current()["dir"] == str(folder)


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
