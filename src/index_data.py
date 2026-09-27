"""
index_data.py — 코스피/코스닥 지수 일별 시세 수집 & 캐시

pykrx의 KRX 직접 지수 조회(stock.get_index_ohlcv)는 KRX 웹사이트 API 변경으로
현재 빈 응답을 반환하며 동작하지 않는다 (2026-09 기준 확인됨). 대신 네이버
금융의 지수 일별시세 페이지를 스크레이핑해 안정적으로 대체한다.
"""
from __future__ import annotations

import logging
import time
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_NAVER_INDEX_URL = "https://finance.naver.com/sise/sise_index_day.naver"
_HEADERS = {"User-Agent": "Mozilla/5.0"}

# market 이름 -> 네이버 지수 코드
_MARKET_CODE = {
    "KOSPI": "KOSPI",
    "KOSDAQ": "KOSDAQ",
}


def _cache_file(market: str) -> Path:
    return CACHE_DIR / f"index_{market.lower()}.parquet"


def fetch_index_daily(
    market: str,
    start_date: str,
    end_date: str,
    sleep_between: float = 0.3,
    max_pages: int = 400,
) -> pd.DataFrame:
    """네이버 금융에서 지수(코스피/코스닥) 일별 종가·등락률 시계열 조회.

    Parameters
    ----------
    market : str
        "KOSPI" 또는 "KOSDAQ"
    start_date, end_date : str
        조회 기간 (YYYYMMDD)

    Returns
    -------
    pd.DataFrame
        columns: date(datetime), close(float), chg_pct(float, 당일 등락률 %)
        날짜 오름차순 정렬
    """
    code = _MARKET_CODE.get(market.upper())
    if code is None:
        raise ValueError(f"지원하지 않는 시장: {market}")

    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)

    rows = []
    page = 1
    while page <= max_pages:
        try:
            resp = requests.get(
                _NAVER_INDEX_URL, params={"code": code, "page": page},
                headers=_HEADERS, timeout=10,
            )
            resp.encoding = "euc-kr"
            tables = pd.read_html(StringIO(resp.text))
        except Exception as e:
            logger.warning(f"[{market}] 지수 페이지 {page} 조회 실패: {e}")
            break

        if not tables:
            break
        df = tables[0].dropna()
        if df.empty:
            break

        df = df.rename(columns={"날짜": "date", "체결가": "close", "등락률": "chg_pct"})
        df["date"] = pd.to_datetime(df["date"], format="%Y.%m.%d")
        df["chg_pct"] = (
            df["chg_pct"].astype(str).str.replace("%", "", regex=False).astype(float)
        )
        rows.append(df[["date", "close", "chg_pct"]])

        oldest = df["date"].min()
        if oldest <= start_ts:
            break

        page += 1
        time.sleep(sleep_between)

    if not rows:
        return pd.DataFrame(columns=["date", "close", "chg_pct"])

    full = pd.concat(rows, ignore_index=True).drop_duplicates("date")
    full = full.sort_values("date").reset_index(drop=True)
    full = full[(full["date"] >= start_ts) & (full["date"] <= end_ts)].reset_index(drop=True)
    return full


def build_index_cache(
    market: str,
    start_date: str,
    end_date: str,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """지수 일별 시세 캐시 로드/생성 (필요 구간을 커버하지 못하면 재수집)."""
    cache_file = _cache_file(market)
    if not force_refresh and cache_file.exists():
        try:
            cached = pd.read_parquet(cache_file)
            cached["date"] = pd.to_datetime(cached["date"])
            if (
                not cached.empty
                and cached["date"].min() <= pd.Timestamp(start_date)
                and cached["date"].max() >= pd.Timestamp(end_date)
            ):
                return cached
        except Exception as e:
            logger.warning(f"[{market}] 지수 캐시 로드 실패, 재수집: {e}")

    print(f"[DL] [{market}] 지수 데이터 수집: {start_date} ~ {end_date}")
    df = fetch_index_daily(market, start_date, end_date)
    if df.empty:
        print(f"[WARN] [{market}] 지수 데이터 수집 실패 — 지수 관련 컬럼은 공란으로 표시됩니다.")
        return df

    df.to_parquet(cache_file, index=False)
    print(f"[OK] [{market}] 지수 캐시 저장: {len(df)}행 ({df['date'].min().date()} ~ {df['date'].max().date()})")
    return df
