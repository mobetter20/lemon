/**
 * lemon dashboard — renders mock_data.json into SVG charts.
 *
 * Phase 3 will produce data.json with the same schema. To switch from mock to
 * real, change DATA_URL.
 */

const DATA_URL = "mock_data.json";

const CATEGORY_LABELS = {
  rate_limits:        { label: "rate / capacity", color: "var(--c-rate)" },
  regressions:        { label: "regression",      color: "var(--c-regress)" },
  refusals:           { label: "refusal",         color: "var(--c-refusal)" },
  code_failures:      { label: "code-specific",   color: "var(--c-code)" },
  reasoning_quality:  { label: "reasoning",       color: "var(--c-reason)" },
  tool_breakage:      { label: "tool / integration", color: "var(--c-tool)" },
};

const VALENCE_KEYS = {
  defection_per_1k:           { label: "defection rhetoric", color: "var(--c-defection)" },
  loyalty_per_1k:             { label: "loyalty rhetoric",   color: "var(--c-loyalty)" },
  conditional_loyalty_per_1k: { label: "conditional",        color: "var(--c-cond)" },
};

const SVG_NS = "http://www.w3.org/2000/svg";

let DATA = null;
let xMode = "wall";  // "wall" | "release"

/* ----------------------------------------------------------
   Boot
   ---------------------------------------------------------- */
async function boot() {
  try {
    const r = await fetch(DATA_URL);
    DATA = await r.json();
  } catch (e) {
    console.error("Failed to load data:", e);
    return;
  }
  renderMeta();
  renderAll();
  wireToggles();
}
document.addEventListener("DOMContentLoaded", boot);

function wireToggles() {
  document.querySelectorAll(".toggle").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".toggle").forEach(b => {
        b.classList.remove("active");
        b.setAttribute("aria-pressed", "false");
      });
      btn.classList.add("active");
      btn.setAttribute("aria-pressed", "true");
      xMode = btn.dataset.axis;
      renderAll();
    });
  });
}

/* ----------------------------------------------------------
   Meta line
   ---------------------------------------------------------- */
function renderMeta() {
  const totalRecords = (DATA.totals.claude.all_mentions || 0) + (DATA.totals.openai.all_mentions || 0);
  document.getElementById("meta-count").textContent = totalRecords.toLocaleString();
  document.getElementById("meta-updated").textContent = (DATA.generated_at || "").slice(0, 10);
  document.getElementById("meta-tax").textContent = DATA.taxonomy_version || "1.0";

  document.getElementById("totals-claude").textContent =
    `${DATA.totals.claude.all_mentions.toLocaleString()} mentions / ${DATA.totals.claude.complaints.toLocaleString()} complaints`;
  document.getElementById("totals-openai").textContent =
    `${DATA.totals.openai.all_mentions.toLocaleString()} mentions / ${DATA.totals.openai.complaints.toLocaleString()} complaints`;
}

/* ----------------------------------------------------------
   Render all charts
   ---------------------------------------------------------- */
function renderAll() {
  for (const family of ["claude", "openai"]) {
    renderTimeseries(`ts-${family}`, DATA.time_series[family], family);
    renderValence(`val-${family}`, DATA.valence_markers[family], family);
    renderBars(`bars-${family}`, DATA.time_series[family]);
  }
}

/* ----------------------------------------------------------
   SVG helpers
   ---------------------------------------------------------- */
