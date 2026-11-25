from __future__ import annotations

import asyncio
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
from automations.full_ai_mode import full
from automations.full_ai_photo import KEY as PHOTOS_KEY
from automations.full_ai_scene import saved_scene, scene_words
from automations.full_ai_sell import Pick, Teased, _money
from db.engine import get_session
from db.models import AiDecision
from isotime import iso_z

MODE = "test"
TRIGGER_KIND = "test"
JOIN_SRC = "test"
TEASE_TTL_S = 900
SIDES = {"checkpoint": "L", "draft": "R"}
_SPEEDS = {"0-2m": lambda r: r.uniform(0, 120), "0-15-60": lambda r: r.triangular(0, 3600, 900)}
_SETTLE_LOCKS: dict[str, asyncio.Lock] = {}


class Conflict(Exception):

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


def _line(direction: str, text: str, at: datetime, mid: int, photo: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(direction=direction, body=text, created_at=at, message_id=mid,
                           automation_kind=None, media_count=1 if photo else 0, raw_json=None,
                           price_cents=None, is_paid=False, purchased_at=None,
                           image_desc=(photo or {}).get("desc"))


def _priced(line: SimpleNamespace, r) -> SimpleNamespace:
    bought = r.outcome == "bought"
    line.price_cents = r.offer_price_cents
    line.media_count = len(_loads(r.offer_media_json).get("locked") or [])
    line.is_paid, line.purchased_at = bought, (r.outcome_at if bought else None)
    return line


def _loads(raw: str | None) -> dict:
    return json.loads(raw) if raw else {}


def _his_line(r) -> str | None:
    his = (_loads(r.jev_json).get("state") or {}).get("fan_new_messages") or []
    return his[-1] if his else None


def _test_photo(reply: dict) -> dict | None:
    photo = reply.get("fan_photo")
    return photo if photo and "text" in photo else None


def _n(trigger_key: str) -> int:
    return int(trigger_key.rsplit(":", 1)[1])


def test_thread(rows) -> list[SimpleNamespace]:
    out: list[SimpleNamespace] = []
    for r in rows:
        photo = _test_photo(_loads(r.reply_json))
        his = photo["text"] if photo else _his_line(r)
        if his or photo:
            out.append(_line("in", his, r.created_at, len(out) + 1, photo))
        for p in _loads(r.reply_json).get("parts") or []:
            if p.get("text"):
                line = _line("out", p["text"], r.created_at, len(out) + 1)
                out.append(_priced(line, r) if p.get("ppv") and r.offer_price_cents else line)
            elif p.get("gif"):
                line = _line("out", "", r.created_at, len(out) + 1)
                line.raw_json = json.dumps({"giphyId": p["gif"], "media": []})
                out.append(line)
    return out



def _offers(rows) -> list:
    return [r for r in rows if r.offer_item_ref and r.offer_price_cents is not None]


def _media(r, *keys: str) -> set[int]:
    m = _loads(r.offer_media_json)
    return {int(x) for k in keys for x in m.get(k) or []}


def owned_of(rows) -> set[int]:
    return {x for r in _offers(rows) if r.outcome == "bought" or r.offer_price_cents == 0
            for x in _media(r, "locked")}


def sent_media_of(rows) -> set[int]:
    return {x for r in _offers(rows) for x in _media(r, "locked", "previews")}


def bought_of(rows) -> list[SimpleNamespace]:
    return sorted((SimpleNamespace(kind="ppv_message", amount_cents=r.offer_price_cents,
                                   occurred_at=r.outcome_at)
                   for r in _offers(rows) if r.outcome == "bought"),
                  key=lambda b: b.occurred_at)


def purchases_of(rows) -> list[str]:
    out = []
    settled = [r for r in _offers(rows)
               if r.outcome in ("bought", "declined") and r.offer_price_cents]
    for r in sorted(settled, key=lambda r: r.outcome_at):
        item = _loads(r.offer_item_ref)
        n, kind = len(_media(r, "locked")), item.get("format") or "item"
        what = f"{n} {kind}{'s' if n != 1 else ''}"
        price = _money(r.offer_price_cents)
        line = (f"bought {what} for {price} (lane {item.get('lane')})" if r.outcome == "bought"
                else f"said no to {what} at {price}")
        out.append(f"{line}: {item['desc']}" if item.get("desc") else line)
    return out


SITTING_GAP_S = 120 * 60
UNASKED_ROWS = ("offer_moment", "scene_offer", "chat_tease")
TEASE_ROW = "chat_tease"
NO_TEASES = "none yet"


def is_tease(r) -> bool:
    if r.route_row == TEASE_ROW:
        return True
    return (_loads(getattr(r, "reply_json", None)).get("chat_tease") or {}).get("cents") is not None


NO_LIKES = "nothing stored yet"


def likes_of(fan_info: dict) -> str:
    v = fan_info.get("fetishes")
    return (v.strip()[:200] if isinstance(v, str) else "") or NO_LIKES


def _sitting(rows, now: datetime) -> list:
    points = [r.created_at for r in rows] + [now]
    start = next((i for i in range(len(rows), 0, -1)
                  if (points[i] - points[i - 1]).total_seconds() > SITTING_GAP_S), 0)
    return rows[start:]


DARED_ROWS = 3
_READ_OUTCOMES = ("described", "cached")


def dare_due_of(rows, now: datetime | None = None) -> bool:
    return (bool(rows) and _joke(rows[-1]) and bool(_sitting(rows, now or datetime.utcnow()))
            and not any(_joke(r) for r in rows[-1 - DARED_ROWS:-1]))


def dared_of(rows) -> bool:
    return any(_carried(rows[j]) and dare_due_of(rows[:j], rows[j].created_at)
               for j in range(max(1, len(rows) - DARED_ROWS), len(rows)))


def looks_of(rows, now: datetime | None = None) -> bool:
    return dared_of(rows) or dare_due_of(rows, now)


def _photo_read(r) -> bool:
    p = _loads(r.reply_json).get("fan_photo") or {}
    return bool(p.get("read")) if "text" in p else p.get("outcome") in _READ_OUTCOMES


def _joke(r) -> bool:
    return r.route == "ai_dare" and r.status == "sent" and not _photo_read(r)


def _carried(r) -> bool:
    if r.status != "sent" or r.route_row == "offer_details":
        return False
    if r.route == "ai_dare":
        return not _photo_read(r)
    return r.route in ("chat", "sext") and not _loads(r.reply_json).get("fan_photo")


def _his_lines(rows) -> int:
    return sum(m.direction == "in" for m in test_thread(rows))


def spacing_of(rows, now: datetime, free: bool = False) -> dict:
    sitting = _sitting(rows, now)
    priced = {id(r) for r in _offers(sitting) if r.offer_price_cents > 0}
    pieces = [i for i, r in enumerate(sitting) if id(r) in priced]
    sent = {id(r) for r in _offers(sitting) if free and r.offer_price_cents == 0
            and is_tease(r)} | priced
    last = [i for i, r in enumerate(sitting) if id(r) in sent]
    lines: int | str = "no piece yet"
    if last:
        lines = _his_lines(sitting[last[-1] + 1:]) + 1
    unasked = sum(sitting[i].route_row in UNASKED_ROWS for i in pieces)
    return dict(zip(router.SPACING_STATE_KEYS, (lines, len(pieces), unasked)))


_TEASE_OUTCOME = {"bought": "he bought it", "declined": "he said no", None: "he did not buy it"}


def teases_sent_of(rows) -> list[str] | str:
    out = []
    for r in _offers(rows):
        if not is_tease(r):
            continue
        if not r.offer_price_cents:
            out.append("free photo")
            continue
        what = "photo" if len(_media(r, "locked")) == 1 else "photo set"
        out.append(f"{_money(r.offer_price_cents)} {what}, {_TEASE_OUTCOME.get(r.outcome, _TEASE_OUTCOME[None])}")
    return out or NO_TEASES


def chat_tease_of(rows, now: datetime) -> dict:
    return dict(zip(router.TEASE_STATE_KEYS, (_his_lines(_sitting(rows, now)) + 1, teases_sent_of(rows))))


def open_offers_of(rows) -> list:
    over = {_loads(r.offer_item_ref).get("over") for r in _offers(rows)}
    owned = owned_of(rows)
    return [r for r in _offers(rows) if r.offer_price_cents > 0 and r.outcome is None
            and r.id not in over and not _media(r, "locked") <= owned]


def open_offer_of(rows):
    opened = open_offers_of(rows)
    return opened[-1] if opened else None


def offer_line(r) -> SimpleNamespace | None:
    if r is None:
        return None
    return next((m for m in reversed(test_thread([r])) if m.price_cents), None)


def pending_tease_of(rows, now: datetime, ttl_s: float = TEASE_TTL_S):
    r = next((x for x in reversed(rows) if x.status == "sent" and x.route_row != "offer_details"), None)
    if r is None:
        return None
    if not (full(r.mode) and r.offer_price_cents is None
            and _loads(r.offer_item_ref).get("kind") == "tease"):
        return None
    if (now - r.created_at).total_seconds() > ttl_s:
        return None
    if any(x.outcome_at is not None and x.outcome_at > r.created_at for x in rows):
        return None
    return r


def tease_bubble_ids(rows, tease) -> set:
    held = [r for r in rows if r.route_row == "offer_details" and _loads(r.reply_json).get("held_tease") == tease.id]
    return {p.get("message_id") for r in (tease, *held) for p in _loads(r.reply_json).get("parts") or []}


def teased_of(r) -> Teased | None:
    if r is None:
        return None
    ref = _loads(r.offer_item_ref)
    return Teased(ref["subject"], ref["format"], tuple(sorted(_media(r, "locked"))),
                  tuple(sorted(_media(r, "previews"))), r.offer_list_cents, r.id)


def pending_offer_text(rows, now: datetime) -> str:
    tease = pending_tease_of(rows, now)
    if tease is not None:
        return " ".join(p["text"] for p in _loads(tease.reply_json).get("parts") or [] if p.get("text"))
    return router.pending_offer(offer_line(open_offer_of(rows)))


def _in_sessions(account_id: str, fan_id: int, prefixes) -> tuple:
    return (AiDecision.account_id == str(account_id), AiDecision.fan_id == fan_id,
            AiDecision.mode == MODE, AiDecision.trigger_kind == TRIGGER_KIND,
            or_(*(AiDecision.trigger_key.startswith(p, autoescape=True) for p in prefixes)))


async def session_rows(account_id: str, pair: str, side: str | None = None) -> list[AiDecision]:
    prefixes = [_prefix(session_key(pair, x)) for x in ([side] if side else SIDES)]
    async with get_session() as s:
        return list((await s.execute(select(AiDecision).where(
            *_in_sessions(account_id, test_fan_id(pair), prefixes)).order_by(AiDecision.id))).scalars().all())


def session_row(r: AiDecision) -> dict:
    reply = _loads(r.reply_json)
    caption = {"caption": reply["caption"]} if reply.get("caption") else {}
    photo = _test_photo(reply)
    return {"row_id": r.id, "side": reply.get("side"), "n": _n(r.trigger_key),
            "text": photo["text"] if photo else _his_line(r), "photo": photo,
            "parts": reply.get("parts") or [], "route": r.route, "heat": r.heat,
            "route_row": r.route_row, "writer": r.writer_model, "attempts": reply.get("attempts") or [],
            "wait_s": reply.get("wait_s"), "status": r.status, "fan_info": reply.get("fan_info") or {},
            "offer": offer_of(r), "created_at": iso_z(r.created_at), **caption,
            **{k: reply[k] for k in ("scene", "price", "dropped_reason", "heat_check", "reply_to_n")
               if reply.get(k)}}


async def fetch(account: str, pair: str, side: str, text: str, config: dict, photo: dict | None = None,
                *, reply_to_n: int | None = None):
    from automations.full_ai_offer_details import session_ask
    from automations.full_ai_turn import TurnFacts
    rows = await session_rows(account, pair, side)
    lines, now = test_thread(rows), datetime.utcnow()
    lines.append(_line("in", text, now, len(lines) + 1, photo))
    cut, turn = cut_runs(lines, None)[-1]
    before = [m for m in lines if cut is not None and (m.created_at, m.message_id) <= cut]
    thread_rows = before[-router.THREAD_LINES:]
    open_offer = open_offer_of(rows)
    spent, offer = bought_of(rows), offer_line(open_offer)
    bought = spent[-1] if spent else None
    dared, due = dared_of(rows), dare_due_of(rows, now)
    on = dared or due or bool(config[PHOTOS_KEY])
    st, _ = build_state(turn, thread_rows, bought, offer, pending=pending_offer_text(rows, now), photos=on)
    fold = _loads(rows[-1].reply_json) if rows else {}
    scene = saved_scene(rows, now, SITTING_GAP_S)
    if config.get("sext_scene"):
        st = {**st, "purchases": purchases_of(rows), "scene": scene_words(scene)}
    tease = bool(config.get("chat_tease"))
    if config.get("sell_spacing") or tease:
        st = {**st, **spacing_of(rows, now, free=tease)}
    if tease:
        st = {**st, **chat_tease_of(rows, now)}
    if config.get("he_likes"):
        st = {**st, "he_likes": likes_of(fold.get("fan_info") or {})}
    session = session_key(pair, side)
    return TurnFacts(
        account_id=str(account), fan_id=test_fan_id(pair), mode=MODE,
        anchor_key=trigger_key(session, len(rows) + 1), state=st, cut_rows=thread_rows + turn,
        bought=bought, offer=offer, fan_info=dict(fold.get("fan_info") or {}),
        asked=dict(fold.get("asked") or {}), config=config, side=side,
        typo_state=dict(fold.get("typo_state") or {}), owned=owned_of(rows), spent=spent,
        sent=sent_media_of(rows), tease=teased_of(pending_tease_of(rows, now)),
        offer_piece=teased_of(open_offer), scene=scene,
        photo={**photo, "text": text, "read": bool(on and photo.get("desc"))} if photo else None,
        dared=dared, dare_due=due,
        purchases=purchases_of(rows) if tease else [],
        offer_ask=session_ask(rows, now, pending_tease_of(rows, now), turn, reply_to_n))


def expect_n(facts, n: int) -> None:
    if _n(facts.anchor_key) != n:
        raise Conflict(None)


def hold(config: dict, anchor_key: str) -> float:
    seed = anchor_key.removeprefix("test:")
    return round(_SPEEDS[config["reply_speed"]](random.Random(seed)), 1)


def send(row: dict, parts: list[str], pick: Pick | None = None, *, over: int | None = None,
         desc: str | None = None) -> None:
    reply = row["reply_json"]
    reply["parts"] = [{"text": p} for p in parts]
    if pick is not None and reply["parts"]:
        if row["route"] == "make_right" and pick.price_cents:
            raise AssertionError("make_right row with a priced Offer")
        tease = row["route"] == "tease"
        kind = "tease" if tease else "free" if row["route"] == "make_right" or not pick.price_cents else "offer"
        if not tease:
            reply["parts"][-1]["ppv"] = {"ref": pick.ref, "price_cents": pick.price_cents,
                                         "media": list(pick.media), "previews": list(pick.previews)}
        row.update(
            offer_price_cents=None if tease else pick.price_cents, offer_list_cents=pick.list_cents,
            offer_media_json=json.dumps({"locked": list(pick.media), "previews": list(pick.previews),
                                         "items": list((pick.facts or {}).get("media") or [])}),
            offer_item_ref=json.dumps({"ref": pick.ref, "subject": pick.subject, "format": pick.format,
                                       "lane": pick.lane, "kind": kind,
                                       **({"over": over} if over is not None else {}),
                                       **({"desc": desc[:120]} if desc else {})}))
    row["status"] = "sent"


def offer_of(r) -> dict | None:
    get = r.get if isinstance(r, dict) else (lambda k: getattr(r, k))
    if not get("offer_item_ref"):
        return None
    item, media = json.loads(get("offer_item_ref")), json.loads(get("offer_media_json") or "{}")
    return {"kind": item["kind"], "ref": item["ref"], "price_cents": get("offer_price_cents"),
            "list_cents": get("offer_list_cents"), "media": media.get("locked") or [],
            "previews": media.get("previews") or [], "items": media.get("items") or [], "refusal": None}


class Unsettled(Exception):

    def __init__(self, reason: str, outcome: str | None = None):
        super().__init__(reason)
        self.reason, self.outcome = reason, outcome


async def settle(account: str, pair: str, side: str, row_id: int,
                 outcome: Literal["bought", "declined"]) -> None:
    async with _SETTLE_LOCKS.setdefault(str(account), asyncio.Lock()):
        await _settle(account, pair, side, row_id, outcome)


async def _settle(account: str, pair: str, side: str, row_id: int,
                  outcome: Literal["bought", "declined"]) -> None:
    mine = _in_sessions(account, test_fan_id(pair), [_prefix(session_key(pair, side))])
    async with get_session() as s:
        if outcome == "bought":
            rows = (await s.execute(select(AiDecision).where(*mine))).scalars().all()
            row = next((r for r in rows if r.id == row_id), None)
            if (row is not None and row.outcome is None and (row.offer_price_cents or 0) > 0
                    and set(_media(row, "locked")) & owned_of([r for r in rows if r.id != row_id])):
                raise Unsettled("already_owned")
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


async def _send_io(row: dict, parts: list[str], pick: Pick | None = None, *, over: int | None = None,
                   desc: str | None = None, gif: dict | None = None) -> None:
    send(row, parts, pick, over=over, desc=desc)
    if gif:
        row["reply_json"]["parts"].append(gif)


def __getattr__(name: str):
    if name == "IO":
        from automations.full_ai_turn import TurnIO
        io = globals()["IO"] = TurnIO(TRIGGER_KIND, hold, _send_io, record)
        return io
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
