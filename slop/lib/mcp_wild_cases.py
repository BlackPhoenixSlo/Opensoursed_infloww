"""The MCP server's hostile case table and its judges (scenarios/2026-11-14-mcp-wild.py), pure: no I/O, so
lib/test_mcp_wild.py checks the table and every judge without a stack.

A Case is one HTTP request a client could send to POST /admin/mcp (or, for the token-scope and report-file
cases, another route) with what it must answer: the HTTP status set, the JSON-RPC error code (None: a result
or a non-JSON-RPC answer), and for tools/call the tool outcome (`tool`: "ok" = result not isError, an int or
a tuple of ints = isError with that error.status). `who` names the identity the scenario attaches
(`IDENTITIES`); `xff` gives a hostile sign-in its own throttle bucket (TEST-NET-3 address). `unread`: refused
on its headers or size before the body is read, so the answer's id is null. `bug` names a suspected product
bug (file:line) the case is expected to trip until fixed.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import struct
from dataclasses import dataclass, field
from typing import Any

MCP = "/admin/mcp"
SEND_TOOLS = ("mass_send", "post_create", "auto_mass", "auto_story")
ANON_TOOLS = frozenset({"connect_account", "register_account", "login"})
TOKEN_BUILTINS = frozenset({"propose_plan", "plan_status"})
RPC_CODES = frozenset({-32700, -32600, -32601, -32602, -32001})
RPC_HTTP = {-32700: (400,), -32600: (400, 403, 413), -32601: (200,), -32602: (200,), -32001: (401,)}
TOKEN_REFUSED = "not allowed with an access token"
NEEDS_TOKEN = "this tool needs an access token"
IDENTITIES = ("anon", "a", "b", "a_revoked", "a_query", "a_lower", "a_emp_hdr", "cookie_a", "cookie_b_plus_a",
              "employee", "garbage", "bare_ifw", "basic", "bearer_empty")
# What an answer must never show a client: a stack, a source path, an exception class, a driver.
LEAKS = ("Traceback", 'File "', '.py"', ".py:", "site-packages", "/service/", "sqlalchemy", "sqlite3.",
         "pydantic_core", "Exception:", "Error(", "asyncio.", "httpx.")
GOOD_PLAN_TEXT = "new set tonight, open it"
BAD_TOTP_SPREAD = 2   # a wrong code avoids every step in now ± this (the verifier's window is ±1)


@dataclass(frozen=True)
class Case:
    name: str
    group: str
    who: str = "anon"
    body: Any = None              # JSON-able (sent as JSON) or bytes (sent raw)
    method: str = "POST"
    path: str = MCP
    headers: tuple[tuple[str, str], ...] = ()
    status: tuple[int, ...] = (200,)
    code: int | None = None
    tool: Any = None              # None: no tools/call outcome to hold; "ok"; int | tuple[int, ...]
    checks: tuple[str, ...] = ()  # invariants this case feeds besides the group-wide ones
    xff: str | None = None
    unread: bool = False          # refused before the body is read (Origin, credential, version header, size)
    bug: str = ""
    secrets: tuple[str, ...] = field(default=(), compare=False)   # request values no answer may echo


def rpc(method: Any, params: Any = None, rid: Any = 1, **extra) -> dict:
    m = {"jsonrpc": "2.0", "id": rid, "method": method, **extra}
    if params is not None:
        m["params"] = params
    return m


def call(name: Any, args: Any = None, rid: Any = 1) -> dict:
    p: dict[str, Any] = {"name": name}
    if args is not None:
        p["arguments"] = args
    return rpc("tools/call", p, rid)


def raw(obj_text: str) -> bytes:
    return obj_text.encode("utf-8", "surrogatepass")


def request_id(body: Any) -> Any:
    """The id an answer must echo: a valid JSON-RPC request's id, else None (the server cannot know it).
    Raw bytes parse like the server's json.loads (NaN, lone surrogates); unparseable → None."""
    if isinstance(body, bytes):
        try:
            body = json.loads(body)
        except (ValueError, RecursionError):
            return None
    if isinstance(body, dict) and "id" in body:
        rid = body["id"]
        if isinstance(rid, (str, int)) and not isinstance(rid, bool):
            return rid
    return None


def mass_step(aid: str, sid: str = "mass", text: str = GOOD_PLAN_TEXT, **kw) -> dict:
    return {"id": sid, "tool": "mass_send", "args": {"account_id": aid, "text": text, "user_lists": ["fans"], **kw}}


# ── the table ────────────────────────────────────────────────────────────────────────────────────────────

