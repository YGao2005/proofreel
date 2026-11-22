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
const VERDICTS = { works: [Verdict.RUN.works, "ok"], problem: [Verdict.RUN.problem, "bad"], shown: [Verdict.RUN.shown, "info"] };
const toVideo = (r, real) => Tracks.along(r.clock, 0, 1, real);
const toReal = (r, video) => Tracks.along(r.clock, 1, 0, video);
const fastest = r => Math.round(Math.max(1, ...Tracks.timemap(r.clock).stretches(1).map(s => s.speed)));
const caps = {};
let run = RUNS.length - 1;
let zoom = true, view = null;
try { zoom = localStorage.getItem("proofreel-zoom") !== "0"; } catch (err) {}
const SUITE = RUNS.some(x => x.suite);
const suiteOf = x => x.suite ? x.suite.id : "";
if (SUITE && !location.hash) view = "journeys";
const MACHINE = RUNS.some(x => x.states && x.states.length);
const VISITS = { ok: [Verdict.VISIT.ok, "ok"], bad: [Verdict.VISIT.bad, "bad"], unchecked: [Verdict.VISIT.unchecked, "info"] };
const visitVerdict = v => v.ok === false ? "bad" : v.ok ? "ok" : "unchecked";
let startAt = null, tracksOpen = false, pickState = null;
const fromHash = () => {
  const m = /^#run-(\d+)(?:&t=(\d+(?:\.\d+)?))?$/.exec(location.hash);
  if (m && +m[1] >= 1 && +m[1] <= RUNS.length) { run = +m[1] - 1; startAt = m[2] === undefined ? null : +m[2]; }
};
fromHash();

function chip(label, css) { return $("span", { class: `chip ${css}`, text: label }); }
const ICONS = {
  play: "M7 5v14l11-7z", pause: "M7 5h4v14H7zM13 5h4v14h-4z", full: "M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5",
  zoom: "M11 4a7 7 0 1 0 0 14a7 7 0 1 0 0-14zM20 20l-4-4M8 11h6M11 8v6",
  help: "M12 21a9 9 0 1 0 0-18a9 9 0 1 0 0 18zM9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6v.6M12 17h.01",
  pin: "M9 4h6M10 4v5l-3 4h10l-3-4V4M12 13v7", chevron: "M9 6l6 6-6 6",
};
const icon = name => {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg"), p = document.createElementNS("http://www.w3.org/2000/svg", "path");
  s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("aria-hidden", "true"); s.setAttribute("class", "icon " + name);
  p.setAttribute("d", ICONS[name]); s.append(p);
  return s;
};
const VIEWS = [["journeys", "Journeys"], ["stats", "Stats"], ["network", "Network"]];
const titleOf = x => x.title;
const placeholder = text => $("div", { class: "empty-pane" }, $("p", { class: "placeholder", text }));

// A suite page switches between the journeys of the suite run on show; any other page, between the runs of one journey.
function runSwitch() {
  const shown = RUNS.map((x, i) => [x, i]).filter(([x]) => !SUITE || suiteOf(x) === suiteOf(RUNS[run]));
  if (shown.length < 2) return null;
  const nav = $("nav", { class: "seg runs", "aria-label": SUITE ? "Journeys" : "Runs" });
  for (const [x, i] of shown) {
    nav.append($("button", { type: "button", "aria-pressed": String(i === run),
      title: `${x.title}: ${VERDICTS[x.verdict][0]}, ${x.when}`, onclick: () => { location.hash = `run-${i + 1}`; } },
      $("span", { class: x.verdict === "problem" ? "bad" : "", text: x.title }), SUITE ? null : $("span", { class: "when", text: x.when.slice(5) })));
  }
  return nav;
}

// Each suite run in the folder, newest first: its pass count, then a row for each journey, in one table layout so the
// columns line up from one suite run to the next.
function journeysView() {
  if (!SUITE) return null;
  const box = $("div", { class: "journeys" });
  for (const id of [...new Set(RUNS.map(suiteOf))].reverse()) {
    const rows = RUNS.map((x, i) => [x, i]).filter(([x]) => suiteOf(x) === id), by = new Map();
    for (const row of rows) by.set(row[0].journey || row[0].id, [...(by.get(row[0].journey || row[0].id) || []), row]);
    const groups = [...by.values()].map(g => [g, g.find(([x]) => x.verdict === "problem") || g[0]]);
    const pass = groups.filter(([g, [x]]) => x.verdict !== "problem" && !x.flaky).length;
    const info = rows[0][0].suite || {};
    box.append($("h2", {}, $("span", { text: info.title || "Runs" }), $("span", { class: "meta", text: `${pass}/${groups.length} pass \u00b7 ${rows[0][0].when}` })));
    const body = $("tbody");
    for (const [g, [x, i]] of groups) {
      const sum = Verdict.summary(x), go = () => { location.hash = `run-${i + 1}`; }, bad = x.verdict === "problem" || x.flaky;
      body.append($("tr", { class: bad ? "bad" : "", tabindex: "0", "aria-current": String(g.some(([, j]) => j === run)), onclick: go,
        onkeydown: ev => { if (ev.key === "Enter") go(); } },
        $("td", {}, $("a", { href: `#run-${i + 1}`, text: g.length > 1 ? x.journey : x.title, onclick: ev => ev.stopPropagation() }),
          g.length > 1 ? $("span", { class: "m" }, ...g.map(([y, j]) => $("a", { href: `#run-${j + 1}`, class: y.verdict === "problem" ? "bad" : "", text: `#${y.attempt}`, onclick: ev => ev.stopPropagation() }))) : null,
          x.error ? $("span", { class: "m bad", text: x.error }) : null),
        $("td", {}, x.flaky ? chip(`Flaky ${x.flaky.passed}/${x.flaky.of}`, "bad") : chip(...VERDICTS[x.verdict])),
        $("td", { text: sum.checks.total ? `${sum.checks.passed}/${sum.checks.total}` : "-" }),
        $("td", { text: sum.budgets.failed ? `${sum.budgets.failed} failed` : "-" }),
        $("td", { text: x.video === false ? "-" : Tracks.format(x.real, "s") })));
    }
    box.append($("table", { class: "numbers journey-table" },
      $("colgroup", {}, ...["", "w112", "w88", "w112", "w96"].map(c => $("col", c ? { class: c } : {}))),
      $("thead", {}, $("tr", {}, ...["Journey", "Result", "Checks", "Budgets", "Length"].map(h => $("th", { text: h })))), body));
  }
  return box;
}

const metaLine = r => [...Verdict.words(Verdict.tally(r.events)), ...(r.video !== false ? [Tracks.format(r.real, "s")] : []), ...r.meta, ...(r.flaky ? [`flaky ${r.flaky.passed}/${r.flaky.of}`] : [])];

let keys = null;

