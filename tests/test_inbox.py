import http.client
import json
import threading
import time

import pytest

from proofreel import Problem, chrome, cli, inbox, screen, vm


@pytest.fixture
def box(tmp_path, monkeypatch):
    """A fresh inbox folder, and a proof page to queue."""
    monkeypatch.setattr(inbox, "FOLDER", tmp_path / "inbox")
    monkeypatch.setattr(inbox, "POLL", 0.02)
    (tmp_path / "proof").mkdir()
    (tmp_path / "proof" / "index.html").write_text("<!doctype html><title>Proof</title><h1>The proof page</h1>")
    (tmp_path / "secret.txt").write_text("outside")
    return tmp_path


def queued(box, **fields):
    return inbox.add(box / "proof", "Spaces upload", "nomi-95", 7, "merge it", **fields)


def test_an_item_survives_a_round_trip_and_its_id_is_readable(box):
    item = queued(box)
    assert item["id"].startswith("spaces-upload-") and len(item["id"]) == len("spaces-upload-") + 4
    assert inbox.load(item["id"]) == item
    assert (item["from"], item["pr"], item["on_approve"], item["page"]) == ("nomi-95", 7, "merge it", str(box / "proof" / "index.html"))
    assert [i["id"] for i in inbox.items()] == [item["id"]]
    assert "waiting" in inbox.listing()[0]


def test_a_missing_page_and_an_unknown_id_are_problems(box):
    with pytest.raises(Problem, match="not a review folder"):
        inbox.add(box / "nothing")
    with pytest.raises(Problem, match="No inbox item"):
        inbox.load("../x")


def test_wait_returns_the_decision_text_and_marks_it_picked(box):
    item = queued(box)
    threading.Timer(0.1, inbox.decide, [item["id"], "approve"]).start()
    assert inbox.wait(item["id"]) == "Approved: Spaces upload. Then: merge it."
    assert inbox.load(item["id"])["picked"]["at"]
    assert inbox.wait(item["id"], 1) == "Approved: Spaces upload. Then: merge it."


def test_the_decision_texts(box):
    texts = {}
    for verdict, said in (("approve_next", "Add import"), ("needs_work", "Fix the title"), ("reject", "")):
        texts[verdict] = inbox.decide(queued(box)["id"], verdict, said)["decision"]["text"]
    assert texts == {"approve_next": "Approved: Spaces upload. Next mission: Add import",
                     "needs_work": "Needs work: Fix the title", "reject": "Rejected: no reason given. Close the branch."}
    with pytest.raises(Problem, match="needs a text"):
        inbox.decide(queued(box)["id"], "needs_work", " ")


def test_wait_with_a_timeout_exits_2(box, capsys):
    item = queued(box)
    assert cli.command(["inbox", "wait", item["id"], "--timeout", "0.1"]) == 2
    assert "No decision" in capsys.readouterr().err


def test_check_here_takes_only_this_repo_and_branch(box, monkeypatch):
    monkeypatch.setattr(inbox, "here", lambda: {"repo": "nomi", "branch": "a"})
    mine, other = queued(box), queued(box)
    inbox.save({**other, "branch": "b"})
    for item in (mine, other):
        inbox.decide(item["id"], "approve")
    assert inbox.check(only_here=True) == ["Approved: Spaces upload. Then: merge it."]
    assert not inbox.load(other["id"]).get("picked")
    assert len(inbox.check()) == 1 and inbox.check() == []


@pytest.fixture
def running(box):
    httpd = inbox.server(0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def request(httpd, method, path, body=None, **headers):
    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
    connection.request(method, path, body, headers)
    answer = connection.getresponse()
    data = answer.read()
    connection.close()
    return answer.status, data


def post(httpd, item, verdict="approve", **headers):
    body = json.dumps({"id": item["id"], "verdict": verdict, "text": "go"})
    return request(httpd, "POST", "/decide", body, **headers)


def test_the_server_shows_the_page_the_queue_and_the_item_files(box, running):
    item = queued(box)
    status, page = request(running, "GET", "/")
    assert status == 200 and inbox.token().encode() in page
    status, data = request(running, "GET", "/items")
    assert json.loads(data)[0]["url"] == f"/item/{item['id']}/index.html" and "page" not in json.loads(data)[0]
    assert request(running, "GET", f"/item/{item['id']}/index.html") == (200, (box / "proof" / "index.html").read_bytes())
    assert request(running, "GET", f"/item/{item['id']}/index.html", Range="bytes=0-4") == (206, b"<!doc")


def test_files_outside_the_item_folder_and_a_foreign_host_are_refused(box, running):
    item = queued(box)
    for path in ("../secret.txt", "..%2Fsecret.txt", "%2e%2e/secret.txt", "/etc/passwd"):
        assert request(running, "GET", f"/item/{item['id']}/{path}")[0] == 404
    assert request(running, "GET", "/item/nothing/index.html")[0] == 404
    assert request(running, "GET", "/items", Host="evil.example")[0] == 403


def test_a_decision_needs_the_token_and_the_servers_own_origin(box, running):
    item = queued(box)
    origin = f"http://127.0.0.1:{running.server_port}"
    secret = inbox.token()
    assert post(running, item, **{"Origin": origin})[0] == 403
    assert post(running, item, **{"X-Inbox-Token": "wrong", "Origin": origin})[0] == 403
    assert post(running, item, **{"X-Inbox-Token": secret, "Origin": "http://evil.example"})[0] == 403
    assert post(running, item, **{"X-Inbox-Token": secret})[0] == 403
    assert not inbox.load(item["id"]).get("decision")
    good = {"X-Inbox-Token": secret, "Origin": origin}
    assert post(running, item, **good)[0] == 200
    assert inbox.load(item["id"])["decision"]["verdict"] == "approve"
    assert post(running, item, **good)[0] == 409
    assert (inbox.FOLDER / "token").stat().st_mode & 0o777 == 0o600


def test_a_taken_port_is_a_problem(running):
    with pytest.raises(Problem, match="in use"):
        inbox.server(running.server_port)


@pytest.fixture
def browser(chrome_path, tmp_path_factory):
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(chrome, "FOLDER", tmp_path_factory.mktemp("chrome"))
        record = chrome.up("web", dict(vm.WEB))
        try:
            yield record
        finally:
            chrome.stop()


def test_the_person_presses_needs_work_and_the_item_has_the_decision(box, running, browser):
    item = queued(box)
    with screen.connect(browser["screen"]) as web:
        web.open(f"http://127.0.0.1:{running.server_port}/")
        assert screen.wait_for(web, "waiting 0 min", 10)
        web.click(*screen.center(screen.matches(web.lines(), "Needs work")[0]))
        assert screen.wait_for(web, "What needs work?", 5)
        web.type("Fix the title")
        web.key("command-enter")
        deadline = time.time() + 10
        while not inbox.load(item["id"]).get("decision") and time.time() < deadline:
            time.sleep(0.1)
    assert inbox.load(item["id"])["decision"]["text"] == "Needs work: Fix the title"
