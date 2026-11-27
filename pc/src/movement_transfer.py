"""처음 보는 장소에서의 위치 추천: 다른 격자로 학습한 ML 모델로 활동 밀집 칸을 고른다.

데이터: Dryad 2rbnzs85c (야외 설치류 4종, 포획 정보 없음). 격자 3개 중 2개로 학습하고 남은 1개로 평가한다.
평가 격자에서는 처음 obs_days일의 위치만 입력으로 쓰고, 나머지 날의 칸별 활동을 예측해 상위 칸을 추천한다.
격자마다 좌표계가 달라 절대 좌표는 특징으로 쓰지 않는다. 칸의 경계(조사 구역 범위)는 미리 안다고 가정한다.
모델: GBM 회귀, RF 회귀 / 기준선: 방문 빈도, KDE, 무작위. 하이퍼파라미터는 평가 결과를 보고 바꾸지 않는다.
예측 대상은 동물이 나타날 칸이지 포획될 칸이 아니다.

실행: python -m src.movement_transfer [데이터 폴더] [결과 JSON 경로] [대시보드 지도 JSON 경로]
"""
import json
import sys
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor

from src import movement_eval as me
from src import movement_ml as ml

NC = me.CELLS * me.CELLS
FEATURES = ("visit_share", "neighbor_share", "visitor_share", "neighbor_visitor_share", "dist_activity", "dist_center")
OBS_DAYS = (1, 2, 3)
RF_TREES = 200
N_BOOT = 300
SEED = me.SEED


def _neighbors(f):
    """칸 값 -> 주변 8칸 평균(격자 밖은 0)."""
    pad = np.pad(f.reshape(me.CELLS, me.CELLS), 1)
    return (sum(pad[1 + dx:1 + dx + me.CELLS, 1 + dy:1 + dy + me.CELLS]
                for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)) / 8).reshape(-1)


def cell_features(counts):
    """counts[개체, 칸] 관측 위치 수 -> (칸 NC x FEATURES) 표. 개체 전체를 합친 장소 단위 특징이다."""
    total = counts.sum(axis=0)
    share = total / total.sum() if total.sum() > 0 else np.zeros(NC)
    seen = counts.sum(axis=1) > 0
    visitors = (counts[seen] > 0).mean(axis=0) if seen.any() else np.zeros(NC)
    idx = np.arange(me.CELLS)
    cc = (np.array([(a, b) for a in idx for b in idx]) + 0.5) / me.CELLS  # lattice의 칸 순서(x 우선)
    mid = cc.mean(axis=0)
    center = (cc * share[:, None]).sum(axis=0) if total.sum() > 0 else mid
    return np.column_stack([share, _neighbors(share), visitors, _neighbors(visitors),
                            np.hypot(*(cc - center).T), np.hypot(*(cc - mid).T)])


def grid_counts(df, grid):
    """(lattice, counts[개체, 날, 칸])"""
    g = df[df["grid"] == grid]
    lat = me.Lattice(g["x"], g["y"])
    return lat, ml._day_counts(lat, g, sorted(g["id"].unique()), int(g["day"].nunique()))


def training_table(df, grids):
    """학습 격자들에서 '앞의 s일 -> 다음 날의 칸별 활동 비율' 표."""
    X, y = [], []
    for grid in grids:
        _, counts = grid_counts(df, grid)
        for s in range(1, counts.shape[1]):
            target = counts[:, s].sum(axis=0)
            if target.sum() == 0:
                continue
            X.append(cell_features(counts[:, :s].sum(axis=1)))
            y.append(target / target.sum())
    return np.vstack(X), np.concatenate(y)


def fit_models(X, y):
    models = {
        "GBM": HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=150, min_samples_leaf=40,
                                             random_state=SEED),
        "RF": RandomForestRegressor(n_estimators=RF_TREES, min_samples_leaf=20, random_state=SEED),
    }
    for m in models.values():
        m.fit(X, y)
    return models


def _share(v):
    """칸 값 -> 합이 1인 비중(음수 예측은 0). 지도 표시용이며 순위·점수 계산에는 쓰지 않는다."""
    v = np.clip(v, 0, None)
    return (v / v.sum() if v.sum() > 0 else v).round(5).tolist()