function svgEl(host) {
  host.innerHTML = "";
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${host.clientWidth} ${host.clientHeight}`);
  svg.setAttribute("preserveAspectRatio", "none");
  host.appendChild(svg);
  return svg;
}

function append(parent, tag, attrs = {}, text) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  if (text != null) el.textContent = text;
  parent.appendChild(el);
  return el;
}

/* ----------------------------------------------------------
   Time series
   ---------------------------------------------------------- */
function renderTimeseries(hostId, series, family) {
  const host = document.getElementById(hostId);
  if (!host || !series) return;
  const W = host.clientWidth;
  const H = host.clientHeight;
  const padL = 36, padR = 12, padT = 10, padB = 38;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;

  const svg = svgEl(host);
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);

  // Determine x-axis: build sorted list of weeks (across all categories)
  const allWeeks = new Set();
  for (const cat of Object.keys(series)) {
    for (const pt of series[cat]) allWeeks.add(pt.week);
  }
  const weeks = [...allWeeks].sort();
  if (weeks.length === 0) return;

  // X-axis transformation depends on mode
  // For release mode, we'd recompute relative to nearest release; mocked for now
  const xOf = (w) => {
    const i = weeks.indexOf(w);
    return padL + (i / Math.max(weeks.length - 1, 1)) * innerW;
  };

  // Y range: peak across categories
  let yMax = 0;
  for (const cat of Object.keys(series)) {
    for (const pt of series[cat]) yMax = Math.max(yMax, pt.complaints_per_1k);
  }
  yMax = Math.ceil(yMax * 1.1);
  const yOf = (v) => padT + innerH - (v / Math.max(yMax, 1)) * innerH;

  // Y-axis
  const ax = append(svg, "g", { class: "axis" });
  for (let i = 0; i <= 4; i++) {
    const v = (yMax / 4) * i;
    const y = yOf(v);
    append(ax, "line", { x1: padL, x2: W - padR, y1: y, y2: y, opacity: 0.3 });
    append(ax, "text", { x: 4, y: y + 3 }, v.toFixed(0));
  }

  // Release event vertical lines (only for wall mode), labels rotated vertical
  if (xMode === "wall" && DATA.releases) {
    for (const rel of DATA.releases) {
      if (rel.model_family !== family) continue;
      const week = nearestWeek(rel.date, weeks);
      if (!week) continue;
      const x = xOf(week);
      append(svg, "line", {
        class: "release-line",
        x1: x, x2: x, y1: padT, y2: padT + innerH,
      });
      append(svg, "text", {
        class: "release-label",
        x: x, y: padT + 8,
        transform: `rotate(-90, ${x}, ${padT + 8})`,
        "text-anchor": "end",
      }, rel.label || rel.id);
    }
  }

  // X-axis labels (sample every Nth week), rotated, anchored above bottom edge
  const labelEvery = Math.max(1, Math.floor(weeks.length / 6));
  const labelY = H - padB + 14;
  for (let i = 0; i < weeks.length; i += labelEvery) {
    const x = xOf(weeks[i]);
    append(ax, "text", {
      x, y: labelY, "text-anchor": "end",
      transform: `rotate(-35, ${x}, ${labelY})`,
    }, weeks[i].replace(/-W/, "·w"));
  }

  // Lines per category
  for (const [catId, info] of Object.entries(CATEGORY_LABELS)) {
    const points = series[catId] || [];
    if (points.length < 2) continue;
    const dParts = points.map((pt, i) => {
      const x = xOf(pt.week).toFixed(2);
      const y = yOf(pt.complaints_per_1k).toFixed(2);
      return `${i === 0 ? "M" : "L"} ${x} ${y}`;
    });
    append(svg, "path", {
      d: dParts.join(" "),
      fill: "none",
      stroke: info.color,
      "stroke-width": "1.5",
    });
  }
}

/* ----------------------------------------------------------
   Valence (rhetoric markers) — three light lines
   ---------------------------------------------------------- */
function renderValence(hostId, valence, family) {
  const host = document.getElementById(hostId);
  if (!host || !valence) return;
  const W = host.clientWidth;
  const H = host.clientHeight;
  const padL = 36, padR = 12, padT = 8, padB = 18;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;

  const svg = svgEl(host);
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);

  // Build x-axis weeks
  const allWeeks = new Set();
  for (const k of Object.keys(VALENCE_KEYS)) {
    for (const pt of (valence[k] || [])) allWeeks.add(pt.week);
  }
  const weeks = [...allWeeks].sort();
  if (weeks.length === 0) return;
  const xOf = (w) => padL + (weeks.indexOf(w) / Math.max(weeks.length - 1, 1)) * innerW;

  let yMax = 0;
  for (const k of Object.keys(VALENCE_KEYS)) {
    for (const pt of (valence[k] || [])) yMax = Math.max(yMax, pt.value);
  }
  yMax = Math.ceil(yMax * 1.1);
  const yOf = (v) => padT + innerH - (v / Math.max(yMax, 1)) * innerH;

  // Y axis (light)
  const ax = append(svg, "g", { class: "axis" });
  for (let i = 0; i <= 2; i++) {
    const v = (yMax / 2) * i;
    const y = yOf(v);
    append(ax, "line", { x1: padL, x2: W - padR, y1: y, y2: y, opacity: 0.2 });
    append(ax, "text", { x: 4, y: y + 3 }, v.toFixed(0));
  }

  // Lines per valence type
  for (const [k, info] of Object.entries(VALENCE_KEYS)) {
    const pts = valence[k] || [];
    if (pts.length < 2) continue;
    const dParts = pts.map((pt, i) => {
      const x = xOf(pt.week).toFixed(2);
      const y = yOf(pt.value).toFixed(2);
      return `${i === 0 ? "M" : "L"} ${x} ${y}`;
    });
    append(svg, "path", {
      d: dParts.join(" "),
      fill: "none",
      stroke: info.color,
      "stroke-width": "1.2",
      "stroke-dasharray": k === "conditional_loyalty_per_1k" ? "3 2" : null,
    });
  }

  // Inline legend
  const legY = H - 4;
  let legX = padL;
  for (const [k, info] of Object.entries(VALENCE_KEYS)) {
    append(svg, "rect", { x: legX, y: legY - 8, width: 8, height: 2, fill: info.color });
    append(svg, "text", { x: legX + 12, y: legY - 1, fill: "var(--fg-mute)", "font-size": "10" }, info.label);
    legX += 130;
  }
}

/* ----------------------------------------------------------
   This-week bars (most recent week's value, per category)
   ---------------------------------------------------------- */
function renderBars(hostId, series) {
  const host = document.getElementById(hostId);
  if (!host || !series) return;
  const W = host.clientWidth;
  const H = host.clientHeight;
  const padL = 140, padR = 36, padT = 6, padB = 6;
  const innerW = W - padL - padR;

  const svg = svgEl(host);
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);

  const cats = Object.keys(CATEGORY_LABELS);
  const rowH = (H - padT - padB) / cats.length;

  // Latest value per category
  const latest = {};
  let max = 0;
  for (const cat of cats) {
    const pts = series[cat] || [];
    const last = pts[pts.length - 1];
    latest[cat] = last ? last.complaints_per_1k : 0;
    max = Math.max(max, latest[cat]);
  }
  max = Math.ceil(max * 1.2);

  cats.forEach((cat, i) => {
    const y = padT + i * rowH;
    const barH = rowH * 0.55;
    const v = latest[cat];
    const w = (v / Math.max(max, 1)) * innerW;
    const info = CATEGORY_LABELS[cat];

    append(svg, "text", {
      x: padL - 8, y: y + rowH / 2 + 3, "text-anchor": "end",
      fill: "var(--fg-dim)", "font-size": "11",
    }, info.label);

    append(svg, "rect", {
      x: padL, y: y + (rowH - barH) / 2,
      width: w, height: barH,
      fill: info.color,
      rx: 2,
    });

    append(svg, "text", {
      x: padL + w + 6, y: y + rowH / 2 + 3,
      fill: "var(--fg)", "font-size": "11",
    }, v.toFixed(1));
  });
}

/* ----------------------------------------------------------
   Helpers
   ---------------------------------------------------------- */
function nearestWeek(dateStr, weeks) {
  // Convert YYYY-MM-DD to nearest YYYY-Www
  if (!dateStr) return null;
  const d = new Date(dateStr);
  if (isNaN(d)) return null;
  const target = `${d.getUTCFullYear()}-W${String(getISOWeek(d)).padStart(2, "0")}`;
  // Find exact or closest
  if (weeks.includes(target)) return target;
  const targetMs = d.getTime();
  let best = null, bestDelta = Infinity;
  for (const w of weeks) {
    const m = w.match(/^(\d{4})-W(\d{2})$/);
    if (!m) continue;
    const wd = isoWeekToDate(parseInt(m[1]), parseInt(m[2]));
    const delta = Math.abs(wd.getTime() - targetMs);
    if (delta < bestDelta) { bestDelta = delta; best = w; }
  }
  return best;
}

function getISOWeek(d) {
  const date = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  date.setUTCDate(date.getUTCDate() + 4 - (date.getUTCDay() || 7));
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
  return Math.ceil((((date - yearStart) / 86400000) + 1) / 7);
}

function isoWeekToDate(year, week) {
  const d = new Date(Date.UTC(year, 0, 1 + (week - 1) * 7));
  d.setUTCDate(d.getUTCDate() - (d.getUTCDay() || 7) + 4);
  return d;
}
