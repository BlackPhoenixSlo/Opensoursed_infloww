#!/usr/bin/env python3
"""Toolbox (`toolbox.call`, `toolbox_decide`, `report_files`; docs/plans/ultra-mode/issues/04-toolbox.md,
05-mcp-server.md) on the two-Agency bench, through the real app in-process.

Cases:
  case_identity_isolated_both_ways — inside a real outer request (B's cookie): an inner call as A's token
                                     sees A, one without creds is a 401 (never B), one with the outer's own
                                     creds sees B; the outer user is B after each.
  case_every_tool_runs_as_owner    — each v1 read tool answers 200 for A's own Creator, open_url set.
  case_cross_agency_refused        — A's token never reads Creator B: by id per tool (403/400), by name in a
                                     recipe (400), and the list tools leave it out; an unknown id is refused.
  case_args_refused                — unknown key, missing id, limit over 30: 422 per field, no request.
  case_send_refused                — an effect="send" tool: 403, no request sent.
  case_shaping_limits              — 50 rows / reports 200, 500-char strings, ~24k cap (halving, then 413),
                                     row_count + truncated, data_only wrap, error shape.
  case_open_url_host               — X-Forwarded-Host / APP_PUBLIC_URL, never Host; bad host → bare path.
  case_client_address_passed       — the inner request sees the caller's address, not 127.0.0.1.
  case_report_file_scoped          — report_file: download for the creating user (token or cookie) only,
                                     404 to the other Agency, 401 without creds, 404 after 15 min.
  case_report_file_caps            — per-user 10, global 50, 100 MB total: the caller's own oldest file
                                     goes, never another user's (else Full, 429); one file over → 413.

Seeded straight into the temp DB; no network.

Run: ./venv/bin/python service/tests/test_toolbox.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from fastapi import Request  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
import auth  # noqa: E402
import client_addr  # noqa: E402
import report_files  # noqa: E402
import server  # noqa: E402
import toolbox  # noqa: E402
import toolbox_decide as td  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Transaction  # noqa: E402

IDS = fx.seed_two_agencies()
CA, CB = IDS["creator_a"], IDS["creator_b"]


async def _seed() -> None:
    async with get_session() as s:
        for aid, cents in ((CA, 1000), (CB, 700)):
            s.add(Transaction(account_id=aid, fan_id=11, kind="tip", amount_cents=cents,
                              occurred_at=datetime.utcnow() - timedelta(days=1),
                              status="cleared", currency="USD", source="ledger"))
asyncio.run(_seed())
for _aid, _nick in ((CA, "creator_a"), (CB, "creator_b")):
    account_registry.save_meta(_aid, {"id": _aid, "nickname": _nick})

A = fx.login_owner("agency_a_owner")
B = fx.login_owner("agency_b_owner")


def _mint(client) -> str:
    r = client.post("/admin/owner-tokens", json={"name": "mcp"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


TOK_A, TOK_B = _mint(A), _mint(B)
CREDS_A = toolbox.Creds(authorization=f"Bearer {TOK_A}")
BY_NAME = {t.name: t for t in td.TOOLS}
CREDS_B = toolbox.Creds(authorization=f"Bearer {TOK_B}")
WEEK = {"preset": "last_7_days"}


def _call(tool, args=None, creds=CREDS_A):
    t = BY_NAME[tool] if isinstance(tool, str) else tool
    return asyncio.run(toolbox.call(t, args or {}, creds))


def _status(out) -> int:
    return out["error"]["status"] if "error" in out else 200


# Throwaway routes on this process's app object only (the spike's pattern): who the inner request is,
# what address it comes from, and an outer route that makes an inner call mid-request.
async def _whoami(request: Request):
    u = auth.get_request_user()
    return {"user": u.username if u else None}


async def _addr(request: Request):
    return {"addr": str(client_addr.client_address(request))}


WHOAMI = td.Tool("zz_whoami", "test", "GET", "/admin/zz-toolbox/whoami", td.NoArgs, "read", open=td.Open("/creators"))
ADDR = td.Tool("zz_addr", "test", "GET", "/admin/zz-toolbox/addr", td.NoArgs, "read")


async def _outer(request: Request):
    who = request.query_params["inner"]
    creds = {"a": CREDS_A, "none": toolbox.Creds(), "self": toolbox.Creds.from_request(request)}[who]
    before = auth.get_request_user().username
    inner = await toolbox.call(WHOAMI, {}, creds)
    return {"before": before, "inner": inner, "after": auth.get_request_user().username}


@contextlib.contextmanager
def _allowed(*tools):
    """These throwaway tools' routes on the token allowlist (token_auth reads td.TOOLS) while inside."""
    saved = td.TOOLS
    td.TOOLS = saved + tools
    try:
        yield
    finally:
        td.TOOLS = saved


