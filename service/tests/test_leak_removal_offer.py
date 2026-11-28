#!/usr/bin/env python3
import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import sys  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from sqlalchemy import select, update  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import leak_removal  # noqa: E402
import leak_tracker_api  # noqa: E402
import leak_tracker  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import LeakWatch, UserAccount  # noqa: E402
from permissions import removal_offer_viewer  # noqa: E402
from test_leak_tracker_api import (  # noqa: E402
    CHATTER_A, CREATOR, CREATORS, DOWN, EMP_A, EMP_SCOPED, ERR_401, IDS, KEY_1, KEY_2, ME, MIA_W, OWNER_A, PUT_CREATED,
    SCOPED, SECOND,
    _connect, _enrol, _golden, _live, _rewatch, _roster, _enrol_three, _tracker,
)

CREATOR_ONE = _golden("creator_one")
CREATOR_LEAKS = _golden("creator_leaks")
ONE = f"/v1/creators/{MIA_W}"
LEAKS = f"/v1/creators/{MIA_W}/leaks"
BRAND = ME["response"]["brand"]
CONTACT = ME["response"]["contact_url"]
TRACK = {"noticed": 4, "gone_after_notice": 2, "gone_no_notice": 1, "delisted": 1, "live_after_notice": 1}
TEAM_LEADER = {"enforce": True, "roles": [], "assignments": {str(EMP_SCOPED): "team-leader"}}
ADMIN = {"enforce": True, "roles": [], "assignments": {str(EMP_A): "admin"}}
LEAK_ROLE = {"id": "role-leaks", "name": "Leak watcher", "description": "", "scope": "self",
             "permissions": {"/creators/leaks": True}}
PAGE_ONLY = {"enforce": True, "roles": [LEAK_ROLE], "assignments": {str(EMP_A): "role-leaks"}}
OWNER_ROLE = {"enforce": True, "roles": [], "assignments": {str(EMP_A): "owner"}}
OFFER = {"brand": BRAND, "contact_url": CONTACT, "angle": "came_back", "n": 1}


def _ago(hours: float | None) -> str | None:
    if hours is None:
        return None
    at = datetime.now(timezone.utc) - timedelta(hours=hours)
    return at.isoformat(timespec="seconds").replace("+00:00", "Z")


def _serve(t, *, one: dict | None = None, me: dict | None = None, drop: tuple[str, ...] = ()) -> None:
    body = {k: v for k, v in {**CREATOR_ONE["response"], **(one or {})}.items() if k not in drop}
    t.routes[ONE] = {**CREATOR_ONE, "response": body}
    t.routes["/v1/me"] = {**ME, "response": {**ME["response"], "notices_updated_at": _ago(1), **(me or {})}}
    t.routes[LEAKS] = CREATOR_LEAKS


def _tracked(t) -> None:
    t.answer = PUT_CREATED
    assert _enrol().status_code == 200
    _rewatch(CREATOR, MIA_W)
    _serve(t)


def _drill(client=OWNER_A, account: str = CREATOR) -> dict:
    r = client.get(f"/admin/leaks/watches/{account}")
    assert r.status_code == 200, r.text
    return r.json()


def _snooze(client=OWNER_A, account: str = CREATOR, body=None):
    return client.post(f"/admin/leaks/watches/{account}/offer-snooze", json={"snoozed": True} if body is None else body)


def _snoozed_until(agency: str = IDS["agency_a_owner"]) -> datetime | None:
    async def _read():
        async with get_session() as s:
            return await s.scalar(select(LeakWatch.offer_snoozed_until).where(
                LeakWatch.agency_user_id == agency, LeakWatch.account_id == CREATOR))
    return asyncio.run(_read())


TABLE = [
    ("none", True, "offer", True),
    ("none", False, "offer", True),
    ("unknown", True, "offer", True),
    ("unknown", False, "hidden", False),
    ("pending", True, "starting", False),
    ("pending", False, "starting", False),
    ("active", True, "track", False),
    ("active", False, "track", False),
    ("former", True, "past", True),
    ("former", False, "past", True),
]


def case_every_removal_area_row_at_47h_49h_and_never():
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        for status, fresh, view, offers in TABLE:
            for hours in ((47,) if fresh else (49, None)):
                notices = _ago(hours)
                _serve(t, one={"service_status": status, "removal": TRACK}, me={"notices_updated_at": notices})
                body = _drill()
                label = (status, hours)
                counts = TRACK if fresh and view in ("track", "past") else None
                assert body["removal"] == {"status": status, "view": view, "notices_updated_at": notices,
                                           "stale": not fresh, "counts": counts, "offer_snoozed_until": None}, (label, body["removal"])
                assert body["offer"] == (OFFER if offers else None), (label, body["offer"])


