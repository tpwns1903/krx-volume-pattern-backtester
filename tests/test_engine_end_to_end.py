"""
test_engine_end_to_end.py — 다운로드를 제외한 전체 파이프라인 검증

합성 전종목 OHLCV → PatternEngine.run_with_sweep → export_excel / export_all_charts
run_pattern.py 가 수행하는 호출 순서를 그대로 재현한다 (pykrx 불필요).
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from src.chart_export import export_all_charts
from src.excel_export import export_excel
from src.pattern_engine import PatternEngine
from src.patterns.volume_pattern import VolumeInflowDeclinePattern


def _make_ticker_df(ticker: str, name: str, seed: int, n_days: int = 300) -> pd.DataFrame:
    """단일 종목 합성 OHLCV. 일부 종목에 패턴을 의도적으로 심는다."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-01", periods=n_days)
    close = 10000 + np.cumsum(rng.normal(0, 120, n_days))
    close = np.maximum(close, 500).round(0)
    openp = (close + rng.normal(0, 80, n_days)).round(0)
    high = np.maximum(openp, close) + np.abs(rng.normal(0, 60, n_days))
    low = np.minimum(openp, close) - np.abs(rng.normal(0, 60, n_days))
    vol = rng.integers(50_000, 150_000, n_days).astype(float)

    # 30일 간격으로 "유입 2일 → 감소 3일" 패턴 삽입
    for start in range(60, n_days - 6, 30):
        ma = vol[start - 20:start].mean()
        vol[start] = ma * 2.6            # Day1
        vol[start + 1] = ma * 3.4        # Day2 (증가)
        vol[start + 2] = ma * 2.5        # Day3 감소
        vol[start + 3] = ma * 1.8        # Day4 감소
        vol[start + 4] = ma * 1.2        # Day5 감소

    return pd.DataFrame({
        "ticker": ticker,
        "name": name,
        "date": dates,
        "open": openp,
        "high": high.round(0),
        "low": low.round(0),
        "close": close,
        "volume": vol,
    })


def _make_full_ohlcv(n_tickers: int = 12) -> tuple[pd.DataFrame, dict]:
    frames = []
    universe = {}
    for i in range(n_tickers):
        tk = f"{i + 1:06d}"
        nm = f"테스트{i + 1}"
        universe[tk] = nm
        frames.append(_make_ticker_df(tk, nm, seed=1000 + i))
    return pd.concat(frames, ignore_index=True), universe


def test_full_pipeline_without_download():
    ohlcv, universe = _make_full_ohlcv()
    pattern = VolumeInflowDeclinePattern()

    engine = PatternEngine(forward_days=5)
    sweep = engine.run_with_sweep(pattern=pattern, ohlcv_data=ohlcv, universe=universe)

    total = sum(len(df) for df in sweep.values() if not df.empty)
    print(f"  감지된 총 신호: {total}")
    assert total > 0, "합성 데이터에서 신호가 하나도 안 잡힘"

    # 배수 스윕 단조성: 배수 클수록 신호 수 <= 작은 배수
    counts = {m: len(df) for m, df in sorted(sweep.items())}
    print(f"  배수별 신호 수: {counts}")
    ms = sorted(counts)
    for a, b in zip(ms, ms[1:]):
        assert counts[a] >= counts[b], f"단조성 위배: {a}x({counts[a]}) < {b}x({counts[b]})"

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        xlsx = export_excel(sweep, pattern.name, forward_days=5, output_dir=tmp)
        charts = export_all_charts(sweep, pattern.name, forward_days=5, out_dir=tmp)
        assert xlsx and Path(xlsx).exists()
        assert len(charts) == 3 and all(Path(c).exists() for c in charts)

        # last_run 갱신도 확인 (임시 patterns 디렉토리)
        pdir = tmp / "patterns"
        pattern.save(pdir)
        pattern.update_last_run({"total_signals": total}, pdir)
        import json
        meta = json.loads((pdir / f"{pattern.name}.json").read_text(encoding="utf-8"))
        assert meta["last_run"] is not None
        assert meta["last_result_summary"]["total_signals"] == total

    print("PASS")


if __name__ == "__main__":
    print("=" * 50)
    print("엔진 → 엑셀/차트 전체 파이프라인 테스트")
    print("=" * 50)
    try:
        test_full_pipeline_without_download()
        print("\nResult: 1 passed, 0 failed")
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        print("\nResult: 0 passed, 1 failed")
        sys.exit(1)