for _p, _fn in (("/admin/zz-toolbox/whoami", _whoami), ("/admin/zz-toolbox/addr", _addr),
                ("/admin/zz-toolbox/outer", _outer)):
    server.app.add_api_route(_p, _fn, methods=["GET"])


def case_identity_isolated_both_ways() -> None:
    with _allowed(WHOAMI):
        for inner, want in (("a", {"user": "agency_a_owner"}), ("self", {"user": "agency_b_owner"})):
            r = B.get("/admin/zz-toolbox/outer", params={"inner": inner})
            assert r.status_code == 200, r.text
            j = r.json()
            assert j["before"] == j["after"] == "agency_b_owner", j
            assert {k: v for k, v in j["inner"].items() if k != "open_url"} == want, j
    j = B.get("/admin/zz-toolbox/outer", params={"inner": "none"}).json()
    assert j["inner"]["error"]["status"] == 401 and j["after"] == "agency_b_owner", j


def _a_page() -> str:
    """A bio page of Agency A (no Creator: no OnlyFans read), made by A's own cookie."""
    r = A.post("/admin/bio-pages", json={"username": f"a_page_{len(_PAGES)}", "display_name": "A"})
    assert r.status_code == 201, r.text
    _PAGES.append(r.json()["profile"]["id"])
    return _PAGES[-1]


_PAGES: list[str] = []


def case_every_tool_runs_as_owner() -> None:
    args = {"creators_list": {}, "stats_per_model": {"account_id": CA}, "vault_search": {"account_id": CA},
            "of_folders_list": {"account_id": CA}, "describe_all_status": {"account_id": CA},
            "automation_kinds": {}, "automation_rules_list": {"account_id": CA}, "bio_pages_list": {},
            "report_catalogue": {}, "report_run": {"recipe": {"dataset": "sales", "window": WEEK}},
            "report_file": {"recipe": {"dataset": "sales", "window": WEEK}}, "bio_page_get": {"pid": _a_page()}}
    reads = {n for n, t in BY_NAME.items() if t.effect == "read"}  # writes: test_toolbox_writes.py
    assert set(args) == reads, reads ^ set(args)
    for name, a in args.items():
        out = _call(name, a)
        assert "error" not in out, (name, out)
        assert out["open_url"] and out["open_url"].startswith("/"), (name, out)
    ids = [c["id"] for c in _call("creators_list")["accounts"]]
    assert ids == [CA], ids
    rows = _call("report_run", args["report_run"])
    assert rows["data_only"]["rows"] and rows["row_count"] == 1 and rows["truncated"] is False, rows


