from datetime import datetime, timezone

import pytest

from src.update_recommendations import update
from tests.test_backend_import import FakeResponse, event, to_frame

NOW = datetime(2026, 11, 26, 15, 10, tzinfo=timezone.utc)  # KST 11/27 00:10
TRAPS = [{"trap_id": "TRAP-01", "report_interval_seconds": 700}]
DEPLOYMENTS = [{"trap_id": "TRAP-01", "location_id": "z-kitchen", "started_at": "2026-11-24T15:00:00.000000Z",
                "ended_at": None}]
YESTERDAY = datetime(2026, 11, 26, 3, 0, tzinfo=timezone.utc)  # KST 11/26 12:00


class Reply:
    def __init__(self, status, data):
        self.status_code, self.data = status, data

    def json(self):
        return self.data


class Backend:
    """CSV 내보내기·트랩·설치 이력 조회와 추천 저장·조회만 흉내 낸다."""

    def __init__(self, rows):
        self.csv = to_frame(rows).to_csv(index=False) if rows else ",".join(to_frame([]).columns) + "\n"
        self.runs, self.periods = [], []

    def get(self, url, params=None, headers=None, timeout=None):
        if url.endswith("events.csv"):
            self.periods.append((params["from"], params["to"]))
            return FakeResponse(text=self.csv)
        return FakeResponse(data={"items": TRAPS if url.endswith("traps") else DEPLOYMENTS})

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):
        if method == "POST":
            assert headers == {"Authorization": "Bearer write"}
            self.runs.append(json)
            return Reply(201, {"duplicate": False})
        return Reply(200, {"items": self.runs})


def visit(at):
    common = {"visit_id": "v1", "deployment_id": "dep-1"}
    return [event("entry_detected", at, "e1", **common),
            event("visit_resolved", at, "r1", species_code="rat", outcome="unconfirmed", **common)]


def test_stores_one_run_per_trap_from_real_and_virtual_data():
    backend = Backend(visit(YESTERDAY))
    payload = update("http://pi:5000", write_token="write", now=NOW, session=backend)
    items = {r["trap_id"]: r for r in payload["recommendations"]}
    assert {"TRAP-01", "TRAP-02", "TRAP-03"} <= set(items) and len(backend.runs) == len(items)
    assert items["TRAP-01"]["current_location_id"] == "z-kitchen"
    assert items["TRAP-01"]["actual_stats"]["rat_detections"] == 1
    # 어제까지의 28일. 가상 시나리오 날짜도 같은 기간에 맞춘다.
    assert backend.periods == [("2026-10-29T15:00:00Z", "2026-11-26T15:00:00Z")]
    assert payload["analysis_period"] == {"from": "2026-10-30T00:00:00+09:00", "to": "2026-11-27T00:00:00+09:00"}


def test_nothing_is_stored_when_the_real_trap_is_not_installed(monkeypatch):
    monkeypatch.setitem(DEPLOYMENTS[0], "trap_id", "TRAP-09")
    backend = Backend([])
    with pytest.raises(ValueError, match="TRAP-01"):
        update("http://pi:5000", write_token="write", now=NOW, session=backend)
    assert backend.runs == []