function render() {
  const r = RUNS[run], app = document.getElementById("app");
  app.replaceChildren();
  document.title = r.title;
  const recorded = r.video !== false;
  const video = $("video", recorded ? { playsinline: "", muted: "", preload: "metadata", poster: r.base + "poster.jpg", src: r.base + "session.mp4" } : {});
  const readoutPill = $("span", { class: "pill live", hidden: "" });
  const overlay = r.overlay ? $("div", { class: "overlay", "aria-hidden": "true" },
    $("div", { class: "top" }, $("span", { class: "pill clock" }), $("span", { class: "pill state" }), $("span", { class: "pill speed" })),
    $("span", { class: "pill now" }), $("div", { class: "bottom" }, readoutPill, $("span", { class: "pill caption" }))) : null;
  const screen = $("div", { class: "screen" }, video, overlay);
  const update = () => {
    stage(r, video, overlay);
    const real = toReal(r, video.currentTime);
    tracks.readout(real);
    flow.now(real);
    if (video.duration) stack.style.setProperty("--at", (video.currentTime / video.duration * 100) + "%");
    time.textContent = `${clock(Math.max(0, real))} / ${clock(r.real)}`;
    bar.setAttribute("aria-valuenow", real.toFixed(1));
    bar.setAttribute("aria-valuetext", `${clock(Math.max(0, real))} of ${clock(r.real)}`);
  };
  const toggle = (label, name, on, title, flip) => {
    const b = $("button", { type: "button", class: "btn tool", "aria-pressed": String(on), title }, icon(name), $("span", { class: "label", text: label }));
    b.addEventListener("click", () => { on = !on; b.setAttribute("aria-pressed", String(on)); flip(on); });
    return b;
  };
  const zoomButton = r.camera && r.camera.length ? toggle("Zoom", "zoom", zoom, "Zoom in on each action", on => {
    zoom = on;
    try { localStorage.setItem("proofreel-zoom", zoom ? "1" : "0"); } catch (err) {}
    update();
  }) : null;
  // WHY: iPhone Safari has no element full screen, only the video's own player.
  const goFull = screen.requestFullscreen ? () => screen.requestFullscreen().catch(() => {}) : video.webkitEnterFullscreen ? () => video.webkitEnterFullscreen() : null;
  const fullButton = goFull ? $("button", { type: "button", class: "btn tool icon-only", title: "Full screen",
    "aria-label": "Full screen", onclick: goFull }, icon("full")) : null;
  const play = $("button", { type: "button", class: "btn tool icon-only play", "aria-label": "Play", onclick: () => video.paused ? video.play().catch(() => {}) : video.pause() }, icon("play"));
  const paint = () => { play.replaceChildren(icon(video.paused ? "play" : "pause")); play.setAttribute("aria-label", video.paused ? "Play" : "Pause"); };
  const mark = () => {
    if (video.paused) history.replaceState(null, "", `#run-${run + 1}&t=${Math.max(0, toReal(r, video.currentTime)).toFixed(1)}`);
  };
  video.addEventListener("play", paint); video.addEventListener("pause", paint);
  video.addEventListener("pause", mark); video.addEventListener("seeked", mark);
  video.addEventListener("click", () => play.click());
  const tick = () => { update(); if (!video.paused) requestAnimationFrame(tick); };
  video.addEventListener("play", () => requestAnimationFrame(tick));
  for (const name of ["seeked", "loadedmetadata", "timeupdate"]) video.addEventListener(name, update);
  const time = $("span", { class: "time" });
  const bar = $("div", { class: "bar", role: "slider", "aria-label": "Seek", tabindex: "0", "aria-valuemin": "0", "aria-valuemax": r.real.toFixed(1), "aria-valuenow": "0" }, $("div", { class: "track" }), $("div", { class: "done" }));
  for (const e of r.events.filter(e => ["step", "check", "wait"].includes(e.kind))) {
    const css = e.kind === "step" ? "step" : (e.ok ? "ok" : "bad");
    bar.append($("i", { class: css, "data-t": toVideo(r, e.t), title: `${clock(e.t)} ${e.text}` }));
  }
  const seek = t => { video.currentTime = Math.max(0, t); video.play().catch(() => {}); };
  const jump = real => { video.currentTime = Math.max(0, toVideo(r, real)); };
  bar.addEventListener("click", ev => {
    const box = bar.getBoundingClientRect();
    if (video.duration) seek((ev.clientX - box.left) / box.width * video.duration);
  });
  bar.addEventListener("keydown", ev => {
    const step = { ArrowLeft: -1, ArrowRight: 1, PageDown: -5, PageUp: 5 }[ev.key];
    if (step && video.duration) { ev.preventDefault(); video.currentTime = Math.min(video.duration, Math.max(0, video.currentTime + step)); }
  });
  const shortcuts = [["Space", "Play or pause"], ["Left, Right", "Back or forward 1 s (Shift: 5 s)"], ["J K", "Previous or next step"],
    ["N", "Next failure"], ["Esc", "Close a tab or unpin a state"]];
  const help = $("details", { class: "help" }, $("summary", { class: "btn tool icon-only", "aria-label": "About this video", title: "About this video" }, icon("help")),
    $("div", { class: "pop" },
      $("p", { text: `Recorded from the screen as the agent drove it. Blue rings are clicks. The video is sped up to about 30 s; a badge shows the speed (up to ${fastest(r)}x with no change on the screen). The clock is real time.` }),
      $("dl", {}, ...shortcuts.flatMap(([k, what]) => [$("dt", { text: k }), $("dd", { text: what })]))));
  const tracks = metricTracks(r, readoutPill, seek);
  const flow = flowPanel(r, seek);
  const timebar = $("div", { class: "timebar" }, $("div", { class: "lead" }, play, time), bar, $("div", { class: "tools" }, zoomButton, fullButton, help));
  const place = () => {
    if (!video.duration) return;
    bar.querySelectorAll("i").forEach(m => m.style.left = (m.dataset.t / video.duration * 100) + "%");
    if (video.videoWidth) document.documentElement.style.setProperty("--ratio", video.videoWidth / video.videoHeight);
  };
  video.addEventListener("loadedmetadata", place);
  if (startAt !== null) {
    const from = startAt;
    startAt = null;
    video.addEventListener("loadedmetadata", () => { video.currentTime = toVideo(r, from); }, { once: true });
  }
  const stagePanel = $("section", { class: "panel stage", "aria-label": "Recording" },
    ...(recorded ? [$("div", { class: "media" }, screen), timebar] : [placeholder(r.error ? `No video: ${r.error}` : "This run made no video.")]));

  const panes = { journeys: journeysView(), stats: statsView(r, seek), network: networkView(r, seek) };
  const views = VIEWS.filter(([name]) => panes[name]);
  if (!panes[view]) view = null;
  const tabs = $("div", { class: "tabs", role: "tablist", "aria-label": "Details" });
  const body = $("div", { class: "body" }, ...Object.values(panes).filter(Boolean));
  const show = () => {
    for (const [name, pane] of Object.entries(panes)) if (pane) pane.hidden = name !== view;
    body.hidden = !view;
    tabs.querySelectorAll("[role=tab]").forEach(b => {
      b.setAttribute("aria-selected", String(b.dataset.view === view));
      b.tabIndex = b.dataset.view === (view || views[0][0]) ? 0 : -1;
    });
  };
  for (const [name, label] of views) {
    panes[name].setAttribute("role", "tabpanel"); panes[name].id = `pane-${name}`; panes[name].setAttribute("aria-labelledby", `tab-${name}`);
    tabs.append($("button", { type: "button", role: "tab", id: `tab-${name}`, "data-view": name, "aria-controls": `pane-${name}`,
      onclick: () => { view = view === name ? null : name; show(); } }, label));
  }
  tabs.addEventListener("keydown", ev => {
    const list = [...tabs.querySelectorAll("[role=tab]")], at = list.indexOf(document.activeElement);
    const to = { ArrowRight: (at + 1) % list.length, ArrowLeft: (at - 1 + list.length) % list.length, Home: 0, End: list.length - 1 }[ev.key];
    if (at < 0 || to === undefined) return;
    ev.preventDefault();
    list[to].tabIndex = 0;
    list[at].tabIndex = -1;
    list[to].focus();
  });
  show();
  const fade = () => tabs.classList.toggle("overflow", tabs.scrollWidth > tabs.clientWidth + 1);
  if (window.ResizeObserver) new ResizeObserver(fade).observe(tabs);
  const open = (name, t) => {
    view = name;
    show();
    const row = body.querySelector(`#pane-${name} [data-t="${t}"]`);
    if (!row) return;
    row.scrollIntoView({ block: "center" });
    row.classList.add("hit");
    setTimeout(() => row.classList.remove("hit"), 1200);
  };
  const viewsPanel = $("section", { class: "panel views" }, $("div", { class: "head" }, tabs), body);
  const dock = $("aside", { class: "panel dock", "aria-label": "Ask" }, askPanel(r, video));
  const cols = $("div", { class: "cols" }, $("div", { class: "main" }, stagePanel, tracks.panel), flow.element);
  const stack = $("div", { class: "stack", style: "--at:0%" }, cols, viewsPanel, dock);
  app.append(header(r, seek, open), stack);
  const fit = () => app.style.setProperty("--cols-h", Math.max(440, Math.floor(innerHeight - cols.getBoundingClientRect().top - scrollY - 16)) + "px");
  window.onresize = fit;
  if (window.ResizeObserver) new ResizeObserver(fit).observe(app.lastChild);
  fit();
  update();
  place();
  watchReview(r);
  const failures = [...new Set([...r.events.filter(e => e.ok === false && ["check", "wait"].includes(e.kind)).map(e => e.t), ...(Verdict.cause(r) ? [Verdict.cause(r).t] : [])])].sort((a, b) => a - b);
  const stepTimes = r.events.filter(e => e.kind === "step").map(e => e.t);
  keys = { video, play, jump,
    now: () => toReal(r, video.currentTime),
    steps: stepTimes, failures,
    escape: () => {
      if (help.open) { help.open = false; return true; }
      if (view) { view = null; show(); return true; }
      return flow.unpin();
    } };
}

