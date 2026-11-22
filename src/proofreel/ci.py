"""Helpers for CI: read the verdict of each journey from a review folder.

The exit code of `proofreel suite` is not the verdict. The verdict of each journey is in runs.json, and a journey
that has no checks is "shown", not "works": a report must not call it a pass.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import Problem, page

ID = re.compile(r"[A-Za-z0-9._-]+")
DEST = re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*")
KEEP = {".mp4", ".jpg"}
MARKER = "<!-- proofreel-comment -->"
LABEL = {"works": "works", "problem": "problem", "shown": "no checks"}


def journeys(out):
    """One dict for each journey of the review folder: id, title, verdict, error, failed checks, seconds."""
    rows = []
    for run in page.load_runs(out):
        failed = [{"text": e["text"], "detail": e.get("detail", "")} for e in run["events"]
                  if e.get("kind") == "check" and e.get("ok") is False]
        rows.append({"id": run["id"], "title": run["title"], "verdict": run["verdict"], "error": run.get("error", ""),
                     "failed": failed, "seconds": run["length"], "poster": f"runs/{run['id']}/poster.jpg"
                     if run.get("video") is not False else None})
    return rows


def check(out):
    """Print one line for each journey. Returns 1 when a journey has a problem or there are no journeys, else 0."""
    rows = journeys(out)
    for row in rows:
        print(f"{LABEL[row['verdict']].upper()}: {row['title']}")
        if row["verdict"] == "shown":
            print(f"::warning::{row['title']} has no checks, so it proves nothing. Add check lines to its flow.")
    if not rows:
        print("No journeys in the review folder.")
    return 1 if not rows or any(r["verdict"] == "problem" for r in rows) else 0


def stage(review, staged):
    """Copy a review folder that came from untrusted code into staged, as static files only.

    Only runs.json, and the .mp4 and .jpg files of each run, go on. A link is an error. The page is written again
    here, by this proofreel, so no script from the run reaches the site."""
    review, staged = Path(review), Path(staged)
    for path in review.rglob("*"):
        if path.is_symlink():
            raise Problem(f"The review folder has a link: {path.relative_to(review)}.")
    runs = page.load_runs(review)
    if not runs:
        raise Problem("The review folder has no runs.json.")
    safe = []
    for run in runs:
        if not ID.fullmatch(run["id"]):
            raise Problem(f"A run has a bad id: {run['id']!r}.")
        safe.append({**run, "base": f"runs/{run['id']}/"})
        for path in sorted((review / "runs" / run["id"]).rglob("*")):
            if path.is_file() and path.suffix in KEEP:
                target = staged / path.relative_to(review)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
    staged.mkdir(parents=True, exist_ok=True)
    (staged / "runs.json").write_text(json.dumps({"version": page.VERSION, "runs": safe}))
    (staged / "index.html").write_text(page.document(safe))
    return staged


def git(folder, *args, token=""):
    done = subprocess.run(["git", "-c", "user.name=proofreel", "-c", "user.email=proofreel@users.noreply.github.com",
                           *args], cwd=folder, capture_output=True, text=True)
    if done.returncode:
        raise Problem(f"git {args[0]} failed: {(done.stderr or done.stdout).replace(token, '***') if token else done.stderr}")
    return done.stdout


def pages(staged, remote, dest, branch="gh-pages", attempts=6, token=""):
    """Put the staged folder at dest on the branch of remote, and keep every other folder. When another job pushes
    first, fetch the new head and put the folder there again, up to attempts times."""
    if not DEST.fullmatch(dest) or ".." in dest.split("/"):
        raise Problem(f"Bad folder name {dest!r}.")
    with tempfile.TemporaryDirectory() as work:
        git(work, "init", "-q")
        git(work, "remote", "add", "origin", remote)
        for attempt in range(attempts):
            try:
                git(work, "fetch", "-q", "--depth", "1", "origin", branch, token=token)
                git(work, "checkout", "-q", "-B", branch, "FETCH_HEAD")
            except Problem:
                if attempt == 0:
                    git(work, "checkout", "-q", "--orphan", branch)
                    (Path(work) / ".nojekyll").touch()
            shutil.rmtree(Path(work) / dest, ignore_errors=True)
            shutil.copytree(staged, Path(work) / dest)
            git(work, "add", "-A")
            if not git(work, "status", "--porcelain"):
                return
            git(work, "commit", "-q", "-m", f"proofreel: {dest}")
            try:
                git(work, "push", "-q", "origin", f"HEAD:refs/heads/{branch}", token=token)
                return
            except Problem as problem:
                if attempt == attempts - 1:
                    raise Problem(f"Could not push {branch} after {attempts} tries. {problem}") from None
                time.sleep(1 + attempt)
                git(work, "reset", "-q", "--hard")


def wait_live(url, seconds=180):
    """Wait until url answers, so the picture in a comment is not a broken link. Returns True when it did."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            with urllib.request.urlopen(url, timeout=10) as answer:
                if answer.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(5)
    return False


