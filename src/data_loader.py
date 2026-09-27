"""
data_loader.py — pykrx 데이터 수집 & 로컬 캐시 관리
"""
from __future__ import annotations

import os
import time
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import pandas as pd
from tqdm import tqdm

try:
    from pykrx import stock
except ImportError:
    raise ImportError("pykrx가 설치되어 있지 않습니다. pip install pykrx 를 실행하세요.")

logger = logging.getLogger(__name__)

# 프로젝트 루트 기준 캐시 경로
PROJECT_ROOT = Path(__file__).parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

OHLCV_CACHE_FILE = CACHE_DIR / "ohlcv_full.parquet"
UNIVERSE_CACHE_FILE = CACHE_DIR / "universe.parquet"


def _cache_file_for_markets(markets: list[str]) -> Path:
    """조회 시장 조합에 맞는 캐시 파일 경로 반환.

    KOSPI+KOSDAQ(기본) 조합은 기존 ohlcv_full.parquet를 그대로 사용해
    하위 호환을 유지하고, 그 외 조합(예: KOSDAQ만)은 별도 파일에 캐싱해
    기존 전종목 캐시를 덮어쓰지 않는다.
    """
    normalized = sorted(m.upper() for m in markets)
    if normalized == ["KOSDAQ", "KOSPI"]:
        return OHLCV_CACHE_FILE
    suffix = "_".join(m.lower() for m in normalized)
    return CACHE_DIR / f"ohlcv_{suffix}.parquet"


