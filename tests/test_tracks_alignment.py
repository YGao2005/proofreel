import pytest

from proofreel import page

playwright = pytest.importorskip("playwright.sync_api")

RUN = {"version": page.VERSION, "id": "r", "title": "Aligned", "about": "", "error": "", "verdict": "works", "meta": [], "base": "",
       "length": 8, "real": 8, "overlay": False, "camera": [], "when": "", "clock": [[0, 0], [8, 8]], "states": [],
       "events": [{"t": 1, "kind": "step", "text": "Go", "row": "key"}],
       "metrics": {"budgets": [], "probes": {}, "series": [
           {"m": "host/cpu", "kind": "sample", "unit": "%", "stats": {"count": 3, "failed": 0, "p50": 5, "p95": 9, "max": 9},
            "points": [[1, 5], [4, 9], [7, 6]]}]}}


@pytest.mark.parametrize("width", [1440, 1000, 420])
def test_the_scrub_bar_and_the_lanes_share_one_horizontal_geometry(tmp_path, width):
    (tmp_path / "index.html").write_text(page.document([RUN]))
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except Exception:
            pytest.skip("no Chrome to launch")
        view = browser.new_page(viewport={"width": width, "height": 900})
        view.goto((tmp_path / "index.html").as_uri())
        view.click(".tracks .fold")
        for at in (0, 50, 100):
            view.evaluate("at => document.querySelector('.stack').style.setProperty('--at', at + '%')", at)
            found = view.evaluate("""() => {
                const bar = document.querySelector('.bar').getBoundingClientRect(), done = document.querySelector('.bar .done').getBoundingClientRect();
                const lane = document.querySelector('.lane'), box = lane.getBoundingClientRect();
                return { bar: [bar.left, bar.right], lane: [box.left, box.right], thumb: done.right, head: box.left + parseFloat(getComputedStyle(lane, '::after').left) };
            }""")
            assert found["bar"] == pytest.approx(found["lane"], abs=1)
            assert found["thumb"] == pytest.approx(found["head"], abs=1)
        browser.close()
