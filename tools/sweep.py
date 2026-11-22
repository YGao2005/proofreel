"""Dev tool, not in the wheel: run the Acme Notes journeys many times and count verdicts that are not the expected ones.

    python tools/sweep.py [--runs 10] [--out sweep] [--port 8791]

Each round runs the suite once against a working server (every journey must pass) and search.flow once against a
server with BROKEN=1 (it must fail on the failed-requests budget, and only on it). It starts each server itself on
--port (default 8791), so stop any other server on it first. proofreel runs as `python -m proofreel.cli`, so
PYTHONPATH picks the code under test. The flows run in the `web` browser runner: no VM, and Chrome
on this machine.
It prints one line for each unexpected result, then the mean and the spread of how long each `wait-text` took
(timing of the checks), and exits 1 when there is an unexpected result.
"""

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

ACME = Path(__file__).resolve().parent.parent / "examples" / "acme-notes"
FAILED_REQUESTS = "net/* failed below 1 in the run"


def suite(flows, out, broken, port, *options):
    """Run a suite against a new Acme Notes server (BROKEN=1 when broken) and return the folder's runs."""
    server = subprocess.Popen([sys.executable, ACME / "server.py"], env={**os.environ, "BROKEN": "1" if broken else "", "PORT": str(port)},
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1)
        subprocess.run([sys.executable, "-m", "proofreel.cli", "suite", str(flows), "--out", str(out), "--set",
                        f"URL=http://127.0.0.1:{port}", *options], stdout=subprocess.DEVNULL, timeout=600)
    finally:
        server.terminate()
    return json.loads((out / "runs.json").read_text())["runs"]


def unexpected(run, broken):
    """Why the run's result is not the expected one, or None."""
    failed = [e["text"] for e in run["events"] if e["kind"] == "check" and not e.get("ok")]
    if run.get("error"):
        return run["error"]
    if broken and failed != [FAILED_REQUESTS]:
        return f"expected only {FAILED_REQUESTS!r} to fail, got {failed}"
    if not broken and failed:
        return f"failed: {failed}"
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--out", type=Path, default=Path("sweep"))
    ap.add_argument("--port", type=int, default=8791)
    args = ap.parse_args()
    bad = total = 0
    waits = {}
    for i in range(1, args.runs + 1):
        for broken, flows in ((False, ACME / "flows"), (True, ACME / "flows" / "search.flow")):
            out = args.out / f"{'down' if broken else 'ok'}-{i}"
            for run in suite(flows, out, broken, args.port):
                total += 1
                for e in run["events"]:
                    if e["kind"] == "wait" and (seen := re.search(r"seen after ([\d.]+) s", e.get("detail", ""))):
                        waits.setdefault((run["title"], e["text"]), []).append(float(seen[1]))
                why = unexpected(run, broken)
                if why:
                    bad += 1
                    print(f"{out / 'runs' / run['id']}: {why}")
    for (title, text), seconds in sorted(waits.items()):
        print(f"{title}: {text} mean {statistics.mean(seconds):.2f} s, spread {statistics.pstdev(seconds):.2f} s, "
              f"max {max(seconds):.2f} s (n={len(seconds)})")
    print(f"{total - bad} of {total} runs as expected.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
