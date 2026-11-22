#!/usr/bin/env python3
"""test_full_ai_live_guards — Full AI live's send guards across modules, one case per W30 review finding
(rwl W30 full-ai-live-engine, F1–F7, F10–F12, F14, N1, C1–C8), through the live job on the _harness temp DB
with a fake OF client, Jev, Writers and vision (`_full_ai_live_fixtures`, `_full_ai_live_helpers`).

  case_f1_truncated_exclusion                         a short read of the exclusion list: nobody listed, 0 sends
  case_f2_switch_flipped_while_waiting_for_write      FULL_AI_CHAT_OFF flipped in the write-gate wait: no POST
  case_f3_unattempted_offer_cannot_adopt_mass_copy    settle never links an Offer whose carrier was never tried
  case_f4_timeout_does_not_adopt_mass_copy_or_unsend  a PPV timeout readback skips mass copies / other media,
                                                      leaves the old Offer on OF
  case_f5_aged_unconfirmed_media_stays_reserved       an unconfirmed priced item is never offered again
  case_f6_inbound_between_bubbles_stays_open          his DM mid-burst: badge kept, its own Turn queued + answered
  case_f7_final_of_read_sees_newer_inbound            the final OF read's newer inbound stands the Turn down
  case_f10_welcome_handoff_honors_speed_and_dedupes   the welcome handoff queues via `enqueue` (reply speed,
                                                      pending-job dedupe)
  case_f11_rejected_sweep_candidates_count_toward_cap rejected sweep candidates use up the per-pass cap
  case_f12_reaped_free_item_is_not_owned              a reaped unconfirmed free item is not counted owned
  case_f14_disabled_job_calls_no_vision               Full AI off: the job calls no vision before its switch check
  case_n1_refused_ppv_frees_its_media                 a PPV POST OF surely refused (400): CLEAR with no read-back,
                                                      no Offer, no attempt, its media offered again
  case_c1_bought_during_gate_wait_stands_ppv_down     he buys the media while the PPV waits for the write gate:
                                                      the gate's offer check stands it down, no claim, no POST
  case_c2_gate_never_crawls_the_fans_list             the gate reads the cached Fans list only: a cold cache stands
                                                      the bubble down with 0 OF list reads
  case_c2_switch_flipped_during_gate_reads            FULL_AI_CHAT_OFF flipped during the gate's own reads: Stand
  case_c3_refusal_never_adopts_an_older_card          a 400 is CLEAR with no read-back (an older same card ignored)
  case_c3_timeout_readback_floor_is_the_attempt_second  a timeout's read-back takes a card from the attempt's
                                                      whole second on (as settle's link_window), never an earlier one
  case_c6_aged_attempt_stays_reserved_until_settled   an unresolved attempted Offer reserves its media at any age,
                                                      and settle still links it
  case_c7_sweep_reaches_the_fan_behind_twenty_stand_downs  20 older stand-downs never starve the 21st Fan
  case_c8_mid_burst_turn_reads_the_whole_burst        a recovered mid-burst DM's thread holds every sent bubble

Run: ./venv/bin/python service/tests/test_full_ai_live_guards.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)
from _jev_fixtures import mapped  # noqa: E402

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from unittest.mock import AsyncMock, patch  # noqa: E402

from sqlalchemy import select  # noqa: E402

from _full_ai_fixtures import KIND, QUIET, _msg  # noqa: E402
from _full_ai_live_fixtures import LiveOF, clear_pause, dm, live_rows, payload, world  # noqa: E402
from _full_ai_live_helpers import NANO, seed_live, world as sell_world  # noqa: E402
from automations import (  # noqa: E402
    full_ai_live, full_ai_look, full_ai_owner_io, full_ai_photo, full_ai_ppv, full_ai_settle, welcome_turn,
)
from db.engine import get_session  # noqa: E402
from db.models import AiDecision, Blacklist, Message, ScheduledJob, VaultItem  # noqa: E402
import of_write  # noqa: E402
import vault_jev_rules  # noqa: E402
import webhook_dispatch as wd  # noqa: E402

CHAT = {"typing_sign": False, "typing_notification": False}
EXCLUDE = {"fans": {"include": [], "exclude": [42]}}
OFF = "FULL_AI_CHAT_OFF"
MEDIA, OTHER, PRICE = 7101, 7102, 1000
PPV = {"ref": MEDIA, "price_cents": PRICE, "media": [MEDIA], "previews": []}


async def _run(aid, fan, mid, rid):
    return await full_ai_live.run(aid, payload(fan, mid, rid), run_id=0)


async def _jobs(aid):
    async with get_session() as s:
        return list((await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == aid, ScheduledJob.kind == KIND,
            ScheduledJob.status == "pending").order_by(ScheduledJob.id))).scalars())


async def _offer(aid, fan, *, status="sending", age_s=0, price=PRICE, attempted=False):
    """A reserved priced Offer row; `attempted`: its carrier POST was tried at reserve time."""
    at = datetime.utcnow() - timedelta(seconds=age_s)
    async with get_session() as s:
        row = AiDecision(
            account_id=aid, fan_id=fan, mode="live", trigger_kind="inbound", trigger_key="100",
            route="sell_now", heat=2, route_row="sell", question_version="x", status=status,
            created_at=at, offer_attempt_at=at if attempted else None,
            reply_json=json.dumps({"parts": [{"text": "just for u", "ppv": {**PPV, "price_cents": price}}]}),
            offer_price_cents=price, offer_list_cents=PRICE,
            offer_media_json=json.dumps({"locked": [MEDIA], "previews": []}),
            offer_item_ref=json.dumps({"ref": MEDIA, "subject": "anything", "format": "photo", "kind": "offer"}),
        )
        s.add(row)
        await s.flush()
        return row.id


async def _send_priced(of, aid, fan, row_id, **kw):
    return await full_ai_ppv.send_priced(
        of, row_id=row_id, account_id=aid, fan_id=fan, text="just for u", ppv=PPV,
        send_purpose=full_ai_live.SEND_PURPOSE, min_gap_s=full_ai_live.WRITE_GAP_S, **kw)


async def case_f1_truncated_exclusion():
    aid, fan, mid = "w30_f1", 701, 9101
    rid = await seed_live(aid, {**CHAT, **EXCLUDE})
    await dm(aid, fan, mid)

    class PartialListOF(LiveOF):
        def list_users_in(self, list_id, *, limit, offset):
            # OF repeats the first page. Its count says the excluded Fan is still unread.
            return {"list": [{"id": fan + 1}], "hasMore": True}

        def get_list(self, list_id):
            return {"usersCount": 2}

    with world(PartialListOF()) as w:
        claimed = await full_ai_owner_io.claimed_ids(aid, [fan])
        await _run(aid, fan, mid, rid)  # reads the cached crawl
    assert (claimed, w.of.calls) == (set(), 0), (
        f"truncated exclusion must stand down; claimed={claimed}, POSTs={w.of.calls}")


async def case_f2_switch_flipped_while_waiting_for_write():
    aid, fan, mid = "w30_f2", 702, 9201
    rid = await seed_live(aid, CHAT)
    await dm(aid, fan, mid)
    waiting, grant = asyncio.Event(), asyncio.Event()
    real_turn = of_write.WriteGate.turn

    async def turn(gate, *args, **kw):
        waiting.set()
        await grant.wait()
        return await real_turn(gate, *args, **kw)

    with world() as w, patch.object(of_write.WriteGate, "turn", turn), patch.dict(os.environ, {OFF: "0"}):
        task = asyncio.create_task(_run(aid, fan, mid, rid))
        try:
            await asyncio.wait_for(waiting.wait(), timeout=5)
            os.environ[OFF] = "1"
        finally:
            grant.set()
            await task
    assert w.of.calls == 0, f"switch flipped before gate grant; POSTs={w.of.calls}, expected 0"


async def case_f3_unattempted_offer_cannot_adopt_mass_copy():
    aid, fan, unrelated = "w30_f3", 703, 9301
    await seed_live(aid)
    row_id = await _offer(aid, fan)
    await _msg(aid, fan, unrelated, "out", "mass copy", datetime.utcnow(),
               price_cents=PRICE, is_paid=True, media_ids=json.dumps([OTHER]), media_count=1,
               raw_json=json.dumps({"queueId": 123, "media": [{"id": OTHER}]}))
    changed = await full_ai_settle.settle_pull(aid, fan)
    (before,) = await live_rows(aid, fan)
    with world() as w:
        sent = await _send_priced(w.of, aid, fan, row_id)
    (after,) = await live_rows(aid, fan)
    assert (changed, before.offer_message_id, before.outcome, w.of.calls) == (0, None, None, 1), (
        f"unattempted Offer must stay unlinked and POST once; settled={changed}, "
        f"linked={before.offer_message_id}, outcome={before.outcome}, POSTs={w.of.calls}")
    assert sent.outcome == full_ai_ppv.SENT and sent.message_id == after.offer_message_id != unrelated, sent


async def case_f4_timeout_does_not_adopt_mass_copy_or_unsend():
    aid, fan, unrelated, old = "w30_f4", 704, 9401, 9402
    await seed_live(aid)
    row_id = await _offer(aid, fan)

    class TimeoutOF(LiveOF):
        def __init__(self):
            super().__init__()
            self.unsent = []

        def send_message(self, chat_id, text, **kw):
            self.calls += 1
            self.chat = [{"id": unrelated, "text": "mass copy", "price": PRICE / 100,
                          "queueId": 124, "fromUser": {"id": int(self.user_id)},
                          "createdAt": datetime.utcnow().isoformat() + "Z", "media": [{"id": OTHER}]}]
            raise TimeoutError("fake PPV POST timed out")

        def unsend_message(self, message_id, chat_id):
            self.unsent.append((message_id, chat_id))

    with world(TimeoutOF()) as w:
        sent = await _send_priced(w.of, aid, fan, row_id, over_message_id=old)
    (row,) = await live_rows(aid, fan)
    assert w.of.calls == 1 and w.of.reads == 1, (w.of.calls, w.of.reads)
    assert (sent.outcome, row.offer_message_id, w.of.unsent) == (full_ai_ppv.UNCONFIRMED, None, []), (
        f"timeout with unrelated PPV must stay unconfirmed and preserve old offer; "
        f"result={sent.outcome}, linked={row.offer_message_id}, unsent={w.of.unsent}")


async def case_f5_aged_unconfirmed_media_stays_reserved():
    aid, fan, mid = "w30_f5", 705, 9501
    rid = await seed_live(aid, {**CHAT, "sell_on": True, "sext_scene": False, "chat_tease": False,
                               "floor_on": False})
    await _offer(aid, fan, status="unconfirmed", age_s=1000)
    async with get_session() as s:
        s.add(VaultItem(account_id=aid, media_id=MEDIA, kind="photo", created_at=datetime.utcnow(),
                        tags="[]", describe_status="described", of_folder_ids="[]",
                        ai_fields_json=json.dumps(mapped({
                            "clothing_state": "dressed", "description": "a selfie in jeans",
                            "people_count": 1, vault_jev_rules.JEV_KEY: {
                                "v": vault_jev_rules.VERSION, "status": "ok", "lane5": "$10",
                                "state": {}, "kind": "photo", "tags": {},
                            },
                        }))))
    await dm(aid, fan, mid, "send me pics")
    await dm(aid, fan + 1, mid + 1, "send me pics")
    jev = ({**QUIET, "wants_content": .9}, 2.0)
    writers = {NANO: "ok:omg ur so sweet. i have something for u"}
    with sell_world(jev=jev, writers=writers) as (of, *_):
        await _run(aid, fan + 1, mid + 1, rid)  # same inventory without a prior Offer
        await _run(aid, fan, mid, rid)
    charged = [(s["fan_id"], s["price"]) for s in of.sent if MEDIA in s.get("media_files", []) and "price" in s]
    assert any(f == fan + 1 for f, _ in charged), f"control did not get the sole sellable item; sends={of.sent}"
    assert all(f != fan for f, _ in charged), (
        f"media {MEDIA} on an unresolved Offer must stay reserved after 900s; priced POSTs={charged}")


async def case_f6_inbound_between_bubbles_stays_open():
    aid, fan, mid = "w30_f6", 706, 9601
    rid = await seed_live(aid, CHAT)
    await dm(aid, fan, mid)
    loop = asyncio.get_running_loop()

    def after_first(n, _text):
        if n == 1:
            asyncio.run_coroutine_threadsafe(
                _msg(aid, fan, mid + 1, "in", "also are u free later", datetime.utcnow()), loop,
            ).result(timeout=5)

    with world(LiveOF(after=after_first)) as w:
        await _run(aid, fan, mid, rid)
    assert w.of.calls >= 1, "setup must land the first bubble"
    queued = [json.loads(j.payload_json).get("anchor") for j in await _jobs(aid)]
    await clear_pause(aid, fan)
    with world(line="ok:yeah im around later tonight"):
        follow_up = await _run(aid, fan, mid + 1, rid)
    assert (w.of.read, queued, follow_up.get("row_status")) == ([], [mid + 1], "sent"), (
        f"new inbound must stay unread, queue and get answered; mark_read={w.of.read}, "
        f"queued={queued}, follow_up={follow_up}")


async def case_f7_final_of_read_sees_newer_inbound():
    aid, fan, mid = "w30_f7", 707, 9701
    rid = await seed_live(aid, CHAT)
    await dm(aid, fan, mid)

    class InboundOF(LiveOF):
        saw_inbound = False

        def get_messages(self, chat_id, **kw):
            self.saw_inbound |= bool(self.chat)
            return super().get_messages(chat_id, **kw)

    of = InboundOF()

    async def hold(*args, **kw):
        # Now visible on OF, after the writer started, with no local Message row.
        of.chat = [{"id": mid + 1, "text": "wait i meant tomorrow", "fromUser": {"id": fan},
                    "createdAt": datetime.utcnow().isoformat() + "Z"}]

    with world(of) as w, patch.object(full_ai_live, "hold_with_typing", hold):
        await _run(aid, fan, mid, rid)
    assert of.saw_inbound, "setup must read the newer inbound from OF after drafting"
    assert w.of.calls == 0, f"new inbound from last OF GET must stop stale draft; POSTs={w.of.calls}, expected 0"


async def case_f10_welcome_handoff_honors_speed_and_dedupes():
    aid, fan, mid = "w30_f10", 710, 9801
    cfg = {"reply_speed": "0-15-60"}
    rid = await seed_live(aid, cfg)
    await dm(aid, fan, mid)
    async with get_session() as s:
        inbound = await s.get(Message, (aid, fan, mid))
    due = full_ai_live.due(cfg, inbound)
    with world(), patch.object(wd, "_schedule_wake") as wake:
        await welcome_turn.enqueue_turn_handoff(aid, fan)
        await welcome_turn.enqueue_turn_handoff(aid, fan)
    jobs = await _jobs(aid)
    actual = [(round((j.run_at - inbound.created_at).total_seconds()), json.loads(j.payload_json).get("_rule_id"))
              for j in jobs]
    expected = (round((due - inbound.created_at).total_seconds()), rid)
    assert (actual, wake.call_count) == ([expected], 1), (
        f"handoff must queue once at reply due time and wake once; expected delay/rule={expected}, "
        f"jobs={actual}, wakes={wake.call_count}")
    assert jobs[0].run_at == due, (jobs[0].run_at, due)


async def case_f11_rejected_sweep_candidates_count_toward_cap():
    aid = "w30_f11"
    await seed_live(aid, EXCLUDE)
    for i in range(25):
        await dm(aid, 800 + i, 9900 + i, ago_s=300)
    class FailedListOF(LiveOF):
        list_reads = 0

        def list_users_in(self, list_id, *, limit, offset):
            self.list_reads += 1
            raise RuntimeError("fake list unavailable")

    with world(FailedListOF()) as w, patch.object(full_ai_look, "last_look", wraps=full_ai_look.last_look) as look:
        stats = await full_ai_live.run(aid, {}, run_id=0)
    assert stats["queued"] == 0, stats
    assert look.await_count <= 20 and w.of.list_reads <= 1, (
        f"sweep must examine at most 20 candidates and read the failing list once; "
        f"pre-looks={look.await_count}, list reads={w.of.list_reads}")


async def case_f12_reaped_free_item_is_not_owned():
    aid, fan, mid = "w30_f12", 712, 9912
    await seed_live(aid)
    await _offer(aid, fan, price=0)
    await dm(aid, fan, mid)
    assert await full_ai_live.reap(aid, fan) == 1
    (row,) = await live_rows(aid, fan)
    assert (row.status, row.offer_message_id) == ("unconfirmed", None), row.status
    facts = await full_ai_live.load(aid, fan, LiveOF())
    assert MEDIA not in facts.owned and MEDIA not in facts.sent, (
        f"reaped Free item with no delivery must stay eligible; owned={facts.owned}, sent={facts.sent}")


async def case_f14_disabled_job_calls_no_vision():
    aid, fan, mid = "w30_f14", 714, 9914
    rid = await seed_live(aid, {**CHAT, full_ai_photo.KEY: True})
    await _msg(aid, fan, mid, "in", "", datetime.utcnow(), media_count=1,
               media_ids=json.dumps([MEDIA]))
    with world() as w, patch.dict(os.environ, {OFF: "1"}), patch.object(
        full_ai_photo.inbound_describe, "describe_message", new_callable=AsyncMock,
        return_value=("a selfie", "fake-vision"),
    ) as describe:
        await _run(aid, fan, mid, rid)
    assert describe.await_count == 0 and w.of.calls == 0, (
        f"disabled job must skip vision and sends; vision calls={describe.await_count}, POSTs={w.of.calls}")


class _Resp400:
    status_code, text = 400, "Please allow 10 seconds before sending another message"

    def json(self):
        raise ValueError("not json")


class _RateLimited(Exception):
    response = _Resp400()


class _RefusedOF(LiveOF):
    """OF surely refuses every DM (a 400: `ax._may_have_sent` False)."""

    def send_message(self, chat_id, text, **kw):
        self.calls += 1
        raise _RateLimited("OF 400: Please allow 10 seconds before sending another message")


def _card(mid, at, *, price=PRICE, media=(MEDIA,)):
    """One PPV line of ours as OF's chat read lists it."""
    return {"id": mid, "text": "just for u", "price": price / 100, "fromUser": {"id": 999},
            "createdAt": at.isoformat() + "Z", "media": [{"id": m} for m in media]}


