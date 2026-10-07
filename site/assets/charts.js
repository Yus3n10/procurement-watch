// Small SVG charts: columns, rows and lines. Each chart redraws at its
// container's real width, carries a hover tooltip, and offers a table view.

const NS = "http://www.w3.org/2000/svg";

function svg(tag, attrs = {}, text) {
  const node = document.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
}

function html(tag, attrs = {}, content) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (content !== undefined) node.innerHTML = content;
  return node;
}

let tipNode;
function showTip(event, content) {
  if (!tipNode) {
    tipNode = html("div", { class: "tip", role: "status" });
    document.body.append(tipNode);
  }
  tipNode.innerHTML = content;
  tipNode.classList.add("on");
  const box = tipNode.getBoundingClientRect();
  const x = Math.min(event.clientX + 14, window.innerWidth - box.width - 8);
  const y = event.clientY - box.height - 12 < 8 ? event.clientY + 18 : event.clientY - box.height - 12;
  tipNode.style.left = `${Math.max(8, x)}px`;
  tipNode.style.top = `${y}px`;
}
function hideTip() {
  if (tipNode) tipNode.classList.remove("on");
}

function ticks(max, count = 4) {
  if (!(max > 0)) return [0, 1];
  const rough = max / count;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= rough);
  const out = [];
  for (let value = 0; value < max + step * 0.999; value += step) out.push(Number(value.toPrecision(12)));
  return out;
}

// Draw x labels left to right, skipping any that would touch the one before.
function xLabels(root, labels, y) {
  let edge = -Infinity;
  for (const { x, text, anchor } of labels) {
    const width = String(text).length * 6.6;
    const start = anchor === "start" ? x : anchor === "end" ? x - width : x - width / 2;
    if (start < edge + 8) continue;
    root.append(svg("text", { x, y, "text-anchor": anchor }, text));
    edge = start + width;
  }
}

function tableView(spec) {
  const details = html("details", { class: "table-view" });
  details.append(html("summary", {}, "Show as table"));
  const head = spec.columns.map((c, i) => `<th${i ? ' class="n"' : ""}>${c}</th>`).join("");
  const body = spec.rows
    .map((row) => `<tr>${row.map((cell, i) => `<td${i ? ' class="n"' : ""}>${cell}</td>`).join("")}</tr>`)
    .join("");
  details.append(html("div", { class: "scroll" }, `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`));
  return details;
}

function legend(items) {
  const list = html("ul", { class: "legend" });
  for (const item of items) {
    list.append(html("li", {}, `<i class="${item.line ? "line" : ""}" style="background:${item.color}"></i>${item.name}`));
  }
  return list;
}

function mount(el, opts, draw) {
  el.classList.add("chart");
  const render = () => {
    el.replaceChildren();
    if (opts.legend) el.append(legend(opts.legend));
    const width = Math.max(280, el.clientWidth);
    const root = svg("svg", { viewBox: `0 0 ${width} ${opts.height}`, role: "img", "aria-label": opts.label || "" });
    el.append(root);
    draw(root, width);
    if (opts.table) el.append(tableView(opts.table));
  };
  // Draw once straight away, then again whenever the container changes width.
  let last = el.clientWidth;
  render();
  new ResizeObserver(() => {
    if (Math.abs(el.clientWidth - last) > 4) {
      last = el.clientWidth;
      render();
    }
  }).observe(el);
}

function yAxis(root, { left, right, top, bottom, max, format }) {
  const scale = (value) => bottom - (value / max) * (bottom - top);
  for (const tick of ticks(max)) {
    if (tick > max * 1.001) continue;
    const y = scale(tick);
    root.append(svg("line", { class: tick ? "grid-line" : "axis-line", x1: left, x2: right, y1: y, y2: y }));
    root.append(svg("text", { x: left - 6, y: y + 4, "text-anchor": "end" }, format(tick)));
  }
  return scale;
}

