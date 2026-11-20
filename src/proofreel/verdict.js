// What a run says about itself, in the words the page uses: Pass, Fail, Not checked. A check is a screen check or a
// budget (a check on a metric; its event has a budget). Pure functions: the page shows the result, and node runs the tests.
const Verdict = (() => {
  const T = typeof Tracks === "undefined" ? require("./tracks.js") : Tracks;
  const RUN = { works: "Pass", problem: "Fail", shown: "No checks" };
  const VISIT = { ok: "Pass", bad: "Fail", unchecked: "Not checked" };
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  const sentence = text => text ? text[0].toUpperCase() + text.slice(1) : text;
  const isBudget = e => e.kind === "check" && !!e.budget;
  const matches = (glob, m) => new RegExp("^" + glob.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".") + "$").test(m);
  const seriesOf = run => (run.metrics && run.metrics.series) || [];
  const NOUN = { net: "requests", input: "inputs" };
  const STAT = { mean: "Average", min: "Lowest", max: "Highest", last: "Last" };
  const lowerFirst = text => /^[A-Z]{2}/.test(text) ? text : text[0].toLowerCase() + text.slice(1);

  // The budget as a person says it: "p95 request time: 4 ms (limit 500 ms)", "Failed requests: 1 (limit 0)".
  // detail is what the check measured, such as "p95 0.0172 s".
  function budgetText(budget, run, detail) {
    const mine = seriesOf(run).filter(s => matches(budget.glob, s.m));
    const group = budget.glob.split("/")[0], counting = budget.stat === "failed" || budget.stat === "count";
    const noun = NOUN[group] || "measurements";
    const what = mine.length === 1 && mine[0].label ? mine[0].label : group === "net" ? "request time" : budget.glob;
    const name = budget.stat === "failed" ? `Failed ${noun}` : budget.stat === "count" ? `Number of ${noun}`
      : /^p\d+$/.test(budget.stat) ? `${budget.stat} ${lowerFirst(what)}` : `${STAT[budget.stat]} ${lowerFirst(what)}`;
    const unit = counting ? "" : (mine[0] && mine[0].unit) || "";
    const found = /^\S+ (-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)/.exec(detail || "");
    const limit = budget.below !== null && budget.below !== undefined
      ? `limit ${counting ? Math.ceil(budget.below) - 1 : T.format(budget.below, unit)}`
      : `minimum ${counting ? budget.above : T.format(budget.above, unit)}`;
    return found ? `${name}: ${T.format(+found[1], unit)} (${limit})` : `${name} (${limit})`;
  }

  const budgetOf = (run, e) => budgetText(e.budget, run, e.detail);

  // Screen checks passed of total and budgets failed of total, for a run or for part of it.
  const tally = events => {
    const checks = events.filter(e => e.kind === "check" && !e.budget), budgets = events.filter(isBudget);
    return { checks: { passed: checks.filter(e => e.ok).length, total: checks.length },
      budgets: { failed: budgets.filter(e => e.ok === false).length, total: budgets.length } };
  };

  // The tally in words: "3/3 checks", "1 budget failed" (or "2 budgets passed").
  function words(count) {
    const out = [];
    if (count.checks.total) out.push(`${count.checks.passed}/${count.checks.total} checks`);
    if (count.budgets.failed) out.push(`${plural(count.budgets.failed, "budget")} failed`);
    else if (count.budgets.total) out.push(`${plural(count.budgets.total, "budget")} passed`);
    return out;
  }

  // The tally of a run and its verdict in page words.
  const summary = run => ({ ...tally(run.events), verdict: { works: "pass", problem: "fail", shown: "none" }[run.verdict] });

  const request = label => {
    const { method, path } = T.request(label);
    return method ? `${method} ${path || "/"}` : label;
  };

  // The worst moment of the series a budget judged: the highest value (the lowest for a minimum).
  function worst(series, low) {
    let best = null;
    const take = (t, v) => { if (best === null || (low ? v < best[1] : v > best[1])) best = [t, v]; };
    for (const s of series) {
      for (const p of s.points || []) take(p[0], p[3] ?? p[1]);
      for (const p of s.spans || []) take(p[0], p[1]);
      for (const m of s.marks || []) if (best === null) best = [m[0], 0];
    }
    return best && best[0];
  }

  const screen = e => {
    const quote = /"[^"]*"/.exec(e.text);
    if (e.kind === "wait") return `${quote ? quote[0] : e.text} did not show${/not seen in (.+)/.exec(e.detail || "") ? ` in ${/not seen in (.+)/.exec(e.detail)[1]}` : ""}`;
    if (quote && / is not on the screen$/.test(e.text)) return `${quote[0]} still shows`;
    if (quote && / is on the screen$/.test(e.text)) return `${quote[0]} did not show`;
    return e.detail ? `${e.text}: ${e.detail}` : e.text;
  };

  // The first failure in time: { text, t (real seconds), target } where target is the tab the failure lives in
  // ("network", "stats") or null. A failed budget on requests names the first failed request; another budget gives its
  // worst value against the limit; a failed wait or screen check says what did not show; a run that stopped says why.
  function cause(run) {
    const found = [];
    for (const e of run.events) {
      if (e.ok !== false || !["check", "wait"].includes(e.kind)) continue;
      if (!e.budget) { found.push({ text: screen(e), t: e.t, target: null }); continue; }
      const mine = seriesOf(run).filter(s => matches(e.budget.glob, s.m));
      const bad = e.budget.stat === "failed" ? mine.flatMap(s => (s.spans || []).filter(p => p[2] === false)).sort((a, b) => a[0] - b[0])[0] : null;
      if (bad) found.push({ text: bad[5] ? `${request(bad[3])} returned ${bad[5]}` : `${request(bad[3])} failed`, t: bad[0], target: "network" });
      else found.push({ text: budgetOf(run, e), t: worst(mine, e.budget.below === null || e.budget.below === undefined) ?? e.t, target: "stats" });
    }
    if (run.error) found.push({ text: run.error, t: run.real, target: null });
    return found.sort((a, b) => a.t - b.t)[0] || null;
  }

  return { RUN, VISIT, plural, sentence, isBudget, matches, budgetText, budgetOf, tally, words, summary, cause };
})();
if (typeof module === "object") module.exports = Verdict;
