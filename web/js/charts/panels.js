// Registro de paneles analíticos. Cada panel consume uno o más indicadores del backend.
// Para añadir un panel: registerPanel({ id, group, title, needs: ["indicador"], render(el, I, ctx) }).
import { catBadge, catInfo, cssVar, DANGER, esc, fmt, HOT } from "../core.js";
import { axis, baseOption, makeChart } from "./ec.js";
import { getPeriod, monthlyCompareOption, monthlyShares, periodLabel, periodPicker, yearlyCompareOption } from "./period.js";

export const GROUPS = [
  ["resumen", "Resumen"], ["calidad", "Calidad de datos"], ["temporal", "Temporal"], ["espacial", "Espacial"],
  ["biodiversidad", "Biodiversidad"], ["conservacion", "Conservación"], ["especies", "Especies"],
];
export const PANELS = [];
export const registerPanel = (p) => PANELS.push({ width: 6, ...p });

// ------------------------------------------------------------------ helpers
const S = (i) => cssVar(`--series-${i}`);
const D = (I, id) => I[id]?.data || {};
const kpiTiles = (items) => `<div class="kpis">${items.map(([l, v, s]) =>
  `<div class="kpi glass"><div class="label">${l}</div><div class="value">${v}</div>${s ? `<div class="sub">${s}</div>` : ""}</div>`).join("")}</div>`;

