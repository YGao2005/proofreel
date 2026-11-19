import json
import shutil
from pathlib import Path

import pytest

from proofreel import Problem, page
from proofreel.motion import Clock, spans, timeline

FIXTURE = Path(__file__).parent / "fixtures" / "v1-runs.json"


def test_the_clock_keeps_every_frame_within_half_a_frame_with_few_points():
    plan = timeline(spans([], [{"t": 20.0, "kind": "click"}, {"t": 50.0, "kind": "click"}]), 80)
    clock = Clock.of(plan)
    assert len(clock.knots) < len(plan) / 10
    assert max(abs(clock.video(now) - n / 30) for n, (now, _) in enumerate(plan)) <= 0.5 / 30
    assert clock.real(clock.video(33.3)) == pytest.approx(33.3, abs=0.01)


def test_a_version_1_run_gets_a_clock_from_its_video_times_and_rows():
    run = page.upgrade(json.loads(FIXTURE.read_text())[0])
    assert run["version"] == page.VERSION and run["verdict"] == "works"
    assert run["clock"] == [[0.0, 0.0], [0.5, 0.5], [2.0, 2.0], [3.0, 2.4], [14.0, 6.0]]
    assert [(e["kind"], e["row"]) for e in run["events"]] == [("step", "key"), ("click", "fold"), ("check", "key")]
    assert not any("v" in e for e in run["events"]) and "verdict_css" not in run and "fast" not in run


def test_a_run_from_a_newer_proofreel_is_refused():
    with pytest.raises(Problem, match="newer proofreel"):
        page.upgrade({"id": "x", "version": page.VERSION + 1, "events": []})


def test_publish_into_a_version_1_folder_keeps_the_old_runs_and_a_backup(tmp_path):
    out = tmp_path / "review"
    out.mkdir()
    shutil.copy(FIXTURE, out / "runs.json")
    session = tmp_path / "sign-up-20261119-090000"
    (session / "shots").mkdir(parents=True)
    (session / "session.mp4").write_bytes(b"mp4")
    (session / "run.json").write_text(json.dumps({**page.upgrade(json.loads(FIXTURE.read_text())[0]),
                                                  "id": session.name, "base": ""}))
    _, files, count = page.publish(session, out)
    data = json.loads((out / "runs.json").read_text())
    assert count == 2 and data["version"] == page.VERSION
    assert [r["id"] for r in data["runs"]] == ["sign-up-20261118-200000", session.name]
    assert json.loads((out / "runs.v1.json").read_text()) == json.loads(FIXTURE.read_text())
    assert list(files) == [f"runs/{session.name}/session.mp4"]
    assert not list(out.glob("*.tmp"))
