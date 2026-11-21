import os

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
                               (qemu, "FOLDER", "qemu"), (qemu, "FIRMWARE", "firmware.gz")):
        monkeypatch.setattr(module, name, tmp_path / path)
    return tmp_path


@pytest.fixture
def chrome():
    """A Google Chrome launched by Playwright. Without Playwright or Chrome the test skips, except in CI, where it fails."""
    if os.environ.get("CI"):
        from playwright.sync_api import sync_playwright
    else:
        sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except Exception:
            if os.environ.get("CI"):
                raise
            pytest.skip("no Chrome to launch")
        yield browser
        browser.close()
