// Mapa 3D inmersivo: terreno real, grilla extruida (riqueza, densidad, peligro, hotspots),
// mapa de calor de avistamientos (KDE drapeado sobre el relieve), puntos por categoría de amenaza,
// línea de tiempo animada y órbita cinemática.
/* global deck */
import { api, catInfo, DANGER, DANGER_LABELS, esc, fmt, HEAT, HOT, hexToRgb, rampColor, state, store } from "../core.js";
import { baseLayers, BASEMAPS, createDeck, fitView, onTerrain, outlineColor, roiOutline, tid } from "../map/engine.js";
import { kdeLayer, kdeLegendHTML, kdeSurface, kdeTerrainRefresher, kdeValueAt } from "../map/kde.js";
import { getPeriod, onPeriod, periodParams, setPeriod } from "../charts/period.js";
import { openSpecies } from "./species.js";

const METRICS = {
  species: { label: "Riqueza (especies)", get: (p) => p.species, ramp: HEAT },
  records: { label: "Registros", get: (p) => p.records, ramp: HEAT, log: true },
  density_km2: { label: "Densidad (reg/km²)", get: (p) => p.density_km2, ramp: HEAT, log: true },
  threatened_species: { label: "Especies amenazadas", get: (p) => p.threatened_species, ramp: HEAT },
  shannon: { label: "Diversidad Shannon H'", get: (p) => p.shannon ?? 0, ramp: HEAT },
  danger_index: { label: "Índice de peligro", get: (p) => p.danger_index ?? 0, classes: "danger" },
  hot_richness: { label: "Hotspots de riqueza (Gi*)", get: (p) => p.gi_richness ?? 0, classes: "hot" },
  hot_threatened: { label: "Hotspots de amenazadas (Gi*)", get: (p) => p.gi_threatened ?? 0, classes: "hot" },
};

let deckgl = null, raf = null, playTimer = null, cleanup = [];
const toObjs = (pts) => pts.lon.map((lon, i) => ({ p: [lon, pts.lat[i]], y: pts.year[i], s: pts.species[pts.sp[i]], t: pts.threat[pts.sp[i]] || "NE" }));

export const title = "Mapa";

