# Probes and budgets

A probe measures while a session records: the host's load, an app's CPU, request times. `host-load` is on for every
recording. `processes` is on for every Linux or macOS run VM: the CPU (`cpu/app`, % of one core) and memory (`mem/app`, MB)
of the process that `start --app` names and every process under it. Add another with `start --probe <name>` or a flow line `probe <name>`; `--probe none` turns the defaults
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
again (at most 12 lines; `--all` for every line, `--json` for all the numbers).

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
folder, the newest 6 runs, and every journey of the newest suite run, keep their rows; older runs keep the numbers.

**Network requests** (`--probe network`, Linux run VMs, `pip install mitmproxy`): a proxy on the host sees each
HTTP and HTTPS request that Chromium in the guest makes. Each request is a span in `net/<host>`, with its method and
path, its status and size, and the time to connect, to do TLS, to wait for the answer, and to receive it. A status of
400 or more, or no answer, is `failed`. It never keeps a query string, a header value, or a body, and a path part that
looks like an id, a token, or an email address shows as `:id` or `:email`. At `start`, the guest gets the proxy and
trusts a CA that is new for each session; at `stop`, both go, and the CA is deleted. Only the run VM may use the
proxy. A request from the guest to `10.0.2.2` (the host) goes through the proxy too, so a test server on the host is
measured.

## The probe contract

A probe is a folder like a condition (`probe.toml` and scripts), found in the same places. Its manifest has `name`,
`version`, `os` (the guest systems it works on), `fidelity` (what it does not measure well), `where` (`host` or
`guest`), `privacy` (what it can see), and `[values]`. More fields:

- `default = true` turns it on for every recording on its systems. `default`, `extras`, and `tunnel` may be a table by
  system: `default = { web = true }` turns it on for `web` only.
- `extras` names a package or command it needs. Without it, the probe is unavailable, and the note says how to
  install it.
- `port = true` gives it a free host port in `PROOFREEL_PORT`.
- `tunnel = <guest port>` gives a host probe `PROOFREEL_TUNNEL`, a host port on 127.0.0.1 that reaches that port on
  the guest's 127.0.0.1 while it runs. On `web`, it is the browser's own DevTools port.
- `setup = true` says that its `start` and `stop` scripts change the run VM for the recording (a proxy, a trusted CA).
  A `web` run has no shell, so it runs no scripts. The `network` probe reads the browser's DevTools Network events
  there, with the same series and fields as the proxy.
- `[tracks."<series glob>"]` sets how the page and `stats` show a series: `label`, `unit`, `better` (`lower` or
  `higher`), `max`, and `bands`.

A host probe is `run.py`. A guest probe is `run.sh` (macOS and Linux) or `run.ps1` (Windows), started over SSH. A
probe prints one JSON line for each measure: `{"m": "cpu/app", "v": 42}` is a sample,
`{"m": "net/GET /items", "d": 0.31, "ok": true}` is a span (something that took `d` seconds), and `{"m": "app/ready"}`
is a mark. A line can carry `t`, the time in the probe's own steady clock; proofreel moves it onto the host clock by
the probe's smallest delay. Control lines are `{"ready": true}`, `{"unavailable": "<why>"}` (the probe cannot measure
here), and `{"meta": {...}}`. Lines over 16 KB, over 200 a second, or past 64 series are counted and dropped; control
lines skip the rate limit. A probe never gets the guest password. The recorder keeps each measure in
`metrics/<probe>.jsonl`, and the probe's status in `metrics/probes.json`.

A host probe for a run VM gets `PROOFREEL_BIND` (the address to listen on), `PROOFREEL_HOST_FOR_GUEST` (that address
as the guest sees it), and `PROOFREEL_GUEST_IP` (the guest as the host sees it). Its `start` and `stop` scripts get
`PROOFREEL_PORT` and `PROOFREEL_HOST_FOR_GUEST`. A `host.sh` runs on the host first, in a copy of the folder (`$OUT`).

A `start` script runs once the host run runs; `stop` must work after a `start` that stopped half way. proofreel writes
each reset into the run record before its `start` runs, so a crash is undone at the next `start`, at `vm save`, or at
`stop`. A condition that lasts one recording uses the same list.
