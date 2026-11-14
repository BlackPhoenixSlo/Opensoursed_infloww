#!/usr/bin/env python3
"""The hosted MCP server (`mcp_api`, POST /admin/mcp; docs/plans/ultra-mode/issues/05-mcp-server.md) on the
two-Agency bench, through the real app in-process with real minted owner tokens.

Cases:
  case_handshake               — initialize (version echo / newest for an unknown one) → initialized 202 →
                                 ping → tools/list (the Toolbox + propose_plan / plan_status) → tools/call creators_list (A's own Creator).
  case_origin_refused          — any Origin → 403, even with a good token; no tool runs.
  case_auth_refused            — cookie-only, a bad ifw_ token, a foreign Bearer, Basic → 401.
  case_anonymous_surface       — no credential: initialize + tools/list = connect_account, register_account, login
                                 (test_mcp_auth.py); its links
                                 (MCP_SIGNUP_URL, else this host); a data tool or propose_plan → isError with the link.
  case_share_token_gate        — SHARE_TOKEN set: anonymous POST /admin/mcp still serves initialize / tools/list
                                 (the anonymous builtins only); GET /admin/mcp is its 405; a data tool,
                                 /admin/mcp-x and /admin/accounts stay refused.
  case_anonymous_predicate     — `anonymous_surface`: exactly PATH, POST + the 405-only methods; audit skips
                                 exactly PATH.
  case_cross_agency_refused    — B's token never reads Creator A (403) and lists only B.
  case_protocol_errors         — unknown method/tool, bad params/arguments, bad args (isError 422), malformed
                                 JSON, deep nesting, batch, no jsonrpc, bad id (a readable id echoed), unsupported
                                 version header, GET/DELETE 405.
  case_hostile_values          — a lone surrogate in id / method / tool name answers (\\u-escaped), never 500;
                                 NaN, a lone surrogate or a 100k query in tool args → isError 422, never 500.
  case_send_tools_absent       — an effect="send" tool is not listed and not callable.
  case_open_url_every_result   — every listed tool's result (ok or error) carries open_url, on X-Forwarded-Host.
  case_employee_header_ignored — X-Employee-Id never reaches the inner request.
  case_audit_inner_only        — /admin/mcp writes no actions row; the inner POST does, via "token mcp".

Seeded straight into the temp DB; no network.

Run: ./venv/bin/python service/tests/test_mcp_api.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402

from fastapi import Request  # noqa: E402
from sqlalchemy import select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
import auth  # noqa: E402
import mcp_api  # noqa: E402
import server  # noqa: E402
import toolbox_decide as td  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Action  # noqa: E402

IDS = fx.seed_two_agencies()
CA, CB = IDS["creator_a"], IDS["creator_b"]
for _aid, _nick in ((CA, "creator_a"), (CB, "creator_b")):
    account_registry.save_meta(_aid, {"id": _aid, "nickname": _nick})

A = fx.login_owner("agency_a_owner")
B = fx.login_owner("agency_b_owner")
ANON = _harness.make_client()  # no cookie jar: every call below picks its own credential


TOK_A, TOK_B = fx.mint_token(A), fx.mint_token(B)
HA = {"Authorization": f"Bearer {TOK_A}"}
HB = {"Authorization": f"Bearer {TOK_B}"}
WEEK = {"preset": "last_7_days"}
_ids = iter(range(1, 10_000))


def _post(body, headers=None, client=ANON):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return client.post(mcp_api.PATH, content=raw, headers={"Content-Type": "application/json", **(headers or {})})


def _rpc(method, params=None, headers=HA, client=ANON):
    msg = {"jsonrpc": "2.0", "id": next(_ids), "method": method, **({"params": params} if params is not None else {})}
    r = _post(msg, headers, client)
    assert r.status_code == 200, (method, r.status_code, r.text)
    j = r.json()
    assert j["jsonrpc"] == "2.0" and j["id"] == msg["id"], j
    return j


def _tool(name, args=None, headers=HA):
    j = _rpc("tools/call", {"name": name, "arguments": args or {}}, headers)
    res = j["result"]
    assert json.loads(res["content"][0]["text"]) == res["structuredContent"], res
    return res


def _err_code(r) -> int:
    return r.json()["error"]["code"]


def case_handshake() -> None:
    init = _rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": "t", "version": "0"}})["result"]
    assert init["protocolVersion"] == "2025-06-18" and init["capabilities"]["tools"] == {"listChanged": False}, init
    assert "connect_account" in init["instructions"] and init["serverInfo"]["name"], init
    newest = _rpc("initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"]
    assert newest == mcp_api.VERSIONS[0] == "2025-11-25", newest
    r = _post({"jsonrpc": "2.0", "method": "notifications/initialized"}, {**HA, "MCP-Protocol-Version": "2025-06-18"})
    assert r.status_code == 202 and r.content == b"", (r.status_code, r.text)
    assert _rpc("ping")["result"] == {}
    names = [t["name"] for t in _rpc("tools/list", headers={**HA, "MCP-Protocol-Version": "2025-06-18"})["result"]["tools"]]
    assert names == [t.name for t in td.token_tools()] + ["propose_plan", "plan_status"], names
    assert not {"mass_send", "post_create", "connect_account"} & set(names), names
    res = _tool("creators_list")
    assert res["isError"] is False, res
    assert [c["id"] for c in res["structuredContent"]["accounts"]] == [CA], res
    assert res["structuredContent"]["open_url"].endswith("/creators"), res


def case_origin_refused() -> None:
    for origin in ("https://evil.example", "null", "http://testserver"):
        r = _post({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "creators_list"}},
                  {**HA, "Origin": origin})
        assert r.status_code == 403 and "result" not in r.json(), (origin, r.status_code, r.text)


def case_auth_refused() -> None:
    init = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    cases = (({}, A), ({"Authorization": "Bearer ifw_" + "x" * 43}, ANON), ({"Authorization": "Bearer abc"}, ANON),
             ({"Authorization": "Basic dXNlcjpwdw=="}, ANON), ({"Cookie": "chatterly_session=bogus"}, ANON))
    for headers, client in cases:
        r = _post(init, headers, client)
        assert r.status_code == 401, (headers, r.status_code, r.text)
        assert "tools" not in r.text, r.text


def case_anonymous_surface() -> None:
    assert _rpc("initialize", {"protocolVersion": "2025-03-26"}, {})["result"]["protocolVersion"] == "2025-03-26"
    r = _post({"jsonrpc": "2.0", "method": "notifications/initialized"}, {})
    assert r.status_code == 202, r.status_code
    tools = _rpc("tools/list", headers={})["result"]["tools"]
    assert [t["name"] for t in tools] == ["connect_account", "register_account", "login"], tools
    fwd = {"X-Forwarded-Host": "app.example.com", "X-Forwarded-Proto": "https"}
    out = _tool("connect_account", headers=fwd)
    s = out["structuredContent"]
    assert out["isError"] is False, out
    assert s["register_url"] == "https://app.example.com/login?mode=register&next=%2Fsettings%2Fai-keys", s
    assert s["login_url"] == "https://app.example.com/login?next=%2Fsettings%2Fai-keys", s
    assert s["open_url"] == s["register_url"] and "Access tokens" in s["next_step"], s
    os.environ["MCP_SIGNUP_URL"] = "https://open.example.net/"
    try:
        s = _tool("connect_account", headers=fwd)["structuredContent"]
        assert s["register_url"].startswith("https://open.example.net/login?mode=register"), s
        assert s["login_url"].startswith("https://app.example.com/login"), s
    finally:
        os.environ.pop("MCP_SIGNUP_URL")
    for name in ("creators_list", "report_run"):
        out = _tool(name, {"recipe": {}} if name == "report_run" else {}, headers={})
        s = out["structuredContent"]
        assert out["isError"] is True and s["error"]["status"] == 401, out
        assert s["open_url"] == s["register_url"] and "accounts" not in s, out
    out = _tool("propose_plan", {"summary": "x", "steps": []}, headers={})  # a token builtin: the link
    assert out["isError"] is True and out["structuredContent"]["error"]["status"] == 401, out
    assert _rpc("tools/call", {"name": "mass_send", "arguments": {}}, {})["error"]["code"] == -32602
    assert _rpc("resources/list", headers={})["error"]["code"] == -32601


def case_share_token_gate() -> None:
    saved = server.SHARE_TOKEN
    server.SHARE_TOKEN = "share-secret"
    try:
        assert ANON.get("/admin/accounts").status_code == 401  # the gate is on
        init = _rpc("initialize", {"protocolVersion": "2025-06-18"}, {})["result"]
        assert init["protocolVersion"] == "2025-06-18", init
        anon = [t["name"] for t in _rpc("tools/list", headers={})["result"]["tools"]]
        assert anon == ["connect_account", "register_account", "login"], anon
        out = _tool("creators_list", headers={})
        assert out["isError"] is True and out["structuredContent"]["error"]["status"] == 401, out
        assert "accounts" not in out["structuredContent"], out
        assert ANON.get(mcp_api.PATH).status_code == 405  # anonymous_surface: the 405-only GET too
        assert ANON.post(mcp_api.PATH + "-x", json={}).status_code == 401  # exact path only
        assert _tool("creators_list")["isError"] is False  # a token still works behind the gate
    finally:
        server.SHARE_TOKEN = saved


def case_anonymous_predicate() -> None:
    import audit_log
    for method, path, want in (("POST", mcp_api.PATH, True), ("GET", mcp_api.PATH, True),
                               ("DELETE", mcp_api.PATH, True), ("PUT", mcp_api.PATH, False),
                               ("PATCH", mcp_api.PATH, False), ("POST", mcp_api.PATH + "-x", False),
                               ("POST", mcp_api.PATH + "/x", False), ("POST", "/admin/accounts", False)):
        assert mcp_api.anonymous_surface(method, path) is want, (method, path)
    assert audit_log._AUDIT_SKIP_PATHS == {mcp_api.PATH}
    assert ANON.request("PUT", mcp_api.PATH).status_code == 401  # no principal, not the surface


def case_cross_agency_refused() -> None:
    res = _tool("of_folders_list", {"account_id": CA}, HB)
    assert res["isError"] is True and res["structuredContent"]["error"]["status"] == 403, res
    res = _tool("vault_search", {"account_id": CA}, HB)
    assert res["isError"] is True and res["structuredContent"]["error"]["status"] == 403, res
    ids = [c["id"] for c in _tool("creators_list", headers=HB)["structuredContent"]["accounts"]]
    assert ids == [CB], ids
    assert _tool("of_folders_list", {"account_id": CA})["isError"] is False  # A's own: fine


def case_protocol_errors() -> None:
    assert _rpc("nope/nope")["error"]["code"] == -32601
    assert _rpc("tools/call", {"name": "no_such_tool"})["error"]["code"] == -32602
    assert _rpc("tools/call", {"arguments": {}})["error"]["code"] == -32602
    assert _rpc("tools/call", {"name": "creators_list", "arguments": [1]})["error"]["code"] == -32602
    assert _rpc("initialize", {})["error"]["code"] == -32602
    r = _post({"jsonrpc": "2.0", "id": 9, "method": "ping", "params": [1]}, HA)
    assert r.status_code == 200 and _err_code(r) == -32602, r.text
    bad = _tool("vault_search", {"account_id": CA, "limit": 99, "bogus": 1})
    assert bad["isError"] is True and bad["structuredContent"]["error"]["status"] == 422, bad
    deep = b'{"jsonrpc":"2.0","id":1,"method":"ping","params":' + b"[" * 100_000 + b"]" * 100_000 + b"}"
    for body, code, rid in ((b"{not json", -32700, None), (b"\xff\xfe", -32700, None),
                            (deep, -32700, None),  # nesting past the C stack: RecursionError, not a 500
                            ([{"jsonrpc": "2.0", "id": 1, "method": "ping"}], -32600, None),
                            ({"jsonrpc": "2.0", "id": True, "method": "ping"}, -32600, None),
                            ({"jsonrpc": "2.0", "id": None, "method": "ping"}, -32600, None), ("x", -32600, None),
                            ({"id": 1, "method": "ping"}, -32600, 1),
                            ({"jsonrpc": "1.0", "id": "a", "method": "ping"}, -32600, "a"),
                            ({"jsonrpc": "2.0", "id": 1}, -32600, 1),
                            ({"jsonrpc": "2.0", "id": 1, "method": 5}, -32600, 1)):
        r = _post(body, HA)  # a readable id is echoed (JSON-RPC 2.0 §5), else null
        assert r.status_code == 400 and _err_code(r) == code and r.json()["id"] == rid, (body, r.status_code, r.text)
    big = b'{"jsonrpc": "2.0", "id": 1, "method": "ping", "pad": "' + b"x" * mcp_api.MAX_BODY + b'"}'
    r = _post(big)  # anonymous, announced length
    assert r.status_code == 413 and _err_code(r) == -32600, (r.status_code, r.text[:200])
    r = ANON.post(mcp_api.PATH, content=iter([big[:1000], big[1000:]]),  # chunked: no Content-Length
                  headers={"Content-Type": "application/json"})
    assert r.status_code == 413, (r.status_code, r.text[:200])
    r = _post({"jsonrpc": "2.0", "id": 3, "result": {}}, HA)  # a client's answer
    assert r.status_code == 202, r.status_code
    r = _post({"jsonrpc": "2.0", "id": 1, "method": "ping"}, {**HA, "MCP-Protocol-Version": "2024-11-05"})
    assert r.status_code == 400, r.status_code
    for method in ("GET", "DELETE"):
        r = ANON.request(method, mcp_api.PATH)
        assert r.status_code == 405 and r.headers["allow"] == "POST", (method, r.status_code)
        assert ANON.request(method, mcp_api.PATH, headers=HA).status_code == 403  # off the token allowlist


def case_hostile_values() -> None:
    """A lone UTF-16 surrogate echoed back (id, method, tool name) answers \\u-escaped, never a 500; args httpx
    can't send (NaN, a lone surrogate, a 100k query) are the tool's 422."""
    r = _post(b'{"jsonrpc":"2.0","id":1,"method":"\\ud800"}', HA)
    assert r.status_code == 200 and _err_code(r) == -32601 and r.json()["id"] == 1, (r.status_code, r.text)
    assert b"\\ud800" in r.content, r.content
    r = _post(b'{"jsonrpc":"2.0","id":"\\udfff","method":"ping"}', HA)
    assert r.status_code == 200 and r.json() == {"jsonrpc": "2.0", "id": "\udfff", "result": {}}, r.text
    r = _post(b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"\\ud83d"}}', HA)
    assert r.status_code == 200 and _err_code(r) == -32602, (r.status_code, r.text)
    r = _post(b'{"jsonrpc":"2.0","id":1,"method":"ping"}', HA)
    assert r.content == b'{"jsonrpc":"2.0","id":1,"result":{}}', r.content  # plain answers: bytes unchanged
    nan = (b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"report_run","arguments":{"recipe":'
           b'{"dataset":"sales","window":{"preset":"last_7_days"},"limit":NaN}}}}')
    sur = (b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"vault_search","arguments":'
           b'{"account_id":"%s","query":"\\ud800"}}}' % CA.encode())
    long = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "vault_search", "arguments": {"account_id": CA, "query": "q" * 100_000}}}
    for name, r in (("nan", _post(nan, HA)), ("surrogate", _post(sur, HA)), ("long", _post(long, HA))):
        assert r.status_code == 200, (name, r.status_code, r.text[:200])
        res = r.json()["result"]
        assert res["isError"] is True and res["structuredContent"]["error"]["status"] == 422, (name, res)
        assert res["structuredContent"]["open_url"], (name, res)


def case_send_tools_absent() -> None:
    send = td.Tool("zz_send", "test", "POST", "/admin/zz-mcp/send", td.NoArgs, "send")
    saved = td.TOOLS
    td.TOOLS = saved + (send,)
    try:
        names = [t["name"] for t in _rpc("tools/list")["result"]["tools"]]
        assert "zz_send" not in names and names, names
        assert _rpc("tools/call", {"name": "zz_send"})["error"]["code"] == -32602
    finally:
        td.TOOLS = saved
    names = [t["name"] for t in _rpc("tools/list")["result"]["tools"]]
    for real in ("mass_send", "post_create", "auto_mass", "auto_story"):  # the registry's own send tools
        assert real in {t.name for t in td.TOOLS} and real not in names, names
        args = {"account_id": CA, "text": "hi", "user_lists": ["fans"]}
        assert _rpc("tools/call", {"name": real, "arguments": args})["error"]["code"] == -32602


def _a_page() -> str:
    """A bio page of Agency A (no Creator: no OnlyFans read), made by A's own cookie."""
    r = A.post("/admin/bio-pages", json={"username": f"a_page_{len(_PAGES)}", "display_name": "A"})
    assert r.status_code == 201, r.text
    _PAGES.append(r.json()["profile"]["id"])
    return _PAGES[-1]


