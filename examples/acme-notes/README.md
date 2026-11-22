# Acme Notes

A made-up notes app to record with proofreel. Run `python3 server.py` (stdlib only, port 8791).
It keeps its 2 first notes and the 3 newest saved ones, so many runs see the same screen. `SLOW_SEARCH_MS=1500` slows `/api/search`. `BROKEN=1` makes `/api/tags` return 500.
The flows run in the `web` browser runner, which reaches it at `http://127.0.0.1:8791`. Use `--set URL=...` to change that. In a Linux VM, the guest reaches it at `http://10.0.2.2:8791`.
Run all three journeys: `proofreel suite examples/acme-notes/flows --out review-acme`.
