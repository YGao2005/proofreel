import json

import pytest
import subprocess
from pathlib import Path

from proofreel import Problem, ci, cli, page

ROOT = Path(__file__).parents[1]


def review(tmp_path, *runs):
    for i, (verdict, checks) in enumerate(runs):
        events = [{"t": 1.0, "kind": "check", "text": text, "ok": ok, "detail": detail} for text, ok, detail in checks]
        run = {**page.stub(f"j{i}-1", f"Journey {i}", "", suite={"id": "s", "title": "T"}), "verdict": verdict,
               "events": events, "length": 3.5, "video": True}
        page.add(tmp_path, run)
    return tmp_path


def test_verdicts_come_from_the_review_folder(tmp_path, capsys):
    out = review(tmp_path, ("works", [("a is on the screen", True, "")]), ("shown", []),
                 ("problem", [("b is on the screen", False, "not found")]))
    rows = ci.journeys(out)
    assert [r["verdict"] for r in rows] == ["works", "shown", "problem"]
    assert rows[2]["failed"] == [{"text": "b is on the screen", "detail": "not found"}]
    assert cli.command(["ci", "check", str(out)]) == 1
    printed = capsys.readouterr().out
    assert "NO CHECKS: Journey 1" in printed and "::warning::Journey 1 has no checks" in printed
    assert "FAIL" not in printed.split("NO CHECKS")[0]


def test_checks_without_a_problem_pass_and_an_empty_folder_fails(tmp_path):
    assert cli.command(["ci", "check", str(review(tmp_path / "a", ("works", [("x", True, "")]), ("shown", [])))]) == 0
    (tmp_path / "empty").mkdir()
    assert cli.command(["ci", "check", str(tmp_path / "empty")]) == 1


def test_install_script_picks_the_version(tmp_path):
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "python").write_text('#!/bin/sh\necho "$@" >> "$LOG"\n')
    (fake / "proofreel").write_text("#!/bin/sh\n")
    for tool in fake.iterdir():
        tool.chmod(0o755)
    seen = {}
    for args in (["", "v1.2.2", "/src"], ["", "v1", "/src"], ["", "main", "/src"], ["", "", "/src"], ["latest", "v1", "/src"],
                 ["1.0.0", "main", "/src"]):
        log = tmp_path / "log"
        log.write_text("")
        subprocess.run([str(ROOT / "ci" / "install.sh"), *args], check=True, env={"PATH": f"{fake}:/usr/bin:/bin", "LOG": str(log)})
        seen[" ".join(args)] = log.read_text().split()[-1]
    assert seen == {" v1.2.2 /src": "proofreel==1.2.2", " v1 /src": "proofreel>=1,<2", " main /src": "/src",
                    "  /src": "/src", "latest v1 /src": "proofreel", "1.0.0 main /src": "proofreel==1.0.0"}


def bare(tmp_path, files=None):
    tmp_path.mkdir(exist_ok=True)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    if files:
        work = tmp_path / "seed"
        subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True, capture_output=True)
        subprocess.run(["git", "checkout", "-q", "-b", "gh-pages"], cwd=work, check=True)
        for name, text in files.items():
            (work / name).parent.mkdir(parents=True, exist_ok=True)
            (work / name).write_text(text)
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*git, "add", "-A"], cwd=work, check=True)
        subprocess.run([*git, "commit", "-qm", "seed"], cwd=work, check=True)
        subprocess.run(["git", "push", "-q", "origin", "gh-pages"], cwd=work, check=True)
    return remote


def listing(remote):
    out = subprocess.run(["git", "ls-tree", "-r", "--name-only", "gh-pages"], cwd=remote, capture_output=True, text=True)
    return out.stdout.split()