def case_a_missing_or_unrecognised_status_reads_unknown():
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        for label, one, drop in [("missing", {}, ("service_status",)), ("unrecognised", {"service_status": "paused"}, ()),
                                 ("not a string", {"service_status": 3}, ())]:
            _serve(t, one=one, drop=drop)
            fresh = _drill()
            _serve(t, one=one, drop=drop, me={"notices_updated_at": _ago(49)})
            stale = _drill()
            assert (fresh["removal"]["status"], fresh["removal"]["view"]) == ("unknown", "offer"), (label, fresh)
            assert fresh["offer"] == OFFER, label
            assert (stale["removal"]["view"], stale["offer"]) == ("hidden", None), (label, stale)


def case_counts_are_null_when_stale_or_the_service_sends_a_bad_track():
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        for removal in ({**TRACK, "noticed": "4"}, [1, 2], {k: v for k, v in TRACK.items() if k != "delisted"}):
            _serve(t, one={"service_status": "active", "removal": removal})
            assert _drill()["removal"]["counts"] is None, removal
        _serve(t, one={"service_status": "active", "removal": TRACK}, me={"notices_updated_at": "not a time"})
        assert _drill()["removal"]["stale"] is True


def case_the_angle_is_clean_first_then_the_first_true_count():
    base = {"visible": 5, "came_back_30d": 0, "cached": 0, "live_30d": 0, "new_7d": 0}
    for label, over, want in [
        ("came back but nothing visible", {"visible": 0, "came_back_30d": 1}, ("clean", 0)),
        ("all zero", {"visible": 0}, ("clean", 0)),
        ("came back", {"came_back_30d": 2, "cached": 3, "live_30d": 4, "new_7d": 5}, ("came_back", 2)),
        ("cached", {"cached": 3, "live_30d": 4, "new_7d": 5}, ("cached", 3)),
        ("up 30 days", {"live_30d": 4, "new_7d": 5}, ("live_30d", 4)),
        ("new this week", {"new_7d": 5}, ("new_week", 5)),
        ("visible only", {}, ("visible", 5)),
    ]:
        assert leak_removal.angle({**base, **over}) == want, label


def case_the_clean_offer_still_links():
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        _serve(t, one={"offer_counts": {"visible": 0, "came_back_30d": 1, "cached": 1, "live_30d": 0, "new_7d": 0}})
        assert _drill()["offer"] == {**OFFER, "angle": "clean", "n": 0}


def case_owner_and_admin_get_the_offer_team_leader_and_chatter_never():
    for label, roles, client, want in [
        ("owner", None, OWNER_A, OFFER),
        ("admin", ADMIN, CHATTER_A, OFFER),
        ("team leader", TEAM_LEADER, SCOPED, None),
        ("chatter role with the page", PAGE_ONLY, CHATTER_A, None),
        ("assigned role id owner", OWNER_ROLE, CHATTER_A, None),
    ]:
        _connect(roles)
        with _tracker() as t, _live({}):
            _tracked(t)
            body = _drill(client)
        assert body["removal"]["view"] == "offer", label
        assert body["offer"] == want, (label, body["offer"])
    _connect({"enforce": True, "roles": [], "assignments": {str(EMP_A): "chatter"}})
    with _tracker() as t, _live({}):
        _tracked(t)
        assert CHATTER_A.get(f"/admin/leaks/watches/{CREATOR}").status_code == 404
    _connect({**ADMIN, "enforce": False})
    with _tracker() as t, _live({}):
        _tracked(t)
        assert CHATTER_A.get(f"/admin/leaks/watches/{CREATOR}").status_code == 404, "page gate fails closed"


def case_the_offer_viewer_is_the_owner_session_or_an_assigned_admin_id_whatever_enforcement():
    owner, emp = SimpleNamespace(is_owner=True, employee_id=None), SimpleNamespace(is_owner=False, employee_id=7)
    for label, ctx, roles, want in [
        ("owner session", owner, {}, True),
        ("admin", emp, {"enforce": True, "assignments": {"7": "admin"}}, True),
        ("admin, enforcement off", emp, {"enforce": False, "assignments": {"7": "admin"}}, True),
        ("assigned owner id", emp, {"enforce": True, "assignments": {"7": "owner"}}, False),
        ("team leader", emp, {"enforce": True, "assignments": {"7": "team-leader"}}, False),
        ("another employee's admin", emp, {"assignments": {"8": "admin"}}, False),
        ("no employee id", SimpleNamespace(is_owner=False, employee_id=None), {"assignments": {"None": "admin"}}, False),
    ]:
        assert removal_offer_viewer(ctx, roles) is want, label


def case_no_offer_before_the_first_daily_scan():
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        for label, one, drop in [("null", {"first_daily_at": None}, ()), ("absent", {}, ("first_daily_at",)),
                                 ("empty", {"first_daily_at": ""}, ()), ("not a string", {"first_daily_at": 1}, ())]:
            _serve(t, one=one, drop=drop)
            assert _drill()["offer"] is None, label


