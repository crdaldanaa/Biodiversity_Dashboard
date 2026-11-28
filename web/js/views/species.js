// Ficha digital de especie: toda la interfaz se tiñe con la paleta extraída de su foto.
/* global deck */
import { api, applyPalette, catInfo, esc, fmt, hexToRgb, resetPalette, state, store } from "../core.js";
import { baseLayers, BASEMAPS, createDeck, fitView, flyTo, onTerrain, outlineColor, roiOutline, tid } from "../map/engine.js";
import { makeChart } from "../charts/ec.js";
import { getPeriod, inPeriod, monthlyCompareOption, onPeriod, periodPicker, yearlyCompareOption } from "../charts/period.js";
import { kdeLayer, kdeLegendHTML, kdeSurface, kdeTerrainRefresher, kdeValueAt } from "../map/kde.js";

const modal = () => document.getElementById("speciesModal");
let miniDeck = null, charts = [], prevHash = null, offPeriod = null, mapRefresh = null;

const SIB_SECTIONS = [["abstract", "Descripción"], ["distribution", "Distribución"], ["habitat", "Hábitat"],
  ["feeding", "Alimentación"], ["reproduction", "Reproducción"], ["behavior", "Comportamiento"],
  ["threats", "Amenazas"], ["conservation", "Conservación"]];
const MONTHS = ["E", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];
const LIGHT = { textColor: "rgba(255,255,255,.82)", gridColor: "rgba(255,255,255,.12)" };

export function openSpecies(name) {
  const target = `#/species/${encodeURIComponent(name)}`;
  if (location.hash !== target) { prevHash = location.hash.startsWith("#/species/") ? prevHash : location.hash; location.hash = target; }
}

export function closeSpecies() {
  location.hash = prevHash && !prevHash.startsWith("#/species/") ? prevHash : "#/catalog";
}

