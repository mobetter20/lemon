/**
 * lemon dashboard (v0) — single complaint-rate per model, weekly, with trend.
 *
 * Reads mock_data.json today; will read data.json once Phase 3 ships the
 * v0 classifier output. Same schema either way.
 */

const SVG_NS = "http://www.w3.org/2000/svg";

let DATA = null;
let xMode = "wall";  // "wall" | "release"

/* ----------------------------------------------------------
   Data loading: prefer real data.json, fall back to mock.
   The standalone build script defines EMBEDDED_DATA before this script,
   in which case we use it directly (no fetch).
   ---------------------------------------------------------- */
async function loadData() {
  if (typeof EMBEDDED_DATA !== "undefined") return EMBEDDED_DATA;
  for (const url of ["data.json", "mock_data.json"]) {
    try {
      const r = await fetch(url);
      if (r.ok) return await r.json();
    } catch (e) { /* try next */ }
  }
  return null;
}

async function boot() {
  DATA = await loadData();
  if (!DATA) {
    showEmptyState();
    return;
  }
  renderMeta();
  renderAll();
  wireToggles();
}

function showEmptyState() {
  const meta = document.getElementById("meta-count");
  if (meta) meta.textContent = "(awaiting classifier output)";

  const hint = "Run scripts/v0_classify.py to populate phase5/data.json.";
  for (const family of ["claude", "openai"]) {
    const rate = document.getElementById(`rate-${family}`);
    if (rate) rate.textContent = "—";
    const totals = document.getElementById(`totals-${family}`);
    if (totals) totals.textContent = "no data yet";
    const delta = document.getElementById(`delta-${family}`);
    if (delta) delta.textContent = hint;
    const bySource = document.getElementById(`by-source-${family}`);
    if (bySource) bySource.textContent = "";
    for (const id of [`trend-${family}`, `def-${family}`]) {
      const host = document.getElementById(id);
      if (host) host.innerHTML = `<p class="chart-empty">no data</p>`;
    }
    const terms = document.getElementById(`terms-${family}`);
    if (terms) terms.innerHTML = `<li class="terms-empty">no data</li>`;
  }
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
   Staleness banner — read generated_at age, render yellow >8h, red >24h.
   The cron refreshes every 4h; if 24h passes with no new data.json,
   something is broken and the visitor should know rather than read stale numbers.
   ---------------------------------------------------------- */
function renderStalenessBanner() {
  const host = document.getElementById("staleness-banner");
  if (!host || !DATA.generated_at) return;
  const ageH = (Date.now() - new Date(DATA.generated_at).getTime()) / 3.6e6;
  if (!isFinite(ageH) || ageH < 8) {
    host.hidden = true;
    host.textContent = "";
    host.classList.remove("stale-yellow", "stale-red");
    return;
  }
  host.hidden = false;
  host.classList.toggle("stale-red", ageH >= 24);
  host.classList.toggle("stale-yellow", ageH >= 8 && ageH < 24);
  const fmt = ageH >= 24 ? `${Math.floor(ageH / 24)}d` : `${Math.floor(ageH)}h`;
  host.textContent =
    ageH >= 24
      ? `data has not refreshed in ${fmt} — cron may be down`
      : `data is ${fmt} old`;
}

/* ----------------------------------------------------------
   Meta line
   ---------------------------------------------------------- */
function relativeTime(iso) {
  const then = new Date(iso || "").getTime();
  if (!isFinite(then)) return "—";
  const diffSec = Math.max(0, (Date.now() - then) / 1000);
  if (diffSec < 60) return "just now";
  const m = Math.floor(diffSec / 60);
  if (m < 60) return m === 1 ? "1 minute ago" : `${m} minutes ago`;
  const h = Math.floor(diffSec / 3600);
  if (h < 24) return h === 1 ? "1 hour ago" : `${h} hours ago`;
  const d = Math.floor(diffSec / 86400);
  return d === 1 ? "1 day ago" : `${d} days ago`;
}

function renderMeta() {
  const totalRecords = DATA.totals?.all_records ?? 0;
  document.getElementById("meta-count").textContent = totalRecords.toLocaleString();
  document.getElementById("meta-updated").textContent = relativeTime(DATA.generated_at);
  document.getElementById("meta-cls").textContent = DATA.classifier_version || "v0";

  renderStalenessBanner();

  // Mock data carries a _note field with "MOCK" — flag it so it's never
  // confused with the live numbers
  if (DATA._note && /mock/i.test(DATA._note)) {
    const meta = document.getElementById("meta-line");
    if (meta && !meta.querySelector(".mock-badge")) {
      const badge = document.createElement("strong");
      badge.className = "mock-badge";
      badge.style.cssText = "color:var(--lemon-rind);margin-left:.5em";
      badge.textContent = "· MOCK DATA";
      meta.appendChild(badge);
    }
  }

  for (const family of ["claude", "openai"]) {
    const s = DATA.summary[family];
    if (!s) continue;
    document.getElementById(`totals-${family}`).textContent =
      `${s.this_week.all_mentions.toLocaleString()} mentions in ${s.this_week_label}`;
  }
}

/* ----------------------------------------------------------
   Render all
   ---------------------------------------------------------- */
function renderAll() {
  for (const family of ["claude", "openai"]) {
    renderBigNumber(family, DATA.summary[family]);
    renderTrend(`trend-${family}`, DATA.trend[family], family);
    renderTopTerms(`terms-${family}`, DATA.top_terms[family]);
    renderDefection(`def-${family}`, DATA.defection_trend[family]);
  }
}

/* ----------------------------------------------------------
   Big number + delta
   ---------------------------------------------------------- */
function renderBigNumber(family, s) {
  if (!s) return;
  const ratePct = (s.this_week.rate * 100);
  document.getElementById(`rate-${family}`).textContent = ratePct.toFixed(0) + "%";

  // Per-source split (HN vs Reddit) — small line beneath the big number
  const bs = s.this_week.by_source || {};
  const sourceEl = document.getElementById(`by-source-${family}`);
  if (sourceEl) {
    const parts = [];
    if (bs.hn) parts.push(`HN ${(bs.hn.rate * 100).toFixed(0)}%`);
    if (bs.reddit) parts.push(`Reddit ${(bs.reddit.rate * 100).toFixed(0)}%`);
    sourceEl.textContent = parts.length ? parts.join(" · ") : "";
  }

  const delta = s.delta_pts;
  const el = document.getElementById(`delta-${family}`);
  el.classList.remove("up", "down");
  if (delta == null || delta === 0) {
    el.textContent = "no change from last week";
    return;
  }
  const dir = delta > 0 ? "up" : "down";
  const glyph = delta > 0 ? "▲" : "▼";
  el.classList.add(dir);
  const absDelta = Math.abs(delta).toFixed(1);
  const lastPct = (s.last_week.rate * 100).toFixed(0);
  el.innerHTML = `<span class="delta-glyph">${glyph}</span> ${absDelta} pts from last week (${lastPct}%)`;
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
  for (const [k, v] of Object.entries(attrs)) {
    if (v != null) el.setAttribute(k, v);
  }
  if (text != null) el.textContent = text;
  parent.appendChild(el);
  return el;
}

/* ----------------------------------------------------------
   Trend chart — single line per panel (complaint rate over time)
   ---------------------------------------------------------- */
function renderTrend(hostId, series, family) {
  const host = document.getElementById(hostId);
  if (!host || !series || series.length === 0) return;
  const W = host.clientWidth;
  const H = host.clientHeight;
  const padL = 36, padR = 12, padT = 10, padB = 38;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;

  const svg = svgEl(host);
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);

  const weeks = series.map(p => p.week);
  const xOf = (w) => padL + (weeks.indexOf(w) / Math.max(weeks.length - 1, 1)) * innerW;

  let yMax = 0;
  for (const p of series) yMax = Math.max(yMax, p.rate);
  yMax = Math.min(1, Math.max(0.05, Math.ceil(yMax * 10 + 1) / 10)); // round up to 10% increments
  const yOf = (v) => padT + innerH - (v / yMax) * innerH;

  const lineColor = family === "claude" ? "var(--c-rate)" : "var(--c-rate-2)";

  // y-axis grid + labels (every 10% up to yMax)
  const ax = append(svg, "g", { class: "axis" });
  const steps = Math.round(yMax / 0.1);
  for (let i = 0; i <= steps; i++) {
    const v = (i / steps) * yMax;
    const y = yOf(v);
    append(ax, "line", { x1: padL, x2: W - padR, y1: y, y2: y, opacity: 0.3 });
    append(ax, "text", { x: 4, y: y + 3 }, `${(v * 100).toFixed(0)}%`);
  }

  // Release lines (wall-clock mode only)
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

  // X-axis labels (rotated)
  const labelEvery = Math.max(1, Math.floor(weeks.length / 6));
  const labelY = H - padB + 14;
  for (let i = 0; i < weeks.length; i += labelEvery) {
    const x = xOf(weeks[i]);
    append(ax, "text", {
      x, y: labelY, "text-anchor": "end",
      transform: `rotate(-35, ${x}, ${labelY})`,
    }, weeks[i].replace(/-W/, "·w"));
  }

  // Light fill under the line
  const linePoints = series.map(p => ({ x: xOf(p.week), y: yOf(p.rate) }));
  const areaD = [
    `M ${linePoints[0].x.toFixed(2)} ${(padT + innerH).toFixed(2)}`,
    ...linePoints.map(pt => `L ${pt.x.toFixed(2)} ${pt.y.toFixed(2)}`),
    `L ${linePoints[linePoints.length - 1].x.toFixed(2)} ${(padT + innerH).toFixed(2)} Z`,
  ].join(" ");
  append(svg, "path", { d: areaD, fill: lineColor, opacity: 0.12 });

  // Line itself
  const lineD = linePoints
    .map((pt, i) => `${i === 0 ? "M" : "L"} ${pt.x.toFixed(2)} ${pt.y.toFixed(2)}`)
    .join(" ");
  append(svg, "path", {
    d: lineD,
    fill: "none",
    stroke: lineColor,
    "stroke-width": "2",
  });

  // Latest dot
  const last = linePoints[linePoints.length - 1];
  append(svg, "circle", {
    cx: last.x, cy: last.y, r: 4,
    fill: lineColor, stroke: "var(--bg)", "stroke-width": "1.5",
  });
}

