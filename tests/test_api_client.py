import pytest

from src.api_client import ApiClient, ApiError, HttpTransport

FROM = "2026-11-09T00:00:00+09:00"
TO = "2026-11-23T00:00:00+09:00"


@pytest.fixture
def client():
    return ApiClient.from_mock()


def test_health_and_simple_lists(client):
    assert client.health()["status"] == "ok"
    assert len(client.get_traps()) == 4
    assert len(client.get_locations()) == 5
    assert [h["trap_id"] for h in client.get_location_history("TRAP-02")] == ["TRAP-02"]


def test_pagination_collects_all_pages(client):
    small = client._get_all("/sensor-readings", FROM, TO, page_size=100)  # 여러 페이지
    big = client.get_sensor_readings(FROM, TO)
    assert len(small) == len(big) > 1000
    assert [r["reading_id"] for r in small] == [r["reading_id"] for r in big]


def test_trap_and_period_filter(client):
    rows = client.get_detection_events(FROM, TO, trap_id="TRAP-01")
    assert rows and all(r["trap_id"] == "TRAP-01" for r in rows)
    half = client.get_detection_events(FROM, "2026-11-16T00:00:00+09:00", trap_id="TRAP-01")
    assert 0 < len(half) < len(rows)


def test_invalid_period_raises_api_error(client):
    with pytest.raises(ApiError) as e:
        client.get_sensor_readings(TO, FROM)
    assert e.value.status == 400 and e.value.code == "INVALID_PARAMETER"


def _payload(run_id="RUN-1"):
    return {"run_id": run_id, "generated_at": TO, "analysis_period": {"from": FROM, "to": TO},
            "algorithm_version": "t", "data_basis": {"is_simulation_based": True},
            "recommendations": [{"trap_id": "TRAP-01"}]}


def test_post_get_recommendations_roundtrip(client):
    res = client.post_recommendations(_payload())
    assert res["saved_count"] == 1
    assert client.get_recommendations()["run_id"] == "RUN-1"
    assert client.get_recommendations("RUN-1")["recommendations"][0]["trap_id"] == "TRAP-01"


def test_duplicate_run_id_is_409(client):
    client.post_recommendations(_payload())
    with pytest.raises(ApiError) as e:
        client.post_recommendations(_payload())
    assert e.value.status == 409 and e.value.code == "DUPLICATE_RESOURCE"


def test_invalid_body_is_422(client):
    with pytest.raises(ApiError) as e:
        client.post_recommendations({"run_id": "X"})
    assert e.value.status == 422


def test_get_without_saved_run_is_404(client):
    with pytest.raises(ApiError) as e:
        client.get_recommendations()
    assert e.value.status == 404


def test_connection_error_is_api_error():
    c = ApiClient(HttpTransport("http://127.0.0.1:9/api/v1", timeout=1))
    with pytest.raises(ApiError) as e:
        c.health()
    assert e.value.code == "CONNECTION_ERROR"
