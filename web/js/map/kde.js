// Superficie de densidad de registros (KDE gaussiano) calculada en el navegador.
// Se dibuja en un canvas en proyección Web Mercator, se recorta al área de interés y se
// drapea sobre el terreno como BitmapLayer: funciona igual en 2D y en 3D.
/* global deck */
import { HEAT, hexToRgb } from "../core.js";
import { TERRAIN_EXT, tid } from "./engine.js";

const mx = (lon) => (lon + 180) / 360;
const my = (lat) => { const s = Math.sin((lat * Math.PI) / 180); return 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI); };

// Desenfoque gaussiano aproximado con 3 pasadas de caja (separable, O(n) por pasada)
function boxesForGauss(sigma, n = 3) {
  const wIdeal = Math.sqrt((12 * sigma * sigma) / n + 1);
  let wl = Math.floor(wIdeal); if (wl % 2 === 0) wl -= 1;
  const m = Math.round((12 * sigma * sigma - n * wl * wl - 4 * n * wl - 3 * n) / (-4 * wl - 4));
  return Array.from({ length: n }, (_, i) => (i < m ? wl : wl + 2));
}
function boxBlurH(src, dst, w, h, r) {
  const iarr = 1 / (r + r + 1);
  for (let j = 0; j < h; j++) {
    const o = j * w;
    let val = 0;
    for (let i = 0; i < Math.min(r, w); i++) val += src[o + i];
    for (let i = 0; i < w; i++) {
      if (i + r < w) val += src[o + i + r];
      if (i - r - 1 >= 0) val -= src[o + i - r - 1];
      dst[o + i] = val * iarr;
    }
  }
}
function boxBlurV(src, dst, w, h, r) {
  const iarr = 1 / (r + r + 1);
  for (let i = 0; i < w; i++) {
    let val = 0;
    for (let j = 0; j < Math.min(r, h); j++) val += src[i + j * w];
    for (let j = 0; j < h; j++) {
      if (j + r < h) val += src[i + (j + r) * w];
      if (j - r - 1 >= 0) val -= src[i + (j - r - 1) * w];
      dst[i + j * w] = val * iarr;
    }
  }
}
function gaussBlur(a, w, h, sigma) {
  const tmp = new Float32Array(a.length);
  for (const b of boxesForGauss(sigma)) {
    const r = Math.max(0, (b - 1) / 2);
    boxBlurH(a, tmp, w, h, r); boxBlurV(tmp, a, w, h, r);
  }
  return a;
}

