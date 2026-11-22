"""위치 추천 알고리즘 (docs/recommendation_design.md, score-v0.1).

규칙 + 점수 기반. 입력은 sim_captures가 있는 trap_day_summary이며, 모든 포획 관련 수치는 가상 데이터 기반 추정이다.
출력 항목은 API 명세(POST /recommendations)의 recommendations 항목과 같은 구조다.
"""
import numpy as np
import pandas as pd
from scipy.stats import chi2

from src.metrics import MIN_OBSERVED_DAYS, MIN_OPERATING_HOURS

ALGORITHM_VERSION = "score-v0.1"
Z = 1.96  # 95%


# ------------------------------------------------------------------ 통계
def wilson_interval(k, n, z=Z):
    """이항 비율(포획/감지)의 Wilson 구간. n=0이면 (nan, nan)."""
    if n <= 0:
        return np.nan, np.nan
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def poisson_rate_interval(k, hours, alpha=0.05):
    """건수 k를 hours 동안 관측했을 때 시간당 건수의 정확(exact) 구간. 재배치가 '의미 있는 차이'인지 확인용."""
    if hours <= 0:
        return np.nan, np.nan
    lo = 0.0 if k == 0 else chi2.ppf(alpha / 2, 2 * k) / 2
    hi = chi2.ppf(1 - alpha / 2, 2 * (k + 1)) / 2
    return lo / hours, hi / hours


# ------------------------------------------------------------------ 집계 보조
def _agg(df):
    return {"observed_days": int((df["operating_hours"] > 0).sum()), "hours": float(df["operating_hours"].sum()),
            "rat": int(df["rat_detections"].sum()), "non_rat": int(df["non_rat_detections"].sum()),
            "caps": int(df["sim_captures"].sum())}


def _sufficient(a, min_detections):
    return (a["observed_days"] >= MIN_OBSERVED_DAYS and a["hours"] >= MIN_OPERATING_HOURS
            and a["rat"] >= min_detections)


def _conv(a):
    return a["caps"] / a["rat"] if a["rat"] > 0 else np.nan


def _peers(summary, trap, loc, dates):
    """같은 위치·같은 날짜에 있었던 다른 트랩의 행."""
    return summary[(summary["location_id"] == loc) & (summary["trap_id"] != trap) & summary["date"].isin(dates)]


def _device_check(summary, trap, loc, min_detections):
    """같은 위치·같은 기간의 다른 트랩보다 전환율이 구간 기준으로 확실히 낮으면 장치 의심.
    반환: (의심 여부, 본인 전환율, 동료 전환율)"""
    own = summary[(summary["trap_id"] == trap) & (summary["location_id"] == loc)]
    a = _agg(own)
    b = _agg(_peers(summary, trap, loc, own["date"]))
    if not (_sufficient(a, min_detections) and _sufficient(b, min_detections)):
        return False, _conv(a), _conv(b)
    own_ub = wilson_interval(a["caps"], a["rat"])[1]
    peer_lb = wilson_interval(b["caps"], b["rat"])[0]
    return own_ub < peer_lb, _conv(a), _conv(b)


# ------------------------------------------------------------------ 위치 점수
def location_scores(summary, exclude_traps=(), min_detections=10, known_locations=None):
    """위치별 점수(0~1, 평가 가능한 위치 중 최댓값 대비 상대값). 평가 불가 위치는 score=NaN.
    기대 포획률 = 시간당 감지 × 전환율 Wilson 하한."""
    d = summary[~summary["trap_id"].isin(exclude_traps)]
    rows = []
    for loc, g in d.groupby("location_id"):
        a = _agg(g)
        ok = _sufficient(a, min_detections)
        rate = a["rat"] / a["hours"] if a["hours"] > 0 else np.nan
        conv_lb = wilson_interval(a["caps"], a["rat"])[0]
        cap_lo, cap_hi = poisson_rate_interval(a["caps"], a["hours"])
        rows.append({"location_id": loc, "eligible": ok, "detection_rate": rate, "sim_conversion": _conv(a),
                     "conversion_lb": conv_lb, "expected_capture_rate": rate * conv_lb if ok else np.nan,
                     "captures_per_hour_lo": cap_lo, "captures_per_hour_hi": cap_hi,
                     "rat_detections": a["rat"], "observed_days": a["observed_days"]})
    out = pd.DataFrame(rows).set_index("location_id")
    if known_locations is not None:
        out = out.reindex(sorted(set(out.index) | set(known_locations)))
        out["eligible"] = out["eligible"].eq(True)
    best = out["expected_capture_rate"].max()
    out["score"] = out["expected_capture_rate"] / best if best and best > 0 else np.nan
    return out


# ------------------------------------------------------------------ 추천
def _num(x, nd=3):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd)


def _pct(x):
    return f"{x:.0%}"


def _stats(a):
    hours = a["hours"]
    return (
        {"operating_hours": _num(hours, 1), "rat_detections": a["rat"], "non_rat_detections": a["non_rat"],
         "rat_detections_per_hour": _num(a["rat"] / hours) if hours > 0 else None},
        {"captures": a["caps"], "capture_conversion_rate": _num(_conv(a)),
         "captures_per_hour": _num(a["caps"] / hours) if hours > 0 else None},
    )


