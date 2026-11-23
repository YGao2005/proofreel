# Review inbox

One local queue for the review pages of all your agents, and the way your decision gets back to the agent that made
the proof.

## How it works

1. The agent queues its page: `proofreel inbox add <review folder> --from <name> --pr N --on-approve "<next step>"`.
   It prints the item id. The first `add` starts the inbox server.
2. The agent runs `proofreel inbox wait <id>`. In Claude Code, run it as a background command: when it exits, it wakes
   the session. Other agents run it in the foreground, or run `proofreel inbox check --here` later.
3. You open http://127.0.0.1:8790, read the page, and press Approve (A), Approve + next (Shift A), Needs work (W), or
   Reject.
4. `wait` prints your decision and exits. The inbox then shows "Picked up by <name>".

The agent reads one of these texts:

| You press | The agent reads |
|---|---|
| Approve | `Approved: <title>. Then: <on-approve text, or "merge by your repo's rules">.` |
| Approve + next | `Approved: <title>. Next mission: <your text>` |
| Needs work | `Needs work: <your notes>` |
| Reject | `Rejected: <your reason>. Close the branch.` |

## Undo and history

A decision goes to the agent 10 seconds after you press the button. Until the agent reads it, Undo takes it back and
the item waits again. After the agent reads it, tell the agent the change yourself.

The inbox keeps a copy of each page (up to 500 MB) and every decision. Sent shows the page next to what you sent, so
a later run in the same folder does not change it. Items are not deleted.

## From your phone

1. Install Tailscale on the Mac and on the phone, and sign in to the same account.
2. On the Mac, run `tailscale serve --bg 8790`.
3. Run `proofreel inbox serve --also <mac>.<tailnet>.ts.net`, and open the `https://` link on the phone.

The list of waiting items opens first. Tap an item to read it. The decision buttons stay at the bottom of the screen.
`--also` saves the host names and starts the server in the background with them. `--also ""` closes them, and
`proofreel inbox list` shows them. A Cloudflare Tunnel with Cloudflare Access is the other safe option.

## Security

- The server listens on 127.0.0.1 only. It refuses a request with any other host name, unless you added that exact
  name with `--also`.
- A decision needs the token of this install (`~/.proofreel/inbox/token`) and an origin of the server itself, so
  another web page cannot decide for you.
- Each page runs in a sandboxed frame, and the server sends files only from that item's folder.
- Never put the inbox on a public tunnel with no login in front. The page carries its token, so anyone with the link
  can decide.

## Commands

| Command | What it does |
|---|---|
| `inbox add <page or folder> [--title T] [--from NAME] [--pr N] [--on-approve TEXT]` | Queue a page. Prints the item id. |
| `inbox wait <id> [--timeout S]` | Wait for the decision, print it, and exit (exit 2 on timeout). |
| `inbox check [--here]` | Print the decisions that no agent has read (`--here`: this repo and branch). |
| `inbox list` | Print the items and the open host names. |
| `inbox serve [--also HOST]...` | Run the server. With `--also`, save the host names and start it in the background. |
| `inbox stop` | Stop the server. |
