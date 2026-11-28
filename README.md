# Biodiversity Intelligence

Plataforma modular para analizar la biodiversidad de **cualquier área de interés**: cargas (o dibujas) un polígono y el sistema descarga los registros de GBIF, los cruza con la **Resolución 0126 de 2024 (MADS)**, la **Lista Roja IUCN** y el **Catálogo de la Biodiversidad del SiB Colombia**, calcula todos los indicadores de la guía *Biodiversidad y Ciencia de Datos* y los sirve en un dashboard web con mapas 3D, análisis interactivo y un catálogo digital de especies.

## Inicio rápido

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # credenciales GBIF (solo para el modo "completo") e IUCN_TOKEN opcional

python scripts/biodiv.py serve   # → http://127.0.0.1:8000
```

En el dashboard, en **Áreas**, sube un GeoPackage, GeoJSON, KML, FlatGeobuf o Shapefile comprimido (cualquier CRS), o dibuja el polígono en el mapa, y pulsa **Calcular todo**.

Desde la terminal:

```bash
# Área desde archivo, modo rápido (API GBIF, sin credenciales, hasta 100.000 registros)
python scripts/biodiv.py create --roi mi_area.geojson --name "Mi área" --mode fast --max-records 20000

# Reutilizar un ZIP SIMPLE_CSV ya descargado de GBIF
python scripts/biodiv.py create --roi data/raw/SDM_Municipalities.gpkg --name "Proyecto REDD+ SDM" \
       --mode zip --zip-path data/raw/0019056-261118162104854.zip

# Descarga completa con DOI citable (requiere GBIF_USER/GBIF_PWD/GBIF_EMAIL)
python scripts/biodiv.py create --roi mi_area.gpkg --name "Mi área" --mode full

