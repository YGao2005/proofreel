# proofreel

Review proof for computer-use agents. proofreel records an agent as it drives a real screen, then makes a short
review video and a page that a person can check in a minute.

- **The video looks edited, but no one edits it.** A drawn pointer glides to each click on a slight arc. Each click
  presses and sends out a ring. The camera zooms in before each action, pans to the next one when it is near, and
  zooms out when the work moves on. Each step is a caption, and each action and check is a chip. Time with no
  change on the screen plays at up to 8x, with a smooth ramp in and out.
- **The video fits about 30 s.** Busy time plays at up to 2.5x when the session is long, a wait for the screen plays
  at 3x, and a badge shows the speed whenever it is above 1x.
- **The page is the review.** It has the video, a scrub bar with a mark for each step and check, a States track
  under it, and a side panel with the timeline of actions and thumbnails. A click on a row or a state jumps the video
  to that moment. A failed check marks the page *Problem*. On a wide screen the page fits the window and only the side
  panel scrolls.
- **Saved states for VMs.** Save a VM as a named state, such as `clean-os`, `app-installed`, or
  `signed-in-mid-onboarding`. Then start each test from that state in seconds. A warm state keeps the memory, so the
  test starts with the apps already open. A state that a flow makes records the flow, so you can make it again when
  the app changes. macOS and Linux guests run in Tart; Windows 11 ARM and Linux guests run in QEMU.
- **Any VNC screen.** This includes macOS and Linux VMs in Tart or UTM, QEMU, and Docker desktops with x11vnc.
  Another tool can also make the frames: give proofreel a folder of timestamped screenshots and an event log.

![A made-up sign-up session: the pointer glides to each field, the camera zooms in and pans, a 8x badge shows over the wait, and the check passes.](docs/demo.gif)

```bash
pip install git+https://github.com/YGao2005/proofreel   # Python 3.11+, and ffmpeg on PATH
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

Checks:

| Check | Passes when |
|---|---|
| `check text <text> [seconds]` | the words show on the screen in the seconds (default 10) |
| `check no-text <text> [seconds]` | the words are gone from the screen in the seconds (default 0) |
| `check cmd "<command>" [seconds]` | a shell command on the host exits 0. It runs again each second until it does or the seconds pass |
| `check sh "<command>" [seconds]` | the same, but in the run VM over SSH (PowerShell on Windows) |
| `check running <process>` | a process with this exact name runs in the run VM |
| `check metric <series> <stat> --below N` (or `--above N`) | a budget on what a probe measured; see [Probes and budgets](#probes-and-budgets) |

Give `--label` to say what a command check proves. The page shows the label, and the end of the command's output as
the detail.

Each command is one action, so an agent can drive the screen with the commands alone. To find words on the screen,
proofreel uses Apple Vision on macOS hosts and Tesseract on other hosts.

### Review on claude.ai

`proofreel publish <session> --out <review folder>` adds a run to a review folder: one page that holds every run of
one journey, so the link in a pull request never changes. It prints the files of the new run and the page's runtime
capabilities. Claude then publishes the page as a claude.ai Artifact (the same file path or URL each time). On
claude.ai the page also has:

- **Comments** on any step or moment, through the artifact's own comments, which can go to the Claude session that
  published the page.
- **Review**: Approve or Needs work for each run, kept in the page's database, so Claude can read the verdict.
- **Ask about this moment**: Claude answers a question from the current video frame and the run's log.

Opened as a plain file, the page is a static review page.

The review folder keeps `runs.json` (`{"version": 2, "runs": [...]}`). It is the only copy of old runs, because
`clean` deletes sessions after 7 days. A folder that an older proofreel wrote is upgraded when you publish to it, and
its old file is kept as `runs.v1.json`. Publishing locks the folder and writes each file whole, so two agents can
publish to one folder at once.

### Flows

A flow is a text file with one proofreel command on each line. Use `#` for comments, and `${NAME}` or
`${NAME:-default}` for values that you set with `--set NAME=value`. proofreel reads and parses every line before the
first one runs, so a typo or a missing value stops the flow before it changes anything. A failed `check` is recorded,
and the flow continues. A check that cannot run (no text recognition, no accessibility tree) is a failed check, and
the page says why. Any other failure stops the flow and the recording, and the page shows where it stopped.

