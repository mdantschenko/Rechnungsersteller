"""Turning HTML into PDF with the Chromium that ships inside Playwright.

Playwright is an optional dependency, so its import waits until a document
is actually written.
"""

from __future__ import annotations

from pathlib import Path


class ChromiumRenderer:
    """Prints the page to PDF through Playwright, without system packages."""

    def write(self, html: str, destination: Path) -> None:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()
                page.set_content(html, wait_until="load")
                page.pdf(
                    path=str(destination),
                    prefer_css_page_size=True,
                    print_background=True,
                )
            finally:
                browser.close()
