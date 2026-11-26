import numpy as np
import pandas as pd
import pytest

from src import evaluation
from src.recommendation import (location_scores, poisson_rate_interval, recommend, wilson_interval)
from src.synthetic_data import generate_scenario


@pytest.fixture(scope="module")
def result():
    s = generate_scenario(write=False)["trap_day_summary"]
    items, scores = recommend(s, known_locations=["LOC-E"])
    return s, {i["trap_id"]: i for i in items}, scores


def test_wilson_basic():
    lo, hi = wilson_interval(6, 35)
    assert 0 < lo < 6 / 35 < hi < 1
    assert np.isnan(wilson_interval(0, 0)[0])
    assert wilson_interval(0, 10)[0] == 0.0


def test_poisson_interval_contains_rate():
    lo, hi = poisson_rate_interval(6, 640)
    assert lo < 6 / 640 < hi


def test_expected_judgements_default_seed(result):
    _, r, _ = result
    assert set(r) == {"TRAP-01", "TRAP-02", "TRAP-03", "TRAP-04", "TRAP-06"}  # TRAP-05는 철수
    assert r["TRAP-01"]["status"] == "keep" and r["TRAP-02"]["status"] == "keep"
    assert r["TRAP-03"]["status"] == "recommended" and r["TRAP-03"]["recommended_location_id"] == "LOC-A"
    assert r["TRAP-04"]["status"] == "insufficient_data"
    assert r["TRAP-06"]["status"] == "device_check"


def test_api_field_consistency(result):
    _, r, _ = result
    for i in r.values():
        assert i["relocate"] == (i["status"] == "recommended")
        if i["status"] != "recommended":
            assert i["recommended_location_id"] is None and i["priority"] is None
        assert i["reasons"] and set(i["actual_stats"]) == {"operating_hours", "rat_detections",
                                                           "non_rat_detections", "rat_detections_per_hour"}
    assert r["TRAP-03"]["priority"] == 1
    assert r["TRAP-03"]["recommended_location_type"] == "existing"


def test_device_trap_excluded_from_location_scores(result):
    s, _, scores = result
    # TRAP-06 데이터를 빼면 LOC-A 전환율이 정상 트랩 수준으로 올라간다
    with_all = location_scores(s)["sim_conversion"]["LOC-A"]
    assert scores["sim_conversion"]["LOC-A"] > with_all
    assert pd.isna(scores["score"]["LOC-D"]) and pd.isna(scores["score"]["LOC-E"])  # 데이터 부족/이력 없음
    assert scores["score"]["LOC-A"] == 1.0


def test_candidate_location_never_recommended(result):
    _, r, _ = result
    assert all(i["recommended_location_id"] != "LOC-E" for i in r.values())


def test_missing_captures_column_raises():
    s = generate_scenario(write=False)["trap_day_summary"].drop(columns=["sim_captures"])
    with pytest.raises(ValueError):
        recommend(s)


def test_multi_seed_match_and_null_scenario():
    seeds = range(42, 47)  # 빠른 검증용 5개 (전체 20개는 python -m src.evaluation)
    assert evaluation.evaluate(seeds)["all_ok"].all()
    assert evaluation.null_scenario(seeds) == {"keep": 20}
    assert evaluation.null_scenario(seeds) == {"keep": 20}  # 원래 파라미터가 복원돼도 결과 동일
    assert evaluation.synthetic_data.LOCATION_PARAMS["LOC-B"] == (0.30, 0.05)
