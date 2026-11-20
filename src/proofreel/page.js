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
const VERDICTS = { works: ["Works", "ok"], problem: ["Problem", "bad"], shown: ["Shown", "info"] };
// The run's clock: [real, video] points joined by straight lines. along() maps one column to the other.
function along(knots, x, y, value) {
  if (knots.length < 2) return value;
  let i = 1;
  while (i < knots.length - 1 && knots[i][x] <= value) i++;
  const [a, b] = [knots[i - 1], knots[i]];
  return b[x] > a[x] ? a[y] + (b[y] - a[y]) * (value - a[x]) / (b[x] - a[x]) : a[y];
}
const toVideo = (r, real) => along(r.clock, 0, 1, real);
const fastest = r => Math.round(Math.max(1, ...r.clock.slice(1).map((k, i) =>
  k[1] > r.clock[i][1] ? (k[0] - r.clock[i][0]) / (k[1] - r.clock[i][1]) : 1)));
const caps = {};
let run = RUNS.length - 1;
let zoom = true, view = "timeline", selected = null;
try { zoom = localStorage.getItem("proofreel-zoom") !== "0"; view = localStorage.getItem("proofreel-view") || view; } catch (err) {}
const MACHINE = RUNS.some(x => x.states && x.states.length);
const VISITS = { ok: ["Pass", "ok"], bad: ["Fail", "bad"], unchecked: ["Not checked", "info"] };
const visitAt = (r, real) => (r.states || []).find(v => v.t <= real && real < v.end) || null;
const visitVerdict = v => v.ok === false ? "bad" : v.ok ? "ok" : "unchecked";
const fromHash = () => {
  const m = /^#run-(\d+)$/.exec(location.hash);
  if (m && +m[1] >= 1 && +m[1] <= RUNS.length) run = +m[1] - 1;
};
fromHash();

function chip(label, css) { return $("span", { class: `chip ${css}`, text: label }); }
const ICONS = {
  play: "M7 5v14l11-7z", pause: "M7 5h4v14H7zM13 5h4v14h-4z", full: "M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5",
  zoom: "M11 4a7 7 0 1 0 0 14a7 7 0 1 0 0-14zM20 20l-4-4M8 11h6M11 8v6",
  help: "M12 21a9 9 0 1 0 0-18a9 9 0 1 0 0 18zM9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6v.6M12 17h.01",
};
const icon = name => {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg"), p = document.createElementNS("http://www.w3.org/2000/svg", "path");
  s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("aria-hidden", "true"); s.setAttribute("class", "icon " + name);
  p.setAttribute("d", ICONS[name]); s.append(p);
  return s;
};
const VIEWS = [["timeline", "Timeline"], ["machine", "State machine"], ["stats", "Stats", true], ["network", "Network", true], ["compare", "Compare", true]];
const SOON = {
  stats: "Per-run numbers: time in each state, checks, retries, CPU and memory peaks. One table, one row per run.",
  network: "Requests on the video time axis: method, URL, status, time. Click a request to jump the video to it.",
  compare: "Two runs side by side: the same state in each, with the frame, the checks, and the time they took.",
};

function runSwitch() {
  if (RUNS.length < 2) return null;
  const nav = $("nav", { class: "seg runs", "aria-label": "Runs" });
  RUNS.forEach((x, i) => nav.append($("button", { type: "button", "aria-pressed": String(i === run),
    title: `Run ${i + 1}: ${VERDICTS[x.verdict][0]}, ${x.when}`, onclick: () => { location.hash = `run-${i + 1}`; } },
    $("span", { class: `dot ${VERDICTS[x.verdict][1]}` }), $("span", { text: `Run ${i + 1}` }), $("span", { class: "when", text: x.when.slice(5) }))));
  return nav;
}

