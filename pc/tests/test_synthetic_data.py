"""가상 시나리오 데이터셋이 설계안(docs/synthetic_data_design.md)의 규칙을 지키는지 검사한다."""
import pandas as pd
import pytest

from src.synthetic_data import SUMMARY_COLUMNS, generate_scenario


@pytest.fixture(scope="module")
def data():
    return generate_scenario(write=False)


def test_deterministic():
    a, b = generate_scenario(write=False), generate_scenario(write=False)
    for name in a:
        pd.testing.assert_frame_equal(a[name], b[name])


def test_columns_and_sources(data):
    s = data["trap_day_summary"]
    assert list(s.columns) == SUMMARY_COLUMNS
    assert set(s["detection_source"]) == {"synthetic"} and set(s["capture_source"]) == {"synthetic"}
    assert set(data["detection_events"]["data_source"]) == {"synthetic"}
    assert set(data["simulated_captures"]["data_source"]) == {"synthetic"}


def test_rule1_captures_not_exceed_rat_detections(data):
    s = data["trap_day_summary"]
    assert (s["sim_captures"] <= s["rat_detections"]).all()


def test_rule2_no_capture_when_not_operating(data):
    s = data["trap_day_summary"]
    zero = s[s["operating_hours"] == 0]
    assert len(zero) >= 1  # 가동 0시간인 날이 실제로 존재
    assert (zero[["rat_detections", "non_rat_detections", "unclassified_detections", "sim_captures"]] == 0).all().all()


def test_rule3_one_capture_per_event(data):
    c, e = data["simulated_captures"], data["detection_events"]
    assert c["event_id"].is_unique
    assert set(c["event_id"]) <= set(e[e["classification"] == "rat"]["event_id"])  # rat로 분류된 이벤트만 포획


def test_rule5_missing_sensor_values_stay_null(data):
    s = data["trap_day_summary"]
    assert s["avg_temperature_c"].isna().any()  # 0시간 날 -> 결측
    assert not (s[["avg_temperature_c", "avg_tvoc_ppb"]] == 0).any().any()


def test_summary_matches_logs(data):
    s, c, e = data["trap_day_summary"], data["simulated_captures"], data["detection_events"]
    assert s["sim_captures"].sum() == len(c)
    assert s["rat_detections"].sum() == (e["classification"] == "rat").sum()
    assert s["non_rat_detections"].sum() == (e["classification"] == "non_rat").sum()
    assert s["unclassified_detections"].sum() == e["classification"].isna().sum()
    # 로그의 날짜별 포획 수 == 일 집계
    per_day = c.assign(date=c["captured_at"].str[:10]).groupby(["trap_id", "date"]).size()
    summed = s.groupby(["trap_id", "date"])["sim_captures"].sum()
    for key, n in per_day.items():
        assert summed.loc[key] == n


def test_capture_after_detection_same_day(data):
    m = data["simulated_captures"].merge(data["detection_events"], on="event_id")
    assert (m["captured_at"] >= m["detected_at"]).all()
    assert (m["captured_at"].str[:10] == m["detected_at"].str[:10]).all()


def _loc(s, loc):
    d = s[s["location_id"] == loc]
    return d["rat_detections"].sum() / d["operating_hours"].sum(), d["sim_captures"].sum() / max(d["rat_detections"].sum(), 1)


def test_scenarios_have_designed_characteristics(data):
    s = data["trap_day_summary"]
    rate_a, conv_a = _loc(s, "LOC-A")
    rate_b, conv_b = _loc(s, "LOC-B")
    rate_c, _ = _loc(s, "LOC-C")
    rate_f, conv_f = _loc(s, "LOC-F")
    assert rate_b > 3 * rate_c and rate_a > 3 * rate_c          # C는 감지 자체가 적음
    assert conv_b < 0.5 * conv_a and conv_f < 0.5 * conv_a       # B, F는 감지 대비 포획이 낮음
    # 장치 문제: TRAP-06은 위치를 옮겨도(A) 낮고, 위치 문제: TRAP-02는 A에서 정상
    t6a = s[(s["trap_id"] == "TRAP-06") & (s["location_id"] == "LOC-A")]
    t2a = s[(s["trap_id"] == "TRAP-02") & (s["location_id"] == "LOC-A")]
    conv = lambda d: d["sim_captures"].sum() / d["rat_detections"].sum()
    assert conv(t6a) < 0.15 and conv(t2a) > 0.15


def test_location_d_is_short_observation(data):
    d = data["trap_day_summary"].query("location_id == 'LOC-D'")
    assert d["date"].nunique() == 3
    assert "LOC-E" not in set(data["trap_day_summary"]["location_id"])  # 후보 위치는 이력 없음
