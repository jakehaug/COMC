"""Human-paced interaction primitives.

Every mouse move, click, keystroke, and navigation the agent does goes through
this module so timing and movement look like a person, not a bot.
"""
from __future__ import annotations

import asyncio
import math
import random
from datetime import datetime
from typing import Sequence

from playwright.async_api import Page, Locator

from .config import settings


def _sleep_ms() -> float:
    lo = settings.stealth.min_action_delay_ms
    hi = settings.stealth.max_action_delay_ms
    # Log-uniform gives more short pauses with occasional long ones, like a human.
    u = random.random()
    return math.exp(math.log(lo) + u * (math.log(hi) - math.log(lo))) / 1000.0


async def pause(multiplier: float = 1.0) -> None:
    await asyncio.sleep(_sleep_ms() * multiplier)


def within_active_hours(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    return settings.stealth.active_hours_start <= now.hour < settings.stealth.active_hours_end


def _bezier_points(start: tuple[float, float], end: tuple[float, float], steps: int) -> list[tuple[float, float]]:
    """Quadratic bezier with a randomized control point for a natural arc."""
    sx, sy = start
    ex, ey = end
    mx = (sx + ex) / 2 + random.uniform(-80, 80)
    my = (sy + ey) / 2 + random.uniform(-80, 80)
    out = []
    for i in range(steps + 1):
        t = i / steps
        x = (1 - t) ** 2 * sx + 2 * (1 - t) * t * mx + t ** 2 * ex
        y = (1 - t) ** 2 * sy + 2 * (1 - t) * t * my + t ** 2 * ey
        out.append((x, y))
    return out


async def move_mouse_to(page: Page, x: float, y: float) -> None:
    # Playwright doesn't expose current cursor position; approximate from last stored one.
    start = getattr(page, "_last_cursor", (random.uniform(0, 400), random.uniform(0, 400)))
    steps = random.randint(18, 34)
    for px, py in _bezier_points(start, (x, y), steps):
        await page.mouse.move(px, py)
        await asyncio.sleep(random.uniform(0.005, 0.018))
    page._last_cursor = (x, y)  # type: ignore[attr-defined]


async def hover_and_click(page: Page, locator: Locator) -> None:
    await locator.scroll_into_view_if_needed()
    await pause(0.4)
    box = await locator.bounding_box()
    if box is None:
        await locator.click()
        return
    tx = box["x"] + box["width"] * random.uniform(0.25, 0.75)
    ty = box["y"] + box["height"] * random.uniform(0.25, 0.75)
    await move_mouse_to(page, tx, ty)
    await asyncio.sleep(random.uniform(0.08, 0.22))
    await page.mouse.down()
    await asyncio.sleep(random.uniform(0.04, 0.14))
    await page.mouse.up()
    await pause()


async def type_text(page: Page, locator: Locator, text: str) -> None:
    await hover_and_click(page, locator)
    cps = settings.stealth.typing_cwpm / 60.0
    for ch in text:
        await page.keyboard.type(ch)
        # Jitter per keystroke; occasionally a longer pause (thinking).
        delay = max(0.02, random.gauss(1.0 / cps, 0.05))
        if random.random() < 0.03:
            delay += random.uniform(0.2, 0.6)
        await asyncio.sleep(delay)


async def human_scroll(page: Page, total_px: int | None = None) -> None:
    """Scroll the page in several uneven bursts like a human reading."""
    total_px = total_px or random.randint(400, 1600)
    scrolled = 0
    while scrolled < total_px:
        step = random.randint(80, 280)
        await page.mouse.wheel(0, step)
        scrolled += step
        await asyncio.sleep(random.uniform(0.15, 0.7))


async def goto_with_retry(page: Page, url: str, attempts: int = 3) -> bool:
    """Navigate with exponential backoff. Humans retry a flaky page too."""
    delay = 2.0
    for i in range(attempts):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            return True
        except Exception:
            if i == attempts - 1:
                return False
            await asyncio.sleep(delay + random.uniform(0, 1.0))
            delay *= 2
    return False


async def warmup_browse(page: Page, warmup_urls: Sequence[str]) -> None:
    """Before doing anything consequential, visit a couple of innocuous pages."""
    n = min(settings.stealth.warmup_pages_before_action, len(warmup_urls))
    for url in random.sample(list(warmup_urls), n):
        await page.goto(url, wait_until="domcontentloaded")
        await pause(1.2)
        await human_scroll(page)
        await pause(0.8)