export async function showSpecies(name) {
  const m = modal();
  const card = m.querySelector(".modal-card");
  m.hidden = false;
  document.body.style.overflow = "hidden";
  card.innerHTML = `<div class="empty">Cargando ficha de <i>${esc(name)}</i>…</div>`;
  let d;
  try {
    d = await api.speciesDetail(state.wsId, name);
  } catch (e) {
    card.innerHTML = `<button class="fx-close" data-close aria-label="Cerrar">✕</button><div class="empty">No se pudo cargar la ficha: ${esc(e.message)}</div>`;
    bindClose(card);
    return;
  }
  const pal = d.media?.palette;
  applyPalette(pal);

  const cn = d.common_name || d.species;
  const nat = d.threat_national, glo = d.threat_global;
  const iucnYear = d.iucn?.year ? ` · ${d.iucn.year}` : "";
  const sib = d.sib || {};

  card.innerHTML = `
    <button class="fx-close" data-close aria-label="Cerrar">✕</button>
    <section class="fx-hero">
      <div class="fx-photo">${d.media?.image ? `<img src="${d.media.image}" alt="${esc(cn)}">` : `<div style="height:100%;min-height:300px;background:radial-gradient(circle at 30% 30%,var(--accent),var(--accent-dark))"></div>`}
        ${d.media?.author ? `<span class="credit">© ${esc(d.media.author)} · ${esc(d.media.license || "")} · ${esc(d.media.source || "")}</span>` : ""}</div>
      <div class="fx-head">
        <div class="eyebrow">${esc(d.tax_class || "")} · ${esc(d.family || "")}</div>
        <h2 id="spTitle">${esc(cn)}</h2>
        <div class="sci">${esc(d.species)}</div>
        <div class="tax">${[d.kingdom, d.phylum, d.tax_class, d.tax_order, d.family, d.genus].filter(Boolean).map(esc).join(" › ")}</div>
        ${d.common_names?.length > 1 ? `<div class="sp-chips">${d.common_names.slice(1, 7).map((n) => `<span class="chip">${esc(n)}</span>`).join("")}</div>` : ""}
        <div class="threat-row">
          ${threatBox("Colombia · Res. 0126/2024", nat, d.threat_national_source)}
          ${threatBox(`Global · IUCN${iucnYear}`, glo, d.iucn?.source || d.iucn_source)}
          ${d.cites ? `<div class="threat-box"><div class="src">CITES</div><div class="cat">Apéndice ${esc(d.cites)}</div></div>` : ""}
        </div>
        <div class="sp-chips">
          ${d.exotic ? `<span class="chip">Exótica</span>` : ""}${d.invasive ? `<span class="chip">Invasora</span>` : ""}
          ${d.new_in_2024 ? `<span class="chip">Nueva en la lista 2024</span>` : ""}
          ${d.rarity ? `<span class="chip">Rareza local: ${esc(d.rarity)}</span>` : ""}
        </div>
      </div>
    </section>
    <section class="fx-body">
      <div class="kpis fx-period-kpis" id="fxPeriodKpis"></div>
      <div class="kpis">
        ${kpi("Registros en el área", fmt.n(d.n_records), "todos los años")}
        ${kpi("AOO (celdas 2 km)", fmt.km2(d.aoo_km2), "Área de ocupación")}
        ${kpi("EOO local", fmt.km2(d.eoo_km2), "Polígono convexo mínimo")}
        ${kpi("Ocupación de la grilla", fmt.pct(d.occupancy_pct), `${fmt.n(d.n_cells)} celdas`)}
        ${kpi("Tendencia reciente", d.trend_pct != null ? `${d.trend_pct > 0 ? "+" : ""}${fmt.d1(d.trend_pct)}%` : "—", "≠ tendencia poblacional")}
        ${kpi("Mes pico", d.peak_month_label || "—")}
        ${kpi("Elevación", d.elev_min != null ? `${fmt.n(d.elev_min)}–${fmt.n(d.elev_max)} m` : "—", "reportada o DEM Copernicus 30 m")}
      </div>
      <div class="fx-map glass" id="fxMap">
        <div class="fx-map-ui">
          <div class="seg" role="group" aria-label="Vista del mapa">
            <button class="chip" data-v="2d">2D</button><button class="chip" data-v="3d">3D</button>
          </div>
          <div class="seg" role="group" aria-label="Capas">
            <button class="chip" data-l="heat">Calor</button><button class="chip" data-l="pts">Puntos</button><button class="chip" data-l="gbif">GBIF global</button>
          </div>
          <div class="seg" role="group" aria-label="Mapa base">${Object.entries(BASEMAPS).map(([k, b]) => `<button class="chip" data-b="${k}">${b.label}</button>`).join("")}</div>
        </div>
        <div class="fx-map-legend" id="fxLegend"></div>
      </div>
      <div class="fx-charts">
        <div class="glass fx-period" id="fxPeriod"></div>
        <div class="glass"><h3 style="font-size:13px">Registros por año</h3><div class="chart" id="fxYear" style="height:170px"></div></div>
        <div class="glass"><h3 style="font-size:13px">Estacionalidad: periodo vs totalidad <span class="muted" style="font-weight:400">(% de cada serie)</span></h3><div class="chart" id="fxMonth" style="height:170px"></div></div>
      </div>
      ${SIB_SECTIONS.some(([k]) => sib[k]) ? `<div class="fx-text glass">${SIB_SECTIONS.filter(([k]) => sib[k]).map(([k, l]) => `<div><h4>${l}</h4><p>${esc(sib[k])}</p></div>`).join("")}
        <p class="muted" style="grid-column:1/-1;font-size:11px">Fuente: Catálogo de la Biodiversidad de Colombia — SiB Colombia.</p></div>` : ""}
      <div class="fx-links">
        ${d.links?.gbif ? `<a class="btn" target="_blank" rel="noopener" href="${d.links.gbif}">GBIF</a>` : ""}
        ${d.links?.sib ? `<a class="btn" target="_blank" rel="noopener" href="${d.links.sib}">Ficha SiB Colombia</a>` : ""}
        ${d.links?.iucn ? `<a class="btn" target="_blank" rel="noopener" href="${d.links.iucn}">IUCN Red List</a>` : ""}
        <span class="muted" style="font-size:11px;align-self:center">Los registros GBIF documentan presencia, no abundancia. Categoría IUCN global; la nacional proviene de la Res. 0126 de 2024 (MADS).</span>
      </div>
    </section>`;
  bindClose(card);
  card.scrollTop = 0;
  renderCharts(d);
  renderPeriodKpis(d);
  renderMiniMap(d);
  offPeriod?.();
  offPeriod = onPeriod(() => { if (modal().hidden) return; renderCharts(d); renderPeriodKpis(d); mapRefresh?.(); });
}

// Cifras de la especie dentro del periodo seleccionado
function renderPeriodKpis(d) {
  const host = document.getElementById("fxPeriodKpis");
  const p = getPeriod(d.yearly.map((r) => r.year));
  if (!host) return;
  host.hidden = !p?.active;
  if (!p?.active) { host.innerHTML = ""; return; }
  const sum = (a, b) => d.yearly.filter((r) => r.year >= a && r.year <= b).reduce((acc, r) => acc + r.n, 0);
  const yrs = (a, b) => b - a + 1;
  const per = sum(p.from, p.to);
  const months = new Set(d.year_month.year.map((y, i) => (y >= p.from && y <= p.to ? d.year_month.month[i] : null)).filter(Boolean)).size;
  host.innerHTML = [
    kpi(`Registros ${esc(p.label)}`, fmt.n(per), `de ${fmt.n(d.n_records)} en todos los años`),
    kpi("Registros por año", fmt.d1(per / yrs(p.from, p.to)), "promedio en el periodo"),
    kpi("Meses con registros", `${fmt.n(months)} de 12`, "en el periodo"),
  ].join("");
}

