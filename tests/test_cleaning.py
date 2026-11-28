"""Paso `clean`: duplicados, tipos de registro, años y marca de incertidumbre para análisis espaciales."""
import duckdb
import pandas as pd

from src.processing.cleaning import clean_occurrences


def _occ(tmp_path):
    df = pd.DataFrame({
        "gbifID": [1, 2, 3, 4, 5, 6, 7],
        "species": ["A a", "A a", "B b", "C c", "D d", "E e", "F f"],
        "scientificName": ["A a"] * 2 + ["B b", "C c", "D d", "E e", "F f"],
        "lon": [-73.5, -73.5, -73.6, -73.7, -73.8, -73.9, -73.4],
        "lat": [4.1] * 7,
        "eventDate": ["2020-01-01", "2020-01-01", "2021-05-05", "1950-01-01", None, "2026-03-01", "2019-02-02"],
        "year": [2020, 2020, 2021, 1950, None, 2026, 2019],
        "basisOfRecord": ["HUMAN_OBSERVATION"] * 3 + ["PRESERVED_SPECIMEN"] + ["HUMAN_OBSERVATION"] * 3,
        "coordinateUncertaintyInMeters": [None, 50.0, 30000.0, None, None, None, 20.0],
    })
    p = tmp_path / "occurrences.parquet"
    df.to_parquet(p)
    return p


def test_clean_rules(tmp_path):
    occ = _occ(tmp_path)
    st = clean_occurrences(occ, tmp_path / "raw.parquet", {"year_max": 2025})
    assert st["raw"] == 7
    assert st["removed_basis"] == 1 and st["removed_no_year"] == 1 and st["removed_after_max"] == 1
    assert st["removed_duplicates"] == 1
    df = duckdb.sql(f"SELECT * FROM '{occ.as_posix()}' ORDER BY gbifID").df()
    assert df["gbifID"].tolist() == [2, 3, 7]  # del duplicado queda el de menor incertidumbre
    assert df.set_index("gbifID")["spatial_ok"].to_dict() == {2: True, 3: False, 7: True}
    assert st["final"] == 3 and st["spatial_excluded"] == 1


def test_clean_is_repeatable_from_raw(tmp_path):
    occ = _occ(tmp_path)
    raw = tmp_path / "raw.parquet"
    clean_occurrences(occ, raw, {"year_max": 2025})
    st = clean_occurrences(occ, raw, {"year_max": None, "exclude_basis": []})  # criterios más laxos
    assert st["raw"] == 7 and st["final"] == 5