function render() {
  const r = RUNS[run], app = document.getElementById("app");
  app.replaceChildren();
  document.title = r.title;
  app.append($("header", { class: "top" },
    $("div", { class: "title" },
      $("div", { class: "name" }, chip(...VERDICTS[r.verdict]), $("h1", { text: r.title })),
      r.about ? $("p", { class: "lede", text: r.about }) : null,
      r.error ? $("p", { class: "lede" }, chip("Stopped", "bad"), document.createTextNode(" " + r.error)) : null,
      $("div", { class: "meta" }, ...r.meta.map(m => $("span", { text: m })))),
    runSwitch()));

  const video = $("video", { playsinline: "", muted: "", preload: "metadata", poster: r.base + "poster.jpg", src: r.base + "session.mp4" });
  const overlay = r.overlay ? $("div", { class: "overlay", "aria-hidden": "true" },
    $("div", { class: "top" }, $("span", { class: "pill clock" }), $("span", { class: "pill state" }), $("span", { class: "pill speed" })),
    $("span", { class: "pill now" }), $("span", { class: "pill caption" })) : null;
  const screen = $("div", { class: "screen" }, video, overlay);
  const update = () => {
    stage(r, video, overlay);
    if (video.duration) timebar.style.setProperty("--at", (video.currentTime / video.duration * 100) + "%");
    time.textContent = `${clock(Math.max(0, toReal(r, video.currentTime)))} / ${clock(r.real)}`;
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
  const fullButton = screen.requestFullscreen ? $("button", { type: "button", class: "btn tool icon-only", title: "Full screen",
    "aria-label": "Full screen", onclick: () => screen.requestFullscreen().catch(() => {}) }, icon("full")) : null;
  const play = $("button", { type: "button", class: "btn tool icon-only play", "aria-label": "Play", onclick: () => video.paused ? video.play().catch(() => {}) : video.pause() }, icon("play"));
  const paint = () => { play.replaceChildren(icon(video.paused ? "play" : "pause")); play.setAttribute("aria-label", video.paused ? "Play" : "Pause"); };
  video.addEventListener("play", paint); video.addEventListener("pause", paint);
  video.addEventListener("click", () => play.click());
  const tick = () => { update(); if (!video.paused) requestAnimationFrame(tick); };
  video.addEventListener("play", () => requestAnimationFrame(tick));
  for (const name of ["seeked", "loadedmetadata", "timeupdate"]) video.addEventListener(name, update);
  const time = $("span", { class: "time" });
  const bar = $("div", { class: "bar", role: "slider", "aria-label": "Seek", tabindex: "0" }, $("div", { class: "track" }), $("div", { class: "done" }));
  for (const e of r.events.filter(e => ["step", "check", "wait"].includes(e.kind))) {
    const css = e.kind === "step" ? "step" : (e.ok ? "ok" : "bad");
    bar.append($("i", { class: css, "data-t": toVideo(r, e.t), title: `${clock(e.t)} ${e.text}` }));
  }
  const seek = t => { video.currentTime = Math.max(0, t); video.play().catch(() => {}); };
  bar.addEventListener("click", ev => {
    const box = bar.getBoundingClientRect();
    if (video.duration) seek((ev.clientX - box.left) / box.width * video.duration);
  });
  bar.addEventListener("keydown", ev => {
    const step = { ArrowLeft: -1, ArrowRight: 1, PageDown: -5, PageUp: 5 }[ev.key];
    if (step && video.duration) { ev.preventDefault(); video.currentTime = Math.min(video.duration, Math.max(0, video.currentTime + step)); }
  });
  const help = $("details", { class: "help" }, $("summary", { class: "btn tool icon-only", "aria-label": "About this video", title: "About this video" }, icon("help")),
    $("div", { class: "pop", text: `Recorded from the screen as the agent drove it. Blue rings are clicks. The video is sped up to about 30 s; a badge shows the speed (up to ${fastest(r)}x with no change on the screen). The clock is real time. Click a row or a mark to jump to it.` }));
  const lanes = $("div", { class: "lanes" });
  const statesLane = $("div", { class: "lane states", "aria-label": "States" });
  for (const v of r.states || []) statesLane.append($("button", { type: "button", class: `seg-state ${VISITS[visitVerdict(v)][1]}`,
    "data-t": toVideo(r, v.t), "data-end": toVideo(r, v.end), title: `${v.name}: ${VISITS[visitVerdict(v)][0]}`,
    onclick: () => seek(toVideo(r, v.t) - 0.2) }, $("span", { text: v.name })));
  if (r.states && r.states.length) lanes.append($("span", { class: "lane-label", text: "States" }), statesLane, $("span"));
  const timebar = $("div", { class: "timebar" },
    $("div", { class: "lead" }, play, time), bar, $("div", { class: "tools" }, zoomButton, fullButton, help), lanes);
  const place = () => {
    if (!video.duration) return;
    bar.querySelectorAll("i").forEach(m => m.style.left = (m.dataset.t / video.duration * 100) + "%");
    statesLane.querySelectorAll(".seg-state").forEach(s => {
      s.style.left = (s.dataset.t / video.duration * 100) + "%";
      s.style.width = (Math.max(0, s.dataset.end - s.dataset.t) / video.duration * 100) + "%";
    });
    if (video.videoWidth) document.documentElement.style.setProperty("--ratio", video.videoWidth / video.videoHeight);
  };
  video.addEventListener("loadedmetadata", place);
  const stagePanel = $("section", { class: "panel stage", "aria-label": "Recording" }, $("div", { class: "media" }, screen), timebar);

  const list = $("ol", { class: "list timeline" });
  let actions = null, summary = null, visit = 0;
  for (const e of r.events) {
    if (e.row === "key") { list.append(row(r, e, seek, e.kind === "state" ? r.states[visit++] : null)); actions = null; continue; }
    if (!actions) {
      actions = $("ol");
      summary = $("summary");
      list.append($("li", { class: "more" }, $("details", {}, summary, actions)));
    }
    actions.append(row(r, e, seek));
    const n = actions.children.length;
    summary.textContent = `${n} action${n === 1 ? "" : "s"}`;
  }
  const machine = MACHINE ? machineView(r, seek) : null;
  const panes = { timeline: list, machine: machine && machine.element };
  for (const [name, , soon] of VIEWS) if (soon) panes[name] = $("div", { class: "soon-pane" }, $("p", { class: "placeholder", text: SOON[name] }));
  const views = VIEWS.filter(([name]) => panes[name]);
  if (!panes[view]) view = "timeline";
  const tabs = $("div", { class: "tabs", role: "tablist", "aria-label": "View" });
  const show = () => {
    for (const [name, pane] of Object.entries(panes)) if (pane) pane.hidden = name !== view;
    tabs.querySelectorAll("[role=tab]").forEach(b => b.setAttribute("aria-selected", String(b.dataset.view === view)));
  };
  for (const [name, label, soon] of views) tabs.append($("button", { type: "button", role: "tab", "data-view": name, class: soon ? "soon" : "",
    onclick: () => { view = name; try { localStorage.setItem("proofreel-view", view); } catch (err) {} show(); } },
    document.createTextNode(label), soon ? $("span", { class: "badge", text: "soon" }) : null));
  show();
  const body = $("div", { class: "body scroll" }, ...Object.values(panes).filter(Boolean));
  const viewsPanel = $("section", { class: "panel views" }, $("div", { class: "head" }, tabs), body);
  const dock = $("aside", { class: "panel dock", "aria-label": "Review" }, reviewPanel(r), askPanel(r, video));
  app.append($("div", { class: "grid" }, stagePanel, viewsPanel, dock));
  const grid = app.lastChild;
  const fit = () => app.style.setProperty("--fit-h", Math.max(160, grid.clientHeight - timebar.offsetHeight - 2) + "px");
  if (window.ResizeObserver) { const watch = new ResizeObserver(fit); watch.observe(grid); watch.observe(timebar); }
  video.addEventListener("timeupdate", () => {
    if (machine) machine.now(toReal(r, video.currentTime));
    let current = null;
    const rows = list.querySelectorAll("li[data-t]");
    for (const li of rows) if (+li.dataset.t <= video.currentTime + 0.05) current = li;
    const folded = current && current.closest("details:not([open])");
    const mark = folded ? folded.parentElement : current;
    for (const li of list.querySelectorAll("li")) li.classList.toggle("now", li === mark);
  });
  update();
  place();
  watchReview(r);
}

const ease = x => { x = Math.min(Math.max(x, 0), 1); return x * x * (3 - 2 * x); };
const toReal = (r, video) => along(r.clock, 1, 0, video);
function speedAt(r, video) {
  const k = r.clock;
  let i = 1;
  while (i < k.length - 1 && k[i][1] <= video) i++;
  return k.length > 1 && k[i][1] > k[i - 1][1] ? (k[i][0] - k[i - 1][0]) / (k[i][1] - k[i - 1][1]) : 1;
}
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
const chipText = e => e.kind === "check" ? (e.ok ? "Pass: " : "Fail: ") + e.text : e.kind === "key" ? keysLabel(e.text) : e.text;

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
  const real = toReal(r, at), speed = speedAt(r, at);
  const [clockPill, statePill, speedPill] = ["clock", "state", "speed"].map(name => overlay.querySelector(".top ." + name));
  clockPill.textContent = clock(Math.max(0, real));
  const visit = visitAt(r, real);
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
    now.textContent = chipText(last);
    now.className = "pill now" + (["check", "wait"].includes(last.kind) ? (last.ok ? " ok" : " bad") : "");
  }
}