_PAGES: list[str] = []


def case_open_url_every_result() -> None:
    args = {"creators_list": {}, "stats_per_model": {"account_id": CA}, "vault_search": {"account_id": CA},
            "of_folders_list": {"account_id": CA}, "describe_all_status": {"account_id": CA},
            "describe_all_plan": {"account_id": CA}, "automation_kinds": {},
            "automation_rules_list": {"account_id": CA}, "bio_pages_list": {},
            "report_catalogue": {}, "report_run": {"recipe": {"dataset": "sales", "window": WEEK}},
            "report_file": {"recipe": {"dataset": "sales", "window": WEEK}}, "bio_page_get": {"pid": _a_page()}}
    reads = {t.name for t in td.TOOLS if t.effect == "read"}  # writes: test_toolbox_writes.py
    assert set(args) == reads, set(args) ^ reads
    fwd = {**HA, "X-Forwarded-Host": "app.example.com", "X-Forwarded-Proto": "https"}
    for name, a in args.items():
        res = _tool(name, a, fwd)
        assert res["isError"] is False, (name, res)
        assert res["structuredContent"]["open_url"].startswith("https://app.example.com/"), (name, res)
    err = _tool("of_folders_list", {"account_id": CB}, fwd)["structuredContent"]
    assert "error" in err and err["open_url"].startswith("https://app.example.com/"), err


