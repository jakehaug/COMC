# COMC Trading Agent

Autonomous agent that buys and sells sports trading cards on [COMC](https://www.comc.com) by scanning listings against recent sold comps, executing trades that meet a configured risk profile, and managing the resulting inventory.

## Strategy (default)

| Rule | Value |
|------|-------|
| Style | Fast flips |
| Scope | Modern + vintage sports, $1-25 per card |
| Budget | $50 total, $10/card cap |
| Concentration | Max 20% of portfolio per player |
| Liquidity gate | >=5 sales in last 90 days |
| Buy signal | Ask >=25% below median comp |
| List price | Lowest recent comp |
| Reprice | -5% weekly while unsold |
| Stop-loss | Liquidate at -20% after 60 days unsold |
| Comps source | COMC sold history |
| Scan cadence | Hourly deal scan, daily reprice sweep |
| Auth | Persistent Playwright browser session |

Override any of these in `config.yaml` or environment variables.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium

# One-time interactive login (saves session to ./browser_state/)
comc-agent login

# Dry-run: scan deals and show recommendations without buying
comc-agent scan --dry-run

# Run the full autonomous loop
comc-agent run
```

## Commands

- `comc-agent login` - open a browser so you can log in once; session is persisted
- `comc-agent scan [--dry-run]` - find buy candidates
- `comc-agent buy <listing-id>` - execute a single buy
- `comc-agent reprice` - run the daily reprice + stop-loss sweep
- `comc-agent portfolio` - show current inventory, cost basis, P&L
- `comc-agent run` - start the scheduler (hourly scan, daily reprice)

## Safety

COMC does not publish an API. This agent automates the website via a headful/headless browser. Use at your own risk; automation may violate COMC's ToS. Start with `--dry-run` until you've validated the buy signals against your own judgement.
