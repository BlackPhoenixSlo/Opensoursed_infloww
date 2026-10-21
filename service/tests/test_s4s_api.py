#!/usr/bin/env python3
"""Share for Share's Relay router and storage (docs/spec/phase-03-share-for-share.md, tickets 15 and 16).

The seam is the Relay over HTTP with real session cookies from the shared
two-Agency fixture (`/auth/login`, `/chatter/login`): every assertion is on a
status code, a response body or the rows an endpoint leaves behind. The
Discovery cases (ticket 16, ADR-0011) seed extra Creators and a third Agency
in the database, then drive them in and out of Discovery over HTTP. Two
storage cases close the file: Alembic's own CLI cycles the S4S migration on
the harness's temp database (`-x url=`, never the `alembic.ini` default), and
the `init_db()` catch-up rebuilds the four S4S tables after they are dropped.

Run: ./venv/bin/python service/tests/test_s4s_api.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

from sqlalchemy import delete, update  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
from _s4s_fixtures import (  # noqa: E402
    OF_ME, audit_rows, count, db as _db, list_in_discovery as _list_in_discovery, new_post as _new_post,
    of_profile as _of_profile, profile as _profile, profiles as _profiles, seed_creators as _seed_creators,
    with_env as _with_env,
)
from db.engine import get_session, init_db  # noqa: E402
from db.models import Account, S4SPost, S4SProfile, User, UserAccount  # noqa: E402

IDS = fx.seed_two_agencies()
A = IDS["creator_a"]
B = IDS["creator_b"]
# An avatar as OnlyFans serves it (public, unsigned): the only kind a profile keeps.
ALPHA_AVATAR = "https://thumbs.onlyfans.com/public/files/thumbs/c144/alpha/avatar.jpg"

_REPO = Path(__file__).resolve().parents[2]
_MIGRATIONS = _REPO / "service" / "db" / "migrations"

_TABLES = ("s4s_profiles", "s4s_posts", "s4s_requests", "s4s_schedule")
_PARTIAL_UNIQUE = {"uq_s4s_posts_primary": "WHERE is_primary",
                   "uq_s4s_requests_open_pair": "WHERE status IN ('pending','skipped')"}


def _every_route(client, account_id: str = A) -> list:
    # 401 and 403 come before 404 and 400, so an id that may not exist is fine here.
    p = f"/admin/s4s/profiles/{account_id}"
    return [
        ("GET /admin/s4s/profiles", client.get("/admin/s4s/profiles")),
        ("GET /admin/s4s/discover", client.get("/admin/s4s/discover?q=x")),
        ("PUT profile", client.put(p, json={"opted_in": True})),
        ("POST posts", client.post(f"{p}/posts", json={"caption": "x"})),
        ("PATCH post", client.patch(f"{p}/posts/1", json={"caption": "x"})),
        ("DELETE post", client.delete(f"{p}/posts/1")),
        ("POST primary", client.post(f"{p}/posts/1/primary")),
    ]


# ── Sessions: 401, 403 ───────────────────────────────────────────────

def case_signed_out_is_401_on_every_route_with_and_without_anonymous_admin():
    anon = _harness.make_client()
    for label, r in _every_route(anon):
        assert r.status_code == 401, f"{label} signed out: {r.status_code} {r.text}"
    for label, r in _with_env("ALLOW_ANONYMOUS_ADMIN", "1", lambda: _every_route(anon)):
        assert r.status_code == 401, f"{label} with ALLOW_ANONYMOUS_ADMIN=1: {r.status_code} {r.text}"
    assert count(S4SProfile) == 0 and count(S4SPost) == 0, "a signed-out call wrote S4S rows"


def case_chatter_is_403_on_every_route():
    for name in ("chatter_a", "chatter_ab"):
        chatter = fx.login_chatter(name)
        for label, r in _every_route(chatter):
            assert r.status_code == 403, f"{label} as {name}: {r.status_code} {r.text}"
    assert count(S4SProfile) == 0 and count(S4SPost) == 0, "a chatter wrote S4S rows"


# ── Profiles ─────────────────────────────────────────────────────────

def case_profiles_list_only_own_creators_opted_out_with_defaults_and_the_read_writes_no_row():
    body = _profiles(fx.login_owner("agency_a_owner"))
    assert body["live_posting"] is True, body  # on by default
    assert body["profiles"] == [{
        "account_id": A, "profile_id": None, "opted_in": False, "discovery_visible": True,
        "daily_limit": 1, "display_name": "creator_a", "username": "creator_a", "avatar_url": None,
        "posts": [],
    }], body
    assert [p["account_id"] for p in _profiles(fx.login_owner("agency_b_owner"))["profiles"]] == [B]
    assert count(S4SProfile) == 0, "a profiles read wrote a row"


def case_live_posting_is_read_on_every_call():
    owner_a = fx.login_owner("agency_a_owner")
    for off in ("0", "false", "No", " off "):
        assert _with_env("S4S_LIVE_POSTING", off, lambda: _profiles(owner_a))["live_posting"] is False, off
    for on in ("1", "true", ""):
        assert _with_env("S4S_LIVE_POSTING", on, lambda: _profiles(owner_a))["live_posting"] is True, on
    assert _profiles(owner_a)["live_posting"] is True


def case_put_upserts_the_profile_and_writes_one_audit_row_per_change():
    owner_a = fx.login_owner("agency_a_owner")
    _of_profile(A, "Fixture Alpha", "fixture_alpha", ALPHA_AVATAR)
    r = owner_a.put(f"/admin/s4s/profiles/{A}", json={
        "opted_in": True, "discovery_visible": False, "daily_limit": 2,
    })
    assert r.status_code == 200, f"PUT: {r.status_code} {r.text}"
    got = _profile(owner_a, A)
    assert isinstance(got["profile_id"], int), got
    assert {k: got[k] for k in ("opted_in", "discovery_visible", "daily_limit", "display_name",
                                "username", "avatar_url")} == {
        "opted_in": True, "discovery_visible": False, "daily_limit": 2, "display_name": "Fixture Alpha",
        "username": "fixture_alpha", "avatar_url": ALPHA_AVATAR}, got
    assert r.json() == got, (r.json(), got)

    # A second, partial PUT updates the same row and leaves the other fields.
    r = owner_a.put(f"/admin/s4s/profiles/{A}", json={"daily_limit": 3, "discovery_visible": True})
    assert r.status_code == 200, f"second PUT: {r.status_code} {r.text}"
    again = _profile(owner_a, A)
    assert again["profile_id"] == got["profile_id"] and again["daily_limit"] == 3, again
    assert again["opted_in"] is True and again["display_name"] == "Fixture Alpha", again
    assert count(S4SProfile, account_id=A) == 1

    rows = audit_rows("s4s.profile_update")
    assert len(rows) == 2, [r.payload_json for r in rows]
    for row in rows:
        assert row.account_id == A and row.employee_id is None, (row.account_id, row.employee_id)
        payload = json.loads(row.payload_json)
        assert payload["agency_user_id"] == IDS["agency_a_owner"], payload
        assert payload["profile_id"] == got["profile_id"], payload
        assert set(payload) == {"agency_user_id", "profile_id", "changed", "opted_in"}, payload
    assert json.loads(rows[1].payload_json)["changed"] == ["daily_limit", "discovery_visible"]


def case_the_display_fields_are_the_creators_onlyfans_profile_and_cannot_be_typed():
    owner_a = fx.login_owner("agency_a_owner")
    before = _profile(owner_a, A)
    for body in ({"display_name": "Typed"}, {"username": "typed"}, {"avatar_url": "https://example.invalid/x.png"},
                 {"daily_limit": 1, "display_name": "Typed"}):
        r = owner_a.put(f"/admin/s4s/profiles/{A}", json=body)
        assert r.status_code == 400 and "unknown field" in r.text, f"{body!r}: {r.status_code} {r.text}"
    assert _profile(owner_a, A) == before

    # A list reads OnlyFans again and keeps the new copy: what Discovery shows.
    _of_profile(A, "Alpha Renamed", "alpha_renamed")
    got = _profile(owner_a, A)
    assert (got["display_name"], got["username"], got["avatar_url"]) == ("Alpha Renamed", "alpha_renamed", None), got
    # No name on OnlyFans reads as the @username; an avatar off OnlyFans' hosts is never kept.
    OF_ME[A] = {"name": "", "username": "alpha_bare", "avatar": "https://example.invalid/x.png"}
    got = _profile(owner_a, A)
    assert (got["display_name"], got["username"], got["avatar_url"]) == ("alpha_bare", "alpha_bare", None), got

    # OnlyFans unreadable: the stored copy stays, less an avatar an owner once typed.
    _of_profile(A, "Fixture Alpha", "fixture_alpha", ALPHA_AVATAR)
    assert _profile(owner_a, A)["avatar_url"] == ALPHA_AVATAR
    OF_ME.pop(A)
    assert _profile(owner_a, A)["avatar_url"] == ALPHA_AVATAR, "a stored OnlyFans avatar stays"
    _db(update(S4SProfile).where(S4SProfile.account_id == A).values(avatar_url="https://example.invalid/typed.png"))
    got = _profile(owner_a, A)
    assert (got["display_name"], got["avatar_url"]) == ("Fixture Alpha", None), got


def case_bad_profile_bodies_are_400_and_change_nothing():
    owner_a = fx.login_owner("agency_a_owner")
    before = _profile(owner_a, A)
    audits = len(audit_rows("s4s.profile_update"))
    bad = [
        {"daily_limit": 0}, {"daily_limit": 4}, {"daily_limit": "2"}, {"daily_limit": True},
        {"daily_limit": 2.5}, {"opted_in": "yes"}, {"discovery_visible": 1},
        {"display_name": ""}, {"display_name": "x" * 65}, {"username": "y" * 65},
        {"avatar_url": "javascript:alert(1)"}, {"avatar_url": 5}, {"nickname": "z"}, [], "text",
    ]
    for body in bad:
        r = owner_a.put(f"/admin/s4s/profiles/{A}", json=body)
        assert r.status_code == 400, f"{body!r}: {r.status_code} {r.text}"
    r = owner_a.put(f"/admin/s4s/profiles/{A}", content=b"{not json",
                    headers={"content-type": "application/json"})
    assert r.status_code == 400, f"broken JSON: {r.status_code} {r.text}"
    assert _profile(owner_a, A) == before
    assert len(audit_rows("s4s.profile_update")) == audits, "a refused PUT wrote an audit row"


def case_opting_out_a_creator_with_no_requests_or_slots_succeeds():
    owner_a = fx.login_owner("agency_a_owner")
    assert _profile(owner_a, A)["opted_in"] is True, "setup: Creator A opted in"
    r = owner_a.put(f"/admin/s4s/profiles/{A}", json={"opted_in": False})
    assert r.status_code == 200, f"opt out: {r.status_code} {r.text}"
    assert _profile(owner_a, A)["opted_in"] is False
    assert json.loads(audit_rows("s4s.profile_update")[-1].payload_json)["opted_in"] is False


# ── S4S posts ────────────────────────────────────────────────────────

def case_posts_create_edit_delete_and_move_the_primary_mark():
    owner_a = fx.login_owner("agency_a_owner")
    assert _profile(owner_a, A)["posts"] == [], "setup: Creator A has no post"
    one = _new_post(owner_a, A, "First promo text")
    two = _new_post(owner_a, A, "Second promo text")
    # Made while the Creator had no Primary post, the first is its Primary post; the second is not.
    assert one == {"id": one["id"], "caption": "First promo text", "is_primary": True, "media": []}, one
    assert two["is_primary"] is False, two
    assert [p["id"] for p in _profile(owner_a, A)["posts"]] == [one["id"], two["id"]]

    r = owner_a.post(f"/admin/s4s/profiles/{A}/posts/{one['id']}/primary")
    assert r.status_code == 200 and r.json()["is_primary"] is True, f"primary: {r.status_code} {r.text}"
    r = owner_a.post(f"/admin/s4s/profiles/{A}/posts/{two['id']}/primary")
    assert r.status_code == 200, f"move primary: {r.status_code} {r.text}"
    assert {p["id"]: p["is_primary"] for p in _profile(owner_a, A)["posts"]} == {one["id"]: False, two["id"]: True}

    r = owner_a.patch(f"/admin/s4s/profiles/{A}/posts/{two['id']}", json={"caption": "Edited promo"})
    assert r.status_code == 200, f"edit: {r.status_code} {r.text}"
    assert r.json() == {"id": two["id"], "caption": "Edited promo", "is_primary": True, "media": []}, r.json()

    r = owner_a.delete(f"/admin/s4s/profiles/{A}/posts/{one['id']}")
    assert r.status_code == 200, f"delete: {r.status_code} {r.text}"
    assert _profile(owner_a, A)["posts"] == [{"id": two["id"], "caption": "Edited promo", "is_primary": True, "media": []}]

    # With the Primary post deleted, the next post made takes the mark.
    r = owner_a.delete(f"/admin/s4s/profiles/{A}/posts/{two['id']}")
    assert r.status_code == 200, f"delete primary: {r.status_code} {r.text}"
    three = _new_post(owner_a, A, "Third promo text")
    assert three["is_primary"] is True, three


def case_a_caption_over_5000_characters_is_400():
    owner_a = fx.login_owner("agency_a_owner")
    before = count(S4SPost, account_id=A)
    for body in ({"caption": "c" * 5001}, {"caption": ""}, {"caption": 7}, {}):
        r = owner_a.post(f"/admin/s4s/profiles/{A}/posts", json=body)
        assert r.status_code == 400, f"create {body!r:.40}: {r.status_code} {r.text}"
    post = _profile(owner_a, A)["posts"][0]
    r = owner_a.patch(f"/admin/s4s/profiles/{A}/posts/{post['id']}", json={"caption": "c" * 5001})
    assert r.status_code == 400, f"edit over 5000: {r.status_code} {r.text}"
    assert count(S4SPost, account_id=A) == before
    exactly = _new_post(owner_a, A, "c" * 5000)
    assert len(exactly["caption"]) == 5000
    owner_a.delete(f"/admin/s4s/profiles/{A}/posts/{exactly['id']}")


def case_the_21st_post_is_409():
    owner_b = fx.login_owner("agency_b_owner")
    for i in range(20):
        _new_post(owner_b, B, f"Promo {i + 1}")
    r = owner_b.post(f"/admin/s4s/profiles/{B}/posts", json={"caption": "Promo 21"})
    assert r.status_code == 409, f"21st post: {r.status_code} {r.text}"
    assert count(S4SPost, account_id=B) == 20


def case_at_most_one_primary_post_per_creator_holds_at_the_database():
    _assert_one_primary_per_creator(sqlite3.connect(_harness.DB_PATH))


def _assert_one_primary_per_creator(conn) -> None:
    """Behaviour, not just a name: a second Primary post for one Creator is
    refused, a Primary post on another Creator is not."""
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("insert into s4s_posts (account_id, caption, is_primary) values ('9000001', 'p', 1)")
        conn.execute("insert into s4s_posts (account_id, caption, is_primary) values ('9000002', 'p', 1)")
        conn.execute("insert into s4s_posts (account_id, caption, is_primary) values ('9000001', 'q', 0)")
        try:
            conn.execute("insert into s4s_posts (account_id, caption, is_primary) values ('9000001', 'r', 1)")
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("a second Primary post for one Creator was accepted")
        conn.rollback()
    finally:
        conn.close()


# ── Isolation ────────────────────────────────────────────────────────

def case_owner_a_naming_creator_b_is_403_and_a_post_of_another_creator_is_404():
    owner_a = fx.login_owner("agency_a_owner")
    owner_b = fx.login_owner("agency_b_owner")
    b_post = _profile(owner_b, B)["posts"][0]
    b_before = _profile(owner_b, B)
    for label, r in _every_route(owner_a, B):
        if label.startswith("GET"):
            continue  # names no Creator
        assert r.status_code == 403, f"{label} on Creator B as owner A: {r.status_code} {r.text}"
    for verb in ("patch", "delete", "post"):
        path = f"/admin/s4s/profiles/{A}/posts/{b_post['id']}" + ("/primary" if verb == "post" else "")
        r = getattr(owner_a, verb)(path, **({"json": {"caption": "taken"}} if verb == "patch" else {}))
        assert r.status_code == 404, f"{verb} B's post under Creator A: {r.status_code} {r.text}"
    for missing in ("999999", "abc"):
        r = owner_a.patch(f"/admin/s4s/profiles/{A}/posts/{missing}", json={"caption": "x"})
        assert r.status_code == 404, f"post {missing}: {r.status_code} {r.text}"
    assert _profile(owner_b, B) == b_before, "Agency B's S4S data changed"


def case_the_master_acts_as_an_owner():
    master = fx.login_owner("agency_master")
    assert _profiles(master)["profiles"] == [], "the Master holds no Creator of its own"
    r = master.put(f"/admin/s4s/profiles/{A}", json={"daily_limit": 1})
    assert r.status_code == 200, f"Master PUT: {r.status_code} {r.text}"
    row = audit_rows("s4s.profile_update")[-1]
    assert json.loads(row.payload_json)["agency_user_id"] == IDS["agency_master"], row.payload_json


# ── Discovery (ticket 16, ADR-0011) ──────────────────────────────────

_PROJECTION = {"profile_id", "display_name", "username", "avatar_url", "primary_caption", "primary_media",
               "daily_limit", "opted_in", "own_agency"}


def _discover(client, q: str | None = None) -> list:
    r = client.get("/admin/s4s/discover", params={} if q is None else {"q": q})
    assert r.status_code == 200, f"GET discover q={q!r}: {r.status_code} {r.text}"
    body = r.json()
    assert isinstance(body, list), body
    for item in body:
        assert set(item) == _PROJECTION, f"Discovery keys {sorted(item)}"
    return body


def _names(items: list) -> list:
    return [i["display_name"] for i in items]


def case_discovery_is_empty_while_no_creator_is_opted_in():
    owner_a = fx.login_owner("agency_a_owner")
    assert _profile(owner_a, A)["opted_in"] is False, "setup: Creator A opted out"
    assert _discover(owner_a) == []


def case_discovery_lists_both_agencies_opted_in_creators_projection_only_own_flagged_sorted():
    owner_a = fx.login_owner("agency_a_owner")
    owner_b = fx.login_owner("agency_b_owner")
    a_caption = _list_in_discovery(owner_a, A, "Fixture Alpha", "fixture_alpha", avatar_url=ALPHA_AVATAR)
    b_caption = _list_in_discovery(owner_b, B, "beta fixture", "fixture_beta", daily_limit=2)
    a_pid, b_pid = _profile(owner_a, A)["profile_id"], _profile(owner_b, B)["profile_id"]
    alpha = {"profile_id": a_pid, "display_name": "Fixture Alpha", "username": "fixture_alpha",
             "avatar_url": ALPHA_AVATAR, "primary_caption": a_caption, "primary_media": [],
             "daily_limit": 1, "opted_in": True}
    beta = {"profile_id": b_pid, "display_name": "beta fixture", "username": "fixture_beta",
            "avatar_url": None, "primary_caption": b_caption, "primary_media": [], "daily_limit": 2,
            "opted_in": True}

    # Sorted by display name, ignoring case: "beta fixture" before "Fixture Alpha".
    assert _discover(owner_a) == [{**beta, "own_agency": False}, {**alpha, "own_agency": True}]
    assert _discover(owner_b) == [{**beta, "own_agency": True}, {**alpha, "own_agency": False}]
    # The Master sees the same projection, never more, and owns neither.
    assert _discover(fx.login_owner("agency_master")) == [{**beta, "own_agency": False},
                                                          {**alpha, "own_agency": False}]

    for client in (owner_a, owner_b):
        text = client.get("/admin/s4s/discover").text
        for aid in (A, B):
            assert aid not in text, f"account id {aid} in Discovery: {text}"


def case_discovery_leaves_out_opted_out_hidden_no_primary_unlinked_and_deleted_agency_creators():
    hidden, opted_out, no_primary, unlinked, orphaned = "1000003", "1000004", "1000005", "1000006", "1000007"
    _seed_creators({hidden: "agency_a_owner", opted_out: "agency_b_owner", no_primary: "agency_b_owner",
                    unlinked: "agency_b_owner", orphaned: "agency_c_owner"}, users=("agency_c_owner",))
    owner_a = fx.login_owner("agency_a_owner")
    owner_b = fx.login_owner("agency_b_owner")
    owner_c = fx.login_owner("agency_c_owner")
    _list_in_discovery(owner_a, hidden, "Fixture Hidden", "fixture_hidden")
    _list_in_discovery(owner_b, opted_out, "Fixture Out", "fixture_out")
    _list_in_discovery(owner_b, no_primary, "Fixture Plain", "fixture_plain")
    _list_in_discovery(owner_b, unlinked, "Fixture Unlinked", "fixture_unlinked")
    _list_in_discovery(owner_c, orphaned, "Fixture Orphan", "fixture_orphan")
    assert _names(_discover(owner_a)) == [
        "beta fixture", "Fixture Alpha", "Fixture Hidden", "Fixture Orphan", "Fixture Out", "Fixture Plain",
        "Fixture Unlinked"], "setup: each Creator is listed before it leaves"

    r = owner_a.put(f"/admin/s4s/profiles/{hidden}", json={"discovery_visible": False})
    assert r.status_code == 200, r.text
    r = owner_b.put(f"/admin/s4s/profiles/{opted_out}", json={"opted_in": False})
    assert r.status_code == 200, r.text
    (primary,) = [p for p in _profile(owner_b, no_primary)["posts"] if p["is_primary"]]
    r = owner_b.delete(f"/admin/s4s/profiles/{no_primary}/posts/{primary['id']}")
    assert r.status_code == 200, r.text
    _db(delete(UserAccount).where(UserAccount.account_id == unlinked))
    _db(delete(User).where(User.username == "agency_c_owner"))

    for client in (owner_a, owner_b):
        assert _names(_discover(client)) == ["beta fixture", "Fixture Alpha"]
    assert count(S4SProfile, account_id=orphaned) == 1, "the deleted Agency's Creator keeps its S4S row"


def case_discovery_q_filters_by_display_name_or_username():
    owner_a = fx.login_owner("agency_a_owner")
    assert _names(_discover(owner_a, "BETA")) == ["beta fixture"]
    assert _names(_discover(owner_a, "fixture_b")) == ["beta fixture"], "@username only"
    assert _names(_discover(owner_a, "@fixture_alpha")) == ["Fixture Alpha"], "a leading @"
    assert _names(_discover(owner_a, "fixture")) == ["beta fixture", "Fixture Alpha"]
    assert _discover(owner_a, "no such creator") == []
    assert _names(_discover(owner_a, "")) == ["beta fixture", "Fixture Alpha"], "an empty q filters nothing"


def case_discovery_is_capped_at_200_by_display_name():
    bulk = [f"20{i:05d}" for i in range(205)]
    before = count(S4SProfile)
    _seed_creators({aid: "agency_b_owner" for aid in bulk})
    conn = sqlite3.connect(_harness.DB_PATH)
    try:
        for i, aid in enumerate(bulk):
            conn.execute("insert into s4s_profiles (account_id, opted_in, discovery_visible, daily_limit,"
                         " display_name, username) values (?, 1, 1, 1, ?, ?)", (aid, f"Bulk {i:03d}", f"bulk_{i}"))
            conn.execute("insert into s4s_posts (account_id, caption, is_primary) values (?, 'Bulk promo', 1)",
                         (aid,))
        conn.commit()
    finally:
        conn.close()
    try:
        got = _discover(fx.login_owner("agency_a_owner"))
        assert _names(got) == ["beta fixture"] + [f"Bulk {i:03d}" for i in range(199)], _names(got)[-3:]
    finally:
        _db(delete(Account).where(Account.id.in_(bulk)))
    assert count(S4SProfile) == before, "cleanup: the bulk rows are gone"


def case_a_creator_with_no_nickname_cannot_opt_in_until_onlyfans_is_read():
    nameless = "1000008"

    async def seed():
        async with get_session() as s:
            s.add(Account(id=nameless, nickname=None, color="#aaaaaa"))
        async with get_session() as s:
            s.add(UserAccount(user_id=IDS["agency_a_owner"], account_id=nameless))
    asyncio.run(seed())
    owner_a = fx.login_owner("agency_a_owner")
    owner_b = fx.login_owner("agency_b_owner")
    got = _profile(owner_a, nameless)
    assert (got["display_name"], got["username"]) == ("", ""), "no nickname: the display fields start empty"

    audits = len(audit_rows("s4s.profile_update"))
    r = owner_a.put(f"/admin/s4s/profiles/{nameless}", json={"opted_in": True})
    assert r.status_code == 400, f"opt in with no display fields: {r.status_code} {r.text}"
    assert "OnlyFans profile could not be read" in r.json()["detail"], r.text
    assert count(S4SProfile, account_id=nameless) == 0, "a refused opt-in wrote a row"
    assert len(audit_rows("s4s.profile_update")) == audits, "a refused opt-in wrote an audit row"

    r = owner_a.put(f"/admin/s4s/profiles/{nameless}", json={"daily_limit": 2})
    assert r.status_code == 200, f"a save that does not opt in: {r.status_code} {r.text}"
    assert _profile(owner_a, nameless)["opted_in"] is False

    _list_in_discovery(owner_a, nameless, "Fixture Nameless", "fixture_nameless")
    assert "Fixture Nameless" in _names(_discover(owner_b))
    text = owner_b.get("/admin/s4s/discover").text
    assert nameless not in text, f"account id {nameless} in Agency B's Discovery: {text}"


def case_discovery_lists_the_owners_other_creators_beside_other_agencies():
    """The rail's creator finds its own Agency's other listed Creators, not
    only other Agencies' (the app leaves out the rail's own card)."""
    owner_a = fx.login_owner("agency_a_owner")
    own = {i["display_name"]: i["own_agency"] for i in _discover(owner_a)}
    assert own["Fixture Alpha"] is True and own["Fixture Nameless"] is True, own
    assert own["beta fixture"] is False, own


def case_a_creator_with_posts_always_has_a_primary_post():
    own, other = "1000020", "1000021"
    _seed_creators({own: "agency_a_owner", other: "agency_b_owner"})
    owner_a = fx.login_owner("agency_a_owner")
    owner_b = fx.login_owner("agency_b_owner")

    # Deleting the Primary post moves the mark to the oldest post left.
    one, two, three = (_new_post(owner_a, own, f"Own promo {i}") for i in (1, 2, 3))
    assert [one["is_primary"], two["is_primary"], three["is_primary"]] == [True, False, False]
    r = owner_a.post(f"/admin/s4s/profiles/{own}/posts/{three['id']}/primary")
    assert r.status_code == 200, r.text
    assert owner_a.delete(f"/admin/s4s/profiles/{own}/posts/{three['id']}").status_code == 200
    assert {p["id"]: p["is_primary"] for p in _profile(owner_a, own)["posts"]} == {one["id"]: True, two["id"]: False}
    # Deleting a post that is not Primary leaves the mark where it is.
    assert owner_a.delete(f"/admin/s4s/profiles/{own}/posts/{two['id']}").status_code == 200
    assert [p["is_primary"] for p in _profile(owner_a, own)["posts"]] == [True]

    # Rows left with posts but no Primary post (made before the rule): the
    # profiles read marks the oldest, and so does Discovery for another Agency's.
    conn = sqlite3.connect(_harness.DB_PATH)
    try:
        conn.execute("update s4s_posts set is_primary = 0 where account_id = ?", (own,))
        for caption in ("Other oldest", "Other newer"):
            conn.execute("insert into s4s_posts (account_id, caption, is_primary) values (?, ?, 0)", (other, caption))
        conn.execute("insert into s4s_profiles (account_id, opted_in, discovery_visible, daily_limit, display_name,"
                     " username) values (?, 1, 1, 1, 'Fixture Late', 'fixture_late')", (other,))
        conn.commit()
    finally:
        conn.close()
    assert [p["is_primary"] for p in _profile(owner_a, own)["posts"]] == [True]
    (late,) = [i for i in _discover(owner_a) if i["display_name"] == "Fixture Late"]
    assert late["primary_caption"] == "Other oldest", late
    assert [(p["caption"], p["is_primary"]) for p in _profile(owner_b, other)["posts"]] == [
        ("Other oldest", True), ("Other newer", False)]


# ── Storage ──────────────────────────────────────────────────────────

def _schema(path) -> tuple[set[str], dict[str, str]]:
    conn = sqlite3.connect(path)
    try:
        tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
        indexes = {r[0]: r[1] for r in conn.execute(
            "select name, sql from sqlite_master where type='index' and sql is not null")}
        return tables, indexes
    finally:
        conn.close()


def _assert_s4s_schema(path) -> None:
    tables, indexes = _schema(path)
    assert set(_TABLES) <= tables, f"missing {set(_TABLES) - tables}"
    for name, where in _PARTIAL_UNIQUE.items():
        assert name in indexes, f"{name} missing: {sorted(indexes)}"
        assert "UNIQUE" in indexes[name].upper() and where in indexes[name], indexes[name]
    conn = sqlite3.connect(path)
    try:
        for t in _TABLES:
            for fk in conn.execute(f"PRAGMA foreign_key_list({t})"):
                if fk[2] == "accounts":
                    assert fk[6] == "CASCADE", f"{t}.{fk[3]} → accounts is ON DELETE {fk[6]}"
    finally:
        conn.close()
    _assert_one_primary_per_creator(sqlite3.connect(path))


def _load_s4s_migration():
    found = list((_MIGRATIONS / "versions").glob("*s4s*.py"))
    assert len(found) == 1, f"want one S4S migration, found {found}"
    spec = importlib.util.spec_from_file_location("s4s_migration", found[0])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _alembic(*args: str) -> str:
    """Alembic's CLI on the harness's temp database only: `-x url=` names the
    harness file (env.py's first source), never the alembic.ini default."""
    db = Path(_harness.DB_PATH)
    assert db.parent == Path(tempfile.gettempdir()) and db.name.startswith("chatterly_test_"), db
    url = f"sqlite:///{db}"
    env = {**os.environ, "PYTHONPATH": str(_REPO), "CHATTERLY_DB_URL": url}
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(_MIGRATIONS / "alembic.ini"), "-x", f"url={url}", *args],
        cwd=_REPO, env=env, capture_output=True, text=True, timeout=300,
    )
    assert r.returncode == 0, f"alembic {' '.join(args)}: {r.returncode}\n{r.stdout}\n{r.stderr}"
    if args[0] not in ("heads", "history"):  # neither opens the database
        assert f"using DB URL: {url}  (source: -x url=)" in r.stderr, r.stderr
    return r.stdout


