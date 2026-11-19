"""The review page: the video, a scrub bar with a mark for each step and check, and the list of actions."""

import html

from .draw import clock
from .motion import FAST

CSS = """
:root { --bg: #f6f7f9; --panel: #ffffff; --fg: #16181d; --muted: #5d6470; --line: #dfe2e8; --accent: #0a6cdf;
  --ok: #1d7a3a; --ok-bg: #e3f3e8; --bad: #b4232a; --bad-bg: #fbe5e6; --info: #4b5563; --info-bg: #eceef2;
  --sans: "Inter", system-ui, -apple-system, sans-serif; --mono: "IBM Plex Mono", ui-monospace, Menlo, monospace; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg: #101216; --panel: #181b21; --fg: #e8eaee;
  --muted: #9aa1ad; --line: #2a2f38; --accent: #6aa8ff; --ok: #6fd08f; --ok-bg: #173323; --bad: #ff8a8f; --bad-bg: #3a1a1d;
  --info: #b7bdc8; --info-bg: #252a32; color-scheme: dark } }
:root[data-theme="dark"] { --bg: #101216; --panel: #181b21; --fg: #e8eaee; --muted: #9aa1ad; --line: #2a2f38;
  --accent: #6aa8ff; --ok: #6fd08f; --ok-bg: #173323; --bad: #ff8a8f; --bad-bg: #3a1a1d; --info: #b7bdc8;
  --info-bg: #252a32; color-scheme: dark }
body { background: var(--bg); color: var(--fg); font: 14px/1.5 var(--sans); }
.wrap { max-width: 1320px; margin: 0 auto; padding-block: 28px 48px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
header { display: flex; flex-direction: column; gap: 8px; margin-bottom: 20px; }
h1 { font-size: 24px; line-height: 1.25; margin: 0; text-wrap: balance; }
.lede { color: var(--muted); max-width: 70ch; margin: 0; }
.meta { display: flex; flex-wrap: wrap; gap: 6px 18px; color: var(--muted); font: 12px/1.4 var(--mono); }
.chip { display: inline-block; font: 600 11px/1 var(--sans); letter-spacing: .04em; text-transform: uppercase;
  padding: 5px 8px; border-radius: 999px; background: var(--info-bg); color: var(--info); white-space: nowrap; }
.chip.ok { background: var(--ok-bg); color: var(--ok); } .chip.bad { background: var(--bad-bg); color: var(--bad); }
.grid { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 20px; align-items: start; }
@media (max-width: 900px) { .grid { grid-template-columns: minmax(0, 1fr); } }
.player { position: sticky; top: calc(12px + env(safe-area-inset-top, 0px)); background: var(--panel);
  border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
.player video { display: block; width: 100%; height: auto; background: #000; }
.bar { position: relative; height: 22px; margin: 8px 14px 0; cursor: pointer; }
.bar .track { position: absolute; left: 0; right: 0; top: 10px; height: 3px; border-radius: 2px; background: var(--line); }
.bar .done { position: absolute; left: 0; top: 10px; height: 3px; border-radius: 2px; background: var(--accent); }
.bar i { position: absolute; top: 5px; width: 3px; height: 13px; margin-left: -1px; border-radius: 2px; background: var(--muted); }
.bar i.ok { background: var(--ok); } .bar i.bad { background: var(--bad); height: 17px; top: 3px; }
.bar i.step { background: var(--fg); width: 2px; }
.player p { margin: 0; padding: 8px 14px 12px; color: var(--muted); font-size: 12px; }
ol { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
li button { all: unset; box-sizing: border-box; cursor: pointer; width: 100%; display: grid;
  grid-template-columns: 52px minmax(0, 1fr) auto; gap: 10px; align-items: start; padding: 8px 10px;
  border-radius: 8px; border: 1px solid transparent; }
li button:hover, li button:focus-visible { background: var(--panel); border-color: var(--line); }
li button:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
li.step button { margin-top: 10px; } li.step .text { font-weight: 600; font-size: 15px; }
li.now button { background: var(--panel); border-color: var(--accent); }
.t { font: 12px/1.6 var(--mono); color: var(--muted); font-variant-numeric: tabular-nums; }
.text { min-width: 0; overflow-wrap: anywhere; } .kind { color: var(--muted); font: 12px var(--mono); }
.detail { display: block; color: var(--muted); font: 12px/1.4 var(--mono); margin-top: 2px; white-space: pre-wrap; }
li img { width: 96px; border-radius: 4px; border: 1px solid var(--line); }
@media (max-width: 480px) { li img { width: 64px; } }
footer { margin-top: 28px; color: var(--muted); font-size: 12px; }
"""