def case_cross_agency_refused() -> None:
    for name in ("stats_per_model", "vault_search", "of_folders_list", "describe_all_status",
                 "automation_rules_list"):
        for aid in (CB, "1999999"):
            out = _call(name, {"account_id": aid})
            assert _status(out) in (403, 404), (name, aid, out)
    for name in ("report_run", "report_file"):
        for who in (CB, "creator_b"):
            out = _call(name, {"recipe": {"dataset": "sales", "window": WEEK, "creators": [who]}})
            assert _status(out) == 400 and "creators" in out["error"]["detail"]["errors"], (name, who, out)
    assert CB not in str(_call("creators_list")) and CB not in str(_call("bio_pages_list"))
    assert CB not in str(_call("stats_per_model")) and CB not in str(_call("automation_rules_list"))
    sales = _call("report_run", {"recipe": {"dataset": "sales", "window": WEEK, "metrics": ["gross"]}})
    assert "creator_b" not in str(sales) and "creator_a" in str(sales), sales
    # and the other way: B's token never sees A
    assert _status(_call("vault_search", {"account_id": CA}, CREDS_B)) == 403
    assert [c["id"] for c in _call("creators_list", {}, CREDS_B)["accounts"]] == [CB]


def _spy_send():
    sent = []
    real = toolbox._send

    async def spy(req, creds):
        sent.append(req)
        return await real(req, creds)
    toolbox._send = spy
    return sent, real


def case_args_refused() -> None:
    sent, real = _spy_send()
    try:
        for name, a, field in (("creators_list", {"x": 1}, "x"), ("vault_search", {}, "account_id"),
                               ("vault_search", {"account_id": CA, "limit": 31}, "limit"),
                               ("report_file", {"recipe": {}, "format": "pdf"}, "format")):
            out = _call(name, a)
            assert out["error"]["status"] == 422 and field in out["error"]["detail"]["errors"], (name, out)
    finally:
        toolbox._send = real
    assert sent == [], sent


def case_send_refused() -> None:
    send = td.Tool("zz_send", "test", "POST", "/admin/reports/run", td.ReportArgs, "send",
                   model_text=("recipe",), text_kind="mass")
    sent, real = _spy_send()
    try:
        out = _call(send, {"recipe": {"dataset": "sales", "window": WEEK}})
    finally:
        toolbox._send = real
    assert out["error"] == {"status": 403, "detail": toolbox.SEND_REFUSED} and sent == [], out


def case_shaping_limits() -> None:
    keep = BY_NAME["vault_search"]
    lst = td.Tool("t", "t", "GET", "/x", td.NoArgs, "read", shape=td.Shape(rows="items"))
    out = td.shape_result(lst, 200, {"items": [{"n": i} for i in range(120)]})
    assert len(out["items"]) == 50 and out["row_count"] == 120 and out["truncated"] is True, out
    out = td.shape_result(lst, 200, {"items": [{"n": 1}]})
    assert out["row_count"] == 1 and out["truncated"] is False
    rep = BY_NAME["report_run"]
    out = td.shape_result(rep, 200, {"rows": [[i] for i in range(250)], "row_count": 900, "truncated": True})
    assert len(out["data_only"]["rows"]) == 200 and out["row_count"] == 900 and out["truncated"] is True
    assert "row_count" not in out["data_only"], out.keys()
    out = td.shape_result(lst, 200, {"items": [{"s": "x" * 600}], "note": "y" * 900})
    assert out["items"][0]["s"] == "x" * 500 + "…" and len(out["note"]) == 501, out
    assert out["truncated"] is True and out["row_count"] == 1, out  # a clipped string is a cut result
    one = td.Tool("o", "o", "GET", "/x", td.NoArgs, "read")
    out = td.shape_result(one, 200, {"a": {"b": ["z" * 501]}})
    assert out["a"]["b"][0] == "z" * 500 + "…" and out["truncated"] is True, out  # nested, no rows list
    assert "truncated" not in td.shape_result(one, 200, {"a": "z" * 500}), "nothing cut, nothing claimed"
    out = td.shape_result(keep, 200, {"list": [{"id": 1}], "hasMore": True})
    assert out["truncated"] is True and out["row_count"] == 1, out  # upstream says there is more
    assert td.shape_result(keep, 200, {"list": [{"id": 1}], "hasMore": False})["truncated"] is False
    out = td.shape_result(lst, 200, {"items": [{"s": "x" * 499, "t": "z" * 499} for _ in range(50)]})
    assert td._size(out) <= td.MAX_CHARS + 100 and len(out["items"]) < 50 and out["truncated"] is True
    big = td.Tool("b", "b", "GET", "/x", td.NoArgs, "read")
    out = td.shape_result(big, 200, {f"k{i}": "x" * 400 for i in range(100)})
    assert out["error"]["status"] == 413, out
    out = td.shape_result(keep, 200, {"list": [{"id": 1, "secret": 2, "_ai": {"tags": ["a"], "x": 1}}]})
    assert out["data_only"]["list"] == [{"id": 1, "_ai": {"tags": ["a"]}}], out
    assert td.shape_result(lst, 403, {"detail": "not your account"}) == \
        {"error": {"status": 403, "detail": "not your account"}}
    assert td.shape_result(lst, 500, "") == {"error": {"status": 500, "detail": "request failed"}}
    assert td.shape_result(lst, 400, {"detail": "bad", "errors": {"a": "b"}})["error"]["detail"] == \
        {"detail": "bad", "errors": {"a": "b"}}