def protocol_cases() -> list[Case]:
    P = "protocol"
    deep = b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{"x":' + b"[" * 100_000 + b"]" * 100_000 + b"}}"
    return [
        Case("p_init_ok", P, body=rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                                     "clientInfo": {"name": "slop", "version": "0"}})),
        Case("p_init_twice", P, body=rpc("initialize", {"protocolVersion": "2025-06-18"}, rid="again")),
        Case("p_init_unknown_version", P, body=rpc("initialize", {"protocolVersion": "1999-01-01"})),
        Case("p_init_no_version", P, body=rpc("initialize", {}), code=-32602),
        Case("p_init_version_int", P, body=rpc("initialize", {"protocolVersion": 5}), code=-32602),
        Case("p_ping", P, body=rpc("ping")),
        Case("p_parse_garbage", P, body=b"{not json", status=(400,), code=-32700),
        Case("p_parse_empty", P, body=b"", status=(400,), code=-32700),
        Case("p_parse_bad_utf8", P, body=b"\xff\xfe{\x00", status=(400,), code=-32700),
        Case("p_parse_trailing", P, body=b'{"jsonrpc":"2.0","id":1,"method":"ping"} {}', status=(400,), code=-32700),
        Case("p_bigint_id", P, body=b'{"jsonrpc":"2.0","method":"ping","id":' + b"9" * 5000 + b"}",
             status=(400,), code=-32700),
        Case("p_deep_nesting", P, body=deep, status=(400,), code=-32700),
        Case("p_batch", P, body=[rpc("ping"), rpc("ping", rid=2)], status=(400,), code=-32600),
        Case("p_batch_empty", P, body=[], status=(400,), code=-32600),
        Case("p_not_object_str", P, body="hello", status=(400,), code=-32600),
        Case("p_not_object_null", P, body=b"null", status=(400,), code=-32600),
        Case("p_no_jsonrpc", P, body={"id": 1, "method": "ping"}, status=(400,), code=-32600),
        Case("p_jsonrpc_1", P, body={"jsonrpc": "1.0", "id": 1, "method": "ping"}, status=(400,), code=-32600),
        Case("p_jsonrpc_num", P, body={"jsonrpc": 2.0, "id": 1, "method": "ping"}, status=(400,), code=-32600),
        Case("p_no_method", P, body={"jsonrpc": "2.0", "id": 1}, status=(400,), code=-32600),
        Case("p_answer_shaped", P, body={"jsonrpc": "2.0", "id": 7, "result": {}}, status=(202,)),
        Case("p_method_int", P, body=rpc(5), status=(400,), code=-32600),
        Case("p_method_null", P, body=rpc(None), status=(400,), code=-32600),
        Case("p_notification", P, body={"jsonrpc": "2.0", "method": "notifications/initialized"}, status=(202,)),
        Case("p_notification_call", P, body={"jsonrpc": "2.0", "method": "tools/call",
                                             "params": {"name": "register_account",
                                                        "arguments": {"username": "x", "password": "y"}}},
             status=(202,)),
        Case("p_id_null", P, body=rpc("ping", rid=None), status=(400,), code=-32600),
        Case("p_id_bool", P, body=rpc("ping", rid=True), status=(400,), code=-32600),
        Case("p_id_obj", P, body=rpc("ping", rid={"a": 1}), status=(400,), code=-32600),
        Case("p_id_float", P, body=rpc("ping", rid=1.5), status=(400,), code=-32600),
        Case("p_id_nan", P, body=b'{"jsonrpc":"2.0","id":NaN,"method":"ping"}', status=(400,), code=-32600),
        Case("p_id_long_str", P, body=rpc("ping", rid="i" * 20_000)),
        Case("p_id_negative", P, body=rpc("ping", rid=-(2 ** 63))),
        Case("p_unknown_method", P, body=rpc("resources/list"), code=-32601),
        Case("p_method_huge", P, body=rpc("m" * 100_000), code=-32601),
        Case("p_method_nul", P, body=rpc("ping\u0000"), code=-32601),
        Case("p_notif_with_id", P, body=rpc("notifications/initialized"), code=-32601),
        Case("p_params_list", P, body=rpc("ping", []), code=-32602),
        Case("p_params_str", P, body=rpc("tools/list", "x"), code=-32602),
        Case("p_params_nan", P, body=b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{"x":NaN,"y":-Infinity}}'),
        Case("p_lone_surrogate_method", P, body=raw('{"jsonrpc":"2.0","id":1,"method":"\\ud800"}'), code=-32601),
        Case("p_lone_surrogate_id", P, body=raw('{"jsonrpc":"2.0","id":"\\udfff","method":"ping"}')),
        Case("p_bad_pv_header", P, body=rpc("ping"), headers=(("MCP-Protocol-Version", "bogus"),),
             status=(400,), code=-32600, unread=True),
        Case("p_good_pv_header", P, body=rpc("ping"), headers=(("MCP-Protocol-Version", "2025-06-18"),)),
        Case("p_content_type_text", P, body=b'{"jsonrpc":"2.0","id":1,"method":"ping"}',
             headers=(("Content-Type", "text/plain"),)),
        Case("p_body_over_256k", P, body=rpc("ping", {"pad": "x" * (300 * 1024)}), status=(413,), code=-32600,
             unread=True),
        Case("p_get", P, method="GET", body=None, status=(405,)),
        Case("p_delete", P, method="DELETE", body=None, status=(405,)),
        Case("p_put", P, method="PUT", body=rpc("ping"), status=(405,)),
        Case("p_sse_accept", P, body=rpc("ping"), headers=(("Accept", "text/event-stream"),)),
    ]