export function tableHTML(cols, rows) {
  return `<div class="tbl-wrap"><table class="tbl"><thead><tr>${cols.map((c) => `<th class="${c.num ? "num" : ""}">${esc(c.label)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((r) => `<tr>${cols.map((c) => { const v = typeof c.get === "function" ? c.get(r) : r[c.key];
      return `<td class="${c.num ? "num" : ""}">${c.html ? v : esc(c.num && typeof v === "number" ? fmt.d2(v) : v ?? "—")}</td>`; }).join("")}</tr>`).join("")}</tbody></table></div>`;
}

function bars(el, cats, vals, { horizontal = true, name = "Registros", color = S(1), onClick, mean, fmtVal = fmt.n, colors } = {}) {
  const b = baseOption();
  const cat = axis("category", { data: cats, inverse: horizontal, axisLabel: { width: 150, overflow: "truncate" } });
  const val = axis("value", { axisLabel: { formatter: (v) => fmt.compact(v) } });
  const series = { type: "bar", name, data: vals.map((v, i) => ({ value: v, itemStyle: colors ? { color: colors[i] } : undefined })),
    barMaxWidth: 16, barCategoryGap: "35%",
    itemStyle: { color, borderRadius: horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0] },
    label: { show: vals.length <= 12, position: horizontal ? "right" : "top", color: cssVar("--text-2"), fontSize: 11, formatter: (p) => fmtVal(p.value) },
    emphasis: { focus: "self" } };
  if (mean) series.markLine = { symbol: "none", label: { formatter: `media ${fmt.n(mean)}`, color: cssVar("--text-2"), position: horizontal ? "end" : "insideEndTop", backgroundColor: cssVar("--bg-2"), padding: [2, 6], borderRadius: 6 }, lineStyle: { color: cssVar("--text-3"), type: "solid", width: 1 }, data: [horizontal ? { xAxis: mean } : { yAxis: mean }] };
  const c = makeChart(el, { ...b, grid: { left: 8, right: 40, top: 10, bottom: 10, containLabel: true },
    tooltip: { ...b.tooltip, trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: fmtVal },
    xAxis: horizontal ? val : cat, yAxis: horizontal ? cat : val, series: [series] });
  if (onClick) { c.on("click", (p) => onClick(p.name, p)); el.style.cursor = "pointer"; }
  return c;
}

const speciesChip = (s) => `<button class="chip sp-link" data-sp="${esc(s.species)}">${catBadge(s.threat_national || s.category || s.threat_global)}<i>${esc(s.species)}</i>${s.common_name ? ` · ${esc(s.common_name)}` : ""}${s.n_records != null ? ` · ${fmt.n(s.n_records)}` : ""}</button>`;

// ================================================================== RESUMEN
registerPanel({ id: "kpis", group: "resumen", width: 12, title: "Cifras clave del área", needs: ["overview", "quality"],
  render(el, I) {
    const o = D(I, "overview").summary || {}, q = D(I, "quality").summary || {};
    el.innerHTML = kpiTiles([
      ["Registros", fmt.n(o.records), `${fmt.d2(o.records_per_km2)} por km²`],
      ["Especies", fmt.n(o.species), `${fmt.n(o.genera)} géneros · ${fmt.n(o.families)} familias`],
      ["Clases", fmt.n(o.classes), `${fmt.n(o.kingdoms)} reinos`],
      ["Amenazadas (Res. 0126)", fmt.n(o.threatened_national), "CR · EN · VU nacional"],
      ["Amenazadas (IUCN)", fmt.n(o.threatened_global), "CR · EN · VU global"],
      ["CITES", fmt.n(o.cites_species), "especies en apéndices"],
      ["Exóticas", fmt.n(o.exotic_species), "según SiB Colombia"],
      ["Calidad", `${fmt.d1(q.score)}`, `score 0–100 · ${q.label || ""}`],
      ["Periodo", o.year_min ? `${o.year_min}–${o.year_max}` : "—", `${fmt.n(o.datasets)} datasets`],
      ["Área", fmt.km2(o.area_km2), `${fmt.d2(o.species_per_100km2)} especies / 100 km²`],
    ]);
  } });

registerPanel({ id: "findings", group: "resumen", width: 8, title: "Hallazgos automáticos", desc: "Plantillas por umbrales (sin IA), listas para informes.",
  needs: ["overview"], render(el, I) {
    const items = Object.values(I).filter((v) => v.ok && v.data?.interpretation?.length);
    el.innerHTML = `<div class="notes">${items.map((v) => v.data.interpretation.map((t) => `<p><b>${esc(v.title)}.</b> ${esc(t)}</p>`).join("")).join("")}</div>`;
  } });

registerPanel({ id: "kingdoms", group: "resumen", width: 4, title: "Especies por reino", needs: ["overview"],
  render(el, I) { const k = D(I, "overview").kingdoms || [];
    return bars(el, k.map((r) => r.kingdom), k.map((r) => r.species), { name: "Especies" }); },
  table: (I) => [[{ key: "kingdom", label: "Reino" }, { key: "species", label: "Especies", num: true }, { key: "records", label: "Registros", num: true }], D(I, "overview").kingdoms || []] });

// ================================================================== CALIDAD (Indicador 4)
registerPanel({ id: "cleaning", group: "calidad", width: 12, title: "Depuración aplicada antes del análisis", desc: "Registros descargados de GBIF vs registros que entran a los indicadores", needs: ["cleaning"],
  render(el, I) { const c = D(I, "cleaning"), s = c.summary || {};
    if (!s.applied) { el.innerHTML = `<p class="muted">${esc((c.interpretation || [])[0] || "Sin depuración.")}</p>`; return null; }
    el.style.height = "auto";
    el.innerHTML = kpiTiles([
      ["Descargados", fmt.n(s.raw), "registros GBIF en el área"],
      ["Eliminados", fmt.n(s.removed), `${fmt.pct(100 - s.retention_pct)} del total`],
      ["En el análisis", fmt.n(s.final), `${fmt.pct(s.retention_pct)} conservado${s.year_max ? ` · hasta ${s.year_max}` : ""}`],
      ["Fuera de análisis espaciales", fmt.n(s.spatial_excluded), s.max_uncertainty_m ? `incertidumbre > ${fmt.n(s.max_uncertainty_m / 1000)} km` : "—"],
    ]) + tableHTML([{ key: "label", label: "Criterio" }, { key: "records", label: "Registros eliminados", num: true, get: (r) => fmt.n(r.records) }, { key: "pct", label: "% de lo descargado", num: true }], c.steps || [])
      + `<p class="muted" style="font-size:12px;margin:8px 0 0">Los criterios se aplican en orden; un registro cuenta en el primer criterio que lo elimina.</p>`;
    return null; } });

registerPanel({ id: "score", group: "calidad", width: 4, title: "Score de calidad", desc: "40% coordenadas válidas + 60% campos con completitud ≥ 80%", needs: ["quality"],
  render(el, I) {
    const q = D(I, "quality").summary || {};
    const st = q.label === "ALTA" ? "--good" : q.label === "MEDIA" ? "--warning" : "--critical";
    el.innerHTML = `<div class="score-ring"><div class="hero-num">${fmt.d1(q.score)}</div>
      <div><span class="chip" style="border-color:var(${st})">● ${q.label}</span><p class="soft" style="margin:8px 0 0;font-size:12px">
      Retención ${fmt.pct(q.retention_pct)} (${fmt.n(q.n_clean)} de ${fmt.n(q.n_total)})<br>
      ${fmt.n(q.fields_high_completeness)} de ${fmt.n(q.fields_evaluated)} campos con alta completitud<br>
      ${fmt.n(q.outliers_iqr)} outliers IQR marcados</p></div></div>`;
  } });

registerPanel({ id: "completeness", group: "calidad", width: 8, title: "Completitud de campos clave", desc: "Semáforo: ALTA ≥ 80% · MEDIA 40–79% · BAJA < 40%", needs: ["quality"],
  render(el, I) { const c = D(I, "quality").completeness || [];
    const col = { ALTA: cssVar("--good"), MEDIA: cssVar("--warning"), BAJA: cssVar("--critical") };
    return bars(el, c.map((r) => `${r.label} · ${r.level}`), c.map((r) => r.pct), { name: "% completo", fmtVal: fmt.pct, colors: c.map((r) => col[r.level]) }); },
  table: (I) => [[{ key: "label", label: "Campo" }, { key: "field", label: "Nombre técnico" }, { key: "complete", label: "Completos", num: true }, { key: "pct", label: "%", num: true }, { key: "level", label: "Nivel" }], D(I, "quality").completeness || []] });

registerPanel({ id: "dups", group: "calidad", width: 6, title: "Duplicados y coordenadas", needs: ["quality"],
  render(el, I) { const q = D(I, "quality"), d = q.duplicates || {}, c = q.coordinates || {};
    el.innerHTML = kpiTiles([
      ["Dup. por gbifID", fmt.n(d.by_id)], ["Dup. espaciotemporales", fmt.n(d.spatiotemporal), fmt.pct(d.pct_spatiotemporal)],
      ["Dup. solo espaciales", fmt.n(d.spatial), fmt.pct(d.pct_spatial)], ["Coordenadas (0,0)", fmt.n(c.zero)],
      ["Issues severos", fmt.n(c.severe_issue)], ["Incertidumbre > umbral", fmt.n(c.high_uncertainty)], ["Coordenadas redondeadas", fmt.n(c.rounded)],
    ]) + `<p class="muted" style="font-size:11px">Outliers IQR (factor ${q.outliers?.factor}): lat ${q.outliers?.bounds?.lat?.join(" a ")} · lon ${q.outliers?.bounds?.lon?.join(" a ")}</p>`;
  } });

registerPanel({ id: "issues", group: "calidad", width: 6, title: "Issues GBIF más frecuentes", needs: ["quality"],
  render(el, I) { const t = D(I, "quality").top_issues || [];
    return bars(el, t.map((r) => r.issue.replaceAll("_", " ").toLowerCase()), t.map((r) => r.records)); } });

registerPanel({ id: "basis", group: "calidad", width: 6, title: "G2 · Tipo de registro (basisOfRecord)", needs: ["composition"],
  render(el, I) { const b = D(I, "composition").basis || [];
    return bars(el, b.map((r) => r.label), b.map((r) => r.records), { fmtVal: fmt.n }); },
  table: (I) => [[{ key: "label", label: "Tipo" }, { key: "records", label: "Registros", num: true }, { key: "pct", label: "%", num: true }, { key: "pct_cum", label: "% acumulado", num: true }], D(I, "composition").basis || []] });

registerPanel({ id: "institutions", group: "calidad", width: 6, title: "Instituciones que publican", needs: ["composition"],
  render(el, I) { const t = D(I, "composition").institutions || [];
    return bars(el, t.map((r) => r.institution), t.map((r) => r.records)); } });

registerPanel({ id: "hist", group: "calidad", width: 12, title: "G5 · Incertidumbre espacial: escala lineal vs logarítmica", needs: ["uncertainty"],
  render(el, I) {
    const u = D(I, "uncertainty");
    if (!u.histogram_linear) { el.innerHTML = `<p class="muted">Sin datos de incertidumbre.</p>`; return; }
    el.innerHTML = `<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px"><div class="chart short"></div><div class="chart short"></div></div>`;
    const [a, b] = el.querySelectorAll(".chart");
    const mk = (node, h, log) => {
      const cats = h.counts.map((_, i) => `${fmt.compact(h.edges[i])}–${fmt.compact(h.edges[i + 1])} m`);
      const base = baseOption();
      return makeChart(node, { ...base, grid: { left: 8, right: 10, top: 24, bottom: 8, containLabel: true },
        title: { text: log ? "Bins logarítmicos" : "Bins lineales (hasta p99)", textStyle: { fontSize: 12, color: cssVar("--text-2"), fontWeight: 500 } },
        tooltip: { ...base.tooltip, trigger: "axis" },
        xAxis: axis("category", { data: cats, axisLabel: { show: false } }),
        yAxis: axis(log ? "log" : "value", { name: "registros", min: log ? 1 : 0 }),
        series: [{ type: "bar", name: "Registros", data: h.counts.map((v) => (log ? Math.max(v, 0.9) : v)), barCategoryGap: "8%", itemStyle: { color: S(1), borderRadius: [3, 3, 0, 0] } }] });
    };
    return [mk(a, u.histogram_linear, false), mk(b, u.histogram_log, true)];
  } });

