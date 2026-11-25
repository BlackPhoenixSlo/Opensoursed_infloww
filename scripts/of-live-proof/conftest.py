import os

import pytest


@pytest.fixture(scope="module")
def pw():
    sync = pytest.importorskip("playwright.sync_api")
    if os.getpriority(os.PRIO_PROCESS, 0) < 10:
        os.setpriority(os.PRIO_PROCESS, 0, 10)
    with sync.sync_playwright() as p:
        try:
            p.chromium.launch().close()
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"no Playwright Chromium: {e}")
        yield p
