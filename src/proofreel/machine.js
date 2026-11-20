const Machine = (() => {
  function at(run, t) {
    return (run.states || []).find(v => v.t <= t && (v.end == null || t < v.end)) || null;
  }
  function sections(run) {
    const events = (run.events || []).filter(e => e.kind !== "state"), states = run.states || [];
    const part = (visit, from, to, back) => {
      const mine = events.filter(e => e.t >= from && e.t < to), checks = mine.filter(e => e.kind === "check");
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

  return { at, sections, now };
})();
if (typeof module === "object") module.exports = Machine;
