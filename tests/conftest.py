import os
import subprocess

import pytest

from proofreel import Problem, qemu, recording, vm
from proofreel import chrome as runner


@pytest.fixture
def alive(monkeypatch):
    """Every recorder counts as alive: a test that fakes a recording writes the pointer and no lock."""
    monkeypatch.setattr(recording, "recording", lambda folder: True)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fresh proofreel home for one test: states, the run record, sessions, and QEMU files live in tmp_path."""
    for module, name, path in ((vm, "HOME", ""), (vm, "STATES", "states"), (vm, "CURRENT", "run.json"),
                               (recording, "POINTER", "session.json"), (recording, "SESSIONS", "sessions"),
                               (qemu, "FOLDER", "qemu"), (runner, "FOLDER", "chrome"), (qemu, "FIRMWARE", "firmware.gz")):
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


@pytest.fixture(scope="session")
def chrome_path():
    """A Chrome for the browser runner. Without one the test skips, except in CI, where it fails."""
    try:
        return runner.find_chrome()
    except Problem:
        if os.environ.get("CI"):
            raise
        pytest.skip("no Chrome to launch")


@pytest.fixture(scope="session", autouse=True)
def idle_browsers(tmp_path_factory):
    """A Chrome that a killed pytest leaves ends itself after 2 minutes (idle.py). A Chrome that a test leaves
    running at the end of the session is a failure: each test stops what it starts. It is named, then ended."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("PROOFREEL_IDLE", "120")
        yield
    flag = f"--user-data-dir={tmp_path_factory.getbasetemp()}"
    left = subprocess.run(["pgrep", "-f", "--", flag], capture_output=True, text=True).stdout.split()
    if left:
        subprocess.run(["pkill", "-KILL", "-f", "--", flag], check=False)
        pytest.fail(f"A test left {len(left)} Chrome processes running (ended now). Stop Chrome in the test's teardown.")
