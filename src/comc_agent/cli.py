"""Typer CLI entry point."""
from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.table import Table

from . import engine, portfolio, scheduler, session
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
    """Show current inventory and cost basis."""
    rows = portfolio.open_positions()
    table = Table(title="Open positions")
    for col in ("listing_id", "title", "player", "cost_basis_usd", "current_list_price_usd", "status"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            str(r["listing_id"]),
            (r["title"] or "")[:60],
            r["player"] or "",
            f"${r['cost_basis_usd']:.2f}",
            f"${r['current_list_price_usd']:.2f}" if r["current_list_price_usd"] else "-",
            r["status"],
        )
    console.print(table)
    console.print(f"Cash deployed: ${portfolio.cash_spent():.2f} / ${settings.strategy.total_budget_usd:.2f}")


@app.command()
def run() -> None:
    """Start the scheduler loop (hourly scan, daily reprice)."""
    asyncio.run(scheduler.run_forever())


if __name__ == "__main__":
    app()