function header(r, seek, open) {
  const cause = r.verdict === "problem" ? Verdict.cause(r) : null;
  const jump = cause && $("button", { type: "button", class: "cause", onclick: () => {
    seek(toVideo(r, cause.t) - 0.2);
    if (cause.target === "network") open("network", cause.t);
  } }, $("span", { text: cause.text }), $("span", { class: "t", text: clock(cause.t) }));
  return $("header", { class: "top" },
    $("div", { class: "title" },
      $("div", { class: "name" }, chip(...VERDICTS[r.verdict]), $("h1", { text: r.title })),
      r.about ? $("p", { class: "lede", text: r.about }) : null,
      jump,
      $("div", { class: "meta" }, ...metaLine(r).map(m => $("span", { text: m })))),
    $("div", { class: "side" }, reviewControl(r), runSwitch()));
}

window.addEventListener("keydown", ev => {
  if (!keys || ev.defaultPrevented || ev.metaKey || ev.ctrlKey || ev.altKey) return;
  const target = ev.target;
  if (target.closest && target.closest("input, textarea, select, [contenteditable]")) return;
  const real = keys.now();
  const near = (list, after) => list.find(t => after ? t > real + 0.05 : t < real - 0.05);
  const key = ev.key;
  if (key === "Escape") { if (keys.escape()) ev.preventDefault(); return; }
  if (key === " ") {
    if (target.closest && target.closest("button, summary, a, [role=button], [role=tab], [role=slider]")) return;
    ev.preventDefault();
    keys.play.click();
  } else if (key === "ArrowLeft" || key === "ArrowRight") {
    ev.preventDefault();
    const step = (ev.shiftKey ? 5 : 1) * (key === "ArrowLeft" ? -1 : 1);
    keys.video.currentTime = Math.min(keys.video.duration || Infinity, Math.max(0, keys.video.currentTime + step));
  } else if (key === "j" || key === "J") { const t = near(keys.steps.slice().reverse(), false); if (t !== undefined) keys.jump(t); }
  else if (key === "k" || key === "K") { const t = near(keys.steps, true); if (t !== undefined) keys.jump(t); }
  else if (key === "n" || key === "N") { const t = near(keys.failures, true) ?? keys.failures[0]; if (t !== undefined) keys.jump(t); }
});

const calm = window.matchMedia("(prefers-reduced-motion: reduce)");
const ease = x => { x = Math.min(Math.max(x, 0), 1); return x * x * (3 - 2 * x); };
function cameraAt(camera, video) {
  let i = 1;
  while (i < camera.length - 1 && camera[i][0] <= video) i++;
  const [a, b] = [camera[i - 1], camera[i] || camera[i - 1]];
  const k = b[0] > a[0] ? Math.min(Math.max((video - a[0]) / (b[0] - a[0]), 0), 1) : 0;
  return [1, 2, 3].map(j => a[j] + (b[j] - a[j]) * k);
}
const keysLabel = text => text.split(/\s+/).map(combo => combo.split("-").map(p => ({ cmd: "Cmd", command: "Cmd",
  ctrl: "Ctrl", opt: "Opt", option: "Opt", alt: "Alt", shift: "Shift", enter: "Return", bsp: "Delete", esc: "Esc",
  tab: "Tab", space: "Space", pgdn: "Page Down", pgup: "Page Up" })[p] || (p.length === 1 ? p.toUpperCase() :
  p[0].toUpperCase() + p.slice(1))).join("+")).join("  ");
const chipText = (e, r) => e.kind === "check" ? (e.ok ? "Pass: " : "Fail: ") + (e.budget ? Verdict.budgetOf(r, e) : e.text) + (e.reported ? " (reported)" : "")
  : e.kind === "wait" && e.detail ? `${e.text}: ${Verdict.sentence(e.detail).toLowerCase()}` : e.kind === "key" ? keysLabel(e.text) : e.text;