SCRIPT = """
const video = document.querySelector("video");
const rows = [...document.querySelectorAll("li[data-t]")];
const bar = document.querySelector(".bar"), done = bar.querySelector(".done");
const seek = t => { video.currentTime = Math.max(0, t); video.play().catch(() => {}); };
rows.forEach(row => row.querySelector("button").addEventListener("click", () => seek(parseFloat(row.dataset.t) - 0.4)));
bar.addEventListener("click", e => {
  const box = bar.getBoundingClientRect();
  if (video.duration) seek((e.clientX - box.left) / box.width * video.duration);
});
const place = () => {
  if (!video.duration) return;
  bar.querySelectorAll("i").forEach(mark => mark.style.left = (parseFloat(mark.dataset.t) / video.duration * 100) + "%");
};
video.addEventListener("loadedmetadata", place);
video.addEventListener("timeupdate", () => {
  if (video.duration) done.style.width = (video.currentTime / video.duration * 100) + "%";
  let current = null;
  for (const row of rows) if (parseFloat(row.dataset.t) <= video.currentTime + 0.05) current = row;
  rows.forEach(row => row.classList.toggle("now", row === current));
});
place();
"""


def verdict(info, events):
    checks = [e for e in events if e["kind"] == "check"]
    failed = [e for e in checks if not e.get("ok")]
    if failed or info.get("error"):
        return "Problem", "bad", checks, failed
    return ("Works", "ok", checks, failed) if checks else ("Shown", "info", checks, failed)


def row(n, e):
    chip = ""
    if e["kind"] == "check":
        chip = '<span class="chip ok">Pass</span>' if e.get("ok") else '<span class="chip bad">Fail</span>'
    elif e["kind"] == "wait":
        chip = '<span class="chip ok">Seen</span>' if e.get("ok") else '<span class="chip bad">Not seen</span>'
    kind = "" if e["kind"] in ("step", "check", "note") else f'<span class="kind">{e["kind"]}</span> '
    detail = f'<span class="detail">{html.escape(e["detail"])}</span>' if e.get("detail") else ""
    image = f'<img src="{e["shot"]}" alt="" loading="lazy">' if e.get("shot") else "<span></span>"
    return (f'<li class="{e["kind"]}" data-t="{e["v"]:.2f}"><button type="button"><span class="t">{clock(e["t"])}</span>'
            f'<span class="text">{kind}{html.escape(e["text"])} {chip}{detail}</span>{image}</button></li>')


def mark(e):
    css = {"step": "step", "check": "ok" if e.get("ok") else "bad"}.get(e["kind"], "")
    if e["kind"] == "wait" and not e.get("ok"):
        css = "bad"
    return f'<i class="{css}" data-t="{e["v"]:.2f}" title="{html.escape(e["text"])}"></i>'


def write(folder, info, events, length, real):
    label, css, checks, failed = verdict(info, events)
    shown = [e for e in events if e["kind"] != "move"]
    meta = [f"{k} {v}" if k else str(v) for k, v in (info.get("meta") or {}).items() if v]
    meta += [f"{len(checks) - len(failed)}/{len(checks)} checks pass" if checks else "",
             f"{real:.0f} s of screen in a {length:.0f} s video"]
    title = html.escape(info.get("title") or folder.name)
    error = f'<p class="lede"><span class="chip bad">Stopped</span> {html.escape(info["error"])}</p>' if info.get("error") else ""
    about = f'<p class="lede">{html.escape(info["about"])}</p>' if info.get("about") else ""
    marks = "".join(mark(e) for e in shown if e["kind"] in ("step", "check", "wait"))
    body = f"""<title>{title}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&family=IBM+Plex+Mono&display=swap">
<style>{CSS}</style>
<div class="wrap">
<header>
  <div><span class="chip {css}">{label}</span></div>
  <h1>{title}</h1>
  {about}
  {error}
  <div class="meta">{"".join(f"<span>{html.escape(m)}</span>" for m in meta if m)}</div>
</header>
<div class="grid">
  <div class="player"><video controls playsinline muted preload="metadata" poster="poster.jpg" src="session.mp4"></video>
    <div class="bar"><div class="track"></div><div class="done"></div>{marks}</div>
    <p>Recorded from the screen as the agent drove it. Blue rings are clicks. The video is sped up to fit about 30 s: a badge shows the speed (up to {FAST}x with no change on the screen). The clock is real time. Click a row or a mark to jump to it.</p></div>
  <ol>{"".join(row(n, e) for n, e in enumerate(shown))}</ol>
</div>
<footer>Made with proofreel.</footer>
</div>
<script>{SCRIPT}</script>
"""
    (folder / "index.html").write_text(body)
    return label