registerPanel({ id: "boxplot", group: "calidad", width: 12, title: "G6 · Incertidumbre por unidad administrativa", desc: "Unidades con ≥ 8 registros con incertidumbre; ordenadas por mediana", needs: ["uncertainty"],
  render(el, I) { const bx = D(I, "uncertainty").boxplot || [];
    if (!bx.length) { el.innerHTML = `<p class="muted">No hay unidades con suficientes registros.</p>`; return; }
    const base = baseOption();
    return makeChart(el, { ...base, tooltip: { ...base.tooltip, trigger: "item", formatter: (p) => `<b>${esc(p.name)}</b><br>min ${fmt.n(p.data[1])} · Q1 ${fmt.n(p.data[2])}<br>mediana ${fmt.n(p.data[3])} · Q3 ${fmt.n(p.data[4])}<br>máx ${fmt.n(p.data[5])} m` },
      xAxis: axis("category", { data: bx.map((b) => b.unit) }), yAxis: axis("log", { name: "metros", min: 1 }),
      series: [{ type: "boxplot", data: bx.map((b) => [Math.max(b.min, 1), Math.max(b.q1, 1), Math.max(b.median, 1), Math.max(b.q3, 1), Math.max(b.max, 1)]),
        itemStyle: { color: "transparent", borderColor: S(1), borderWidth: 2 } }] });
  } });

// ================================================================== TEMPORAL (G3, G4)
// Estos paneles usan siempre la serie completa (ctx.full) para mostrar el periodo dentro de toda la historia.
const tPeriod = () => getPeriod();

registerPanel({ id: "period", group: "temporal", width: 12, title: "Periodo de análisis", desc: "El mismo periodo filtra el mapa, el catálogo y las fichas (botón de calendario de la barra superior)", needs: ["temporal"],
  render(el, I) { const p = tPeriod(); if (!p) { el.textContent = "Sin años disponibles."; return null; }
    const y = D(I, "temporal").yearly || [];
    const sum = (a, b) => y.filter((r) => r.year >= a && r.year <= b).reduce((acc, r) => acc + r.records, 0);
    const tot = sum(p.lo, p.hi), per = sum(p.from, p.to);
    const nYears = p.to - p.from + 1, allYears = p.hi - p.lo + 1;
    el.style.height = "auto";
    el.appendChild(periodPicker(p));
    el.insertAdjacentHTML("beforeend", p.active ? `<p class="period-sum">El periodo <b>${periodLabel(p)}</b> (${nYears} de ${allYears} años) reúne
      <b>${fmt.n(per)}</b> registros, el <b>${fmt.pct(tot ? per / tot * 100 : 0)}</b> del total (${fmt.n(per / nYears)} registros/año).</p>`
      : `<p class="period-sum">Se muestran <b>todos los años</b> (${p.lo}–${p.hi}, ${fmt.n(tot)} registros). Elige un periodo para filtrar.</p>`);
    return null; } });

