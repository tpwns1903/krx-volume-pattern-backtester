"""
universe.py — 종목 유니버스 필터링 (스팩/우선주/ETF 제외)
"""
from __future__ import annotations

import re
import logging
from io import BytesIO

logger = logging.getLogger(__name__)

# pykrx의 KRX 직접 종목 리스트 조회(stock.get_market_ticker_list)가
# KRX 웹사이트 API 변경으로 현재 빈 응답을 반환한다 (2026-09 기준 확인됨).
# 이 경우 한국거래소 상장법인목록(KIND) 다운로드로 대체한다.
_KIND_MARKET_TYPE = {"KOSPI": "stockMkt", "KOSDAQ": "kosdaqMkt"}
_KIND_URL = "https://kind.krx.co.kr/corpgeneral/corpList.do"

# 제외할 종목명 패턴 (정규식)
EXCLUSION_PATTERNS = [
    re.compile(r"스팩"),                        # 스팩 (SPAC)
    re.compile(r"(^|\s)\d*우B?$"),             # 우선주: ~우, ~1우, ~2우, ~우B
    re.compile(r"(^|\s)\d*우\d*B?$"),          # 우선주 변형
]


def _is_excluded(name: str) -> bool:
    """종목명이 제외 대상인지 확인"""
    if not name or not name.strip():
        return True
    for pat in EXCLUSION_PATTERNS:
        if pat.search(name):
            return True
    return False


def _tickers_via_pykrx(date: str, market: str) -> dict[str, str]:
    """pykrx(KRX 직접 조회)로 {ticker: name} 조회. 실패 시 빈 dict."""
    from pykrx import stock
    try:
        tickers = stock.get_market_ticker_list(date, market=market)
    except Exception as e:
        logger.warning(f"[{market}] pykrx 종목 리스트 조회 실패: {e}")
        return {}
    if not tickers:
        return {}

    result = {}
    for ticker in tickers:
        try:
            result[ticker] = stock.get_market_ticker_name(ticker)
        except Exception:
            result[ticker] = ""
    return result


def _tickers_via_kind(market: str) -> dict[str, str]:
    """KRX 상장법인목록(KIND) 다운로드로 {ticker: name} 조회 (pykrx 실패 시 대체 경로)."""
    import requests
    import pandas as pd

    market_type = _KIND_MARKET_TYPE.get(market.upper())
    if market_type is None:
        return {}

    try:
        resp = requests.get(
            _KIND_URL,
            params={"method": "download", "marketType": market_type},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        resp.encoding = "euc-kr"
        tables = pd.read_html(BytesIO(resp.content), encoding="euc-kr")
    except Exception as e:
        logger.warning(f"[{market}] KIND 상장법인목록 조회 실패: {e}")
        return {}

    if not tables:
        return {}
    df = tables[0]
    if "종목코드" not in df.columns or "회사명" not in df.columns:
        return {}

    df["종목코드"] = df["종목코드"].astype(str).str.zfill(6)
    df = df[df["종목코드"].str.match(r"^\d{6}$")]  # 임시코드(문자 포함) 등 제외
    return dict(zip(df["종목코드"], df["회사명"]))


def get_filtered_universe(
    date: str,
    markets: list[str] = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """
    지정 날짜 기준 코스피/코스닥 필터링된 종목 유니버스 반환.

    Parameters
    ----------
    date : str
        기준일 (YYYYMMDD)
    markets : list[str]
        조회 시장 목록. 기본값: ["KOSPI", "KOSDAQ"]

    Returns
    -------
    tuple[dict[str, str], dict[str, str]]
        ({ticker: name}, {ticker: market}) — 필터링 후 유효 종목만
    """
    try:
        import pykrx  # noqa: F401  (설치 여부 확인용)
    except ImportError:
        raise ImportError("pykrx가 설치되어 있지 않습니다. pip install pykrx 를 실행하세요.")

    if markets is None:
        markets = ["KOSPI", "KOSDAQ"]

    universe: dict[str, str] = {}
    ticker_market: dict[str, str] = {}
    excluded_count = 0

    for market in markets:
        name_map = _tickers_via_pykrx(date, market)
        if not name_map:
            logger.warning(f"[{market}] pykrx 종목 리스트가 비어있어 KIND 대체 조회로 전환합니다.")
            name_map = _tickers_via_kind(market)

        if not name_map:
            raise RuntimeError(
                f"[{market}] 종목 리스트를 가져오지 못했습니다 (pykrx/KIND 모두 실패). "
                "네트워크 연결 또는 KRX/KIND 웹사이트 상태를 확인하세요."
            )

        for ticker, name in name_map.items():
            if _is_excluded(name):
                excluded_count += 1
                logger.debug(f"제외: {ticker} {name}")
                continue

            universe[ticker] = name
            ticker_market[ticker] = market

    logger.info(
        f"유니버스 필터링 완료: 유효 {len(universe)}개, "
        f"제외 {excluded_count}개 (스팩/우선주/이름없음)"
    )
    return universe, ticker_market
