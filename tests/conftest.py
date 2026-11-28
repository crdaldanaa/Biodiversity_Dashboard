import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from src.analytics import AnalysisContext
from src.config_loader import get_config

ROI = box(-73.8, 4.0, -73.5, 4.3)


@pytest.fixture()
def ctx(tmp_path):
    rng = np.random.default_rng(0)
    n = 600
    species = [f"Genus sp{i}" for i in range(40)]
    weights = np.array([1 / (i + 1) for i in range(40)])
    df = pd.DataFrame({
        "gbifID": np.arange(n),
        "datasetKey": rng.choice(["a", "b"], n),
        "kingdom": "Animalia", "phylum": "Chordata",
        "tax_class": rng.choice(["Aves", "Mammalia"], n, p=[0.8, 0.2]),
        "tax_order": "Ord", "family": rng.choice(["F1", "F2", "F3"], n), "genus": "Genus",
        "species": rng.choice(species, n, p=weights / weights.sum()),
        "scientificName": "x", "stateProvince": rng.choice(["Meta", "Guaviare"], n),
        "coordinateUncertaintyInMeters": rng.choice([np.nan, 30.0, 500.0, 20000.0], n),
        "elevation": np.nan, "eventDate": "2022-01-01",
        "year": rng.integers(2015, 2025, n), "month": rng.integers(1, 13, n), "day": rng.integers(1, 28, n),
        "basisOfRecord": rng.choice(["HUMAN_OBSERVATION", "PRESERVED_SPECIMEN"], n, p=[0.9, 0.1]),
        "institutionCode": "CLO", "recordedBy": "obs", "license": "CC0", "issue": None, "mediaType": None,
        "lon": rng.uniform(-73.79, -73.51, n), "lat": rng.uniform(4.01, 4.29, n),
    })
    path = tmp_path / "occ.parquet"
    df.to_parquet(path)
    sp = df.groupby("species").agg(n_records=("gbifID", "size"), tax_class=("tax_class", "first"),
                                   family=("family", "first")).reset_index()
    sp["kingdom"] = "Animalia"
    sp["threat_national"] = None
    sp.loc[0, "threat_national"] = "EN"
    sp["threat_global"] = "LC"
    sp.loc[1, "threat_global"] = "VU"
    sp["common_name"], sp["cites"] = None, ""
    sp["exotic"] = sp["invasive"] = sp["new_in_2024"] = False
    roi = gpd.GeoDataFrame(geometry=[ROI], crs="EPSG:4326")
    return AnalysisContext(occurrences_path=path.as_posix(), roi=roi, metric_crs="EPSG:9377",
                           cfg=get_config()["settings"]["analysis"], species=sp)