async def _hdr(request: Request):
    u = auth.get_request_user()
    return {"employee": request.headers.get("x-employee-id"), "user": u.username if u else None}


server.app.add_api_route("/admin/zz-mcp/hdr", _hdr, methods=["GET"])


def case_employee_header_ignored() -> None:
    probe = td.Tool("zz_hdr", "test", "GET", "/admin/zz-mcp/hdr", td.NoArgs, "read", open=td.Open("/creators"))
    saved = td.TOOLS
    td.TOOLS = saved + (probe,)
    try:
        s = _tool("zz_hdr", headers={**HA, "X-Employee-Id": "1"})["structuredContent"]
        assert s["employee"] is None and s["user"] == "agency_a_owner", s
    finally:
        td.TOOLS = saved


async def _actions() -> list[tuple[str, str | None]]:
    async with get_session() as s:
        return [(a, v) for a, v in (await s.execute(select(Action.action, Action.via))).all()]


def case_audit_inner_only() -> None:
    before = len(asyncio.run(_actions()))
    res = _tool("report_file", {"recipe": {"dataset": "sales", "window": WEEK}})
    assert res["isError"] is False, res
    new = asyncio.run(_actions())[before:]
    assert ("POST /admin/reports/files", "token mcp") in new, new
    assert not any("/admin/mcp" in a for a, _ in asyncio.run(_actions())), new


_harness.run()
