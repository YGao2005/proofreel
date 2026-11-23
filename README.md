# proofreel

Video proof that your coding agent's change works: the review video Devin gives you, for any coding agent.

[![PyPI](https://img.shields.io/pypi/v/proofreel)](https://pypi.org/project/proofreel/)
[![Tests](https://github.com/YGao2005/proofreel/actions/workflows/test.yml/badge.svg)](https://github.com/YGao2005/proofreel/actions/workflows/test.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Your agent uses your app as a person does, and proofreel records it. You get a short video that zooms to each action,
the user flow that the run covered, and the checks that decide pass or fail. A person can review it in a minute.

**[Open an example review page →](https://ygao2005.github.io/proofreel/example/)** Acme Notes, a made-up app: three
journeys pass, and one fails its network budget.

[![A tour of the review page: the video plays, the flow lights each state, a click jumps the video, Tracks open, and a failed run shows its failed budget, request, and numbers.](https://raw.githubusercontent.com/YGao2005/proofreel/main/docs/tour.gif)](https://raw.githubusercontent.com/YGao2005/proofreel/main/docs/tour.mp4)

## What you get

- **A review video.** The camera follows each click and key. Each step and check is a mark on the scrub bar.
- **The user flow.** The page draws the states that each run went through. A click on a state jumps the video there.
- **Checks and budgets.** Text on the screen, shell commands, processes, and measured numbers (requests, web vitals,
  input latency) pass or fail the run.
- **Any coding agent.** Claude Code, Codex, Cursor, Antigravity, or any agent that runs shell commands. proofreel
  calls no model.
- **Web and native apps.** A web app runs in a headless Chrome on your machine. A native macOS, Linux, or Windows app
  runs in a clean VM from a saved state.
- **One review inbox.** Your agents queue their proofs in one local page. Your decision goes back to the agent that
  made the proof, also from your phone.
- **CI.** A GitHub Action replays your saved flows on each pull request and comments with the result.

## Install

```bash
brew install ffmpeg          # makes the video
pip install proofreel        # Python 3.11+
proofreel demo               # renders a made-up session; open the index.html that it prints
```

A web app also needs Google Chrome. For native apps, add the VM tool for each guest that you use:

| Guest | Install |
|---|---|
| macOS | `brew install cirruslabs/cli/tart` (an Apple Silicon Mac) |
| Linux or Windows | `brew install qemu` |
| Request metrics in a Linux VM | `pip install "proofreel[network]"` (a web run needs nothing extra) |

## Connect your agent

| Agent | How |
|---|---|
| Claude Code | `/plugin marketplace add YGao2005/proofreel`, then `/plugin install proofreel@proofreel` |
| Codex, Cursor, Antigravity | `proofreel skill install` (copies the skill to `~/.agents/skills/proofreel`, which they read) |
| Any agent that runs shell commands | `proofreel skill install --to .`, then add this line to its `AGENTS.md`: `To test an app, run proofreel help and follow the skill at ./proofreel/SKILL.md.` |

Then ask your agent to prove its change. The skill tells it how to record, check, and publish.

## Quickstart

The example app is in this repo. Three journeys record and publish in about 40 seconds, with nothing on your screen:

```bash
git clone https://github.com/YGao2005/proofreel && cd proofreel
python3 examples/acme-notes/server.py &      # a made-up notes app on port 8791
proofreel suite examples/acme-notes/flows --out review-acme
open review-acme/index.html
```

Start the server with `BROKEN=1` to see a failed run: one API call returns 500, and the network budget fails. See
[`examples/acme-notes`](examples/acme-notes).

## Record a journey

An agent drives the app one command at a time:

```bash
proofreel vm up web                          # a headless Chrome, started in a second
proofreel start sign-in --title "Sign in" --about "A returning user signs in."
proofreel step "Open Acme Notes"
proofreel open http://127.0.0.1:8791/
proofreel wait-text "Welcome back" 30
proofreel click-text "Email"                 # finds the words on the screen, then clicks them
proofreel type "sam@example.com"
proofreel click-text "Sign in"
proofreel state "Notes"                      # names the place; the page draws the flow from these
proofreel wait-text "Your notes" 20
proofreel check text "Signed in as sam@example.com"
proofreel stop                               # makes the video and the page; prints the session folder
proofreel publish <session> --out review-sign-in
proofreel vm down
```

A web run measures requests (`net/*`) and web vitals with no flag, so a budget such as
`check metric net/* failed --below 1` works at once.

To run a journey again the same way, save it as a flow: a text file with one command on each line, without the word
`proofreel`. A suite runs many flows, each from a clean browser or VM:

```bash
proofreel run flows/sign-up.flow --set EMAIL=sam@example.com
proofreel suite flows/ --out review-sign-in --title "Sign in"
```

## Native apps in a VM

A native app runs in a VM from a saved state, so each run starts clean. Make a state once, install your app in it,
and start each run from it ([VM states](docs/vm-states.md)):

```bash
proofreel vm base macos-26 ghcr.io/cirruslabs/macos-tahoe-vanilla:26.0   # once: a clean macOS
proofreel vm up macos-26                     # a throwaway run VM, cloned in seconds
```

```bash
proofreel vm image                           # once: the linux state (Debian, Xfce, Chromium; about 5 minutes)
proofreel vm up linux
proofreel open http://10.0.2.2:8791/         # in a Linux VM, the host is at 10.0.2.2
```

After `vm up`, the commands are the same as for a web app. Conditions fake a user's setup, such as no microphone, an
offline network, or a quarantined download ([VM states](docs/vm-states.md)).

## Checks

| Check | Passes when |
|---|---|
| `check text <text> [seconds] [--in BOX]` | the words show on the screen in the seconds (default 10) |
| `check no-text <text> [seconds]` | the words are gone from the screen in the seconds (default 0) |
| `check cmd "<command>" [seconds]` | a shell command on the host exits 0; it runs again each second until then |
| `check sh "<command>" [seconds]` | the same, in the run VM over SSH (PowerShell on Windows) |
| `check running <process>` | a process with this exact name runs in the run VM |
| `check metric <series> <stat> --below N` | a budget on what a probe measured (or `--above N`); see [Probes and budgets](docs/probes.md) |

All commands are in [Flows, checks, and commands](docs/flows.md).

## Review the result

- **The review page.** One page holds every run of a journey: the video on the left, the user flow on the right, and
  the stats and network requests below. A failed check marks the page *Fail*, and one click jumps the video to it.
  See [The review page](docs/review-page.md).
- **The review inbox.** `proofreel inbox add` queues a page at http://127.0.0.1:8790, and `proofreel inbox wait`
  gives your Approve, Needs work, or Reject to the agent. You can undo a decision until the agent reads it.
  See [Review inbox](docs/inbox.md).
- **CI.** The GitHub Action needs no model and no tokens. See [proofreel in CI](docs/ci.md).

## Docs

| Page | Contents |
|---|---|
| [Flows, checks, and commands](docs/flows.md) | checks, flows, suites, states, crash reports, the accessibility tree, modifier keys |
| [VM states](docs/vm-states.md) | saved states, Tart (macOS and Linux), QEMU (Windows and Linux), conditions, the `linux` image |
| [Probes and budgets](docs/probes.md) | what a probe measures, `check metric`, `stats`, input latency, network requests |
| [The review page](docs/review-page.md) | the page, publishing, review folders, claude.ai features |
| [Review inbox](docs/inbox.md) | the queue, decisions, undo, phone access, security |
| [proofreel in CI](docs/ci.md) | the GitHub Action, permissions, Pages or artifact, pull requests from forks |
| [How it works](docs/how-it-works.md) | the video, screens it records, the session folder, capture, time, camera |
| [The agent skill](skills/proofreel/SKILL.md) | what your agent reads |

## Limits

- A run VM is headless and isolated: no window, no host audio, and no shared clipboard. Nothing it does shows or plays
  on the host.
- Each `PROOFREEL_VM` name (default `pr-run`) has one run VM and one recording at a time. Agents that work at the same
  time each set their own name, such as `PROOFREEL_VM=pr-a`. A Mac runs at most 2 macOS VMs at once.
- Files go to `PROOFREEL_HOME` (default `~/.proofreel`). The guest password is in each state's file. Use a throwaway
  password in a VM, never a real one.
- A VNC server sends keys as keysyms, and some apps read hardware key codes. A macOS run VM posts modifier keys in the
  guest ([Modifier keys](docs/flows.md#modifier-keys-macos-guests)).
- To record an existing VNC screen in place of a VM, set `PROOFREEL_VNC=127.0.0.1::5900` and `PROOFREEL_PASSWORD`.

## Development

```bash
pip install -e '.[network]' pytest playwright
pytest -q
```

`tools/readme_media.py review-acme` makes the tour above again, `tools/example_page.py` makes the example page, and
`tools/agent_cost.py` measures what a proof costs a coding agent in tokens. Changes are in [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE)