def auth_cases(ids: dict) -> list[Case]:
    A = "auth"
    tl = rpc("tools/list")
    return [
        Case("au_anon_list", A, body=tl, checks=("anonymous_only_three_tools",)),
        Case("au_anon_creators", A, body=call("creators_list", {}), tool=401, checks=("anonymous_only_three_tools",)),
        Case("au_anon_propose", A, body=call("propose_plan", {"summary": "x", "steps": [mass_step(ids["a_aid"])]}),
             tool=401, checks=("anonymous_only_three_tools",)),
        Case("au_anon_status", A, body=call("plan_status", {"plan_id": ids["b_plan"]}), tool=401,
             checks=("anonymous_only_three_tools",)),
        Case("au_anon_mass_send", A, body=call("mass_send", {"account_id": ids["b_aid"], "text": "hi",
                                                             "user_lists": ["fans"]}),
             code=-32602, checks=("no_send_ever",)),
        Case("au_query_token_list", A, who="a_query", body=tl, checks=("anonymous_only_three_tools",)),
        Case("au_query_token_creators", A, who="a_query", body=call("creators_list", {}), tool=401,
             checks=("anonymous_only_three_tools",)),
        Case("au_token_list", A, who="a", body=tl, checks=("send_tools_never_listed",)),
        Case("au_token_list_b", A, who="b", body=tl, checks=("send_tools_never_listed",)),
        Case("au_token_creators", A, who="a", body=call("creators_list", {}), tool="ok"),
        Case("au_token_lower_scheme", A, who="a_lower", body=call("creators_list", {}), tool="ok"),
        Case("au_token_emp_header", A, who="a_emp_hdr", body=call("creators_list", {}), tool="ok"),
        Case("au_cookie_b_plus_token_a", A, who="cookie_b_plus_a", body=call("bio_pages_list", {}), tool="ok"),
        Case("au_origin_anon", A, body=tl, headers=(("Origin", "https://evil.example.com"),), status=(403,),
             code=-32600, checks=("origin_refused",), unread=True),
        Case("au_origin_null", A, body=tl, headers=(("Origin", "null"),), status=(403,), code=-32600,
             checks=("origin_refused",), unread=True),
        Case("au_origin_token", A, who="a", body=call("creators_list", {}),
             headers=(("Origin", "https://evil.example.com"),), status=(403,), code=-32600, checks=("origin_refused",),
             unread=True),
        Case("au_cookie_owner", A, who="cookie_a", body=call("creators_list", {}), status=(401,), code=-32001,
             checks=("cookie_refused",), unread=True),
        Case("au_cookie_owner_list", A, who="cookie_a", body=tl, status=(401,), code=-32001, checks=("cookie_refused",),
             unread=True),
        Case("au_cookie_employee", A, who="employee", body=call("creators_list", {}), status=(401, 403),
             checks=("employee_no_token", "cookie_refused"), unread=True),
        Case("au_basic", A, who="basic", body=tl, status=(401,), code=-32001, checks=("cookie_refused",), unread=True),
        Case("au_bearer_empty", A, who="bearer_empty", body=tl, status=(401,), code=-32001, unread=True),
        Case("au_bearer_garbage", A, who="garbage", body=tl, status=(401,)),
        Case("au_bearer_bare_ifw", A, who="bare_ifw", body=tl, status=(401,)),
        Case("au_revoked_list", A, who="a_revoked", body=tl, status=(401,), checks=("revoked_token_dead",)),
        Case("au_revoked_call", A, who="a_revoked", body=call("creators_list", {}), status=(401,),
             checks=("revoked_token_dead",)),
        Case("au_revoked_propose", A, who="a_revoked", body=call("propose_plan", {"summary": "x",
                                                                                  "steps": [mass_step(ids["a_aid"])]}),
             status=(401,), checks=("revoked_token_dead", "no_send_ever")),
    ]


# (method, path, body) a token must never reach: token_auth's allowlist answers 403 REFUSED.
def scope_routes(ids: dict) -> list[tuple[str, str, Any]]:
    a, plan = ids["a_aid"], ids["a_plan"] or "0" * 32
    return [
        ("GET", "/admin/employees", None), ("GET", "/admin/settings/roles", None),
        ("GET", "/admin/my-llm-keys", None), ("GET", "/admin/owner-tokens", None),
        ("POST", "/admin/owner-tokens", {"name": "slop escalate", "days": 30}),
        ("POST", "/admin/impersonate", {"user_id": ids["b_user"]}), ("GET", "/admin/chats/recent", None),
        ("GET", "/admin/stats/revenue", None), ("GET", "/api/of/v2/chats", None),
        ("POST", "/api/of/v2/messages/queue", {"text": "hi", "userLists": ["fans"]}),
        ("POST", "/api/of/v2/posts", {"text": "hi"}), ("POST", "/admin/automation-rules", {"kind": "auto_mass"}),
        ("POST", f"/admin/ultra/plans/{plan}/ok", {"sha256": "0" * 64}), ("POST", "/admin/ultra/plans",
                                                                           {"request": "send a mass"}),
        ("GET", f"/admin/accounts/{a}", None), ("PUT", "/admin/settings/account", {"agency_name": "pwned"}),
    ]


