import json
import re
from datetime import datetime

import pytest

from src.api_client import ApiError
from src.backend_client import BackendTransport, backend_client, from_backend_runs, to_backend_runs
from src.export_recommendations import KST, build_payload, export_recommendations
from src.recommendation import recommend
from src.synthetic_data import generate_scenario

NOW = datetime(2026, 11, 23, 14, 5, 30, tzinfo=KST)
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")


@pytest.fixture(scope="module")
def summary():
    return generate_scenario(write=False)["trap_day_summary"]


@pytest.fixture()
def payload(summary):
    items, _ = recommend(summary)
    return build_payload(items, summary, now=NOW)


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class FakeBackend:
    """backend/app/recommendations.py의 저장 규칙(같은 run_id: 같은 내용이면 200 duplicate, 다르면 409)을 흉내 낸다."""

    def __init__(self):
        self.runs, self.calls = {}, []

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):
        self.calls.append((method, url, headers))
        if method == "POST":
            if headers.get("Authorization") != "Bearer write":
                return FakeResponse(401, {"error": {"code": "unauthorized", "message": "token"}})
            old = self.runs.get(json["run_id"])
            if old is not None:
                same = old == json
                return FakeResponse(200, {"run_id": json["run_id"], "duplicate": True}) if same else \
                    FakeResponse(409, {"error": {"code": "run_conflict", "message": "different"}})
            self.runs[json["run_id"]] = json
            return FakeResponse(201, {"run_id": json["run_id"], "duplicate": False})
        newest_first = sorted(self.runs.values(), key=lambda r: (r["generated_at"], r["run_id"]), reverse=True)
        return FakeResponse(200, {"items": newest_first[:params["limit"]], "next_offset": None})


def test_runs_follow_backend_contract(payload):
    runs = to_backend_runs(payload)
    assert len(runs) == len(payload["recommendations"])
    for run in runs:
        assert IDENTIFIER.fullmatch(run["run_id"]) and IDENTIFIER.fullmatch(run["trap_id"])
        assert run["status"] in ("ready", "insufficient_data")
        assert run["prediction_kind"] == "target_entry" and run["target_species"] == "rat"
        ranks = [c["rank"] for c in run["candidates"]]
        assert ranks == list(range(1, len(ranks) + 1))
        assert all(0 <= c["score"] <= 1 for c in run["candidates"])
        if run["status"] == "ready":
            assert run["score_type"] == "relative_score" and "reason" not in run
        else:
            assert run["candidates"] == [] and run["reason"] and "score_type" not in run
        assert set(run) <= {"run_id", "trap_id", "target_species", "model_version", "generated_at",
                            "prediction_kind", "data_from", "data_to", "forecast_from", "forecast_to", "status",
                            "score_type", "reason", "candidates", "data_basis", "details"}
        json.dumps(run, allow_nan=False)
        assert datetime.fromisoformat(run["forecast_to"]) > datetime.fromisoformat(run["forecast_from"])
    assert {r["details"]["decision"] for r in runs} == {r["status"] for r in payload["recommendations"]}


def test_recommended_lists_target_then_current(payload):
    run = next(r for r, i in zip(to_backend_runs(payload), payload["recommendations"]) if i["status"] == "recommended")
    item = next(i for i in payload["recommendations"] if i["trap_id"] == run["trap_id"])
    assert [c["location_id"] for c in run["candidates"]][0] == item["recommended_location_id"]
    assert run["candidates"][0]["score"] == item["score"]


def test_round_trip_keeps_everything_including_simulation_marks(payload):
    restored = from_backend_runs(to_backend_runs(payload))
    assert restored["recommendations"] == payload["recommendations"]
    assert restored["data_basis"] == payload["data_basis"] and restored["data_basis"]["is_simulation_based"]
    assert (restored["run_id"], restored["algorithm_version"]) == (payload["run_id"], payload["algorithm_version"])


def test_keep_without_score_cannot_be_expressed(payload):
    keep = next(i for i in payload["recommendations"] if i["status"] == "keep")
    bad = {**payload, "recommendations": [{**keep, "current_location_score": None}]}
    with pytest.raises(ValueError, match="keep"):
        to_backend_runs(bad)


def test_export_through_backend_client(summary):
    fake = FakeBackend()
    client = backend_client("http://pi:5000/", read_token="read", write_token="write", session=fake)
    sent, response = export_recommendations(summary, client, now=NOW)
    assert response == {"run_id": sent["run_id"], "saved_count": len(sent["recommendations"]),
                        "saved_at": sent["generated_at"]}
    assert all(url.startswith("http://pi:5000/api/recommendations") for _, url, _ in fake.calls)
    assert client.get_recommendations(sent["run_id"])["recommendations"] == sent["recommendations"]
    assert client.get_recommendations()["run_id"] == sent["run_id"]
    with pytest.raises(ApiError) as e:  # 같은 run_id 재전송은 거절한다(덮어쓰기, 재시도 없음)
        client.post_recommendations(sent)
    assert (e.value.status, e.value.code) == (409, "DUPLICATE_RESOURCE")


def test_latest_returns_newest_batch_only(summary):
    fake = FakeBackend()
    client = backend_client("http://pi:5000", write_token="write", session=fake)
    first, _ = export_recommendations(summary, client, now=NOW, run_id="RUN-A")
    later = datetime(2026, 11, 24, 9, 0, 0, tzinfo=KST)
    second, _ = export_recommendations(summary, client, now=later, run_id="RUN-B")
    assert client.get_recommendations()["run_id"] == "RUN-B"
    assert client.get_recommendations("RUN-A")["recommendations"] == first["recommendations"]
    with pytest.raises(ApiError) as e:
        client.get_recommendations("RUN-NONE")
    assert e.value.status == 404


def test_auth_failure_and_unsupported_paths(payload):
    fake = FakeBackend()
    client = backend_client("http://pi:5000", write_token="wrong", session=fake)
    with pytest.raises(ApiError) as e:
        client.post_recommendations(payload)
    assert (e.value.status, e.value.code) == (401, "unauthorized") and len(fake.calls) == 1
    with pytest.raises(ApiError) as e:
        client.get_traps()
    assert e.value.status == 501


def test_connection_error_is_reported():
    client = backend_client("http://127.0.0.1:9", timeout=1)
    with pytest.raises(ApiError) as e:
        client.health()
    assert e.value.code == "CONNECTION_ERROR"


def test_partial_save_is_reported(payload):
    class FailsSecond(FakeBackend):
        def request(self, method, url, **kw):
            if method == "POST" and len(self.runs) == 1:
                return FakeResponse(500, {"error": {"code": "internal_error", "message": "boom"}})
            return super().request(method, url, **kw)

    client = backend_client("http://pi:5000", write_token="write", session=FailsSecond())
    with pytest.raises(ApiError) as e:
        client.post_recommendations(payload)
    assert e.value.status == 500 and "앞선 1건" in e.value.message
