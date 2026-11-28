// Enrutador, selector de workspace, sondeo de estado y tema claro/oscuro.
// Para añadir una vista: crea views/mi_vista.js con { title, mount(el, params), unmount(el) } y regístrala en VIEWS.
import { api, currentWs, esc, onState, setState, state, store, toast } from "./core.js";
import * as areas from "./views/areas.js";
import * as map3d from "./views/map3d.js";
import * as analysis from "./views/analysis.js";
import * as catalog from "./views/catalog.js";
import { hideSpecies, showSpecies } from "./views/species.js";
import { getPeriod, onPeriod, periodPicker, setSpan } from "./charts/period.js";

const VIEWS = { areas, map: map3d, analysis, catalog };
const viewEl = document.getElementById("view");
let active = null, activeKey = null, mounting = 0;

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "") || "areas";
  const [path, query = ""] = raw.split("?");
  const parts = path.split("/");
  return { view: parts[0], arg: parts.slice(1).map(decodeURIComponent).join("/"), params: Object.fromEntries(new URLSearchParams(query)) };
}

async function route() {
  const { view, arg, params } = parseHash();
  if (view === "species") {
    if (!active) await mountView("catalog", {});
    showSpecies(arg);
    return;
  }
  hideSpecies();
  const key = VIEWS[view] ? view : "areas";
  await syncPeriodBar(key);
  const sig = `${key}|${state.wsId}|${JSON.stringify(params)}`;
  if (sig === activeKey) return;
  await mountView(key, params);
}

async function mountView(key, params) {
  const token = ++mounting;
  if (active?.unmount) active.unmount(viewEl);
  active = VIEWS[key];
  activeKey = `${key}|${state.wsId}|${JSON.stringify(params)}`;
  viewEl.innerHTML = "";
  document.getElementById("viewTitle").textContent = active.title;
  document.querySelectorAll(".rail .nav[data-view]").forEach((a) => a.classList.toggle("active", a.dataset.view === key));
  document.body.classList.toggle("map-mode", key === "map");
  try { await active.mount(viewEl, params); } catch (e) {
    if (token === mounting) viewEl.innerHTML = `<div class="empty glass">No se pudo cargar la vista: ${esc(e.message)}</div>`;
    console.error(e);
  }
}

// ---------------------------------------------------------------- Periodo global (barra superior)
let spanWs = null;
async function syncPeriodBar(viewKey) {
  const bar = document.getElementById("periodBar");
  const ws = currentWs();
  const ready = ws?.status?.state === "done";
  if (ready && spanWs !== ws.id) {
    try {
      const a = await api.analysis(ws.id);
      setSpan((a.indicators?.temporal?.data?.yearly || []).filter((r) => r.records > 0).map((r) => r.year));
      spanWs = ws.id;
    } catch { setSpan([]); }
  }
  bar.hidden = !ready || viewKey === "areas" || !getPeriod();
  renderPeriodBar();
}
function renderPeriodBar() {
  const bar = document.getElementById("periodBar");
  const p = getPeriod();
  if (!p) { bar.innerHTML = ""; return; }
  const open = bar.classList.contains("open");
  bar.innerHTML = `<button class="period-chip glass ${p.active ? "active" : ""}" aria-expanded="${open}" aria-controls="periodPop" title="Filtrar todas las vistas por periodo">
      <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>
      <span>${esc(p.label)}</span><small>${p.lo}–${p.hi}</small></button>
    <div class="period-pop glass" id="periodPop" ${open ? "" : "hidden"}>
      <p class="pp-help">Filtra el mapa, el análisis, el catálogo y las fichas.</p></div>`;
  bar.querySelector("#periodPop").appendChild(periodPicker(p));
  bar.querySelector(".period-chip").onclick = () => { bar.classList.toggle("open"); renderPeriodBar(); };
}
onPeriod(() => renderPeriodBar());
document.addEventListener("click", (e) => {
  const bar = document.getElementById("periodBar");
  if (bar?.classList.contains("open") && !bar.contains(e.target) && e.target.isConnected) { bar.classList.remove("open"); renderPeriodBar(); }
});

function renderSelect() {
  const sel = document.getElementById("workspaceSelect");
  const ready = state.workspaces;
  sel.innerHTML = ready.length ? ready.map((w) => `<option value="${w.id}" ${w.id === state.wsId ? "selected" : ""}>${esc(w.name)}${w.status?.state !== "done" ? " · procesando" : ""}</option>`).join("")
    : `<option value="">Sin áreas de interés</option>`;
  const chip = document.getElementById("statusChip");
  const ws = currentWs();
  const st = ws?.status;
  if (st && ["running", "queued"].includes(st.state)) {
    chip.hidden = false;
    chip.innerHTML = `<span class="dot"></span>${esc(st.message || st.step || "en cola")} · ${Math.round((st.progress || 0) * 100)}%`;
  } else if (st?.state === "error") {
    chip.hidden = false; chip.innerHTML = `⚠ ${esc(st.error || "Error")}`;
  } else chip.hidden = true;
}

async function poll() {
  const running = state.workspaces.filter((w) => ["running", "queued"].includes(w.status?.state));
  if (!running.length) return;
  const fresh = await api.workspaces().catch(() => null);
  if (!fresh) return;
  const finished = running.filter((w) => fresh.find((f) => f.id === w.id)?.status?.state === "done");
  setState({ workspaces: fresh });
  if (finished.length) spanWs = null;
  finished.forEach((w) => { api.invalidate(w.id); toast(`✓ “${w.name}” listo: ${fmt(fresh.find((f) => f.id === w.id))}`); });
  if (activeKey?.startsWith("areas")) areas.renderList(viewEl);
  if (finished.some((w) => w.id === state.wsId) && !activeKey?.startsWith("areas")) { activeKey = null; route(); }
}
const fmt = (w) => `${(w?.total_records || 0).toLocaleString("es-CO")} registros`;

function initTheme() {
  const saved = store.get("theme", null);
  if (saved) document.documentElement.dataset.theme = saved;
  document.getElementById("themeToggle").onclick = () => {
    const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next; store.set("theme", next);
    activeKey = null; route();
  };
}

async function boot() {
  initTheme();
  const [config, workspaces] = await Promise.all([api.config(), api.workspaces()]);
  document.getElementById("projectName").textContent = config.project;
  const saved = store.get("wsId");
  const wsId = workspaces.find((w) => w.id === saved)?.id || workspaces.find((w) => w.status?.state === "done")?.id || workspaces[0]?.id || null;
  setState({ config, workspaces, wsId });
  document.getElementById("workspaceSelect").onchange = (e) => { setState({ wsId: e.target.value || null }); };
  onState((s, patch) => {
    if ("wsId" in patch) { store.set("wsId", s.wsId); spanWs = null; activeKey = null; if (!location.hash.startsWith("#/areas")) route(); else syncPeriodBar("areas"); }
    renderSelect();
  });
  renderSelect();
  window.addEventListener("hashchange", route);
  setInterval(poll, 2500);
  if (!location.hash) location.hash = wsId && workspaces.find((w) => w.id === wsId)?.status?.state === "done" ? "#/map" : "#/areas";
  route();
}

boot().catch((e) => { viewEl.innerHTML = `<div class="empty glass">No se pudo conectar con la API: ${esc(e.message)}</div>`; });
