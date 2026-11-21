# Changelog

## Unreleased

- Tracks start folded on every run, also when a budget failed; the Budget failed chip still shows on the folded row. Opened, they stay open while you switch runs.
- In Flow, a click on a state that this run did not visit opens a run that did, at that state (a run where it failed first, else the newest). The "In other runs" buttons also go to the state.

## 1.1.0

- **Review page redesign:** a Pass, Fail, or No checks verdict by the title, with a cause line that jumps to the first failure (a click on a failed request opens Network); Approve and Needs work beside the title; one type and colour system (IBM Plex); a redrawn Flow with its details under it; Tracks with a time axis that lines up with the scrub bar; a Network waterfall; one Stats table that writes each budget as a sentence; keyboard keys (Space, arrows, J, K, N, Esc) and a `#run-N&t=SECONDS` link. Budgets count apart from screen checks.
- QEMU guests are 1440x900 after a plain `pip install`: the edk2 firmware that takes any screen size ships in the package (1.6 MB packed, BSD-2-Clause-Patent). Its build script moves to `src/proofreel/firmware/`.

## 1.0.0

The first release. proofreel records a coding agent driving an app in a VM and turns the run into a review video and a review page (a claude.ai artifact).

- **Record:** `start`, `stop`, and flows of steps, states, waits, and checks. Click by words, by the macOS accessibility tree, or by coordinates; real modifier keys in macOS guests.
- **Review page:** the video with the checks on its scrub bar; the user flow as a state machine of every run (Flow), or each state's steps and times (Steps); Tracks for the metrics, closed until you open them or a budget fails; Journeys, Stats, and Network tabs; Ask about this moment; reviews.
- **VM states:** macOS and Linux through Tart, Windows 11 ARM and Linux through QEMU. Save a state, warm or cold, and start each run from it.
- **Suites:** many journeys, each from a clean state, on one page.
- **Conditions:** `slow-network`, `offline`, `no-microphone`, `bluetooth-headset-call-mode`, `quarantined-download`, `run-from-dmg`.
- **Probes and budgets:** `host-load`, `processes`, `network`, `browser`, and input latency from the frames; `check metric` fails a run on a budget; `stats` prints a summary.
- **Crash and hang reports** from macOS guests.
- **`proofreel vm image`** makes the `linux` state from nothing: it downloads Debian (SHA-512 checked), installs Xfce and Chromium, and saves the state.
- **Claude Code plugin:** `/plugin marketplace add YGao2005/proofreel`, then `/plugin install proofreel@proofreel`.
- **Docs:** the README is the front page, with a tour video of the review page; the reference is in docs/. `tools/readme_media.py` makes the tour again from a review folder.
- **`proofreel --version`.**
- **License:** MIT (was PolyForm Noncommercial 1.0.0).
