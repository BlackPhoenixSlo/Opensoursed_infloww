"""lib/mcp_wild_cases.py: the case table's shape and the judges (scenarios/2026-11-14-mcp-wild.py)."""
from __future__ import annotations

import json

import pytest

from slop.lib import mcp_wild_cases as mc
from slop.lib import mcp_wild_faults as mf

IDS = {"a_aid": "100000001", "b_aid": "450000001", "b_pid": "bpmcpwild000001", "b_lid": "blmcpwild000001",
       "b_user": "u-b", "a_user": "slop1", "a_password": "slop-throwaway-password", "new_user": "slop1mcpnew",
       "emp_user": "slop1mcpemp", "emp_password": "slop-chatter-password", "tf_user": "slop1mcptf",
       "tf_password": "slop-throwaway-password", "tf_bad_code": "000000", "tf_code": "123456", "squat": "slopsquat1",
       "a_plan": "a" * 32, "b_plan": "b" * 32, "a_file": "/admin/reports/files/" + "c" * 32,
       "b_file": "/admin/reports/files/" + "d" * 32}


def table() -> list[mc.Case]:
    return (mc.protocol_cases() + mc.auth_cases(IDS) + mc.scope_cases(IDS) + mc.args_cases(IDS)
            + mc.plan_cases(IDS) + mc.plan_followups(IDS) + mc.report_file_cases(IDS) + mc.signup_cases(IDS)
            + mc.login_burst(IDS) + [mc.two_factor_followup(IDS)])


def test_table_names_unique_identities_known_checks_real():
    cases = table()
    names = [c.name for c in cases]
    assert len(names) == len(set(names))
    assert {c.group for c in cases} >= {"protocol", "auth", "args", "plans", "signup"}
    for c in cases:
        assert c.who in mc.IDENTITIES, c.name
        assert set(c.checks) <= set(mf.CHECKS), c.name
        assert c.code is None or c.code in mc.RPC_CODES, c.name
    for check in (mf.C_ORIGIN, mf.C_COOKIE, mf.C_SCOPE, mf.C_EMPLOYEE, mf.C_REPORT_FILE, mf.C_REVOKED):
        assert any(check in c.checks for c in cases), check


def test_send_tool_calls_expect_unknown_tool():
    sends = [c for c in table() if isinstance(c.body, dict) and c.body.get("method") == "tools/call"
             and (c.body.get("params") or {}).get("name") in mc.SEND_TOOLS]
    assert sends
    assert all(c.code == -32602 for c in sends)
    mix = {x[1]: x[3] for x in mc.mix_table(IDS)}
    assert mix["v_send_tool"]["params"]["name"] in mc.SEND_TOOLS


def test_scope_cases_off_mcp_expect_403():
    for c in mc.scope_cases(IDS):
        assert c.path != mc.MCP and c.status == (403,) and mf.C_SCOPE in c.checks


def test_signup_each_case_own_address_and_example_com_only():
    xffs = [c.xff for c in mc.signup_cases(IDS)]
    assert len(xffs) == len(set(xffs)) and all(x.startswith("203.0.113.") for x in xffs)
    blob = json.dumps([c.body for c in table() if isinstance(c.body, dict)])
    for tok in blob.split('"'):
        if "@" in tok and "." in tok.split("@")[-1]:
            assert tok.endswith("example.com"), tok


def test_mix_names_unique_and_expectations_cover_every_pick():
    import importlib
    scen = importlib.import_module("slop.scenarios.2026-11-14-mcp-wild")
    names = [x[1] for x in mc.mix_table(IDS)]
    assert len(names) == len(set(names))
    assert set(names) == set(scen._MIX_STATUS)
    assert all(x[2] in mc.IDENTITIES and x[0] > 0 for x in mc.mix_table(IDS))
    assert scen.FAULT in __import__("slop.lib.faults", fromlist=["FAULTS"]).FAULTS


@pytest.mark.parametrize("status,ctype,text,rid,www,ok", [
    (200, "application/json", '{"jsonrpc":"2.0","id":1,"result":{}}', 1, "", True),
    (400, "application/json", '{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"Parse error"}}', None,
     "", True),
    (200, "application/json", '{"jsonrpc":"2.0","id":1,"error":{"code":-32601,"message":"Method not found: x"}}', 1,
     "", True),
    (202, "", "", None, "", True),
    (405, "text/plain", "POST only", None, "", True),
    (401, "text/plain", "invalid, expired or revoked access token", 1, 'Bearer realm="x"', True),
    (401, "text/plain", "invalid", 1, "", False),                                     # no WWW-Authenticate
    (500, "text/plain", "Internal Server Error", 1, "", False),
    (200, "application/json", '{"jsonrpc":"2.0","id":2,"result":{}}', 1, "", False),  # id not echoed
    (200, "application/json", '{"jsonrpc":"2.0","id":1,"result":{},"error":{}}', 1, "", False),
    (400, "application/json", '{"jsonrpc":"2.0","id":1,"error":{"code":-32601,"message":"x"}}', 1, "", False),
    (200, "application/json", '{"jsonrpc":"2.0","id":1,"error":{"code":-1,"message":"x"}}', 1, "", False),
    (200, "application/json", '{"jsonrpc":"2.0","id":1,"error":{"code":true,"message":"x"}}', 1, "", False),
    (400, "application/json", '{"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":" "}}', 1, "", False),
    (202, "application/json", '{"x":1}', None, "", False),
])
def test_wellformed(status, ctype, text, rid, www, ok):
    assert (mc.wellformed(status, ctype, text, rid, www_auth=www) is None) is ok


