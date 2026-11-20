(() => {
  if (self.__proofreelOn || typeof __proofreel !== "function") return;
  self.__proofreelOn = true;
  const send = (found) => {
    if (found.length) __proofreel(JSON.stringify({ now: performance.now(), url: location.href, found }));
  };
  const watch = (type, take, options = {}) => {
    try {
      new PerformanceObserver((list) => send(take(list.getEntries()))).observe({ type, buffered: true, ...options });
    } catch {}
  };
  const shown = () => send([{ k: "shown", at: performance.now(), v: document.visibilityState === "visible" }]);
  addEventListener("visibilitychange", shown);
  shown();
  let cls = 0, shifts = 0, first = 0, last = 0;
  const worst = new Map();

  watch("largest-contentful-paint", (entries) => entries.map((e) => ({ k: "lcp", at: e.startTime, v: e.startTime })));
  watch("layout-shift", (entries) => entries.flatMap((e) => {
    if (e.hadRecentInput) return [];
    if (e.startTime - last > 1000 || e.startTime - first > 5000) [shifts, first] = [0, e.startTime];
    last = e.startTime;
    shifts += e.value;
    if (shifts <= cls) return [];
    cls = shifts;
    return [{ k: "cls", at: e.startTime, v: cls }];
  }));
  watch("event", (entries) => {
    const longest = new Map();
    for (const e of entries) {
      if (e.interactionId && e.duration > (longest.get(e.interactionId)?.duration || 0)) longest.set(e.interactionId, e);
    }
    const found = [...longest].filter(([id, e]) => e.duration > (worst.get(id) || 0)).map(([id, e]) => {
      worst.set(id, e.duration);
      return { k: "interaction", at: e.startTime + e.duration, d: e.duration, name: e.name };
    });
    if (!found.length) return found;
    const all = [...worst.values()].sort((a, b) => b - a);
    return [...found, { k: "inp", at: found.at(-1).at, v: all[Math.min(Math.floor(all.length / 50), all.length - 1)] }];
  }, { durationThreshold: 16 });
  watch("long-animation-frame", (entries) => entries.map((e) => ({
    k: "frame", at: e.startTime + e.duration, d: e.duration, blocking: e.blockingDuration,
    name: e.scripts.map((s) => s.invoker).filter(Boolean)[0] || "",
  })));
  watch("mark", (entries) => entries.map((e) => ({ k: "mark", at: e.startTime, name: e.name })));
  watch("measure", (entries) => entries.map((e) => ({ k: "measure", at: e.startTime + e.duration, d: e.duration, name: e.name })));
})();
