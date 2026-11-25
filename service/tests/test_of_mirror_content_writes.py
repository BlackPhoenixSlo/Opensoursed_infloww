#!/usr/bin/env python3
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import json  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import of_client  # noqa: E402
import permissions  # noqa: E402
import server  # noqa: E402,F401  (builds the app the contract sends to)
from _relay_contract import CHATTER_A, CREATOR, OWNER_A, roles, send as _send  # noqa: E402

CAPTURES = Path(__file__).resolve().parents[2] / "docs" / "of-manager" / "captures"
sys.path.append(str(Path(__file__).resolve().parents[2] / "scripts" / "of-live-proof"))
from proof_core import fill as _fill  # noqa: E402  (proof_core is stdlib-only and never touches sys.path)

ROUTES: list[dict] = []

MASTER = fx.login_owner("agency_master")


def _record(row: dict) -> dict:
    return row.get("record_body") or json.loads((CAPTURES / f"{row['record']}.json").read_text())


def assert_contract(row: dict) -> None:
    rec = _record(row)
    fill = {"creator": CREATOR, **row.get("fill", {})}
    req = rec["request"]
    method, body = req["method"], _fill(req.get("body"), fill)
    want = [(method, of_client.OF_WEB_ORIGIN + _fill(req["path"], fill), body)]
    where = f"{method} {row['relay']}"

    r, sent = _send(OWNER_A, method, row["relay"], body, CREATOR)
    assert r.status_code == 200, f"{where}: {r.status_code} {r.text}"
    assert sent == want, f"{where}: OF got {sent}, capture says {want}"

    r, sent = _send(OWNER_A, method, row["relay"], {**body, "oiExtraKey": 1}, CREATOR)
    assert r.status_code == 422 and sent == [], f"{where}: extra key gave {r.status_code}, OF got {sent}"

    r, sent = _send(MASTER, method, row["relay"], body, None)
    assert r.status_code == 400 and sent == [], f"{where}: no X-Account-Id gave {r.status_code}, OF got {sent}"

    pages = permissions.route_pages(row["relay"].split("?")[0], method) or ()
    assert row["page"] in pages, f"{where}: page map serves {pages}, not {row['page']}"
    try:
        roles("role-p2", True, {h: h != row["page"] for h in permissions.PAGE_MAP})
        r, sent = _send(CHATTER_A, method, row["relay"], body, CREATOR)
        assert r.status_code == 403 and sent == [], f"{where}: chatter without {row['page']}: {r.status_code} {sent}"
        roles("role-p2", True, {row["page"]: True})
        r, sent = _send(CHATTER_A, method, row["relay"], body, CREATOR)
        assert r.status_code == 200 and sent == want, f"{where}: chatter with {row['page']} alone: {r.status_code}"
    finally:
        roles("role-p2", False, {})


def case_every_route_row_holds_the_contract():
    for row in ROUTES:
        assert_contract(row)


_PLANTED = {"relay": "/api/of/v2/users/me/settings/security", "page": "/of-manager/settings",
            "record_body": {"request": {"method": "PATCH", "path": "/api2/v2/users/me/settings/security",
                                        "body": {"isAutoFollowBack": True}}}}


def case_the_contract_holds_on_a_planted_known_route():
    assert_contract(_PLANTED)


def case_the_contract_fails_a_planted_row_on_the_wrong_page():
    try:
        assert_contract({**_PLANTED, "page": "/of-manager/home"})
    except AssertionError as e:
        assert "page map serves" in str(e), e
        return
    raise AssertionError("a row naming a page the route does not serve passed the chatter check")


_harness.run()