def case_brand_and_contact_url_must_be_valid():
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        long_url = "https://removal.example/" + "c" * (512 - len("https://removal.example/"))
        for label, me, ok in [
            ("brand at 40", {"brand": "B" * 40}, True),
            ("url at 512", {"contact_url": long_url}, True),
            ("brand missing", {"brand": None}, False),
            ("brand empty", {"brand": ""}, False),
            ("brand blank", {"brand": "  "}, False),
            ("brand over 40", {"brand": "B" * 41}, False),
            ("url missing", {"contact_url": None}, False),
            ("url plain http", {"contact_url": "http://removal.example/contact"}, False),
            ("url relative", {"contact_url": "removal.example/contact"}, False),
            ("url no host", {"contact_url": "https:///contact"}, False),
            ("url with a space", {"contact_url": "https://removal.example/a b"}, False),
            ("url over 512", {"contact_url": long_url + "c"}, False),
            ("url not a string", {"contact_url": ["https://removal.example/"]}, False),
        ]:
            _serve(t, me=me)
            offer = _drill()["offer"]
            assert (offer is not None) == ok, (label, offer)
            if ok:
                assert offer == {**OFFER, **me}, (label, offer)
        _serve(t)
        assert _drill()["offer"] == OFFER
        t.routes["/v1/me"] = DOWN
        assert _drill()["offer"] == OFFER, "the last good /v1/me copy still serves"
        leak_tracker.drop_copies(IDS["agency_a_owner"])
        body = _drill()
        assert body["offer"] is None and body["removal"]["stale"] is True, body


def case_no_offer_key_on_roster_rows_or_the_week_strip():
    _connect()
    with _tracker() as t, _live({}):
        _enrol_three(t)
        t.routes["/v1/creators"] = CREATORS
        body = _roster()
    assert body["rows"] and all(r["this_week"] is None or isinstance(r["this_week"], dict) for r in body["rows"])
    for r in body["rows"]:
        for part in (r, r["this_week"] or {}):
            assert not {"offer", "offer_counts", "first_daily_at", "contact_url"} & set(part), part
    assert "offer" not in body


def case_not_now_snoozes_the_offer_for_seven_days():
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        assert _drill()["offer"] == OFFER
        before = datetime.utcnow()
        r = _snooze()
        after = datetime.utcnow()
        assert r.status_code == 200, r.text
        stored = _snoozed_until()
        assert before + timedelta(days=7) - timedelta(seconds=1) <= stored <= after + timedelta(days=7), stored
        assert r.json() == {"offer_snoozed_until": stored.replace(microsecond=0).isoformat() + "Z"}, r.json()
        body = _drill()
        assert (body["offer"], body["removal"]["view"]) == (None, "offer"), body
        assert body["removal"]["offer_snoozed_until"] == r.json()["offer_snoozed_until"]
        _serve(t, one={"offer_counts": {"visible": 9, "came_back_30d": 5, "cached": 4, "live_30d": 3, "new_7d": 2}})
        t.routes[LEAKS] = {**CREATOR_LEAKS, "response": {**CREATOR_LEAKS["response"],
                           "leaks": CREATOR_LEAKS["response"]["leaks"] * 2}}
        assert _drill()["offer"] is None, "new Leaks and higher counts never reset the snooze"

        async def _expire():
            async with get_session() as s:
                await s.execute(update(LeakWatch).where(LeakWatch.account_id == CREATOR).values(
                    offer_snoozed_until=datetime.utcnow() - timedelta(seconds=1)))
        asyncio.run(_expire())
        expired = _drill()
        assert expired["offer"] is not None and expired["removal"]["offer_snoozed_until"] is None, expired


def case_snooze_is_owner_or_admin_only_and_checks_its_body():
    _connect(TEAM_LEADER)
    with _tracker() as t, _live({}):
        _tracked(t)
        r = _snooze(SCOPED)
        assert r.status_code == 403, r.text
        assert _snoozed_until() is None
        for body in ({}, {"snoozed": False}, {"snoozed": "true"}, []):
            assert _snooze(body=body).status_code == 422, body
        assert _snooze(account=SECOND).status_code == 404, "no watch for that Creator"
        assert _snooze(account="9999999").status_code == 404, "outside the agency"
        assert _snoozed_until() is None
    _connect(OWNER_ROLE)
    with _tracker() as t, _live({}):
        _tracked(t)
        assert _snooze(CHATTER_A).status_code == 403, "assigned owner id is not the Owner session"
        assert _snoozed_until() is None
    _connect(ADMIN)
    with _tracker() as t, _live({}):
        _tracked(t)
        assert _snooze(CHATTER_A).status_code == 200
        assert _snoozed_until() is not None


def case_snooze_is_404_with_the_gates_off():
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        fx.store_blob(IDS["agency_a_owner"], "flags", {"leak_tracker": False})
        assert _snooze().status_code == 404
    assert _snooze().status_code == 404, "deployment gate off"
    assert _snoozed_until() is None


OTHER_W = "w_miavale_b0001"


