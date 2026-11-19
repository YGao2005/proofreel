const test = require("node:test");
const assert = require("node:assert");
const Machine = require("../../src/proofreel/machine.js");

const run = (...path) => ({ states: path.map((name, i) => ({ name, t: i, end: i + 1, ok: true })) });
const size = () => [80, 30];

test("runs merge into one node per state and one edge per pair", () => {
  const g = Machine.build([run("Home", "Sign in", "Welcome"), run("Home", "Sign in", "Wrong password"), { states: [] }]);
  assert.deepStrictEqual(g.nodes.map(n => n.id), ["Start", "Home", "Sign in", "Welcome", "Wrong password"]);
  assert.deepStrictEqual(g.edges.map(e => [e.from, e.to, e.takes.length]),
    [["Start", "Home", 2], ["Home", "Sign in", 2], ["Sign in", "Welcome", 1], ["Sign in", "Wrong password", 1]]);
});

test("a branch puts both states on one layer, side by side", () => {
  const box = Machine.layout(Machine.build([run("A", "B"), run("A", "C")]), size);
  const at = Object.fromEntries(box.nodes.map(n => [n.id, n]));
  assert.ok(at.Start.y < at.A.y && at.A.y < at.B.y);
  assert.strictEqual(at.B.y, at.C.y);
  assert.ok(Math.abs(at.B.x - at.C.x) >= 80);
});

test("a loop goes back in a side lane and does not change the layers", () => {
  const box = Machine.layout(Machine.build([run("Sign in", "Wrong password", "Sign in", "Welcome")]), size);
  const at = Object.fromEntries(box.nodes.map(n => [n.id, n]));
  assert.ok(at["Sign in"].y < at["Wrong password"].y && at["Wrong password"].y === at.Welcome.y);
  const back = box.edges.filter(e => e.back);
  assert.deepStrictEqual(back.map(e => [e.from, e.to]), [["Wrong password", "Sign in"]]);
  assert.match(back[0].d, /V/);
  assert.ok(box.edges.every(e => e.from === e.to || !e.back || /V/.test(e.d)));
  for (const n of box.nodes) assert.ok(n.x >= 0 && n.x + n.w <= box.width);
});

test("a long edge passes through a point on each layer it crosses", () => {
  const box = Machine.layout(Machine.build([run("A", "B", "C"), run("A", "C")]), size);
  const long = box.edges.find(e => e.from === "A" && e.to === "C");
  assert.strictEqual((long.d.match(/ L/g) || []).length, 1);
});

test("a state visited again in place gets a small loop", () => {
  const box = Machine.layout(Machine.build([run("A", "A")]), size);
  assert.ok(box.edges.find(e => e.from === "A" && e.to === "A").back);
});

test("a node's verdict in a run: a failed visit wins, then a pass, then not checked", () => {
  const states = [{ name: "A", ok: true }, { name: "A", ok: false }, { name: "B", ok: null }, { name: "C", ok: true }, { name: "C", ok: null }];
  assert.strictEqual(Machine.verdict(states, "A"), "bad");
  assert.strictEqual(Machine.verdict(states, "B"), "unchecked");
  assert.strictEqual(Machine.verdict(states, "C"), "ok");
  assert.strictEqual(Machine.verdict(states, "D"), null);
});
