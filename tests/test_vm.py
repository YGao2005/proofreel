import json

import pytest

from proofreel import qemu, vm


def test_states_tree_survives_a_parent_cycle(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vm, "STATES", tmp_path)
    for name, parent in (("a", "a"), ("b", "a"), ("c", "d"), ("d", "c"), ("e", "gone")):
        (tmp_path / f"{name}.json").write_text(json.dumps({"name": name, "parent": parent, "created": "x"}))
    vm.states()
    assert capsys.readouterr().out.split("\n")[:5] == ["a  x", "  b  x", "c  x", "d  x", "e  x"]


def test_saving_over_the_run_state_keeps_its_parent(tmp_path, monkeypatch):
    monkeypatch.setattr(vm, "STATES", tmp_path)
    monkeypatch.setattr(vm, "CURRENT", tmp_path / "run.json")
    vm.write_state("app", parent="clean", user="u", password="p", warm=False, backend="qemu")
    (tmp_path / "run.json").write_text(json.dumps({"state": "app", "backend": "qemu", "user": "u", "password": "p"}))

    class Backend:
        save = staticmethod(lambda name, run, warm: {"memory": 4096, "cpu": 4})
        resume = staticmethod(lambda name, run, warm: {"vm": "r", "ip": "127.0.0.1", "vnc": "v"})

    monkeypatch.setattr(vm, "backend", lambda kind: Backend)
    monkeypatch.setattr(vm, "start", lambda info, name, run: run)
    vm.save("app")
    assert vm.state_info("app")["parent"] == "clean"


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
    with pytest.raises(SystemExit):
        qemu.up("s", {}, display="big")