Every command exits 0 when it is done, 1 for a failed check (or a `find` that finds nothing, or a flow with a
failed check), and 2 for a problem.
A problem prints one line that says what to do.

```bash
proofreel run flows/sign-up.flow --set EMAIL=sam@example.com
```

### States: the flow as a state machine

Put `state <name>` where the app should be, such as `state "Sign in"`. The waits and checks after it, up to the next
`state`, prove that the app got there. A visit to a state passes when all of them pass. It fails when one fails or the
run stopped in it. With no wait or check, it is "not checked". The actions between two states are a transition, and
`step` names it.

```
state Home
wait-text "Acme Notes" 30
step "Open sign in"
click-text "Sign in"
state "Sign in"
check text "Sign in to Acme"
```

`stop` prints the run's path, such as `States: Home ok → Sign in ok → Welcome FAIL`. On the page, the
State machine tab draws the states of every run in the review folder as one graph: a node for each state
and an edge for each transition that a run took. Other flows and conditions add branches and loops. The run on show
is drawn strong, each node has a dot for its verdict in each run, and each edge shows how long the transition took.
Click a state or a transition to play the video from there. Click a state again to go to its next visit. The node
that the video is in lights up. Use the same state name in each flow for the same place in the app.

### Probes and budgets

A probe measures while a session records: the host's load, an app's CPU, request times. `host-load` is on for every
recording. Add another with `start --probe <name>` or a flow line `probe <name>`; `--probe none` turns the defaults
off. `proofreel probes` lists them, with what each can see and what it does not measure well.

```
probe host-load
start sign-up
...
check metric host/cpu p95 --below 80          # the whole run so far
check metric net/* p95 --below 0.5 --step     # since the last step or state
check metric net/* failed --below 1 --last 30
```

`--probe browser` measures web pages in the `linux` VM's Chromium: LCP, CLS, and INP (`web/lcp`, `web/cls`,
`web/inp`, in ms), long animation frames, the page's own `performance.measure` and `mark` (`web/measure/<name>`), the
JS heap, and DOM nodes. For example, `check metric web/inp max --below 200`. It needs `pip install websocket-client`.

A stat is `mean`, `min`, `max`, `p50`, `p90`, `p95`, `p99`, `last`, `count`, or `failed`. A budget waits up to
`--wait` seconds (default 2) for a measure that came after it began. With no data in its window, it is a failed check
that says which series there are. `stop` prints a line for each series, and `proofreel stats [session]` prints them
again (`--json` for all the numbers).

Input latency needs no probe: when the run stops, proofreel reads the recorded frames and measures how long the
screen took to answer each click (around the pointer) and each key (anywhere), with an error bar of half the time
between two frames. It ignores what was already changing just before (a caret, a spinner). The series are
`input/click` and `input/key`; an input that got no change on the screen in 2 s counts as `failed`. A budget on
`input/*` is decided at `stop`, which then exits 1 if it failed:
`check metric input/* p95 --below 0.2`.

On the page, each series is a row under the scrub bar, on the video's time axis: samples as a line in their lo-hi
envelope, spans in rows (`+N` when more do not fit), and marks as ticks. Stretches that play fast are hatched and
labelled with their speed, such as `8x`. A chip per group (the part of the series id before `/`) hides its rows, and
a pin puts a series in the readout at the bottom left of the video. The page remembers both for each viewer. The Stats
tab has input latency, then p50, p95, and max for each series with its budgets, failing ones first. The Network tab is
a waterfall of the spans that have `phases`. The track fields `label`, `unit`, `max`, and `bands` (values to draw a
guide line at) set how a row looks. A run keeps at most 200 KB of metrics: up to 600 bins per series, 2000 spans
(failed first, then the slowest, then a spread), and 1000 marks. Query strings are cut from labels. In a review
folder, the newest 6 runs keep their rows; older runs keep the numbers.

