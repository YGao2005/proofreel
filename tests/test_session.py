import json
import shutil
from pathlib import Path

import pytest

from proofreel import Problem, session
from proofreel.screen import Screen

FIXTURE = Path(__file__).parent / "fixtures" / "v1-session"


def test_a_version_1_session_reads_as_version_2_in_time_order():
    events = session.Session(FIXTURE).events()
    assert [(e["kind"], e["t"], e.get("end")) for e in events] == [
        ("step", 100.0, None),
        ("click", 101.3, None),
        ("type", 102.0, 102.5),
        ("drag", 104.0, 104.6),
        ("check", 105.0, None),
        ("wait", 105.5, 110.0),
        ("wait", 109.0, 111.0),
    ]
    assert not any("dur" in e or "waited" in e for e in events)


def test_the_upgrade_never_writes_the_folder(tmp_path):
    folder = shutil.copytree(FIXTURE, tmp_path / "s")
    before = (folder / "events.jsonl").read_text()
    session.Session(folder).events()
    assert (folder / "events.jsonl").read_text() == before


def test_a_folder_from_a_newer_proofreel_is_refused(tmp_path):
    (tmp_path / "session.json").write_text(json.dumps({"version": session.VERSION + 1}))
    with pytest.raises(Problem, match="newer proofreel"):
        session.Session(tmp_path).events()


def test_log_keeps_an_end_only_for_an_action_with_a_length(tmp_path):
    s = session.Session(tmp_path)
    s.log("click", "click", 10.0, 10.001, x=1, y=2)
    s.log("type", "type", 11.0, 11.5)
    assert [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()] == [
        {"t": 10.0, "kind": "click", "text": "click", "x": 1, "y": 2},
        {"t": 11.0, "end": 11.5, "kind": "type", "text": "type"}]


def test_a_verdict_shows_at_its_end_and_an_action_at_its_start():
    assert session.moment({"t": 1.0, "end": 5.0, "kind": "check"}) == 5.0
    assert session.moment({"t": 1.0, "end": 5.0, "kind": "type"}) == 1.0


def test_frames_of_version_1_have_the_request_time_as_arrival(tmp_path):
    (tmp_path / "frames").mkdir()
    for n in range(2):
        (tmp_path / "frames" / f"{n:06d}.jpg").touch()
    (tmp_path / "times.txt").write_text("5.0\n4.0 4.1\n")
    paths, requests, arrivals = session.Session(tmp_path).frames()
    assert [p.name for p in paths] == ["000001.jpg", "000000.jpg"]
    assert requests == [4.0, 5.0] and arrivals == [4.1, 5.0]


def test_an_unknown_key_name_is_a_problem_that_lists_the_names():
    screen = Screen("vnc")
    assert screen.name("shift-a") == "shift-a" and screen.name("pgdn") == "pgdn"
    with pytest.raises(Problem, match="Unknown key 'Page_Down'.*pgdn"):
        screen.name("Page_Down")