// Vertical bars. opts.data: [{ x, y, color }]. opts.ceilingAfter draws the
// red ceiling line in the gap after that bar index.
export function columns(el, opts) {
  const options = { height: 260, yFormat: String, ...opts };
  mount(el, options, (root, width) => {
    const data = options.data;
    const left = 46, right = width - 8, top = options.ceilingLabel ? 30 : 12, bottom = options.height - 26;
    const max = ticks(options.yMax ?? Math.max(...data.map((d) => d.y))).at(-1);
    const scale = yAxis(root, { left, right, top, bottom, max, format: options.yFormat });
    const band = (right - left) / data.length;
    const gap = band > 12 ? 2 : 1;
    const labels = [];
    data.forEach((d, i) => {
      const x = left + i * band + gap / 2;
      const w = Math.max(1, band - gap);
      const y = scale(d.y);
      const r = Math.min(4, w / 2, Math.max(0, bottom - y));
      const path = `M${x},${bottom}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${bottom}Z`;
      const mark = svg("path", { class: "mark", d: path, fill: d.color || "var(--series-1)" });
      root.append(mark);
      const label = options.xTick ? options.xTick(d, i) : d.x;
      // The first label starts at its bar so it cannot run under the y axis.
      if (label) labels.push({ x: i ? x + w / 2 : x, text: label, anchor: i ? "middle" : "start" });
      const hit = svg("rect", { class: "hit", x: left + i * band, y: top, width: band, height: bottom - top });
      hit.addEventListener("mousemove", (event) => {
        root.querySelectorAll(".mark").forEach((m) => m.classList.toggle("dim", m !== mark));
        showTip(event, options.tip(d, i));
      });
      hit.addEventListener("mouseleave", () => {
        root.querySelectorAll(".mark").forEach((m) => m.classList.remove("dim"));
        hideTip();
      });
      root.append(hit);
    });
    xLabels(root, labels, bottom + 16);
    if (options.ceilingAfter !== undefined) {
      const x = left + (options.ceilingAfter + 1) * band;
      root.append(svg("line", { class: "ceiling-line", x1: x, x2: x, y1: top - 14, y2: bottom }));
      if (options.ceilingLabel) {
        root.append(svg("text", { class: "ceiling-label", x: x + 6, y: top - 6 }, options.ceilingLabel));
      }
    }
    if (options.refAfter !== undefined) {
      const x = left + (options.refAfter + 1) * band;
      root.append(svg("line", { class: "ref-line", x1: x, x2: x, y1: top - 14, y2: bottom }));
      root.append(svg("text", { class: "ref-label", x: x + 6, y: top - 6 }, options.refLabel || ""));
    }
  });
}

// Horizontal bars. opts.data: [{ label, value, color }]. opts.ref draws a
// dashed reference line at a value.
export function rows(el, opts) {
  const options = { rowHeight: 30, valueFormat: String, ...opts };
  options.height = options.data.length * options.rowHeight + 34;
  mount(el, options, (root, width) => {
    const data = options.data;
    const left = Math.min(150, width * 0.34), right = width - 56, top = 18;
    const max = ticks(Math.max(...data.map((d) => d.value), options.ref ? options.ref.value : 0)).at(-1);
    const scale = (value) => left + (value / max) * (right - left);
    root.append(svg("line", { class: "axis-line", x1: left, x2: left, y1: top - 4, y2: options.height - 12 }));
    data.forEach((d, i) => {
      const y = top + i * options.rowHeight;
      const h = options.rowHeight - 10;
      const w = Math.max(1, scale(d.value) - left);
      const r = Math.min(4, w, h / 2);
      const path = `M${left},${y}H${left + w - r}Q${left + w},${y} ${left + w},${y + r}V${y + h - r}Q${left + w},${y + h} ${left + w - r},${y + h}H${left}Z`;
      const mark = svg("path", { class: "mark", d: path, fill: d.color || "var(--series-1)" });
      root.append(mark);
      root.append(svg("text", { x: left - 8, y: y + h / 2 + 4, "text-anchor": "end" }, d.label));
      root.append(svg("text", { class: "direct-label", x: left + w + 6, y: y + h / 2 + 4 }, options.valueFormat(d.value)));
      const hit = svg("rect", { class: "hit", x: 0, y: y - 5, width, height: options.rowHeight });
      hit.addEventListener("mousemove", (event) => {
        root.querySelectorAll(".mark").forEach((m) => m.classList.toggle("dim", m !== mark));
        showTip(event, options.tip(d, i));
      });
      hit.addEventListener("mouseleave", () => {
        root.querySelectorAll(".mark").forEach((m) => m.classList.remove("dim"));
        hideTip();
      });
      root.append(hit);
    });
    if (options.ref) {
      const x = scale(options.ref.value);
      root.append(svg("line", { class: "ref-line", x1: x, x2: x, y1: top - 8, y2: options.height - 12 }));
      root.append(svg("text", { class: "ref-label", x: x + 5, y: options.height - 2 }, options.ref.label));
    }
  });
}

