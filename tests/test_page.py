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
    _, files, count, new = page.publish(session, out)
    data = json.loads((out / "runs.json").read_text())
    assert count == 2 and data["version"] == page.VERSION
    assert [r["id"] for r in data["runs"]] == ["sign-up-20261118-200000", session.name]
    assert json.loads((out / "runs.v1.json").read_text()) == json.loads(FIXTURE.read_text())
    assert list(files) == new == [f"runs/{session.name}/session.mp4"]
    assert not list(out.glob("*.tmp"))


def test_the_newest_runs_keep_their_curves_and_older_runs_keep_stats_only(tmp_path):
    out = tmp_path / "review"
    series = {"m": "host/cpu", "kind": "sample", "unit": "%", "stats": {"count": 2, "failed": 0, "max": 9},
              "points": [[0.5, 1], [1.5, 9]]}
    for n in range(page.CURVES + 2):
        folder = tmp_path / f"run-{n}"
        folder.mkdir()
        (folder / "run.json").write_text(json.dumps({
            "version": page.VERSION, "id": folder.name, "title": "t", "verdict": "works", "events": [], "clock": [[0, 0]],
            "metrics": {"series": [series], "budgets": [], "probes": {}}}))
        page.publish(folder, out)
    runs = page.load_runs(out)
    assert [("points" in r["metrics"]["series"][0]) for r in runs] == [False, False] + [True] * page.CURVES
    assert all(r["metrics"]["series"][0]["stats"]["max"] == 9 for r in runs)


def session(tmp_path, name, **run):
    folder = tmp_path / name
    (folder / "shots").mkdir(parents=True)
    (folder / "session.mp4").write_bytes(b"mp4")
    (folder / "shots" / "1.jpg").write_bytes(b"jpg")
    (folder / "run.json").write_text(json.dumps(page.stub(name, name, "", video=True, **run)))
    return folder


def test_publish_lists_the_files_of_every_run_in_the_folder_not_only_the_new_one(tmp_path):
    out = tmp_path / "review"
    page.publish(session(tmp_path, "a-1"), out)
    _, files, count, new = page.publish(session(tmp_path, "a-2"), out)
    assert count == 2
    assert sorted(files) == ["runs/a-1/session.mp4", "runs/a-1/shots/1.jpg", "runs/a-2/session.mp4",
                             "runs/a-2/shots/1.jpg"]
    assert new == ["runs/a-2/session.mp4", "runs/a-2/shots/1.jpg"]
    assert all(Path(source).exists() for source in files.values())


def test_a_suite_page_is_titled_by_the_suite_and_keeps_each_journey(tmp_path):
    out = tmp_path / "review"
    suite = {"id": "20261119-100000", "title": "Upload"}
    page.publish(session(tmp_path, "drag-1"), out, suite=suite, journey="drag")
    page.add(out, page.stub("browse-1", "browse", "SSH in the VM did not start.", suite=suite, journey="browse"))
    runs = page.load_runs(out)
    assert [(r["journey"], r["suite"]["id"], r.get("video", True)) for r in runs] == [
        ("drag", suite["id"], True), ("browse", suite["id"], False)]
    assert (out / "index.html").read_text().startswith("<title>Upload</title>")


def test_every_journey_of_the_newest_suite_run_keeps_its_curves(tmp_path):
    out = tmp_path / "review"
    series = {"m": "host/cpu", "kind": "sample", "unit": "%", "stats": {"count": 2, "failed": 0, "max": 9},
              "points": [[0.5, 1], [1.5, 9]]}
    for stamp in ("1", "2"):
        for n in range(page.CURVES + 1):
            page.add(out, page.stub(f"j{n}-{stamp}", f"j{n}", "", suite={"id": stamp, "title": "S"},
                                    metrics={"series": [series], "budgets": [], "probes": {}}))
    runs = page.load_runs(out)
    assert [("points" in r["metrics"]["series"][0]) for r in runs] == [False] * (page.CURVES + 1) + [True] * (page.CURVES + 1)
