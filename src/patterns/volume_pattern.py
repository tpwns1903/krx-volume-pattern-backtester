"""
volume_pattern.py — 거래량 유입 후 감소 패턴

패턴 정의:
  Phase 1 (2일 고정):
    Day1: 거래량 > MA20 * multiplier
    Day2: 거래량 > Day1 거래량 (더 증가)

  Phase 2 (1~3일, Day3~Day5):
    Day3~: 거래량 < 전일 거래량 (감소 추세)
    양봉/음봉 무관, 거래량 감소만 조건
    최대 phase2_max_days(기본 3)일까지
    감소 추세가 이어지는 마지막 날 = 신호일

신호일 = Phase2 마지막 날 종가 기준
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd

from .base_pattern import BasePattern


class VolumeInflowDeclinePattern(BasePattern):
    """거래량 유입 후 감소 패턴"""

    name = "거래량_유입후_감소"
    description = (
        "Phase1: 2일간 거래량이 MA20 대비 배수 이상으로 증가 (Day2 > Day1). "
        "Phase2: 이후 거래량 감소 추세 1~3일 지속. "
        "신호일 = Phase2 마지막 날 (최대 Day5)."
    )
    default_params = {
        "ma_window": 20,               # 평균 거래량 계산 기간
        "multipliers": [1.5, 2.0, 2.5, 3.0],  # Day1 거래량 배수 스윕 목록
        "phase1_days": 2,              # Phase1 고정 길이
        "phase2_min_days": 1,          # Phase2 최소 일수
        "phase2_max_days": 3,          # Phase2 최대 일수
        "forward_days": 5,             # Forward test 일수
        "min_volume": 1_000,           # 최소 거래량 필터 (거래량 희소 종목 제외)
    }

    def detect(
        self,
        df: pd.DataFrame,
        multiplier: float = 2.0,
        **kwargs,
    ) -> list[datetime]:
        """
        단일 종목에서 신호일 탐색 (특정 multiplier 기준).

        Parameters
        ----------
        df : pd.DataFrame
            단일 종목 OHLCV. columns: date, open, high, low, close, volume
        multiplier : float
            Day1 거래량 기준 배수 (MA20 대비)

        Returns
        -------
        list[datetime]
            신호일 날짜 목록
        """
        params = {**self.params, **kwargs}
        ma_window = params["ma_window"]
        phase2_min = params["phase2_min_days"]
        phase2_max = params["phase2_max_days"]
        min_vol = params["min_volume"]

        if df.empty or len(df) < ma_window + 5:
            return []

        df = df.copy().reset_index(drop=True)

        # MA20 (rolling, 해당 날 포함 X → shift(1) 후 rolling)
        df["ma_vol"] = df["volume"].shift(1).rolling(window=ma_window).mean()

        signal_dates = []
        i = ma_window  # MA 계산 가능한 첫 인덱스부터

        while i < len(df) - 1:
            # ── Phase 1 체크 ──────────────────────────────────────
            # Day1 조건
            day1_idx = i
            day1_vol = df.loc[day1_idx, "volume"]
            day1_ma = df.loc[day1_idx, "ma_vol"]

            if pd.isna(day1_ma) or day1_ma <= 0:
                i += 1
                continue
            if day1_vol < min_vol:
                i += 1
                continue
            if day1_vol < day1_ma * multiplier:
                i += 1
                continue

            # Day2 조건
            day2_idx = day1_idx + 1
            if day2_idx >= len(df):
                break
            day2_vol = df.loc[day2_idx, "volume"]
            if day2_vol <= day1_vol:
                i += 1
                continue

            # ── Phase 2 체크 ──────────────────────────────────────
            # Day3부터 시작, 거래량이 전일 대비 감소하는 날을 연속으로 탐색
            phase2_count = 0
            last_signal_idx = None
            prev_vol = day2_vol

            for j in range(day2_idx + 1, min(day2_idx + 1 + phase2_max, len(df))):
                cur_vol = df.loc[j, "volume"]
                if cur_vol < prev_vol:
                    phase2_count += 1
                    last_signal_idx = j
                    prev_vol = cur_vol
                else:
                    break  # 감소 추세 끊김

            # Phase2 최소 일수 충족 여부 확인
            if phase2_count >= phase2_min and last_signal_idx is not None:
                signal_date = df.loc[last_signal_idx, "date"]
                if isinstance(signal_date, pd.Timestamp):
                    signal_date = signal_date.to_pydatetime()
                signal_dates.append(signal_date)
                # 신호일 이후부터 다시 탐색 (중복 방지)
                i = last_signal_idx + 1
            else:
                i += 1

        return signal_dates

    def detect_all_multipliers(
        self,
        df: pd.DataFrame,
    ) -> dict[float, list[datetime]]:
        """
        params에 정의된 모든 multiplier에 대해 신호일 탐색.

        Returns
        -------
        dict[float, list[datetime]]
            {multiplier: [signal_dates]}
        """
        results = {}
        for m in self.params["multipliers"]:
            results[m] = self.detect(df, multiplier=m)
        return results