/* ----------------------------------------------------------
   Defection rhetoric — single line, smaller chart
   ---------------------------------------------------------- */
function renderDefection(hostId, series) {
  const host = document.getElementById(hostId);
  if (!host || !series || series.length === 0) return;
  const W = host.clientWidth;
  const H = host.clientHeight;
  const padL = 36, padR = 12, padT = 8, padB = 22;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;

  const svg = svgEl(host);
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);

  const weeks = series.map(p => p.week);
  const xOf = (w) => padL + (weeks.indexOf(w) / Math.max(weeks.length - 1, 1)) * innerW;

  let yMax = 0;
  for (const p of series) yMax = Math.max(yMax, p.rate);
  yMax = Math.max(0.01, Math.ceil(yMax * 100) / 100);
  const yOf = (v) => padT + innerH - (v / yMax) * innerH;

  // y axis (light)
  const ax = append(svg, "g", { class: "axis" });
  for (let i = 0; i <= 2; i++) {
    const v = (i / 2) * yMax;
    const y = yOf(v);
    append(ax, "line", { x1: padL, x2: W - padR, y1: y, y2: y, opacity: 0.2 });
    append(ax, "text", { x: 4, y: y + 3 }, `${(v * 100).toFixed(1)}%`);
  }

  // x labels (sparse)
  const labelEvery = Math.max(1, Math.floor(weeks.length / 4));
  for (let i = 0; i < weeks.length; i += labelEvery) {
    const x = xOf(weeks[i]);
    append(ax, "text", { x, y: H - 6, "text-anchor": "middle" }, weeks[i].replace(/-W/, "·w"));
  }

  const dParts = series
    .map((p, i) => `${i === 0 ? "M" : "L"} ${xOf(p.week).toFixed(2)} ${yOf(p.rate).toFixed(2)}`)
    .join(" ");
  append(svg, "path", {
    d: dParts,
    fill: "none",
    stroke: "var(--c-defection)",
    "stroke-width": "1.5",
  });
}