function threatBox(src, code, origin) {
  const c = code ? catInfo(code) : null;
  return `<div class="threat-box"><div class="src">${esc(src)}</div>
    <div class="cat">${c ? `<i style="background:${c.color};color:${c.color}"></i>${c.code} · ${esc(c.label)}` : `<span class="muted">No listada</span>`}</div>
    ${origin ? `<div class="src" style="margin-top:4px">${esc(origin)}</div>` : ""}</div>`;
}
const kpi = (l, v, s = "") => `<div class="kpi glass"><div class="label">${l}</div><div class="value" style="font-size:22px">${v}</div>${s ? `<div class="sub">${s}</div>` : ""}</div>`;

function renderCharts(d) {
  charts.forEach((c) => c.dispose()); charts = [];
  const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent-light").trim() || "#c9fff0";
  const host = document.getElementById("fxPeriod");
  const years = [], counts = [];
  const p = getPeriod(d.yearly.map((r) => r.year));
  host.innerHTML = "";
  if (!p) { host.innerHTML = `<p class="muted" style="margin:0;font-size:12px">Sin registros fechados.</p>`; return; }
  // Solo los años en que la especie tiene registros (sin barras en cero)
  d.yearly.filter((r) => r.n > 0).sort((a, b) => a.year - b.year).forEach((r) => { years.push(r.year); counts.push(r.n); });
  host.appendChild(periodPicker(p, null, { dark: true }));
  const opt = { ...LIGHT, periodColor: accent, compact: true };
  charts.push(makeChart(document.getElementById("fxYear"), yearlyCompareOption(years, counts, p, opt)));
  const ym = d.year_month || { year: [], month: [], n: [] };
  charts.push(makeChart(document.getElementById("fxMonth"), monthlyCompareOption(ym, p, { ...opt, labels: MONTHS })));
}

