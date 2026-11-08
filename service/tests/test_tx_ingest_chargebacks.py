#!/usr/bin/env python3
"""
transaction_chargebacks: OF's disputes list flips the ledger row it names.
Fixtures are real items from the 2026-11-07 prod capture
(.scratch/chargebacks-capture/raw_redacted: fan names redacted, ids kept) —
LEDGER_B / DISPUTE_B are the same PPV sale on 15891843 read from both endpoints.

    case_match_table                exact (fan, amount, sale second) 0/1/>1, undo vs done, already
        reversed, tip fallback +-300 s (kind='tip' only), no fallback for non-tips
    case_two_disputes_one_row       the second is `already`, one delta
    case_parse_real_item / case_poll_window
    case_dispute_then_ledger        dispute flips + deducts once; re-poll 0 writes, no applied log;
        the ledger's own `undo` of it afterwards writes nothing
    case_ledger_then_dispute        ledger deducted first; the dispute is `already`, 0 writes
    case_unmatched_never_inserts    no row / a WS-only twin (no provider id): nothing written
    case_applied_broadcasts_a_status_flip
    case_poll_wire_and_paging       startDate/endDate date-only on the wire, limit 100, offset
        paging while full, 5-page cap, inside an of_pacing walk kind=chargebacks
    case_tick_hook                  refresh / backfill poll after the walk; recent does not; a
        disputes error logs ingest_cb_error and leaves the tick ok, streak 0

Run: ./venv/bin/python service/tests/test_tx_ingest_chargebacks.py
"""
from __future__ import annotations

import _harness  # MUST be first

_harness.bootstrap()

import copy  # noqa: E402
import logging  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import func, select  # noqa: E402

import of_client  # noqa: E402
import of_pacing  # noqa: E402
import transaction_chargebacks as cb  # noqa: E402
import transaction_ingest as ti  # noqa: E402
from db import write_telemetry  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Fan, Transaction, TransactionScanHistory  # noqa: E402
from transaction_chargebacks import Held, parse_dispute, plan_chargebacks  # noqa: E402

ti._PAGE_SLEEP_S = 0.0

# ── real items (redacted) ───────────────────────────────────────────
_USER_B = {"view": "t", "id": 498183621, "name": "<red:str>", "username": "<red:str>", "isVerified": False,
           "isDeleted": False, "isActive": True, "avatar": None, "avatarThumbs": None, "displayName": "<red:str>"}
# GET /payouts/transactions?limit=10&startDate=2026-10-28 (B), list[0]
LEDGER_B = {"amount": 28.88, "vatAmount": 0, "taxAmount": 0, "mediaTaxAmount": 0, "net": 23.1, "fee": 5.78,
            "createdAt": "2026-10-28T20:00:19+00:00", "currency": "USD",
            "description": "Payment for message from <a href=\"https://onlyfans.com/u498183621\">RED</a>",
            "descriptionDetails": {"type": "message", "params": {"URL": "https://onlyfans.com/u498183621",
                                                                  "NAME": "<red:str>"}},
            "status": "undo", "user": _USER_B, "refundReason": "agent", "id": "e1d357379ee52b352f52dd3852e986d9"}
# GET /payouts/chargebacks?limit=100 (B): the same sale, a different payment id
DISPUTE_B = {"id": 0, "createdAt": "2026-11-03T14:05:23+00:00", "paymentType": "chat_messages",
             "payment": {k: v for k, v in LEDGER_B.items() if k not in ("refundReason", "id")}
             | {"id": "e07f5e73ecd0534ce9bfbee9e30977c8"}}
# (A) a tip dispute, reversed
DISPUTE_TIP = {"id": 0, "createdAt": "2026-10-17T12:48:51+00:00", "paymentType": "tips",
               "payment": {"amount": 8.9, "vatAmount": 1.16, "taxAmount": 0, "mediaTaxAmount": 0, "net": 7.12,
                           "fee": 1.78, "createdAt": "2026-10-17T00:32:08+00:00", "currency": "USD",
                           "description": "Tip from <a href=\"https://onlyfans.com/u469515269\">RED</a>",
                           "descriptionDetails": {"type": "tips", "params": {
                               "URL": "https://onlyfans.com/u469515269", "NAME": "<red:str>"}},
                           "status": "undo", "user": {"view": "t", "id": 469515269, "name": "<red:str>"},
                           "id": "3b80e749e7d5626ec5181bdd47442c98"}}
