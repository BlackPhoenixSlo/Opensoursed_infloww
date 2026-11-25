from __future__ import annotations

LEAK = "no DM reached another Agency's /events stream"


def _wants_ignores_creator_clamp() -> None:
    import events_decide as ed

    real_wants, real_sees = ed.wants, ed.sees
    ed.wants = lambda scope, accounts, agencies, event: real_wants(scope, None, agencies, event)
    ed.sees = lambda scope, accounts, account_id: real_sees(scope, None, account_id)


def register(Fault) -> dict:
    return {
        "sse-wants-ignores-creator-clamp": Fault(_wants_ignores_creator_clamp, (LEAK,)),
    }