function renderMiniMap(d) {
  const el = document.getElementById("fxMap");
  const lon = d.points.lon, lat = d.points.lat;
  if (!lon.length) return;
  const meta = state.workspaces.find((w) => w.id === state.wsId);
  const o = Object.assign({ view: "2d", heat: true, pts: true, gbif: false, basemap: "satellite" }, store.get("fx.map", {}));
  const pad = 0.15;
  const bb = [Math.min(...lon), Math.min(...lat), Math.max(...lon), Math.max(...lat)];
  const span = Math.max(bb[2] - bb[0], bb[3] - bb[1], 0.2);
  const bbox = lon.length > 1 ? [bb[0] - span * pad, bb[1] - span * pad, bb[2] + span * pad, bb[3] + span * pad] : meta.roi.bbox;
  const color = hexToRgb(getComputedStyle(document.documentElement).getPropertyValue("--accent-light").trim() || "#c9fff0");
  const allPts = lon.map((x, i) => ({ p: [x, lat[i]], y: d.points.year[i], id: d.points.id[i] }));
  let per = getPeriod(), pts = allPts, surfKey = "";
  const split = () => {
    per = getPeriod();
    pts = per?.active ? allPts.filter((q) => q.y && inPeriod(per, q.y)) : allPts;
  };
  split();
  const view = (v) => fitView(bbox, el, v === "3d" ? { pitch: 50, bearing: -15, padding: 40 } : { pitch: 0, bearing: 0, padding: 40 });
  let roi = null, surf = null;
  // Radio del kernel según la extensión de los registros (≈ 1/25 del lado, entre 300 m y 8 km)
  const bwM = Math.min(8000, Math.max(300, (span * 111320) / 25));
  const tipStyle = { background: "rgba(10,14,24,.9)", color: "#fff", borderRadius: "8px", fontSize: "11px", padding: "6px 8px" };
  miniDeck = createDeck(el, { initialViewState: view(o.view),
    controller: { dragRotate: o.view === "3d", touchRotate: o.view === "3d", inertia: 300 },
    getTooltip: (info) => {
      if (info.layer?.id.startsWith("sp-pts") && info.object) return { html: `${info.object.y || "s/f"} · GBIF ${info.object.id}<br><span style="opacity:.7">Clic para abrir el registro</span>`, style: tipStyle };
      if (info.layer?.id.startsWith("sp-kde") && info.bitmap) { const v = kdeValueAt(surf, info.bitmap.pixel);
        return v > 0.04 ? { html: `Probabilidad relativa de avistamiento: <b>${fmt.n(v * 100)}%</b>`, style: tipStyle } : null; }
      return null;
    },
    onClick: ({ object, layer }) => { if (layer?.id.startsWith("sp-pts") && object?.id) window.open(`https://www.gbif.org/occurrence/${object.id}`, "_blank", "noopener"); } });

  const sync = () => {
    el.querySelectorAll("[data-v]").forEach((b) => b.classList.toggle("on", b.dataset.v === o.view));
    el.querySelectorAll("[data-l]").forEach((b) => b.classList.toggle("on", !!o[b.dataset.l]));
    el.querySelectorAll("[data-b]").forEach((b) => b.classList.toggle("on", b.dataset.b === o.basemap));
    el.querySelector("#fxLegend").innerHTML = `${o.heat && pts.length ? kdeLegendHTML() : ""}
      <div class="muted" style="font-size:11px;margin-top:4px">${per?.active ? `${fmt.n(pts.length)} registros en ${esc(per.label)}` : `${fmt.n(lon.length)} registros en el área`}${o.heat && pts.length ? ` · kernel ${fmt.d1(bwM / 1000)} km` : ""}${o.gbif ? " · hexágonos: registros GBIF globales" : ""}</div>`;
  };
  const render = () => {
    store.set("fx.map", o);
    const layers = [...baseLayers({ basemap: o.basemap, terrain: o.view === "3d", exaggeration: 2, onTerrainLoad: refresher.onLoad })];
    if (o.gbif && d.gbif_key) {
      layers.push(new deck.TileLayer({ id: tid("gbif-density", o.view === "3d"), data: `https://api.gbif.org/v2/map/occurrence/density/{z}/{x}/{y}@1x.png?taxonKey=${d.gbif_key}&bin=hex&hexPerTile=48&style=classic-noborder.poly`,
        minZoom: 0, maxZoom: 14, opacity: 0.5, ...onTerrain(o.view === "3d", "drape"),
        renderSubLayers: (props) => { const [[w, s], [e, n]] = props.tile.boundingBox;
          return new deck.BitmapLayer(props, { data: null, image: props.data, bounds: [w, s, e, n] }); } }));
    }
    if (roi) layers.push(...roiOutline(roi, outlineColor(o.basemap), "mroi", o.view === "3d"));
    if (o.heat && pts.length) {
      const key = `${per?.active ? `${per.from}-${per.to}` : "all"}|${!!roi}`;
      if (!surf || key !== surfKey) { surf = kdeSurface(pts.map((q) => q.p), bbox, { bandwidthM: bwM, roi, size: 700 }); surfKey = key; }
      layers.push(kdeLayer(surf, { id: `sp-kde-${key}`, opacity: 0.85, terrain: o.view === "3d", version: refresher.version }));
    }
    if (o.pts) {
      layers.push(new deck.ScatterplotLayer({ id: tid("sp-pts", o.view === "3d"), data: pts, getPosition: (q) => q.p, radiusUnits: "pixels", getRadius: o.heat ? 3.5 : 5,
        stroked: true, lineWidthUnits: "pixels", getLineWidth: 1.2, getLineColor: [10, 14, 24, 230], getFillColor: o.heat ? [255, 255, 255, 235] : color, pickable: true,
        updateTriggers: { getRadius: [o.heat], getFillColor: [o.heat] }, ...onTerrain(o.view === "3d") }));
    }
    miniDeck?.setProps({ layers });
    sync();
  };
  const refresher = kdeTerrainRefresher(() => render());
  el.querySelector(".fx-map-ui").onclick = (e) => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.v && b.dataset.v !== o.view) {
      o.view = b.dataset.v;
      miniDeck.setProps({ controller: { dragRotate: o.view === "3d", touchRotate: o.view === "3d", inertia: 300 } });
      flyTo(miniDeck, view(o.view), 900);
    }
    if (b.dataset.l) o[b.dataset.l] = !o[b.dataset.l];
    if (b.dataset.b) o.basemap = b.dataset.b;
    render();
  };
  el.querySelector('[data-l="gbif"]').hidden = !d.gbif_key;
  mapRefresh = () => { split(); render(); };
  render();
  api.roi(state.wsId).then((r) => { roi = r; surf = null; render(); });
}

function bindClose(card) {
  card.querySelectorAll("[data-close]").forEach((b) => { b.onclick = closeSpecies; });
  modal().querySelector(".modal-backdrop").onclick = closeSpecies;
}

export function hideSpecies() {
  const m = modal();
  if (m.hidden) return;
  m.hidden = true;
  document.body.style.overflow = "";
  charts.forEach((c) => c.dispose()); charts = [];
  if (miniDeck) { miniDeck.finalize(); miniDeck = null; }
  offPeriod?.(); offPeriod = null; mapRefresh = null;
  resetPalette();
}

document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modal().hidden) closeSpecies(); });
