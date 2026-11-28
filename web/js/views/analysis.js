// Vista de análisis: pestañas por grupo, paneles interactivos con vista de tabla y notas metodológicas.
import { api, esc, state, store } from "../core.js";
import { GROUPS, PANELS, tableHTML } from "../charts/panels.js";
import { getPeriod, onPeriod, periodParams } from "../charts/period.js";
import { openSpecies } from "./species.js";

export const title = "Análisis";
let charts = [], offPeriod = null, mountToken = 0;

// Indicadores del periodo (recalculados en el servidor). La serie temporal se toma completa
// para que los gráficos por año y estacionalidad muestren el periodo dentro de toda la historia.
async function loadSet(ws) {
  const base = await api.analysis(ws);
  const p = getPeriod();
  if (!p?.active) return { base, I: base.indicators, p };
  const P = await api.analysis(ws, periodParams(p));
  return { base, I: { ...P.indicators, temporal: base.indicators.temporal }, p, empty: !!P.empty };
}

export async function mount(el) {
  if (!state.wsId) { el.innerHTML = `<div class="empty glass">Crea o selecciona un área de interés.</div>`; return; }
  const token = ++mountToken;
  const p0 = getPeriod();
  el.innerHTML = `<div class="empty">${p0?.active ? `Recalculando indicadores para ${esc(p0.label)}… (la primera vez tarda unos segundos)` : "Cargando indicadores…"}</div>`;
  let set;
  try { set = await loadSet(state.wsId); } catch (e) {
    if (token === mountToken) el.innerHTML = `<div class="empty glass">El análisis aún no está disponible (${esc(e.message)}).</div>`; return;
  }
  if (token !== mountToken) return;
  offPeriod?.(); offPeriod = onPeriod(() => mount(el));
  const { I, base: analysis, p } = set;
  let group = store.get("analysis.tab", "resumen");
  const ctx = { openSpecies, go: (h) => { location.hash = h; }, refresh: () => renderGroup() };

  el.innerHTML = `
    ${p?.active ? `<div class="period-banner glass"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>
      <span>Indicadores del periodo <b>${esc(p.label)}</b>${set.empty ? " · <b>sin registros en este periodo</b>" : ""}</span>
      <span class="muted">Registros por año y estacionalidad muestran la serie completa.</span></div>` : ""}
    <div class="tabs" role="tablist">${GROUPS.map(([k, l]) => `<button role="tab" data-g="${k}">${l}</button>`).join("")}</div>
    <div class="panels" id="panels"></div>
    <div class="section-title"><span class="muted" style="font-size:12px">Generado ${esc(new Date(analysis.generated_at).toLocaleString("es-CO"))}</span>
      <div class="row">
        <a class="btn sm" href="${api.exportUrl(state.wsId, "analysis.json")}">Indicadores JSON</a>
        <a class="btn sm" href="${api.exportUrl(state.wsId, "species.csv")}">Especies CSV</a>
        <a class="btn sm" href="${api.exportUrl(state.wsId, "occurrences.csv")}">Ocurrencias CSV</a>
        <a class="btn sm" href="${api.exportUrl(state.wsId, "grid.gpkg")}">Grilla GPKG</a>
        <a class="btn sm" href="${api.exportUrl(state.wsId, "grid.geojson")}">Grilla GeoJSON</a>
      </div></div>`;

  const renderGroup = () => {
    charts.forEach((c) => c?.dispose?.()); charts = [];
    el.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.g === group));
    const host = el.querySelector("#panels");
    host.innerHTML = "";
    PANELS.filter((p) => p.group === group && (!p.when || p.when(ctx))).forEach((p) => {
      const ready = p.needs.every((n) => I[n]?.ok);
      const failed = p.needs.map((n) => I[n]).filter((x) => x && !x.ok);
      const card = document.createElement("section");
      card.className = `panel glass w${p.width}`;
      card.innerHTML = `<header><div><h3>${esc(p.title)}</h3>${p.desc ? `<div class="desc">${esc(p.desc)}</div>` : ""}</div>
        ${p.table ? `<button class="btn sm table-toggle" aria-pressed="false">Tabla</button>` : ""}</header>
        <div class="chart ${p.chartClass || ""}"></div><div class="tbl-host" hidden></div><div class="notes"></div>`;
      host.appendChild(card);
      const body = card.querySelector(".chart");
      if (!ready) { body.innerHTML = `<p class="muted">${failed.length ? `Error: ${esc(failed[0].error)}` : "Indicador no calculado."}</p>`; body.style.height = "auto"; return; }
      const out = p.render(body, I, ctx);
      if (out) charts.push(...(Array.isArray(out) ? out : [out]));
      if (!out) body.style.height = "auto";
      // Notas metodológicas del indicador principal (una vez por indicador y pestaña)
      const main = I[p.needs[0]]?.data || {};
      if (main.disclaimer && !host.dataset[`d_${p.needs[0]}`]) {
        host.dataset[`d_${p.needs[0]}`] = "1";
        card.querySelector(".notes").innerHTML = `<p class="warn">${esc(main.disclaimer)}</p>`;
      }
      if (p.table) {
        const btn = card.querySelector(".table-toggle"), tbl = card.querySelector(".tbl-host");
        btn.onclick = () => {
          const show = tbl.hidden;
          if (show && !tbl.innerHTML) { const [cols, rows] = p.table(I); tbl.innerHTML = tableHTML(cols, rows); }
          tbl.hidden = !show; body.hidden = show; btn.setAttribute("aria-pressed", String(show));
          btn.textContent = show ? "Gráfico" : "Tabla";
        };
      }
    });
    host.querySelectorAll("[data-sp]").forEach((b) => { b.onclick = () => openSpecies(b.dataset.sp); });
  };
  el.querySelector(".tabs").onclick = (e) => {
    const b = e.target.closest("[data-g]"); if (!b) return;
    group = b.dataset.g; store.set("analysis.tab", group); renderGroup();
  };
  renderGroup();
}

export function unmount() { mountToken++; offPeriod?.(); offPeriod = null; charts.forEach((c) => c?.dispose?.()); charts = []; }
