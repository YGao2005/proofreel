# VM states

Save a VM as a named state, such as `clean-os`, `app-installed`, or
`signed-in-mid-onboarding`. Then start each test from that state in seconds. A warm state keeps the memory, so the
test starts with the apps already open. A state that a flow makes records the flow, so you can make it again when
the app changes. macOS and Linux guests run in Tart; Windows 11 ARM and Linux guests run in QEMU.

Send each test to the right VM:

- A test that any browser can run goes to the `linux` state (QEMU).
- A test of a Windows app goes to a Windows state (QEMU).
- Use a macOS VM only for a native Mac app. A Mac runs at most 2 macOS VMs at the same time. QEMU VMs are limited
  only by memory.

## macOS and Linux (Tart)

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

A web app needs no VM: see [The browser runner](#the-browser-runner).

A clone is copy on write (APFS), so a state costs only the disk blocks that it changes. On an M-series Mac with a
macOS 26 guest: `up` from a cold state takes about 18 s to SSH ready, a warm `up` about 12 s with the apps as they
were, and `save --warm` about 60 s. A warm state needs a run VM
that was started with `--warmable` (Tart `--suspendable`). proofreel starts every Tart run VM with `--no-audio`. In
Tart 2.41 (`VM.swift`, `craftConfiguration`), a VM gets host audio only when it has audio and is not suspendable.
Otherwise the guest gets one virtio speaker with no output and no microphone. So no run VM plays or records sound on
the host, and a warm VM has no microphone: do not test a microphone in it. Run `save --warm` outside any macOS sandbox
(such as an agent's command sandbox): a memory file saved inside one cannot be restored, so `save --warm` refuses
there. A warm save resumes at once, and a state that does not restore is deleted.

## Conditions: fake hardware and setups

A condition makes the guest look like a setup that you do not have, such as a Bluetooth headset, a Mac with no
microphone, or a choppy network. It is a plugin folder: `condition.toml` says what it fakes, how it applies, how it checks, and what it
does not reproduce. `apply` and `check` run in the guest (`.sh` on macOS and Linux, `.ps1` on Windows). An optional
`host.sh` runs on the host first, for example to build a driver. proofreel looks for a condition or a probe
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

## Windows 11 ARM and Linux (QEMU)

```bash
brew install qemu
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
  has only 640x480, 800x600, and 1024x768. proofreel ships its own edk2 firmware (`src/proofreel/firmware/`), which
  uses the size from `up --display` in place of 1024x768 (default 1440x900; give a size larger than 800x600). `up`
  unpacks it into `~/.proofreel/firmware` once. To rebuild it, run `src/proofreel/firmware/build.sh` from a checkout
  (`brew install llvm lld acpica`). It uses edk2 tag `edk2-stable202408` and `ramfb-resolution.patch`, and replaces
  `edk2-aarch64-code.fd.gz`. edk2 is BSD-2-Clause-Patent: `LICENSE-edk2.txt` is next to the binary.
- Windows keeps the last screen size and scales it to fit a new size. A cold `save` deletes the saved size
  (`HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers\Configuration`), so the next `up` fills the screen. A
  cold state keeps the `--display` that it was saved with. A warm state always has the size that it was saved with.
- A command from `vm sh` runs in the SSH session, which has no desktop. To open an app on the screen, run it as a
  scheduled task with `/it`, as in the example above.
- After a warm `up`, the guest clock shows the time of the save until Windows syncs it again.
- QEMU's VNC server types the keysym that it gets, so proofreel sends the upper-case keysym for a capital letter.

## Linux with a browser (QEMU)

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
- Chromium makes no background requests. The quiet flags turn off most of them. The component updater and the account check run at start whatever the flags say, so both point at a closed local port (see `src/proofreel/images/debian-desktop.sh`).
- The guest has no screen lock, no screensaver, no screen blank, and no automatic updates.
- The screen size is the `--display` size: the kernel takes the largest firmware mode (`video=efifb:auto`).
- The state disk is about 2.1 GB. The state is cold only: a cold `up` is already fast.

To make the `linux` state, run `proofreel vm image` (a name is optional; the default is `linux`). It needs QEMU, and
takes about 4 minutes. It does these steps:

1. Downloads `debian-13-generic-arm64.qcow2` from `cloud.debian.org/images/cloud/trixie/latest/` into
   `$PROOFREEL_HOME/images`, and checks its SHA-512 against `SHA512SUMS` from the same folder.
2. Makes a state from it (`vm base`) and makes the disk 10 GB.
3. Boots it once with cloud-init. The host serves `images/debian-seed` (the `tester` user) over HTTP; there is no ISO.
4. Runs `images/debian-desktop.sh` in the guest over SSH, then saves the state (`vm save`), which also checks that
   the desktop starts.

Both files are in the package (`src/proofreel/images`). If a step fails, the half-made state is deleted.

## The browser runner

A web app runs in a headless Chrome on the host: no VM, no SSH, no image to build. The built-in state `web` is an
empty browser profile, so `vm up web` works on a new machine.

```bash
proofreel vm up web                          # about 1 s: Chrome, 1440x900, no window, no sound
proofreel start signup --title "Sign up"
proofreel open http://127.0.0.1:8791/notes.html
proofreel wait-text "Your notes"
proofreel click-text "Title"
proofreel type "Trip plan"
proofreel check text "Trip plan"
proofreel stop
proofreel vm save signed-in                  # the profile (cookies, storage) is the state
proofreel vm up signed-in                    # a copy of it: each run starts from the same place
proofreel vm down
```

- Chrome comes from `PROOFREEL_CHROME`, then the newest Chromium of Playwright (`playwright install chromium`), then
  Google Chrome in `/Applications`, then `chromium` or `google-chrome` on PATH.
- A watchdog starts with Chrome and ends it after `PROOFREEL_IDLE` seconds (default 1800) with no proofreel command
  and no recording. It also ends Chrome's helpers and the run profile. The next command says: "The browser stopped
  after 30 min with no proofreel command. Start it again: proofreel vm up web." `vm down` ends the watchdog.
- Chrome is `--headless=new --mute-audio --hide-scrollbars`, and its DevTools port listens on 127.0.0.1 only. The run
  record's `screen` is `cdp://127.0.0.1:<port>` (a VNC run has `host::port`). `--vnc cdp://127.0.0.1:<port>` drives
  any Chrome that you started with `--remote-debugging-port`.
- The screen is the first tab. Coordinates are CSS pixels of the 1440x900 viewport (device scale 1).
- Text comes from the page, not from OCR: `find`, `click-text`, `wait-text`, `check text`, and `--in` read the visible
  text lines with their boxes, including input values and placeholders. Text that a modal covers, that is
  `display: none`, or that is outside the viewport is not read, as on a real screen. Text in iframes and in shadow DOM
  is not read.
- The recorder uses the screencast of Chrome (`Page.startScreencast`): a frame at each change of the page, and one at
  the start. The renderer draws the pointer, as it does for a VM.
- `vm save` waits 6 s (Chrome writes localStorage up to 5 s late), closes Chrome so it writes its cookies and storage,
  copies the profile, and starts Chrome again. A state
  is cold only (`--warm` and `--warmable` are refused). `vm sh`, `put`, `get`, `check sh`, `check running`, conditions,
  and guest probes need a shell, which a browser run does not have: use `check cmd` for a command on the host.
- `open <url>` works on every run VM: `web` navigates the tab and waits for its load event, Linux runs `browse`,
  macOS runs `open`, and Windows runs `start`.
