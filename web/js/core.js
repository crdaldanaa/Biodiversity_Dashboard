// Núcleo del frontend: API, estado compartido, tema dinámico y utilidades de formato.

// ---------------------------------------------------------------- API
async function req(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch { /* sin cuerpo JSON */ }
    const err = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    err.status = r.status;
    throw err;
  }
  return r.json();
}
const qs = (p = {}) => {
  const s = new URLSearchParams();
  Object.entries(p).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") s.set(k, v); });
  const t = s.toString();
  return t ? `?${t}` : "";
};
const memo = new Map();
const cached = (key, fn) => { if (!memo.has(key)) memo.set(key, fn().catch((e) => { memo.delete(key); throw e; })); return memo.get(key); };

export const api = {
  config: () => cached("config", () => req("/api/config")),
  workspaces: () => req("/api/workspaces"),
  workspace: (id) => req(`/api/workspaces/${id}`),
  // `p` = {year_from, year_to}: indicadores/grilla recalculados para ese periodo (vacío = todos los años)
  analysis: (id, p = {}) => cached(`a:${id}:${JSON.stringify(p)}`, () => req(`/api/workspaces/${id}/analysis${qs(p)}`)),
  grid: (id, p = {}) => cached(`g:${id}:${JSON.stringify(p)}`, () => req(`/api/workspaces/${id}/grid${qs(p)}`)),
  roi: (id) => cached(`r:${id}`, () => req(`/api/workspaces/${id}/roi`)),
  points: (id, p = {}) => cached(`p:${id}:${JSON.stringify(p)}`, () => req(`/api/workspaces/${id}/points${qs(p)}`)),
  species: (id, p = {}) => req(`/api/workspaces/${id}/species${qs(p)}`),
  speciesDetail: (id, name) => cached(`s:${id}:${name}`, () => req(`/api/workspaces/${id}/species/${encodeURIComponent(name)}`)),
  media: (name, p = {}) => cached(`m:${name}`, () => req(`/api/media/${encodeURIComponent(name)}${qs(p)}`)),
  createFromFile: (form) => req("/api/workspaces", { method: "POST", body: form }),
  createFromDraw: (body) => req("/api/workspaces/draw", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  rerun: (id, steps) => req(`/api/workspaces/${id}/rerun${qs({ steps })}`, { method: "POST" }),
  remove: (id) => req(`/api/workspaces/${id}`, { method: "DELETE" }),
  exportUrl: (id, kind) => `/api/workspaces/${id}/export/${kind}`,
  invalidate: (id) => { for (const k of [...memo.keys()]) if (k.includes(`:${id}`)) memo.delete(k); },
};

// ---------------------------------------------------------------- Estado
const listeners = new Set();
export const state = { config: null, workspaces: [], wsId: null };
export function setState(patch) { Object.assign(state, patch); listeners.forEach((fn) => fn(state, patch)); }
export function onState(fn) { listeners.add(fn); return () => listeners.delete(fn); }
export const currentWs = () => state.workspaces.find((w) => w.id === state.wsId) || null;

export const store = {
  get(k, d = null) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* almacenamiento no disponible */ } },
};

