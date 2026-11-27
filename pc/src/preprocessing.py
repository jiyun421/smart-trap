"""전처리: API 원시 데이터 정제 + 일 단위 통합 데이터셋(trap_day_summary) 생성.

핵심 원칙 (docs/synthetic_data_design.md 2-3):
- 측정하지 못한 값은 0이 아니라 NaN(결측)으로 둔다.
- 중복 ID는 제거하고, 제거/수정 건수는 품질 리포트(dict)로 돌려준다.
- 위치는 trap-location-history로 시각마다 결정한다. 이력이 없는 구간의 데이터는 집계에서 제외하고 건수를 보고한다.
- 이 모듈은 포획(sim_captures) 컬럼을 만들지 않는다. 포획은 가상 데이터이며 별도 단계에서 결합한다.
"""
import numpy as np
import pandas as pd

TZ = "Asia/Seoul"
VALID_CLASSES = {"rat", "non_rat"}

# 센서 유효 범위 (벗어나면 NaN 처리)
SENSOR_RANGES = {
    "temperature_c": (-20, 60),
    "humidity_pct": (0, 100),
    "tvoc_ppb": (0, 60000),
    "eco2_ppm": (400, 60000),
}

# 실제 데이터 일 집계 컬럼 (synthetic_data.SUMMARY_COLUMNS 에서 포획 관련 2개를 뺀 것)
BASE_SUMMARY_COLUMNS = [
    "trap_id", "location_id", "date", "operating_hours", "rat_detections",
    "non_rat_detections", "unclassified_detections", "avg_temperature_c",
    "avg_humidity_pct", "avg_tvoc_ppb", "avg_eco2_ppm", "detection_source",
]


def _to_kst(series):
    """ISO 8601 문자열 -> KST 시각. 해석 불가한 값은 NaT."""
    return pd.to_datetime(series, utc=True, errors="coerce").dt.tz_convert(TZ)


def _ts(value):
    t = pd.Timestamp(value)
    return t.tz_localize(TZ) if t.tzinfo is None else t.tz_convert(TZ)


def load_trap_day_summary(path):
    """저장된 trap_day_summary CSV 읽기 (date는 'YYYY-MM-DD' 문자열 유지)."""
    return pd.read_csv(path, dtype={"date": str})


# ------------------------------------------------------------------ 정제
def clean_events(rows):
    """감지 이벤트 정제. (DataFrame, 품질 리포트) 반환."""
    df = pd.DataFrame(rows)
    report = {"input_rows": len(df), "duplicates_removed": 0, "invalid_time_removed": 0,
              "invalid_class_set_null": 0, "invalid_confidence_set_null": 0}
    if df.empty:  # 감지가 없어도 이후 단계가 쓰는 컬럼은 있어야 한다
        df = pd.DataFrame(columns=["event_id", "trap_id", "detected_at", "classification", "confidence"])
        df["detected_at"] = _to_kst(df["detected_at"])
        return df, report
    before = len(df)
    df = df.drop_duplicates("event_id", keep="first")
    report["duplicates_removed"] = before - len(df)

    df["detected_at"] = _to_kst(df["detected_at"])
    bad = df["detected_at"].isna() | df["trap_id"].isna()
    report["invalid_time_removed"] = int(bad.sum())
    df = df[~bad].copy()

    bad_cls = df["classification"].notna() & ~df["classification"].isin(VALID_CLASSES)
    report["invalid_class_set_null"] = int(bad_cls.sum())
    df.loc[bad_cls, ["classification", "confidence"]] = None  # 알 수 없는 분류는 결측 처리

    conf = pd.to_numeric(df["confidence"], errors="coerce")
    bad_conf = conf.notna() & ((conf < 0) | (conf > 1))
    report["invalid_confidence_set_null"] = int(bad_conf.sum())
    df["confidence"] = conf.mask(bad_conf)
    return df.sort_values(["detected_at", "trap_id"]).reset_index(drop=True), report


