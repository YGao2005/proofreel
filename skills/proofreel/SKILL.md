---
name: proofreel
description: "Use to test an app as a real user in a headless browser, a clean VM, or a VNC screen and record the run as review proof: a video with a gliding pointer, click rings, zoom, captions, and checks, plus a page that lists each step. Also use to start a test from a saved VM state (clean OS, app installed, mid-onboarding). Triggers: record yourself doing it, review proof, demo video, first launch, onboarding, install, a bug that only shows on a clean machine."
---

# proofreel

1. Start the screen. Pick the runner by the target (`proofreel vm states` lists the states):
   - A web app: `proofreel vm up web`. It is a headless browser on this machine, with no VM. Open a page with `proofreel open <url>`. A server on this machine is at `127.0.0.1`.
   - A native Mac app: use a macOS VM state. Use macOS for nothing else: a Mac runs only 2 macOS VMs at the same time.
   - A Windows or Linux app: use a `windows` or `linux` state.
   Or set `PROOFREEL_VNC` and `PROOFREEL_PASSWORD` for a screen that you already have.
   A Windows VM starts at 1440x900. To change the size, use `vm up <state> --display WIDTHxHEIGHT`.
2. `proofreel start <name> --title "<what this shows>" --about "<the user, and what must stay true>"`.
3. Drive the screen as a person does. When the app should be at a new place (a page, a screen, a dialog), write `proofreel state "<place>"`, then the wait or check that proves it. Use the same name for the same place in every flow: the page joins the runs into one state machine. Begin each part with `proofreel step "<part>"`. Click by words (`click-text`), not coordinates; `proofreel find` prints the words and their click points. Use `click <x> <y> --label '<what it is>'` only for a control with no words. To hover, `move <x> <y>`, then check what the hover shows. For a key that an app watches (a push-to-talk key, a double tap), use `hold <key> <seconds>` and `tap <key> [count]`: a macOS run VM posts `fn`, `option`, `command`, `control`, and `shift` in the guest with real timing.
4. Check what the screen shows (`check text`, `check no-text`) or what the machine measures: `check sh "<guest command>" [seconds] --label` (in the run VM), `check cmd` (on the host), `check running <process>`. For speed or load, set a budget: `check metric <series> <stat> --below N` (`proofreel probes` lists what can be measured; `host-load` is always on). Never pass a check because a command ran. A failed check is a finding: report it; never run again to get a pass.
5. `proofreel stop`. Look at `index.html` and several frames of `session.mp4` before you share it.
6. To share: `proofreel publish <session> --out <scratchpad>/review-<journey>` (the same folder for every run of a journey). Give the person the path of the review folder's `index.html`; it opens in any browser as a file.
   - If you have an Artifact tool (Claude Code): publish `index.html` with it. `files` = the `files` it prints, `capabilities` = the `capabilities` it prints, and the same file path (or the artifact `url`) on each later run. Comments on the page that people send to Claude reach you; read verdicts with ArtifactData (`reviews`).
7. To save a place to start later tests from: `proofreel vm save <state>` (disk) or `--warm` (memory too; a Tart run VM needs `vm up --warmable`). Name states by what is true: `app-installed-no-permissions`, `signed-in-empty`.

8. For a bug that needs a setup you do not have (a Bluetooth headset, no microphone, offline, an app run from its DMG or from Downloads), build a state with conditions: `proofreel vm build <state> --from <base> --condition <name>` (list: `proofreel vm conditions`). Put `condition <name>` at the top of the flow. For a slow or choppy network, put `condition slow-network:profile=3g` (or `edge`, `lossy-wifi`, or values such as `latency=200ms,loss=5%`) at the top of the flow: it lasts one recording, with no state. Read the fidelity notes before you trust a pass.
9. Start each recording of a macOS app with `--app <name>`. A crash of the app then fails the run and the page shows its stack. Never call a run good when the app window went away: read `reports/`.

Write repeat journeys as flow files (one proofreel command per line, `${NAME:-default}` values) and run them with `proofreel run`. Use made-up data only.

For many journeys of one feature, put `from <state>` (a saved VM state) at the top of each flow and run `proofreel suite <folder> --out <scratchpad>/review-<feature>`. Each flow gets a new clone of its state, so each starts from the same place. Share the suite's `index.html` as in step 6: its Journeys tab lists every journey with its result. An Artifact publish takes at most 255 files: for a bigger folder, publish `new` first, then the rest in batches to the same `url`.

When the same words show twice (a dialog title and its button), use `click-text <text> --role AXButton` in a macOS VM, or `--in x,y,w,h`. Use `--in` on `check text` so that it reads only the part of the screen that you mean.