/* ----------------------------------------------------------
   Top terms list (no chart, just text + faint bar)
   ---------------------------------------------------------- */
function renderTopTerms(hostId, top) {
  const host = document.getElementById(hostId);
  if (!host || !top) return;
  host.innerHTML = "";
  const items = top.this_week || [];
  const max = items.reduce((m, it) => Math.max(m, it.count), 0) || 1;

  const buildRow = () => {
    const term = document.createElement("span");
    term.className = "term";
    const bar = document.createElement("span");
    bar.className = "bar";
    const fill = document.createElement("span");
    fill.className = "bar-fill";
    bar.appendChild(fill);
    const count = document.createElement("span");
    count.className = "count";
    return { term, bar, fill, count };
  };

  const KIND_LABEL = {
    top_scored: "top-scored",
    newest: "most recent",
    oldest: "earliest",
  };

  for (const it of items.slice(0, 10)) {
    const li = document.createElement("li");
    const hasExamples = Array.isArray(it.examples) && it.examples.length > 0;
    const { term, bar, fill, count } = buildRow();
    term.textContent = it.term;
    fill.style.width = `${(it.count / max) * 100}%`;
    count.textContent = `${it.count}×`;

    if (hasExamples) {
      li.classList.add("has-examples");  // explicit fallback when :has() unsupported
      // <details> gives free expand/collapse keyboard accessibility
      const det = document.createElement("details");
      det.className = "term-details";
      const summary = document.createElement("summary");
      summary.className = "term-summary";
      bar.setAttribute("aria-hidden", "true");  // decorative; don't announce
      summary.append(term, bar, count);
      det.appendChild(summary);

      const exUl = document.createElement("ul");
      exUl.className = "term-examples";
      for (const ex of it.examples) {
        const exli = document.createElement("li");
        const kind = document.createElement("span");
        kind.className = "ex-kind";
        kind.textContent = KIND_LABEL[ex._kind] || ex._kind || "example";
        const a = document.createElement("a");
        a.href = ex.permalink;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.className = "ex-link";
        const date = (ex.date || "").slice(0, 10);
        const src = ex.source || "?";
        const score = ex.score != null && ex.score > 0 ? ` · score ${ex.score}` : "";
        a.textContent = `${date} · ${src}${score}`;
        exli.append(kind, a);
        exUl.appendChild(exli);
      }
      det.appendChild(exUl);
      li.appendChild(det);
    } else {
      li.append(term, bar, count);
    }
    host.appendChild(li);
  }
}

/* ----------------------------------------------------------
   Helpers
   ---------------------------------------------------------- */
function nearestWeek(dateStr, weeks) {
  if (!dateStr) return null;
  const d = new Date(dateStr);
  if (isNaN(d)) return null;
  const target = `${d.getUTCFullYear()}-W${String(getISOWeek(d)).padStart(2, "0")}`;
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