def test_stage_keeps_static_files_and_writes_the_page_again(tmp_path):
    out = review(tmp_path / "r", ("works", [("a", True, "")]))
    run = out / "runs" / "j0-1"
    run.mkdir(parents=True)
    (run / "poster.jpg").write_bytes(b"jpg")
    (run / "session.mp4").write_bytes(b"mp4")
    (run / "evil.html").write_text("<script>alert(1)</script>")
    (out / "index.html").write_text("<script>alert(2)</script>")
    staged = ci.stage(out, tmp_path / "s")
    names = sorted(str(p.relative_to(staged)) for p in staged.rglob("*") if p.is_file())
    assert names == ["index.html", "runs.json", "runs/j0-1/poster.jpg", "runs/j0-1/session.mp4"]
    assert "alert" not in (staged / "index.html").read_text()


def test_stage_refuses_a_link(tmp_path):
    out = review(tmp_path / "r", ("works", [("a", True, "")]))
    (out / "secret.jpg").symlink_to("/etc/passwd")
    with pytest.raises(Problem, match="has a link"):
        ci.stage(out, tmp_path / "s")


def test_pages_makes_the_branch_and_keeps_other_folders(tmp_path):
    staged = tmp_path / "s"
    staged.mkdir()
    (staged / "index.html").write_text("new")
    remote = bare(tmp_path, {"example/index.html": "keep", "index.html": "root"})
    ci.pages(staged, str(remote), "pr/7")
    ci.pages(staged, str(remote), "pr/8")
    assert listing(remote) == ["example/index.html", "index.html", "pr/7/index.html", "pr/8/index.html"]
    fresh = bare(tmp_path / "fresh")
    ci.pages(staged, str(fresh), "pr/1")
    assert listing(fresh) == [".nojekyll", "pr/1/index.html"]


def count(remote):
    out = subprocess.run(["git", "rev-list", "--count", "gh-pages"], cwd=remote, capture_output=True, text=True)
    return int(out.stdout)


def test_pages_keeps_one_commit_and_drops_closed_pull_requests(tmp_path):
    staged = tmp_path / "s"
    staged.mkdir()
    (staged / "index.html").write_text("new")
    remote = bare(tmp_path, {"example/index.html": "keep", "index.html": "root", "pr/1/index.html": "closed",
                             "pr/2/index.html": "open", "pr/notes/x.txt": "not a number"})
    ci.pages(staged, str(remote), "pr/7", keep={2})
    assert listing(remote) == ["example/index.html", "index.html", "pr/2/index.html", "pr/7/index.html", "pr/notes/x.txt"]
    assert count(remote) == 1
    ci.pages(staged, str(remote), "pr/7", keep={2})
    ci.pages(staged, str(remote), "pr/8", keep=None)
    assert count(remote) == 1 and "pr/7/index.html" in listing(remote)


def test_a_pull_request_list_that_fails_prunes_nothing():
    def broken(*args):
        raise Problem("gh failed")

    assert ci.open_prs("o/r", broken) is None
    assert ci.open_prs("o/r", lambda *a: "3\n12\n") == {3, 12}


def test_pages_retries_when_another_job_pushes_first(tmp_path, monkeypatch):
    staged = tmp_path / "s"
    staged.mkdir()
    (staged / "index.html").write_text("mine")
    remote = bare(tmp_path, {"a.txt": "a"})
    real, raced = ci.git, []

    def racing(folder, *args, **kw):
        if args[0] == "push" and not raced:
            raced.append(1)
            other = tmp_path / "other"
            subprocess.run(["git", "clone", "-q", "-b", "gh-pages", str(remote), str(other)], check=True, capture_output=True)
            (other / "pr" / "9").mkdir(parents=True)
            (other / "pr" / "9" / "index.html").write_text("theirs")
            git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
            subprocess.run([*git, "add", "-A"], cwd=other, check=True)
            subprocess.run([*git, "commit", "-qm", "other"], cwd=other, check=True)
            subprocess.run(["git", "push", "-q", "origin", "gh-pages"], cwd=other, check=True)
        return real(folder, *args, **kw)

    monkeypatch.setattr(ci, "git", racing)
    monkeypatch.setattr(ci.time, "sleep", lambda s: None)
    ci.pages(staged, str(remote), "pr/5", keep={5, 9})
    assert raced and listing(remote) == ["a.txt", "pr/5/index.html", "pr/9/index.html"] and count(remote) == 1