# (A) an open dispute: payment.status done (our row: refund_pending)
DISPUTE_OPEN = {"id": 0, "createdAt": "2026-10-29T13:51:05+00:00", "paymentType": "subscribes",
                "payment": {"amount": 4.55, "vatAmount": 0, "taxAmount": 0, "mediaTaxAmount": 0, "net": 3.64,
                            "fee": 0.91, "createdAt": "2026-10-18T16:17:29+00:00", "currency": "USD",
                            "description": "Subscription from <span>RED</span>",
                            "descriptionDetails": {"type": "subscription", "params": {"NAME": "<red:str>"}},
                            "status": "done", "user": {"view": "t", "id": 146973725, "name": "<red:str>"},
                            "id": "e10fe9176a2fd6ab5836b805620be912"}}

SALE_B = datetime(2026, 10, 28, 20, 0, 19)
SALE_TIP = datetime(2026, 10, 17, 0, 32, 8)
FAN_B, FAN_TIP = 498183621, 469515269


def _with(item: dict, **pay) -> dict:
    out = copy.deepcopy(item)
    out["payment"].update(pay)
    return out


def _held(i, *, fan=FAN_B, amount=2888, at=SALE_B, kind="ppv_message", status="cleared",
          currency="USD") -> Held:
    return Held(i, f"pid{i}", fan, kind, amount, at, status, currency)


