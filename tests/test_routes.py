"""Las rutas principales de la API están registradas (protege contra ediciones que las borren)."""
from src.api.app import app

EXPECTED = {
    "/api/workspaces", "/api/workspaces/draw", "/api/workspaces/{ws_id}", "/api/workspaces/{ws_id}/status",
    "/api/workspaces/{ws_id}/rerun", "/api/workspaces/{ws_id}/roi", "/api/workspaces/{ws_id}/grid",
    "/api/workspaces/{ws_id}/analysis", "/api/workspaces/{ws_id}/analysis/{indicator}",
    "/api/workspaces/{ws_id}/points", "/api/workspaces/{ws_id}/export/{kind}", "/api/workspaces/{ws_id}/summary-text",
    "/api/workspaces/{ws_id}/species", "/api/workspaces/{ws_id}/species/{name}", "/api/media/{name}",
    "/api/references/res0126",
}


def test_routes_registered():
    paths = set(app.openapi()["paths"])
    assert EXPECTED <= paths, EXPECTED - paths
