"""
sample_signals.py — 전체 신호 리스트에서 무작위 표본을 뽑아 눈으로 보기 쉬운 엑셀로 저장

사용법:
  python sample_signals.py                    # data/results 최신 결과 CSV에서 200건 무작위 추출
  python sample_signals.py --csv data/results/거래량_유입후_감소_20260911_1412.csv
  python sample_signals.py --n 100             # 추출 건수 변경
  python sample_signals.py --seed 42           # 재현 가능한(항상 같은) 무작위 추출
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from src.excel_export import HAS_OPENPYXL, _apply_pct_color, _col_hdr, _data_cell, _hdr_style

RESULTS_DIR = Path(__file__).parent / "data" / "results"

# 표시할 등락률 확인 시점 (D+1/D+3/D+5 = 초과수익까지 계산되는 확인일과 동일)
RETURN_DAYS = (1, 3, 5)
NEEDED_COLS = ["ticker", "name", "signal_date", "signal_close"] + [f"ret_d{n}" for n in RETURN_DAYS]


def _latest_signal_csv() -> Path:
    """data/results/*.csv 중 가장 최근 결과 파일 (샘플 파일 자신은 제외)"""
    candidates = [
        p for p in RESULTS_DIR.glob("*.csv") if "샘플" not in p.stem
    ]
    if not candidates:
        raise FileNotFoundError(
            f"{RESULTS_DIR}에 신호 결과 CSV가 없습니다. 먼저 python run_pattern.py 를 실행하세요."
        )
    return max(candidates, key=lambda p: p.stat().st_mtime)


def build_sample(csv_path: Path, n: int, seed: int = None) -> pd.DataFrame:
    """전체 신호 CSV에서 n건을 무작위 추출해 표시용 컬럼만 정리."""
    df = pd.read_csv(csv_path, encoding="utf-8-sig")

    missing = [c for c in NEEDED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"CSV에 필요한 컬럼이 없습니다: {missing}")

    total = len(df)
    # 같은 신호가 배수(multiplier)만 다르게 여러 번 잡힌 경우 종목코드+신호일 기준으로
    # 한 번만 남긴다 (그대로 두면 같은 사건이 눈으로 확인할 200건 중 여러 자리를 차지함).
    unique_events = df[NEEDED_COLS].drop_duplicates(subset=["ticker", "signal_date"])
    n = min(n, len(unique_events))
    sample = unique_events.sample(n=n, random_state=seed).copy()

    # CSV round-trip 과정에서 종목코드(ticker)가 숫자로 인식되며
    # 앞자리 0이 사라지는 경우가 있어 6자리로 복원한다.
    sample["ticker"] = sample["ticker"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    sample["signal_date"] = pd.to_datetime(sample["signal_date"])

    # 눈으로 확인하기 쉽도록 신호일 → 종목코드 순 정렬 + 일련번호 부여
    sample = sample.sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    sample.insert(0, "no", range(1, len(sample) + 1))

    print(
        f"[INFO] 원본 {total:,}행(배수 중복 포함) → 종목코드+신호일 기준 고유 신호 "
        f"{len(unique_events):,}건 중 {n}건 무작위 추출"
    )
    return sample


def export_sample_excel(sample: pd.DataFrame, out_path: Path):
    """샘플을 단일 시트 엑셀로 저장 (기존 결과 엑셀과 동일한 스타일)."""
    if not HAS_OPENPYXL:
        raise RuntimeError("openpyxl이 설치되어 있지 않습니다. pip install openpyxl")

    from openpyxl import Workbook
    from openpyxl.styles import Alignment
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "샘플"

    headers = ["No", "종목코드", "종목명", "신호일", "신호일 종가"] + [f"D+{n} 등락률(%)" for n in RETURN_DAYS]

    _hdr_style(ws, 1, len(headers), f"신호 무작위 샘플 ({len(sample)}건)")
    ws.row_dimensions[1].height = 24

    for col, h in enumerate(headers, 1):
        _col_hdr(ws.cell(row=2, column=col), h)
    ws.row_dimensions[2].height = 20

    for i, row in sample.iterrows():
        r = 3 + i
        alt = i % 2 == 1

        _data_cell(ws.cell(row=r, column=1), int(row["no"]), alt_row=alt)
        _data_cell(ws.cell(row=r, column=2), row["ticker"], alt_row=alt)

        c_name = ws.cell(row=r, column=3)
        _data_cell(c_name, str(row["name"]), alt_row=alt)
        c_name.alignment = Alignment(horizontal="left", vertical="center")

        c_date = ws.cell(row=r, column=4)
        c_date.value = row["signal_date"].to_pydatetime()
        c_date.number_format = "YYYY-MM-DD"
        _data_cell(c_date, None, alt_row=alt)

        close_val = row["signal_close"]
        close_val = int(close_val) if pd.notna(close_val) else None
        _data_cell(ws.cell(row=r, column=5), close_val, fmt="#,##0", alt_row=alt)

        col = 6
        for n in RETURN_DAYS:
            ret_val = row.get(f"ret_d{n}")
            ret_val = round(float(ret_val), 2) if pd.notna(ret_val) else None
            cell = ws.cell(row=r, column=col)
            _data_cell(cell, ret_val, fmt='0.00"%"', alt_row=alt)
            _apply_pct_color(ws, r, col, ret_val)
            col += 1

        ws.row_dimensions[r].height = 17

    for i, w in enumerate([6, 10, 18, 13, 12] + [12] * len(RETURN_DAYS), 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.freeze_panes = "A3"
    max_col = get_column_letter(len(headers))
    ws.auto_filter.ref = f"A2:{max_col}{2 + len(sample)}"

    wb.save(out_path)


def main():
    parser = argparse.ArgumentParser(description="전체 신호 리스트에서 무작위 표본 추출")
    parser.add_argument("--csv", type=str, default=None, help="원본 신호 CSV 경로 (기본: data/results 최신 결과)")
    parser.add_argument("--n", type=int, default=200, help="추출할 건수 (기본 200)")
    parser.add_argument("--seed", type=int, default=None, help="재현 가능한 무작위 추출을 위한 시드값")
    args = parser.parse_args()

    csv_path = Path(args.csv) if args.csv else _latest_signal_csv()
    print(f"[LOAD] 원본: {csv_path}")

    sample = build_sample(csv_path, args.n, args.seed)

    timestamp = datetime.today().strftime("%Y%m%d_%H%M")
    # "거래량_유입후_감소_20260911_1412" -> "거래량_유입후_감소"
    pattern_name = csv_path.stem.rsplit("_", 2)[0]
    out_path = RESULTS_DIR / f"{pattern_name}_샘플{len(sample)}_{timestamp}.xlsx"

    export_sample_excel(sample, out_path)
    print(f"[SAVE] 샘플 저장: {out_path}")


if __name__ == "__main__":
    main()
