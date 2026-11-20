const test = require("node:test");
const assert = require("node:assert");
const Verdict = require("../../src/proofreel/verdict.js");

const net = { m: "net/10.0.2.2", kind: "span", unit: "s", spans: [
  [1.7, 0.008, true, "GET 10.0.2.2:8791/notes.html", {}, 200], [1.832, 0.0093, false, "GET 10.0.2.2:8791/api/tags", {}, 500],
  [2.0, 0.004, false, "POST 10.0.2.2:8791/api/notes", {}, 503]] };
const click = { m: "input/click", kind: "span", unit: "s", label: "Click latency", spans: [[3.1, 0.2, true, "click"], [4.0, 0.03, true, "click"]] };
const cpu = { m: "host/cpu", kind: "sample", unit: "%", label: "Host CPU", points: [[0.5, 10], [2.5, 62], [4, 20]] };
const check = (t, text, ok, extra = {}) => ({ t, kind: "check", text, ok, detail: "", ...extra });
const budget = (t, glob, stat, below, ok, detail, above = null) => check(t, `${glob} ${stat} below ${below}`, ok, { detail, budget: { glob, stat, below, above } });
const run = (events, extra = {}) => ({ verdict: "problem", error: "", real: 7.4, events, metrics: { series: [net, click, cpu], budgets: [] }, ...extra });

test("budgets count apart from screen checks, and the verdict uses the page words", () => {
  const events = [check(1, '"A" is on the screen', true), check(2, '"B" is on the screen', true), { t: 3, kind: "wait", text: 'wait for "C"', ok: true },
    budget(4, "net/*", "p95", 0.5, true, "p95 0.01 s"), budget(5, "net/*", "failed", 1, false, "failed 2")];
  assert.deepStrictEqual(Verdict.summary(run(events)), { checks: { passed: 2, total: 2 }, budgets: { failed: 1, total: 2 }, verdict: "fail" });
  assert.strictEqual(Verdict.summary(run([], { verdict: "works" })).verdict, "pass");
  assert.strictEqual(Verdict.summary(run([], { verdict: "shown" })).verdict, "none");
});

test("budgets read as a sentence from the metric, stat, and limit", () => {
  const r = run([]);
  assert.strictEqual(Verdict.budgetText({ glob: "net/*", stat: "failed", below: 1, above: null }, r, "failed 1"), "Failed requests: 1 (limit 0)");
  assert.strictEqual(Verdict.budgetText({ glob: "net/*", stat: "p95", below: 0.5, above: null }, r, "p95 0.004 s"), "p95 request time: 4 ms (limit 500 ms)");
  assert.strictEqual(Verdict.budgetText({ glob: "input/click", stat: "max", below: 0.1, above: null }, r, "max 0.032 s"), "Highest click latency: 32 ms (limit 100 ms)");
  assert.strictEqual(Verdict.budgetText({ glob: "host/cpu", stat: "max", below: 50, above: null }, r, "max 62"), "Highest host CPU: 62% (limit 50%)");
  assert.strictEqual(Verdict.budgetText({ glob: "net/*", stat: "count", below: null, above: 3 }, r, "count 2"), "Number of requests: 2 (minimum 3)");
  assert.strictEqual(Verdict.budgetText({ glob: "net/*", stat: "failed", below: 1, above: null }, r, "decided when the run stops"), "Failed requests (limit 0)");
});

test("the cause of a failed request budget is the first failed request, with its time", () => {
  const events = [budget(5, "net/*", "failed", 1, false, "failed 2")];
  assert.deepStrictEqual(Verdict.cause(run(events)), { text: "GET /api/tags returned 500", t: 1.832, target: "network" });
});

test("the cause of a latency budget is the worst value against the limit", () => {
  const events = [budget(5, "host/cpu", "max", 50, false, "max 62")];
  assert.deepStrictEqual(Verdict.cause(run(events)), { text: "Highest host CPU: 62% (limit 50%)", t: 2.5, target: "stats" });
});

test("the cause of a failed screen check is what did not show", () => {
  assert.deepStrictEqual(Verdict.cause(run([check(3.2, '"Welcome" is on the screen', false)])), { text: '"Welcome" did not show', t: 3.2, target: null });
  assert.strictEqual(Verdict.cause(run([check(3.2, '"Ad" is not on the screen', false)])).text, '"Ad" still shows');
  assert.strictEqual(Verdict.cause(run([{ t: 3, kind: "wait", text: 'wait for "Done"', ok: false, detail: "not seen in 10 s" }])).text, '"Done" did not show in 10 s');
});

test("a run that stopped with an error gives the error, and the first failure in time wins", () => {
  assert.deepStrictEqual(Verdict.cause(run([], { error: "The VM stopped." })), { text: "The VM stopped.", t: 7.4, target: null });
  const events = [budget(5, "net/*", "failed", 1, false, "failed 2"), check(0.9, '"X" is on the screen', false)];
  assert.strictEqual(Verdict.cause(run(events, { error: "x" })).t, 0.9);
  assert.strictEqual(Verdict.cause(run([check(1, "ok", true)], { verdict: "works" })), null);
});

test("counts read in the singular and the plural", () => {
  assert.strictEqual(Verdict.plural(1, "input"), "1 input");
  assert.strictEqual(Verdict.plural(2, "input"), "2 inputs");
  assert.strictEqual(Verdict.sentence("seen after 1.3 s"), "Seen after 1.3 s");
});
