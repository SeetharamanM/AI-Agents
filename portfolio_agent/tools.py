"""Tools exposed to Claude. Each returns a JSON string.

Errors are returned as {"error": ...} rather than raised, so a single bad
ticker doesn't stop the whole analysis -- Claude sees the error and carries on.
"""

from __future__ import annotations

import json
from typing import Any

from anthropic import beta_tool

from . import analytics, data

_HOLDINGS_PATH = "holdings.csv"


def set_holdings_path(path: str) -> None:
    global _HOLDINGS_PATH
    _HOLDINGS_PATH = path


def _ok(payload: Any) -> str:
    return json.dumps(payload, default=str, ensure_ascii=False)


def _err(exc: Exception) -> str:
    return _ok({"error": f"{type(exc).__name__}: {exc}"})


def _resolve(symbol: str) -> str:
    """Accept 'RELIANCE', 'RELIANCE.NS' or a symbol from the holdings file."""
    symbol = symbol.strip().upper()
    try:
        h = data.load_holdings(_HOLDINGS_PATH)
        match = h.loc[h["symbol"] == symbol, "ticker"]
        if not match.empty:
            return match.iloc[0]
    except Exception:
        pass
    return data.to_ticker(symbol)


@beta_tool
def get_portfolio_holdings() -> str:
    """Get every holding in the user's portfolio with live price, invested amount,
    current value, profit/loss (INR and %), portfolio weight, sector and market-cap
    bucket, plus portfolio totals. Call this first."""
    try:
        h = data.load_holdings(_HOLDINGS_PATH)
        prices = data.latest_prices(h["ticker"].tolist())
        df = analytics.value_holdings(h, prices)
        df["sector"] = [data.info(t).get("sector") or "Unknown" for t in df["ticker"]]
        df["market_cap_bucket"] = [
            analytics.market_cap_bucket(data.info(t).get("marketCap")) for t in df["ticker"]
        ]
        cols = ["symbol", "ticker", "sector", "market_cap_bucket", "quantity", "avg_price",
                "current_price", "invested", "current_value", "pnl", "pnl_pct", "weight_pct"]
        invested, value = df["invested"].sum(), df["current_value"].sum()
        return _ok(
            {
                "currency": "INR",
                "holdings": df[cols].round(2).to_dict(orient="records"),
                "totals": {
                    "invested": round(invested, 2),
                    "current_value": round(value, 2),
                    "pnl": round(value - invested, 2),
                    "pnl_pct": round((value / invested - 1) * 100, 2) if invested else None,
                    "number_of_stocks": int(len(df)),
                },
                "missing_prices": df.loc[df["current_price"].isna(), "symbol"].tolist(),
            }
        )
    except Exception as e:
        return _err(e)


@beta_tool
def get_allocation_and_concentration() -> str:
    """Get portfolio allocation by sector and by market-cap bucket (large/mid/small,
    approximate), and concentration metrics: largest position, top-3 weight,
    Herfindahl index and effective number of stocks."""
    try:
        h = data.load_holdings(_HOLDINGS_PATH)
        df = analytics.value_holdings(h, data.latest_prices(h["ticker"].tolist()))
        df["sector"] = [data.info(t).get("sector") or "Unknown" for t in df["ticker"]]
        df["market_cap_bucket"] = [
            analytics.market_cap_bucket(data.info(t).get("marketCap")) for t in df["ticker"]
        ]
        return _ok(
            {
                "by_sector_pct": analytics.group_weights(df, "sector"),
                "by_market_cap_pct": analytics.group_weights(df, "market_cap_bucket"),
                "concentration": analytics.concentration(df.set_index("symbol")["weight_pct"]),
            }
        )
    except Exception as e:
        return _err(e)