python scripts/biodiv.py rerun <workspace_id> --steps elevation analyze   # pasos: ingest elevation enrich analyze
python scripts/biodiv.py list
```

## Qué se calcula

| Módulo (`src/analytics/`) | Referencia en la guía | Salidas |
|---|---|---|
| `overview` | — | Registros, riqueza por nivel taxonómico, densidad, amenazadas, CITES, exóticas |
| `quality` | Indicador 4 (L1.4) | Duplicados (gbifID / espaciotemporal / espacial), coordenadas problemáticas e issues GBIF, outliers IQR, completitud con semáforo, **score 0–100** (40% coordenadas + 60% completitud), retención |
| `composition` | Indicador 2, G2 | % por basisOfRecord, dominancia, datasets, instituciones, observadores |
| `geography` | Indicador 1, G1, G7 | Top unidades administrativas, concentración top 3, heatmap unidad × año |
| `elevation` | — | Gradiente altitudinal: registros, especies y amenazadas por franja; elevación reportada vs completada con DEM |
| `temporal` | G3, G4 | Serie anual + media móvil + tendencia lineal, % de cambio a 5 años, estacionalidad, sesgo de fin de semana, curva de descubrimiento, matriz año × mes (el dashboard compara cualquier periodo contra la totalidad) |
| `uncertainty` | G5, G6 | Histogramas lineal y log, boxplot por unidad (n ≥ 8) |
| `taxonomy` | Indicador 3 | Ranking por clase, pivot clase × categoría (nacional y global), % de amenazadas, árbol taxonómico |
| `threats` | — | Res. 0126/2024 vs IUCN, especies más estrictas a nivel nacional, CITES, exóticas, invasoras, nuevas en 2024 |
| `spatial_grid` | L2.3 | Grilla métrica (tamaño automático) recortada al ROI: conteos, densidad por km², riqueza, Shannon por celda, Gini |
| `danger_index` | L2.4 | Índice compuesto 0,5·amenaza + 0,3·densidad + 0,2·certeza, Min-Max, quintiles 1–5, contribución por especie |
| `hotspots` | — | Getis-Ord Gi* de riqueza, registros y amenazadas (90/95/99%) |
| `diversity` | — | Shannon, Simpson, Pielou, números de Hill, Margalef, Berger-Parker, Chao1, Chao2 por incidencia, cobertura de Good, rarefacción, acumulación espacial |
| `species_profiles` | Ficha L4.1 | Por especie: AOO (celdas IUCN de 2 km), EOO local, ocupación, tendencia, mes pico, elevación, rareza |
| `evidence_threat` | G8 | Dispersión evidencia (log) × amenaza ordinal con cuadrantes de priorización |

Cada indicador incluye textos de interpretación automática generados con plantillas por umbrales y la advertencia metodológica correspondiente (GBIF ≠ población; IUCN ≠ abundancia). Todos los parámetros (umbrales, pesos del índice, tamaño de celda, CRS métrico) se configuran en `config/settings.yaml`.

## Fuentes integradas

| Fuente | Uso | Acceso |
|---|---|---|
| GBIF | Ocurrencias, resolución taxonómica, fotos, capa de densidad global | API REST / descargas asíncronas |
| Resolución 0126 de 2024 (MADS) | Categoría nacional CR/EN/VU, nombres comunes, taxones nuevos | Checklist oficial del SiB en el IPT (DOI 10.15472/frowz3), materializado en `data/reference/` |
| Catálogo de la Biodiversidad (SiB Colombia) | Nombres comunes, CITES, exóticas e invasoras, descripción, hábitat, amenazas, fotos | `api.catalogo.biodiversidad.co` |
| IUCN Red List | Categoría global (API v4 con `IUCN_TOKEN`; sin token, la categoría publicada por GBIF) | API v4 / GBIF |
| Copernicus DEM GLO-30 | Elevación (~30 m) para completar la de cada registro; interpolación bilineal | AWS Open Data (`copernicus-dem-30m`), teselas cacheadas en `data/cache/dem/` |

Las respuestas se guardan en una caché HTTP persistente (`data/cache/`), así que las ejecuciones repetidas tardan segundos.

### Depuración de registros

El paso `clean` (después de `ingest`) aplica los criterios de `cleaning` en `config/settings.yaml`:
- excluye especímenes de museo y fósiles;
- excluye los registros sin año y los posteriores a 2025;
- quita los duplicados (misma especie, coordenada y fecha) y conserva el de menor incertidumbre.

Los registros con incertidumbre mayor a `spatial_max_uncertainty_m` (10 km) se marcan con `spatial_ok = false`. Cuentan para riqueza y temporalidad, pero no para la grilla, AOO/EOO, hotspots, elevación ni mapas.

La descarga original queda en `occurrences_raw.parquet`. Para aplicar otros criterios sin volver a descargar: `POST /api/workspaces/{id}/rerun?steps=clean,elevation,enrich,analyze`.

### Elevación con DEM

El paso `elevation` muestrea el DEM en cada ubicación: conserva la elevación reportada (`elevation_reported`), guarda la del DEM (`elevation_dem`) y deja en `elevation` la reportada o, si falta, la del DEM (`elevation_source` indica cuál). Si tienes un raster de mayor resolución (ALOS PALSAR 12,5 m, DEM del IGAC…), indícalo en `dem.local_path` de `config/settings.yaml`: se usa primero y Copernicus completa el resto. GLO-30 es un modelo de superficie (DSM): bajo bosque denso puede incluir parte del dosel.

### Mapa de calor de avistamientos

El mapa 3D y la ficha de cada especie calculan en el navegador una densidad kernel gaussiana (KDE) de los registros visibles, recortada al área y drapeada sobre el relieve (funciona en 2D y 3D). Responde a los filtros de año, especie y "solo amenazadas", y el radio de suavizado es ajustable. Es una probabilidad *relativa* de avistamiento basada en registros: refleja también el esfuerzo de observación.

### Periodo de análisis

El botón de calendario de la barra superior fija un **periodo** que filtra el mapa, el análisis, el catálogo y las fichas de especie.

- **Análisis:** los indicadores se recalculan en el servidor solo con los registros del periodo. El resultado se guarda en `periods/`.
- **Mapa:** muestra los puntos, el mapa de calor, la grilla y las cifras del periodo. La línea de tiempo muestra solo los años con registros: clic elige un año, Mayús+clic amplía el rango y doble clic vuelve a todos los años.
- **Catálogo:** con un periodo activo lista solo las especies registradas en él, con sus registros del periodo.
- **Ficha de especie:** muestra los registros, el promedio anual y los meses con registros del periodo. El gráfico por año incluye solo los años en que la especie tiene registros.

## Arquitectura

```text
src/
├── analytics/        Indicadores enchufables (registro automático, un archivo por módulo)
├── ingestion/        Clientes: gbif_api, gbif_client (descargas), res0126, sib_catalog, iucn_client
├── processing/       DuckDB Spatial: normalización + recorte al ROI → GeoParquet
├── spatial/          Lectura de ROIs, CRS métrico, grilla, DEM (elevación), preparación WKT para GBIF
├── services/         pipeline (orquestación + jobs), enrichment, media (foto + paleta de color)
├── workspaces/       Un directorio por área de interés con todos sus artefactos
├── references/       Vocabulario de categorías de amenaza
└── api/              FastAPI (REST + archivos estáticos del dashboard)
web/
├── js/views/         areas · map3d · analysis · catalog · species (ficha)
├── js/charts/        panels.js (registro de paneles) · ec.js (ECharts sobre el tema)
├── js/map/          engine.js (deck.gl: terreno, satélite, cámara) · kde.js (mapa de calor)
└── css/app.css       Sistema glassmorphism; los acentos se tiñen con la paleta de cada especie
```

### Añadir un indicador

Crea `src/analytics/mi_indicador.py`:

```python
from src.analytics.base import AnalysisContext, Indicator, register

