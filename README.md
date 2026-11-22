# proofreel

Video proof that your coding agent's change works: the review video Devin gives you, for any coding agent.

Your agent (Claude Code, Codex, or any agent that runs shell commands) uses your app as a person would, and proofreel
records it. A web app runs in a headless browser on your machine; a native Mac, Linux, or Windows app runs in a clean VM.
You get a short video that zooms to each action, the user flow it covered, and the checks and numbers that decide pass
or fail, on a review page that a person can check in a minute.

**[See a real review page →](https://ygao2005.github.io/proofreel/example/)** (the Acme Notes example: three
journeys that pass and one with a failed network budget)

[![A tour of the review page: the video plays, the flow lights each state, a click jumps the video, Tracks open, and a failed run shows its failed budget, request, and numbers.](https://raw.githubusercontent.com/YGao2005/proofreel/main/docs/tour.gif)](https://raw.githubusercontent.com/YGao2005/proofreel/main/docs/tour.mp4)

## Install

```bash
brew install ffmpeg          # it makes the video
pip install proofreel        # Python 3.11+, on an Apple Silicon Mac; a web app needs Chrome too
proofreel demo               # a made-up session: open the index.html it prints
```

For native apps, add the VM tools for the guests you use (see [Native apps in a VM](#native-apps-in-a-vm)):

- `brew install cirruslabs/cli/tart`: for a macOS guest (Tart).
- `brew install qemu`: for a Linux or Windows guest (QEMU).
- `pip install "proofreel[network]"`: the proxy that measures requests in a Linux VM (a web run needs no extra).

To let Claude Code drive it, add the plugin in Claude Code:

```text
/plugin marketplace add YGao2005/proofreel
/plugin install proofreel@proofreel
```

## Use it with your agent

| Agent | How |
|---|---|
| Claude Code | The plugin above. |
| Codex, Antigravity, Cursor | `proofreel skill install` (copies the skill to `~/.agents/skills/proofreel`, which they read). |
| Any other agent that runs shell commands | Run `proofreel skill install --to .`, then add this line to its `AGENTS.md`: `To test an app, run proofreel help and follow the skill at ./proofreel/SKILL.md.` |

## Quickstart

A web app runs in a headless Chrome on your machine: nothing shows on screen, and there is no VM and no image to make.
The example app is in this repo. Three flows record and publish in about 40 seconds (measured on an Apple Silicon Mac):

```bash
git clone https://github.com/YGao2005/proofreel && cd proofreel
python3 examples/acme-notes/server.py &      # a made-up app on port 8791
proofreel suite examples/acme-notes/flows --out review-acme
open review-acme/index.html
```

The same journey by hand, one command at a time:

```bash
proofreel vm up web                          # a headless Chrome, started in a second
proofreel start sign-in --title "Sign in" --about "A returning user signs in."
proofreel step "Open Acme Notes"
proofreel open http://127.0.0.1:8791/        # the app is on this machine, at 127.0.0.1
proofreel wait-text "Welcome back" 30
proofreel click-text "Email"                 # finds the words on the page, then clicks them
proofreel type "sam@example.com"
proofreel key tab
proofreel click-text "Sign in"
proofreel wait-text "Your notes" 20
proofreel check text "Signed in as sam@example.com"   # a pass or fail on the page
proofreel stop                               # makes session.mp4, index.html, poster.jpg, shots/
proofreel publish <session> --out review-sign-in   # adds the run to a review folder, and prints its files
proofreel vm down
```

`stop` prints the session folder to give to `publish`. `proofreel click 512 400` clicks a point on the screen.
A web run measures requests (`net/*`) and web vitals with no flag, so a budget such as
`check metric net/* failed --below 1` works at once.

Publishing is in [the review page](docs/review-page.md). To use an existing VNC screen in place of a VM, set
`PROOFREEL_VNC=127.0.0.1::5900` and `PROOFREEL_PASSWORD=...`.

## Native apps in a VM

A native Mac, Linux, or Windows app runs in a VM from a saved state, so each run starts clean. For a Mac app, make a
macOS state once, install the app, and start each test from it ([VM states](docs/vm-states.md)):

```bash
proofreel vm base macos-26 ghcr.io/cirruslabs/macos-tahoe-vanilla:26.0   # once: a clean OS
proofreel vm up macos-26                     # a throwaway run VM, cloned in seconds
```

For a Linux guest with Chromium (or a Windows guest), make the `linux` state once. It downloads Debian (about 0.4 GB)
and takes about 5 minutes. A state that exists is not made again; `proofreel vm drop linux` removes it:

```bash
proofreel vm image                           # once: the linux state (Debian, Xfce, Chromium)
proofreel vm up linux
proofreel open http://10.0.2.2:8791/         # in a Linux VM, the host is at 10.0.2.2
```

The commands after that are the same as for a web app.

A flow is a text file with one command on each line, so a journey runs again the same way. Write each line without the
word `proofreel`, and begin with `from web` (or another state) and `open URL` for the page step. [`examples/acme-notes/flows`](examples/acme-notes/flows)
has flows to copy. A suite runs many flows, each from a clean browser or VM:

```bash
proofreel run flows/sign-up.flow --set EMAIL=sam@example.com
proofreel suite flows/ --out review-sign-in --title "Sign in"
```

## Checks

| Check | Passes when |
|---|---|
| `check text <text> [seconds] [--in BOX]` | the words show on the screen in the seconds (default 10) |
| `check no-text <text> [seconds]` | the words are gone from the screen in the seconds (default 0) |
| `check cmd "<command>" [seconds]` | a shell command on the host exits 0. It runs again each second until it does or the seconds pass |
| `check sh "<command>" [seconds]` | the same, but in the run VM over SSH (PowerShell on Windows) |
| `check running <process>` | a process with this exact name runs in the run VM |
| `check metric <series> <stat> --below N` (or `--above N`) | a budget on what a probe measured; see [Probes and budgets](docs/probes.md) |

`--in`, `click-text`, and the other commands are in [Flows, checks, and commands](docs/flows.md).

## The review page

On a wide screen the video, a scrub bar with a mark for each step and check, and a folded Tracks row are on the left.
The right column shows the state machine of the review folder, drawn from the runs' `state` lines (Flow), or a list of
the steps of each state with their times (Steps). A click on a state or a step jumps the video to that moment. The page
fits the window, and only that column scrolls. Journeys, Stats, and Network are tabs below. A failed check marks the
page *Fail*, and under the title a line names the first failure; a click on it jumps the video there. Approve and Needs work sit by the title.
Keys: Space plays, the arrows seek, J and K step, N finds the next failure.

Publishing, review folders, and what the page adds on claude.ai are in [the review page](docs/review-page.md).
Tracks, Stats, and Network show what the [probes](docs/probes.md) measured.

## Review inbox

One local queue for the review pages of all your agents, and the way your decision gets back to the agent that made
the proof. The agent runs `proofreel inbox add <review folder> --from <name> --pr N --on-approve "<next step>"`, then
`proofreel inbox wait <id>` (in Claude Code, as a background command: when it exits, it wakes the session). You open
http://127.0.0.1:8790, read the page, and press Approve (A), Approve + next (Shift A), Needs work (W), or Reject.
`wait` prints your decision and exits; the inbox then shows "Picked up by <name>". `proofreel inbox check --here`
reads decisions later, and `proofreel inbox stop` ends the server. The server listens on this machine only.

**From your phone.** Install Tailscale on the Mac and on the phone. On the Mac, run `tailscale serve --bg 8790`. Then run
`proofreel inbox serve --also <mac>.<tailnet>.ts.net`, and open the `https://` link on the phone. The list of waiting
items opens first; tap an item to read it. The Approve, Needs work, and Reject buttons stay at the bottom of the screen.
`--also` saves the host names and starts the server in the background with them; pass `--also ""` to close them. `inbox list` shows
the open names. Never put the inbox on a public tunnel with no login in front: the page carries its token, so anyone with
the link can decide. A Cloudflare Tunnel with Cloudflare Access is the other safe option.

## In CI

A GitHub Action replays your saved flows on each pull request and comments with the verdicts, a picture, and a link
to the review page. It uses no model and no tokens. See [proofreel in CI](docs/ci.md) for the workflow to copy.

## Example: Acme Notes

[`examples/acme-notes`](examples/acme-notes) is a made-up notes app with three flows (sign in, write a note,
search). Its README says how to run it, and how `BROKEN=1` makes a run fail. The suite:

```bash
python3 examples/acme-notes/server.py &    # skip if it already runs
proofreel suite examples/acme-notes/flows --out review-acme
```

The tour above is made from these runs. `tools/readme_media.py review-acme` makes it again, and `tools/example_page.py` makes the example page. `tools/agent_cost.py` measures what a proof costs a coding agent in tokens.

## Docs

| Page | What is in it |
|---|---|
| [Flows, checks, and commands](docs/flows.md) | the checks, flows, suites, states, crash reports, another tool that drives the screen, the accessibility tree, modifier keys |
| [VM states](docs/vm-states.md) | saved states, Tart (macOS and Linux), conditions, QEMU (Windows and Linux), the `linux` browser image |
| [Probes and budgets](docs/probes.md) | what a probe measures, `check metric`, `stats`, input latency, network requests, the probe contract |
| [proofreel in CI](docs/ci.md) | the GitHub Action, permissions, Pages or artifact, pull requests from forks |
| [The review page](docs/review-page.md) | what the page shows, publishing, review folders, claude.ai features |
| [How it works](docs/how-it-works.md) | the video, the screens it can record, the session folder, capture, time, camera, drawing |

The skill an agent reads is [`skills/proofreel/SKILL.md`](skills/proofreel/SKILL.md).

## Limits

- A run VM is headless and isolated: no window, no host audio (Tart `--no-audio`; QEMU `-audio none` and no
  sound device), no shared clipboard. Nothing it does shows or plays on the host.
- One run VM and one recording at a time for each `PROOFREEL_VM` name (default `pr-run`). Agents that work at the
  same time each set their own name, such as `PROOFREEL_VM=pr-a`. macOS lets a Mac run at most 2 macOS VMs at once.
  State and run names use letters, digits, `-`, and `_`. The backend names a run VM `<name>.vm`, so it never has the
  name of a state. Commands to one run VM share one SSH connection for each boot.
- Files go to `PROOFREEL_HOME` (default `~/.proofreel`): states, run records, compiled helpers, and `sessions/`
  (`PROOFREEL_SESSIONS`). The guest password is in each state's file (`states/<name>.json`), and it reaches `ssh` through the environment,
  never a command line. Use a throwaway password in a VM, never a real one.
- A VNC server sends keys as keysyms. Some apps read hardware key codes. A macOS run VM posts modifiers in the
  guest (see [Modifier keys](docs/flows.md#modifier-keys-macos-guests)); send other keys from in the guest, and log them with
  `proofreel event key ...`.

## License

[MIT](LICENSE).
