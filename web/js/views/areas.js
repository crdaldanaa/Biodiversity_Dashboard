// Áreas de interés: crear (subir archivo o dibujar polígono), seguir el progreso y gestionar workspaces.
/* global deck */
import { api, esc, fmt, setState, state, toast } from "../core.js";
import { baseLayers, createDeck } from "../map/engine.js";

export const title = "Áreas de interés";
let drawDeck = null, file = null, verts = [], closed = false;

const STEP_LABEL = { ingest: "Descargando y recortando registros", enrich: "Enriqueciendo especies (Res. 0126 · IUCN · SiB)", analyze: "Calculando indicadores" };

export function mount(el) {
  const cfg = state.config || {};
  el.innerHTML = `
    <div class="areas-grid">
      <section class="create-card glass" aria-labelledby="newTitle">
        <div><h2 id="newTitle" style="font-size:20px">Nueva área de interés</h2>
          <p class="soft" style="margin:4px 0 0">Sube un polígono o dibújalo. Se descargan los registros GBIF, se cruzan con la Resolución 0126 de 2024, la Lista Roja IUCN y el Catálogo del SiB Colombia, y se calculan todos los indicadores.</p></div>
        <div class="row">
          <label class="field" style="flex:2 1 220px">Nombre<input id="name" placeholder="Ej. Corredor Meta–Guaviare" maxlength="120"></label>
          <label class="field" style="flex:1 1 180px">Fuente de datos
            <select id="mode"><option value="fast">Rápido · API GBIF (sin credenciales)</option>
              <option value="full" ${cfg.gbif_credentials ? "" : "disabled"}>Completo · descarga GBIF con DOI${cfg.gbif_credentials ? "" : " (configura .env)"}</option></select></label>
        </div>
        <div class="row">
          <label class="field" style="flex:1">Máx. registros (rápido)<input id="max" type="number" min="100" max="100000" step="1000" value="${cfg.fast_mode_max_records || 20000}"></label>
          <label class="field" style="flex:1">Año desde<input id="ys" type="number" min="1700" max="2100" placeholder="todos"></label>
          <label class="field" style="flex:1">Año hasta<input id="ye" type="number" min="1700" max="2100" placeholder="todos"></label>
        </div>
        <p class="muted" style="font-size:12px;margin:-4px 0 4px">Recomendado: deja los años vacíos para descargar toda la serie histórica y filtra después por periodo (y compara) en el mapa, el análisis, el catálogo y las fichas.</p>
        <div class="dropzone" id="drop" tabindex="0" role="button">
          <strong>Arrastra tu área de interés aquí</strong>
          <span class="soft">GeoPackage, GeoJSON, KML, FlatGeobuf o Shapefile comprimido (.zip) · cualquier CRS</span>
          <input type="file" id="file" accept=".gpkg,.geojson,.json,.kml,.zip,.fgb" hidden>
          <div id="fileName" class="chip" style="margin-top:10px" hidden></div>
        </div>
        <div class="draw-map" id="drawMap"><div class="hint glass" id="drawHint">…o dibuja: clic para añadir vértices · <b>Cerrar</b> para terminar</div></div>
        <div class="row" style="justify-content:space-between">
          <div class="row"><button class="btn sm" id="closePoly">Cerrar polígono</button><button class="btn sm" id="clearPoly">Borrar dibujo</button></div>
          <button class="btn primary" id="submit">Calcular todo</button>
        </div>
      </section>
      <section aria-labelledby="listTitle">
        <div class="section-title" style="margin-top:0"><h2 id="listTitle">Workspaces</h2><span class="muted">${state.workspaces.length}</span></div>
        <div class="ws-list" id="wsList"></div>
      </section>
    </div>`;
  const $ = (id) => el.querySelector(`#${id}`);
  file = null; verts = []; closed = false;

  // Subida
  const drop = $("drop");
  const pick = (f) => { file = f; $("fileName").hidden = !f; $("fileName").textContent = f ? `📎 ${f.name}` : "";
    if (f && !$("name").value) $("name").value = f.name.replace(/\.[^.]+$/, ""); };
  drop.onclick = () => $("file").click();
  drop.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") $("file").click(); };
  $("file").onchange = (e) => pick(e.target.files[0]);
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("drag"); };
  drop.ondragleave = () => drop.classList.remove("drag");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("drag"); pick(e.dataTransfer.files[0]); };

  // Dibujo
  drawDeck = createDeck($("drawMap"), {
    initialViewState: { longitude: -73.5, latitude: 4.3, zoom: 4.6, pitch: 0, bearing: 0 },
    controller: { doubleClickZoom: false },
    onClick: (info) => { if (closed || !info.coordinate) return; verts.push(info.coordinate.slice(0, 2)); drawLayers(); },
  });
  const drawLayers = () => {
    const ring = closed ? [...verts, verts[0]] : verts;
    drawDeck.setProps({ layers: [
      ...baseLayers({ basemap: "satellite", terrain: false }),
      new deck.PolygonLayer({ id: "poly", data: closed && verts.length > 2 ? [{ ring }] : [], getPolygon: (d) => d.ring,
        getFillColor: [25, 227, 166, 60], getLineColor: [25, 227, 166, 255], lineWidthMinPixels: 2 }),
      new deck.PathLayer({ id: "path", data: verts.length > 1 ? [{ path: ring }] : [], getPath: (d) => d.path, getColor: [255, 255, 255, 230], widthMinPixels: 2 }),
      new deck.ScatterplotLayer({ id: "v", data: verts, getPosition: (d) => d, radiusUnits: "pixels", getRadius: 5, getFillColor: [25, 227, 166], stroked: true, getLineColor: [255, 255, 255], lineWidthMinPixels: 1.5 }),
    ] });
    $("drawHint").innerHTML = closed ? `Polígono listo · ${verts.length} vértices` : `${verts.length} vértices · clic para añadir · <b>Cerrar</b> para terminar`;
  };
  drawLayers();
  $("closePoly").onclick = () => { if (verts.length < 3) return toast("Necesitas al menos 3 vértices"); closed = true; drawLayers(); };
  $("clearPoly").onclick = () => { verts = []; closed = false; drawLayers(); };

  $("submit").onclick = async () => {
    const name = $("name").value.trim();
    if (!name) return toast("Ponle un nombre al área de interés");
    const opts = { mode: $("mode").value, max_records: +$("max").value || null, year_start: +$("ys").value || null, year_end: +$("ye").value || null };
    $("submit").disabled = true;
    try {
      let ws;
      if (file) {
        const fd = new FormData();
        fd.append("file", file); fd.append("name", name); fd.append("mode", opts.mode);
        ["max_records", "year_start", "year_end"].forEach((k) => opts[k] && fd.append(k, opts[k]));
        ws = await api.createFromFile(fd);
      } else if (closed && verts.length > 2) {
        ws = await api.createFromDraw({ name, ...opts, geojson: { type: "Polygon", coordinates: [[...verts, verts[0]]] } });
      } else {
        toast("Sube un archivo o dibuja y cierra un polígono"); return;
      }
      toast(`“${ws.name}” en proceso…`);
      setState({ workspaces: [ws, ...state.workspaces], wsId: ws.id });
      renderList(el);
    } catch (e) { toast(`Error: ${e.message}`, 6000); }
    finally { $("submit").disabled = false; }
  };
  renderList(el);
}

