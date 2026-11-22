# Flows, checks, and commands

## Checks

The checks table is in [the README](../README.md#checks). More about the checks:

`--in` keeps a text check (and `wait-text`, `find`, `click-text`) to one part of the screen: a box in pixels
(`--in 0,0,1440,450`), or the label of an element in the accessibility tree of a macOS run VM (`--in "Upload"`,
such as a dialog). A check whose element is not there fails and says why. To check by role, use
`check ax <text> --role AXButton`.

`click-text` clicks the matched words, not the middle of their line, so `click-text browse` hits the link in
"Drag files here or browse". In a macOS run VM it first looks for a button with that label in the accessibility
tree, so a button wins over a dialog title with the same words. It uses the tree when it has at least `--nth`
buttons with exactly that label, and the words on the screen otherwise. `--role` clicks only an element with that
role. `find` reads only the words on the screen, so in a macOS run VM its point can differ from the button that
`click-text` clicks.

Give `--label` to say what a command check proves. The page shows the label, and the end of the command's output as
the detail.

Each command is one action, so an agent can drive the screen with the commands alone. To find words on the screen,
proofreel uses Apple Vision on macOS hosts and Tesseract on other hosts.

## Flows

A flow is a text file with one proofreel command on each line. Use `#` for comments, and `${NAME}` or
`${NAME:-default}` for values that you set with `--set NAME=value`. proofreel reads and parses every line before the
first one runs, so a typo or a missing value stops the flow before it changes anything. A failed `check` is recorded,
and the flow continues. A check that cannot run (no text recognition, no accessibility tree) is a failed check, and
the page says why. Any other failure stops the flow and the recording, and the page shows where it stopped.

`start` on a session whose recorder died stops and renders that session first, then starts.

Every command exits 0 when it is done, 1 for a failed check (or a `find` that finds nothing, or a flow with a
failed check), and 2 for a problem.
A problem prints one line that says what to do.

```bash
proofreel run flows/sign-up.flow --set EMAIL=sam@example.com
```

A line `from <state>` names the saved VM state that the flow starts from. `run` refuses a run VM from another
saved state.

## Suites: many journeys, each from a clean VM

```bash
proofreel suite flows/upload/ --state warm-app --out review-upload --title "Upload"
```

A suite runs each flow in the folders and files that you give. For each flow, it starts a new clone of the flow's
saved VM state (its `from` line, or `--state`), runs the flow, and deletes the clone. So each journey starts from the
same place, and nothing from one journey reaches the next in the VM. A server on the host is not reset: what one
journey saves there, the next one sees. It reads every flow and finds every state before the first
VM starts. A journey that fails does not stop the suite: its row says why. A recording that a flow leaves open is
stopped. All journeys go to one review folder, and one page shows them all. The run switcher names each journey, and
the Journeys tab lists them with their result, checks passed, and length; a click on a row plays that journey. A
journey that made no video shows its error in place of the video. The suite prints PASS or FAIL for each journey,
then the same output as `publish`, and exits 1 if a journey failed.



## States: the flow as a state machine

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

`stop` prints the run's path, such as `States: Home ok → Sign in ok → Welcome FAIL`. On the page, the user flow sits
under the video: a node for each state in the order the run reached it, with an arrow for each transition, and a
transition that skips ahead or goes back drawn as an arc under the nodes. A node shows its checks passed of total, and
it is green when they pass, red when one fails, and grey with no checks. The node that the video is in lights up. Click
a node to play the video from there. Click it again to go to its next visit. A run with no `state` lines has no flow.
Use the same state name in each flow for the same place in the app.

## Crash and hang reports (macOS guests)

`start` marks the time in the guest. `stop` copies each new `.ips`, `.hang`, and `.spin` report from
`~/Library/Logs/DiagnosticReports` and `/Library/Logs/DiagnosticReports` to `reports/` in the session folder. Name
the app under test with `start <name> --app <process name or bundle ID>`. A crash or hang of that app is a failed
check, with the process, the exception type, and the top frames of the crashed thread and of the last exception.
With no crash, the page shows the check "<app> did not crash or hang" as a pass. Reports from other processes are
notes. Without `--app`, a crash of any process is a failed check. macOS can write a report about a minute after the
crash, so if the app is gone at `stop`, proofreel waits up to 2 minutes for it.

## When another tool drives the screen

Log what the other tool does, and proofreel records and renders it in the same way:

```bash
proofreel event click 'click "Save"' --x 640 --y 410
proofreel event check "The file is saved" --ok
```

## Click by the accessibility tree (macOS guests)

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

## Modifier keys (macOS guests)

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