async def case_n1_refused_ppv_frees_its_media():
    aid, fan, mid = "w30_n1", 721, 9721
    await seed_live(aid)
    row_id = await _offer(aid, fan)

    with world(_RefusedOF()) as w:
        sent = await _send_priced(w.of, aid, fan, row_id)
    (row,) = await live_rows(aid, fan)
    assert w.of.calls == 1 and w.of.reads == 0, (w.of.calls, w.of.reads)   # one POST, no read-back (W30 C3)
    assert (sent.outcome, sent.dropped) == (full_ai_ppv.CLEAR, "send"), sent
    assert (row.offer_price_cents, row.offer_media_json, row.offer_attempt_at) == (None, None, None), (
        f"a refused PPV must leave no Offer and no attempt; price={row.offer_price_cents}, "
        f"media={row.offer_media_json}, attempt={row.offer_attempt_at}")
    await dm(aid, fan, mid)
    facts = await full_ai_live.load(aid, fan, LiveOF())
    assert MEDIA not in facts.owned, f"a refused PPV's media must be offered again; owned={facts.owned}"


async def _anchor(aid, fan, mid):
    async with get_session() as s:
        m = await s.get(Message, (aid, fan, mid))
    return m.created_at, mid


async def _gate(aid, fan, anchor, client, bubble, row=None):
    """`full_ai_look.gate` on one bubble's look: the Stand's (check, reason), or None (it may POST)."""
    try:
        await full_ai_look.gate(full_ai_look.Look(aid, fan, anchor, client, row or {"id": None}, bubble, 0, 0))
    except full_ai_look.Stand as e:
        return e.why
    return None


