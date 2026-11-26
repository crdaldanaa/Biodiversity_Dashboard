# Biodiversity Pipeline (GBIF + DuckDB Spatial + GeoParquet)

Pipeline modular en Python diseñado para descargar **todos** los registros de presencia de GBIF dentro de un Área de Interés (ROI) definida en un archivo GeoPackage (`.gpkg`), procesarlos en *streaming* con **DuckDB Spatial** sin saturar la RAM y servirlos en un dashboard interactivo con **Streamlit**.

## Estructura del Proyecto

```text
biodiversity_pipeline/
├── config/                  # Configuración declarativa y filtros de GBIF
├── data/                    # Datos crudos, temporales y GeoParquets finales
├── src/
│   ├── config_loader.py     # Carga de YAML y .env
│   ├── spatial/             # Manejo de GPKG, reproyección, simplificación WKT
│   ├── ingestion/           # Cliente asíncrono de descargas GBIF (pygbif)
│   ├── processing/          # Motor SQL espacial en DuckDB (streaming -> GeoParquet)
│   └── utils/               # Logging y auditoría de DOIs
├── app/                     # Dashboard en Streamlit desacoplado del ETL
└── scripts/                 # Orquestador CLI
```

## Instalación

1. Crear entorno virtual e instalar en modo editable:
```bash
python -m venv .venv
source .venv/bin/activate  # En Windows: .venv\Scripts\activate
pip install -e .
```

2. Configurar credenciales de GBIF:
```bash
cp .env.example .env
# Edita .env con tu usuario, contraseña y correo de GBIF
```

## Ejecución del Pipeline

```bash
python scripts/run_pipeline.py \
  --gpkg data/raw/mi_roi.gpkg \
  --layer poligono_roi \
  --output data/processed/gbif_roi.parquet
```

Si deseas saltar la descarga y reprocesar un `.zip` ya descargado de GBIF:
```bash
python scripts/run_pipeline.py \
  --gpkg data/raw/mi_roi.gpkg \
  --layer poligono_roi \
  --zip-path data/raw/0012345-260101000000.zip \
  --output data/processed/gbif_roi.parquet
```

## Ejecutar el Dashboard

```bash
streamlit run app/main.py
```
