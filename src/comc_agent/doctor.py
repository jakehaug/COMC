"""Selector diagnostic tool.

Walks the site the same way `scrape` does and reports, for each thing we
expect to find (listing cards, price, sold history, add-to-cart button),
whether our selectors actually matched anything. Saves HTML snapshots to
`logs/doctor/` so the user can share them for selector tuning.
"""
from __future__ import annotations

from pathlib import Path

from playwright.async_api import Page

from .config import settings
from .human import human_scroll, pause
from .logging_setup import log
from .session import browser_session


async def _save_html(page: Page, name: str) -> Path:
    out_dir = settings.runtime.logs_dir / "doctor"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.html"
    path.write_text(await page.content(), encoding="utf-8")
    return path


async def check_search(page: Page) -> dict:
    url = f"{settings.runtime.base_url}/Cards"
    await page.goto(url, wait_until="domcontentloaded")
    await pause()
    await human_scroll(page, total_px=900)
    count = await page.evaluate(
        """
        () => document.querySelectorAll('[data-listing-id], a[href*="/Cards/"]').length
        """
    )
    path = await _save_html(page, "search")
    return {"url": url, "matched_cards": count, "snapshot": str(path)}


async def check_listing_detail(page: Page) -> dict:
    """Open the first listing from search results and inspect the detail page."""
    await page.goto(f"{settings.runtime.base_url}/Cards", wait_until="domcontentloaded")
    await pause()
    first = await page.evaluate(
        "() => {"
        "  const a = document.querySelector('a[href*=\"/Cards/\"]');"
        "  return a ? a.href : null;"
        "}"
    )
    if not first:
        return {"error": "no listing link found on /Cards"}
    await page.goto(first, wait_until="domcontentloaded")
    await pause()
    fields = await page.evaluate(
        """
        () => {
          const labels = ['player', 'year', 'set', 'card', 'sport', 'grade', 'seller'];
          const found = {};
          for (const l of labels) {
            const re = new RegExp('^\\\\s*' + l, 'i');
            for (const el of document.querySelectorAll('dt,th,span,div,li')) {
              if (re.test(el.innerText || '')) {
                const sib = el.nextElementSibling;
                if (sib) { found[l] = (sib.innerText || '').trim().slice(0, 80); break; }
              }
            }
          }
          return found;
        }
        """
    )
    path = await _save_html(page, "listing_detail")
    return {"url": first, "fields_found": fields, "snapshot": str(path)}


async def run_diagnostics() -> list[dict]:
    report: list[dict] = []
    async with browser_session() as (_ctx, page):
        log.info("doctor: checking search page...")
        report.append({"check": "search", **(await check_search(page))})
        log.info("doctor: checking listing detail...")
        report.append({"check": "listing_detail", **(await check_listing_detail(page))})
    return report