def case_alembic_cycles_the_s4s_migration_on_the_harness_database_only():
    mod = _load_s4s_migration()
    heads = [line for line in _alembic("heads").splitlines() if line.strip()]
    # One head, which is S4S or a revision chained on top of it (0069 Sales
    # records and 0070 Employee groups landed after; their downgrade passes
    # back through S4S). The `history` listing must still carry S4S.
    assert len(heads) == 1, heads
    assert mod.revision in _alembic("history"), mod.revision

    # ASSUMPTION: the harness file is first stamped at the S4S migration's own
    # `down_revision`, so only the revisions from S4S up run on it. init_db()
    # builds it with create_all and stamps it 0001_initial, and the older
    # migrations do not replay on that. Observed 2026-10-16 on a fresh
    # init_db() harness file, `-x url=` only: `upgrade head` from 0001_initial
    # stops at its first step, "Running upgrade 0001_initial ->
    # 0002_saved_replies", with "sqlite3.OperationalError: table
    # saved_replies already exists" (versions/20260519_0001_saved_replies.py
    # line 27). Rung 5 for stamping at down_revision. Overturned if the older
    # migrations become replayable on a create_all database.
    _alembic("stamp", mod.down_revision)
    _alembic("upgrade", "head")
    before, _ = _schema(_harness.DB_PATH)
    assert set(_TABLES) <= before, before

    _alembic("downgrade", mod.down_revision)
    after, indexes = _schema(_harness.DB_PATH)
    # Later migrations chained on top (0069, 0070) are undone by the same
    # downgrade and their tables join the removed set, so S4S's four are a
    # subset of it rather than the whole of it.
    assert set(_TABLES) <= before - after, f"downgrade removed {before - after}"
    assert after <= before, after - before
    assert not set(_PARTIAL_UNIQUE) & set(indexes), indexes

    _alembic("upgrade", "head")
    restored, _ = _schema(_harness.DB_PATH)
    assert restored == before, (before ^ restored)
    _assert_s4s_schema(_harness.DB_PATH)
    assert "(head)" in _alembic("current"), "the harness file is not at head after the round trip"