class DataLoader:
    """pykrx 기반 OHLCV 데이터 수집 & 캐시 관리 클래스"""

    def __init__(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        markets: list[str] = None,
        max_workers: int = 4,
        sleep_between: float = 0.3,
    ):
        """
        Parameters
        ----------
        start_date : str, optional
            조회 시작일 (YYYYMMDD). None이면 실행일 -2년
        end_date : str, optional
            조회 종료일 (YYYYMMDD). None이면 실행일
        markets : list[str], optional
            조회 시장 목록. 기본값: ["KOSPI", "KOSDAQ"]
        max_workers : int
            병렬 다운로드 스레드 수 (pykrx rate limit 고려해 4 권장)
        sleep_between : float
            종목별 요청 간 대기 시간(초)
        """
        today = datetime.today()
        self.end_date = end_date or today.strftime("%Y%m%d")
        self.start_date = start_date or (today - timedelta(days=730)).strftime("%Y%m%d")
        self.markets = markets or ["KOSPI", "KOSDAQ"]
        self.max_workers = max_workers
        self.sleep_between = sleep_between
        self.cache_file = _cache_file_for_markets(self.markets)
        self.ticker_market: dict[str, str] = {}

    # ------------------------------------------------------------------
    # 유니버스 조회
    # ------------------------------------------------------------------

    def download_universe(self) -> dict[str, str]:
        """
        KOSPI + KOSDAQ 종목 유니버스 조회 (스팩/우선주 제외)

        Returns
        -------
        dict[str, str]
            {ticker: name} 딕셔너리
        """
        from src.universe import get_filtered_universe
        universe, ticker_market = get_filtered_universe(self.end_date, self.markets)
        self.ticker_market = ticker_market
        logger.info(f"유니버스 로드 완료: {len(universe)}개 종목")
        return universe

    # ------------------------------------------------------------------
    # OHLCV 단일 종목
    # ------------------------------------------------------------------

    def _fetch_ohlcv_single(self, ticker: str) -> pd.DataFrame:
        """단일 종목 OHLCV 조회 (pykrx). 실패 시 빈 DataFrame 반환."""
        try:
            df = stock.get_market_ohlcv(self.start_date, self.end_date, ticker)
            if df is None or df.empty:
                return pd.DataFrame()
            df = df.reset_index()
            # pykrx get_market_ohlcv(fromdate, todate, ticker)는 보통
            # [날짜,시가,고가,저가,종가,거래량,등락률] 7개 컬럼을 반환한다(거래대금 없음).
            # 일부 환경/버전에서 거래대금이 포함된 8개 컬럼이 오는 경우도 위치 기준으로 처리.
            n_cols = len(df.columns)
            if n_cols == 7:
                df.columns = ["date", "open", "high", "low", "close", "volume", "chg_pct"]
            elif n_cols == 8:
                df.columns = ["date", "open", "high", "low", "close", "volume", "trading_value", "chg_pct"]
            else:
                logger.warning(f"[{ticker}] 예상치 못한 컬럼 수({n_cols}): {df.columns.tolist()}")
                return pd.DataFrame()
            # 필요한 컬럼만
            needed = ["date", "open", "high", "low", "close", "volume"]
            df = df[[c for c in needed if c in df.columns]]
            df.insert(0, "ticker", ticker)
            df["date"] = pd.to_datetime(df["date"])
            return df
        except Exception as e:
            logger.warning(f"[{ticker}] 데이터 조회 실패: {e}")
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # 전종목 캐시 빌드
    # ------------------------------------------------------------------

    def build_cache(self, force_refresh: bool = False, universe: dict[str, str] = None) -> pd.DataFrame:
        """
        전종목 OHLCV를 parquet으로 캐싱.

        Parameters
        ----------
        force_refresh : bool
            True면 기존 캐시 무시하고 새로 다운로드
        universe : dict[str, str], optional
            {ticker: name}. None이면 자동 조회

        Returns
        -------
        pd.DataFrame
            columns: ticker, date, open, high, low, close, volume
        """
        if not force_refresh and self.cache_file.exists():
            print(f"[OK] 캐시 파일 발견: {self.cache_file}")
            print("   캐시를 로드합니다. 강제 갱신 시 --refresh 옵션 사용.")
            return self.load_cache()

        if universe is None:
            universe = self.download_universe()

        tickers = list(universe.keys())
        print(f"\n[DL] 전종목 OHLCV 다운로드 시작")
        print(f"   기간: {self.start_date} ~ {self.end_date}")
        print(f"   종목 수: {len(tickers)}개")
        print(f"   병렬 스레드: {self.max_workers}개")
        print(f"   예상 소요 시간: 약 30~60분\n")

        all_dfs = []
        failed = []

        def fetch_with_sleep(ticker: str) -> pd.DataFrame:
            time.sleep(self.sleep_between)
            return self._fetch_ohlcv_single(ticker)

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(fetch_with_sleep, t): t for t in tickers}
            with tqdm(total=len(tickers), desc="OHLCV 다운로드", unit="종목") as pbar:
                for future in as_completed(futures):
                    ticker = futures[future]
                    try:
                        df = future.result()
                        if not df.empty:
                            all_dfs.append(df)
                        else:
                            failed.append(ticker)
                    except Exception as e:
                        logger.warning(f"[{ticker}] 예외: {e}")
                        failed.append(ticker)
                    pbar.update(1)

        if not all_dfs:
            raise RuntimeError("다운로드된 데이터가 없습니다.")

        print(f"\n[OK] 다운로드 완료: {len(all_dfs)}개 성공, {len(failed)}개 실패")

        full_df = pd.concat(all_dfs, ignore_index=True)

        # 종목명 컬럼 추가
        name_map = pd.Series(universe)
        full_df["name"] = full_df["ticker"].map(name_map).fillna("")

        # 정렬
        full_df = full_df.sort_values(["ticker", "date"]).reset_index(drop=True)

        # 저장
        full_df.to_parquet(self.cache_file, index=False)
        print(f"[SAVE] 캐시 저장 완료: {self.cache_file}")
        print(f"   총 {len(full_df):,} rows, {full_df['ticker'].nunique():,} 종목")

        if failed:
            failed_path = CACHE_DIR / "failed_tickers.txt"
            with open(failed_path, "w", encoding="utf-8") as f:
                f.write("\n".join(failed))
            print(f"[WARN]  실패 종목 목록: {failed_path}")

        return full_df

    # ------------------------------------------------------------------
    # 캐시 로드
    # ------------------------------------------------------------------

    def load_cache(self) -> pd.DataFrame:
        """
        캐시된 OHLCV parquet 로드.

        Returns
        -------
        pd.DataFrame
            columns: ticker, name, date, open, high, low, close, volume
        """
        if not self.cache_file.exists():
            raise FileNotFoundError(
                f"캐시 파일이 없습니다: {self.cache_file}\n"
                "먼저 build_cache()를 실행하거나 --refresh 옵션을 사용하세요."
            )
        df = pd.read_parquet(self.cache_file)
        df["date"] = pd.to_datetime(df["date"])
        print(f"[OK] 캐시 로드 완료: {len(df):,} rows, {df['ticker'].nunique():,} 종목")
        print(f"   기간: {df['date'].min().date()} ~ {df['date'].max().date()}")
        return df

    def cache_info(self) -> dict:
        """캐시 파일 정보 반환"""
        if not self.cache_file.exists():
            return {"exists": False}
        stat = self.cache_file.stat()
        df = pd.read_parquet(self.cache_file, columns=["ticker", "date"])
        df["date"] = pd.to_datetime(df["date"])
        return {
            "exists": True,
            "path": str(self.cache_file),
            "size_mb": round(stat.st_size / 1024 / 1024, 1),
            "rows": len(df),
            "tickers": df["ticker"].nunique(),
            "date_min": str(df["date"].min().date()),
            "date_max": str(df["date"].max().date()),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
        }
