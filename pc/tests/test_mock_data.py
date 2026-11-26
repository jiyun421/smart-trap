"""Mock JSON이 API 명세 v1.0 규칙을 지키는지 검사한다."""
import re

from src.mock_data import generate

ISO_KST = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+09:00$")


def test_deterministic(tmp_path):
    a = generate(tmp_path / "a")
    b = generate(tmp_path / "b")
    assert a == b  # 시드 고정 -> 재현 가능


def test_required_fields_and_formats(tmp_path):
    f = generate(tmp_path)
    for t in f["traps.json"]["data"]:
        assert re.match(r"^TRAP-\d{2}$", t["trap_id"])
        assert re.match(r"^LOC-[A-Z]$", t["location_id"])
        assert t["status"] in {"operating", "stopped", "error", "unknown"}
        assert ISO_KST.match(t["installed_at"])
    for r in f["sensor_readings.json"]["data"]:
        assert ISO_KST.match(r["measured_at"])
        assert set(r) == {"reading_id", "trap_id", "measured_at", "temperature_c",
                          "humidity_pct", "tvoc_ppb", "eco2_ppm", "load_cell_g"}
    for e in f["detection_events.json"]["data"]:
        assert ISO_KST.match(e["detected_at"])
        assert e["classification"] in {"rat", "non_rat", None}
        assert (e["confidence"] is None) == (e["classification"] is None)


def test_ids_unique_and_sorted(tmp_path):
    f = generate(tmp_path)
    for name, key, ts in [("sensor_readings.json", "reading_id", "measured_at"),
                          ("detection_events.json", "event_id", "detected_at")]:
        rows = f[name]["data"]
        assert len({r[key] for r in rows}) == len(rows)
        assert [r[ts] for r in rows] == sorted(r[ts] for r in rows)  # 시각 오름차순


def test_missing_values_are_null_not_zero(tmp_path):
    rows = generate(tmp_path)["sensor_readings.json"]["data"]
    assert any(r["tvoc_ppb"] is None for r in rows)
    assert not any(r["tvoc_ppb"] == 0 for r in rows)


def test_no_events_while_stopped(tmp_path):
    f = generate(tmp_path)
    stopped = [l for l in f["trap_status_logs.json"]["data"] if l["status"] == "stopped"]
    assert stopped
    s = stopped[0]
    end = next(l for l in f["trap_status_logs.json"]["data"]
               if l["trap_id"] == s["trap_id"] and l["changed_at"] > s["changed_at"])
    for e in f["detection_events.json"]["data"]:
        if e["trap_id"] == s["trap_id"]:
            assert not (s["changed_at"] <= e["detected_at"] < end["changed_at"])