def clean_sensor_readings(rows):
    """센서 측정값 정제. 유효 범위를 벗어난 값은 NaN. (DataFrame, 품질 리포트) 반환."""
    df = pd.DataFrame(rows)
    report = {"input_rows": len(df), "duplicates_removed": 0, "invalid_time_removed": 0,
              "out_of_range_set_null": {k: 0 for k in SENSOR_RANGES}}
    if df.empty:
        df = pd.DataFrame(columns=["reading_id", "trap_id", "measured_at", *SENSOR_RANGES, "load_cell_g"])
        df = df.astype({c: float for c in (*SENSOR_RANGES, "load_cell_g")})
        df["measured_at"] = _to_kst(df["measured_at"])
        return df, report
    before = len(df)
    df = df.drop_duplicates("reading_id", keep="first")
    report["duplicates_removed"] = before - len(df)

    df["measured_at"] = _to_kst(df["measured_at"])
    bad = df["measured_at"].isna() | df["trap_id"].isna()
    report["invalid_time_removed"] = int(bad.sum())
    df = df[~bad].copy()

    for col, (lo, hi) in SENSOR_RANGES.items():
        v = pd.to_numeric(df[col], errors="coerce")
        out = v.notna() & ((v < lo) | (v > hi))
        report["out_of_range_set_null"][col] = int(out.sum())
        df[col] = v.mask(out)
    df["load_cell_g"] = pd.to_numeric(df["load_cell_g"], errors="coerce")
    return df.sort_values(["measured_at", "trap_id"]).reset_index(drop=True), report


# ------------------------------------------------------- 위치 / 작동 시간
def prepare_location_history(rows, period_start, period_end):
    """위치 이력을 분석 기간으로 자른 DataFrame (start_at, end_at: KST). end_at=None은 기간 끝까지."""
    ps, pe = _ts(period_start), _ts(period_end)
    df = pd.DataFrame(rows)
    df["start_at"] = _to_kst(df["start_at"]).clip(lower=ps)
    df["end_at"] = _to_kst(df["end_at"]).fillna(pe).clip(upper=pe)
    return df[df["start_at"] < df["end_at"]].reset_index(drop=True)


def _split_by_day(start, end):
    """[start, end) 구간을 KST 날짜별 (날짜 문자열, 시간) 으로 나눈다."""
    cur = start
    while cur < end:
        nxt = min(cur.normalize() + pd.Timedelta(days=1), end)
        yield cur.strftime("%Y-%m-%d"), (nxt - cur).total_seconds() / 3600
        cur = nxt


def operating_hours_by_day(status_logs, history, period_start, period_end):
    """상태 로그(변경 시에만 기록)로 트랩·위치·날짜별 실제 작동 시간(h)을 계산한다.

    - 로그의 다음 변경 시각(없으면 기간 끝)까지 해당 상태가 유지된다고 본다.
    - 첫 로그 이전 구간은 상태를 알 수 없으므로 작동 시간에 포함하지 않는다.
    """
    ps, pe = _ts(period_start), _ts(period_end)
    logs = pd.DataFrame(status_logs, columns=["trap_id", "changed_at", "status"])
    logs["changed_at"] = _to_kst(logs["changed_at"])
    acc = {}
    for trap_id, g in logs.dropna(subset=["changed_at"]).sort_values("changed_at").groupby("trap_id"):
        starts = g["changed_at"].tolist()
        ends = starts[1:] + [pe]
        hist = history[history["trap_id"] == trap_id]
        for s, e, status in zip(starts, ends, g["status"]):
            s, e = max(s, ps), min(e, pe)
            if status != "operating" or s >= e:
                continue
            for h in hist.itertuples():
                a, b = max(s, h.start_at), min(e, h.end_at)
                for day, hours in (_split_by_day(a, b) if a < b else []):
                    key = (trap_id, h.location_id, day)
                    acc[key] = acc.get(key, 0.0) + hours
    out = pd.DataFrame([(*k, v) for k, v in acc.items()],
                       columns=["trap_id", "location_id", "date", "operating_hours"])
    return out.astype({"operating_hours": float})


