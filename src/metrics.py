"""성과 지표 계산 (docs/synthetic_data_design.md 6-2).

- 입력: trap_day_summary (실제 또는 가상). 포획 컬럼(sim_captures)이 없으면 포획 지표는 NaN.
- 분모가 0이면 지표는 0이 아니라 NaN (계산 불가를 0 성과로 오해하지 않기 위함).
- sim_ 접두사 지표는 가상 포획에 기반한 추정치이며 실제 포획 실적이 아니다.
"""
import numpy as np
import pandas as pd

# 데이터 부족 기준 (초기값, EDA 후 확정)
MIN_OBSERVED_DAYS = 7
MIN_OPERATING_HOURS = 72


def _ratio(num, den):
    num, den = num.astype(float), den.astype(float)
    return pd.Series(np.where(den > 0, num / den.where(den > 0, 1), np.nan), index=num.index)


def add_derived_metrics(df):
    """집계된 합계 컬럼으로 파생 지표를 추가한다 (일 단위 행, 집계 행 모두 사용 가능)."""
    out = df.copy()
    out["detection_rate"] = _ratio(out["rat_detections"], out["operating_hours"])
    # 비대상 '분류' 비율. 정답 라벨이 있을 때만 의미 있는 값이며 분류기 출력 기준임에 유의
    out["non_rat_ratio"] = _ratio(out["non_rat_detections"], out["rat_detections"] + out["non_rat_detections"])
    if "sim_captures" in out:
        out["sim_capture_rate"] = _ratio(out["sim_captures"], out["operating_hours"])
        out["sim_conversion"] = _ratio(out["sim_captures"], out["rat_detections"])
    else:
        out["sim_capture_rate"] = np.nan
        out["sim_conversion"] = np.nan
    return out


def aggregate_performance(summary, by=("location_id",)):
    """그룹(기본: 위치)별로 합산하고 파생 지표와 데이터 부족 여부를 계산한다."""
    spec = {
        "observed_days": ("operating_hours", lambda s: int((s > 0).sum())),
        "operating_hours": ("operating_hours", "sum"),
        "rat_detections": ("rat_detections", "sum"),
        "non_rat_detections": ("non_rat_detections", "sum"),
        "unclassified_detections": ("unclassified_detections", "sum"),
    }
    if "sim_captures" in summary:
        spec["sim_captures"] = ("sim_captures", "sum")
    out = summary.groupby(list(by)).agg(**spec).reset_index()
    out = add_derived_metrics(out)
    out["is_insufficient"] = (out["observed_days"] < MIN_OBSERVED_DAYS) | (out["operating_hours"] < MIN_OPERATING_HOURS)
    return out
