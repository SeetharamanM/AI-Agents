"""MCP server exposing the portfolio tools to the Claude app (Claude Desktop).

Claude Desktop runs this as a local process. Claude does the reasoning under
your Claude subscription and calls these tools for data and maths, so no
Anthropic API key is needed.

Run manually (for testing):
    python -m portfolio_agent.mcp_server

Set PORTFOLIO_HOLDINGS to the absolute path of your holdings CSV.
See README.md -> "Use it from the Claude app" for the Claude Desktop config.
"""

from __future__ import annotations

import contextlib
import os
import sys

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from . import tools
from .agent import SYSTEM_PROMPT

tools.set_holdings_path(
    os.environ.get(
        "PORTFOLIO_HOLDINGS",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "holdings.csv"),
    )
)


def _run(tool, args: dict) -> str:
    # Claude Desktop talks to this server over stdout; anything a library prints
    # there (yfinance does) would corrupt the protocol, so send it to stderr.
    with contextlib.redirect_stdout(sys.stderr):
        return tool.call(args)


server = _Server(
    name="indian-portfolio-analyst",
    instructions=(
        "Tools for analysing the user's Indian (NSE/BSE) stock portfolio from their holdings CSV. "
        "Call get_portfolio_holdings first. All numbers are computed in Python; use them as-is."
    ),
)


@server.tool()
def get_portfolio_holdings() -> str:
    """Every holding with live price, invested amount, value, P&L, weight, sector,
    market-cap bucket, plus portfolio totals. Call this first."""
    return _run(tools.get_portfolio_holdings, {})


@server.tool()
def get_allocation_and_concentration() -> str:
    """Allocation by sector and market-cap bucket, plus concentration metrics
    (largest position, top-3 weight, Herfindahl index, effective number of stocks)."""
    return _run(tools.get_allocation_and_concentration, {})


@server.tool()
def get_portfolio_risk(period: str = "1y") -> str:
    """Risk vs NIFTY 50 over a lookback period ("6mo", "1y", "2y", "3y", "5y"):
    annualised return and volatility, Sharpe, beta, max drawdown, per-stock
    volatility and most-correlated pairs."""
    return _run(tools.get_portfolio_risk, {"period": period})


@server.tool()
def get_technicals(symbol: str) -> str:
    """50/200-DMA trend, RSI(14), 52-week high/low distance and 1m-1y returns for
    one NSE symbol, e.g. "RELIANCE"."""
    return _run(tools.get_technicals, {"symbol": symbol})


@server.tool()
def get_fundamentals(symbol: str) -> str:
    """P/E, P/B, ROE, debt/equity, margins, growth, dividend yield and analyst
    target for one NSE symbol, e.g. "TCS"."""
    return _run(tools.get_fundamentals, {"symbol": symbol})


@server.tool()
def get_recent_news(symbol: str) -> str:
    """Recent news headlines for one NSE symbol, e.g. "INFY"."""
    return _run(tools.get_recent_news, {"symbol": symbol})


@server.prompt()
def portfolio_review() -> str:
    """Full portfolio review using the analyst playbook."""
    return SYSTEM_PROMPT + "\n\nReview my portfolio now."


def main() -> None:
    server.run()  # stdio transport, which is what Claude Desktop uses


if __name__ == "__main__":
    main()
