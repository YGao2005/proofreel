# How it works

## The video

- **The video looks edited, but no one edits it.** A drawn pointer glides to each click on a slight arc. Each click
  presses and sends out a ring. The camera zooms in before each action, pans to the next one when it is near, and
  zooms out when the work moves on. Each step is a caption, and each action and check is a chip. Time with no
  change on the screen plays at up to 8x, with a smooth ramp in and out.
- **The video fits about 30 s.** Busy time plays at up to 2.5x when the session is long, a wait for the screen plays
  at 3x, and a badge shows the speed whenever it is above 1x.

## Screens it can record

This includes macOS and Linux VMs in Tart or UTM, QEMU, and Docker desktops with x11vnc.
  Another tool can also make the frames: give proofreel a folder of timestamped screenshots and an event log.

## The session folder

Any tool can write this folder and then run `proofreel render <dir>`. `src/proofreel/session.py` owns the format:

| File | Content |
|---|---|
| `session.json` | `{"version": 2, "title", "about", "meta": {label: value}, "error", "app", "conditions", "os", "run", "started"}` |
| `events.jsonl` | one event on each line: `{"t", "end", "kind", "text", "x", "y", "x2", "y2", "ok", "detail"}`, in unix seconds. `[t, end]` is when the action affected the screen: a click's press, the first and last key of `type`, `key`, `hold`, and `tap`, a drag's press and release, and a `wait`'s or `check`'s first look and its verdict. `end` is left out when the event has no length. The kinds are `state`, `step`, `note`, `click`, `double`, `right`, `move`, `drag`, `type`, `key`, `hold`, `tap`, `open`, `wait`, and `check` |
| `metrics/<probe>.jsonl` | what each probe printed, one measure on each line, with `a`: the unix time it arrived |
| `metrics/probes.json` | each probe's status (`ok`, `unavailable`, `silent`, `failed`), its note, and how many lines it kept and dropped |
| `reports/` | the crash and hang reports of a macOS run VM |
| `frames/*.jpg` | the screen, in name order |
| `times.txt` | `<request> <arrival>`: when each frame was asked for and when it came, one frame on each line |
| `screen.txt` | `<width> <height>`: the pixel space of the event coordinates (the frames can be smaller) |

A folder that an older proofreel wrote (no `version`) is read as version 2 and never written back. A folder from a
newer proofreel is refused. Another tool logs with times: `proofreel event click "Save" --x 10 --y 20 --t <unix s>`.

## Capture, time, camera, drawing

- **Capture** (`capture.py`): the recorder gets full VNC frames as fast as the screen changes (up to 24 a second),
  makes them half size, and saves them as JPEG on two threads. Some VNC servers send nothing while the screen stays
  the same. Apple Virtualization (Tart and UTM macOS guests) is one of these: with a menu or a file dialog open, it
  answers one full-frame request on each connection and then nothing. For these servers, a request that waits 1 s
  reconnects, because a new connection always gets a whole frame. A command that reads the screen does the same: it
  waits 2, 4, then 8 s, and then stops with a problem that says so.
- **Time** (`motion.timeline`): the renderer finds the moments when the screen changes (a 96x64 difference) or an
  action occurs. These moments play at 1x, and the time between them plays at up to 8x. The speed ramps, so the
  video has no cuts.
- **Camera** (`motion.Camera`): actions that are near in time and space form a group. In a group, the camera zooms
  in once and pans from action to action. A critically damped spring moves the camera, so it never jumps or
  overshoots.
- **Drawing** (`draw.py`): the renderer draws shapes at 4x and then scales them down, because Pillow draws without
  antialiasing. It renders the frames in parallel and sends them to ffmpeg (H.264, CRF 28).
