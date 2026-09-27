"""
run_pattern.py — 메인 실행 진입점

사용법:
  python run_pattern.py                              # 기본 실행 (캐시 있으면 재사용)
  python run_pattern.py --refresh                    # 데이터 강제 재다운로드
  python run_pattern.py --multipliers 2.0 3.0        # 특정 배수만 실행
  python run_pattern.py --pattern 거래량_유입후_감소  # 저장된 패턴 이름으로 실행
  python run_pattern.py --start 20240101             # 데이터 시작일 지정
  python run_pattern.py --workers 8                  # 다운로드 병렬 스레드 수
"""
from __future__ import annotations

import argparse
import importlib
import json
import logging
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent))

# Windows 콘솔(cp949)에서도 유니코드 출력이 깨지지 않도록
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from src.chart_export import export_all_charts
from src.data_loader import DataLoader
from src.excel_export import export_excel
from src.index_data import build_index_cache
from src.pattern_engine import PatternEngine
from src.patterns.volume_pattern import VolumeInflowDeclinePattern
from src.report import print_summary

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

PATTERNS_DIR = Path(__file__).parent / "patterns"


def load_pattern_by_name(name: str):
    """저장된 패턴 JSON에서 패턴 인스턴스 복원"""
    pattern_file = PATTERNS_DIR / f"{name}.json"
    if not pattern_file.exists():
        raise FileNotFoundError(f"패턴 파일을 찾을 수 없습니다: {pattern_file}")

    with open(pattern_file, "r", encoding="utf-8") as f:
        meta = json.load(f)

    params = meta.get("params", {})
    module_name = meta.get("module", "")
    class_name = meta.get("class", "")

    # JSON에 module/class가 있으면 동적 import로 임의 패턴 복원
    if module_name and class_name:
        try:
            mod = importlib.import_module(module_name)
            cls = getattr(mod, class_name)
            return cls(params=params)
        except (ImportError, AttributeError) as e:
            raise NotImplementedError(
                f"패턴 클래스 로드 실패: {module_name}.{class_name} ({e})"
            )

    # 폴백 (구버전 JSON 호환)
    if class_name == "VolumeInflowDeclinePattern":
        return VolumeInflowDeclinePattern(params=params)
    raise NotImplementedError(f"아직 지원하지 않는 패턴 클래스: {class_name}")


