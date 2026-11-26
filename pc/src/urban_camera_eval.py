"""도시 카메라트랩 데이터(Dryad 73n5tb3bz, 독일 프라이부르크, 24지점)로 지점별 쥐 활동의 지속성을 검증한다.

예측 대상은 '다음 시즌에 쥐가 많이 찍히는 지점'이다. 포획 정보는 없다.
검증 1 (롤링 시간 분할): 앞쪽 시즌들로 학습 -> 바로 다음 시즌 평가를 시즌마다 반복한다.
        모델: 방문 빈도 / 직전 시즌 / 불투과면만 / GBM / RF / 무작위
검증 2 (관측 기간별 순위 안정성): N일만 관측했을 때의 지점 순위가 나머지 기간의 순위와 얼마나 맞는가.

한계: 시즌별 카메라 가동일이 없다. 그 시즌에 기록이 하나라도 있는 지점을 '가동 중'으로 간주한다.
쥐 기록은 30분 이상 간격으로 끊은 '방문(bout)'으로 센다 (연속 촬영 중복을 줄이기 위함).

실행: python -m src.urban_camera_eval [xlsx 경로] [결과 JSON 경로]
"""
import json
import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor

XLSX = "data/external/NocturnalNeigborsData.xlsx"
BOUT_GAP_MIN = 30
MIN_HISTORY = 3  # 롤링 평가의 최소 학습 시즌 수 (ML 학습 표에는 이 이후 시즌부터 쓴다)
FIRST_ORIGIN = 5
N_BOOT = 300
SEED = 20260126
WINDOWS = (7, 14, 30, 60, 90, 180)
RF_TREES = 200
METHODS = ("방문 빈도", "직전 시즌", "불투과면만", "GBM", "RF")


def load(path):
    cols = ["ID", "Species", "Timestamp", "SeasonYear", "avg_impervious", "MaxDays"]
    return prepare(pd.read_excel(path, usecols=cols))


def prepare(df):
    """기록 표를 받아 쥐 방문(bout) 표와 지점·시즌 정보를 만든다."""
    df = df.dropna(subset=["Timestamp", "ID", "SeasonYear"]).copy()
    order = df.groupby("SeasonYear")["Timestamp"].median().sort_values().index.tolist()
    cams = sorted(df["ID"].unique())
    cam_info = df.groupby("ID").agg(imp=("avg_impervious", "first"), days=("MaxDays", "first")).reindex(cams)
    rat = df[df["Species"] == "Rat"].sort_values(["ID", "Timestamp"]).copy()
    gap = rat.groupby("ID")["Timestamp"].diff().dt.total_seconds().div(60)
    rat["bout"] = (gap.isna() | (gap > BOUT_GAP_MIN)).astype(int)
    pos = {c: i for i, c in enumerate(cams)}
    bpos = {b: i for i, b in enumerate(order)}
    bouts = np.zeros((len(cams), len(order)))
    for c, b, v in zip(rat["ID"], rat["SeasonYear"], rat["bout"]):
        bouts[pos[c], bpos[b]] += v
    active = np.zeros_like(bouts, dtype=bool)
    for c, b in zip(df["ID"], df["SeasonYear"]):
        active[pos[c], bpos[b]] = True
    return {"df": df, "rat": rat, "cams": cams, "blocks": order, "bouts": bouts, "active": active, "cam_info": cam_info}


def _metrics(pred, truth, k, rng):
    """상위 k 적중률, 순위상관, 상위 k 커버리지. 예측 동점은 무작위로 깬다."""
    if truth.sum() == 0 or len(truth) < 5:
        return (np.nan, np.nan, np.nan)
    p = pred + rng.random(len(pred)) * 1e-9
    top = np.argsort(-p)[:k]
    best = np.argsort(-(truth + rng.random(len(truth)) * 1e-9))[:k]
    rho = pd.Series(p).rank().corr(pd.Series(truth).rank())
    return (len(set(top) & set(best)) / k, float(rho), float(truth[top].sum() / truth.sum()))


def _k(n):
    return max(3, round(0.2 * n))


