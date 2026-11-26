"""머신러닝 모델과 통계 모델(KDE, 방문 빈도)을 같은 시간 분할 검증틀에서 비교한다.

검증틀은 src/movement_eval.py와 같다: 격자별로 앞쪽 날로 학습하고 뒤쪽 날의 칸별 활동을 예측한다.
모델
  - 방문 빈도 / KDE : 통계 기준선 (movement_eval)
  - GBM 회귀, RF 회귀 : (개체, 칸) 단위 표를 만들어 '다음 기간의 방문 비율'을 예측
  - 이동 모델(RF) : 현재 칸·시각·집 위치로 다음 칸을 예측하고 시뮬레이션해 칸별 점유를 얻음
  - 무작위
지표: 상위 k칸 적중률, 순위상관, 상위 k칸이 담는 활동 비율(커버리지)
평가 구간의 위치는 학습·대역폭 선택·시뮬레이션 길이 어디에도 쓰지 않는다 (평가 일수만 설계값으로 사용).

실행: python -m src.movement_ml [데이터 폴더] [결과 JSON 경로]
"""
import json
import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import (
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)

from src import movement_eval as me

NC = me.CELLS * me.CELLS
N_REPS = 20  # 이동 모델 시뮬레이션 반복 수
N_BOOT = 300
RF_TREES = 200
SIM_TREES = 100
SEED = me.SEED
ML_NAMES = ("GBM 회귀", "RF 회귀", "이동 모델")


def coverage(pred, truth, k=me.TOP_K):
    """예측 상위 k칸이 실제 활동의 몇 %를 담는지."""
    if truth.sum() == 0 or np.ptp(pred) == 0:
        return np.nan
    return float(truth[np.argsort(-pred, kind="stable")[:k]].sum() / truth.sum())


def all_scores(pred, truth):
    top, rho = me.score_prediction(pred, truth)
    return top, rho, coverage(pred, truth)


def _norm_centers(lat):
    cc = lat.cell_centers()
    return (cc - np.array([lat.x0, lat.y0])) / lat.side


def cell_features(lat, own, others):
    """한 개체의 (칸 수 NC x 특징 7) 표. own/others: 칸별 위치 수 (others는 다른 개체 합)."""
    n = own.sum()
    f = own / n if n > 0 else np.zeros(NC)
    pad = np.pad(f.reshape(me.CELLS, me.CELLS), 1)
    nb = sum(
        pad[1 + dx:1 + dx + me.CELLS, 1 + dy:1 + dy + me.CELLS]
        for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)
    ) / 8
    po = others / others.sum() if others.sum() > 0 else np.zeros(NC)
    cc = _norm_centers(lat)
    home = (cc * f[:, None]).sum(axis=0) if n > 0 else cc.mean(axis=0)
    d_home = np.hypot(cc[:, 0] - home[0], cc[:, 1] - home[1])
    d_mid = np.hypot(cc[:, 0] - cc[:, 0].mean(), cc[:, 1] - cc[:, 1].mean())
    return np.column_stack([f, nb.reshape(-1), po, d_home, d_mid, cc[:, 0], cc[:, 1]])


def _day_counts(lat, g, ids, n_days):
    """counts[i, day, cell]"""
    out = np.zeros((len(ids), n_days, NC))
    cell = lat.cell_index(g["x"].to_numpy(), g["y"].to_numpy())
    pos = {i: k for k, i in enumerate(ids)}
    for i, d, c in zip(g["id"], g["day"], cell):
        out[pos[i], d, c] += 1
    return out


def regression_predictions(lat, counts, ntr, models, rng):
    """GBM/RF 회귀. 학습 구간 안에서 '앞 날들 -> 다음 날' 표를 만들어 맞추고, 전체 학습 구간 -> 평가 구간을 예측."""
    n_ind = counts.shape[0]
    X, y = [], []
    for s in range(1, ntr):
        feat = counts[:, :s].sum(axis=1)
        total = feat.sum(axis=0)
        for i in range(n_ind):
            tgt = counts[i, s]
            if tgt.sum() == 0 or feat[i].sum() == 0:
                continue
            X.append(cell_features(lat, feat[i], total - feat[i]))
            y.append(tgt / tgt.sum())
    X, y = np.vstack(X), np.concatenate(y)
    feat = counts[:, :ntr].sum(axis=1)
    total = feat.sum(axis=0)
    Xte = [cell_features(lat, feat[i], total - feat[i]) for i in range(n_ind)]
    w = feat.sum(axis=1)  # 학습 구간 위치 수를 개체의 활동량 가중치로 사용
    out = {}
    for name, mdl in models.items():
        mdl.fit(X, y)
        out[name] = np.vstack([np.clip(mdl.predict(x), 0, None) * w[i] for i, x in enumerate(Xte)])
    return out


