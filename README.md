# AI Agents — Indian Stock Portfolio Analyst

An AI agent built on Claude that reviews your NSE/BSE stock portfolio. It pulls
live prices, computes allocation, risk and technicals in Python, reads
fundamentals and news, and writes a Markdown report with a view on each stock.

## How it works

```
holdings.csv ─► Claude (agent loop) ──► tools ──► Yahoo Finance (.NS / .BO)
                    ▲                    │
                    └── tool results ◄───┘
                    │
                    ▼
        reports/portfolio-report-<date>.md
```

Claude decides which tools to call and in what order. All arithmetic (P&L, weights,
volatility, beta, RSI…) happens in Python (`portfolio_agent/analytics.py`). Claude
only interprets the numbers.

| Tool | What it returns |
|---|---|
| `get_portfolio_holdings` | Live price, invested, value, P&L, weight, sector, cap bucket |
| `get_allocation_and_concentration` | Sector and market-cap mix, top-3 weight, HHI, effective no. of stocks |
| `get_portfolio_risk` | Return, volatility, Sharpe, beta and max drawdown vs NIFTY 50; correlated pairs |
| `get_technicals` | 50/200 DMA trend, RSI(14), 52-week high/low, 1m–1y returns |
| `get_fundamentals` | P/E, P/B, ROE, D/E, margins, growth, dividend yield, analyst target |
| `get_recent_news` | Recent headlines for a stock |

## Setup

```bash
python -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

```bash
cp .env.example .env
```

Then put your Anthropic API key (from https://console.anthropic.com) in `.env`.

## Add your holdings

Edit `holdings.csv` (the sample is placeholder data):

```csv
symbol,quantity,avg_price,exchange
RELIANCE,40,2450.00,NSE
TCS,15,3500.00,NSE
```

- `symbol`: NSE symbol (`RELIANCE`) or BSE code (`500325` with `exchange=BSE`)
- `exchange`: optional, defaults to `NSE`
- Most brokers (Zerodha Console, Groww, INDmoney, Upstox) let you export holdings as CSV.
  Rename the columns to match.

## Run

Full portfolio review:

```bash
python -m portfolio_agent.agent
```

Ask a specific question:

```bash
python -m portfolio_agent.agent -q "Which of my stocks are overvalued vs their sector?"
```

Cheaper, faster run with a different holdings file:

```bash
python -m portfolio_agent.agent --holdings my_holdings.csv --effort medium
```

The report prints to the terminal and is saved under `reports/`.

## Tests

```bash
python -m pytest -q
```

The tests cover the analytics with synthetic data and need no network or API key.

## Extending it

- **More tools:** add a function with `@beta_tool` in `portfolio_agent/tools.py` and add it
  to `ALL_TOOLS`. The docstring becomes the description Claude sees.
- **Better Indian data:** swap `portfolio_agent/data.py` for a broker API (Zerodha Kite,
  Upstox, Angel One SmartAPI) for real-time prices and your live holdings.
- **Mutual funds:** add a tool backed by AMFI NAV data (https://www.amfiindia.com).
- **Schedule it:** run weekly with cron and email the report.

## Caveats

- Yahoo Finance data is delayed and sometimes incomplete for smaller Indian companies.
- Market-cap buckets use approximate INR thresholds, not SEBI's official ranking list.
- This is an educational tool, not investment advice. Consult a SEBI-registered
  investment adviser before acting on any output.
