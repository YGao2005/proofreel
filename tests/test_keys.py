import pytest

from proofreel import Problem, cli, guest
from proofreel.screen import Screen


class Client:
    def __init__(self):
        self.sent = []

    def keyDown(self, key):
        self.sent.append(("down", key))

    def keyUp(self, key):
        self.sent.append(("up", key))

    def keyPress(self, key):
        self.sent.append(("press", key))


def screen(keys=None):
    s = Screen("vnc", keys=keys)
    s.client = Client()
    return s


def test_a_macos_guest_posts_modifiers_in_the_guest_and_other_keys_over_vnc(monkeypatch):
    calls = []
    monkeypatch.setattr(guest.MacOS, "keys_helper", lambda self, run, *args, timeout=30: calls.append(args))
    mac, s = guest.GUESTS["macos"], screen(guest.GUESTS["macos"].keys)
    mac.tap(None, s, "fn", 2)
    mac.hold(None, s, "option", 1.5)
    mac.press(None, s, "command", True)
    mac.tap(None, s, "a", 2)
    assert calls == [("tap", "fn", "2", "70", "110"), ("hold", "option", "1.5"), ("down", "command")]
    assert s.client.sent == [("down", "a"), ("up", "a"), ("down", "a"), ("up", "a")]


def test_other_guests_send_every_key_over_vnc(monkeypatch):
    monkeypatch.setattr(guest.MacOS, "keys_helper", lambda *_, **__: pytest.fail("not a macOS guest"))
    s = screen()
    guest.GUESTS["linux"].press(None, s, "shift", True)
    guest.Guest().tap(None, s, "ctrl", 1)
    assert s.client.sent == [("down", "shift"), ("down", "ctrl"), ("up", "ctrl")]


def test_combos_use_the_names_of_the_guest_vnc_server():
    s = screen(guest.GUESTS["macos"].keys)
    s.key("command-a", "enter")
    assert s.client.sent == [("press", "alt-a"), ("press", "enter")]


def test_hold_takes_seconds_down_or_up(monkeypatch):
    done = []
    monkeypatch.setattr(cli, "log", lambda *a, **k: None)
    system = guest.Guest()
    monkeypatch.setattr(system, "press", lambda run, screen, key, down: done.append((key, down)))
    monkeypatch.setattr(system, "hold", lambda run, screen, key, seconds: done.append((key, seconds)))

    class Run:
        guest = system

    for argv in (["hold", "fn", "down"], ["hold", "fn", "up"], ["hold", "fn", "0.5"]):
        cli.act(cli.parser().parse_args(argv), None, Run())
    assert done == [("fn", True), ("fn", False), ("fn", 0.5)]
    with pytest.raises(Problem, match="seconds, down, or up"):
        cli.act(cli.parser().parse_args(["hold", "fn", "long"]), None, Run())