def _second_agency() -> None:
    agency = IDS["agency_b_owner"]
    now = datetime.utcnow()

    async def _seed():
        async with get_session() as s:
            if await s.scalar(select(UserAccount).where(UserAccount.user_id == agency,
                                                        UserAccount.account_id == CREATOR)) is None:
                s.add(UserAccount(user_id=agency, account_id=CREATOR))
            s.add(LeakWatch(agency_user_id=agency, account_id=CREATOR, watch_id=OTHER_W, platform="onlyfans",
                            username="miavale", consent_at=now, consent_by="owner", synced_at=now))
    asyncio.run(_seed())
    fx.store_blob(agency, "flags", {"leak_tracker": True})
    fx.store_blob(agency, "roles", {"enforce": True, "roles": [], "assignments": {}})
    asyncio.run(leak_tracker.store_key(agency, KEY_2))
    asyncio.run(leak_tracker.bind_tenant(agency, ME["response"]["tenant_id"]))


def case_the_same_creator_in_a_second_agency_keeps_its_card():
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        _second_agency()
        owner_b = fx.login_owner("agency_b_owner")
        t.routes[f"/v1/creators/{OTHER_W}"] = {**t.routes[ONE], "path": f"/v1/creators/{OTHER_W}"}
        t.routes[f"/v1/creators/{OTHER_W}/leaks"] = {**CREATOR_LEAKS, "path": f"/v1/creators/{OTHER_W}/leaks"}
        assert _snooze().status_code == 200
        assert _drill()["offer"] is None
        assert _drill(owner_b)["offer"] == OFFER
        assert _snoozed_until(IDS["agency_b_owner"]) is None


ME_VIDEO = _golden("me_video")
VIDEO = ME_VIDEO["response"]["video"]
POPUP = f"/admin/leaks/watches/{CREATOR}/offer"


def _popup(client=OWNER_A, account: str = CREATOR):
    return client.get(f"/admin/leaks/watches/{account}/offer")


def _serve_video(t, video=VIDEO) -> None:
    _serve(t, me={"video": video})


def _upstream(t) -> list[str]:
    return [r.url.path for r in t.calls]


def case_the_popup_read_answers_the_offer_preview_video_scenes_and_last_checked():
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        _serve_video(t)
        r = _popup()
        assert r.status_code == 200, r.text
        body = r.json()
    one = CREATOR_ONE["response"]
    assert set(body) == {"offer", "preview_leak", "video", "scenes", "last_checked_at"}, body
    assert body["offer"] == OFFER
    assert body["video"] == VIDEO
    assert body["last_checked_at"] == one["last_checked_at"]
    assert body["preview_leak"] == one["preview_leak"], body["preview_leak"]
    assert [x["leak_id"] for x in body["scenes"]["google"]] == ["lk_0001", "lk_0002"], body["scenes"]
    assert body["scenes"]["google"][0] == {"leak_id": "lk_0001", "leak_site": "example-leaks.test", "kind": "page",
                                          "title": "miavale onlyfans leak", "pill": "live", "preview": None}
    assert body["scenes"]["mega"] == [{"leak_id": "lk_0003", "leak_site": "example-index.test", "kind": "mega",
                                       "title": "miavale folder", "pill": "listed", "preview": None}]
    assert all(not body["scenes"][kind] for kind in ("google_images", "forum", "x")), body["scenes"]


def case_a_missing_or_bad_video_reads_null():
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        for label, video in [("missing", None), ("not a dict", [1]), ("zero duration", {**VIDEO, "duration_s": 0}),
                             ("bool duration", {**VIDEO, "duration_s": True}),
                             ("has_poster not bool", {**VIDEO, "has_poster": "yes"})]:
            _serve_video(t, video)
            assert _popup().json()["video"] is None, label
        _serve(t)
        assert _popup().json()["video"] is None, "a /v1/me with no video field"


def case_cues_are_kept_only_sorted_inside_duration_at_most_12_and_known():
    cues = VIDEO["cues"]
    for label, raw, ok in [
        ("golden", cues, True),
        ("equal times", [{"t_s": 3, "kind": "google"}, {"t_s": 3, "kind": "mega"}], True),
        ("cue at duration", cues[:-1] + [{"t_s": 42, "kind": "end"}], True),
        ("twelve", [{"t_s": i, "kind": "x"} for i in range(12)], True),
        ("unsorted", list(reversed(cues)), False),
        ("past duration", cues[:-1] + [{"t_s": 42.5, "kind": "end"}], False),
        ("thirteen", [{"t_s": i, "kind": "x"} for i in range(13)], False),
        ("unknown kind", cues[:-1] + [{"t_s": 40, "kind": "tiktok"}], False),
        ("negative", [{"t_s": -1, "kind": "google"}], False),
        ("string time", [{"t_s": "3", "kind": "google"}], False),
        ("bool time", [{"t_s": True, "kind": "google"}], False),
        ("not a cue", [3], False),
        ("not a list", {"t_s": 3, "kind": "google"}, False),
        ("null", None, False),
    ]:
        got = leak_removal.video_of({**VIDEO, "cues": raw})
        assert got["cues"] == ([{"t_s": c["t_s"], "kind": c["kind"]} for c in raw] if ok else None), (label, got)
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        _serve_video(t, {**VIDEO, "cues": list(reversed(cues))})
        assert _popup().json()["video"] == {**VIDEO, "cues": None}


