"""High-level orchestration: one scan cycle, one reprice cycle."""
from __future__ import annotations

import random
from typing import Sequence

from playwright.async_api import Page

from . import portfolio, scraper, trader, valuation
from .config import settings
from .models import BuyCandidate
from .human import pause


# Short, targeted query set so our traffic looks like a collector browsing
# specific interests - not a bot crawling everything. Rotate and jitter these.
DEFAULT_QUERIES: tuple[str, ...] = (
    "rookie card",
    "topps chrome",
    "panini prizm",
    "bowman chrome",
    "upper deck young guns",
    "donruss optic",
)


async def find_candidates(page: Page, queries: Sequence[str] | None = None) -> list[BuyCandidate]:
    queries = list(queries or DEFAULT_QUERIES)
    random.shuffle(queries)
    queries = queries[: max(1, len(queries) // 2)]  # sample a subset per scan

    candidates: list[BuyCandidate] = []
    for q in queries:
        listings = await scraper.search_listings(page, query=q)
        for listing in listings:
            # Enrich every listing that looks in-price-band before spending
            # a round-trip on sold history.
            if not valuation.in_price_band(listing):
                continue
            detailed = await scraper.fetch_listing_detail(page, listing)
            if not valuation.in_scope(detailed):
                continue

            sig = portfolio.card_signature(detailed)
            sales = portfolio.get_cached_comps(sig)
            if sales is None:
                sales = await scraper.fetch_sold_history(page, detailed)
                portfolio.put_cached_comps(sig, sales)

            cand = valuation.evaluate_buy(detailed, sales)
            if cand is not None:
                candidates.append(cand)
            await pause(0.8)
    return candidates


async def scan_cycle(page: Page, dry_run: bool = False) -> dict:
    candidates = await find_candidates(page)
    executed = await trader.scan_and_buy(page, candidates, dry_run=dry_run)
    return {
        "candidates_found": len(candidates),
        "buys_executed": len(executed),
        "cash_spent": portfolio.cash_spent(),
        "budget": settings.strategy.total_budget_usd,
    }


async def reprice_cycle(page: Page) -> dict:
    await trader.reprice_stale_listings(page)
    return {"open_positions": len(portfolio.open_positions())}
