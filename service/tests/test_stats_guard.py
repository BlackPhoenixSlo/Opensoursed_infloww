#!/usr/bin/env python3
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

from datetime import date, datetime, timedelta, timezone  # noqa: E402
from urllib.parse import urlencode  # noqa: E402

import _agency_fixtures as fx  # noqa: E402

IDS = fx.seed_two_agencies()
OWNER = fx.login_owner("agency_a_owner")
TO = date(2026, 10, 19)


def _get(path: str, **q):
    return OWNER.get(f"{path}?{urlencode(q, doseq=True)}")


def _window(days: int) -> dict[str, str]:
    return {"from": (TO - timedelta(days=days - 1)).isoformat(), "to": TO.isoformat()}


def _refused(r, code: str) -> dict:
    assert r.status_code == 413, (r.status_code, r.text)
    d = r.json()["detail"]
    assert d["code"] == code and d["message"], d
    return d


def case_400_days_pass_401_are_refused():
    assert _get("/admin/stats/revenue", **_window(400)).status_code == 200
    d = _refused(_get("/admin/stats/revenue", **_window(401)), "stats_window_too_long")
    assert (d["days"], d["max_days"]) == (401, 400), d
    assert "400 days" in d["message"], d


def case_iso_instants_and_an_open_end():
    r = _get("/admin/stats/revenue", **{"from": "2025-01-01T10:00:00.000Z",
                                       "to": "2026-10-19T09:59:59.999Z"})
    _refused(r, "stats_window_too_long")
    _refused(_get("/admin/stats/revenue", **{"from": "2020-01-01"}), "stats_window_too_long")


def case_a_report_zone_window_of_400_days_passes():
    first = TO - timedelta(days=399)
    utc = lambda d: (d - timedelta(days=1)).isoformat()  # noqa: E731 — local midnight is 22:00 UTC the day before
    r = _get("/admin/stats/revenue", **{"from": f"{utc(first)}T22:00:00.000Z",
                                       "to": f"{TO.isoformat()}T21:59:59.999Z"})
    assert r.status_code == 200, (r.status_code, r.text)
    d = _refused(_get("/admin/stats/revenue", **{"from": f"{utc(first - timedelta(days=1))}T22:00:00.000Z",
                                                 "to": f"{TO.isoformat()}T21:59:59.999Z"}),
                 "stats_window_too_long")
    assert d["days"] == 401, d


def case_a_dst_fall_back_hour_is_not_a_day():
    from zoneinfo import ZoneInfo
    bud = ZoneInfo("Europe/Budapest")
    first, last = datetime(2025, 10, 25, tzinfo=bud), datetime(2026, 11, 28, 23, 59, 59, 999000, tzinfo=bud)
    assert (last.date() - first.date()).days + 1 == 400
    iso = lambda dt: dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")  # noqa: E731
    assert _get("/admin/stats/revenue", **{"from": iso(first), "to": iso(last)}).status_code == 200
    d = _refused(_get("/admin/stats/revenue", **{"from": iso(first - timedelta(days=1)), "to": iso(last)}),
                 "stats_window_too_long")
    assert d["days"] == 401, d


def case_too_many_creators():
    many = [str(2_000_000 + i) for i in range(51)]
    d = _refused(_get("/admin/stats/revenue", account_id=",".join(many)), "stats_too_many_accounts")
    assert (d["accounts"], d["max_accounts"]) == (51, 50), d
    r = _get("/admin/stats/sales-records", account_id=[",".join(many[:26]), *many[26:]])
    _refused(r, "stats_too_many_accounts")
    assert _get("/admin/stats/revenue", account_id=",".join(many[:50])).status_code == 403
    one = IDS["creator_a"]
    assert _get("/admin/stats/revenue", account_id=",".join([one] * 60)).status_code == 200


def case_no_filter_and_garbage_are_the_routes_own():
    assert _get("/admin/stats/revenue").status_code == 200
    assert _get("/admin/stats/revenue", **{"from": "not-a-date"}).status_code == 400


def case_every_stats_route_is_guarded():
    import server
    routes = sorted({(r.path, m) for r in server.app.routes
                     if getattr(r, "path", "").startswith("/admin/stats/") for m in r.methods})
    assert ("/admin/stats/referrals", "GET") in routes, routes
    assert len(routes) >= 10, routes
    q = urlencode({"from": "2020-01-01", "to": "2026-01-01"})
    for p, m in routes:
        _refused(OWNER.request(m, f"{p}?{q}"), "stats_window_too_long")


if __name__ == "__main__":
    _harness.run()