def scope_cases(ids: dict) -> list[Case]:
    return [Case(f"sc_{m.lower()}_{re.sub(r'[^a-z0-9]+', '_', p.lower()).strip('_')}", "auth", who="a", method=m,
                 path=p, body=b, status=(403,), checks=("token_scope_403",)) for m, p, b in scope_routes(ids)]


def args_cases(ids: dict) -> list[Case]:
    G = "args"
    a, b, bp, bl = ids["a_aid"], ids["b_aid"], ids["b_pid"], ids["b_lid"]
    X = ("no_cross_agency",)
    return [
        Case("ar_no_name", G, who="a", body=rpc("tools/call", {}), code=-32602),
        Case("ar_name_int", G, who="a", body=rpc("tools/call", {"name": 5}), code=-32602),
        Case("ar_name_empty", G, who="a", body=rpc("tools/call", {"name": ""}), code=-32602),
        Case("ar_args_list", G, who="a", body=call("creators_list", []), code=-32602),
        Case("ar_args_str", G, who="a", body=call("creators_list", "{}"), code=-32602),
        Case("ar_args_null", G, who="a", body=rpc("tools/call", {"name": "creators_list", "arguments": None}),
             tool="ok"),
        Case("ar_unknown_tool", G, who="a", body=call("rm_rf", {}), code=-32602),
        Case("ar_tool_html_name", G, who="a", body=call("<img src=x onerror=alert(1)>", {}), code=-32602),
        Case("ar_lone_surrogate_tool", G, who="a", body=raw('{"jsonrpc":"2.0","id":1,"method":"tools/call",'
                                                            '"params":{"name":"\\ud83d"}}'), code=-32602),
        *[Case(f"ar_send_{t}", G, who="a", body=call(t, {"account_id": a, "text": "hi", "user_lists": ["fans"]}),
               code=-32602, checks=("no_send_ever",)) for t in SEND_TOOLS],
        Case("ar_extra_key", G, who="a", body=call("creators_list", {"evil": 1}), tool=422),
        Case("ar_wrong_type", G, who="a", body=call("vault_search", {"account_id": 123}), tool=422),
        Case("ar_limit_0", G, who="a", body=call("vault_search", {"account_id": a, "limit": 0}), tool=422),
        Case("ar_limit_31", G, who="a", body=call("vault_search", {"account_id": a, "limit": 31}), tool=422),
        Case("ar_limit_nan", G, who="a", body=raw('{"jsonrpc":"2.0","id":1,"method":"tools/call","params":'
                                                  '{"name":"vault_search","arguments":{"account_id":"%s",'
                                                  '"limit":NaN}}}' % a), tool=422),
        Case("ar_type_enum", G, who="a", body=call("vault_search", {"account_id": a, "type": "exe"}), tool=422),
        Case("ar_query_huge", G, who="a", body=call("vault_search", {"account_id": a, "query": "q" * 100_000}),
             tool=("ok", 400, 413, 414, 422)),
        Case("ar_query_sql", G, who="a", body=call("vault_search", {"account_id": a,
                                                                    "query": "' OR 1=1; DROP TABLE accounts;--"}),
             tool="ok"),
        Case("ar_vault_own", G, who="a", body=call("vault_search", {"account_id": a, "query": "set"}), tool="ok"),
        Case("ar_stats_bad_date", G, who="a", body=call("stats_per_model", {"from": "not-a-date"}),
             tool=(400, 422)),
        Case("ar_stats_inf", G, who="a", body=raw('{"jsonrpc":"2.0","id":1,"method":"tools/call","params":'
                                                  '{"name":"stats_per_model","arguments":{"engagement":Infinity}}}'),
             tool=422),
        Case("ar_stats_own", G, who="a", body=call("stats_per_model", {}), tool="ok"),
        Case("ar_vault_other", G, who="a", body=call("vault_search", {"account_id": b}), tool=(403, 404), checks=X),
        Case("ar_folders_other", G, who="a", body=call("of_folders_list", {"account_id": b}), tool=(403, 404),
             checks=X),
        Case("ar_describe_other", G, who="a", body=call("describe_all_status", {"account_id": b}), tool=(403, 404),
             checks=X),
        Case("ar_describe_plan_other", G, who="a", body=call("describe_all_plan", {"account_id": b}),
             tool=(403, 404), checks=X),
        Case("ar_stats_other", G, who="a", body=call("stats_per_model", {"account_id": b}), tool=(403, 404),
             checks=X),
        Case("ar_rules_other", G, who="a", body=call("automation_rules_list", {"account_id": b}), tool=(403, 404),
             checks=X),
        Case("ar_bio_get_other", G, who="a", body=call("bio_page_get", {"pid": bp}), tool=(403, 404), checks=X),
        Case("ar_bio_get_traversal", G, who="a", body=call("bio_page_get", {"pid": "../../etc/passwd"}), tool=422),
        Case("ar_bio_link_add_other", G, who="a", body=call("bio_link_add", {"pid": bp, "title": "pwn",
                                                                             "destination": "https://example.com/"}),
             tool=(403, 404), checks=X),
        Case("ar_bio_avatar_other", G, who="a", body=call("bio_avatar_from_vault", {"pid": bp, "media_id": 1}),
             tool=(403, 404), checks=X),
        Case("ar_bio_bg_other", G, who="a", body=call("bio_page_background", {"pid": bp, "media_id": 1}),
             tool=(403, 404), checks=X),
        Case("ar_bio_link_bg_other", G, who="a", body=call("bio_link_bg_from_vault", {"pid": bp, "lid": bl,
                                                                                      "media_id": 1}),
             tool=(403, 404), checks=X),
        Case("ar_bio_create_other_creator", G, who="a",
             body=call("bio_page_create", {"username": ids["squat"], "account_id": b}), tool=(403, 404), checks=X),
        Case("ar_bio_create_bad_username", G, who="a", body=call("bio_page_create", {"username": "A B"}), tool=422),
        Case("ar_folder_create_other", G, who="a", body=call("of_folder_create", {"account_id": b, "name": "pwn"}),
             tool=(403, 404), checks=X),
        Case("ar_folder_add_other", G, who="a", body=call("of_folder_add", {"account_id": b, "list_id": 1,
                                                                            "media_ids": [1]}),
             tool=(403, 404), checks=X),
        Case("ar_folder_add_neg", G, who="a", body=call("of_folder_add", {"account_id": a, "list_id": -1,
                                                                          "media_ids": [1]}), tool=422),
        Case("ar_folder_add_empty", G, who="a", body=call("of_folder_add", {"account_id": a, "list_id": 1,
                                                                            "media_ids": []}), tool=422),
        Case("ar_folder_add_bool", G, who="a", body=call("of_folder_add", {"account_id": a, "list_id": 1,
                                                                           "media_ids": [True]}), tool=422),
        Case("ar_folder_name_long", G, who="a", body=call("of_folder_create", {"account_id": a, "name": "n" * 121}),
             tool=422),
        Case("ar_report_empty", G, who="a", body=call("report_run", {"recipe": {}}), tool=(400, 422)),
        Case("ar_report_dataset", G, who="a", body=call("report_run", {"recipe": {"dataset": "users",
                                                                                  "window": {"preset": "today"}}}),
             tool=(400, 422)),
        Case("ar_report_limit", G, who="a", body=call("report_run", {"recipe": {
            "dataset": "sales", "window": {"preset": "last_7_days"}, "limit": 10 ** 9}}), tool=(400, 422)),
        Case("ar_report_group_sql", G, who="a", body=call("report_run", {"recipe": {
            "dataset": "sales", "window": {"preset": "last_7_days"}, "group_by": ["'; DROP TABLE users;--"]}}),
             tool=(400, 422)),
        Case("ar_report_recipe_nan", G, who="a", body=raw(
            '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"report_run","arguments":{"recipe":'
            '{"dataset":"sales","window":{"preset":"last_7_days"},"limit":NaN}}}}'), tool=(400, 422)),
        Case("ar_report_ok", G, who="a", body=call("report_run", {"recipe": {
            "dataset": "sales", "window": {"preset": "last_7_days"}}}), tool="ok", checks=X),
        Case("ar_report_file_pdf", G, who="a", body=call("report_file", {"recipe": {
            "dataset": "sales", "window": {"preset": "last_7_days"}}, "format": "pdf"}), tool=422),
    ]


