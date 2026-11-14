"""automations/full_ai_test.py — Full AI Chat's Test transport (Mode `test`).

The owner chats as a Fan on the Full AI Chat page; each side (checkpoint / draft) of a pair is
one session whose only store is its own Decision rows (`mode='test'`, `trigger_kind='test'`,
`trigger_key='test:<session>:<n>'`, the pair's negative Fan id). His line comes from the request,
her bubbles land on the row (`reply_json.parts`). There is no Fan row, message, transaction,
vault send, lease, DM rate or OF call: Test chat is off-site by design.

  test_fan_id(pair)            negative int from sha256 of the pair: never an OF fan id
  session_key(pair, side)      "<pair>-L" (checkpoint) | "<pair>-R" (draft)
  test_thread(rows)            pure: the session's rows as plain message rows; a PPV bubble is her
                               priced row (price, media count, paid flag, purchase time) (03b)
  owned_of / sent_media_of / bought_of / open_offer_of / offer_line / pending_offer_text
                               pure session folds (03b): what he owns, was sent, bought; the open
                               Offer and its Pending offer line
  session_rows(account, pair, side=None) / session_row(row)   the session read and its row shape
  fetch(account, pair, side, text, config) -> TurnFacts
  hold(config, anchor_key)     no-op returning wait_s, drawn per `session:n`; never sleeps
  send(row, parts, pick=None)  her bubbles onto the row's values, status `sent`; a Pick rides the
                               last text bubble as its PPV and onto the row's Offer columns (03b)
  offer_of(row)                the Offer a row (dict or AiDecision) carries, else None
  expect_n(facts, n)           Conflict(None) unless `n` is the Turn number `fetch` found
  record(row)                  INSERT when n == 1 + the session's row count, in one transaction
  settle(account, pair, side, row_id, outcome)   fake Buy / Decline: one guarded UPDATE of that
                               row's `outcome`, `outcome_at`, `join_src='test'`; `Unsettled` otherwise

Sends nothing: no direct import of an OF client, executor, lease, DM rate or OF write module (AST
scan + runtime send traps in test_full_ai_test_chat.py; shared helpers load them transitively).
"""
from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime
from types import SimpleNamespace
from typing import Literal

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError

from automations import _router_jev as router
from automations.full_ai_chat import build_state, cut_runs
from automations.full_ai_sell import Pick
from db.engine import get_session
from db.models import AiDecision
from isotime import iso_z

MODE = "test"
TRIGGER_KIND = "test"
JOIN_SRC = "test"                   # the Offer outcome's source: the owner's fake Buy / Decline
SIDES = {"checkpoint": "L", "draft": "R"}
# "0-15-60": most replies near 15 min, none past an hour (spec › Config v1 `reply_speed`).
_SPEEDS = {"0-2m": lambda r: r.uniform(0, 120), "0-15-60": lambda r: r.triangular(0, 3600, 900)}


class Conflict(Exception):
    """The Turn number is not the session's next one, or the Turn already has its row
    (`row_id`, None when there is none)."""

    def __init__(self, row_id: int | None):
        super().__init__(row_id)
        self.row_id = row_id


def test_fan_id(pair: str) -> int:
    return -(int.from_bytes(hashlib.sha256(pair.encode()).digest()[:7], "big") + 1)


def session_key(pair: str, side: str) -> str:
    return f"{pair}-{SIDES[side]}"


def _prefix(session: str) -> str:
    return f"test:{session}:"


def trigger_key(session: str, n: int) -> str:
    return f"{_prefix(session)}{int(n)}"


def _line(direction: str, text: str, at: datetime, mid: int) -> SimpleNamespace:
    """A plain message row with every attribute `_router_jev` reads; unpriced."""
    return SimpleNamespace(direction=direction, body=text, created_at=at, message_id=mid,
                           automation_kind=None, media_count=0, raw_json=None,
                           price_cents=None, is_paid=False, purchased_at=None)


