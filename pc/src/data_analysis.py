"""EDA용 분석/시각화 함수.

모든 차트에는 데이터 출처 문구(SOURCE_NOTE)를 넣는다. 이 프로젝트의 포획 수치는 가상 데이터이므로
차트만 따로 캡처해도 실제 실적으로 오해되지 않게 하기 위해서다.
"""
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from matplotlib import font_manager
from matplotlib import pyplot as plt
from matplotlib.patches import Patch
from scipy import stats

# --- 색상 토큰 (데이터 시각화 가이드의 기본 팔레트, 라이트 모드)
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e6e5e1"
BLUE = "#2a78d6"          # 크기(magnitude) 단일 색
NEUTRAL = "#c9c8c3"       # 데이터 부족 막대 (빗금 + 라벨 병행, 색만으로 구분하지 않음)

SOURCE_NOTE = "가상(시뮬레이션) 데이터 기준 · 포획 수치는 실제 포획 실적이 아님"
NIGHT_HOURS = {22, 23, 0, 1, 2, 3, 4, 5}

_FONT_CANDIDATES = [
    "/mnt/c/Windows/Fonts/malgun.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
]


def setup_style():
    """한글 폰트와 공통 스타일 설정."""
    family = "DejaVu Sans"
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            font_manager.fontManager.addfont(path)
            family = font_manager.FontProperties(fname=path).get_name()
            break
    matplotlib.rcParams.update({
        "font.family": family, "axes.unicode_minus": False,
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": GRID, "axes.labelcolor": INK_2, "xtick.color": INK_2, "ytick.color": INK_2,
        "text.color": INK, "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
        "figure.dpi": 110, "axes.titleweight": "bold", "axes.titlesize": 12, "axes.titlelocation": "left",
    })
    return family


def _finish(fig, title, subtitle=None):
    """제목/부제목/출처 문구 배치. 인치 단위로 계산해 그림 크기와 무관하게 겹치지 않게 한다."""
    h = fig.get_figheight()
    fig.text(0.01, 1 - 0.10 / h, title, ha="left", va="top", fontsize=14, fontweight="bold", color=INK)
    if subtitle:
        fig.text(0.01, 1 - 0.46 / h, subtitle, ha="left", va="top", fontsize=10, color=INK_2)
    fig.text(0.01, 0.1 / h, SOURCE_NOTE, ha="left", va="bottom", fontsize=8.5, color=INK_2)
    top = 1 - (0.85 if subtitle else 0.55) / h
    return (0, 0.45 / h, 1, top)


def _bars(ax, labels, values, insufficient, fmt, counts=None):
    """가로 막대. 데이터 부족은 회색 빗금. 값은 막대 끝에 직접 표기."""
    y = np.arange(len(labels))
    vmax = np.nanmax(values) if len(values) else 1
    for yi, v, ins in zip(y, values, insufficient):
        if np.isnan(v):
            ax.text(0.0, yi, "  계산 불가", va="center", fontsize=9, color=INK_2)
            continue
        ax.barh(yi, v, height=0.55, color=NEUTRAL if ins else BLUE, hatch="///" if ins else None,
                edgecolor=SURFACE, linewidth=0)
        tag = fmt(v) + ("  (데이터 부족)" if ins else "")
        ax.text(v + vmax * 0.02, yi, tag, va="center", fontsize=9, color=INK)
    ax.set_yticks(y, labels)
    ax.set_xlim(0, vmax * 1.45 if vmax else 1)
    ax.grid(axis="y", visible=False)


# ---------------------------------------------------------------- 차트
def plot_location_comparison(agg):
    """위치별 감지 빈도와 감지 대비 가상 포획 전환율 (작은 다중 차트)."""
    agg = agg.sort_values("location_id")
    labels = [f"{r.location_id}  ({int(r.rat_detections)}건)" for r in agg.itertuples()]
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.9), sharey=True)
    _bars(axes[0], labels, agg["detection_rate"].to_numpy(), agg["is_insufficient"], lambda v: f"{v:.3f}")
    axes[0].set_title("작동 시간당 쥐 감지 빈도")
    axes[0].set_xlabel("건 / 작동 시간")
    _bars(axes[1], labels, agg["sim_conversion"].to_numpy(), agg["is_insufficient"], lambda v: f"{v:.1%}")
    axes[1].set_title("감지 대비 가상 포획 전환율")
    axes[1].set_xlabel("가상 포획 / 쥐 감지")
    axes[0].invert_yaxis()  # sharey: 한 번만 뒤집는다
    fig.legend(handles=[Patch(facecolor=NEUTRAL, hatch="///", edgecolor=SURFACE, label="데이터 부족(관측 7일 미만)")],
               loc="lower right", bbox_to_anchor=(0.99, 0.0), frameon=False, fontsize=9)
    rect = _finish(fig, "위치별 감지와 가상 포획 성과 비교", "라벨 괄호 안은 쥐 감지 건수 (표본 크기)")
    fig.tight_layout(rect=rect)
    return fig