const PREFS = (() => { try { return JSON.parse(localStorage.getItem("proofreel-tracks")) || {}; } catch (err) { return {}; } })();
const savePrefs = () => { try { localStorage.setItem("proofreel-tracks", JSON.stringify(PREFS)); } catch (err) {} };
const groupOf = s => s.m.split("/")[0];
const nameOf = s => s.label || s.m;
const metricsOf = r => (r.metrics && r.metrics.series) || [];
const budgetsOf = (r, s) => ((r.metrics && r.metrics.budgets) || []).filter(b => b.series.includes(s.m));
const rankOf = (r, s) => budgetsOf(r, s).some(b => b.ok === false) ? 0 : groupOf(s) === "input" ? 1 : budgetsOf(r, s).length ? 2 : 3;
const W = 600;
const SVG = (tag, attrs = {}) => {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
};
const limitOf = b => b.below !== null && b.below !== undefined ? b.below : b.above;

// One row on the video's time axis for each series, the way its record looks: samples as a line in their lo-hi
// envelope, spans in rows (+N when more do not fit), marks as ticks. Sped-up stretches are hatched and labelled.
// A chip per group hides its rows; a pin per series puts it in the readout on the video. The panel is one row until the
// viewer opens it, and stays open across runs; the readout on the video shows only while it is open.
function metricTracks(r, live, seek) {
  const drawn = metricsOf(r).filter(s => s.points || s.spans || s.marks);
  const series = [...drawn.filter(s => rankOf(r, s) === 0), ...drawn.filter(s => rankOf(r, s) !== 0)];
  const map = Tracks.timemap(r.clock), length = r.length || map.video(r.real) || 1;
  const x = t => map.video(t) / length * W, pct = v => `${v / W * 100}%`;
  const pins = () => PREFS.pins || [...new Set(series.map(groupOf))].map(g => series.find(s => groupOf(s) === g).m).slice(0, 3);
  let open = tracksOpen, at = 0;
  const readout = real => {
    at = real;
    const shown = series.filter(s => pins().includes(s.m));
    live.hidden = !shown.length || !open;
    live.replaceChildren(...shown.map(s => $("span", {}, $("b", { text: nameOf(s) }), Tracks.format(Tracks.valueAt(s, real), s.unit))));
  };
  if (!series.length) return { readout, panel: null };
  const stretches = map.stretches();
  const hatch = lane => stretches.forEach(st => lane.append($("span", { class: "stretch", style: `left:${st.from / length * 100}%;width:${(st.to - st.from) / length * 100}%`,
    title: `Plays at up to ${Math.round(st.speed)}x` })));
  const failed = ((r.metrics && r.metrics.budgets) || []).some(b => b.ok === false);
  const lanes = $("div", { class: "lanes" });
  const hidden = new Set(PREFS.hidden || crowded(r, series)), rows = [];
  const chips = $("div", { class: "chips metric" });
  for (const g of new Set(series.map(groupOf))) {
    const b = $("button", { type: "button", class: "toggle", "aria-pressed": String(!hidden.has(g)), title: `Show the ${Tracks.groupName(g)} rows`, text: Tracks.groupName(g) });
    b.addEventListener("click", () => {
      hidden.has(g) ? hidden.delete(g) : hidden.add(g);
      b.setAttribute("aria-pressed", String(!hidden.has(g)));
      PREFS.hidden = [...hidden];
      savePrefs();
      show();
    });
    chips.append(b);
  }
  for (const s of series) {
    const lane = $("div", { class: `lane metric ${s.kind}`, title: `${s.m}: ${statLine(s)}` });
    lane.addEventListener("click", ev => {
      const box = lane.getBoundingClientRect();
      seek((ev.clientX - box.left) / box.width * length);
    });
    drawLane(r, s, lane, x, pct, seek, map);
    hatch(lane);
    const pin = $("button", { type: "button", class: "pin-btn", "aria-pressed": String(pins().includes(s.m)),
      title: `Show ${nameOf(s)} on the video`, "aria-label": `Pin ${nameOf(s)}` }, icon("pin"));
    pin.addEventListener("click", () => {
      const now = pins();
      PREFS.pins = now.includes(s.m) ? now.filter(m => m !== s.m) : [...now, s.m];
      savePrefs();
      lanes.querySelectorAll(".pin-btn").forEach((b, i) => b.setAttribute("aria-pressed", String(PREFS.pins.includes(series[i].m))));
    });
    const label = $("span", { class: `lane-label${rankOf(r, s) === 0 ? " bad" : ""}`, text: nameOf(s), title: s.m });
    rows.push([groupOf(s), label, lane, pin]);
    lanes.append(label, lane, pin);
  }
  const axis = $("div", { class: "axis", "aria-hidden": "true" });
  for (const t of Tracks.ticks(0, r.real)) {
    const left = map.video(t) / length * 100;
    axis.append($("span", { class: `tick${left > 92 ? " last" : ""}${left < 1 ? " first" : ""}`, style: `left:${left}%`, text: Tracks.axisLabel(t) }));
  }
  lanes.append(axis);
  const show = () => {
    rows.forEach(([g, ...els]) => els.forEach(el => { el.hidden = hidden.has(g); }));
    axis.hidden = rows.every(([g]) => hidden.has(g));
  };
  show();
  const fold = $("button", { type: "button", class: "fold", "aria-expanded": String(open), title: "Show the metric rows" },
    icon("chevron"), $("span", { text: "Tracks" }));
  const panel = $("section", { class: `panel tracks${failed ? " bad" : ""}`, "aria-label": "Tracks" },
    $("div", { class: "head" }, fold, chips, failed ? chip("Budget failed", "bad") : null), lanes);
  const paint = () => {
    fold.setAttribute("aria-expanded", String(open));
    lanes.hidden = !open;
    chips.hidden = !open;
    readout(at);
  };
  fold.addEventListener("click", () => { tracksOpen = open = !open; paint(); });
  paint();
  return { readout, panel };
}

// WHY: many series would push the video off a short window, so past ROWS rows a group starts hidden. Groups with a
// failed budget, then input latency, then a budget, keep their rows first.
const ROWS = 8;
function crowded(r, series) {
  const best = g => Math.min(...series.filter(s => groupOf(s) === g).map(s => rankOf(r, s)));
  const groups = [...new Set(series.map(groupOf))].map((g, i) => [best(g), i, g]).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  let rows = 0;
  return groups.map(([, , g]) => g).filter(g => {
    const n = series.filter(s => groupOf(s) === g).length;
    if (rows && rows + n > ROWS) return true;
    rows += n;
    return false;
  });
}

