// Periodo global de análisis. Los datos se descargan con todos los años; el periodo filtra después el
// mapa, el análisis, el catálogo y las fichas. Se recuerda en el navegador y se comparte entre vistas.
import { cssVar, esc, fmt, store } from "../core.js";
import { axis, baseOption } from "./ec.js";

export const MONTHS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];
const KEY = "time.v2";
const EVT = "period:change";
let SPAN = null;  // [lo, hi] años con registros del workspace activo

/** Años con datos del workspace activo (los fija main.js al cambiar de workspace). */
export function setSpan(years) {
  const ys = (years || []).filter(Boolean);
  SPAN = ys.length ? [Math.min(...ys), Math.max(...ys)] : null;
}
export const span = () => SPAN;

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/**
 * Periodo vigente acotado a los años disponibles.
 * @returns {{from,to,lo,hi,active,label}|null}
 *  `active` = el periodo no cubre toda la serie (hay filtro).
 */
export function getPeriod(years = null) {
  let lo, hi;
  if (years?.length) { const ys = years.filter(Boolean); lo = Math.min(...ys); hi = Math.max(...ys); }
  if (SPAN) { lo = Math.min(lo ?? SPAN[0], SPAN[0]); hi = Math.max(hi ?? SPAN[1], SPAN[1]); }
  if (lo == null) return null;
  const s = store.get(KEY, {}) || {};
  let from = clamp(s.from ?? lo, lo, hi), to = clamp(s.to ?? hi, lo, hi);
  if (from > to) [from, to] = [to, from];
  const active = from > lo || to < hi;
  return { from, to, lo, hi, active, label: active ? yr(from, to) : "Todos los años" };
}
const yr = (a, b) => (a === b ? `${a}` : `${a}–${b}`);
export const periodLabel = (p) => p.label ?? yr(p.from, p.to);
export const inPeriod = (p, y) => !p || !p.active || (y >= p.from && y <= p.to);
/** Parámetros de API del periodo (vacío si no hay filtro). */
export const periodParams = (p) => (p?.active ? { year_from: p.from, year_to: p.to } : {});

export function setPeriod(patch) {
  store.set(KEY, { ...(store.get(KEY, {}) || {}), ...patch });
  window.dispatchEvent(new CustomEvent(EVT, { detail: getPeriod() }));
}
export function onPeriod(fn) {
  const h = (e) => fn(e.detail);
  window.addEventListener(EVT, h);
  return () => window.removeEventListener(EVT, h);
}

/** Selector de periodo. Emite el evento global al cambiar. */
export function periodPicker(p, onChange = null, { dark = false } = {}) {
  const wrap = document.createElement("div");
  wrap.className = `period-picker${dark ? " on-dark" : ""}`;
  const opts = (sel) => Array.from({ length: p.hi - p.lo + 1 }, (_, i) => p.lo + i)
    .map((y) => `<option value="${y}" ${y === sel ? "selected" : ""}>${y}</option>`).join("");
  const n = p.hi - p.lo + 1;
  const presets = [[0, "Todos"], [5, "5 años"], [10, "10 años"], [20, "20 años"]].filter(([k]) => k === 0 || n > k);
  const isPreset = (k) => (k === 0 ? !p.active : p.to === p.hi && p.from === p.hi - k + 1);
  wrap.innerHTML = `<div class="pp-row"><span class="pp-label">Periodo</span>
      <label><span class="sr-only">Desde</span><select data-k="from">${opts(p.from)}</select></label>
      <span aria-hidden="true">–</span>
      <label><span class="sr-only">Hasta</span><select data-k="to">${opts(p.to)}</select></label>
      ${presets.map(([k, l]) => `<button class="chip ${isPreset(k) ? "on" : ""}" data-n="${k}">${esc(l)}</button>`).join("")}</div>`;
  wrap.addEventListener("change", (e) => {
    const k = e.target.dataset.k; if (!k) return;
    setPeriod({ [k]: +e.target.value }); onChange?.();
  });
  wrap.addEventListener("click", (e) => {
    const b = e.target.closest("[data-n]"); if (!b) return;
    const k = +b.dataset.n;
    setPeriod(k === 0 ? { from: p.lo, to: p.hi } : { from: p.hi - k + 1, to: p.hi }); onChange?.();
  });
  return wrap;
}

// Neutro para los años fuera del periodo; color de acento para el periodo
const allColor = () => cssVar("--series-other") || "#6b7280";

