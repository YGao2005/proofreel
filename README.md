# proofreel

Review proof for computer-use agents. proofreel records an agent as it drives a real screen, then makes a short
review video and a page that a person can check in a minute.

- **The video looks edited, but no one edits it.** A drawn pointer glides to each click on a slight arc. Each click
  presses and sends out a ring. The camera zooms in before each action, pans to the next one when it is near, and
  zooms out when the work moves on. Each step is a caption, and each action and check is a chip. Time with no
  change on the screen plays at up to 8x, with a smooth ramp in and out.
- **The page is the review.** It has the video, a scrub bar with a mark for each step and check, and the list of
  actions with thumbnails. A click on a row jumps the video to that moment. A failed check marks the page *Problem*.
- **Saved states for VMs.** Save a VM as a named state, such as `clean-os`, `app-installed`, or
  `signed-in-mid-onboarding`. Then start each test from that state in seconds. A warm state keeps the memory, so the
  test starts with the apps already open. A state that a flow makes records the flow, so you can make it again when
  the app changes.
- **Any VNC screen.** This includes macOS and Linux VMs in Tart or UTM, QEMU, and Docker desktops with x11vnc.
  Another tool can also make the frames: give proofreel a folder of timestamped screenshots and an event log.

```bash
pip install proofreel        # Python 3.11+, and ffmpeg on PATH
proofreel demo               # a made-up session, no VNC needed: open the index.html it prints
```

## Record a session

```bash
export PROOFREEL_VNC=127.0.0.1::5900 PROOFREEL_PASSWORD=...   # or: proofreel vm up <state>
proofreel start sign-up --title "Sign up" --about "A new user makes an account."
proofreel step "Fill in the form"
proofreel click-text "Email"                 # finds the words on the screen, then clicks them
proofreel type "sam@example.com"
proofreel key tab
proofreel click 1210 830 --label 'click "Create account"'
proofreel wait-text "Welcome" 30
proofreel check text "Welcome, Sam"          # a pass or fail on the page
proofreel check cmd "curl -sf localhost:8080/health" --label "The server is up"
proofreel stop                               # makes session.mp4, index.html, poster.jpg, shots/
```

Each command is one action, so an agent can drive the screen with the commands alone. To find words on the screen,
proofreel uses Apple Vision on macOS hosts and Tesseract on other hosts.

### Flows

A flow is a text file with one proofreel command on each line. Use `#` for comments, and `${NAME}` or
`${NAME:-default}` for values that you set with `--set NAME=value`. A failed `check` is recorded, and the flow
continues. Any other failure stops the flow, and the page shows where it stopped.

```bash
proofreel run flows/sign-up.flow --set EMAIL=sam@example.com
```

### When another tool drives the screen

Log what the other tool does, and proofreel records and renders it in the same way:

```bash
proofreel event click 'click "Save"' --x 640 --y 410
proofreel event check "The file is saved" --ok
```

## VM states (Tart)

```bash
proofreel vm base macos-26 ghcr.io/cirruslabs/macos-tahoe-vanilla:26.0   # once: a clean OS
proofreel vm up macos-26 --warmable           # a throwaway run VM, cloned in seconds
proofreel vm put MyApp.dmg /Users/admin/Downloads/
# ... install the app, stop before any permission prompt ...
proofreel vm save app-installed               # cold: the disk only
# ... go on through onboarding to the step you want ...
proofreel vm save mid-onboarding --warm       # warm: the memory too, so the app is still open
proofreel vm states
#   macos-26        2026-11-18 20:10
#     app-installed 2026-11-18 20:25
#       mid-onboarding 2026-11-18 20:31  [warm]
proofreel vm up mid-onboarding                # each test starts here
proofreel vm build app-installed --from macos-26 --flow flows/install.flow --set DMG=MyApp-1.2.dmg
proofreel vm down
```

A clone is copy on write (APFS), so a state costs only the disk blocks that it changes. A warm state needs a run VM
that was started with `--warmable`. Tart then turns off the VM's audio devices, so do not test a microphone in a
warm VM.

## The session folder

Any tool can write this folder and then run `proofreel render <dir>`:

| File | Content |
|---|---|
| `session.json` | `{"title", "about", "meta": {label: value}, "error"}` |
| `events.jsonl` | one action on each line: `{"t": unix seconds, "kind", "text", "x", "y", "ok", "detail"}`. The kinds are `step`, `note`, `click`, `double`, `right`, `move`, `drag` (`x2`, `y2`), `type`, `key`, `open`, `wait`, and `check` |
| `frames/*.jpg` | the screen, in name order |
| `times.txt` | the unix time of each frame, one on each line |
| `screen.txt` | `<width> <height>`: the pixel space of the event coordinates (the frames can be smaller) |

## How it works

- **Capture** (`capture.py`): the recorder gets full VNC frames as fast as the screen changes (up to 24 a second),
  makes them half size, and saves them as JPEG on two threads. Some VNC servers send nothing while the screen stays
  the same. Apple Virtualization (Tart and UTM macOS guests) is one of these. For these servers, a request that
  waits 1 s reconnects, because a new connection always gets a whole frame.
- **Time** (`motion.timeline`): the renderer finds the moments when the screen changes (a 96x64 difference) or an
  action occurs. These moments play at 1x, and the time between them plays at up to 8x. The speed ramps, so the
  video has no cuts.
- **Camera** (`motion.Camera`): actions that are near in time and space form a group. In a group, the camera zooms
  in once and pans from action to action. A critically damped spring moves the camera, so it never jumps or
  overshoots.
- **Drawing** (`draw.py`): the renderer draws shapes at 4x and then scales them down, because Pillow draws without
  antialiasing. It renders the frames in parallel and sends them to ffmpeg (H.264, CRF 28).

## Limits

- One run VM at a time for each `PROOFREEL_VM` name. macOS lets a Mac run at most 2 macOS VMs at once.
- A VNC server sends keys as keysyms. Some apps read hardware key codes or modifier-only keys, such as a key that
  you hold down. Send those keys from in the guest instead, and log them with `proofreel event key ...`.

## License

MIT