def _tool(is_error, status=None, detail=None):
    sc = {"error": {"status": status, "detail": detail}} if status else {"x": 1}
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [], "structuredContent": sc, "isError": is_error}}


@pytest.mark.parametrize("case,status,parsed,n", [
    (mc.Case("t", "g", tool="ok"), 200, _tool(False), 0),
    (mc.Case("t", "g", tool="ok"), 200, _tool(True, 403, "no"), 1),
    (mc.Case("t", "g", tool=(403, 404)), 200, _tool(True, 404, "gone"), 0),
    (mc.Case("t", "g", tool=401), 200, {"jsonrpc": "2.0", "id": 1, "result": {}}, 1),       # no tools/call result
    (mc.Case("t", "g", status=(400,), code=-32700), 400,
     {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "x"}}, 0),
    (mc.Case("t", "g", status=(400,), code=-32700), 400,
     {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "x"}}, 1),
    (mc.Case("t", "g"), 200, {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "x"}}, 1),
    (mc.Case("t", "g", status=(401, 403)), 401,
     {"jsonrpc": "2.0", "id": 1, "error": {"code": -32001, "message": "x"}}, 0),
    (mc.Case("t", "g"), 500, None, 1),
])
def test_expect_problems(case, status, parsed, n):
    assert len(mc.expect_problems(case, status, parsed)) == n


def test_tool_outcome_and_names():
    assert mc.tool_outcome(_tool(True, 401, "needs")) == (True, 401, "needs")
    assert mc.tool_outcome(_tool(False)) == (False, None, None)
    assert mc.tool_outcome({"result": {}}) == (None, None, None)
    assert mc.tool_names({"result": {"tools": [{"name": "a"}, {"name": "b"}, 3]}}) == {"a", "b"}
    assert mc.tool_names(None) == set()


def test_leaks_and_sentinels():
    assert mc.leaks("Traceback (most recent call last)")
    assert mc.leaks('File "/app/service/x.py", line 3')
    assert mc.leaks("bad password hunter22!", ("hunter22!",))
    assert not mc.leaks("invalid arguments", ("abc",))   # secrets under 4 chars ignored
    assert mc.sentinel_hits("nick bwild1nick x", ("bwild1nick", "", "zz")) == ["bwild1nick"]


def test_redact():
    sec = {"ifw_secret123": "token:a"}
    got = mc.redact({"headers": {"Authorization": "Bearer ifw_secret123"}, "password": "pw",
                     "nested": [{"code": "123456"}, "x ifw_secret123 y"]}, sec)
    assert got == {"headers": {"Authorization": "Bearer <token:a>"}, "password": "<password>",
                   "nested": [{"code": "<password>"}, "x <token:a> y"]}
    assert "ifw_secret123" not in json.dumps(got)


def test_short_body_and_pct():
    assert mc.short_body(b"\xff" * 700)["raw"].endswith("chars)")
    assert len(mc.short_body({"s": "x" * 1000})["s"]) < 260
    assert mc.pct([], 0.5) is None
    assert mc.pct([1, 2, 3, 4], 0.5) == 3 and mc.pct([5.0], 0.95) == 5.0


def test_totp_rfc6238_vector_and_bad_code():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"   # RFC 6238 SHA-1 key "12345678901234567890"
    assert mc.totp(secret, 1) == "287082"          # T = 59 s
    assert mc.totp(secret, 37037036) == "081804"   # T = 1111111109 s
    for step in (37037036, 59_000_000):
        bad = mc.bad_code(secret, step)
        assert len(bad) == 6 and bad.isdigit()
        assert all(mc.totp(secret, step + k) != bad for k in range(-mc.BAD_TOTP_SPREAD, mc.BAD_TOTP_SPREAD + 1))


def test_request_id_and_raw():
    assert mc.request_id(mc.rpc("ping", rid=7)) == 7
    assert mc.request_id(b"{") is None
    assert mc.raw('"\\ud800"') == '"\\ud800"'.encode()
    # raw bodies parse like the server's json.loads: NaN, a lone surrogate id; too deep / too long → None
    assert mc.request_id(b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{"x":NaN}}') == 1
    assert mc.request_id(mc.raw('{"jsonrpc":"2.0","id":"\\udfff","method":"ping"}')) == "\udfff"
    assert mc.request_id(b'{"id":' + b"[" * 100_000 + b"]" * 100_000 + b"}") is None
    assert mc.request_id(b'{"id":' + b"9" * 5000 + b"}") is None


def test_unread_cases_are_header_or_size_refusals():
    unread = {c.name for c in table() if c.unread}
    assert {"p_bad_pv_header", "p_body_over_256k", "au_origin_anon", "au_cookie_owner", "au_basic",
            "au_bearer_empty"} <= unread
    assert all(c.status != (200,) for c in table() if c.unread)
    import importlib
    scen = importlib.import_module("slop.scenarios.2026-11-14-mcp-wild")
    assert scen._MIX_UNREAD <= set(scen._MIX_STATUS)


def test_fault_registers_known_target():
    class Fault:
        def __init__(self, apply, targets):
            self.apply, self.targets = apply, targets
    reg = mf.register(Fault)
    assert set(reg) == {"mcp-anon-sees-token-builtins"}
    assert all(set(f.targets) <= set(mf.CHECKS) for f in reg.values())