def _leak(n: int, *, kind: str = "page", site: str = "example-leaks.test", sources=("google_web",), pill: str = "live",
          seen: str | None = None, preview: dict | None = None) -> dict:
    first = f"2026-11-{n:02d}T00:00:00Z"
    return {"leak_id": f"lk_{n:04d}", "leak_site": site, "kind": kind, "title": f"t{n}", "pill": pill,
            "first_seen_at": first, "sources": list(sources), "preview": preview,
            "events": [{"at": first, "type": "seen", "data": {}}] + ([{"at": seen, "type": "seen", "data": {}}] if seen else [])}


def case_overlay_scenes_maps_each_kind_caps_and_orders_newest_seen_first():
    shot = {"vertical": "images", "seen_at": "2026-11-20T00:00:00Z"}
    leaks = [
        _leak(1), _leak(2, seen="2026-11-29T00:00:00Z"), _leak(3), _leak(4), _leak(5),
        _leak(6, pill="gone"), _leak(7, pill="listed"), _leak(8, pill="not_checked"), _leak(9, pill="cached"),
        *(_leak(10 + i, kind="media", sources=("google_images",), preview=shot) for i in range(7)),
        _leak(20, kind="media", sources=("google_images",)),
        _leak(21, kind="mega", sources=("mega_index",), pill="listed"), _leak(22, kind="mega", sources=("mega_index",), pill="gone"),
        _leak(23, sources=("site_search",), site="forum.example.test"),
        _leak(24, sources=("site_search",), site="x.com"), _leak(25, sources=("x_search",), site="twitter.com"),
    ]
    scenes = leak_removal.overlay_scenes(leaks)
    ids = {k: [x["leak_id"] for x in v] for k, v in scenes.items()}
    assert ids == {
        "google": ["lk_0002", "lk_0009", "lk_0005", "lk_0004"],
        "google_images": ["lk_0016", "lk_0015", "lk_0014", "lk_0013", "lk_0012", "lk_0011"],
        "mega": ["lk_0021"],
        "forum": ["lk_0023"],
        "x": ["lk_0025", "lk_0024"],
    }, ids
    assert scenes["mega"] == [{"leak_id": "lk_0021", "leak_site": "example-leaks.test", "kind": "mega", "title": "t21",
                               "pill": "listed", "preview": None}]
    assert all(x["preview"] is None for v in scenes.values() for x in v), "previews stay off in the CRM"
    assert leak_removal.overlay_scenes([]) == {k: [] for k in ("google", "google_images", "mega", "forum", "x")}


def case_the_popup_read_is_404_when_the_offer_decision_fails():
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        assert _popup().status_code == 200
        _serve(t, one={"first_daily_at": None})
        assert _popup().status_code == 404, "before the first daily scan"
        _serve(t, me={"brand": None})
        assert _popup().status_code == 404, "no brand"
        _serve(t, one={"service_status": "active"})
        assert _popup().status_code == 404, "active has no offer"
        _serve(t)
        assert _popup(account=SECOND).status_code == 404, "no watch"
        assert _popup(account="9999999").status_code == 404, "outside the agency"
        assert _snooze().status_code == 200
        assert _popup().status_code == 404, "snoozed"
        fx.store_blob(IDS["agency_a_owner"], "flags", {"leak_tracker": False})
        assert _popup().status_code == 404, "agency flag off"
    for label, roles, client in [("team leader", TEAM_LEADER, SCOPED), ("chatter role with the page", PAGE_ONLY, CHATTER_A),
                                 ("assigned owner id", OWNER_ROLE, CHATTER_A)]:
        _connect(roles)
        with _tracker() as t, _live({}):
            _tracked(t)
            before = len(t.calls)
            assert _popup(client).status_code == 404, label
            assert len(t.calls) == before, (label, "no egress")
    _connect(ADMIN)
    with _tracker() as t, _live({}):
        _tracked(t)
        assert _popup(CHATTER_A).status_code == 200, "admin"


def case_the_popup_read_never_uses_the_read_cache():
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        assert _drill()["offer"] == OFFER
        before = len(t.calls)
        assert _popup().status_code == 200
        assert {ONE, "/v1/me", LEAKS} <= set(_upstream(t)[before:]), _upstream(t)[before:]
        for path in (ONE, "/v1/me", LEAKS):
            _serve(t)
            t.routes[path] = DOWN
            assert _drill()["offer"] == OFFER or path == LEAKS, "the drill-in may serve its copy"
            r = _popup()
            assert r.status_code == 503, (path, r.status_code, "a down live read is never answered from the cache")


def case_the_popup_read_maps_a_refused_key_and_a_deleted_watch():
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        t.routes["/v1/me"] = ERR_401
        r = _popup()
        assert r.status_code == 409 and r.json()["detail"]["error"] == "key_invalid", r.text
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        t.routes[ONE] = {**_golden("err_410"), "path": ONE}
        assert _popup().status_code == 404
        assert _drill()["tracked"] is False, "the deleted watch is forgotten"


