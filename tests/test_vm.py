import gzip
import json
from pathlib import Path

import pytest

from proofreel import Problem, guest, qemu, tart, vm


def test_states_tree_survives_a_parent_cycle(home, capsys):
    vm.STATES.mkdir()
    for name, parent in (("a", "a"), ("b", "a"), ("c", "d"), ("d", "c"), ("e", "gone")):
        (vm.STATES / f"{name}.json").write_text(json.dumps({"name": name, "parent": parent, "created": "x"}))
    vm.states()
    assert capsys.readouterr().out.split("\n")[:5] == ["a  x", "  b  x", "c  x", "d  x", "e  x"]


def test_saving_over_the_run_state_keeps_its_parent(home, tmp_path, monkeypatch):
    vm.write_state("app", parent="clean", user="u", password="p", warm=False, backend="qemu", os="linux")
    (tmp_path / "run.json").write_text(json.dumps({"id": "r1", "state": "app", "backend": "qemu", "os": "linux",
                                                   "user": "u", "password": "p", "conditions": []}))

    class Backend:
        save = staticmethod(lambda name, run, warm: {"memory": 4096, "cpu": 4})
        resume = staticmethod(lambda name, run, warm: {"vm": "r", "ip": "127.0.0.1", "screen": "v"})

    monkeypatch.setattr(vm, "backend", lambda kind: Backend)
    monkeypatch.setattr(vm, "start", lambda info, name, fields: fields)
    vm.save("app")
    assert vm.state_info("app")["parent"] == "clean"


def test_a_state_must_say_its_backend_and_system(home):
    vm.write_state("old", parent="x", user="u", password="p")
    with pytest.raises(Problem, match="does not say its backend or os"):
        vm.state_info("old")


@pytest.mark.parametrize("system, cleaned", [("windows", True), ("linux", False), ("macos", False)])
def test_only_windows_forgets_its_screen_size_before_a_cold_save(system, cleaned, monkeypatch):
    commands = []
    monkeypatch.setattr(vm.Run, "ssh", lambda self, command, **_: commands.append(command))
    guest.of({"os": system}).before_save(vm.Run({"id": "r1"}))
    assert bool(commands) == cleaned and all("GraphicsDrivers" in c for c in commands)


def test_qemu_display_comes_from_up_then_the_state_then_the_default(home, monkeypatch):
    monkeypatch.setattr(qemu, "clone", lambda source, target: None)
    monkeypatch.setattr(qemu, "boot", lambda machine, memory_file=None, extra=(): machine["display"])
    assert qemu.up("s", {}) == "1440x900"
    assert qemu.up("s", {"machine": {"display": "1280x800"}}) == "1280x800"
    assert qemu.up("s", {"machine": {"display": "1280x800"}}, display="1920x1080") == "1920x1080"
    assert qemu.up("s", {"warm": True, "machine": {"display": "1280x800"}}, display="1920x1080") == "1280x800"
    with pytest.raises(Problem):
        qemu.up("s", {}, display="big")


def test_the_firmware_is_unpacked_once_into_home(home, monkeypatch):
    qemu.FIRMWARE.write_bytes(gzip.compress(b"uefi"))
    monkeypatch.setattr(qemu, "HOME", home)
    monkeypatch.setattr(qemu, "need_qemu", lambda: "/opt/q/bin/qemu-system-aarch64")
    code, variables = qemu.firmware()
    assert code.read_bytes() == b"uefi" and code.parent == home / "firmware"
    assert variables == Path("/opt/q/share/qemu/edk2-arm-vars.fd")
    code.write_bytes(b"kept")
    assert qemu.firmware()[0].read_bytes() == b"kept"
    qemu.FIRMWARE.write_bytes(gzip.compress(b"newer"))
    assert qemu.firmware()[0].read_bytes() == b"newer"


def test_the_shipped_firmware_is_a_64_mb_pflash_image():
    assert len(gzip.decompress(qemu.FIRMWARE.read_bytes())) == 64 * 1024 * 1024


def test_the_guest_password_never_goes_to_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(vm, "HOME", tmp_path)
    env = vm.askpass("s3cret")
    assert env["PROOFREEL_GUEST_PASSWORD"] == "s3cret"
    assert "s3cret" not in (tmp_path / "askpass.sh").read_text()
    import subprocess
    assert subprocess.run([env["SSH_ASKPASS"]], env=env, capture_output=True, text=True).stdout == "s3cret\n"
    assert vm.askpass("other")["SSH_ASKPASS"] == env["SSH_ASKPASS"]


def test_a_run_vm_never_has_the_name_of_a_state():
    assert "." in vm.MACHINE
    for name in ("run", "pr-run", "a"):
        assert tart.PREFIX + vm.check_name(name) != vm.MACHINE
    for bad in ("a.vm", "", "../x", "a b"):
        with pytest.raises(Problem, match="letters, digits"):
            vm.check_name(bad)


def test_every_command_shares_one_ssh_connection_for_each_boot(home, monkeypatch):
    calls = []
    monkeypatch.setattr(vm.subprocess, "run", lambda args, **_: calls.append(args))
    run = vm.Run({"id": "abc123", "os": "linux", "user": "u", "ip": "10.0.0.2", "password": "p"})
    run.ssh("true")
    assert calls[0][-3:] == ["ControlPersist=600", "-fN", "u@10.0.0.2"]
    assert calls[1][-4:] == ["-o", "ControlMaster=no", "u@10.0.0.2", "true"]
    assert all(f"ControlPath={run._socket}" in args for args in calls)


def warm_run(tmp_path, monkeypatch, restore):
    vm.write_state("base", user="u", password="p", warm=False, backend="tart", os="macos")
    (tmp_path / "run.json").write_text(json.dumps({"id": "r1", "state": "base", "backend": "tart", "os": "macos",
                                                   "user": "u", "password": "p", "conditions": []}))
    dropped = []

    class Backend:
        save = staticmethod(lambda name, run, warm: None)
        resume = staticmethod(restore)
        drop = staticmethod(dropped.append)

    monkeypatch.setattr(vm, "backend", lambda kind: Backend)
    monkeypatch.setattr(vm, "start", lambda info, name, fields: fields)
    return dropped


def test_a_warm_save_in_a_sandbox_is_refused_before_anything_changes(home, tmp_path, monkeypatch):
    dropped = warm_run(tmp_path, monkeypatch, lambda name, run, warm: {})
    monkeypatch.setattr(vm, "sandboxed", lambda: True)
    with pytest.raises(Problem, match="outside the sandbox"):
        vm.save("app", warm=True)
    assert not (vm.STATES / "app.json").exists() and dropped == []


def test_a_warm_state_that_does_not_restore_is_deleted(home, tmp_path, monkeypatch):
    def resume(name, run, warm):
        raise Problem("Tart printed no VNC address.")
    dropped = warm_run(tmp_path, monkeypatch, resume)
    monkeypatch.setattr(vm, "sandboxed", lambda: False)
    with pytest.raises(Problem, match="did not restore, so it was deleted"):
        vm.save("app", warm=True)
    assert dropped == ["app"] and not (vm.STATES / "app.json").exists()


def test_the_qmp_socket_path_fits_a_unix_socket_in_a_deep_home(monkeypatch, tmp_path):
    monkeypatch.setattr(qemu, "FOLDER", tmp_path / ("deep" * 30))
    assert len(str(qemu.qmp_socket())) < 104