async def case_c1_bought_during_gate_wait_stands_ppv_down():
    aid, fan, mid = "w30_c1", 731, 9731
    await seed_live(aid, CHAT)
    row_id = await _offer(aid, fan)
    await dm(aid, fan, mid)
    anchor = await _anchor(aid, fan, mid)
    real_turn = of_write.WriteGate.turn

    async def turn(gate, *args, **kw):
        # He buys the same media in another lane while the replacement PPV waits for its write turn.
        await _msg(aid, fan, mid + 1, "out", "paid elsewhere", datetime.utcnow() - timedelta(hours=1),
                   price_cents=500, is_paid=True, media_ids=json.dumps([MEDIA]), media_count=1,
                   automation_kind="ppv_send")
        return await real_turn(gate, *args, **kw)

    stood = None
    with world() as w, patch.object(of_write.WriteGate, "turn", turn):
        look = full_ai_look.Look(aid, fan, anchor, w.of, {"id": row_id}, {"text": "just for u", "ppv": PPV}, 0, 0)
        try:
            await _send_priced(w.of, aid, fan, row_id, before_write=lambda: full_ai_look.gate(look))
        except full_ai_look.Stand as e:
            stood = e.why
    (row,) = await live_rows(aid, fan)
    assert (stood, w.of.calls, row.offer_attempt_at) == (("offer_valid", "owned"), 0, None), (
        f"media bought during the gate wait must stand the PPV down before its claim; "
        f"stood={stood}, POSTs={w.of.calls}, attempt={row.offer_attempt_at}")


