"""
US universe definition for V0.1.

V0.1 ships with a static list rather than scraping S&P 500 membership at
runtime: the trend-momentum backtest needs a fast, reproducible starting
universe and point-in-time membership is a V1.x concern.

The list is a hand-picked 100 large-cap tickers chosen to give the trend
strategy enough breadth across sectors plus the five core ETFs the
backtest engine needs as benchmarks (SPY/QQQ/TLT/GLD/IWM).
"""

from __future__ import annotations

from datetime import date

# 100 large-cap US equities, grouped roughly by sector for reviewer clarity.
# Source: hand-curated from S&P 100 + sector leaders. See README "Engineering
# decisions" — Wikipedia/datahub scrape is V1.x.
_LARGE_CAPS: tuple[str, ...] = (
    # Mega-cap tech / communications
    "AAPL",
    "MSFT",
    "GOOGL",
    "GOOG",
    "AMZN",
    "META",
    "NVDA",
    "TSLA",
    "AVGO",
    "ORCL",
    "ADBE",
    "CRM",
    "NFLX",
    "AMD",
    "QCOM",
    "INTC",
    "CSCO",
    "IBM",
    "TXN",
    "INTU",
    # Consumer
    "WMT",
    "COST",
    "HD",
    "MCD",
    "NKE",
    "SBUX",
    "LOW",
    "TGT",
    "TJX",
    "BKNG",
    "DIS",
    "CMCSA",
    "T",
    "VZ",
    "PG",
    "KO",
    "PEP",
    "MDLZ",
    "PM",
    "MO",
    # Healthcare
    "UNH",
    "JNJ",
    "LLY",
    "ABBV",
    "PFE",
    "MRK",
    "TMO",
    "ABT",
    "DHR",
    "BMY",
    "AMGN",
    "GILD",
    "CVS",
    "MDT",
    "ELV",
    "ISRG",
    "REGN",
    "VRTX",
    "CI",
    "HUM",
    # Financials
    "JPM",
    "BAC",
    "WFC",
    "GS",
    "MS",
    "C",
    "AXP",
    "BLK",
    "SCHW",
    "USB",
    "PNC",
    "TFC",
    "COF",
    "MMC",
    "CME",
    "SPGI",
    "ICE",
    "PYPL",
    "V",
    "MA",
    # Industrials / Materials / Energy
    "CAT",
    "DE",
    "BA",
    "HON",
    "UNP",
    "UPS",
    "LMT",
    "RTX",
    "GE",
    "MMM",
    "XOM",
    "CVX",
    "COP",
    "SLB",
    "EOG",
    "PSX",
    "VLO",
    "MPC",
    "OXY",
    "APA",
)

_CORE_ETFS: tuple[str, ...] = ("SPY", "QQQ", "TLT", "GLD", "IWM")


_US_UNIVERSE: tuple[str, ...] = _LARGE_CAPS + _CORE_ETFS


def get_us_universe(_as_of: date | None = None) -> list[str]:
    """Return the US universe of tickers as of ``_as_of``.

    V0.1 ignores the date argument: membership is static. The signature
    keeps the door open for V1.x point-in-time membership without forcing
    callers to change.
    """
    return list(_US_UNIVERSE)


def is_etf(code: str) -> bool:
    """Return True if ``code`` is one of the core ETFs we track."""
    return code in _CORE_ETFS


__all__ = ["get_us_universe", "is_etf"]
