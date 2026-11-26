"""공개 이동 좌표 데이터(Dryad 2rbnzs85c, 야외 설치류 4종)로 '활동 밀집 칸' 예측을 검증한다.

예측 대상은 동물이 나타날 칸이지 포획될 칸이 아니다 (이 데이터에는 포획 정보가 없다).
격자(G2, G3, G5)마다 좌표계·측정 간격이 달라 격자별로 따로 학습·평가한다.

모델: 가우시안 KDE (대역폭은 학습 구간 안의 교차검증으로 선택)
기준선: 무작위 / 중심 거리 / 단순 방문 빈도(칸별 위치 수)
검증: (1) 시간 분할 - 앞쪽 날로 학습, 뒤쪽 날로 평가
      (2) 개체 분할 - 일부 개체로 학습, 처음 보는 개체로 평가 (5겹)

실행: python -m src.movement_eval [데이터 폴더] [결과 JSON 경로]
"""
import csv
import json
import math
import sys
from datetime import datetime

import numpy as np
import pandas as pd

COORD_FILE = "CoordinatesCommunity_AnimalsAllGrids.txt"
CELLS = 8  # 격자별 위치 범위를 CELLS x CELLS 칸으로 나눈다 (좌표 단위가 문서에 없어 상대 분할)
LATTICE = 48  # KDE 평가용 촘촘한 점 격자 (CELLS의 배수)
BANDWIDTHS = (0.02, 0.03, 0.05, 0.08, 0.12, 0.2)  # 격자 변 길이 대비 비율
TOP_K = 6  # 64칸 중 약 10%
N_BOOT = 300
SEED = 20260126


def _num(s):
    return float(s.replace(",", "."))


def load_fixes(path):
    """좌표 파일을 읽어 DataFrame으로 돌려준다 (열: id, grid, t, x, y, active, date).

    파일 문제를 보정한다: (a) 일부 행은 열 순서가 (활동여부, X, Y)로 밀려 있다.
    (b) G5는 날짜가 DD.MM.YYYY 형식이다. 보정 건수는 df.attrs에 담는다.
    """
    rows, shifted = [], 0
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            c4, c5, c6 = r["X_Coordinate"], r["Y_Coordinate"], r["ActiveCoordinate"]
            if c4 in ("0", "1") and c6 not in ("0", "1"):
                act, x, y = c4, _num(c5), _num(c6)
                shifted += 1
            else:
                x, y, act = _num(c4), _num(c5), c6
            fmt = "%d.%m.%Y" if "." in r["Date"] else "%Y%m%d"
            t = datetime.strptime(r["Date"] + " " + r["Time"], fmt + " %H:%M:%S")
            rows.append((r["ID"], r["Grid"], t, x, y, int(act)))
    df = pd.DataFrame(rows, columns=["id", "grid", "t", "x", "y", "active"])
    df["date"] = df["t"].dt.date
    df.attrs["shifted_rows_fixed"] = shifted
    return df


def day_index(df):
    """격자 안에서 날짜 순서(0부터)."""
    out = pd.Series(0, index=df.index)
    for _, g in df.groupby("grid"):
        order = {d: i for i, d in enumerate(sorted(g["date"].unique()))}
        out.loc[g.index] = g["date"].map(order)
    return out


class Lattice:
    """한 격자의 위치 범위를 CELLS x CELLS 칸 / LATTICE x LATTICE 점으로 나눈다."""

    def __init__(self, x, y):
        self.x0, self.x1 = float(np.min(x)), float(np.max(x))
        self.y0, self.y1 = float(np.min(y)), float(np.max(y))
        self.side = max(self.x1 - self.x0, self.y1 - self.y0) or 1.0
        gx = self.x0 + (np.arange(LATTICE) + 0.5) / LATTICE * (self.x1 - self.x0 or 1.0)
        gy = self.y0 + (np.arange(LATTICE) + 0.5) / LATTICE * (self.y1 - self.y0 or 1.0)
        self.pts = np.array([(a, b) for a in gx for b in gy])  # (LATTICE^2, 2), x 우선

    def _idx(self, v, lo, hi, n):
        span = (hi - lo) or 1.0
        return np.clip(((v - lo) / span * n).astype(int), 0, n - 1)

    def lattice_index(self, x, y):
        return self._idx(x, self.x0, self.x1, LATTICE) * LATTICE + self._idx(y, self.y0, self.y1, LATTICE)

    def cell_index(self, x, y):
        return self._idx(x, self.x0, self.x1, CELLS) * CELLS + self._idx(y, self.y0, self.y1, CELLS)

    def lattice_to_cell(self, dens):
        """점 격자 값 -> 칸 평균."""
        r = LATTICE // CELLS
        return dens.reshape(CELLS, r, CELLS, r).mean(axis=(1, 3)).reshape(-1)

    def cell_centers(self):
        cx = self.x0 + (np.arange(CELLS) + 0.5) / CELLS * (self.x1 - self.x0)
        cy = self.y0 + (np.arange(CELLS) + 0.5) / CELLS * (self.y1 - self.y0)
        return np.array([(a, b) for a in cx for b in cy])


