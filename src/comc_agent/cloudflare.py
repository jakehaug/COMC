"""Cloudflare challenge detection and handling.

COMC sits behind Cloudflare's managed challenge. When our automated browser
hits a protected page cold, we see a "Just a moment..." interstitial while
Cloudflare fingerprints us. With a sufficiently realistic fingerprint, it
auto-passes in a few seconds; otherwise it prompts for a click.

Strategy:
  1. Detect the challenge by title / body text.
  2. Wait up to `timeout_s` for the title to change (invisible pass).
  3. If still blocked, flag it to the user; since we run headful, they can
     click "Verify" once and the session continues.
"""
from __future__ import annotations

import asyncio

from playwright.async_api import Page

from .logging_setup import log


CHALLENGE_TITLE_HINTS = ("just a moment", "attention required", "please wait")
CHALLENGE_BODY_HINTS = ("security verification", "performing security",
                        "ray id:", "cloudflare", "checking your browser")


async def is_cloudflare_challenge(page: Page) -> bool:
    """Heuristic: combine title and visible body text."""
    try:
        title = (await page.title()).lower()
    except Exception:
        return False
    if any(h in title for h in CHALLENGE_TITLE_HINTS):
        return True
    try:
        body = await page.evaluate(
            "() => (document.body ? document.body.innerText : '').toLowerCase()"
        )
    except Exception:
        return False
    return any(h in body for h in CHALLENGE_BODY_HINTS)


async def wait_for_challenge_to_clear(page: Page, timeout_s: float = 45.0) -> bool:
    """Poll until the page is no longer showing a challenge. Returns True if cleared."""
    if not await is_cloudflare_challenge(page):
        return True
    log.info("Cloudflare challenge detected - waiting up to %ds for it to clear...", int(timeout_s))
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(1.5)
        if not await is_cloudflare_challenge(page):
            log.info("Challenge cleared.")
            return True
    log.warning("Challenge did NOT clear within %ds.", int(timeout_s))
    return False


async def prompt_human_to_solve(page: Page, timeout_s: float = 5 * 60.0) -> bool:
    """Non-blocking prompt: keep polling while asking the human to click Verify."""
    print("\n" + "=" * 72)
    print("Cloudflare challenge did not auto-pass.")
    print("Please click 'Verify' (or the checkbox) in the browser window.")
    print("The agent will wait up to 5 minutes for you.")
    print("=" * 72 + "\n")
    return await wait_for_challenge_to_clear(page, timeout_s=timeout_s)


async def ensure_past_challenge(page: Page) -> bool:
    """Call this after any page navigation to make sure we're not stuck on
    the Cloudflare interstitial. Returns True if we're on the real page."""
    if not await is_cloudflare_challenge(page):
        return True
    if await wait_for_challenge_to_clear(page, timeout_s=30):
        return True
    return await prompt_human_to_solve(page)
