#!/usr/bin/env python3
"""
Ingest-side placeholder reconcile — `attribution.adopt_thread_placeholders`.

The gap this closes: `write_mass_optimistic_rows` stamps a 5e15-band row at send
time (OF's queue endpoint returns no per-fan ids and the WS pump skips outbound).
`send_mass_message` drops that row the moment OF echoes an id inline — but
`ppv_send` and every list/online audience get NO echo, so the real row only
arrives hours later on the scrape and nothing ever removed the placeholder.
Observed in prod 2026-07-25: 15,341 placeholder rows in 5 days, of which 1,448
(9.4%) had a real twin ingested — those threads rendered the PPV twice and the
real row (no `automation_kind`) read as a HUMAN send, inflating creator-typed
counts. The other 90% are threads never ingested, where the stub is the ONLY
record; that 9.4% hit rate is why the reconcile is per-THREAD (one indexed seek
that usually returns empty) rather than per-message.

  case_scrape_adopts_placeholder:
      The scrape's real outbound row inherits automation_kind / mass_run_id /
      sent_by_employee_id and the placeholder is gone. One row, fully attributed.
  case_price_recovered_when_of_reports_zero:
      OF omits the price on some scraped PPV rows; the placeholder's price is
      adopted so the sale keeps its value. A real non-zero price is NEVER
      overwritten.
  case_nearest_placeholder_wins:
      The same caption sent to one fan twice leaves two placeholders — the real
      row adopts the one closest in time, and only that one is deleted.
  case_unrelated_bodies_untouched:
      A different caption, and an inbound-only twin, leave every placeholder alone.
  case_two_placeholders_never_share_one_real_row:
      Two same-caption stubs with only ONE real row: exactly one is folded in.
  case_bad_timestamp_never_wins_nearest:
      A stub with an unusable created_at must LOSE the nearest-match, not win it
      (the first cut's `else 0` made it always win).
  case_ledger_tip_band_is_out_of_range:
      6e15 ledger-tip rows are permanent synthetic history — never in delete range.
  case_of_br_echo_adopts:
      THE bug this file could not fail on: every body here was one line, so exact
      equality always worked. We store `\n`; OF echoes the same caption back with
      `<br />`. Multi-line captions never adopted — 161k live stubs, every PPV in
      the thread twice, every real row reading as a HUMAN send. Also the one case
      that catches an implementer who changes only the SQL gate (or only the
      Python one) — either alone is a no-op.
  case_two_normalized_pairs_do_not_cross_claim:
      Two stubs and two real rows on the same normalized key: each takes its own
      nearest, nobody is double-claimed, nothing is left over.
  case_second_pass_adopts_nothing:
      Adoption runs on EVERY ingest of the thread and the second pass must be a
      no-op. NOTE this proves only "the delete stuck" — the stub is gone before
      any guard runs, so it passes with the cross-invocation guard removed. The
      guard's real coverage is case_a_real_row_from_another_run_is_not_reclaimed.
  case_empty_normalized_key_never_pairs:
      `<photo>` and `<video>` both normalize to "" — folding them into one bucket
      would let an unrelated stub adopt an unrelated send.
  case_transaction_is_repointed_not_orphaned:
      A purchase links straight to the synthetic id. Deleting underneath it drops
      the money into the revenue view's orphan branch with no way back, so the
      ledger row moves first — and an adoption that CANNOT move it is refused.
  case_chat_pointer_follows_the_adopted_row:
      `chats.last_message_id` holds the stub id. Both ingest updaters advance on
      numeric-id monotonicity and a real OF id (~1.1e13) can never beat 5e15, so
      a chat left pointing at a deleted stub is frozen forever.
  case_a_refused_pair_fences_the_contested_row:
      The refusal above only holds if the row it refused is taken OFF the table.
      Otherwise the next stub adopts it and gets deleted — the exact loss the
      refusal exists to prevent, one iteration later.
  case_a_refused_stub_does_not_fall_through_to_a_farther_row:
      The refusal is STUB-scoped as well as row-scoped. A stub whose ledger row
      could not move must not quietly fold into the next-nearest send instead —
      that repoints the purchase onto the wrong message and deletes the evidence.
  case_stubs_months_apart_each_adopt_their_own:
      The read is per-stub ranges OR'd together, not one span from the oldest stub
      to the newest. Correctness half of that: two sends two months apart each
      pair, and the same caption sitting between them pairs with neither.
  case_a_real_row_from_another_run_is_not_reclaimed:
      `claimed`/`used` live for ONE invocation. A row already stamped by another
      run must not let a second stub be deleted against it.

Run: ./venv/bin/python service/tests/test_placeholder_adopt.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from attribution import (  # noqa: E402
    _MASS_PLACEHOLDER_BASE,
    adopt_thread_placeholders,
)
from db.engine import get_session  # noqa: E402
from db.models import Account, Employee, MassRun, Message  # noqa: E402

ACCT = "777"
FAN = 424242
CAPTION = "filmed somethin earlier n immediately thought of u"
T0 = datetime(2026, 7, 25, 4, 50, 0)
# mass_run_id / sent_by_employee_id are real FKs — the rows must exist or the
# placeholder insert fails before the reconcile is ever exercised.
RUNS = (2709, 2598, 2599, 3000, 3001, 4000, 4001, 4002, 4003,
        5000, 5001, 5002, 5003, 5004, 5005, 5006, 5007, 5008,
        5009, 5010, 5011, 5012, 5013, 5014)


async def _seed_account() -> None:
    async with get_session() as s:
        if await s.get(Account, ACCT) is None:
            s.add(Account(id=ACCT, nickname="ppv-test"))
        if await s.get(Employee, 2) is None:
            s.add(Employee(id=2, display_name="Automation"))
    async with get_session() as s:
        for rid in RUNS:
            if await s.get(MassRun, rid) is None:
                s.add(MassRun(id=rid, account_id=ACCT, recipient_count=1))


async def _add(message_id: int, *, direction="out", body=CAPTION, kind=None,
               run_id=None, emp=None, price=0, at=T0, fan=FAN) -> None:
    async with get_session() as s:
        s.add(Message(
            account_id=ACCT, fan_id=fan, message_id=message_id, direction=direction,
            sender_name="", body=body, media_ids="[]", media_count=0,
            price_cents=price, is_tip=False, is_unsent=False, is_promise=False,
            automation_kind=kind, mass_run_id=run_id, sent_by_employee_id=emp,
            created_at=at,
        ))


async def _adopt(fan=FAN) -> int:
    async with get_session() as s:
        got = await adopt_thread_placeholders(s, account_id=ACCT, fan_id=fan)
    return got


async def _rows(fan=FAN) -> list[Message]:
    from sqlalchemy import select
    async with get_session() as s:
        return list((await s.execute(
            select(Message).where(Message.account_id == ACCT, Message.fan_id == fan)
            .order_by(Message.message_id)
        )).scalars().all())


async def case_scrape_adopts_placeholder() -> None:
    fan = FAN
    await _add(_MASS_PLACEHOLDER_BASE + 2709, kind="ppv_send", run_id=2709, emp=2,
               price=1499, at=T0, fan=fan)
    await _add(10523500704836, at=T0 + timedelta(seconds=13), price=1499, fan=fan)

    assert await _adopt(fan) == 1

    rows = await _rows(fan)
    assert len(rows) == 1, [r.message_id for r in rows]
    real = rows[0]
    assert real.message_id == 10523500704836
    assert real.automation_kind == "ppv_send", real.automation_kind
    assert real.mass_run_id == 2709
    assert real.sent_by_employee_id == 2
    print("[ok] case_scrape_adopts_placeholder")


async def case_price_recovered_when_of_reports_zero() -> None:
    fan = FAN + 1
    await _add(_MASS_PLACEHOLDER_BASE + 2598, kind="ppv_send", run_id=2598, emp=2,
               price=5999, at=T0, fan=fan)
    await _add(10492570037225, at=T0 + timedelta(seconds=11), price=0, fan=fan)
    assert await _adopt(fan) == 1
    rows = await _rows(fan)
    assert len(rows) == 1
    assert rows[0].price_cents == 5999, rows[0].price_cents

    # ...but a real price OF DID report is authoritative and must survive.
    fan2 = FAN + 2
    await _add(_MASS_PLACEHOLDER_BASE + 2599, kind="ppv_send", run_id=2599, emp=2,
               price=5999, at=T0, fan=fan2)
    await _add(10492570037226, at=T0 + timedelta(seconds=11), price=899, fan=fan2)
    assert await _adopt(fan2) == 1
    rows2 = await _rows(fan2)
    assert rows2[0].price_cents == 899, rows2[0].price_cents
    print("[ok] case_price_recovered_when_of_reports_zero")


async def case_nearest_placeholder_wins() -> None:
    fan = FAN + 3
    far = _MASS_PLACEHOLDER_BASE + 3000
    near = _MASS_PLACEHOLDER_BASE + 3001
    await _add(far, kind="ppv_send", run_id=3000, emp=2, at=T0, fan=fan)
    await _add(near, kind="ppv_send", run_id=3001, emp=2,
               at=T0 + timedelta(hours=6), fan=fan)
    # real row lands right after the SECOND send
    await _add(10600000000001, at=T0 + timedelta(hours=6, seconds=10), fan=fan)

    assert await _adopt(fan) == 1
    ids = [r.message_id for r in await _rows(fan)]
    assert near not in ids, ids          # the near placeholder was folded in
    assert far in ids, ids               # the older one is untouched
    real = [r for r in await _rows(fan) if r.message_id == 10600000000001][0]
    assert real.mass_run_id == 3001, real.mass_run_id
    print("[ok] case_nearest_placeholder_wins")


async def case_unrelated_bodies_untouched() -> None:
    fan = FAN + 4
    ph = _MASS_PLACEHOLDER_BASE + 4000
    await _add(ph, kind="ppv_send", run_id=4000, emp=2, at=T0, fan=fan)
    # different caption → no pair
    await _add(10700000000001, body="a totally different line", at=T0, fan=fan)
    # an INBOUND row with the same body is not a send of ours and must not pair
    await _add(10700000000002, direction="in", at=T0, fan=fan)
    assert await _adopt(fan) == 0
    assert ph in [r.message_id for r in await _rows(fan)]
    print("[ok] case_unrelated_bodies_untouched")


async def case_two_placeholders_never_share_one_real_row() -> None:
    fan = FAN + 5
    a, b = _MASS_PLACEHOLDER_BASE + 4001, _MASS_PLACEHOLDER_BASE + 4002
    await _add(a, kind="ppv_send", run_id=4001, emp=2, at=T0, fan=fan)
    await _add(b, kind="ppv_send", run_id=4002, emp=2,
               at=T0 + timedelta(hours=3), fan=fan)
    await _add(10800000000001, at=T0 + timedelta(seconds=5), fan=fan)  # ONE real row

    assert await _adopt(fan) == 1
    ids = [r.message_id for r in await _rows(fan)]
    assert a not in ids, ids       # nearest one folded in
    assert b in ids, ids           # the other keeps its stub, not double-claimed
    print("[ok] case_two_placeholders_never_share_one_real_row")


async def case_bad_timestamp_never_wins_nearest() -> None:
    """created_at is NOT NULL, so this guards the ORDERING RULE directly: the
    first cut scored an unusable timestamp as `0` — the minimum — so a corrupt
    row always won the nearest-match. It must score as `inf` and always lose."""
    from attribution import _seconds_apart

    assert _seconds_apart(T0, T0 + timedelta(seconds=4)) == 4.0
    assert _seconds_apart(None, T0) == float("inf")
    assert _seconds_apart(T0, None) == float("inf")
    assert _seconds_apart(None, None) == float("inf")
    # ...and it loses to any real distance, however large
    assert _seconds_apart(None, T0) > _seconds_apart(T0, T0 + timedelta(days=365))
    print("[ok] case_bad_timestamp_never_wins_nearest")


async def case_ledger_tip_band_is_out_of_range() -> None:
    fan = FAN + 7
    tip = 6_000_000_000_000_001        # transaction_ingest._TIP_MSG_ID_BASE band
    await _add(tip, kind=None, at=T0, fan=fan)
    await _add(11000000000001, at=T0, fan=fan)
    assert await _adopt(fan) == 0
    assert tip in [r.message_id for r in await _rows(fan)], "ledger tip was deleted"
    print("[ok] case_ledger_tip_band_is_out_of_range")


async def case_a_stale_placeholder_cannot_claim_an_unrelated_send() -> None:
    """The pairing was distance-ORDERED but not distance-LIMITED.

    A placeholder and the row it stands for are seconds to minutes apart — the stub
    is written as the send goes out, the real row lands on the next ingest. But the
    same caption legitimately goes to the same fan again, weeks later. When a stub's
    OWN real row never ingested, the greedy pass had nothing nearer to prefer, so it
    adopted whatever same-caption row existed at any distance: that later send was
    stamped with a month-old mass_run_id and automation_kind, and the stub deleted,
    so the mis-attribution could never be traced back."""
    fan = FAN + 11
    stub = 5_000_000_000_002_709
    later = 11000000000077
    await _add(stub, kind="mass_ppv", run_id=4003, emp=2, at=T0, fan=fan)
    # His real row never arrived. This one is the SAME caption, 30 days on.
    await _add(later, kind=None, at=T0 + timedelta(days=30), fan=fan)

    assert await _adopt(fan) == 0, "a month-old stub must not adopt an unrelated send"
    rows = {r.message_id: r for r in await _rows(fan)}
    assert later in rows, "the real row was consumed"
    assert rows[later].mass_run_id is None, (
        f"unrelated send stamped with a stale run: {rows[later].mass_run_id}")
    assert rows[later].automation_kind is None, (
        f"unrelated send stamped with a stale kind: {rows[later].automation_kind}")
    assert stub in rows, "the stub was deleted despite adopting nothing"
    print("[ok] case_a_stale_placeholder_cannot_claim_an_unrelated_send")


async def case_a_slow_ingest_still_adopts() -> None:
    """The bound must forgive a stalled ingest, or it trades a rare wrong pairing
    for a common missed one. Four hours late is still the same send."""
    fan = FAN + 12
    stub = 5_000_000_000_002_598
    real = 11000000000078
    await _add(stub, kind="mass_ppv", run_id=4002, emp=2, at=T0, fan=fan)
    await _add(real, kind=None, at=T0 + timedelta(hours=4), fan=fan)

    assert await _adopt(fan) == 1, "a 4h-late ingest is still the same send"
    rows = {r.message_id: r for r in await _rows(fan)}
    assert rows[real].mass_run_id == 4002, rows[real].mass_run_id
    assert stub not in rows, "the stub should be gone once adopted"
    print("[ok] case_a_slow_ingest_still_adopts")



# ── The <br /> echo, and everything that has to move with the delete ──────────

# What we stored (plain newlines) vs what OF echoes back for the SAME send. The
# byte-equality key this shipped with could never match them.
MULTILINE = "couldnt keep the gingham up\n\nim doin somethin a lil crazy tonight"
OF_ECHO = ("couldnt keep the gingham up<br />\n<br />\n"
           "im doin somethin a lil crazy tonight")


async def case_of_br_echo_adopts() -> None:
    fan = FAN + 20
    stub = _MASS_PLACEHOLDER_BASE + 5000
    real = 11165218112525
    await _add(stub, body=MULTILINE, kind="ppv_send", run_id=5000, emp=2,
               price=1499, at=T0, fan=fan)
    await _add(real, body=OF_ECHO, at=T0 + timedelta(seconds=17), fan=fan)

    assert await _adopt(fan) == 1, "the <br /> echo of our own caption must pair"
    rows = await _rows(fan)
    assert len(rows) == 1, [r.message_id for r in rows]
    assert rows[0].message_id == real
    assert rows[0].automation_kind == "ppv_send", rows[0].automation_kind
    assert rows[0].mass_run_id == 5000, rows[0].mass_run_id
    # OF's body is authoritative — we tag the row, we do not rewrite it.
    assert rows[0].body == OF_ECHO, rows[0].body
    print("[ok] case_of_br_echo_adopts")


async def case_two_normalized_pairs_do_not_cross_claim() -> None:
    fan = FAN + 21
    s1 = _MASS_PLACEHOLDER_BASE + 5001
    s2 = _MASS_PLACEHOLDER_BASE + 5002
    r1, r2 = 11165218112601, 11165218112602
    await _add(s1, body=MULTILINE, kind="ppv_send", run_id=5001, emp=2, at=T0, fan=fan)
    await _add(r1, body=OF_ECHO, at=T0 + timedelta(seconds=9), fan=fan)
    await _add(s2, body=MULTILINE, kind="ppv_send", run_id=5002, emp=2,
               at=T0 + timedelta(hours=5), fan=fan)
    await _add(r2, body=OF_ECHO, at=T0 + timedelta(hours=5, seconds=9), fan=fan)

    assert await _adopt(fan) == 2, "both sends pair, each with its own row"
    rows = {r.message_id: r for r in await _rows(fan)}
    assert set(rows) == {r1, r2}, sorted(rows)
    assert rows[r1].mass_run_id == 5001, rows[r1].mass_run_id
    assert rows[r2].mass_run_id == 5002, rows[r2].mass_run_id
    print("[ok] case_two_normalized_pairs_do_not_cross_claim")


async def case_second_pass_adopts_nothing() -> None:
    fan = FAN + 22
    stub = _MASS_PLACEHOLDER_BASE + 5003
    real = 11165218112603
    await _add(stub, body=MULTILINE, kind="ppv_send", run_id=5003, emp=2, at=T0, fan=fan)
    await _add(real, body=OF_ECHO, at=T0 + timedelta(seconds=9), fan=fan)
    assert await _adopt(fan) == 1
    assert await _adopt(fan) == 0, "re-ingest must not re-claim an adopted row"
    assert [r.message_id for r in await _rows(fan)] == [real]
    print("[ok] case_second_pass_adopts_nothing")


async def case_empty_normalized_key_never_pairs() -> None:
    """A media-only send strips to nothing. If "" were a key, every one of them
    on the account would land in the same bucket and adopt each other."""
    from attribution import _norm_body
    assert _norm_body("<photo>") == ""
    assert _norm_body("<video>") == ""
    assert _norm_body(None) == "" and _norm_body("") == ""
    assert _norm_body(MULTILINE) == _norm_body(OF_ECHO) != ""

    fan = FAN + 23
    stub = _MASS_PLACEHOLDER_BASE + 5004
    await _add(stub, body="<photo>", kind="ppv_send", run_id=5004, emp=2, at=T0, fan=fan)
    await _add(11165218112604, body="<video>", at=T0 + timedelta(seconds=4), fan=fan)
    assert await _adopt(fan) == 0, "media-only bodies must never pair"
    assert stub in [r.message_id for r in await _rows(fan)]
    print("[ok] case_empty_normalized_key_never_pairs")


async def _add_tx(fan: int, message_id: int, cents: int, *, at=T0) -> int:
    from db.models import Transaction
    async with get_session() as s:
        tx = Transaction(account_id=ACCT, fan_id=fan, kind="ppv_message",
                         message_id=message_id, amount_cents=cents,
                         currency="USD", occurred_at=at)
        s.add(tx)
        await s.flush()
        return int(tx.id)


async def _tx_msg_id(tx_id: int) -> int | None:
    from db.models import Transaction
    async with get_session() as s:
        return (await s.get(Transaction, tx_id)).message_id


async def case_transaction_is_repointed_not_orphaned() -> None:
    fan = FAN + 24
    stub = _MASS_PLACEHOLDER_BASE + 5005
    real = 11165218112605
    await _add(stub, body=MULTILINE, kind="ppv_send", run_id=5005, emp=2,
               price=2499, at=T0, fan=fan)
    await _add(real, body=OF_ECHO, at=T0 + timedelta(seconds=9), fan=fan)
    # …and the stub knows about the unlock the scraped row does not.
    async with get_session() as s:
        ph = await s.get(Message, (ACCT, fan, stub))
        ph.is_paid = True
        ph.purchased_at = T0 + timedelta(minutes=4)
    tx = await _add_tx(fan, stub, 2499)

    assert await _adopt(fan) == 1
    assert await _tx_msg_id(tx) == real, "the purchase was orphaned by the delete"
    rows = {r.message_id: r for r in await _rows(fan)}
    assert rows[real].is_paid is True, rows[real].is_paid
    assert rows[real].purchased_at == T0 + timedelta(minutes=4)
    assert rows[real].price_cents == 2499, rows[real].price_cents

    # Collision: the REAL row already carries its own ledger row, so there is no
    # non-destructive move. Keep today's duplicate rather than lose an amount.
    fan2 = FAN + 25
    stub2 = _MASS_PLACEHOLDER_BASE + 5006
    real2 = 11165218112606
    await _add(stub2, body=MULTILINE, kind="ppv_send", run_id=5006, emp=2, at=T0, fan=fan2)
    await _add(real2, body=OF_ECHO, at=T0 + timedelta(seconds=9), fan=fan2)
    tx_stub = await _add_tx(fan2, stub2, 1000)
    tx_real = await _add_tx(fan2, real2, 1000)

    assert await _adopt(fan2) == 0, "an unresolvable ledger collision must refuse"
    assert stub2 in [r.message_id for r in await _rows(fan2)]
    assert await _tx_msg_id(tx_stub) == stub2
    assert await _tx_msg_id(tx_real) == real2
    print("[ok] case_transaction_is_repointed_not_orphaned")


async def case_a_refused_pair_fences_the_contested_row() -> None:
    fan = FAN + 28
    s1 = _MASS_PLACEHOLDER_BASE + 5009
    s2 = _MASS_PLACEHOLDER_BASE + 5010
    real = 11165218112609
    # ONE real row, and it already carries its own ledger row — so nothing may
    # be deleted against it. Two stubs are in range; the nearer one is refused.
    await _add(real, body=OF_ECHO, at=T0 + timedelta(seconds=9), fan=fan)
    await _add(s1, body=MULTILINE, kind="ppv_send", run_id=5009, emp=2, at=T0, fan=fan)
    await _add(s2, body=MULTILINE, kind="ppv_send", run_id=5010, emp=2,
               at=T0 - timedelta(minutes=30), fan=fan)
    await _add_tx(fan, real, 1000)
    await _add_tx(fan, s1, 1000)

    assert await _adopt(fan) == 0, "a contested row must take neither stub"
    ids = [r.message_id for r in await _rows(fan)]
    assert s1 in ids and s2 in ids, (
        f"a stub was deleted against a contested row: {ids}")
    print("[ok] case_a_refused_pair_fences_the_contested_row")


async def case_a_refused_stub_does_not_fall_through_to_a_farther_row() -> None:
    fan = FAN + 29
    stub = _MASS_PLACEHOLDER_BASE + 5011
    near = 11165218112610      # the true twin — but it carries its own ledger row
    far = 11165218112611       # same caption, 4h later, no ledger row
    await _add(stub, body=MULTILINE, kind="ppv_send", run_id=5011, emp=2,
               price=1000, at=T0, fan=fan)
    await _add(near, body=OF_ECHO, at=T0 + timedelta(seconds=9), fan=fan)
    await _add(far, body=OF_ECHO, at=T0 + timedelta(hours=4), fan=fan)
    tx = await _add_tx(fan, stub, 1000)
    await _add_tx(fan, near, 1000)

    assert await _adopt(fan) == 0, (
        "the stub folded into a send that is not its own")
    ids = [r.message_id for r in await _rows(fan)]
    assert stub in ids, ids
    assert await _tx_msg_id(tx) == stub, (
        "the purchase was repointed onto the wrong message")
    print("[ok] case_a_refused_stub_does_not_fall_through_to_a_farther_row")


async def case_stubs_months_apart_each_adopt_their_own() -> None:
    fan = FAN + 30
    s_old = _MASS_PLACEHOLDER_BASE + 5012
    s_new = _MASS_PLACEHOLDER_BASE + 5013
    r_old, r_new = 11165218112612, 11165218112613
    middle = 11165218112614     # same caption, a month from either stub
    await _add(s_old, body=MULTILINE, kind="ppv_send", run_id=5012, emp=2,
               at=T0, fan=fan)
    await _add(r_old, body=OF_ECHO, at=T0 + timedelta(seconds=9), fan=fan)
    await _add(middle, body=OF_ECHO, at=T0 + timedelta(days=30), fan=fan)
    await _add(s_new, body=MULTILINE, kind="ppv_send", run_id=5013, emp=2,
               at=T0 + timedelta(days=60), fan=fan)
    await _add(r_new, body=OF_ECHO, at=T0 + timedelta(days=60, seconds=9), fan=fan)

    assert await _adopt(fan) == 2, "each send must pair with its own row"
    rows = {r.message_id: r for r in await _rows(fan)}
    assert set(rows) == {r_old, middle, r_new}, sorted(rows)
    assert rows[r_old].mass_run_id == 5012, rows[r_old].mass_run_id
    assert rows[r_new].mass_run_id == 5013, rows[r_new].mass_run_id
    assert rows[middle].mass_run_id is None, (
        f"a row 30 days from either stub was stamped: {rows[middle].mass_run_id}")
    print("[ok] case_stubs_months_apart_each_adopt_their_own")


async def case_chat_pointer_follows_the_adopted_row() -> None:
    from db.models import Chat
    fan = FAN + 26
    stub = _MASS_PLACEHOLDER_BASE + 5007
    real = 11165218112607
    at_real = T0 + timedelta(seconds=9)
    await _add(stub, body=MULTILINE, kind="ppv_send", run_id=5007, emp=2, at=T0, fan=fan)
    await _add(real, body=OF_ECHO, at=at_real, fan=fan)
    async with get_session() as s:
        s.add(Chat(account_id=ACCT, fan_id=fan, last_message_id=stub,
                   last_message_at=T0, last_message_preview="stale"))

    assert await _adopt(fan) == 1
    async with get_session() as s:
        chat = await s.get(Chat, (ACCT, fan))
    assert chat.last_message_id == real, (
        f"inbox left pointing at a deleted row ({chat.last_message_id}) — no ingest "
        "can ever fix that, both updaters advance on numeric id and 1.1e13 < 5e15")
    assert chat.last_message_at == at_real
    assert "<br" not in (chat.last_message_preview or ""), chat.last_message_preview
    print("[ok] case_chat_pointer_follows_the_adopted_row")


async def case_a_real_row_from_another_run_is_not_reclaimed() -> None:
    """`claimed`/`used` are per-invocation, and adoption runs on every ingest."""
    fan = FAN + 27
    stub = _MASS_PLACEHOLDER_BASE + 5008
    real = 11165218112608
    # The real row was adopted on an earlier pass — run 5000, already stamped.
    await _add(real, body=OF_ECHO, kind="ppv_send", run_id=5000, emp=2,
               at=T0 + timedelta(seconds=9), fan=fan)
    # A second stub, same caption, same 6h window, DIFFERENT run.
    await _add(stub, body=MULTILINE, kind="ppv_send", run_id=5008, emp=2, at=T0, fan=fan)

    assert await _adopt(fan) == 0, "a row owned by another run must not eat a stub"
    ids = [r.message_id for r in await _rows(fan)]
    assert stub in ids, "the stub was deleted against a row it did not create"
    print("[ok] case_a_real_row_from_another_run_is_not_reclaimed")


async def case_unsent_stub_keeps_the_real_row_unsent() -> None:
    """REGRESSION (wave6 B8): the auto-unsend flipped the stub, then the scrape
    adopted it — the real row must inherit the unsend, not resurrect the send."""
    from sqlalchemy import update
    fan = FAN + 90
    stub = _MASS_PLACEHOLDER_BASE + 5014
    at_unsend = T0 + timedelta(minutes=5)
    await _add(stub, kind="mass_premade", run_id=5014, emp=2, at=T0, fan=fan)
    async with get_session() as s:
        await s.execute(update(Message).where(
            Message.account_id == ACCT, Message.fan_id == fan,
            Message.message_id == stub,
        ).values(is_unsent=True, unsent_at=at_unsend))
    await _add(11734249147473, at=T0 + timedelta(seconds=9), fan=fan)

    assert await _adopt(fan) == 1
    rows = await _rows(fan)
    assert [r.message_id for r in rows] == [11734249147473], rows
    assert rows[0].is_unsent is True, "adoption resurrected an unsent broadcast"
    assert rows[0].unsent_at == at_unsend, rows[0].unsent_at
    assert rows[0].mass_run_id == 5014
    print("[ok] case_unsent_stub_keeps_the_real_row_unsent")


async def main() -> None:
    await _seed_account()
    for case in (case_a_stale_placeholder_cannot_claim_an_unrelated_send,
                 case_of_br_echo_adopts,
                 case_two_normalized_pairs_do_not_cross_claim,
                 case_second_pass_adopts_nothing,
                 case_empty_normalized_key_never_pairs,
                 case_transaction_is_repointed_not_orphaned,
                 case_chat_pointer_follows_the_adopted_row,
                 case_a_refused_pair_fences_the_contested_row,
                 case_a_refused_stub_does_not_fall_through_to_a_farther_row,
                 case_stubs_months_apart_each_adopt_their_own,
                 case_a_real_row_from_another_run_is_not_reclaimed,
                 case_a_slow_ingest_still_adopts,
                 case_scrape_adopts_placeholder,
                 case_price_recovered_when_of_reports_zero,
                 case_nearest_placeholder_wins,
                 case_unrelated_bodies_untouched,
                 case_two_placeholders_never_share_one_real_row,
                 case_bad_timestamp_never_wins_nearest,
                 case_ledger_tip_band_is_out_of_range,
                 case_unsent_stub_keeps_the_real_row_unsent):
        await case()
    print("all cases passed")


if __name__ == "__main__":
    asyncio.run(main())
