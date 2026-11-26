"""백엔드 데이터(CSV 내보내기 + 설치 이력 + 트랩 목록) -> trap_day_summary(실제 데이터, 포획 제외).

백엔드 이벤트(backend/docs/api.md)를 기존 전처리(src/preprocessing.py)가 받는 형식으로 바꾼 뒤 그대로 넘긴다.
- 방문(visit): entry_detected + visit_resolved를 visit_id로 묶는다. 종이 없거나 unknown이면 미분류(null), rat 외는 non_rat.
- 센서: 온도·습도·미끼 무게(bait_g -> load_cell_g)가 하나라도 있는 이벤트. eCO2/TVOC는 백엔드에 없어 NaN이다(0 아님).
- 작동 시간: 백엔드에 상태 로그가 없어, 이벤트(주기 보고 포함)가 이어지는 구간을 작동 중으로 본다.
  이벤트 사이 간격이 보고 주기의 3배(백엔드의 offline 기준)를 넘으면 그 시점부터 다음 이벤트까지는 작동하지 않은 것으로 계산한다.
- 위치 이력은 /api/deployments의 설치 이력이다.
- 이 모듈은 포획 컬럼을 만들지 않는다. 가상 포획 결합은 별도 단계다(preprocessing.py와 같은 원칙).
"""
import argparse
import io
from datetime import timedelta
from pathlib import Path

import pandas as pd
import requests

from src.api_client import ApiError
from src.preprocessing import _ts, build_trap_day_summary, clean_events, clean_sensor_readings

CHUNK_DAYS = 30  # 백엔드 CSV는 한 요청 최대 31일
OFFLINE_FACTOR = 3  # 백엔드 connection_state 기준(보고 주기의 3배)
DEFAULT_INTERVAL_S = 60


def _utc(ts):
    return ts.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ 가져오기
def _get(session, base_url, path, params, token, timeout):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = session.get(base_url.rstrip("/") + path, params=params, headers=headers, timeout=timeout)
    except requests.RequestException as e:
        raise ApiError(0, "CONNECTION_ERROR", str(e)) from e
    if r.status_code >= 400:
        raise ApiError(r.status_code, "BACKEND_ERROR", f"GET {path}: HTTP {r.status_code}")
    return r


def fetch_backend_data(base_url, period_start, period_end, read_token=None, timeout=30, session=None):
    """(events_csv 텍스트, traps, deployments)를 읽는다. 31일 제한 때문에 CSV는 기간을 나눠 받는다."""
    session = session or requests
    start, end = _ts(period_start).tz_convert("UTC"), _ts(period_end).tz_convert("UTC")
    parts, cur = [], start
    while cur < end:
        nxt = min(cur + timedelta(days=CHUNK_DAYS), end)
        r = _get(session, base_url, "/api/export/events.csv", {"from": _utc(cur), "to": _utc(nxt)},
                 read_token, timeout)
        parts.append(r.content.decode("utf-8") if isinstance(r.content, bytes) else r.text)
        cur = nxt
    frames = [pd.read_csv(io.StringIO(t), dtype=str) for t in parts]
    events = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    traps = _get(session, base_url, "/api/traps", None, read_token, timeout).json()["items"]
    deployments = _get(session, base_url, "/api/deployments", None, read_token, timeout).json()["items"]
    return events, traps, deployments


# ------------------------------------------------------------------ 변환
def _num(series):
    return pd.to_numeric(series, errors="coerce")


def visit_rows(events):
    """백엔드 이벤트 -> 감지 이벤트 행(event_id, trap_id, detected_at, classification, confidence)."""
    v = events[events["visit_id"].notna() & events["event_type"].isin(["entry_detected", "visit_resolved"])]
    rows = []
    for (dep, vid), g in v.groupby(["deployment_id", "visit_id"], sort=False):
        entry = g[g["event_type"] == "entry_detected"]
        res = g[g["event_type"] == "visit_resolved"]
        first = entry.iloc[0] if len(entry) else res.iloc[0]
        species = res.iloc[0]["species_code"] if len(res) else None
        conf = _num(res["confidence"]).iloc[0] if len(res) else float("nan")
        if pd.isna(conf) and len(entry):
            conf = _num(entry["confidence"]).iloc[0]
        rows.append({
            "event_id": f"{dep}:{vid}", "trap_id": first["trap_id"], "detected_at": first["observed_at"],
            "classification": None if pd.isna(species) or species == "unknown"
            else ("rat" if species == "rat" else "non_rat"),
            "confidence": None if pd.isna(conf) else float(conf),
        })
    return rows


