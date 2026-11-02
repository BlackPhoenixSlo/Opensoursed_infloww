"""The welcome chatter's break-it-once faults (lib/faults.py merges `register(Fault)` into
FAULTS). Both patch `automations.welcome_chatter_for_info` (wcfi) inside the throwaway
relay, never service/:

  wcfi-skiplist-ignored   scenarios/2026-10-30-welcome-chatter-walk (its FAULT)
  wcfi-turn-sent-twice    the same scenario, --break --fault=wcfi-turn-sent-twice

The flow's check names live here and its scenario imports them, so a target can never name
a check that does not exist.
"""
from __future__ import annotations

TURNS = ("one-turn-per-reply: every DM of an open fan (we spoke last, or his own line was "
         "still unanswered) gets exactly one turn: >= 1 bubble at OF before his next DM, "
         "turn_counter +1 per DM, and the runs' replies_sent = the turns taken")
SKIPLISTED = ("no-send-to-skiplisted: a blacklisted, skip-listed, muted-creator or promo-spam fan "
              "who DMs gets nothing (no OF send, no outbound row)")
DOUBLE = ("no-double-send: no bubble reached OF twice (same Creator, fan and text), and no body "
          "repeats in a fan's new outbound rows")
COUNTS = ("counts: fake OF's sends = new welcome_chatter_for_info outbound rows (same ids), none to a "
          "fan who did not DM, the runs report no errors")
LANDED = "every fan DM was accepted and is a messages row in its thread"


def _wcfi_skiplist_ignored() -> None:
    """wcfi's verdict forgets the stop-lists: a `Skip("listed")` (blacklist / skip_list) is
    re-decided as if he were on neither. Exercised by the scenario's BLACKLISTED fans only:
    W7 wakes the lane for them and they get a reply; its skip-listed fans never reach
    run() (W7 wakes no lane for them). Everything around the verdict (reads, sends,
    counters) is the product's."""
    from dataclasses import replace

    from automations import wcfi_decide as wd

    real = wd.decide

    def decide(snap):
        v = real(snap)
        if isinstance(v, wd.Skip) and v.reason == "listed":
            return real(replace(snap, listed=False))
        return v

    wd.decide = decide  # wcfi.run looks it up per fan (`wcfi_decide.decide`)


def _wcfi_turn_sent_twice() -> None:
    """The turn's bubble loop runs twice: after wcfi persists a text bubble
    (`write_outbound_attribution`, looked up per call in wcfi's module), the same bubble
    goes to OF again through the run's client seam (`automation_executor._make_client`)
    and is persisted under OF's new id. Rows and OF agree (nothing dropped), the turn is
    counted once, so only the double-send check can see it. Declared: the hook wraps wcfi's
    persist call, as no wcfi-only send function exists (the bubble send is inline)."""
    import asyncio
    from datetime import datetime

    import automation_executor as ax
    from automations import welcome_chatter_for_info as wcfi

    real = wcfi.write_outbound_attribution

    async def twice(**kw):
        out = await real(**kw)
        if kw.get("automation_kind") == wcfi._PURPOSE and kw.get("body") and not kw.get("price_cents"):
            client = await asyncio.to_thread(ax._make_client, kw["account_id"])
            res = await asyncio.to_thread(client.send_message, kw["fan_id"], kw["body"])
            await real(**{**kw, "message_id": int(res["id"]),
                          "created_at": ax._parse_iso(res.get("createdAt")) or datetime.utcnow()})
        return out

    wcfi.write_outbound_attribution = twice


def register(Fault) -> dict:
    return {
        "wcfi-skiplist-ignored": Fault(_wcfi_skiplist_ignored, (SKIPLISTED,)),
        "wcfi-turn-sent-twice": Fault(_wcfi_turn_sent_twice, (DOUBLE,)),
    }