function drawLane(r, s, lane, x, pct, seek, map) {
  if (s.kind === "sample") {
    const cols = Tracks.bin(s.points, x, W), on = cols.map((c, i) => c && [i + 0.5, c]).filter(Boolean);
    const limits = budgetsOf(r, s).filter(b => !["count", "failed"].includes(b.stat));
    const top = s.max || Math.max(1e-9, ...on.map(([, c]) => c.hi), ...limits.map(limitOf), ...(s.bands || [])) * 1.1;
    const y = v => 30 - Math.min(Math.max(v / top, 0), 1) * 28;
    const svg = SVG("svg", { viewBox: `0 0 ${W} 30`, preserveAspectRatio: "none" });
    if (on.length) {
      svg.append(SVG("path", { class: "env", d: "M" + on.map(([i, c]) => `${i},${y(c.hi)}`).join(" L") + " L" + on.slice().reverse().map(([i, c]) => `${i},${y(c.lo)}`).join(" L") + "Z" }));
      svg.append(SVG("path", { class: "line", d: "M" + on.map(([i, c]) => `${i},${y(c.v)}`).join(" L") }));
    }
    for (const v of s.bands || []) svg.append(SVG("line", { class: "band", x1: 0, x2: W, y1: y(v), y2: y(v) }));
    for (const b of limits) svg.append(SVG("line", { class: `limit ${b.ok === false ? "bad" : ""}`, x1: 0, x2: W, y1: y(limitOf(b)), y2: y(limitOf(b)) }));
    lane.append(svg);
    const first = x(s.points[0][0]) / W, last = x(s.points[s.points.length - 1][0]) / W;
    if (first > 0.005) lane.append($("span", { class: "nodata", title: "No data", style: `left:0;width:${first * 100}%` }));
    if (last < 0.995) lane.append($("span", { class: "nodata", title: "No data", style: `left:${last * 100}%;right:0` }));
  } else if (s.kind === "span") {
    const items = s.spans.map(([t, d, ok, label]) => ({ from: x(t), to: x(t + d), t, d, ok, label })).sort((a, b) => a.from - b.from);
    const { row, more } = Tracks.pack(items, 3);
    items.forEach((it, i) => {
      if (row[i] < 0) return;
      const bad = it.ok === false;
      const el = $("i", { class: bad ? "bad" : "", title: `${it.label || s.m}: ${Tracks.format(it.d, "s")}`,
        style: `left:${pct(it.from)};width:${pct(Math.max(it.to - it.from, 1))}${bad ? "" : `;top:${4 + row[i] * 8}px`}` });
      el.addEventListener("click", ev => { ev.stopPropagation(); seek(map.video(it.t) - 0.2); });
      lane.append(el);
    });
    lane.style.height = `${Math.max(16, 8 + 8 * Math.max(1, Math.max(...row) + 1))}px`;
    if (more + (s.more || 0)) lane.append($("span", { class: "more", text: `+${more + (s.more || 0)}` }));
  } else {
    for (const [t, ok, label] of s.marks) lane.append($("b", { class: ok === false ? "bad" : "", style: `left:${pct(x(t))}`, title: label || s.m }));
    if (s.more) lane.append($("span", { class: "more", text: `+${s.more}` }));
  }
}

const statLine = s => s.stats.p50 === undefined ? `${s.stats.count} marks` :
  `p50 ${Tracks.format(s.stats.p50, s.unit)}, p95 ${Tracks.format(s.stats.p95, s.unit)}, max ${Tracks.format(s.stats.max, s.unit)}`;

// The numbers of the run: one table, a row for each series (failing budgets first) with p50, p95, max, and each budget as
// a sentence with its result. A row jumps the video to the series' worst moment.
const budgetChip = b => b.ok === false ? [VISITS.bad[0], "bad"] : b.ok ? [VISITS.ok[0], "ok"] : [VISITS.unchecked[0], "info"];
function statsView(r, seek) {
  const series = metricsOf(r), budgets = (r.metrics && r.metrics.budgets) || [];
  if (!series.length && !budgets.length) return placeholder("No metrics in this run. Probes measure while a session records; proofreel probes lists them.");
  const box = $("div", { class: "stats" });
  const worst = s => s.points ? s.points.reduce((a, p) => (p[3] ?? p[1]) > (a[3] ?? a[1]) ? p : a)[0]
    : s.spans ? s.spans.reduce((a, p) => p[1] > a[1] ? p : a)[0] : s.marks && s.marks.length ? s.marks[0][0] : null;
  const go = s => { const t = worst(s); if (t !== null) seek(toVideo(r, t) - 0.3); };
  const sentence = b => $("div", { class: `budget${b.ok === false ? " bad" : ""}` }, $("span", { text: Verdict.budgetText(b, r, b.detail) }), chip(...budgetChip(b)));
  const body = $("tbody");
  for (const b of budgets.filter(b => !b.series.length)) body.append($("tr", { class: "bad" },
    $("td", {}, document.createTextNode(b.glob), $("span", { class: "m", text: b.detail || "no data" })),
    $("td", { colspan: "3", text: "-" }), $("td", {}, sentence(b))));
  for (const s of series.slice().sort((a, b) => rankOf(r, a) - rankOf(r, b))) {
    const mine = budgetsOf(r, s), none = s.stats.p50 === undefined;
    body.append($("tr", { class: mine.some(b => b.ok === false) ? "bad" : "", tabindex: "0", onclick: () => go(s),
      onkeydown: ev => { if (ev.key === "Enter") go(s); } },
      $("td", {}, document.createTextNode(nameOf(s)), s.label ? $("span", { class: "m", text: s.m }) : null,
        s.stats.failed && groupOf(s) === "input" ? $("span", { class: "m bad", text: `${Verdict.plural(s.stats.failed, "input")} got no change on the screen` }) : null),
      ...(none ? [$("td", { colspan: "3", text: Verdict.plural(s.stats.count, "mark") })] : ["p50", "p95", "max"].map(k => $("td", { text: Tracks.format(s.stats[k], s.unit) }))),
      $("td", {}, ...mine.map(sentence))));
  }
  box.append($("table", { class: "numbers stats-table" },
    $("colgroup", {}, ...["", "w96", "w96", "w96", "budget"].map(c => $("col", c ? { class: c } : {}))),
    $("thead", {}, $("tr", {}, ...["Series", "p50", "p95", "max", "Budget"].map(h => $("th", { text: h })))), body));
  const quiet = Object.entries((r.metrics && r.metrics.probes) || {}).filter(([, p]) => p.status && p.status !== "ok");
  for (const [name, p] of quiet) box.append($("p", { class: "hint", text: `Probe ${name} ${p.status}${p.note ? ": " + p.note : ""}` }));
  return box;
}

// Each request (a span with phases) as a row of a waterfall, in start order: the request, its bars on one time axis, its
// status and time. A row jumps the video to its start.
function networkView(r, seek) {
  const fall = Tracks.waterfall(metricsOf(r));
  if (!fall.rows.length) return placeholder("No requests in this run. A web run records them; in a VM, start with --probe network.");
  const span = fall.to - fall.from || 1;
  const axis = $("div", { class: "req axis-row", "aria-hidden": "true" }, $("span"), $("div", { class: "axis" },
    ...Tracks.ticks(fall.from, fall.to).map(t => $("span", { class: "tick", style: `left:${(t - fall.from) / span * 100}%`, text: Tracks.axisLabel(t) }))), $("span"));
  const box = $("div", { class: "net" },
    $("div", { class: "legend" }, ...fall.names.map((name, i) => $("span", {}, $("i", { class: `p${i % 5}` }), name))), axis);
  const CAP = 500;
  for (const q of fall.rows.slice(0, CAP)) {
    const bad = q.ok === false, split = Tracks.request(q.label), tail = split.path.length > 16 ? 12 : 0;
    const bar = $("div", { class: "fall" }, $("span", { class: "whole", style: `left:${q.left * 100}%;width:${q.width * 100}%` }),
      ...q.parts.map(([name, left, width]) => $("span", { class: `p${fall.names.indexOf(name) % 5}`, title: `${name} ${Tracks.format(width * span, "s")}`,
        style: `left:${left * 100}%;width:${width * 100}%` })));
    box.append($("div", { class: `req${bad ? " bad" : ""}`, tabindex: "0", role: "button", title: q.label, "data-t": q.t,
      onclick: () => seek(toVideo(r, q.t) - 0.2), onkeydown: ev => { if (ev.key === "Enter") seek(toVideo(r, q.t) - 0.2); } },
      $("span", { class: "name" }, $("span", { class: "dim", text: `${split.method} ` }), $("span", { class: "dim host", text: split.host }),
        $("span", { class: "path head", text: tail ? split.path.slice(0, -tail) : split.path }), tail ? $("span", { class: "path tail", text: split.path.slice(-tail) }) : null),
      bar,
      $("span", { class: "d" }, q.status ? (bad ? chip(String(q.status), "bad") : $("span", { class: "dim", text: String(q.status) })) : null, $("span", { text: Tracks.format(q.d, "s") }))));
  }
  if (fall.rows.length > CAP) box.append($("p", { class: "hint", text: `${Verdict.plural(fall.rows.length - CAP, "more request")} not listed.` }));
  return box;
}

