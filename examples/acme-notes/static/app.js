const $ = (id) => document.getElementById(id);
const show = (notes) => { $("list").innerHTML = notes.map((n) => `<li><b>${n.title}</b>: ${n.body}</li>`).join(""); };
const get = (url) => fetch(url).then((r) => r.json());

$("who").textContent = "Signed in as " + (localStorage.email || "guest");
get("/api/notes").then(show);
get("/api/tags").catch(() => {});

$("q").oninput = () => get("/api/search?q=" + encodeURIComponent($("q").value)).then(show);

$("save").onclick = async () => {
  await fetch("/api/notes", { method: "POST", body: JSON.stringify({ title: $("title").value, body: $("body").value }) });
  $("status").textContent = "Note saved";
  get("/api/notes").then(show);
};