def case_init_db_brings_the_dropped_tables_back_with_their_partial_unique_indexes():
    conn = sqlite3.connect(_harness.DB_PATH)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        for t in reversed(_TABLES):
            conn.execute(f"DROP TABLE IF EXISTS {t}")
        conn.commit()
    finally:
        conn.close()
    tables, _ = _schema(_harness.DB_PATH)
    assert not set(_TABLES) & tables, "setup: the tables survived the DROP"

    asyncio.run(init_db())

    _assert_s4s_schema(_harness.DB_PATH)
    # The router works on the rebuilt tables.
    owner_a = fx.login_owner("agency_a_owner")
    assert _profile(owner_a, A)["profile_id"] is None
    _new_post(owner_a, A, "After the rebuild")


_harness.run(
    case_signed_out_is_401_on_every_route_with_and_without_anonymous_admin,
    case_chatter_is_403_on_every_route,
    case_profiles_list_only_own_creators_opted_out_with_defaults_and_the_read_writes_no_row,
    case_live_posting_is_read_on_every_call,
    case_put_upserts_the_profile_and_writes_one_audit_row_per_change,
    case_the_display_fields_are_the_creators_onlyfans_profile_and_cannot_be_typed,
    case_bad_profile_bodies_are_400_and_change_nothing,
    case_opting_out_a_creator_with_no_requests_or_slots_succeeds,
    case_posts_create_edit_delete_and_move_the_primary_mark,
    case_a_caption_over_5000_characters_is_400,
    case_the_21st_post_is_409,
    case_at_most_one_primary_post_per_creator_holds_at_the_database,
    case_owner_a_naming_creator_b_is_403_and_a_post_of_another_creator_is_404,
    case_the_master_acts_as_an_owner,
    case_discovery_is_empty_while_no_creator_is_opted_in,
    case_discovery_lists_both_agencies_opted_in_creators_projection_only_own_flagged_sorted,
    case_discovery_leaves_out_opted_out_hidden_no_primary_unlinked_and_deleted_agency_creators,
    case_discovery_q_filters_by_display_name_or_username,
    case_discovery_is_capped_at_200_by_display_name,
    case_a_creator_with_no_nickname_cannot_opt_in_until_onlyfans_is_read,
    case_discovery_lists_the_owners_other_creators_beside_other_agencies,
    case_a_creator_with_posts_always_has_a_primary_post,
    case_alembic_cycles_the_s4s_migration_on_the_harness_database_only,
    case_init_db_brings_the_dropped_tables_back_with_their_partial_unique_indexes,
)
