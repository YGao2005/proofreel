"""The review page. One template for a single run and for a run history published to one URL.

The page draws itself from embedded run data. The list shows the steps and checks; the actions between them fold
under one line. On claude.ai, the artifact's own comments work on any row, and the page adds a shared
Approve / Needs work review and questions about the current frame. Opened as a plain file, it is a static page.
"""

import html
import json
import shutil
from pathlib import Path

from .draw import clock
from .motion import FAST

CAPABILITIES = {"db": {}, "user": {"scopes": ["profile"]}, "sample": {"images": True}}

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
header { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; }
h1 { font-size: 24px; line-height: 1.25; margin: 0; text-wrap: balance; }
.lede { color: var(--muted); max-width: 70ch; margin: 0; }
.meta { display: flex; flex-wrap: wrap; gap: 6px 18px; color: var(--muted); font: 12px/1.4 var(--mono); }
.chip { display: inline-block; font: 600 11px/1 var(--sans); letter-spacing: .04em; text-transform: uppercase;
  padding: 5px 8px; border-radius: 999px; background: var(--info-bg); color: var(--info); white-space: nowrap; }
.chip.ok { background: var(--ok-bg); color: var(--ok); } .chip.bad { background: var(--bad-bg); color: var(--bad); }
.runs { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 16px; }
.runs button, .btn { all: unset; box-sizing: border-box; cursor: pointer; display: inline-flex; align-items: center; gap: 8px;
  padding: 6px 10px; border-radius: 8px; border: 1px solid var(--line); background: var(--panel); font: 13px/1.2 var(--sans); }