async def case_c2_gate_never_crawls_the_fans_list():
    aid, fan, mid = "w30_c2", 732, 9732
    await seed_live(aid, {**CHAT, **EXCLUDE})
    await dm(aid, fan, mid)
    anchor = await _anchor(aid, fan, mid)

    class CrawlOF(LiveOF):
        list_reads = 0

        def list_users_in(self, list_id, *, limit, offset):
            self.list_reads += 1
            return {"list": [{"id": fan + 1}], "hasMore": False}

        def get_list(self, list_id):
            return {"usersCount": 1}

    with world(CrawlOF()) as w:
        stood = await _gate(aid, fan, anchor, w.of, {"text": "hey"})
    assert stood is not None and w.of.list_reads == 0, (
        f"the gate reads the cached Fans list only and fails closed on a miss; stood={stood}, "
        f"list reads={w.of.list_reads}")


async def case_c2_switch_flipped_during_gate_reads():
    aid, fan, mid = "w30_c2b", 737, 9737
    await seed_live(aid, CHAT)
    await dm(aid, fan, mid)
    anchor = await _anchor(aid, fan, mid)
    real = full_ai_look.newest_inbound

    async def flip(*args):
        os.environ[OFF] = "1"               # flipped after the gate's off_switch read
        return await real(*args)

    with world() as w, patch.dict(os.environ, {OFF: "0"}), patch.object(full_ai_look, "newest_inbound", flip):
        stood = await _gate(aid, fan, anchor, w.of, {"text": "hey"})
    assert stood == ("off_switch", "off_global"), f"switch flipped during the gate's reads; stood={stood}"