def evaluate_fold(df, test_grid, obs_days):
    train_grids = [g for g in sorted(df["grid"].unique()) if g != test_grid]
    models = fit_models(*training_table(df, train_grids))
    lat, counts = grid_counts(df, test_grid)
    observed, truth_i = counts[:, :obs_days].sum(axis=1), counts[:, obs_days:].sum(axis=1)
    truth = truth_i.sum(axis=0)

    g = df[(df["grid"] == test_grid) & (df["day"] < obs_days)]
    h = me.select_bandwidth(lat, [d[["x", "y"]].to_numpy() for _, d in g.groupby("id")])
    ids = sorted(df.loc[df["grid"] == test_grid, "id"].unique())
    kde_i = np.vstack([lat.lattice_to_cell(me.kde_lattice(lat, g[g["id"] == i][["x", "y"]].to_numpy(), h))
                       for i in ids])

    def predict(pick):
        feat = cell_features(observed[pick])
        out = {name: m.predict(feat) for name, m in models.items()}
        out["방문 빈도"] = observed[pick].sum(axis=0)
        out["KDE"] = kde_i[pick].sum(axis=0)
        return out

    everyone = np.arange(len(ids))
    pred = predict(everyone)
    rng = np.random.default_rng(SEED)
    results = {k: ml.all_scores(v, truth) for k, v in pred.items()}
    results["무작위"] = tuple(np.nanmean([ml.all_scores(rng.random(NC), truth) for _ in range(200)], axis=0))

    diffs = {name: [] for name in models}
    for _ in range(N_BOOT):  # 개체를 다시 뽑아 ML - 방문 빈도 커버리지 차이의 95% 구간
        pick = rng.integers(0, len(ids), len(ids))
        p, t = predict(pick), truth_i[pick].sum(axis=0)
        base = ml.coverage(p["방문 빈도"], t)
        for name in models:
            d = ml.coverage(p[name], t) - base
            if not np.isnan(d):
                diffs[name].append(d)
    gaps = {k: {"mean": float(np.mean(v)), "lo": float(np.percentile(v, 2.5)), "hi": float(np.percentile(v, 97.5))}
            for k, v in diffs.items() if v}
    return {"test_grid": test_grid, "train_grids": train_grids, "obs_days": obs_days,
            "test_days": int(counts.shape[1] - obs_days), "individuals": len(ids), "results": results,
            "coverage_gap_vs_frequency": gaps,
            "recommended_cells": {k: np.argsort(-v, kind="stable")[:me.TOP_K].tolist() for k, v in pred.items()},
            "shares": {"GBM": _share(pred["GBM"]), "방문 빈도": _share(pred["방문 빈도"]), "actual": _share(truth)},
            "actual_top": np.argsort(-truth, kind="stable")[:me.TOP_K].tolist(),
            "extent": [lat.x1 - lat.x0, lat.y1 - lat.y0]}


def run(data_dir):
    df = me.load_fixes(f"{data_dir}/{me.COORD_FILE}")
    df["day"] = me.day_index(df)
    folds = [evaluate_fold(df, g, k) for k in OBS_DAYS for g in sorted(df["grid"].unique())
             if k < df.loc[df["grid"] == g, "day"].nunique()]
    return {"cells": me.CELLS, "top_k": me.TOP_K, "folds": folds}


def map_data(out):
    """대시보드 지도용 요약. 개체·시각 정보 없이 칸별 비중과 점수(적중률, 커버리지)만 담는다."""
    def scores(rows):
        return {n: [round(float(np.mean([r["results"][n][i] for r in rows])), 4) for i in (0, 2)]
                for n in rows[0]["results"]}

    folds = [{**{k: r[k] for k in ("test_grid", "train_grids", "obs_days", "test_days", "individuals", "extent",
                                   "shares", "actual_top")},
              "recommended": {n: r["recommended_cells"][n] for n in ("GBM", "방문 빈도")},
              "scores": scores([r])} for r in out["folds"]]
    days = sorted({r["obs_days"] for r in out["folds"]})
    return {"source": "Dryad 2rbnzs85c · 야외 설치류 4종 이동 좌표 (쥐 아님, 포획 정보 없음)",
            "cells": out["cells"], "top_k": out["top_k"], "folds": folds,
            "averages": [{"obs_days": k, "scores": scores([r for r in out["folds"] if r["obs_days"] == k])}
                         for k in days]}


def format_report(out):
    lines = [f"처음 보는 격자 평가, {out['cells']}x{out['cells']}칸, 상위 {out['top_k']}칸 (적중률 / 순위상관 / 커버리지)"]
    for r in out["folds"]:
        lines.append(f"\n관측 {r['obs_days']}일, 평가 {r['test_grid']} (학습 {'+'.join(r['train_grids'])}), "
                     f"개체 {r['individuals']}, 평가 {r['test_days']}일")
        for name, (top, rho, cov) in r["results"].items():
            lines.append(f"  {name:8s} {top:.2f}  {rho:+.2f}  {cov:.2f}")
        for name, v in r["coverage_gap_vs_frequency"].items():
            lines.append(f"  {name} - 방문 빈도 커버리지 {v['mean']:+.3f} ({v['lo']:+.3f}~{v['hi']:+.3f})")
    for k in sorted({r["obs_days"] for r in out["folds"]}):
        same = [r for r in out["folds"] if r["obs_days"] == k]
        lines.append(f"\n[관측 {k}일 평균] " + ", ".join(
            f"{n} {np.mean([r['results'][n][0] for r in same]):.2f}/{np.mean([r['results'][n][2] for r in same]):.2f}"
            for n in same[0]["results"]) + "  (적중률/커버리지)")
    return "\n".join(lines)


if __name__ == "__main__":
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "data/external"
    dest = sys.argv[2] if len(sys.argv) > 2 else "data/processed/movement_transfer_results.json"
    result = run(data_dir)
    print(format_report(result))
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    map_dest = sys.argv[3] if len(sys.argv) > 3 else "dashboard/data/external_map.json"
    Path(map_dest).parent.mkdir(parents=True, exist_ok=True)
    with open(map_dest, "w", encoding="utf-8") as f:
        json.dump(map_data(result), f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    print(f"\n저장: {dest}, {map_dest}")
