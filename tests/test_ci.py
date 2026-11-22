import json
import subprocess
from pathlib import Path

from proofreel import ci, cli, page

ROOT = Path(__file__).parents[1]


def review(tmp_path, *runs):
    for i, (verdict, checks) in enumerate(runs):
        events = [{"t": 1.0, "kind": "check", "text": text, "ok": ok, "detail": detail} for text, ok, detail in checks]
        run = {**page.stub(f"j{i}-1", f"Journey {i}", "", suite={"id": "s", "title": "T"}), "verdict": verdict,
               "events": events, "length": 3.5}
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
