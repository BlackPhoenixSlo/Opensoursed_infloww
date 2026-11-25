from __future__ import annotations

import json
import logging

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from automation_registry import register
from automations import _router_jev as router
from automations import full_ai_photo
from automations.full_ai_config import loaded
from automations.full_ai_decide import SALT_VER, Facts, arm_of, decide_turn
from db.engine import get_session
from db.models import AccountAiConfig, AiDecision, Message, Transaction

log = logging.getLogger("of-relay.automation.full_ai_chat")

MODE = "shadow"
TRIGGER_KIND = "inbound"
STATUS = "planned"
CATCHUP_CAP = 20
_TURN_KEY = ["account_id", "fan_id", "mode", "trigger_key"]


def _before_or_at(created_at, message_id):
    return or_(Message.created_at < created_at,
               and_(Message.created_at == created_at, Message.message_id <= message_id))


def _after(created_at, message_id):
    return or_(Message.created_at > created_at,
               and_(Message.created_at == created_at, Message.message_id > message_id))


def _newest_out(chat, upto):
    return (select(Message.created_at, Message.message_id)
            .where(*chat, Message.direction == "out", upto)
            .order_by(Message.created_at.desc(), Message.message_id.desc()).limit(1))


async def decides(account_id: str, fan_id: int, payload: dict, message_id: int) -> bool:
    if payload.get("only_fan_ids") != [int(fan_id)] or payload.get("anchor") is None:
        return False
    chat = (Message.account_id == str(account_id), Message.fan_id == int(fan_id))
    async with get_session() as s:
        dm = await s.get(Message, (str(account_id), int(fan_id), int(message_id)))
        if dm is None:
            return False
        return (await s.execute(select(Message.message_id).where(
            *chat, Message.message_id == int(payload["anchor"]),
            _before_or_at(dm.created_at, dm.message_id)))).first() is not None


def cut_runs(rows, cut) -> list[tuple[tuple | None, list]]:
    runs: list[tuple[tuple | None, list]] = []
    turn: list = []
    for m in rows:
        if m.direction == "in":
            turn.append(m)
            continue
        if turn:
            runs.append((cut, turn))
            turn = []
        cut = (m.created_at, m.message_id)
    if turn:
        runs.append((cut, turn))
    return runs


def build_state(turn: list, thread_rows: list, bought, offer, *,
                pending: str | None = None, photos: bool = False) -> tuple[dict, bool]:
    router.read_photos([*turn, *thread_rows], photos)
    t0 = turn[0].created_at
    return router.state(
        [router.line_text(m) for m in turn],
        router.thread(thread_rows, t0), router.her_last_line(thread_rows),
        router.last_purchase(bought, t0),
        router.pending_offer(offer) if pending is None else pending), offer is not None


async def _state(s, account_id: str, fan_id: int, cut, turn: list[Message],
                 photos: bool = False) -> tuple[dict, bool]:
    thread_rows, offer, bought = await _reads(s, account_id, fan_id, cut, turn)
    return build_state(turn, thread_rows, bought, offer, photos=photos)


async def _reads(s, account_id: str, fan_id: int, cut, turn: list[Message]) -> tuple[list, Message | None, Transaction | None]:
    chat = (Message.account_id == account_id, Message.fan_id == fan_id)
    thread_rows, offer = [], None
    if cut is not None:
        thread_rows = list(reversed((await s.execute(
            select(Message)
            .where(*chat, Message.direction.in_(("in", "out")), _before_or_at(*cut))
            .order_by(Message.created_at.desc(), Message.message_id.desc())
            .limit(router.THREAD_LINES))).scalars().all()))
        offer = (await s.execute(
            select(Message)
            .where(*chat, Message.direction == "out", Message.price_cents > 0,
                   or_(Message.is_paid.is_(None), Message.is_paid.is_(False)),
                   Message.purchased_at.is_(None), Message.is_unsent.is_(False),
                   _before_or_at(*cut))
            .order_by(Message.created_at.desc(), Message.message_id.desc()).limit(1))).scalar_one_or_none()
    bought = (await s.execute(
        select(Transaction)
        .where(Transaction.account_id == account_id, Transaction.fan_id == fan_id,
               Transaction.kind.in_(router.PURCHASE_KINDS),
               Transaction.occurred_at <= turn[-1].created_at)
        .order_by(Transaction.occurred_at.desc(), Transaction.id.desc()).limit(1))).scalar_one_or_none()
    return thread_rows, offer, bought


async def _photos_on(account_id: str) -> bool:
    async with get_session() as s:
        row = await s.get(AccountAiConfig, str(account_id))
    got = loaded(row.full_ai_config_json if row is not None else None)
    if got is None:
        log.warning("full_ai bad stored config account=%s: describe_fan_photos off", account_id)
        return False
    return bool(got["checkpoint"][full_ai_photo.KEY])


