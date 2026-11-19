import subprocess

import pytest

from proofreel import Problem, cli, vm


def run_check(argv, monkeypatch):
    logged = []
    monkeypatch.setattr(cli, "log", lambda kind, text, **fields: logged.append((text, fields["ok"], fields["detail"])))
    try:
        cli.main(["check", *argv])
    except SystemExit:
        pass
    return logged[0]


@pytest.mark.parametrize("system, code, ok", [("macos", 0, True), ("linux", 1, False), ("windows", 0, True)])
def test_running_asks_the_guest_in_its_own_way(system, code, ok, monkeypatch):
    sent = []
    monkeypatch.setattr(vm.Run, "current", classmethod(lambda cls: cls({"os": system})))
    monkeypatch.setattr(vm.Run, "ssh", lambda self, command, **_: sent.append(command) or
                        subprocess.CompletedProcess(command, code, "", ""))
    assert run_check(["running", "it's.exe" if system == "windows" else "app"], monkeypatch)[1] is ok
    assert ("if (Get-Process -Name 'it''s' " in sent[0] and sent[0].startswith("powershell -NoProfile")
            if system == "windows" else sent[0].startswith("pgrep -x app"))


def test_a_guest_command_runs_again_until_it_passes(monkeypatch):
    codes = iter([1, 1, 0])
    monkeypatch.setattr(vm.Run, "current", classmethod(lambda cls: cls({"os": "linux"})))
    monkeypatch.setattr(vm.Run, "ssh", lambda self, command, **_: subprocess.CompletedProcess(command, next(codes), "ok\n", ""))
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    assert run_check(["sh", "test -f /tmp/x", "30", "--label", "x exists"], monkeypatch) == ("x exists", True, "ok")


def test_a_host_command_with_no_seconds_runs_once(monkeypatch):
    assert run_check(["cmd", "exit 3"], monkeypatch) == ("exit 3", False, "")


def test_an_unquoted_command_stops_with_a_hint():
    with pytest.raises(Problem, match="Quote the command"):
        cli.check(cli.parser().parse_args(["check", "cmd", "echo", "a", "b"]), None, None)