def case_open_url_host() -> None:
    os.environ.pop("APP_PUBLIC_URL", None)
    fwd = toolbox.Creds(authorization=f"Bearer {TOK_A}", forwarded_host="app.example.com", forwarded_proto="https")
    assert _call("creators_list", {}, fwd)["open_url"] == "https://app.example.com/creators"
    assert _call("creators_list")["open_url"] == "/creators"
    out = _call("report_run", {"recipe": {"dataset": "fan_spend", "window": WEEK}}, fwd)
    assert out["open_url"] == "https://app.example.com/analytics/fan-reports", out["open_url"]
    for bad in ("evil.com/x", "a b", "@evil.com"):
        c = toolbox.Creds(authorization=f"Bearer {TOK_A}", forwarded_host=bad)
        assert _call("creators_list", {}, c)["open_url"] == "/creators", bad
    os.environ["APP_PUBLIC_URL"] = "https://agency.example.org/"
    try:
        assert _call("creators_list", {}, fwd)["open_url"] == "https://agency.example.org/creators"
    finally:
        os.environ.pop("APP_PUBLIC_URL")
    # Through a real request whose Host is the relay's: the public host comes from X-Forwarded-Host.
    r = B.get("/admin/zz-toolbox/outer", params={"inner": "self"},
              headers={"Host": "relay.internal:8000", "X-Forwarded-Host": "app.example.com",
                       "X-Forwarded-Proto": "https"})
    assert r.json()["inner"]["open_url"] == "https://app.example.com/creators", r.json()
    r = B.get("/admin/zz-toolbox/outer", params={"inner": "self"}, headers={"Host": "relay.internal:8000"})
    assert r.json()["inner"]["open_url"] == "/creators", r.json()
    # ...while the inner request keeps the caller's Host + X-Forwarded-*: bio public URLs as the caller's.
    fwd_self = toolbox.Creds(authorization=f"Bearer {TOK_A}", host="relay.internal:8000",
                             forwarded_host="app.example.com", forwarded_proto="https")
    assert _call("bio_pages_list", {}, fwd_self)["public_base"] == "https://app.example.com/p"
    assert _call("bio_pages_list", {}, toolbox.Creds(authorization=f"Bearer {TOK_A}", host="direct.example:8000")
                 )["public_base"] == "http://direct.example:8000/p"


def case_client_address_passed() -> None:
    with _allowed(ADDR):
        out = asyncio.run(toolbox.call(ADDR, {}, toolbox.Creds(authorization=f"Bearer {TOK_A}",
                                                               client_host="203.0.113.7")))
    assert out["addr"] == "203.0.113.7", out