def context(environ=os.environ):
    """What the workflow event says: repo, pull request number, tested commit, and whether the head is a fork."""
    event = {}
    if path := environ.get("GITHUB_EVENT_PATH"):
        event = json.loads(Path(path).read_text())
    pr = event.get("pull_request") or {}
    repo = environ.get("GITHUB_REPOSITORY", "")
    return {"repo": repo, "pr": pr.get("number"), "sha": (pr.get("head") or {}).get("sha") or environ.get("GITHUB_SHA", ""),
            "fork": bool(pr) and ((pr.get("head") or {}).get("repo") or {}).get("full_name") != repo,
            "run": f"{environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repo}/actions/runs/{environ.get('GITHUB_RUN_ID', '')}"}


def publish(review, mode, ctx, token, server="https://github.com", output=None):
    """Publish a review folder. Returns (mode used, link to the review, note). pages needs a pull request from the
    same repository; else, or when the push fails, the review stays in the artifact and the note says why."""
    note = ""
    if mode == "auto":
        mode = "pages"
    if mode == "pages" and (not ctx["pr"] or ctx["fork"]):
        mode, note = "artifact", ("This pull request is from a fork, so the token cannot write to Pages." if ctx["fork"]
                                  else "Pages publishing needs a pull request.")
    link = ctx["run"]
    if mode == "pages":
        owner, name = ctx["repo"].split("/")
        remote = f"{server.replace('https://', f'https://x-access-token:{token}@')}/{ctx['repo']}.git"
        try:
            with tempfile.TemporaryDirectory() as staged:
                pages(stage(review, Path(staged) / "s"), remote, f"pr/{ctx['pr']}", token=token)
            link = f"https://{owner.lower()}.github.io/{name}/pr/{ctx['pr']}/"
            if not wait_live(link):
                note = "Pages was slow to update. The page may take a minute to show."
        except Problem as problem:
            mode, note = "artifact", f"Pages publishing failed: {str(problem).replace(token, '***') if token else problem}"
    if output:
        with open(output, "a") as out:
            out.write(f"mode={mode}\nlink={link}\nnote={note}\n")
    return mode, link, note


def md(text, limit=140):
    """Text from a run, safe in a Markdown table: one line, no pipes, no links, no HTML, no mentions."""
    text = " ".join(str(text).split()).replace("|", "/").replace("`", "'").replace("@", "@\u200b")
    text = text.replace("<", "&lt;").replace("[", "(").replace("]", ")")
    return text if len(text) <= limit else text[:limit - 1] + "..."


def result(row):
    if row["verdict"] == "works":
        return "works"
    if row["verdict"] == "shown":
        return "no checks"
    why = [f"`{md(f['text'], 80)}`" + (f" ({md(f['detail'], 60)})" if f["detail"] else "") for f in row["failed"][:2]]
    if len(row["failed"]) > 2:
        why.append(f"and {len(row['failed']) - 2} more")
    if row["error"]:
        why.append(md(row["error"]))
    return "problem: " + "; ".join(why) if why else "problem"


