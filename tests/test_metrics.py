import json
from pathlib import Path
import sys
import time

import pytest

from proofreel import Problem, cli, flow, metrics, probes
from proofreel.motion import Clock


def folder_with(tmp_path, lines, probe="p", tracks=None):
    (tmp_path / "metrics").mkdir(exist_ok=True)
    (tmp_path / "metrics" / f"{probe}.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))
    (tmp_path / "session.json").write_text(json.dumps({"probes": [{"name": probe, "tracks": tracks or {}}]}))
    return tmp_path


def test_a_line_is_a_measure_or_a_control_line_or_nothing():
    assert probes.parse('{"m": "cpu/app", "v": 4}') == {"m": "cpu/app", "v": 4}
    assert probes.parse('{"ready": true}') == {"ready": True}
    for bad in ('not json', '[1]', '{"v": 1}', '{"m": "", "v": 1}', '{"m": "x", "v": NaN}', '{"m": "x", "v": true}',
                '{"m": "x", "d": "1"}', '{"m": "x", "t": Infinity}'):
        assert probes.parse(bad) is None, bad


def test_the_recorder_keeps_good_lines_and_counts_each_kind_of_dropped_one(tmp_path, monkeypatch):
    script = (
        "import json\n"
        "print(json.dumps({'ready': True}))\n"
        "print('x' * 20000)\n"
        "print('{bad')\n"
        "for n in range(70): print(json.dumps({'m': f's/{n}', 'v': n}))\n"
        "for n in range(300): print(json.dumps({'m': 's/0', 'v': n}))\n"
        "print(json.dumps({'unavailable': 'no camera'}))\n")
    monkeypatch.setattr(probes, "process", lambda *_: ([sys.executable, "-c", script], None))
    (tmp_path / "metrics").mkdir()
    probe = probes.Probe({"name": "fake"}, tmp_path, {}, None)
    probe.process.wait()
    status = probe.stop()
    assert status["status"] == "unavailable" and status["note"] == "no camera"
    assert status["size"] == 1 and status["bad"] == 1 and status["series"] == 6
    assert status["kept"] + status["rate"] + status["series"] == 370 and status["kept"] <= 2 * probes.RATE
    kept = [json.loads(line) for line in (tmp_path / "metrics" / "fake.jsonl").read_text().splitlines()]
    assert len({line["m"] for line in kept}) == probes.SERIES and all("a" in line for line in kept)


def test_a_probe_clock_goes_onto_the_host_clock_by_its_smallest_delay(tmp_path):
    lines = [{"m": "x", "v": 1, "t": t, "a": 1000 + t + delay} for t, delay in ((0, 0.05), (1, 0.9), (2, 0.04), (3, 2.5))]
    found = metrics.load(folder_with(tmp_path, lines))
    assert [round(x.t, 3) for x in found.measures] == [1000.04, 1001.04, 1002.04, 1003.04]


def test_stats_over_a_series_glob_and_a_window(tmp_path):
    lines = [{"m": "cpu/a", "v": v, "a": 100 + n} for n, v in enumerate((10, 20, 30, 40))]
    lines += [{"m": "cpu/b", "v": 90, "a": 104}, {"m": "net/x", "d": 0.5, "ok": False, "a": 104}]
    found = metrics.load(folder_with(tmp_path, lines))
    assert found.stat("cpu/a", "mean") == 25 and found.stat("cpu/a", "p50") == 25 and found.stat("cpu/*", "max") == 90
    assert found.stat("cpu/a", "mean", since=102) == 35 and found.stat("cpu/a", "last") == 40
    assert found.stat("net/*", "failed") == 1 and found.stat("net/*", "count") == 1
    assert found.stat("gpu/*", "mean") is None and found.stat("gpu/*", "count") == 0
    with pytest.raises(Problem, match="Unknown stat"):
        found.stat("cpu/a", "p42")


def test_a_budget_passes_fails_or_cannot_run_without_data(tmp_path):
    now = time.time()
    folder = folder_with(tmp_path, [{"m": "host/cpu", "v": v, "a": now - 3 + n} for n, v in enumerate((20, 30, 95, 40))],
                         tracks={"host/cpu": {"unit": "%"}})
    ok, label, detail, fields = metrics.check(folder, "host/cpu", "max", below=80, wait=0)
    assert not ok and label == "host/cpu max below 80 in the run" and detail == "max 95%"
    assert fields == {"budget": {"glob": "host/cpu", "stat": "max", "below": 80, "above": None}}
    assert metrics.check(folder, "host/cpu", "max", below=80, since=now - 0.5, window="the last 0.5 s", wait=0)[0]
    assert metrics.check(folder, "host/*", "mean", above=10, wait=0)[0]
    with pytest.raises(Problem, match="No gpu/\\* data in the run. Series: host/cpu"):
        metrics.check(folder, "gpu/*", "max", below=1, wait=0)


def test_the_summary_says_what_failed_then_one_line_for_each_series(tmp_path):
    lines = [{"m": "host/cpu", "v": v, "a": n} for n, v in enumerate((10, 30))] + [{"m": "net/api", "d": 0.2, "ok": False, "a": 3}]
    folder = folder_with(tmp_path, lines, tracks={"host/cpu": {"label": "Host CPU", "unit": "%"}})
    (folder / "metrics" / "probes.json").write_text(json.dumps({"p": {"status": "ok"}, "gpu": {"status": "unavailable", "note": "no GPU"}}))
    assert metrics.load(folder).summary() == [
        "Probe gpu unavailable: no GPU",
        "Host CPU: mean 20%, p95 29%, max 30%",
        "net/api: 1 spans, p50 0.2 s, p95 0.2 s, max 0.2 s, 1 failed",
    ]


def test_host_load_is_on_by_default_and_none_turns_defaults_off():
    assert [p["name"] for p in probes.select([], None)] == ["host-load"]
    assert probes.select(["none"], None) == []
    record = probes.select(["none", "host-load"], {"os": "linux"})[0]
    assert record["where"] == "host" and "host/cpu" in record["tracks"]
    with pytest.raises(Problem, match="No probe 'gpu'"):
        probes.select(["gpu"], None)


def test_a_flow_probe_line_goes_to_its_start_and_a_bad_budget_stops_the_flow_first(tmp_path):
    good = tmp_path / "good.flow"
    good.write_text("probe host-load\nstart x\ncheck metric host/cpu p95 --below 80\n")
    assert flow.load(good, {}, cli.parse).probes == ["host-load"]
    bad = tmp_path / "bad.flow"
    bad.write_text("start x\ncheck metric host/cpu p96 --below 80\n")
    with pytest.raises(Problem, match="bad.flow:2: .*A stat is one of"):
        flow.load(bad, {}, cli.parse)
    bad.write_text("start x\ncheck metric host/cpu p95\n")
    with pytest.raises(Problem, match="bad.flow:2: check metric takes one of"):
        flow.load(bad, {}, cli.parse)


def an_hour(spike_at=2000.0):
    """A made-up 1-hour session: 1 Hz samples of 6 series with one spike, many clicks, requests with phases and a
    secret in the URL, and marks. The clock plays 100 s to 3500 s at 8x."""
    start, ms = 1_800_000_000.0, []
    for n in range(3600):
        for k, m in enumerate(("host/cpu", "host/vm-cpu", "host/other-cpu", "host/load", "cpu/app", "mem/app")):
            v = 99.0 if m == "host/cpu" and n == spike_at else 10.0 + k + (n % 7)
            ms.append(metrics.Measure("p", m, start + n, start + n, v, None, None))
    for n in range(5000):
        ms.append(metrics.Measure("input", "input/click", start + n * 0.7 + 0.2, 0, None, 0.05 + (n % 9) / 100, n % 500 != 7,
                                  {"label": f'click "Button {n}"'}))
        ms.append(metrics.Measure("network", "net/GET api.acme.test", start + n * 0.7 + 0.5, 0, None, 0.1 + (n % 13) / 10,
                                  n % 400 != 3, {"label": f"GET https://api.acme.test/notes/{n}?token=SECRET",
                                                 "phases": {"connect": 0.01, "wait": 0.08, "receive": 0.01}}))
    ms += [metrics.Measure("app", "app/frame", start + n * 1.1, 0, None, None, None) for n in range(3000)]
    clock = Clock([[0.0, 0.0], [100.0, 100.0], [3500.0, 525.0], [3600.0, 625.0]])
    return metrics.Metrics(ms, {"host/cpu": {"label": "Host CPU", "unit": "%", "max": 100}}, {"p": {"status": "ok"}}), start, clock


def test_the_page_metrics_of_an_hour_fit_in_200_kb_and_keep_failures_and_no_secret():
    found, start, clock = an_hour()
    data = found.page(start, 3600, clock.video)
    text = json.dumps(data)
    assert len(text) <= metrics.LIMIT and "SECRET" not in text
    series = {s["m"]: s for s in data["series"]}
    assert all(len(s["points"]) <= 600 for s in series.values() if s["kind"] == "sample")
    clicks, requests = series["input/click"], series["net/GET api.acme.test"]
    assert clicks["kind"] == "span" and clicks["unit"] == "s" and clicks["stats"]["failed"] == 10
    assert sum(1 for s in clicks["spans"] if s[2] is False) == 10 and len(clicks["spans"]) + clicks["more"] == 5000
    assert requests["spans"][0][4] == {"connect": 0.01, "wait": 0.08, "receive": 0.01}
    assert series["app/frame"]["kind"] == "mark" and len(series["app/frame"]["marks"]) <= 1000
    assert series["host/cpu"]["label"] == "Host CPU" and series["host/cpu"]["stats"]["max"] == 99


def test_a_spike_inside_an_8x_stretch_stays_in_its_bin():
    found, start, clock = an_hour(spike_at=2000.0)
    cpu = next(s for s in found.page(start, 3600, clock.video)["series"] if s["m"] == "host/cpu")
    top = max(cpu["points"], key=lambda p: p[-1])
    assert top[-1] == 99 and 100 < top[0] < 3500
    assert max(p[-1] for p in cpu["points"] if p is not top) < 99


def test_a_budget_lists_the_series_it_judged():
    found, start, clock = an_hour()
    event = {"t": 12.0, "kind": "check", "text": "host/* p95 below 80 in the run", "ok": True, "detail": "p95 17%",
             "budget": {"glob": "host/*", "stat": "p95", "below": 80, "above": None}}
    budget = found.page(start, 3600, clock.video, [event])["budgets"][0]
    assert budget["ok"] and budget["series"] == ["host/cpu", "host/vm-cpu", "host/other-cpu", "host/load"]


def test_requests_from_the_network_probe_keep_their_phases_and_status():
    start = 1795134462.315
    data = metrics.load(Path(__file__).parent / "fixtures" / "network").page(start, 26.74, lambda t: t)
    net = data["series"][0]
    assert net["m"] == "net/10.0.2.2" and net["kind"] == "span" and net["unit"] == "s" and net["stats"]["failed"] == 1
    assert net["spans"][3] == [15.699, 0.8263, True, "GET 10.0.2.2:52356/slow",
                               {"connect": 0.0005, "wait": 0.8179, "receive": 0.0027}, 200]
    assert [s[5] for s in net["spans"]] == [200, 200, 200, 200, 500, 200]