def plan_cases(ids: dict) -> list[Case]:
    G = "plans"
    a, b = ids["a_aid"], ids["b_aid"]
    pr = lambda summary, steps: call("propose_plan", {"summary": summary, "steps": steps})  # noqa: E731
    return [
        Case("pl_empty_steps", G, who="a", body=pr("x", []), tool=422),
        Case("pl_60_steps", G, who="a", body=pr("x", [mass_step(a, f"m{i}") for i in range(60)]), tool=422),
        Case("pl_summary_long", G, who="a", body=pr("s" * 501, [mass_step(a)]), tool=422),
        Case("pl_unknown_tool", G, who="a", body=pr("x", [{"id": "z", "tool": "rm_rf", "args": {}}]), tool=422),
        Case("pl_other_agency", G, who="a", body=pr("x", [mass_step(b)]), tool=422, checks=("no_cross_agency",)),
        Case("pl_offplatform", G, who="a", body=pr("x", [mass_step(a, text="add me on telegram")]), tool=422),
        Case("pl_narration", G, who="a", body=pr("x", [mass_step(a, text="*smiles* new set")]), tool=422),
        Case("pl_ref_in_send", G, who="a", body=pr("x", [{"id": "f", "tool": "of_folders_list",
                                                         "args": {"account_id": a}},
                                                        mass_step(a, "m", user_lists=["$f.list.0.id"])]), tool=422),
        Case("pl_dup_ids", G, who="a", body=pr("x", [mass_step(a), mass_step(a)]), tool=422),
        Case("pl_extra_key", G, who="a", body=call("propose_plan", {"summary": "x", "steps": [mass_step(a)],
                                                                    "approved": True}), tool=422),
        Case("pl_status_other", G, who="a", body=call("plan_status", {"plan_id": ids["b_plan"]}), tool=404,
             checks=("no_cross_agency",)),
        Case("pl_status_bad_id", G, who="a", body=call("plan_status", {"plan_id": "../" + "a" * 29}), tool=422),
        Case("pl_status_unknown", G, who="a", body=call("plan_status", {"plan_id": "f" * 32}), tool=404),
        Case("pl_good", G, who="a", body=pr("slop mcp-wild good plan", [mass_step(a)]), tool="ok"),
    ]


