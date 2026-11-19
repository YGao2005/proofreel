"""Record a VNC screen into a session folder: python -m proofreel.capture <dir> <server> <password> <fps> [reduce].

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


def main(folder, server, password, fps, reduce=2):
    folder = Path(folder)
    frames = folder / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    jobs = queue.Queue(maxsize=48)

    def writer():
        while (job := jobs.get()) is not None:
            image, path = job
            image = image.convert("RGB")
            (image.reduce(reduce) if reduce > 1 else image).save(path, quality=82)

    threads = [threading.Thread(target=writer, daemon=True) for _ in range(2)]
    for thread in threads:
        thread.start()
    client = api.connect(server, password=password or None, timeout=1)
    index, size = 0, None
    with open(folder / "times.txt", "a") as times:
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
                client = api.connect(server, password=password or None, timeout=1)
                continue
            screen = client.screen.copy()
            if screen.size != size:
                size = screen.size
                (folder / "screen.txt").write_text(f"{screen.width} {screen.height}\n")
            jobs.put((screen, frames / f"{index:06d}.jpg"))
            times.write(f"{started:.3f}\n")
            times.flush()
            index += 1
            stop.wait(max(0.0, 1 / fps - (time.time() - started)))
    for _ in threads:
        jobs.put(None)
    for thread in threads:
        thread.join()
    try:
        client.disconnect()
    except Exception:
        pass
    api.shutdown()


if __name__ == "__main__":
    args = sys.argv[1:]
    main(args[0], args[1], args[2], float(args[3]), int(args[4]) if len(args) > 4 else 2)
