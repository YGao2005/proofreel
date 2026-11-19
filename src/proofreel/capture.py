"""Record a VNC screen into a session folder: python -m proofreel.capture <dir> <server> <password> <fps> [reduce] [streams].

Writes frames/<n>.jpg, times.txt (the unix time of each frame), and screen.txt (the screen size). Stops on SIGTERM.
Some VNC servers (Apple Virtualization, so Tart and UTM macOS guests) send nothing while the screen stays the same.
A capture that waits 1 s therefore reconnects, because a new connection always gets a whole frame. JPEG encoding
runs on two threads, so a slow encode does not drop the capture rate.
"""

import queue
import signal
import sys
import threading
import time
from pathlib import Path

from vncdotool import api


def main(folder, server, password, fps, reduce=0, streams=2):
    """reduce 0 keeps at most 1920 px per row. streams: VNC connections that capture in turn, because one full
    update takes a round trip, and two in flight about double the frame rate."""
    folder = Path(folder)
    frames = folder / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    jobs = queue.Queue(maxsize=48)
    lock = threading.Lock()
    state = {"index": 0, "size": None}
    times = open(folder / "times.txt", "a")

    def writer():
        while (job := jobs.get()) is not None:
            image, path = job
            image = image.convert("RGB")
            factor = reduce or -(-image.width // 1920)
            (image.reduce(factor) if factor > 1 else image).save(path, quality=90)

    def connect():
        return api.connect(server, password=password or None, timeout=1)

    def capture(offset):
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
                if stop.is_set():
                    break
                client = connect()
                continue
            screen = client.screen.copy()
            with lock:
                if screen.size != state["size"]:
                    state["size"] = screen.size
                    (folder / "screen.txt").write_text(f"{screen.width} {screen.height}\n")
                jobs.put((screen, frames / f"{state['index']:06d}.jpg"))
                times.write(f"{started:.3f}\n")
                times.flush()
                state["index"] += 1
            stop.wait(max(0.0, streams / fps - (time.time() - started)))
        try:
            client.disconnect()
        except Exception:
            pass

    writers = [threading.Thread(target=writer, daemon=True) for _ in range(3)]
    capturers = [threading.Thread(target=capture, args=(n / fps,), daemon=True) for n in range(streams)]
    for thread in writers + capturers:
        thread.start()
    while not stop.is_set():
        stop.wait(0.5)
    for thread in capturers:
        thread.join(timeout=5)
    for _ in writers:
        jobs.put(None)
    for thread in writers:
        thread.join()
    times.close()
    api.shutdown()


if __name__ == "__main__":
    args = sys.argv[1:]
    main(args[0], args[1], args[2], float(args[3]), int(args[4]) if len(args) > 4 else 0,
         int(args[5]) if len(args) > 5 else 2)