// The page draws on the video what the video does not: where the camera looks, the clock, the speed, the step, and
// the last action or check. Times come from the run's clock, so they line up with every speed of the video.
function stage(r, video, overlay) {
  const at = video.currentTime;
  if (r.camera && r.camera.length) {
    const [cx, cy, z] = zoom ? cameraAt(r.camera, at) : [0.5, 0.5, 1];
    const left = Math.min(Math.max(cx - 0.5 / z, 0), 1 - 1 / z), top = Math.min(Math.max(cy - 0.5 / z, 0), 1 - 1 / z);
    video.style.transform = z > 1.001 ? `scale(${z}) translate(${-left * 100}%, ${-top * 100}%)` : "";
  }
  if (!overlay) return;
  const real = toReal(r, at), speed = Tracks.timemap(r.clock).speed(at);
  const [clockPill, statePill, speedPill] = ["clock", "state", "speed"].map(name => overlay.querySelector(".top ." + name));
  clockPill.textContent = clock(Math.max(0, real));
  const visit = Machine.at(r, real);
  statePill.hidden = !visit;
  if (visit) {
    statePill.textContent = visit.name;
    statePill.className = `pill state ${VISITS[visitVerdict(visit)][1]}`;
  }
  speedPill.textContent = `${speed >= 2 ? Math.round(speed) : speed.toFixed(1)}x speed`;
  speedPill.style.opacity = Math.min(1, Math.max(0, (speed - 1.3) / 1.5));
  const steps = r.events.filter(e => e.kind === "step" && e.t <= real);
  const caption = overlay.querySelector(".caption");
  caption.style.opacity = steps.length ? ease((real - steps[steps.length - 1].t) / 0.3) : 0;
  if (steps.length) caption.replaceChildren($("b", { text: String(steps.length) }), steps[steps.length - 1].text);
  const recent = r.events.filter(e => e.chip && real - e.t >= 0 && real - e.t < 1.8 + (e.dur || 0));
  const now = overlay.querySelector(".now"), last = recent[recent.length - 1];
  now.style.opacity = last ? ease((real - last.t) / 0.15) * (1 - ease((real - last.t - 1.5 - (last.dur || 0)) / 0.3)) : 0;
  if (last) {
    now.textContent = chipText(last, r);
    now.className = "pill now" + (["check", "wait"].includes(last.kind) ? (last.ok ? " ok" : " bad") : "");
  }
}

function row(r, e, seek) {
  const budget = Verdict.isBudget(e), failed = e.ok === false && ["check", "wait"].includes(e.kind);
  const text = (budget ? Verdict.budgetOf(r, e) : e.text) + (e.reported ? " (reported)" : "");
  const status = e.kind === "check" ? chip(...budgetChip(e)) : null;
  const detail = budget ? null : e.kind === "wait" && e.detail ? Verdict.sentence(e.detail) : e.detail;
  const body = $("div", { class: "row", tabindex: "0", role: "button", "aria-label": `Jump to ${clock(e.t)}: ${text}` },
    $("span", { class: "t", text: clock(e.t) }),
    $("span", { class: "text" },
      ["step", "check", "note"].includes(e.kind) || e.text.startsWith(e.kind) ? null : $("span", { class: "kind", text: e.kind + " " }),
      document.createTextNode(text), detail ? $("span", { class: "detail", text: detail }) : null), status);
  const li = $("li", { class: e.kind + (failed ? " bad" : "") }, body);
  const go = () => seek(toVideo(r, e.t) - 0.4);
  body.addEventListener("click", go);
  body.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); go(); } });
  return li;
}

