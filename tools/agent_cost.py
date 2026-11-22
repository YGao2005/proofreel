"""Dev tool, not in the wheel: measure what a proof costs a coding agent, in tokens.

    python tools/agent_cost.py [--agent claude|codex|both] [--task search] [--context N]
                               [--proofreel SPEC] [--dir DIR] [--baseline results.json]

Each run starts in a fresh copy of examples/acme-notes with only the skill installed, and has its own PROOFREEL_HOME
and its own server port. A baseline run (the agent only says OK) gives what the agent costs just to start; the table
shows the proof run minus that baseline. --context N puts about N tokens of neutral text at the top of the prompt
(Codex cuts an AGENTS.md at 32 KiB), so the agent starts with a context of a real session. --proofreel is what pip installs into
the tool's own venv: a path (default: this checkout) or a name such as proofreel==1.2.2, to compare versions.
The agents run one after another with no permission prompts, and they cost money: Claude's cost is the USD it reports, Codex reports
none. The work folder is kept (raw logs, review pages, results.json); its path is printed. --baseline takes the
results.json of an earlier run and reuses its baseline runs (same agent and context), which saves their cost.
"""

import argparse
import json
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACME = ROOT / "examples" / "acme-notes"
TASKS = {
    "search": "Search by title already works in this app; the server is running at {url}. Prove it works with "
              "proofreel: record a short proof that searching notes by title shows the matching note. Then tell me "
              "the verdict and the path of the review page.",
}
BASELINE = "Reply with the word OK and do nothing else."
WORDS = ("release note wiki ticket branch review style guide naming folder lower case team weekly build queue "
         "owner cache table field value config deploy rollback metric alert dashboard sprint backlog label").split()
AGENTS = ("claude", "codex")


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def filler(tokens):
    """About this many tokens of neutral project notes (4 characters to a token), the same text every time."""
    rng, lines, size = random.Random(1), [], 0
    while size < tokens * 4:
        line = f"Note {len(lines) + 1}: " + " ".join(rng.choices(WORDS, k=14)) + "."
        lines.append(line)
        size += len(line) + 1
    return "# Project notes\n\n" + "\n".join(lines) + "\n"


def prepare(folder, venv):
    """A fresh copy of Acme Notes in folder/app with the skill for Claude and for Codex. Returns the app folder."""
    app = folder / "app"
    shutil.copytree(ACME, app, ignore=shutil.ignore_patterns("__pycache__"))
    for skills in (".claude/skills", ".agents/skills"):
        subprocess.run([venv / "bin" / "proofreel", "skill", "install", "--to", app / skills],
                       check=True, capture_output=True)
    return app


def command(agent, prompt, app):
    if agent == "claude":
        return ["claude", "-p", prompt, "--output-format", "json", "--permission-mode", "bypassPermissions"]
    return ["codex", "exec", "--json", "-s", "danger-full-access", "--skip-git-repo-check", "-C", str(app), prompt]


def tally(agent, out):
    """The numbers of one run: new input, output, cache reads, turns (Claude) or commands (Codex), USD, last message."""
    if agent == "claude":
        data = json.loads(out)
        use = data.get("usage", {})
        return dict(new=use.get("input_tokens", 0) + use.get("cache_creation_input_tokens", 0),
                    out=use.get("output_tokens", 0), cache=use.get("cache_read_input_tokens", 0),
                    turns=data.get("num_turns", 0), usd=data.get("total_cost_usd") or 0.0, text=data.get("result") or "")
    events = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    if failed := next((e for e in events if e.get("type") in ("error", "turn.failed")), None):
        sys.exit(f"codex failed: {failed.get('message') or failed.get('error')}")
    done = [e for e in events if e.get("type") == "item.completed"]
    use = [e["usage"] for e in events if e.get("type") == "turn.completed"]
    cache = sum(u.get("cached_input_tokens", 0) for u in use)
    messages = [e["item"].get("text", "") for e in done if e["item"].get("type") == "agent_message"]
    return dict(new=sum(u.get("input_tokens", 0) for u in use) - cache, out=sum(u.get("output_tokens", 0) for u in use),
                cache=cache, turns=sum(e["item"].get("type") == "command_execution" for e in done), usd=0.0,
                text=messages[-1] if messages else "")