VIDEO_PATH = "/v1/offer-video/video"
BYTES = bytes(range(256)) * 4


def _part(part: str = "video", status: int = 206, ctype: str = "video/mp4", raw: bytes = BYTES[:100],
          headers: dict | None = None) -> dict:
    h = {"content-type": ctype, **({"content-range": "bytes 0-99/1024", "accept-ranges": "bytes"} if status == 206 else {}),
         **(headers or {})}
    return {"method": "GET", "path": f"/v1/offer-video/{part}", "status": status, "raw": raw, "headers": h}


def _video(client=OWNER_A, part: str = "video", headers=None, query: str = ""):
    return client.get(f"/admin/leaks/offer-video/{part}{query}", headers=headers)


def _closed(r) -> None:
    assert r.headers.get("cache-control") == "private, no-store", (r.status_code, r.headers)
    assert r.headers.get("x-content-type-options") == "nosniff", (r.status_code, r.headers)


def case_the_offer_video_streams_each_part_with_its_fixed_type():
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        t.routes[VIDEO_PATH] = _part()
        r = _video(headers={"Range": "bytes=0-99"})
        assert r.status_code == 206, r.text
        assert r.content == BYTES[:100]
        assert (r.headers["content-type"], r.headers["content-range"], r.headers["accept-ranges"],
                r.headers["content-length"]) == ("video/mp4", "bytes 0-99/1024", "bytes", "100"), r.headers
        _closed(r)
        for part, ctype, raw in [("poster", "image/webp", b"RIFF\x0c\x00\x00\x00WEBPVP8 "),
                                 ("captions", "text/vtt; charset=utf-8", b"WEBVTT\n\n00:00.000 --> 00:02.000\nHi\n")]:
            t.routes[f"/v1/offer-video/{part}"] = _part(part, 200, ctype, raw)
            r = _video(part=part)
            assert (r.status_code, r.content) == (200, raw), (part, r.status_code)
            assert r.headers["content-type"].split(";")[0] == ctype.split(";")[0], r.headers
            _closed(r)
        t.routes[VIDEO_PATH] = _part(status=200, raw=BYTES, headers={"accept-ranges": "bytes"})
        r = _video(query=f"?account_id={CREATOR}")
        assert (r.status_code, r.content) == (200, BYTES), "the Creator query names the Agency for a bare <video> GET"


def case_the_offer_video_sends_only_the_bearer_and_one_range_upstream():
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        t.routes[VIDEO_PATH] = _part()
        before = len(t.calls)
        session = "; ".join(f"{k}={v}" for k, v in OWNER_A.cookies.items())
        r = _video(headers={"Range": "bytes=0-99", "Cookie": f"{session}; lt_marker=cookie_secret_9", "X-Account-Id": CREATOR,
                            "Referer": f"http://testserver/creators/leaks?open={CREATOR}", "X-Watch-Id": MIA_W},
                   query=f"?account_id={CREATOR}&watch_id={MIA_W}&leak_id=lk_0001&handle=miavale")
        assert r.status_code == 206, r.text
        (req,) = t.calls[before:]
        assert str(req.url) == "http://127.0.0.1:9" + VIDEO_PATH, req.url
        assert req.headers.get_list("range") == ["bytes=0-99"]
        assert req.headers["authorization"] == f"Bearer {KEY_1}"
        sent = {k.lower() for k in req.headers}
        assert not sent & {"cookie", "x-account-id", "referer", "x-watch-id", "x-employee-id", "origin"}, sent
        blob = str(req.url) + repr(list(req.headers.items()))
        for secret in (MIA_W, "lk_0001", "miavale", CREATOR, "cookie_secret_9", *OWNER_A.cookies.values()):
            assert secret not in blob, secret
        for part in ("poster", "captions"):
            t.routes[f"/v1/offer-video/{part}"] = _part(part, 200, "image/webp" if part == "poster" else "text/vtt", b"x")
            before = len(t.calls)
            assert _video(part=part, headers={"Range": "bytes=0-0"}).status_code == 200
            assert "range" not in t.calls[before].headers, f"{part} takes no Range"


def case_a_bad_or_second_range_is_refused_before_egress():
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        t.routes[VIDEO_PATH] = _part()
        before = len(t.calls)
        for rng in ("bytes=0-1,5-9", "bytes=0-99, 200-299", "bytes=-", "bytes=abc", "items=0-1", "bytes=50-10",
                    "bytes=" + "9" * 40 + "-"):
            r = _video(headers={"Range": rng})
            assert r.status_code == 416, (rng, r.status_code)
            _closed(r)
        r = OWNER_A.get("/admin/leaks/offer-video/video", headers=[("Range", "bytes=0-1"), ("Range", "bytes=2-3")])
        assert r.status_code == 416, r.status_code
        _closed(r)
        assert len(t.calls) == before, "no egress"