**Network requests** (`--probe network`, Linux run VMs, `pip install mitmproxy`): a proxy on the host sees each
HTTP and HTTPS request that Chromium in the guest makes. Each request is a span in `net/<host>`, with its method and
path, its status and size, and the time to connect, to do TLS, to wait for the answer, and to receive it. A status of
400 or more, or no answer, is `failed`. It never keeps a query string, a header value, or a body, and a path part that
looks like an id, a token, or an email address shows as `:id` or `:email`. At `start`, the guest gets the proxy and
trusts a CA that is new for each session; at `stop`, both go, and the CA is deleted. Only the run VM may use the
proxy. A request from the guest to `10.0.2.2` (the host) goes through the proxy too, so a test server on the host is
measured.

A probe is a folder like a condition (`probe.toml` and a script), found in the same places. It runs on the host
(`run.py`) or in the guest (`run.sh`, `run.ps1`) and prints one JSON line for each measure:
`{"m": "cpu/app", "v": 42}` is a sample, `{"m": "net/GET /items", "d": 0.31, "ok": true}` is a span (something that
took `d` seconds), and `{"m": "app/ready"}` is a mark. A line can carry `t`, the time in the probe's own steady
clock; proofreel moves it onto the host clock by the probe's smallest delay. `{"unavailable": "<why>"}` says the probe
cannot measure here. Lines over 16 KB, over 200 a second, or past 64 series are counted and dropped. A probe never
gets the guest password. A probe can also change the guest for the recording with `start` and `stop` scripts (a proxy,
a trusted CA). proofreel writes each reset into the run record before its `start` runs, so a crash is undone at the
next `start`, at `vm save`, or at `stop`. A condition that lasts one recording uses the same list. See `src/proofreel/probes/__init__.py` for the whole contract.

### Crash and hang reports (macOS guests)

`start` marks the time in the guest. `stop` copies each new `.ips`, `.hang`, and `.spin` report from
`~/Library/Logs/DiagnosticReports` and `/Library/Logs/DiagnosticReports` to `reports/` in the session folder. Name
the app under test with `start <name> --app <process name or bundle ID>`. A crash or hang of that app is a failed
check, with the process, the exception type, and the top frames of the crashed thread and of the last exception.
With no crash, the page shows the check "<app> did not crash or hang" as a pass. Reports from other processes are
notes. Without `--app`, a crash of any process is a failed check. macOS can write a report about a minute after the
crash, so if the app is gone at `stop`, proofreel waits up to 2 minutes for it.

### When another tool drives the screen

Log what the other tool does, and proofreel records and renders it in the same way:

```bash
proofreel event click 'click "Save"' --x 640 --y 410
proofreel event check "The file is saved" --ok
```

### Click by the accessibility tree (macOS guests)

Text recognition finds what the screen shows. In a macOS run VM, proofreel can also read the accessibility (AX)
tree: the role, label, value, and frame of each element. A small helper runs in the guest over SSH, so the app under
test needs no permission.

```bash
proofreel ax --app TextEdit                 # the tree of the app's windows, with the click point of each element
proofreel ax --find "Save"                  # only the elements with this label (the front app by default)
proofreel ax --json                         # the raw tree: frames in points, and the screen size in points
proofreel click-ax "Save" --role AXButton   # find the element by its label, then click its center
proofreel check ax "Saved" 10               # a pass when the label shows in 10 s
proofreel check no-ax "Error"
```

The label of an element is its title, description, linked label, text value, or identifier. An exact label comes
first, then a label that contains the text. Case is ignored. An element counts only when its center is in its window
and its scroll areas, so scroll to a row that is out of view first. The click points are screen pixels (2x the
points on a Retina guest), the same as `click`.

