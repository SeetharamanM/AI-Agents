"""Market data for Indian stocks via Yahoo Finance (yfinance).

NSE tickers use the `.NS` suffix, BSE tickers `.BO`. Data is delayed and
best-effort -- fine for portfolio review, not for trading decisions.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd
import yfinance as yf

BENCHMARK = "^NSEI"  # NIFTY 50
SUFFIX = {"NSE": ".NS", "BSE": ".BO"}


def to_ticker(symbol: str, exchange: str = "NSE") -> str:
    """'RELIANCE' -> 'RELIANCE.NS'. Leaves indices (^NSEI) and suffixed symbols alone."""
    symbol = symbol.strip().upper()
    if symbol.startswith("^") or symbol.endswith((".NS", ".BO")):
        return symbol
    return symbol + SUFFIX.get((exchange or "NSE").strip().upper(), ".NS")


def load_holdings(path: str | Path) -> pd.DataFrame:
    """Read a CSV with columns: symbol, quantity, avg_price[, exchange]."""
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    missing = {"symbol", "quantity", "avg_price"} - set(df.columns)
    if missing:
        raise ValueError(f"holdings file is missing columns: {sorted(missing)}")
    if "exchange" not in df.columns:
        df["exchange"] = "NSE"
    df["exchange"] = df["exchange"].fillna("NSE")
    df["symbol"] = df["symbol"].str.strip().str.upper()
    df["ticker"] = [to_ticker(s, e) for s, e in zip(df["symbol"], df["exchange"])]
    df["quantity"] = df["quantity"].astype(float)
    df["avg_price"] = df["avg_price"].astype(float)
    return df


@lru_cache(maxsize=64)
def _history(tickers: tuple[str, ...], period: str) -> pd.DataFrame:
    data = yf.download(list(tickers), period=period, auto_adjust=True, progress=False)
    if data.empty:
        raise RuntimeError(f"No price data returned for {tickers}")
    close = data["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame(tickers[0])
    return close


def price_history(tickers: list[str], period: str = "1y") -> pd.DataFrame:
    """Daily adjusted closes, one column per ticker."""
    return _history(tuple(sorted(set(tickers))), period).copy()


def latest_prices(tickers: list[str]) -> dict[str, float]:
    close = price_history(tickers, period="5d").ffill()
    return {t: float(close[t].dropna().iloc[-1]) for t in close.columns if close[t].notna().any()}


@lru_cache(maxsize=128)
def info(ticker: str) -> dict:
    """Company profile + fundamentals from Yahoo. Can be slow or partially empty."""
    try:
        return yf.Ticker(ticker).info or {}
    except Exception:  # Yahoo frequently rate-limits / changes shape
        return {}


def news(ticker: str, limit: int = 8) -> list[dict]:
    items = yf.Ticker(ticker).news or []
    out = []
    for item in items[:limit]:
        content = item.get("content", item)  # newer yfinance nests under "content"
        provider = content.get("provider") or {}
        out.append(
            {
                "title": content.get("title"),
                "publisher": provider.get("displayName") if isinstance(provider, dict) else content.get("publisher"),
                "published": content.get("pubDate") or content.get("providerPublishTime"),
                "summary": (content.get("summary") or "")[:300],
            }
        )
    return out
