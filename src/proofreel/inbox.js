const TOKEN = document.querySelector('meta[name="inbox-token"]').content;
const NS = "http://www.w3.org/2000/svg";
const ICONS = { check: "M5 12.5l4.5 4.5L19 7.5", x: "M6.5 6.5l11 11M17.5 6.5l-11 11", back: "M15 5l-7 7 7 7", next: "M5 12h14M13 6l6 6-6 6", note: "M4 5h16v11H10l-4 4v-4H4zM12 8.5v4M10 10.5h4" };
const VERDICT = { works: ["Works", "ok"], problem: ["Problem", "bad"], shown: ["No checks", ""] };
const DECIDED = { approve: ["Approved", "ok"], approve_next: ["Approved, next mission", "ok"], needs_work: ["Needs work", "bad"], reject: ["Rejected", ""] };
const COMPOSE = {
  next: ["Next mission for this session", "Add an Import button that reads the same format.", "Approve and send", "approve_next", true],
  work: ["What needs work?", "Say what to change.", "Send", "needs_work", true],
  reject: ["Why reject it? (optional)", "The agent closes the branch.", "Reject", "reject", false],
};
const el = id => document.querySelector(id);
const queueEl = el(".queue"), mainEl = el(".main"), barEl = el(".bar"), railEl = el(".rail-items"), drawer = el(".drawer"), openBtn = el("#open-queue");

function h(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "text") node.textContent = v; else if (k.startsWith("on")) node.addEventListener(k.slice(2), v); else node.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) node.append(kid);
  return node;
}
const icon = name => {
  const svg = document.createElementNS(NS, "svg"), path = document.createElementNS(NS, "path");
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("class", "icon"); svg.setAttribute("aria-hidden", "true");
  path.setAttribute("d", ICONS[name]); svg.append(path); return svg;
};
const waited = at => {
  const m = Math.max(0, Math.floor((Date.now() / 1000 - at) / 60)), days = Math.floor(m / 1440);
  return days >= 2 ? `${days} days` : days ? "yesterday" : m < 60 ? `${m}m` : `${Math.floor(m / 60)}h ${m % 60}m`;
};
const clock = at => new Date(at * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const stamp = at => new Date(at * 1000).toDateString() === new Date().toDateString() ? clock(at) : `${new Date(at * 1000).toLocaleDateString([], { weekday: "short" })} ${clock(at)}`;
const who = i => [i.from, i.pr ? `#${i.pr}` : [i.repo, i.branch].filter(Boolean).join("/")].filter(Boolean).join(" · ");
const place = i => [i.repo && i.branch ? `${i.repo}/${i.branch}` : i.repo, i.pr ? `PR #${i.pr}` : ""].filter(Boolean).join(" · ");
const delivery = i => i.picked ? [`Picked up by ${i.from || "the agent"} at ${clock(i.picked.at)}`, "ok"] : ["Not picked up yet", "warn"];

let screen = "list", list = [], seen = "", drawn = "", view = "waiting", selected = null, mode = null;
const shown = () => view === "waiting" ? list.filter(i => !i.decision) : list.filter(i => i.decision).sort((a, b) => b.decision.at - a.decision.at);
const stateOf = i => i ? `${i.id} ${!!i.decision} ${!!i.picked}` : "";
const current = () => shown().find(i => i.id === selected);

function renderQueue() {
  document.querySelectorAll(".seg button").forEach(b => {
    b.setAttribute("aria-pressed", String(b.dataset.view === view));
    b.querySelector(".n").textContent = list.filter(i => !!i.decision === (b.dataset.view === "sent")).length;
  });
  const rows = shown();
  el("#count").textContent = view === "waiting" ? rows.length : "";
  railEl.replaceChildren(...rows.map(i => h("button", { type: "button", "aria-current": String(i.id === selected), "aria-label": i.title, title: `${i.title}\n${i.from}`,
    onclick: () => select(i.id) }, (i.from || "?")[0].toUpperCase(), h("span", { class: `dot ${i.decision ? delivery(i)[1] : (VERDICT[i.verdict] || [])[1] || ""}` }))));
  if (!rows.length) { queueEl.replaceChildren(h("p", { class: "none", text: view === "waiting" ? "Nothing waits for you." : "No decisions sent yet." })); return; }
  queueEl.replaceChildren(...rows.map(i => {
    const [label, css] = i.decision ? DECIDED[i.decision.verdict] : VERDICT[i.verdict] || [];
    const state = i.decision ? delivery(i) : null;
    return h("button", { type: "button", class: "row", "aria-current": String(i.id === selected), onclick: () => select(i.id) },
      h("span", { class: "title", text: i.title, title: i.title }), label ? h("span", { class: `chip ${css}`, text: label }) : null,
      h("span", { class: "sub" }, h("span", { class: "fold", text: who(i) }),
        h("span", { class: "when mono", text: stamp(i.decision ? i.decision.at : i.added) })),
      state ? h("span", { class: "sub" }, h("span", { class: `chip ${state[1]}`, text: state[0] })) : null);
  }));
}

function showScreen(name) { screen = name; document.querySelector(".app").dataset.screen = name; }

function select(id) {
  selected = id; mode = null; showScreen("item"); drawer.hidden = true; openBtn.setAttribute("aria-expanded", "false");
  renderItem();
}

function renderItem() {
  const i = current();
  drawn = stateOf(i);
  renderQueue();
  renderBar(i);
  mainEl.replaceChildren();
  if (!i) {
    mainEl.append(h("div", { class: "empty-pane" }, h("h1", { text: view === "waiting" ? "Nothing waits for you" : "No decisions sent yet" }),
      view === "waiting" ? h("p", {}, "An agent adds a proof with ", h("code", { text: "proofreel inbox add" }), ". It shows here.") : null));
    return;
  }
  if (!i.decision) { mainEl.append(h("iframe", { sandbox: "allow-scripts", allow: "fullscreen", src: i.url, title: `Review page: ${i.title}` })); return; }
  const [label, css] = DECIDED[i.decision.verdict], [state] = delivery(i);
  mainEl.append(h("article", { class: "sent" }, h("div", { class: "name" }, h("span", { class: `chip ${css}`, text: label }), h("h1", { text: i.title })),
    h("pre", { text: i.decision.text }), h("p", { text: `Sent at ${clock(i.decision.at)}. ${state}.` })));
}

function renderBar(i) {
  barEl.replaceChildren(h("button", { type: "button", class: "btn tool back", "aria-label": "Back to the queue", onclick: () => showScreen("list") }, icon("back"), "Queue"));
  if (!i) { barEl.append(h("div", { class: "who" }, h("b", { text: "Review inbox" }))); return; }
  const sep = wide => h("span", { class: `sep${wide ? " wide" : ""}`, text: "·" });
  barEl.append(h("div", { class: "who" }, h("span", { text: i.from || "An agent" }), i.repo ? [sep(true), h("span", { class: "mono fold wide", text: place(i) })] : null,
    !i.decision ? [sep(), h("span", { text: `waiting ${waited(i.added)}` })] : null));
  if (i.decision) return;
  const label = text => h("span", { class: "label", text });
  const press = m => { mode = mode === m ? null : m; renderBar(i); };
  barEl.append(h("div", { class: "acts" },
    h("button", { type: "button", class: "btn tool", "aria-pressed": String(mode === "reject"), "aria-label": "Reject", onclick: () => press("reject") }, icon("x"), label("Reject")),
    h("button", { type: "button", class: "btn bad", "aria-pressed": String(mode === "work"), "aria-label": "Needs work", title: "Needs work (W)", onclick: () => press("work") }, icon("note"), label("Needs work")),
    h("button", { type: "button", class: "btn", "aria-pressed": String(mode === "next"), "aria-label": "Approve and give a next mission", title: "Approve, then a next mission (Shift A)", onclick: () => press("next") }, icon("next"), label("Approve + next")),
    h("button", { type: "button", class: "btn primary", "aria-label": "Approve", title: i.on_approve ? `Then: ${i.on_approve}` : "Approve (A)", onclick: () => send(i, "approve") }, icon("check"), label("Approve"), h("kbd", { text: "A" }))));
  if (!mode) return;
  const [title, hint, button, verdict, required] = COMPOSE[mode];
  const box = h("textarea", { id: "decide-box", placeholder: hint, rows: "3" }), error = h("p", { class: "error", role: "alert" });
  const go = h("button", { type: "button", class: `btn ${mode === "reject" ? "" : "primary"}`, text: button, disabled: required });
  box.addEventListener("input", () => { go.disabled = required && !box.value.trim(); });
  go.addEventListener("click", () => send(i, verdict, box.value.trim(), error));
  box.addEventListener("keydown", ev => { if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey) && !go.disabled) go.click(); });
  barEl.append(h("div", { class: "drop", role: "dialog", "aria-label": title }, h("div", { class: "compose" }, h("label", { for: "decide-box", text: title }), box,
    mode === "next" && i.on_approve ? h("p", { class: "hint", text: `Approve first: ${i.on_approve}` }) : null, error,
    h("div", { class: "end" }, h("span", { class: "hint", text: `Goes to ${i.from || "the agent"}` }), h("button", { type: "button", class: "btn tool", text: "Cancel", onclick: () => press(mode) }), go))));
  requestAnimationFrame(() => box.focus());
}

