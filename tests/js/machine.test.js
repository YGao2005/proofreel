const test = require("node:test");
const assert = require("node:assert");
const Machine = require("../../src/proofreel/machine.js");

const path = (...names) => names.map((name, i) => ({ name, t: i * 10, end: i * 10 + 10, ok: true }));
const check = (t, ok = true) => ({ kind: "check", t, ok });

test("a visit holds the events in its time, and counts the checks, not the waits", () => {
  const events = [{ kind: "state", t: 0, text: "A" }, { kind: "step", t: 1 }, check(2), check(3, false), { kind: "wait", t: 4, ok: true },
    { kind: "state", t: 10, text: "B" }, check(11)];
  const [a, b] = Machine.sections({ states: path("A", "B"), events });
  assert.deepStrictEqual([a.name, a.events.length, a.passed, a.total], ["A", 4, 1, 2]);
  assert.deepStrictEqual([b.name, b.events.length, b.passed, b.total], ["B", 1, 1, 1]);
});

test("a section takes the verdict of its visit", () => {
  const states = [{ name: "A", t: 0, end: 1, ok: true }, { name: "B", t: 1, end: 2, ok: null }, { name: "C", t: 2, end: 3, ok: false }];
  assert.deepStrictEqual(Machine.sections({ states }).map(s => s.ok), [true, null, false]);
});

test("a return to a state seen before says so; a first visit does not", () => {
  const list = Machine.sections({ states: path("Sign in", "Wrong password", "Sign in", "Welcome") });
  assert.deepStrictEqual(list.map(s => s.back), [null, null, "Sign in", null]);
});

test("the last visit holds every later event", () => {
  const [a] = Machine.sections({ states: path("A"), events: [check(5), check(99)] });
  assert.strictEqual(a.events.length, 2);
});

test("events before the first state go to an unnamed section", () => {
  const list = Machine.sections({ states: [{ name: "A", t: 5, end: 9, ok: true }], events: [{ kind: "step", t: 1 }, check(6)] });
  assert.deepStrictEqual(list.map(s => [s.name, s.events.length]), [[null, 1], ["A", 1]]);
});

test("a run with no states is one unnamed section with every event but the state marks", () => {
  const list = Machine.sections({ events: [{ kind: "step", t: 1 }, check(2)] });
  assert.deepStrictEqual(list.map(s => [s.name, s.visit, s.events.length, s.passed, s.total]), [[null, null, 2, 1, 1]]);
  assert.strictEqual(Machine.sections({})[0].events.length, 0);
});

test("the current visit and event for a time", () => {
  const events = [{ kind: "step", t: 1 }, check(2), { kind: "step", t: 12 }];
  const list = Machine.sections({ states: path("A", "B"), events });
  assert.deepStrictEqual(Machine.now(list, 0), { section: 0, event: -1 });
  assert.deepStrictEqual(Machine.now(list, 2.5), { section: 0, event: 1 });
  assert.deepStrictEqual(Machine.now(list, 10), { section: 1, event: -1 });
  assert.deepStrictEqual(Machine.now(list, 15), { section: 1, event: 0 });
  assert.deepStrictEqual(Machine.now(Machine.sections({ events }), 1.5), { section: 0, event: 0 });
});

test("the state at a time is the visit that holds it", () => {
  const run = { states: path("A", "B") };
  assert.strictEqual(Machine.at(run, 0).name, "A");
  assert.strictEqual(Machine.at(run, 10).name, "B");
  assert.strictEqual(Machine.at(run, 20), null);
  assert.strictEqual(Machine.at({}, 1), null);
  assert.strictEqual(Machine.at({ states: [{ name: "A", t: 0, end: null }] }, 99).name, "A");
});