def plan_followups(ids: dict) -> list[Case]:
    """Once pl_good stored A's plan: its status (never OK'd) and the OK no token or foreign cookie may give."""
    G = "plans"
    return [
        Case("pl_status_own", G, who="a", body=call("plan_status", {"plan_id": ids["a_plan"]}), tool="ok"),
        Case("pl_status_own_by_b", G, who="b", body=call("plan_status", {"plan_id": ids["a_plan"]}), tool=404,
             checks=("no_cross_agency",)),
        Case("pl_ok_by_token", G, who="a", path=f"/admin/ultra/plans/{ids['a_plan']}/ok", body={"sha256": "0" * 64},
             status=(403,), checks=("token_scope_403", "no_send_ever")),
        Case("pl_ok_b_plan_by_cookie_a", G, who="cookie_a", path=f"/admin/ultra/plans/{ids['b_plan']}/ok",
             body={"sha256": "0" * 64}, status=(404, 409), checks=("no_cross_agency", "no_send_ever")),
    ]


def report_file_cases(ids: dict) -> list[Case]:
    """A's file (made by ar_report_file_ok) and B's (made in setup): only the maker downloads."""
    G, C = "args", ("report_file_owner_only",)
    fa, fb = ids["a_file"], ids["b_file"]
    return [
        Case("rf_own", G, who="a", method="GET", path=fa, body=None, status=(200,), checks=C),
        Case("rf_own_by_b", G, who="b", method="GET", path=fa, body=None, status=(404,), checks=C + ("no_cross_agency",)),
        Case("rf_b_by_a", G, who="a", method="GET", path=fb, body=None, status=(404,), checks=C + ("no_cross_agency",)),
        Case("rf_own_anon", G, method="GET", path=fa, body=None, status=(401, 403, 404), checks=C),
        Case("rf_own_revoked", G, who="a_revoked", method="GET", path=fa, body=None, status=(401,),
             checks=C + ("revoked_token_dead",)),
        Case("rf_unknown", G, who="a", method="GET", path="/admin/reports/files/" + "0" * 32, body=None,
             status=(404,), checks=C),
    ]


def signup_cases(ids: dict) -> list[Case]:
    """Anonymous register/login; each on its own X-Forwarded-For (203.0.113.<n>) so throttles never cross cases."""
    G = "signup"
    u, pw, new = ids["a_user"], ids["a_password"], ids["new_user"]
    emp, emp_pw = ids["emp_user"], ids["emp_password"]
    tf, tf_pw = ids["tf_user"], ids["tf_password"]
    S = lambda *s: tuple(x for x in s if x)  # noqa: E731
    cases = [
        Case("su_register_ok", G, body=call("register_account", {"username": new, "password": "slop-wild-pw-1",
                                                                  "agency_name": "Slop Wild"}),
             tool="ok", secrets=S("slop-wild-pw-1")),
        Case("su_register_dup", G, body=call("register_account", {"username": new, "password": "slop-wild-pw-2"}),
             tool=409, secrets=S("slop-wild-pw-2")),
        Case("su_register_bad_username", G, body=call("register_account", {"username": "BAD NAME!",
                                                                            "password": "slop-wild-pw-3"}),
             tool=(400, 422), secrets=S("slop-wild-pw-3")),
        Case("su_register_email_username", G, body=call("register_account", {"username": "x@example.com",
                                                                              "password": "slop-wild-pw-4"}),
             tool=(400, 422), secrets=S("slop-wild-pw-4")),
        Case("su_register_short_pw", G, body=call("register_account", {"username": new + "s", "password": "a"}),
             tool=(400, 422)),
        Case("su_register_agency_10k", G, body=call("register_account", {"username": new + "l",
                                                                         "password": "slop-wild-pw-5",
                                                                         "agency_name": "A" * 10_000}),
             tool=422, secrets=S("slop-wild-pw-5")),
        Case("su_register_is_admin", G, body=call("register_account", {"username": new + "x",
                                                                       "password": "slop-wild-pw-6",
                                                                       "is_admin": True}),
             tool=422, secrets=S("slop-wild-pw-6")),
        Case("su_register_missing", G, body=call("register_account", {}), tool=422),
        Case("su_login_wrong_pw", G, body=call("login", {"username": u, "password": "wrong-" + pw}), tool=401,
             secrets=S("wrong-" + pw)),
        Case("su_login_unknown", G, body=call("login", {"username": new + "nobody", "password": "slop-wild-pw-7"}),
             tool=401, secrets=S("slop-wild-pw-7")),
        Case("su_login_employee", G, body=call("login", {"username": emp, "password": emp_pw}), tool=403,
             checks=("employee_no_token",), secrets=S(emp_pw)),
        Case("su_login_2fa_no_code", G, body=call("login", {"username": tf, "password": tf_pw}), tool=401,
             secrets=S(tf_pw)),
        Case("su_login_2fa_bad_code", G, body=call("login", {"username": tf, "password": tf_pw,
                                                             "code": ids["tf_bad_code"]}),
             tool=(400, 401), secrets=S(tf_pw, ids["tf_bad_code"])),
        Case("su_login_2fa_code_long", G, body=call("login", {"username": tf, "password": tf_pw, "code": "9" * 65}),
             tool=422, secrets=S(tf_pw)),
        Case("su_login_ok", G, body=call("login", {"username": u, "password": pw}), tool="ok", secrets=S(pw)),
    ]
    return [Case(**{**c.__dict__, "xff": f"203.0.113.{10 + i}"}) for i, c in enumerate(cases)]


