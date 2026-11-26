import numpy as np
import pandas as pd

from src import movement_eval as me

HEADER = "ID\tDate\tTime\tX_Coordinate\tY_Coordinate\tActiveCoordinate\tGrid\n"


def _write(tmp_path, body):
    p = tmp_path / "coords.txt"
    p.write_text(HEADER + body, encoding="utf-8")
    return str(p)


def test_로더가_열이_밀린_행과_두_가지_날짜형식을_보정한다(tmp_path):
    body = (
        "1790\t20160812\t16:53:16\t30,06\t-18,73\t0\tG2\n"  # 정상
        "2686\t20160829\t09:23:16\t1\t25,14\t4,06\tG3\n"  # (활동, X, Y) 순서로 밀림
        "5504\t01.10.2016\t10:53:36\t31,5\t-14,9\t1\tG5\n"  # DD.MM.YYYY
    )
    df = me.load_fixes(_write(tmp_path, body))
    assert df.attrs["shifted_rows_fixed"] == 1
    r = df.set_index("id")
    assert (r.loc["1790", "x"], r.loc["1790", "y"], r.loc["1790", "active"]) == (30.06, -18.73, 0)
    assert (r.loc["2686", "x"], r.loc["2686", "y"], r.loc["2686", "active"]) == (25.14, 4.06, 1)
    assert str(r.loc["5504", "date"]) == "2016-10-01"


def test_개체ID는_숫자로_해석하지_않는다(tmp_path):
    body = "9,00E+52\t20160829\t09:23:16\t1,0\t2,0\t1\tG3\nFeb 01\t20160829\t09:33:16\t1,0\t2,0\t1\tG3\n"
    df = me.load_fixes(_write(tmp_path, body))
    assert list(df["id"]) == ["9,00E+52", "Feb 01"]


def test_날짜순서는_격자마다_따로_센다():
    df = pd.DataFrame({
        "grid": ["G2", "G2", "G5", "G5"],
        "date": pd.to_datetime(["2016-08-12", "2016-08-13", "2016-10-01", "2016-10-02"]).date,
    })
    assert list(me.day_index(df)) == [0, 1, 0, 1]


def test_점수는_같은_순위면_만점_무작위면_낮다():
    truth = np.arange(64, dtype=float)
    top, rho = me.score_prediction(truth.copy(), truth)
    assert top == 1.0 and rho > 0.999
    top, rho = me.score_prediction(truth[::-1].copy(), truth)
    assert top == 0.0 and rho < -0.999


def test_예측이_전부_같으면_NaN이다():
    top, rho = me.score_prediction(np.zeros(64), np.arange(64, dtype=float))
    assert np.isnan(top) and np.isnan(rho)


def test_한쪽_구석에_몰린_분포를_KDE가_학습한다():
    rng = np.random.default_rng(1)
    xy = np.vstack([rng.normal([10, 10], 2, (400, 2)), rng.uniform(0, 100, (20, 2))])
    lat = me.Lattice(xy[:, 0], xy[:, 1])
    pred = lat.lattice_to_cell(me.kde_lattice(lat, xy, 0.05 * lat.side))
    top_cell = lat.cell_index(np.array([10.0]), np.array([10.0]))[0]
    assert np.argsort(-pred)[0] in {top_cell, top_cell + 1, top_cell - 1, top_cell + me.CELLS, top_cell - me.CELLS}


def test_대역폭은_후보_중에서_고른다():
    rng = np.random.default_rng(2)
    xy = rng.normal([50, 50], 10, (600, 2))
    lat = me.Lattice(xy[:, 0], xy[:, 1])
    groups = [xy[i::3] for i in range(3)]
    h = me.select_bandwidth(lat, groups)
    assert any(abs(h - f * lat.side) < 1e-9 for f in me.BANDWIDTHS)


def test_시간분할은_학습과_평가를_날짜로_나누고_무작위보다_낫다():
    rng = np.random.default_rng(3)
    rows = []
    for ind in range(6):
        for day in range(5):
            pts = np.vstack([rng.normal([20, 20], 4, (60, 2)), rng.uniform(0, 100, (10, 2))])
            for x, y in pts:
                rows.append((f"A{ind}", "G9", pd.Timestamp(2016, 8, 12 + day, 12), x, y, 1))
    df = pd.DataFrame(rows, columns=["id", "grid", "t", "x", "y", "active"])
    df["date"] = df["t"].dt.date
    df["day"] = me.day_index(df)
    out = me.temporal_split(df, "G9")
    assert out["train_days"] == 3 and out["test_days"] == 2
    assert out["results"]["KDE"][0] > out["results"]["무작위"][0] + 0.3