def case_the_offer_video_is_404_for_a_team_leader_an_unknown_part_or_the_gates_off():
    _connect(TEAM_LEADER)
    with _tracker() as t, _live({}):
        _tracked(t)
        t.routes[VIDEO_PATH] = _part()
        before = len(t.calls)
        r = _video(SCOPED)
        assert r.status_code == 404, r.text
        _closed(r)
        for part in ("cues", "offer.mp4", "VIDEO", "me"):
            r = _video(part=part)
            assert r.status_code == 404, part
            _closed(r)
        assert len(t.calls) == before, "no egress"
        fx.store_blob(IDS["agency_a_owner"], "flags", {"leak_tracker": False})
        r = _video()
        assert r.status_code == 404
        _closed(r)
    _connect(PAGE_ONLY)
    with _tracker() as t, _live({}):
        _tracked(t)
        t.routes[VIDEO_PATH] = _part()
        assert _video(CHATTER_A).status_code == 404, "chatter with the page"
    _connect(ADMIN)
    with _tracker() as t, _live({}):
        _tracked(t)
        t.routes[VIDEO_PATH] = _part()
        assert _video(CHATTER_A, headers={"Range": "bytes=0-99"}).status_code == 206, "admin"


def case_the_offer_video_refuses_a_wrong_upstream_type_a_redirect_and_odd_statuses():
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        for label, answer in [
            ("html on video", _part(status=200, ctype="text/html", raw=b"<html></html>")),
            ("json on video", _part(status=200, ctype="application/json", raw=b"{}")),
            ("no type", {**_part(status=200), "headers": {}}),
            ("redirect", _part(status=302, headers={"location": "https://elsewhere.test/v.mp4"})),
            ("404", {"method": "GET", "path": VIDEO_PATH, "status": 404, "response": {"error": "not_found"}}),
            ("500", {"method": "GET", "path": VIDEO_PATH, "status": 500, "response": {"error": "x"}}),
            ("connect", DOWN),
        ]:
            t.routes[VIDEO_PATH] = answer
            before = len(t.calls)
            r = _video()
            assert r.status_code in (404, 503), (label, r.status_code)
            assert r.status_code == (503 if label == "connect" else 404), (label, r.status_code)
            assert b"<html" not in r.content, label
            _closed(r)
            assert len(t.calls) == before + 1, (label, "never followed")
        t.routes["/v1/offer-video/captions"] = _part("captions", 200, "text/html", b"<script>")
        assert _video(part="captions").status_code == 404
        t.routes[VIDEO_PATH] = {**_part(status=416, raw=b""), "headers": {"content-range": "bytes */1024"}}
        r = _video(headers={"Range": "bytes=2000-3000"})
        assert (r.status_code, r.headers.get("content-range")) == (416, "bytes */1024"), r.status_code
        _closed(r)


def case_an_upstream_401_marks_the_key_invalid():
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        t.routes[VIDEO_PATH] = {**ERR_401, "path": VIDEO_PATH}
        r = _video()
        assert r.status_code == 404, r.status_code
        _closed(r)
        assert leak_tracker.key_invalid(IDS["agency_a_owner"]) is True
        assert OWNER_A.get("/admin/leaks/setup").json()["key"] == "invalid"
        before = len(t.calls)
        assert _video().status_code == 404
        assert len(t.calls) == before, "an invalid key makes no further call"


def case_the_offer_video_bounds_size_and_concurrent_streams():
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        t.routes["/v1/offer-video/poster"] = _part("poster", 200, "image/webp", b"x" * 64)
        cap = dict(leak_removal.VIDEO_PARTS)
        try:
            leak_removal.VIDEO_PARTS["poster"] = ("image/webp", 32)
            r = _video(part="poster")
            assert r.status_code == 404, r.status_code
            _closed(r)
        finally:
            leak_removal.VIDEO_PARTS.update(cap)
        assert _video(part="poster").status_code == 200
        t.routes[VIDEO_PATH] = _part()
        t.routes["/v1/offer-video/captions"] = _part("captions", 200, "text/vtt", b"WEBVTT\n")
        saved = leak_tracker_api.STREAMS_MAX
        try:
            leak_tracker_api.STREAMS_MAX = 0
            before = len(t.calls)
            r = _video()
            assert r.status_code == 429, r.status_code
            _closed(r)
            assert len(t.calls) == before
            assert _video(part="poster").status_code == 200, "only video counts toward the cap"
            assert _video(part="captions").status_code == 200, "only video counts toward the cap"
        finally:
            leak_tracker_api.STREAMS_MAX = saved
        assert not leak_tracker_api._streams.get(IDS["agency_a_owner"]), "every stream released its slot"


def _video_call(send_body, *, send_start=None):
    cookie = "; ".join(f"{k}={v}" for k, v in OWNER_A.cookies.items()).encode()
    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}, "http_version": "1.1", "method": "GET",
             "scheme": "http", "path": "/admin/leaks/offer-video/video", "raw_path": b"/admin/leaks/offer-video/video",
             "query_string": b"", "root_path": "", "client": ("testclient", 50000), "server": ("testserver", 80),
             "headers": [(b"host", b"testserver"), (b"cookie", cookie)]}

    async def receive():
        await asyncio.Event().wait()

    async def send(message):
        if message["type"] == "http.response.start" and send_start:
            send_start(message)
        if message["type"] == "http.response.body":
            await send_body(message)
    return asyncio.ensure_future(OWNER_A.app(scope, receive, send))