// The run's flow, top to bottom: a node for each state the run visited, with its time and checks, and under it the steps
// of that visit. A run with no states is one list of steps. The node and step at the video's time are lit, and the
// column follows them except for 4 s after the person scrolls it.
// Every run's states as one graph. The run on show is drawn strong: its path, a verdict on each node it visited, and
// how long each step took. The node the video is in lights up, and the page shows the details of a state under the drawing.
function machineView(r, seek) {
  const NS = "http://www.w3.org/2000/svg";
  const svg = (tag, attrs = {}, ...kids) => {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) if (k.startsWith("on")) el.addEventListener(k.slice(2), v); else el.setAttribute(k, v);
    for (const kid of kids) if (kid) el.append(kid);
    return el;
  };
  const graph = Machine.build(RUNS), current = RUNS.indexOf(r), many = RUNS.length > 1, states = r.states || [];
  const measure = document.createElement("canvas").getContext("2d");
  measure.font = "600 14px 'IBM Plex Sans', system-ui, sans-serif";
  const name = id => id.length > 32 ? id.slice(0, 31) + "…" : id;
  const size = id => id === Machine.START ? [measure.measureText(id).width + 24, 24] : [Math.max(64, measure.measureText(name(id)).width + 28), 40];
  const box = Machine.layout(graph, size, { x: 28, y: 64, lane: 16 });
  const pad = 8;
  const marker = (id, css) => svg("marker", { id, viewBox: "0 0 10 10", refX: "9", refY: "5", markerWidth: "8", markerHeight: "8", orient: "auto-start-reverse" },
    svg("path", { d: "M0,0 L10,5 L0,10 z", class: css }));
  const drawing = svg("svg", { role: "group", "aria-label": "State machine of the runs" },
    svg("defs", {}, marker("arrow", "head"), marker("arrow-on", "head on")));
  const start = (run, visit) => visit ? RUNS[run].states[visit - 1].t : 0;
  const small = document.createElement("canvas").getContext("2d");
  small.font = "12px 'IBM Plex Mono', ui-monospace, monospace";
  let left = 0, right = box.width;
  for (const e of box.edges) {
    const mine = e.takes.filter(x => x.run === current);
    const steps = mine.map(x => r.events.find(ev => ev.kind === "step" && ev.t >= start(current, x.visit) && ev.t < states[x.visit].t));
    const took = mine.map(x => states[x.visit].t - start(current, x.visit));
    const label = mine.length ? `${Tracks.format(took[0], "s")}${mine.length > 1 ? ` ×${mine.length}` : ""}` : "";
    const runs = [...new Set(e.takes.map(x => x.run))];
    const g = svg("g", { class: "edge" + (mine.length ? " on" : "") + (e.back ? " back" : ""),
      onclick: () => { if (mine.length) seek(toVideo(r, start(current, mine[0].visit)) - 0.2); } },
      svg("title", {}, `${e.from} to ${e.to}${many ? ` (${runs.map(i => RUNS[i].title).join(", ")})` : ""}${steps[0] ? ": " + steps[0].text : ""}`),
      svg("path", { d: e.d, class: "hit" }), svg("path", { d: e.d, class: "line", "marker-end": mine.length ? "url(#arrow-on)" : "url(#arrow)" }));
    if (label && e.label) {
      const [x, y, anchor, slope] = e.label, width = small.measureText(label).width, gap = 8 + slope * 7, at = anchor === "end" ? x - gap : x + gap;
      g.append(svg("text", { x: at, y: y + 4, "text-anchor": anchor, class: "label" }, label));
      left = Math.min(left, anchor === "end" ? at - width : at);
      right = Math.max(right, anchor === "end" ? at : at + width);
    }
    drawing.append(g);
  }
  const nodes = new Map(), halos = new Map();
  let pinned = pickState, following = null;
  pickState = null;
  // A state this run never visits opens the run that does (the failing one first, else the newest) at that state.
  const elsewhere = id => {
    const has = RUNS.map((x, i) => [i, Machine.verdict(x.states || [], id)]).filter(([i, v]) => v && i !== current);
    return (has.find(([, v]) => v === "bad") || has[has.length - 1] || [])[0];
  };
  const open = (i, id) => {
    pickState = id;
    location.hash = `run-${i + 1}&t=${Math.max(0, RUNS[i].states.find(v => v.name === id).t - 0.2).toFixed(1)}`;
  };
  const failing = states.find(v => v.ok === false);
  const shown = () => pinned || (failing ? failing.name : following);
  const sum = id => {
    const visits = states.filter(v => v.name === id), checks = r.events.filter(e => e.kind === "check" && !e.budget && visits.some(v => e.t >= v.t && e.t < v.end));
    return `${checks.filter(e => e.ok).length} of ${Verdict.plural(checks.length, "check")}`;
  };
  for (const n of box.nodes) {
    const here = Machine.verdict(states, n.id), first = n.id === Machine.START;
    const halo = svg("rect", { class: "halo", x: n.x - 4, y: n.y - 4, width: n.w + 8, height: n.h + 8, rx: 10 });
    const g = svg("g", { class: `node ${first ? "start" : here ? VISITS[here][1] : "away"}`, tabindex: first ? "-1" : "0", role: first ? "presentation" : "button",
      transform: `translate(${n.x},${n.y})` },
      svg("rect", { width: n.w, height: n.h, rx: 6 }),
      svg("text", { x: n.w / 2, y: n.h / 2 + 4.5, class: "name" }, first ? n.id : name(n.id)));
    if (!first) g.setAttribute("aria-label", `${n.id}, ${here ? `${{ ok: "passed", bad: "failed", unchecked: "not checked" }[here]}, ${sum(n.id)}` : `opens ${RUNS[elsewhere(n.id)].title}`}`);
    if (!first) {
      const pick = () => {
        if (!here) return open(elsewhere(n.id), n.id);
        pinned = pinned === n.id ? null : n.id;
        details();
        const v = states.find(v => v.name === n.id);
        if (pinned && v) seek(toVideo(r, v.t) - 0.2);
      };
      g.addEventListener("click", pick);
      g.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); pick(); } });
    }
    drawing.append(halo, g);
    nodes.set(n.id, g);
    halos.set(n.id, halo);
  }
  drawing.setAttribute("viewBox", `${left - pad} ${-pad} ${right - left + 2 * pad} ${box.height + 2 * pad}`);
  drawing.setAttribute("width", right - left + 2 * pad);
  const info = $("div", { class: "visit" });
  let detailed = null;
  const details = () => {
    const id = shown();
    detailed = id;
    nodes.forEach((g, key) => g.classList.toggle("picked", key === pinned));
    info.replaceChildren();
    if (!id || !nodes.has(id)) return;
    const here = Machine.verdict(states, id);
    info.append($("h2", {}, $("span", { text: id }), chip(...VISITS[here])));
    const visits = states.filter(v => v.name === id);
    const checks = r.events.filter(e => ["wait", "check"].includes(e.kind) && visits.some(v => e.t >= v.t && e.t < v.end));
    if (checks.length) { const ol = $("ol"); checks.forEach(e => ol.append(row(r, e, seek))); info.append(ol); }
    if (r.error && visits.includes(states[states.length - 1])) info.append($("p", { class: "stopped" }, chip("Stopped", "bad"), document.createTextNode(" " + r.error)));
    if (many) {
      const others = $("div", { class: "choices" });
      RUNS.forEach((x, i) => {
        const v = Machine.verdict(x.states, id);
        if (v && i !== current) others.append($("button", { type: "button", class: "btn small", onclick: () => open(i, id) },
          $("span", { text: x.title }), chip(...VISITS[v])));
      });
      if (others.children.length) info.append($("p", { class: "others", text: "In other runs:" }), others);
    }
  };
  details();
  const element = $("div", { class: "machine body" }, $("div", { class: "graph" }, drawing), info);
  const now = real => {
    const v = Machine.at(r, real);
    nodes.forEach((g, id) => { const on = !!v && v.name === id; g.classList.toggle("now", on); halos.get(id).classList.toggle("on", on); });
    following = v ? v.name : states.length ? states[0].name : null;
    if (shown() !== detailed) details();
  };
  const unpin = () => {
    if (!pinned) return false;
    pinned = null;
    details();
    return true;
  };
  return { element, now, unpin };
}

