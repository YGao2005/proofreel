(() => {
  const W = innerWidth, H = innerHeight;
  const skip = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "HEAD", "TITLE", "OPTION"]);
  const fields = new Set(["", "text", "search", "email", "url", "tel", "number", "button", "submit", "reset"]);
  const visible = (el) => el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true});
  const pad = (cs, side) => parseFloat(cs["padding" + side]) + parseFloat(cs["border" + side + "Width"]);
  const canvas = document.createElement("canvas").getContext("2d");
  const words = [];

  const add = (text, left, top, width, height, el) => {
    const x = Math.max(left, 0), y = Math.max(top, 0), r = Math.min(left + width, W), b = Math.min(top + height, H);
    if (r - x < 1 || b - y < 1) return;
    const hit = document.elementFromPoint((x + r) / 2, (y + b) / 2);
    if (hit && (el.contains(hit) || hit.contains(el))) {
      words.push({text, x: Math.round(x), y: Math.round(y), w: Math.round(r - x), h: Math.round(b - y)});
    }
  };

  const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT);
  const range = document.createRange();
  for (let node; (node = walker.nextNode());) {
    const el = node.parentElement;
    if (!el || skip.has(el.tagName) || !node.data.trim() || !visible(el)) continue;
    for (const m of node.data.matchAll(/\S+/g)) {
      range.setStart(node, m.index);
      range.setEnd(node, m.index + m[0].length);
      const r = range.getClientRects()[0];
      if (r) add(m[0], r.left, r.top, r.width, r.height, el);
    }
  }

  for (const el of document.querySelectorAll("input, textarea, select")) {
    if (el.tagName === "INPUT" && !fields.has(el.type) || !visible(el)) continue;
    const text = el.tagName === "SELECT" ? (el.selectedOptions[0] || {}).text : el.value || el.placeholder;
    if (!text) continue;
    const box = el.getBoundingClientRect(), cs = getComputedStyle(el);
    const size = parseFloat(cs.fontSize), line = parseFloat(cs.lineHeight) || size * 1.2;
    const room = box.width - pad(cs, "Left") - pad(cs, "Right");
    canvas.font = cs.font;
    text.split("\n").forEach((row, i) => {
      const total = canvas.measureText(row).width;
      const shift = cs.textAlign === "center" ? (room - total) / 2 : /right|end/.test(cs.textAlign) ? room - total : 0;
      const top = el.tagName === "TEXTAREA" ? box.top + pad(cs, "Top") + i * line : box.top + (box.height - line) / 2;
      for (const m of row.matchAll(/\S+/g)) {
        const before = canvas.measureText(row.slice(0, m.index)).width;
        add(m[0], box.left + pad(cs, "Left") + shift + before, top, canvas.measureText(m[0]).width, line, el);
      }
    });
  }

  words.sort((a, b) => a.y + a.h / 2 - (b.y + b.h / 2));
  const rows = [];
  for (const w of words) {
    const row = rows[rows.length - 1];
    if (row && Math.abs(w.y + w.h / 2 - row.mid) < row.h / 2) row.words.push(w);
    else rows.push({mid: w.y + w.h / 2, h: w.h, words: [w]});
  }
  const lines = [];
  for (const row of rows) {
    row.words.sort((a, b) => a.x - b.x);
    const joined = [];
    for (const w of row.words) {
      const before = joined[joined.length - 1];
      if (before && w.x - (before.x + before.w) < w.h * 0.15) {
        before.text += w.text;
        before.w = Math.max(before.w, w.x + w.w - before.x);
        before.h = Math.max(before.h, w.h);
      } else joined.push({...w});
    }
    let line = null;
    for (const w of joined) {
      const last = line && line[line.length - 1];
      if (last && w.x - (last.x + last.w) <= Math.min(last.h, w.h)) line.push(w);
      else lines.push(line = [w]);
    }
  }
  return lines.map((ws) => {
    const x = Math.min(...ws.map((w) => w.x)), y = Math.min(...ws.map((w) => w.y));
    return {text: ws.map((w) => w.text).join(" "), x, y, w: Math.max(...ws.map((w) => w.x + w.w)) - x,
            h: Math.max(...ws.map((w) => w.y + w.h)) - y, words: ws};
  }).sort((a, b) => a.y - b.y || a.x - b.x);
})()