export function renderList(root = document) {
  const host = root.querySelector?.("#wsList");
  if (!host) return;
  if (!state.workspaces.length) { host.innerHTML = `<div class="empty glass">Aún no hay áreas de interés. Crea la primera.</div>`; return; }
  host.innerHTML = state.workspaces.map((w) => {
    const st = w.status || {}, running = ["running", "queued"].includes(st.state);
    return `<article class="ws-card glass ${w.id === state.wsId ? "active" : ""}" data-id="${w.id}">
      <div><h3>${esc(w.name)}</h3><div class="meta">
        <span>${fmt.n(w.total_records)} registros</span><span>${fmt.km2(w.area_km2)}</span>
        <span>${w.mode === "fast" ? "API rápida" : w.mode === "zip" ? "ZIP GBIF" : "Descarga GBIF"}</span>
        <span class="${st.state === "error" ? "" : "muted"}">${st.state === "done" ? "✓ listo" : st.state === "error" ? `⚠ ${esc(st.error || "error")}` : running ? esc(st.message || STEP_LABEL[st.step] || "en cola") : esc(st.state || "")}</span>
      </div></div>
      <div class="actions">
        <button class="btn sm" data-act="open" ${st.state !== "done" ? "disabled" : ""}>Abrir</button>
        <button class="btn sm" data-act="rerun" title="Recalcular enriquecimiento e indicadores" ${running ? "disabled" : ""}>↻</button>
        <button class="btn sm" data-act="del" title="Eliminar" ${running ? "disabled" : ""}>✕</button>
      </div>
      ${running ? `<div class="progress"><i style="width:${Math.round((st.progress || 0) * 100)}%"></i></div>` : ""}
    </article>`;
  }).join("");
  host.onclick = async (e) => {
    const card = e.target.closest(".ws-card"); if (!card) return;
    const id = card.dataset.id, act = e.target.closest("[data-act]")?.dataset.act;
    if (act === "del") {
      if (!confirm("¿Eliminar este workspace y todos sus resultados?")) return;
      await api.remove(id); api.invalidate(id);
      setState({ workspaces: state.workspaces.filter((w) => w.id !== id), wsId: state.wsId === id ? null : state.wsId });
      renderList(root); return;
    }
    if (act === "rerun") { await api.rerun(id, "enrich,analyze"); api.invalidate(id); toast("Recalculando…"); return; }
    const w = state.workspaces.find((x) => x.id === id);
    setState({ wsId: id });
    if (w?.status?.state === "done") location.hash = "#/map"; else renderList(root);
  };
}

export function unmount() { if (drawDeck) { drawDeck.finalize(); drawDeck = null; } }