The helper is compiled on the host once (`swiftc`, into `~/.proofreel/bin/`) and copied into the guest on first use.
It needs a run VM from `proofreel vm up`, because it uses SSH. A plain `--vnc` screen cannot use it.

**The permission.** macOS gives each app its own permissions. A process that SSH starts uses the Accessibility
permission of `/usr/libexec/sshd-keygen-wrapper`. Give that permission once in your base state:

1. `proofreel vm up <state>`, then open the VNC address that it prints in a VNC viewer.
2. In the guest, open System Settings > Privacy & Security > Accessibility, click **+**, and type the password. In the
   file dialog, press Cmd-Shift-G, type `/usr/libexec/sshd-keygen-wrapper`, press Return, and click **Open**. Make sure
   that its switch is on.
3. Save it as a new state, such as `proofreel vm save macos-ax`, and make your later states from it.

The app under test gets nothing from this, so a state such as "app installed, no permissions" stays true for the app.
But the grant leaves a trace: `sshd-keygen-wrapper` shows in the Accessibility list. A check that the list is empty
sees it.

### Modifier keys (macOS guests)

`key` presses keys and combos (`key command-a`, `key enter`). `hold` and `tap` press one key with timing, for an app
that watches the keys themselves, such as a push-to-talk key or a double tap:

```bash
proofreel hold fn 1.5          # hold Fn for 1.5 s
proofreel tap option 2         # a double tap: 70 ms presses, 110 ms apart
proofreel hold command down    # only press it ...
proofreel hold command up      # ... and release it later
```