// ---------------------------------------------------------------- Tema dinámico
const DEFAULT_ACCENT = { vibrant: "#19e3a6", secondary: "#8b5cff", third: "#ff4f9a", dark: "#0c2b2a", light: "#c9fff0" };
export function applyPalette(p) {
  const root = document.documentElement.style;
  const pal = p || DEFAULT_ACCENT;
  root.setProperty("--accent", pal.vibrant);
  root.setProperty("--accent-2", pal.secondary || pal.vibrant);
  root.setProperty("--accent-3", pal.third || (pal.swatches && pal.swatches[2]) || pal.secondary || pal.vibrant);
  root.setProperty("--accent-dark", pal.dark || "#0b1222");
  root.setProperty("--accent-light", pal.light || "#ffffff");
  // Texto sobre el degradado de acento: negro o blanco según el contraste WCAG más alto
  const mid = mixHex(pal.vibrant, pal.secondary || pal.vibrant);
  root.setProperty("--on-accent", contrast(mid, "#06110f") >= contrast(mid, "#ffffff") ? "#06110f" : "#ffffff");
}
function mixHex(a, b) { const x = hexToRgb(a), y = hexToRgb(b); return `#${[0, 1, 2].map((i) => Math.round((x[i] + y[i]) / 2).toString(16).padStart(2, "0")).join("")}`; }
export function luminance(hex) {
  const [r, g, b] = hexToRgb(hex).slice(0, 3).map((v) => { const c = v / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
export function contrast(a, b) { const [x, y] = [luminance(a), luminance(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); }
export const resetPalette = () => applyPalette(null);
export const cssVar = (name, el = document.documentElement) => getComputedStyle(el).getPropertyValue(name).trim();
export const seriesColors = () => [1, 2, 3, 4, 5, 6, 7, 8].map((i) => cssVar(`--series-${i}`));

export function hexToRgb(hex, alpha = 255) {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255, alpha];
}

// Rampa de "calor semántico" (vecinos análogos violeta→magenta→naranja→amarillo) para magnitudes en el mapa
export const HEAT = ["#2b1055", "#5b1a8c", "#a3228f", "#e0446a", "#f9813a", "#fcc84a", "#fdf4a6"];
export const DANGER = { 0: "#4b5563", 1: "#1a9850", 2: "#91cf60", 3: "#fee08b", 4: "#fc8d59", 5: "#d73027" };
export const DANGER_LABELS = { 0: "Sin registros", 1: "Muy bajo", 2: "Bajo", 3: "Moderado", 4: "Alto", 5: "Muy alto" };
export const HOT = { "-3": "#2166ac", "-2": "#67a9cf", "-1": "#a9cce3", 0: "#6b7280", 1: "#f4a582", 2: "#d6604d", 3: "#b2182b" };
export function rampColor(t, ramp = HEAT, alpha = 235) {
  const x = Math.max(0, Math.min(1, t)) * (ramp.length - 1);
  const i = Math.floor(x), f = x - i;
  const a = hexToRgb(ramp[i]), b = hexToRgb(ramp[Math.min(i + 1, ramp.length - 1)]);
  return [0, 1, 2].map((k) => Math.round(a[k] + (b[k] - a[k]) * f)).concat(alpha);
}

// ---------------------------------------------------------------- Formato
const nf0 = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 2 });
export const fmt = {
  n: (v) => (v === null || v === undefined || Number.isNaN(v) ? "—" : nf0.format(v)),
  d1: (v) => (v === null || v === undefined ? "—" : nf1.format(v)),
  d2: (v) => (v === null || v === undefined ? "—" : nf2.format(v)),
  pct: (v) => (v === null || v === undefined ? "—" : `${nf1.format(v)}%`),
  km2: (v) => (v === null || v === undefined ? "—" : `${v >= 100 ? nf0.format(v) : nf2.format(v)} km²`),
  compact: (v) => (v === null || v === undefined ? "—" : new Intl.NumberFormat("es-CO", { notation: "compact" }).format(v)),
};
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export function catInfo(code) {
  const cats = state.config?.categories || [];
  return cats.find((c) => c.code === code) || { code: code || "NE", label: "No evaluada", color: "#ffffff" };
}
export function catBadge(code, prefix = "") {
  if (!code) return "";
  const c = catInfo(code);
  const fg = contrast(c.color, "#111111") >= contrast(c.color, "#ffffff") ? "#111" : "#fff";
  return `<span class="badge" title="${esc(prefix)} ${esc(c.label)}"><span class="code" style="background:${c.color};color:${fg}">${c.code}</span>${esc(prefix)}</span>`;
}

export function toast(msg, ms = 3500) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.hidden = true; }, ms);
}

export const h = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; };
export const debounce = (fn, ms = 250) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
