from __future__ import annotations

C_WRITE_SCOPE = "POST send without X-Account-Id on a 2-Creator Agency → 400, 0 OF sends"


def _write_scope_falls_back_active() -> None:
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
        "write-scope-falls-back-active": Fault(_write_scope_falls_back_active, (C_WRITE_SCOPE,)),
    }
