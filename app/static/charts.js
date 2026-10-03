"use strict";

/*
 * Small SVG chart kit for the Insights tab (no dependencies).
 *
 * Follows one spec everywhere: thin marks (bars <= 24px, 4px rounded data-end,
 * square at the baseline), 2px lines, a 2px surface gap between stacked
 * segments, hairline solid gridlines, clean rounded ticks, text in ink tokens
 * (never the series colour), a hover/focus tooltip on every mark whose hit
 * area is larger than the mark, and a table view for every chart.
 */
const Charts = (() => {
  const NS = "http://www.w3.org/2000/svg";
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  function el(tag, attrs = {}, parent) {
    const node = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (parent) parent.appendChild(node);
    return node;
  }

  function text(parent, x, y, content, attrs = {}) {
    const t = el("text", { x, y, ...attrs }, parent);
    t.textContent = content;
    return t;
  }

  /** Clean axis ticks: 0, then round steps (1/2/5 × 10^n) covering max. */
  function niceTicks(max, count = 4) {
    if (max <= 0) return [0, 1];
    const raw = max / count;
    const mag = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw);
    const ticks = [];
    for (let v = 0; v <= max + step * 0.001; v += step) ticks.push(v);
    if (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] + step);
    return ticks;
  }

  /** Bar path: square at the baseline, 4px rounded at the data end. */
  function barPath(x, y, w, h, dir = "up", r = 4) {
    r = Math.max(0, Math.min(r, (dir === "up" ? h : w) / 2, (dir === "up" ? w : h) / 2));
    if (dir === "up") {
      return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
    }
    return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`;
  }

  /* ---------------------------------------------------------------- tooltip */

  function tooltip(host) {
    let tip = host.querySelector(".chart-tip");
    if (!tip) {
      tip = document.createElement("div");
      tip.className = "chart-tip";
      tip.setAttribute("role", "status");
      host.appendChild(tip);
    }
    return {
      show(x, y, title, rows) {
        tip.replaceChildren();
        const head = document.createElement("div");
        head.className = "chart-tip-title";
        head.textContent = title;
        tip.appendChild(head);
        for (const row of rows) {
          const line = document.createElement("div");
          line.className = "chart-tip-row";
          if (row.color) {
            const key = document.createElement("span");
            key.className = "chart-tip-key";
            key.style.background = row.color;
            line.appendChild(key);
          }
          const value = document.createElement("strong");
          value.textContent = row.value;
          line.appendChild(value);
          if (row.label) {
            const label = document.createElement("span");
            label.textContent = row.label;
            line.appendChild(label);
          }
          tip.appendChild(line);
        }
        tip.classList.add("on");
        const hostW = host.clientWidth;
        const tw = tip.offsetWidth;
        tip.style.left = `${Math.max(4, Math.min(x + 14, hostW - tw - 4))}px`;
        tip.style.top = `${Math.max(4, y - tip.offsetHeight - 10)}px`;
      },
      hide() { tip.classList.remove("on"); },
    };
  }

  function frame(host, height) {
    host.querySelector("svg")?.remove();
    const width = Math.max(260, host.clientWidth);
    const svg = el("svg", { width, height, viewBox: `0 0 ${width} ${height}`, class: "chart-svg" });
    host.prepend(svg);
    return { svg, width, height };
  }

  function yAxis(svg, ticks, scale, left, right, fmt) {
    const g = el("g", { class: "axis" }, svg);
    for (const t of ticks) {
      const y = scale(t);
      el("line", { x1: left, x2: right, y1: y, y2: y, class: t === 0 ? "baseline" : "grid" }, g);
      text(g, left - 8, y + 4, fmt(t), { "text-anchor": "end", class: "tick" });
    }
  }

  /* ---------------------------------------------------------------- area + line (single series, trend) */

  function area(host, data, { value, label, format, color, height = 260, ariaLabel }) {
    const { svg, width } = frame(host, height);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", ariaLabel);
    svg.setAttribute("tabindex", "0");
    const m = { top: 16, right: 18, bottom: 30, left: 62 };
    const max = Math.max(...data.map(value), 1);
    const ticks = niceTicks(max);
    const yMax = ticks[ticks.length - 1];
    const x = (i) => m.left + (data.length === 1 ? 0 : (i / (data.length - 1)) * (width - m.left - m.right));
    const y = (v) => m.top + (1 - v / yMax) * (height - m.top - m.bottom);
    yAxis(svg, ticks, y, m.left, width - m.right, format.axis);

    const every = Math.ceil(data.length / Math.max(2, Math.floor((width - m.left) / 70)));
    data.forEach((d, i) => {
      // Anchored to the latest day so the right edge never crowds.
      if ((data.length - 1 - i) % every === 0) text(svg, x(i), height - 10, label(d), { "text-anchor": "middle", class: "tick" });
    });

    const pts = data.map((d, i) => [x(i), y(value(d))]);
    const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0]},${p[1]}`).join("");
    el("path", { d: `${line}L${pts[pts.length - 1][0]},${y(0)}L${pts[0][0]},${y(0)}Z`, fill: color, "fill-opacity": 0.1 }, svg);
    el("path", { d: line, fill: "none", stroke: color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);

    // Label only the extreme: the best day.
    const best = data.reduce((b, d, i) => (value(d) > value(data[b]) ? i : b), 0);
    el("circle", { cx: pts[best][0], cy: pts[best][1], r: 4.5, fill: color, stroke: css("--surface") || "#fff", "stroke-width": 2 }, svg);
    const bestLabel = text(svg, pts[best][0], pts[best][1] - 10, `Best day ${format.short(value(data[best]))}`, { "text-anchor": "middle", class: "direct-label" });
    const half = bestLabel.getComputedTextLength() / 2;
    bestLabel.setAttribute("x", Math.max(m.left + half + 4, Math.min(pts[best][0], width - m.right - half)));

    // Crosshair snaps to the nearest day.
    const cross = el("line", { y1: m.top, y2: y(0), class: "crosshair", visibility: "hidden" }, svg);
    const dot = el("circle", { r: 5, fill: color, stroke: "#fff", "stroke-width": 2, visibility: "hidden" }, svg);
    const tip = tooltip(host);
    const showAt = (i) => {
      const [px, py] = pts[i];
      cross.setAttribute("x1", px); cross.setAttribute("x2", px); cross.setAttribute("visibility", "visible");
      dot.setAttribute("cx", px); dot.setAttribute("cy", py); dot.setAttribute("visibility", "visible");
      tip.show(px, py, label(data[i], true), [{ value: format.full(value(data[i])), label: format.unit, color }]);
    };
    const hide = () => { cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); tip.hide(); };
    const hit = el("rect", { x: m.left, y: 0, width: width - m.left - m.right, height: height - m.bottom, fill: "transparent" }, svg);
    hit.addEventListener("pointermove", (e) => {
      const box = svg.getBoundingClientRect();
      const px = e.clientX - box.left;
      let i = Math.round(((px - m.left) / (width - m.left - m.right)) * (data.length - 1));
      showAt(Math.max(0, Math.min(data.length - 1, i)));
    });
    hit.addEventListener("pointerleave", hide);
    let focusIdx = data.length - 1;
    svg.addEventListener("focus", () => showAt(focusIdx));
    svg.addEventListener("blur", hide);
    svg.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft") focusIdx = Math.max(0, focusIdx - 1);
      else if (e.key === "ArrowRight") focusIdx = Math.min(data.length - 1, focusIdx + 1);
      else return;
      e.preventDefault(); showAt(focusIdx);
    });
  }

  /* ---------------------------------------------------------------- vertical columns (single series or stacked) */

  function columns(host, data, { series, label, format, height = 240, ariaLabel, labelMax = true }) {
    const { svg, width } = frame(host, height);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", ariaLabel);
    const m = { top: 20, right: 12, bottom: 30, left: 44 };
    const total = (d) => series.reduce((s, k) => s + (d[k.key] || 0), 0);
    const max = Math.max(...data.map(total), 1);
    const ticks = niceTicks(max);
    const yMax = ticks[ticks.length - 1];
    const y = (v) => m.top + (1 - v / yMax) * (height - m.top - m.bottom);
    yAxis(svg, ticks, y, m.left, width - m.right, format.axis);

    const band = (width - m.left - m.right) / data.length;
    const bw = Math.min(24, Math.max(4, band * 0.62));
    const every = Math.ceil(data.length / Math.max(2, Math.floor((width - m.left) / 46)));
    const tip = tooltip(host);
    const best = data.reduce((b, d, i) => (total(d) > total(data[b]) ? i : b), 0);

    data.forEach((d, i) => {
      const cx = m.left + band * i + band / 2;
      let base = y(0);
      const visible = series.filter((s) => (d[s.key] || 0) > 0);
      visible.forEach((s, j) => {
        const v = d[s.key];
        const h = y(0) - y(v);
        const top = j === visible.length - 1;
        const gap = j > 0 ? 2 : 0;                 // 2px surface gap between stacked segments
        const segH = Math.max(0, h - gap);
        const segY = base - h;
        el("path", { d: top ? barPath(cx - bw / 2, segY, bw, segH, "up") : `M${cx - bw / 2},${segY}h${bw}v${segH}h${-bw}Z`, fill: s.color, class: "mark" }, svg);
        base = segY;
      });
      if ((data.length - 1 - i) % every === 0) text(svg, cx, height - 10, label(d), { "text-anchor": "middle", class: "tick" });
      if (labelMax && i === best && total(d) > 0) text(svg, cx, y(total(d)) - 6, format.short(total(d)), { "text-anchor": "middle", class: "direct-label" });

      const hit = el("rect", { x: m.left + band * i, y: m.top, width: band, height: height - m.top - m.bottom, fill: "transparent", tabindex: 0, class: "hit" }, svg);
      hit.setAttribute("aria-label", `${label(d, true)}: ${series.map((s) => `${s.label} ${format.full(d[s.key] || 0)}`).join(", ")}`);
      const show = () => tip.show(cx, y(total(d)), label(d, true),
        series.length > 1
          ? [...series].reverse().map((s) => ({ value: format.full(d[s.key] || 0), label: s.label, color: s.color }))
            .concat([{ value: format.full(total(d)), label: "total" }])
          : [{ value: format.full(total(d)), label: series[0].label, color: series[0].color }]);
      hit.addEventListener("pointerenter", show);
      hit.addEventListener("focus", show);
      hit.addEventListener("pointerleave", () => tip.hide());
      hit.addEventListener("blur", () => tip.hide());
    });
  }

  /* ---------------------------------------------------------------- horizontal bars (ranked list) */

  function hbars(host, data, { value, label, format, color, ariaLabel }) {
    const row = 34;
    const height = data.length * row + 8;
    const { svg, width } = frame(host, height);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", ariaLabel);
    const labelW = Math.min(190, width * 0.42);
    const valueW = 78;
    const max = Math.max(...data.map(value), 1);
    const span = width - labelW - valueW - 8;
    const tip = tooltip(host);
    data.forEach((d, i) => {
      const yTop = i * row + 6;
      const v = value(d);
      const w = Math.max(v > 0 ? 3 : 0, (v / max) * span);
      const t = text(svg, labelW - 10, yTop + 15, label(d), { "text-anchor": "end", class: "bar-label" });
      // Never clip a label at the edge: shorten it until it fits (full name stays in the tooltip and table).
      let full = label(d);
      while (t.getComputedTextLength() > labelW - 14 && full.length > 4) {
        full = full.slice(0, -1);
        t.textContent = full.trimEnd() + "…";
      }
      if (w > 0) el("path", { d: barPath(labelW, yTop + 3, w, 18, "right"), fill: color, class: "mark" }, svg);
      text(svg, labelW + w + 8, yTop + 16, format.short(v), { class: "direct-label" });
      const hit = el("rect", { x: 0, y: yTop - 2, width, height: row, fill: "transparent", tabindex: 0, class: "hit" }, svg);
      hit.setAttribute("aria-label", `${label(d)}: ${format.full(v)}`);
      const show = () => tip.show(labelW + w, yTop + 4, label(d), [{ value: format.full(v), label: format.unit, color }]);
      hit.addEventListener("pointerenter", show);
      hit.addEventListener("focus", show);
      hit.addEventListener("pointerleave", () => tip.hide());
      hit.addEventListener("blur", () => tip.hide());
    });
  }

  /* ---------------------------------------------------------------- table view twin */

  function table(host, headers, rows) {
    host.replaceChildren();
    const t = document.createElement("table");
    t.className = "chart-table";
    const head = t.createTHead().insertRow();
    headers.forEach((h) => { const th = document.createElement("th"); th.textContent = h; head.appendChild(th); });
    const body = t.createTBody();
    rows.forEach((r) => {
      const tr = body.insertRow();
      r.forEach((c) => { tr.insertCell().textContent = c; });
    });
    host.appendChild(t);
  }

  return { area, columns, hbars, table };
})();