/** Registros por año: barras neutras (todos los años) y de color (periodo) + medias. */
export function yearlyCompareOption(years, counts, p, { textColor, gridColor, periodColor, extraSeries = [], compact = false } = {}) {
  const b = baseOption({ textColor, gridColor });
  const pc = periodColor || cssVar("--series-1");
  const act = !!p?.active;
  const inP = (y) => act && y >= p.from && y <= p.to;
  const mean = (f) => { const v = counts.filter((_, i) => f(years[i])); return v.reduce((a, x) => a + x, 0) / Math.max(1, v.length); };
  const ax = (t, extra) => axis(t, { ...extra, axisLabel: { ...(extra?.axisLabel || {}), ...(textColor ? { color: textColor } : {}) },
    ...(gridColor ? { splitLine: { lineStyle: { color: gridColor } }, axisLine: { lineStyle: { color: gridColor } } } : {}) });
  // Etiquetas en extremos opuestos para que no se solapen
  const ml = (v, name, color, position) => ({ yAxis: +v.toFixed(1), name, lineStyle: { color, type: "dashed", width: 1.5 },
    label: { formatter: `${name}: ${fmt.d1(v)}/año`, color: textColor || cssVar("--text-2"), position, fontSize: 10 } });
  const bar = (name, data, color, { itemStyle = {}, ...extra } = {}) => ({ type: "bar", name, data, barGap: "-100%", barMaxWidth: 26,
    itemStyle: { color, borderRadius: [4, 4, 0, 0], ...itemStyle }, ...extra });
  const series = [bar("Todos los años", counts, allColor(), { itemStyle: { opacity: act ? 0.45 : 0.8 },
    markLine: { symbol: "none", silent: true, data: [ml(mean(() => true), "Media total", allColor(), "insideStartTop")] } })];
  if (act) series.push(bar(`Periodo ${p.label}`, counts.map((v, i) => (inP(years[i]) ? v : null)), pc,
    { markLine: { symbol: "none", silent: true, data: [ml(mean(inP), "Media periodo", pc, "insideEndTop")] } }));
  return {
    ...b,
    legend: { top: 0, textStyle: { color: textColor || cssVar("--text-2"), fontSize: 11 }, itemWidth: 12, itemHeight: 8 },
    grid: { ...b.grid, top: compact ? 28 : 40, left: compact ? 8 : b.grid.left, right: compact ? 8 : b.grid.right, bottom: compact ? 4 : b.grid.bottom },
    tooltip: { ...b.tooltip, trigger: "axis", axisPointer: { type: "shadow" },
      formatter: (items) => {
        const y = +items[0].axisValue, n = counts[years.indexOf(y)] ?? 0;
        return `<b>${y}</b>${inP(y) ? ` · periodo ${p.label}` : ""}<br>${fmt.n(n)} registros` +
          items.filter((s) => s.seriesType === "line").map((s) => `<br>${s.marker}${esc(s.seriesName)}: ${fmt.d1(s.value)}`).join("");
      } },
    xAxis: ax("category", { data: years }),
    yAxis: ax("value", { axisLabel: { formatter: (v) => fmt.compact(v) } }),
    dataZoom: !compact && years.length > 25 ? [{ type: "inside" }, { type: "slider", height: 14, bottom: 0 }] : [],
    series: [...series, ...extraSeries],
  };
}

/** Matriz año×mes → % mensual de todos los años y del periodo (misma escala para comparar la forma). */
export function monthlyShares(ym, p) {
  const ref = Array(12).fill(0), per = Array(12).fill(0);
  const act = !!p?.active;
  ym.year.forEach((y, i) => {
    const m = ym.month[i] - 1, n = ym.n?.[i] ?? ym.records[i];
    ref[m] += n;
    if (act && y >= p.from && y <= p.to) per[m] += n;
  });
  const tr = ref.reduce((a, v) => a + v, 0), tp = per.reduce((a, v) => a + v, 0);
  return { all: ref, per, ta: tr, tp, pa: ref.map((v) => (tr ? (v / tr) * 100 : 0)), pp: per.map((v) => (tp ? (v / tp) * 100 : 0)) };
}

export function monthlyCompareOption(ym, p, { textColor, gridColor, periodColor, compact = false, labels = MONTHS } = {}) {
  const b = baseOption({ textColor, gridColor });
  const pc = periodColor || cssVar("--series-1");
  const act = !!p?.active;
  const s = monthlyShares(ym, p);
  const refName = "Todos los años";
  const ax = (t, extra) => axis(t, { ...extra, axisLabel: { ...(extra?.axisLabel || {}), ...(textColor ? { color: textColor } : {}) },
    ...(gridColor ? { splitLine: { lineStyle: { color: gridColor } }, axisLine: { lineStyle: { color: gridColor } } } : {}) });
  const series = [{ type: "bar", name: `${refName} (${fmt.n(s.ta)})`, data: s.pa.map((v) => +v.toFixed(2)), barMaxWidth: 16, barGap: "12%",
    itemStyle: { color: allColor(), opacity: 0.7, borderRadius: [4, 4, 0, 0] } }];
  if (act) series.push({ type: "bar", name: `Periodo ${p.label} (${fmt.n(s.tp)})`, data: s.pp.map((v) => +v.toFixed(2)), barMaxWidth: 16,
    itemStyle: { color: pc, borderRadius: [4, 4, 0, 0] } });
  return {
    ...b,
    legend: { top: 0, textStyle: { color: textColor || cssVar("--text-2"), fontSize: 11 }, itemWidth: 12, itemHeight: 8 },
    grid: { ...b.grid, top: compact ? 28 : 40, left: compact ? 8 : b.grid.left, right: compact ? 8 : b.grid.right, bottom: compact ? 4 : b.grid.bottom },
    tooltip: { ...b.tooltip, trigger: "axis", axisPointer: { type: "shadow" },
      formatter: (items) => { const i = items[0].dataIndex;
        return `<b>${MONTHS[i]}</b><br>${items[0].marker}${esc(refName)}: ${fmt.d1(s.pa[i])}% (${fmt.n(s.all[i])})` +
          (act ? `<br>${items[1]?.marker || ""}Periodo ${p.label}: ${fmt.d1(s.pp[i])}% (${fmt.n(s.per[i])})` : ""); } },
    xAxis: ax("category", { data: labels }),
    yAxis: ax("value", { axisLabel: { formatter: (v) => `${v}%` } }),
    series,
  };
}
