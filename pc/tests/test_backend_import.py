import csv
import io
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from src.api_client import ApiError
from src.backend_import import build_summary, fetch_backend_data, sensor_rows, status_logs, visit_rows

COLUMNS = ["schema_version", "trap_id", "deployment_id", "location_id", "visit_id", "event_id", "event_type",
           "observed_at", "received_at", "target_species", "species_code", "confidence", "temperature_c",
           "humidity_pct", "illuminance_lux", "bait_g", "door_state", "occupancy_state", "outcome",
           "outcome_evidence"]
T0 = datetime(2026, 11, 9, 15, 0, 0, tzinfo=timezone.utc)  # = KST 2026-11-10 00:00
TRAPS = [{"trap_id": "TRAP-01", "report_interval_seconds": 60}]
DEPLOYMENTS = [
    {"trap_id": "TRAP-01", "location_id": "LOC-A", "started_at": "2026-11-09T15:00:00.000000Z",
     "ended_at": "2026-11-10T15:00:00.000000Z"},  # KST 11/10 하루
    {"trap_id": "TRAP-01", "location_id": "LOC-B", "started_at": "2026-11-10T15:00:00.000000Z", "ended_at": None},
]


def z(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000000Z")


def event(kind, at, eid, **kw):
    row = dict.fromkeys(COLUMNS, "")
    row.update(schema_version="1", trap_id="TRAP-01", deployment_id="dep-1", event_id=eid, event_type=kind,
               observed_at=z(at), received_at=z(at))
    row.update(kw)
    return row


def to_frame(rows):
    out = io.StringIO()
    w = csv.DictWriter(out, COLUMNS)
    w.writeheader()
    w.writerows(rows)
    return pd.read_csv(io.StringIO(out.getvalue()), dtype=str)


@pytest.fixture()
def events():
    rows = [event("telemetry", T0 + timedelta(minutes=m), f"t{m}", temperature_c="20", humidity_pct="50",
                  bait_g="12") for m in range(61)]  # 매 분, 1시간
    rows[0]["temperature_c"] = "22"  # 평균 확인용
    rows += [
        event("entry_detected", T0 + timedelta(minutes=10), "e1", visit_id="v1"),
        event("visit_resolved", T0 + timedelta(minutes=10, seconds=20), "r1", visit_id="v1",
              species_code="rat", confidence="0.9", outcome="capture_confirmed"),
        event("entry_detected", T0 + timedelta(minutes=20), "e2", visit_id="v2"),
        event("visit_resolved", T0 + timedelta(minutes=20, seconds=20), "r2", visit_id="v2",
              species_code="mouse", confidence="0.7", outcome="release_confirmed"),
        event("entry_detected", T0 + timedelta(minutes=30), "e3", visit_id="v3"),  # 종 미정
        event("entry_detected", T0 + timedelta(minutes=40), "e4", visit_id="v4"),
        event("visit_resolved", T0 + timedelta(minutes=40, seconds=20), "r4", visit_id="v4",
              species_code="unknown", outcome="unconfirmed"),
        # 재배치 후(LOC-B) 감지
        event("entry_detected", T0 + timedelta(hours=24), "e5", visit_id="v5", deployment_id="dep-2"),
        event("visit_resolved", T0 + timedelta(hours=24, seconds=20), "r5", visit_id="v5", deployment_id="dep-2",
              species_code="rat", confidence="0.8", outcome="release_confirmed"),
    ]
    return to_frame(rows)


def test_visit_classification(events):
    by = {r["event_id"]: r for r in visit_rows(events)}
    assert by["dep-1:v1"]["classification"] == "rat" and by["dep-1:v1"]["confidence"] == 0.9
    assert by["dep-1:v2"]["classification"] == "non_rat"
    assert by["dep-1:v3"]["classification"] is None and by["dep-1:v3"]["confidence"] is None  # 종 미정
    assert by["dep-1:v4"]["classification"] is None  # unknown은 미분류
    assert len(by) == 5


def test_summary_counts_hours_and_missing_values(events):
    summary, report = build_summary(events, TRAPS, DEPLOYMENTS, "2026-11-10", "2026-11-12")
    day1 = summary[(summary["date"] == "2026-11-10")].iloc[0]
    assert day1["location_id"] == "LOC-A" and day1["detection_source"] == "actual"
    assert (day1["rat_detections"], day1["non_rat_detections"], day1["unclassified_detections"]) == (1, 1, 2)
    assert day1["operating_hours"] == pytest.approx(1.05)  # 60분 + 마지막 보고 뒤 3분
    assert day1["avg_temperature_c"] == pytest.approx((22 + 20 * 60) / 61, abs=0.01)
    assert np.isnan(day1["avg_tvoc_ppb"]) and np.isnan(day1["avg_eco2_ppm"])  # 0이 아니라 결측
    day2 = summary[summary["date"] == "2026-11-11"].iloc[0]
    assert day2["location_id"] == "LOC-B" and day2["rat_detections"] == 1
    assert "sim_captures" not in summary and report["events_without_location"] == 0


def test_gap_longer_than_three_intervals_is_not_operating():
    ev = to_frame([event("telemetry", T0 + timedelta(seconds=s), f"t{s}", temperature_c="20")
                   for s in (0, 60, 120, 3600)])
    logs = [(r["status"], r["changed_at"]) for r in status_logs(ev, TRAPS)]
    assert logs == [("operating", "2026-11-09T15:00:00Z"), ("offline", "2026-11-09T15:05:00Z"),
                    ("operating", "2026-11-09T16:00:00Z"), ("offline", "2026-11-09T16:03:00Z")]


class FakeResponse:
    def __init__(self, text=None, data=None, status=200):
        self.status_code, self._data = status, data
        self.content = (text or "").encode("utf-8")

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, csv_text, status=200):
        self.csv_text, self.calls, self.status = csv_text, [], status

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        if self.status >= 400:
            return FakeResponse(status=self.status)
        if url.endswith("events.csv"):
            return FakeResponse(text=self.csv_text)
        return FakeResponse(data={"items": TRAPS if url.endswith("traps") else DEPLOYMENTS})


