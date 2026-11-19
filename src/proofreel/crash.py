"""Crash and hang reports from a macOS guest.

`start` marks the session start in the guest. `stop` copies the .ips, .hang, and .spin reports newer than the mark
from ~/Library/Logs/DiagnosticReports and /Library/Logs/DiagnosticReports into <session>/reports, and logs each one.
A crash or hang of the app under test (`start --app NAME`) is a failed check, with the process, the exception type,
and the top frames of the crashed thread. Without --app, a crash of any process is a failed check. Other reports are
notes. A crash during a run never passes quietly.
"""

import json
import re
import shlex
import time
from datetime import datetime
from pathlib import Path

MARK = "/tmp/proofreel-session-start"
FOLDERS = "~/Library/Logs/DiagnosticReports /Library/Logs/DiagnosticReports"
KINDS = (".ips", ".hang", ".spin")
TOP = 8
LATE = 120


def mark(run):
    run.ssh(f"touch {MARK}", check=False, timeout=20)


def when(text):
    for pattern in ("%Y-%m-%d %H:%M:%S.%f %z", "%Y-%m-%d %H:%M:%S %z"):
        try:
            return datetime.strptime(text.strip(), pattern).timestamp()
        except (ValueError, AttributeError):
            pass
    return None


def frames(stack, images):
    lines = []
    for number, frame in enumerate(stack[:TOP]):
        index = frame.get("imageIndex", -1)
        image = images[index].get("name", "?") if 0 <= index < len(images) else "?"
        symbol = frame.get("symbol")
        where = f"{symbol} + {frame.get('symbolLocation', 0)}" if symbol else hex(frame.get("imageOffset", 0))
        lines.append(f"  {number} {image}  {where}")
    return lines


def parse(name, text):
    """A report's summary: {file, process, bundle, kind (crash, hang, or report), time, summary}."""
    if not name.endswith(".ips"):
        process = re.search(r"^Process:\s+(.+?)(?:\s+\[\d+\])?\s*$", text, re.M)
        duration = re.search(r"^Duration:\s+(.+)$", text, re.M)
        date = re.search(r"^Date/Time:\s+(.+)$", text, re.M)
        process = process[1] if process else "?"
        return {"file": name, "process": process, "bundle": "", "kind": "hang", "time": when(date[1]) if date else None,
                "summary": f"{process} hang" + (f", {duration[1].strip()}" if duration else "")}
    head, _, body = text.partition("\n")
    head = json.loads(head)
    try:
        data = json.loads(body)
    except ValueError:
        data = {}
    process = data.get("procName") or head.get("app_name") or head.get("name") or "?"
    exception = data.get("exception") or {}
    crashed = head.get("bug_type") == "309" and not head.get("is_simulated") and bool(exception)
    kind = " ".join(x for x in (exception.get("type"), f"({exception['signal']})" if exception.get("signal") else "")
                    if x) or f"bug type {head.get('bug_type')}"
    lines = [f"{process}: {kind}"]
    lines += [text for texts in (data.get("asi") or {}).values() for text in texts]
    images, threads, faulting = data.get("usedImages") or [], data.get("threads") or [], data.get("faultingThread", 0)
    if crashed and 0 <= faulting < len(threads):
        lines += [f"Thread {faulting} crashed:", *frames(threads[faulting].get("frames", []), images)]
    if crashed and data.get("lastExceptionBacktrace"):
        lines += ["Last exception backtrace:", *frames(data["lastExceptionBacktrace"], images)]
    return {"file": name, "process": process, "kind": "crash" if crashed else "report",
            "bundle": head.get("bundleID") or (data.get("bundleInfo") or {}).get("CFBundleIdentifier", ""),
            "time": when(data.get("captureTime") or head.get("timestamp")), "summary": "\n".join(lines)}


def ours(report, app):
    return not app or app.lower() in (report["process"].lower(), report["bundle"].lower())


def events(reports, app, start, end):
    """The log events for the reports: failed checks for the app under test, notes for the rest."""
    out, failed = [], False
    for report in reports:
        t = report["time"] if report["time"] and start <= report["time"] <= end else end
        if report["kind"] == "crash" and ours(report, app) or report["kind"] == "hang" and app and ours(report, app):
            failed = True
            out.append({"t": t, "kind": "check", "text": f"{report['process']} did not {report['kind']}", "ok": False,
                        "detail": report["summary"]})
        else:
            out.append({"t": t, "kind": "note", "text": f"{report['process']}: {report['kind']} report {report['file']}",
                        "detail": report["summary"]})
    if app and not failed:
        out.append({"t": end, "kind": "check", "text": f"{app} did not crash or hang", "ok": True,
                    "detail": f"{len(reports)} other report(s) in the guest" if reports else "no report in the guest"})
    return out


def listing(run):
    names = " -o ".join(f"-name '*{kind}'" for kind in KINDS)
    found = run.ssh(f"sudo -n find {FOLDERS} -maxdepth 1 -type f \\( {names} \\) -newer {MARK} 2>/dev/null",
                   check=False, timeout=30)
    return [line for line in found.stdout.splitlines() if line.strip()]


def harvest(run, folder, app=None, start=0.0):
    """Copy the new reports into folder/reports and return their log events. If the app under test is gone and left
    no report yet, wait up to LATE seconds: ReportCrash writes the report a few seconds after the crash."""
    end = time.time()
    paths = listing(run)
    if app and run.ssh(f"pgrep -xq {shlex.quote(app)}", check=False, timeout=20).returncode:
        give_up = time.time() + LATE
        while time.time() < give_up and not any(Path(p).name.lower().startswith(app.lower()) for p in paths):
            time.sleep(2)
            paths = listing(run)
    reports = []
    for path in paths:
        text = run.ssh(f"sudo -n cat {shlex.quote(path)}", check=False, timeout=60).stdout
        (folder / "reports").mkdir(exist_ok=True)
        (folder / "reports" / Path(path).name).write_text(text)
        try:
            reports.append(parse(Path(path).name, text))
        except ValueError:
            reports.append({"file": Path(path).name, "process": "?", "bundle": "", "kind": "report", "time": None,
                            "summary": "The report could not be read."})
    return events(reports, app, start, end)
