from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

import llm_client
from auth import assert_account_owned, clamp_account_filter
from automations import _customs
from customs_decide import (
    _Msg, _whole_messages, blast_counts, brief_msgs, brief_skip_reason, is_his_line,
    order_span,
)
from db.engine import get_session
from db.models import Account, AutomationRule, Fan, Message, Transaction

_REVIEW_DAYS = 60

# Symmetric 100 each side (operator spec); `before` must never be the small side: the ask sits in the run-up behind the tip that paid for it.
_BRIEF_BEFORE = 100
_BRIEF_AFTER = 100

# Backstop for a pathological thread, sized above the window: at 60 it dropped the message that WAS the order.
_BRIEF_MAX_LINES = 400

log = logging.getLogger("of-relay.customs_api")

router = APIRouter()




def _order_tips_q(*conditions):
    # The column tuple and occurred_at DESC are a contract (orders_per_fan/bursts_per_fan destructure it); DM tips and SETTLED money only, else refunded work shows as owed.
    return (select(Transaction.account_id, Transaction.fan_id,
                   Transaction.amount_cents, Transaction.occurred_at,
                   Transaction.message_id)
            .where(Transaction.kind.in_(_customs.ORDER_KINDS),
                   Transaction.status.in_(_customs.SETTLED_STATUSES),
                   *conditions)
            .order_by(Transaction.occurred_at.desc()))


def _chat_href(account_id: str, fan_id: int, msg_id) -> str:
    base = f"/chat/{account_id}/{int(fan_id)}"
    return f"{base}?msg={int(msg_id)}" if msg_id else base


@router.get("/admin/customs")
async def list_customs(account_id: str | None = Query(None)) -> dict[str, Any]:
    """Every fan owed a custom. `account_id` optional — omit for the whole roster."""
    allowed = clamp_account_filter(account_id)

    async with get_session() as s:
        q = select(Fan.account_id, Fan.fan_id, Fan.customs_owed_at,
                   Fan.of_display_name, Fan.of_username,
                   Fan.lifetime_spend_cents).where(
            Fan.customs_owed_at.is_not(None))
        if allowed is not None:
            q = q.where(Fan.account_id.in_(allowed))
        owed = (await s.execute(q)).all()

        if not owed:
            # Still report untracked accounts: an empty queue plus a silent config gap looks like a healthy empty queue.
            return {"customs": [], "count": 0,
                    "untracked": await _untracked(allowed)}

        keys = {(r[0], int(r[1])) for r in owed}
        oldest = min((r[2] for r in owed if r[2] is not None), default=None)
        floor_at = datetime.utcnow() - timedelta(days=_REVIEW_DAYS)
        since = max(oldest - timedelta(minutes=_customs.BURST_MINUTES),
                    floor_at) if oldest is not None else floor_at
        tips = (await s.execute(_order_tips_q(
            Transaction.account_id.in_({k[0] for k in keys}),
            Transaction.fan_id.in_({k[1] for k in keys}),
            Transaction.occurred_at >= since,
        ))).all()
        all_bursts = {k: v for k, v in _customs.bursts_per_fan(tips).items()
                      if k in keys}

        names = {a: (n or a) for a, n in (await s.execute(
            select(Account.id, Account.nickname)
            .where(Account.id.in_({k[0] for k in keys}))
        )).all()}

    out = []
    for acct, fid, owed_at, disp, uname, spend in owed:
        bursts = all_bursts.get((acct, int(fid)), [])
        cents = sum(b[0] for b in bursts) if bursts else None
        at, msg_id = (bursts[0][1], bursts[0][2]) if bursts else (None, None)
        out.append({
            "account_id": acct,
            "account_name": names.get(acct, acct),
            "fan_id": int(fid),
            "marked": True,
            "display_name": disp or uname or f"fan #{fid}",
            # The handle, separate from the display name: OF search takes the @username, a display name finds nothing.
            "of_username": uname or None,
            "tip_cents": cents,
            "order_count": len(bursts),
            "orders": [{"cents": int(c), "at": a.isoformat() if a else None,
                        "msg_id": int(m) if m else None}
                       for c, a, m in bursts],
            # customs_owed_at is the authority on WHEN he paid; fall back to it when the tip scan is empty so the row still ages correctly.
            "tipped_at": (at or owed_at).isoformat() if (at or owed_at) else None,
            "lifetime_spend_cents": int(spend or 0),
            "chat_href": _chat_href(acct, fid, msg_id),
        })
    out.extend(await _unmarked(allowed, {(r["account_id"], r["fan_id"]) for r in out}))
    out.sort(key=lambda r: (r["tipped_at"] or "9999"))
    return {"customs": out, "count": len(out),
            "untracked": await _untracked(allowed)}