async def case_c3_refusal_never_adopts_an_older_card():
    aid, fan = "w30_c3", 733
    await seed_live(aid)
    row_id = await _offer(aid, fan)
    of = _RefusedOF()
    of.chat = [_card(97331, datetime.utcnow() - timedelta(seconds=1))]   # the same Offer, sent before
    with world(of) as w:
        sent = await _send_priced(w.of, aid, fan, row_id)
    (row,) = await live_rows(aid, fan)
    assert (sent.outcome, sent.dropped, w.of.reads, row.offer_message_id) == (full_ai_ppv.CLEAR, "send", 0, None), (
        f"a 400 is CLEAR with no read-back; result={sent}, reads={w.of.reads}, linked={row.offer_message_id}")


async def case_c3_timeout_readback_floor_is_the_attempt_second():
    class TimeoutOF(LiveOF):
        def send_message(self, chat_id, text, **kw):
            self.calls += 1
            raise TimeoutError("fake PPV POST timed out")

    at = datetime.utcnow().replace(microsecond=500_000)      # the attempt, mid-second (a fixed clock)

    class Clock(datetime):
        @classmethod
        def utcnow(cls):
            return at

    sec = at.replace(microsecond=0)
    table = (("the attempt's own second, before it in µs", sec, full_ai_ppv.SENT),
             ("a later second", sec + timedelta(seconds=1), full_ai_ppv.SENT),
             ("an earlier second", sec - timedelta(seconds=1), full_ai_ppv.UNCONFIRMED))
    for i, (name, card_at, want) in enumerate(table):
        aid, fan, card = f"w30_c3b{i}", 734 + 100 * i, 97341 + i
        await seed_live(aid)
        row_id = await _offer(aid, fan)
        of = TimeoutOF()
        of.chat = [_card(card, card_at)]
        with world(of) as w, patch.object(full_ai_ppv, "datetime", Clock):
            sent = await _send_priced(w.of, aid, fan, row_id)
        (row,) = await live_rows(aid, fan)
        linked = card if want == full_ai_ppv.SENT else None
        assert (sent.outcome, row.offer_message_id, w.of.reads) == (want, linked, 1), (
            f"{name}: the read-back takes a card from the attempt's whole second on; result={sent}, "
            f"linked={row.offer_message_id}, reads={w.of.reads}")