In a macOS run VM, the modifiers (`fn`, `option`, `command`, `control`, `shift`, and `roption`, `rcommand`,
`rcontrol`, `rshift` for the right keys) do not go through VNC: VNC has no Fn key, and each VNC command is a new
connection, so a double tap would lose its timing. A small helper (`keys.swift`) posts them in the guest as a hardware
keyboard does, with the key code and the left or right device flag. A whole `hold` or `tap` is one process in the
guest, so its timing holds. The helper needs the same Accessibility grant as [the accessibility tree](#click-by-the-accessibility-tree-macos-guests),
and it stops with an error without it. A modifier from `hold <key> down` reaches apps that watch modifier changes,
but a VNC click or key does not carry it: for Cmd-click or a shifted key, use `key` with a combo. On other screens,
`hold` and `tap` send every key over VNC.

## VM states

Send each test to the right VM:

- A test that any browser can run goes to the `linux` state (QEMU).
- A test of a Windows app goes to a Windows state (QEMU).
- Use a macOS VM only for a native Mac app. A Mac runs at most 2 macOS VMs at the same time. QEMU VMs are limited
  only by memory.

### macOS and Linux (Tart)

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

Each state names its backend and its guest system (`--os macos`, the default, `linux`, or `windows`). The
system decides what proofreel can do in it: crash reports and the accessibility tree are macOS only, and each
condition names the systems it works on. All of this is in `src/proofreel/guest.py`, so a new system is one class.

A clone is copy on write (APFS), so a state costs only the disk blocks that it changes. On an M-series Mac with a
macOS 26 guest: `up` from a cold state takes about 18 s to SSH ready, a warm `up` about 12 s with the apps as they
were, and `save --warm` about 60 s. A warm state needs a run VM
that was started with `--warmable`. Tart then turns off the VM's audio devices, so do not test a microphone in a
warm VM.

### Conditions: fake hardware and setups

A condition makes the guest look like a setup that you do not have, such as a Bluetooth headset, a Mac with no
microphone, or a choppy network. It is a plugin folder: `condition.toml` says what it fakes, how it applies, how it checks, and what it
does not reproduce. `apply` and `check` run in the guest (`.sh` on macOS and Linux, `.ps1` on Windows). An optional
`host.sh` runs on the host first, for example to build a driver. proofreel looks for a condition (and later a probe)
by name in this order: a folder path, `./.proofreel/conditions/` in the project you work in, then
`$PROOFREEL_HOME/conditions/`, then the ones that come with proofreel. So an app's repo can ship its own conditions,
and `proofreel vm conditions` says where each one comes from.

```bash
proofreel vm conditions                                   # the list, with what each does not fake
proofreel vm build headset --from macos-26 --condition bluetooth-headset-call-mode
proofreel vm build offline-dmg --from macos-26 --condition offline --condition run-from-dmg --set DMG=MyApp.dmg
```

`build` applies each condition, then runs its check. A check that fails stops the build. The state keeps its
conditions, and a state built from it keeps them too. `vm up` runs the checks again, so a condition that no longer
holds stops the run. A flow line `condition <name>` makes `proofreel run` refuse a run VM whose state does not have
it. The page lists the conditions of the run in its header.

A condition with a remove step (`removes` in its manifest) lasts one recording instead of a state. `start --condition
<name>[:KEY=VALUE,...]`, or a flow line `condition <name>[:KEY=VALUE,...]`, applies it before the recorder starts.
`stop` removes it and logs a check that it is gone. The remove is written to the run record before the apply, so a crash is undone at the next `start`. Its values go in
`session.json` and in the page header. A condition can name sets of values in `[profiles]`: the value `profile`
picks one, and a value that you give replaces the profile's.

```bash
proofreel start slow-load --condition slow-network                    # profile=3g
proofreel start slow-load --condition slow-network:profile=lossy-wifi,loss=20%
proofreel start slow-load --condition slow-network:profile=none,latency=200ms
```

| Condition | Fakes | Check |
|---|---|---|
| `bluetooth-headset-call-mode` | the only microphone is a Bluetooth headset; when input starts, its rate drops from 48 kHz to `RATE` (24000 or 16000) | the default input is Bluetooth at 48 kHz, is `RATE` while input runs, and is 48 kHz again after |
| `no-microphone` | no input device at all | Core Audio lists no device with input |
| `offline` | no internet (pf refuses all traffic but SSH from the host) | pf is on; a TCP connection and DNS fail |
| `run-from-dmg` | the app runs from its mounted DMG (`DMG=<host path>`) | the DMG is mounted with an app at its top |
| `quarantined-download` | the app is in `~/Downloads` with the quarantine flag and download record a browser makes, so the first open shows Gatekeeper and translocates it | the flag is set, not yet approved, and has a download record |
| `slow-network` | one recording on a slow, choppy network (Linux and macOS): `latency` and `jitter` (round trip), `loss` and `rate` (each way). Profiles: `3g` (300ms, 50ms, 1%, 1mbit), `edge` (800ms, 100ms, 2%, 200kbit), `lossy-wifi` (60ms, 40ms, 10%, 10mbit), `none` | netem (Linux) or dummynet (macOS) shapes all traffic but SSH |

The headset is a small Core Audio driver (`headset.c`, an AudioServerPlugIn), built on the host with clang. It
reports Bluetooth transport. When input starts, it asks Core Audio for a configuration change to the call rate, as a
real Bluetooth driver does. proofreel does not use BlackHole: it is GPL-3.0, and its device cannot report Bluetooth.
A condition fakes the signals that macOS gives an app. It does not fake a radio, a codec, or hardware timing, so test
on real hardware before a release.

### Windows 11 ARM and Linux (QEMU)

```bash
brew install qemu llvm lld acpica
firmware/build.sh                                       # once: UEFI firmware that takes any screen size
proofreel vm base win11 win11.qcow2 --backend qemu --os windows   # once: a disk that boots Windows (see below)
proofreel vm up win11                                   # PowerShell over SSH, the screen over VNC (1440x900)
proofreel vm up win11 --display 1920x1080               # any WIDTHxHEIGHT
proofreel vm sh 'Get-ComputerInfo -Property OsName'
proofreel vm sh 'schtasks /create /tn open /tr notepad.exe /sc once /st 00:00 /it /f; schtasks /run /tn open'
proofreel vm save notepad-open --warm                   # the memory too: Notepad stays open
proofreel vm up notepad-open
```

`base` takes a disk file: a qcow2 (cloned, copy on write) or any format that `qemu-img` reads (converted). All the
other `vm` commands work as they do for Tart, and `--warmable` is not necessary. A Windows disk must have:

- Windows 11 ARM64 that starts from UEFI on an NVMe disk (the Windows boot manager on the EFI partition).
- The virtio network driver (NetKVM, ARM64, from [virtio-win](https://github.com/virtio-win/virtio-win-pkg-scripts)).
- OpenSSH Server that starts automatically, with password login and PowerShell as its default shell
  (`HKLM\SOFTWARE\OpenSSH\DefaultShell`).
- Automatic sign-in for the user that you give to `base` (`--user`, `--guest-password`; the default is admin/admin),
  hibernation off (`powercfg /hibernate off`), and no sleep or lock screen.
- The boot manager in the highest screen mode: `bcdedit /set "{globalsettings}" highestmode on`.

A UTM Windows VM keeps its disk as a `.qcow2` in the bundle's `Data` folder. Give that file to `base` after you
install the items above (`base` clones it, so UTM's copy does not change).

To make a disk from Microsoft's own files: the Media Creation Tool catalog (`products.cab`) lists the Windows 11 ARM64
ESD. Use `wimlib-imagex` to make an install tree, add an `autounattend.xml` and the NetKVM driver in `$WinPEDriver$`,
and make an ISO with `xorriso` (boot image `efi/microsoft/boot/efisys_noprompt.bin`). Boot it once in QEMU with the
ISO as a USB CD-ROM and a new qcow2 disk. Setup then runs with no clicks.

proofreel runs `qemu-system-aarch64` with HVF, headless (`-display none`, `-audio none`, no sound device, no
clipboard), QEMU's own VNC server on 127.0.0.1, user networking with SSH forwarded from a free 127.0.0.1 port, an
NVMe disk, a USB keyboard and tablet, and a `ramfb` screen. A state is a folder in `~/.proofreel/qemu`: `disk.qcow2`,
`vars.fd` (the UEFI variables), and for a warm state `memory.bin`. A cold save shuts the guest down with the ACPI
power button. A warm save pauses the VM and writes its memory and device state to `memory.bin` (a QEMU migration
to a file); `up` loads it with `-incoming`. This works with the UEFI variables as a raw flash file. QEMU's own
`savevm` does not: with raw variables it stops with "Device 'pflash1' is writable but does not support snapshots".
With the variables as a qcow2, `savevm` works but writes the memory into the variables file, `-loadvm` at start
works, and `loadvm` in a running VM stops QEMU 11.1 with an assertion.

On an M-series Mac, with Windows 11 Pro 24H2 ARM64, 4 GB of memory, and 4 cores:

| Step | Time | Disk |
|---|---|---|
| `up` from a cold state | about 20-35 s to SSH | copy on write |
| `save` (cold) | about 30 s: the guest shuts down, then starts again | copy on write |
| `save --warm` | about 35 s | `memory.bin` is about the size of the guest memory (4 GB) |
| `up` from a warm state | about 6 s to SSH, with the apps open | none |

Limits that are particular to QEMU:

- Windows has no display driver for `ramfb`. It uses the screen mode that the UEFI firmware set. QEMU's own firmware
  has only 640x480, 800x600, and 1024x768. `firmware/build.sh` builds edk2 with `firmware/ramfb-resolution.patch` and
  installs it in `~/.proofreel/firmware`. This firmware uses the size from `up --display` in place of 1024x768 (default
  1440x900; give a size larger than 800x600). Without it, the screen is 1024x768 at most and `up` says so.
- Windows keeps the last screen size and scales it to fit a new size. A cold `save` deletes the saved size
  (`HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers\Configuration`), so the next `up` fills the screen. A
  cold state keeps the `--display` that it was saved with. A warm state always has the size that it was saved with.
- A command from `vm sh` runs in the SSH session, which has no desktop. To open an app on the screen, run it as a
  scheduled task with `/it`, as in the example above.
- After a warm `up`, the guest clock shows the time of the save until Windows syncs it again.
- QEMU's VNC server types the keysym that it gets, so proofreel sends the upper-case keysym for a capital letter.

### Linux with a browser (QEMU)

The `linux` state is Debian 13 arm64 with Xfce and Chromium at 1440x900. It signs in by itself as `tester`
(password `tester`). SSH uses the same user and password.

```bash
proofreel vm up linux                                   # about 11 s to SSH; the desktop is ready at the same time
proofreel vm sh 'browse http://10.0.2.2:8000/'          # open a page in Chromium on the screen
proofreel vm sh 'setsid -f xfce4-terminal'              # any app: SSH sessions have DISPLAY=:0
```

- The guest reaches the host at `10.0.2.2`. A server on the host's 127.0.0.1 is enough.
- `browse` starts Chromium maximized, or opens a new tab when Chromium runs. The page shows about 1.5 s later.
- Chromium listens for DevTools on the guest's 127.0.0.1:9222, for the `browser` probe.
- Chromium shows no first-run pages. Policies turn off the password, autofill, translate, and sign-in prompts.
- The guest has no screen lock, no screensaver, no screen blank, and no automatic updates.
- The screen size is the `--display` size: the kernel takes the largest firmware mode (`video=efifb:auto`).
- The state disk is about 2.1 GB. The state is cold only: a cold `up` is already fast.

To make the `linux` state again:

1. Get `debian-13-generic-arm64.qcow2` from `cloud.debian.org/images/cloud/trixie/latest/`. Make it larger with
   `qemu-img resize debian-13-generic-arm64.qcow2 10G`.
2. Make a cloud-init disk: `xorriso -as mkisofs -V cidata -J -r -o seed.iso images/debian-seed`.
3. Start the image once in QEMU with the flags of `up`, and add `seed.iso` as a virtio disk.
4. Copy `images/debian-desktop.sh` into the guest. Run `sudo sh debian-desktop.sh tester`, then shut down.
5. `proofreel vm base linux debian-13-generic-arm64.qcow2 --backend qemu --os linux --user tester --guest-password tester`.
6. `proofreel vm up linux --memory 2048`, then `proofreel vm save linux`.

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

- A run VM is headless and isolated: no window, no audio device (Tart `--no-audio`, QEMU `-audio none` and no
  sound device), no shared clipboard. Nothing it does shows or plays on the host.
- One run VM and one recording at a time for each `PROOFREEL_VM` name (default `pr-run`). Agents that work at the
  same time each set their own name, such as `PROOFREEL_VM=pr-a`. macOS lets a Mac run at most 2 macOS VMs at once.
  State and run names use letters, digits, `-`, and `_`. The backend names a run VM `<name>.vm`, so it never has the
  name of a state. Commands to one run VM share one SSH connection for each boot.
- Files go to `PROOFREEL_HOME` (default `~/.proofreel`): states, run records, compiled helpers, and `sessions/`
  (`PROOFREEL_SESSIONS`). The guest password is in each state's file (`states/<name>.json`), and it reaches `ssh` through the environment,
  never a command line. Use a throwaway password in a VM, never a real one.
- A VNC server sends keys as keysyms. Some apps read hardware key codes. A macOS run VM posts modifiers in the
  guest (see [Modifier keys](#modifier-keys-macos-guests)); send other keys from in the guest, and log them with
  `proofreel event key ...`.

## License

[PolyForm Noncommercial 1.0.0](LICENSE): free to use, change, and share for any noncommercial purpose (personal
projects, research, education, nonprofits). For commercial use, ask the author.
