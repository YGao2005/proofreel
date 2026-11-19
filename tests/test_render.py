import json
import subprocess

from proofreel.demo import demo
from proofreel.motion import FAST, Camera, Pointer, spans, timeline


def test_timeline_ramps_and_slows_for_actions():
    plan = timeline(spans([], [{"t": 20.0, "kind": "click"}]), 30)
    speeds = [speed for _, speed in plan]
    assert max(speeds) > FAST * 0.9
    assert all(abs(b - a) < FAST * 0.6 for a, b in zip(speeds, speeds[1:]))
    near_click = [speed for now, speed in plan if 18.8 <= now <= 22]
    assert near_click and max(near_click) < 1.05


def test_camera_view_stays_on_the_screen():
    size = (1440, 900)
    events = [{"t": 1.0, "kind": "click", "x": 5, "y": 5}, {"t": 2.0, "kind": "click", "x": 1435, "y": 895},
              {"t": 2.5, "kind": "type", "text": "x"}]
    camera = Camera(events, Pointer(events, size), size)
    for i in range(24 * 6):
        left, top, w, h = camera.step(i / 24, 1 / 24)
        assert left >= 0 and top >= 0 and left + w <= size[0] + 1e-6 and top + h <= size[1] + 1e-6


def test_pointer_reaches_each_click_on_time():
    events = [{"t": 1.0, "kind": "click", "x": 100, "y": 200}, {"t": 1.3, "kind": "click", "x": 900, "y": 700}]
    pointer = Pointer(events, (1440, 900))
    assert pointer.at(1.0) == (100, 200)
    assert pointer.at(1.3) == (900, 700)


def test_demo_renders_a_page_and_video(tmp_path):
    demo(tmp_path / "demo")
    page = (tmp_path / "demo" / "index.html").read_text()
    assert "Works" in page and "session.mp4" in page
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json",
                            str(tmp_path / "demo" / "session.mp4")], capture_output=True, text=True, check=True)
    assert 8 < float(json.loads(probe.stdout)["format"]["duration"]) < 16


def test_a_long_wait_plays_faster_than_real_time_even_while_the_screen_changes():
    changes = [10 + i * 0.25 for i in range(40)]
    plan = timeline(spans(changes, [{"t": 10.0, "end": 21.0, "kind": "wait"}]), 24)
    during = [speed for now, speed in plan if 12.5 <= now <= 19.5]
    assert min(during) > 2.5


def test_the_page_assets_ship_with_the_package():
    from proofreel import page
    assert "function render()" in page.ASSETS.joinpath("page.js").read_text()
    assert "--accent" in page.ASSETS.joinpath("page.css").read_text()
