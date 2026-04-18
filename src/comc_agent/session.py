"""Browser session: persistent Playwright context + anti-detection patches.

The agent uses a single long-lived profile directory so cookies, localStorage,
and browsing history accumulate over time - that alone makes the agent look
far less like a throwaway bot. On top of that we apply stealth patches to
hide the common `navigator.webdriver` / WebGL / plugin tells.
"""
from __future__ import annotations

import contextlib
from typing import AsyncIterator

from playwright.async_api import BrowserContext, Page, async_playwright

try:
    from playwright_stealth import stealth_async
    _HAS_STEALTH_LIB = True
except ImportError:  # pragma: no cover
    _HAS_STEALTH_LIB = False

from .config import settings


# Common automation fingerprints patched inline. We deliberately avoid a
# pip dependency on playwright-stealth so we're not pinned to its version.
_STEALTH_JS = r"""
// Hide navigator.webdriver
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// Plugins: give a non-empty, plausible list.
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        { name: 'Chrome PDF Plugin' },
        { name: 'Chrome PDF Viewer' },
        { name: 'Native Client' },
    ],
});

// Languages
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

// WebGL vendor/renderer strings (avoid "SwiftShader" / "Google Inc." headless tells)
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function (p) {
    if (p === 37445) return 'Intel Inc.';            // UNMASKED_VENDOR_WEBGL
    if (p === 37446) return 'Intel Iris OpenGL Engine'; // UNMASKED_RENDERER_WEBGL
    return getParameter.call(this, p);
};

// chrome runtime stub
window.chrome = window.chrome || { runtime: {} };

// Permissions API returns "prompt" for notifications (real Chrome) not "denied" (headless)
const originalQuery = navigator.permissions && navigator.permissions.query;
if (originalQuery) {
    navigator.permissions.query = (params) =>
        params && params.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(params);
}
"""


@contextlib.asynccontextmanager
async def browser_session() -> AsyncIterator[tuple[BrowserContext, Page]]:
    """Open a persistent browser context and yield (context, page).

    Usage:
        async with browser_session() as (ctx, page):
            await page.goto("https://www.comc.com")
    """
    settings.runtime.ensure_dirs()
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(settings.runtime.browser_state_dir),
            headless=settings.stealth.headless,
            viewport={
                "width": settings.stealth.viewport_width,
                "height": settings.stealth.viewport_height,
            },
            locale=settings.stealth.locale,
            timezone_id=settings.stealth.timezone_id,
            # Use a real Chrome channel when available; falls back to bundled chromium.
            channel="chrome",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        if settings.stealth.use_stealth_patches:
            await context.add_init_script(_STEALTH_JS)

        page = context.pages[0] if context.pages else await context.new_page()
        if settings.stealth.use_stealth_patches and _HAS_STEALTH_LIB:
            # playwright-stealth patches dozens of additional fingerprints
            # (iframe.contentWindow, chrome.loadTimes, codec detection, etc.)
            # that pure JS init scripts can't easily cover.
            try:
                await stealth_async(page)
            except Exception:
                pass
        try:
            yield context, page
        finally:
            await context.close()


async def is_logged_in(page: Page) -> bool:
    """Best-effort check. COMC login state is exposed via an "Account" menu."""
    await page.goto(f"{settings.runtime.base_url}/", wait_until="domcontentloaded")
    # The header shows "Sign In" when logged out and the username when logged in.
    try:
        sign_in = page.get_by_role("link", name="Sign In")
        return not await sign_in.is_visible(timeout=2000)
    except Exception:
        return True


async def interactive_login() -> None:
    """Open a browser window for the user to log in once. The persistent context
    retains the session afterward; subsequent runs don't need credentials.
    """
    async with browser_session() as (_ctx, page):
        # Go to the homepage; the user clicks Sign In from there. The exact
        # login URL path is versioned by COMC so we don't hardcode it.
        await page.goto(settings.runtime.base_url)
        print("Sign in to COMC in the browser window (including any 2FA).")
        print("When you're done, come back here - the agent auto-detects login.")
        try:
            await page.wait_for_function(
                "() => !document.body.innerText.match(/\\bSign In\\b/i)",
                timeout=10 * 60 * 1000,
            )
            print("Login detected. Session saved.")
        except Exception:
            print("Login wait timed out or window closed; session state still saved if cookies were set.")