async function send(i, verdict, text = "", error = null) {
  const answer = await fetch("/decide", { method: "POST", headers: { "Content-Type": "application/json", "X-Inbox-Token": TOKEN }, body: JSON.stringify({ id: i.id, verdict, text }) });
  if (!answer.ok) {
    const message = (await answer.json().catch(() => ({}))).error || "The decision was not sent.";
    if (error) error.textContent = message; else el("#live").textContent = message;
    return;
  }
  mode = null;
  await refresh();
  el("#live").textContent = "Decision sent.";
}

async function refresh() {
  const text = await (await fetch("/items", { cache: "no-store" })).text();
  if (text !== seen) { seen = text; list = JSON.parse(text); }
  if (!current()) selected = (shown()[0] || {}).id;
  if (stateOf(current()) !== drawn) renderItem(); else renderQueue();
}

document.querySelectorAll(".seg button").forEach(b => b.addEventListener("click", () => { view = b.dataset.view; selected = (shown()[0] || {}).id; mode = null; renderItem(); }));
showScreen("list");
openBtn.addEventListener("click", () => { drawer.hidden = !drawer.hidden; openBtn.setAttribute("aria-expanded", String(!drawer.hidden)); });
document.addEventListener("keydown", ev => {
  if (ev.target.closest("textarea, input") || ev.metaKey || ev.ctrlKey || ev.altKey) { if (ev.key === "Escape" && mode) { mode = null; renderBar(current()); } return; }
  const i = current(), key = ev.key.toLowerCase();
  if (key === "[") openBtn.click();
  else if (key === "escape") { mode = null; drawer.hidden = true; if (i) renderBar(i); }
  else if (i && !i.decision && key === "a") ev.shiftKey ? (mode = "next", renderBar(i)) : send(i, "approve");
  else if (i && !i.decision && key === "w") { mode = "work"; renderBar(i); }
});
const tick = () => refresh().catch(() => {});
tick();
setInterval(tick, 2000);
