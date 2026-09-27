"""
test_pattern_logic.py — 패턴 감지 로직 단위 테스트 (pykrx 없이 합성 데이터 사용)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.patterns.volume_pattern import VolumeInflowDeclinePattern
from src.backtest import calc_forward_returns


def make_ohlcv(volumes: list, start: str = "2024-01-01") -> pd.DataFrame:
    """합성 OHLCV DataFrame 생성"""
    n = len(volumes)
    dates = pd.date_range(start=start, periods=n, freq="B")
    df = pd.DataFrame({
        "date": dates,
        "open": [10000] * n,
        "high": [10500] * n,
        "low": [9500] * n,
        "close": [10000] * n,
        "volume": volumes,
    })
    return df


def test_basic_signal_detected():
    """기본 패턴: MA20 대비 2배 유입 후 2일 감소 → 신호 감지"""
    # MA20 기간 + Phase1 2일 + Phase2 2일 = 24일 이상 필요
    # MA20 베이스라인: 1000
    base_vols = [1000] * 25  # 평균 거래량 ~1000
    # Day1: 2100 (MA20*2.0배 이상), Day2: 2500 (Day1보다 증가)
    # Day3: 2000 (감소), Day4: 1500 (감소) → 신호일 = Day4
    vols = base_vols + [2100, 2500, 2000, 1500, 5000]
    df = make_ohlcv(vols)

    pattern = VolumeInflowDeclinePattern(params={"min_volume": 0})
    signals = pattern.detect(df, multiplier=2.0)

    print(f"[test_basic_signal_detected] signals: {signals}")
    assert len(signals) >= 1, "신호가 1개 이상 감지되어야 합니다"
    print("PASS")


def test_no_signal_when_volume_not_enough():
    """거래량이 MA20 * multiplier 미만이면 신호 없음"""
    base_vols = [1000] * 25
    # Day1: 1500 (MA20*1.5 미만, 2.0배 기준 불충족)
    vols = base_vols + [1500, 2000, 1800, 1600]
    df = make_ohlcv(vols)

    pattern = VolumeInflowDeclinePattern(params={"min_volume": 0})
    signals = pattern.detect(df, multiplier=2.0)

    print(f"[test_no_signal_when_volume_not_enough] signals: {signals}")
    assert len(signals) == 0, "No signal expected (volume too low)"
    print("PASS")


def test_no_signal_day2_not_greater():
    """Day2 거래량 <= Day1 이면 신호 없음"""
    base_vols = [1000] * 25
    # Day1: 2500 (2배 이상), Day2: 2400 (감소) → Phase1 조건 미충족
    vols = base_vols + [2500, 2400, 2000, 1500]
    df = make_ohlcv(vols)

    pattern = VolumeInflowDeclinePattern(params={"min_volume": 0})
    signals = pattern.detect(df, multiplier=2.0)

    print(f"[test_no_signal_day2_not_greater] signals: {signals}")
    assert len(signals) == 0, "No signal expected (Day2 < Day1)"
    print("PASS")


def test_phase2_max_days_limit():
    """Phase2가 3일을 초과해도 마지막 3번째 감소일을 신호일로"""
    base_vols = [1000] * 25
    # Day1: 2200, Day2: 3000, Day3~6: 감소
    vols = base_vols + [2200, 3000, 2800, 2500, 2200, 1900]  # 4일 감소지만 최대 3일까지
    df = make_ohlcv(vols)

    pattern = VolumeInflowDeclinePattern(params={"min_volume": 0})
    signals = pattern.detect(df, multiplier=2.0)

    print(f"[test_phase2_max_days_limit] signals: {signals}")
    assert len(signals) >= 1
    print("PASS")


def test_forward_returns():
    """Forward return 계산 정확성 테스트 (매수 시점 = D+1 시가)"""
    closes = [10000, 10100, 10200, 10300, 10400, 10500, 10600]
    dates = pd.date_range("2024-01-02", periods=7, freq="B")
    df = pd.DataFrame({
        "date": dates,
        "open": closes,
        "high": closes,
        "low": closes,
        "close": closes,
        "volume": [1000] * 7,
    })

    signal_date = dates[0].to_pydatetime()  # 신호일(D0) close = 10000
    result = calc_forward_returns(df, signal_date, forward_days=5)

    print(f"[test_forward_returns] result: {result}")
    # 매수가 = D+1 시가 = 10100 (open==close인 합성데이터이므로 close_d1과 동일)
    assert abs(result["entry_price"] - 10100) < 0.01, f"매수가 오류: {result['entry_price']}"
    # D+1: (10100-10100)/10100 * 100 = 0.0% (매수 당일 종가 기준이라 0)
    assert abs(result["ret_d1"] - 0.0) < 0.01, f"D+1 수익률 오류: {result['ret_d1']}"
    # D+5: (10500-10100)/10100 * 100 ≈ 3.9604%
    assert abs(result["ret_d5"] - 3.9604) < 0.01, f"D+5 수익률 오류: {result['ret_d5']}"
    print("PASS")


def test_forward_returns_excess_over_index():
    """지수 데이터가 주어지면 idx_ret_dN / excess_dN이 계산되는지 테스트"""
    closes = [10000, 10100, 10200, 10300, 10400, 10500, 10600]
    dates = pd.date_range("2024-01-02", periods=7, freq="B")
    df = pd.DataFrame({
        "date": dates,
        "open": closes,
        "high": closes,
        "low": closes,
        "close": closes,
        "volume": [1000] * 7,
    })

    # 지수는 신호일(1000) 대비 D+5에 +2% 상승했다고 가정
    idx_closes = [1000, 1005, 1010, 1015, 1018, 1020, 1022]
    index_df = pd.DataFrame({
        "date": dates,
        "close": idx_closes,
        "chg_pct": [0.0] + [
            round((idx_closes[i] - idx_closes[i - 1]) / idx_closes[i - 1] * 100, 4)
            for i in range(1, len(idx_closes))
        ],
    })

    signal_date = dates[0].to_pydatetime()
    result = calc_forward_returns(df, signal_date, forward_days=5, index_df=index_df)

    print(f"[test_forward_returns_excess_over_index] result: {result}")
    # 지수 D+5 누적수익률: (1020-1000)/1000*100 = 2.0%
    assert abs(result["idx_ret_d5"] - 2.0) < 0.01, f"지수 D+5 수익률 오류: {result['idx_ret_d5']}"
    # 초과수익 D+5 = 종목 ret_d5(3.9604) - 지수 idx_ret_d5(2.0)
    assert abs(result["excess_d5"] - (result["ret_d5"] - result["idx_ret_d5"])) < 0.001
    print("PASS")


def test_multiplier_sweep_ordering():
    """배수 클수록 신호 수가 적거나 같아야 함"""
    base_vols = [1000] * 25
    # 여러 신호 조건 생성
    signals_by_mult = {}
    pattern = VolumeInflowDeclinePattern(params={"min_volume": 0})

    for mult in [1.5, 2.0, 2.5, 3.0]:
        # 3.5x inflow pattern
        vols = (base_vols
                + [3500, 4000, 3500, 3000]
                + [1000] * 5
                + [2200, 2500, 2100, 1800])
        df = make_ohlcv(vols)
        sigs = pattern.detect(df, multiplier=mult)
        signals_by_mult[mult] = len(sigs)
        print(f"  mult={mult}: {len(sigs)}")

    # 1.5배 >= 2.0배 >= 2.5배 >= 3.0배
    assert signals_by_mult[1.5] >= signals_by_mult[2.0], "1.5x >= 2.0x signal count violated"
    assert signals_by_mult[2.0] >= signals_by_mult[2.5], "2.0x >= 2.5x signal count violated"
    assert signals_by_mult[2.5] >= signals_by_mult[3.0], "2.5x >= 3.0x signal count violated"
    print("PASS")


if __name__ == "__main__":
    print("=" * 50)
    print("패턴 로직 단위 테스트")
    print("=" * 50)
    tests = [
        test_basic_signal_detected,
        test_no_signal_when_volume_not_enough,
        test_no_signal_day2_not_greater,
        test_phase2_max_days_limit,
        test_forward_returns,
        test_forward_returns_excess_over_index,
        test_multiplier_sweep_ordering,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"FAIL: {t.__name__} - {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR: {t.__name__} - {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    print(f"\nResult: {passed} passed, {failed} failed")
