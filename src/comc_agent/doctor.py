"""Selector diagnostic tool.

Each check is isolated so one failure doesn't abort the whole run. We
deliberately avoid mouse-scroll / mouse-move gestures here - they're
helpful for stealth but can fail on pages that redirect or close quickly,
and we just want to see what the agent is getting.
"""
from __future__ import annotations

import asyncio
import traceback
from pathlib import Path

from playwright.async_api import Page

from .cloudflare import ensure_past_challenge, is_cloudflare_challenge
from .config import settings
from .logging_setup import log
from .session import browser_session


async def _page_report(page: Page, label: str) -> dict:
    """Pull the human-readable info we need to diagnose what's on screen."""
    try:
        title = await page.title()
    except Exception:
        title = "(could not read title)"
    try:
        body_sample = await page.evaluate(
            "() => (document.body ? document.body.innerText : '').slice(0, 1200)"
        )
    except Exception as e:
        body_sample = f"(could not read body: {e})"

    is_blocked = any(
        phrase in body_sample.lower()
        for phrase in ("page not available", "access denied", "captcha",
                       "unusual activity", "blocked", "not found", "404")
    )

    snapshot = settings.runtime.logs_dir / "doctor" / f"{label}.html"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    try:
        snapshot.write_text(await page.content(), encoding="utf-8")
    except Exception:
        snapshot = None

    screenshot: Path | None = settings.runtime.logs_dir / "doctor" / f"{label}.png"
    try:
        await page.screenshot(path=str(screenshot), full_page=False)
    except Exception:
        screenshot = None

    try:
        final_url = page.url
    except Exception:
        final_url = "(closed)"

    try:
        on_challenge = await is_cloudflare_challenge(page)
    except Exception:
        on_challenge = False

    return {
        "title": title,
        "final_url": final_url,
        "cloudflare_challenge": on_challenge,
        "body_sample": body_sample.replace("\n", " | ")[:600],
        "looks_blocked": is_blocked,
        "snapshot_html": str(snapshot) if snapshot else None,
        "snapshot_png": str(screenshot) if screenshot else None,
    }


async def _safe_goto(page: Page, url: str) -> bool:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(2)
        await ensure_past_challenge(page)
        return True
    except Exception as e:
        log.warning("goto %s failed: %s", url, e)
        return False


async def check_homepage(page: Page) -> dict:
    try:
        await _safe_goto(page, settings.runtime.base_url)
        return {"check": "homepage", **(await _page_report(page, "homepage"))}
    except Exception as e:
        return {"check": "homepage", "error": str(e), "trace": traceback.format_exc(limit=3)}


async def check_browse_via_menu(page: Page) -> dict:
    try:
        await _safe_goto(page, settings.runtime.base_url)
        for label in ("Buy Cards", "Buy", "Shop", "Browse", "Cards", "Marketplace"):
            link = page.get_by_role("link", name=label, exact=False)
            if await link.count() > 0:
                try:
                    await link.first.click(timeout=5000)
                    await page.wait_for_load_state("domcontentloaded")
                    await asyncio.sleep(2)
                    rep = await _page_report(page, "browse_via_menu")
                    rep["clicked_label"] = label
                    return {"check": "browse_via_menu", **rep}
                except Exception:
                    continue
        return {"check": "browse_via_menu", "error": "no browse link found on homepage"}
    except Exception as e:
        return {"check": "browse_via_menu", "error": str(e), "trace": traceback.format_exc(limit=3)}


async def check_direct_cards_url(page: Page) -> dict:
    try:
        await _safe_goto(page, f"{settings.runtime.base_url}/Cards")
        return {"check": "direct /Cards", **(await _page_report(page, "direct_cards"))}
    except Exception as e:
        return {"check": "direct /Cards", "error": str(e), "trace": traceback.format_exc(limit=3)}


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
