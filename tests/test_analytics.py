import numpy as np
import pandas as pd
import pytest

from portfolio_agent import analytics, data


def test_to_ticker():
    assert data.to_ticker("reliance") == "RELIANCE.NS"
    assert data.to_ticker("500325", "BSE") == "500325.BO"
    assert data.to_ticker("TCS.NS") == "TCS.NS"
    assert data.to_ticker("^NSEI") == "^NSEI"


def test_load_holdings(tmp_path):
    f = tmp_path / "h.csv"
    f.write_text("Symbol,Quantity,Avg_Price\nitc,10,400\n")
    h = data.load_holdings(f)
    assert h.loc[0, "ticker"] == "ITC.NS"
    with pytest.raises(ValueError):
        (tmp_path / "bad.csv").write_text("symbol,qty\nA,1\n")
        data.load_holdings(tmp_path / "bad.csv")


def test_value_holdings_and_concentration():
    h = pd.DataFrame({"ticker": ["A", "B"], "quantity": [10, 10], "avg_price": [100, 100]})
    df = analytics.value_holdings(h, {"A": 150, "B": 50})
    assert df["pnl"].tolist() == [500, -500]
    assert df["weight_pct"].tolist() == [75, 25]
    c = analytics.concentration(df["weight_pct"])
    assert c["hhi"] == pytest.approx(0.625)
    assert c["effective_number_of_stocks"] == pytest.approx(1.6)


def test_market_cap_bucket():
    assert analytics.market_cap_bucket(2e5 * analytics.CRORE) == "Large cap"
    assert analytics.market_cap_bucket(5e4 * analytics.CRORE) == "Mid cap"
    assert analytics.market_cap_bucket(1e3 * analytics.CRORE) == "Small cap"
    assert analytics.market_cap_bucket(None) == "Unknown"


def test_max_drawdown():
    assert analytics.max_drawdown(pd.Series([100, 120, 60, 90])) == pytest.approx(-50)


def test_rsi_extremes():
    up = pd.Series(np.arange(1, 50, dtype=float))
    assert analytics.rsi(up) == 100.0
    down = pd.Series(np.arange(50, 1, -1, dtype=float))
    assert analytics.rsi(down) < 1


def _prices(n=300, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2025-01-01", periods=n)
    bench = pd.Series(100 * np.cumprod(1 + rng.normal(0.0005, 0.01, n)), idx)
    a = 100 * np.cumprod(1 + 2 * bench.pct_change().fillna(0).values)  # beta 2 to benchmark
    b = 100 * np.cumprod(1 + rng.normal(0.0003, 0.015, n))
    return pd.DataFrame({"A": a, "B": b}, idx), bench


def test_portfolio_risk_beta():
    close, bench = _prices()
    r = analytics.portfolio_risk(close[["A"]], {"A": 1}, bench)
    assert r["beta_vs_benchmark"] == pytest.approx(2.0, abs=0.01)
    assert r["max_drawdown_pct"] <= 0
    r2 = analytics.portfolio_risk(close, {"A": 5, "B": 5}, bench)
    assert r2["most_correlated_pairs"][0]["pair"] == "A / B"


def test_technicals_uptrend():
    idx = pd.bdate_range("2024-01-01", periods=300)
    close = pd.Series(np.linspace(100, 200, 300), idx)
    t = analytics.technicals(close)
    assert t["trend"].startswith("Uptrend")
    assert t["golden_cross_active"] is True
    assert t["pct_below_52w_high"] == 0
    assert t["returns_pct"]["1y"] > 0
