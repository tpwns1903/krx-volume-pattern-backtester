"""
report.py — 결과 출력 & 요약 테이블
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.backtest import EXCESS_DAYS

try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False


def _fmt_pct(val) -> str:
    if val is None or pd.isna(val):
        return "N/A"
    return f"{val:+.2f}%"


def print_summary(
    sweep_results: dict[float, pd.DataFrame],
    forward_days: int = 5,
    top_n: int = 20,
):
    """
    스윕 결과 전체 요약 출력.

    Parameters
    ----------
    sweep_results : dict[float, pd.DataFrame]
        {multiplier: results_df}
    forward_days : int
        Forward test 기간
    top_n : int
        상세 신호 목록 상위 N건
    """
    print("\n" + "=" * 70)
    print("[CHART]  백테스팅 결과 요약")
    print("=" * 70)

    # -- 배수별 비교 테이블 --------------------------------------------
    summary_rows = []
    for m, df in sorted(sweep_results.items()):
        if df.empty:
            summary_rows.append({
                "배수": f"{m}x",
                "신호수": 0,
                **{f"D+{n} 평균": "N/A" for n in range(1, forward_days + 1)},
                **{f"D+{n} 승률": "N/A" for n in range(1, forward_days + 1)},
            })
            continue

        row = {"배수": f"{m}x", "신호수": len(df)}
        for n in range(1, forward_days + 1):
            col = f"ret_d{n}"
            if col in df.columns:
                series = df[col].dropna()
                avg = series.mean() if len(series) > 0 else None
                win = (series > 0).mean() * 100 if len(series) > 0 else None
                row[f"D+{n} 평균"] = _fmt_pct(avg)
                row[f"D+{n} 승률"] = f"{win:.1f}%" if win is not None else "N/A"
            else:
                row[f"D+{n} 평균"] = "N/A"
                row[f"D+{n} 승률"] = "N/A"
        summary_rows.append(row)

    if summary_rows:
        print("\n[배수 파라미터별 비교 — 평균 수익률]")
        avg_cols = ["배수", "신호수"] + [f"D+{n} 평균" for n in range(1, forward_days + 1)]
        avg_df = pd.DataFrame(summary_rows)[avg_cols]
        _print_table(avg_df)

        print("\n[배수 파라미터별 비교 — 승률(수익률 > 0)]")
        win_cols = ["배수", "신호수"] + [f"D+{n} 승률" for n in range(1, forward_days + 1)]
        win_df = pd.DataFrame(summary_rows)[win_cols]
        _print_table(win_df)

    # -- 각 배수별 상세 통계 -------------------------------------------
    for m, df in sorted(sweep_results.items()):
        if df.empty:
            print(f"\n[{m}x] 신호 없음")
            continue

        print(f"\n{'-' * 60}")
        print(f"[{m}x] 신호 {len(df)}건 — 수익률 분포")
        print(f"{'-' * 60}")

        dist_rows = []
        for n in range(1, forward_days + 1):
            col = f"ret_d{n}"
            if col not in df.columns:
                continue
            s = df[col].dropna()
            if s.empty:
                continue
            dist_rows.append({
                "Day": f"D+{n}",
                "N": len(s),
                "평균": _fmt_pct(s.mean()),
                "중앙값": _fmt_pct(s.median()),
                "표준편차": f"{s.std():.2f}",
                "최솟값": _fmt_pct(s.min()),
                "최댓값": _fmt_pct(s.max()),
                "승률": f"{(s > 0).mean() * 100:.1f}%",
            })
        if dist_rows:
            _print_table(pd.DataFrame(dist_rows))

        # -- 지수 대비 초과수익 (D+1/D+3/D+5) --
        excess_rows = []
        for n in EXCESS_DAYS:
            col = f"excess_d{n}"
            idx_col = f"idx_ret_d{n}"
            ret_col = f"ret_d{n}"
            if col not in df.columns:
                continue
            s = df[col].dropna()
            if s.empty:
                continue
            excess_rows.append({
                "Day": f"D+{n}",
                "N": len(s),
                "종목 평균": _fmt_pct(df[ret_col].dropna().mean()) if ret_col in df.columns else "N/A",
                "지수 평균": _fmt_pct(df[idx_col].dropna().mean()) if idx_col in df.columns else "N/A",
                "초과수익 평균": _fmt_pct(s.mean()),
                "초과 승률": f"{(s > 0).mean() * 100:.1f}%",
            })
        if excess_rows:
            print(f"\n[{m}x] 지수 대비 초과수익")
            _print_table(pd.DataFrame(excess_rows))

    # -- 최근 신호 상위 목록 ------------------------------------------
    all_dfs = [df for df in sweep_results.values() if not df.empty]
    if all_dfs:
        combined = pd.concat(all_dfs, ignore_index=True)
        if "signal_date" in combined.columns:
            combined["signal_date"] = pd.to_datetime(combined["signal_date"])
            recent = combined.sort_values("signal_date", ascending=False).head(top_n)

            print(f"\n{'-' * 60}")
            print(f"[최근 신호 {top_n}건]")
            print(f"{'-' * 60}")

            display_cols = ["ticker", "name", "market", "multiplier", "signal_date", "trading_value_signal", "entry_price"]
            display_cols = [c for c in display_cols if c in recent.columns]
            headers = {
                "ticker": "코드", "name": "종목명", "market": "시장", "multiplier": "배수",
                "signal_date": "신호일", "trading_value_signal": "신호일 거래대금",
                "entry_price": "매수가(D+1시가)",
            }
            for n in range(1, forward_days + 1):
                if f"ret_d{n}" in recent.columns:
                    display_cols.append(f"ret_d{n}")
                    headers[f"ret_d{n}"] = f"D+{n}(%)"
                if n in EXCESS_DAYS and f"excess_d{n}" in recent.columns:
                    display_cols.append(f"excess_d{n}")
                    headers[f"excess_d{n}"] = f"D+{n} 초과(%)"

            display = recent[display_cols].copy()
            display["signal_date"] = display["signal_date"].dt.strftime("%Y-%m-%d")
            if "trading_value_signal" in display.columns:
                display["trading_value_signal"] = (display["trading_value_signal"] / 1e8).round(1)
                headers["trading_value_signal"] = "신호일 거래대금(억)"
            display.columns = [headers[c] for c in display_cols]
            _print_table(display)

    print("\n" + "=" * 70)


def _print_table(df: pd.DataFrame):
    if HAS_TABULATE:
        print(tabulate(df, headers="keys", tablefmt="simple", showindex=False))
    else:
        print(df.to_string(index=False))
