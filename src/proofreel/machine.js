// The state machine of a review folder: the path of every run through its states, merged into one graph and laid
// out from top to bottom. Pure functions: the page draws the result, and node runs the tests.
const Machine = (() => {
  const START = "Start";

  // A node for each state name, and an edge for each pair of states that follow each other in a run. Each visit and
  // each step along an edge remembers its run and its place in that run's path.
  function build(runs) {
    const nodes = new Map(), edges = new Map();
    const node = id => nodes.get(id) || nodes.set(id, { id, visits: [] }).get(id);
    runs.forEach((r, run) => {
      if (!r.states || !r.states.length) return;
      let from = node(START).id;
      r.states.forEach((v, visit) => {
        node(v.name).visits.push({ run, visit });
        const key = JSON.stringify([from, v.name]);
        if (!edges.has(key)) edges.set(key, { from, to: v.name, takes: [] });
        edges.get(key).takes.push({ run, visit });
        from = v.name;
      });
    });
    return { nodes: [...nodes.values()], edges: [...edges.values()] };
  }

  // Layers come from the longest path from Start, with the edges that go back (loops) left out. A long edge gets a
  // point on each layer that it crosses. Each layer is sorted by the mean place of its neighbours, down and up a few
  // times, to cut crossings. Edges that go back run in lanes at the side nearer to where they start.
  // size(id) gives a node's [width, height]. Returns nodes with x, y, w, h, and edges with an SVG path d and a
  // label place [x, y, anchor, slope] (the slope is how far the curve runs sideways for each unit down at the label).
  function layout(graph, size, gap = { x: 28, y: 56, lane: 14 }) {
    const out = new Map(graph.nodes.map(n => [n.id, []]));
    for (const e of graph.edges) out.get(e.from).push(e);
    const seen = new Map(), back = new Set(), order = [];
    const walk = id => {
      seen.set(id, 1);
      for (const e of out.get(id)) {
        if (seen.get(e.to) === 1) back.add(e);
        else if (!seen.has(e.to)) walk(e.to);
      }
      seen.set(id, 2);
      order.unshift(id);
    };
    for (const n of graph.nodes) if (!seen.has(n.id)) walk(n.id);
    const rank = new Map(order.map(id => [id, 0]));
    for (const id of order) for (const e of out.get(id)) if (!back.has(e)) rank.set(e.to, Math.max(rank.get(e.to), rank.get(id) + 1));

    const layers = [], items = new Map();
    const put = item => { (layers[item.rank] = layers[item.rank] || []).push(item); return item; };
    for (const id of order) {
      const [w, h] = size(id);
      items.set(id, put({ id, w, h, rank: rank.get(id), up: [], down: [] }));
    }
    const routes = graph.edges.map(e => {
      const chain = [items.get(e.from)];
      if (back.has(e)) chain.push(items.get(e.to));
      else {
        for (let r = rank.get(e.from) + 1; r < rank.get(e.to); r++) chain.push(put({ w: 8, h: 0, rank: r, up: [], down: [], dummy: true }));
        chain.push(items.get(e.to));
        for (let i = 1; i < chain.length; i++) { chain[i - 1].down.push(chain[i]); chain[i].up.push(chain[i - 1]); }
      }
      return { edge: e, back: back.has(e), chain };
    });

    layers.forEach(l => l.forEach((it, i) => { it.order = i; }));
    const mean = list => list.length ? list.reduce((s, it) => s + it.order, 0) / list.length : null;
    for (let pass = 0; pass < 4; pass++) {
      const down = pass % 2 === 0;
      for (const layer of down ? layers.slice(1) : layers.slice(0, -1).reverse()) {
        const key = new Map(layer.map(it => [it, mean(down ? it.up : it.down) ?? it.order]));
        layer.sort((a, b) => key.get(a) - key.get(b) || a.order - b.order);
        layer.forEach((it, i) => { it.order = i; });
      }
    }

    const span = l => l.reduce((s, it) => s + it.w, 0) + gap.x * (l.length - 1);
    const inner = Math.max(...layers.map(span));
    let top = 0;
    const rows = layers.map(l => {
      const h = Math.max(...l.map(it => it.h)), row = { top, h };
      let x = (inner - span(l)) / 2;
      for (const it of l) { it.x = x; it.y = top + (h - it.h) / 2; x += it.w + gap.x; }
      top += h + gap.y;
      return row;
    });
    const loops = routes.filter(r => r.back && r.edge.from !== r.edge.to);
    const side = r => r.chain[0].x + r.chain[0].w / 2 < inner / 2 ? "left" : "right";
    const lanes = { left: loops.filter(r => side(r) === "left"), right: loops.filter(r => side(r) === "right") };
    const margin = gap.lane * (lanes.left.length + 1);
    for (const it of items.values()) it.x += margin;
    for (const l of layers) for (const it of l) if (it.dummy) it.x += margin;

    const curve = (a, b) => ` C${a[0]},${(a[1] + b[1]) / 2} ${b[0]},${(a[1] + b[1]) / 2} ${b[0]},${b[1]}`;
    const edges = routes.map(r => {
      const [a, b] = [r.chain[0], r.chain[r.chain.length - 1]];
      let d, label = null;
      if (r.back && a === b) {
        const [x, y] = [a.x + a.w, a.y + a.h / 2];
        d = `M${x},${y - 6} C${x + 26},${y - 20} ${x + 26},${y + 20} ${x},${y + 6}`;
      } else if (r.back) {
        const left = side(r) === "left", k = lanes[left ? "left" : "right"].indexOf(r) + 1;
        const lane = left ? margin - gap.lane * k : margin + inner + gap.lane * k;
        const [x1, y1, x2, y2] = left ? [a.x, a.y + a.h / 2, b.x, b.y + b.h / 2] : [a.x + a.w, a.y + a.h / 2, b.x + b.w, b.y + b.h / 2];
        const s = left ? -1 : 1, bend = Math.min(8, Math.abs(y1 - y2) / 2);
        d = `M${x1},${y1} H${lane - s * bend} Q${lane},${y1} ${lane},${y1 - bend} V${y2 + bend} Q${lane},${y2} ${lane - s * bend},${y2} H${x2}`;
      } else {
        const points = [[a.x + a.w / 2, a.y + a.h]];
        for (const it of r.chain.slice(1, -1)) {
          const row = rows[it.rank];
          points.push([it.x + it.w / 2, row.top], [it.x + it.w / 2, row.top + row.h]);
        }
        points.push([b.x + b.w / 2, b.y]);
        d = `M${points[0]}`;
        for (let i = 1; i < points.length; i++) d += i % 2 ? curve(points[i - 1], points[i]) : ` L${points[i]}`;
        // An edge that leans left keeps its label on the left, so the labels of a branch do not run into each other.
        const lean = Math.sign(points[1][0] - points[0][0]);
        const slope = 1.5 * Math.abs(points[1][0] - points[0][0]) / Math.max(1, points[1][1] - points[0][1]);
        label = [(points[0][0] + points[1][0]) / 2, (points[0][1] + points[1][1]) / 2, lean < 0 ? "end" : "start", slope];
      }
      return { ...r.edge, back: r.back, d, label };
    });
    const nodes = order.map(id => { const { x, y, w, h } = items.get(id); return { id, x, y, w, h }; });
    const width = margin + inner + gap.lane * (lanes.right.length + 1) + (routes.some(r => r.back && r.edge.from === r.edge.to) ? 28 : 0);
    return { width, height: top - gap.y, nodes, edges };
  }

  // A node's verdict in one run: "bad" when a visit failed, "ok" when one passed, "unchecked" when it was visited
  // with no checks, and null when the run did not visit it.
  function verdict(states, id) {
    const visits = (states || []).filter(v => v.name === id);
    if (!visits.length) return null;
    return visits.some(v => v.ok === false) ? "bad" : visits.some(v => v.ok) ? "ok" : "unchecked";
  }


  function at(run, t) {
    return (run.states || []).find(v => v.t <= t && (v.end == null || t < v.end)) || null;
  }
  function sections(run) {
    const events = (run.events || []).filter(e => e.kind !== "state"), states = run.states || [];
    const part = (visit, from, to, back) => {
      const mine = events.filter(e => e.t >= from && e.t < to), checks = mine.filter(e => e.kind === "check" && !e.budget);
      return { visit, name: visit ? visit.name : null, t: from, ok: visit ? visit.ok : null, back, events: mine,
        passed: checks.filter(e => e.ok).length, total: checks.length };
    };
    if (!states.length) return [part(null, -Infinity, Infinity, null)];
    const seen = new Set(), out = [];
    if (events.some(e => e.t < states[0].t)) out.push(part(null, -Infinity, states[0].t, null));
    states.forEach((v, i) => {
      out.push(part(v, v.t, i === states.length - 1 || v.end == null ? Infinity : v.end, seen.has(v.name) ? v.name : null));
      seen.add(v.name);
    });
    return out;
  }
  function now(list, t) {
    let i = 0;
    list.forEach((s, k) => { if (s.t <= t) i = k; });
    let j = -1;
    list[i].events.forEach((e, k) => { if (e.t <= t + 0.05) j = k; });
    return { section: i, event: j };
  }

  return { START, build, layout, verdict, at, sections, now };
})();
if (typeof module === "object") module.exports = Machine;
