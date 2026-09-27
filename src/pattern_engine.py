"""
pattern_engine.py — 재사용 가능한 패턴 검색 엔진 (핵심)

새로운 패턴을 추가할 때는 BasePattern을 상속한 클래스를 만들고
PatternEngine.run()에 전달하면 됩니다.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import pandas as pd
from tqdm import tqdm

from src.backtest import calc_forward_returns
from src.patterns.base_pattern import BasePattern

logger = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).parent.parent / "data" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


class PatternEngine:
    """
    패턴 검색 & 백테스팅 통합 엔진.

    사용 예시:
        engine = PatternEngine()
        pattern = VolumeInflowDeclinePattern()
        results = engine.run_with_sweep(pattern, ohlcv_data, universe)
    """

    def __init__(self, forward_days: int = 5, min_trading_value: float = 1_000_000_000):
        """
        Parameters
        ----------
        forward_days : int
            Forward test 기간
        min_trading_value : float
            신호일 기준 최소 거래대금(원) 필터. 미만인 신호는 제외.
            거래대금 = 신호일 종가 × 거래량 (KRX 거래대금 API가 현재 불안정하여 근사).
            기본값 10억원.
        """
        self.forward_days = forward_days
        self.min_trading_value = min_trading_value

    # ------------------------------------------------------------------
    # 단일 multiplier 실행
    # ------------------------------------------------------------------

    def run(
        self,
        pattern: BasePattern,
        ohlcv_data: pd.DataFrame,
        universe: dict[str, str],
        multiplier: float = 2.0,
        show_progress: bool = True,
        ticker_market: dict[str, str] = None,
        index_data: dict[str, pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """
        단일 multiplier로 패턴 검색 + Forward test 실행.

        Parameters
        ----------
        pattern : BasePattern
            패턴 인스턴스
        ohlcv_data : pd.DataFrame
            전종목 OHLCV 캐시 (columns: ticker, name, date, open, high, low, close, volume)
        universe : dict[str, str]
            {ticker: name} — 검색 대상 종목
        multiplier : float
            거래량 배수 파라미터
        show_progress : bool
            tqdm 진행 표시 여부
        ticker_market : dict[str, str], optional
            {ticker: "KOSPI"|"KOSDAQ"} — 초과수익 계산 시 어떤 지수와 비교할지 결정
        index_data : dict[str, pd.DataFrame], optional
            {"KOSPI": df, "KOSDAQ": df} — 지수 일별 시세 (date, close, chg_pct)

        Returns
        -------
        pd.DataFrame
            신호 건별 결과 DataFrame (최소 거래대금 필터 적용 후)
        """
        tickers = list(universe.keys())
        ticker_market = ticker_market or {}
        index_data = index_data or {}
        all_results = []
        excluded_by_liquidity = 0

        iter_obj = tqdm(tickers, desc=f"패턴 검색 (x{multiplier})", unit="종목") if show_progress else tickers

        for ticker in iter_obj:
            df_ticker = ohlcv_data[ohlcv_data["ticker"] == ticker].copy()
            if df_ticker.empty:
                continue

            df_ticker = df_ticker.sort_values("date").reset_index(drop=True)
            name = universe.get(ticker, "")
            market = ticker_market.get(ticker)
            index_df = index_data.get(market) if market else None

            # 패턴 감지
            try:
                signal_dates = pattern.detect(df_ticker, multiplier=multiplier)
            except Exception as e:
                logger.warning(f"[{ticker}] 패턴 감지 오류: {e}")
                continue

            # Forward test
            for sig_date in signal_dates:
                sig_row = df_ticker[df_ticker["date"] == pd.Timestamp(sig_date)]
                sig_volume = sig_row["volume"].iloc[0] if not sig_row.empty else None
                sig_close = sig_row["close"].iloc[0] if not sig_row.empty else None

                # 최소 거래대금 필터 (신호일 기준, 종가 × 거래량 근사)
                trading_value = (
                    float(sig_close) * float(sig_volume)
                    if sig_close is not None and sig_volume is not None
                    and pd.notna(sig_close) and pd.notna(sig_volume)
                    else None
                )
                if trading_value is None or trading_value < self.min_trading_value:
                    excluded_by_liquidity += 1
                    continue

                fwd = calc_forward_returns(df_ticker, sig_date, self.forward_days, index_df=index_df)
                row = {
                    "ticker": ticker,
                    "name": name,
                    "market": market,
                    "multiplier": multiplier,
                    "trading_value_signal": round(trading_value, 0),
                    **fwd,
                }
                all_results.append(row)

        if excluded_by_liquidity:
            logger.info(
                f"[x{multiplier}] 최소 거래대금({self.min_trading_value:,.0f}원) 미달로 "
                f"{excluded_by_liquidity}건 제외"
            )

        if not all_results:
            return pd.DataFrame()

        return pd.DataFrame(all_results)

    # ------------------------------------------------------------------
    # 파라미터 스윕 (multiplier 리스트 전체)
    # ------------------------------------------------------------------

    def run_with_sweep(
        self,
        pattern: BasePattern,
        ohlcv_data: pd.DataFrame,
        universe: dict[str, str],
        ticker_market: dict[str, str] = None,
        index_data: dict[str, pd.DataFrame] = None,
    ) -> dict[float, pd.DataFrame]:
        """
        패턴 params의 multipliers 목록 전체를 순회하며 실행.

        Returns
        -------
        dict[float, pd.DataFrame]
            {multiplier: results_df}
        """
        multipliers = pattern.params.get("multipliers", [2.0])
        sweep_results = {}

        print(f"\n[SEARCH] 패턴 검색 시작: [{pattern.name}]")
        print(f"   multipliers: {multipliers}")
        print(f"   종목 수: {len(universe)}개")
        print(f"   최소 거래대금 필터: {self.min_trading_value:,.0f}원\n")

        for m in multipliers:
            print(f"[RUN] multiplier = {m}배")
            df_result = self.run(
                pattern=pattern,
                ohlcv_data=ohlcv_data,
                universe=universe,
                multiplier=m,
                show_progress=True,
                ticker_market=ticker_market,
                index_data=index_data,
            )
            sweep_results[m] = df_result
            count = len(df_result)
            print(f"  → 신호 {count}건 감지\n")

        return sweep_results

    # ------------------------------------------------------------------
    # 결과 저장
    # ------------------------------------------------------------------

    def save_results(
        self,
        sweep_results: dict[float, pd.DataFrame],
        pattern_name: str,
    ) -> Path:
        """
        스윕 결과를 CSV로 저장.

        Returns
        -------
        Path
            저장된 파일 경로
        """
        # 전체 합치기
        all_dfs = []
        for m, df in sweep_results.items():
            if not df.empty:
                all_dfs.append(df)

        if not all_dfs:
            print("[WARN]  저장할 결과가 없습니다.")
            return None

        combined = pd.concat(all_dfs, ignore_index=True)
        timestamp = datetime.today().strftime("%Y%m%d_%H%M")
        fname = RESULTS_DIR / f"{pattern_name}_{timestamp}.csv"
        combined.to_csv(fname, index=False, encoding="utf-8-sig")
        print(f"[SAVE] 결과 저장: {fname}")
        return fname
