import { columns, lines, rows } from "./charts.js";

const PAGES = [
  ["index.html", "Overview"],
  ["patterns.html", "Patterns"],
  ["agencies.html", "Agencies"],
  ["negros.html", "Negros Occidental"],
  ["quality.html", "Data quality"],
  ["methods.html", "Methods"],
];

const TYPE_LABEL = {
  barangay: "Barangay",
  municipality: "Municipality",
  city: "City",
  province: "Province",
  national_or_other: "National agency or other",
};

const $ = (selector) => document.querySelector(selector);
const int = (value) => Math.round(value).toLocaleString("en-US");
const ratio = (value) => (value === null || value === undefined ? "n/a" : value.toFixed(2));
const pct = (value, digits = 0) => `${(value * 100).toFixed(digits)}%`;
const esc = (text) => String(text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

function peso(value, long = false) {
  const units = [[1e12, "trillion", "T"], [1e9, "billion", "B"], [1e6, "million", "M"], [1e3, "thousand", "K"]];
  for (const [size, word, letter] of units) {
    if (Math.abs(value) >= size) {
      const scaled = value / size;
      const text = scaled >= 100 ? scaled.toFixed(0) : scaled >= 10 ? scaled.toFixed(1) : scaled.toFixed(2);
      // Short form drops trailing zeros: ₱1M and ₱1.5M, not ₱1.00M.
      return long ? `₱${text} ${word}` : `₱${parseFloat(text)}${letter}`;
    }
  }
  return `₱${int(value)}`;
}

const cache = new Map();
function load(name) {
  if (!cache.has(name)) {
    cache.set(name, fetch(`data/${name}.json`).then((response) => {
      if (!response.ok) throw new Error(`data/${name}.json returned ${response.status}`);
      return response.json();
    }));
  }
  return cache.get(name);
}

function set(selector, text) {
  document.querySelectorAll(selector).forEach((node) => { node.textContent = text; });
}

function table(el, head, body) {
  const th = head.map((h) => `<th${h.n ? ' class="n"' : ""}>${h.label}</th>`).join("");
  const tr = body.map((cells) => `<tr>${cells.map((cell, i) => `<td${head[i].n ? ' class="n"' : ""}>${cell}</td>`).join("")}</tr>`).join("");
  el.innerHTML = `<div class="scroll"><table><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`;
}

function chrome(summary) {
  // Some hosts serve /patterns for patterns.html, so compare without the extension.
  const here = (location.pathname.split("/").pop() || "index").replace(/\.html$/, "");
  const active = here === "agency" ? "agencies" : here;
  const links = PAGES.map(([href, label]) => `<a href="${href}"${href === `${active}.html` ? ' aria-current="page"' : ""}>${label}</a>`).join("");
  $("#masthead").innerHTML = `<div class="wrap"><a class="brand" href="index.html">Procurement Watch</a><nav aria-label="Sections">${links}</nav></div>`;
  $("#footer").innerHTML = `<div class="wrap">
    <p>Every figure describes award records as published on PhilGEPS and republished by BetterGov.PH under CC0. A high value marks a pattern worth a closer look. It is not evidence of wrongdoing by any agency.</p>
    <p>Snapshot dated ${summary.snapshot_date}. ${int(summary.counts.staged_rows)} awards kept, ${int(summary.counts.quarantined_rows)} set aside. <a href="quality.html">See every check</a> and <a href="methods.html">how each figure is made</a>.</p></div>`;
}

const agencyLink = (row) => `<a href="agency.html?id=${row.agency_id}">${esc(row.agency_name)}</a>`;

// Overview ------------------------------------------------------------------

async function overview(summary) {
  const [bunching, cliff, yearly] = await Promise.all([load("bunching"), load("cliff"), load("yearly")]);
  const row = bunching.find((b) => b.award_year === cliff.year && b.round_amount === 1000000);
  set("[data-fill=year]", cliff.year);
  set("[data-fill=under]", int(row.awards_under));
  set("[data-fill=over]", int(row.awards_over));
  set("[data-fill=ratio]", ratio(row.ratio));
  set("[data-fill=placebo]", ratio(row.placebo_ratio));
  set("[data-fill=awards]", int(summary.counts.staged_rows));
  set("[data-fill=agencies]", int(summary.counts.agencies));
  set("[data-fill=quarantined]", int(summary.counts.quarantined_rows));
  set("[data-fill=checks]", summary.checks.filter((c) => c.severity === "error" && c.passed).length);
  set("[data-fill=span]", `${yearly[0].award_year} to ${yearly.at(-1).award_year}`);

  const peak = Math.max(...Object.values(cliff.amounts).flat().map((d) => d.awards));
  const drawCliff = (selector, amount, isCeiling) => {
    const data = cliff.amounts[amount].map((d) => ({
      ...d,
      y: d.awards,
      color: isCeiling ? "var(--series-1)" : "var(--neutral-mark)",
    }));
    const stepPeso = (step) => peso(amount * (1 + step / 100));
    columns($(selector), {
      data,
      height: 300,
      yMax: peak,
      label: `Awards in ${cliff.year} by contract amount, around ${peso(amount)}`,
      yFormat: int,
      xTick: (d) => ((d.step + 20) % 10 === 0 ? stepPeso(d.step) : ""),
      tip: (d) => `Over ${stepPeso(d.step)} up to ${stepPeso(d.step + 1)}<br><b>${int(d.awards)}</b> awards`,
      ...(isCeiling
        ? { ceilingAfter: 19, ceilingLabel: `Ceiling ${peso(amount)}` }
        : { refAfter: 19, refLabel: `${peso(amount)}, no rule` }),
      table: {
        columns: ["Amount up to", "Awards"],
        rows: cliff.amounts[amount].map((d) => [stepPeso(d.step + 1), int(d.awards)]),
      },
    });
  };
  drawCliff("#cliff-ceiling", 1000000, true);
  drawCliff("#cliff-placebo", 1500000, false);
  const last = (amount) => cliff.amounts[amount][19].awards;
  const next = (amount) => cliff.amounts[amount][20].awards;
  set("[data-fill=last-ceiling]", int(last(1000000)));
  set("[data-fill=next-ceiling]", int(next(1000000)));
  set("[data-fill=last-placebo]", int(last(1500000)));
  set("[data-fill=next-placebo]", int(next(1500000)));

  const years = yearly.filter((y) => y.award_year >= 2008);
  columns($("#yearly-awards"), {
    data: years.map((y) => ({ ...y, x: y.award_year, y: y.awards })),
    label: "Awards published per year",
    yFormat: (v) => (v >= 1000 ? `${v / 1000}K` : v),
    xTick: (d) => (d.award_year % 2 === 0 ? d.award_year : ""),
    tip: (d) => `${d.award_year}<br><b>${int(d.awards)}</b> awards<br><b>${peso(d.total_value, true)}</b>`,
    table: {
      columns: ["Year", "Awards", "Value", "Agencies"],
      rows: years.map((y) => [y.award_year, int(y.awards), peso(y.total_value), int(y.agencies)]),
    },
  });
  columns($("#yearly-value"), {
    data: years.map((y) => ({ ...y, x: y.award_year, y: y.total_value / 1e9 })),
    label: "Value awarded per year, in billions of pesos",
    yFormat: (v) => (v >= 1000 ? `₱${v / 1000}T` : `₱${v}B`),
    xTick: (d) => (d.award_year % 2 === 0 ? d.award_year : ""),
    tip: (d) => `${d.award_year}<br><b>${peso(d.total_value, true)}</b>`,
  });
}

// Patterns ------------------------------------------------------------------

const KIND = {
  threshold: { color: "var(--series-1)", name: "A ceiling on simplified procurement" },
  other_rule: { color: "var(--series-2)", name: "A different rule sits here" },
  placebo: { color: "var(--neutral-mark)", name: "No rule: an ordinary round amount" },
};

async function patterns() {
  const [bunching, rule, sameDay, concentration, ranking, byType] = await Promise.all(
    ["bunching", "rule_change", "same_day", "concentration", "patterns", "bunching_by_type"].map(load),
  );

  const years = [...new Set(bunching.map((b) => b.award_year))].filter((y) => y >= 2010);
  const yearSelect = $("#bunching-year");
  yearSelect.innerHTML = years.map((y) => `<option${y === 2024 ? " selected" : ""}>${y}</option>`).join("");
  const drawAmounts = () => {
    const year = Number(yearSelect.value);
    const data = bunching.filter((b) => b.award_year === year && b.ratio !== null);
    const host = $("#bunching-amounts");
    const fresh = host.cloneNode(false);
    host.replaceWith(fresh);
    rows(fresh, {
      data: data.map((b) => ({ ...b, label: peso(b.round_amount), value: b.ratio, color: KIND[b.amount_kind].color })),
      label: `Awards just under each amount for every award just over it, ${year}`,
      legend: Object.values(KIND),
      valueFormat: ratio,
      ref: { value: data[0].placebo_ratio, label: `Typical with no rule: ${ratio(data[0].placebo_ratio)}` },
      tip: (b) => `${peso(b.round_amount)}<br><b>${int(b.awards_under)}</b> just under, <b>${int(b.awards_over)}</b> just over<br>${ratio(b.excess)} times the no-rule level`,
      table: {
        columns: ["Amount", "Just under", "Just over", "Ratio", "Times the no-rule level"],
        rows: data.map((b) => [peso(b.round_amount), int(b.awards_under), int(b.awards_over), ratio(b.ratio), ratio(b.excess)]),
      },
    });
  };
  yearSelect.addEventListener("change", drawAmounts);
  drawAmounts();

  const million = bunching.filter((b) => b.round_amount === 1000000 && b.award_year >= 2010);
  lines($("#bunching-trend"), {
    x: million.map((b) => b.award_year),
    xTickEvery: 2,
    series: [{ name: "₱1,000,000", color: "var(--series-1)", values: million.map((b) => b.excess) }],
    label: "Bunching under one million pesos as a multiple of the no-rule level, by year",
    yFormat: (v) => `${v}×`,
    hline: { value: 1, label: "Same as an amount with no rule" },
    tip: (i) => `${million[i].award_year}<br><b>${ratio(million[i].excess)}</b> times the no-rule level<br>${int(million[i].awards_under)} under, ${int(million[i].awards_over)} over`,
    table: {
      columns: ["Year", "Just under", "Just over", "Ratio", "Times the no-rule level"],
      rows: million.map((b) => [b.award_year, int(b.awards_under), int(b.awards_over), ratio(b.ratio), ratio(b.excess)]),
    },
  });

  const latestTypes = byType.filter((t) => t.award_year === 2024 && t.awards_over > 0);
  table($("#bunching-types"), [{ label: "Kind of agency" }, { label: "Just under", n: 1 }, { label: "Just over", n: 1 }, { label: "Ratio", n: 1 }],
    latestTypes.sort((a, b) => b.awards_under - a.awards_under).map((t) => [TYPE_LABEL[t.agency_type], int(t.awards_under), int(t.awards_over), ratio(t.awards_under / t.awards_over)]));

  const months = rule.monthly.filter((m) => m.award_month >= "2024-01" && m.over_2m >= 20);
  const monthLabel = (m) => new Date(`${m.award_month}T00:00:00`).toLocaleString("en-US", { month: "short", year: "2-digit" });
  lines($("#rule-monthly"), {
    x: months.map(monthLabel),
    xTickEvery: 3,
    series: [
      { name: "Around ₱1,000,000", color: "var(--series-1)", values: months.map((m) => m.under_1m / m.over_1m) },
      { name: "Around ₱2,000,000", color: "var(--series-2)", values: months.map((m) => m.under_2m / m.over_2m) },
    ],
    label: "Monthly ratio of awards just under to just over one and two million pesos",
    yFormat: ratio,
    vline: { index: months.findIndex((m) => m.award_month.startsWith("2025-03")) - 0.2, label: "Ceiling moves to ₱2,000,000", shortLabel: "New ceiling", ceiling: true },
    tip: (i) => `${monthLabel(months[i])}<br>₱1M: <b>${ratio(months[i].under_1m / months[i].over_1m)}</b> (${int(months[i].under_1m)} / ${int(months[i].over_1m)})<br>₱2M: <b>${ratio(months[i].under_2m / months[i].over_2m)}</b> (${int(months[i].under_2m)} / ${int(months[i].over_2m)})`,
    table: {
      columns: ["Month", "Awards", "₱1M under", "₱1M over", "₱2M under", "₱2M over"],
      rows: months.map((m) => [monthLabel(m), int(m.awards), int(m.under_1m), int(m.over_1m), int(m.under_2m), int(m.over_2m)]),
    },
  });
  table($("#rule-summary"), [{ label: "March to August" }, { label: "Awards", n: 1 }, { label: "Ratio at ₱1,000,000", n: 1 }, { label: "Ratio at ₱2,000,000", n: 1 }],
    rule.summary.map((s) => [s.award_year, int(s.awards), ratio(s.ratio_1m), ratio(s.ratio_2m)]));

  columns($("#same-day"), {
    data: sameDay.map((s) => ({ ...s, x: s.award_year, y: s.groups })),
    label: "Same-day groups per year",
    yFormat: int,
    tip: (s) => `${s.award_year}<br><b>${int(s.groups)}</b> groups at <b>${int(s.agencies)}</b> agencies<br>${int(s.notices)} notices worth ${peso(s.total_value, true)}`,
    table: {
      columns: ["Year", "Groups", "Notices", "Value", "Agencies"],
      rows: sameDay.map((s) => [s.award_year, int(s.groups), int(s.notices), peso(s.total_value), int(s.agencies)]),
    },
  });

  const conc = concentration.filter((c) => c.award_year >= 2010);
  lines($("#concentration"), {
    x: conc.map((c) => c.award_year),
    xTickEvery: 2,
    series: [{ name: "Median agency", color: "var(--series-1)", values: conc.map((c) => c.median * 100) }],
    band: { lo: conc.map((c) => c.p25 * 100), hi: conc.map((c) => c.p75 * 100), color: "var(--series-1)" },
    label: "Share of an agency's yearly spend that went to its largest supplier",
    yFormat: (v) => `${v}%`,
    tip: (i) => `${conc[i].award_year}<br>Median <b>${pct(conc[i].median)}</b><br>Middle half of agencies: ${pct(conc[i].p25)} to ${pct(conc[i].p75)}<br>${int(conc[i].above_half)} of ${int(conc[i].agencies)} above half`,
    table: {
      columns: ["Year", "Agencies", "Lower quarter", "Median", "Upper quarter", "Above half"],
      rows: conc.map((c) => [c.award_year, int(c.agencies), pct(c.p25), pct(c.median), pct(c.p75), int(c.above_half)]),
    },
  });

  const RANK = {
    bunching_1m: {
      head: [{ label: "Agency" }, { label: "Kind" }, { label: "Just under ₱1M", n: 1 }, { label: "Just over", n: 1 }, { label: "All awards", n: 1 }],
      cells: (r) => [agencyLink(r), TYPE_LABEL[r.agency_type], int(r.under_1m), int(r.over_1m), int(r.awards)],
    },
    same_day: {
      head: [{ label: "Agency" }, { label: "Kind" }, { label: "Same-day groups", n: 1 }, { label: "Value in groups", n: 1 }, { label: "All awards", n: 1 }],
      cells: (r) => [agencyLink(r), TYPE_LABEL[r.agency_type], int(r.same_day_groups), peso(r.same_day_value), int(r.awards)],
    },
    concentration: {
      head: [{ label: "Agency" }, { label: "Kind" }, { label: "Largest supplier's share", n: 1 }, { label: "Suppliers", n: 1 }, { label: "All awards", n: 1 }],
      cells: (r) => [agencyLink(r), TYPE_LABEL[r.agency_type], pct(r.top_supplier_share, 1), int(r.suppliers), int(r.awards)],
    },
  };
  const rankYears = Object.keys(ranking).sort();
  const rankYear = $("#rank-year");
  rankYear.innerHTML = rankYears.map((y) => `<option${y === "2024" ? " selected" : ""}>${y}</option>`).join("");
  let current = "bunching_1m";
  const drawRank = () => {
    const list = ranking[rankYear.value][current];
    if (!list.length) {
      $("#rank-table").innerHTML = `<p class="small">No agency has enough records for this pattern in ${rankYear.value}. Try another year.</p>`;
      return;
    }
    table($("#rank-table"), RANK[current].head, list.map(RANK[current].cells));
  };
  document.querySelectorAll("#rank-tabs button").forEach((button) => {
    button.addEventListener("click", () => {
      current = button.dataset.pattern;
      document.querySelectorAll("#rank-tabs button").forEach((b) => b.setAttribute("aria-selected", b === button));
      drawRank();
    });
  });
  rankYear.addEventListener("change", drawRank);
  drawRank();
}

// Agencies ------------------------------------------------------------------

function unpack(columnar) {
  const keys = Object.keys(columnar);
  return columnar[keys[0]].map((_, i) => Object.fromEntries(keys.map((key) => [key, columnar[key][i]])));
}

async function agencies() {
  const list = unpack(await load("agencies"));
  const search = $("#agency-search");
  const type = $("#agency-type");
  type.innerHTML = `<option value="">All kinds</option>${Object.entries(TYPE_LABEL).map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}`;
  const draw = () => {
    const words = search.value.trim().toUpperCase().split(/\s+/).filter(Boolean);
    const found = list.filter((a) => (!type.value || a.agency_type === type.value) && words.every((w) => a.agency_name.toUpperCase().includes(w)));
    $("#agency-count").textContent = found.length > 200 ? `Showing the 200 largest of ${int(found.length)} agencies.` : `${int(found.length)} ${found.length === 1 ? "agency" : "agencies"}.`;
    if (!found.length) {
      $("#agency-table").innerHTML = `<p class="small">No agency matches. Agencies with fewer than 100 awards are not listed.</p>`;
      return;
    }
    table($("#agency-table"), [{ label: "Agency" }, { label: "Kind" }, { label: "Main delivery area" }, { label: "Awards", n: 1 }, { label: "Value", n: 1 }, { label: "Years", n: 1 }],
      found.slice(0, 200).map((a) => [agencyLink(a), TYPE_LABEL[a.agency_type], a.main_area || "Not stated", int(a.awards), peso(a.total_value), `${a.first_year} to ${a.last_year}`]));
  };
  search.addEventListener("input", draw);
  type.addEventListener("change", draw);
  draw();
}

async function agency() {
  const id = new URLSearchParams(location.search).get("id");
  const [list, yearsColumnar] = await Promise.all([load("agencies"), load("agency_years")]);
  const info = unpack(list).find((a) => a.agency_id === id);
  if (!info) {
    $("#agency-body").innerHTML = `<p>No agency with that id is listed. <a href="agencies.html">Search the agencies</a>.</p>`;
    return;
  }
  const years = unpack(yearsColumnar).filter((y) => y.agency_id === id);
  document.title = `${info.agency_name} · Procurement Watch`;
  set("[data-fill=name]", info.agency_name);
  set("[data-fill=kind]", `${TYPE_LABEL[info.agency_type]}${info.main_area ? `. Delivers mainly to ${info.main_area}.` : "."}`);
  set("[data-fill=awards]", int(info.awards));
  set("[data-fill=value]", peso(info.total_value, true));
  set("[data-fill=years]", `${info.first_year} to ${info.last_year}`);
  set("[data-fill=groups]", int(years.reduce((sum, y) => sum + y.same_day_groups, 0)));

  columns($("#agency-awards"), {
    data: years.map((y) => ({ ...y, x: y.award_year, y: y.awards })),
    label: "Awards per year",
    yFormat: int,
    xTick: (d) => (years.length > 12 && d.award_year % 2 ? "" : d.award_year),
    tip: (y) => `${y.award_year}<br><b>${int(y.awards)}</b> awards worth <b>${peso(y.total_value, true)}</b>`,
  });
  lines($("#agency-share"), {
    x: years.map((y) => y.award_year),
    xTickEvery: years.length > 12 ? 2 : 1,
    series: [{ name: "Largest supplier's share", color: "var(--series-1)", values: years.map((y) => (y.awards >= 30 ? y.top_supplier_share * 100 : null)) }],
    label: "Largest supplier's share of yearly spend",
    yFormat: (v) => `${v}%`,
    tip: (i) => `${years[i].award_year}<br>${years[i].awards >= 30 ? `<b>${pct(years[i].top_supplier_share, 1)}</b> across ${int(years[i].suppliers)} suppliers` : "Fewer than 30 awards, not shown"}`,
  });
  table($("#agency-years"),
    [{ label: "Year" }, { label: "Awards", n: 1 }, { label: "Value", n: 1 }, { label: "Suppliers", n: 1 }, { label: "Largest supplier's share", n: 1 }, { label: "Just under ₱1M", n: 1 }, { label: "Just over", n: 1 }, { label: "Same-day groups", n: 1 }],
    years.slice().reverse().map((y) => [y.award_year, int(y.awards), peso(y.total_value), int(y.suppliers), y.awards >= 30 ? pct(y.top_supplier_share, 1) : "too few", int(y.under_1m), int(y.over_1m), int(y.same_day_groups)]));
}

// Negros Occidental ---------------------------------------------------------

async function negros() {
  const [focus, listed] = await Promise.all([load("focus_area"), load("agencies")]);
  const known = new Set(listed.agency_id);
  const years = focus.yearly.filter((y) => y.award_year >= 2010);
  const latest = years.find((y) => y.award_year === 2024) || years.at(-1);
  set("[data-fill=latest-year]", latest.award_year);
  set("[data-fill=latest-awards]", int(latest.awards));
  set("[data-fill=latest-value]", peso(latest.total_value, true));
  set("[data-fill=all-awards]", int(focus.yearly.reduce((sum, y) => sum + y.awards, 0)));
  set("[data-fill=all-value]", peso(focus.yearly.reduce((sum, y) => sum + y.total_value, 0), true));
  columns($("#negros-value"), {
    data: years.map((y) => ({ ...y, x: y.award_year, y: y.total_value / 1e9 })),
    label: "Value of awards delivered to Negros Occidental per year, in billions of pesos",
    yFormat: (v) => `₱${v}B`,
    xTick: (d) => (d.award_year % 2 === 0 ? d.award_year : ""),
    tip: (y) => `${y.award_year}<br><b>${peso(y.total_value, true)}</b> across <b>${int(y.awards)}</b> awards`,
    table: { columns: ["Year", "Awards", "Value"], rows: years.map((y) => [y.award_year, int(y.awards), peso(y.total_value)]) },
  });
  rows($("#negros-types"), {
    data: focus.by_type.map((t) => ({ ...t, label: TYPE_LABEL[t.agency_type].replace(" or other", ""), value: t.total_value / 1e9 })),
    label: "Value by kind of agency, all years",
    valueFormat: (v) => `₱${v.toFixed(1)}B`,
    tip: (t) => `${TYPE_LABEL[t.agency_type]}<br><b>${peso(t.total_value, true)}</b> across <b>${int(t.awards)}</b> awards`,
  });
  table($("#negros-agencies"), [{ label: "Agency" }, { label: "Kind" }, { label: "Awards", n: 1 }, { label: "Value", n: 1 }],
    focus.agencies.slice(0, 30).map((a) => [known.has(a.agency_id) ? agencyLink(a) : esc(a.agency_name), TYPE_LABEL[a.agency_type], int(a.awards), peso(a.total_value)]));
}

// Data quality --------------------------------------------------------------

const RULE_LABEL = {
  exact_duplicate: "Identical to another record in every column",
  amount_below_one_peso: "Contract amount below one peso",
  award_date_before_2006: "Award dated before 2006",
  amount_above_10bn_unreviewed: "Above ten billion pesos and not yet verified against another source",
  award_date_after_snapshot: "Award dated after the snapshot was taken",
  missing_award_date: "No award date",
  empty_name_after_normalisation: "Agency or supplier name empty after cleaning",
};

async function quality(summary) {
  const counts = summary.counts;
  const blocking = summary.checks.filter((c) => c.severity === "error");
  set("[data-fill=passed]", `${blocking.filter((c) => c.passed).length} of ${blocking.length}`);
  set("[data-fill=raw]", int(counts.raw_rows));
  set("[data-fill=staged]", int(counts.staged_rows));
  set("[data-fill=quarantined]", int(counts.quarantined_rows));
  set("[data-fill=verdict]", summary.publishable ? "Every blocking check passed, so this build was published." : "A blocking check failed.");
  const status = (c) => (c.passed ? `<span class="status pass">✓ PASS</span>` : c.severity === "warn" ? `<span class="status warn">! WARNING</span>` : `<span class="status fail">✕ FAIL</span>`);
  table($("#checks"), [{ label: "Result" }, { label: "What is checked" }, { label: "Blocks publishing" }, { label: "Violations", n: 1 }],
    summary.checks.map((c) => [status(c), esc(c.description), c.severity === "error" ? "Yes" : "No", int(c.violations)]));
  table($("#quarantine"), [{ label: "Reason a record was set aside" }, { label: "Records", n: 1 }],
    Object.entries(counts.quarantine_by_rule).map(([rule, n]) => [RULE_LABEL[rule] || rule, int(n)]));

  const dups = summary.duplicates_by_year.filter((d) => d.award_year >= 2006 && d.award_year <= Number(summary.snapshot_date.slice(0, 4)) && d.raw_value > 0);
  columns($("#duplicates"), {
    data: dups.map((d) => ({ ...d, x: d.award_year, y: (d.duplicate_value / d.raw_value) * 100 })),
    label: "Share of each year's raw value that was duplicate records",
    yFormat: (v) => `${v}%`,
    xTick: (d) => (d.award_year % 2 === 0 ? d.award_year : ""),
    tip: (d) => `${d.award_year}<br><b>${pct(d.duplicate_value / d.raw_value, 1)}</b> of raw value<br>${int(d.duplicate_rows)} of ${int(d.raw_rows)} records`,
    table: { columns: ["Year", "Raw records", "Duplicates", "Share of value"], rows: dups.map((d) => [d.award_year, int(d.raw_rows), int(d.duplicate_rows), pct(d.duplicate_value / d.raw_value, 1)]) },
  });

  set("[data-fill=agency-raw]", int(counts.agency_names_raw));
  set("[data-fill=agency-keys]", int(counts.agencies));
  set("[data-fill=supplier-raw]", int(counts.supplier_names_raw));
  set("[data-fill=supplier-entities]", int(counts.suppliers));
  if (summary.matching) {
    const m = summary.matching;
    set("[data-fill=pairs]", int(m.usable_pairs));
    set("[data-fill=unsure]", int(m.unsure_pairs));
    const names = { 1: "Punctuation, initials and legal-form abbreviations", 2: "Plus a branch folded into its parent company", 3: "Plus the legal form dropped" };
    table($("#matching"), [{ label: "Rules applied" }, { label: "Correct merges", n: 1 }, { label: "Wrong merges", n: 1 }, { label: "Missed", n: 1 }, { label: "Recall", n: 1 }],
      Object.entries(m.levels).map(([level, r]) => [`${names[level]}${Number(level) === m.level_in_use ? " (in use)" : ""}`, int(r.true_positives), int(r.false_positives), int(r.false_negatives), pct(r.recall)]));
  }
}

// Methods -------------------------------------------------------------------

async function methods(summary) {
  set("[data-fill=band]", pct(summary.settings.band_width));
  set("[data-fill=min-band]", summary.settings.min_band_awards);
  set("[data-fill=min-year]", summary.settings.min_agency_year_awards);
  set("[data-fill=min-notices]", summary.settings.same_day_min_notices);
  set("[data-fill=min-listed]", summary.settings.min_agency_awards_listed);
  set("[data-fill=snapshot]", summary.snapshot_date);
  table($("#amounts"), [{ label: "Amount" }, { label: "Treated as" }, { label: "Why" }],
    summary.amounts.map((a) => [peso(a.round_amount), { threshold: "Ceiling", other_rule: "Other rule", placebo: "No rule" }[a.amount_kind], esc(a.note || "Round amount with no rule found")]));
  table($("#thresholds"), [{ label: "Ceiling" }, { label: "Amount", n: 1 }, { label: "From" }, { label: "Until" }, { label: "Basis" }],
    summary.thresholds.map((t) => [t.threshold.replaceAll("_", " "), peso(t.amount), t.effective_from, t.effective_to || "in force", `<a href="${t.source}">${esc(t.legal_basis)}</a>`]));
}

// ---------------------------------------------------------------------------

const ROUTES = { overview, patterns, agencies, agency, negros, quality, methods };

load("summary")
  .then(async (summary) => {
    chrome(summary);
    await ROUTES[document.body.dataset.page](summary);
    document.querySelectorAll(".loading").forEach((node) => node.remove());
  })
  .catch((error) => {
    console.error(error);
    $("main").insertAdjacentHTML("afterbegin", `<div class="wrap"><p class="caveat">The data for this page did not load (${esc(error.message)}). Reload the page to try again.</p></div>`);
  });
