"""Execute purchases and manage listings on COMC.

All browser interactions route through the `human` helpers so actions have
natural timing and movement. Selectors are isolated at the top of each
function and will need tuning against the live site.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Sequence

from playwright.async_api import Page

from . import portfolio, valuation
from .config import settings
from .human import hover_and_click, pause, type_text, warmup_browse, within_active_hours
from .models import BuyCandidate, Listing


WARMUP_URLS = [
    "{base}/",
    "{base}/Cards",
    "{base}/Help",
]


class TradingPaused(Exception):
    """Raised when we hit a captcha, rate limit, or outside-hours window."""


def _assert_active() -> None:
    if not within_active_hours():
        raise TradingPaused("Outside active trading hours; deferring.")


async def _check_for_friction(page: Page) -> None:
    """Abort the whole session if COMC shows a captcha or block page."""
    text = (await page.content()).lower()
    flags = ("captcha", "access denied", "rate limit", "too many requests", "unusual activity")
    if any(f in text for f in flags):
        raise TradingPaused("Detected captcha / rate-limit; pausing agent.")


# --- Buy ---------------------------------------------------------------

async def execute_buy(page: Page, candidate: BuyCandidate) -> bool:
    """Navigate to the listing, add to cart, and check out. Returns True on success."""
    _assert_active()
    l = candidate.listing

    if not portfolio.can_afford(l.ask_price_usd):
        portfolio.log_event("skip_buy_budget", {"listing_id": l.listing_id})
        return False
    if not portfolio.within_player_limit(l.player, l.ask_price_usd):
        portfolio.log_event("skip_buy_concentration", {"listing_id": l.listing_id, "player": l.player})
        return False

    warmup = [u.format(base=settings.runtime.base_url) for u in WARMUP_URLS]
    await warmup_browse(page, warmup)

    await page.goto(l.url, wait_until="domcontentloaded")
    await pause()
    await _check_for_friction(page)

    add_to_cart = page.get_by_role("button", name=lambda s: "add to cart" in s.lower())
    if await add_to_cart.count() == 0:
        portfolio.log_event("buy_failed_no_button", {"listing_id": l.listing_id})
        return False
    await hover_and_click(page, add_to_cart.first)

    await page.goto(f"{settings.runtime.base_url}/Cart", wait_until="domcontentloaded")
    await pause()
    await _check_for_friction(page)

    checkout = page.get_by_role("button", name=lambda s: "checkout" in s.lower())
    if await checkout.count() == 0:
        portfolio.log_event("buy_failed_no_checkout", {"listing_id": l.listing_id})
        return False
    await hover_and_click(page, checkout.first)
    await pause(1.5)

    confirm = page.get_by_role("button", name=lambda s: any(k in s.lower() for k in ("place order", "confirm", "buy")))
    if await confirm.count() == 0:
        portfolio.log_event("buy_failed_no_confirm", {"listing_id": l.listing_id})
        return False
    await hover_and_click(page, confirm.first)
    await page.wait_for_load_state("domcontentloaded")
    await pause(2.0)

    portfolio.record_purchase(l, l.ask_price_usd)
    return True


# --- List / reprice / liquidate ---------------------------------------

async def list_card_for_sale(page: Page, listing_id: str, price: float) -> bool:
    _assert_active()
    # COMC's "Set Price" endpoint for user-owned cards.
    url = f"{settings.runtime.base_url}/Users/Inventory/SetPrice?ListingId={listing_id}"
    await page.goto(url, wait_until="domcontentloaded")
    await pause()
    await _check_for_friction(page)

    price_input = page.get_by_label("Price").or_(page.get_by_placeholder("Price")).first
    await price_input.fill("")
    await type_text(page, price_input, f"{price:.2f}")

    save = page.get_by_role("button", name=lambda s: any(k in s.lower() for k in ("save", "list", "update")))
    if await save.count() == 0:
        return False
    await hover_and_click(page, save.first)
    await pause(1.2)
    portfolio.record_listing(listing_id, price)
    return True


async def reprice_stale_listings(page: Page) -> None:
    """Weekly drop + 60-day auto-liquidate."""
    _assert_active()
    for row in portfolio.open_positions():
        last = datetime.fromisoformat(row["last_repriced_at"]) if row["last_repriced_at"] else datetime.fromisoformat(row["bought_at"])
        age_days = (datetime.utcnow() - datetime.fromisoformat(row["bought_at"])).days
        current = row["current_list_price_usd"] or row["cost_basis_usd"]

        if age_days >= settings.strategy.liquidate_after_days:
            new_price = valuation.liquidation_price(row["cost_basis_usd"])
            await list_card_for_sale(page, row["listing_id"], new_price)
            portfolio.log_event("liquidate", {"listing_id": row["listing_id"], "price": new_price})
            continue

        if datetime.utcnow() - last >= timedelta(days=7):
            new_price = valuation.reprice_after_week(current)
            await list_card_for_sale(page, row["listing_id"], new_price)


# --- Scan + act --------------------------------------------------------

async def scan_and_buy(page: Page, candidates: Sequence[BuyCandidate], dry_run: bool = False) -> list[BuyCandidate]:
    """Filter candidates through budget/concentration and (optionally) execute buys."""
    executed: list[BuyCandidate] = []
    bought_today = 0
    for c in sorted(candidates, key=lambda c: -c.expected_net_profit_usd):
        if bought_today >= settings.stealth.max_buys_per_day:
            break
        if not portfolio.can_afford(c.listing.ask_price_usd):
            continue
        if not portfolio.within_player_limit(c.listing.player, c.listing.ask_price_usd):
            continue
        if dry_run:
            executed.append(c)
            continue
        ok = await execute_buy(page, c)
        if ok:
            executed.append(c)
            bought_today += 1
            await pause(3.0)  # breathe between purchases
    return executed
