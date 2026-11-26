"""추천 알고리즘 검증 (가상 시나리오 기준, docs/recommendation_design.md 5절).

주의: 이 정확도는 '설계된 가상 상황을 구분하는 능력'이며 실제 현장 성능이 아니다.
실행: python -m src.evaluation
"""
import collections

import pandas as pd

from src import synthetic_data
from src.recommendation import recommend
from src.synthetic_data import generate_scenario

# 분석 기간 마지막 날 설치 중인 트랩의 기대 판단 (TRAP-05는 기간 중 철수해 평가 대상 아님)
EXPECTED = {
    "TRAP-01": ("keep", None),
    "TRAP-02": ("keep", None),
    "TRAP-03": ("recommended", "LOC-A"),
    "TRAP-04": ("insufficient_data", None),
    "TRAP-06": ("device_check", None),
}
SEEDS = range(42, 62)  # 20개


def evaluate_seed(seed, **params):
    """한 시드의 트랩별 일치 여부와 위치 점수 순서 점검."""
    summary = generate_scenario(write=False, seed=seed)["trap_day_summary"]
    items, scores = recommend(summary, known_locations=["LOC-E"], **params)
    got = {i["trap_id"]: (i["status"], i["recommended_location_id"]) for i in items}
    row = {"seed": seed, "trap_set_ok": set(got) == set(EXPECTED)}
    for trap, exp in EXPECTED.items():
        row[trap] = got.get(trap) == exp
    s = scores["score"]
    row["score_order_ok"] = bool(s["LOC-A"] > s["LOC-B"] and s["LOC-A"] > s["LOC-C"]
                                 and pd.isna(s["LOC-D"]) and pd.isna(s["LOC-E"]))
    cols = ["trap_set_ok", "score_order_ok", *EXPECTED]
    row["all_ok"] = all(row[c] for c in cols)
    return row


def evaluate(seeds=SEEDS, **params):
    return pd.DataFrame([evaluate_seed(s, **params) for s in seeds])


def sensitivity(seeds=SEEDS):
    """임계값을 바꿨을 때 전체 일치율(모든 트랩이 맞은 시드 비율)."""
    rows = []
    for ratio in (0.3, 0.5, 0.7):
        for min_det in (5, 10, 20):
            r = evaluate(seeds, relocate_ratio=ratio, min_detections=min_det)
            rows.append({"relocate_ratio": ratio, "min_detections": min_det, "all_ok_rate": r["all_ok"].mean()})
    return pd.DataFrame(rows)


def null_scenario(seeds=SEEDS, **params):
    """모든 위치 성과가 같고 고장 트랩도 없는 데이터. 억지 재배치/장치 의심을 만들지 않는지(거짓 양성) 확인.
    데이터 부족인 TRAP-04는 제외한다. 반환: 상태별 건수."""
    saved = dict(synthetic_data.LOCATION_PARAMS), dict(synthetic_data.DEVICE_FACTOR)
    counts = collections.Counter()
    try:
        for k in synthetic_data.LOCATION_PARAMS:
            synthetic_data.LOCATION_PARAMS[k] = (0.28, 0.30)
        synthetic_data.DEVICE_FACTOR.clear()
        for seed in seeds:
            summary = synthetic_data.generate_scenario(write=False, seed=seed)["trap_day_summary"]
            items, _ = recommend(summary, **params)
            counts.update(i["status"] for i in items if i["trap_id"] != "TRAP-04")
    finally:
        synthetic_data.LOCATION_PARAMS.clear(); synthetic_data.LOCATION_PARAMS.update(saved[0])
        synthetic_data.DEVICE_FACTOR.update(saved[1])
    return dict(counts)


if __name__ == "__main__":
    res = evaluate()
    print(f"[기본 임계값] 시드 {len(res)}개 (가상 데이터, 설계된 상황 구분 능력)")
    cols = ["trap_set_ok", "score_order_ok", *EXPECTED, "all_ok"]
    print((res[cols].mean() * 100).round(0).astype(int).astype(str).add("%").to_string())
    failed = res[~res["all_ok"]]
    if len(failed):
        print("\n불일치 시드:\n", failed.to_string(index=False))
    print("\n[민감도] 전체 일치율")
    print(sensitivity().pivot(index="relocate_ratio", columns="min_detections", values="all_ok_rate").to_string())
    print("\n[대조 시나리오] 모든 위치 동일·고장 없음 → 판정 건수:", null_scenario())
