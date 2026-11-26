import json

import numpy as np
import pandas as pd

from src import movement_eval as me
from src import movement_transfer as mt


def _toy(grid, hot, seed, n_ind=6, n_days=5):
    """hot 지점에 몰리는 활동 + 약간의 균등 잡음."""
    rng = np.random.default_rng(seed)
    rows = []
    for ind in range(n_ind):
        for day in range(n_days):
            t0 = pd.Timestamp(2016, 8, 12 + day)
            pts = np.vstack([rng.normal(hot, 4, (60, 2)), rng.uniform(0, 100, (20, 2))])
            for k, (x, y) in enumerate(pts):
                rows.append((f"{grid}-{ind}", grid, t0 + pd.Timedelta(minutes=10 * k), x, y, 1))
    return pd.DataFrame(rows, columns=["id", "grid", "t", "x", "y", "active"])


def toy_all():
    df = pd.concat([_toy("G1", (20, 20), 1), _toy("G2", (70, 30), 2), _toy("G3", (40, 80), 3)], ignore_index=True)
    df["date"] = df["t"].dt.date
    df["day"] = me.day_index(df)
    return df


def test_특징은_칸마다_한_행이고_절대_좌표를_쓰지_않는다():
    counts = np.zeros((2, mt.NC))
    counts[0, 10], counts[1, 10], counts[0, 11] = 30, 5, 10
    X = mt.cell_features(counts)
    assert X.shape == (mt.NC, len(mt.FEATURES))
    assert abs(X[:, 0].sum() - 1) < 1e-9
    assert X[10, mt.FEATURES.index("visitor_share")] == 1.0 and X[11, mt.FEATURES.index("visitor_share")] == 0.5
    assert not {"x", "y"} & set(mt.FEATURES)


def test_학습표는_학습_격자만_쓴다():
    df = toy_all()
    X, y = mt.training_table(df, ["G1", "G2"])
    assert len(X) == len(y) == 2 * 4 * mt.NC  # 격자 2개 x (5일 중 다음 날 4번) x 칸
    changed = df.copy()
    changed.loc[changed["grid"] == "G3", ["x", "y"]] = 0.0
    X2, y2 = mt.training_table(changed, ["G1", "G2"])
    assert np.array_equal(X, X2) and np.array_equal(y, y2)


def test_처음_보는_격자에서_평가_구간을_쓰지_않고_추천한다(monkeypatch):
    monkeypatch.setattr(mt, "N_BOOT", 5)
    monkeypatch.setattr(mt, "RF_TREES", 20)
    df = toy_all()
    r = mt.evaluate_fold(df, "G3", obs_days=2)
    assert r["train_grids"] == ["G1", "G2"] and r["obs_days"] == 2 and r["test_days"] == 3
    for name in ("GBM", "RF", "방문 빈도", "KDE", "무작위"):
        assert name in r["results"]
    for name in ("GBM", "RF"):
        assert r["results"][name][2] > r["results"]["무작위"][2] + 0.1
    # 평가 구간을 바꿔도 예측(추천 칸)은 같아야 한다
    changed = df.copy()
    late = (changed["grid"] == "G3") & (changed["day"] >= 2)
    changed.loc[late, "x"] = changed.loc[late, "x"].to_numpy()[::-1]
    assert mt.evaluate_fold(changed, "G3", obs_days=2)["recommended_cells"] == r["recommended_cells"]


def test_지도_데이터는_추천칸과_실제_상위칸을_담는다(monkeypatch):
    monkeypatch.setattr(mt, "N_BOOT", 5)
    monkeypatch.setattr(mt, "RF_TREES", 20)
    fold = mt.evaluate_fold(toy_all(), "G3", obs_days=2)
    data = mt.map_data({"cells": me.CELLS, "top_k": me.TOP_K, "folds": [fold]})
    f = data["folds"][0]
    for key in ("GBM", "방문 빈도", "actual"):
        assert len(f["shares"][key]) == mt.NC and abs(sum(f["shares"][key]) - 1) < 1e-3
        assert min(f["shares"][key]) >= 0
    assert f["recommended"]["GBM"] == fold["recommended_cells"]["GBM"]
    assert len(f["actual_top"]) == me.TOP_K
    hit = len(set(f["recommended"]["GBM"]) & set(f["actual_top"])) / me.TOP_K
    assert abs(hit - f["scores"]["GBM"][0]) < 1e-3
    assert data["averages"][0]["obs_days"] == 2 and "무작위" in data["averages"][0]["scores"]
    json.dumps(data, allow_nan=False)