def _move_features(lat, cell, prev_cell, hour, home):
    cc = _norm_centers(lat)
    c, p = cc[cell], cc[prev_cell]
    ang = 2 * np.pi * hour / 24
    return np.column_stack([c[:, 0], c[:, 1], np.sin(ang), np.cos(ang), home[:, 0], home[:, 1],
                            c[:, 0] - home[:, 0], c[:, 1] - home[:, 1], c[:, 0] - p[:, 0], c[:, 1] - p[:, 1]])


def movement_predictions(lat, g_train, ids, ntr, n_test_days, interval_min, rng):
    """다음 칸 예측 모델(RF)을 학습하고, 개체별로 시뮬레이션해 칸별 기대 점유(방문 수)를 만든다."""
    cc = _norm_centers(lat)
    homes, X, y = {}, [], []
    for i in ids:
        d = g_train[g_train["id"] == i].sort_values("t")
        cell = lat.cell_index(d["x"].to_numpy(), d["y"].to_numpy())
        f = np.bincount(cell, minlength=NC) / max(len(cell), 1)
        homes[i] = (cc * f[:, None]).sum(axis=0)
        t = d["t"].to_numpy()
        gap = np.diff(t).astype("timedelta64[s]").astype(float) / 60
        ok = gap <= 3 * interval_min
        cur, nxt = cell[:-1][ok], cell[1:][ok]
        prv = np.concatenate([[cell[0]], cell[:-1]])[:-1][ok]
        hour = (d["t"].dt.hour + d["t"].dt.minute / 60).to_numpy()[:-1][ok]
        X.append(_move_features(lat, cur, prv, hour, np.tile(homes[i], (len(cur), 1))))
        y.append(nxt)
    X, y = np.vstack(X), np.concatenate(y)
    clf = RandomForestClassifier(n_estimators=SIM_TREES, min_samples_leaf=3, random_state=SEED, n_jobs=-1).fit(X, y)

    n_ind = len(ids)
    n_train_fix = np.array([(g_train["id"] == i).sum() for i in ids])
    steps = np.round(n_train_fix / ntr * n_test_days).astype(int)
    last = [g_train[g_train["id"] == i].sort_values("t").iloc[-1] for i in ids]
    cur = np.repeat(lat.cell_index(np.array([r["x"] for r in last]), np.array([r["y"] for r in last])), N_REPS)
    prv = cur.copy()
    t0 = [r["t"] for r in last]
    home = np.repeat(np.array([homes[i] for i in ids]), N_REPS, axis=0)
    occ = np.zeros((n_ind, NC))
    ind_of = np.repeat(np.arange(n_ind), N_REPS)
    for s in range(1, steps.max() + 1):
        hour = np.array([(t0[k] + pd.Timedelta(minutes=interval_min * s)).hour
                         + (t0[k] + pd.Timedelta(minutes=interval_min * s)).minute / 60 for k in ind_of])
        proba = clf.predict_proba(_move_features(lat, cur, prv, hour, home))
        u = rng.random(len(cur))[:, None]
        nxt = clf.classes_[np.minimum((proba.cumsum(axis=1) < u).sum(axis=1), len(clf.classes_) - 1)]
        prv, cur = cur, nxt
        active = s <= steps[ind_of]
        np.add.at(occ, (ind_of[active], cur[active]), 1)
    return occ / N_REPS


