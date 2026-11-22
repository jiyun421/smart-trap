"""추천 결과를 API 명세(POST /recommendations)의 JSON으로 만들고 전송한다.

- 전송 전에 명세 기준으로 자체 검증한다(validate_payload). 어긋나면 전송하지 않는다.
- data_basis는 입력 데이터의 출처 컬럼에서 만든다. 포획이 가상이면 항상 시뮬레이션 기반으로 표시한다.
- 이 CLI는 Mock 전송만 한다. 실제 Pi 서버 연동은 명세 확인 후 7단계에서 한다.
실행: python -m src.export_recommendations
"""
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from src.api_client import ApiClient, ApiError
from src.preprocessing import load_trap_day_summary
from src.recommendation import ALGORITHM_VERSION, recommend

KST = timezone(timedelta(hours=9))
STATUSES = {"recommended", "keep", "insufficient_data", "device_check"}
CAPTURE_NOTE = "포획 관련 수치는 가상 데이터 기반 추정이며 실제 포획 실적이 아님"
ALL_SYNTHETIC_NOTE = "감지·포획 모두 가상(시나리오) 데이터 기반이며 실제 현장 실적이 아님"
ROOT = Path(__file__).resolve().parent.parent
SCENARIO_CSV = ROOT / "data" / "synthetic" / "scenario" / "trap_day_summary.csv"
OUT_DIR = ROOT / "data" / "processed"


def _iso(dt):
    return dt.isoformat(timespec="seconds")


def _source(summary, col):
    """출처 컬럼 값. 한 종류면 그 값, 섞여 있으면 mixed, 컬럼이 없으면 unknown."""
    vals = set(summary[col].dropna().unique()) if col in summary else set()
    return vals.pop() if len(vals) == 1 else ("mixed" if vals else "unknown")


def build_data_basis(summary):
    detection, capture = _source(summary, "detection_source"), _source(summary, "capture_source")
    return {"detection_data": detection, "capture_data": capture,
            "is_simulation_based": capture != "actual",
            "note": ALL_SYNTHETIC_NOTE if detection == "synthetic" else CAPTURE_NOTE}


def build_payload(items, summary, now=None, run_id=None):
    """추천 항목 리스트를 요청 본문으로 만든다. analysis_period.to는 마지막 날의 다음 날 0시(배타적)."""
    now = now or datetime.now(KST)
    dates = pd.to_datetime(summary["date"])
    first = datetime.combine(dates.min().date(), datetime.min.time(), tzinfo=KST)
    last = datetime.combine(dates.max().date(), datetime.min.time(), tzinfo=KST) + timedelta(days=1)
    payload = {"run_id": run_id or f"RUN-{now:%Y%m%d-%H%M%S}", "generated_at": _iso(now),
               "analysis_period": {"from": _iso(first), "to": _iso(last)},
               "algorithm_version": ALGORITHM_VERSION, "data_basis": build_data_basis(summary),
               "recommendations": items}
    errors = validate_payload(payload)
    if errors:
        raise ValueError("명세 검증 실패: " + "; ".join(errors))
    return payload


def _has_nan(obj):
    if isinstance(obj, float):
        return math.isnan(obj) or math.isinf(obj)
    if isinstance(obj, dict):
        return any(_has_nan(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_nan(v) for v in obj)
    return False


def validate_payload(p):
    """API 명세 3-1 기준 검증. 문제 목록을 반환한다(빈 리스트면 통과)."""
    errs = []
    for k in ("run_id", "generated_at", "analysis_period", "algorithm_version", "data_basis", "recommendations"):
        if k not in p:
            errs.append(f"필수 필드 없음: {k}")
    if errs:
        return errs
    if _has_nan(p):
        errs.append("NaN/Infinity 값이 있음 (결측은 null이어야 함)")
    basis = p["data_basis"]
    if not {"detection_data", "capture_data", "is_simulation_based", "note"} <= set(basis):
        errs.append("data_basis 필드 부족")
    elif basis["capture_data"] != "actual" and not (basis["is_simulation_based"] and basis["note"]):
        errs.append("가상 포획 데이터인데 시뮬레이션 기반 표시/문구가 없음")
    priorities = []
    for r in p["recommendations"]:
        t = r.get("trap_id", "?")
        if r.get("status") not in STATUSES:
            errs.append(f"{t}: status 값 오류 {r.get('status')!r}")
        if r.get("relocate") != (r.get("status") == "recommended"):
            errs.append(f"{t}: relocate와 status 불일치")
        if r.get("status") == "recommended":
            if not r.get("recommended_location_id") or r.get("recommended_location_type") != "existing":
                errs.append(f"{t}: 추천 위치/유형 누락")
            if not isinstance(r.get("priority"), int):
                errs.append(f"{t}: priority 누락")
            priorities.append(r.get("priority"))
        elif r.get("recommended_location_id") is not None or r.get("priority") is not None:
            errs.append(f"{t}: 재배치가 아닌데 추천 위치/priority가 있음")
        for s in ("score", "current_location_score"):
            if r.get(s) is not None and not 0 <= r[s] <= 1:
                errs.append(f"{t}: {s} 범위(0~1) 벗어남")
        if not r.get("reasons") or not all(isinstance(x, str) and x for x in r["reasons"]):
            errs.append(f"{t}: reasons 비어 있음")
        if not {"actual_stats", "simulated_stats"} <= set(r):
            errs.append(f"{t}: 실제/가상 통계 분리 누락")
    if len(priorities) != len(set(priorities)):
        errs.append("priority 중복")
    traps = [r.get("trap_id") for r in p["recommendations"]]
    if len(traps) != len(set(traps)):
        errs.append("trap_id 중복")
    return errs


def export_recommendations(summary, client, now=None, run_id=None, **params):
    """추천 계산 → 본문 생성·검증 → 전송 → 재조회 일치 확인. 반환: (payload, POST 응답).
    같은 run_id는 서버가 409로 거절한다(ApiError). 덮어쓰기나 자동 재시도는 하지 않는다."""
    items, _ = recommend(summary, **params)
    payload = build_payload(items, summary, now=now, run_id=run_id)
    response = client.post_recommendations(payload)
    saved = client.get_recommendations(payload["run_id"])
    if saved["recommendations"] != payload["recommendations"]:
        raise RuntimeError("재조회한 추천 결과가 전송한 내용과 다릅니다.")
    return payload, response


def main():
    summary = load_trap_day_summary(SCENARIO_CSV)
    client = ApiClient.from_mock()
    payload, response = export_recommendations(summary, client)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"recommendations_{payload['run_id']}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print("POST 응답:", response)
    print("data_basis:", payload["data_basis"])
    for r in payload["recommendations"]:
        print(f"  {r['trap_id']} @{r['current_location_id']}: {r['status']}"
              + (f" -> {r['recommended_location_id']} (priority {r['priority']})" if r["relocate"] else ""))
    try:
        client.post_recommendations(payload)
    except ApiError as e:
        print("같은 run_id 재전송:", e.status, e.code, "(예상된 거절)")
    print("저장:", out)


if __name__ == "__main__":
    main()