function flowView(r, seek) {
  const list = Machine.sections(r), body = $("div", { class: "body" }), items = $("ol", { class: "list flow-list" });
  const nodes = [], steps = [];
  list.forEach((s, i) => {
    const tone = VISITS[visitVerdict(s)][1], item = $("li", { class: `visit ${tone}` });
    if (s.visit) {
      const node = $("button", { type: "button", class: "visit-node", title: `${s.name}: ${VISITS[visitVerdict(s)][0]}`,
        onclick: () => seek(toVideo(r, s.t) - 0.2) },
        $("span", { class: "name", text: s.name }), $("span", { class: "t", text: clock(s.t) }),
        $("span", { class: "checks", text: Verdict.words(Verdict.tally(s.events)).join(" \u00b7 ") }), s.total || s.ok === false ? chip(...VISITS[tone]) : null);
      nodes.push(node);
      item.append(node);
    } else nodes.push(null);
    const ol = $("ol", { class: "steps" }), mine = [];
    let group = null, summary = null;
    for (const e of s.events) {
      if (e.row === "key") { const li = row(r, e, seek); ol.append(li); mine.push(li); group = null; continue; }
      if (!group) {
        group = $("ol"); summary = $("summary", {}, icon("chevron"), $("span"));
        ol.append($("li", { class: "more" }, $("details", {}, summary, group)));
      }
      const li = row(r, e, seek);
      group.append(li); mine.push(li);
      summary.lastChild.textContent = Verdict.plural(group.children.length, "action");
    }
    item.append(ol);
    items.append(item);
    steps.push(mine);
  });
  const lit = list.length === 1 && !list[0].events.length ? $("p", { class: "placeholder", text: "No steps were recorded." }) : null;
  body.append(lit || items);
  let touched = -Infinity, last = "";
  for (const name of ["wheel", "touchstart", "pointerdown", "keydown"]) body.addEventListener(name, () => { touched = Date.now(); }, { passive: true });
  const reveal = (el, pad) => {
    const box = body.getBoundingClientRect(), at = el.getBoundingClientRect();
    if (at.top < box.top + pad || at.bottom > box.bottom - 8) body.scrollTo({ top: body.scrollTop + at.top - box.top - body.clientHeight / 3, behavior: calm.matches ? "auto" : "smooth" });
  };
  const now = real => {
    const { section, event } = Machine.now(list, real), key = `${section}:${event}`;
    if (key === last) return;
    last = key;
    const li = event < 0 ? null : steps[section][event], folded = li && li.closest("details:not([open])");
    const mark = folded ? folded.parentElement : li;
    items.querySelectorAll(".now").forEach(el => el.classList.remove("now"));
    if (nodes[section]) nodes[section].classList.add("now");
    if (mark) mark.classList.add("now");
    if (Date.now() - touched < 4000) return;
    const node = nodes[section];
    if (mark) reveal(mark, node ? node.offsetHeight + 4 : 0); else if (node) reveal(node, 0);
  };
  return { element: body, now };
}

function flowPanel(r, seek) {
  const steps = flowView(r, seek), diagram = MACHINE ? machineView(r, seek) : null;
  const panes = { flow: diagram && diagram.element, steps: steps.element };
  let mode = diagram ? "flow" : "steps";
  const buttons = Object.keys(panes).filter(k => panes[k]).map(k => $("button", { type: "button", "aria-pressed": String(k === mode), text: k === "flow" ? "Flow" : "Steps",
    onclick: () => { mode = k; show(); } }));
  const show = () => {
    for (const k in panes) if (panes[k]) panes[k].hidden = k !== mode;
    buttons.forEach(b => b.setAttribute("aria-pressed", String(b.textContent.toLowerCase() === mode)));
  };
  show();
  const head = diagram ? $("div", { class: "head" }, $("div", { class: "seg", role: "group", "aria-label": "Show" }, ...buttons)) : $("h2", { text: "Steps" });
  return { element: $("aside", { class: "panel flow", "aria-label": "User flow" }, head, diagram && diagram.element, steps.element),
    now: real => { steps.now(real); if (diagram) diagram.now(real); },
    unpin: () => !!diagram && diagram.unpin() };
}

function reviewControl(r) {
  const panel = $("div", { class: "review", id: "review", hidden: "" });
  const choices = $("div", { class: "seg", role: "group", "aria-label": "Review" });
  for (const [value, label, css] of [["approve", "Approve", "ok"], ["needs-work", "Needs work", "bad"]]) {
    choices.append($("button", { type: "button", class: css, "data-v": value, "aria-pressed": "false", text: label, onclick: () => setReview(r, value) }));
  }
  panel.append(choices, $("div", { class: "who", role: "status", text: "No review yet." }));
  return panel;
}

let unwatch = null;
function watchReview(r) {
  if (unwatch) { unwatch(); unwatch = null; }
  const panel = document.getElementById("review");
  if (!caps.db || !panel) return;
  panel.hidden = false;
  const who = panel.querySelector(".who");
  const timer = setTimeout(() => { who.textContent = "Reviews are not loading here."; }, 10000);
  unwatch = caps.db.doc(`reviews/${r.id}`).onSnapshot(async snap => {
    clearTimeout(timer);
    const data = snap.exists ? snap.data() : null, set = data && data.verdict ? data : null;
    panel.querySelectorAll("[data-v]").forEach(b => b.setAttribute("aria-pressed", String(!!set && b.dataset.v === set.verdict)));
    if (!set) { who.textContent = "No review yet."; return; }
    let name = "Someone";
    if (caps.user && set.by) { const ps = await caps.user.profiles([set.by]); name = (ps[set.by] && ps[set.by].name) || "Someone"; }
    who.textContent = `${set.verdict === "approve" ? "Approved" : "Needs work"} by ${name}, ${new Date(set.at).toLocaleString()}`;
  }, () => { clearTimeout(timer); who.textContent = "Reviews are not available here."; });
}

async function setReview(r, verdict) {
  if (!caps.db) return;
  const who = document.querySelector("#review .who");
  const chosen = document.querySelector(`#review [data-v="${verdict}"]`).getAttribute("aria-pressed") === "true";
  try {
    const by = caps.user ? await caps.user.id() : null;
    await caps.db.doc(`reviews/${r.id}`).set({ verdict: chosen ? null : verdict, run: run + 1, title: r.title, by, at: Date.now() });
  } catch (err) { who.textContent = "Only people who can edit this page can review it."; }
}

function askPanel(r, video) {
  const panel = $("section", { class: "section ask", id: "ask" });
  panel.hidden = !caps.sample;
  const box = $("textarea", { "aria-label": "Ask about this moment", rows: "1", placeholder: "Why did the check fail?" });
  const answer = $("div", { class: "answer" });
  let controller = null;
  const ask = async () => {
    const question = box.value.trim();
    if (!question || !caps.sample) return;
    if (controller) controller.abort();
    controller = new AbortController();
    answer.textContent = "Thinking...";
    const at = video.currentTime;
    const log = r.events.filter(e => e.kind !== "move").map(e => `${clock(e.t)} (video ${toVideo(r, e.t).toFixed(1)} s) ${e.kind}: ${e.text}${e.kind === "check" || e.kind === "wait" ? (e.ok ? " [pass]" : " [FAIL]") : ""}${e.detail ? " - " + e.detail : ""}`).join("\n");
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
    $("div", { class: "body" }, $("div", { class: "ask-row" }, box, $("button", { type: "button", class: "btn", text: "Ask", onclick: ask })), answer));
  return panel;
}

window.addEventListener("hashchange", () => { fromHash(); render(); });
const fonts = document.fonts ? Promise.race([Promise.all([document.fonts.load("600 14px 'IBM Plex Sans'"), document.fonts.load("12px 'IBM Plex Mono'")]), new Promise(done => setTimeout(done, 1500))]).catch(() => {}) : Promise.resolve();
(async () => {
  await fonts;
  render();
  const use = name => (window.claude && window.claude.use ? window.claude.use(name) : Promise.resolve(null)).catch(() => null);
  const [db, user, sample] = await Promise.all([use("db"), use("user"), use("sample")]);
  Object.assign(caps, { db, user, sample });
  if (db || user || sample) render();
})();
