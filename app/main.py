import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import plotly.express as px
import streamlit as st
from app.queries import (
    load_filter_options,
    load_map_points,
    load_summary_metrics,
    load_top_species,
    load_yearly_trend,
)
st.set_page_config(page_title="Dashboard Biodiversidad Proyecto REDD+ SDM", layout="wide")
st.title("Registros de Biodiversidad de la región del proyecto")

processed_dir = Path("data/processed")
parquet_files = sorted(
    p for p in processed_dir.glob("*.parquet") if not p.name.endswith("_grid.parquet")
)

if not parquet_files:
    st.warning(
        "No se encontraron archivos .parquet en `data/processed/`. "
        "Ejecuta primero `python scripts/run_pipeline.py`."
    )
    st.stop()

selected_file = st.sidebar.selectbox(
    "Dataset GeoParquet",
    options=parquet_files,
    format_func=lambda p: p.name,
)

opts = load_filter_options(selected_file)
selected_kingdom = st.sidebar.selectbox("Reino", ["Todos"] + opts["kingdoms"])

year_range = None
if opts["min_year"] and opts["max_year"] and opts["min_year"] < opts["max_year"]:
    year_range = st.sidebar.slider(
        "Rango de años",
        int(opts["min_year"]),
        int(opts["max_year"]),
        (int(opts["min_year"]), int(opts["max_year"])),
    )

# KPIs principales
metrics = load_summary_metrics(selected_file, selected_kingdom, year_range)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Registros en ROI", f"{metrics['total_records']:,}")
c2.metric("Especies únicas", f"{metrics['total_species']:,}")
c3.metric("Familias", f"{metrics['total_families']:,}")
c4.metric("Datasets GBIF", f"{metrics['total_datasets']:,}")

# Mapa espacial
st.subheader("Distribución espacial de ocurrencias")
df_map = load_map_points(selected_file, selected_kingdom, year_range, max_points=50000)
if not df_map.empty:
    fig_map = px.scatter_map(
        df_map,
        lat="lat",
        lon="lon",
        color="family",
        hover_name="scientificName",
        hover_data=["year", "basisOfRecord"],
        zoom=7,
        height=500,
    )
    fig_map.update_layout(map_style="carto-positron", margin={"r": 0, "t": 0, "l": 0, "b": 0})
    st.plotly_chart(fig_map, use_container_width=True)

# Gráficos analíticos
col_left, col_right = st.columns(2)
with col_left:
    st.subheader("Top 15 especies más registradas")
    df_sp = load_top_species(selected_file, selected_kingdom, year_range)
    if not df_sp.empty:
        fig_sp = px.bar(df_sp, x="registros", y="species", color="family", orientation="h")
        fig_sp.update_layout(yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig_sp, use_container_width=True)

with col_right:
    st.subheader("Serie histórica de registros por año")
    df_yr = load_yearly_trend(selected_file, selected_kingdom, year_range)
    if not df_yr.empty:
        fig_yr = px.area(df_yr, x="year", y="registros")
        st.plotly_chart(fig_yr, use_container_width=True)

# Pie de página con DOI oficial de GBIF si existe el archivo de metadatos
meta_file = selected_file.with_suffix(".metadata.json")
if meta_file.exists():
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    doi = meta.get("gbif_download", {}).get("doi")
    if doi:
        st.caption(f"Citación oficial GBIF Download DOI: https://doi.org/{doi}")
