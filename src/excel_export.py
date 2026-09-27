"""
excel_export.py - 백테스팅 결과를 엑셀 파일로 출력

시트 구성:
  [요약] 배수 x 확인일수 별 평균수익률 / 승률 / 샘플수
  [상세] 전체 신호 리스트 (종목코드, 종목명, 신호일, 종가, D+1~+5 수익률)
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.backtest import EXCESS_DAYS

try:
    import openpyxl
    from openpyxl import Workbook
    from openpyxl.styles import (
        Alignment, Border, Font, GradientFill, PatternFill, Side
    )
    from openpyxl.utils import get_column_letter
    from openpyxl.utils.dataframe import dataframe_to_rows
    from openpyxl.formatting.rule import ColorScaleRule, DataBarRule
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

RESULTS_DIR = Path(__file__).parent.parent / "data" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# ── 색상 상수 ──────────────────────────────────────────────────────────
CLR_HEADER_BG   = "1F4E79"   # 헤더 배경 (진한 파랑)
CLR_HEADER_FG   = "FFFFFF"   # 헤더 글자 (흰색)
CLR_SUBHDR_BG   = "2E75B6"   # 서브헤더
CLR_POS         = "C6EFCE"   # 양수 배경 (연초록)
CLR_POS_FG      = "276221"
CLR_NEG         = "FFC7CE"   # 음수 배경 (연빨강)
CLR_NEG_FG      = "9C0006"
CLR_NEUTRAL     = "FFEB9C"   # 중립 배경 (연노랑)
CLR_ROW_ALT     = "F2F7FF"   # 교번 행 배경


def _hdr_style(ws, row, col_count, title: str, bg=CLR_HEADER_BG, fg=CLR_HEADER_FG):
    """병합 헤더 셀 스타일 적용"""
    cell = ws.cell(row=row, column=1)
    cell.value = title
    cell.font = Font(name="맑은 고딕", bold=True, color=fg, size=12)
    cell.fill = PatternFill("solid", fgColor=bg)
    cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=col_count)
    ws.row_dimensions[row].height = 22


def _col_hdr(cell, text: str, bg=CLR_SUBHDR_BG):
    cell.value = text
    cell.font = Font(name="맑은 고딕", bold=True, color="FFFFFF", size=10)
    cell.fill = PatternFill("solid", fgColor=bg)
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin = Side(style="thin", color="B0C4DE")
    cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)


def _data_cell(cell, value, fmt: str = None, alt_row: bool = False):
    bg = CLR_ROW_ALT if alt_row else "FFFFFF"
    cell.fill = PatternFill("solid", fgColor=bg)
    cell.alignment = Alignment(horizontal="center", vertical="center")
    thin = Side(style="thin", color="D9E1F2")
    cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)
    cell.font = Font(name="맑은 고딕", size=9)
    if value is not None:
        cell.value = value
    if fmt:
        cell.number_format = fmt


def _apply_pct_color(ws, row, col, value):
    """수익률 값에 따라 양수/음수 색상 적용"""
    cell = ws.cell(row=row, column=col)
    if value is None or (isinstance(value, float) and value != value):
        return
    try:
        v = float(value)
        if v > 0:
            cell.fill = PatternFill("solid", fgColor=CLR_POS)
            cell.font = Font(name="맑은 고딕", size=9, color=CLR_POS_FG, bold=True)
        elif v < 0:
            cell.fill = PatternFill("solid", fgColor=CLR_NEG)
            cell.font = Font(name="맑은 고딕", size=9, color=CLR_NEG_FG, bold=True)
    except (TypeError, ValueError):
        pass


# ── 요약 시트 ──────────────────────────────────────────────────────────

def _build_summary_sheet(ws, sweep_results: dict, forward_days: int):
    """요약 시트: 배수 × 확인일수 별 평균수익률 / 승률 / 샘플수"""
    multipliers = sorted(sweep_results.keys())
    days = list(range(1, forward_days + 1))

    # 제목
    _hdr_style(ws, 1, 3 + len(days) * 3, "배수 파라미터별 백테스팅 결과 요약")
    ws.row_dimensions[1].height = 26

    # 컬럼 헤더 — 2행: 그룹명
    ws.cell(row=2, column=1).value = "배수"
    ws.cell(row=2, column=2).value = "신호수"
    ws.cell(row=2, column=3).value = "기간"
    for i, n in enumerate(days):
        col_start = 4 + i * 3
        ws.merge_cells(start_row=2, start_column=col_start, end_row=2, end_column=col_start + 2)
        c = ws.cell(row=2, column=col_start)
        c.value = f"D+{n}"
        c.font = Font(name="맑은 고딕", bold=True, color="FFFFFF", size=10)
        c.fill = PatternFill("solid", fgColor=CLR_SUBHDR_BG)
        c.alignment = Alignment(horizontal="center", vertical="center")

    # 3행: 세부 헤더
    for col, txt in [(1, "배수"), (2, "신호수"), (3, "기간(영업일)")]:
        _col_hdr(ws.cell(row=3, column=col), txt)
    for i, n in enumerate(days):
        base = 4 + i * 3
        _col_hdr(ws.cell(row=3, column=base), "평균수익률")
        _col_hdr(ws.cell(row=3, column=base + 1), "승률")
        _col_hdr(ws.cell(row=3, column=base + 2), "샘플수")

    ws.row_dimensions[2].height = 20
    ws.row_dimensions[3].height = 20

    # 데이터 행
    for r_idx, m in enumerate(multipliers):
        row = 4 + r_idx
        df = sweep_results[m]
        alt = r_idx % 2 == 1

        _data_cell(ws.cell(row=row, column=1), f"{m}x", alt_row=alt)
        _data_cell(ws.cell(row=row, column=2), len(df) if not df.empty else 0, alt_row=alt)
        _data_cell(ws.cell(row=row, column=3), forward_days, alt_row=alt)

        for i, n in enumerate(days):
            base = 4 + i * 3
            col_ret = f"ret_d{n}"
            if df.empty or col_ret not in df.columns:
                for c in range(base, base + 3):
                    _data_cell(ws.cell(row=row, column=c), "N/A", alt_row=alt)
                continue
            s = df[col_ret].dropna()
            avg = round(s.mean(), 4) if len(s) > 0 else None
            win = round((s > 0).mean() * 100, 1) if len(s) > 0 else None
            cnt = len(s)

            c_avg = ws.cell(row=row, column=base)
            _data_cell(c_avg, avg, fmt='0.00"%"', alt_row=alt)
            _apply_pct_color(ws, row, base, avg)

            c_win = ws.cell(row=row, column=base + 1)
            _data_cell(c_win, win, fmt='0.0"%"', alt_row=alt)
            # 승률 색상 (50% 기준)
            if win is not None:
                if win >= 55:
                    c_win.fill = PatternFill("solid", fgColor=CLR_POS)
                elif win < 45:
                    c_win.fill = PatternFill("solid", fgColor=CLR_NEG)

            _data_cell(ws.cell(row=row, column=base + 2), cnt, alt_row=alt)

        ws.row_dimensions[row].height = 18

    # 열 너비
    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 8
    ws.column_dimensions["C"].width = 12
    for i in range(len(days) * 3):
        col_letter = get_column_letter(4 + i)
        ws.column_dimensions[col_letter].width = 11

    ws.freeze_panes = "A4"


# ── 상세 시트 ──────────────────────────────────────────────────────────

def _build_detail_sheet(ws, sweep_results: dict, forward_days: int):
    """상세 시트: 전체 신호 리스트"""
    all_dfs = []
    for m, df in sorted(sweep_results.items()):
        if not df.empty:
            all_dfs.append(df)
    if not all_dfs:
        ws.cell(row=1, column=1).value = "신호 없음"
        return

    combined = pd.concat(all_dfs, ignore_index=True)
    combined["signal_date"] = pd.to_datetime(combined["signal_date"])
    combined = combined.sort_values(["multiplier", "signal_date"]).reset_index(drop=True)

    days = list(range(1, forward_days + 1))

    # 고정 컬럼: 종목코드/명/시장/배수/신호일/신호종가/매수일/매수가/거래대금/신호일지수등락률
    fixed_headers = [
        "종목코드", "종목명", "시장", "배수", "신호일", "신호종가",
        "매수일(D+1)", "매수가(D+1시가)", "신호일 거래대금(억)", "신호일 지수등락률(%)",
    ]
    # 가변 컬럼: D+n 수익률 (+ 지수/초과수익 컬럼은 EXCESS_DAYS만)
    day_headers = []
    for n in days:
        day_headers.append(f"D+{n}(%)")
        if n in EXCESS_DAYS:
            day_headers.append(f"D+{n} 지수(%)")
            day_headers.append(f"D+{n} 초과수익(%)")

    headers = fixed_headers + day_headers

    _hdr_style(ws, 1, len(headers), "전체 신호 상세 리스트")
    ws.row_dimensions[1].height = 26

    for col, h in enumerate(headers, 1):
        _col_hdr(ws.cell(row=2, column=col), h)
    ws.row_dimensions[2].height = 20

    def _num(val):
        try:
            return float(val) if val is not None and pd.notna(val) else None
        except (TypeError, ValueError):
            return None

    for r_idx, (_, row_data) in enumerate(combined.iterrows()):
        row = 3 + r_idx
        alt = r_idx % 2 == 1
        col = 1

        _data_cell(ws.cell(row=row, column=col), str(row_data.get("ticker", "")), alt_row=alt); col += 1
        _data_cell(ws.cell(row=row, column=col), str(row_data.get("name", "")), alt_row=alt)
        ws.cell(row=row, column=col).alignment = Alignment(horizontal="left", vertical="center")
        col += 1
        _data_cell(ws.cell(row=row, column=col), str(row_data.get("market") or ""), alt_row=alt); col += 1
        _data_cell(ws.cell(row=row, column=col), f"{row_data.get('multiplier', '')}x", alt_row=alt); col += 1

        sig_date = row_data.get("signal_date")
        c = ws.cell(row=row, column=col)
        if pd.notna(sig_date):
            c.value = pd.Timestamp(sig_date).to_pydatetime()
            c.number_format = "YYYY-MM-DD"
        _data_cell(c, None, alt_row=alt); col += 1

        _data_cell(ws.cell(row=row, column=col), _num(row_data.get("signal_close")), fmt="#,##0", alt_row=alt); col += 1

        entry_date = row_data.get("entry_date")
        c = ws.cell(row=row, column=col)
        if pd.notna(entry_date):
            c.value = pd.Timestamp(entry_date).to_pydatetime()
            c.number_format = "YYYY-MM-DD"
        _data_cell(c, None, alt_row=alt); col += 1

        _data_cell(ws.cell(row=row, column=col), _num(row_data.get("entry_price")), fmt="#,##0", alt_row=alt); col += 1

        tv = _num(row_data.get("trading_value_signal"))
        tv_eok = round(tv / 1e8, 2) if tv is not None else None
        _data_cell(ws.cell(row=row, column=col), tv_eok, fmt="#,##0.0", alt_row=alt); col += 1

        idx_chg = _num(row_data.get("idx_chg_signal"))
        c_idx = ws.cell(row=row, column=col)
        _data_cell(c_idx, idx_chg, fmt='0.00"%"', alt_row=alt)
        _apply_pct_color(ws, row, col, idx_chg)
        col += 1

        for n in days:
            val = _num(row_data.get(f"ret_d{n}"))
            _data_cell(ws.cell(row=row, column=col), val, fmt='0.00"%"', alt_row=alt)
            _apply_pct_color(ws, row, col, val)
            col += 1

            if n in EXCESS_DAYS:
                idx_ret = _num(row_data.get(f"idx_ret_d{n}"))
                _data_cell(ws.cell(row=row, column=col), idx_ret, fmt='0.00"%"', alt_row=alt)
                _apply_pct_color(ws, row, col, idx_ret)
                col += 1

                excess = _num(row_data.get(f"excess_d{n}"))
                _data_cell(ws.cell(row=row, column=col), excess, fmt='0.00"%"', alt_row=alt)
                _apply_pct_color(ws, row, col, excess)
                col += 1

        ws.row_dimensions[row].height = 16

    # 열 너비
    fixed_widths = [10, 16, 7, 7, 13, 12, 13, 13, 14, 14]
    day_widths = []
    for n in days:
        day_widths.append(10)
        if n in EXCESS_DAYS:
            day_widths.append(10)
            day_widths.append(11)
    widths = fixed_widths + day_widths
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.freeze_panes = "A3"

    # 자동 필터
    max_col = get_column_letter(len(headers))
    ws.auto_filter.ref = f"A2:{max_col}{2 + len(combined)}"


# ── 메인 함수 ──────────────────────────────────────────────────────────

def export_excel(
    sweep_results: dict,
    pattern_name: str,
    forward_days: int = 5,
    output_dir: Path = None,
) -> Path:
    """
    백테스팅 결과를 엑셀 파일로 저장.

    Parameters
    ----------
    sweep_results : dict[float, pd.DataFrame]
        {multiplier: results_df}
    pattern_name : str
        패턴 이름 (파일명에 사용)
    forward_days : int
        Forward test 기간
    output_dir : Path, optional
        저장 디렉토리. 기본값: data/results/

    Returns
    -------
    Path
        저장된 엑셀 파일 경로
    """
    if not HAS_OPENPYXL:
        print("[WARN] openpyxl이 설치되어 있지 않습니다. pip install openpyxl")
        return None

    out_dir = output_dir or RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.today().strftime("%Y%m%d_%H%M")
    fname = out_dir / f"{pattern_name}_{timestamp}.xlsx"

    wb = Workbook()

    # ── 요약 시트
    ws_summary = wb.active
    ws_summary.title = "요약"
    _build_summary_sheet(ws_summary, sweep_results, forward_days)

    # ── 상세 시트
    ws_detail = wb.create_sheet("상세")
    _build_detail_sheet(ws_detail, sweep_results, forward_days)

    # 인쇄 설정
    for ws in [ws_summary, ws_detail]:
        ws.page_setup.fitToPage = True
        ws.page_setup.fitToWidth = 1
        ws.sheet_view.showGridLines = True

    wb.save(fname)
    print(f"[SAVE] Excel: {fname}")
    return fname