def test_fetch_splits_period_into_chunks_and_sends_token():
    one = to_frame([event("telemetry", T0, "t0", temperature_c="20")])
    text = one.to_csv(index=False)
    session = FakeSession(text)
    events, traps, deployments = fetch_backend_data("http://pi:5000/", "2026-11-01", "2026-12-15",
                                                    read_token="rd", session=session)
    csv_calls = [c for c in session.calls if c[0].endswith("events.csv")]
    assert len(csv_calls) == 2 and len(events) == 2  # 44일 -> 30일 + 14일
    assert csv_calls[0][1]["from"] == "2026-10-31T15:00:00Z" and csv_calls[0][1]["to"] == "2026-11-30T15:00:00Z"
    assert csv_calls[1][1]["from"] == csv_calls[0][1]["to"] and csv_calls[1][1]["to"] == "2026-12-14T15:00:00Z"
    assert all(c[2] == {"Authorization": "Bearer rd"} for c in session.calls)
    assert traps == TRAPS and deployments == DEPLOYMENTS


def test_fetch_reports_http_errors():
    with pytest.raises(ApiError) as e:
        fetch_backend_data("http://pi:5000", "2026-11-01", "2026-11-02", session=FakeSession("", status=401))
    assert e.value.status == 401


def test_air_quality_is_imported_when_the_backend_exports_it():
    row = event("telemetry", T0, "air", temperature_c="20")
    frame = to_frame([row])
    frame["eco2_ppm"], frame["tvoc_ppb"] = "450.0", "0.0"
    (out,) = sensor_rows(frame)
    assert (out["eco2_ppm"], out["tvoc_ppb"]) == (450.0, 0.0)


@pytest.mark.parametrize("rows", [
    [event("telemetry", T0, "t0", temperature_c="20")],  # 감지 없음
    [event("entry_detected", T0, "e1", visit_id="v1")],  # 센서 값 없음
    [],  # 이벤트 없음
], ids=["no_visits", "no_sensors", "no_events"])
def test_quiet_period_still_makes_a_row_per_day(rows):
    summary, _ = build_summary(to_frame(rows), TRAPS, DEPLOYMENTS, "2026-11-10", "2026-11-12")
    assert list(summary["date"]) == ["2026-11-10", "2026-11-11"]
    assert summary["rat_detections"].sum() == 0
    assert summary["unclassified_detections"].sum() == sum(r["event_type"] == "entry_detected" for r in rows)
