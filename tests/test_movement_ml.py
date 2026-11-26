import numpy as np
import pandas as pd

from src import movement_eval as me
from src import movement_ml as ml


def _toy(n_ind=6, n_days=5, seed=3):
    rng = np.random.default_rng(seed)
    rows = []
    for ind in range(n_ind):
        for day in range(n_days):
            t0 = pd.Timestamp(2016, 8, 12 + day, 0, 0)
            pts = np.vstack([rng.normal([20, 20], 4, (60, 2)), rng.uniform(0, 100, (20, 2))])
            for k, (x, y) in enumerate(pts):
                rows.append((f"A{ind}", "G9", t0 + pd.Timedelta(minutes=10 * k), x, y, 1))
    df = pd.DataFrame(rows, columns=["id", "grid", "t", "x", "y", "active"])
    df["date"] = df["t"].dt.date
    df["day"] = me.day_index(df)
    return df


def test_커버리지는_상위칸이_담는_활동_비율이다():
    truth = np.array([50.0, 30.0, 10.0, 5.0, 3.0, 1.0, 1.0] + [0.0] * 57)
    assert ml.coverage(truth.copy(), truth) == 99 / 100
    assert ml.coverage(truth[::-1].copy(), truth) == 0.0
    assert np.isnan(ml.coverage(np.zeros(64), truth))


def test_칸_특징표는_칸마다_한_행이고_비율은_합이_1이다():
    lat = me.Lattice(np.array([0.0, 100.0]), np.array([0.0, 100.0]))
    own = np.zeros(ml.NC)
    own[10], own[11] = 30, 10
    X = ml.cell_features(lat, own, np.ones(ml.NC))
    assert X.shape == (ml.NC, 7)
    assert abs(X[:, 0].sum() - 1) < 1e-9 and abs(X[:, 2].sum() - 1) < 1e-9
    assert X[10, 1] > 0 and X[0, 1] == 0  # 이웃 평균(1열): 이웃한 칸에는 생기고 먼 칸에는 없다
    assert X[10, 3] < X[0, 3]  # 집(위치 가중 중심)까지 거리(3열)는 방문한 칸이 더 가깝다


def test_세_ML모델이_끝까지_돌고_결과를_돌려준다(monkeypatch):
    monkeypatch.setattr(ml, "N_REPS", 2)
    monkeypatch.setattr(ml, "N_BOOT", 5)
    monkeypatch.setattr(ml, "RF_TREES", 10)
    monkeypatch.setattr(ml, "SIM_TREES", 10)
    out = ml.run_grid(_toy(), "G9")
    assert out["train_days"] == 3 and out["test_days"] == 2
    for name in ("방문 빈도", "KDE", "GBM 회귀", "RF 회귀", "이동 모델", "무작위"):
        assert name in out["results"]
    assert out["results"]["방문 빈도"][2] > out["results"]["무작위"][2] + 0.1
    assert set(out["vs_방문빈도"]) == {"KDE", "GBM 회귀", "RF 회귀", "이동 모델"}
