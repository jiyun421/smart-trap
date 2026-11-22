import numpy as np
import pandas as pd
import pytest

from src.api_client import ApiClient
from src.metrics import add_derived_metrics, aggregate_performance
from src.preprocessing import (BASE_SUMMARY_COLUMNS, build_trap_day_summary, clean_events,
                               clean_sensor_readings, load_trap_day_summary)
from src.synthetic_data import generate_scenario

FROM, TO = "2026-11-09T00:00:00+09:00", "2026-11-23T00:00:00+09:00"


# ------------------------------------------------------------ 정제
def _ev(i, **kw):
    base = {"event_id": i, "trap_id": "TRAP-01", "detected_at": "2026-11-10T01:00:00+09:00",
            "ir_detected": True, "classification": "rat", "confidence": 0.9}
    return {**base, **kw}


def test_clean_events_dedup_and_invalid_values():
    rows = [_ev(1), _ev(1), _ev(2, classification="cat", confidence=0.8),
            _ev(3, confidence=1.7), _ev(4, detected_at="not-a-time"), _ev(5, classification=None, confidence=None)]
    df, rep = clean_events(rows)
    assert rep["duplicates_removed"] == 1 and rep["invalid_time_removed"] == 1
    assert rep["invalid_class_set_null"] == 1 and rep["invalid_confidence_set_null"] == 1
    assert len(df) == 4
    assert df.loc[df["event_id"] == 2, "classification"].isna().all()
    assert df.loc[df["event_id"] == 3, "confidence"].isna().all()  # 0이 아닌 결측


def test_clean_sensors_out_of_range_becomes_nan_not_zero():
    base = {"trap_id": "TRAP-01", "measured_at": "2026-11-10T01:00:00+09:00", "load_cell_g": None}
    rows = [{**base, "reading_id": 1, "temperature_c": 99.0, "humidity_pct": 50.0, "tvoc_ppb": 100, "eco2_ppm": 500},
            {**base, "reading_id": 1, "temperature_c": 22.0, "humidity_pct": 50.0, "tvoc_ppb": 100, "eco2_ppm": 500},
            {**base, "reading_id": 2, "temperature_c": 22.0, "humidity_pct": 120.0, "tvoc_ppb": None, "eco2_ppm": 500}]
    df, rep = clean_sensor_readings(rows)
    assert rep["duplicates_removed"] == 1 and len(df) == 2
    assert np.isnan(df.loc[df["reading_id"] == 1, "temperature_c"]).all()  # 99도 -> 이상치 NaN
    assert rep["out_of_range_set_null"]["humidity_pct"] == 1
    assert df["tvoc_ppb"].isna().sum() == 1


# ------------------------------------------- Mock API -> 일 집계 (통합 흐름)
@pytest.fixture(scope="module")
def mock_summary():
    c = ApiClient.from_mock()
    events, _ = clean_events(c.get_detection_events(FROM, TO))
    sensors, _ = clean_sensor_readings(c.get_sensor_readings(FROM, TO))
    summary, rep = build_trap_day_summary(events, sensors, c.get_status_logs(FROM, TO),
                                          c.get_location_history(), FROM, TO)
    return summary, rep, events


def test_summary_columns_and_totals(mock_summary):
    s, rep, events = mock_summary
    assert list(s.columns) == BASE_SUMMARY_COLUMNS
    assert set(s["detection_source"]) == {"actual"}
    assert rep == {"events_without_location": 0, "sensors_without_location": 0}
    total = s[["rat_detections", "non_rat_detections", "unclassified_detections"]].sum().sum()
    assert total == len(events)  # 이벤트가 하나도 사라지거나 중복되지 않음


def test_operating_hours_reflect_stop_and_short_install(mock_summary):
    s, _, _ = mock_summary
    hours = s.groupby("trap_id")["operating_hours"].sum()
    assert hours["TRAP-01"] == pytest.approx(14 * 24)
    assert hours["TRAP-02"] == pytest.approx(14 * 24 - 12)  # 12시간 작동 중단 제외
    assert hours["TRAP-04"] == pytest.approx(48)             # 설치 2일
    assert s["operating_hours"].between(0, 24).all()


def test_no_detections_while_stopped_in_summary(mock_summary):
    s, _, _ = mock_summary
    stopped_day = s[(s["trap_id"] == "TRAP-02") & (s["date"] == "2026-11-14")]
    assert stopped_day["operating_hours"].iloc[0] == pytest.approx(12)


# ------------------------------------------------------------ 지표
@pytest.fixture(scope="module")
def synthetic():
    return generate_scenario(write=False)["trap_day_summary"]


def test_metrics_aggregate_by_location(synthetic):
    m = aggregate_performance(synthetic).set_index("location_id")
    assert m.loc["LOC-D", "is_insufficient"] and m.loc["LOC-D", "observed_days"] == 3
    assert not m.loc["LOC-A", "is_insufficient"] and not m.loc["LOC-B", "is_insufficient"]
    a = m.loc["LOC-A"]
    assert a["detection_rate"] == pytest.approx(a["rat_detections"] / a["operating_hours"])
    assert a["sim_conversion"] == pytest.approx(a["sim_captures"] / a["rat_detections"])
    assert m.loc["LOC-B", "sim_conversion"] < m.loc["LOC-A", "sim_conversion"]


def test_zero_denominator_is_nan_not_zero():
    df = pd.DataFrame({"operating_hours": [0.0, 10.0], "rat_detections": [0, 0], "non_rat_detections": [0, 0],
                       "sim_captures": [0, 0]})
    out = add_derived_metrics(df)
    assert np.isnan(out.loc[0, "detection_rate"]) and np.isnan(out.loc[0, "sim_capture_rate"])
    assert out.loc[1, "detection_rate"] == 0.0           # 작동했는데 감지 0건은 실제 0
    assert out["sim_conversion"].isna().all()            # 감지가 없으면 전환율 계산 불가
    assert out["non_rat_ratio"].isna().all()


def test_metrics_without_capture_column(mock_summary):
    s, _, _ = mock_summary
    m = aggregate_performance(s)  # 실제 데이터에는 sim_captures 없음
    assert m["sim_conversion"].isna().all() and m["detection_rate"].notna().all()


def test_load_summary_csv_roundtrip(tmp_path):
    s = generate_scenario(out_dir=tmp_path)["trap_day_summary"]
    loaded = load_trap_day_summary(tmp_path / "trap_day_summary.csv")
    assert len(loaded) == len(s) and loaded["date"].iloc[0] == s["date"].iloc[0]