def _priced(line: SimpleNamespace, r) -> SimpleNamespace:
    """`line` as her PPV message: the row's Offer price, its locked media count, paid when the
    row's outcome is `bought` (purchased at `outcome_at`), as a DB message reads after a purchase."""
    bought = r.outcome == "bought"
    line.price_cents = r.offer_price_cents
    line.media_count = len(_loads(r.offer_media_json).get("locked") or [])
    line.is_paid, line.purchased_at = bought, (r.outcome_at if bought else None)
    return line


def _loads(raw: str | None) -> dict:
    return json.loads(raw) if raw else {}


def _his_line(r) -> str | None:
    """His line of a test row: the last of `jev_json.state.fan_new_messages` (earlier ones belong
    to rows before it)."""
    his = (_loads(r.jev_json).get("state") or {}).get("fan_new_messages") or []
    return his[-1] if his else None


def _n(trigger_key: str) -> int:
    return int(trigger_key.rsplit(":", 1)[1])


def test_thread(rows) -> list[SimpleNamespace]:
    """The session's rows (oldest first) as plain chat rows: his line (the last of the row's
    `jev_json.state.fan_new_messages`; earlier ones belong to rows before it) then her bubbles
    (`reply_json.parts` with text); the bubble carrying a `ppv` is her priced message
    (`_priced`), so the Router's `_ppv` note reads as on a DB thread. Pure."""
    out: list[SimpleNamespace] = []
    for r in rows:
        his = _his_line(r)
        if his:
            out.append(_line("in", his, r.created_at, len(out) + 1))
        for p in _loads(r.reply_json).get("parts") or []:
            if p.get("text"):
                line = _line("out", p["text"], r.created_at, len(out) + 1)
                out.append(_priced(line, r) if p.get("ppv") and r.offer_price_cents else line)
    return out


# ── Session folds (03b): pure, over one session's rows oldest first ──

def _offers(rows) -> list:
    return [r for r in rows if r.offer_item_ref and r.offer_price_cents is not None]


def _media(r, *keys: str) -> set[int]:
    m = _loads(r.offer_media_json)
    return {int(x) for k in keys for x in m.get(k) or []}


def owned_of(rows) -> set[int]:
    """Owned media: the locked media of every bought Offer and every Free item (price 0). Raw
    ids: the Sell executor expands them through dupe groups (`full_ai_sell.pool`)."""
    return {x for r in _offers(rows) if r.outcome == "bought" or r.offer_price_cents == 0
            for x in _media(r, "locked")}


def sent_media_of(rows) -> set[int]:
    """Every media id an Offer showed him: locked, previews and Free items."""
    return {x for r in _offers(rows) for x in _media(r, "locked", "previews")}


def bought_of(rows) -> list[SimpleNamespace]:
    """His purchases, oldest first, shaped as the `PURCHASE_KINDS` rows `last_purchase` and the
    spend line read: a bought Offer is a `ppv_message` of its price at `outcome_at`."""
    return sorted((SimpleNamespace(kind="ppv_message", amount_cents=r.offer_price_cents,
                                   occurred_at=r.outcome_at)
                   for r in _offers(rows) if r.outcome == "bought"),
                  key=lambda b: b.occurred_at)


def open_offer_of(rows):
    """The newest priced Offer with no outcome, else None."""
    return next((r for r in reversed(_offers(rows)) if r.offer_price_cents > 0 and r.outcome is None), None)


def offer_line(r) -> SimpleNamespace | None:
    """Offer row `r` as the Pending offer message: the bubble its PPV rode, priced (`_priced`)."""
    if r is None:
        return None
    return next((m for m in reversed(test_thread([r])) if m.price_cents), None)


def pending_offer_text(rows) -> str:
    """The Pending offer as the Router states it (`_router_jev.pending_offer`): the open Offer's
    price and caption, else "none". (A Pending tease goes first once ticket 46 lands.)"""
    return router.pending_offer(offer_line(open_offer_of(rows)))


def _in_sessions(account_id: str, fan_id: int, prefixes) -> tuple:
    """The one definition of a session's rows: account, test Fan, Mode, trigger kind, key prefix."""
    return (AiDecision.account_id == str(account_id), AiDecision.fan_id == fan_id,
            AiDecision.mode == MODE, AiDecision.trigger_kind == TRIGGER_KIND,
            or_(*(AiDecision.trigger_key.startswith(p, autoescape=True) for p in prefixes)))


