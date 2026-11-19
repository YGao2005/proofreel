---
name: proofreel
description: "Use to test an app as a real user on a clean VM or VNC screen and record the run as review proof: a video with a gliding pointer, click rings, zoom, captions, and checks, plus a page that lists each step. Also use to start a test from a saved VM state (clean OS, app installed, mid-onboarding). Triggers: record yourself doing it, review proof, demo video, first launch, onboarding, install, a bug that only shows on a clean machine."
---

# proofreel

1. Start the screen: `proofreel vm up <state>` (see `proofreel vm states`), or set `PROOFREEL_VNC` and `PROOFREEL_PASSWORD`. Pick the VM by the target:
   - A test that any browser can run: use the `linux` state (Debian, Xfce, Chromium, 1440x900).
   - A Windows app: use a Windows state.
   - A native Mac app: use a macOS VM. Use macOS for nothing else: a Mac runs only 2 macOS VMs at the same time.
   In `linux`, open a page with `proofreel vm sh 'browse <url>'`. The guest reaches a server on the host at `10.0.2.2`.
   A Windows VM starts at 1440x900. To change the size, use `vm up <state> --display WIDTHxHEIGHT`. If `up` says the screen is 1024x768 at most, run `firmware/build.sh` from the proofreel repo once.
2. `proofreel start <name> --title "<what this shows>" --about "<the user, and what must stay true>"`.
3. Drive the screen as a person does. Begin each part with `proofreel step "<part>"`. Click by words (`click-text`), not coordinates; `proofreel find` prints the words and their click points. Use `click <x> <y> --label '<what it is>'` only for a control with no words. For a key that an app watches (a push-to-talk key, a double tap), use `hold <key> <seconds>` and `tap <key> [count]`: a macOS run VM posts `fn`, `option`, `command`, `control`, and `shift` in the guest with real timing.
4. Check what the screen shows (`check text`, `check no-text`) or what the machine measures: `check sh "<guest command>" [seconds] --label` (in the run VM), `check cmd` (on the host), `check running <process>`. Never pass a check because a command ran. A failed check is a finding: report it; never run again to get a pass.
5. `proofreel stop`. Look at `index.html` and several frames of `session.mp4` before you share it.
6. To share: `proofreel publish <session> --out <scratchpad>/review-<journey>` (the same folder for every run of a journey). Publish its `index.html` with the Artifact tool: `files` = the `files` it prints, `capabilities` = the `capabilities` it prints, and the same file path (or the artifact `url`) on each later run. Comments on the page that people send to Claude reach you; read verdicts with ArtifactData (`reviews`).
7. To save a place to start later tests from: `proofreel vm save <state>` (disk) or `--warm` (memory too; a Tart run VM needs `vm up --warmable`). Name states by what is true: `app-installed-no-permissions`, `signed-in-empty`.

8. For a bug that needs a setup you do not have (a Bluetooth headset, no microphone, offline, an app run from its DMG or from Downloads), build a state with conditions: `proofreel vm build <state> --from <base> --condition <name>` (list: `proofreel vm conditions`). Put `condition <name>` at the top of the flow. Read the fidelity notes before you trust a pass.
9. Start each recording of a macOS app with `--app <name>`. A crash of the app then fails the run and the page shows its stack. Never call a run good when the app window went away: read `reports/`.

Write repeat journeys as flow files (one proofreel command per line, `${NAME:-default}` values) and run them with `proofreel run`. Use made-up data only.
