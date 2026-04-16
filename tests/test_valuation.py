"""Smoke tests for the pure-logic modules (no browser needed)."""
from __future__ import annotations

from datetime import datetime

from comc_agent.models import Listing, Sale
from comc_agent.valuation import compute_comps, evaluate_buy, reprice_after_week, liquidation_price


def _listing(**overrides) -> Listing:
    base = dict(
        listing_id="123",
        title="2020 Topps Chrome Mike Trout",
        player="Mike Trout",
        year=2020,
        set_name="Topps Chrome",
        card_number="1",
        sport="baseball",
        ask_price_usd=5.00,
        url="https://www.comc.com/Cards/123",
    )
    base.update(overrides)
    return Listing(**base)


def _sales(prices: list[float]) -> list[Sale]:
    return [Sale(sold_price_usd=p, sold_at=datetime.utcnow()) for p in prices]


def test_compute_comps_stats():
    comps = compute_comps(_sales([8, 10, 12, 9, 11]))
    assert comps.sample_size == 5
    assert comps.median_usd == 10
    assert comps.lowest_usd == 8


def test_evaluate_buy_accepts_discounted_card():
    listing = _listing(ask_price_usd=5.0)
    sales = _sales([10, 11, 12, 9, 10])  # median 10
    c = evaluate_buy(listing, sales)
    assert c is not None
    assert c.discount_pct >= 0.25
    assert c.expected_net_profit_usd > 0


def test_evaluate_buy_rejects_thin_liquidity():
    listing = _listing(ask_price_usd=5.0)
    sales = _sales([10, 11])  # only 2 sales, below min_sales_last_90d
    assert evaluate_buy(listing, sales) is None


def test_evaluate_buy_rejects_non_discounted():
    listing = _listing(ask_price_usd=9.5)
    sales = _sales([10, 10, 10, 10, 10])
    assert evaluate_buy(listing, sales) is None


def test_reprice_drops_5_percent():
    assert reprice_after_week(10.00) == 9.50


def test_liquidation_price():
    assert liquidation_price(10.00) == 8.00
