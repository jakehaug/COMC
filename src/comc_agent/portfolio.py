"""SQLite-backed portfolio state.

Tables:
  positions - every card we've bought, with cost basis, listing state, P&L.
  comps_cache - cached sold-history results keyed by card signature (TTL'd).
  events - append-only audit log of every agent action.

We keep this tiny and synchronous; the agent is low-throughput.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Iterator

from .config import settings
from .models import Listing, Sale


SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    listing_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    player TEXT,
    sport TEXT,
    year INTEGER,
    cost_basis_usd REAL NOT NULL,
    bought_at TEXT NOT NULL,
    current_list_price_usd REAL,
    last_repriced_at TEXT,
    sold_at TEXT,
    sold_price_usd REAL,
    status TEXT NOT NULL DEFAULT 'owned'  -- owned | listed | sold | liquidated
);

CREATE TABLE IF NOT EXISTS comps_cache (
    card_signature TEXT PRIMARY KEY,
    sales_json TEXT NOT NULL,
    cached_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
"""


def card_signature(listing: Listing) -> str:
    """Stable key for grouping the same card across listings."""
    parts = [
        (listing.player or "").lower(),
        str(listing.year or ""),
        (listing.set_name or "").lower(),
        (listing.card_number or "").lower(),
        (listing.grade or "raw").lower(),
    ]
    return "|".join(parts)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    settings.runtime.ensure_dirs()
    conn = sqlite3.connect(settings.runtime.db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


# --- Positions ----------------------------------------------------------

def record_purchase(listing: Listing, cost_basis: float) -> None:
    with connect() as c:
        c.execute(
            """
            INSERT OR REPLACE INTO positions
                (listing_id, title, player, sport, year, cost_basis_usd, bought_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'owned')
            """,
            (
                listing.listing_id, listing.title, listing.player, listing.sport,
                listing.year, cost_basis, datetime.utcnow().isoformat(),
            ),
        )
    log_event("purchase", {"listing_id": listing.listing_id, "cost_basis": cost_basis})


def record_listing(listing_id: str, list_price: float) -> None:
    with connect() as c:
        c.execute(
            """
            UPDATE positions
               SET current_list_price_usd = ?,
                   last_repriced_at = ?,
                   status = 'listed'
             WHERE listing_id = ?
            """,
            (list_price, datetime.utcnow().isoformat(), listing_id),
        )
    log_event("list", {"listing_id": listing_id, "price": list_price})


def record_sale(listing_id: str, sold_price: float) -> None:
    with connect() as c:
        c.execute(
            """
            UPDATE positions
               SET sold_at = ?, sold_price_usd = ?, status = 'sold'
             WHERE listing_id = ?
            """,
            (datetime.utcnow().isoformat(), sold_price, listing_id),
        )
    log_event("sale", {"listing_id": listing_id, "price": sold_price})


def open_positions() -> list[sqlite3.Row]:
    with connect() as c:
        return list(c.execute(
            "SELECT * FROM positions WHERE status IN ('owned', 'listed')"
        ))


def cash_spent() -> float:
    with connect() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(cost_basis_usd), 0) AS s FROM positions "
            "WHERE status IN ('owned', 'listed')"
        ).fetchone()
        return float(row["s"] or 0.0)


def player_exposure_usd(player: str | None) -> float:
    if not player:
        return 0.0
    with connect() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(cost_basis_usd), 0) AS s FROM positions "
            "WHERE status IN ('owned', 'listed') AND LOWER(player) = LOWER(?)",
            (player,),
        ).fetchone()
        return float(row["s"] or 0.0)


# --- Budget / concentration checks --------------------------------------

def can_afford(price: float) -> bool:
    return (cash_spent() + price) <= settings.strategy.total_budget_usd


def within_player_limit(player: str | None, price: float) -> bool:
    if not player:
        return True
    cap = settings.strategy.total_budget_usd * settings.strategy.max_player_concentration_pct
    return (player_exposure_usd(player) + price) <= cap


# --- Comps cache --------------------------------------------------------

def get_cached_comps(sig: str) -> list[Sale] | None:
    ttl = timedelta(hours=settings.runtime.sold_history_cache_ttl_hours)
    with connect() as c:
        row = c.execute(
            "SELECT sales_json, cached_at FROM comps_cache WHERE card_signature = ?",
            (sig,),
        ).fetchone()
    if not row:
        return None
    cached_at = datetime.fromisoformat(row["cached_at"])
    if datetime.utcnow() - cached_at > ttl:
        return None
    return [Sale(**s) for s in json.loads(row["sales_json"])]


def put_cached_comps(sig: str, sales: list[Sale]) -> None:
    with connect() as c:
        c.execute(
            "INSERT OR REPLACE INTO comps_cache (card_signature, sales_json, cached_at) VALUES (?, ?, ?)",
            (sig, json.dumps([s.model_dump(mode="json") for s in sales]), datetime.utcnow().isoformat()),
        )


# --- Audit log ----------------------------------------------------------

def log_event(kind: str, payload: dict) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO events (ts, kind, payload_json) VALUES (?, ?, ?)",
            (datetime.utcnow().isoformat(), kind, json.dumps(payload, default=str)),
        )
