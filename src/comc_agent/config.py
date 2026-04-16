"""Strategy config and runtime settings.

Defaults encode the rulebook agreed with the user. Override via env vars
(prefix COMC_) or by passing a different Settings() instance.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


REPO_ROOT = Path(__file__).resolve().parents[2]


class Strategy(BaseSettings):
    """Trading rules. Every knob the agent uses is here - no magic numbers elsewhere."""

    model_config = SettingsConfigDict(env_prefix="COMC_STRATEGY_", extra="ignore")

    # Portfolio
    total_budget_usd: float = 50.0
    per_card_cap_usd: float = 10.0
    min_card_price_usd: float = 1.0
    max_card_price_usd: float = 25.0
    max_player_concentration_pct: float = 0.20  # 20% of portfolio in any single player

    # Buy signal
    min_sales_last_90d: int = 5
    min_discount_vs_comp_pct: float = 0.25  # 25% below median comp
    comp_source: Literal["comc_sold", "ebay_sold", "blended"] = "comc_sold"

    # Sell / reprice
    list_price_basis: Literal["lowest_comp", "median_comp"] = "lowest_comp"
    weekly_price_drop_pct: float = 0.05  # -5% every 7 days unsold
    liquidate_after_days: int = 60
    liquidate_loss_pct: float = 0.20  # sell at cost_basis * (1 - 0.20)

    # Scope
    allow_modern: bool = True    # 2000+
    allow_vintage: bool = True   # pre-2000
    allowed_sports: tuple[str, ...] = (
        "baseball", "basketball", "football", "hockey", "soccer",
    )


class StealthConfig(BaseSettings):
    """Anti-detection knobs. Defaults chosen to pass as human."""

    model_config = SettingsConfigDict(env_prefix="COMC_STEALTH_", extra="ignore")

    headless: bool = False  # headful is harder to detect
    use_stealth_patches: bool = True
    min_action_delay_ms: int = 800
    max_action_delay_ms: int = 3000
    typing_cwpm: int = 240  # chars-per-minute (~48 wpm)
    warmup_pages_before_action: int = 2
    viewport_width: int = 1440
    viewport_height: int = 900
    locale: str = "en-US"
    timezone_id: str = "America/Los_Angeles"
    # Activity window: agent refuses to act outside these hours (local time)
    active_hours_start: int = 8
    active_hours_end: int = 23
    # Per-session caps so volume stays human-scale
    max_listings_per_scan: int = 40
    max_buys_per_day: int = 5


class RuntimeConfig(BaseSettings):
    """Non-strategy plumbing: paths, URLs, cadence."""

    model_config = SettingsConfigDict(env_prefix="COMC_", extra="ignore")

    base_url: str = "https://www.comc.com"
    data_dir: Path = REPO_ROOT / "data"
    browser_state_dir: Path = REPO_ROOT / "browser_state"
    logs_dir: Path = REPO_ROOT / "logs"
    db_path: Path = Field(default_factory=lambda: REPO_ROOT / "data" / "agent.db")

    scan_interval_minutes: int = 60
    reprice_interval_hours: int = 24
    sold_history_cache_ttl_hours: int = 24

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.browser_state_dir, self.logs_dir):
            p.mkdir(parents=True, exist_ok=True)


class Settings:
    """Single entry point that bundles the three config groups."""

    def __init__(self) -> None:
        self.strategy = Strategy()
        self.stealth = StealthConfig()
        self.runtime = RuntimeConfig()
        self.runtime.ensure_dirs()


settings = Settings()
