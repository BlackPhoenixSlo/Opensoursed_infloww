"""The relay's SSE routing rule (service/events_decide.py, `wants`) break-it-once fault:
lib/faults.py merges `register(Fault)` into FAULTS. It patches the pure decide inside the relay
(events.py calls `ed.wants` / `ed.sees` through the module, so the shell routes as the patched ones say).
The check it targets is scenarios/2026-10-24-big-model-dm-flood.py's cross-Agency leak check: each
Agency owner's real /events stream ("all", clamped to its own Creators) must never get another
Agency's DM.
"""
from __future__ import annotations

LEAK = "no DM reached another Agency's /events stream"


def _wants_ignores_creator_clamp() -> None:
    """Routing ignores the subscriber's Creator clamp (`accounts`): an "all" stream sees every
    account's events, as an unclamped one does. `sees` (the replay's ring filter) drops it too, so
    a reconnect replays what the live stream would have sent: with only `wants` patched, the event
    bus's reconnects lose the leaked DMs and its "nothing dropped" goes red as noise. Scope,
    Agency-wide audiences and everything else are as shipped, so nothing is dropped and order
    holds: only a check that a stream got an event of a Creator outside its session can see it
    (bug class: a dropped allowlist filter)."""
    import events_decide as ed

    real_wants, real_sees = ed.wants, ed.sees
    ed.wants = lambda scope, accounts, agencies, event: real_wants(scope, None, agencies, event)
    ed.sees = lambda scope, accounts, account_id: real_sees(scope, None, account_id)


def register(Fault) -> dict:
    return {
        # slop/run big-model --no-ui --break --fault=sse-wants-ignores-creator-clamp
        "sse-wants-ignores-creator-clamp": Fault(_wants_ignores_creator_clamp, (LEAK,)),
    }
