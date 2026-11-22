"""One recording at a time for each run name (PROOFREEL_VM): start, log, stop, and the recorder process itself.

`start` makes the session folder and starts one detached recorder: `python -m proofreel.recording <folder> <screen>
<fps> <reduce>`, with the screen password in the environment. The recorder holds an exclusive lock on
`<folder>/recorder.lock` for as long as it lives, so "is it still recording?" never depends on a pid. It writes
frames/<n>.jpg, times.txt (the unix time of each frame), and screen.txt (the screen size), until SIGTERM. It also
runs the session's probes (see probes) as its children, in its own process group, so `stop` ends them all. The
conditions that last one recording are applied before the recorder starts, and removed at `stop`.

Some VNC servers (Apple Virtualization, so Tart macOS guests) send nothing while the screen stays the same. Each
capture asks for a whole frame, and VNC_STREAMS connections take turns, because one full update takes a round trip.
A browser screen (`cdp://`) sends a frame only when the page changes, so the recorder takes one at the start.
"""

import fcntl
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import HOME, Problem, conditions, plugins, probes, session, vm
from .screen import is_browser

SESSIONS = Path(os.environ.get("PROOFREEL_SESSIONS", HOME / "sessions"))
POINTER = HOME / f"{vm.RUN}-session.json"
VNC_STREAMS = 2
MAX_WIDTH = 1920
BEAT_SECONDS = 2
DIED = "The recorder stopped before proofreel stop."


def unstopped():
    """The session of this run name that nobody has stopped: {"dir", "pid"}, or None. Its recorder may be dead. A
    pointer to a session that never took a frame is cleared."""
    if not POINTER.exists():
        return None
    session = json.loads(POINTER.read_text())
    if not recording(Path(session["dir"])) and not (Path(session["dir"]) / "frames").exists():
        POINTER.unlink(missing_ok=True)
        return None
    return session


def current():
    """The recording of this run name: {"dir", "pid"}, or None. Only a live recorder counts."""
    session = unstopped()
    return session if session and recording(Path(session["dir"])) else None


def session_folder(name):
    """A session folder from a path or a bare session name (a folder in SESSIONS)."""
    for folder in (Path(name), SESSIONS / name):
        if (folder / "session.json").exists():
            return folder
    raise Problem(f"No session {name!r}: not a session folder, and not in {SESSIONS}.")


def recording(folder):
    """True while a recorder holds the folder's lock."""
    lock = Path(folder) / "recorder.lock"
    if not lock.exists():
        return False
    with open(lock) as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
        return False


def log(kind, text, t=None, end=None, **fields):
    """Add an event to the current recording. With no recording, do nothing."""
    if active := current():
        session.Session(active["dir"]).log(kind, text, t, end, **fields)


def start(name, server, password, info, fps=30, reduce=0, run=None):
    """Make the session folder, start the recorder, and return the folder once the first frame is on disk."""
    if active := unstopped():
        if recording(Path(active["dir"])):
            raise Problem(f"A session is recording: {active['dir']}. Stop it first: proofreel stop.")
        print(f"The recorder of {active['dir']} died. Stopping that session first: {stop(error=DIED)}", file=sys.stderr)
    folder = SESSIONS / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}"
    folder.mkdir(parents=True)
    if run:
        for line in plugins.failed(plugins.undo(run)):
            print(line, file=sys.stderr)
        run.guest.mark(run)
    probes.prepare(info.get("probes") or [], run)
    (folder / "session.json").write_text(json.dumps({"version": session.VERSION, **info, "os": run["os"] if run else None,
                                                    "run": run["id"] if run else None, "started": time.time()}))
    try:
        conditions.begin(run, [c for c in info.get("conditions", []) if c.get("recording")])
        with open(folder / "recorder.log", "w") as out:
            recorder = subprocess.Popen([sys.executable, "-m", "proofreel.recording", str(folder), server, str(fps),
                                         str(reduce)], stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                        env={**os.environ, "PROOFREEL_SCREEN_PASSWORD": password or "",
                                             "PROOFREEL_BEAT": (run or {}).get("beat", "")},
                                        start_new_session=True)
        POINTER.write_text(json.dumps({"dir": str(folder), "pid": recorder.pid}))
        deadline = time.time() + 15
        while not (folder / "frames" / "000000.jpg").exists():
            if recorder.poll() is not None or time.time() > deadline:
                POINTER.unlink(missing_ok=True)
                recorder.kill()
                raise Problem(f"The recorder did not start: {(folder / 'recorder.log').read_text().strip()[-400:] or 'no frame in 15 s'}")
            time.sleep(0.1)
        if info.get("probes"):
            probes.wait_settled(folder)
        if run:
            try:
                probes.begin(info.get("probes") or [], run)
            except Problem:
                POINTER.unlink(missing_ok=True)
                probes.end_group(recorder.pid)
                raise
    except BaseException:
        if run:
            plugins.undo(run)
        raise
    return folder