@beta_tool
def get_portfolio_risk(period: str = "1y") -> str:
    """Get risk metrics for the current holdings over a past period, versus the
    NIFTY 50: annualised return and volatility, Sharpe ratio, beta, max drawdown,
    per-stock volatility and the most correlated pairs of holdings.

    Args:
        period: Lookback window. One of "6mo", "1y", "2y", "3y", "5y".
    """
    try:
        if period not in {"6mo", "1y", "2y", "3y", "5y"}:
            period = "1y"
        h = data.load_holdings(_HOLDINGS_PATH)
        tickers = h["ticker"].tolist()
        close = data.price_history(tickers + [data.BENCHMARK], period=period)
        quantities = dict(zip(h["ticker"], h["quantity"]))
        result = analytics.portfolio_risk(close.drop(columns=[data.BENCHMARK]), quantities,
                                          close[data.BENCHMARK])
        result["benchmark"] = "NIFTY 50"
        return _ok(result)
    except Exception as e:
        return _err(e)


@beta_tool
def get_technicals(symbol: str) -> str:
    """Get a technical snapshot for one stock: 50/200-day moving averages and trend,
    RSI(14), distance from 52-week high/low, and 1m/3m/6m/1y returns.

    Args:
        symbol: NSE symbol such as "RELIANCE" (".NS"/".BO" suffix optional).
    """
    try:
        ticker = _resolve(symbol)
        close = data.price_history([ticker], period="2y")[ticker]
        return _ok({"symbol": symbol.upper(), "ticker": ticker, **analytics.technicals(close)})
    except Exception as e:
        return _err(e)


_FUNDAMENTAL_FIELDS = {
    "longName": "name",
    "sector": "sector",
    "industry": "industry",
    "marketCap": "market_cap_inr",
    "trailingPE": "pe_trailing",
    "forwardPE": "pe_forward",
    "priceToBook": "price_to_book",
    "returnOnEquity": "roe",
    "returnOnAssets": "roa",
    "debtToEquity": "debt_to_equity",
    "profitMargins": "net_margin",
    "operatingMargins": "operating_margin",
    "revenueGrowth": "revenue_growth_yoy",
    "earningsGrowth": "earnings_growth_yoy",
    "dividendYield": "dividend_yield",
    "payoutRatio": "payout_ratio",
    "beta": "beta",
    "targetMeanPrice": "analyst_target_mean",
    "recommendationKey": "analyst_recommendation",
    "numberOfAnalystOpinions": "analyst_count",
    "currentPrice": "current_price",
}


@beta_tool
def get_fundamentals(symbol: str) -> str:
    """Get valuation and quality fundamentals for one stock: P/E, P/B, ROE, ROA,
    debt/equity, margins, revenue and earnings growth, dividend yield, market cap,
    and the analyst consensus target and rating. Ratios are decimals (0.15 = 15%)
    except debt_to_equity, which Yahoo reports as a percentage.

    Args:
        symbol: NSE symbol such as "TCS" (".NS"/".BO" suffix optional).
    """
    try:
        ticker = _resolve(symbol)
        raw = data.info(ticker)
        if not raw:
            return _ok({"symbol": symbol.upper(), "error": "No fundamentals returned by Yahoo Finance"})
        out = {new: raw.get(old) for old, new in _FUNDAMENTAL_FIELDS.items()}
        out["market_cap_bucket"] = analytics.market_cap_bucket(raw.get("marketCap"))
        if out.get("analyst_target_mean") and out.get("current_price"):
            out["upside_to_target_pct"] = round(
                (out["analyst_target_mean"] / out["current_price"] - 1) * 100, 2
            )
        return _ok({"symbol": symbol.upper(), "ticker": ticker, **out})
    except Exception as e:
        return _err(e)


@beta_tool
def get_recent_news(symbol: str) -> str:
    """Get recent news headlines for one stock, to explain big moves or flag events
    (results, management changes, regulatory action).

    Args:
        symbol: NSE symbol such as "INFY" (".NS"/".BO" suffix optional).
    """
    try:
        ticker = _resolve(symbol)
        return _ok({"symbol": symbol.upper(), "news": data.news(ticker)})
    except Exception as e:
        return _err(e)


ALL_TOOLS = [
    get_portfolio_holdings,
    get_allocation_and_concentration,
    get_portfolio_risk,
    get_technicals,
    get_fundamentals,
    get_recent_news,
]
