#!/usr/bin/env python3
"""
`fans.custom_fields` — the shared per-fan state blob, and the three accessors that
are now the ONLY way into it. Durable regression suite (plain-assert, no pytest —
repo convention).

One JSON column holds every automation's per-fan scratch state, namespaced by a
leading underscore: `_hot_teaser`, `_typo_fix`, `_image_reply`, `_tip_request`,
`_bot_dare`. Five modules used to hand-roll the same read-modify-write against it
— an identical `_load_custom_fields` copy-pasted into tip_reward and tip_request,
and a fresh load/save pair per feature in ai_chatter.

That duplication is not cosmetic: every writer reads the WHOLE blob, edits its own
key and writes the whole thing back, so one writer getting it subtly wrong wipes a
sibling automation's state. These cases pin the behaviour that makes that safe.

Cases:
  case_read_is_pure_and_type_guarded:
      `fan_state` takes the row the sweep already loaded — no DB — and treats a
      slot holding a non-dict (corruption from an older writer) as unset rather
      than handing back a str for the caller to `.get()` on.
  case_write_preserves_siblings:
      the headline invariant. Writing `_bot_dare` must not disturb `_hot_teaser`,
      and clearing a slot must remove only that one.
  case_write_merges_against_the_stored_row:
      `set_fan_state` re-reads inside its own session, so a sibling key written
      AFTER the caller loaded its stale `Fan` still survives — the concurrent-
      automation case the hand-rolled versions got wrong.
  case_in_session_write_is_atomic_with_its_caller:
      `put_fan_state` writes into the CALLER's transaction, so a stamp and the
      rows it belongs with commit (or roll back) together. Senders stamp a
      cooldown alongside the VaultSend rows for what they just sent; two
      transactions could credit a send with no cooldown.
  case_missing_fan_never_raises:
      a stamp is never worth raising into an automation's send path.

Run: cd service/tests && \
  PYTHONPATH=$(cd .. && pwd) ../../venv/bin/python test_fan_state.py
Exit 0 = all cases passed. Temp DB bound by _harness (never prod).
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import json  # noqa: E402

from sqlalchemy import select  # noqa: E402

from automations.fan_state import fan_state, put_fan_state, set_fan_state  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Fan, VaultSend  # noqa: E402


async def _seed(aid: str, fan_id: int = 1, blob: dict | None = None) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        s.add(Fan(account_id=aid, fan_id=fan_id,
                  custom_fields=json.dumps(blob) if blob is not None else None))
        await s.commit()


async def _blob(aid: str, fan_id: int = 1) -> dict:
    async with get_session() as s:
        raw = (await s.execute(select(Fan.custom_fields).where(
            Fan.account_id == aid, Fan.fan_id == fan_id))).scalar_one()
    return json.loads(raw) if raw else {}


async def case_read_is_pure_and_type_guarded():
    detached = Fan(account_id="x", fan_id=1, custom_fields=json.dumps({
        "_hot_teaser": {"rung": 3},
        "_junk": "a string where a dict belongs",
        "_alsojunk": [1, 2],
    }))
    assert fan_state(detached, "_hot_teaser") == {"rung": 3}
    assert fan_state(detached, "_never_set") == {}
    # A non-dict slot is corruption from an older writer — "unset", not a str.
    assert fan_state(detached, "_junk") == {}, "a str slot must not escape as a str"
    assert fan_state(detached, "_alsojunk") == {}
    # Absent / NULL / unparseable rows all read as empty rather than raising.
    assert fan_state(None, "_x") == {}
    assert fan_state(Fan(account_id="x", fan_id=2), "_x") == {}
    assert fan_state(Fan(account_id="x", fan_id=3, custom_fields="{not json"), "_x") == {}


async def case_write_preserves_siblings():
    aid = "siblings"
    await _seed(aid, blob={"_hot_teaser": {"rung": 2, "at": "yesterday"},
                           "_typo_fix": {"since": 9}})

    await set_fan_state(aid, 1, "_bot_dare", {"at": "now"})

    blob = await _blob(aid)
    assert blob["_hot_teaser"] == {"rung": 2, "at": "yesterday"}, \
        f"a sibling automation's state was clobbered: {blob}"
    assert blob["_typo_fix"] == {"since": 9}, blob
    assert blob["_bot_dare"] == {"at": "now"}, blob

    # Clearing removes exactly one slot.
    await set_fan_state(aid, 1, "_hot_teaser", None)
    blob = await _blob(aid)
    assert "_hot_teaser" not in blob, blob
    assert blob["_typo_fix"] == {"since": 9} and blob["_bot_dare"] == {"at": "now"}, blob


async def case_write_merges_against_the_stored_row():
    """The concurrent-automation case: our caller's `Fan` is STALE."""
    aid = "stale"
    await _seed(aid, blob={"_typo_fix": {"since": 1}})

    # Whoever called us loaded the fan here…
    async with get_session() as s:
        stale = (await s.execute(select(Fan).where(
            Fan.account_id == aid, Fan.fan_id == 1))).scalar_one()
        assert fan_state(stale, "_hot_teaser") == {}

    # …and another automation stamped a DIFFERENT key in between.
    await set_fan_state(aid, 1, "_hot_teaser", {"rung": 5})
    # Now we stamp ours. A writer that serialized its own stale copy would drop it.
    await set_fan_state(aid, 1, "_bot_dare", {"at": "now"})

    blob = await _blob(aid)
    assert blob.get("_hot_teaser") == {"rung": 5}, \
        f"a key written after our caller's read was lost: {blob}"
    assert blob.get("_bot_dare") == {"at": "now"}, blob
    assert blob.get("_typo_fix") == {"since": 1}, blob


async def case_in_session_write_is_atomic_with_its_caller():
    aid = "atomic"
    await _seed(aid, blob={"_typo_fix": {"since": 4}})

    # The real shape: stamp the cooldown in the SAME transaction as the rows that
    # record what was sent, so the two can never disagree.
    async with get_session() as s:
        s.add(VaultSend(account_id=aid, fan_id=1, media_id=77, price_cents=0))
        fan = await s.get(Fan, (aid, 1))
        put_fan_state(fan, "_image_reply", {"at": "now"})
        await s.commit()

    blob = await _blob(aid)
    assert blob["_image_reply"] == {"at": "now"}, blob
    assert blob["_typo_fix"] == {"since": 4}, f"sibling lost on the in-session path: {blob}"
    async with get_session() as s:
        n = len((await s.execute(select(VaultSend.media_id).where(
            VaultSend.account_id == aid))).scalars().all())
    assert n == 1, "the send rows and the stamp must land together"

    # A rollback takes BOTH — the point of sharing the transaction.
    async with get_session() as s:
        s.add(VaultSend(account_id=aid, fan_id=1, media_id=88, price_cents=0))
        fan = await s.get(Fan, (aid, 1))
        put_fan_state(fan, "_image_reply", {"at": "rolled-back"})
        await s.rollback()
    blob = await _blob(aid)
    assert blob["_image_reply"] == {"at": "now"}, \
        f"the stamp survived a rolled-back send: {blob}"


async def case_missing_fan_never_raises():
    aid = "nofan"
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        await s.commit()
    await set_fan_state(aid, 999, "_bot_dare", {"at": "now"})   # must not raise


_harness.run(
    case_read_is_pure_and_type_guarded,
    case_write_preserves_siblings,
    case_write_merges_against_the_stored_row,
    case_in_session_write_is_atomic_with_its_caller,
    case_missing_fan_never_raises,
)
