import os
import signal
import subprocess
import sys
import textwrap
import time

import pytest

from proofreel import Problem, chrome, vm


def running(pattern):
    return subprocess.run(["pgrep", "-f", "--", pattern], capture_output=True).returncode == 0


def gone(pattern, seconds):
    end = time.time() + seconds
    while running(pattern) and time.time() < end:
        time.sleep(0.2)
    return not running(pattern)


@pytest.fixture
def browser(home, chrome_path, monkeypatch):
    monkeypatch.setenv("PROOFREEL_IDLE", "3")
    yield home
    vm.down()


def test_an_idle_browser_ends_with_its_watchdog_and_the_next_command_says_why(browser):
    vm.up("web")
    flag = f"--user-data-dir={chrome.folder(vm.MACHINE)}"
    assert running(flag) and running(f"proofreel.idle {chrome.FOLDER}")
    assert gone(flag, 12) and gone(f"proofreel.idle {chrome.FOLDER}", 5)
    assert not chrome.folder(vm.MACHINE).exists()
    with pytest.raises(Problem, match=r"The browser stopped after 3 s with no proofreel command. Start it again"):
        vm.Run.current()


def test_a_command_within_the_idle_time_keeps_the_browser(browser):
    vm.up("web")
    for _ in range(5):
        time.sleep(1)
        vm.Run.current()
    assert running(f"--user-data-dir={chrome.folder(vm.MACHINE)}")
    vm.down()
    assert gone(f"--user-data-dir={chrome.folder(vm.MACHINE)}", 5) and gone(f"proofreel.idle {chrome.FOLDER}", 5)


def test_a_killed_pytest_leaves_no_chrome(tmp_path, chrome_path):
    (tmp_path / "test_up.py").write_text(textwrap.dedent("""
        import time
        from proofreel import vm

        def test_up():
            vm.up("web")
            time.sleep(60)
    """))
    env = {**os.environ, "PROOFREEL_HOME": str(tmp_path / "home"), "PROOFREEL_IDLE": "3"}
    child = subprocess.Popen([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tmp_path / "test_up.py")],
                             env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    flag = f"--user-data-dir={tmp_path / 'home' / 'chrome' / vm.MACHINE}"
    try:
        end = time.time() + 30
        while not running(flag) and time.time() < end:
            time.sleep(0.2)
        assert running(flag)
        child.send_signal(signal.SIGKILL)
        assert gone(flag, 15)
    finally:
        child.kill()
        subprocess.run(["pkill", "-KILL", "-f", "--", str(tmp_path / "home")], check=False)
