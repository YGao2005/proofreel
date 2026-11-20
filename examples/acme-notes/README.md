# Acme Notes

A made-up notes app to record with proofreel. Run `python3 server.py` (stdlib only, port 8791).
`SLOW_SEARCH_MS=1500` slows `/api/search`. `BROKEN=1` makes `/api/tags` return 500.
In the `linux` state the guest reaches it at `http://10.0.2.2:8791`. Use `--set URL=...` to change that.
Run all three journeys: `proofreel suite examples/acme-notes/flows --out review-acme`.
