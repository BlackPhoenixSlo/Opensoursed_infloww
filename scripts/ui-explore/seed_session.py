"""Register the demo owner on a `demo-shots/run.sh serve` stack, seed the synthetic agency
(demo-shots dataset.py -> seed.py, as capture.py does) and print the owner's session cookie.

    DEMO_SHOTS_TMP=... seed_session.py <app-url>   -> stdout: session cookie
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/demo-shots"))

import dataset  # noqa: E402
from seed import Api, seed  # noqa: E402

PASSWORD = "ui-explore-throwaway"


def main() -> int:
    app, tmp = sys.argv[1], Path(os.environ["DEMO_SHOTS_TMP"])
    d = dataset.build()
    owner = {"username": dataset.OWNER_USERNAME, "password": PASSWORD}
    with sync_playwright() as pw:
        req = pw.request.new_context()
        r = req.post(f"{app}/auth/register", data=owner)
        if not r.ok:
            print(f"ui-explore: register -> {r.status} {r.text()[:200]}", file=sys.stderr)
            return 1
        seed(d, db=tmp / "relay.db", sessions=tmp / "sessions", user_id=r.json()["user_id"], api=Api(req, app))
        cookie = next(c for c in req.storage_state()["cookies"] if c["name"] == "chatterly_session")
        req.dispose()
    print(f"chatterly_session={cookie['value']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