@register
class Endemismo(Indicator):
    id = "endemismo"
    title = "Endemismo"
    group = "biodiversidad"
    order = 120
    requires = ("species_profiles",)        # dependencias opcionales

    def compute(self, ctx: AnalysisContext) -> dict:
        df = ctx.sql("SELECT species, COUNT(*) n FROM occ GROUP BY 1")   # DuckDB sobre el GeoParquet
        return {"summary": {...}, "interpretation": ["..."], "disclaimer": "..."}
```

Se descubre automáticamente, se ejecuta en `analyze` y queda disponible en `/api/workspaces/{id}/analysis/endemismo`. Para mostrarlo, registra un panel en `web/js/charts/panels.js` con `registerPanel({ id, group, title, needs: ["endemismo"], render(el, I, ctx) {...} })`.

### API principal

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/workspaces` | Crear desde archivo (multipart: `file`, `name`, `mode`, `max_records`, `year_start`, `year_end`) |
| POST | `/api/workspaces/draw` | Crear desde GeoJSON dibujado |
| GET | `/api/workspaces/{id}/status` | Progreso del job |
| GET | `/api/workspaces/{id}/analysis[/{indicador}]?year_from&year_to` | Resultados (recalculados para el periodo si se indica) |
| GET | `/api/workspaces/{id}/grid?year_from&year_to` · `/roi` · `/points?year_from&year_to` | Capas para el mapa |
| GET | `/api/workspaces/{id}/species?year_from&year_to&ref_from&ref_to&presence` · `/species/{nombre}` | Catálogo (con conteos por periodo) y ficha |
| GET | `/api/workspaces/{id}/export/{occurrences.csv,species.csv,grid.gpkg,grid.geojson,analysis.json,roi.gpkg}` | Entregables GIS |

Documentación interactiva en `http://127.0.0.1:8000/docs`.

## Pruebas

```bash
pytest -q
```

## Advertencias metodológicas

- Los registros GBIF documentan presencia observada: no son abundancia ni ausencia, y reflejan el esfuerzo de muestreo y la accesibilidad del territorio.
- La categoría IUCN es global y puede estar desactualizada; la categoría nacional proviene de la Resolución 0126 de 2024.
- El índice compuesto de peligro es un instrumento didáctico: requiere validación con expertos y datos de campo antes de usarse en decisiones.
- AOO y EOO se calculan solo con los registros dentro del área de interés.

El dashboard Streamlit anterior (`app/`) y `scripts/run_pipeline.py` se conservan por compatibilidad.