def _features(P, s, c):
    """지점 c의 s 시즌 이전 기록에서 만든 특징."""
    b, a = P["bouts"][c, :s], P["active"][c, :s]
    n_act = max(int(a.sum()), 1)
    imp = P["cam_info"]["imp"].iloc[c]
    return [b.sum() / n_act, b[-1] if s >= 1 else 0, b[-2:].sum(), float((b[a] > 0).mean()) if a.any() else 0.0,
            int(a.sum()), imp, P["cam_info"]["days"].iloc[c]]


def _predictions(P, s, rng):
    n_cam = len(P["cams"])
    feat = np.array([_features(P, s, c) for c in range(n_cam)], dtype=float)
    out = {"방문 빈도": feat[:, 0], "직전 시즌": feat[:, 1]}
    imp = feat[:, 5]
    ok = ~np.isnan(imp)
    sign = np.sign(pd.Series(imp[ok]).corr(pd.Series(feat[ok, 0]), method="spearman")) if ok.sum() > 3 else 0
    out["불투과면만"] = np.nan_to_num(imp) * (sign or 1.0)
    X, y = [], []
    for t in range(MIN_HISTORY, s):
        for c in range(n_cam):
            if P["active"][c, t]:
                X.append(_features(P, t, c))
                y.append(np.log1p(P["bouts"][c, t]))
    if len(X) >= 20:
        X, y = np.nan_to_num(np.array(X, dtype=float), nan=-1), np.array(y)
        Xte = np.nan_to_num(feat, nan=-1)
        gbm = HistGradientBoostingRegressor(max_depth=2, learning_rate=0.05, max_iter=100, min_samples_leaf=10, random_state=SEED)
        rf = RandomForestRegressor(n_estimators=RF_TREES, min_samples_leaf=5, random_state=SEED, n_jobs=-1)
        out["GBM"], out["RF"] = gbm.fit(X, y).predict(Xte), rf.fit(X, y).predict(Xte)
    else:
        out["GBM"] = out["RF"] = np.full(n_cam, np.nan)
    return out


def rolling_eval(P):
    rng = np.random.default_rng(SEED)
    rows, store = [], []
    for s in range(FIRST_ORIGIN, len(P["blocks"])):
        act = P["active"][:, s]
        truth = P["bouts"][:, s]
        if act.sum() < 8 or truth[act].sum() == 0:
            continue
        pred = _predictions(P, s, rng)
        k = _k(int(act.sum()))
        store.append((s, act, truth, pred, k))
        row = {"block": P["blocks"][s], "cameras": int(act.sum()), "k": k, "test_bouts": int(truth[act].sum())}
        for m in METHODS:
            row[m] = _metrics(pred[m][act], truth[act], k, rng) if not np.isnan(pred[m]).all() else (np.nan,) * 3
        rnd = np.array([_metrics(rng.random(int(act.sum())), truth[act], k, rng) for _ in range(200)])
        row["무작위"] = tuple(np.nanmean(rnd, axis=0))
        rows.append(row)
    mean = {m: tuple(float(np.nanmean([r[m][i] for r in rows])) for i in range(3)) for m in METHODS + ("무작위",)}
    gaps = {}
    for m in METHODS:
        if m == "방문 빈도":
            continue
        d_top, d_cov = [], []
        for _ in range(N_BOOT):
            pick = rng.integers(0, len(P["cams"]), len(P["cams"]))
            a_top, a_cov, b_top, b_cov = [], [], [], []
            for s, act, truth, pred, k in store:
                if np.isnan(pred[m]).all():
                    continue
                keep = act[pick]
                if keep.sum() < 8 or truth[pick][keep].sum() == 0:
                    continue
                kk, t = _k(int(keep.sum())), truth[pick][keep]
                ra, rb = _metrics(pred[m][pick][keep], t, kk, rng), _metrics(pred["방문 빈도"][pick][keep], t, kk, rng)
                a_top.append(ra[0]); a_cov.append(ra[2]); b_top.append(rb[0]); b_cov.append(rb[2])
            if a_top:
                d_top.append(np.nanmean(a_top) - np.nanmean(b_top))
                d_cov.append(np.nanmean(a_cov) - np.nanmean(b_cov))
        ci = lambda v: {"mean": float(np.mean(v)), "lo": float(np.percentile(v, 2.5)), "hi": float(np.percentile(v, 97.5))} if v else None
        gaps[m] = {"적중률": ci(d_top), "커버리지": ci(d_cov)}
    return {"origins": rows, "mean": mean, "vs_방문빈도": gaps}