async def case_c6_aged_attempt_stays_reserved_until_settled():
    aid, fan, mid, card = "w30_c6", 735, 9735, 97351
    await seed_live(aid)
    await _offer(aid, fan, status="sent", age_s=8 * 86400, attempted=True)
    await dm(aid, fan, mid)
    owned = (await full_ai_live.load(aid, fan, LiveOF())).owned
    (row,) = await live_rows(aid, fan)
    await _msg(aid, fan, card, "out", "just for u", row.offer_attempt_at + timedelta(seconds=5),
               price_cents=PRICE, media_ids=json.dumps([MEDIA]), media_count=1)
    linked = await full_ai_settle.settle_pull(aid, fan)
    (after,) = await live_rows(aid, fan)
    assert MEDIA in owned and (linked, after.offer_message_id) == (1, card), (
        f"an unresolved attempted Offer stays reserved at any age and settle still links it; "
        f"owned={owned}, settled={linked}, linked={after.offer_message_id}")


async def case_c7_sweep_reaches_the_fan_behind_twenty_stand_downs():
    aid, fan = "w30_c7", 8520
    await seed_live(aid)
    banned = [8500 + i for i in range(20)]
    async with get_session() as s:
        s.add_all(Blacklist(fan_id=f, reason="test") for f in banned)
    for i, f in enumerate(banned):                  # older DMs: first in the sweep's order
        await dm(aid, f, 98500 + i, ago_s=900 - i)
    await dm(aid, fan, 98520, ago_s=300)
    with world(), patch.object(wd, "_schedule_wake"):
        for _ in range(2):
            await full_ai_live.run(aid, {}, run_id=0)
    queued = [json.loads(j.payload_json)["only_fan_ids"] for j in await _jobs(aid)]
    assert queued == [[fan]], f"the 21st Fan must be queued within two passes; queued={queued}"


