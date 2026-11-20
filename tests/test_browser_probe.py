import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from proofreel import probes, redact

FOLDER = Path(probes.__file__).parent / "browser"
FIXTURE = Path(__file__).parent / "fixtures" / "browser-cdp.jsonl"


def load():
    spec = importlib.util.spec_from_file_location("browser_probe", FOLDER / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replay(since):
    """The recorded messages of a real run (Acme Notes opened, then Save clicked) through Browser, as the probe's
    loop feeds them. Returns (browser, lines, commands)."""
    browser, lines, commands = load().Browser(since), [], []
    for record in map(json.loads, FIXTURE.read_text().splitlines()):
        if "tick" in record:
            browser.tick()
        else:
            lines += browser.feed(record["message"], record["at"])
        commands += map(json.loads, browser.outbox)
        browser.outbox.clear()
    return browser, lines, commands


def test_recorded_messages_make_vitals_frames_user_timing_and_metrics():
    _, lines, commands = replay(since=0)
    by = {}
    for line in lines:
        by.setdefault(line["m"], []).append(line)
        assert probes.parse(json.dumps(line)) == line
    assert {"web/lcp", "web/cls", "web/inp", "web/interaction", "web/long-frame", "web/measure/save",
            "web/mark/app-start", "web/mark/save-start", "web/heap", "web/nodes", "web/layouts"} <= set(by)
    assert by["web/inp"][-1]["v"] == 312 and by["web/interaction"][-1]["d"] == 0.312
    assert by["web/lcp"][-1]["v"] > 1200 and by["web/cls"][-1]["v"] > 0.03
    frame = by["web/long-frame"][-1]
    assert frame["script"] == "BUTTON#save.onclick" and frame["d"] > 0.3
    save = by["web/measure/save"][0]
    assert save["d"] == 0.3 and abs(save["t"] - by["web/mark/save-start"][0]["t"] - 0.3) < 0.002
    assert save["t"] < frame["t"] < by["web/inp"][-1]["t"]
    assert all(line["label"] == "10.0.2.2:18431/" for line in lines)
    assert "SECRET" not in json.dumps(lines)
    pages = [c for c in commands if c["method"] == "Target.attachToTarget"]
    assert len(pages) == 1
    session = next(c["sessionId"] for c in commands if c["method"] == "Runtime.addBinding")
    assert {c["method"] for c in commands if c.get("sessionId") == session} == {
        "Performance.enable", "Runtime.addBinding", "Page.addScriptToEvaluateOnNewDocument", "Runtime.evaluate",
        "Performance.getMetrics"}


def test_entries_from_before_the_probe_started_are_not_kept():
    _, lines, _ = replay(since=json.loads(FIXTURE.read_text().splitlines()[0])["tick"])
    assert "web/mark/app-start" not in {line["m"] for line in lines}
    assert "web/inp" in {line["m"] for line in lines}


def test_only_a_shown_web_tab_is_read_and_a_new_document_starts_its_counts_again():
    browser = load().Browser(0)
    browser.feed({"method": "Target.attachedToTarget", "params": {
        "sessionId": "S", "targetInfo": {"targetId": "T", "type": "page", "url": "https://acme.test/notes?id=7"}}}, 1)
    browser.outbox.clear()
    browser.tick()
    assert browser.outbox == []
    shown = {"now": 10, "url": "https://acme.test/notes?id=7", "found": [{"k": "shown", "at": 10, "v": True}]}
    browser.feed({"method": "Runtime.bindingCalled", "sessionId": "S",
                  "params": {"name": "__proofreel", "payload": json.dumps(shown)}}, 2)
    browser.tick()
    assert [json.loads(c)["method"] for c in browser.outbox] == ["Performance.getMetrics"]
    for junk in ("x", "[]", json.dumps({"now": 1, "url": "https://acme.test/", "found": [{"k": "lcp"}]})):
        assert browser.feed({"method": "Runtime.bindingCalled", "sessionId": "S",
                             "params": {"name": "__proofreel", "payload": junk}}, 2) == []
    read = lambda at, layouts: browser.feed({"id": 9, "sessionId": "S", "result": {"metrics": [
        {"name": "Timestamp", "value": at}, {"name": "JSHeapUsedSize", "value": 2_500_000}, {"name": "Nodes", "value": 40},
        {"name": "LayoutCount", "value": layouts}, {"name": "RecalcStyleCount", "value": layouts}]}}, at)
    assert {line["m"] for line in read(3, 10)} == {"web/heap", "web/nodes"}
    assert {line["m"]: line["v"] for line in read(5, 14)}["web/layouts"] == 2.0
    assert {line["m"] for line in read(6, 1)} == {"web/heap", "web/nodes"}


def test_user_timing_names_past_the_limit_share_one_series():
    module = load()
    browser = module.Browser(0)
    found = [{"k": "mark", "at": 1, "name": f"step {n}"} for n in range(module.NAMES + 5)]
    lines = browser.entries({"shown": True}, {"now": 1, "url": "https://acme.test/", "found": found}, 1)
    series = {line["m"] for line in lines}
    assert len(series) == module.NAMES + 1 and "web/mark/other" in series
    assert lines[-1]["name"] == f"step {module.NAMES + 4}"


def test_without_websocket_client_or_a_tunnel_the_probe_says_why():
    no_module = subprocess.run([sys.executable, "-c", "import runpy, sys; sys.modules['websocket'] = None; "
                                f"runpy.run_path({str(FOLDER / 'run.py')!r}, run_name='__main__')"],
                               capture_output=True, text=True, env={"PROOFREEL_TUNNEL": "1"})
    assert "pip install websocket-client" in json.loads(no_module.stdout)["unavailable"]
    no_tunnel = subprocess.run([sys.executable, str(FOLDER / "run.py")], capture_output=True, text=True, env={})
    assert "run VM" in json.loads(no_tunnel.stdout)["unavailable"]


def test_a_url_label_keeps_only_host_and_path():
    assert redact.url_label("GET", "https://ann:pw@acme.test:8443/notes/7?token=SECRET#top") == "GET acme.test:8443/notes/:id"
    assert redact.url_label(None, "http://10.0.2.2:18431/?token=SECRET") == "10.0.2.2:18431/"
    assert redact.url_label(None, "file:///home/tester/a.html") == "file:/home/tester/a.html"


def test_a_probe_with_a_tunnel_gets_its_port_and_the_tunnel_ends_with_it(tmp_path, monkeypatch):
    (tmp_path / "metrics").mkdir()
    tunnel = subprocess.Popen(["sleep", "30"])
    given, real = {}, probes.process

    class Run(dict):
        def forward(self, port):
            given["guest"] = port
            return 4321, tunnel

    def process(record, folder, info, run, port=None):
        given["port"] = port
        return [sys.executable, "-c", "print('{\"ready\": true}')"], None

    monkeypatch.setattr(probes, "process", process)
    probe = probes.Probe({"name": "fake", "tunnel": 9222}, tmp_path, {}, Run(os="linux"))
    probe.process.wait()
    assert probe.stop()["status"] == "ok"
    assert given == {"guest": 9222, "port": 4321} and tunnel.poll() is not None
    assert real({"where": "host", "values": {}, "source": str(FOLDER)}, tmp_path, {}, None, 4321)[1][
        "PROOFREEL_TUNNEL"] == "4321"
