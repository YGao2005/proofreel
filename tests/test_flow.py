import json

import pytest

from proofreel import Problem, cli, flow, recording


def write(tmp_path, text):
    path = tmp_path / "f.flow"
    path.write_text(text)
    return path


def test_a_typo_on_any_line_stops_the_flow_before_the_first_line_runs(tmp_path, monkeypatch):
    ran = []
    monkeypatch.setattr(cli, "command", lambda words: ran.append(words))
    path = write(tmp_path, "note one\nnote two\nclick 10 ten\n")
    with pytest.raises(Problem, match=r"f.flow:3: proofreel click: argument y: invalid int value"):
        cli.run_flow(path, {})
    assert ran == []


def test_a_value_comes_from_set_then_the_default_and_a_missing_one_names_its_line(tmp_path):
    path = write(tmp_path, "note ${A}\nnote ${B:-bee}\n")
    assert flow.load(path, {"A": "ay"}, parse=lambda words: None).lines == [(1, ["note", "ay"]), (2, ["note", "bee"])]
    with pytest.raises(Problem, match=r"f.flow:1: No value for \$\{A\}"):
        flow.load(path, {}, parse=lambda words: None)


def test_a_failed_check_goes_on_and_any_other_failure_stops_the_recording(tmp_path):
    results = {"check": 1, "note": 0, "find": 1, "boom": None}

    def execute(words):
        if words[0] == "boom":
            raise RuntimeError("VNC refused")
        ran.append(words[0])
        return results[words[0]]

    stopped = []
    ran = []
    assert flow.run(flow.Flow("f.flow", [(1, ["check", "x"]), (2, ["note", "y"])]), execute, stopped.append) == 1
    assert ran == ["check", "note"] and stopped == []
    with pytest.raises(Problem, match="exit 1"):
        flow.run(flow.Flow("f.flow", [(1, ["find", "x"]), (2, ["note", "y"])]), execute, stopped.append)
    with pytest.raises(RuntimeError):
        flow.run(flow.Flow("f.flow", [(4, ["boom"])]), execute, stopped.append)
    assert stopped == ["f.flow:1: find x: exit 1", "f.flow:4: boom: VNC refused"]


def test_a_check_that_cannot_run_is_a_failed_check_with_the_reason(tmp_path, monkeypatch, alive):
    session = tmp_path / "s"
    (session / "frames").mkdir(parents=True)
    monkeypatch.setattr(recording, "POINTER", tmp_path / "active.json")
    (tmp_path / "active.json").write_text(json.dumps({"dir": str(session), "pid": 0}))

    def broken(*_args, **_kwargs):
        raise Problem("Text recognition needs macOS (swiftc) or tesseract on PATH.")

    monkeypatch.setattr(cli, "wait_for", broken)
    args = cli.parser().parse_args(["check", "text", "Saved"])
    assert cli.run_check(args, screen=None) == 1
    event = json.loads((session / "events.jsonl").read_text())
    assert (event["kind"], event["ok"]) == ("check", False)
    assert event["detail"] == "The check could not run: Text recognition needs macOS (swiftc) or tesseract on PATH."


def test_main_exits_1_for_a_failed_check_and_2_for_a_problem(monkeypatch, capsys):
    monkeypatch.setattr(cli, "command", lambda argv: 1)
    with pytest.raises(SystemExit) as done:
        cli.main([])
    assert done.value.code == 1

    def problem(argv):
        raise Problem("No run VM. Start one: proofreel vm up <state>.")

    monkeypatch.setattr(cli, "command", problem)
    with pytest.raises(SystemExit) as done:
        cli.main([])
    assert done.value.code == 2
    assert capsys.readouterr().err == "proofreel: No run VM. Start one: proofreel vm up <state>.\n"


def test_a_command_that_returns_a_value_does_not_become_the_exit_code(monkeypatch):
    monkeypatch.setattr(cli.vms, "up", lambda *a, **k: {"vm": "pr-run.vm"})
    assert cli.command(["vm", "up", "linux"]) is None


def test_version_prints_the_package_version(capsys):
    from proofreel import __version__
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["--version"])
    assert capsys.readouterr().out.strip() == f"proofreel {__version__}"
