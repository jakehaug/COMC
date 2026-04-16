"""Typer CLI entry point."""
from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.table import Table

from . import doctor as doctor_mod, engine, portfolio, scheduler, session, valuation
from .config import settings


app = typer.Typer(help="COMC autonomous trading agent")
console = Console()


@app.command()
def login() -> None:
    """One-time interactive login. Saves the browser session for future runs."""
    asyncio.run(session.interactive_login())


@app.command()
def scan(dry_run: bool = typer.Option(True, "--dry-run/--live", help="If --live, actually buys.")) -> None:
    """Scan for buy candidates. Defaults to dry-run."""
    async def _go():
        async with session.browser_session() as (_ctx, page):
            if not await session.is_logged_in(page):
                console.print("[red]Not logged in.[/red] Run `comc-agent login` first.")
                raise typer.Exit(code=1)
            result = await engine.scan_cycle(page, dry_run=dry_run)
            console.print(result)
    asyncio.run(_go())


@app.command()
def reprice() -> None:
    """Run the reprice + stop-loss sweep once."""
    async def _go():
        async with session.browser_session() as (_ctx, page):
            result = await engine.reprice_cycle(page)
            console.print(result)
    asyncio.run(_go())


@app.command(name="portfolio")
def show_portfolio() -> None:
    """Show current inventory, cost basis, and realized P&L."""
    rows = portfolio.open_positions()
    table = Table(title="Open positions")
    for col in ("listing_id", "title", "player", "cost_basis", "list_price", "unrealized", "status"):
        table.add_column(col)
    for r in rows:
        list_price = r["current_list_price_usd"]
        unrealized = (valuation.net_proceeds(list_price) - r["cost_basis_usd"]) if list_price else None
        table.add_row(
            str(r["listing_id"]),
            (r["title"] or "")[:50],
            r["player"] or "",
            f"${r['cost_basis_usd']:.2f}",
            f"${list_price:.2f}" if list_price else "-",
            f"${unrealized:+.2f}" if unrealized is not None else "-",
            r["status"],
        )
    console.print(table)

    realized = portfolio.realized_pnl_total()
    closed = len(portfolio.closed_positions())
    console.print(
        f"Cash deployed: ${portfolio.cash_spent():.2f} / "
        f"${settings.strategy.total_budget_usd:.2f}    "
        f"Realized P&L: ${realized:+.2f} over {closed} closed positions"
    )


@app.command()
def doctor() -> None:
    """Check that our DOM selectors still match COMC's live site.

    Saves HTML snapshots to logs/doctor/ for selector tuning.
    """
    async def _go():
        report = await doctor_mod.run_diagnostics()
        for entry in report:
            console.print(entry)
    asyncio.run(_go())


@app.command()
def run() -> None:
    """Start the scheduler loop (hourly scan, daily reprice)."""
    asyncio.run(scheduler.run_forever())


if __name__ == "__main__":
    app()