async def _unmarked(allowed: list[str] | None,
                    already: set[tuple]) -> list[dict[str, Any]]:
    # A REVIEW list, not a debt list: a $100 DM tip is an order on male accounts and generosity on female ones, nothing here can tell which.
    since = datetime.utcnow() - timedelta(days=_REVIEW_DAYS)
    async with get_session() as s:
        q = _order_tips_q(Transaction.occurred_at >= since,
                          Transaction.fan_id.is_not(None))
        if allowed is not None:
            q = q.where(Transaction.account_id.in_(allowed))
        tips = (await s.execute(q)).all()
        if not tips:
            return []

        keys = {(a, int(f)) for a, f, _, _, _ in tips} - already
        if not keys:
            return []
        fans = {(f.account_id, int(f.fan_id)): f for f in (await s.execute(
            select(Fan).where(Fan.account_id.in_({k[0] for k in keys})))
        ).scalars().all()}
        names = {a: (n or a) for a, n in (await s.execute(
            select(Account.id, Account.nickname)
            .where(Account.id.in_({k[0] for k in keys}))
        )).all()}

    out = []
    for key, bursts in _customs.bursts_per_fan(tips).items():
        if key not in keys:
            continue
        acct, fid = key
        fan = fans.get(key)
        for cents, at, msg_id in bursts:
            if fan is not None and fan.customs_cleared_at and at <= fan.customs_cleared_at:
                continue
            out.append({
                "account_id": acct,
                "account_name": names.get(acct, acct),
                "fan_id": int(fid),
                "marked": False,
                "display_name": ((fan.of_display_name or fan.of_username) if fan else None)
                                or f"fan #{fid}",
                "of_username": (fan.of_username if fan else None) or None,
                "tip_cents": int(cents or 0),
                "tipped_at": at.isoformat() if at else None,
                "lifetime_spend_cents": int((fan.lifetime_spend_cents if fan else 0) or 0),
                "chat_href": _chat_href(acct, fid, msg_id),
            })
    return out


async def _untracked(allowed: list[str] | None) -> list[dict[str, Any]]:
    # Deliberately NOT auto-enabling the watcher: what a $100 DM tip means differs by account, enabling it would mark fans owed and stop the bot selling to them.
    since = datetime.utcnow() - timedelta(days=14)
    async with get_session() as s:
        q = (select(Transaction.account_id, func.count(),
                    func.max(Transaction.amount_cents))
             .where(Transaction.kind.in_(_customs.ORDER_KINDS),
                    Transaction.amount_cents >= _customs.MIN_CENTS,
                    # A charged-back tip is no evidence an account takes custom orders.
                    Transaction.status.in_(_customs.SETTLED_STATUSES),
                    Transaction.occurred_at >= since)
             .group_by(Transaction.account_id))
        if allowed is not None:
            q = q.where(Transaction.account_id.in_(allowed))
        tipped = (await s.execute(q)).all()
        if not tipped:
            return []

        watching = {a for (a,) in (await s.execute(
            select(AutomationRule.account_id)
            .where(AutomationRule.kind == "customs_watch",
                   AutomationRule.is_enabled.is_(True),
                   AutomationRule.account_id.in_({t[0] for t in tipped}))
        )).all()}

        names = {a: (n or a) for a, n in (await s.execute(
            select(Account.id, Account.nickname)
            .where(Account.id.in_({t[0] for t in tipped}))
        )).all()}

    return [{"account_id": a, "account_name": names.get(a, a),
             "qualifying_tips": int(n), "biggest_cents": int(mx or 0)}
            for a, n, mx in tipped if a not in watching]


