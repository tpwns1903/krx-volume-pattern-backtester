"""
backtest.py — Forward test & 수익률 계산

매수 시점: 신호일(D0) 종가가 아니라 다음 거래일(D+1) 시가.
  → 신호일 당일 종가로는 실제로 매수할 수 없으므로(신호는 종가 확정 후 판단),
    현실적인 진입 시점인 D+1 시가를 기준으로 수익률을 계산한다.
  → 확인일(D+1~D+N)의 수익률/누적수익률은 모두 이 진입가(entry_price) 대비로 계산한다.

지수 초과수익: index_df(코스피/코스닥 일별 종가·등락률)가 주어지면
  - idx_chg_signal : 신호일 당일 지수 등락률(%) — 참고용
  - idx_ret_dN (N=1,3,5) : 신호일 종가 대비 D+N 지수 종가 누적등락률(%)
    (지수는 장중 매매 기준가를 별도로 얻기 어려워 신호일 종가를 기준선으로 사용)
  - excess_dN = ret_dN(종목, 진입가 기준) - idx_ret_dN(지수, 신호일 종가 기준)
    → 두 기준일이 하루 어긋나는 근사치이나, 종목 성과가 시장 대비 초과/미달인지
      가늠하는 용도로는 충분하다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd

EXCESS_DAYS = (1, 3, 5)


def _lookup_nearest(series: pd.Series, date) -> Optional[float]:
    """date에 해당하는 값을 찾되, 없으면 그 이전 최근 거래일 값을 사용."""
    ts = pd.Timestamp(date)
    if ts in series.index:
        v = series.loc[ts]
        return float(v) if pd.notna(v) else None
    prior = series.index[series.index <= ts]
    if len(prior) == 0:
        return None
    v = series.loc[prior.max()]
    return float(v) if pd.notna(v) else None


def calc_forward_returns(
    df: pd.DataFrame,
    signal_date: datetime,
    forward_days: int = 5,
    index_df: pd.DataFrame = None,
) -> dict:
    """
    신호일 기준 Day+1 ~ Day+N 수익률(%) 계산. 매수 시점은 D+1 시가.

    Parameters
    ----------
    df : pd.DataFrame
        단일 종목 OHLCV. columns: date(datetime), open, close, ...
        날짜 오름차순 정렬 보장.
    signal_date : datetime
        신호일 (D0)
    forward_days : int
        Forward test 기간 (영업일 기준)
    index_df : pd.DataFrame, optional
        해당 종목 시장(코스피/코스닥)의 지수 일별 시세.
        columns: date(datetime), close, chg_pct(당일 등락률 %)

    Returns
    -------
    dict
        {
          "signal_date", "signal_close",
          "entry_date", "entry_price",   # D+1 시가
          "ret_d1"..."ret_dN", "cum_ret_d1"..."cum_ret_dN", "close_d1"..."close_dN",
          "idx_close_signal", "idx_chg_signal",
          "idx_ret_d1", "idx_ret_d3", "idx_ret_d5",
          "excess_d1", "excess_d3", "excess_d5",
        }
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    sig_mask = df["date"] == pd.Timestamp(signal_date)
    if not sig_mask.any():
        return _empty_returns(signal_date, forward_days)

    sig_idx = sig_mask.idxmax()
    signal_close = df.loc[sig_idx, "close"]

    # 매수 시점 = D+1 시가 (다음 거래일 데이터가 없으면 아직 매수할 수 없음)
    entry_idx = sig_idx + 1
    if entry_idx >= len(df):
        return _empty_returns(signal_date, forward_days, signal_close=signal_close)

    entry_date = df.loc[entry_idx, "date"]
    entry_price = df.loc[entry_idx, "open"]
    if pd.isna(entry_price) or not entry_price:
        return _empty_returns(signal_date, forward_days, signal_close=signal_close)

    result = {
        "signal_date": signal_date,
        "signal_close": signal_close,
        "entry_date": entry_date,
        "entry_price": entry_price,
    }

    # ── 지수 정보 (신호일 종가를 기준선으로 사용) ─────────────────────
    idx_close_series = None
    idx_chg_series = None
    if index_df is not None and not index_df.empty:
        idx = index_df.dropna(subset=["date"]).set_index(pd.to_datetime(index_df["date"]))
        idx_close_series = idx["close"]
        idx_chg_series = idx["chg_pct"] if "chg_pct" in idx.columns else None

    baseline_idx_close = _lookup_nearest(idx_close_series, signal_date) if idx_close_series is not None else None
    result["idx_close_signal"] = baseline_idx_close
    result["idx_chg_signal"] = (
        _lookup_nearest(idx_chg_series, signal_date) if idx_chg_series is not None else None
    )

    for n in range(1, forward_days + 1):
        future_idx = sig_idx + n
        if future_idx < len(df):
            future_close = df.loc[future_idx, "close"]
            future_date = df.loc[future_idx, "date"]
            ret = (future_close - entry_price) / entry_price * 100
            result[f"ret_d{n}"] = round(ret, 4)
            result[f"cum_ret_d{n}"] = round(ret, 4)  # 진입가 고정 기준이므로 개별 = 누적
            result[f"close_d{n}"] = future_close

            if n in EXCESS_DAYS:
                idx_ret = None
                if idx_close_series is not None and baseline_idx_close:
                    idx_close_n = _lookup_nearest(idx_close_series, future_date)
                    if idx_close_n is not None:
                        idx_ret = round((idx_close_n - baseline_idx_close) / baseline_idx_close * 100, 4)
                result[f"idx_ret_d{n}"] = idx_ret
                result[f"excess_d{n}"] = round(ret - idx_ret, 4) if idx_ret is not None else None
        else:
            result[f"ret_d{n}"] = None
            result[f"cum_ret_d{n}"] = None
            result[f"close_d{n}"] = None
            if n in EXCESS_DAYS:
                result[f"idx_ret_d{n}"] = None
                result[f"excess_d{n}"] = None

    return result


def _empty_returns(signal_date: datetime, forward_days: int, signal_close=None) -> dict:
    result = {
        "signal_date": signal_date,
        "signal_close": signal_close,
        "entry_date": None,
        "entry_price": None,
        "idx_close_signal": None,
        "idx_chg_signal": None,
    }
    for n in range(1, forward_days + 1):
        result[f"ret_d{n}"] = None
        result[f"cum_ret_d{n}"] = None
        result[f"close_d{n}"] = None
        if n in EXCESS_DAYS:
            result[f"idx_ret_d{n}"] = None
            result[f"excess_d{n}"] = None
    return result