def stability_curve(P, windows=WINDOWS, step_days=30):
    """N일 관측 순위와 그 밖의 기간 순위의 Spearman (윈도 시작일을 30일씩 옮겨 가며)."""
    rat, df = P["rat"], P["df"]
    t0, t1 = df["Timestamp"].min().normalize(), df["Timestamp"].max().normalize()
    cams = P["cams"]
    out = []
    for n in windows:
        rhos, hits, ncams = [], [], []
        start = t0
        while start + pd.Timedelta(days=n) <= t1:
            end = start + pd.Timedelta(days=n)
            seen = set(df.loc[(df["Timestamp"] >= start) & (df["Timestamp"] < end), "ID"])
            inside = (rat["Timestamp"] >= start) & (rat["Timestamp"] < end)
            a = rat[inside].groupby("ID")["bout"].sum().reindex(cams).fillna(0)
            b = rat[~inside].groupby("ID")["bout"].sum().reindex(cams).fillna(0)
            idx = [c for c in cams if c in seen]
            if len(idx) >= 10 and a[idx].sum() > 0:
                rhos.append(a[idx].rank().corr(b[idx].rank()))
                k = _k(len(idx))
                hits.append(len(set(a[idx].sort_values(ascending=False, kind="stable").index[:k]) &
                                set(b[idx].sort_values(ascending=False, kind="stable").index[:k])) / k)
                ncams.append(len(idx))
            start += pd.Timedelta(days=step_days)
        if rhos:
            out.append({"days": n, "windows": len(rhos), "rho_median": float(np.nanmedian(rhos)),
                        "rho_q25": float(np.nanpercentile(rhos, 25)), "rho_q75": float(np.nanpercentile(rhos, 75)),
                        "top_hit_mean": float(np.nanmean(hits)), "cameras_mean": float(np.mean(ncams))})
    return out


def run(path=XLSX):
    P = load(path)
    return {"records": int(len(P["df"])), "cameras": len(P["cams"]), "rat_records": int(len(P["rat"])),
            "rat_bouts": int(P["rat"]["bout"].sum()), "blocks": P["blocks"],
            "rolling": rolling_eval(P), "stability": stability_curve(P)}


def format_report(out):
    L = [f"기록 {out['records']:,}건, 카메라 {out['cameras']}곳, 쥐 기록 {out['rat_records']:,}건 -> 방문 {out['rat_bouts']:,}회",
         f"시즌 순서: {', '.join(out['blocks'])}", "\n[롤링 시간 분할] 상위 k(가동 지점의 20%) 적중률 / 순위상관 / 커버리지"]
    for r in out["rolling"]["origins"]:
        L.append(f"  평가 {r['block']}  지점 {r['cameras']}, k={r['k']}, 방문 {r['test_bouts']}")
    L.append("  평균:")
    for m, (a, b, c) in out["rolling"]["mean"].items():
        L.append(f"    {m:8s} {a:.2f}  {b:+.2f}  {c:.2f}")
    for m, v in out["rolling"]["vs_방문빈도"].items():
        a, c = v["적중률"], v["커버리지"]
        if a and c:
            L.append(f"    {m} - 방문 빈도: 적중률 {a['mean']:+.2f} ({a['lo']:+.2f}~{a['hi']:+.2f}), 커버리지 {c['mean']:+.3f} ({c['lo']:+.3f}~{c['hi']:+.3f})")
    L.append("\n[관측 기간별 순위 안정성] N일 관측 순위 vs 나머지 기간 순위")
    for s in out["stability"]:
        L.append(f"  {s['days']:>3d}일  Spearman 중앙값 {s['rho_median']:+.2f} (사분위 {s['rho_q25']:+.2f}~{s['rho_q75']:+.2f})  "
                 f"상위 적중 {s['top_hit_mean']:.2f}  창 {s['windows']}개, 평균 {s['cameras_mean']:.0f}지점")
    return "\n".join(L)


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else XLSX
    dest = sys.argv[2] if len(sys.argv) > 2 else "data/processed/urban_camera_eval_results.json"
    result = run(src)
    print(format_report(result))
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n저장: {dest}")
