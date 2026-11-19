from proofreel import screen


def test_words_that_text_recognition_reads_in_look_alike_letters_are_found(monkeypatch):
    lines = [{"text": "Sign in to Астe", "x": 260, "y": 226, "w": 300, "h": 40}]
    monkeypatch.setattr(screen, "screen_text", lambda _: lines)
    assert screen.find(None, "Sign in to Acme") == lines
    assert screen.find(None, "sign in TO acme") == lines
    assert screen.find(None, "Sign in to Acne") == []