def _cause(summary, trap, cur, scores_ok_peers, own_conv_ci, min_detections):
    """재배치 사유의 원인 문장. 근거가 없으면 '원인 미확정'."""
    cur_ub = own_conv_ci[1]
    for loc in summary.loc[(summary["trap_id"] == trap) & (summary["location_id"] != cur), "location_id"].unique():
        a = _agg(summary[(summary["trap_id"] == trap) & (summary["location_id"] == loc)])
        if _sufficient(a, min_detections) and wilson_interval(a["caps"], a["rat"])[0] > cur_ub:
            return f"같은 트랩이 {loc}에서는 전환율 {_pct(_conv(a))}로 더 높았음 → 장치는 정상, 위치 문제로 판단"
    if scores_ok_peers is not None:
        return f"같은 위치의 다른 트랩도 비슷한 수준({_pct(scores_ok_peers)}) → 위치 문제로 판단"
    return "원인 미확정(같은 위치 다른 트랩·이전 설치 이력 없음) → 위치 문제 가능성으로 재배치 제안"


def recommend(summary, relocate_ratio=0.5, min_detections=10, known_locations=None):
    """분석 기간 마지막 날 설치 중인 트랩별 추천을 만든다. 반환: (추천 항목 리스트, 위치 점수 DataFrame)."""
    if "sim_captures" not in summary:
        raise ValueError("sim_captures 컬럼이 필요합니다 (가상 포획 데이터 기반 알고리즘).")
    last = summary["date"].max()
    current = summary[summary["date"] == last].groupby("trap_id")["location_id"].first()

    # 1) 장치 의심 트랩 판정 → 위치 점수에서 제외
    device = {t: _device_check(summary, t, loc, min_detections) for t, loc in current.items()}
    suspects = [t for t, (flag, _, _) in device.items() if flag]
    scores = location_scores(summary, suspects, min_detections, known_locations)

    items = []
    for trap, cur in current.items():
        a = _agg(summary[(summary["trap_id"] == trap) & (summary["location_id"] == cur)])
        actual, simulated = _stats(a)
        cur_score = scores["score"].get(cur, np.nan)
        item = {"trap_id": trap, "current_location_id": cur, "recommended_location_id": None,
                "recommended_location_type": None, "relocate": False, "status": None, "priority": None,
                "score": None, "current_location_score": _num(cur_score), "reasons": [],
                "actual_stats": actual, "simulated_stats": simulated}
        flag, own_conv, peer_conv = device[trap]
        if flag:
            item["status"] = "device_check"
            item["reasons"] = [f"{trap}은(는) {cur}에서 감지 대비 가상 포획 전환율이 {_pct(own_conv)}로, 같은 위치·같은 기간의 "
                               f"다른 트랩({_pct(peer_conv)})보다 확실히 낮음 → 위치가 아니라 장치 점검 필요"]
        elif not _sufficient(a, min_detections) or np.isnan(cur_score):
            item["status"] = "insufficient_data"
            item["reasons"] = [f"현재 위치 관측 {a['observed_days']}일·작동 {a['hours']:.0f}시간·쥐 감지 {a['rat']}건으로 "
                               f"기준(7일, 72시간, 감지 {min_detections}건) 미달 → 추천 확정 안 함"]
        else:
            others = scores[(scores.index != cur) & scores["score"].notna()]
            target = others["score"].idxmax() if len(others) else None
            moved = False
            if target is not None:
                t_row, c_row = scores.loc[target], scores.loc[cur]
                significant = c_row["captures_per_hour_hi"] < t_row["captures_per_hour_lo"]
                moved = cur_score <= relocate_ratio * t_row["score"] and significant
            if moved:
                peers = _agg(_peers(summary, trap, cur, summary.loc[(summary["trap_id"] == trap)
                                                                      & (summary["location_id"] == cur), "date"]))
                peer_c = _conv(peers) if _sufficient(peers, min_detections) else None
                item.update(status="recommended", relocate=True, recommended_location_id=target,
                            recommended_location_type="existing", score=_num(t_row["score"]))
                item["reasons"] = [
                    f"현재 위치({cur}) 점수 {cur_score:.2f} ≤ 추천 위치({target}) 점수 {t_row['score']:.2f}의 "
                    f"{relocate_ratio:.0%}, 시간당 가상 포획 차이도 구간 기준으로 유의함",
                    _cause(summary, trap, cur, peer_c, wilson_interval(a["caps"], a["rat"]), min_detections)]
            else:
                item["status"] = "keep"
                item["reasons"] = [f"현재 위치({cur}) 점수 {cur_score:.2f}: 다른 위치로 옮길 만큼 확실히 낮지 않음"]
        items.append(item)

    rec = sorted((i for i in items if i["status"] == "recommended"),
                 key=lambda i: i["score"] - i["current_location_score"], reverse=True)
    for rank, i in enumerate(rec, start=1):
        i["priority"] = rank
    return items, scores
