"""가상 포획 시나리오 데이터셋 생성기 (모드 1, docs/synthetic_data_design.md 참고).

주의: 이 모듈이 만드는 모든 감지/포획 값은 **가상**이다.
- 실제 센서/감지 데이터가 아니며, 포획은 실제 포획 실적이 아니라 시뮬레이션 값이다.
- 위치별 감지율(lam)과 포획확률(p)은 현장 추정값이 아니라 설계자가 정한 가정이다.

실행: python -m src.synthetic_data  ->  data/synthetic/scenario/*.csv
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
KST = timezone(timedelta(hours=9))
START = datetime(2026, 11, 9, tzinfo=KST)
DAYS = 28
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic" / "scenario"

# 위치별 (시간당 쥐 감지율 lam, 감지 1건당 포획확률 p)  ※ 설계자 가정값
LOCATION_PARAMS = {
    "LOC-A": (0.30, 0.35),
    "LOC-B": (0.30, 0.05),
    "LOC-C": (0.05, 0.30),
    "LOC-D": (0.25, 0.30),
    "LOC-F": (0.28, 0.35),
}
# 트랩별 장치 계수 (1.0 = 정상, 낮을수록 장치 문제)
DEVICE_FACTOR = {"TRAP-06": 0.15}

# (trap_id, location_id, 시작일 index, 끝일 index(미포함))
SEGMENTS = [
    ("TRAP-01", "LOC-A", 0, 28),
    ("TRAP-02", "LOC-B", 0, 14),
    ("TRAP-02", "LOC-A", 14, 28),  # 위치 이동: B에서 낮았던 이유가 장치가 아님을 확인
    ("TRAP-03", "LOC-C", 0, 28),
    ("TRAP-04", "LOC-D", 25, 28),  # 관찰 3일 -> 데이터 부족
    ("TRAP-05", "LOC-B", 0, 14),   # 같은 위치(B)에 다른 트랩도 낮음 -> 위치 문제
    ("TRAP-06", "LOC-F", 0, 14),
    ("TRAP-06", "LOC-A", 14, 28),  # 위치 이동 후에도 낮음 -> 장치 문제
]

NIGHT_SHARE = 0.75            # 야간(22~05시) 감지 비중
NON_RAT_RATIO = 0.15          # 쥐 감지 대비 비대상 동물 비율
UNCLASSIFIED_RATE = 0.05      # 분류 실패 비율
MISSING_RATE = 0.02           # 센서 값 결측 비율
NIGHT_HOURS = {22, 23, 0, 1, 2, 3, 4, 5}

SCENARIO_TRUTH = [
    ("LOC-A", "high_detection_high_capture", "keep"),
    ("LOC-B", "high_detection_low_capture_location_issue", "relocate"),
    ("LOC-C", "low_detection_low_capture", "relocate"),
    ("LOC-D", "short_observation", "insufficient_data"),
    ("LOC-E", "no_install_history_candidate", "new_candidate"),
    ("LOC-F", "high_detection_low_capture_device_issue", "check_device"),
]

SUMMARY_COLUMNS = [
    "trap_id", "location_id", "date", "operating_hours", "rat_detections",
    "non_rat_detections", "unclassified_detections", "avg_temperature_c",
    "avg_humidity_pct", "avg_tvoc_ppb", "avg_eco2_ppm", "sim_captures",
    "detection_source", "capture_source",
]


def _iso(dt):
    return dt.isoformat(timespec="seconds")


def _hour_weight(hour_of_day):
    """시간대별 감지 비중. 합계가 1이 되도록 야간 8시간/주간 16시간에 배분."""
    return NIGHT_SHARE / 8 if hour_of_day in NIGHT_HOURS else (1 - NIGHT_SHARE) / 16


def _operating_mask(trap_id, segs, rng):
    """시간 단위 작동 여부. 작동 중단 구간(6~24시간 연속 1~2회)을 제외한다."""
    mask = np.zeros(DAYS * 24, dtype=bool)
    first, last = min(s[2] for s in segs), max(s[3] for s in segs)
    mask[first * 24: last * 24] = True
    if trap_id != "TRAP-04":  # 3일뿐인 트랩은 중단 없이 둔다
        for _ in range(int(rng.integers(1, 3))):
            length = int(rng.integers(6, 25))
            begin = int(rng.integers(first * 24, last * 24 - length))
            mask[begin: begin + length] = False
    if trap_id == "TRAP-01":  # 하루 전체 중단 (operating_hours = 0 검증용)
        mask[10 * 24: 11 * 24] = False
    return mask


def _simulate_trap(trap_id, segs, rng):
    mask = _operating_mask(trap_id, segs, rng)
    factor = DEVICE_FACTOR.get(trap_id, 1.0)
    events, hours = [], []
    for _, loc, d0, d1 in segs:
        lam, p = LOCATION_PARAMS[loc]
        for h in range(d0 * 24, d1 * 24):
            if not mask[h]:
                continue
            hod = h % 24
            temp = 21 + 1.5 * np.sin(2 * np.pi * (hod - 9) / 24) + rng.normal(0, 0.5)
            hum = float(np.clip(50 + 5 * np.sin(2 * np.pi * (hod - 3) / 24) + rng.normal(0, 2), 20, 90))
            sensors = {
                "temperature_c": temp, "humidity_pct": hum,
                "tvoc_ppb": float(rng.integers(50, 301)), "eco2_ppm": float(rng.integers(400, 701)),
            }
            for k in sensors:  # 센서 값 결측은 0이 아니라 NaN
                if rng.random() < MISSING_RATE:
                    sensors[k] = np.nan
            day = START + timedelta(days=h // 24)
            hours.append({"trap_id": trap_id, "location_id": loc, "date": day.date().isoformat(), **sensors})

            env = 1 + 0.05 * np.clip((temp - 22) / 3, -1, 1) + 0.05 * np.clip((hum - 50) / 10, -1, 1)
            base = lam * 24 * _hour_weight(hod) * env
            truths = ["rat"] * int(rng.poisson(base)) + ["non_rat"] * int(rng.poisson(base * NON_RAT_RATIO))
            for truth in truths:
                t = START + timedelta(hours=h, seconds=int(rng.integers(0, 3600)))
                if rng.random() < UNCLASSIFIED_RATE:
                    cls, conf = None, None
                else:
                    cls, conf = truth, round(float(rng.uniform(0.6, 0.99)), 2)
                captured = cls == "rat" and rng.random() < p * factor  # 이벤트당 최대 1회
                events.append({"trap_id": trap_id, "location_id": loc, "detected_at": t,
                               "classification": cls, "confidence": conf, "captured": captured,
                               "capture_delay": int(rng.integers(1, 31))})
    return events, hours


def generate_scenario(out_dir=OUT_DIR, write=True):
    all_events, all_hours = [], []
    traps = sorted({s[0] for s in SEGMENTS})
    for trap_id in traps:
        rng = np.random.default_rng(SEED + int(trap_id[-2:]))
        ev, hr = _simulate_trap(trap_id, [s for s in SEGMENTS if s[0] == trap_id], rng)
        all_events += ev
        all_hours += hr

    ev = pd.DataFrame(all_events).sort_values(["detected_at", "trap_id"], kind="stable").reset_index(drop=True)
    ev["event_id"] = ev.index + 1
    ev["date"] = ev["detected_at"].map(lambda t: t.date().isoformat())

    # 이벤트 로그 (API 스키마 + data_source)
    events = pd.DataFrame({
        "event_id": ev["event_id"], "trap_id": ev["trap_id"],
        "detected_at": ev["detected_at"].map(_iso), "ir_detected": True,
        "classification": ev["classification"], "confidence": ev["confidence"],
        "data_source": "synthetic",
    })

    # 가상 포획 로그 (이벤트당 최대 1건, 같은 날 23:59:59를 넘기지 않음)
    cap = ev[ev["captured"]].copy().reset_index(drop=True)

    def captured_at(r):
        t = r["detected_at"] + timedelta(seconds=int(r["capture_delay"]))
        end_of_day = r["detected_at"].replace(hour=23, minute=59, second=59)
        return _iso(min(t, end_of_day))

    captures = pd.DataFrame({
        "sim_capture_id": cap.index + 1, "event_id": cap["event_id"],
        "trap_id": cap["trap_id"], "location_id": cap["location_id"],
        "captured_at": cap.apply(captured_at, axis=1) if len(cap) else [],
        "data_source": "synthetic",
    })

    # 일 단위 통합 데이터셋
    grid = pd.DataFrame([
        {"trap_id": t, "location_id": loc, "date": (START + timedelta(days=d)).date().isoformat()}
        for t, loc, d0, d1 in SEGMENTS for d in range(d0, d1)
    ])
    keys = ["trap_id", "location_id", "date"]
    hrs = pd.DataFrame(all_hours)
    agg = hrs.groupby(keys).agg(
        operating_hours=("temperature_c", "size"),
        avg_temperature_c=("temperature_c", "mean"), avg_humidity_pct=("humidity_pct", "mean"),
        avg_tvoc_ppb=("tvoc_ppb", "mean"), avg_eco2_ppm=("eco2_ppm", "mean"),
    ).reset_index()
    counts = (ev.assign(cls=ev["classification"].fillna("unclassified"))
              .pivot_table(index=keys, columns="cls", values="event_id", aggfunc="count", fill_value=0)
              .reindex(columns=["rat", "non_rat", "unclassified"], fill_value=0).reset_index())
    caps = ev[ev["captured"]].groupby(keys).size().rename("sim_captures").reset_index()
    summary = grid.merge(agg, on=keys, how="left").merge(counts, on=keys, how="left").merge(caps, on=keys, how="left")
    summary = summary.rename(columns={"rat": "rat_detections", "non_rat": "non_rat_detections",
                                      "unclassified": "unclassified_detections"})
    for c in ["operating_hours", "rat_detections", "non_rat_detections", "unclassified_detections", "sim_captures"]:
        summary[c] = summary[c].fillna(0).astype(int)
    for c in ["avg_temperature_c", "avg_humidity_pct", "avg_tvoc_ppb", "avg_eco2_ppm"]:
        summary[c] = summary[c].round(2)
    summary["detection_source"] = "synthetic"
    summary["capture_source"] = "synthetic"
    summary = summary[SUMMARY_COLUMNS].sort_values(["date", "trap_id"]).reset_index(drop=True)

    truth = pd.DataFrame(SCENARIO_TRUTH, columns=["location_id", "scenario_type", "expected_judgement"])
    out = {"detection_events": events, "simulated_captures": captures,
           "trap_day_summary": summary, "scenario_truth": truth}
    if write:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        for name, df in out.items():
            df.to_csv(Path(out_dir) / f"{name}.csv", index=False, encoding="utf-8")
    return out


if __name__ == "__main__":
    result = generate_scenario()
    for name, df in result.items():
        print(f"{name:<22} {len(df)}행")
    s = result["trap_day_summary"]
    g = s.groupby("location_id").agg(
        트랩일=("date", "size"), 작동시간=("operating_hours", "sum"),
        쥐감지=("rat_detections", "sum"), 가상포획=("sim_captures", "sum"))
    g["감지율/h"] = (g["쥐감지"] / g["작동시간"]).round(3)
    g["전환율"] = (g["가상포획"] / g["쥐감지"]).round(3)
    print(g.to_string())