async def _read(account_id: str, fan_id: int, anchor_id: int, photos: bool = False
                ) -> list[tuple[Message, dict, bool, dict | None]] | None:
    async with get_session() as s:
        first = await s.get(Message, (str(account_id), int(fan_id), int(anchor_id)))
        if first is None:
            return None
        chat = (Message.account_id == str(account_id), Message.fan_id == int(fan_id))
        cut = (await s.execute(_newest_out(chat, _before_or_at(first.created_at, first.message_id)))).first()
        q = select(Message).where(*chat, Message.direction.in_(("in", "out")))
        if cut is not None:
            q = q.where(_after(*cut))
        runs = cut_runs((await s.execute(q.order_by(Message.created_at, Message.message_id))).scalars(), cut)
        decided = set((await s.execute(
            select(AiDecision.trigger_key).where(
                AiDecision.account_id == str(account_id), AiDecision.fan_id == int(fan_id),
                AiDecision.mode == MODE,
                AiDecision.trigger_key.in_([str(t[-1].message_id) for _, t in runs])))).scalars())
        return [(t[-1], *await _state(s, str(account_id), int(fan_id), c, t, photos),
                 await full_ai_photo.describe_turn(str(account_id), t, None) if photos else None)
                for c, t in runs if str(t[-1].message_id) not in decided]


async def _record(account_id: str, fan_id: int, anchor: Message, st: dict, has_offer: bool,
                  jev: router.Answers | str, photo: dict | None = None) -> tuple[int | None, str, str, int | None]:
    if isinstance(jev, str):
        fired, intensity, answers, score, model, ms, error = frozenset(), 0.0, None, None, None, None, jev
    else:
        fired, intensity, answers = router.fired(jev.answers), jev.intensity, jev.answers
        score, model, ms, error = {"score": jev.intensity, "p": jev.intensity_p}, jev.model, jev.ms, None
    d = decide_turn(Facts(fired=fired, intensity=intensity, pending_offer=has_offer,
                          pending_tease=False, jev_ok=error is None))
    jev_json = {"answers": answers, "intensity": score, "fired": sorted(fired), "state": st}
    if photo is not None:
        jev_json["photo"] = photo
    async with get_session() as s:
        row_id = (await s.execute(
            sqlite_insert(AiDecision).values(
                account_id=str(account_id), fan_id=int(fan_id), mode=MODE,
                trigger_kind=TRIGGER_KIND, trigger_key=str(anchor.message_id),
                anchor_message_id=anchor.message_id, anchor_created_at=anchor.created_at,
                arm=arm_of(str(account_id), int(fan_id)), salt_ver=SALT_VER,
                route=d.route, heat=d.heat, route_row=d.row,
                question_version=router.QUESTION_VERSION, router_model=model,
                writer_model=None, jev_json=json.dumps(jev_json, ensure_ascii=False),
                jev_ms=ms, jev_error=error, status=STATUS)
            .on_conflict_do_nothing(index_elements=_TURN_KEY)
            .returning(AiDecision.id))).scalar_one_or_none()
    return row_id, d.route, d.row, ms


@register("full_ai_chat")
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    """Catch up the one Fan in `payload["only_fan_ids"]`: decide and record,
    oldest first, every Turn from the run holding `payload["anchor"]` forward
    whose Anchor has no row yet, one Jev call each, at most `CATCHUP_CAP`. Stats: recorded, duplicate
    (an insert that lost the Turn key to a racing job), one entry per row written and `capped` (Turns
    left undecided, when any); or `skipped` with why nothing was decided."""
    from automations import full_ai_live
    if await full_ai_live.live_rule(account_id) is not None:
        return await full_ai_live.run(account_id, payload, run_id=run_id)
    if payload.get("anchor") is None:
        return {"skipped": "unanchored"}
    fan_id = int(payload["only_fan_ids"][0])
    recorded, duplicate, rows = 0, 0, []
    try:
        turns = await _read(account_id, fan_id, int(payload["anchor"]), await _photos_on(account_id))
        if turns is None:
            return {"skipped": "anchor_missing"}
        if not turns:
            return {"skipped": "duplicate_turn"}
        capped = max(0, len(turns) - CATCHUP_CAP)
        for anchor, st, has_offer, photo in turns[:CATCHUP_CAP]:
            try:
                jev: router.Answers | str = await router.ask(st, account_id)
            except router.GateError as e:
                jev = str(e) or type(e).__name__
            row_id, route, row, ms = await _record(account_id, fan_id, anchor, st, has_offer, jev, photo)
            if row_id is None:
                duplicate += 1
                continue
            recorded += 1
            log.info("full_ai_turn account=%s fan=%s route=%s row=%s jev_ms=%s",
                     account_id, fan_id, route, row, ms)
            rows.append({"row_id": row_id, "route": route, "jev_ms": ms})
    except Exception:
        log.warning("full_ai_turn_failed account=%s fan=%s", account_id, fan_id, exc_info=True)
        raise
    return {"recorded": recorded, "duplicate": duplicate, "rows": rows, **({"capped": capped} if capped else {})}
