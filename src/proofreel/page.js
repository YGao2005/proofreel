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
    text: zoom ? "Zoom on" : "Zoom off", title: "Zoom in on each action", onclick: () => {
      zoom = !zoom;
      try { localStorage.setItem("proofreel-zoom", zoom ? "1" : "0"); } catch (err) {}
      zoomButton.setAttribute("aria-pressed", String(zoom));
      zoomButton.textContent = zoom ? "Zoom on" : "Zoom off";
      const at = video.currentTime, playing = !video.paused;
      video.src = source();
      video.addEventListener("loadedmetadata", () => { video.currentTime = at; if (playing) video.play().catch(() => {}); }, { once: true });
    } }) : null;
  const done = $("div", { class: "done" });
  const bar = $("div", { class: "bar" }, $("div", { class: "track" }), done);
  const shown = r.events;
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
    if (e.row === "key") { list.append(row(r, e, seek)); actions = null; continue; }
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
