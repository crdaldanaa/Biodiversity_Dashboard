"""CLI del sistema de biodiversidad.

  python scripts/biodiv.py create --roi data/raw/SDM_Municipalities.gpkg --name "Proyecto REDD+ SDM" \
         --mode zip --zip-path data/raw/0019056-261118162104854.zip
  python scripts/biodiv.py create --roi mi_area.geojson --name "Mi área" --mode fast --max-records 20000
  python scripts/biodiv.py rerun <workspace_id> --steps elevation enrich analyze
  python scripts/biodiv.py list
  python scripts/biodiv.py serve
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.services import pipeline  # noqa: E402
from src.spatial.roi_io import read_roi_file  # noqa: E402
from src.workspaces.workspace import list_workspaces  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create", help="Crear un workspace a partir de un área de interés y analizarlo")
    c.add_argument("--roi", required=True, help="GPKG, GeoJSON, KML o SHP comprimido en ZIP")
    c.add_argument("--layer", default=None)
    c.add_argument("--name", required=True)
    c.add_argument("--mode", choices=["fast", "full", "zip"], default="fast")
    c.add_argument("--zip-path", default=None, help="ZIP SIMPLE_CSV de GBIF (modo zip)")
    c.add_argument("--max-records", type=int, default=None)
    c.add_argument("--year-start", type=int, default=None)
    c.add_argument("--year-end", type=int, default=None)

    r = sub.add_parser("rerun", help="Re-ejecutar pasos de un workspace existente")
    r.add_argument("workspace")
    r.add_argument("--steps", nargs="+", default=["analyze"], choices=list(pipeline.STEPS))

    sub.add_parser("list", help="Listar workspaces")
    s = sub.add_parser("serve", help="Levantar API + dashboard")
    s.add_argument("--host", default=None)
    s.add_argument("--port", type=int, default=None)
    s.add_argument("--reload", action="store_true")
    args = p.parse_args()

    if args.cmd == "create":
        if args.mode == "zip" and not args.zip_path:
            p.error("--zip-path es obligatorio en modo zip")
        gdf = read_roi_file(args.roi, args.layer)
        opts = {"zip_path": str(Path(args.zip_path).resolve()) if args.zip_path else None,
                "max_records": args.max_records, "year_start": args.year_start, "year_end": args.year_end}
        ws = pipeline.new_workspace(gdf, args.name, args.mode, opts)
        print(f"Workspace creado: {ws.id}")
        pipeline.run(ws.id)
        st = ws.status
        print(f"Estado: {st['state']} {st.get('error') or ''}")
    elif args.cmd == "rerun":
        pipeline.run(args.workspace, args.steps)
    elif args.cmd == "list":
        for m in list_workspaces():
            print(f"{m['id']:<40} {m['status'].get('state'):<8} {m.get('total_records', 0):>9,}  {m['name']}")
    elif args.cmd == "serve":
        import uvicorn
        from src.config_loader import get_config

        api = get_config()["settings"]["api"]
        uvicorn.run("src.api.app:app", host=args.host or api["host"], port=args.port or api["port"],
                    reload=args.reload)


if __name__ == "__main__":
    main()