def login_burst(ids: dict, n: int = 8) -> list[Case]:
    """`n` wrong passwords for one unknown name from one address: past the per-name bucket (5) → 429."""
    name = ids["new_user"] + "burst"
    return [Case(f"su_burst_{i:02d}", "signup", body=call("login", {"username": name, "password": f"burst-pw-{i}"}),
                 tool=(401, 429), xff="203.0.113.200", secrets=(f"burst-pw-{i}",)) for i in range(n)]


def two_factor_followup(ids: dict) -> Case:
    return Case("su_login_2fa_ok", "signup", body=call("login", {"username": ids["tf_user"],
                                                                 "password": ids["tf_password"],
                                                                 "code": ids["tf_code"]}),
                tool="ok", xff="203.0.113.60", secrets=(ids["tf_password"],))


# ── the volume mix: (weight, name, who, body); answers judged like the table, statuses histogrammed ─────────

def mix_table(ids: dict) -> list[tuple[int, str, str, Any]]:
    a, b = ids["a_aid"], ids["b_aid"]
    return [
        (10, "v_list_a", "a", rpc("tools/list")), (6, "v_list_b", "b", rpc("tools/list")),
        (6, "v_list_anon", "anon", rpc("tools/list")), (8, "v_ping", "anon", rpc("ping")),
        (8, "v_creators_a", "a", call("creators_list", {})), (6, "v_creators_b", "b", call("creators_list", {})),
        (6, "v_bio_list_a", "a", call("bio_pages_list", {})), (4, "v_bio_other", "a",
                                                               call("bio_page_get", {"pid": ids["b_pid"]})),
        (4, "v_vault_other", "a", call("vault_search", {"account_id": b})),
        (4, "v_vault_own", "a", call("vault_search", {"account_id": a, "limit": 5})),
        (4, "v_kinds", "b", call("automation_kinds", {})), (4, "v_catalogue", "a", call("report_catalogue", {})),
        (4, "v_status_other", "a", call("plan_status", {"plan_id": ids["b_plan"]})),
        (4, "v_send_tool", "a", call("mass_send", {"account_id": a, "text": "hi", "user_lists": ["fans"]})),
        (4, "v_garbage", "anon", b"{\"jsonrpc\":"), (3, "v_batch", "a", [rpc("ping")]),
        (3, "v_unknown_method", "b", rpc("sampling/createMessage")),
        (3, "v_revoked", "a_revoked", call("creators_list", {})),
        (3, "v_cookie", "cookie_a", rpc("tools/list")), (3, "v_anon_data", "anon", call("creators_list", {})),
        (2, "v_bad_args", "a", call("vault_search", {"account_id": a, "limit": "lots"})),
        (2, "v_notification", "a", {"jsonrpc": "2.0", "method": "notifications/cancelled"}),
    ]


# ── judges ───────────────────────────────────────────────────────────────────────────────────────────────

