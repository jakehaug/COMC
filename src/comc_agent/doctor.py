"""Selector diagnostic tool.

Walks the site the same way `scrape` does and reports what the agent
actually sees. We warm up via the homepage and reach /Cards by clicking a
link (like a human would) rather than navigating directly - COMC serves
different content depending on how you arrive.
"""
from __future__ import annotations

from pathlib import Path

from playwright.async_api import Page

from .config import settings
from .human import human_scroll, pause
from .logging_setup import log
from .session import browser_session


async def _page_report(page: Page, label: str) -> dict:
    """Pull the human-readable info we need to diagnose what's on screen."""
    title = await page.title()
    body_sample = await page.evaluate(
        "() => (document.body ? document.body.innerText : '').slice(0, 800)"
    )
    is_blocked = any(
        phrase in body_sample.lower()
        for phrase in ("page not available", "access denied", "captcha",
                       "unusual activity", "blocked", "not found", "404")
    )
    snapshot = settings.runtime.logs_dir / "doctor" / f"{label}.html"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(await page.content(), encoding="utf-8")
    screenshot = snapshot.with_suffix(".png")
    try:
        await page.screenshot(path=str(screenshot), full_page=False)
    except Exception:
        screenshot = None
    return {
        "title": title,
        "final_url": page.url,
        "body_sample": body_sample.replace("\n", " | ")[:400],
        "looks_blocked": is_blocked,
        "snapshot_html": str(snapshot),
        "snapshot_png": str(screenshot) if screenshot else None,
    }


async def check_homepage(page: Page) -> dict:
    await page.goto(settings.runtime.base_url, wait_until="domcontentloaded")
    await pause()
    await human_scroll(page, total_px=600)
    return {"check": "homepage", **(await _page_report(page, "homepage"))}


async def check_browse_via_menu(page: Page) -> dict:
    """Reach the browse page by clicking a menu link, like a human."""
    await page.goto(settings.runtime.base_url, wait_until="domcontentloaded")
    await pause()
    # Try a few likely menu link texts.
    for label in ("Buy Cards", "Buy", "Shop", "Browse", "Cards", "Marketplace"):
        link = page.get_by_role("link", name=label, exact=False)
        if await link.count() > 0:
            try:
                await link.first.click()
                await page.wait_for_load_state("domcontentloaded")
                await pause()
                rep = await _page_report(page, "browse_via_menu")
                rep["clicked_label"] = label
                return {"check": "browse_via_menu", **rep}
            except Exception:
                continue
    return {"check": "browse_via_menu", "error": "no browse link found on homepage"}


async def check_direct_cards_url(page: Page) -> dict:
    await page.goto(f"{settings.runtime.base_url}/Cards", wait_until="domcontentloaded")
    await pause()
    return {"check": "direct /Cards", **(await _page_report(page, "direct_cards"))}


async def run_diagnostics() -> list[dict]:
    report: list[dict] = []
    async with browser_session() as (_ctx, page):
        log.info("doctor: homepage...")
        report.append(await check_homepage(page))
        log.info("doctor: browse via menu...")
        report.append(await check_browse_via_menu(page))
        log.info("doctor: direct /Cards...")
        report.append(await check_direct_cards_url(page))
    return report
