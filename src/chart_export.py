"""
chart_export.py - 백테스팅 결과 시각화 차트 PNG 저장

차트 종류:
  1. 수익률 분포 히스토그램 (D+1, D+3, D+5)
  2. 배수 파라미터별 평균수익률 비교 막대그래프
  3. 배수 x 확인일수 조합 히트맵 (평균수익률 / 승률)
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # GUI 없는 환경에서 렌더링

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

try:
    import seaborn as sns
    HAS_SEABORN = True
except ImportError:
    HAS_SEABORN = False

RESULTS_DIR = Path(__file__).parent.parent / "data" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# ── 공통 스타일 ──────────────────────────────────────────────────────
PALETTE = {
    1.5: "#4C72B0",
    2.0: "#55A868",
    2.5: "#C44E52",
    3.0: "#8172B2",
}
FONT_KR = "Malgun Gothic"   # Windows 한글 폰트

plt.rcParams.update({
    "font.family": FONT_KR,
    "axes.unicode_minus": False,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 150,
    "savefig.dpi": 150,
    "savefig.bbox": "tight",
    "savefig.facecolor": "white",
})


def _get_combined(sweep_results: dict) -> pd.DataFrame:
    """sweep_results → 단일 DataFrame"""
    dfs = [df for df in sweep_results.values() if not df.empty]
    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)


# ── 1. 히스토그램 ───────────────────────────────────────────────────

def plot_histogram(
    sweep_results: dict,
    forward_days: int = 5,
    target_days: list = None,
    out_dir: Path = None,
    pattern_name: str = "pattern",
) -> Path:
    """
    D+N별 수익률 분포 히스토그램 (배수별 색상 구분)

    Parameters
    ----------
    target_days : list, optional
        출력할 Day 목록. 기본값: [1, 3, 5] (forward_days < 5이면 조정)
    """
    if target_days is None:
        target_days = [n for n in [1, 3, 5] if n <= forward_days]

    combined = _get_combined(sweep_results)
    if combined.empty:
        print("[WARN] 히스토그램: 데이터 없음")
        return None

    fig, axes = plt.subplots(
        1, len(target_days),
        figsize=(6 * len(target_days), 5),
        sharey=False,
    )
    if len(target_days) == 1:
        axes = [axes]

    multipliers = sorted(sweep_results.keys())

    for ax, n in zip(axes, target_days):
        col = f"ret_d{n}"
        if col not in combined.columns:
            ax.set_title(f"D+{n} (데이터 없음)")
            continue

        all_vals = combined[col].dropna()
        if all_vals.empty:
            continue

        # 배수별 레이어 히스토그램
        bins = np.linspace(all_vals.quantile(0.01), all_vals.quantile(0.99), 40)
        for m in multipliers:
            df_m = sweep_results[m]
            if df_m.empty or col not in df_m.columns:
                continue
            vals = df_m[col].dropna()
            if vals.empty:
                continue
            ax.hist(
                vals, bins=bins, alpha=0.55,
                color=PALETTE.get(m, "#888888"),
                label=f"{m}x (n={len(vals)})",
                edgecolor="white", linewidth=0.4,
            )

        # 0 기준선
        ax.axvline(0, color="black", linewidth=1.2, linestyle="--", alpha=0.7)
        # 전체 평균
        avg = all_vals.mean()
        ax.axvline(avg, color="red", linewidth=1.2, linestyle=":", alpha=0.8,
                   label=f"전체평균 {avg:+.2f}%")

        ax.set_title(f"D+{n} 수익률 분포", fontsize=13, fontweight="bold", pad=10)
        ax.set_xlabel("수익률 (%)", fontsize=10)
        ax.set_ylabel("빈도", fontsize=10)
        ax.legend(fontsize=8, framealpha=0.8)
        ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))
        ax.tick_params(labelsize=9)

    fig.suptitle(f"[{pattern_name}] 수익률 분포 히스토그램",
                 fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()

    out_dir = out_dir or RESULTS_DIR
    timestamp = datetime.today().strftime("%Y%m%d_%H%M")
    fpath = out_dir / f"{pattern_name}_histogram_{timestamp}.png"
    fig.savefig(fpath)
    plt.close(fig)
    print(f"[SAVE] 히스토그램: {fpath}")
    return fpath


# ── 2. 평균수익률 막대그래프 ─────────────────────────────────────────

def plot_avg_return_bar(
    sweep_results: dict,
    forward_days: int = 5,
    out_dir: Path = None,
    pattern_name: str = "pattern",
) -> Path:
    """배수 파라미터별 × Day별 평균수익률 그룹 막대그래프"""
    multipliers = sorted(sweep_results.keys())
    days = list(range(1, forward_days + 1))

    # 데이터 수집
    avg_matrix = {}
    for m in multipliers:
        df = sweep_results[m]
        row = {}
        for n in days:
            col = f"ret_d{n}"
            if not df.empty and col in df.columns:
                s = df[col].dropna()
                row[f"D+{n}"] = s.mean() if len(s) > 0 else 0.0
            else:
                row[f"D+{n}"] = 0.0
        avg_matrix[f"{m}x"] = row

    df_plot = pd.DataFrame(avg_matrix).T  # index=배수, columns=D+1~D+5

    fig, ax = plt.subplots(figsize=(10, 5))

    x = np.arange(len(days))
    width = 0.8 / len(multipliers)
    offsets = np.linspace(-(len(multipliers) - 1) / 2, (len(multipliers) - 1) / 2, len(multipliers))

    for i, (m, offset) in enumerate(zip(multipliers, offsets)):
        label = f"{m}x"
        vals = [df_plot.loc[label, f"D+{n}"] for n in days]
        bars = ax.bar(
            x + offset * width, vals, width * 0.9,
            color=PALETTE.get(m, "#888888"),
            label=label, alpha=0.85, zorder=3,
        )
        # 값 레이블
        for bar, v in zip(bars, vals):
            if abs(v) > 0.01:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + (0.02 if v >= 0 else -0.05),
                    f"{v:+.2f}%",
                    ha="center", va="bottom" if v >= 0 else "top",
                    fontsize=7.5, fontweight="bold",
                    color=PALETTE.get(m, "#888888"),
                )

    ax.axhline(0, color="black", linewidth=0.8, linestyle="-")
    ax.set_xticks(x)
    ax.set_xticklabels([f"D+{n}" for n in days], fontsize=11)
    ax.set_ylabel("평균 수익률 (%)", fontsize=11)
    ax.set_title(f"[{pattern_name}] 배수별 평균 수익률 비교",
                 fontsize=13, fontweight="bold", pad=12)
    ax.legend(title="거래량 배수", fontsize=9, title_fontsize=9)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f%%"))
    ax.grid(axis="y", alpha=0.3, zorder=0)
    ax.tick_params(labelsize=10)

    plt.tight_layout()

    out_dir = out_dir or RESULTS_DIR
    timestamp = datetime.today().strftime("%Y%m%d_%H%M")
    fpath = out_dir / f"{pattern_name}_avg_return_bar_{timestamp}.png"
    fig.savefig(fpath)
    plt.close(fig)
    print(f"[SAVE] 막대그래프: {fpath}")
    return fpath


# ── 3. 히트맵 ────────────────────────────────────────────────────────

def plot_heatmap(
    sweep_results: dict,
    forward_days: int = 5,
    out_dir: Path = None,
    pattern_name: str = "pattern",
) -> Path:
    """배수 × 확인일수 조합 히트맵 (평균수익률 + 승률, 2개 나란히)"""
    multipliers = sorted(sweep_results.keys())
    days = list(range(1, forward_days + 1))

    # 매트릭스 구축
    ret_mat  = pd.DataFrame(index=[f"{m}x" for m in multipliers],
                            columns=[f"D+{n}" for n in days], dtype=float)
    win_mat  = pd.DataFrame(index=[f"{m}x" for m in multipliers],
                            columns=[f"D+{n}" for n in days], dtype=float)
    cnt_mat  = pd.DataFrame(index=[f"{m}x" for m in multipliers],
                            columns=[f"D+{n}" for n in days], dtype=int)

    for m in multipliers:
        df = sweep_results[m]
        for n in days:
            col = f"ret_d{n}"
            if df.empty or col not in df.columns:
                ret_mat.loc[f"{m}x", f"D+{n}"] = np.nan
                win_mat.loc[f"{m}x", f"D+{n}"] = np.nan
                cnt_mat.loc[f"{m}x", f"D+{n}"] = 0
                continue
            s = df[col].dropna()
            ret_mat.loc[f"{m}x", f"D+{n}"] = s.mean() if len(s) > 0 else np.nan
            win_mat.loc[f"{m}x", f"D+{n}"] = (s > 0).mean() * 100 if len(s) > 0 else np.nan
            cnt_mat.loc[f"{m}x", f"D+{n}"] = len(s)

    ret_mat = ret_mat.astype(float)
    win_mat = win_mat.astype(float)
    cnt_mat = cnt_mat.astype(int)

    fig, axes = plt.subplots(1, 2, figsize=(14, max(3, len(multipliers) * 1.2 + 1.5)))

    cmap_ret = "RdYlGn"
    cmap_win = "RdYlGn"

    # ── 평균수익률 히트맵
    ax0 = axes[0]
    if HAS_SEABORN:
        sns.heatmap(
            ret_mat, ax=ax0, annot=True, fmt=".2f",
            cmap=cmap_ret, center=0,
            linewidths=0.5, linecolor="white",
            cbar_kws={"label": "평균수익률 (%)"},
            annot_kws={"size": 11, "weight": "bold"},
        )
    else:
        im = ax0.imshow(ret_mat.values, cmap=cmap_ret, aspect="auto")
        for i in range(len(multipliers)):
            for j in range(len(days)):
                val = ret_mat.iloc[i, j]
                ax0.text(j, i, f"{val:.2f}", ha="center", va="center",
                         fontsize=10, fontweight="bold")
        ax0.set_xticks(range(len(days)))
        ax0.set_xticklabels([f"D+{n}" for n in days])
        ax0.set_yticks(range(len(multipliers)))
        ax0.set_yticklabels([f"{m}x" for m in multipliers])
        plt.colorbar(im, ax=ax0, label="평균수익률 (%)")

    ax0.set_title("평균 수익률 (%)", fontsize=12, fontweight="bold", pad=10)
    ax0.set_xlabel("확인일수", fontsize=10)
    ax0.set_ylabel("거래량 배수", fontsize=10)

    # 샘플수 주석 추가 (셀 오른쪽 아래)
    for i in range(len(multipliers)):
        for j in range(len(days)):
            n_cnt = cnt_mat.iloc[i, j]
            ax0.text(j + 0.45, i + 0.42, f"n={n_cnt}",
                     ha="right", va="bottom", fontsize=6.5, color="gray",
                     transform=ax0.transData)

    # ── 승률 히트맵
    ax1 = axes[1]
    if HAS_SEABORN:
        sns.heatmap(
            win_mat, ax=ax1, annot=True, fmt=".1f",
            cmap=cmap_win, center=50, vmin=30, vmax=70,
            linewidths=0.5, linecolor="white",
            cbar_kws={"label": "승률 (%)"},
            annot_kws={"size": 11, "weight": "bold"},
        )
    else:
        im2 = ax1.imshow(win_mat.values, cmap=cmap_win, aspect="auto", vmin=30, vmax=70)
        for i in range(len(multipliers)):
            for j in range(len(days)):
                val = win_mat.iloc[i, j]
                ax1.text(j, i, f"{val:.1f}", ha="center", va="center",
                         fontsize=10, fontweight="bold")
        ax1.set_xticks(range(len(days)))
        ax1.set_xticklabels([f"D+{n}" for n in days])
        ax1.set_yticks(range(len(multipliers)))
        ax1.set_yticklabels([f"{m}x" for m in multipliers])
        plt.colorbar(im2, ax=ax1, label="승률 (%)")

    ax1.set_title("승률 (%, 수익률 > 0)", fontsize=12, fontweight="bold", pad=10)
    ax1.set_xlabel("확인일수", fontsize=10)
    ax1.set_ylabel("거래량 배수", fontsize=10)

    fig.suptitle(f"[{pattern_name}] 배수 × 확인일수 조합 히트맵",
                 fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()

    out_dir = out_dir or RESULTS_DIR
    timestamp = datetime.today().strftime("%Y%m%d_%H%M")
    fpath = out_dir / f"{pattern_name}_heatmap_{timestamp}.png"
    fig.savefig(fpath)
    plt.close(fig)
    print(f"[SAVE] 히트맵: {fpath}")
    return fpath


# ── 통합 출력 함수 ───────────────────────────────────────────────────

def export_all_charts(
    sweep_results: dict,
    pattern_name: str,
    forward_days: int = 5,
    out_dir: Path = None,
) -> list[Path]:
    """
    모든 차트를 한 번에 저장.

    Returns
    -------
    list[Path]
        저장된 PNG 파일 경로 목록
    """
    out_dir = out_dir or RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    paths = []

    target_days = [n for n in [1, 3, 5] if n <= forward_days]
    p1 = plot_histogram(sweep_results, forward_days, target_days, out_dir, pattern_name)
    if p1:
        paths.append(p1)

    p2 = plot_avg_return_bar(sweep_results, forward_days, out_dir, pattern_name)
    if p2:
        paths.append(p2)

    p3 = plot_heatmap(sweep_results, forward_days, out_dir, pattern_name)
    if p3:
        paths.append(p3)

    return paths