def stop(error=None, plain=False, width=None, keep_frames=False):
    """Stop the recorder, read the guest's crash reports, and render. Returns render's one-line summary."""
    active = unstopped()
    if not active:
        raise Problem("No session is recording.")
    folder = Path(active["dir"])
    for sig, seconds in ((signal.SIGTERM, 10), (signal.SIGKILL, 5)):
        if not recording(folder):
            break
        try:
            os.kill(active["pid"], sig)
        except ProcessLookupError:
            pass
        deadline = time.time() + seconds
        while recording(folder) and time.time() < deadline:
            time.sleep(0.1)
    probes.end_group(active["pid"])
    POINTER.unlink(missing_ok=True)
    (folder / "recorder.lock").unlink(missing_ok=True)
    info = json.loads((folder / "session.json").read_text())
    events = []
    if info.get("run"):
        run = vm.Run.current() if vm.CURRENT.exists() else None
        if run and run["id"] == info["run"]:
            undone = plugins.undo(run)
            events = [{"t": time.time(), "kind": "note", "text": line}
                      for line in plugins.failed([r for r in undone if r[0]["kind"] != "condition"])]
            events += [{"t": time.time(), "kind": "check", "text": f"{entry['name']} is removed", "ok": ok, "detail": said}
                       for entry, ok, said in undone if entry["kind"] == "condition"]
            events += run.guest.harvest(run, folder, info.get("app"), info.get("started", 0))
        else:
            events = [{"t": time.time(), "kind": "note", "text": "No crash reports: the run VM stopped or changed."}]
    with open(folder / "events.jsonl", "a") as out:
        for event in events:
            out.write(json.dumps(event) + "\n")
    if error:
        (folder / "session.json").write_text(json.dumps({**info, "error": error}))
    from .render import render
    summary = render(folder, framed=not plain, width=width)
    if not keep_frames:
        shutil.rmtree(folder / "frames", ignore_errors=True)
    return summary


def clean(days):
    """Delete sessions older than `days` (at least 1), except the one recording now. Returns the deleted folders."""
    cutoff = time.time() - max(days, 1) * 86400
    keep = Path((unstopped() or {}).get("dir", "/")).resolve()
    old = [f for f in SESSIONS.glob("*/") if f.resolve() != keep and f.stat().st_mtime < cutoff] \
        if SESSIONS.exists() else []
    for folder in old:
        shutil.rmtree(folder)
    return old


def save_frame(image, path, reduce):
    image = image.convert("RGB")
    factor = reduce or -(-image.width // MAX_WIDTH)
    (image.reduce(factor) if factor > 1 else image).save(path, quality=90)


def vnc_capture(server, password, offset, fps, stop, deliver, reduce):
    """One of VNC_STREAMS connections that ask for a whole frame in turn, offset seconds after the first."""
    from vncdotool import api

    def connect():
        while not stop.is_set():
            try:
                return api.connect(server, password=password or None, timeout=1)
            except Exception:
                stop.wait(0.5)

    stop.wait(offset)
    client = connect()
    while not stop.is_set():
        started = time.time()
        try:
            client.refreshScreen(incremental=False)
        except Exception:
            try:
                client.disconnect()
            except Exception:
                pass
            client = connect()
            continue
        screen = client.screen.copy()
        deliver(started, screen.size, lambda path: save_frame(screen, path, reduce))
        stop.wait(max(0.0, VNC_STREAMS / fps - (time.time() - started)))
    if client:
        try:
            client.disconnect()
        except Exception:
            pass


def record(folder, server, password, fps, reduce=0):
    """The recorder process: capture until SIGTERM, holding the folder's lock the whole time. The frames come from
    VNC_STREAMS VNC connections, or from the screencast of a browser screen (cdp.py)."""
    folder = Path(folder)
    lock = open(folder / "recorder.lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    frames = folder / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    jobs = queue.Queue(maxsize=48)
    guard = threading.Lock()
    state = {"index": 0, "size": None}
    times = open(folder / "times.txt", "a")

    def writer():
        while (job := jobs.get()) is not None:
            job()

    def deliver(requested, size, write):
        """Queue a frame: write(path) saves it. size is the pixel space of the events (screen.txt)."""
        with guard:
            if size != state["size"]:
                state["size"] = size
                (folder / "screen.txt").write_text(f"{size[0]} {size[1]}\n")
            path = frames / f"{state['index']:06d}.jpg"
            jobs.put(lambda: write(path))
            times.write(f"{requested:.3f} {time.time():.3f}\n")
            times.flush()
            state["index"] += 1

    if is_browser(server):
        from . import cdp
        emulate = json.loads((folder / "session.json").read_text()).get("emulate", [])
        sources = [lambda: cdp.screencast(server, stop, deliver, emulate)]
    else:
        sources = [lambda n=n: vnc_capture(server, password, n / fps, fps, stop, deliver, reduce)
                   for n in range(VNC_STREAMS)]
    writers = [threading.Thread(target=writer, daemon=True) for _ in range(3)]
    capturers = [threading.Thread(target=source, daemon=True) for source in sources]
    for thread in writers + capturers:
        thread.start()
    started = probes.launch(folder)
    beat = Path(os.environ["PROOFREEL_BEAT"]) if os.environ.get("PROOFREEL_BEAT") else None
    while not stop.is_set():
        if beat:
            beat.touch()
        stop.wait(BEAT_SECONDS)
    for thread in capturers:
        thread.join(timeout=5)
    for _ in writers:
        jobs.put(None)
    for thread in writers:
        thread.join()
    times.close()
    probes.finish(folder, started)
    if not is_browser(server):
        from vncdotool import api
        api.shutdown()


if __name__ == "__main__":
    args = sys.argv[1:]
    record(args[0], args[1], os.environ.get("PROOFREEL_SCREEN_PASSWORD", ""), float(args[2]),
           int(args[3]) if len(args) > 3 else 0)