class _Logs(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []
        self.levels: dict[str, int] = {}
        self.traced: list[bool] = []

    def emit(self, record):
        self.lines.append(record.getMessage())
        self.levels[record.getMessage().split(" ", 1)[0]] = record.levelno
        self.traced.append(bool(record.exc_info))

    def named(self, name: str) -> list[str]:
        return [ln for ln in self.lines if ln.split(" ", 1)[0] == name]


LOGS = _Logs()
_lg = logging.getLogger("of-relay.ingest_tx")
_lg.addHandler(LOGS)
_lg.setLevel(logging.DEBUG)
_lg.propagate = False


# ── pure ────────────────────────────────────────────────────────────

def case_match_table():
    s = timedelta(seconds=1)
    def tip(i, at, kind="tip", status="cleared"):
        return _held(i, fan=FAN_TIP, amount=890, at=at, kind=kind, status=status)
    table = [
        # (name, dispute, held rows, (outcome, target id, delta, candidates))
        ("exact 1", DISPUTE_B, [_held(1)], ("applied", 1, -2888, 1)),
        ("exact 1 among others of the fan", DISPUTE_B,
         [_held(1), _held(2, amount=2887), _held(3, at=SALE_B + s), _held(4, fan=FAN_B + 1)],
         ("applied", 1, -2888, 1)),
        ("open dispute (done): no write, even with a match", DISPUTE_OPEN,
         [_held(1, fan=146973725, amount=455, at=datetime(2026, 10, 18, 16, 17, 29))], ("open", None, 0, 0)),
        ("no candidate", DISPUTE_B, [], ("unmatched", None, 0, 0)),
        ("one second off is no match", DISPUTE_B, [_held(1, at=SALE_B - s)], ("unmatched", None, 0, 0)),
        ("two exact", DISPUTE_B, [_held(1), _held(2)], ("ambiguous", None, 0, 2)),
        ("already chargedback: re-poll", DISPUTE_B, [_held(1, status="chargedback")], ("already", 1, 0, 1)),
        ("already refunded", DISPUTE_B, [_held(1, status="refunded")], ("already", 1, 0, 1)),
        ("failed row: never revenue", DISPUTE_B, [_held(1, status="failed")], ("already", 1, 0, 1)),
        ("refund_pending still counted: deducts", DISPUTE_B, [_held(1, status="refund_pending")],
         ("applied", 1, -2888, 1)),
        ("pending row deducts", DISPUTE_B, [_held(1, status="pending")], ("applied", 1, -2888, 1)),
        ("non-tip: no +-300 s fallback", DISPUTE_B, [_held(1, at=SALE_B + 60 * s)], ("unmatched", None, 0, 0)),
        ("tip exact", DISPUTE_TIP, [tip(1, SALE_TIP)], ("applied", 1, -890, 1)),
        ("tip fallback 120 s (promoted WS clock)", DISPUTE_TIP, [tip(1, SALE_TIP + 120 * s)],
         ("applied", 1, -890, 1)),
        ("tip fallback edge 300 s", DISPUTE_TIP, [tip(1, SALE_TIP - 300 * s)], ("applied", 1, -890, 1)),
        ("tip fallback 301 s", DISPUTE_TIP, [tip(1, SALE_TIP + 301 * s)], ("unmatched", None, 0, 0)),
        ("tip fallback two in window", DISPUTE_TIP, [tip(1, SALE_TIP + 60 * s), tip(2, SALE_TIP - 90 * s)],
         ("ambiguous", None, 0, 2)),
        ("tip fallback rejects non-tip kind", DISPUTE_TIP, [tip(1, SALE_TIP + 60 * s, kind="tip_post")],
         ("unmatched", None, 0, 0)),
        ("a tip-kind row near a non-tips dispute: no fallback",
         _with(DISPUTE_TIP) | {"paymentType": "chat_messages"}, [tip(1, SALE_TIP + 60 * s)],
         ("unmatched", None, 0, 0)),
        ("tips dispute, same-second PPV twin: not the PPV", DISPUTE_TIP,
         [tip(1, SALE_TIP, kind="ppv_message")], ("unmatched", None, 0, 0)),
        ("tips dispute, same-second PPV twin + the tip: the tip", DISPUTE_TIP,
         [tip(1, SALE_TIP, kind="ppv_message"), tip(2, SALE_TIP)], ("applied", 2, -890, 1)),
        ("chat_messages dispute vs a same-second tip: no match", DISPUTE_B, [_held(1, kind="tip")],
         ("unmatched", None, 0, 0)),
        ("subscribes dispute matches a rebill", _with(DISPUTE_B) | {"paymentType": "subscribes"},
         [_held(1, kind="rebill"), _held(2, kind="ppv_message")], ("applied", 1, -2888, 1)),
        ("unknown paymentType: no kind constraint", _with(DISPUTE_B) | {"paymentType": "streams"},
         [_held(1, kind="ppv_stream")], ("applied", 1, -2888, 1)),
        ("currency mismatch", DISPUTE_B, [_held(1, currency="EUR")], ("unmatched", None, 0, 0)),
        ("row currency unknown: no constraint", DISPUTE_B, [_held(1, currency=None)], ("applied", 1, -2888, 1)),
        ("tip exact wins over a fallback neighbour", DISPUTE_TIP, [tip(1, SALE_TIP), tip(2, SALE_TIP + 60 * s)],
         ("applied", 1, -890, 1)),
        ("tip fallback already reversed", DISPUTE_TIP, [tip(1, SALE_TIP + 60 * s, status="chargedback")],
         ("already", 1, 0, 1)),
        ("no fan", _with(DISPUTE_B, user={}), [_held(1)], ("unmatched", None, 0, 0)),
    ]
    bad = []
    for name, item, rows, want in table:
        (op,) = plan_chargebacks([parse_dispute(item)], rows)
        got = (op.outcome, op.target.id if op.target else None, op.lifetime_delta, op.candidates)
        if got != want:
            bad.append((name, got, want))
        assert op.writes == (op.outcome == "applied"), name
    assert not bad, "\n".join(f"{n}: got {g} want {w}" for n, g, w in bad)


def case_two_disputes_one_row():
    ops = plan_chargebacks([parse_dispute(DISPUTE_B), parse_dispute(DISPUTE_B)], [_held(1)])
    assert [(o.outcome, o.lifetime_delta) for o in ops] == [("applied", -2888), ("already", 0)], ops


def case_parse_real_item():
    assert parse_dispute(DISPUTE_B) == {
        "fan_id": FAN_B, "amount_cents": 2888, "sale_at": SALE_B,
        "dispute_at": datetime(2026, 11, 3, 14, 5, 23), "payment_type": "chat_messages", "currency": "USD",
        "undo": True}
    assert parse_dispute(DISPUTE_OPEN)["undo"] is False


def case_poll_window():
    assert cb.poll_window(datetime(2026, 11, 7, 23, 30)) == ("2026-08-09", "2026-11-08")
    assert cb.poll_window(datetime(2026, 1, 1, 0, 0)) == ("2025-10-03", "2026-01-02")


# ── the write path ──────────────────────────────────────────────────

BASE_LIFETIME = 10_000


async def _account(aid: str, fans=(FAN_B,)) -> None:
    async with get_session() as s:
        s.add(Account(id=aid))
        for f in fans:
            s.add(Fan(account_id=aid, fan_id=f, lifetime_spend_cents=BASE_LIFETIME))


async def _lifetime(aid: str, fan=FAN_B) -> int:
    async with get_session() as s:
        return (await s.get(Fan, (aid, fan))).lifetime_spend_cents


async def _rows(aid: str) -> list[tuple]:
    async with get_session() as s:
        return [(t.provider_transaction_id, t.status, t.amount_cents) for t in (await s.execute(
            select(Transaction).where(Transaction.account_id == aid).order_by(Transaction.id))).scalars()]


def _txns(label: str) -> int:
    return (write_telemetry.snapshot("test")["w"].get(label) or {}).get("n", 0)


def _reset_txns() -> None:
    _txns("ledger"), _txns("ledger-chargebacks")


async def case_dispute_then_ledger():
    aid = "cb_1"
    await _account(aid)
    assert await ti.write_page(aid, [LEDGER_B | {"status": "done"}]) == (1, 0)
    assert await _lifetime(aid) == BASE_LIFETIME + 2888
    _reset_txns()
    LOGS.lines.clear()
    r = await cb.apply_chargebacks(aid, [DISPUTE_B])
    assert (r["items"], r["applied"]) == (1, 1), r
    assert await _rows(aid) == [(LEDGER_B["id"], "chargedback", 2888)]
    assert await _lifetime(aid) == BASE_LIFETIME, "the sale comes off once"
    assert _txns("ledger-chargebacks") == 1
    assert LOGS.named("ingest_cb_applied") == [
        f"ingest_cb_applied account={aid} fan={FAN_B} provider={LEDGER_B['id']} amount=2888 "
        "dispute_at=2026-11-03T14:05:23"], LOGS.lines
    assert LOGS.levels["ingest_cb_applied"] == logging.INFO
    # Re-poll: nothing written, nothing "applied".
    LOGS.lines.clear()
    r = await cb.apply_chargebacks(aid, [DISPUTE_B])
    assert (r["applied"], r["already"]) == (0, 1), r
    assert _txns("ledger-chargebacks") == 0, "a re-poll takes no write lock"
    assert not LOGS.named("ingest_cb_applied"), LOGS.lines
    # The ledger catches up (`undo`): same status, same fields -> noop.
    assert await ti.write_page(aid, [LEDGER_B]) == (0, 1)
    assert _txns("ledger") == 0, "the ledger's own undo of a disputed row writes nothing"
    assert await _lifetime(aid) == BASE_LIFETIME


async def case_ledger_then_dispute():
    aid = "cb_2"
    await _account(aid)
    await ti.write_page(aid, [LEDGER_B | {"status": "done"}])
    await ti.write_page(aid, [LEDGER_B])
    assert await _lifetime(aid) == BASE_LIFETIME
    _reset_txns()
    r = await cb.apply_chargebacks(aid, [DISPUTE_B, DISPUTE_OPEN])
    assert (r["applied"], r["already"], r["open"]) == (0, 1, 1), r
    assert LOGS.levels.get("ingest_cb_open") == logging.DEBUG, LOGS.levels
    assert _txns("ledger-chargebacks") == 0
    assert await _lifetime(aid) == BASE_LIFETIME
    assert await _rows(aid) == [(LEDGER_B["id"], "chargedback", 2888)]


async def case_dispute_then_ledger_says_done():
    # The dispute flipped it; a ledger re-read still says `done`: the amount
    # comes back with the status (lifetime follows status), the next poll
    # takes it off again. Net: one deduction while the dispute stands.
    aid = "cb_2b"
    await _account(aid)
    await ti.write_page(aid, [LEDGER_B | {"status": "done"}])
    await cb.apply_chargebacks(aid, [DISPUTE_B])
    await ti.write_page(aid, [LEDGER_B | {"status": "done"}])
    assert await _lifetime(aid) == BASE_LIFETIME + 2888
    await cb.apply_chargebacks(aid, [DISPUTE_B])
    assert await _lifetime(aid) == BASE_LIFETIME
    assert (await _rows(aid))[0][1] == "chargedback"


async def case_unmatched_never_inserts():
    aid = "cb_3"
    await _account(aid, fans=(FAN_B, FAN_TIP))
    # A WS-pump tip at the exact key but no provider id: not a ledger row, not a candidate.
    async with get_session() as s:
        s.add(Transaction(account_id=aid, fan_id=FAN_TIP, kind="tip", amount_cents=890,
                          occurred_at=SALE_TIP, source="ws", status="cleared"))
    before = await _rows(aid)
    _reset_txns()
    LOGS.lines.clear()
    r = await cb.apply_chargebacks(aid, [DISPUTE_B, DISPUTE_TIP])
    assert (r["unmatched"], r["applied"]) == (2, 0), r
    assert await _rows(aid) == before
    assert _txns("ledger-chargebacks") == 0
    assert await _lifetime(aid, FAN_TIP) == BASE_LIFETIME
    assert len(LOGS.named("ingest_cb_unmatched")) == 2, LOGS.lines
    assert LOGS.levels["ingest_cb_unmatched"] == logging.DEBUG, "per-item unmatched is debug (recurs every poll)"
    assert r["unmatched_sample"] == [(FAN_B, 2888, "2026-10-28T20:00:19"), (FAN_TIP, 890, "2026-10-17T00:32:08")], r
    async with get_session() as s:
        n = (await s.execute(select(func.count()).select_from(Transaction).where(
            Transaction.account_id == aid))).scalar_one()
    assert n == 1


async def case_applied_broadcasts_a_status_flip():
    import events
    aid = "cb_4"
    await _account(aid)
    await ti.write_page(aid, [LEDGER_B | {"status": "done"}])
    seen = []

    async def announce(account_id, fan_id, **kw):
        seen.append((account_id, fan_id, kw["reason"], kw["status"], kw["capped"], kw["kind"]))

    real = events.announce_transaction
    events.announce_transaction = announce
    try:
        await cb.apply_chargebacks(aid, [DISPUTE_B])
        await cb.apply_chargebacks(aid, [DISPUTE_B])
    finally:
        events.announce_transaction = real
    assert seen == [(aid, FAN_B, "status_flip", "chargedback", False, "ppv_message")], seen


class _Fake:
    """OF: `transactions` answers `tx_pages`, `chargebacks` answers `cb_pages` (a callable
    raises); the wire params the real OFClient methods send are kept."""

    def __init__(self, tx_pages=(), cb_pages=()):
        self.tx_pages, self.cb_pages = list(tx_pages), list(cb_pages)
        self.cb_wire, self.cb_walks = [], []

    def _rec(self, sink):
        rec = of_client.OFClient.__new__(of_client.OFClient)
        rec.get_json = lambda path, params=None: sink.append(params) or {}
        return rec

    def transactions(self, **kw):
        of_client.OFClient.transactions(self._rec([]), **kw)
        return self.tx_pages.pop(0) if self.tx_pages else {"list": [], "hasMore": False}

    def chargebacks(self, **kw):
        of_client.OFClient.chargebacks(self._rec(self.cb_wire), **kw)
        w = of_pacing._WALK.get()
        self.cb_walks.append(w.kind if w else None)
        p = self.cb_pages.pop(0) if self.cb_pages else {"list": []}
        if callable(p):
            p()
        return p


async def case_poll_wire_and_paging():
    aid = "cb_5"
    await _account(aid)
    other = _with(DISPUTE_B, user={"id": 1})   # unmatched filler
    fake = _Fake(cb_pages=[{"list": [DISPUTE_B] + [other] * 99, "marker": 1}, {"list": [other] * 100},
                           {"list": [other] * 3}])
    r = await cb.poll_chargebacks(aid, fake)
    assert r["items"] == 203 and r["unmatched"] == 203, r
    start, end = cb.poll_window(datetime.utcnow())
    assert fake.cb_wire == [{"limit": 100, "offset": o, "startDate": start, "endDate": end}
                            for o in (0, 100, 200)], fake.cb_wire
    assert fake.cb_walks == ["chargebacks"] * 3, fake.cb_walks
    capped = _Fake(cb_pages=[{"list": [other] * 100}] * 9)
    LOGS.lines.clear()
    r = await cb.poll_chargebacks(aid, capped)
    assert len(capped.cb_wire) == 5 and r["items"] == 500, (len(capped.cb_wire), r)
    assert LOGS.named("ingest_cb_page_cap") and LOGS.named("ingest_cb_poll"), LOGS.lines
    (poll,) = LOGS.named("ingest_cb_poll")
    assert LOGS.levels["ingest_cb_poll"] == logging.INFO and poll.endswith(
        "unmatched=500 ambiguous=0 already=0 pages=5 unmatched_sample="
        "1,2888,2026-10-28T20:00:19;1,2888,2026-10-28T20:00:19;1,2888,2026-10-28T20:00:19"), poll


ACCT = "cb_tick"


async def _scan_row(fully_backfilled: bool) -> None:
    async with get_session() as s:
        if await s.get(Account, ACCT) is None:
            s.add(Account(id=ACCT))
            s.add(Fan(account_id=ACCT, fan_id=FAN_B, lifetime_spend_cents=BASE_LIFETIME))
    async with get_session() as s:
        row = await s.get(TransactionScanHistory, ACCT)
        if row is None:
            row = TransactionScanHistory(account_id=ACCT)
            s.add(row)
        row.fully_backfilled = fully_backfilled
        row.backfill_floor = datetime(2026, 8, 1)
        row.current_status = "ok"
        row.consecutive_failures = 0
        row.paused_until = None


async def _tick(fake, mode):
    orig = ti._client_for
    ti._client_for = lambda _aid: fake
    try:
        return await ti.run_one_tick(ACCT, mode=mode)
    finally:
        ti._client_for = orig


async def case_tick_hook():
    await _scan_row(False)
    fake = _Fake(tx_pages=[{"list": [LEDGER_B | {"status": "done"}], "hasMore": False}],
                 cb_pages=[{"list": [DISPUTE_B]}])
    res = await _tick(fake, "backfill")
    assert res["error"] is None and res["rows_inserted"] == 1, res
    assert len(fake.cb_wire) == 1, "a completed backfill polls disputes"
    assert await _rows(ACCT) == [(LEDGER_B["id"], "chargedback", 2888)]
    assert await _lifetime(ACCT) == BASE_LIFETIME
    # recent: no disputes call
    await _scan_row(True)
    fake = _Fake(cb_pages=[{"list": [DISPUTE_B]}])
    assert (await _tick(fake, "recent"))["error"] is None
    assert fake.cb_wire == [], "recent ticks never poll disputes"
    # refresh polls; a disputes error is logged and the tick stays ok, streak 0;
    # a traceback only the first time for the account
    cb._error_traced.discard(ACCT)
    traced = []
    for _ in range(4):
        LOGS.lines.clear()
        LOGS.traced.clear()
        fake = _Fake(cb_pages=[lambda: (_ for _ in ()).throw(RuntimeError("OF 500 on chargebacks"))])
        res = await _tick(fake, "refresh")
        assert res["error"] is None, res
        assert len(fake.cb_wire) == 1 and LOGS.named("ingest_cb_error"), LOGS.lines
        traced.append(LOGS.traced[LOGS.lines.index(LOGS.named("ingest_cb_error")[0])])
    assert traced == [True, False, False, False], traced
    async with get_session() as s:
        row = await s.get(TransactionScanHistory, ACCT)
        assert (row.current_status, row.consecutive_failures, row.paused_until) == ("ok", 0, None), \
            (row.current_status, row.consecutive_failures, row.paused_until)


_harness.run()