// Lines over an ordered x. opts.series: [{ name, color, values }] with null
// for gaps. opts.band shades between two value arrays. opts.vline marks an x.
export function lines(el, opts) {
  const options = { height: 260, yFormat: String, xTickEvery: 1, ...opts };
  if (options.series.length > 1 && !options.legend) {
    options.legend = options.series.map((s) => ({ name: s.name, color: s.color, line: true }));
  }
  mount(el, options, (root, width) => {
    const x = options.x;
    const left = 46, right = width - (options.directLabels ? 64 : 12), top = options.vline ? 30 : 12, bottom = options.height - 26;
    const all = options.series.flatMap((s) => s.values).concat(options.band ? options.band.hi : [], options.hline ? [options.hline.value] : []);
    const max = ticks(Math.max(...all.filter((v) => v !== null))).at(-1);
    const scale = yAxis(root, { left, right, top, bottom, max, format: options.yFormat });
    const px = (i) => (x.length === 1 ? (left + right) / 2 : left + (i / (x.length - 1)) * (right - left));
    const labels = [];
    x.forEach((label, i) => {
      if (i % options.xTickEvery !== 0) return;
      labels.push({ x: px(i), text: label, anchor: i === 0 ? "start" : i === x.length - 1 ? "end" : "middle" });
    });
    xLabels(root, labels, bottom + 16);
    if (options.band) {
      const upper = options.band.hi.map((v, i) => `${px(i)},${scale(v)}`);
      const lower = options.band.lo.map((v, i) => `${px(i)},${scale(v)}`).reverse();
      root.append(svg("polygon", { points: upper.concat(lower).join(" "), fill: options.band.color, opacity: 0.18 }));
    }
    if (options.hline) {
      const y = scale(options.hline.value);
      root.append(svg("line", { class: "ref-line", x1: left, x2: right, y1: y, y2: y }));
      root.append(svg("text", { class: "ref-label", x: left + 4, y: y - 5 }, options.hline.label));
    }
    if (options.vline) {
      const vx = px(options.vline.index);
      root.append(svg("line", { class: options.vline.ceiling ? "ceiling-line" : "ref-line", x1: vx, x2: vx, y1: top - 14, y2: bottom }));
      const anchor = vx > (left + right) / 2 ? "end" : "start";
      root.append(svg("text", { class: options.vline.ceiling ? "ceiling-label" : "ref-label", x: vx + (anchor === "end" ? -6 : 6), y: top - 6, "text-anchor": anchor }, width < 480 && options.vline.shortLabel ? options.vline.shortLabel : options.vline.label));
    }
    for (const series of options.series) {
      let path = "";
      let pen = false;
      series.values.forEach((value, i) => {
        if (value === null) { pen = false; return; }
        path += `${pen ? "L" : "M"}${px(i)},${scale(value)}`;
        pen = true;
      });
      root.append(svg("path", { d: path, fill: "none", stroke: series.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
      if (options.directLabels) {
        const lastIndex = series.values.findLastIndex((v) => v !== null);
        if (lastIndex >= 0) {
          root.append(svg("text", { class: "direct-label", x: px(lastIndex) + 8, y: scale(series.values[lastIndex]) + 4 }, series.short || series.name));
        }
      }
    }
    const cross = svg("line", { class: "crosshair", y1: top, y2: bottom, visibility: "hidden" });
    root.append(cross);
    const dots = options.series.map((series) => {
      const dot = svg("circle", { r: 4.5, fill: series.color, stroke: "var(--panel)", "stroke-width": 2, visibility: "hidden" });
      root.append(dot);
      return dot;
    });
    const hit = svg("rect", { class: "hit", x: left, y: top, width: right - left, height: bottom - top });
    hit.addEventListener("mousemove", (event) => {
      const box = root.getBoundingClientRect();
      const ratio = ((event.clientX - box.left) / box.width) * width;
      const i = Math.max(0, Math.min(x.length - 1, Math.round(((ratio - left) / (right - left)) * (x.length - 1))));
      cross.setAttribute("x1", px(i));
      cross.setAttribute("x2", px(i));
      cross.setAttribute("visibility", "visible");
      options.series.forEach((series, s) => {
        const value = series.values[i];
        dots[s].setAttribute("visibility", value === null ? "hidden" : "visible");
        if (value !== null) {
          dots[s].setAttribute("cx", px(i));
          dots[s].setAttribute("cy", scale(value));
        }
      });
      showTip(event, options.tip(i));
    });
    hit.addEventListener("mouseleave", () => {
      cross.setAttribute("visibility", "hidden");
      dots.forEach((dot) => dot.setAttribute("visibility", "hidden"));
      hideTip();
    });
    root.append(hit);
  });
}
