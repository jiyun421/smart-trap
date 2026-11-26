from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from src.export_recommendations import KST, build_data_basis, build_payload
from src.mvp_dataset import add_virtual_captures, build_mvp_summary
from src.preprocessing import BASE_SUMMARY_COLUMNS
from src.recommendation import recommend
from src.synthetic_data import generate_scenario


@pytest.fixture(scope="module")
def synthetic():
    return generate_scenario(write=False)["trap_day_summary"]


def actual_summary(location="LOC-REAL-1"):
    dates = pd.date_range("2026-11-09", periods=28).strftime("%Y-%m-%d")
    return pd.DataFrame({
        "trap_id": "TRAP-01", "location_id": location, "date": dates, "operating_hours": 20.0,
        "rat_detections": 4, "non_rat_detections": 1, "unclassified_detections": 0,
        "avg_temperature_c": 21.0, "avg_humidity_pct": 50.0, "avg_tvoc_ppb": np.nan, "avg_eco2_ppm": np.nan,
        "detection_source": "actual",
    })[BASE_SUMMARY_COLUMNS]


def test_virtual_captures_are_marked_and_bounded():
    out = add_virtual_captures(actual_summary())
    assert (out["sim_captures"] <= out["rat_detections"]).all() and out["sim_captures"].sum() > 0
    assert set(out["capture_source"]) == {"synthetic"} and set(out["detection_source"]) == {"actual"}
    assert out["sim_captures"].equals(add_virtual_captures(actual_summary())["sim_captures"])  # 같은 시드 -> 재현


def test_only_real_trap_is_actual(synthetic):
    merged = build_mvp_summary(actual_summary(), synthetic)
    assert set(merged.loc[merged["trap_id"] == "TRAP-01", "detection_source"]) == {"actual"}
    assert set(merged.loc[merged["trap_id"] == "TRAP-01", "location_id"]) == {"LOC-REAL-1"}
    assert set(merged.loc[merged["trap_id"] != "TRAP-01", "detection_source"]) == {"synthetic"}
    assert merged["trap_id"].nunique() == synthetic["trap_id"].nunique()
    basis = build_data_basis(merged)
    assert (basis["detection_data"], basis["capture_data"], basis["is_simulation_based"]) == ("mixed", "synthetic", True)


def test_real_and_synthetic_locations_must_not_mix(synthetic):
    with pytest.raises(ValueError, match="LOC-A"):
        build_mvp_summary(actual_summary("LOC-A"), synthetic)
    with pytest.raises(ValueError, match="TRAP-01"):
        build_mvp_summary(actual_summary().assign(trap_id="TRAP-09"), synthetic)


def test_recommendation_runs_on_merged_summary(synthetic):
    merged = build_mvp_summary(actual_summary(), synthetic)
    items, _ = recommend(merged)
    payload = build_payload(items, merged, now=datetime(2026, 12, 7, 9, tzinfo=KST))
    assert payload["data_basis"]["is_simulation_based"]
    # 현재 설치 중인 트랩만 추천 대상이다(시나리오의 TRAP-05는 이미 철수). 실제 트랩도 포함되어야 한다.
    assert {r["trap_id"] for r in payload["recommendations"]} == {"TRAP-01", "TRAP-02", "TRAP-03", "TRAP-04", "TRAP-06"}
