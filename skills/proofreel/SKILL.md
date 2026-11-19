---
name: proofreel
description: "Use to test an app as a real user on a clean VM or VNC screen and record the run as review proof: a video with a gliding pointer, click rings, zoom, captions, and checks, plus a page that lists each step. Also use to start a test from a saved VM state (clean OS, app installed, mid-onboarding). Triggers: record yourself doing it, review proof, demo video, first launch, onboarding, install, a bug that only shows on a clean machine."
---

# proofreel

1. Start the screen: `proofreel vm up <state>` (see `proofreel vm states`), or set `PROOFREEL_VNC` and `PROOFREEL_PASSWORD`.
2. `proofreel start <name> --title "<what this shows>" --about "<the user, and what must stay true>"`.
3. Drive the screen as a person does. Begin each part with `proofreel step "<part>"`. Click by words (`click-text`), not coordinates; `proofreel find` prints the words and their click points. Use `click <x> <y> --label '<what it is>'` only for a control with no words.
4. Check what the screen shows (`check text`, `check no-text`) or what the machine measures (`check cmd ... --label`). Never pass a check because a command ran. A failed check is a finding: report it; never run again to get a pass.
5. `proofreel stop`. Look at `index.html` and several frames of `session.mp4` before you share it.
6. To share: `proofreel publish <session> --out <scratchpad>/review-<journey>` (the same folder for every run of a journey). Publish its `index.html` with the Artifact tool: `files` = the `files` it prints, `capabilities` = the `capabilities` it prints, and the same file path (or the artifact `url`) on each later run. Comments sent to Claude from a step reach you; read verdicts with ArtifactData (`reviews`).
7. To save a place to start later tests from: `proofreel vm save <state>` (disk) or `--warm` (memory too; the run VM needs `vm up --warmable`). Name states by what is true: `app-installed-no-permissions`, `signed-in-empty`.

Write repeat journeys as flow files (one proofreel command per line, `${NAME:-default}` values) and run them with `proofreel run`. Use made-up data only.
