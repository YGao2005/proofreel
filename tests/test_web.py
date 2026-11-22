import http.server
import threading
import json
import subprocess
import time

import pytest
from PIL import Image

from proofreel import Problem, cdp, chrome, cli, guest, recording, screen, vm

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


def test_open_returns_after_the_page_has_painted(page, tmp_path):
    (tmp_path / "slow.html").write_text("<h1>Slow page</h1><script>onload = () => setTimeout(() => { for (let t = Date.now(); Date.now() - t < 600;); })</script>")
    started, ended = page.open((tmp_path / "slow.html").as_uri())
    assert ended - started >= 0.5


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
    end = time.time() + 5
    while time.time() < end and not subprocess.run(["pgrep", "-f", "--", f"--user-data-dir={chrome.folder(vm.MACHINE)}"],
                                                   capture_output=True).returncode:
        time.sleep(0.1)
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


SITE = """<!doctype html><title>t</title><h1>Fetching</h1>
<script>
fetch('/ok?token=QUERYSECRET', {headers: {'X-Key': 'HEADERSECRET'}}).then(() => fetch('/broken'))
  .then(() => { document.title = 'done'; document.body.append('Fetched') })
</script>
"""


@pytest.fixture
def site():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            known = self.path.startswith(("/ok", "/favicon")) or self.path == "/"
            body = (SITE if self.path == "/" else "{}").encode()
            self.send_response(200 if known else 500)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_a_web_recording_measures_requests_and_vitals_with_no_flags(runs, site, monkeypatch):
    # WHY: the recorder is another process: it finds the run record through PROOFREEL_HOME.
    monkeypatch.setenv("PROOFREEL_HOME", str(runs))
    monkeypatch.setattr(vm, "CURRENT", runs / f"{vm.RUN}.json")
    monkeypatch.setattr(recording, "POINTER", runs / f"{vm.RUN}-session.json")
    vm.up("web")
    assert cli.command(["start", "web-net"]) is None
    cli.command(["open", site + "/"])
    cli.command(["wait-text", "Fetched", "10"])
    # WHY: a span reaches the file a moment after the page sees the answer.
    time.sleep(1)
    assert cli.command(["check", "metric", "net/*", "failed", "--below", "1"]) == 1
    cli.command(["stop"])
    vm.down()
    [folder] = (runs / "sessions").iterdir()
    status = json.loads((folder / "metrics" / "probes.json").read_text())
    assert {n: status[n]["status"] for n in ("network", "browser")} == {"network": "ok", "browser": "ok"}
    lines = [json.loads(line) for line in (folder / "metrics" / "network.jsonl").read_text().splitlines()]
    by_label = {line["label"]: line for line in lines if "favicon" not in line["label"]}
    assert set(by_label) == {"GET 127.0.0.1:" + site.rsplit(":", 1)[1] + p for p in ("/", "/ok", "/broken")}
    ok, broken = (by_label[next(k for k in by_label if k.endswith(p))] for p in ("/ok", "/broken"))
    assert ok["m"] == "net/127.0.0.1" and ok["ok"] is True and ok["n"]["status"] == 200 and ok["n"]["size"] > 0
    assert broken["ok"] is False and broken["n"]["status"] == 500
    assert {"connect", "wait", "receive"} <= set(ok["phases"]) or {"wait", "receive"} <= set(ok["phases"])
    assert "QUERYSECRET" not in (folder / "metrics" / "network.jsonl").read_text()
    assert "HEADERSECRET" not in (folder / "metrics" / "network.jsonl").read_text()
    assert any(json.loads(line)["m"] == "web/heap" for line in (folder / "metrics" / "browser.jsonl").read_text().splitlines())
    check = [json.loads(line) for line in (folder / "events.jsonl").read_text().splitlines() if '"check"' in line][-1]
    assert check["detail"] == "failed 1"


REDUCED = "matchMedia('(prefers-reduced-motion: reduce)').matches"


def asked(runs, screen_address, expression):
    with screen.connect(screen_address) as web:
        return web.call("Runtime.evaluate", expression=expression, returnByValue=True)["result"]["value"]


@pytest.mark.parametrize("options, held", [([], True), (["--full-motion"], False)])
def test_a_web_recording_holds_reduced_motion_unless_the_flow_asks_for_full_motion(runs, options, held):
    address = vm.up("web")["screen"]
    assert asked(runs, address, REDUCED) is False
    assert cli.command(["start", "motion", "--probe", "none", *options]) is None
    assert asked(runs, address, REDUCED) is held
    cli.command(["stop"])
    assert asked(runs, address, REDUCED) is False
    [folder] = (runs / "sessions").iterdir()
    assert json.loads((folder / "session.json").read_text())["meta"].get("motion") == ("reduced" if held else None)
    vm.down()


def test_full_motion_is_only_for_a_web_run(home):
    with pytest.raises(Problem, match="--full-motion is for a web run"):
        cli.command(["--vnc", "127.0.0.1::1", "start", "x", "--full-motion"])


def acme_server():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("acme_server", Path(__file__).parent.parent / "examples/acme-notes/server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, module


def test_a_check_for_data_that_an_earlier_run_saved_passes_on_a_broken_save_and_run_makes_it_fail(runs, tmp_path, monkeypatch):
    from pathlib import Path
    server, acme = acme_server()
    url = f"http://127.0.0.1:{server.server_port}"
    old = tmp_path / "old.flow"
    old.write_text("from web\nopen ${URL}/notes.html\nwait-text \"Your notes\" 20\nclick-text \"Title\"\ntype \"Trip plan\"\n"
                   "click-text \"Write a note\"\ntype \"Book the train on Friday\"\nclick-text \"Save note\"\n"
                   "wait-text \"Note saved\" 10\ncheck text \"Trip plan: Book the train on Friday\" 3\n")
    new = tmp_path / "new.flow"
    new.write_text(old.read_text().replace('"Trip plan"', '"Trip plan ${RUN}"').replace("Trip plan: Book", "Trip plan ${RUN}: Book"))
    acme.NOTES.append({"id": 9, "title": "Trip plan", "body": "Book the train on Friday"})
    monkeypatch.setenv("BROKEN", "save")
    try:
        vm.up("web")
        assert cli.run_flow(old, {"URL": url}) == 0
        vm.down()
        vm.up("web")
        assert cli.run_flow(new, {"URL": url}) == 1
        assert cli.load_flow(new, {"URL": url}).run != cli.load_flow(new, {"URL": url}).run
        assert cli.load_flow(new, {"URL": url, "RUN": "mine"}).run == "mine"
    finally:
        server.shutdown()


def test_a_browser_that_ends_at_start_says_how_it_ended(home, monkeypatch, tmp_path):
    fake = tmp_path / "fake-chrome"
    fake.write_text("#!/bin/sh\necho 'no display here'\nexit 3\n")
    fake.chmod(0o755)
    monkeypatch.setattr(chrome, "find_chrome", lambda: str(fake))
    with pytest.raises(Problem, match=r"Chrome did not start: it ended with code 3\. Its output: no display here"):
        vm.up("web")