def parse(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None


def tool_outcome(parsed: Any) -> tuple[bool | None, int | None, Any]:
    """(isError, error.status, error.detail) of a tools/call result; (None, None, None) when it is none."""
    res = parsed.get("result") if isinstance(parsed, dict) else None
    if not isinstance(res, dict) or "isError" not in res:
        return None, None, None
    sc = res.get("structuredContent")
    err = sc.get("error") if isinstance(sc, dict) else None
    if isinstance(err, dict):
        return bool(res["isError"]), err.get("status"), err.get("detail")
    return bool(res["isError"]), None, None


def wellformed(status: int, ctype: str, text: str, req_id: Any, *, mcp: bool = True,
               www_auth: str = "") -> str | None:
    """Why one answer is not a proper answer to a client, else None. An MCP-endpoint answer is a JSON-RPC
    2.0 object (one of result/error; error {code int known, message non-empty str}; id echoed, None when
    the request's was unusable; an error code on its HTTP status), a 202 with no body, a 405, or the token
    layer's 401 (WWW-Authenticate: Bearer). Off the endpoint: any answer below 500."""
    if status >= 500:
        return f"HTTP {status}"
    if not mcp:
        return None
    if status == 202:
        return None if not text.strip() else "202 with a body"
    if status == 405:
        return None
    parsed = parse(text)
    if not isinstance(parsed, dict) or parsed.get("jsonrpc") != "2.0":
        if status == 401 and "bearer" in www_auth.lower():
            return None
        return f"HTTP {status} answer is no JSON-RPC 2.0 object: {text[:120]!r}"
    if "application/json" not in ctype:
        return f"JSON-RPC answer with content-type {ctype!r}"
    if ("result" in parsed) == ("error" in parsed):
        return "neither or both of result/error"
    if "id" not in parsed:
        return "no id"
    if parsed["id"] != req_id:
        return f"id {str(parsed['id'])[:40]!r} != request id {str(req_id)[:40]!r}"
    if "error" in parsed:
        e = parsed["error"]
        if not isinstance(e, dict) or not isinstance(e.get("code"), int) or isinstance(e.get("code"), bool):
            return f"error not {{code:int,…}}: {str(e)[:120]}"
        if e["code"] not in RPC_CODES:
            return f"unknown error code {e['code']}"
        if not isinstance(e.get("message"), str) or not e["message"].strip():
            return "error message missing"
        if status not in RPC_HTTP[e["code"]]:
            return f"code {e['code']} on HTTP {status}"
    elif status != 200:
        return f"result on HTTP {status}"
    return None


def leaks(text: str, secrets: tuple[str, ...] = ()) -> list[str]:
    """What an answer shows that it never should: LEAKS markers and any request secret echoed back."""
    out = [m for m in LEAKS if m in text]
    out += [f"secret:{s[:3]}…" for s in secrets if s and len(s) >= 4 and s in text]
    return out


def sentinel_hits(text: str, sentinels: tuple[str, ...]) -> list[str]:
    return [s for s in sentinels if s and s in text]


def expect_problems(case: Case, status: int, parsed: Any) -> list[str]:
    """How one answer differs from the case's expectation (empty: as expected)."""
    out = []
    if status not in case.status:
        out.append(f"status {status} not in {case.status}")
    code = parsed.get("error", {}).get("code") if isinstance(parsed, dict) and isinstance(
        parsed.get("error"), dict) else None
    if case.code is not None and code != case.code:
        out.append(f"rpc code {code} != {case.code}")
    if case.code is None and code is not None and status == 200:
        out.append(f"unexpected rpc error {code}")
    if case.tool is not None and status == 200 and code is None:
        is_err, tstatus, _ = tool_outcome(parsed)
        want = case.tool if isinstance(case.tool, tuple) else (case.tool,)
        got = "ok" if is_err is False else tstatus
        if is_err is None:
            out.append("no tools/call result")
        elif got not in want:
            out.append(f"tool outcome {got!r} not in {want}")
    return out


def tool_names(parsed: Any) -> set[str]:
    res = parsed.get("result") if isinstance(parsed, dict) else None
    tools = res.get("tools") if isinstance(res, dict) else None
    return {t.get("name") for t in tools if isinstance(t, dict)} if isinstance(tools, list) else set()


def redact(obj: Any, secrets: dict[str, str]) -> Any:
    """`obj` with every secret value (token, password, code) swapped for its <label>, recursively."""
    if isinstance(obj, str):
        for val, lab in sorted(secrets.items(), key=lambda kv: -len(kv[0])):
            if val and len(val) >= 4:
                obj = obj.replace(val, f"<{lab}>")
        return obj
    if isinstance(obj, dict):
        return {k: ("<password>" if k in ("password", "code") and isinstance(v, str) else redact(v, secrets))
                for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact(v, secrets) for v in obj]
    return obj


def short_body(body: Any, limit: int = 600) -> Any:
    """A request body as evidence: JSON objects kept (long strings cut), raw bytes as a cut repr."""
    if isinstance(body, bytes):
        s = body.decode("utf-8", "backslashreplace")
        return {"raw": s[:limit] + (f"… (+{len(s) - limit} chars)" if len(s) > limit else "")}

    def cut(v):
        if isinstance(v, str) and len(v) > 200:
            return v[:200] + f"… (+{len(v) - 200} chars)"
        if isinstance(v, dict):
            return {k: cut(x) for k, x in v.items()}
        if isinstance(v, list):
            return [cut(x) for x in v[:25]] + ([f"… (+{len(v) - 25} items)"] if len(v) > 25 else [])
        return v
    return cut(body)


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, int(len(s) * q))], 1)


# ── TOTP (RFC 6238: SHA-1, 30 s, 6 digits), as service/account_security.totp ─────────────────────────────

def totp(secret_b32: str, step: int) -> str:
    key = base64.b32decode(secret_b32.upper() + "=" * (-len(secret_b32) % 8))
    d = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    o = d[-1] & 0x0F
    return str((struct.unpack(">I", d[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** 6).zfill(6)


def bad_code(secret_b32: str, step: int) -> str:
    """A 6-digit code that no step in step ± BAD_TOTP_SPREAD accepts."""
    near = {totp(secret_b32, step + k) for k in range(-BAD_TOTP_SPREAD, BAD_TOTP_SPREAD + 1)}
    return next(c for c in (f"{n:06d}" for n in range(0, 1_000_000, 111_111)) if c not in near)
