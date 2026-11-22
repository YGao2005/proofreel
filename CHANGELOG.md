# Changelog

## 1.4.1

The review inbox works from a phone, and its list shows when each item came.

- **Times:** each queue item shows the clock time it was added ("1:36 PM", or "Sat 1:36 PM" on another day), and decided items show the time of the decision. The top bar of an open item shows how long it waits ("waiting 1h 11m"). The second line of an item is the agent and PR ("agent-1 · #12"), so items added in the same minute are easy to tell apart.
- **Phone layout:** under 700 px wide, the queue is a full-width screen. Tap an item to read its page, and use "Queue" to go back. The decision buttons and the notes box stay fixed at the bottom.
- **Undo and history:** a decision goes to the agent 10 s after the press, and Undo takes it back until the agent reads it. Each item keeps a copy of its page, and Sent shows that page with the decision, so you can look at it again later.
- **Full screen:** the Full screen button of a review page works inside the inbox. On an iPhone, it opens the video in the system player.
- **Private tunnels:** `proofreel inbox serve --also box.example.ts.net` makes the server accept that exact host name (and `https://` or `http://` origins from it), for example behind `tailscale serve --bg 8790`. The names are saved, and the server restarts in the background with them. The default is unchanged: only 127.0.0.1 and localhost. No wildcards, and no suffix matching. `inbox list` and `serve` print the open names.

## 1.4.0

One review inbox for every agent, and truer timing in macOS VM recordings.

- **Review inbox:** `proofreel inbox add <review folder>` queues a review page in one local inbox (http://127.0.0.1:8790), and `proofreel inbox wait <id>` blocks until the person presses Approve, Approve + next mission, Needs work, or Reject, then prints the decision. Tested end to end with Claude Code (background wait) and Codex (foreground wait). In Claude Code a background `wait` wakes the session when it exits. `inbox check --here` reads decisions later; `inbox list`, `serve`, and `stop` manage the queue. The server listens on 127.0.0.1 only, and a decision needs a per-install token. See the README.
- **Fix (macOS VMs):** a frame is timed by when it arrived. Apple's VNC server holds a frame request until the screen changes, so a frame timed by its request showed the screen after a click before the click: the video showed the next screen at the click, and latency read the click's own change as background motion ("no change on the screen in 2 s").
- **Fix:** a click that changes nothing near it (a sidebar item that changes the main pane) is looked for on the whole screen before it reads "no change on the screen".

## 1.3.0

Proof in every pull request, cheaper proofs, and steadier browser runs.

- **GitHub Action:** `uses: YGao2005/proofreel@v1` replays saved flows on each pull request, with no model and no tokens, and `YGao2005/proofreel/publish@v1` puts the review page on GitHub Pages and keeps one comment on the pull request up to date: the verdict of each journey, a picture, and a link. The run and the publishing are separate jobs, so the pull request's code never runs with write access. A journey with no checks shows as "no checks", never as a pass. See docs/ci.md.
- **Cheaper proofs:** the skill writes the whole flow and runs it with one `suite` command; the run prints a summary (each failed check with what the screen showed, and the words that appeared and went in each step), so an agent reads text, not frames. `proofreel help` is a short, task-ordered help (`help all` for every command). `suite` and `publish` print one line; the Artifact data goes to `artifact.json`. Claude Code's plugin has a `proof-runner` agent (Sonnet) that writes checks from the request, not from the code. A short proof went from 14 turns to 5 in a measured Claude Code run. `tools/agent_cost.py` measures it.
- **Clicks in the video:** each click holds the screen it clicked for 0.3 s while its ring plays, so the ring is on the control that was clicked, not on the page that came after.
- **Flaky journeys:** `suite --repeat N` runs each flow N times; a journey whose results differ is flaky, and not a pass.
- **Variants on the web:** conditions `phone`, `dark`, `slow-network`, and `offline` work in the browser runner, and `suite --each-condition plain,phone,dark` runs each flow once for each.
- **Unique data:** `${RUN}` in a flow is a new id each run, so a note saved by an earlier run cannot make a check pass.
- **Provenance:** a check that another tool reported (`event check`) is marked "reported", and each run records its git commit and a hash of its flow.
- **Steadier browser runs:** recordings set reduced motion (`--full-motion` turns it off) and a light color scheme; `open` waits for the first paint.
- **No browser left behind:** a browser that `vm up web` started ends itself after 30 min with no proofreel command (`PROOFREEL_IDLE`). The test suite fails when a test leaves Chrome running.
- When Chrome does not start, the error says whether it ended (with its exit code) or did not answer, and nothing of it is left running.

## 1.2.2

- **Fix (browser runner):** clicks and keys no longer read "no change on the screen in 2 s" when the action before them (a page load, a focus ring) changed the same pixels less than 0.6 s earlier. An input's settle time stops at the next action.
- **Fix:** a step picture shows the screen before the next action starts. In a fast flow, it showed later actions.

## 1.2.1

- The skill says to check the result where the app shows it, not the field you typed into, and to end with `proofreel vm down` so no browser or VM is left running. Both came from a real Codex run.
- The example review page moves to GitHub Pages: https://ygao2005.github.io/proofreel/example/ (recorded on the browser runner).
- The Network tab's empty-state text fits web runs.

## 1.2.0

Any agent, any runner: a web app records in a headless Chrome with no VM, and the skill works in Codex, Antigravity, Cursor, and Claude Code.

- **Any agent:** the skill no longer names Claude in its main path (the Artifact steps are a note for Claude Code), `pip install` ships it, and `proofreel skill install [--to DIR]` copies it to `~/.agents/skills` for Codex, Antigravity, and Cursor.
- **Browser runner:** a web app records in a headless, muted Chrome on the host, with no VM. `vm up web` starts it (no `vm image` or `vm base`), `vm save` keeps the profile (cookies, storage) as a state, and `vm drop` and `vm down` clean up. Flows, checks, the recording, and the page are the same as in a VM. Text comes from the page (`find`, `click-text`, `wait-text`, `check text`, `--in`), not from OCR. The run record's `vnc` and `vnc_password` are now `screen` and `screen_password`.
- New `open <url>` command for every run VM: the browser tab of `web`, `browse` in Linux, `open` in macOS, `start` in Windows. A `web` run has no shell: `vm sh`, `check sh`, and `check running` say to use `check cmd`.
- `websocket-client` is now a dependency, not only the `browser` extra.
- **Fix:** a recording with no probes no longer ends with a traceback in `recorder.log`.
- **Fix:** a `count` or `failed` budget with no data in its window now fails ("No net/* data in the run"), as the docs say. Before, `net/* failed --below 1` passed when the network probe was not installed, so a run with failed requests could pass.
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
