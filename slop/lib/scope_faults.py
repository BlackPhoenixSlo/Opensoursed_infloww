"""Write scope's break-it-once fault (service/server.py `_resolve_account_id`, which every
route and `_get_client` look up on the module at call time, so the patch is what the real
send route resolves): lib/faults.py merges `register(Fault)` into FAULTS. The check name
lives here and scenarios/2026-10-28-scoped-reads-fanout.py imports it, so a target can never
name a check that does not exist.
"""
from __future__ import annotations

C_WRITE_SCOPE = "POST send without X-Account-Id on a 2-Creator Agency → 400, 0 OF sends"


def _write_scope_falls_back_active() -> None:
    """The pre-fix resolver: a request naming no Creator falls back to the active one for
    every method, so a write with no X-Account-Id is sent as whichever Creator is active.
    Only the real resolver's `account_required` refusal is undone, by resolving that request
    as a background caller (`None`): the active account, then the same 403 ownership check."""
    import server
    from fastapi import HTTPException

    real = server._resolve_account_id

    def falls_back(request):
        try:
            return real(request)
        except HTTPException as e:
            if not (isinstance(e.detail, dict) and e.detail.get("error") == "account_required"):
                raise
            return real(None)

    server._resolve_account_id = falls_back


def register(Fault) -> dict:
    return {
        # slop/run 2026-10-28-scoped-reads-fanout --break --fault=write-scope-falls-back-active
        "write-scope-falls-back-active": Fault(_write_scope_falls_back_active, (C_WRITE_SCOPE,)),
    }
