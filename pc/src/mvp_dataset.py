"""MVP 데이터셋: 트랩 하나(실제) + 나머지 트랩(가상 시나리오)을 한 trap_day_summary로 합친다.

- 실제 트랩: 감지·센서·작동 시간은 실제(detection_source=actual). 포획은 실제 포획 실적을 쓰지 않고
  쥐 감지 건수에 가정 확률을 곱해 가상으로 채운다(capture_source=synthetic, 모든 포획 수치는 가상 데이터 기반 추정).
- 나머지 트랩: synthetic_data 시나리오 그대로(detection_source=synthetic).
- 시나리오의 같은 트랩 ID 행은 실제 트랩으로 대체한다.
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from src.preprocessing import load_trap_day_summary
from src.synthetic_data import OUT_DIR, SEED, SUMMARY_COLUMNS

REAL_TRAP_ID = "TRAP-01"
CAPTURE_PROB = 0.30  # 쥐 감지 1건당 가상 포획 확률. 설계자 가정값이며 실제 포획률이 아니다.


def add_virtual_captures(actual, capture_prob=CAPTURE_PROB, seed=SEED):
    """실제 일별 요약에 가상 포획(sim_captures)을 붙인다. 쥐 감지 건수를 넘지 않는다."""
    out = actual.copy()
    rng = np.random.default_rng(seed)
    out["sim_captures"] = rng.binomial(out["rat_detections"].to_numpy(dtype=int), capture_prob)
    out["capture_source"] = "synthetic"
    return out


def build_mvp_summary(actual, synthetic, real_trap_id=REAL_TRAP_ID, capture_prob=CAPTURE_PROB, seed=SEED):
    """실제 트랩 1개 + 가상 트랩들을 합친 trap_day_summary를 만든다."""
    real = actual[actual["trap_id"] == real_trap_id]
    if real.empty:
        raise ValueError(f"실제 데이터에 {real_trap_id} 행이 없습니다.")
    others = synthetic[synthetic["trap_id"] != real_trap_id]
    clash = set(real["location_id"]) & set(others["location_id"])
    if clash:
        raise ValueError(
            f"실제 트랩의 위치 ID {sorted(clash)}가 가상 시나리오의 위치와 겹칩니다. "
            "실제와 가상 데이터가 한 위치로 섞이므로, 백엔드에 실제 위치를 다른 ID(예: LOC-REAL-1)로 등록하세요.")
    real = add_virtual_captures(real, capture_prob, seed)
    merged = pd.concat([others[SUMMARY_COLUMNS], real[SUMMARY_COLUMNS]], ignore_index=True)
    return merged.sort_values(["date", "trap_id"]).reset_index(drop=True)


def main():
    p = argparse.ArgumentParser(description="실제 트랩 1개 + 가상 트랩 시나리오를 합친 trap_day_summary CSV를 만든다.")
    p.add_argument("--actual", required=True, help="backend_import가 만든 실제 요약 CSV")
    p.add_argument("--synthetic", default=str(OUT_DIR / "trap_day_summary.csv"))
    p.add_argument("--real-trap", default=REAL_TRAP_ID)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    summary = build_mvp_summary(load_trap_day_summary(a.actual), load_trap_day_summary(a.synthetic), a.real_trap)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(a.out, index=False)
    print(f"저장: {a.out} ({len(summary)}행, 트랩 {summary['trap_id'].nunique()}개)")


if __name__ == "__main__":
    main()