def test_pages_refuses_a_bad_folder(tmp_path):
    for bad in ("../x", "", "/abs", "a/../b"):
        with pytest.raises(Problem, match="Bad folder"):
            ci.pages(tmp_path, "unused", bad)


def test_a_fork_falls_back_to_the_artifact(tmp_path):
    out = tmp_path / "o"
    ctx = {"repo": "o/r", "pr": 3, "sha": "abc", "fork": True, "run": "https://github.com/o/r/actions/runs/9"}
    mode, link, note = ci.publish(out, "auto", ctx, "t", output=str(tmp_path / "gh"))
    assert (mode, link) == ("artifact", ctx["run"]) and "fork" in note
    assert (tmp_path / "gh").read_text().startswith("mode=artifact\nlink=https://github.com/o/r/actions/runs/9\n")


def test_context_reads_the_event(tmp_path):
    event = tmp_path / "e.json"
    event.write_text(json.dumps({"pull_request": {"number": 4, "head": {"sha": "abc", "repo": {"full_name": "me/r"}}}}))
    ctx = ci.context({"GITHUB_EVENT_PATH": str(event), "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "5"})
    assert (ctx["pr"], ctx["sha"], ctx["fork"]) == (4, "abc", True) and ctx["run"].endswith("/o/r/actions/runs/5")


CTX = {"repo": "o/r", "pr": 3, "sha": "0123456789abcdef", "fork": False, "run": "https://github.com/o/r/actions/runs/9"}


def mixed(tmp_path):
    return review(tmp_path, ("works", [("a is on the screen", True, "")]), ("shown", []),
                  ("problem", [("b | @me is on the screen", False, "not found")]))


def test_comment_names_the_commit_and_each_verdict(tmp_path):
    body = ci.comment(mixed(tmp_path), CTX, "https://o.github.io/r/pr/3/")
    assert body.startswith(ci.MARKER) and "1 works, 1 problem, 1 no checks" in body
    assert "[`0123456`](https://github.com/o/r/commit/0123456789abcdef)" in body
    assert "| Journey 0 | works | 3.5 s |" in body and "| Journey 1 | no checks | 3.5 s |" in body
    assert "problem: `b / @​me is on the screen` (not found)" in body
    assert "![Journey 2](https://o.github.io/r/pr/3/runs/j2-1/poster.jpg?v=0123456)](https://o.github.io/r/pr/3/?v=0123456)" in body
    assert "passed" not in body and "PASS" not in body


def test_comment_shows_the_first_journey_when_none_fail_and_no_picture_for_an_artifact(tmp_path):
    out = review(tmp_path, ("works", [("a", True, "")]))
    assert "runs/j0-1/poster.jpg" in ci.comment(out, CTX, "https://x/")
    body = ci.comment(out, CTX, "https://github.com/o/r/actions/runs/9", "artifact", "From a fork.")
    assert "![" not in body and "download the `proofreel-review` artifact" in body and "Note: From a fork." in body


def test_comment_text_from_a_run_cannot_make_a_link_or_a_tag(tmp_path):
    out = review(tmp_path, ("problem", [("<img src=x> [click](http://evil)", False, "")]))
    body = ci.comment(out, CTX, "https://x/")
    assert "<img" not in body and "[click]" not in body


def test_post_changes_the_comment_with_the_marker_else_makes_one(tmp_path):
    calls = []

    def fake(found):
        def run(*args):
            calls.append(args)
            return found if args[0] == "api" and "--paginate" in args else '{"id": 77}'
        return run

    assert ci.post("o/r", 3, "body", fake("41\n")) == "41"
    assert calls[-1][:3] == ("api", "-X", "PATCH") and calls[-1][3] == "repos/o/r/issues/comments/41"
    assert ci.post("o/r", 3, "body", fake("")) == 77
    assert calls[-1][1] == "repos/o/r/issues/3/comments" and "-X" not in calls[-1]
