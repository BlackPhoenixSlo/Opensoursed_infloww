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
ECHO = ("no echoed bubble reached OF: a reply that repeats the fan's DM is dropped and counted "
        "(each echo reply's other bubble still sent, one distinct bubble per turn)")


def _wcfi_skiplist_ignored() -> None:
    from dataclasses import replace

    from automations import wcfi_decide as wd

    real = wd.decide

    def decide(snap):
        v = real(snap)
        if isinstance(v, wd.Skip) and v.reason == "listed":
            return real(replace(snap, listed=False))
        return v

    wd.decide = decide


def _wcfi_turn_sent_twice() -> None:
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


def _reply_shape_echo_kept() -> None:
    from automations import _reply_shape

    _reply_shape._looks_like_echo = lambda _part, _echo_of: False


def register(Fault) -> dict:
    return {
        "wcfi-skiplist-ignored": Fault(_wcfi_skiplist_ignored, (SKIPLISTED,)),
        "wcfi-turn-sent-twice": Fault(_wcfi_turn_sent_twice, (DOUBLE,)),
        "reply-shape-echo-kept": Fault(_reply_shape_echo_kept, (ECHO,)),
    }