function row(r, e, seek, visit) {
  const status = e.kind === "check" ? chip(e.ok ? "Pass" : "Fail", e.ok ? "ok" : "bad")
    : e.kind === "wait" ? chip(e.ok ? "Seen" : "Not seen", e.ok ? "ok" : "bad")
    : visit ? chip(...VISITS[visitVerdict(visit)]) : null;
  const text = $("span", { class: "text" },
    ["state", "step", "check", "note"].includes(e.kind) || e.text.startsWith(e.kind) ? null : $("span", { class: "kind", text: e.kind + " " }),
    document.createTextNode(e.text + " "), status, e.detail ? $("span", { class: "detail", text: e.detail }) : null);
  const body = $("div", { class: "row", tabindex: "0", role: "button", "aria-label": `Jump to ${clock(e.t)}: ${e.text}` },
    $("span", { class: "t", text: clock(e.t) }), text, e.shot ? $("img", { src: r.base + e.shot, alt: "", loading: "lazy" }) : $("span"));
  const li = $("li", { class: e.kind + (visit ? " " + VISITS[visitVerdict(visit)][1] : ""), "data-t": toVideo(r, e.t) }, body);
  const go = () => seek(toVideo(r, e.t) - 0.4);
  body.addEventListener("click", go);
  body.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); go(); } });
  return li;
}

