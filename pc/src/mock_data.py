"""API 명세 v1.0 형식의 Mock JSON 생성기.

주의: 이 파일이 만드는 데이터는 **API 연동 개발용 Mock** 이다.
- 실제 센서/감지 데이터가 아니다.
- 가상 포획 데이터셋(synthetic_data.py)과도 다르다. 포획 정보는 포함하지 않는다.

실행: python -m src.mock_data   ->  data/mock/*.json 생성
"""
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEED = 42
KST = timezone(timedelta(hours=9))
START = datetime(2026, 11, 9, 0, 0, tzinfo=KST)
END = datetime(2026, 11, 23, 0, 0, tzinfo=KST)
SENSOR_INTERVAL_MIN = 30
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "mock"

LOCATIONS = [
    {"location_id": "LOC-A", "name": "주방 입구", "is_candidate": False, "x": 1.0, "y": 1.0},
    {"location_id": "LOC-B", "name": "창고 중앙", "is_candidate": False, "x": 4.0, "y": 1.0},
    {"location_id": "LOC-C", "name": "복도 끝", "is_candidate": False, "x": 7.0, "y": 1.0},
    {"location_id": "LOC-D", "name": "후문 옆", "is_candidate": False, "x": 1.0, "y": 4.0},
    {"location_id": "LOC-E", "name": "쓰레기장 뒤", "is_candidate": True, "x": 4.0, "y": 4.0},
]

# trap_id -> (location_id, 설치 시각, 하루 평균 쥐 감지 시도 수)
TRAPS = {
    "TRAP-01": ("LOC-A", START, 6.0),
    "TRAP-02": ("LOC-B", START, 5.0),
    "TRAP-03": ("LOC-C", START, 0.8),
    "TRAP-04": ("LOC-D", END - timedelta(days=2), 3.0),  # 관찰 기간이 짧은 트랩
}

# 트랩별 작동 중단 구간 (시작, 끝)
STOPPED = {
    "TRAP-02": [(START + timedelta(days=5, hours=10), START + timedelta(days=5, hours=22))],
}


def iso(dt):
    return dt.isoformat(timespec="seconds")


def is_stopped(trap_id, t):
    return any(s <= t < e for s, e in STOPPED.get(trap_id, []))


def wrap(rows, from_=START, to=END):
    return {
        "data": rows,
        "meta": {"page": 1, "page_size": 1000, "total": len(rows), "from": iso(from_), "to": iso(to)},
    }


def make_traps():
    now = END
    return {"data": [
        {
            "trap_id": tid,
            "location_id": loc,
            "installed_at": iso(inst),
            "status": "operating",
            "door_state": "closed",
            "last_seen_at": iso(now - timedelta(minutes=1)),
        }
        for tid, (loc, inst, _) in TRAPS.items()
    ]}


def make_location_history():
    return {"data": [
        {"trap_id": tid, "location_id": loc, "start_at": iso(inst), "end_at": None}
        for tid, (loc, inst, _) in TRAPS.items()
    ]}


def make_status_logs():
    rows, log_id = [], 1
    for tid, (_, inst, _) in TRAPS.items():
        rows.append({"log_id": log_id, "trap_id": tid, "changed_at": iso(inst),
                     "status": "operating", "door_state": "closed"})
        log_id += 1
        for s, e in STOPPED.get(tid, []):
            rows.append({"log_id": log_id, "trap_id": tid, "changed_at": iso(s),
                         "status": "stopped", "door_state": "closed"})
            rows.append({"log_id": log_id + 1, "trap_id": tid, "changed_at": iso(e),
                         "status": "operating", "door_state": "closed"})
            log_id += 2
    rows.sort(key=lambda r: r["changed_at"])
    return wrap(rows)


def make_sensor_readings(rng):
    rows, rid = [], 1
    for tid, (_, inst, _) in TRAPS.items():
        t = inst
        while t < END:
            if not is_stopped(tid, t):
                hour = t.hour + t.minute / 60
                temp = 21 + 2 * rng.random() + (1.5 if 12 <= hour <= 18 else 0)
                row = {
                    "reading_id": rid,
                    "trap_id": tid,
                    "measured_at": iso(t),
                    "temperature_c": round(temp, 1),
                    "humidity_pct": round(45 + 8 * rng.random(), 1),
                    "tvoc_ppb": rng.randint(50, 300),
                    "eco2_ppm": rng.randint(400, 700),
                    "load_cell_g": None,  # 포획 전에는 측정값 없음 -> 결측
                }
                # 일부 센서 값 결측 (0으로 채우지 않고 null)
                if rng.random() < 0.02:
                    row["tvoc_ppb"] = None
                    row["eco2_ppm"] = None
                rows.append(row)
                rid += 1
            t += timedelta(minutes=SENSOR_INTERVAL_MIN)
    rows.sort(key=lambda r: (r["measured_at"], r["trap_id"]))
    return wrap(rows)


def make_detection_events(rng):
    rows = []
    for tid, (_, inst, per_day) in TRAPS.items():
        days = (END - inst).total_seconds() / 86400
        n = int(per_day * days)
        for _ in range(n):
            # 야간(22~05시) 집중
            hour = rng.choice([22, 23, 0, 1, 2, 3, 4, 5]) if rng.random() < 0.75 else rng.randint(6, 21)
            t = inst + timedelta(days=rng.random() * days)
            t = t.replace(hour=hour, minute=rng.randint(0, 59), second=rng.randint(0, 59))
            if not (inst <= t < END) or is_stopped(tid, t):
                continue
            r = rng.random()
            if r < 0.80:
                cls, conf = "rat", round(rng.uniform(0.6, 0.99), 2)
            elif r < 0.95:
                cls, conf = "non_rat", round(rng.uniform(0.6, 0.99), 2)
            else:
                cls, conf = None, None  # 분류 실패 -> 결측
            rows.append({"trap_id": tid, "detected_at": iso(t), "ir_detected": True,
                         "classification": cls, "confidence": conf})
    rows.sort(key=lambda r: r["detected_at"])
    for i, row in enumerate(rows, start=1):
        row["event_id"] = i
    rows = [{"event_id": r["event_id"], **{k: v for k, v in r.items() if k != "event_id"}} for r in rows]
    return wrap(rows)


def generate(out_dir=OUT_DIR):
    rng = random.Random(SEED)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "health.json": {"status": "ok", "server_time": iso(END)},
        "traps.json": make_traps(),
        "locations.json": {"data": LOCATIONS},
        "trap_location_history.json": make_location_history(),
        "sensor_readings.json": make_sensor_readings(rng),
        "detection_events.json": make_detection_events(rng),
        "trap_status_logs.json": make_status_logs(),
    }
    for name, obj in files.items():
        (out_dir / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    return files


if __name__ == "__main__":
    for name, obj in generate().items():
        n = len(obj["data"]) if isinstance(obj, dict) and "data" in obj else 1
        print(f"{name:<30} {n}건")