def plot_trap_location_conversion(agg_trap_loc):
    """트랩×위치별 전환율. 같은 트랩이 위치를 옮겼을 때/같은 위치의 다른 트랩과 비교해 위치·장치 문제를 가려낸다."""
    d = agg_trap_loc.sort_values(["location_id", "trap_id"])
    labels = [f"{r.location_id} · {r.trap_id}  ({int(r.rat_detections)}건)" for r in d.itertuples()]
    fig, ax = plt.subplots(figsize=(9, 0.5 * len(d) + 1.9))
    _bars(ax, labels, d["sim_conversion"].to_numpy(), d["is_insufficient"], lambda v: f"{v:.1%}")
    ax.set_xlabel("가상 포획 / 쥐 감지")
    ax.set_title("트랩 × 설치 위치별 감지 대비 가상 포획 전환율")
    ax.invert_yaxis()
    rect = _finish(fig, "위치 문제 vs 장치 문제 구분", "같은 위치의 다른 트랩, 같은 트랩의 다른 위치와 비교")
    fig.tight_layout(rect=rect)
    return fig


def hourly_profile(events):
    """시간대(0~23시)별 쥐로 분류된 감지 건수."""
    rat = events[events["classification"] == "rat"]
    hours = rat["detected_at"].str[11:13].astype(int)
    return hours.value_counts().reindex(range(24), fill_value=0).sort_index()


def plot_hourly_profile(events):
    prof = hourly_profile(events)
    fig, ax = plt.subplots(figsize=(10, 3.9))
    ax.bar(prof.index, prof.values, width=0.65, color=BLUE)
    for h in range(24):
        if h in NIGHT_HOURS:
            ax.axvspan(h - 0.5, h + 0.5, color=GRID, alpha=0.45, lw=0, zorder=0)
    peak = prof.idxmax()
    ax.annotate(f"최대 {int(prof.max())}건 ({peak}시)", (peak, prof.max()), xytext=(0, 6),
                textcoords="offset points", ha="center", fontsize=9, color=INK)
    share = prof[list(NIGHT_HOURS)].sum() / prof.sum()
    ax.set_xticks(range(0, 24, 2))
    ax.set_xlabel("시각 (회색 배경 = 야간 22~05시)")
    ax.set_ylabel("쥐 감지 건수")
    ax.set_ylim(0, prof.max() * 1.18)
    ax.set_title(f"시간대별 쥐 감지 건수 · 야간 비중 {share:.0%}")
    rect = _finish(fig, "시간대별 감지 분포")
    fig.tight_layout(rect=rect)
    return fig, share


def env_vs_detection(summary, min_hours=6):
    """온도와 감지 빈도의 관계. 위치 차이를 제거하려고 '위치 평균 대비 감지율 비'를 쓴다."""
    d = summary[(summary["operating_hours"] >= min_hours) & summary["avg_temperature_c"].notna()].copy()
    d["rate"] = d["rat_detections"] / d["operating_hours"]
    d["rate_vs_loc_mean"] = d["rate"] / d.groupby("location_id")["rate"].transform("mean")
    d = d.replace([np.inf, -np.inf], np.nan).dropna(subset=["rate_vs_loc_mean"])
    rho, p = stats.spearmanr(d["avg_temperature_c"], d["rate_vs_loc_mean"])
    return d, rho, p


def plot_env_vs_detection(summary):
    d, rho, p = env_vs_detection(summary)
    fig, ax = plt.subplots(figsize=(8, 4.6))
    ax.scatter(d["avg_temperature_c"], d["rate_vs_loc_mean"], s=28, color=BLUE, alpha=0.55,
               edgecolor=SURFACE, linewidth=0.8)
    ax.axhline(1.0, color=INK_2, lw=1, ls="--")
    ax.text(ax.get_xlim()[0], 1.0, " 위치 평균", va="bottom", ha="left", fontsize=9, color=INK_2)
    ax.set_xlabel("일 평균 온도 (℃)")
    ax.set_ylabel("위치 평균 대비 감지율 (배)")
    span = d["avg_temperature_c"].max() - d["avg_temperature_c"].min()
    ax.set_title(f"온도와 감지 빈도 · Spearman ρ = {rho:.2f} (p = {p:.2f}, n = {len(d)})")
    rect = _finish(fig, "환경 조건과 쥐 감지의 관계",
                   f"일 평균 온도 범위가 {span:.1f}℃뿐이라 관계를 판단하기 어려움 (하루 6시간 이상 작동한 트랩-일 기준)")
    fig.tight_layout(rect=rect)
    return fig, rho, p


# --------------------------------------------------------------- 데이터 품질
def quality_report(summary, events):
    """일 집계/이벤트의 결측·이상 요약 (dict)."""
    env_cols = ["avg_temperature_c", "avg_humidity_pct", "avg_tvoc_ppb", "avg_eco2_ppm"]
    n = len(events)
    return {
        "trap_day_rows": len(summary),
        "zero_operating_rows": int((summary["operating_hours"] == 0).sum()),
        "env_missing_rate": {c: round(float(summary[c].isna().mean()), 3) for c in env_cols},
        "event_count": n,
        "unclassified_rate": round(float(events["classification"].isna().mean()), 3),
        "non_rat_rate_of_classified": round(float((events["classification"] == "non_rat").sum()
                                                  / max(events["classification"].notna().sum(), 1)), 3),
        "duplicate_event_ids": int(events["event_id"].duplicated().sum()),
    }
