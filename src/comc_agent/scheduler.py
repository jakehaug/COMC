"""Runs the agent on its cadence.

Uses APScheduler's async scheduler with jitter so run times don't look
mechanical. The browser context is kept open for the duration of the
process so session cookies stay warm.
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from rich.console import Console

from . import engine, trader
from .config import settings
from .logging_setup import log
from .session import browser_session


console = Console()


async def run_forever() -> None:
    async with browser_session() as (_ctx, page):
        scheduler = AsyncIOScheduler()

        async def scan():
            try:
                result = await engine.scan_cycle(page)
                log.info("scan: %s", result)
            except trader.TradingPaused as e:
                log.warning("paused: %s", e)

        async def reprice():
            try:
                result = await engine.reprice_cycle(page)
                log.info("reprice: %s", result)
            except trader.TradingPaused as e:
                log.warning("paused: %s", e)

        # Jitter initial run time and interval so we don't hit the same minute every hour.
        scheduler.add_job(
            scan,
            IntervalTrigger(
                minutes=settings.runtime.scan_interval_minutes,
                jitter=60 * 10,  # +/- 10 min
            ),
            next_run_time=datetime.now().replace(microsecond=0),
        )
        scheduler.add_job(
            reprice,
            IntervalTrigger(
                hours=settings.runtime.reprice_interval_hours,
                jitter=60 * 60,  # +/- 1 hr
            ),
        )
        scheduler.start()
        log.info("Agent running. Ctrl+C to stop.")
        try:
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, asyncio.CancelledError):
            scheduler.shutdown()
