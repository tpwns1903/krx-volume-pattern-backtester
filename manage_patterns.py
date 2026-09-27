"""
manage_patterns.py — 패턴 목록 조회 & 관리 CLI

사용법:
  python manage_patterns.py list                      # 저장된 패턴 목록
  python manage_patterns.py show 거래량_유입후_감소   # 패턴 상세 정보
  python manage_patterns.py run  거래량_유입후_감소   # 패턴 재실행
  python manage_patterns.py delete 거래량_유입후_감소 # 패턴 삭제
  python manage_patterns.py cache-info                # 캐시 상태 확인
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False

sys.path.insert(0, str(Path(__file__).parent))

# Windows 콘솔(cp949)에서도 유니코드 출력이 깨지지 않도록
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

PATTERNS_DIR = Path(__file__).parent / "patterns"


def _load_all_patterns() -> list[dict]:
    """patterns/ 폴더의 모든 JSON 파일 로드"""
    PATTERNS_DIR.mkdir(parents=True, exist_ok=True)
    patterns = []
    for f in sorted(PATTERNS_DIR.glob("*.json")):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                data["_file"] = str(f)
                patterns.append(data)
        except Exception as e:
            print(f"⚠️  {f.name} 로드 실패: {e}")
    return patterns


def cmd_list(args):
    """저장된 패턴 목록 출력"""
    patterns = _load_all_patterns()
    if not patterns:
        print("저장된 패턴이 없습니다.")
        print(f"  패턴 폴더: {PATTERNS_DIR}")
        return

    rows = []
    for p in patterns:
        last_run = p.get("last_run") or "미실행"
        summary = p.get("last_result_summary") or {}
        total_sig = summary.get("total_signals", "-")
        rows.append({
            "패턴 이름": p.get("name", "?"),
            "생성일": p.get("created_at", "?"),
            "마지막 실행": last_run,
            "총 신호 수": total_sig,
            "설명": (p.get("description_ko") or "")[:40] + "...",
        })

    print(f"\n[Pattern List] ({len(patterns)} patterns)\n")
    if HAS_TABULATE:
        print(tabulate(rows, headers="keys", tablefmt="simple", showindex=True))
    else:
        for i, r in enumerate(rows):
            print(f"[{i}] {r}")


def cmd_show(args):
    """패턴 상세 정보 출력"""
    pattern_file = PATTERNS_DIR / f"{args.name}.json"
    if not pattern_file.exists():
        print(f"[-] 패턴을 찾을 수 없습니다: {args.name}")
        print(f"   (찾은 위치: {pattern_file})")
        return

    with open(pattern_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"\n{'='*60}")
    print(f"패턴 이름  : {data.get('name')}")
    print(f"생성일     : {data.get('created_at')}")
    print(f"클래스     : {data.get('module')}.{data.get('class')}")
    print(f"설명       : {data.get('description_ko')}")
    print(f"\n[파라미터]")
    for k, v in (data.get("params") or {}).items():
        print(f"  {k}: {v}")
    print(f"\n[마지막 실행]")
    print(f"  실행 시각: {data.get('last_run') or '미실행'}")
    summary = data.get("last_result_summary") or {}
    if summary:
        for k, v in summary.items():
            print(f"  {k}: {v}")
    print(f"{'='*60}")


def cmd_run(args):
    """저장된 패턴 재실행 (run_pattern.py 호출)"""
    pattern_file = PATTERNS_DIR / f"{args.name}.json"
    if not pattern_file.exists():
        print(f"[-] 패턴을 찾을 수 없습니다: {args.name}")
        return

    cmd = [sys.executable, "run_pattern.py", "--pattern", args.name]

    # 추가 옵션 전달
    if getattr(args, "refresh", False):
        cmd.append("--refresh")
    if getattr(args, "multipliers", None):
        cmd.extend(["--multipliers"] + [str(m) for m in args.multipliers])
    if getattr(args, "start", None):
        cmd.extend(["--start", args.start])
    if getattr(args, "end", None):
        cmd.extend(["--end", args.end])
    if getattr(args, "forward_days", None):
        cmd.extend(["--forward-days", str(args.forward_days)])
    if getattr(args, "workers", None):
        cmd.extend(["--workers", str(args.workers)])
    if getattr(args, "market", None):
        cmd.extend(["--market", args.market])
    if getattr(args, "min_trading_value", None) is not None:
        cmd.extend(["--min-trading-value", str(args.min_trading_value)])
    if getattr(args, "top", None):
        cmd.extend(["--top", str(args.top)])
    if getattr(args, "no_save", False):
        cmd.append("--no-save")
    if getattr(args, "no_excel", False):
        cmd.append("--no-excel")
    if getattr(args, "no_charts", False):
        cmd.append("--no-charts")

    print(f"▶ 실행: {' '.join(cmd)}\n")
    subprocess.run(cmd, cwd=str(Path(__file__).parent))


def cmd_delete(args):
    """패턴 파일 삭제"""
    pattern_file = PATTERNS_DIR / f"{args.name}.json"
    if not pattern_file.exists():
        print(f"[-] 패턴을 찾을 수 없습니다: {args.name}")
        return

    confirm = input(f"정말 '{args.name}' 패턴을 삭제하시겠습니까? (y/N): ").strip().lower()
    if confirm == "y":
        pattern_file.unlink()
        print(f"[+] 삭제 완료: {pattern_file}")
    else:
        print("취소되었습니다.")


def cmd_cache_info(args):
    """캐시 상태 확인"""
    from src.data_loader import DataLoader
    markets = None if getattr(args, "market", None) in (None, "ALL") else [args.market]
    loader = DataLoader(markets=markets)
    info = loader.cache_info()
    if not info["exists"]:
        print("[-] 캐시 파일이 없습니다.")
        print("   python run_pattern.py --refresh 를 실행하세요.")
        return

    print(f"\n[Cache Info]")
    print(f"  경로      : {info['path']}")
    print(f"  파일 크기  : {info['size_mb']} MB")
    print(f"  총 행수    : {info['rows']:,}")
    print(f"  종목 수    : {info['tickers']:,}")
    print(f"  기간       : {info['date_min']} ~ {info['date_max']}")
    print(f"  마지막 수정: {info['modified']}")


def main():
    parser = argparse.ArgumentParser(
        description="패턴 관리 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list
    subparsers.add_parser("list", help="저장된 패턴 목록 출력")

    # show
    show_p = subparsers.add_parser("show", help="패턴 상세 정보")
    show_p.add_argument("name", help="패턴 이름")

    # run
    run_p = subparsers.add_parser("run", help="저장된 패턴 재실행")
    run_p.add_argument("name", help="패턴 이름")
    run_p.add_argument("--refresh", action="store_true", help="캐시 강제 갱신")
    run_p.add_argument("--multipliers", nargs="+", type=float, help="배수 오버라이드")
    run_p.add_argument("--start", type=str, help="데이터 시작일 (YYYYMMDD)")
    run_p.add_argument("--end", type=str, help="데이터 종료일 (YYYYMMDD)")
    run_p.add_argument("--forward-days", type=int, help="Forward test 기간")
    run_p.add_argument("--workers", type=int, help="병렬 다운로드 스레드 수")
    run_p.add_argument("--market", choices=["ALL", "KOSPI", "KOSDAQ"], help="조회할 시장 (기본: ALL)")
    run_p.add_argument("--min-trading-value", type=float, help="신호일 최소 거래대금(원) 필터 (기본: 10억원)")
    run_p.add_argument("--top", type=int, help="최근 신호 상위 출력 건수")
    run_p.add_argument("--no-save", action="store_true", help="CSV/엑셀/차트 저장 안 함")
    run_p.add_argument("--no-excel", action="store_true", help="엑셀 생성 안 함")
    run_p.add_argument("--no-charts", action="store_true", help="차트 생성 안 함")

    # delete
    del_p = subparsers.add_parser("delete", help="패턴 삭제")
    del_p.add_argument("name", help="패턴 이름")

    # cache-info
    cache_p = subparsers.add_parser("cache-info", help="OHLCV 캐시 상태 확인")
    cache_p.add_argument("--market", choices=["ALL", "KOSPI", "KOSDAQ"], help="조회할 시장 (기본: ALL)")

    args = parser.parse_args()

    commands = {
        "list": cmd_list,
        "show": cmd_show,
        "run": cmd_run,
        "delete": cmd_delete,
        "cache-info": cmd_cache_info,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
