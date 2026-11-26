import numpy as np
import pandas as pd

from src import urban_camera_eval as uc


def _toy(n_cam=12, seed=5):
    """지점 0~2는 모든 시즌에 쥐가 많고 나머지는 적다. 시즌 8개, 시즌당 90일."""
    rng = np.random.default_rng(seed)
    rows = []
    for b in range(8):
        base = pd.Timestamp(2022, 1, 1) + pd.Timedelta(days=90 * b)
        for c in range(n_cam):
            rows.append((f"C{c:02d}", "Fox", base, f"S{b}", 10.0 * c, 300))  # 가동 표시용 기록
            n = 30 if c < 3 else 2
            for k in range(n):
                t = base + pd.Timedelta(days=int(rng.integers(0, 90)), hours=int(rng.integers(0, 24)), minutes=int(rng.integers(0, 60)))
                rows.append((f"C{c:02d}", "Rat", t, f"S{b}", 10.0 * c, 300))
    return pd.DataFrame(rows, columns=["ID", "Species", "Timestamp", "SeasonYear", "avg_impervious", "MaxDays"])


def test_연속_촬영은_한_번의_방문으로_센다():
    t0 = pd.Timestamp(2022, 1, 1, 22, 0)
    df = pd.DataFrame({
        "ID": ["C1"] * 4, "Species": ["Rat"] * 4,
        "Timestamp": [t0, t0 + pd.Timedelta(minutes=5), t0 + pd.Timedelta(minutes=20), t0 + pd.Timedelta(minutes=120)],
        "SeasonYear": ["S0"] * 4, "avg_impervious": [1.0] * 4, "MaxDays": [100] * 4,
    })
    P = uc.prepare(df)
    assert len(P["rat"]) == 4 and int(P["rat"]["bout"].sum()) == 2
    assert P["bouts"][0, 0] == 2


def test_시즌은_시간순으로_정렬되고_가동_표시가_만들어진다():
    P = uc.prepare(_toy())
    assert P["blocks"] == [f"S{b}" for b in range(8)]
    assert P["active"].all() and P["bouts"].shape == (12, 8)


def test_지속적인_지점은_방문빈도가_무작위보다_잘_맞힌다():
    out = uc.rolling_eval(uc.prepare(_toy()))
    mean = out["mean"]
    assert mean["방문 빈도"][0] > mean["무작위"][0] + 0.3
    assert mean["방문 빈도"][2] > 0.8
    assert set(out["vs_방문빈도"]) == {"직전 시즌", "불투과면만", "GBM", "RF"}


def test_메트릭은_평가_기록이_없으면_NaN이다():
    rng = np.random.default_rng(0)
    assert all(np.isnan(v) for v in uc._metrics(np.arange(10.0), np.zeros(10), 3, rng))


def test_안정성_곡선은_항상_같은_상위_지점을_찾아낸다():
    # 나머지 9곳은 기록 2건짜리 잡음이라 전체 순위상관은 낮고(약 0.27), 상위 지점 적중은 1.0이어야 한다
    curve = uc.stability_curve(uc.prepare(_toy()), windows=(60,), step_days=60)
    assert curve and curve[0]["top_hit_mean"] == 1.0 and curve[0]["rho_median"] > 0.1