def review(home, text):
    """(verdict, review page path) of a run: the path the agent gave, else the newest session's page."""
    sessions = sorted(Path(home).glob("sessions/*/run.json"), key=lambda p: p.stat().st_mtime)
    verdict = json.loads(sessions[-1].read_text()).get("verdict", "?") if sessions else "none"
    given = re.findall(r"(/[^\s`'\"()]+index\.html)", text)
    page = given[-1] if given and Path(given[-1]).exists() else str(sessions[-1].parent / "index.html") if sessions else ""
    return verdict, page


def measure(agent, kind, prompt, folder, venv, context):
    """Run the agent once in a fresh app. Returns its numbers, with the verdict and the review page."""
    folder.mkdir(parents=True)
    app = prepare(folder, venv)
    home = folder / "home"
    env = {**os.environ, "PATH": f"{venv / 'bin'}{os.pathsep}{os.environ['PATH']}", "PROOFREEL_HOME": str(home)}
    port = free_port()
    server = subprocess.Popen([sys.executable, app / "server.py"], env={**env, "PORT": str(port)},
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1)
        started = time.time()
        text = (filler(context) if context else "") + prompt.format(url=f"http://127.0.0.1:{port}")
        done = subprocess.run(command(agent, text, app), cwd=app, env=env, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=900)
        (folder / "out.json").write_text(done.stdout)
        (folder / "err.txt").write_text(done.stderr)
        if done.returncode and not done.stdout.strip():
            sys.exit(f"{agent} stopped with exit {done.returncode}: {done.stderr.strip()[-400:]}")
        row = tally(agent, done.stdout)
        row["seconds"] = round(time.time() - started)
        row["verdict"], row["page"] = review(home, row["text"]) if kind == "proof" else ("", "")
        return row
    finally:
        server.terminate()
        subprocess.run([venv / "bin" / "proofreel", "vm", "down"], env=env, capture_output=True)


def table(results):
    head = f"{'agent':7} {'context':>8} {'new in':>8} {'out':>7} {'cache reads':>12} {'turns':>6} {'USD':>6} {'s':>4}  verdict  page"
    print(head)
    for (agent, context), (base, proof) in results.items():
        diff = {k: proof[k] - base[k] for k in ("new", "out", "cache", "turns", "usd", "seconds")}
        usd = f"{diff['usd']:.2f}" if agent == "claude" else "-"
        print(f"{agent:7} {context:>8} {diff['new']:>8} {diff['out']:>7} {diff['cache']:>12} {diff['turns']:>6} "
              f"{usd:>6} {diff['seconds']:>4}  {proof['verdict']:7}  {proof['page']}")
    print("Each row: the proof run minus the baseline run of the same agent and context.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--agent", choices=[*AGENTS, "both"], default="both")
    p.add_argument("--task", choices=TASKS, default="search")
    p.add_argument("--context", type=int, default=0, help="pad the starting context to about this many tokens")
    p.add_argument("--proofreel", default=str(ROOT), help="what pip installs: a path or a name (default: this checkout)")
    p.add_argument("--baseline", help="the results.json of an earlier run: reuse its baseline runs")
    p.add_argument("--dir", help="the work folder (default: a new temporary folder)")
    a = p.parse_args()
    work = Path(a.dir or tempfile.mkdtemp(prefix="agent-cost-")).resolve()
    work.mkdir(parents=True, exist_ok=True)
    venv = work / "venv"
    if not venv.exists():
        subprocess.run(["uv", "venv", "-q", venv], check=True)
        subprocess.run(["uv", "pip", "install", "-q", "--python", venv / "bin" / "python", a.proofreel], check=True)
    version = subprocess.run([venv / "bin" / "proofreel", "--version"], capture_output=True, text=True).stdout.strip()
    print(f"{version}; work folder {work}")
    earlier = json.loads(Path(a.baseline).read_text()) if a.baseline else {}
    results = {}
    for agent in AGENTS if a.agent == "both" else [a.agent]:
        base = earlier.get(f"{agent}:{a.context}", [None])[0] or \
            measure(agent, "base", BASELINE, work / f"{agent}-base", venv, a.context)
        runs = [base, measure(agent, "proof", TASKS[a.task], work / f"{agent}-proof", venv, a.context)]
        results[(agent, a.context)] = runs
        print(f"{agent} proof said: {runs[1]['text'][-300:]!r}")
    table(results)
    (work / "results.json").write_text(json.dumps({f"{k[0]}:{k[1]}": v for k, v in results.items()}, indent=1))


if __name__ == "__main__":
    main()