def main():
    parser = argparse.ArgumentParser(
        description="국내 주식 패턴 스크리닝 & 백테스팅",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="OHLCV 캐시를 강제 갱신합니다 (기본: 캐시 재사용)",
    )
    parser.add_argument(
        "--multipliers", nargs="+", type=float,
        help="거래량 배수 파라미터 (예: --multipliers 1.5 2.0 2.5 3.0)",
    )
    parser.add_argument(
        "--pattern", type=str, default=None,
        help="실행할 패턴 이름 (patterns/ 폴더의 JSON 파일명, 확장자 제외)",
    )
    parser.add_argument(
        "--start", type=str, default=None,
        help="데이터 시작일 (YYYYMMDD). 기본: 실행일 -2년",
    )
    parser.add_argument(
        "--end", type=str, default=None,
        help="데이터 종료일 (YYYYMMDD). 기본: 실행일",
    )
    parser.add_argument(
        "--workers", type=int, default=4,
        help="병렬 다운로드 스레드 수 (기본: 4)",
    )
    parser.add_argument(
        "--market", choices=["ALL", "KOSPI", "KOSDAQ"], default="ALL",
        help="조회할 시장 (기본: ALL = 코스피+코스닥). 코스닥만: --market KOSDAQ",
    )
    parser.add_argument(
        "--forward-days", type=int, default=5,
        help="Forward test 기간 (기본: 5영업일)",
    )
    parser.add_argument(
        "--no-save", action="store_true",
        help="결과를 CSV/엑셀/차트로 저장하지 않습니다",
    )
    parser.add_argument(
        "--no-excel", action="store_true",
        help="엑셀 파일을 생성하지 않습니다 (CSV/차트는 유지)",
    )
    parser.add_argument(
        "--no-charts", action="store_true",
        help="차트 PNG를 생성하지 않습니다 (CSV/엑셀은 유지)",
    )
    parser.add_argument(
        "--top", type=int, default=20,
        help="최근 신호 상위 몇 건을 출력할지 (기본: 20)",
    )
    parser.add_argument(
        "--min-trading-value", type=float, default=1_000_000_000,
        help="신호일 기준 최소 거래대금(원) 필터. 미달 신호 제외 (기본: 10억원)",
    )

    args = parser.parse_args()

    # -- 1. 패턴 선택 -------------------------------------------------
    if args.pattern:
        print(f"📂 패턴 로드: {args.pattern}")
        pattern = load_pattern_by_name(args.pattern)
    else:
        pattern = VolumeInflowDeclinePattern()

    # multipliers 오버라이드
    if args.multipliers:
        pattern.params["multipliers"] = args.multipliers
        print(f"[INFO]  multipliers 오버라이드: {args.multipliers}")

    # -- 2. 데이터 로드 -----------------------------------------------
    markets = None if args.market == "ALL" else [args.market]
    loader = DataLoader(
        start_date=args.start,
        end_date=args.end,
        markets=markets,
        max_workers=args.workers,
    )

    # 캐시 정보 출력
    info = loader.cache_info()
    if info["exists"]:
        print(f"\n[PKG] 기존 캐시 정보:")
        print(f"   경로: {info['path']}")
        print(f"   크기: {info['size_mb']} MB")
        print(f"   종목수: {info['tickers']}개, 행수: {info['rows']:,}")
        print(f"   기간: {info['date_min']} ~ {info['date_max']}")
        print(f"   마지막 수정: {info['modified']}")

    # 유니버스 & OHLCV 로드
    universe = loader.download_universe()
    ticker_market = loader.ticker_market
    ohlcv_data = loader.build_cache(force_refresh=args.refresh, universe=universe)

    if ohlcv_data.empty:
        print("[ERR] OHLCV 데이터가 없습니다. 종료합니다.")
        sys.exit(1)

    # 지수(코스피/코스닥) 데이터 로드 — 초과수익 계산용
    needed_markets = sorted(set(ticker_market.values())) or loader.markets
    index_data = {
        mkt: build_index_cache(mkt, loader.start_date, loader.end_date, force_refresh=args.refresh)
        for mkt in needed_markets
    }

    # -- 3. 패턴 저장 (첫 실행 시) -----------------------------------
    saved_path = pattern.save(PATTERNS_DIR)
    print(f"\n[SAVE] 패턴 정의 저장: {saved_path}")

    # -- 4. 패턴 검색 & 백테스팅 -------------------------------------
    engine = PatternEngine(forward_days=args.forward_days, min_trading_value=args.min_trading_value)
    sweep_results = engine.run_with_sweep(
        pattern=pattern,
        ohlcv_data=ohlcv_data,
        universe=universe,
        ticker_market=ticker_market,
        index_data=index_data,
    )

    # -- 5. 결과 출력 -------------------------------------------------
    print_summary(sweep_results, forward_days=args.forward_days, top_n=args.top)

    # -- 6. 결과 저장 (CSV / 엑셀 / 차트) --------------------------
    result_path = None
    excel_path = None
    chart_paths: list = []
    if not args.no_save:
        result_path = engine.save_results(sweep_results, pattern.name)

        if not args.no_excel:
            try:
                excel_path = export_excel(
                    sweep_results, pattern.name, forward_days=args.forward_days
                )
            except Exception as e:
                print(f"[WARN] 엑셀 생성 실패: {e}")

        if not args.no_charts:
            try:
                chart_paths = export_all_charts(
                    sweep_results, pattern.name, forward_days=args.forward_days
                )
            except Exception as e:
                print(f"[WARN] 차트 생성 실패: {e}")

    # -- 7. 패턴 last_run 갱신 ----------------------------------------
    total_signals = sum(len(df) for df in sweep_results.values() if not df.empty)
    summary_meta = {
        "total_signals": total_signals,
        "multipliers": pattern.params.get("multipliers"),
        "csv": str(result_path) if result_path else None,
        "excel": str(excel_path) if excel_path else None,
        "charts": [str(p) for p in chart_paths],
    }
    pattern.update_last_run(summary_meta, PATTERNS_DIR)

    print(f"\n[OK] 완료! 총 {total_signals}건의 신호가 감지되었습니다.")
    if result_path:
        print(f"   CSV   : {result_path}")
    if excel_path:
        print(f"   Excel : {excel_path}")
    for cp in chart_paths:
        print(f"   차트  : {cp}")


if __name__ == "__main__":
    main()
