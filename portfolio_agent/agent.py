"""Indian stock portfolio analysis agent.

Usage:
    python -m portfolio_agent.agent                       # full review of holdings.csv
    python -m portfolio_agent.agent -q "Should I trim ITC?"
    python -m portfolio_agent.agent --holdings my.csv --effort medium
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import anthropic

from . import tools

MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """\
You are a disciplined equity research analyst reviewing an Indian retail investor's
stock portfolio (NSE/BSE, amounts in INR). You have tools that return live holdings,
allocation, risk metrics, technicals, fundamentals and news.

How to work:
- Start with get_portfolio_holdings, then allocation and risk. Pull technicals and
  fundamentals for every holding (call tools in parallel where you can), and news
  only for stocks with unusual moves or red flags.
- Use only numbers that the tools returned. Never invent prices, ratios or news.
  If a tool returns an error or missing data, say so and work with what you have.
- Judge each stock on both quality/valuation (fundamentals) and trend/momentum
  (technicals). Compare valuations against the stock's sector, not the whole market.
- Flag concentration risk (single stock > 15%, single sector > 30%), high
  correlation between holdings, and a beta well above 1.

Write the final answer as a Markdown report with these sections:
1. Snapshot - total invested, current value, P&L, number of stocks, benchmark comparison.
2. Allocation & concentration - sector and market-cap mix, what is over/under-weight.
3. Risk - volatility, beta, drawdown, Sharpe, correlated pairs, in plain language.
4. Stock-by-stock - one table row per holding: weight, P&L %, trend, RSI, P/E, ROE,
   view (Hold / Add on dips / Review / Trim) and a one-line reason.
5. Action items - at most 5 concrete, prioritised suggestions.
6. Data caveats - delayed data, missing fields, assumptions.

End with: "This is an automated analysis for educational purposes, not investment
advice. Consult a SEBI-registered investment adviser before acting."
"""

DEFAULT_QUESTION = "Give me a complete review of my portfolio."


def run(question: str, holdings: str, effort: str = "high", verbose: bool = True) -> str:
    tools.set_holdings_path(holdings)
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY

    runner = client.beta.messages.tool_runner(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        # If a request is declined by a safety classifier, retry on a fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        tools=tools.ALL_TOOLS,
        messages=[{"role": "user", "content": question}],
        max_iterations=30,
    )

    final = None
    for message in runner:
        final = message
        if verbose:
            for block in message.content:
                if block.type == "tool_use":
                    args = ", ".join(f"{k}={v!r}" for k, v in block.input.items())
                    print(f"  -> {block.name}({args})", file=sys.stderr)

    if final is None:
        raise RuntimeError("The agent returned no response.")
    if final.stop_reason == "refusal":
        raise RuntimeError(f"Request was declined: {final.stop_details}")
    if final.stop_reason == "max_tokens":
        print("Warning: report was cut off at max_tokens.", file=sys.stderr)

    return "\n".join(b.text for b in final.content if b.type == "text").strip()


def main() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    p = argparse.ArgumentParser(description="AI agent for Indian stock portfolio analysis")
    p.add_argument("-q", "--question", default=DEFAULT_QUESTION)
    p.add_argument("--holdings", default="holdings.csv", help="CSV: symbol,quantity,avg_price[,exchange]")
    p.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--out", default="reports", help="Directory for the Markdown report")
    p.add_argument("--quiet", action="store_true", help="Don't print tool calls")
    args = p.parse_args()

    if not Path(args.holdings).exists():
        sys.exit(f"Holdings file not found: {args.holdings}")

    print(f"Analysing {args.holdings} with {MODEL}...", file=sys.stderr)
    report = run(args.question, args.holdings, args.effort, verbose=not args.quiet)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"portfolio-report-{dt.datetime.now():%Y-%m-%d-%H%M}.md"
    path.write_text(report + "\n", encoding="utf-8")

    print(report)
    print(f"\nSaved to {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