async def case_c8_mid_burst_turn_reads_the_whole_burst():
    aid, fan, a = "w30_c8", 738, 9738
    await seed_live(aid, CHAT)
    t = datetime.utcnow() - timedelta(minutes=5)
    await _msg(aid, fan, a, "in", "hey", t)
    async with get_session() as s:      # her live Turn on `a`: bubble 1, his DM, bubble 2
        s.add(AiDecision(account_id=aid, fan_id=fan, mode="live", trigger_kind="inbound", trigger_key=str(a),
                         route="chat", heat=1, route_row="otherwise", question_version="x", status="sent",
                         created_at=t, updated_at=t))
    await _msg(aid, fan, a + 1, "out", "omg hiii", t + timedelta(seconds=10), automation_kind=KIND)
    await _msg(aid, fan, a + 2, "in", "u there?", t + timedelta(seconds=15))
    await _msg(aid, fan, a + 3, "out", "just got out of the shower", t + timedelta(seconds=20), automation_kind=KIND)
    facts = await full_ai_live.load(aid, fan, LiveOF())
    outs = [m.message_id for m in facts.cut_rows if m.direction == "out"]
    got = (facts.anchor_key, outs, facts.cut_rows[-1].message_id, facts.state["her_last_line"])
    assert got == (str(a + 2), [a + 1, a + 3], a + 2, "just got out of the shower"), (
        f"a recovered mid-burst DM reads every sent bubble in order, its own Anchor kept; got={got}")


_harness.run()