def kde_lattice(lat, xy, h):
    """위치 점들이 만드는 (정규화 전) KDE 합을 점 격자에서 계산한다."""
    out = np.zeros(len(lat.pts))
    for s in range(0, len(xy), 2000):
        d2 = ((lat.pts[None, :, :] - xy[s:s + 2000, None, :]) ** 2).sum(axis=2)
        out += np.exp(-d2 / (2 * h * h)).sum(axis=0)
    return out


def select_bandwidth(lat, groups):
    """leave-one-group-out 로그우도가 가장 높은 대역폭(절대 길이)을 고른다.

    groups: 위치 배열(n,2) 리스트 (시간 분할이면 날, 개체 분할이면 개체).
    """
    best, best_ll = None, -math.inf
    for frac in BANDWIDTHS:
        h = frac * lat.side
        per = [kde_lattice(lat, g, h) for g in groups]
        total = np.sum(per, axis=0)
        ll = 0.0
        for g, d in zip(groups, per):
            loo = total - d
            p = loo / loo.sum() + 1e-12
            ll += np.log(p[lat.lattice_index(g[:, 0], g[:, 1])]).sum()
        if ll > best_ll:
            best, best_ll = h, ll
    return best


def _rank_corr(a, b):
    return float(pd.Series(a).rank().corr(pd.Series(b).rank()))


def score_prediction(pred, truth, k=TOP_K):
    """pred, truth: 칸별 값. 상위 k칸 겹침 비율과 순위상관."""
    if np.ptp(pred) == 0 or truth.sum() == 0:
        top = np.nan
    else:
        top = len(set(np.argsort(-pred, kind="stable")[:k]) & set(np.argsort(-truth, kind="stable")[:k])) / k
    return top, (_rank_corr(pred, truth) if np.ptp(pred) > 0 else np.nan)


def _predictions(lat, train_xy, h, rng):
    cells = lat.cell_index(train_xy[:, 0], train_xy[:, 1])
    freq = np.bincount(cells, minlength=CELLS * CELLS).astype(float)
    centroid = train_xy.mean(axis=0)
    cc = lat.cell_centers()
    dist = -np.hypot(cc[:, 0] - centroid[0], cc[:, 1] - centroid[1])
    kde = lat.lattice_to_cell(kde_lattice(lat, train_xy, h))
    return {"KDE": kde, "방문 빈도": freq, "중심 거리": dist, "무작위": rng.random(CELLS * CELLS)}


def _eval_one(lat, train_xy, test_xy, h, rng, n_random=200):
    truth = np.bincount(lat.cell_index(test_xy[:, 0], test_xy[:, 1]), minlength=CELLS * CELLS).astype(float)
    res = {}
    preds = _predictions(lat, train_xy, h, rng)
    for name, p in preds.items():
        if name == "무작위":
            sc = [score_prediction(rng.random(CELLS * CELLS), truth) for _ in range(n_random)]
            res[name] = (float(np.nanmean([s[0] for s in sc])), float(np.nanmean([s[1] for s in sc])))
        else:
            res[name] = score_prediction(p, truth)
    return res


def temporal_split(df, grid, train_frac=0.6):
    g = df[df["grid"] == grid]
    n_days = g["day"].nunique()
    n_train = max(1, round(n_days * train_frac))
    lat = Lattice(g["x"], g["y"])
    tr, te = g[g["day"] < n_train], g[g["day"] >= n_train]
    rng = np.random.default_rng(SEED)
    groups = [d[["x", "y"]].to_numpy() for _, d in tr.groupby("day")]
    h = select_bandwidth(lat, groups)
    res = _eval_one(lat, tr[["x", "y"]].to_numpy(), te[["x", "y"]].to_numpy(), h, rng)
    boot = _bootstrap_gap(lat, tr, te, h, rng)
    return {"grid": grid, "train_days": int(n_train), "test_days": int(n_days - n_train),
            "individuals": int(g["id"].nunique()), "h_frac": round(h / lat.side, 3),
            "results": res, "kde_minus_freq_top_k": boot}


