import json

import pytest
from PIL import Image, ImageDraw

from proofreel import latency, metrics

FPS = 30


def frames(tmp_path, draw, seconds=4):
    """Frames drawn by draw(image_draw, t), 30 a second, each arriving 20 ms after its request."""
    paths, requested, arrived = [], [], []
    for n in range(int(seconds * FPS)):
        t = n / FPS
        image = Image.new("RGB", (1440, 900), "white")
        draw(ImageDraw.Draw(image), t)
        path = tmp_path / f"{n:06d}.jpg"
        image.save(path, quality=90)
        paths.append(path)
        requested.append(t)
        arrived.append(t + 0.02)
    return paths, requested, arrived


def caret(d, t):
    if int(t / 0.5) % 2:
        d.rectangle((100, 100, 102, 120), fill="black")


def spinner(d, t):
    if int(t / 0.5) % 2:
        d.rectangle((100, 600, 140, 640), fill="black")


def test_a_click_answered_in_240_ms_measures_240_ms_with_a_caret_and_a_hover_before_it(tmp_path):
    def draw(d, t):
        caret(d, t)
        if t >= 1.8:
            d.rectangle((480, 280, 520, 320), fill=(200, 220, 255))
        if t >= 2.24:
            d.rectangle((480, 280, 520, 320), fill=(10, 100, 255))
    shown = frames(tmp_path, draw)
    events = [{"t": 2.0, "kind": "click", "text": "click Save", "x": 500, "y": 300}]
    assert latency.measure(tmp_path, events, *shown, scale=1.0) == 1
    line = json.loads((tmp_path / "metrics" / "input.jsonl").read_text())
    assert line["ok"] and line["d"] == pytest.approx(0.24, abs=line["err"] + 0.02) and line["err"] <= 1 / FPS


def test_a_key_ignores_a_spinner_that_blinks_before_the_answer(tmp_path):
    def draw(d, t):
        spinner(d, t)
        if t >= 1.6:
            d.text((600, 400), "Saved", fill="black")
    shown = frames(tmp_path, draw)
    latency.measure(tmp_path, [{"t": 1.4, "kind": "key", "text": "key cmd-s"}], *shown, scale=1.0)
    line = json.loads((tmp_path / "metrics" / "input.jsonl").read_text())
    assert line["m"] == "input/key" and line["d"] == pytest.approx(0.2, abs=line["err"] + 0.02)


def test_no_change_is_a_failed_mark_that_budgets_count_and_latency_stats_skip(tmp_path):
    shown = frames(tmp_path, caret)
    latency.measure(tmp_path, [{"t": 1.0, "kind": "click", "text": "click nothing", "x": 900, "y": 600}], *shown, scale=1.0)
    line = json.loads((tmp_path / "metrics" / "input.jsonl").read_text())
    assert line["ok"] is False and "d" not in line
    found = metrics.load(tmp_path)
    assert found.stat("input/*", "failed") == 1 and found.stat("input/*", "p95") is None


def test_a_budget_on_input_waits_for_the_end_of_the_run(tmp_path):
    (tmp_path / "metrics").mkdir()
    (tmp_path / "metrics" / "input.jsonl").write_text(
        "".join(json.dumps({"m": "input/click", "d": d, "ok": True, "a": 10 + n}) + "\n" for n, d in enumerate((0.1, 0.3))))
    ok, label, detail, fields = metrics.pending("input/*", "max", 0.2, None, None, 20, "the run")
    assert ok is None and label == "input/* max below 0.2 in the run"
    late = metrics.decide(tmp_path, [{"t": 15, "kind": "check", "text": label, **fields}])[0]
    assert late["ok"] is False and late["late"] and late["detail"] == "max 0.3 s, measured after the run"
    early = metrics.decide(tmp_path, [{"t": 15, "kind": "check", "text": label, **{"pending": {**fields["pending"], "until": 10.5}}}])[0]
    assert early["ok"] is True
