// Motor 3D compartido (deck.gl): terreno real (AWS Terrain Tiles), imagen satelital o bases oscura/clara (Esri),
// iluminación y utilidades de cámara. Las capas temáticas usan TERRAIN_EXT para posarse sobre el relieve.
/* global deck */

const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services";
export const BASEMAPS = {
  satellite: { label: "Satélite", url: `${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`,
    attribution: "Imagen © Esri, Maxar, Earthstar Geographics" },
  // CARTO pasó a exigir API key; Esri Canvas es gratuito, sin clave, con capa de nombres aparte
  dark: { label: "Oscuro", url: `${ESRI}/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`,
    labels: `${ESRI}/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}`, maxZoom: 16,
    attribution: "Mapa © Esri, HERE, Garmin, © OpenStreetMap" },
  light: { label: "Claro", url: `${ESRI}/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}`,
    labels: `${ESRI}/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}`, maxZoom: 16,
    attribution: "Mapa © Esri, HERE, Garmin, © OpenStreetMap" },
};
const TERRAIN_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png";

export const TERRAIN_EXT = new deck._TerrainExtension();

// Decodificador memoizado por exageración: un objeto nuevo en cada render haría recargar todas las teselas
const DECODERS = new Map();
const decoder = (e) => {
  if (!DECODERS.has(e)) DECODERS.set(e, { rScaler: 256 * e, gScaler: 1 * e, bScaler: e / 256, offset: -32768 * e });
  return DECODERS.get(e);
};

const bitmapTiles = (props) => {
  const [[w, s], [e, n]] = props.tile.boundingBox;
  return new deck.BitmapLayer(props, { data: null, image: props.data, bounds: [w, s, e, n] });
};

// Nombres de lugares (bases oscura/clara): teselas transparentes sobre la base, drapeadas en 3D
function labelLayer(bm, key, terrain) {
  if (!bm.labels) return [];
  return [new deck.TileLayer({
    id: `labels-${key}${terrain ? "@3d" : "@2d"}`, data: bm.labels, minZoom: 0, maxZoom: bm.maxZoom || 19, tileSize: 256,
    renderSubLayers: bitmapTiles, ...(terrain ? { extensions: [TERRAIN_EXT], terrainDrawMode: "drape" } : {}),
  })];
}

export function baseLayers({ basemap = "satellite", terrain = true, exaggeration = 1.5, onTerrainLoad = null }) {
  const bm = BASEMAPS[basemap] || BASEMAPS.satellite;
  const url = bm.url;
  if (terrain) {
    const e = exaggeration;
    return [new deck.TerrainLayer({
      id: `terrain-${basemap}-${e}`,
      minZoom: 0, maxZoom: 14, strategy: "no-overlap",
      elevationDecoder: decoder(e),
      elevationData: TERRAIN_URL, texture: url, meshMaxError: 3, operation: "terrain+draw",
      color: [255, 255, 255],
      ...(onTerrainLoad ? { onTileLoad: onTerrainLoad } : {}),  // TerrainLayer no reenvía onViewportLoad
    }), ...labelLayer(bm, basemap, true)];
  }
  return [new deck.TileLayer({
    id: `tiles-${basemap}`, data: url, minZoom: 0, maxZoom: bm.maxZoom || 19, tileSize: 256, maxRequests: 12,
    renderSubLayers: bitmapTiles,
  }), ...labelLayer(bm, basemap, false)];
}

export function lighting() {
  const ambient = new deck.AmbientLight({ color: [255, 255, 255], intensity: 1.15 });
  const key = new deck.DirectionalLight({ color: [255, 244, 230], intensity: 1.6, direction: [-3, -6, -8] });
  const rim = new deck.DirectionalLight({ color: [160, 190, 255], intensity: 0.6, direction: [4, 6, -2] });
  return new deck.LightingEffect({ ambient, key, rim });
}

export function fitView(bbox, el, { pitch = 55, bearing = -18, padding = 70 } = {}) {
  const width = el.clientWidth || window.innerWidth, height = el.clientHeight || window.innerHeight;
  const vp = new deck.WebMercatorViewport({ width, height });
  // padding puede ser número u objeto {left, right, top, bottom} para dejar libres los paneles flotantes
  const pad = typeof padding === "number" ? Math.min(padding, width / 4, height / 4) : padding;
  const { longitude, latitude, zoom } = vp.fitBounds([[bbox[0], bbox[1]], [bbox[2], bbox[3]]], { padding: pad });
  return { longitude, latitude, zoom: Math.min(zoom, 15), pitch, bearing, maxPitch: 85 };
}

export function createDeck(container, { initialViewState, getTooltip, onClick, onViewStateChange, controller } = {}) {
  // deck.gl trata `undefined` como valor explícito: solo pasar callbacks definidos
  const callbacks = Object.fromEntries(Object.entries({ getTooltip, onClick, onViewStateChange }).filter(([, v]) => v));
  return new deck.Deck({
    parent: container,
    initialViewState,
    controller: controller ?? { doubleClickZoom: true, inertia: 300, touchRotate: true },
    effects: [lighting()],
    ...callbacks,
    layers: [],
    useDevicePixels: Math.min(window.devicePixelRatio || 1, 2),
    _typedArrayManagerProps: { overAlloc: 1, poolSize: 0 },
  });
}

// Animación de vuelo suave hacia una vista
export function flyTo(d, view, ms = 1800) {
  d.setProps({ initialViewState: { ...view, transitionDuration: ms, transitionInterpolator: new deck.FlyToInterpolator({ speed: 1.4 }) } });
}

// Las capas con TERRAIN_EXT solo se dibujan si existe una capa de terreno: aplicarla solo en 3D.
// deck.gl no reinicializa una capa si cambian sus `extensions` con el mismo id: el id incluye el modo.
export const onTerrain = (terrain, mode) => (terrain ? { extensions: [TERRAIN_EXT], ...(mode ? { terrainDrawMode: mode } : {}) } : {});
export const tid = (id, terrain) => `${id}${terrain ? "@3d" : "@2d"}`;

// Contorno legible según el mapa base: oscuro sobre la base clara, blanco sobre satélite/oscura
export const outlineColor = (basemap) => (basemap === "light" ? [15, 23, 42] : [255, 255, 255]);

export const roiOutline = (roi, color = [255, 255, 255], idPrefix = "roi", terrain = true) => [
  new deck.GeoJsonLayer({ id: tid(`${idPrefix}-glow`, terrain), data: roi, stroked: true, filled: false,
    getLineColor: [...color, 70], lineWidthMinPixels: 9, ...onTerrain(terrain, "drape") }),
  new deck.GeoJsonLayer({ id: tid(`${idPrefix}-line`, terrain), data: roi, stroked: true, filled: false,
    getLineColor: [...color, 240], lineWidthMinPixels: 2, ...onTerrain(terrain, "drape") }),
];