function clipToRoi(ctx, roi, toPx) {
  ctx.globalCompositeOperation = "destination-in";
  ctx.beginPath();
  const ring = (coords) => coords.forEach((c, i) => { const [x, y] = toPx(c[0], c[1]); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
  for (const f of roi.features || []) {
    const g = f.geometry; if (!g) continue;
    const polys = g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : [];
    polys.forEach((p) => p.forEach((r) => { ring(r); ctx.closePath(); }));
  }
  ctx.fillStyle = "#000"; ctx.fill("evenodd");
  ctx.globalCompositeOperation = "source-over";
}

/**
 * @param {Array<[number, number]>} points  [lon, lat]
 * @param {number[]} bbox  [w, s, e, n]
 * @param {{bandwidthM:number, roi?:object, size?:number, ramp?:string[]}} o
 * @returns {{canvas, bounds, density:Float32Array, w, h, max}}
 */
export function kdeSurface(points, bbox, { bandwidthM = 1500, roi = null, size = 900, ramp = HEAT } = {}) {
  const g = densityGrid(points, bbox, bandwidthM, size);
  const { grid, W, H } = g;
  const max = robustMax(grid);
  const stops = ramp.slice(1).map((c) => hexToRgb(c));
  const canvas = document.createElement("canvas");
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext("2d");
  const img = ctx.createImageData(W, H);
  // Escala logarítmica: los registros se agrupan mucho (ríos, vías, estaciones); el log revela la estructura
  const K = 40, lk = Math.log1p(K);
  for (let i = 0; i < grid.length; i++) {
    const t = Math.log1p(K * Math.min(1, grid[i] / max)) / lk;
    if (t < 0.04) continue;
    const x = t * (stops.length - 1), k = Math.floor(x), f = x - k;
    const a = stops[k], b = stops[Math.min(k + 1, stops.length - 1)];
    img.data[i * 4] = a[0] + (b[0] - a[0]) * f;
    img.data[i * 4 + 1] = a[1] + (b[1] - a[1]) * f;
    img.data[i * 4 + 2] = a[2] + (b[2] - a[2]) * f;
    img.data[i * 4 + 3] = Math.round(255 * Math.min(1, 0.35 + t * 0.75) * Math.min(1, (t - 0.04) * 8));
  }
  ctx.putImageData(img, 0, 0);
  if (roi) clipToRoi(ctx, roi, g.toPx);
  return { canvas, bounds: g.bounds, density: grid, w: W, h: H, max };
}

// Rejilla Web Mercator con conteos suavizados (misma geometría para cualquier conjunto de puntos)
function densityGrid(points, bbox, bandwidthM, size) {
  const pad = (bandwidthM * 3) / 111320;  // margen para que los bordes no se corten
  const [w0, s0, e0, n0] = [bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad];
  const X0 = mx(w0), X1 = mx(e0), Y0 = my(n0), Y1 = my(s0);
  const ratio = (Y1 - Y0) / (X1 - X0);
  const W = ratio > 1 ? Math.round(size / ratio) : size, H = ratio > 1 ? size : Math.round(size * ratio);
  const grid = new Float32Array(W * H);
  for (const [lon, lat] of points) {
    const px = Math.floor(((mx(lon) - X0) / (X1 - X0)) * W), py = Math.floor(((my(lat) - Y0) / (Y1 - Y0)) * H);
    if (px >= 0 && py >= 0 && px < W && py < H) grid[py * W + px] += 1;
  }
  const midLat = ((s0 + n0) / 2) * (Math.PI / 180);
  const mPerPx = ((e0 - w0) * 111320 * Math.cos(midLat)) / W;
  gaussBlur(grid, W, H, Math.max(0.8, bandwidthM / mPerPx));
  const toPx = (lon, lat) => [((mx(lon) - X0) / (X1 - X0)) * W, ((my(lat) - Y0) / (Y1 - Y0)) * H];
  return { grid, W, H, bounds: [w0, s0, e0, n0], toPx };
}

// Escala robusta: percentil 99,5 de las celdas con valor (evita que un solo foco sature todo)
function robustMax(grid) {
  const nz = []; for (let i = 0; i < grid.length; i += 3) if (grid[i] > 1e-9) nz.push(grid[i]);
  nz.sort((a, b) => a - b);
  return nz.length ? nz[Math.min(nz.length - 1, Math.floor(nz.length * 0.995))] : 1;
}

/** Probabilidad relativa (0–1, misma escala log del color) en un píxel del bitmap, para tooltips. */
export const kdeValueAt = (surf, [px, py]) => (surf && px >= 0 && py >= 0 && px < surf.w && py < surf.h
  ? Math.log1p(40 * Math.min(1, surf.density[py * surf.w + px] / surf.max)) / Math.log1p(40) : null);

export function kdeLayer(surf, { id = "kde", opacity = 0.85, pickable = true, terrain = false, version = 0 } = {}) {
  // Canvas ya dibujado: textura síncrona. Drapeada sobre el relieve (deck.gl 9.0) la capa solo se ve con
  // opacity 1 y sin picking (la pasada de picking comparte la cobertura del terreno); la transparencia
  // ya está en el alfa del canvas. En 3D el tooltip de probabilidad no está disponible.
  // Además, la capa drapeada debe crearse cuando ya cargaron las teselas del terreno: quien la usa
  // incrementa `version` al cargar teselas del TerrainLayer (ver kdeTerrainRefresher).
  // Un canvas por modo: al finalizar la capa 2D deck.gl destruye la textura asociada a su imagen
  const key = terrain ? "img3d" : "img2d";
  if (!surf[key] || terrain) {
    const c = document.createElement("canvas");
    c.width = surf.canvas.width; c.height = surf.canvas.height;
    c.getContext("2d").drawImage(surf.canvas, 0, 0);
    surf[key] = c;
  }
  return new deck.BitmapLayer({
    id: `${tid(id, terrain)}${terrain ? `.${version}` : ""}`, image: surf[key], bounds: surf.bounds, opacity: terrain ? 1 : opacity, pickable: pickable && !terrain,
    ...(terrain ? { extensions: [TERRAIN_EXT], terrainDrawMode: "drape" } : {}),
  });
}

export function kdeLegendHTML(ramp = HEAT) {
  return `<div class="ramp" style="background:linear-gradient(90deg,${ramp.slice(1).join(",")})"></div>
    <div class="ramp-labels"><span>Baja</span><span>Alta</span></div>
    <div class="ramp-caption">Probabilidad relativa de avistamiento</div>`;
}

/** Callback (con debounce) para onTileLoad del TerrainLayer que vuelve a crear la capa drapeada. */
export function kdeTerrainRefresher(rerender) {
  const st = { version: 0, t: null };
  st.onLoad = () => { clearTimeout(st.t); st.t = setTimeout(() => { st.version += 1; rerender(); }, 800); };
  return st;
}