def run_grid(df, grid, train_frac=0.6):
    g = df[df["grid"] == grid]
    ids = sorted(g["id"].unique())
    n_days = int(g["day"].nunique())
    ntr = max(1, round(n_days * train_frac))
    lat = me.Lattice(g["x"], g["y"])
    rng = np.random.default_rng(SEED)
    counts = _day_counts(lat, g, ids, n_days)
    tr, te = g[g["day"] < ntr], g[g["day"] >= ntr]
    truth_i = counts[:, ntr:].sum(axis=1)
    interval = float(np.median(np.concatenate([
        np.diff(d.sort_values("t")["t"].to_numpy()).astype("timedelta64[s]").astype(float) / 60
        for _, d in g.groupby("id")])))
    h = me.select_bandwidth(lat, [d[["x", "y"]].to_numpy() for _, d in tr.groupby("day")])

    pred = {"방문 빈도": counts[:, :ntr].sum(axis=1)}
    pred["KDE"] = np.vstack([lat.lattice_to_cell(me.kde_lattice(lat, tr[tr["id"] == i][["x", "y"]].to_numpy(), h)) for i in ids])
    models = {
        "GBM 회귀": HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=150, min_samples_leaf=40, random_state=SEED),
        "RF 회귀": RandomForestRegressor(n_estimators=RF_TREES, min_samples_leaf=20, random_state=SEED, n_jobs=-1),
    }
    pred.update(regression_predictions(lat, counts, ntr, models, rng))
    pred["이동 모델"] = movement_predictions(lat, tr, ids, ntr, n_days - ntr, interval, rng)

    truth = truth_i.sum(axis=0)
    results = {k: all_scores(v.sum(axis=0), truth) for k, v in pred.items()}
    rnd = np.array([all_scores(rng.random(NC), truth) for _ in range(200)])
    results["무작위"] = tuple(np.nanmean(rnd, axis=0))

    gaps = {}
    for name in ("KDE",) + ML_NAMES:
        d_top, d_cov = [], []
        for _ in range(N_BOOT):
            pick = rng.integers(0, len(ids), len(ids))
            t = truth_i[pick].sum(axis=0)
            a, b = all_scores(pred[name][pick].sum(axis=0), t), all_scores(pred["방문 빈도"][pick].sum(axis=0), t)
            if not (np.isnan(a[0]) or np.isnan(b[0]) or np.isnan(a[2]) or np.isnan(b[2])):
                d_top.append(a[0] - b[0])
                d_cov.append(a[2] - b[2])
        ci = lambda v: {"mean": float(np.mean(v)), "lo": float(np.percentile(v, 2.5)), "hi": float(np.percentile(v, 97.5))} if v else None
        gaps[name] = {"적중률": ci(d_top), "커버리지": ci(d_cov)}
    return {"grid": grid, "individuals": len(ids), "train_days": int(ntr), "test_days": int(n_days - ntr),
            "results": results, "vs_방문빈도": gaps}


def run(data_dir):
    df = me.load_fixes(f"{data_dir}/{me.COORD_FILE}")
    df["day"] = me.day_index(df)
    return {"top_k": me.TOP_K, "cells": me.CELLS, "grids": [run_grid(df, g) for g in sorted(df["grid"].unique())]}


def format_report(out):
    lines = [f"시간 분할, {out['cells']}x{out['cells']}칸, 상위 {out['top_k']}칸 (적중률 / 순위상관 / 커버리지)"]
    for r in out["grids"]:
        lines.append(f"\n{r['grid']}  개체 {r['individuals']}, 학습 {r['train_days']}일 / 평가 {r['test_days']}일")
        for name, (top, rho, cov) in r["results"].items():
            lines.append(f"  {name:8s} {top:.2f}  {rho:+.2f}  {cov:.2f}")
        for name, v in r["vs_방문빈도"].items():
            a, c = v["적중률"], v["커버리지"]
            if a and c:
                lines.append(f"  {name} - 방문 빈도: 적중률 {a['mean']:+.2f} ({a['lo']:+.2f}~{a['hi']:+.2f}), 커버리지 {c['mean']:+.3f} ({c['lo']:+.3f}~{c['hi']:+.3f})")
    return "\n".join(lines)


if __name__ == "__main__":
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "data/external"
    dest = sys.argv[2] if len(sys.argv) > 2 else "data/processed/movement_ml_results.json"
    result = run(data_dir)
    print(format_report(result))
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n저장: {dest}")