async def session_rows(account_id: str, pair: str, side: str | None = None) -> list[AiDecision]:
    """The pair's rows under `account_id` (one side, or both), oldest first."""
    prefixes = [_prefix(session_key(pair, x)) for x in ([side] if side else SIDES)]
    async with get_session() as s:
        return list((await s.execute(select(AiDecision).where(
            *_in_sessions(account_id, test_fan_id(pair), prefixes)).order_by(AiDecision.id))).scalars().all())


def session_row(r: AiDecision) -> dict:
    """One row as the session read returns it."""
    reply = _loads(r.reply_json)
    return {"row_id": r.id, "side": reply.get("side"), "n": _n(r.trigger_key), "text": _his_line(r),
            "parts": reply.get("parts") or [], "route": r.route, "heat": r.heat,
            "route_row": r.route_row, "writer": r.writer_model, "attempts": reply.get("attempts") or [],
            "wait_s": reply.get("wait_s"), "status": r.status, "fan_info": reply.get("fan_info") or {},
            "offer": offer_of(r), "created_at": iso_z(r.created_at)}


async def fetch(account: str, pair: str, side: str, text: str, config: dict):
    """The Turn of his line `text` on the session's next Turn number: his run (with any line
    left unanswered before it), the `THREAD_LINES` before it, and the session fold (`fan_info`,
    `asked`, `typo_state` from the newest row's `reply_json`; his last purchase, the Pending offer,
    Owned media and the bought list from the Offer columns, this session's rows only)."""
    from automations.full_ai_turn import TurnFacts
    rows = await session_rows(account, pair, side)
    lines = test_thread(rows)
    lines.append(_line("in", text, datetime.utcnow(), len(lines) + 1))
    cut, turn = cut_runs(lines, None)[-1]
    before = [m for m in lines if cut is not None and (m.created_at, m.message_id) <= cut]
    thread_rows = before[-router.THREAD_LINES:]
    spent, offer = bought_of(rows), offer_line(open_offer_of(rows))
    bought = spent[-1] if spent else None
    st, _ = build_state(turn, thread_rows, bought, offer)
    fold = _loads(rows[-1].reply_json) if rows else {}
    session = session_key(pair, side)
    return TurnFacts(
        account_id=str(account), fan_id=test_fan_id(pair), mode=MODE,
        anchor_key=trigger_key(session, len(rows) + 1), state=st, cut_rows=thread_rows + turn,
        bought=bought, offer=offer, fan_info=dict(fold.get("fan_info") or {}),
        asked=dict(fold.get("asked") or {}), config=config, side=side,
        typo_state=dict(fold.get("typo_state") or {}), owned=owned_of(rows), spent=spent)


def expect_n(facts, n: int) -> None:
    """The client's Turn number must be the one `fetch` found (1 + the session's row count)."""
    if _n(facts.anchor_key) != n:
        raise Conflict(None)


def hold(config: dict, anchor_key: str) -> float:
    """The reply wait the page shows, drawn from the side's reply speed seeded by `session:n`
    (replayable). Test never holds: the server never sleeps."""
    seed = anchor_key.removeprefix("test:")
    return round(_SPEEDS[config["reply_speed"]](random.Random(seed)), 1)


def send(row: dict, parts: list[str], pick: Pick | None = None) -> None:
    """Her bubbles onto the row about to be recorded; the row's `mode='test'` marks it a test row.
    A `pick` (`full_ai_sell.Pick`) rides the last bubble as `ppv: {ref, price_cents, media,
    previews}` and lands on the row's Offer columns (0120): price, list, media, item ref;
    `offer_message_id`, `outcome`, `outcome_at`, `join_src` stay NULL (no send, no settle yet).
    One call, one Pick: at most one priced Offer per row. A make_right row never carries a
    priced Offer (raises)."""
    reply = row["reply_json"]
    reply["parts"] = [{"text": p} for p in parts]
    if pick is not None and reply["parts"]:
        if row["route"] == "make_right" and pick.price_cents:
            raise AssertionError("make_right row with a priced Offer")
        reply["parts"][-1]["ppv"] = {"ref": pick.ref, "price_cents": pick.price_cents,
                                     "media": list(pick.media), "previews": list(pick.previews)}
        row.update(
            offer_price_cents=pick.price_cents, offer_list_cents=pick.list_cents,
            offer_media_json=json.dumps({"locked": list(pick.media), "previews": list(pick.previews)}),
            offer_item_ref=json.dumps({"ref": pick.ref, "subject": pick.subject, "format": pick.format,
                                       "lane": pick.lane, "kind": "offer"}))
    row["status"] = "sent"