registerPanel({ id: "yearly", group: "temporal", width: 8, title: "G3 · Registros por año", desc: "Gris: todos los años · color: periodo seleccionado · líneas: media móvil y tendencia de toda la serie", needs: ["temporal"],
  render(el, I) { const t = D(I, "temporal"), y = t.yearly || [], tr = t.trend || {}; const p = tPeriod(I); if (!p) return null;
    const extra = [{ type: "line", name: "Media móvil", data: y.map((r) => r.moving_avg), smooth: true, symbolSize: 6, lineStyle: { width: 2, color: S(2) }, itemStyle: { color: S(2) } }];
    if (tr.slope != null) extra.push({ type: "line", name: "Tendencia lineal", data: y.map((r) => +(tr.slope * r.year + tr.intercept).toFixed(1)), symbol: "none", lineStyle: { width: 2, color: S(3) }, itemStyle: { color: S(3) } });
    return makeChart(el, yearlyCompareOption(y.map((r) => r.year), y.map((r) => r.records), p, { extraSeries: extra }));
  },
  table: (I) => { const p = tPeriod(I);
    return [[{ key: "year", label: "Año" }, { label: "En el periodo", get: (r) => (p?.active && r.year >= p.from && r.year <= p.to ? "Sí" : "") },
      { key: "records", label: "Registros", num: true }, { key: "moving_avg", label: "Media móvil", num: true }, { key: "species", label: "Especies", num: true }, { key: "new_species", label: "Especies nuevas", num: true }], D(I, "temporal").yearly || []]; } });

registerPanel({ id: "temporal-kpis", group: "temporal", width: 4, title: "Indicadores temporales", needs: ["temporal"],
  render(el, I) { const s = D(I, "temporal").summary || {};
    el.innerHTML = kpiTiles([
      ["Cambio reciente", s.pct_change_recent != null ? `${s.pct_change_recent > 0 ? "+" : ""}${fmt.d1(s.pct_change_recent)}%` : "—", "últimos 5 años vs previos"],
      ["Pendiente", fmt.n(s.trend_slope_per_year), `reg/año · R² ${fmt.d2(s.trend_r2)}`],
      ["Mes pico", s.peak_month || "—", `CV mensual ${fmt.d2(s.seasonality_cv)}`],
      ["Fin de semana", fmt.pct(s.weekend_pct), "esperado ≈ 28,6%"],
    ]); } });

