const Machine = (() => {
  function flow(run) {
    const checks = (run.events || []).filter(e => e.kind === "check" || e.kind === "wait");
    const nodes = new Map(), edges = new Map();
    let from = null;
    for (const v of run.states || []) {
      if (!nodes.has(v.name)) nodes.set(v.name, { id: v.name, passed: 0, total: 0, visits: [] });
      const node = nodes.get(v.name), mine = checks.filter(e => e.t >= v.t && (v.end == null || e.t < v.end));
      node.visits.push({ t: v.t, ok: v.ok });
      node.total += mine.length;
      node.passed += mine.filter(e => e.ok).length;
      if (from !== null) {
        const key = JSON.stringify([from, v.name]);
        if (!edges.has(key)) edges.set(key, { from, to: v.name, takes: 0 });
        edges.get(key).takes++;
      }
      from = v.name;
    }
    const list = [...nodes.values()], at = id => list.findIndex(n => n.id === id);
    for (const n of list) n.verdict = n.visits.some(v => v.ok === false) ? "bad" : n.visits.some(v => v.ok) ? "ok" : "unchecked";
    return { nodes: list, edges: [...edges.values()].map(e => ({ ...e, next: at(e.to) === at(e.from) + 1 })) };
  }
  function at(run, t) {
    return (run.states || []).find(v => v.t <= t && (v.end == null || t < v.end)) || null;
  }

  return { flow, at };
})();
if (typeof module === "object") module.exports = Machine;
