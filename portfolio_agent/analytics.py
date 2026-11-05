"""Pure portfolio maths. No network calls here, so everything is unit-testable.

The agent does the numbers in Python and lets Claude interpret them -- LLMs
should not be trusted to do arithmetic on price series.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252
# Approximate Indian risk-free rate (91-day T-bill). Override via function args.
DEFAULT_RISK_FREE = 0.065

# Approximate SEBI-style buckets by market cap in INR crore.
# SEBI actually ranks by position (top 100 / 101-250 / rest); these thresholds
# are a rough proxy for when the ranking list isn't available.
LARGE_CAP_CRORE = 100_000
MID_CAP_CRORE = 30_000
CRORE = 10_000_000


def market_cap_bucket(market_cap_inr: float | None) -> str:
    if market_cap_inr is None or (isinstance(market_cap_inr, float) and np.isnan(market_cap_inr)):
        return "Unknown"
    crore = market_cap_inr / CRORE
    if crore >= LARGE_CAP_CRORE:
        return "Large cap"
    if crore >= MID_CAP_CRORE:
        return "Mid cap"
    return "Small cap"


def value_holdings(holdings: pd.DataFrame, prices: dict[str, float]) -> pd.DataFrame:
    """Add current price, value, P&L and weight columns.

    holdings needs columns: ticker, quantity, avg_price.
    """
    df = holdings.copy()
    df["current_price"] = df["ticker"].map(prices).astype(float)
    df["invested"] = df["quantity"] * df["avg_price"]
    df["current_value"] = df["quantity"] * df["current_price"]
    df["pnl"] = df["current_value"] - df["invested"]
    df["pnl_pct"] = df["pnl"] / df["invested"] * 100
    total = df["current_value"].sum()
    df["weight_pct"] = df["current_value"] / total * 100 if total else np.nan
    return df


def concentration(weights_pct: pd.Series) -> dict:
    """Herfindahl index and effective number of holdings."""
    w = weights_pct.dropna() / 100
    hhi = float((w**2).sum())
    return {
        "hhi": round(hhi, 4),
        "effective_number_of_stocks": round(1 / hhi, 2) if hhi else None,
        "largest_position_pct": round(float(weights_pct.max()), 2),
        "top3_pct": round(float(weights_pct.nlargest(3).sum()), 2),
    }


def group_weights(df: pd.DataFrame, column: str) -> dict[str, float]:
    return (
        df.groupby(column)["weight_pct"].sum().sort_values(ascending=False).round(2).to_dict()
    )


def daily_returns(close: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    return close.pct_change(fill_method=None).dropna(how="all")


def max_drawdown(series: pd.Series) -> float:
    """Max peak-to-trough decline of a price or value series, as a negative %."""
    s = series.dropna()
    if s.empty:
        return float("nan")
    running_max = s.cummax()
    return float(((s / running_max) - 1).min() * 100)


def portfolio_risk(
    close: pd.DataFrame,
    quantities: dict[str, float],
    benchmark: pd.Series,
    risk_free: float = DEFAULT_RISK_FREE,
) -> dict:
    """Risk of the *current* holdings replayed over the price history.

    close: daily close prices, one column per ticker.
    quantities: ticker -> number of shares held.
    benchmark: daily close of the benchmark index (e.g. NIFTY 50).
    """
    tickers = [t for t in quantities if t in close.columns]
    close = close[tickers].ffill().dropna(how="any")
    value = (close * pd.Series(quantities)[tickers]).sum(axis=1)

    port_ret = daily_returns(value)
    bench_ret = daily_returns(benchmark.reindex(value.index).ffill())
    aligned = pd.concat([port_ret, bench_ret], axis=1, keys=["p", "b"]).dropna()

    ann_ret = float((1 + port_ret).prod() ** (TRADING_DAYS / max(len(port_ret), 1)) - 1)
    ann_vol = float(port_ret.std() * np.sqrt(TRADING_DAYS))
    beta = float(aligned["p"].cov(aligned["b"]) / aligned["b"].var()) if len(aligned) > 2 else float("nan")
    bench_ann_ret = float((1 + aligned["b"]).prod() ** (TRADING_DAYS / max(len(aligned), 1)) - 1)

    stock_ret = daily_returns(close)
    stock_vol = (stock_ret.std() * np.sqrt(TRADING_DAYS) * 100).round(2).to_dict()

    corr = stock_ret.corr()
    pairs = []
    for i, a in enumerate(corr.columns):
        for b in corr.columns[i + 1 :]:
            pairs.append((a, b, float(corr.loc[a, b])))
    pairs.sort(key=lambda p: p[2], reverse=True)

    return {
        "period_days": int(len(port_ret)),
        "annualised_return_pct": round(ann_ret * 100, 2),
        "benchmark_annualised_return_pct": round(bench_ann_ret * 100, 2),
        "annualised_volatility_pct": round(ann_vol * 100, 2),
        "sharpe_ratio": round((ann_ret - risk_free) / ann_vol, 2) if ann_vol else None,
        "beta_vs_benchmark": round(beta, 2),
        "max_drawdown_pct": round(max_drawdown(value), 2),
        "per_stock_volatility_pct": stock_vol,
        "most_correlated_pairs": [
            {"pair": f"{a} / {b}", "correlation": round(c, 2)} for a, b, c in pairs[:3]
        ],
        "risk_free_rate_assumed_pct": risk_free * 100,
    }


def rsi(close: pd.Series, period: int = 14) -> float:
    """Wilder's RSI of the last bar."""
    delta = close.diff().dropna()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    last_loss = loss.iloc[-1]
    if last_loss == 0:
        return 100.0
    rs = gain.iloc[-1] / last_loss
    return float(100 - 100 / (1 + rs))


def _pct_return(close: pd.Series, days: int) -> float | None:
    if len(close) <= days:
        return None
    return round(float(close.iloc[-1] / close.iloc[-1 - days] - 1) * 100, 2)


def technicals(close: pd.Series) -> dict:
    """Trend and momentum snapshot from ~1y+ of daily closes."""
    close = close.dropna()
    last = float(close.iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
    sma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None
    window = close.iloc[-TRADING_DAYS:]
    high_52w, low_52w = float(window.max()), float(window.min())

    if sma50 and sma200:
        if last > sma50 > sma200:
            trend = "Uptrend (price > 50DMA > 200DMA)"
        elif last < sma50 < sma200:
            trend = "Downtrend (price < 50DMA < 200DMA)"
        else:
            trend = "Mixed / sideways"
    else:
        trend = "Insufficient history"

    r = rsi(close)
    return {
        "last_close": round(last, 2),
        "sma_50": round(sma50, 2) if sma50 else None,
        "sma_200": round(sma200, 2) if sma200 else None,
        "trend": trend,
        "golden_cross_active": bool(sma50 and sma200 and sma50 > sma200),
        "rsi_14": round(r, 1),
        "rsi_signal": "Overbought" if r > 70 else "Oversold" if r < 30 else "Neutral",
        "high_52w": round(high_52w, 2),
        "low_52w": round(low_52w, 2),
        "pct_below_52w_high": round((1 - last / high_52w) * 100, 2),
        "returns_pct": {
            "1m": _pct_return(close, 21),
            "3m": _pct_return(close, 63),
            "6m": _pct_return(close, 126),
            "1y": _pct_return(close, 252),
        },
    }
