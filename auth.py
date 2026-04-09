"""Authentication helpers: launch a persistent Chrome context, wait for Google
login, then export cookies in Netscape format for use by gpwc.Client."""

from __future__ import annotations

import time
import threading
from pathlib import Path
from typing import Callable

CONFIG_DIR = Path.home() / ".gphotohandler"
CHROME_PROFILE_DIR = CONFIG_DIR / "chrome_profile"
COOKIES_PATH = CONFIG_DIR / "cookies.txt"

GOOGLE_PHOTOS_URL = "https://photos.google.com"


def is_authenticated() -> bool:
    """Return True if a cookies.txt file exists and is non-empty."""
    return COOKIES_PATH.exists() and COOKIES_PATH.stat().st_size > 50


def do_login(on_complete: Callable[[], None], on_error: Callable[[str], None]) -> None:
    """Open a visible Chrome window so the user can log in to Google Photos.

    Runs in a daemon thread to avoid blocking the Tkinter event loop.
    Calls on_complete() on success or on_error(message) on failure.
    """
    thread = threading.Thread(
        target=_login_thread,
        args=(on_complete, on_error),
        daemon=True,
    )
    thread.start()


def _login_thread(on_complete: Callable, on_error: Callable) -> None:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                str(CHROME_PROFILE_DIR),
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
                no_viewport=True,
            )

            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(GOOGLE_PHOTOS_URL, wait_until="domcontentloaded")

            # Wait until the user lands on Google Photos (not login/consent pages).
            while True:
                if page.is_closed():
                    raise RuntimeError("Browser was closed before login completed.")
                url = page.url
                if (
                    "photos.google.com" in url
                    and "accounts.google.com" not in url
                    and "myaccount.google.com" not in url
                ):
                    break
                time.sleep(1)

            # Small delay to let any post-login redirects settle.
            page.wait_for_timeout(2000)
            cookies = ctx.cookies()
            ctx.close()

        _save_netscape_cookies(cookies, COOKIES_PATH)
        on_complete()

    except Exception as exc:  # noqa: BLE001
        on_error(str(exc))


def _save_netscape_cookies(cookies: list[dict], path: Path) -> None:
    """Persist Playwright cookies as a Netscape HTTP Cookie File."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Netscape HTTP Cookie File\n"]
    for c in cookies:
        domain = c.get("domain", "")
        include_subdomain = "TRUE" if domain.startswith(".") else "FALSE"
        cookie_path = c.get("path", "/")
        secure = "TRUE" if c.get("secure", False) else "FALSE"
        raw_expires = c.get("expires", -1)
        expires = int(raw_expires) if raw_expires and raw_expires > 0 else 0
        name = c.get("name", "")
        value = c.get("value", "")
        lines.append(
            f"{domain}\t{include_subdomain}\t{cookie_path}\t"
            f"{secure}\t{expires}\t{name}\t{value}\n"
        )
    path.write_text("".join(lines), encoding="utf-8")