def offer_of(r) -> dict | None:
    """The Offer a row carries (the row dict before or the AiDecision after its INSERT), as the
    turn response and the session read return it; None on a row with none.
    `refusal` is None on an Offer (a Refusal row has no Offer; its reason is `reply_json.refusal`)."""
    get = r.get if isinstance(r, dict) else (lambda k: getattr(r, k))
    if not get("offer_item_ref"):
        return None
    item, media = json.loads(get("offer_item_ref")), json.loads(get("offer_media_json") or "{}")
    return {"kind": item["kind"], "ref": item["ref"], "price_cents": get("offer_price_cents"),
            "list_cents": get("offer_list_cents"), "media": media.get("locked") or [],
            "previews": media.get("previews") or [], "refusal": None}


class Unsettled(Exception):
    """A settle that changed nothing, and why: `not_this_session` (404), `already_settled` (409,
    `outcome` the stored one) or `not_a_priced_offer` (422)."""

    def __init__(self, reason: str, outcome: str | None = None):
        super().__init__(reason)
        self.reason, self.outcome = reason, outcome


async def settle(account: str, pair: str, side: str, row_id: int,
                 outcome: Literal["bought", "declined"]) -> None:
    """Fake Buy / Decline on one of the session's rows: one UPDATE of `outcome`, `outcome_at`,
    `join_src='test'`, guarded by "a priced test Offer of this session with no outcome yet"
    (atomic, so a double click settles once). Any unsettled priced Offer of the session may be
    settled, not only the newest. Writes that row's three columns only. Raises `Unsettled`."""
    mine = _in_sessions(account, test_fan_id(pair), [_prefix(session_key(pair, side))])
    async with get_session() as s:
        res = await s.execute(update(AiDecision).where(
            AiDecision.id == row_id, *mine, AiDecision.outcome.is_(None),
            AiDecision.offer_price_cents > 0).values(
            outcome=outcome, outcome_at=datetime.utcnow(), join_src=JOIN_SRC))
        if res.rowcount == 1:
            return
        got = (await s.execute(select(AiDecision.outcome).where(
            AiDecision.id == row_id, *mine))).one_or_none()
    if got is None:
        raise Unsettled("not_this_session")
    if got.outcome is not None:
        raise Unsettled("already_settled", got.outcome)
    raise Unsettled("not_a_priced_offer")


async def record(row: dict) -> int:
    """INSERT the Turn's row when its Turn number is 1 + the session's row count, in one
    transaction. Raises `Conflict` otherwise, or on a replay that hits `uq_ai_decisions_turn`."""
    key = row["trigger_key"]
    prefix, n = key.rsplit(":", 1)[0] + ":", _n(key)
    values = dict(row, reply_json=json.dumps(row["reply_json"], ensure_ascii=False),
                  jev_json=json.dumps(row["jev_json"], ensure_ascii=False))
    async with get_session() as s:
        try:
            count = (await s.execute(select(func.count()).select_from(AiDecision).where(
                *_in_sessions(row["account_id"], row["fan_id"], [prefix])))).scalar_one()
            if n != count + 1:
                raise Conflict(await _existing(s, row))
            obj = AiDecision(**values)
            s.add(obj)
            await s.commit()
        except IntegrityError:
            await s.rollback()
            raise Conflict(await _existing(s, row)) from None
        return obj.id


async def _existing(s, row: dict) -> int | None:
    return (await s.execute(select(AiDecision.id).where(
        AiDecision.account_id == row["account_id"], AiDecision.fan_id == row["fan_id"],
        AiDecision.mode == MODE, AiDecision.trigger_key == row["trigger_key"]))).scalar_one_or_none()
