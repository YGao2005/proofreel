// Metric tracks on the video's time axis: the time map, bins to draw, rows for spans, and the value at a time.
// Pure functions: the page draws with them, and node runs the tests.
const Tracks = (() => {
  // The run's clock: [real, video] points joined by straight lines. along() maps one column to the other.
  function along(knots, x, y, value) {
    if (knots.length < 2) return value;
    let i = 1;
    while (i < knots.length - 1 && knots[i][x] <= value) i++;
    const [a, b] = [knots[i - 1], knots[i]];
    return b[x] > a[x] ? a[y] + (b[y] - a[y]) * (value - a[x]) / (b[x] - a[x]) : a[y];
  }

  // video(real), real(video), speed(video), and the stretches that play at least min times faster than real time:
  // [{from, to, speed}] in video seconds, the speed being the fastest part of the stretch.
  function timemap(knots) {
    const rate = i => knots[i][1] > knots[i - 1][1] ? (knots[i][0] - knots[i - 1][0]) / (knots[i][1] - knots[i - 1][1]) : 1;
    const speed = video => {
      let i = 1;
      while (i < knots.length - 1 && knots[i][1] <= video) i++;
      return knots.length > 1 ? rate(i) : 1;
    };
    const stretches = (min = 1.5) => {
      const out = [];
      for (let i = 1; i < knots.length; i++) {
        const s = rate(i), last = out[out.length - 1];
        if (s < min) continue;
        if (last && last.to === knots[i - 1][1]) { last.to = knots[i][1]; last.speed = Math.max(last.speed, s); }
        else out.push({ from: knots[i - 1][1], to: knots[i][1], speed: s });
      }
      return out;
    };
    return { video: real => along(knots, 0, 1, real), real: video => along(knots, 1, 0, video), speed, stretches };
  }

  // Points [t, v] or [t, v, lo, hi] in width columns, x(t) giving a column: each column that has points gets
  // {lo, hi, v} (the lowest, the highest, the mean), so a spike stays when many points share one column.
  function bin(points, x, width) {
    const out = new Array(width).fill(null), n = new Array(width).fill(0);
    for (const [t, v, lo = v, hi = v] of points) {
      const i = Math.floor(x(t));
      if (i < 0 || i >= width) continue;
      const c = out[i];
      out[i] = c ? { lo: Math.min(c.lo, lo), hi: Math.max(c.hi, hi), v: c.v + v } : { lo, hi, v };
      n[i]++;
    }
    return out.map((c, i) => c && { ...c, v: c.v / n[i] });
  }

  // Spans [{from, to}] (sorted by from) in at most rows rows, with gap between two spans in a row. Returns the row of
  // each span (-1 when it does not fit) and how many did not fit.
  function pack(spans, rows, gap = 1) {
    const ends = [];
    let more = 0;
    const row = spans.map(s => {
      let r = ends.findIndex(end => end + gap <= s.from);
      if (r < 0 && ends.length < rows) r = ends.push(-Infinity) - 1;
      if (r < 0) { more++; return -1; }
      ends[r] = Math.max(s.to, s.from + gap);
      return r;
    });
    return { row, more };
  }

  // A series' value at real time t: the last sample, the length of the last span that ended, or the number of
  // marks so far. null when nothing came yet.
  function valueAt(series, t) {
    if (series.kind === "sample") {
      let last = null;
      for (const p of series.points || []) { if (p[0] > t) break; last = p[1]; }
      return last;
    }
    if (series.kind === "span") {
      let last = null, end = -Infinity;
      for (const [from, d] of series.spans || []) if (from + d <= t && from + d >= end) { end = from + d; last = d; }
      return last;
    }
    return (series.marks || []).filter(m => m[0] <= t).length;
  }

  // Requests (spans that have phases) on one real-time axis, in start order: each row's place and length, and each
  // phase as [name, from, width], all as fractions of the axis. The phases are laid end to end from the start.
  function waterfall(series) {
    const rows = [];
    for (const s of series) for (const [t, d, ok, label, phases, status] of s.spans || [])
      if (phases) rows.push({ m: s.m, t, d, ok, label: label || s.m, phases, status });
    rows.sort((a, b) => a.t - b.t);
    if (!rows.length) return { rows, names: [], from: 0, to: 0 };
    const from = rows[0].t, to = Math.max(...rows.map(r => r.t + r.d)), span = to - from || 1;
    for (const r of rows) {
      let at = r.t;
      r.left = (r.t - from) / span;
      r.width = r.d / span;
      r.parts = Object.entries(r.phases).map(([name, v]) => { const part = [name, (at - from) / span, v / span]; at += v; return part; });
    }
    return { rows, names: [...new Set(rows.flatMap(r => Object.keys(r.phases)))], from, to };
  }

  // One formatter for every number on the page: under 1 s "9 ms", under 60 s "2.4 s", then "1 m 12 s"; memory in MB or GB;
  // CPU in %.
  function duration(v) {
    if (v < 1) return `${Math.round(v * 1000)} ms`;
    if (v < 59.95) return `${v.toFixed(1)} s`;
    const total = Math.round(v);
    return `${Math.floor(total / 60)} m ${total % 60} s`;
  }
  function format(v, unit) {
    if (v === null || v === undefined) return "–";
    if (unit === "s") return duration(v);
    if (unit === "MB" && Math.abs(v) >= 1024) return `${+(v / 1024).toPrecision(3)} GB`;
    const n = Math.abs(v) >= 100 ? Math.round(v) : +v.toPrecision(3);
    return unit === "%" ? `${n}%` : unit ? `${n} ${unit}` : String(n);
  }

  return { along, timemap, bin, pack, valueAt, waterfall, duration, format };
})();
if (typeof module === "object") module.exports = Tracks;
