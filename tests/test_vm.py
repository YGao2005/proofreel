import json

import pytest

from proofreel import Problem, guest, qemu, vm


def test_states_tree_survives_a_parent_cycle(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vm, "STATES", tmp_path)
    for name, parent in (("a", "a"), ("b", "a"), ("c", "d"), ("d", "c"), ("e", "gone")):
        (tmp_path / f"{name}.json").write_text(json.dumps({"name": name, "parent": parent, "created": "x"}))
    vm.states()
    assert capsys.readouterr().out.split("\n")[:5] == ["a  x", "  b  x", "c  x", "d  x", "e  x"]


def test_saving_over_the_run_state_keeps_its_parent(tmp_path, monkeypatch):
    monkeypatch.setattr(vm, "STATES", tmp_path)
    monkeypatch.setattr(vm, "CURRENT", tmp_path / "run.json")
    vm.write_state("app", parent="clean", user="u", password="p", warm=False, backend="qemu", os="linux")
    (tmp_path / "run.json").write_text(json.dumps({"state": "app", "backend": "qemu", "os": "linux", "user": "u",
                                                   "password": "p", "conditions": []}))

    class Backend:
        save = staticmethod(lambda name, run, warm: {"memory": 4096, "cpu": 4})
        resume = staticmethod(lambda name, run, warm: {"vm": "r", "ip": "127.0.0.1", "vnc": "v"})

    monkeypatch.setattr(vm, "backend", lambda kind: Backend)
    monkeypatch.setattr(vm, "start", lambda info, name, run: run)
    vm.save("app")
    assert vm.state_info("app")["parent"] == "clean"


def test_a_state_must_say_its_backend_and_system(tmp_path, monkeypatch):
    monkeypatch.setattr(vm, "STATES", tmp_path)
    vm.write_state("old", parent="x", user="u", password="p")
    with pytest.raises(Problem, match="does not say its backend or os"):
        vm.state_info("old")


@pytest.mark.parametrize("system, cleaned", [("windows", True), ("linux", False), ("macos", False)])
def test_only_windows_forgets_its_screen_size_before_a_cold_save(system, cleaned, monkeypatch):
    commands = []
    monkeypatch.setattr(vm, "ssh", lambda command, **_: commands.append(command))
    guest.of({"os": system}).before_save({})
    assert bool(commands) == cleaned and all("GraphicsDrivers" in c for c in commands)


def test_qemu_display_comes_from_up_then_the_state_then_the_default(tmp_path, monkeypatch):
    monkeypatch.setattr(qemu, "FOLDER", tmp_path)
    monkeypatch.setattr(qemu, "CUSTOM_FIRMWARE", tmp_path / "code.fd")
    (tmp_path / "code.fd").touch()
    monkeypatch.setattr(qemu, "clone", lambda source, target: None)
    monkeypatch.setattr(qemu, "boot", lambda machine, memory_file=None: machine["display"])
    assert qemu.up("s", {}) == "1440x900"
    assert qemu.up("s", {"machine": {"display": "1280x800"}}) == "1280x800"
    assert qemu.up("s", {"machine": {"display": "1280x800"}}, display="1920x1080") == "1920x1080"
    assert qemu.up("s", {"warm": True, "machine": {"display": "1280x800"}}, display="1920x1080") == "1280x800"
    with pytest.raises(Problem):
        qemu.up("s", {}, display="big")


def test_the_guest_password_never_goes_to_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(vm, "HOME", tmp_path)
    env = vm.askpass("s3cret")
    assert env["PROOFREEL_GUEST_PASSWORD"] == "s3cret"
    assert "s3cret" not in (tmp_path / "askpass.sh").read_text()
    import subprocess
    assert subprocess.run([env["SSH_ASKPASS"]], env=env, capture_output=True, text=True).stdout == "s3cret\n"
    assert vm.askpass("other")["SSH_ASKPASS"] == env["SSH_ASKPASS"]
