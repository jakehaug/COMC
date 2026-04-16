"""COMC site scraper.

COMC has no public API, so we drive the site via the persistent Playwright
context. Every DOM selector here is a guess based on public pages - they will
almost certainly need to be tuned once we can observe the real site. Each
selector is isolated in a small helper so tuning is localized.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Iterable

from playwright.async_api import Page

from .config import settings
from .human import human_scroll, pause, type_text
from .models import Listing, Sale


# --- Search --------------------------------------------------------------

SEARCH_URL = "{base}/Cards"  # COMC's main browse page


async def search_listings(
    page: Page,
    query: str | None = None,
    max_price: float | None = None,
    min_price: float | None = None,
    limit: int | None = None,
) -> list[Listing]:
    """Return up to `limit` listings matching the filters.

    `query` is a freeform search term (e.g., "2023 topps chrome rookie"). Price
    filters map onto COMC's price-range facets.
    """
    limit = limit or settings.stealth.max_listings_per_scan
    min_price = min_price if min_price is not None else settings.strategy.min_card_price_usd
    max_price = max_price if max_price is not None else settings.strategy.max_card_price_usd

    url = SEARCH_URL.format(base=settings.runtime.base_url)
    await page.goto(url, wait_until="domcontentloaded")
    await pause()

    if query:
        search_box = page.get_by_role("searchbox").first
        await type_text(page, search_box, query)
        await page.keyboard.press("Enter")
        await page.wait_for_load_state("domcontentloaded")
        await pause()

    # Apply price range via URL params - most COMC pages accept ?Price=min-max.
    current = page.url
    sep = "&" if "?" in current else "?"
    await page.goto(f"{current}{sep}Price={min_price:.2f}-{max_price:.2f}",
                    wait_until="domcontentloaded")
    await pause()

    listings: list[Listing] = []
    seen: set[str] = set()
    for _ in range(20):  # up to 20 pagination scrolls
        await human_scroll(page, total_px=900)
        new = await _extract_listings_on_page(page)
        for listing in new:
            if listing.listing_id in seen:
                continue
            seen.add(listing.listing_id)
            listings.append(listing)
            if len(listings) >= limit:
                return listings
        if not await _go_to_next_page(page):
            break
    return listings


async def _extract_listings_on_page(page: Page) -> list[Listing]:
    """Pull listing cards out of the current search results DOM."""
    # Structure on COMC: each card is an <a> with an href like /Cards/.../12345678
    # and a price node. We read them via evaluate() in one round-trip for speed.
    raw = await page.evaluate(
        """
        () => {
          const cards = [...document.querySelectorAll('[data-listing-id], a[href*="/Cards/"]')];
          const out = [];
          const seen = new Set();
          for (const el of cards) {
            const href = el.getAttribute('href') || '';
            const id = el.getAttribute('data-listing-id')
                   || (href.match(/(\\d{6,})$/) || [])[1];
            if (!id || seen.has(id)) continue;
            seen.add(id);
            const priceTxt = (el.innerText || '').match(/\\$\\s*[0-9,.]+/);
            const title = (el.getAttribute('title') || el.innerText || '').trim().split('\\n')[0];
            const img = el.querySelector('img');
            out.push({
              id,
              href,
              title,
              price: priceTxt ? priceTxt[0] : null,
              image: img ? img.getAttribute('src') : null,
            });
          }
          return out;
        }
        """
    )
    results: list[Listing] = []
    for r in raw:
        price = _parse_price(r.get("price"))
        if price is None:
            continue
        href = r["href"]
        url = href if href.startswith("http") else f"{settings.runtime.base_url}{href}"
        results.append(Listing(
            listing_id=str(r["id"]),
            title=r["title"] or "(unknown)",
            ask_price_usd=price,
            url=url,
            image_url=r.get("image"),
        ))
    return results


async def _go_to_next_page(page: Page) -> bool:
    next_link = page.get_by_role("link", name=re.compile(r"next", re.I))
    if await next_link.count() == 0:
        return False
    try:
        await next_link.first.click()
        await page.wait_for_load_state("domcontentloaded")
        await pause()
        return True
    except Exception:
        return False


def _parse_price(txt: str | None) -> float | None:
    if not txt:
        return None
    m = re.search(r"[\d,]+\.?\d*", txt.replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


# --- Listing detail + sold history --------------------------------------

async def fetch_listing_detail(page: Page, listing: Listing) -> Listing:
    """Visit a listing page and enrich with player/year/set/grade."""
    await page.goto(listing.url, wait_until="domcontentloaded")
    await pause()
    await human_scroll(page, total_px=600)

    detail = await page.evaluate(
        """
        () => {
          const pick = (re) => {
            for (const el of document.querySelectorAll('dt,th,span,div,li')) {
              if (re.test(el.innerText || '')) {
                const sib = el.nextElementSibling;
                if (sib) return (sib.innerText || '').trim();
              }
            }
            return null;
          };
          return {
            player: pick(/^player/i),
            year: pick(/^year/i),
            set_name: pick(/^set/i),
            card_number: pick(/^card\\s*#/i),
            sport: pick(/^sport/i),
            grade: pick(/^grade/i),
            seller: pick(/^seller/i),
          };
        }
        """
    )

    year_txt = detail.get("year") or ""
    year_m = re.search(r"\b(19|20)\d{2}\b", year_txt)
    grade_txt = detail.get("grade")

    return listing.model_copy(update={
        "player": detail.get("player"),
        "year": int(year_m.group(0)) if year_m else None,
        "set_name": detail.get("set_name"),
        "card_number": detail.get("card_number"),
        "sport": (detail.get("sport") or "").lower() or None,
        "graded": bool(grade_txt),
        "grade": grade_txt,
        "seller": detail.get("seller"),
    })


async def fetch_sold_history(page: Page, listing: Listing, window_days: int = 90) -> list[Sale]:
    """Scrape COMC's 'Recent Sales' panel for the same card.

    COMC exposes sold history on the listing detail page, typically behind a
    "Recent Sales" or "Sold" tab. We try a couple of common locations.
    """
    # Some pages put sold history on a sibling URL pattern.
    candidates: Iterable[str] = (
        listing.url + "/Sold",
        listing.url.replace("/Cards/", "/Sold/"),
        listing.url,  # fallback: sold panel on same page
    )
    cutoff = datetime.utcnow() - timedelta(days=window_days)
    for candidate in candidates:
        try:
            await page.goto(candidate, wait_until="domcontentloaded")
        except Exception:
            continue
        await pause()
        rows = await page.evaluate(
            """
            () => {
              const rows = [...document.querySelectorAll('tr, li, [data-sold-price]')];
              const out = [];
              for (const r of rows) {
                const txt = (r.innerText || '').trim();
                const price = txt.match(/\\$\\s*([0-9,.]+)/);
                const date = txt.match(/(\\d{4}-\\d{2}-\\d{2}|\\d{1,2}\\/\\d{1,2}\\/\\d{2,4})/);
                if (price && date) out.push({ price: price[1], date: date[1] });
              }
              return out;
            }
            """
        )
        sales: list[Sale] = []
        for row in rows:
            try:
                price = float(row["price"].replace(",", ""))
            except (KeyError, ValueError):
                continue
            sold_at = _parse_date(row["date"])
            if sold_at is None or sold_at < cutoff:
                continue
            sales.append(Sale(sold_price_usd=price, sold_at=sold_at, source="comc_sold"))
        if sales:
            return sales
    return []


def _parse_date(txt: str) -> datetime | None:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(txt, fmt)
        except ValueError:
            continue
    return None
