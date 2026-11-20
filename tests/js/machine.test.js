const test = require("node:test");
const assert = require("node:assert");
const Machine = require("../../src/proofreel/machine.js");

const path = (...names) => names.map((name, i) => ({ name, t: i * 10, end: i * 10 + 10, ok: true }));
const check = (t, ok = true) => ({ kind: "check", t, ok });

test("a node for each state in the order the run reached it, an edge for each transition", () => {
  const f = Machine.flow({ states: path("Home", "Sign in", "Welcome") });
  assert.deepStrictEqual(f.nodes.map(n => n.id), ["Home", "Sign in", "Welcome"]);
  assert.deepStrictEqual(f.edges.map(e => [e.from, e.to, e.next]), [["Home", "Sign in", true], ["Sign in", "Welcome", true]]);
});

test("a run that goes back to a state keeps one node and shows the edge back", () => {
  const f = Machine.flow({ states: path("Sign in", "Wrong password", "Sign in", "Welcome") });
  assert.deepStrictEqual(f.nodes.map(n => n.id), ["Sign in", "Wrong password", "Welcome"]);
  assert.deepStrictEqual(f.edges.map(e => [e.from, e.to, e.next]),
    [["Sign in", "Wrong password", true], ["Wrong password", "Sign in", false], ["Sign in", "Welcome", false]]);
  assert.strictEqual(f.nodes[0].visits.length, 2);
});

test("a repeated transition is one edge that counts its takes", () => {
  const f = Machine.flow({ states: path("A", "B", "A", "B") });
  assert.deepStrictEqual(f.edges.map(e => [e.from, e.to, e.takes]), [["A", "B", 2], ["B", "A", 1]]);
});

test("a node counts the checks that ran in its visits, as the header does, and not the waits", () => {
  const events = [check(1), check(2, false), { kind: "wait", t: 12, ok: true }, { kind: "step", t: 13 }, check(25)];
  const f = Machine.flow({ states: path("A", "B", "C"), events });
  assert.deepStrictEqual(f.nodes.map(n => [n.passed, n.total]), [[1, 2], [0, 0], [1, 1]]);
});

test("a verdict is bad when a visit failed, ok when one passed, unchecked when none was checked", () => {
  const states = [{ name: "A", t: 0, end: 1, ok: true }, { name: "B", t: 1, end: 2, ok: null }, { name: "C", t: 2, end: 3, ok: false },
    { name: "A", t: 3, end: 4, ok: false }];
  assert.deepStrictEqual(Machine.flow({ states }).nodes.map(n => n.verdict), ["bad", "unchecked", "bad"]);
  assert.strictEqual(Machine.flow({ states: path("A") }).nodes[0].verdict, "ok");
});

test("a run with no states has no flow", () => {
  assert.deepStrictEqual(Machine.flow({ states: [] }), { nodes: [], edges: [] });
  assert.deepStrictEqual(Machine.flow({}), { nodes: [], edges: [] });
});

test("the state at a time is the visit that holds it", () => {
  const run = { states: path("A", "B") };
  assert.strictEqual(Machine.at(run, 0).name, "A");
  assert.strictEqual(Machine.at(run, 10).name, "B");
  assert.strictEqual(Machine.at(run, 20), null);
  assert.strictEqual(Machine.at({}, 1), null);
  assert.strictEqual(Machine.at({ states: [{ name: "A", t: 0, end: null }] }, 99).name, "A");
});
