"""Load the app once in a browser so next dev has compiled the page and its client chunks.

    warm.py <shim-url> <name=value cookie> <chrome resolver flag> <width> <height>
"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright


def main() -> int:
    shim, cookie, resolver, w, h = sys.argv[1:]
    name, value = cookie.split("=", 1)
    with sync_playwright() as p:
        browser = p.chromium.launch(args=[resolver])
        ctx = browser.new_context(viewport={"width": int(w), "height": int(h)})
        ctx.add_cookies([{"name": name, "value": value, "url": shim}])
        page = ctx.new_page()
        page.goto(shim + "/", wait_until="load", timeout=300_000)
        page.wait_for_timeout(5_000)
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
