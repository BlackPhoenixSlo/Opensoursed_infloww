"""MCP wild's break-it-once fault (scenarios/2026-11-14-mcp-wild.py): lib/faults.py merges `register(Fault)` into
FAULTS. The check names live here and the scenario imports them, so a target can never name a check that does not
exist.
"""
from __future__ import annotations

C_5XX = "no_5xx"
C_WELLFORMED = "jsonrpc_errors_wellformed"
C_NO_SEND = "no_send_ever"
C_CROSS = "no_cross_agency"
C_SEND_LISTED = "send_tools_never_listed"
C_ANON3 = "anonymous_only_three_tools"
C_REVOKED = "revoked_token_dead"
C_ORIGIN = "origin_refused"
C_COOKIE = "cookie_refused"
C_SCOPE = "token_scope_403"
C_EMPLOYEE = "employee_no_token"
C_PLAIN = "errors_are_plain"
C_REPORT_FILE = "report_file_owner_only"
C_STUCK = "no_stuck_plans"
C_AS_SPECIFIED = "cases_answer_as_specified"
CHECKS = (C_5XX, C_WELLFORMED, C_NO_SEND, C_CROSS, C_SEND_LISTED, C_ANON3, C_REVOKED, C_ORIGIN, C_COOKIE, C_SCOPE,
          C_EMPLOYEE, C_PLAIN, C_REPORT_FILE, C_STUCK, C_AS_SPECIFIED)


def _anon_sees_token_builtins() -> None:
    """The no-credential surface lists every builtin (bug class: the `token` filter on BUILTINS dropped), so an
    anonymous tools/list shows propose_plan and plan_status; their calls then answer 401/404 with no connect link.
    `mcp_api._dispatch` / `_call` look `_builtins` up at call time. Only anonymous_only_three_tools goes red."""
    import mcp_api

    mcp_api._builtins = lambda token: list(mcp_api.BUILTINS.values())


def register(Fault) -> dict:
    return {
        # slop/run 2026-11-14-mcp-wild --break (the scenario's FAULT)
        "mcp-anon-sees-token-builtins": Fault(_anon_sees_token_builtins, (C_ANON3,)),
    }
