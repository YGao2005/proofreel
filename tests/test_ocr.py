from proofreel import screen


def test_words_that_text_recognition_reads_in_look_alike_letters_are_found(monkeypatch):
    lines = [{"text": "Sign in to Астe", "x": 260, "y": 226, "w": 300, "h": 40}]
    monkeypatch.setattr(screen, "screen_text", lambda _: lines)
    assert screen.find(None, "Sign in to Acme") == lines
    assert screen.find(None, "sign in TO acme") == lines
    assert screen.find(None, "Sign in to Acne") == []


def test_a_match_inside_a_longer_line_points_at_its_own_words(monkeypatch):
    words = [{"text": t, "x": x, "y": 290, "w": w, "h": 24}
             for t, x, w in (("Wrong", 80, 70), ("password.", 156, 110), ("Try", 272, 40), ("again", 316, 66))]
    line = {"text": "Wrong password. Try again", "x": 80, "y": 290, "w": 302, "h": 24, "words": words}
    monkeypatch.setattr(screen, "screen_text", lambda _: [line])
    found = screen.find(None, "Try again")[0]
    assert (found["x"], found["w"]) == (272, 110) and screen.center(found) == (327, 302)
    assert screen.find(None, "Wrong password. Try again")[0] is line
    assert screen.find(None, "word. Tr")[0]["x"] == 156