@router.get("/admin/customs/context")
async def customs_context(
    account_id: str = Query(...),
    fan_id: int = Query(...),
    at: str | None = Query(None, description="ISO anchor; default = his newest qualifying tip"),
    before: int = Query(18, ge=1, le=250),
    after: int = Query(6, ge=0, le=250),
) -> dict[str, Any]:
    """The conversation AROUND the tip — what was actually ordered.

    This is the answer to "how do we know what to do with this row". A tip on its
    own says a man paid; the twenty messages around it say what he paid FOR. From
    a real thread (Amia / 142006425): "I can start doing it babe immediately
    after you tip for it" / "Make sure you talk dirty to daddy Dennis while
    you're riding me" / $200 + $100 / "Wanna see me in a sexy lingerie" — a
    complete work order, reconstructed from messages we already store.

    COUNT-BASED, not a time window. A time window is empty on a slow thread and
    unbounded on a fast one; N-before/M-after always returns something to read.

    It also makes the chat deep-link's page bound stop mattering for the common
    case: the context arrives WITH the row, so nobody has to reach a 700-hour-old
    message in the OnlyFans-backed thread pane to make the call."""
    assert_account_owned(account_id)

    async with get_session() as s:
        anchor_at = None
        if at:
            try:
                parsed = datetime.fromisoformat(at.replace("Z", "+00:00"))
            except ValueError:
                raise HTTPException(422, "bad `at` timestamp")
            # CONVERT to UTC before dropping the offset: `.replace(tzinfo=None)` alone discards it and reads two hours of the wrong conversation.
            anchor_at = (parsed.astimezone(timezone.utc).replace(tzinfo=None)
                         if parsed.tzinfo is not None else parsed)
        if anchor_at is None:
            anchor_at = (await s.execute(
                select(func.max(Transaction.occurred_at))
                .where(Transaction.account_id == str(account_id),
                       Transaction.fan_id == int(fan_id),
                       # Anchoring on a charged-back tip points at a conversation about money taken back.
                       Transaction.status.in_(_customs.SETTLED_STATUSES),
                       Transaction.kind.in_(_customs.ORDER_KINDS))
            )).scalar_one_or_none()
        if anchor_at is None:
            return {"anchor_at": None, "messages": []}

        cols = (Message.message_id, Message.direction, Message.body,
                Message.created_at, Message.is_tip, Message.price_cents)
        older = (await s.execute(
            select(*cols).where(Message.account_id == str(account_id),
                                Message.fan_id == int(fan_id),
                                Message.is_unsent.is_(False),
                                Message.created_at <= anchor_at)
            .order_by(Message.created_at.desc()).limit(before)
        )).all()
        newer = (await s.execute(
            select(*cols).where(Message.account_id == str(account_id),
                                Message.fan_id == int(fan_id),
                                Message.is_unsent.is_(False),
                                Message.created_at > anchor_at)
            .order_by(Message.created_at.asc()).limit(after)
        )).all()

    from automation_executor import _strip_html

    def _row(r) -> dict[str, Any]:
        mid, direction, body, created, is_tip, price = r
        return {
            "message_id": int(mid),
            "from_fan": direction == "in",
            "text": _strip_html(body or ""),
            "at": created.isoformat() if created else None,
            "is_tip": bool(is_tip),
            "price_cents": int(price or 0),
        }

    return {"anchor_at": anchor_at.isoformat(),
            "messages": [_row(r) for r in reversed(older)] + [_row(r) for r in newer]}


# The whole relationship, not a window around the tip: 58 days separated one live order from the tip that surfaced it.
_ORDER_SEARCH_DAYS = 400
_ORDER_SEARCH_MAX = 4000


@router.get("/admin/customs/order")
async def customs_order(
    account_id: str = Query(...),
    fan_id: int = Query(...),
) -> dict[str, Any]:
    """WHAT HE ORDERED, in his words, found across the WHOLE thread.

    This serves the operator's 2026-09-05 ruling — *"copy and paste the exact
    username, which account, and what the customer said"*. `customs_context`
    cannot serve it, and why not is the entire reason this endpoint exists.

    ⚠️ THE REQUEST IS NOT NEAR THE TIP, AND ON A LAYAWAY CUSTOM IT IS NOWHERE
    NEAR IT. Verified against two live rows, not argued from first principles:

      fan A — order placed in July. The tip that put him on the queue landed
      in September, and he had been paying it off in $100 instalments the whole
      time ("I'm now 400/700 of what I owe you for that custom"). That is 58
      days and several hundred messages apart. A 160-message `before` window
      reads none of it — what it actually returns is small talk.

      fan B — the ask is SPLIT across two days (the scenario and wardrobe one
      day, "five minute video" the next), and then RENEGOTIATED BY US to ten
      minutes. Keeping only his longest single message loses half the order;
      keeping only HIS messages loses the spec that was actually agreed.

    So: scan the whole thread, keep the lines that are ABOUT an order, return
    them oldest-first with dates. BOTH DIRECTIONS, and that is deliberate — the
    spec gets settled in the back-and-forth ("ten minutes, no cuts, that covers
    the hat, the toy, and every filthy word"), so a fan-only view of that
    conversation is not the order.

    NO MODEL, on purpose. The operator films against this text, and a paraphrase
    that quietly rewrites "ten minutes, no cuts" costs a take. Matching is a
    literal substring test he can predict, and every line is returned verbatim.
    """
    assert_account_owned(account_id)

    from automation_executor import _strip_html

    since = datetime.utcnow() - timedelta(days=_ORDER_SEARCH_DAYS)
    async with get_session() as s:
        rows = (await s.execute(
            select(Message.message_id, Message.direction, Message.body,
                   Message.created_at, Message.is_tip)
            .where(Message.account_id == str(account_id),
                   Message.fan_id == int(fan_id),
                   Message.is_unsent.is_(False),
                   Message.created_at >= since)
            .order_by(Message.created_at.desc())
            .limit(_ORDER_SEARCH_MAX)
        )).all()
        rows = list(reversed(rows))

        blast = blast_counts((await s.execute(
                select(Message.body, func.count(func.distinct(Message.fan_id)))
                .where(Message.account_id == str(account_id),
                       Message.direction == "out",
                       Message.is_unsent.is_(False))
                .group_by(Message.body)
        )).all(), _strip_html)

    msgs = [_Msg(int(mid), direction, _strip_html(body or "").strip(),
                 created, bool(is_tip))
            for mid, direction, body, created, is_tip in rows]

    return order_span(msgs, blast)


