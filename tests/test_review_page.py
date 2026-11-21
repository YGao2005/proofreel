import pytest

from proofreel import page

playwright = pytest.importorskip("playwright.sync_api")


def run(title, *path, failed_budget=False):
    states = [{"name": name, "t": i * 2 + 1, "end": i * 2 + 3, "ok": True} for i, name in enumerate(path)]
    budget = [{"glob": "host/cpu", "stat": "p95", "below": 5, "above": None, "ok": False, "detail": "p95 9 %", "t": 7, "series": ["host/cpu"]}] if failed_budget else []
    return {"version": page.VERSION, "id": title, "title": title, "about": "", "error": "", "verdict": "works", "meta": [], "base": "",
            "length": 8, "real": 8, "overlay": False, "camera": [], "when": "", "clock": [[0, 0], [8, 8]], "states": states,
            "events": [{"t": 1, "kind": "step", "text": "Go", "row": "key"}],
            "metrics": {"budgets": budget, "probes": {}, "series": [
                {"m": "host/cpu", "kind": "sample", "unit": "%", "stats": {"count": 3, "failed": 0, "p50": 5, "p95": 9, "max": 9},
                 "points": [[1, 5], [4, 9], [7, 6]]}]}}


@pytest.fixture
def view(tmp_path):
    (tmp_path / "index.html").write_text(page.document([run("Sign in", "Home", "Welcome"), run("Wrong password", "Home", "Error", failed_budget=True)]))
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except Exception:
            pytest.skip("no Chrome to launch")
        tab = browser.new_page(viewport={"width": 1440, "height": 900})
        tab.goto((tmp_path / "index.html").as_uri())
        yield tab
        browser.close()


def test_tracks_start_folded_even_when_a_budget_failed_and_stay_as_set_across_runs(view):
    assert view.get_attribute(".tracks .fold", "aria-expanded") == "false"
    assert view.is_hidden(".tracks .lanes")
    view.click(".tracks .fold")
    view.evaluate("location.hash = 'run-1'")
    view.wait_for_function("document.querySelector('.tracks .fold').getAttribute('aria-expanded') === 'true'")


def test_a_state_from_another_run_opens_that_run_at_the_state(view):
    view.click(".machine .node[aria-label^='Welcome']")
    view.wait_for_function("location.hash === '#run-1&t=2.8'")
    assert view.inner_text(".machine .visit h2").startswith("Welcome")
    assert "picked" in view.get_attribute(".machine .node[aria-label^='Welcome']", "class")
