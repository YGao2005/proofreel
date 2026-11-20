import importlib.util
import io
import json
import shutil
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from proofreel import Problem, page, plugins, probes, redact, vm

tflow = pytest.importorskip("mitmproxy.test.tflow")
http = pytest.importorskip("mitmproxy.http")

NETWORK = Path(probes.__file__).parent / "network"
SECRETS = ("SECRET123", "QUERYSECRET", "HEADERSECRET", "BODYSECRET", "PATHSECRET4f9a8b7c6d5e", "lee.planted@acme.test",
           "hunter2pw")


@pytest.fixture
def addon(monkeypatch):
    monkeypatch.setenv("PROOFREEL_REDACT", redact.__file__)
    spec = importlib.util.spec_from_file_location("network_addon", NETWORK / "addon.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def spans(addon, flows, guest="10.0.2.15"):
    out = io.StringIO()
    hooks = addon.Spans(guest, "10.0.2.2", "127.0.0.1", out)
    for flow in flows:
        hooks.response(flow) if flow.response else hooks.error(flow)
    return [json.loads(line) for line in out.getvalue().splitlines()]


def made(url, status=200, start=100.0, server=None, body=b"", headers=(), answer=b"{}"):
    """A finished flow: the request at start, the server answers 0.8 s later."""
    flow = tflow.tflow(resp=status is not None, err=status is None)
    flow.request = http.Request.make("POST" if body else "GET", url, body, {"Host": urlsplit(url).netloc, **dict(headers)})
    flow.request.timestamp_start, flow.request.timestamp_end = start, start + 0.01
    if server:
        flow.server_conn = server
    else:
        flow.server_conn.timestamp_start, flow.server_conn.timestamp_tcp_setup = start + 0.01, start + 0.03
        flow.server_conn.timestamp_tls_setup = start + 0.07
    if status is not None:
        flow.response = http.Response.make(status, answer, {"Set-Cookie": "session=HEADERSECRET"})
        flow.response.timestamp_start, flow.response.timestamp_end = start + 0.8, start + 0.85
    return flow


def test_a_request_is_a_span_with_phases_and_a_redacted_label(addon):
    first = made("https://api.acme.test/items/42?token=SECRET123", answer=b"x" * 300)
    again = made("https://api.acme.test/report", start=101.0, server=first.server_conn)
    line, reused = spans(addon, [first, again])
    assert line["m"] == "net/api.acme.test" and line["label"] == "GET api.acme.test/items/:id" and line["ok"] is True
    assert line["t"] == 100.85 and line["d"] == 0.85
    assert line["phases"] == {"connect": 0.02, "tls": 0.04, "wait": 0.73, "receive": 0.05}
    assert line["n"] == {"status": 200, "size": 300}
    assert "connect" not in reused["phases"] and reused["d"] == 0.85 and reused["phases"]["wait"] == 0.79


def test_a_server_error_and_a_lost_connection_are_failed_spans(addon):
    error, lost = spans(addon, [made("http://10.0.2.2:8123/sync", status=500), made("http://down.test/x", status=None)])
    assert error["ok"] is False and error["n"]["status"] == 500 and error["m"] == "net/10.0.2.2"
    assert lost["ok"] is False and "error" in lost["n"] and lost["label"] == "GET down.test/x"


def test_only_the_guest_may_use_the_proxy(addon):
    hooks = addon.Spans("10.0.2.15", "10.0.2.2", "127.0.0.1", io.StringIO())
    guest, other = tflow.tclient_conn(), tflow.tclient_conn()
    guest.peername, other.peername = ("10.0.2.15", 5000), ("192.168.1.9", 5000)
    hooks.client_connected(guest)
    hooks.client_connected(other)
    assert guest.error is None and other.error


def test_a_request_to_the_host_as_the_guest_sees_it_goes_to_the_bound_address(addon):
    hooks = addon.Spans("127.0.0.1", "10.0.2.2", "127.0.0.1", io.StringIO())
    flow = made("http://10.0.2.2:8123/slow")
    hooks.requestheaders(flow)
    assert flow.request.host == "127.0.0.1" and flow.request.pretty_host == "10.0.2.2"
    same = addon.Spans("192.168.64.5", "192.168.64.1", "192.168.64.1", io.StringIO())
    flow = made("http://192.168.64.1:8123/slow")
    same.requestheaders(flow)
    assert flow.request.host == "192.168.64.1"


def test_a_span_line_keeps_the_protocol_limits(addon):
    huge = made("https://acme.test/" + "/".join(["part"] * 5000) + "?q=" + "x" * 50000)
    line = spans(addon, [huge])[0]
    raw = json.dumps(line)
    assert len(raw) < probes.LINE and probes.parse(raw) == line and len(line["label"]) <= 4 + redact.LONGEST


def test_redact_keeps_the_path_shape_and_drops_what_identifies_a_person():
    assert redact.url_label("GET", "https://u:pw@api.acme.test:8443/users/42/reset/abcDEF0123456789xyz?token=x#top") \
        == "GET api.acme.test:8443/users/:id/reset/:id"
    assert redact.url_label("POST", "http://h/users/sam%40example.com/v1/profile;jsessionid=abc") \
        == "POST h/users/:email/v1/profile"
    assert redact.url_label("", "https://acme.test") == "acme.test/"
    assert redact.text("failed at http://x/y?token=SECRET123 for sam@example.com, card 4111111111111111") \
        == "failed at http://x/y for :email, card :id"


def test_planted_secrets_reach_no_session_or_published_file(addon, tmp_path):
    from proofreel.demo import demo
    session = tmp_path / "s"
    demo(session)
    flows = [made("https://api.acme.test/items?token=SECRET123&key=QUERYSECRET",
                  headers={"Authorization": "Bearer HEADERSECRET", "Cookie": "pw=hunter2pw"}),
             made("https://api.acme.test/reset/PATHSECRET4f9a8b7c6d5e/lee.planted@acme.test", body=b"password=BODYSECRET"),
             made("http://user:hunter2pw@10.0.2.2:8123/sync?SECRET123", status=500),
             made("http://down.test/x?token=SECRET123", status=None)]
    lines = spans(addon, flows)
    (session / "metrics" / "network.jsonl").write_text("".join(json.dumps({**line, "a": line.get("t", 1)}) + "\n"
                                                               for line in lines))
    info = json.loads((session / "session.json").read_text())
    info["probes"].append({"name": "network", "version": "1", "where": "host", "values": {}, "tracks": {}})
    (session / "session.json").write_text(json.dumps(info))
    from proofreel.render import render
    render(session, width=320)
    page.publish(session, tmp_path / "review")
    files = [f for f in tmp_path.rglob("*") if f.is_file()]
    assert any(f.name == "runs.json" for f in files) and len(lines) == 4
    for f in files:
        data = f.read_bytes()
        assert not [s for s in SECRETS if s.encode() in data], f


def test_a_setup_probe_needs_start_and_stop_and_a_run_vm(tmp_path):
    folder = tmp_path / "network"
    shutil.copytree(NETWORK, folder)
    (folder / "stop.sh").unlink()
    with pytest.raises(ValueError, match="stop.sh"):
        plugins.manifest("probe", folder)
    with pytest.raises(Problem, match="run VM"):
        probes.select(["none", "network"], None)


def test_a_missing_extra_makes_the_probe_unavailable_and_it_never_starts(home, monkeypatch, tmp_path):
    monkeypatch.setattr(probes, "installed", lambda package: False)
    run = vm.Run({"backend": "qemu", "os": "linux", "id": "x"})
    record = probes.select(["none", "network"], run)[0]
    assert record["port"] and "pip install mitmproxy" in record["unavailable"]
    (tmp_path / "session.json").write_text(json.dumps({"probes": [record]}))
    assert probes.launch(tmp_path) == []
    status = json.loads((tmp_path / "metrics" / "probes.json").read_text())["network"]
    assert status["status"] == "unavailable"
    monkeypatch.setattr(plugins, "script", lambda *a, **k: pytest.fail("no guest step for an unavailable probe"))
    probes.begin([record], run)


def pending():
    return json.loads(vm.CURRENT.read_text()).get("pending", [])


def test_a_reset_is_pending_before_its_start_and_a_failed_start_is_undone(home, monkeypatch):
    vm.CURRENT.write_text(json.dumps({"backend": "qemu", "os": "linux", "id": "x"}))
    run = vm.Run.current()
    steps = []

    def script(run, kind, name, step, values, timeout=300):
        steps.append((name, step, [r["name"] for r in pending()]))
        return (1, "no sudo") if (name, step) == ("b", "start") else (0, "")

    monkeypatch.setattr(plugins, "script", script)
    records = [{"name": n, "values": {}, "setup": True, "port": 9} for n in ("a", "b")]
    with pytest.raises(Problem, match="Probe b: its start in the run VM failed: no sudo"):
        probes.begin(records, run)
    assert steps == [("a", "start", ["a"]), ("b", "start", ["a", "b"]), ("b", "stop", ["a", "b"]),
                     ("a", "stop", ["a", "b"])]
    assert pending() == [] and plugins.undo(run) == []


def test_an_extra_is_a_pip_package_not_a_command():
    assert probes.installed("pluggy") and not probes.installed("no-such-package-proofreel")
