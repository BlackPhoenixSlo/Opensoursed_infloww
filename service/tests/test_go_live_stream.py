#!/usr/bin/env python3
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import of_client  # noqa: E402
import permissions  # noqa: E402
import server  # noqa: E402
from _relay_contract import CHATTER_A, CREATOR, OWNER_A, roles, send  # noqa: E402

GO_LIVE = "/of-manager/streaming"
ROUTES: list[dict] = []

ROUTES += [
    {"method": "GET", "route": "/api/of/v2/users/search", "relay": "/api/of/v2/users/search?q=synth&limit=5",
     "of": "/api2/v2/users?limit=5&offset=0&query=synth&view=se", "body": None},
    {"method": "GET", "route": "/api/of/v2/posts/search", "relay": "/api/of/v2/posts/search?query=synth&limit=5",
     "of": "/api2/v2/posts?limit=5&query=synth&skip_users=all&format=infinite", "body": None},
]


def _send(client, row: dict, refuse: bool = False):
    return send(client, row["method"], row["relay"], row["body"], CREATOR, refuse=refuse)


def assert_contract(row: dict) -> None:
    method = row["method"]
    where = f"{method} {row['relay']}"
    want = [(method, of_client.OF_WEB_ORIGIN + row["of"], row["body"])]

    mounted = {(m, r.path) for r in server.app.routes for m in getattr(r, "methods", ())}
    assert (method, row["route"]) in mounted, f"{where}: route {method} {row['route']} not registered"

    r, sent = _send(OWNER_A, row)
    assert r.status_code == 200, f"{where}: {r.status_code} {r.text}"
    assert sent == want, f"{where}: OF got {sent}, the row says {want}"

    r, sent = _send(OWNER_A, row, refuse=True)
    detail = r.json().get("detail") if r.status_code == 502 else None
    assert isinstance(detail, dict) and detail.get("upstream_status") == 400 \
        and "Synthetic refusal" in str(detail.get("upstream_body")), \
        f"{where}: OF refusal gave {r.status_code} {r.text}"

    pages = permissions.route_pages(row["relay"].split("?")[0], method) or ()
    assert GO_LIVE in pages, f"{where}: chatter check: page map serves {pages}, not Go live ({GO_LIVE})"
    try:
        roles("role-p4", True, {GO_LIVE: True})
        r, sent = _send(CHATTER_A, row)
        assert r.status_code == 200 and sent == want, \
            f"{where}: chatter check: a chatter granted Go live alone got {r.status_code}, OF got {sent}"
    finally:
        roles("role-p4", False, {})


def case_every_route_row_holds_the_contract():
    for row in ROUTES:
        assert_contract(row)


_PLANTED = {"method": "POST", "route": "/api/of/v2/streams", "relay": "/api/of/v2/streams", "of": "/api2/v2/streams",
            "body": {"description": "Synthetic stream", "scheduledDate": "2026-10-20T18:30:00+02:00",
                     "isShowTips": True}}


def case_the_contract_holds_on_a_planted_known_route():
    assert_contract(_PLANTED)


def case_the_contract_fails_a_planted_route_missing_from_go_live():
    row = {"method": "PATCH", "route": "/api/of/v2/users/me/settings/security",
           "relay": "/api/of/v2/users/me/settings/security", "of": "/api2/v2/users/me/settings/security",
           "body": {"isAutoFollowBack": True}}
    try:
        assert_contract(row)
    except AssertionError as e:
        assert "chatter check: page map serves" in str(e), e
        return
    raise AssertionError("a route missing from Go live's page entry passed the chatter check")


_harness.run()
