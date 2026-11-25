#!/usr/bin/env python3
from __future__ import annotations

import _harness

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
    await _add(10600000000001, at=T0 + timedelta(hours=6, seconds=10), fan=fan)

    assert await _adopt(fan) == 1
    ids = [r.message_id for r in await _rows(fan)]
    assert near not in ids, ids
    assert far in ids, ids
    real = [r for r in await _rows(fan) if r.message_id == 10600000000001][0]
    assert real.mass_run_id == 3001, real.mass_run_id
    print("[ok] case_nearest_placeholder_wins")


async def case_unrelated_bodies_untouched() -> None:
    fan = FAN + 4
    ph = _MASS_PLACEHOLDER_BASE + 4000
    await _add(ph, kind="ppv_send", run_id=4000, emp=2, at=T0, fan=fan)
    await _add(10700000000001, body="a totally different line", at=T0, fan=fan)
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
    await _add(10800000000001, at=T0 + timedelta(seconds=5), fan=fan)

    assert await _adopt(fan) == 1
    ids = [r.message_id for r in await _rows(fan)]
    assert a not in ids, ids
    assert b in ids, ids
    print("[ok] case_two_placeholders_never_share_one_real_row")


async def case_bad_timestamp_never_wins_nearest() -> None:
    from attribution import _seconds_apart

    assert _seconds_apart(T0, T0 + timedelta(seconds=4)) == 4.0
    assert _seconds_apart(None, T0) == float("inf")
    assert _seconds_apart(T0, None) == float("inf")
    assert _seconds_apart(None, None) == float("inf")
    assert _seconds_apart(None, T0) > _seconds_apart(T0, T0 + timedelta(days=365))
    print("[ok] case_bad_timestamp_never_wins_nearest")


async def case_ledger_tip_band_is_out_of_range() -> None:
    fan = FAN + 7
    tip = 6_000_000_000_000_001
    await _add(tip, kind=None, at=T0, fan=fan)
    await _add(11000000000001, at=T0, fan=fan)
    assert await _adopt(fan) == 0
    assert tip in [r.message_id for r in await _rows(fan)], "ledger tip was deleted"
    print("[ok] case_ledger_tip_band_is_out_of_range")


async def case_a_stale_placeholder_cannot_claim_an_unrelated_send() -> None:
    fan = FAN + 11
    stub = 5_000_000_000_002_709
    later = 11000000000077
    await _add(stub, kind="mass_ppv", run_id=4003, emp=2, at=T0, fan=fan)
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




# We store \n; OF echoes the same caption with <br />.
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
    near = 11165218112610
    far = 11165218112611
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
    middle = 11165218112614
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
    fan = FAN + 27
    stub = _MASS_PLACEHOLDER_BASE + 5008
    real = 11165218112608
    await _add(real, body=OF_ECHO, kind="ppv_send", run_id=5000, emp=2,
               at=T0 + timedelta(seconds=9), fan=fan)
    await _add(stub, body=MULTILINE, kind="ppv_send", run_id=5008, emp=2, at=T0, fan=fan)

    assert await _adopt(fan) == 0, "a row owned by another run must not eat a stub"
    ids = [r.message_id for r in await _rows(fan)]
    assert stub in ids, "the stub was deleted against a row it did not create"
    print("[ok] case_a_real_row_from_another_run_is_not_reclaimed")


async def case_unsent_stub_keeps_the_real_row_unsent() -> None:
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
