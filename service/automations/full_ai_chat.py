"""automations/full_ai_chat.py — Full AI Chat's shadow runner (kind `full_ai_chat`).

Shadow mode: decide and record, send nothing (ADR-0033). A job is queued by
W7's full_ai hook (`webhook_dispatch._full_ai_hook`) for one Fan, anchored on
his DM, and is a catch-up for that Fan: from the run holding its anchor
forward, oldest first, every run whose Anchor (its last inbound row) has no row
yet is one Turn. For each, the runner reads his Turn (his run of messages since
her newest outbound, up to the Anchor), the `THREAD_LINES` lines before it, her
last line, his last purchase and the Pending offer from the DB, rows created
at or before that Anchor (a row's paid flags as they stand now), asks Jev every Router question in one
request (`_router_jev.ask`, with no DB connection held), maps the answers
through the pure Route table (`full_ai_decide.decide_turn`) and INSERTs one
Decision row (`ai_decisions`, ON CONFLICT DO NOTHING on the Turn key, so a
retry redoes only the Turns still without a row), carrying the Fan's Arm
(`arm_of`; Shadow writes no Enrolment). A Jev failure (`GateError`) is a row
too, route chat at Heat 1 (row `jev_failed`) with the error, never a no_send,
and the catch-up goes on. Those rows are all it writes. Cutting runs into
Turns (`cut_runs`) and mapping read rows to the Jev state (`build_state`) are
pure, apart from the SQL that reads them. With the checkpoint's
`describe_fan_photos` on, his photos read `[he sent: …]` from descriptions
already cached (`full_ai_photo`; Shadow describes none: no OF client) and the
row records `photo`.

It has no send path by construction: it imports no OF client, no outbound
helper, no executor and no lease module, and names no client factory, send,
lease or cooldown function (test_full_ai_shadow.py, no-send (a) to (c)).
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from automation_registry import register
from automations import _router_jev as router
from automations import full_ai_photo
from automations.full_ai_config import merged
from automations.full_ai_decide import SALT_VER, Facts, arm_of, decide_turn
from db.engine import get_session
from db.models import AccountAiConfig, AiDecision, Message, Transaction

log = logging.getLogger("of-relay.automation.full_ai_chat")

MODE = "shadow"
TRIGGER_KIND = "inbound"
STATUS = "planned"      # Shadow rows are a plan never executed; they never move
_TURN_KEY = ["account_id", "fan_id", "mode", "trigger_key"]


def _before_or_at(created_at, message_id):
    """Messages at or before (created_at, message_id) in chat order."""
    return or_(Message.created_at < created_at,
               and_(Message.created_at == created_at, Message.message_id <= message_id))


def _after(created_at, message_id):
    return or_(Message.created_at > created_at,
               and_(Message.created_at == created_at, Message.message_id > message_id))


def _newest_out(chat, upto):
    """Her newest outbound at or before `upto`, from any sender or Lane, as
    (created_at, message_id): where a Turn is cut. `system` rows are not chat lines."""
    return (select(Message.created_at, Message.message_id)
            .where(*chat, Message.direction == "out", upto)
            .order_by(Message.created_at.desc(), Message.message_id.desc()).limit(1))


async def decides(account_id: str, fan_id: int, payload: dict, message_id: int) -> bool:
    """Whether a job with `payload` decides the Turn of Fan `fan_id`'s DM
    `message_id` (W7's hook folds such a DM into it). Its walk starts at her
    newest outbound before its anchor, so it does when it is this Fan's one-Fan
    job and its anchor sorts at or before the DM in chat order. False for a job
    with no anchor (it decides nothing), a row missing from `messages`, or a DM
    older than the anchor (a WS replay), which may sit before the walk."""
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
    """The Fan's runs in `rows` (chat rows, oldest first, each with `.direction`,
    `.created_at`, `.message_id`), as (cut, turn): `cut` the outbound before the
    run as (created_at, message_id), the starting `cut` (her outbound before
    `rows`, None for none) for a first run before any outbound in `rows`, `turn`
    its inbound rows. A trailing outbound opens no run. Pure."""
    # The one Turn definition: runs are cut at each outbound row, each run is
    # (the outbound before it, its inbound rows), its last inbound the Anchor.
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
    """The Jev state of one Turn and whether it has a Pending offer, from rows
    already read: his run `turn`, the lines before it `thread_rows` (oldest
    first), his last purchase `bought` (a `PURCHASE_KINDS` row or None) and the
    Pending offer `offer` (or None). `pending`, when given, is the state's
    `pending_offer` as already stated (test: `full_ai_test.pending_offer_text`,
    a Pending tease first); else it is `offer`'s line. Pure: attribute reads
    only, so rows from any source with `Message`/`Transaction`'s fields work.
    `photos` (the side's `describe_fan_photos`) switches the `[he sent: …]` tag
    on these rows (`router.read_photos`); the Writer reads the same rows."""
    # ASSUMPTION: paid flags are read as of decide time, as the probe's sampler
    # did (sampler.py:68); overturned if catch-up rows show it.
    # ASSUMPTION: the probe's clock: every age (each line's `when`, his last
    # purchase) is from his Turn's first message, as probe.py measured it
    # (sampler `t0`). Overturned if rows show long Turns misread as "minutes before".
    router.read_photos([*turn, *thread_rows], photos)
    t0 = turn[0].created_at
    return router.state(
        [router.line_text(m) for m in turn],
        router.thread(thread_rows, t0), router.her_last_line(thread_rows),
        router.last_purchase(bought, t0),
        router.pending_offer(offer) if pending is None else pending), offer is not None


async def _state(s, account_id: str, fan_id: int, cut, turn: list[Message],
                 photos: bool = False) -> tuple[dict, bool]:
    """The Jev state of one Turn and whether it has a Pending offer
    (`build_state`), read in session `s`: the `THREAD_LINES` lines at or before
    `cut` (her outbound that opened the run, None for none), the Pending offer
    among them, and his last purchase at or before its Anchor (`turn[-1]`):
    only rows created at or before that Anchor, their paid flags (`is_paid`,
    `purchased_at`) as they stand at decide time."""
    chat = (Message.account_id == account_id, Message.fan_id == fan_id)
    thread_rows, offer = [], None
    if cut is not None:
        thread_rows = list(reversed((await s.execute(
            select(Message)
            .where(*chat, Message.direction.in_(("in", "out")), _before_or_at(*cut))
            .order_by(Message.created_at.desc(), Message.message_id.desc())
            .limit(router.THREAD_LINES))).scalars().all()))
        # The Pending offer stand-in: her newest priced, unbought, not-unsent
        # outbound before his Turn, from any Lane or a human, of any age.
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
    return build_state(turn, thread_rows, bought, offer, photos=photos)


async def _photos_on(account_id: str) -> bool:
    """The checkpoint's `describe_fan_photos` (Shadow reads no other config: route flags all on)."""
    async with get_session() as s:
        row = await s.get(AccountAiConfig, str(account_id))
    raw = row.full_ai_config_json if row is not None else None
    return bool(merged(json.loads(raw) if raw else {})["checkpoint"][full_ai_photo.KEY])


async def _read(account_id: str, fan_id: int, anchor_id: int, photos: bool = False
                ) -> list[tuple[Message, dict, bool, dict | None]] | None:
    """The catch-up's one read session: every undecided Turn of the Fan from
    the run holding the payload anchor forward, oldest first, each as its
    Anchor, Jev state, whether it has a Pending offer and its photo record
    (`full_ai_photo.describe_turn` with no client: cached only; None with
    `photos` off). None when the payload anchor is not in `messages`."""
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
    """INSERT the Turn's Decision row from Jev's answers, or from the error text
    of a failed call. Returns (row id or None, Route, row, Jev ms)."""
    if isinstance(jev, str):
        # ASSUMPTION: a Jev-failed row keeps jev_json's shape with answers and
        # intensity null and nothing fired, so SQL and replay read one shape.
        # Overturned if the page or WATCH wants failed rows' jev_json NULL.
        fired, intensity, answers, score, model, ms, error = frozenset(), 0.0, None, None, None, None, jev
    else:
        fired, intensity, answers = router.fired(jev.answers), jev.intensity, jev.answers
        score, model, ms, error = {"score": jev.intensity, "p": jev.intensity_p}, jev.model, jev.ms, None
    # Shadow sends no tease, so no Pending tease exists there (ADR-0033); route flags all on.
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
    whose Anchor has no row yet, one Jev call each. Stats: recorded, duplicate
    (an insert that lost the Turn key to a racing job) and one entry per row
    written; or `skipped` with why nothing was decided."""
    if payload.get("anchor") is None:       # the rule's interval tick, a Run-now
        return {"skipped": "unanchored"}
    fan_id = int(payload["only_fan_ids"][0])
    recorded, duplicate, rows = 0, 0, []
    try:
        turns = await _read(account_id, fan_id, int(payload["anchor"]), await _photos_on(account_id))
        if turns is None:
            return {"skipped": "anchor_missing"}
        if not turns:
            return {"skipped": "duplicate_turn"}
        for anchor, st, has_offer, photo in turns:
            try:
                jev: router.Answers | str = await router.ask(st, account_id)   # no DB connection held
            except router.GateError as e:                   # never a "no": chat, Heat 1
                jev = str(e) or type(e).__name__
            row_id, route, row, ms = await _record(account_id, fan_id, anchor, st, has_offer, jev, photo)
            if row_id is None:
                duplicate += 1
                continue
            recorded += 1
            # ASSUMPTION: `row=` is the Route table row that matched, as `row` is in
            # the page's read (spec › full_ai_api); the row id is in the stats.
            # Overturned if the WATCH check wants the id there.
            log.info("full_ai_turn account=%s fan=%s route=%s row=%s jev_ms=%s",
                     account_id, fan_id, route, row, ms)
            rows.append({"row_id": row_id, "route": route, "jev_ms": ms})
    except Exception:
        log.warning("full_ai_turn_failed account=%s fan=%s", account_id, fan_id, exc_info=True)
        raise
    return {"recorded": recorded, "duplicate": duplicate, "rows": rows}