def sensor_rows(events):
    """온도·습도·미끼 무게 중 하나라도 있는 이벤트 -> 센서 행. eCO2/TVOC는 NaN."""
    env = events[["temperature_c", "humidity_pct", "bait_g"]].apply(_num)
    has = env.notna().any(axis=1)
    return [{
        "reading_id": f"{r.deployment_id}:{r.event_id}", "trap_id": r.trap_id, "measured_at": r.observed_at,
        "temperature_c": t, "humidity_pct": h, "tvoc_ppb": None, "eco2_ppm": None, "load_cell_g": b,
    } for r, t, h, b in zip(events[has].itertuples(), env[has]["temperature_c"],
                            env[has]["humidity_pct"], env[has]["bait_g"])]


def status_logs(events, traps):
    """이벤트가 이어지는 구간을 작동 중으로 본 상태 로그(변경 시에만 기록)."""
    interval = {t["trap_id"]: t.get("report_interval_seconds") or DEFAULT_INTERVAL_S for t in traps}
    logs = []
    times = pd.to_datetime(events["observed_at"], utc=True, errors="coerce")
    for trap_id, ts in times.groupby(events["trap_id"]):
        ts = ts.dropna().sort_values().drop_duplicates()
        if ts.empty:
            continue
        gap = timedelta(seconds=OFFLINE_FACTOR * interval.get(trap_id, DEFAULT_INTERVAL_S))
        logs.append((trap_id, ts.iloc[0], "operating"))
        for prev, nxt in zip(ts.iloc[:-1], ts.iloc[1:]):
            if nxt - prev > gap:
                logs += [(trap_id, prev + gap, "offline"), (trap_id, nxt, "operating")]
        logs.append((trap_id, ts.iloc[-1] + gap, "offline"))
    return [{"trap_id": t, "changed_at": _utc(c), "status": s} for t, c, s in logs]


def location_history(deployments):
    return [{"trap_id": d["trap_id"], "location_id": d["location_id"],
             "start_at": d["started_at"], "end_at": d.get("ended_at")} for d in deployments]


def build_summary(events, traps, deployments, period_start, period_end):
    """백엔드 데이터로 trap_day_summary(포획 제외)를 만든다. 반환: (summary, 품질 리포트)."""
    ev, ev_report = clean_events(visit_rows(events))
    sn, sn_report = clean_sensor_readings(sensor_rows(events))
    summary, report = build_trap_day_summary(ev, sn, status_logs(events, traps), location_history(deployments),
                                             period_start, period_end)
    return summary, {"events": ev_report, "sensors": sn_report, **report}


def main():
    p = argparse.ArgumentParser(description="백엔드 데이터로 trap_day_summary(실제, 포획 제외) CSV를 만든다.")
    p.add_argument("--base-url", required=True, help="예: http://192.168.0.10:5000")
    p.add_argument("--from", dest="start", required=True, help="기간 시작(KST), 예: 2026-11-09")
    p.add_argument("--to", dest="end", required=True, help="기간 끝(KST, 미포함), 예: 2026-11-23")
    p.add_argument("--read-token", help="백엔드가 TRAP_READ_AUTH=off이면 생략")
    p.add_argument("--out", required=True, help="저장할 CSV 경로")
    a = p.parse_args()
    events, traps, deployments = fetch_backend_data(a.base_url, a.start, a.end, a.read_token)
    summary, report = build_summary(events, traps, deployments, a.start, a.end)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(a.out, index=False)
    print(f"저장: {a.out} ({len(summary)}행)")
    print("품질 리포트:", report)


if __name__ == "__main__":
    main()
