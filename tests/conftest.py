import pytest

from proofreel import qemu, recording, vm


@pytest.fixture
def alive(monkeypatch):
    """Every recorder counts as alive: a test that fakes a recording writes the pointer and no lock."""
    monkeypatch.setattr(recording, "recording", lambda folder: True)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fresh proofreel home for one test: states, the run record, sessions, and QEMU files live in tmp_path."""
    for module, name, path in ((vm, "HOME", ""), (vm, "STATES", "states"), (vm, "CURRENT", "run.json"),
                               (recording, "POINTER", "session.json"), (recording, "SESSIONS", "sessions"),
                               (qemu, "FOLDER", "qemu"), (qemu, "CUSTOM_FIRMWARE", "firmware/code.fd")):
        monkeypatch.setattr(module, name, tmp_path / path)
    return tmp_path
