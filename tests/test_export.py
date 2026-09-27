"""
test_export.py — 엑셀/차트 출력 파이프라인 스모크 테스트

pykrx 없이 합성 sweep_results로 export_excel / export_all_charts를 호출해
파일이 실제로 생성되는지 확인한다.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from src.chart_export import export_all_charts
from src.excel_export import export_excel


def _fake_sweep(multipliers=(1.5, 2.0, 2.5, 3.0), n_per=40, forward_days=5) -> dict:
    """배수별 합성 신호 결과 DataFrame 생성"""
    rng = np.random.default_rng(42)
    sweep = {}
    for m in multipliers:
        rows = []
        for k in range(n_per):
            base = rng.normal(0.2 * m, 2.0)
            row = {
                "ticker": f"{k:06d}",
                "name": f"종목{k}",
                "multiplier": m,
                "signal_date": pd.Timestamp("2025-01-02") + pd.Timedelta(days=k),
                "signal_close": int(rng.integers(3000, 90000)),
            }
            for d in range(1, forward_days + 1):
                row[f"ret_d{d}"] = round(base + rng.normal(0.1 * d, 1.0), 4)
                row[f"cum_ret_d{d}"] = row[f"ret_d{d}"]
                row[f"close_d{d}"] = row["signal_close"]
            rows.append(row)
        sweep[m] = pd.DataFrame(rows)
    return sweep


def test_export_excel_creates_file():
    sweep = _fake_sweep()
    with tempfile.TemporaryDirectory() as tmp:
        out = export_excel(sweep, "테스트패턴", forward_days=5, output_dir=Path(tmp))
        assert out is not None, "엑셀 경로가 None"
        assert Path(out).exists(), f"엑셀 파일 없음: {out}"
        assert Path(out).stat().st_size > 0, "엑셀 파일이 비어 있음"

        # 시트 구성 확인
        import openpyxl
        wb = openpyxl.load_workbook(out)
        assert "요약" in wb.sheetnames
        assert "상세" in wb.sheetnames
    print("PASS")


def test_export_charts_create_files():
    sweep = _fake_sweep()
    with tempfile.TemporaryDirectory() as tmp:
        paths = export_all_charts(sweep, "테스트패턴", forward_days=5, out_dir=Path(tmp))
        assert len(paths) == 3, f"차트 3개가 아님: {len(paths)}"
        for p in paths:
            assert Path(p).exists(), f"차트 파일 없음: {p}"
            assert Path(p).stat().st_size > 0, f"차트 파일이 비어 있음: {p}"
    print("PASS")


def test_export_handles_empty_sweep():
    """신호가 하나도 없어도 예외 없이 처리"""
    empty = {1.5: pd.DataFrame(), 2.0: pd.DataFrame()}
    with tempfile.TemporaryDirectory() as tmp:
        out = export_excel(empty, "빈패턴", forward_days=5, output_dir=Path(tmp))
        assert out is not None and Path(out).exists()
        paths = export_all_charts(empty, "빈패턴", forward_days=5, out_dir=Path(tmp))
        # 히스토그램은 데이터 없으면 None → 막대/히트맵만 생성될 수 있음
        for p in paths:
            assert Path(p).exists()
    print("PASS")


if __name__ == "__main__":
    print("=" * 50)
    print("엑셀/차트 출력 스모크 테스트")
    print("=" * 50)
    tests = [
        test_export_excel_creates_file,
        test_export_charts_create_files,
        test_export_handles_empty_sweep,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            print(f"\n[{t.__name__}]")
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
    sys.exit(1 if failed else 0)
