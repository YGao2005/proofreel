import http.server
import itertools
import json
import threading
import time

import pytest

from proofreel import Problem, cli, conditions, emulation, page, screen, suite, vm
from proofreel import chrome as runner

NAMES = itertools.count()
PAGE = b"<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'><title>t</title><h1>Hello</h1>"


@pytest.fixture
def runs(home, chrome_path):
    yield home
    vm.down()


@pytest.fixture
def site():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(PAGE)))
            self.end_headers()
            self.wfile.write(PAGE)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/"
    server.shutdown()


LOOK = ("[innerWidth, innerHeight, devicePixelRatio, 'ontouchstart' in window, navigator.userAgent.includes('iPhone'), "
        "matchMedia('(prefers-color-scheme: dark)').matches]")
FETCH = "fetch('/').then(r => r.status, e => 'failed').then(s => [s, Math.round(performance.now())])"


def recorded(address, site, condition, look):
    """What a page opened during a recording sees, and what a page opened after it stops sees."""
    cli.command(["start", f"c{next(NAMES)}", "--probe", "none", *(["--condition", condition] if condition else [])])
    with screen.connect(address) as web:
        web.open(site)
        during = web.call("Runtime.evaluate", expression=look, returnByValue=True, awaitPromise=True)["result"]["value"]
    cli.command(["stop"])
    with screen.connect(address) as web:
        web.open(site)
        return during, web.call("Runtime.evaluate", expression=look, returnByValue=True, awaitPromise=True)["result"]["value"]


def test_a_phone_run_sees_a_phone_and_a_portrait_video_and_leaves_the_page_as_it_was(runs, site):
    address = vm.up("web")["screen"]
    during, after = recorded(address, site, "phone", LOOK)
    assert during == [390, 844, 3, True, True, False]
    assert after[:2] == [1440, 900] and after[3:5] == [False, False]
    [folder] = (runs / "sessions").iterdir()
    assert (folder / "screen.txt").read_text().split() == ["390", "844"]
    info = json.loads((folder / "session.json").read_text())
    assert [c["name"] for c in info["conditions"]] == ["phone"] and info["meta"]["motion"] == "reduced"


def test_a_plain_run_is_light_and_the_dark_condition_makes_it_dark(runs, site):
    address = vm.up("web")["screen"]
    assert recorded(address, site, None, LOOK)[0][5] is False
    assert recorded(address, site, "dark", LOOK)[0][5] is True


def test_slow_network_and_offline_change_the_requests_of_the_page(runs, site):
    address = vm.up("web")["screen"]
    assert recorded(address, site, None, FETCH)[0][0] == 200
    slow = f"slow-network:profile=none,latency=700ms"
    during, _ = recorded(address, site, slow, FETCH)
    assert during[0] == 200 and during[1] >= 700
    assert recorded(address, site, "offline", "navigator.onLine")[0] is False
    assert recorded(address, site, None, FETCH)[0][0] == 200


def test_a_condition_for_the_web_is_checked_before_anything_starts(home):
    with pytest.raises(Problem, match="works on macos, and the VM is web"):
        conditions.record("no-microphone", {}, "web", recording=True)
    with pytest.raises(Problem, match="phone works on web, and the VM is linux"):
        conditions.record("phone", {}, "linux", recording=True)
    with pytest.raises(Problem, match="lasts one recording"):
        conditions.record("phone", {}, "web", recording=False)


def test_the_slow_network_profile_becomes_latency_and_bytes_a_second():
    pairs = emulation.commands(False, [conditions.record("slow-network", {}, "web", recording=True)])
    [network] = [set_[1] for set_, _ in pairs if set_[0] == "Network.emulateNetworkConditions"]
    assert (network["latency"], network["downloadThroughput"], network["offline"]) == (300.0, 125000.0, False)
    with pytest.raises(Problem, match="takes latency such as 300ms"):
        emulation.slow_network({"latency": "fast", "rate": "1mbit"})


def test_each_condition_runs_each_flow_once_for_each_condition_as_its_own_journey(home, tmp_path, monkeypatch, alive):
    (tmp_path / "a.flow").write_text("from web\nstart a --title 'A page'\ncheck cmd true\nstop\n")
    started = []

    def up(state, *args, **kwargs):
        vm.CURRENT.write_text(json.dumps({"id": state, "state": state, "os": "web", "conditions": []}))

    monkeypatch.setattr(vm, "up", up)
    monkeypatch.setattr(vm, "down", lambda: vm.CURRENT.unlink(missing_ok=True))
    monkeypatch.setattr(suite.vms, "state_info", lambda name: {"os": "web"})

    def execute(words):
        if words[0] == "start":
            started.append(words[2:])
        if words[0] == "stop":
            return None
        return 0

    out = tmp_path / "review"
    _, rows = suite.run([tmp_path / "a.flow"], lambda path: cli.load_flow(path, {}), cli.play, execute,
                        out=out, each_condition=["plain", "phone", "dark"])
    assert [name for _, name, _ in rows] == ["a", "a (phone)", "a (dark)"]
    assert [[w for w in words if not w.startswith("--meta=flow=")] for words in started] == [
        ["--title", "A page"], ["--title", "A page", "--condition=phone"], ["--title", "A page", "--condition=dark"]]
    with pytest.raises(Problem, match="works on macos"):
        suite.run([tmp_path / "a.flow"], lambda path: cli.load_flow(path, {}), cli.play, execute, out=out,
                  each_condition=["no-microphone"])
