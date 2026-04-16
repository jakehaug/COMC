"""Turn listings + sold history into buy/sell decisions."""
from __future__ import annotations

from statistics import median

from .config import settings
from .models import BuyCandidate, CompStats, Listing, Sale


# COMC takes a ~20% seller fee on sales within the marketplace plus a flat
# per-card processing fee. Numbers approximate COMC's public fee schedule for
# standard sellers. We use these to estimate *net* profit when evaluating a buy.
COMC_SELLER_FEE_PCT = 0.20
COMC_PROCESSING_FEE_USD = 0.25


def compute_comps(sales: list[Sale], window_days: int = 90) -> CompStats | None:
    if not sales:
        return None
    prices = [s.sold_price_usd for s in sales]
    return CompStats(
        sample_size=len(prices),
        median_usd=median(prices),
        lowest_usd=min(prices),
        highest_usd=max(prices),
        window_days=window_days,
        source="comc_sold",
    )


def in_price_band(listing: Listing) -> bool:
    s = settings.strategy
    return s.min_card_price_usd <= listing.ask_price_usd <= s.max_card_price_usd


def in_scope(listing: Listing) -> bool:
    s = settings.strategy
    if listing.ask_price_usd > s.per_card_cap_usd:
        return False
    if listing.sport and listing.sport.lower() not in {sp.lower() for sp in s.allowed_sports}:
        return False
    if listing.year:
        is_modern = listing.year >= 2000
        if is_modern and not s.allow_modern:
            return False
        if not is_modern and not s.allow_vintage:
            return False
    return True


def evaluate_buy(listing: Listing, sales: list[Sale]) -> BuyCandidate | None:
    """Return a BuyCandidate if `listing` passes all gates, else None."""
    if not in_price_band(listing) or not in_scope(listing):
        return None
    comps = compute_comps(sales)
    if comps is None or not comps.is_liquid_enough:
        return None

    discount = 1.0 - (listing.ask_price_usd / comps.median_usd)
    if discount < settings.strategy.min_discount_vs_comp_pct:
        return None

    # Expected net = selling at lowest comp, minus fees, minus ask price.
    gross_sale = comps.lowest_usd
    net_sale = gross_sale * (1 - COMC_SELLER_FEE_PCT) - COMC_PROCESSING_FEE_USD
    expected_profit = net_sale - listing.ask_price_usd
    if expected_profit <= 0:
        return None

    reason = (
        f"ask ${listing.ask_price_usd:.2f} vs median comp ${comps.median_usd:.2f} "
        f"({discount:.0%} below); {comps.sample_size} sales; "
        f"est. net profit ${expected_profit:.2f}"
    )
    return BuyCandidate(
        listing=listing,
        comps=comps,
        discount_pct=discount,
        expected_net_profit_usd=expected_profit,
        reason=reason,
    )


def list_price_for(comps: CompStats) -> float:
    """Price we should list an owned card at, given fresh comps."""
    if settings.strategy.list_price_basis == "median_comp":
        return round(comps.median_usd, 2)
    return round(comps.lowest_usd, 2)


def reprice_after_week(current_price: float) -> float:
    """Apply the weekly drop."""
    return round(current_price * (1 - settings.strategy.weekly_price_drop_pct), 2)


def liquidation_price(cost_basis: float) -> float:
    return round(cost_basis * (1 - settings.strategy.liquidate_loss_pct), 2)


def net_proceeds(sale_price: float) -> float:
    """What you actually pocket from a sale, after COMC fees."""
    return sale_price * (1 - COMC_SELLER_FEE_PCT) - COMC_PROCESSING_FEE_USD


def realized_pnl(cost_basis: float, sale_price: float) -> float:
    return net_proceeds(sale_price) - cost_basis