def _assign_location(df, time_col, history):
    loc = pd.Series(np.nan, index=df.index, dtype=object)
    for h in history.itertuples():
        m = (df["trap_id"] == h.trap_id) & (df[time_col] >= h.start_at) & (df[time_col] < h.end_at)
        loc[m & loc.isna()] = h.location_id
    return loc


# ------------------------------------------------------------- 통합 데이터셋
def build_trap_day_summary(events, sensors, status_logs, location_history, period_start, period_end):
    """실제 데이터로 trap_day_summary(포획 제외)를 만든다.

    events/sensors: clean_* 결과 DataFrame, status_logs/location_history: API 응답 리스트.
    반환: (summary, 리포트). 리포트에 위치 이력이 없어 제외된 건수가 들어 있다.
    """
    ps, pe = _ts(period_start), _ts(period_end)
    history = prepare_location_history(location_history, ps, pe)
    keys = ["trap_id", "location_id", "date"]
    report = {"events_without_location": 0, "sensors_without_location": 0}

    # 행 틀: 트랩이 해당 위치에 있었던 모든 날짜
    grid = pd.DataFrame([
        {"trap_id": h.trap_id, "location_id": h.location_id, "date": d.strftime("%Y-%m-%d")}
        for h in history.itertuples()
        for d in pd.date_range(h.start_at.normalize(), (h.end_at - pd.Timedelta(nanoseconds=1)).normalize(),
                               freq="D", tz=TZ)
    ]).drop_duplicates()

    ev = events[(events["detected_at"] >= ps) & (events["detected_at"] < pe)].copy()
    ev["location_id"] = _assign_location(ev, "detected_at", history)
    report["events_without_location"] = int(ev["location_id"].isna().sum())
    ev = ev.dropna(subset=["location_id"])
    ev["date"] = ev["detected_at"].dt.strftime("%Y-%m-%d")
    ev["cls"] = ev["classification"].fillna("unclassified")
    counts = (ev.pivot_table(index=keys, columns="cls", values="event_id", aggfunc="count", fill_value=0)
              .reindex(columns=["rat", "non_rat", "unclassified"], fill_value=0).reset_index())

    sn = sensors[(sensors["measured_at"] >= ps) & (sensors["measured_at"] < pe)].copy()
    sn["location_id"] = _assign_location(sn, "measured_at", history)
    report["sensors_without_location"] = int(sn["location_id"].isna().sum())
    sn = sn.dropna(subset=["location_id"])
    sn["date"] = sn["measured_at"].dt.strftime("%Y-%m-%d")
    env = sn.groupby(keys).agg(
        avg_temperature_c=("temperature_c", "mean"), avg_humidity_pct=("humidity_pct", "mean"),
        avg_tvoc_ppb=("tvoc_ppb", "mean"), avg_eco2_ppm=("eco2_ppm", "mean")).reset_index()

    hours = operating_hours_by_day(status_logs, history, ps, pe)
    summary = grid.merge(hours, on=keys, how="left").merge(counts, on=keys, how="left").merge(env, on=keys, how="left")
    summary = summary.rename(columns={"rat": "rat_detections", "non_rat": "non_rat_detections",
                                      "unclassified": "unclassified_detections"})
    summary["operating_hours"] = summary["operating_hours"].fillna(0.0).round(2)  # 작동 기록 없음 = 0시간
    for c in ["rat_detections", "non_rat_detections", "unclassified_detections"]:
        summary[c] = summary[c].fillna(0).astype(int)
    for c in ["avg_temperature_c", "avg_humidity_pct", "avg_tvoc_ppb", "avg_eco2_ppm"]:
        summary[c] = summary[c].round(2)  # 측정값 없는 날은 NaN 유지
    summary["detection_source"] = "actual"
    summary = summary[BASE_SUMMARY_COLUMNS].sort_values(["date", "trap_id"]).reset_index(drop=True)
    return summary, report