def case_report_file_scoped() -> None:
    fwd = toolbox.Creds(authorization=f"Bearer {TOK_A}", forwarded_host="app.example.com", forwarded_proto="https")
    out = _call("report_file", {"recipe": {"dataset": "sales", "window": WEEK, "metrics": ["gross"]}}, fwd)
    assert out["download_url"].startswith("https://app.example.com/admin/reports/files/"), out
    assert out["filename"].startswith("sales_") and out["filename"].endswith(".csv") and out["expires_in_s"] == 900
    path = out["download_url"].removeprefix("https://app.example.com")
    client = _harness.make_client()
    r = client.get(path, headers={"Authorization": f"Bearer {TOK_A}"})
    assert r.status_code == 200 and r.text.splitlines() == ["Creator,Gross ($)", "creator_a,10.0"], r.text
    assert 'attachment; filename="sales_' in r.headers["content-disposition"] and r.headers["cache-control"] == "no-store"
    assert A.get(path).status_code == 200  # the same owner by cookie
    assert B.get(path).status_code == 404 and client.get(path, headers={"Authorization": f"Bearer {TOK_B}"}).status_code == 404
    assert _harness.make_client().get(path).status_code == 401
    assert client.get("/admin/reports/files/nope", headers={"Authorization": f"Bearer {TOK_A}"}).status_code == 404
    real = report_files._clock
    report_files._clock = lambda: real() + report_files.TTL_S + 1
    try:
        assert client.get(path, headers={"Authorization": f"Bearer {TOK_A}"}).status_code == 404
    finally:
        report_files._clock = real
    x = _call("report_file", {"recipe": {"dataset": "sales", "window": WEEK}, "format": "xlsx"})
    assert x["filename"].endswith(".xlsx") and x["download_url"].startswith("/admin/reports/files/"), x


def case_report_file_caps() -> None:
    saved = dict(report_files._files)
    report_files._files.clear()
    try:
        first = report_files.put("u1", "a.csv", "text/csv", b"1")
        for _ in range(report_files.MAX_PER_USER):
            report_files.put("u1", "a.csv", "text/csv", b"1")
        mine = [f for f in report_files._files.values() if f.user_id == "u1"]
        assert len(mine) == report_files.MAX_PER_USER and report_files.get(first.id, "u1") is None
        report_files._files.clear()
        others = [report_files.put(f"v{i}", "b.csv", "text/csv", b"2") for i in range(report_files.MAX_FILES)]
        try:  # full of other users' files: refused, none of theirs evicted
            report_files.put("u1", "a.csv", "text/csv", b"1")
            raise AssertionError("put past MAX_FILES evicted another user's file")
        except report_files.Full:
            pass
        assert all(report_files.get(f.id, f.user_id) is f for f in others)
        report_files._files.pop(others[0].id)
        mine1 = report_files.put("u1", "a.csv", "text/csv", b"1")  # room for one: taken
        mine2 = report_files.put("u1", "a.csv", "text/csv", b"1")  # full again: the caller's own oldest goes
        assert report_files.get(mine1.id, "u1") is None and report_files.get(mine2.id, "u1") is mine2
        assert all(report_files.get(f.id, f.user_id) is f for f in others[1:])
        report_files._files.clear()
        half = report_files.MAX_BYTES // 2 + 1
        old = report_files.put("u2", "c.csv", "text/csv", b"x" * half)
        try:  # over MAX_BYTES only by evicting u2's file: refused
            report_files.put("u3", "c.csv", "text/csv", b"x" * half)
            raise AssertionError("put past MAX_BYTES evicted another user's file")
        except report_files.Full:
            pass
        new = report_files.put("u2", "c.csv", "text/csv", b"x" * half)
        assert report_files.get(old.id, "u2") is None and report_files.get(new.id, "u2") is new
        try:
            report_files.put("u4", "d.csv", "text/csv", b"x" * (report_files.MAX_BYTES + 1))
            raise AssertionError("over MAX_BYTES accepted")
        except report_files.TooLarge:
            pass
        f = report_files.put("u5", "e.csv", "text/csv", b"z")
        assert len(f.id) >= 32 and report_files.get(f.id, "u6") is None and report_files.get(f.id, "u5") is f
    finally:
        report_files._files.clear()
        report_files._files.update(saved)


_harness.run()