def _bootstrap_gap(lat, tr, te, h, rng):
    """개체를 다시 뽑아(부트스트랩) KDE와 방문 빈도의 상위 k칸 적중률 차이의 95% 구간을 구한다 (h 고정)."""
    ids = sorted(set(tr["id"]) & set(te["id"]))
    nc = CELLS * CELLS
    kde_i, frq_i, tru_i = {}, {}, {}
    for i in ids:
        a, b = tr[tr["id"] == i][["x", "y"]].to_numpy(), te[te["id"] == i][["x", "y"]].to_numpy()
        kde_i[i] = lat.lattice_to_cell(kde_lattice(lat, a, h))
        frq_i[i] = np.bincount(lat.cell_index(a[:, 0], a[:, 1]), minlength=nc).astype(float)
        tru_i[i] = np.bincount(lat.cell_index(b[:, 0], b[:, 1]), minlength=nc).astype(float)
    diffs = []
    for _ in range(N_BOOT):
        pick = rng.choice(ids, size=len(ids), replace=True)
        k = sum(kde_i[i] for i in pick)
        f = sum(frq_i[i] for i in pick)
        t = sum(tru_i[i] for i in pick)
        a, b = score_prediction(k, t)[0], score_prediction(f, t)[0]
        if not (np.isnan(a) or np.isnan(b)):
            diffs.append(a - b)
    if not diffs:
        return None
    return {"mean": float(np.mean(diffs)), "lo": float(np.percentile(diffs, 2.5)), "hi": float(np.percentile(diffs, 97.5))}


def individual_split(df, grid, folds=5):
    g = df[df["grid"] == grid]
    lat = Lattice(g["x"], g["y"])
    ids = np.array(sorted(g["id"].unique()))
    rng = np.random.default_rng(SEED)
    rng.shuffle(ids)
    parts = np.array_split(ids, folds)
    acc = {}
    for fold in parts:
        tr, te = g[~g["id"].isin(fold)], g[g["id"].isin(fold)]
        groups = [d[["x", "y"]].to_numpy() for _, d in tr.groupby("id")]
        h = select_bandwidth(lat, groups)
        res = _eval_one(lat, tr[["x", "y"]].to_numpy(), te[["x", "y"]].to_numpy(), h, rng)
        for k, v in res.items():
            acc.setdefault(k, []).append(v)
    return {"grid": grid, "folds": folds, "individuals": int(len(ids)),
            "results": {k: (float(np.nanmean([a for a, _ in v])), float(np.nanmean([b for _, b in v]))) for k, v in acc.items()}}


def run(data_dir):
    df = load_fixes(f"{data_dir}/{COORD_FILE}")
    df["day"] = day_index(df)
    out = {"rows": int(len(df)), "shifted_rows_fixed": int(df.attrs["shifted_rows_fixed"]),
           "cells": CELLS, "top_k": TOP_K, "temporal": [], "individual": []}
    for grid in sorted(df["grid"].unique()):
        out["temporal"].append(temporal_split(df, grid))
        out["individual"].append(individual_split(df, grid))
    return out


def format_report(out):
    lines = [f"위치 {out['rows']:,}개 (열 밀림 보정 {out['shifted_rows_fixed']:,}행), {out['cells']}x{out['cells']}칸, 상위 {out['top_k']}칸 적중률 / 순위상관"]
    for title, key in (("시간 분할 (앞쪽 날 학습 -> 뒤쪽 날 평가)", "temporal"), ("개체 분할 (처음 보는 개체 5겹)", "individual")):
        lines.append(f"\n[{title}]")
        for r in out[key]:
            lines.append(f"  {r['grid']}  개체 {r['individuals']}" + (f", 학습 {r['train_days']}일/평가 {r['test_days']}일, h={r['h_frac']}" if key == "temporal" else ""))
            for name, (top, rho) in r["results"].items():
                lines.append(f"    {name:8s} 적중률 {top:.2f}  순위상관 {rho:+.2f}")
            gap = r.get("kde_minus_freq_top_k")
            if gap:
                lines.append(f"    KDE-방문빈도 적중률 차이 {gap['mean']:+.2f} (95% 구간 {gap['lo']:+.2f} ~ {gap['hi']:+.2f})")
    return "\n".join(lines)


if __name__ == "__main__":
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "data/external"
    dest = sys.argv[2] if len(sys.argv) > 2 else "data/processed/movement_eval_results.json"
    result = run(data_dir)
    print(format_report(result))
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n저장: {dest}")
