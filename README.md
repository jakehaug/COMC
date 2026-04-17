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

## Quickstart (macOS)

You don't need to know Python. Just open Terminal, `cd` into this folder, and run:

```bash
./setup.sh        # one-time: installs Homebrew, Python, the agent, and a browser
./comc login      # opens a browser, sign into COMC once - the session is saved
./comc doctor     # checks that the agent can read COMC's pages
./comc scan       # dry-run: shows what it *would* buy, without buying
./comc scan --live  # actually buys (only do this after doctor looks good)
./comc portfolio  # shows your inventory and P&L
./comc run        # starts the hourly/daily autonomous loop
```

If `./setup.sh` fails, the most likely cause is a macOS security prompt asking
to allow Terminal to run downloaded scripts - accept and re-run.

## Setup (other platforms / manual)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
comc-agent login
comc-agent scan --dry-run
comc-agent run
```

## Commands

- `./comc login` - open a browser so you can log in once; session is persisted
- `./comc doctor` - verify the agent can read COMC; saves HTML snapshots to `logs/doctor/`
- `./comc scan` - dry-run: find buy candidates without buying
- `./comc scan --live` - actually buys the candidates
- `./comc reprice` - run the daily reprice + stop-loss sweep
- `./comc portfolio` - show current inventory, cost basis, realized + unrealized P&L
- `./comc run` - start the scheduler (hourly scan, daily reprice)

## Safety

COMC does not publish an API. This agent automates the website via a headful/headless browser. Use at your own risk; automation may violate COMC's ToS. Start with `--dry-run` until you've validated the buy signals against your own judgement.
