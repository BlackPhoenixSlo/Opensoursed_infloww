from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, select, update

from db.engine import get_session
from db.models import MassRun, Message

log = logging.getLogger(__name__)

# OF rate-limits mass sends so a blast sprays over minutes; 3 min bridges it without merging two blasts of the same line.
DEFAULT_GAP_SECONDS = 180
# Below this, identical bodies could be genuine 1:1s: left alone.
DEFAULT_MIN_RECIPIENTS = 5

# queue_id stays NULL: these never had an OF queue id.
DETECTED_KIND = "detected_blast"


async def detect_mass_bursts(
    *,
    account_ids: list[str] | None = None,
    gap_seconds: int = DEFAULT_GAP_SECONDS,
    min_recipients: int = DEFAULT_MIN_RECIPIENTS,
    window_start: datetime | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    gap = timedelta(seconds=gap_seconds)

    q = (
        select(
            Message.account_id,
            Message.fan_id,
            Message.message_id,
            Message.body,
            Message.price_cents,
            Message.media_count,
            Message.created_at,
        )
        .where(Message.direction == "out")
        .where(Message.mass_run_id.is_(None))
        .where(Message.automation_kind.is_(None))
        .order_by(
            Message.account_id,
            Message.body,
            Message.price_cents,
            Message.media_count,
            Message.created_at,
            Message.message_id,
        )
    )
    if account_ids is not None:
        q = q.where(Message.account_id.in_(account_ids))
    if window_start is not None:
        q = q.where(Message.created_at >= window_start)

    async with get_session() as s:
        rows = (await s.execute(q)).all()

    bursts: list[dict[str, Any]] = []
    cur_key: tuple | None = None
    cur_members: list[tuple[int, int]] = []
    cur_fans: set[int] = set()
    cur_first: datetime | None = None
    cur_last: datetime | None = None
    cur_account: str | None = None
    cur_body: str = ""

    def _close() -> None:
        if cur_account is None or len(cur_fans) < min_recipients:
            return
        bursts.append({
            "account_id": cur_account,
            "body": cur_body,
            "recipients": len(cur_fans),
            "rows": len(cur_members),
            "members": list(cur_members),
            "first": cur_first,
            "last": cur_last,
        })

    for r in rows:
        key = (r.account_id, r.body, r.price_cents, r.media_count)
        contiguous = (
            key == cur_key
            and cur_last is not None
            and r.created_at is not None
            and (r.created_at - cur_last) <= gap
        )
        if not contiguous:
            _close()
            cur_key = key
            cur_members = []
            cur_fans = set()
            cur_first = r.created_at
            cur_account = r.account_id
            cur_body = r.body or ""
        cur_members.append((int(r.fan_id), int(r.message_id)))
        cur_fans.add(int(r.fan_id))
        cur_last = r.created_at
    _close()

    runs_created = 0
    rows_tagged = 0
    summary_bursts: list[dict[str, Any]] = []
    for b in bursts:
        summary_bursts.append({
            "account_id": b["account_id"],
            "body": (b["body"] or "")[:60],
            "recipients": b["recipients"],
            "rows": b["rows"],
            "first": b["first"].isoformat() if b["first"] else None,
            "last": b["last"].isoformat() if b["last"] else None,
        })
        runs_created += 1
        rows_tagged += b["rows"]

    if not dry_run:
        for b in bursts:
            async with get_session() as s:
                run = MassRun(
                    account_id=b["account_id"],
                    audience_filter="{}",
                    recipient_count=b["recipients"],
                    automation_kind=DETECTED_KIND,
                    started_at=b["first"] or datetime.utcnow(),
                    completed_at=b["last"],
                    status="completed",
                )
                s.add(run)
                await s.flush()
                rid = run.id
                # message_id is OF-globally-unique, so (account_id, message_id) pins each row; chunk keeps the IN list bounded.
                msg_ids = [m[1] for m in b["members"]]
                for i in range(0, len(msg_ids), 500):
                    chunk = msg_ids[i : i + 500]
                    await s.execute(
                        update(Message)
                        .where(
                            and_(
                                Message.account_id == b["account_id"],
                                Message.message_id.in_(chunk),
                            )
                        )
                        .values(mass_run_id=rid)
                    )

    log.info(
        "detect_mass_bursts: %s runs, %s rows tagged (dry_run=%s)",
        runs_created, rows_tagged, dry_run,
    )
    return {
        "runs_created": runs_created,
        "rows_tagged": rows_tagged,
        "dry_run": dry_run,
        "bursts": summary_bursts,
    }
