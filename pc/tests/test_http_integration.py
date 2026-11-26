"""실제 HTTP를 거치는 통합 테스트 (로컬 Mock 서버). Pi 서버 검증이 아니라 PC 쪽 클라이언트/전송 경로 검증이다."""
import json
import urllib.request

import pytest

from src.api_client import ApiClient, ApiError
from src.export_recommendations import SCENARIO_CSV, export_recommendations
from src.mock_server import start_in_thread
from src.preprocessing import load_trap_day_summary


@pytest.fixture()
def server():
    srv = start_in_thread()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


@pytest.fixture()
def client(server):
    return ApiClient.from_url(server + "/api/v1", timeout=5)


def test_조회_API가_HTTP로_동작한다(client):
    assert client.health()
    assert len(client.get_traps()) > 0
    ev = client.get_detection_events("2026-11-09T00:00:00+09:00", "2026-11-10T00:00:00+09:00")
    assert isinstance(ev, list)


def test_추천_전송_재조회_중복거절(client):
    summary = load_trap_day_summary(SCENARIO_CSV)
    payload, resp = export_recommendations(summary, client, run_id="RUN-HTTP-1")
    assert resp["run_id"] == "RUN-HTTP-1" and resp["saved_count"] == len(payload["recommendations"])
    with pytest.raises(ApiError) as e:
        client.post_recommendations(payload)
    assert (e.value.status, e.value.code) == (409, "DUPLICATE_RESOURCE")
    assert client.get_recommendations()["run_id"] == "RUN-HTTP-1"  # latest 기본 동작


def test_없는_run_은_404(client):
    with pytest.raises(ApiError) as e:
        client.get_recommendations("RUN-NOPE")
    assert e.value.status == 404


def test_서버가_없으면_CONNECTION_ERROR():
    with pytest.raises(ApiError) as e:
        ApiClient.from_url("http://127.0.0.1:1/api/v1", timeout=1).health()
    assert e.value.code == "CONNECTION_ERROR"


def test_대시보드가_같은_출처에서_제공되고_API를_읽는다(server, client):
    html = urllib.request.urlopen(server + "/dashboard/").read().decode()
    assert "js/layout.js" in html  # 상시 배너(sim-banner)는 layout.js가 그린다
    layout = urllib.request.urlopen(server + "/dashboard/js/layout.js").read().decode()
    assert "sim-banner" in layout
    summary = load_trap_day_summary(SCENARIO_CSV)
    export_recommendations(summary, client, run_id="RUN-HTTP-2")
    # 대시보드가 쓰는 URL: GET {apiBase}/recommendations (파라미터 없음 = 최신 run)
    data = json.loads(urllib.request.urlopen(server + "/api/v1/recommendations").read())
    assert data["run_id"] == "RUN-HTTP-2" and data["data_basis"]["is_simulation_based"] is True
