import json
import subprocess
import time

import pytest
from PIL import Image

from proofreel import Problem, cdp, chrome, cli, guest, screen, vm

PAGE = """<!doctype html><title>t</title>
<h1>Your notes</h1>
<input id=q placeholder="Search notes">
<button onclick="out.textContent='Saved'">Save note</button>
<p id=out></p>
<script>q.onkeydown = e => { if (e.key === 'Enter') out.textContent = 'Entered ' + q.value }</script>
<p style="display:none">Hidden words</p>
<p style="margin-top:3000px">Far below</p>
<div style="position:fixed;inset:0;top:300px;background:white"><p>Covers the page</p></div>
"""


@pytest.fixture(scope="module")
def browser(chrome_path, tmp_path_factory):
    """One headless Chrome for the module, on a throwaway profile."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(chrome, "FOLDER", tmp_path_factory.mktemp("chrome"))
        record = chrome.up("web", dict(vm.WEB))
        yield record
        chrome.stop()


@pytest.fixture
def runs(home, chrome_path):
    """A proofreel home for a test that starts run browsers; any still running at the end is stopped."""
    yield home
    vm.down()


@pytest.fixture
def page(browser, tmp_path):
    (tmp_path / "page.html").write_text(PAGE)
    with screen.connect(browser["screen"]) as web:
        web.open((tmp_path / "page.html").as_uri())
        yield web


def words(web):
    return [line["text"] for line in web.lines()]


def test_lines_have_the_shape_of_ocr_and_only_what_a_person_sees(page):
    found = page.lines()
    title = screen.matches(found, "Your notes")[0]
    assert set(title) == {"text", "x", "y", "w", "h", "words"} and set(title["words"][0]) == {"text", "x", "y", "w", "h"}
    assert 0 <= title["x"] < 1440 and 0 <= title["y"] < 900 and 20 < title["h"] < 80
    assert [w["text"] for w in title["words"]] == ["Your", "notes"]
    assert screen.matches(found, "Search notes"), "an input placeholder is on the screen"
    assert not screen.matches(found, "Hidden words") and not screen.matches(found, "Far below")
    assert screen.matches(found, "Covers the page")
    assert [line["y"] for line in found] == sorted(line["y"] for line in found)


def test_click_text_finds_a_button_and_the_page_changes(page):
    button = screen.matches(page.lines(), "Save note")[0]
    assert "Saved" not in words(page)
    page.click(*screen.center(button))
    assert screen.wait_for(page, "Saved", 3)


def test_typing_goes_into_the_focused_input_and_keys_edit_it(page):
    page.click(*screen.center(screen.matches(page.lines(), "Search notes")[0]))
    page.type("Trip plan")
    assert "Trip plan" in words(page)
    page.key("ctrl-a")
    page.type("é")
    page.key("enter")
    assert screen.wait_for(page, "Entered é", 3)


def test_capture_writes_a_jpeg_of_the_viewport(page, tmp_path):
    page.capture(tmp_path / "shot.jpg")
    with Image.open(tmp_path / "shot.jpg") as image:
        assert (image.format, image.size) == ("JPEG", (1440, 900))
    assert page.size() == (1440, 900)


def test_open_waits_for_the_page_and_a_dead_address_is_a_problem(page, tmp_path):
    (tmp_path / "next.html").write_text("<h1>Second page</h1>")
    page.open((tmp_path / "next.html").as_uri())
    assert "Second page" in words(page)
    with pytest.raises(Problem, match="could not open"):
        page.open("http://127.0.0.1:1/")


def test_a_key_that_does_not_exist_is_a_problem():
    with pytest.raises(Problem, match="Unknown key 'nope'"):
        cdp.keystroke("nope")
    assert cdp.keystroke("command-a")[:2] == (4, "a")


def test_a_saved_web_state_keeps_the_profile_and_drop_removes_it(runs, tmp_path):
    (tmp_path / "page.html").write_text(PAGE)
    first = vm.up("web")
    with screen.connect(first["screen"]) as web:
        web.open((tmp_path / "page.html").as_uri())
        web.call("Runtime.evaluate", expression="localStorage.setItem('user', 'guest')")
    vm.save("signed-in")
    print("DEBUG", sorted(str(p.relative_to(chrome.folder("signed-in"))) for p in chrome.folder("signed-in").rglob("*") if "Storage" in str(p) or "Local" in str(p)), flush=True)
    assert vm.state_info("signed-in")["parent"] == "web" and vm.state_info("signed-in")["os"] == "web"
    second = vm.up("signed-in")
    with screen.connect(second["screen"]) as web:
        web.open((tmp_path / "page.html").as_uri())
        assert web.call("Runtime.evaluate", expression="localStorage.getItem('user')", returnByValue=True)["result"] \
            .get("value") == "guest"
    vm.down()
    assert not chrome.folder(vm.MACHINE).exists() and chrome.exists("signed-in")
    vm.drop("signed-in")
    assert not chrome.exists("signed-in")
    assert subprocess.run(["pgrep", "-f", "--", f"--user-data-dir={chrome.folder(vm.MACHINE)}"],
                          capture_output=True).returncode == 1


def test_a_recording_of_the_web_state_makes_a_video_and_a_page(runs, tmp_path):
    (tmp_path / "page.html").write_text(PAGE)
    vm.up("web")
    assert cli.command(["start", "web-run", "--probe", "none"]) is None
    cli.command(["open", (tmp_path / "page.html").as_uri()])
    cli.command(["wait-text", "Your notes", "5"])
    cli.command(["click-text", "Save note"])
    assert cli.command(["check", "text", "Saved", "3"]) == 0
    time.sleep(0.5)
    cli.command(["stop"])
    vm.down()
    [folder] = (runs / "sessions").iterdir()
    assert (folder / "session.mp4").exists() and (folder / "index.html").exists()
    kinds = [json.loads(line)["kind"] for line in (folder / "events.jsonl").read_text().splitlines()]
    assert kinds[:2] == ["open", "wait"] and "click" in kinds
    assert (folder / "screen.txt").read_text().split() == ["1440", "900"]
    assert "Traceback" not in (folder / "recorder.log").read_text()


def test_the_built_in_state_needs_no_file_and_cannot_be_saved_over(home):
    assert vm.state_info("web")["backend"] == "chrome" and vm.state_info("web")["os"] == "web"
    with pytest.raises(Problem, match="built-in"):
        vm.save("web")


def test_a_browser_run_has_no_shell_and_says_to_use_check_cmd(home):
    run = vm.Run({"id": "r", "os": "web", "backend": "chrome", "state": "web", "user": "", "password": "",
                  "conditions": []})
    for call in (lambda: run.ssh("ls"), lambda: run.upload("a", "b"), lambda: run.guest.running(run, "x")):
        with pytest.raises(Problem, match="no shell.*check cmd"):
            call()
    assert cli.run_check(cli.parse(["check", "sh", "ls"]), None, run) == 1


@pytest.mark.parametrize("system, command", [("linux", "browse 'http://h/a b'"), ("macos", "open 'http://h/a b'"),
                                             ("windows", 'start "" "http://h/a b"')])
def test_open_uses_each_guests_own_way_to_show_a_page(system, command):
    sent = []
    run = type("Run", (), {"ssh": lambda self, c, **_: sent.append(c) or subprocess.CompletedProcess(c, 0)})()
    guest.of({"os": system}).open(run, None, "http://h/a b")
    assert sent == [command]


def test_vm_states_lists_the_built_in_web_state_once_a_saved_state_comes_from_it(home, capsys):
    vm.write_state("signed-in", parent="web", backend="chrome", os="web", user="", password="", warm=False)
    vm.states()
    first, second = capsys.readouterr().out.splitlines()[:2]
    assert first.startswith("web  built in") and second.startswith("  signed-in") and second.endswith("[web]")


def test_words_with_no_gap_between_them_are_one_word_as_on_the_screen(page, tmp_path):
    (tmp_path / "inline.html").write_text("<p><b>Trip plan</b>: Book the train</p>")
    page.open((tmp_path / "inline.html").as_uri())
    assert words(page) == ["Trip plan: Book the train"]
    assert [w["text"] for w in page.lines()[0]["words"]] == ["Trip", "plan:", "Book", "the", "train"]