.runs button[aria-pressed="true"] { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }
.runs .when { color: var(--muted); font: 12px var(--mono); }
.btn:hover, .runs button:hover { border-color: var(--muted); }
.btn:focus-visible, .runs button:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
.btn[aria-pressed="true"].ok { background: var(--ok-bg); color: var(--ok); border-color: var(--ok); }
.btn[aria-pressed="true"].bad { background: var(--bad-bg); color: var(--bad); border-color: var(--bad); }
.btn.small { padding: 3px 8px; font-size: 12px; }
.grid { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 20px; align-items: start; }
@media (max-width: 900px) { .grid { grid-template-columns: minmax(0, 1fr); } }
.side { position: sticky; top: calc(12px + env(safe-area-inset-top, 0px)); display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.panel { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
.player video { display: block; width: 100%; height: auto; background: #000; }
.bar { position: relative; height: 22px; margin: 8px 14px 0; cursor: pointer; }
.bar .track { position: absolute; left: 0; right: 0; top: 10px; height: 3px; border-radius: 2px; background: var(--line); }
.bar .done { position: absolute; left: 0; top: 10px; height: 3px; border-radius: 2px; background: var(--accent); }
.bar i { position: absolute; top: 5px; width: 3px; height: 13px; margin-left: -1px; border-radius: 2px; background: var(--muted); }
.bar i.ok { background: var(--ok); } .bar i.bad { background: var(--bad); height: 17px; top: 3px; }
.bar i.step { background: var(--fg); width: 2px; }
.player p, .panel .body { margin: 0; padding: 8px 14px 12px; color: var(--muted); font-size: 12px; }
.panel h2 { font-size: 13px; margin: 0; padding: 12px 14px 0; }
.review .body { display: flex; flex-direction: column; gap: 8px; color: var(--fg); font-size: 13px; }
.review .choices { display: flex; gap: 8px; flex-wrap: wrap; }
.review .who { color: var(--muted); font-size: 12px; }
textarea { box-sizing: border-box; width: 100%; min-height: 56px; resize: vertical; padding: 8px; border-radius: 8px;
  border: 1px solid var(--line); background: var(--bg); color: var(--fg); font: 13px/1.4 var(--sans); }
.answer { white-space: pre-wrap; color: var(--fg); font-size: 13px; }
ol { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
li .row { display: grid; grid-template-columns: 52px minmax(0, 1fr) auto; gap: 10px; align-items: start; padding: 8px 10px;
  border-radius: 8px; border: 1px solid transparent; cursor: pointer; }
li .row:hover { background: var(--panel); border-color: var(--line); }
li .row:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
li.step .row { margin-top: 10px; } li.step .text { font-weight: 600; font-size: 15px; }
li.now .row { background: var(--panel); border-color: var(--accent); }
li.more > details > summary { list-style: none; cursor: pointer; padding: 2px 10px 2px 72px; color: var(--muted);
  font: 12px/1.6 var(--sans); border-radius: 6px; }
li.more > details > summary::-webkit-details-marker { display: none; }
li.more > details > summary::before { content: "\25B8"; display: inline-block; width: 1.2em; transition: transform .15s; }
li.more > details[open] > summary::before { transform: rotate(90deg); }
li.more > details > summary:hover { color: var(--fg); }
li.more.now > details > summary { color: var(--accent); }
li.more ol { margin: 4px 0 2px; gap: 2px; } li.more .row { padding: 4px 10px; } li.more .text { font-size: 13px; }
.view { display: flex; justify-content: flex-end; gap: 6px; padding: 8px 14px 0; }
.t { font: 12px/1.6 var(--mono); color: var(--muted); font-variant-numeric: tabular-nums; }
.text { min-width: 0; overflow-wrap: anywhere; } .kind { color: var(--muted); font: 12px var(--mono); }
.detail { display: block; color: var(--muted); font: 12px/1.4 var(--mono); margin-top: 2px; white-space: pre-wrap; }
li img { width: 96px; border-radius: 4px; border: 1px solid var(--line); }
@media (max-width: 480px) { li img { width: 64px; } li.more > details > summary { padding-left: 10px; } }
footer { margin-top: 28px; color: var(--muted); font-size: 12px; }
"""

SCRIPT = r"""
const RUNS = JSON.parse(document.getElementById("runs").textContent);
const $ = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") el.className = v; else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v); else el.setAttribute(k, v);
  }
  for (const kid of kids) if (kid) el.append(kid);
  return el;
};
const clock = s => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, "0")}`;
const caps = {};
let run = RUNS.length - 1;
const KEY_KINDS = ["step", "check", "wait", "note", "error"];
let zoom = true;
try { zoom = localStorage.getItem("proofreel-zoom") !== "0"; } catch (err) {}
const fromHash = () => {
  const m = /^#run-(\d+)$/.exec(location.hash);
  if (m && +m[1] >= 1 && +m[1] <= RUNS.length) run = +m[1] - 1;
};
fromHash();

function chip(label, css) { return $("span", { class: `chip ${css}`, text: label }); }

function render() {
  const r = RUNS[run], app = document.getElementById("app");
  app.replaceChildren();
  document.title = r.title;
  const header = $("header", {},
    $("div", {}, chip(r.verdict, r.verdict_css)),
    $("h1", { text: r.title }),
    r.about ? $("p", { class: "lede", text: r.about }) : null,
    r.error ? $("p", { class: "lede" }, chip("Stopped", "bad"), document.createTextNode(" " + r.error)) : null,
    $("div", { class: "meta" }, ...r.meta.map(m => $("span", { text: m }))));
  app.append(header);
  if (RUNS.length > 1) {
    const tabs = $("div", { class: "runs", role: "group", "aria-label": "Runs" });
    RUNS.forEach((x, i) => tabs.append($("button", { type: "button", "aria-pressed": String(i === run),
      onclick: () => { location.hash = `run-${i + 1}`; } },
      $("span", { text: `Run ${i + 1}` }), chip(x.verdict, x.verdict_css), $("span", { class: "when", text: x.when }))));
    app.append(tabs);
  }
  const source = () => r.base + (r.wide && !zoom ? "session-wide.mp4" : "session.mp4");
  const video = $("video", { controls: "", playsinline: "", muted: "", preload: "metadata", poster: r.base + "poster.jpg",
    src: source() });
  const zoomButton = r.wide ? $("button", { type: "button", class: "btn small", "aria-pressed": String(zoom),
    text: "Zoom", title: "Zoom in on each action", onclick: () => {
      zoom = !zoom;
      try { localStorage.setItem("proofreel-zoom", zoom ? "1" : "0"); } catch (err) {}
      zoomButton.setAttribute("aria-pressed", String(zoom));
      const at = video.currentTime, playing = !video.paused;
      video.src = source();
      video.addEventListener("loadedmetadata", () => { video.currentTime = at; if (playing) video.play().catch(() => {}); }, { once: true });
    } }) : null;
  const done = $("div", { class: "done" });
  const bar = $("div", { class: "bar" }, $("div", { class: "track" }), done);
  const shown = r.events.filter(e => e.kind !== "move");
  for (const e of shown.filter(e => ["step", "check", "wait"].includes(e.kind))) {
    const css = e.kind === "step" ? "step" : (e.ok ? "ok" : "bad");
    bar.append($("i", { class: css, "data-t": e.v, title: e.text }));
  }
  const seek = t => { video.currentTime = Math.max(0, t); video.play().catch(() => {}); };
  bar.addEventListener("click", ev => {
    const box = bar.getBoundingClientRect();
    if (video.duration) seek((ev.clientX - box.left) / box.width * video.duration);
  });
  const place = () => { if (video.duration) bar.querySelectorAll("i").forEach(m => m.style.left = (m.dataset.t / video.duration * 100) + "%"); };
  video.addEventListener("loadedmetadata", place);
  const player = $("div", { class: "panel player" }, zoomButton ? $("div", { class: "view" }, zoomButton) : null, video, bar,
    $("p", { text: `Recorded from the screen as the agent drove it. Blue rings are clicks. The video is sped up to about 30 s; a badge shows the speed (up to ${r.fast}x with no change on the screen). The clock is real time. Click a row or a mark to jump to it.` }));
  const side = $("div", { class: "side" }, player, reviewPanel(r), askPanel(r, video));
  const list = $("ol");
  let actions = null, summary = null;
  for (const e of shown) {
    if (KEY_KINDS.includes(e.kind)) { list.append(row(r, e, seek)); actions = null; continue; }
    if (!actions) {
      actions = $("ol");
      summary = $("summary");
      list.append($("li", { class: "more" }, $("details", {}, summary, actions)));
    }
    actions.append(row(r, e, seek));
    const n = actions.children.length;
    summary.textContent = `${n} action${n === 1 ? "" : "s"}`;
  }
  app.append($("div", { class: "grid" }, side, list));
  video.addEventListener("timeupdate", () => {
    if (video.duration) done.style.width = (video.currentTime / video.duration * 100) + "%";
    let current = null;
    const rows = list.querySelectorAll("li[data-t]");
    for (const li of rows) if (+li.dataset.t <= video.currentTime + 0.05) current = li;
    const folded = current && current.closest("details:not([open])");
    const mark = folded ? folded.parentElement : current;
    for (const li of list.querySelectorAll("li")) li.classList.toggle("now", li === mark);
  });
  place();
  watchReview(r);
}

function row(r, e, seek) {
  const status = e.kind === "check" ? chip(e.ok ? "Pass" : "Fail", e.ok ? "ok" : "bad")
    : e.kind === "wait" ? chip(e.ok ? "Seen" : "Not seen", e.ok ? "ok" : "bad") : null;
  const text = $("span", { class: "text" },
    ["step", "check", "note"].includes(e.kind) || e.text.startsWith(e.kind) ? null : $("span", { class: "kind", text: e.kind + " " }),
    document.createTextNode(e.text + " "), status, e.detail ? $("span", { class: "detail", text: e.detail }) : null);
  const body = $("div", { class: "row", tabindex: "0", role: "button", "aria-label": `Jump to ${clock(e.t)}: ${e.text}` },
    $("span", { class: "t", text: clock(e.t) }), text, e.shot ? $("img", { src: r.base + e.shot, alt: "", loading: "lazy" }) : $("span"));
  const li = $("li", { class: e.kind, "data-t": e.v }, body);
  const go = () => seek(e.v - 0.4);
  body.addEventListener("click", go);
  body.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); go(); } });
  return li;
}

function reviewPanel(r) {
  const panel = $("section", { class: "panel review", id: "review", hidden: "" });
  panel.append($("h2", { text: "Review" }));
  const body = $("div", { class: "body" });
  const choices = $("div", { class: "choices" });
  const who = $("div", { class: "who", text: "No review yet." });
  for (const [value, label, css] of [["approve", "Approve", "ok"], ["needs-work", "Needs work", "bad"]]) {
    choices.append($("button", { type: "button", class: `btn ${css}`, "data-v": value, "aria-pressed": "false", text: label,
      onclick: () => setReview(r, value) }));
  }
  body.append(choices, who);
  panel.append(body);
  return panel;
}

let unwatch = null;
function watchReview(r) {
  if (unwatch) { unwatch(); unwatch = null; }
  const panel = document.getElementById("review");
  if (!caps.db || !panel) return;
  panel.hidden = false;
  const timer = setTimeout(() => { panel.querySelector(".who").textContent = "Reviews are not loading here."; }, 10000);
  unwatch = caps.db.doc(`reviews/${r.id}`).onSnapshot(async snap => {
    clearTimeout(timer);
    const data = snap.exists ? snap.data() : null;
    panel.querySelectorAll("[data-v]").forEach(b => b.setAttribute("aria-pressed", String(!!data && b.dataset.v === data.verdict)));
    if (!data) { panel.querySelector(".who").textContent = "No review yet."; return; }
    let name = "Someone";
    if (caps.user && data.by) { const ps = await caps.user.profiles([data.by]); name = (ps[data.by] && ps[data.by].name) || "Someone"; }
    panel.querySelector(".who").textContent = `${data.verdict === "approve" ? "Approved" : "Needs work"} by ${name}, ${new Date(data.at).toLocaleString()}`;
  }, () => { clearTimeout(timer); panel.querySelector(".who").textContent = "Reviews are not available here."; });
}

async function setReview(r, verdict) {
  if (!caps.db) return;
  const who = document.querySelector("#review .who");
  try {
    const by = caps.user ? await caps.user.id() : null;
    await caps.db.doc(`reviews/${r.id}`).set({ verdict, run: run + 1, title: r.title, by, at: Date.now() });
  } catch (err) { who.textContent = "Only people who can edit this page can review it."; }
}

function askPanel(r, video) {
  const panel = $("section", { class: "panel", id: "ask", hidden: "" });
  const box = $("textarea", { "aria-label": "Ask about this moment", placeholder: "Ask about this moment, such as: why did the check fail?" });
  const answer = $("div", { class: "answer" });
  let controller = null;
  const ask = async () => {
    const question = box.value.trim();
    if (!question || !caps.sample) return;
    if (controller) controller.abort();
    controller = new AbortController();
    answer.textContent = "Thinking...";
    const at = video.currentTime;
    const log = r.events.filter(e => e.kind !== "move").map(e => `${clock(e.t)} (video ${e.v.toFixed(1)} s) ${e.kind}: ${e.text}${e.kind === "check" || e.kind === "wait" ? (e.ok ? " [pass]" : " [FAIL]") : ""}${e.detail ? " - " + e.detail : ""}`).join("\n");
    const prompt = `You review a recorded test run of an app. Answer the question in plain words, in at most 5 sentences. Say what the frame shows and what the log shows; do not guess beyond them.\n\nRun: ${r.title}\nAbout: ${r.about || ""}\nResult: ${r.verdict}${r.error ? " (stopped: " + r.error + ")" : ""}\nThe attached image is the video frame at ${at.toFixed(1)} s.\n\nLog:\n${log}\n\nQuestion: ${question}`;
    const images = [];
    try {
      const canvas = document.createElement("canvas");
      canvas.width = Math.min(1280, video.videoWidth || 1280);
      canvas.height = Math.round(canvas.width * (video.videoHeight || 720) / (video.videoWidth || 1280));
      canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
      images.push(await new Promise(ok => canvas.toBlob(ok, "image/jpeg", 0.85)));
    } catch (err) {}
    try {
      const out = await caps.sample(prompt, { images: images.filter(Boolean), signal: controller.signal, cache: false,
        onText: ({ text }) => { answer.textContent = text; } });
      answer.textContent = out.text;
    } catch (err) {
      if (err && err.code === "cancelled") return;
      answer.textContent = err && err.code === "rate_limited" ? "Too many questions. Wait a moment." : "Claude could not answer here.";
      if (err && (err.code === "not_granted" || err.code === "images_unavailable")) panel.hidden = err.code === "not_granted";
    }
  };
  panel.append($("h2", { text: "Ask about this moment" }),
    $("div", { class: "body" }, box, $("div", { class: "choices" }, $("button", { type: "button", class: "btn small", text: "Ask", onclick: ask })), answer));
  return panel;
}

window.addEventListener("hashchange", () => { fromHash(); render(); });
render();
(async () => {
  const use = name => (window.claude && window.claude.use ? window.claude.use(name) : Promise.resolve(null)).catch(() => null);
  const [db, user, sample] = await Promise.all([use("db"), use("user"), use("sample")]);
  Object.assign(caps, { db, user, sample });
  if (db || user || sample) render();
  if (sample) document.getElementById("ask").hidden = false;
})();
"""


def verdict(info, events):
    checks = [e for e in events if e["kind"] == "check"]
    failed = [e for e in checks if not e.get("ok")]
    if failed or info.get("error"):
        return "Problem", "bad", checks, failed
    return ("Works", "ok", checks, failed) if checks else ("Shown", "info", checks, failed)


def run_data(folder, info, events, length, real):
    label, css, checks, failed = verdict(info, events)
    meta = [f"{k} {v}" if k else str(v) for k, v in (info.get("meta") or {}).items() if v]
    meta += [f"{len(checks) - len(failed)}/{len(checks)} checks pass" if checks else "",
             f"{real:.0f} s of screen in a {length:.0f} s video"]
    keep = ("t", "v", "kind", "text", "ok", "detail", "shot")
    return {"id": folder.name, "title": info.get("title") or folder.name, "about": info.get("about", ""),
            "error": info.get("error", ""), "verdict": label, "verdict_css": css, "meta": [m for m in meta if m],
            "when": (info.get("meta") or {}).get("", ""), "fast": FAST, "base": "",
            "wide": (folder / "session-wide.mp4").exists(),
            "events": [{k: e[k] for k in keep if k in e} for e in events]}


def document(runs):
    data = json.dumps(runs).replace("</", "<\\/")
    title = html.escape(runs[-1]["title"])
    return f"""<title>{title}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&family=IBM+Plex+Mono&display=swap">
<style>{CSS}</style>
<div class="wrap"><main id="app"></main><footer>Made with <a href="https://github.com/YGao2005/proofreel">proofreel</a>.</footer></div>
<script type="application/json" id="runs">{data}</script>
<script>{SCRIPT}</script>
"""


def write(folder, info, events, length, real):
    run = run_data(folder, info, events, length, real)
    (folder / "run.json").write_text(json.dumps(run))
    (folder / "index.html").write_text(document([run]))
    return run["verdict"]


def publish(session, out):
    """Add a session to a review folder that holds every run of one journey, for one artifact URL. Returns the
    files of this run (published path -> source) for the Artifact tool, and the page path."""
    session, out = Path(session), Path(out)
    run = json.loads((session / "run.json").read_text())
    target = out / "runs" / run["id"]
    if target.exists():
        shutil.rmtree(target)
    (target / "shots").mkdir(parents=True)
    for name in ("session.mp4", "session-wide.mp4", "poster.jpg"):
        if (session / name).exists():
            shutil.copy2(session / name, target / name)
    for shot in (session / "shots").glob("*.jpg"):
        shutil.copy2(shot, target / "shots" / shot.name)
    manifest = out / "runs.json"
    runs = [r for r in (json.loads(manifest.read_text()) if manifest.exists() else []) if r["id"] != run["id"]]
    runs.append({**run, "base": f"runs/{run['id']}/"})
    manifest.write_text(json.dumps(runs))
    page = out / "index.html"
    page.write_text(document(runs))
    files = {str(p.relative_to(out)): str(p.resolve()) for p in sorted(target.rglob("*")) if p.is_file()}
    return page, files, len(runs)
