"""Typed domain objects passed between modules."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Listing(BaseModel):
    """A card currently for sale on COMC."""

    listing_id: str
    title: str
    player: str | None = None
    year: int | None = None
    set_name: str | None = None
    card_number: str | None = None
    sport: str | None = None
    graded: bool = False
    grade: str | None = None
    ask_price_usd: float
    seller: str | None = None
    url: str
    image_url: str | None = None
    scraped_at: datetime = Field(default_factory=datetime.utcnow)


class Sale(BaseModel):
    """One historical sale used for comps."""

    sold_price_usd: float
    sold_at: datetime
    source: Literal["comc_sold", "ebay_sold"] = "comc_sold"


class CompStats(BaseModel):
    """Aggregate comp statistics for a specific card."""

    sample_size: int
    median_usd: float
    lowest_usd: float
    highest_usd: float
    window_days: int
    source: str

    @property
    def is_liquid_enough(self) -> bool:
        from .config import settings
        return (
            self.sample_size >= settings.strategy.min_sales_last_90d
            and self.window_days <= 90
        )


class BuyCandidate(BaseModel):
    listing: Listing
    comps: CompStats
    discount_pct: float  # 0.30 == 30% below median comp
    expected_net_profit_usd: float  # after COMC seller fees (~20%)
    reason: str  # human-readable explanation
