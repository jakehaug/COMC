"""Portfolio / budget / concentration / comps-cache tests.

Each test gets an isolated SQLite DB via monkeypatching runtime.db_path.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from comc_agent import portfolio
from comc_agent.config import settings
from comc_agent.models import Listing, Sale


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    db = tmp_path / "agent.db"
    monkeypatch.setattr(settings.runtime, "db_path", db)
    monkeypatch.setattr(settings.runtime, "data_dir", tmp_path)
    monkeypatch.setattr(settings.runtime, "logs_dir", tmp_path / "logs")
    monkeypatch.setattr(settings.runtime, "browser_state_dir", tmp_path / "bs")
    yield


def _listing(listing_id="abc", player="Mike Trout", price=5.0) -> Listing:
    return Listing(
        listing_id=listing_id,
        title=f"card {listing_id}",
        player=player,
        year=2020,
        set_name="Topps Chrome",
        card_number="1",
        sport="baseball",
        ask_price_usd=price,
        url=f"https://www.comc.com/Cards/{listing_id}",
    )


def test_card_signature_is_stable():
    a = _listing(listing_id="1")
    b = _listing(listing_id="2")  # different listing, same card
    assert portfolio.card_signature(a) == portfolio.card_signature(b)


def test_record_purchase_and_open_positions():
    portfolio.record_purchase(_listing("1"), 5.0)
    portfolio.record_purchase(_listing("2", price=7.0), 7.0)
    rows = portfolio.open_positions()
    assert len(rows) == 2
    assert portfolio.cash_spent() == pytest.approx(12.0)


def test_budget_cap_enforced():
    # default budget is $50
    portfolio.record_purchase(_listing("1", price=45.0), 45.0)
    assert portfolio.can_afford(4.99)
    assert not portfolio.can_afford(6.0)


def test_player_concentration_cap():
    # 20% of $50 = $10 max per player
    portfolio.record_purchase(_listing("1", player="LeBron", price=8.0), 8.0)
    assert portfolio.within_player_limit("LeBron", 1.50)  # $9.50 <= $10
    assert not portfolio.within_player_limit("LeBron", 5.0)  # $13 > $10
    # Different player unaffected
    assert portfolio.within_player_limit("Curry", 9.0)


def test_comps_cache_roundtrip():
    sales = [Sale(sold_price_usd=10.0, sold_at=datetime.utcnow())]
    portfolio.put_cached_comps("sig-1", sales)
    got = portfolio.get_cached_comps("sig-1")
    assert got is not None and len(got) == 1
    assert got[0].sold_price_usd == 10.0


def test_comps_cache_miss():
    assert portfolio.get_cached_comps("never-stored") is None


def test_record_listing_transitions_state():
    portfolio.record_purchase(_listing("1"), 5.0)
    portfolio.record_listing("1", 8.00)
    rows = portfolio.open_positions()
    assert rows[0]["status"] == "listed"
    assert rows[0]["current_list_price_usd"] == 8.00


def test_record_sale_closes_position():
    portfolio.record_purchase(_listing("1"), 5.0)
    portfolio.record_sale("1", 10.0)
    assert portfolio.open_positions() == []