// Every run's states as one graph. The run on show is drawn strong: its path, a verdict on each node it visited, and
// how long each step took. A dot under a node is its verdict in each run. The node the video is in lights up.
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
  measure.font = "600 13px Inter, system-ui, sans-serif";
  const name = id => id.length > 32 ? id.slice(0, 31) + "…" : id;
  const size = id => id === Machine.START ? [measure.measureText(id).width + 26, 26]
    : [Math.max(64, measure.measureText(name(id)).width + 30), many ? 46 : 34];
  const box = Machine.layout(graph, size);
  const pad = 8;
  const drawing = svg("svg", { role: "img", "aria-label": "State machine of the runs" },
    svg("defs", {}, svg("marker", { id: "arrow", viewBox: "0 0 10 10", refX: "9", refY: "5", markerWidth: "7",
      markerHeight: "7", orient: "auto-start-reverse" }, svg("path", { d: "M0,0 L10,5 L0,10 z", class: "head" }))));
  const start = (run, visit) => visit ? RUNS[run].states[visit - 1].t : 0;
  const small = document.createElement("canvas").getContext("2d");
  small.font = "11px Inter, system-ui, sans-serif";
  let left = 0, right = box.width;
  for (const e of box.edges) {
    const mine = e.takes.filter(x => x.run === current);
    const steps = mine.map(x => r.events.find(ev => ev.kind === "step" && ev.t >= start(current, x.visit) && ev.t < states[x.visit].t));
    const took = mine.map(x => states[x.visit].t - start(current, x.visit));
    const label = mine.length ? `${took[0].toFixed(1)} s${mine.length > 1 ? ` ×${mine.length}` : ""}${steps[0] ? " · " + steps[0].text : ""}` : "";
    const runs = [...new Set(e.takes.map(x => x.run + 1))];
    const g = svg("g", { class: "edge" + (mine.length ? " on" : "") + (e.back ? " back" : ""),
      onclick: () => { if (mine.length) seek(toVideo(r, start(current, mine[0].visit)) - 0.2); } },
      svg("title", {}, `${e.from} → ${e.to}${many ? ` (run ${runs.join(", ")})` : ""}${steps[0] ? ": " + steps[0].text : ""}`),
      svg("path", { d: e.d, class: "hit" }), svg("path", { d: e.d, class: "line", "marker-end": "url(#arrow)" }));
    if (label && e.label) {
      const text = label.length > 34 ? label.slice(0, 33) + "…" : label;
      const [x, y, anchor] = e.label, width = small.measureText(text).width, at = anchor === "end" ? x - 7 : x + 7;
      g.append(svg("text", { x: at, y: y + 4, "text-anchor": anchor, class: "label" }, text));
      left = Math.min(left, anchor === "end" ? at - width : at);
      right = Math.max(right, anchor === "end" ? at : at + width);
    }
    drawing.append(g);
  }
  const nodes = new Map();
  let playing = -1;
  for (const n of box.nodes) {
    const here = Machine.verdict(states, n.id), first = n.id === Machine.START;
    const g = svg("g", { class: `node ${first ? "start" : here ? VISITS[here][1] : "away"}`, tabindex: "0", role: "button",
      transform: `translate(${n.x},${n.y})`, "aria-label": `${n.id}${here ? ": " + VISITS[here][0] : ""}` },
      svg("rect", { width: n.w, height: n.h, rx: first ? n.h / 2 : 8 }),
      svg("text", { x: n.w / 2, y: many && !first ? 19 : n.h / 2 + 4.5, class: "name" }, first ? n.id : name(n.id)));
    if (many && !first) RUNS.forEach((x, i) => {
      const v = Machine.verdict(x.states, n.id);
      g.append(svg("circle", { cx: n.w / 2 + (i - (RUNS.length - 1) / 2) * 11, cy: 33, r: i === current ? 4 : 3.2,
        class: `dot ${v ? VISITS[v][1] : "away"}${i === current ? " mine" : ""}` }, svg("title", {}, `Run ${i + 1}: ${v ? VISITS[v][0] : "not visited"}`)));
    });
    // A state the run visits more than once: each click goes to its next visit.
    const pick = () => {
      selected = n.id;
      details();
      const visits = states.filter(v => v.name === n.id);
      const v = visits.find(v => v.t > playing + 0.3) || visits[0];
      if (v) seek(toVideo(r, v.t) - 0.2);
    };
    g.addEventListener("click", pick);
    g.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); pick(); } });
    drawing.append(g);
    nodes.set(n.id, g);
  }
  drawing.setAttribute("viewBox", `${left - pad} ${-pad} ${right - left + 2 * pad} ${box.height + 2 * pad}`);
  drawing.setAttribute("width", right - left + 2 * pad);
  const info = $("div", { class: "visit" });
  const details = () => {
    nodes.forEach((g, id) => g.classList.toggle("picked", id === selected));
    info.replaceChildren();
    if (!selected || selected === Machine.START || !nodes.has(selected)) {
      info.append($("p", { class: "hint", text: "Click a state to see its checks, or a step to jump to it." }));
      return;
    }
    const here = Machine.verdict(states, selected);
    info.append($("h3", {}, document.createTextNode(selected + " "), here ? chip(...VISITS[here]) : chip("Not in this run", "info")));
    const visits = states.filter(v => v.name === selected);
    const checks = r.events.filter(e => ["wait", "check"].includes(e.kind) && visits.some(v => e.t >= v.t && e.t < v.end));
    if (visits.length && !checks.length) info.append($("p", { class: "hint", text: "No wait or check ran in this state." }));
    if (checks.length) { const ol = $("ol"); checks.forEach(e => ol.append(row(r, e, seek))); info.append(ol); }
    if (r.error && visits.includes(states[states.length - 1])) info.append($("p", { class: "hint" }, chip("Stopped", "bad"), document.createTextNode(" " + r.error)));
    if (many) {
      const others = $("div", { class: "choices" });
      RUNS.forEach((x, i) => {
        const v = Machine.verdict(x.states, selected);
        if (v && i !== current) others.append($("button", { type: "button", class: "btn small", onclick: () => { location.hash = `run-${i + 1}`; } },
          $("span", { text: `Run ${i + 1}` }), chip(...VISITS[v])));
      });
      if (others.children.length) info.append($("p", { class: "hint", text: "In other runs:" }), others);
    }
  };
  details();
  const element = $("div", { class: "machine" }, $("div", { class: "graph" }, drawing), info);
  const now = real => {
    playing = real;
    const v = visitAt(r, real);
    nodes.forEach((g, id) => g.classList.toggle("now", !!v && v.name === id));
  };
  return { element, now };
}

function reviewPanel(r) {
  const panel = $("section", { class: "section review", id: "review", hidden: "" });
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
  const panel = $("section", { class: "section ask", id: "ask", hidden: "" });
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
render();
(async () => {
  const use = name => (window.claude && window.claude.use ? window.claude.use(name) : Promise.resolve(null)).catch(() => null);
  const [db, user, sample] = await Promise.all([use("db"), use("user"), use("sample")]);
  Object.assign(caps, { db, user, sample });
  if (db || user || sample) render();
  if (sample) document.getElementById("ask").hidden = false;
})();
