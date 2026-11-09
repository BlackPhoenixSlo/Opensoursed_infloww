#!/usr/bin/env python3
"""The chat open's bundle (service/chat_screen_api.py): one call answers a thread open's local reads with exactly
what each route answers, under the same authorization; `lacks` adds the Creator-wide lists; `thumbs` lists the seed's
fresh photo thumbnails. And the vault backfill answers the fan's new history when it inserted rows.

The seam is the Relay over HTTP with real session cookies (the shared two-Agency fixture).

Run: ./venv/bin/python service/tests/test_chat_screen_api.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import base64  # noqa: E402
import contextlib  # noqa: E402
import json  # noqa: E402

import anyio.from_thread  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
import employees  # noqa: E402
import server  # noqa: F401, E402  (loads every router)
import chat_screen_api  # noqa: E402

IDS = fx.seed_two_agencies()
A1, B1 = IDS["creator_a"], IDS["creator_b"]
FAN = 4242
for aid in (A1, B1):
    d = account_registry.ACCOUNTS_DIR / aid
    d.mkdir(exist_ok=True)
    account_registry.upsert_account(aid, nickname=f"n{aid}")
    (d / "latest.json").write_text(json.dumps({"session": "s.json"}))   # has_session

# The chatter's mirror Employee up front (as test_screens_api): its first request would otherwise race its creation.
EMP_A = asyncio.run(employees.get_or_create_mirror_employee(
    IDS["chatter_a"], IDS["agency_a_owner"], display_name="chatter_a", color="#bbbbbb"))
_LOOP = contextlib.ExitStack()   # one event loop for every request, as in the running relay
PORTAL = _LOOP.enter_context(anyio.from_thread.start_blocking_portal())


def _one_loop(client):
    client.portal = PORTAL
    return client


OWNER_A = _one_loop(fx.login_owner("agency_a_owner"))
CHATTER_A = _one_loop(fx.login_chatter("chatter_a"))


def _get(client, path: str, aid: str | None = None, **params):
    r = client.get(path, params=params, headers={"X-Account-Id": aid} if aid else {})
    return r.status_code, r.json()


def _chat(client, **params):
    import screens_api
    screens_api._SHARED.clear()
    return client.get("/admin/screens/chat", params={"account": A1, "fan": FAN, **params})


def _flat(env: dict) -> dict:
    """The screen envelope (screens_api.run_screen) as `{read: body}` plus `errors` (every answer with a status),
    `thumbs` and `asOf`, for these checks."""
    assert set(env) == {"answers", "thumbs", "asOf"}, set(env)
    out = {"errors": [], "thumbs": env["thumbs"], "asOf": env["asOf"]}
    for a in env["answers"]:
        assert ("body" in a) != ("status" in a), a
        assert a["accountId"] == (A1 if a["read"] == "scheduledSends" else None), a
        if "status" in a:
            out["errors"].append(a)
        else:
            out[a["read"]] = a["body"]
    return out


def _cf(exp: int) -> str:
    """A CloudFront-signed URL expiring at `exp` (its custom Policy, CloudFront's base64)."""
    pol = json.dumps({"Statement": [{"Resource": "x", "Condition": {"DateLessThan": {"AWS:EpochTime": exp}}}]})
    raw = base64.b64encode(pol.encode()).decode().translate(str.maketrans("+=/", "-_~"))
    return f"https://cdn2.onlyfans.com/files/{exp}.jpg?Policy={raw}&Signature=s&Key-Pair-Id=k"


def case_the_open_reads_are_the_routes_bodies_in_one_call():
    r = _chat(OWNER_A, lacks="savedReplies,sensitiveWords")
    assert r.status_code == 200 and r.headers.get("cache-control") == "no-store", r.text
    got = _flat(r.json())
    assert got["errors"] == [], got["errors"]
    assert got["seed"] == _get(OWNER_A, f"/admin/messages/{A1}/{FAN}", limit=30)[1]
    assert got["fan"] == _get(OWNER_A, f"/admin/fans/{A1}/{FAN}")[1]
    assert got["attribution"] == _get(OWNER_A, f"/admin/messages/{A1}/{FAN}/attribution")[1]
    assert got["fanHistory"] == _get(OWNER_A, "/admin/vault/fan-history", account_id=A1, fan_id=FAN)[1]
    assert got["scheduledSends"] == _get(OWNER_A, "/api/of/v2/scheduled-sends", A1, fan_id=FAN)[1]
    assert got["savedReplies"] == _get(OWNER_A, "/admin/saved-replies", account_id=A1)[1]
    assert got["sensitiveWords"] == _get(OWNER_A, "/admin/sensitive-words", account_id=A1)[1]
    assert got["thumbs"] == [] and isinstance(got["asOf"], int), got


def case_lacks_names_the_lists_read_else_none():
    got = _flat(_chat(OWNER_A).json())
    assert "savedReplies" not in got and "sensitiveWords" not in got, sorted(got)
    got = _flat(_chat(OWNER_A, lacks="sensitiveWords,bogus").json())
    assert "sensitiveWords" in got and "savedReplies" not in got and "bogus" not in got, sorted(got)


def case_back_to_back_fans_keep_their_own_reads():
    import screens_api
    screens_api._SHARED.clear()
    first = OWNER_A.get("/admin/screens/chat", params={"account": A1, "fan": FAN})
    second_fan = FAN + 1
    second = OWNER_A.get("/admin/screens/chat", params={"account": A1, "fan": second_fan})
    assert first.status_code == second.status_code == 200
    answers = {a["read"]: a for a in second.json()["answers"]}
    for name, path in {"seed": f"/admin/messages/{A1}/{second_fan}",
                       "fan": f"/admin/fans/{A1}/{second_fan}",
                       "attribution": f"/admin/messages/{A1}/{second_fan}/attribution"}.items():
        route = OWNER_A.get(path, params={"limit": 30} if name == "seed" else {})
        if route.status_code == 200:
            assert answers[name]["body"] == route.json(), name
        else:
            assert answers[name]["status"] == route.status_code, name


def _role(pages: dict[str, bool] | None) -> None:
    blob = {"enforce": False} if pages is None else {
        "enforce": True, "assignments": {str(EMP_A): "fx"},
        "roles": [{"id": "fx", "name": "Fixture fx", "description": "", "permissions": pages, "scope": "self"}]}
    r = OWNER_A.put("/admin/settings/roles", json=blob)
    assert r.status_code == 200, r.text


def case_a_chatter_gets_each_routes_own_answer():
    """Each read is what its route answers the chatter (a body, or the role hook's refusal)."""
    _same_as_routes()


def case_a_restricted_chatter_gets_each_routes_own_refusal():
    _role({"/": True})   # the Dashboard only: no chat page
    try:
        _same_as_routes(want_refused=True)
    finally:
        _role(None)


def _same_as_routes(want_refused: bool = False):
    r = _chat(CHATTER_A)
    assert r.status_code == 200, r.text
    got = _flat(r.json())
    errs = {e["read"]: e["status"] for e in got["errors"]}
    routes = {"seed": (f"/admin/messages/{A1}/{FAN}", None, {"limit": 30}), "fan": (f"/admin/fans/{A1}/{FAN}", None, {}),
              "attribution": (f"/admin/messages/{A1}/{FAN}/attribution", None, {}),
              "fanHistory": ("/admin/vault/fan-history", None, {"account_id": A1, "fan_id": FAN}),
              "scheduledSends": ("/api/of/v2/scheduled-sends", A1, {"fan_id": FAN})}
    for name, (path, aid, q) in routes.items():
        r = CHATTER_A.get(path, params=q, headers={"X-Account-Id": aid} if aid else {})
        if r.status_code == 200:
            assert got.get(name) == r.json() and name not in errs, (name, got.get(name), errs)
        else:
            assert errs.get(name) == r.status_code and name not in got, (name, r.status_code, errs)
    if want_refused:
        assert errs, "the role refuses at least one read"


def case_another_agencys_creator_is_403_before_any_read():
    r = OWNER_A.get("/admin/screens/chat", params={"account": B1, "fan": FAN})
    assert r.status_code == 403, (r.status_code, r.text)
    assert OWNER_A.get(f"/admin/fans/{B1}/{FAN}").status_code == 403   # the route agrees


def case_thumbs_fresh_photos_newest_first_at_most_six():
    now = 1_900_000_000
    fresh, old = _cf(now + 3600), _cf(now - 1)
    seed = {"messages": [
        {"media": [{"type": "photo", "thumb_url": fresh}, {"type": "video", "thumb_url": "https://x/v.jpg"}]},
        {"media": [{"type": "photo", "thumb_url": old}, {"type": "photo", "thumb_url": fresh}]},
        {"media": [{"type": "photo", "thumb_url": f"https://public.onlyfans.com/{i}.jpg"} for i in range(9)]},
    ]}
    got = chat_screen_api.thumbs(seed, now=now)
    assert got == [fresh] + [f"https://public.onlyfans.com/{i}.jpg" for i in range(5)], got
    assert chat_screen_api._expired(old, now) and not chat_screen_api._expired(fresh, now)
    assert not chat_screen_api._expired("https://cdn2.onlyfans.com/a.jpg?Policy=%%%", now)   # unreadable: /img decides
    assert chat_screen_api._expired("https://x/a.jpg?Expires=10", now)


def case_the_backfill_answers_the_new_history():
    item = {"message_id": 777, "media_ids": [55], "price_cents": 500, "was_purchased": True}
    r = OWNER_A.post("/admin/vault/sends/backfill", json={"account_id": A1, "fan_id": FAN, "items": [item]})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["inserted"] == 1 and got["history"] == _get(
        OWNER_A, "/admin/vault/fan-history", account_id=A1, fan_id=FAN)[1], got
    assert "55" in got["history"]["by_media"], got["history"]
    again = OWNER_A.post("/admin/vault/sends/backfill", json={"account_id": A1, "fan_id": FAN, "items": [item]}).json()
    assert again == {"ok": True, "inserted": 0, "skipped": 1}, again


try:
    _harness.run()
finally:
    _LOOP.close()   # the portal's loop thread, else the exit waits on it
