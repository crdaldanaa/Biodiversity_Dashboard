import argparse
from pathlib import Path
from src.config_loader import load_project_config
from src.ingestion.gbif_client import request_and_download_gbif
from src.processing.duckdb_engine import process_gbif_zip_with_duckdb
from src.spatial.grid_aggregator import build_spatial_grid_summary
from src.spatial.roi_handler import prepare_roi_for_gbif
from src.utils.logger import get_logger, save_metadata_audit

logger = get_logger("run_pipeline")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pipeline de descarga y filtrado espacial de registros GBIF con DuckDB."
    )
    parser.add_argument("--gpkg", required=True, help="Ruta al archivo GeoPackage (.gpkg) del ROI.")
    parser.add_argument("--layer", default=None, help="Nombre de la capa dentro del GeoPackage.")
    parser.add_argument(
        "--output",
        default="data/processed/gbif_roi.parquet",
        help="Ruta de salida del archivo GeoParquet.",
    )
    parser.add_argument(
        "--zip-path",
        default=None,
        help="Opcional: ruta a un ZIP ya descargado de GBIF para saltar la descarga en API.",
    )
    parser.add_argument(
        "--build-grid",
        action="store_true",
        help="Generar además una capa agregada en grilla para mapas rápidos.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_project_config()
    settings = cfg["settings"]

    # 1. Preparar geometría WKT desde el GeoPackage
    wkt_polygon, source_crs = prepare_roi_for_gbif(
        gpkg_path=args.gpkg,
        layer=args.layer,
        target_crs=settings["project"]["target_crs"],
        tolerance=settings["spatial"]["simplify_tolerance"],
        max_wkt_length=settings["spatial"]["max_wkt_length"],
    )

    # 2. Descargar desde GBIF (o reutilizar ZIP local)
    if args.zip_path:
        zip_path = Path(args.zip_path)
        download_info = {"source": "local_zip", "zip_path": str(zip_path)}
        logger.info(f"Reutilizando ZIP local: {zip_path}")
    else:
        zip_path, download_info = request_and_download_gbif(
            wkt_polygon=wkt_polygon,
            pred_cfg=cfg["predicates"],
            auth=cfg["gbif_auth"],
            raw_dir=settings["paths"]["raw_dir"],
        )

    # 3. Filtrado espacial en streaming con DuckDB Spatial -> GeoParquet
    total_records = process_gbif_zip_with_duckdb(
        zip_path=zip_path,
        gpkg_path=args.gpkg,
        layer=args.layer,
        source_crs=source_crs,
        output_parquet=args.output,
        duckdb_cfg=settings["duckdb"],
        interim_dir=settings["paths"]["interim_dir"],
    )

    # 4. Opcional: generar grilla espacial agregada
    grid_path = None
    if args.build_grid:
        grid_out = Path(args.output).with_name(f"{Path(args.output).stem}_grid.parquet")
        grid_path = str(
            build_spatial_grid_summary(
                parquet_path=args.output,
                output_grid_parquet=grid_out,
                memory_limit=settings["duckdb"]["memory_limit"],
            )
        )

    # 5. Guardar metadatos y DOI para citación en el dashboard
    meta_file = save_metadata_audit(
        output_parquet=args.output,
        metadata={
            "roi_gpkg": str(args.gpkg),
            "roi_layer": args.layer,
            "roi_source_crs": source_crs,
            "total_records_inside_roi": total_records,
            "grid_parquet": grid_path,
            "gbif_download": download_info,
        },
    )
    logger.info(f"Auditoría y citación guardadas en: {meta_file}")


if __name__ == "__main__":
    main()