registerPanel({ id: "monthly", group: "temporal", width: 6, title: "G4 · Estacionalidad: periodo vs totalidad", desc: "% de los registros de cada serie por mes, para comparar la forma estacional", needs: ["temporal"],
  render(el, I) { const ym = D(I, "temporal").year_month, p = tPeriod(I);
    if (!ym || !p) { el.innerHTML = `<p class="muted">Vuelve a ejecutar el análisis para habilitar la comparación por periodo.</p>`; return null; }
    return makeChart(el, monthlyCompareOption(ym, p)); },
  table: (I) => { const ym = D(I, "temporal").year_month, p = tPeriod(I); if (!ym || !p) return [[], []];
    const s = monthlyShares(ym, p);
    return [[{ key: "m", label: "Mes" }, { key: "all", label: "Todos los años", num: true }, { key: "pa", label: "% total", num: true },
      { key: "per", label: `Periodo ${periodLabel(p)}`, num: true }, { key: "pp", label: "% periodo", num: true }],
    s.all.map((v, i) => ({ m: ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"][i], all: v, pa: s.pa[i], per: s.per[i], pp: s.pp[i] }))]; } });

registerPanel({ id: "discovery", group: "temporal", width: 6, title: "Curva de descubrimiento de especies", desc: "Especies acumuladas según el año de su primer registro", needs: ["temporal"],
  render(el, I) { const y = D(I, "temporal").yearly || []; const base = baseOption();
    return makeChart(el, { ...base, tooltip: { ...base.tooltip, trigger: "axis", valueFormatter: fmt.n },
      xAxis: axis("category", { data: y.map((r) => r.year), boundaryGap: false }), yAxis: axis("value", { name: "especies", axisLabel: { formatter: (v) => fmt.n(v) } }),
      series: [{ type: "line", name: "Especies acumuladas", data: y.map((r) => r.cumulative_species), areaStyle: { opacity: 0.18, color: S(3) }, lineStyle: { width: 2, color: S(3) }, itemStyle: { color: S(3) }, symbolSize: 8 }] }); } });

// ================================================================== ESPACIAL (G1, G7, grilla, hotspots)
registerPanel({ id: "units", group: "espacial", width: 6, title: "G1 · Registros por unidad administrativa", needs: ["geography"],
  render(el, I) { const g = D(I, "geography"), u = (g.units || []).slice(0, 12);
    return bars(el, u.map((r) => r.unit), u.map((r) => r.records), { mean: g.summary?.mean_records }); },
  table: (I) => [[{ key: "rank", label: "#" }, { key: "unit", label: "Unidad" }, { key: "records", label: "Registros", num: true }, { key: "pct", label: "%", num: true }, { key: "species", label: "Especies", num: true }], D(I, "geography").units || []] });

registerPanel({ id: "elevation", group: "espacial", width: 6, title: "Gradiente altitudinal", desc: "Especies por franja de elevación (reportada por el observador o completada con DEM)", needs: ["elevation"],
  render(el, I) { const e = D(I, "elevation"), b = (e.bands || []).slice().reverse(), sm = e.summary || {};
    if (!b.length) { el.innerHTML = `<p class="muted">Sin elevación disponible.</p>`; return null; }
    const base = baseOption();
    return makeChart(el, { ...base, grid: { left: 8, right: 30, top: 30, bottom: 8, containLabel: true },
      title: { text: `${fmt.pct(sm.pct_with_elevation)} con elevación · ${fmt.n(sm.n_dem)} completadas con DEM`, textStyle: { color: cssVar("--text-3"), fontSize: 11, fontWeight: 400 }, top: 0, left: 0 },
      tooltip: { ...base.tooltip, trigger: "axis", axisPointer: { type: "shadow" }, formatter: (it) => { const r = b[it[0].dataIndex];
        return `<b>${esc(r.label)}</b><br>${fmt.n(r.species)} especies · ${fmt.n(r.records)} registros<br>${fmt.n(r.threatened_species)} especies amenazadas`; } },
      xAxis: axis("value"), yAxis: axis("category", { data: b.map((r) => r.label) }),
      series: [{ type: "bar", name: "Especies", data: b.map((r) => r.species), barMaxWidth: 14, itemStyle: { color: S(3), borderRadius: [0, 4, 4, 0] },
        label: { show: b.length <= 14, position: "right", color: cssVar("--text-2"), fontSize: 11, formatter: (p) => fmt.n(p.value) } }] }); },
  table: (I) => [[{ key: "label", label: "Franja" }, { key: "records", label: "Registros", num: true }, { key: "species", label: "Especies", num: true }, { key: "threatened_species", label: "Amenazadas", num: true }], D(I, "elevation").bands || []] });

registerPanel({ id: "heatmap", group: "espacial", width: 6, title: "G7 · Heatmap unidad × año", needs: ["geography"],
  render(el, I) { const h = D(I, "geography").heatmap || {}; const base = baseOption();
    const data = (h.cells || []).map((c) => [h.years.indexOf(c.year), h.units.indexOf(c.unit), c.records]);
    const max = Math.max(1, ...data.map((d) => d[2]));
    return makeChart(el, { ...base, grid: { left: 8, right: 16, top: 10, bottom: 50, containLabel: true },
      tooltip: { ...base.tooltip, formatter: (p) => `${esc(h.units[p.data[1]])} · ${h.years[p.data[0]]}<br><b>${fmt.n(p.data[2])}</b> registros` },
      xAxis: axis("category", { data: h.years, splitArea: { show: false } }), yAxis: axis("category", { data: h.units }),
      visualMap: { min: 0, max, calculable: true, orient: "horizontal", left: "center", bottom: 0, itemHeight: 120, textStyle: { color: cssVar("--text-2") }, formatter: (v) => fmt.n(v),
        inRange: { color: ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"] } },
      series: [{ type: "heatmap", data, itemStyle: { borderColor: cssVar("--bg"), borderWidth: 2, borderRadius: 3 } }] }); } });

registerPanel({ id: "grid-kpis", group: "espacial", width: 4, title: "Grilla de densidad", needs: ["spatial_grid", "hotspots"],
  render(el, I) { const g = D(I, "spatial_grid").summary || {}, h = D(I, "hotspots").summary || {};
    el.innerHTML = kpiTiles([
      ["Tamaño de celda", `${fmt.d1(g.cell_size_m / 1000)} km`, `${fmt.n(g.n_cells)} celdas`],
      ["Celdas con registros", fmt.pct(g.pct_occupied), `${fmt.n(g.occupied_cells)} celdas`],
      ["Gini de registros", fmt.d2(g.gini_records), "0 uniforme · 1 concentrado"],
      ["Máx. especies/celda", fmt.n(g.max_species_cell)],
      ["Hotspots de riqueza", fmt.n(h.richness_hotspots_95), "Gi* ≥ 95%"],
    ]) + `<a class="btn sm" href="#/map">Ver en el mapa 3D →</a>`; } });

registerPanel({ id: "hot-classes", group: "espacial", width: 8, title: "Hotspots Getis-Ord Gi*", desc: "Celdas por nivel de significancia, para riqueza, registros y amenazadas", needs: ["hotspots"],
  render(el, I) { const c = D(I, "hotspots").classes || {}; const base = baseOption();
    const keys = [["richness", "Riqueza"], ["records", "Registros"], ["threatened", "Amenazadas"]];
    const levels = (c.richness || []).map((r) => r);
    return makeChart(el, { ...base, legend: { top: 0, textStyle: { color: cssVar("--text-2") } }, grid: { ...base.grid, top: 40 },
      tooltip: { ...base.tooltip, trigger: "axis", axisPointer: { type: "shadow" } },
      xAxis: axis("category", { data: keys.map((k) => k[1]) }), yAxis: axis("value", { name: "celdas" }),
      series: levels.filter((l) => l.class !== 0).map((l) => ({ type: "bar", stack: "s", name: l.label, barMaxWidth: 56,
        itemStyle: { color: HOT[l.class], borderColor: cssVar("--bg"), borderWidth: 2 },
        data: keys.map(([k]) => (c[k] || []).find((r) => r.class === l.class)?.cells || 0) })) }); } });

// ================================================================== BIODIVERSIDAD
registerPanel({ id: "div-kpis", group: "biodiversidad", width: 12, title: "Índices de diversidad alfa y completitud del inventario", needs: ["diversity"],
  render(el, I) { const s = D(I, "diversity").summary || {};
    el.innerHTML = kpiTiles([
      ["Riqueza observada (S)", fmt.n(s.S)], ["Shannon H'", fmt.d2(s.shannon_H), `Pielou J ${fmt.d2(s.pielou_J)}`],
      ["Simpson 1−D", fmt.d2(s.simpson_1_minus_D), `Inverso ${fmt.d1(s.inverse_simpson)}`],
      ["Hill q1 · q2", `${fmt.d1(s.hill_q1)} · ${fmt.d1(s.hill_q2)}`, "especies efectivas"],
      ["Chao1", fmt.n(s.chao1), `±${fmt.n(s.chao1_sd)} · completitud ${fmt.pct((s.completeness_chao1 || 0) * 100)}`],
      ["Chao2 (incidencia)", fmt.n(s.spatial_chao2), `completitud ${fmt.pct((s.spatial_completeness_chao2 || 0) * 100)}`],
      ["Singletons", fmt.n(s.singletons), `doubletons ${fmt.n(s.doubletons)}`],
      ["Cobertura de Good", fmt.pct((s.good_coverage || 0) * 100)], ["Margalef", fmt.d1(s.margalef)], ["Berger-Parker", fmt.d2(s.berger_parker), "dominancia"],
    ]); } });

registerPanel({ id: "rarefaction", group: "biodiversidad", width: 6, title: "Rarefacción (Hurlbert)", desc: "Especies esperadas según el número de registros; la línea marca Chao1", needs: ["diversity"],
  render(el, I) { const d = D(I, "diversity"), r = d.rarefaction || []; const base = baseOption();
    return makeChart(el, { ...base, tooltip: { ...base.tooltip, trigger: "axis", valueFormatter: fmt.n },
      xAxis: axis("value", { name: "registros", axisLabel: { formatter: (v) => fmt.compact(v) } }), yAxis: axis("value", { name: "especies" }),
      series: [{ type: "line", name: "E[S]", data: r.map((p) => [p.records, p.expected_species]), smooth: true, symbol: "none", lineStyle: { width: 2, color: S(1) },
        areaStyle: { opacity: 0.12, color: S(1) },
        markLine: { symbol: "none", lineStyle: { color: S(2), width: 1.5, type: "solid" }, label: { formatter: `Chao1 ${fmt.n(d.summary?.chao1)}`, color: cssVar("--text-2") }, data: [{ yAxis: d.summary?.chao1 }] } }] }); } });

registerPanel({ id: "accumulation", group: "biodiversidad", width: 6, title: "Acumulación espacial de especies", desc: "Promedio de 20 órdenes aleatorios de celdas; la línea marca Chao2", needs: ["diversity"],
  render(el, I) { const d = D(I, "diversity"), r = d.accumulation || []; const base = baseOption();
    return makeChart(el, { ...base, tooltip: { ...base.tooltip, trigger: "axis", valueFormatter: fmt.n },
      xAxis: axis("value", { name: "celdas muestreadas" }), yAxis: axis("value", { name: "especies" }),
      series: [{ type: "line", name: "Especies", data: r.map((p) => [p.cells, p.species]), smooth: true, symbol: "none", lineStyle: { width: 2, color: S(3) }, areaStyle: { opacity: 0.12, color: S(3) },
        markLine: { symbol: "none", lineStyle: { color: S(2), width: 1.5, type: "solid" }, label: { formatter: `Chao2 ${fmt.n(d.summary?.spatial_chao2)}`, color: cssVar("--text-2") }, data: [{ yAxis: d.summary?.spatial_chao2 }] } }] }); } });

registerPanel({ id: "rank-abundance", group: "biodiversidad", width: 6, title: "Curva rango-abundancia (Whittaker)", desc: "Registros por especie en escala log; clic para abrir la ficha", needs: ["diversity"],
  render(el, I, ctx) { const r = D(I, "diversity").rank_abundance || []; const base = baseOption();
    const c = makeChart(el, { ...base, tooltip: { ...base.tooltip, trigger: "item", formatter: (p) => `#${p.data[0]} <i>${esc(r[p.dataIndex].species)}</i><br>${fmt.n(p.data[1])} registros` },
      xAxis: axis("value", { name: "rango", min: 1 }), yAxis: axis("log", { name: "registros", min: 1 }),
      series: [{ type: "line", data: r.map((p) => [p.rank, p.records]), symbolSize: 6, lineStyle: { width: 2, color: S(1) }, itemStyle: { color: S(1) } }] });
    c.on("click", (p) => ctx.openSpecies(r[p.dataIndex].species)); return c; } });

registerPanel({ id: "sunburst", group: "biodiversidad", width: 6, title: "Árbol taxonómico", desc: "Reino → clase → orden → familia (tamaño = nº de especies). Clic para profundizar", needs: ["taxonomy"],
  render(el, I) { const hier = D(I, "taxonomy").hierarchy || []; const base = baseOption();
    const cols = [1, 2, 3, 4, 5, 6].map(S);
    const data = hier.map((k, i) => ({ ...k, itemStyle: { color: cols[i % cols.length] } }));
    return makeChart(el, { ...base, tooltip: { ...base.tooltip, formatter: (p) => `<b>${esc(p.name)}</b><br>${fmt.n(p.value)} especies` },
      series: [{ type: "sunburst", data, radius: ["12%", "95%"], sort: "desc", nodeClick: "rootToNode",
        itemStyle: { borderColor: cssVar("--bg"), borderWidth: 2, borderRadius: 4 },
        levels: [{}, { label: { rotate: "tangential", fontSize: 11 } }, { label: { fontSize: 10 }, itemStyle: { opacity: 0.85 } }, { label: { show: false }, itemStyle: { opacity: 0.7 } }, { label: { show: false }, itemStyle: { opacity: 0.55 } }],
        label: { color: "#fff", minAngle: 8 } }] }); },
  chartClass: "tall" });

registerPanel({ id: "classes", group: "biodiversidad", width: 6, title: "Indicador 3 · Ranking por clase taxonómica", desc: "Clic en una clase para abrirla en el catálogo", needs: ["taxonomy"],
  render(el, I, ctx) { const r = (D(I, "taxonomy").ranking || []).slice(0, 14);
    return bars(el, r.map((x) => x.class), r.map((x) => x.species), { name: "Especies", onClick: (name) => ctx.go(`#/catalog?tax_class=${encodeURIComponent(name)}`) }); },
  table: (I) => [[{ key: "class", label: "Clase" }, { key: "records", label: "Registros", num: true }, { key: "pct_records", label: "% registros", num: true }, { key: "species", label: "Especies", num: true }, { key: "families", label: "Familias", num: true }], D(I, "taxonomy").ranking || []] });

registerPanel({ id: "div-class", group: "biodiversidad", width: 12, title: "Diversidad por clase", needs: ["diversity"],
  render(el, I) { const r = D(I, "diversity").by_class || [];
    el.innerHTML = tableHTML([{ key: "class", label: "Clase" }, { key: "S", label: "Especies (S)", num: true }, { key: "N", label: "Registros", num: true },
      { key: "shannon_H", label: "Shannon H'", num: true }, { key: "simpson", label: "Simpson 1−D", num: true }, { key: "chao1", label: "Chao1", num: true }], r); } });

// ================================================================== CONSERVACIÓN
registerPanel({ id: "threat-compare", group: "conservacion", width: 6, title: "Categorías: Colombia (Res. 0126/2024) vs global (IUCN)", needs: ["threats"],
  render(el, I) { const t = D(I, "threats"); const base = baseOption();
    const cats = ["CR", "EN", "VU", "NT", "DD"];
    return makeChart(el, { ...base, legend: { top: 0, textStyle: { color: cssVar("--text-2") } }, grid: { ...base.grid, top: 36 },
      tooltip: { ...base.tooltip, trigger: "axis", axisPointer: { type: "shadow" } },
      xAxis: axis("category", { data: cats.map((c) => `${c} · ${catInfo(c).label}`), axisLabel: { interval: 0, width: 80, overflow: "break" } }), yAxis: axis("value", { name: "especies" }),
      series: [{ type: "bar", name: "Res. 0126/2024 (nacional)", data: cats.map((c) => t.national_by_category?.[c] || 0), itemStyle: { color: S(1), borderRadius: [4, 4, 0, 0] }, barMaxWidth: 22, label: { show: true, position: "top", color: cssVar("--text-2") } },
        { type: "bar", name: "IUCN (global)", data: cats.map((c) => t.global_by_category?.[c] || 0), itemStyle: { color: S(2), borderRadius: [4, 4, 0, 0] }, barMaxWidth: 22, label: { show: true, position: "top", color: cssVar("--text-2") } }] }); } });

registerPanel({ id: "pivot", group: "conservacion", width: 6, title: "Clase × categoría (nacional)", desc: "% de amenazadas = (CR+EN+VU) / especies de la clase", needs: ["taxonomy"],
  render(el, I) { const pv = D(I, "taxonomy").pivot_national; if (!pv) return;
    const cats = pv.categories.filter((c) => c !== "NE");
    el.innerHTML = tableHTML([{ key: "class", label: "Clase" }, ...cats.map((c) => ({ key: c, label: c, num: true })),
      { key: "TOTAL", label: "Total", num: true }, { key: "pct_threatened", label: "% amenazadas", num: true }], pv.rows.filter((r) => r.threatened > 0 || r.TOTAL > 20).slice(0, 25)); } });

registerPanel({ id: "g8", group: "conservacion", width: 12, title: "G8 · Evidencia GBIF vs amenaza", desc: "Cuadrantes de priorización · color = clase (3 principales + otras) · clic para abrir la ficha", needs: ["evidence_threat"],
  chartClass: "tall",
  render(el, I, ctx) { const e = D(I, "evidence_threat"), pts = e.points || [];
    if (!pts.length) { el.innerHTML = `<p class="muted">Sin categorías disponibles.</p>`; return; }
    const top = Object.entries(pts.reduce((a, p) => ((a[p.tax_class] = (a[p.tax_class] || 0) + 1), a), {})).sort((a, b) => b[1] - a[1]).slice(0, 3).map((x) => x[0]);
    const groups = [...top, "Otras"];
    const colors = [S(1), S(2), S(3), cssVar("--series-other")];
    const yLabels = { 0: "LC", 1: "NT", 1.5: "DD", 2: "VU", 3: "EN", 4: "CR", 5: "EX/EW" };
    const thr = Math.log10(e.summary?.evidence_threshold_records || 1);
    const jitter = (s) => ((s.split("").reduce((a, c) => a + c.charCodeAt(0), 0) % 100) / 100 - 0.5) * 0.3;
    const base = baseOption();
    const c = makeChart(el, { ...base, legend: { top: 0, textStyle: { color: cssVar("--text-2") } }, grid: { ...base.grid, top: 40 },
      tooltip: { ...base.tooltip, trigger: "item", formatter: (p) => { const d = p.data.raw;
        return `<b><i>${esc(d.species)}</i></b>${d.common_name ? `<br>${esc(d.common_name)}` : ""}<br>${fmt.n(d.n_records)} registros · ${d.category}<br>${esc(e.quadrants[d.quadrant])}`; } },
      xAxis: axis("log", { name: "registros GBIF (log)", min: 1 }),
      yAxis: axis("value", { name: "amenaza (ordinal)", min: -0.5, max: 5.5, interval: 0.5, axisLabel: { formatter: (v) => yLabels[v] || "" } }),
      series: groups.map((g, gi) => ({ type: "scatter", name: g, itemStyle: { color: colors[gi], borderColor: cssVar("--bg"), borderWidth: 1.5, opacity: 0.9 },
        symbolSize: (v) => 8 + Math.log10(v[0] + 1) * 5,
        data: pts.filter((p) => (gi < 3 ? p.tax_class === g : !top.includes(p.tax_class))).map((p) => ({ value: [p.n_records, p.threat_ordinal + jitter(p.species)], raw: p })),
        markLine: gi === 0 ? { symbol: "none", silent: true, lineStyle: { color: cssVar("--text-3"), width: 1, type: "solid" },
          label: { color: cssVar("--text-3"), fontSize: 11 }, data: [{ xAxis: 10 ** thr, label: { formatter: "umbral de evidencia" } }, { yAxis: 1.75, label: { formatter: "≥ VU" } }] } : undefined,
        markArea: gi === 0 ? { silent: true, itemStyle: { color: "rgba(208,59,59,.08)" }, label: { color: cssVar("--text-2"), position: "insideTopLeft" },
          data: [[{ name: "PRIORITARIO", coord: [1, 1.75] }, { coord: [10 ** thr, 5.5] }]] } : undefined })) });
    c.on("click", (p) => p.data?.raw && ctx.openSpecies(p.data.raw.species));
    return c; } });

registerPanel({ id: "priority", group: "conservacion", width: 6, title: "Especies prioritarias", desc: "Amenazadas y con poca evidencia (cuadrante superior izquierdo)", needs: ["evidence_threat"],
  render(el, I) { const p = D(I, "evidence_threat").priority_species || [];
    el.innerHTML = p.length ? `<div class="sp-chips">${p.map(speciesChip).join("")}</div>` : `<p class="muted">Ninguna especie en el cuadrante prioritario.</p>`; } });

registerPanel({ id: "threatened-list", group: "conservacion", width: 6, title: "Amenazadas a nivel nacional (Res. 0126/2024)", needs: ["threats"],
  render(el, I) { const t = D(I, "threats").threatened_national || [];
    el.innerHTML = t.length ? `<div class="sp-chips">${t.map(speciesChip).join("")}</div>` : `<p class="muted">Ninguna especie del área figura en la Resolución 0126 de 2024.</p>`;
    const g = D(I, "threats").national_stricter || [];
    if (g.length) el.innerHTML += `<h4 style="margin:14px 0 6px;font-size:13px">Amenazadas en Colombia pero no globalmente</h4><div class="sp-chips">${g.map(speciesChip).join("")}</div>`; } });

registerPanel({ id: "danger-classes", group: "conservacion", width: 6, title: "Índice compuesto de peligro · clases", desc: "0,50·amenaza + 0,30·densidad + 0,20·certeza espacial · quintiles", needs: ["danger_index"],
  render(el, I) { const d = (D(I, "danger_index").class_distribution || []).filter((r) => r.class > 0).reverse();
    return bars(el, d.map((r) => `${r.class} · ${r.label}`), d.map((r) => r.area_km2), { name: "Área (km²)", fmtVal: fmt.km2, colors: d.map((r) => DANGER[r.class]) }); } });

registerPanel({ id: "danger-contrib", group: "conservacion", width: 6, title: "Contribución de especies al componente de amenaza", desc: "peso IUCN/nacional × registros", needs: ["danger_index"],
  render(el, I, ctx) { const c = (D(I, "danger_index").species_contribution || []).slice(0, 15);
    return bars(el, c.map((r) => `${r.species} (${r.category})`), c.map((r) => r.pct), { name: "% del componente", fmtVal: fmt.pct,
      colors: c.map((r) => catInfo(r.category).color), onClick: (_n, p) => ctx.openSpecies(c[p.dataIndex].species) }); } });

registerPanel({ id: "flags", group: "conservacion", width: 12, title: "CITES, exóticas y nuevas en la lista 2024", needs: ["threats"],
  render(el, I) { const t = D(I, "threats");
    const block = (title, list) => `<div><h4 style="font-size:13px;margin-bottom:6px">${title} <span class="muted">(${(list || []).length})</span></h4><div class="sp-chips">${(list || []).slice(0, 40).map(speciesChip).join("") || `<span class="muted">—</span>`}</div></div>`;
    el.innerHTML = `<div style="display:grid;gap:16px">${block("Especies en apéndices CITES", t.cites)}${block("Exóticas (SiB)", t.exotic)}${block("Invasoras (SiB)", t.invasive)}${block("Nuevas en la Res. 0126/2024", t.new_in_2024)}</div>`; } });

// ================================================================== ESPECIES
registerPanel({ id: "rarity", group: "especies", width: 4, title: "Rareza local", desc: "Según ocupación de la grilla", needs: ["species_profiles"],
  render(el, I) { const r = D(I, "species_profiles").rarity || {}; const order = ["Registro único", "Restringida", "Intermedia", "Amplia"];
    return bars(el, order, order.map((k) => r[k] || 0), { name: "Especies" }); } });

registerPanel({ id: "aoo", group: "especies", width: 8, title: "Mayor área de ocupación (AOO, celdas 2 km)", needs: ["species_profiles"],
  render(el, I, ctx) { const w = D(I, "species_profiles").widest || [];
    return bars(el, w.map((r) => r.species), w.map((r) => r.aoo_km2), { name: "AOO", fmtVal: fmt.km2, onClick: (n) => ctx.openSpecies(n) }); },
  table: (I) => [[{ key: "species", label: "Especie" }, { key: "n_records", label: "Registros", num: true }, { key: "aoo_km2", label: "AOO km²", num: true }, { key: "eoo_km2", label: "EOO km²", num: true }, { key: "occupancy_pct", label: "% celdas", num: true }], D(I, "species_profiles").widest || []] });

for (const [id, key, title] of [["rising", "rising", "Mayor aumento reciente de registros"], ["declining", "declining", "Mayor descenso reciente de registros"]]) {
  registerPanel({ id, group: "especies", width: 6, title, desc: "Especies con ≥ 10 registros · refleja esfuerzo, no población", needs: ["species_profiles"],
    render(el, I, ctx) { const r = D(I, "species_profiles")[key] || [];
      return bars(el, r.map((x) => x.species), r.map((x) => x.trend_pct), { name: "% cambio", fmtVal: fmt.pct, color: key === "rising" ? S(3) : S(2), onClick: (n) => ctx.openSpecies(n) }); } });
}