def _abandoned_generators_stay_open(work):
    async def run():
        sys.set_asyncgen_hooks(firstiter=lambda gen: None, finalizer=lambda gen: None)
        return await work()
    return asyncio.run(run())


def _asgi(send_body) -> int:
    async def work():
        await asyncio.gather(asyncio.wait_for(_video_call(send_body), 2), return_exceptions=True)
        return leak_tracker_api._streams.get(IDS["agency_a_owner"], 0)
    return _abandoned_generators_stay_open(work)


def case_a_client_that_leaves_mid_stream_frees_its_slot():
    agency = IDS["agency_a_owner"]
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        t.routes[VIDEO_PATH] = _part(status=200, raw=BYTES * 256)

        async def gone(message):
            raise OSError("client went away")
        assert _asgi(gone) == 0, "a disconnect frees the slot"

        async def cancelled():
            started = asyncio.Event()

            async def hang(message):
                started.set()
                await asyncio.Event().wait()
            task = _video_call(hang)
            await asyncio.wait_for(started.wait(), 2)
            assert leak_tracker_api._streams.get(agency) == 1, "the slot is held while streaming"
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return leak_tracker_api._streams.get(agency, 0)
        assert _abandoned_generators_stay_open(cancelled) == 0, "a cancelled stream frees the slot"

        async def cut():
            yield BYTES[:100]
            raise leak_tracker.httpx.ReadError("upstream cut")
        t.routes[VIDEO_PATH] = {**_part(status=200), "raw": cut()}
        assert _asgi(lambda message: asyncio.sleep(0)) == 0, "a truncated upstream frees the slot"


def case_stalled_video_releases_the_slot_before_the_asgi_wait_expires():
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        original = leak_tracker_api.STREAM_FOR_S
        leak_tracker_api.STREAM_FOR_S = 0.25
        try:
            async def stall():
                await asyncio.Event().wait()

            class StalledStream(leak_tracker.httpx.AsyncByteStream):
                def __init__(self):
                    self.closed = asyncio.Event()
                    self.reading = asyncio.Event()

                async def __aiter__(self):
                    for _ in range(3):
                        yield BYTES * 64
                    self.reading.set()
                    await stall()

                async def aclose(self):
                    self.closed.set()

            async def drive(stall_client):
                upstream = StalledStream()
                sending = asyncio.Event()
                part = _part(status=200, headers={"content-length": str(4 * 64 * len(BYTES))})
                part["stream"] = upstream
                t.routes[VIDEO_PATH] = part

                starts, bodies = [], []

                async def send(message):
                    bodies.append(message.get("body", b""))
                    if stall_client:
                        sending.set()
                        await stall()

                task = _video_call(send, send_start=starts.append)
                try:
                    stalled = sending if stall_client else upstream.reading
                    await asyncio.wait_for(stalled.wait(), 1)
                    assert leak_tracker_api._streams.get(IDS["agency_a_owner"]) == 1
                    await asyncio.wait_for(upstream.closed.wait(), 1)
                    assert not leak_tracker_api._streams.get(IDS["agency_a_owner"])
                    if not stall_client:
                        assert dict(starts[0]["headers"])[b"content-length"] == part["headers"]["content-length"].encode()
                        assert sum(map(len, bodies)) == 3 * 64 * len(BYTES)
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

            _abandoned_generators_stay_open(lambda: drive(False))
            _abandoned_generators_stay_open(lambda: drive(True))
        finally:
            leak_tracker_api.STREAM_FOR_S = original


def case_stale_creator_details_never_supply_fresh_removal_counts():
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        _serve(t, one={"service_status": "active", "removal": TRACK})
        assert _drill()["removal"]["counts"] == TRACK
        t.routes[ONE] = DOWN
        stale = _drill()["removal"]
        assert stale["stale"] is True and stale["counts"] is None, stale


def case_a_non_http_error_opening_the_stream_closes_the_client_and_frees_the_slot():
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        made = []
        build = leak_tracker.httpx.AsyncClient
        leak_tracker.httpx.AsyncClient = lambda **kw: made.append(build(**kw)) or made[-1]
        try:
            t.routes[VIDEO_PATH] = RuntimeError("boom")
            assert _asgi(lambda message: asyncio.sleep(0)) == 0
        finally:
            leak_tracker.httpx.AsyncClient = build
        assert made and all(c.is_closed for c in made), made


def case_the_isolation_404_for_a_foreign_creator_query_is_no_store():
    _connect()
    with _tracker() as t, _live({}):
        _tracked(t)
        t.routes[VIDEO_PATH] = _part()
        before = len(t.calls)
        r = _video(query=f"?account_id={IDS['creator_b']}")
        assert r.status_code == 404, r.status_code
        _closed(r)
        assert len(t.calls) == before


if __name__ == "__main__":
    _harness.run()
