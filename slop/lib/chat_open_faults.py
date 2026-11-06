"""The chat open's break-it-once fault (service/chat_screen_api.py, checked in
scenarios/2026-11-05-slow-connections.py's thread flow): lib/faults.py merges `register(Fault)` into FAULTS. The
check names live here and the scenario imports them, so a target can never name a check that does not exist.
"""
from __future__ import annotations

THREAD_ONCE = "thread: each read once per open (no route GET twice: attribution, fan-history)"
THREAD_BUNDLE = "thread: the open's local reads in one /admin/screens/chat, none per route"


def _chat_bundle_drops_attribution() -> None:
    """The chat open's bundle never reads attribution (`chat_screen_api._run`, its module global, without that
    read): the thread's "Sent by" map goes out per route again, bare then `since_id`."""
    import chat_screen_api
    real = chat_screen_api._run

    async def without(outer, reads, deadline_at):
        return await real(outer, [r for r in reads if r.name != "attribution"], deadline_at)

    chat_screen_api._run = without


def register(Fault) -> dict:
    # slop/run 2026-11-05-slow-connections --net=jp --scale=small --break --fault=chat-bundle-drops-attribution
    #   --baseline=<green>: the thread's bare and since_id attribution reads go out on their own (two GETs of one
    #   route, neither in the bundle). Not targets: the bubbles, budgets and request caps (one more parallel read).
    return {"chat-bundle-drops-attribution": Fault(_chat_bundle_drops_attribution, (THREAD_ONCE, THREAD_BUNDLE))}