class _BriefBody(BaseModel):
    account_id: str
    fan_id: int
    at: str | None = None


@router.post("/admin/customs/brief")
async def customs_brief(body: _BriefBody = Body(...)) -> dict[str, Any]:
    """A WORK ORDER for one owed custom: what to record, in the fan's terms.

    The Read pane already shows the thread; this reads it FOR the operator and
    says what the voice note has to contain. It exists because the answer is
    usually spread across several messages ("25 back 25 front", a name to say, a
    scenario) and reconstructing it means re-reading the thread every time
    somebody picks the row up.

    ⚠️ THE MODEL NEVER STATES AN AMOUNT, AND THAT IS THE WHOLE SAFETY ARGUMENT.
    `transactions` knows exactly what was paid; a model asked to attribute
    dollars to deliverables will invent a split, the operator will film to it,
    and the recording is burned before anyone notices. So the money is passed IN
    as ground truth, the schema has no field for it, and the prompt forbids
    restating it. Deliverables come from the model; figures come from the DB.

    ON CLICK ONLY, never on queue load — a per-row call for rows nobody opens is
    money spent on nothing. Cheap model (`deepseek-v4-flash`), and every call is
    capped and audited by `llm_client.chat` like any other.

    Best-effort by construction: a cap hit or a bad JSON body returns
    `ok: false` with a reason rather than raising, because the raw thread is
    rendered underneath and the operator is never blocked on this. A missing or
    rejected API key is the one exception — it raises `LLMKeyError`, which
    server.py answers as the typed 424 the app toasts with the fix."""
    assert_account_owned(body.account_id)

    async with get_session() as s:
        tips = (await s.execute(_order_tips_q(
            Transaction.account_id == str(body.account_id),
            Transaction.fan_id == int(body.fan_id),
            Transaction.occurred_at >= datetime.utcnow()
            - timedelta(days=_REVIEW_DAYS),
        ))).all()
    bursts = _customs.bursts_per_fan(tips).get(
        (str(body.account_id), int(body.fan_id)), [])
    paid_cents = sum(b[0] for b in bursts)

    # Anchor on the OLDEST outstanding order and run to now: the ask predates the tip, a newest-tip window summarises the wrong conversation.
    anchor_at = body.at or (bursts[-1][1].isoformat() if bursts else None)
    ctx = await customs_context(account_id=body.account_id, fan_id=body.fan_id,
                                at=anchor_at, before=_BRIEF_BEFORE,
                                after=_BRIEF_AFTER)
    window = ctx.get("messages") or []
    span = (await customs_order(account_id=body.account_id,
                                fan_id=body.fan_id)).get("lines") or []
    msgs = brief_msgs(span, window)
    skip = brief_skip_reason(msgs)
    if skip:
        return {"ok": False, "reason": skip}

    def _line(m) -> str:
        day = (m.get("at") or "")[:10]
        if m.get("is_tip"):
            return f"TIP {day}: {m.get('text') or ''}".rstrip()
        who = "HIM" if m.get("from_fan") else "US"
        return f"{who} {day}: {(m.get('text') or '').strip()}"
    lines = [_line(m) for m in msgs
             if m.get("is_tip") or (m.get("text") or "").strip()]

    if len(lines) > _BRIEF_MAX_LINES:
        head = _BRIEF_MAX_LINES * 2 // 3
        lines = lines[:head] + ["…"] + lines[-(_BRIEF_MAX_LINES - head):]
    transcript = "\n".join(lines)
    system = (
        "You read one OnlyFans fan's chat with the creator and write the WORK "
        "ORDER for a custom he paid for. The creator's team records it from "
        "your note alone, so be concrete. Lines are labelled HIM (the fan), US "
        "(the creator) and TIP. Reply with JSON only: "
        '{"summary": str, "his_words": [str], '
        '"call_him": str|null, "found_request": bool}. '
        "summary: 2-3 plain sentences saying exactly what to make — what it is "
        "(video or voice note), how long, what to wear or use, what to say and "
        "how, what to call him. Imperative, like a note to the person holding "
        "the camera. A US line counts as spec ONLY when it states what THIS "
        "custom will be — its length, what it covers, what is worn or used — "
        "and when US sets that after HIM proposed something else, the US line "
        "is the agreed spec: use it and say so. Everything else US writes — "
        "sexting, flirting, selling, promises — is NOT the order; never turn it "
        "into an instruction. Only include wardrobe, props or actions that were "
        "stated for this custom; do not carry them over from other chat. "
        "If HIM asked for more than one custom over time, describe only the "
        "one the most recent tips paid for. Everything in the summary must be "
        "traceable to a HIM line in his_words or to a US line that states this "
        "custom's contents; if you cannot point to one, leave it out. "
        "Write it out in full — never abbreviate ('wear the hat, shirt off, toy "
        "out', not 'hat/shirt/toy'). "
        "his_words: the 1-3 HIM messages that ARE the request, copied COMPLETE "
        "and word for word — the whole message every time, never shortened, "
        "never trailing off with '...'. "
        "call_him: the name he wants used, or null. If he asked to be called "
        "something different later in the chat, the later name wins. "
        "found_request: true ONLY if these messages contain him asking for "
        "something specific. If he never says what he wants here — the ask was "
        "earlier than this excerpt, or he only discussed price — set it false, "
        "leave todo empty and say in summary that the ask is not in this "
        "excerpt. A confident guess gets recorded and the take is wasted. "
        "NEVER state, guess, split or total any dollar amount — the system "
        "already knows what he paid and shows it. Do not invent anything he "
        "did not ask for."
    )
    try:
        res = await llm_client.chat(
            model="deepseek-v4-flash",
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": transcript}],
            purpose="customs_brief",
            account_id=str(body.account_id),
            fan_id=int(body.fan_id),
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        brief = res.parsed if isinstance(res.parsed, dict) else json.loads(res.content)
    except llm_client.LLMKeyError:
        raise
    except Exception as exc:
        log.warning("customs brief failed account=%s fan=%s: %s",
                    body.account_id, body.fan_id, exc)
        return {"ok": False, "reason": str(exc)}

    return {
        "ok": True,
        # From the DB, never from the model.
        "paid_cents": paid_cents,
        "order_count": len(bursts),
        "found_request": bool(brief.get("found_request", True)),
        "summary": str(brief.get("summary") or "").strip(),
        # Whole messages enforced here, not trusted to the prompt: each quote is swapped for the full stored message; one matching nothing he sent is dropped.
        "his_words": _whole_messages(
            [str(x).strip() for x in (brief.get("his_words") or []) if str(x).strip()],
            [m for m in msgs if is_his_line(m)])[:3],
        "call_him": (str(brief["call_him"]).strip()
                     if brief.get("call_him") else None),
    }


class _ClearBody(BaseModel):
    account_id: str
    fan_id: int


@router.post("/admin/customs/clear")
async def clear_custom(body: _ClearBody = Body(...)) -> dict[str, Any]:
    """Mark one custom delivered — blanks `customs_owed_at` and stamps settled.

    Nothing is pushed to OnlyFans. This used to also strip a " Custom" suffix from
    the fan's OF display name and PUT the shortened name back; both halves are
    gone with the suffix, and with them the failure mode where the push failed,
    was reported as `pushed_to_of: false`, and was never retried by anything."""
    assert_account_owned(body.account_id)

    async with get_session() as s:
        fan = await s.get(Fan, {"account_id": str(body.account_id),
                                "fan_id": int(body.fan_id)})
        if fan is None:
            raise HTTPException(404, "fan not found")
        # clear() is False when nothing was owed (double click, or a REVIEW row): it must still SETTLE, else a review row reappears on every load.
        already = not _customs.clear(fan)
        if already:
            fan.customs_cleared_at = datetime.utcnow()
        await s.commit()

    log.info("customs CLEARED account=%s fan=%s already_clear=%s",
             body.account_id, body.fan_id, already)
    return {"ok": True, "already_clear": already}
