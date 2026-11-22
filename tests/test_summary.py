import json

from proofreel import summary


def session(tmp_path, events):
    (tmp_path / "session.json").write_text(json.dumps({"version": 2, "title": "t"}))
    (tmp_path / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    return tmp_path


def lines(*texts):
    return [{"text": t} for t in texts]


def test_a_step_lists_the_text_that_appeared_and_went(tmp_path):
    folder = session(tmp_path, [{"t": 1, "kind": "step", "text": "Open"}, {"t": 2, "kind": "open", "text": "open x"},
                                {"t": 5, "kind": "step", "text": "Search"}, {"t": 6, "kind": "type", "text": "type"}])
    for t, texts in ((0, ["blank"]), (4, ["Welcome", "Groceries"]), (8, ["Groceries", "milk"])):
        (folder / summary.FILE).open("a").write(json.dumps({"t": t, "lines": texts}) + "\n")
    assert summary.steps(folder) == ["1. Open: appeared: Welcome | Groceries gone: blank",
                                     "2. Search: appeared: milk gone: Welcome"]


def test_a_step_with_no_change_and_long_lists_are_short(tmp_path):
    folder = session(tmp_path, [{"t": 1, "kind": "step", "text": "Go"}])
    many = [f"line {n}" for n in range(10)]
    for t, texts in ((0, many), (4, many), (6, [])):
        (folder / summary.FILE).open("a").write(json.dumps({"t": t, "lines": texts}) + "\n")
    rows = summary.steps(folder)
    assert rows[0] == "1. Go: the text did not change"
    assert rows[1].endswith("gone: line 0 | line 1 | line 2 | line 3 (+6 more)")


def test_save_waits_for_an_action(tmp_path):
    folder = session(tmp_path, [{"t": 1, "kind": "click", "text": "c"}])
    summary.save(folder, lines("a"))
    summary.save(folder, lines("b"))
    assert [s["lines"] for s in summary.saves(folder)] == [["a"]]
    summary.save(folder, lines("b"), force=True)
    assert len(summary.saves(folder)) == 2


def test_text_names_each_failed_check_with_its_detail(tmp_path):
    folder = session(tmp_path, [{"t": 1, "kind": "check", "text": '"x" is on the screen', "ok": False,
                                 "detail": "The screen showed: a | b"},
                                {"t": 2, "kind": "check", "text": "y", "ok": True}])
    assert summary.text(folder) == 'Checks: 1 pass, 1 fail.\nFail: "x" is on the screen (The screen showed: a | b)'


def test_text_says_how_many_checks_another_tool_reported(tmp_path):
    folder = session(tmp_path, [{"t": 1, "kind": "check", "text": "a", "ok": True, "reported": True},
                                {"t": 2, "kind": "check", "text": "b", "ok": False, "reported": True},
                                {"t": 3, "kind": "check", "text": "c", "ok": True}])
    assert summary.text(folder) == "Checks: 2 pass, 1 fail (2 reported by another tool).\nFail: b (reported)"
