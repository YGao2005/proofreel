const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const Tracks = require("../../src/proofreel/tracks.js");

const clock = [[0, 0], [10, 10], [12, 11], [92, 21], [100, 29]];

test("the time map goes both ways and finds the sped-up stretches", () => {
  const map = Tracks.timemap(clock);
  assert.strictEqual(map.video(5), 5);
  assert.strictEqual(map.video(52), 16);
  assert.strictEqual(map.real(16), 52);
  assert.strictEqual(map.speed(15), 8);
  assert.deepStrictEqual(map.stretches(), [{ from: 10, to: 21, speed: 8 }]);
  assert.deepStrictEqual(Tracks.timemap([[0, 0]]).stretches(), []);
});

test("binning on the video axis keeps a spike inside an 8x stretch", () => {
  const map = Tracks.timemap(clock);
  const points = Array.from({ length: 100 }, (_, t) => [t, t === 50 ? 99 : 10]);
  const cols = Tracks.bin(points, t => map.video(t) / 29 * 29, 29);
  const top = cols.reduce((a, c) => c && c.hi > a.hi ? c : a, { hi: -1 });
  assert.strictEqual(top.hi, 99);
  assert.strictEqual(cols.indexOf(top), Math.floor(map.video(50)));
  assert.ok(top.v < 99 && top.lo === 10);
});

test("a packed bin keeps its envelope", () => {
  const cols = Tracks.bin([[0.2, 5, 1, 9], [0.7, 7]], t => t * 2, 2);
  assert.deepStrictEqual(cols, [{ lo: 1, hi: 9, v: 5 }, { lo: 7, hi: 7, v: 7 }]);
});

test("spans pack into rows, and what does not fit is counted", () => {
  const spans = [{ from: 0, to: 10 }, { from: 2, to: 5 }, { from: 3, to: 4 }, { from: 11, to: 12 }, { from: 6, to: 9 }];
  const { row, more } = Tracks.pack(spans, 2);
  assert.deepStrictEqual(row, [0, 1, -1, 0, 1]);
  assert.strictEqual(more, 1);
});

test("the value at a time is the last sample, the last span that ended, or the marks so far", () => {
  const sample = { kind: "sample", points: [[1, 10], [2, 20, 15, 25], [3, 30]] };
  assert.strictEqual(Tracks.valueAt(sample, 0.5), null);
  assert.strictEqual(Tracks.valueAt(sample, 2.5), 20);
  const span = { kind: "span", spans: [[1, 0.5, true], [1.2, 2, false], [2, 0.1, true]] };
  assert.strictEqual(Tracks.valueAt(span, 2.2), 0.1);
  assert.strictEqual(Tracks.valueAt(span, 1.6), 0.5);
  assert.strictEqual(Tracks.valueAt({ kind: "mark", marks: [[1], [2], [5]] }, 3), 2);
});

test("values read in their unit", () => {
  assert.strictEqual(Tracks.format(0.123, "s"), "123 ms");
  assert.strictEqual(Tracks.format(2.5, "s"), "2.5 s");
  assert.strictEqual(Tracks.format(42.42, "%"), "42.4%");
  assert.strictEqual(Tracks.format(1234.5, "MB"), "1.21 GB");
  assert.strictEqual(Tracks.format(519.8, "MB"), "520 MB");
  assert.strictEqual(Tracks.format(0.009, "s"), "9 ms");
  assert.strictEqual(Tracks.format(72, "s"), "1 m 12 s");
  assert.strictEqual(Tracks.format(59.97, "s"), "1 m 0 s");
  assert.strictEqual(Tracks.format(null, "%"), "–");
});

test("the requests of a network probe run draw as a waterfall in start order", () => {
  const lines = fs.readFileSync(path.join(__dirname, "../fixtures/network/metrics/network.jsonl"), "utf8").trim().split("\n").map(JSON.parse);
  const start = lines[0].t - lines[0].d;
  const series = [{ m: "net/10.0.2.2", kind: "span", spans: lines.map(l => [l.t - l.d - start, l.d, l.ok, l.label, l.phases, l.n.status]) },
    { m: "host/cpu", kind: "sample", points: [[0, 1]] }];
  const fall = Tracks.waterfall(series);
  assert.deepStrictEqual(fall.names, ["connect", "wait", "receive"]);
  assert.strictEqual(fall.rows.length, 6);
  assert.strictEqual(fall.rows[0].left, 0);
  const slow = fall.rows.find(r => r.label.endsWith("/slow"));
  assert.ok(slow.width > 0.45 && slow.parts[1][0] === "wait" && slow.parts[1][2] > 0.45);
  assert.strictEqual(fall.rows.find(r => r.status === 500).ok, false);
  assert.ok(Math.abs(Math.max(...fall.rows.map(r => r.left + r.width)) - 1) < 1e-9);
  assert.deepStrictEqual(Tracks.waterfall([series[1]]).rows, []);
});

test("axis ticks fall on a nice step and number at most ten", () => {
  assert.deepStrictEqual(Tracks.ticks(0, 7.4), [0, 1, 2, 3, 4, 5, 6, 7]);
  assert.deepStrictEqual(Tracks.ticks(0, 30), [0, 5, 10, 15, 20, 25, 30]);
  assert.deepStrictEqual(Tracks.ticks(1.7, 3.5), [1.8, 2, 2.2, 2.4, 2.6, 2.8, 3, 3.2, 3.4]);
  assert.ok(Tracks.ticks(0, 600).length <= 10 && Tracks.ticks(0, 600).length >= 6);
  assert.deepStrictEqual(Tracks.ticks(2, 2), []);
  assert.strictEqual(Tracks.axisLabel(0), "0 s");
  assert.strictEqual(Tracks.axisLabel(3), "3 s");
  assert.strictEqual(Tracks.axisLabel(2.5), "2.5 s");
  assert.strictEqual(Tracks.axisLabel(120), "2 m");
});

test("groups have human names, and a request label splits into method, host, and path", () => {
  assert.deepStrictEqual(["mem", "net", "web", "input", "other"].map(Tracks.groupName), ["Memory", "Network", "Browser", "Input", "Other"]);
  assert.deepStrictEqual(Tracks.request("GET 10.0.2.2:8791/api/tags"), { method: "GET", host: "10.0.2.2:8791", path: "/api/tags" });
  assert.deepStrictEqual(Tracks.request("click"), { method: "", host: "", path: "click" });
});

test("a hold at a click maps its real time to the start of the hold", () => {
  const knots = [[0, 0], [1, 1], [1, 1.3], [2, 2.3]];
  assert.equal(Tracks.along(knots, 0, 1, 1), 1);
  assert.ok(Math.abs(Tracks.along(knots, 0, 1, 1.0004) - 1) < 1e-3);
  assert.equal(Tracks.along(knots, 1, 0, 1.15), 1);
  assert.ok(Math.abs(Tracks.along(knots, 0, 1, 1.5) - 1.8) < 1e-9);
  assert.equal(Tracks.timemap(knots).speed(1.15), 0);
});