export async function mount(el) {
  const ws = state.wsId;
  if (!ws) { el.innerHTML = `<div class="empty glass">Crea o selecciona un área de interés para ver el mapa.</div>`; return; }
  el.classList.add("full");
  el.innerHTML = `
    <div class="map-stage" id="stage"></div>
    <div class="map-ui">
      <div class="map-kpis" id="mapKpis"></div>
      <aside class="map-ctrl glass" aria-label="Capas del mapa">
        <h3>Mapa base</h3>
        <div class="seg" id="basemaps"></div>
        <label class="toggle">Relieve 3D <input type="checkbox" id="terrain"></label>
        <label class="field">Exageración vertical <input type="range" id="exag" min="1" max="4" step="0.5"></label>
        <h3>Capas</h3>
        <label class="toggle">Grilla 3D <input type="checkbox" id="lGrid"></label>
        <label class="field"><span class="sr-only">Variable de la grilla</span><select id="metric"></select></label>
        <label class="toggle">Mapa de calor de avistamientos <input type="checkbox" id="lHeat"></label>
        <label class="field" id="bwField">Radio de suavizado: <b id="bwVal"></b><input type="range" id="bw" min="250" max="10000" step="250"></label>
        <label class="toggle">Puntos por amenaza <input type="checkbox" id="lPts"></label>
        <h3>Filtros</h3>
        <label class="toggle">Solo especies amenazadas <input type="checkbox" id="onlyThr"></label>
        <p class="muted filter-note" id="filterNote"></p>
        <h3>Especie</h3>
        <label class="field"><span class="sr-only">Filtrar por especie</span>
          <input id="spFilter" list="spList" placeholder="Buscar especie…" autocomplete="off"></label>
        <datalist id="spList"></datalist>
        <h3>Cámara</h3>
        <div class="seg">
          <button class="btn sm" id="orbit">Órbita</button>
          <button class="btn sm" id="reset">Encuadrar</button>
          <button class="btn sm" id="top">Cenital</button>
        </div>
        <p class="muted" style="font-size:11px;margin:12px 0 0" id="attrib"></p>
      </aside>
      <div class="map-legend glass" id="legend"></div>
      <div class="cell-panel glass" id="cellPanel" hidden></div>
      <div class="timeline glass">
        <button class="btn primary play" id="play" title="Animar en el tiempo" aria-label="Animar en el tiempo">▶</button>
        <div class="years"><span id="yFrom"></span><div class="bars" id="yBars" title="Clic: un año · Mayús+clic: ampliar el periodo · doble clic: todos los años"></div><span id="yTo"></span></div>
        <span class="chip" id="yLabel">Todos los años</span>
        <span class="chip loading-chip" id="pLoading" hidden>Recalculando periodo…</span>
      </div>
    </div>`;

  const opts = Object.assign({ basemap: "satellite", terrain: true, exag: 2, grid: false, metric: "species",
    pts: true, heat: true, bw: null, onlyThr: false }, store.get("map.opts.v2", {}));
  const $ = (id) => el.querySelector(`#${id}`);

  const [analysis, grid, roi, pts] = await Promise.all([api.analysis(ws), api.grid(ws), api.roi(ws), api.points(ws, { limit: 80000 })]);
  const ind = analysis.indicators;
  // Periodo global: puntos, grilla e indicadores del periodo
  let per = getPeriod(), perPts = null, perGrid = null, perOv = null, playRange = null, loadTok = 0;
  const meta = state.workspaces.find((w) => w.id === ws);
  const cellSize = ind.spatial_grid?.data?.summary?.cell_size_m || 2000;
  // Radio por defecto ≈ lado del área / 40 (p. ej. 12.000 km² → ~2,75 km), entre 0,5 y 10 km
  if (!opts.bw) opts.bw = Math.min(10000, Math.max(500, Math.round((Math.sqrt(meta?.area_km2 || 400) * 1000) / 40 / 250) * 250));
  const THR = ["CR", "EN", "VU"];
  let surf = null, surfKey = "";

  // Puntos → objetos (una vez) para deck.gl
  const allPts = toObjs(pts);
  // Línea de tiempo y animación: solo los años con registros
  const yearly = (ind.temporal?.data?.yearly || []).filter((r) => r.year && r.records > 0);
  const years = yearly.map((r) => r.year);
  let speciesSel = null;
  const occAll = grid.features.filter((f) => f.properties.records > 0);
  let occupied = occAll;

  // UI inicial
  $("basemaps").innerHTML = Object.entries(BASEMAPS).map(([k, b]) => `<button class="chip ${k === opts.basemap ? "on" : ""}" data-b="${k}">${b.label}</button>`).join("");
  $("metric").innerHTML = Object.entries(METRICS).map(([k, m]) => `<option value="${k}">${m.label}</option>`).join("");
  $("spList").innerHTML = pts.species.map((s) => `<option value="${esc(s)}">`).join("");
  Object.assign($("terrain"), { checked: opts.terrain }); $("exag").value = opts.exag;
  $("lGrid").checked = opts.grid; $("metric").value = opts.metric; $("bw").value = opts.bw;
  $("lPts").checked = opts.pts; $("lHeat").checked = opts.heat; $("onlyThr").checked = opts.onlyThr;

  const ov = ind.overview?.data?.summary || {};
  function renderKpis() {
    const act = per?.active && perOv;
    const cur = act ? perOv : ov;
    
    $("mapKpis").innerHTML = [
      ["Especies", fmt.n(cur.species), ""], ["Registros", fmt.compact(cur.records), ""],
      ["Amenazadas", fmt.n(cur.threatened_any), ""],
      act ? ["Periodo", per.label, ""] : ["Área", fmt.km2(meta?.area_km2), ""],
    ].map(([l, v, sb]) => `<div class="kpi glass"><div class="label">${l}</div><div class="value">${v}</div>${sb}</div>`).join("");
  }
  renderKpis();

  // Línea de tiempo (conteos reales por año, no la muestra de puntos)
  const byYear = yearly.map((r) => r.records);
  const maxY = Math.max(1, ...byYear);
  $("yFrom").textContent = years[0] ?? ""; $("yTo").textContent = years.at(-1) ?? "";
  $("yBars").innerHTML = years.map((y, i) => `<span data-y="${y}" style="height:${Math.max(6, (byYear[i] / maxY) * 100)}%" title="${y}: ${fmt.n(byYear[i])} registros"></span>`).join("");
  function paintTimeline() {
    const r = playRange || (per?.active ? [per.from, per.to] : null);
    $("yBars").querySelectorAll("span").forEach((sp) => { const y = +sp.dataset.y;
      const inR = !!r && y >= r[0] && y <= r[1];
      sp.classList.toggle("off", !!r && !inR); });
    $("yLabel").textContent = playRange ? (playRange[0] === playRange[1] ? `Año ${playRange[0]}` : `${playRange[0]}–${playRange[1]}`) : per?.label ?? "Todos los años";
  }

  async function loadPeriod() {
    const tok = ++loadTok;
    per = getPeriod();
    paintTimeline();
    if (!per?.active) { perPts = perGrid = perOv = null; occupied = occAll; renderKpis(); render(); return; }
    $("pLoading").hidden = false;
    try {
      const [aP, gP, pP] = await Promise.all([
        api.analysis(ws, periodParams(per)), api.grid(ws, periodParams(per)),
        api.points(ws, { ...periodParams(per), limit: 80000 }),
      ]);
      if (tok !== loadTok) return;
      perOv = aP.indicators?.overview?.data?.summary || { records: 0, species: 0, threatened_any: 0 };
      perPts = toObjs(pP);
      perGrid = gP; occupied = gP.features.filter((f) => f.properties.records > 0);
    } catch (e) { console.error(e); }
    finally { if (tok === loadTok) $("pLoading").hidden = true; }
    renderKpis(); render();
  }

  const framing = () => (el.clientWidth > 1100
    ? { padding: { left: 460, right: 320, top: 150, bottom: 170 } } : { padding: 40 });
  const vs0 = fitView(meta.roi.bbox, el, framing());
  let viewState = { ...vs0 };
  deckgl = createDeck($("stage"), {
    initialViewState: vs0,
    onViewStateChange: ({ viewState: v }) => { viewState = v; },
    getTooltip: (info) => tooltip(info) || heatTooltip(info),
    onClick: (info) => { if (info.layer?.id.startsWith("grid") && info.object) showCell(info.object); },
  });

  const keep = (d) => (!opts.onlyThr || THR.includes(d.t)) && (speciesSel === null || d.s === speciesSel);
  function filteredPts() {
    if (playRange) return allPts.filter((d) => d.y >= playRange[0] && d.y <= playRange[1] && keep(d));
    if (per?.active && !perPts) return allPts.filter((d) => d.y >= per.from && d.y <= per.to && keep(d));  // mientras carga
    return (per?.active ? perPts : allPts).filter(keep);
  }
  const gridCells = () => (opts.onlyThr ? occupied.filter((f) => f.properties.threatened_species > 0) : occupied);

  function heatSurface(data) {
    const key = `${playRange}|${per?.active ? `${per.from}-${per.to}` : "all"}|${opts.onlyThr}|${speciesSel}|${opts.bw}|${data.length}`;
    if (key !== surfKey) {
      surf = data.length ? kdeSurface(data.map((d) => d.p), meta.roi.bbox, { bandwidthM: opts.bw, roi }) : null;
      surfKey = key;
    }
    return surf;
  }

  function metricScale(key) {
    const m = METRICS[key];
    const vals = occupied.map((f) => m.get(f.properties)).filter((v) => v > 0);
    const max = Math.max(1e-9, ...vals.map((v) => (m.log ? Math.log1p(v) : v)));
    const norm = (v) => (v > 0 ? (m.log ? Math.log1p(v) : v) / max : 0);
    return { m, norm, max: Math.max(0, ...vals) };
  }

  const refresher = kdeTerrainRefresher(() => { if (deckgl && opts.heat && opts.terrain) render(); });
  function render() {
    store.set("map.opts.v2", opts);
    const layers = [...baseLayers({ basemap: opts.basemap, terrain: opts.terrain, exaggeration: opts.exag, onTerrainLoad: refresher.onLoad })];
    layers.push(...roiOutline(roi, outlineColor(opts.basemap), "roi", opts.terrain));
    const height = cellSize * 7;
    if (opts.grid) {
      const { m, norm } = metricScale(opts.metric);
      const colorOf = (p) => {
        if (m.classes === "danger") return hexToRgb(DANGER[p.danger_class ?? 0], 225);
        if (m.classes === "hot") return hexToRgb(HOT[String(opts.metric === "hot_richness" ? p.hot_richness : p.hot_threatened) ?? "0"] || HOT[0], 225);
        return rampColor(norm(m.get(p)), m.ramp, 225);
      };
      const elevOf = (p) => {
        if (m.classes === "danger") return (p.danger_index ?? 0) * height;
        if (m.classes === "hot") return Math.max(0, m.get(p)) / 4 * height;
        return norm(m.get(p)) * height;
      };
      layers.push(new deck.GeoJsonLayer({
        id: tid("grid", opts.terrain), data: { type: "FeatureCollection", features: gridCells() }, pickable: true, autoHighlight: true,
        highlightColor: [255, 255, 255, 90], extruded: true, wireframe: false, filled: true, stroked: false,
        getFillColor: (f) => colorOf(f.properties), getElevation: (f) => elevOf(f.properties), elevationScale: 1,
        material: { ambient: 0.55, diffuse: 0.7, shininess: 48, specularColor: [255, 255, 255] },
        transitions: { getElevation: { duration: 900, enter: () => [0] }, getFillColor: 600 },
        updateTriggers: { getFillColor: [opts.metric], getElevation: [opts.metric] }, opacity: opts.heat ? 0.75 : 1,
        ...onTerrain(opts.terrain, "offset"),
      }));
    }
    const data = filteredPts();
    if (opts.heat) {
      const sf = heatSurface(data);
      // Bajo la grilla extruida para no taparla; sobre el terreno en 2D y 3D
      if (sf) layers.splice(opts.grid ? layers.length - 1 : layers.length, 0, kdeLayer(sf, { opacity: opts.grid ? 0.7 : 0.88, terrain: opts.terrain, version: refresher.version }));
    }
    if (opts.pts) {
      layers.push(new deck.ScatterplotLayer({
        id: tid("pts", opts.terrain), data, getPosition: (d) => d.p, pickable: true, radiusUnits: "pixels", stroked: true,
        getRadius: (d) => (THR.includes(d.t) ? 6 : opts.heat ? 1.8 : 2.6), lineWidthUnits: "pixels", getLineWidth: (d) => (THR.includes(d.t) ? 1.5 : 0),
        getLineColor: [255, 255, 255, 220],
        getFillColor: (d) => hexToRgb(catInfo(d.t).color, THR.includes(d.t) ? 255 : opts.heat ? 120 : 170),
        updateTriggers: { getFillColor: [state.config, opts.heat], getRadius: [opts.heat] }, ...onTerrain(opts.terrain),
      }));
    }
    deckgl.setProps({ layers });
    $("bwField").hidden = !opts.heat;
    $("bwVal").textContent = `${fmt.d1(opts.bw / 1000)} km`;
    const nSp = new Set(data.map((d) => d.s)).size;
    const totRec = per?.active && perOv ? perOv.records : ov.records;
    $("filterNote").textContent = `${fmt.n(data.length)} registros · ${fmt.n(nSp)} especies visibles`
      + (per?.active ? ` · ${per.label}` : "")
      + (opts.onlyThr ? ` · ${fmt.n(gridCells().length)} celdas con amenazadas` : "")
      + (!playRange && data.length < (totRec || 0) && !opts.onlyThr && speciesSel === null ? ` (muestra de ${fmt.n(data.length)} de ${fmt.n(totRec)})` : "");
    $("attrib").textContent = `${BASEMAPS[opts.basemap].attribution}${opts.terrain ? " · Relieve: AWS Terrain Tiles" : ""} · Datos: GBIF.org`;
    renderLegend();
  }

  function renderLegend() {
    const m = METRICS[opts.metric];
    const what = `${opts.onlyThr ? "registros de especies amenazadas" : "registros"}${speciesSel !== null ? ` de <i>${esc(speciesSel)}</i>` : ""}`;
    let html = !opts.heat ? "" : `<h3 style="font-size:13px;margin-bottom:6px">Mapa de calor de avistamientos</h3>${kdeLegendHTML()}
        <p class="muted" style="font-size:11px;margin:6px 0 10px">Densidad kernel gaussiana de ${what}${playRange || per?.active ? ` (${esc($("yLabel").textContent)})` : ""}, radio ${fmt.d1(opts.bw / 1000)} km.</p>`;
    if (opts.grid || !opts.heat) html += `<h3 style="font-size:13px;margin-bottom:6px">${opts.grid ? esc(m.label) : "Puntos por categoría"}</h3>`;
    if (opts.grid && m.classes === "danger") {
      html += `<div class="legend">${[5, 4, 3, 2, 1].map((k) => `<span><i style="background:${DANGER[k]}"></i>${k} · ${DANGER_LABELS[k]}</span>`).join("")}</div>
        <p class="muted" style="font-size:11px;margin:8px 0 0">Altura = índice continuo (0–1). Índice didáctico: requiere validación de campo.</p>`;
    } else if (opts.grid && m.classes === "hot") {
      html += `<div class="legend">${[["3", "Hotspot 99%"], ["2", "Hotspot 95%"], ["1", "Hotspot 90%"], ["0", "No significativo"], ["-2", "Coldspot 95%"]].map(([k, l]) => `<span><i style="background:${HOT[k]}"></i>${l}</span>`).join("")}</div>`;
    } else if (opts.grid) {
      const { max } = metricScale(opts.metric);
      html += `<div class="ramp" style="background:linear-gradient(90deg,${m.ramp.join(",")})"></div>
        <div class="ramp-labels"><span>0</span><span>${m.log ? "escala log · " : ""}${fmt.d1(max)}</span></div>
        <p class="muted" style="font-size:11px;margin:8px 0 0">Celdas de ${fmt.d1(cellSize / 1000)} km · altura ∝ valor. Grilla calculada con ${per?.active && perGrid ? `los registros de ${esc(per.label)}` : "todos los años"}.</p>`;
    }
    if (opts.pts) {
      html += `<div class="legend" style="margin-top:10px">${["CR", "EN", "VU", "NT", "LC", "DD", "NE"].map((c) => `<span><i style="background:${catInfo(c).color};border-radius:50%"></i>${c}</span>`).join("")}</div>`;
    }
    html += `<p class="muted" style="font-size:11px;margin:8px 0 0">Concentración de registros ≠ abundancia: refleja también esfuerzo de observación.</p>`;
    $("legend").innerHTML = html;
  }

  function tooltip({ object, layer }) {
    if (!object || !layer) return null;
    const style = { background: "rgba(10,14,24,.88)", color: "#fff", borderRadius: "12px", padding: "10px 12px", fontSize: "12px", border: "1px solid rgba(255,255,255,.15)", backdropFilter: "blur(10px)" };
    if (layer.id.startsWith("grid")) {
      const p = object.properties;
      return { style, html: `<b>Celda ${esc(p.cell_id)}</b><br>${fmt.n(p.records)} registros · ${fmt.n(p.species)} especies<br>
        ${fmt.n(p.threatened_species)} amenazadas · ${fmt.d2(p.density_km2)} reg/km²<br>
        Peligro: ${p.danger_class ? `${p.danger_class} · ${DANGER_LABELS[p.danger_class]}` : "—"} · Shannon ${fmt.d2(p.shannon)}<br><span style="opacity:.7">Clic para detalle</span>` };
    }
    if (layer.id.startsWith("pts")) {
      return { style, html: `<b><i>${esc(object.s)}</i></b><br>${object.y || "s/f"} · ${esc(catInfo(object.t).label)}` };
    }
    return null;
  }
  function heatTooltip(info) {
    if (!info.layer?.id.startsWith("kde") || !info.bitmap) return null;
    const v = kdeValueAt(surf, info.bitmap.pixel);
    if (v === null || v < 0.04) return null;
    const lvl = v > 0.75 ? "Muy alta" : v > 0.5 ? "Alta" : v > 0.25 ? "Media" : v > 0.1 ? "Baja" : "Muy baja";
    return { style: { background: "rgba(10,14,24,.88)", color: "#fff", borderRadius: "12px", padding: "8px 10px", fontSize: "12px" },
      html: `Probabilidad relativa de avistamiento: <b>${lvl}</b> (${fmt.n(v * 100)}%)` };
  }

  function showCell(f) {
    const p = f.properties;
    const coords = f.geometry.type === "Polygon" ? f.geometry.coordinates[0] : f.geometry.coordinates.flat(1);
    const xs = coords.map((c) => c[0]), ys = coords.map((c) => c[1]);
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const counts = new Map();
    filteredPts().forEach((d) => { if (d.p[0] >= x0 && d.p[0] <= x1 && d.p[1] >= y0 && d.p[1] <= y1) counts.set(d.s, (counts.get(d.s) || 0) + 1); });
    const top = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12);
    const panel = $("cellPanel");
    panel.hidden = false;
    panel.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center"><h3 style="font-size:15px">Celda ${esc(p.cell_id)}${per?.active ? ` · ${esc(per.label)}` : ""}</h3>
      <button class="btn sm" data-close>✕</button></div>
      <div class="kpis" style="grid-template-columns:repeat(2,1fr);margin-top:10px">
        ${[["Registros", fmt.n(p.records)], ["Especies", fmt.n(p.species)], ["Amenazadas", fmt.n(p.threatened_species)],
           ["Índice peligro", p.danger_index != null ? fmt.d2(p.danger_index) : "—"], ["Shannon H'", fmt.d2(p.shannon)], ["Área", fmt.km2(p.area_km2)]]
          .map(([l, v]) => `<div class="kpi glass"><div class="label">${l}</div><div class="value" style="font-size:20px">${v}</div></div>`).join("")}
      </div>
      <h3 style="font-size:12px;margin:14px 0 6px;color:var(--text-3);text-transform:uppercase;letter-spacing:.1em">Especies con más registros</h3>
      <div class="sp-chips">${top.map(([s, n]) => `<button class="chip sp-link" data-sp="${esc(s)}"><i>${esc(s)}</i> · ${n}</button>`).join("")}</div>`;
    panel.querySelector("[data-close]").onclick = () => { panel.hidden = true; };
    panel.querySelectorAll("[data-sp]").forEach((b) => { b.onclick = () => openSpecies(b.dataset.sp); });
  }

  // Eventos
  const on = (node, ev, fn) => { node.addEventListener(ev, fn); cleanup.push(() => node.removeEventListener(ev, fn)); };
  on($("basemaps"), "click", (e) => { const b = e.target.closest("[data-b]"); if (!b) return; opts.basemap = b.dataset.b;
    $("basemaps").querySelectorAll(".chip").forEach((c) => c.classList.toggle("on", c === b)); render(); });
  on($("terrain"), "change", (e) => { opts.terrain = e.target.checked; render(); });
  on($("exag"), "change", (e) => { opts.exag = Number(e.target.value); render(); });
  [["lGrid", "grid"], ["lPts", "pts"], ["lHeat", "heat"], ["onlyThr", "onlyThr"]].forEach(([id, k]) =>
    on($(id), "change", (e) => { opts[k] = e.target.checked; render(); }));
  on($("bw"), "input", (e) => { $("bwVal").textContent = `${fmt.d1(+e.target.value / 1000)} km`; });
  on($("bw"), "change", (e) => { opts.bw = Number(e.target.value); render(); });
  on($("metric"), "change", (e) => { opts.metric = e.target.value; opts.grid = true; $("lGrid").checked = true; render(); });
  on($("spFilter"), "change", (e) => { speciesSel = pts.species.includes(e.target.value) ? e.target.value : null; render(); });
  on($("reset"), "click", () => deckgl.setProps({ initialViewState: { ...fitView(meta.roi.bbox, el, framing()), transitionDuration: 1500, transitionInterpolator: new deck.FlyToInterpolator() } }));
  on($("top"), "click", () => deckgl.setProps({ initialViewState: { ...viewState, pitch: 0, bearing: 0, transitionDuration: 1200 } }));
  on($("orbit"), "click", (e) => {
    if (raf) { cancelAnimationFrame(raf); raf = null; e.target.classList.remove("primary"); return; }
    e.target.classList.add("primary");
    const step = () => { viewState = { ...viewState, bearing: (viewState.bearing + 0.12) % 360, pitch: Math.max(viewState.pitch, 50) };
      deckgl.setProps({ initialViewState: viewState }); raf = requestAnimationFrame(step); };
    step();
  });
  // La línea de tiempo fija el periodo global (también filtra análisis, catálogo y fichas)
  on($("yBars"), "click", (e) => { const sp = e.target.closest("[data-y]"); if (!sp) return; const y = +sp.dataset.y;
    if (e.shiftKey && per?.active) setPeriod({ from: Math.min(per.from, y), to: Math.max(per.to, y) });
    else setPeriod({ from: y, to: y }); });
  on($("yBars"), "dblclick", () => { if (per) setPeriod({ from: per.lo, to: per.hi }); });
  cleanup.push(onPeriod(() => loadPeriod()));
  // La animación recorre los años con la muestra completa sin tocar el periodo global
  const setYears = (r) => { playRange = r; paintTimeline(); render(); };
  on($("play"), "click", (e) => {
    if (playTimer) { clearInterval(playTimer); playTimer = null; e.target.textContent = "▶"; return; }
    e.target.textContent = "❚❚";
    let i = 0;
    const tick = () => { if (i >= years.length) { clearInterval(playTimer); playTimer = null; e.target.textContent = "▶"; setYears(null); return; }
      setYears([years[0], years[i]]); i += 1; };
    tick(); playTimer = setInterval(tick, 450);
  });

  render();
  loadPeriod();
}

export function unmount(el) {
  cleanup.forEach((fn) => fn()); cleanup = [];
  if (raf) cancelAnimationFrame(raf); raf = null;
  if (playTimer) clearInterval(playTimer); playTimer = null;
  if (deckgl) { deckgl.finalize(); deckgl = null; }
  el.classList.remove("full");
}
