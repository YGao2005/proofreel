from proofreel import screen as screens
from proofreel.screen import Screen


class Client:
    def __init__(self):
        self.sent = []

    def mouseMove(self, x, y):
        self.sent.append(("move", x, y))

    def mousePress(self, button):
        self.sent.append(("press", button))


def test_move_and_click_glide_in_and_end_on_the_target(monkeypatch):
    monkeypatch.setattr(screens.time, "sleep", lambda _: None)
    s = Screen("vnc")
    s.client = Client()
    s.move(500, 300)
    moves = [m for m in s.client.sent if m[0] == "move"]
    assert len(moves) == screens.GLIDE_STEPS and moves[-1] == ("move", 500, 300)
    assert moves[0][1:] != (500, 300) and all(a[1] <= b[1] and a[2] <= b[2] for a, b in zip(moves, moves[1:]))
    s.client.sent.clear()
    s.click(10, 5)
    assert s.client.sent[-2:] == [("move", 10, 5), ("press", 1)] and min(m[1] for m in s.client.sent[:-1]) >= 0
