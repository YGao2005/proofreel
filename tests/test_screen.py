import json
import platform
import shutil
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw, ImageFont

from proofreel import Problem, cli, recording, screen


def line(text, x, y, word_width=40, gap=10, h=20):
    words, at = [], x
    for word in text.split():
        words.append({"text": word, "x": at, "y": y, "w": word_width, "h": h})
        at += word_width + gap
    return {"text": text, "x": x, "y": y, "w": at - gap - x, "h": h, "words": words}


def test_a_match_inside_a_line_gets_the_box_of_its_own_words():
    [match] = screen.matches([line("Drag files here or browse", 100, 100)], "browse")
    assert screen.center(match) == (320, 110)
    [match] = screen.matches([line("Drag files here or browse", 100, 100)], "here or")
    assert (match["x"], match["w"]) == (200, 90)


def test_a_line_with_no_word_boxes_keeps_its_box():
    old = {"text": "Save as", "x": 10, "y": 10, "w": 100, "h": 20}
    assert screen.matches([old], "as") == [{"text": "Save as", "x": 10, "y": 10, "w": 100, "h": 20}]


def test_a_box_keeps_only_the_matches_in_it():
    lines = [line("Import", 100, 50), line("Import", 300, 400)]
    assert [m["y"] for m in screen.matches(lines, "Import")] == [50, 400]
    assert [m["y"] for m in screen.matches(lines, "Import", box=(200, 300, 400, 200))] == [400]


@pytest.mark.skipif(platform.system() != "Darwin" or not shutil.which("swiftc"), reason="Apple Vision only")
def test_vision_gives_each_word_its_own_box(tmp_path):
    image = Image.new("RGB", (1200, 200), "white")
    ImageDraw.Draw(image).text((100, 60), "Drag files here or browse", fill="black",
                               font=ImageFont.load_default(size=36))
    image.save(tmp_path / "t.png")
    [full] = screen.read_text(tmp_path / "t.png")
    [match] = screen.matches([full], "browse")
    assert match["w"] < full["w"] / 3 and match["x"] > full["x"] + full["w"] / 2


class Client:
    """A VNC client whose server answers the given number of full-frame requests on each connection."""
    def __init__(self, log, answers):
        self.log, self.answers, self.timeout = log, answers, 30
        self.screen = SimpleNamespace(save=lambda path: log.append("saved"))

    def refreshScreen(self, incremental):
        if self.answers <= 0:
            raise TimeoutError("Timeout while waiting for client response")
        self.answers -= 1
        self.log.append("frame")

    def disconnect(self):
        self.log.append("disconnect")


def test_a_still_screen_gets_each_frame_on_a_new_connection(monkeypatch):
    log = []
    monkeypatch.setattr(screen, "FRAME_WAITS", (0.01, 0.01, 0.01))
    monkeypatch.setattr(screen.api, "connect", lambda *a, **k: Client(log, 1))
    with screen.Screen("vnc") as s:
        for _ in range(3):
            s.capture("x.png")
    assert [step for step in log if step != "disconnect"] == ["frame", "saved"] * 3
    assert log.count("disconnect") >= 2


def test_a_screen_that_never_answers_is_a_problem_not_a_traceback(monkeypatch):
    monkeypatch.setattr(screen, "FRAME_WAITS", (0.01, 0.01, 0.01))
    monkeypatch.setattr(screen.api, "connect", lambda *a, **k: Client([], 0))
    with pytest.raises(Problem, match="sent no frame in 3 tries"):
        with screen.Screen("vnc") as s:
            s.capture("x.png")


def args(*words):
    return cli.parser().parse_args(list(words))


@pytest.fixture
def macos(monkeypatch):
    """A macOS run VM whose AX tree has a dialog title and a button with the same words, over OCR lines of both."""
    tree = [{"role": "AXStaticText", "value": "Import", "x": 400, "y": 100, "box": [300, 80, 200, 40], "visible": True},
            {"role": "AXButton", "title": "Import", "x": 700, "y": 600, "box": [650, 580, 100, 40], "visible": True}]
    monkeypatch.setattr(cli.ax, "elements", lambda run, screen, app=None: tree)
    monkeypatch.setattr(cli, "screen_text", lambda s: [line("Import", 380, 90), line("Import", 680, 590)])
    return SimpleNamespace(guest=SimpleNamespace(ax=True))


def test_click_text_prefers_a_button_in_the_accessibility_tree(macos):
    assert cli.locate(args("click-text", "Import"), None, macos) == [(700, 600)]
    assert cli.locate(args("click-text", "Import", "--role", "AXStaticText"), None, macos) == [(400, 100)]


def test_click_text_uses_the_words_when_the_tree_has_too_few_exact_buttons(macos):
    assert cli.locate(args("click-text", "Import", "--nth", "2"), None, macos) == [(400, 100), (700, 600)]
    assert cli.locate(args("click-text", "Imp", "--timeout", "0"), None, macos) == [(400, 100), (700, 600)]


def test_click_text_without_the_tree_clicks_the_words(macos, monkeypatch):
    def denied(*_a, **_k):
        raise TimeoutError("ssh timed out")

    monkeypatch.setattr(cli.ax, "elements", denied)
    notes = []
    monkeypatch.setattr(cli, "log", lambda kind, text, *_a, **_k: notes.append((kind, text)))
    assert cli.locate(args("click-text", "Import", "--timeout", "0"), None, macos) == [(400, 100), (700, 600)]
    assert notes == [("note", "The accessibility tree could not be read (ssh timed out), so click-text reads the screen.")]
    assert cli.locate(args("click-text", "Import", "--in", "600,500,300,200"), None, None) == [(700, 600)]
    with pytest.raises(Problem, match="--role reads the accessibility tree"):
        cli.locate(args("click-text", "Import", "--role", "AXButton"), None, None)


def test_a_check_scoped_to_an_element_that_is_not_there_fails_and_says_why(tmp_path, monkeypatch):
    session = tmp_path / "s"
    (session / "frames").mkdir(parents=True)
    monkeypatch.setattr(recording, "POINTER", tmp_path / "active.json")
    (tmp_path / "active.json").write_text(json.dumps({"dir": str(session), "pid": 0}))
    monkeypatch.setattr(cli, "screen_text", lambda s: [])
    monkeypatch.setattr(screen, "screen_text", lambda s: [])
    assert cli.run_check(args("check", "no-text", "Error", "--in", "Upload"), None, None) == 1
    event = json.loads((session / "events.jsonl").read_text())
    assert "only a macOS run VM has the accessibility tree" in event["detail"]
    assert cli.run_check(args("check", "no-text", "Error", "--in", "0,0,10,10"), None, None) == 0
