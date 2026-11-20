import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("readme_media", Path(__file__).parent.parent / "tools" / "readme_media.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def test_the_tour_is_valid():
    assert tool.check_tour(tool.TOUR) == []


def test_every_click_target_makes_a_selector():
    for step in tool.TOUR:
        if step["action"] == "click":
            assert tool.selector(*step["target"])


def test_the_tour_fits_the_length_of_the_video():
    assert 45 <= sum(step["pause"] for step in tool.TOUR) <= 60


def test_a_bad_step_is_named():
    bad = [{"action": "click", "target": ("sidebar", None), "caption": "Click it", "pause": 1},
           {"action": "hover", "target": None, "caption": "One two three", "pause": 1}]
    problems = tool.check_tour(bad)
    assert len(problems) == 3
    assert [p.split(":")[0] for p in problems] == ["step 1", "step 1", "step 2"]
