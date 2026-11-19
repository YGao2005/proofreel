import pytest

from proofreel import cli, qemu, vm


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fresh proofreel home for one test: states, the run record, sessions, and QEMU files live in tmp_path."""
    for module, name, path in ((vm, "HOME", ""), (vm, "STATES", "states"), (vm, "CURRENT", "run.json"),
                               (cli, "ACTIVE", "session.json"), (cli, "SESSIONS", "sessions"),
                               (qemu, "FOLDER", "qemu"), (qemu, "CUSTOM_FIRMWARE", "firmware/code.fd")):
        monkeypatch.setattr(module, name, tmp_path / path)
    return tmp_path
