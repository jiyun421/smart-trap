import copy
import json
from datetime import datetime

import pytest

from src.api_client import ApiClient, ApiError
from src.export_recommendations import (KST, build_data_basis, build_payload, export_recommendations,
                                        validate_payload)
from src.recommendation import recommend
from src.synthetic_data import generate_scenario

NOW = datetime(2026, 11, 23, 14, 5, 30, tzinfo=KST)


@pytest.fixture(scope="module")
def summary():
    return generate_scenario(write=False)["trap_day_summary"]


@pytest.fixture()
def payload(summary):
    items, _ = recommend(summary)
    return build_payload(items, summary, now=NOW)


def test_payload_header_and_period(payload):
    assert payload["run_id"] == "RUN-20261123-140530"
    assert payload["generated_at"] == "2026-11-23T14:05:30+09:00"
    assert payload["analysis_period"] == {"from": "2026-11-09T00:00:00+09:00",
                                          "to": "2026-12-07T00:00:00+09:00"}  # 28일, to는 배타적
    assert validate_payload(payload) == []


def test_strict_json_serializable(payload):
    text = json.dumps(payload, ensure_ascii=False, allow_nan=False)  # NaN이 있으면 예외
    assert json.loads(text)["run_id"] == payload["run_id"]


def test_data_basis_marks_simulation(summary):
    b = build_data_basis(summary)
    assert b["detection_data"] == "synthetic" and b["capture_data"] == "synthetic"
    assert b["is_simulation_based"] is True and "가상" in b["note"]
    mixed = summary.copy()
    mixed["detection_source"] = "actual"
    b2 = build_data_basis(mixed)
    assert b2["detection_data"] == "actual" and b2["is_simulation_based"] is True
    assert "포획" in b2["note"]


@pytest.mark.parametrize("mutate,expected", [
    (lambda p: p["recommendations"][0].update(status="unknown"), "status 값 오류"),
    (lambda p: p["recommendations"][0].update(relocate=True), "relocate와 status 불일치"),
    (lambda p: p["recommendations"][0].update(score=1.5), "범위"),
    (lambda p: p["recommendations"][0].update(reasons=[]), "reasons"),
    (lambda p: p["recommendations"][0]["actual_stats"].update(rat_detections_per_hour=float("nan")), "NaN"),
    (lambda p: p["data_basis"].update(is_simulation_based=False), "시뮬레이션"),
    (lambda p: p["recommendations"][1].update(trap_id=p["recommendations"][0]["trap_id"]), "trap_id 중복"),
    (lambda p: p.pop("run_id"), "필수 필드"),
])
def test_validate_catches_bad_payloads(payload, mutate, expected):
    bad = copy.deepcopy(payload)
    mutate(bad)
    assert any(expected in e for e in validate_payload(bad))


def test_recommended_requires_location_and_priority(payload):
    bad = copy.deepcopy(payload)
    rec = next(r for r in bad["recommendations"] if r["status"] == "recommended")
    rec["recommended_location_id"] = None
    rec["priority"] = None
    errs = validate_payload(bad)
    assert any("추천 위치" in e for e in errs) and any("priority" in e for e in errs)


def test_build_payload_refuses_invalid(summary):
    items, _ = recommend(summary)
    items[0]["status"] = "bogus"
    with pytest.raises(ValueError):
        build_payload(items, summary, now=NOW)


def test_post_then_get_roundtrip_and_duplicate_409(summary):
    client = ApiClient.from_mock()
    payload, res = export_recommendations(summary, client, now=NOW)
    assert res["saved_count"] == len(payload["recommendations"]) == 5
    saved = client.get_recommendations(payload["run_id"])
    assert saved["data_basis"]["is_simulation_based"] is True
    with pytest.raises(ApiError) as e:
        export_recommendations(summary, client, now=NOW)  # 같은 run_id
    assert e.value.status == 409 and e.value.code == "DUPLICATE_RESOURCE"
    assert len(client._t.saved_runs) == 1  # 덮어쓰기/중복 저장 없음


def test_new_run_after_time_passes(summary):
    client = ApiClient.from_mock()
    export_recommendations(summary, client, now=NOW)
    later = datetime(2026, 11, 23, 14, 6, 30, tzinfo=KST)
    payload, _ = export_recommendations(summary, client, now=later)
    assert payload["run_id"] == "RUN-20261123-140630"
    assert client.get_recommendations()["run_id"] == payload["run_id"]  # 최신 run 조회
