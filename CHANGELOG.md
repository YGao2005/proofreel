# Changelog

## Unreleased

- **`proofreel vm image`** makes the `linux` state from nothing: downloads Debian (SHA-512 checked), installs Xfce and Chromium, saves the state. The cloud-init files and the desktop script ship in the package (`proofreel/images`).
- The README says what to install for each guest, and the quickstart runs as written with the Acme Notes app.
- New `browser` extra (`websocket-client`). The QMP socket moves to the temp folder, so a deep `PROOFREEL_HOME` works. The Acme Notes notes page fits a 1024x768 screen.

## 1.0.0

The first release. proofreel records a coding agent driving an app in a VM and turns the run into a review video and a review page (a claude.ai artifact).

- **Record:** `start`, `stop`, and flows of steps, states, waits, and checks. Click by words, by the macOS accessibility tree, or by coordinates; real modifier keys in macOS guests.
- **Review page:** the video with the checks on its scrub bar; the user flow as a state machine of every run (Flow), or each state's steps and times (Steps); Tracks for the metrics, closed until you open them or a budget fails; Journeys, Stats, and Network tabs; Ask about this moment; reviews.
- **VM states:** macOS and Linux through Tart, Windows 11 ARM and Linux through QEMU. Save a state, warm or cold, and start each run from it.
- **Suites:** many journeys, each from a clean state, on one page.
- **Conditions:** `slow-network`, `offline`, `no-microphone`, `bluetooth-headset-call-mode`, `quarantined-download`, `run-from-dmg`.
- **Probes and budgets:** `host-load`, `processes`, `network`, `browser`, and input latency from the frames; `check metric` fails a run on a budget; `stats` prints a summary.
- **Crash and hang reports** from macOS guests.
- **Docs:** the README is the front page, with a tour video of the review page; the reference is in docs/. `tools/readme_media.py` makes the tour again from a review folder.
- **`proofreel --version`.**
- **License:** MIT (was PolyForm Noncommercial 1.0.0).