def comment(review, ctx, link, mode="pages", note=""):
    """The text of the pull request comment: the commit, one line for each journey, a picture, and the link."""
    rows = journeys(review)
    counts = {v: sum(r["verdict"] == v for r in rows) for v in LABEL}
    head = ", ".join(f"{counts[v]} {LABEL[v]}" for v in LABEL if counts[v]) or "no journeys"
    commit = f"[`{ctx['sha'][:7]}`]({os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{ctx['repo']}/commit/{ctx['sha']})" \
        if ctx.get("sha") else "an unknown commit"
    lines = [MARKER, f"### proofreel: {head}", "",
             f"Ran on {commit}. Each push replaces this comment.", "",
             "| Journey | Result | Time |", "|---|---|---|"]
    lines += [f"| {md(r['title'], 60)} | {result(r)} | {r['seconds']:.1f} s |" for r in rows]
    shown = next((r for r in rows if r["verdict"] == "problem"), rows[0] if rows else None)
    if mode == "pages" and shown and shown["poster"]:
        lines += ["", f"[![{md(shown['title'], 60)}]({link}{shown['poster']})]({link})"]
    lines += ["", f"[Open the full review]({link})" if mode == "pages" else
              f"[Open the run]({link}) and download the `proofreel-review` artifact at the bottom of the page."]
    if note:
        lines += ["", f"Note: {md(note, 300)}"]
    return "\n".join(lines) + "\n"


def gh(*args, **kw):
    done = subprocess.run(["gh", *args], capture_output=True, text=True, **kw)
    if done.returncode:
        raise Problem(f"gh {args[0]} failed: {done.stderr.strip()}")
    return done.stdout


def post(repo, pr, body, run=gh):
    """Write the comment on the pull request: change the one with the marker, or make it. Returns its id."""
    found = run("api", "--paginate", f"repos/{repo}/issues/{pr}/comments", "--jq",
                f'.[] | select(.user.type == "Bot" and (.body | contains("{MARKER}"))) | .id').split()
    with tempfile.NamedTemporaryFile("w", suffix=".md") as file:
        file.write(body)
        file.flush()
        if found:
            run("api", "-X", "PATCH", f"repos/{repo}/issues/comments/{found[0]}", "-F", f"body=@{file.name}")
            return found[0]
        return json.loads(run("api", f"repos/{repo}/issues/{pr}/comments", "-F", f"body=@{file.name}"))["id"]


def main(argv):
    p = argparse.ArgumentParser(prog="proofreel ci", description="Helpers for CI.")
    sub = p.add_subparsers(dest="action", required=True)
    s = sub.add_parser("check", help="print the verdicts of a review folder; exit 1 if a journey has a problem")
    s.add_argument("dir")
    s = sub.add_parser("publish", help="put a review folder on the Pages branch, or keep it in the artifact")
    s.add_argument("dir")
    s.add_argument("--mode", choices=["auto", "pages", "artifact"], default="auto")
    s = sub.add_parser("comment", help="print the pull request comment; --post writes it and the job summary")
    s.add_argument("dir")
    s.add_argument("--mode", choices=["pages", "artifact"], default="pages")
    s.add_argument("--link", required=True)
    s.add_argument("--note", default="")
    s.add_argument("--post", action="store_true")
    try:
        a = p.parse_args(argv)
    except SystemExit as stop:
        raise Problem("Usage: proofreel ci check|publish|comment <review folder>") from stop
    if a.action == "publish":
        mode, link, note = publish(a.dir, a.mode, context(), os.environ.get("GITHUB_TOKEN", ""),
                                   os.environ.get("GITHUB_SERVER_URL", "https://github.com"),
                                   os.environ.get("GITHUB_OUTPUT"))
        return print(f"{mode}: {link}" + (f"\n{note}" if note else ""))
    if a.action == "comment":
        ctx = context()
        body = comment(a.dir, ctx, a.link, a.mode, a.note)
        if not a.post:
            return print(body, end="")
        if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(summary, "a") as out:
                out.write(body)
        if ctx["pr"]:
            try:
                post(ctx["repo"], ctx["pr"], body)
            except Problem as problem:
                print(f"::warning::No comment on the pull request. {problem}")
        return
    return check(Path(a.dir))
