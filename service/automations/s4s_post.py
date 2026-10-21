"""service/automations/s4s_post.py — one S4S slot, posted on its own Creator's
account through Auto Post, behind the live-posting flag.

Accept queues one `s4s_post` job per S4S slot on the slot's poster account at
`slot_at`, payload `{"slot_id"}` (s4s_requests_api `_book`). This run
(docs/spec/phase-03-share-for-share.md, Interfaces):

  - does nothing to a slot that is `posted`, `canceled` or `failed`, or that
    another account's job names (a slot posts only on its poster's account);
  - marks a slot found in `posting` `failed` / `interrupted_mid_post`: an
    earlier attempt claimed it and died (the executor retries a raised job),
    and it may already be on OnlyFans, so it is never posted again;
  - marks a `scheduled` slot `canceled` with a reason when `S4S_LIVE_POSTING`
    is set off (`live posting off`; unset reads as on), when the poster is opted out (`opted_out`)
    or has no Agency (`no_agency`), when the partner is opted out or has no
    Agency (`partner_opted_out`), or when the run comes 24 hours or more after
    `slot_at` (`missed`);
  - otherwise claims the slot `scheduled` → `posting` by a status-guarded
    UPDATE and commits, and only then calls Auto Post's public `run` with
    `{"posts": [{"text", "hours_to_live": 24}]}` on the poster's account, the
    text being the slot's (the partner's caption plus an @mention of the
    partner, which OnlyFans renders as the link to onlyfans.com/<partner>)
    with Infloww's `#advertisement` tag as its last line (`_advertised`); Auto
    Post records the `posts` row and queues the unsend automation's removal
    24h later. On `ok` the slot records `post_id`, `of_post_id`, `posted_at`
    and `remove_at` (Auto Post's `local_post_id`, the post's `posted_at`, and
    Auto Post's `delete_at`); any other result ends `failed` with its reason.
  - with S4S media (ADR-0015): the partner's snapshot vault ids are resolved
    before the claim (`s4s_media.slot_vault_ids`). After it, each item is read
    from the partner's vault with the partner's own session into a temporary
    directory (`s4s_media.fetch_to`) and uploaded to the poster's own account,
    one `of_write_paced` write each; their `send_with` entries ride as the
    post's `media_claims`, and the directory is removed. A snapshot row or
    vault item that is gone ends the slot `failed` / `media_missing`, any
    other read failure `failed` / `media_fetch_failed`, a failed upload
    `failed` / `upload_failed`, all with nothing posted;
  - on `posted`, queues `s4s_check` (the tamper check) on the poster's
    account 30 minutes before the post's removal. Every run ends with an
    S4S media prune.

`s4s_post` is classified `not_fan_dm` in the audience fence's sender
classification (audience_include.AUDIENCE_SENDER_CLASSIFICATION): its own
write is the S4S media upload, and its post is Auto Post's, both wall posts,
never a fan DM.

Every end writes one `actions` row on the poster: `s4s.slot_post`,
`s4s.slot_fail` or `s4s.slot_cancel`, with the poster's Agency user id and the
S4S row ids, never the caption. Every move of the slot is the same
status-guarded transition the slot-cancel route and the opt-out cascade use:
`s4s_schedule_api.claim_slot` for the unaudited claim, `move_slot` (the
claim plus its audit row) for every end, the `posted` step included. A row
that is no longer in the expected status is never moved, audited or
reported `ok`. The flag is read on every run (`s4s_api.live_posting`). Auto
Post gained only `media_claims`; the unsend automation is unchanged. Self-registers via
`@register("s4s_post")` on import.

One process, and why the status guard still matters. The relay runs one
uvicorn process with no `--workers` (Dockerfile:73-75 "Single worker on
purpose"; service/relay_cache.py:36-38 "The relay runs single-worker by
design"; no `--workers` in scripts/, deploy/ or docker-compose.yml), so the executor's per-process `(account, kind)` run
lock (automation_executor.py `_run_locks`, checked in `run_once`) keeps two
runs of one slot apart today. That lock is process-local: a second relay
process on the same database (a restart overlapping the old process, or a
future `--workers > 1`) is not covered by it, and then the status guard on
every slot move is the only protection against a second post or a stale
`posted` row.

ASSUMPTION: a run's audit row has `employee_id` null and `actor: system`,
as a lazy expiry's does (rung 3, `s4s_requests_api._expire_due`), and also
names the poster's Agency user id (ticket 19: "with the Agency's user id").
Overturned by an owner wanting the Automation employee named.
ASSUMPTION: the audit row's Agency is the first of `tenant_keys.owners_of`
for the poster (a Master link drops whenever a non-Master link exists), and
None when it has none. Rung 3 (the house's one owner-plus-Master rule,
tenant_keys.billable_owners). Overturned by an owner wanting every linked
Agency named for a Creator two non-Master Agencies share.
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

import automation_executor as ax
from automation_registry import register
from automations import auto_posts
from db.engine import get_session
from db.models import Post, S4SProfile, S4SSlot
from s4s_api import live_posting
from s4s_media import MediaMissing, fetch_to, prune, slot_vault_ids
from s4s_requests_api import _linked
from s4s_schedule_api import claim_slot, move_slot
from tenant_keys import owners_of

log = logging.getLogger("of-relay.automation.s4s_post")

HOURS_TO_LIVE = 24
MISSED_AFTER = timedelta(hours=24)
DONE = ("posted", "canceled", "failed")
# The tamper check reads the post this long before its scheduled removal.
CHECK_BEFORE_REMOVAL = timedelta(minutes=30)


async def _copy(account_id: str, partner_id: str, vault_ids: list[int]) -> list | str:
    """Read each of the partner's vault items with the partner's session and
    upload it to the poster's own account, one paced write each; the
    `send_with` entries in order, or the slot's failure reason.

    ASSUMPTION: the upload claim goes straight into the post, not through
    `materialize_to_vault` (ADR-0015): no carrier post, and OF files the
    posted media in the poster's vault itself. Rung 3 (the OF mirror's Add
    media posts `send_with` the same way). Overturned if OF refuses a claim
    on a post.
    """
    client = await asyncio.to_thread(ax._make_client, account_id)
    out: list = []
    with tempfile.TemporaryDirectory(prefix="s4s_") as tmp:
        for vid in vault_ids:
            try:
                p = await asyncio.to_thread(fetch_to, partner_id, vid, Path(tmp))
            except MediaMissing:
                log.warning("s4s_post: vault item %s of account=%s is gone", vid, partner_id)
                return "media_missing"
            except Exception:  # noqa: BLE001 — the slot ends `media_fetch_failed`; the error is logged
                log.warning("s4s_post: vault item %s of account=%s could not be read", vid, partner_id, exc_info=True)
                return "media_fetch_failed"
            try:
                up = await ax.of_write_paced(account_id, lambda p=p: client.upload_media(p),
                                             send_purpose="not_fan_dm")
            except Exception:  # noqa: BLE001 — the slot ends `upload_failed`; the error is logged, not stored
                log.warning("s4s_post: upload of %s failed for account=%s", p.name, account_id, exc_info=True)
                return "upload_failed"
            finally:
                p.unlink(missing_ok=True)
            if not up.get("ready"):
                log.warning("s4s_post: upload of %s not ready for account=%s: %s", p.name, account_id,
                            up.get("note"))
                return "upload_failed"
            out.extend(up["send_with"])
    return out


async def _prune() -> None:
    try:
        await prune()
    except Exception:  # noqa: BLE001 — a cleanup failure never changes a slot's outcome
        log.warning("s4s_post: S4S media prune failed", exc_info=True)


# Infloww's S4S post guideline (remote web bundle index.9f50f370.js, SavePost):
# "Please write in the third person and @id your account. Infloww will
# automatically insert #advertisement at the end of each post." The client
# saves the caption bare (PUT /growth/post/edit {message}), so the tag is
# added at post time, server-side; no OnlyFans post flag is involved.
AD_TAG = "#advertisement"


def _advertised(text: str) -> str:
    """The posted text: the slot's text with `AD_TAG` as its last line, once.

    ASSUMPTION: the tag goes on its own line, after the @mention. Rung 6
    (Infloww fixes "at the end of each post", not the joint). Overturned by a
    live Infloww S4S post showing another separator.
    """
    body = text.rstrip()
    return body if body.endswith(AD_TAG) else f"{body}\n{AD_TAG}"


async def _agency(account_id: str) -> str | None:
    """The poster's Agency (`users.id`) by the house rule, or None once it has none."""
    return next(iter(await owners_of(account_id)), None)


async def _cancel_reason(s, slot: S4SSlot, now: datetime) -> str | None:
    """Why a `scheduled` slot must not post now, or None.

    ASSUMPTION: the checks run in the spec's order (flag, opt-ins, Agencies,
    then `missed`), so a slot that is late and also unflagged reads `live
    posting off`. Rung 6. Overturned by an owner wanting another reason first.
    ASSUMPTION: a partner with no Agency left cancels as `partner_opted_out`,
    the reason the schedule already shows for it (rung 3,
    `s4s_schedule_api._display`), and a poster with none as `no_agency`.
    Overturned with the schedule's reason.
    """
    if not live_posting():
        return "live posting off"
    ids = {slot.poster_account_id, slot.partner_account_id}
    opted = set((await s.execute(
        select(S4SProfile.account_id).where(S4SProfile.account_id.in_(ids), S4SProfile.opted_in.is_(True))
    )).scalars().all())
    linked = await _linked(s, ids)
    if slot.poster_account_id not in opted:
        return "opted_out"
    if slot.poster_account_id not in linked:
        return "no_agency"
    if slot.partner_account_id not in opted or slot.partner_account_id not in linked:
        return "partner_opted_out"
    if now - slot.slot_at >= MISSED_AFTER:
        return "missed"
    return None


def _when(iso: str) -> datetime:
    """Auto Post's `delete_at` ("…Z") → naive UTC."""
    return datetime.fromisoformat(iso.rstrip("Z"))


async def _fail(slot: S4SSlot, reason: str, agency: str | None) -> None:
    async with get_session() as s:
        await move_slot(s, slot, "posting", {"status": "failed", "reason": reason[:500]}, action="s4s.slot_fail",
                        audit={"actor": "system", "reason": reason[:500]}, agency_user_id=agency, employee_id=None)


@register("s4s_post")
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    """Post one S4S slot, or end it with a reason. Returns a stats dict."""
    try:
        return await _run(account_id, payload, run_id=run_id)
    finally:
        await _prune()


async def _run(account_id: str, payload: dict, *, run_id: int) -> dict:
    try:
        slot_id = int((payload or {}).get("slot_id"))
    except (TypeError, ValueError):
        return {"status": "skipped", "reason": "no_slot_id"}
    now = datetime.utcnow()
    async with get_session() as s:
        slot = await s.get(S4SSlot, slot_id)
        if slot is None:
            return {"status": "skipped", "reason": "no_slot", "slot_id": slot_id}
        if slot.poster_account_id != str(account_id):
            log.warning("s4s_post: slot %s belongs to another poster than account=%s", slot_id, account_id)
            return {"status": "skipped", "reason": "not_the_poster", "slot_id": slot_id}
        if slot.status in DONE:
            return {"status": "skipped", "reason": slot.status, "slot_id": slot_id}
        # Every path from here writes an audit row naming the poster's Agency:
        # looked up once, and used for the end after the post as well.
        agency = await _agency(str(account_id))
        if slot.status == "posting":
            await move_slot(s, slot, "posting", {"status": "failed", "reason": "interrupted_mid_post"},
                            action="s4s.slot_fail", audit={"actor": "system", "reason": "interrupted_mid_post"},
                            agency_user_id=agency, employee_id=None)
            return {"status": "skipped", "reason": "interrupted_mid_post", "slot_id": slot_id}
        reason = await _cancel_reason(s, slot, now)
        if reason is not None:
            await move_slot(s, slot, "scheduled", {"status": "canceled", "reason": reason}, action="s4s.slot_cancel",
                            audit={"actor": "system", "reason": reason}, agency_user_id=agency, employee_id=None)
            return {"status": "skipped", "reason": reason, "slot_id": slot_id}
        try:
            vault_ids = await slot_vault_ids(s, slot)
        except MediaMissing:
            await move_slot(s, slot, "scheduled", {"status": "failed", "reason": "media_missing"},
                            action="s4s.slot_fail", audit={"actor": "system", "reason": "media_missing"},
                            agency_user_id=agency, employee_id=None)
            return {"status": "error", "reason": "media_missing", "slot_id": slot_id}
        if not await claim_slot(s, slot, "scheduled", {"status": "posting"}):
            return {"status": "skipped", "reason": "claimed_elsewhere", "slot_id": slot_id}
        text = _advertised(slot.text)
    # The claim is committed: from here a crash leaves `posting`, never a second post.

    item: dict = {"text": text, "hours_to_live": HOURS_TO_LIVE}
    if vault_ids:
        claims = await _copy(str(account_id), slot.partner_account_id, vault_ids)
        if isinstance(claims, str):
            await _fail(slot, claims, agency)
            return {"status": "error", "reason": claims, "slot_id": slot_id}
        item["media_claims"] = claims
    try:
        res = await auto_posts.run(str(account_id), {"posts": [item]}, run_id=run_id)
    except Exception as e:
        # ASSUMPTION: a raised post call ends the slot `failed` with the error
        # at once and is re-raised, so the executor still records the error
        # (and its dead-session check still sees it) while its retry finds a
        # failed slot and posts nothing. Rung 4 (an honest status now over
        # `posting` until the retry). Overturned by an owner wanting such a
        # slot retried, which the spec's never-re-post rule rules out today.
        await _fail(slot, repr(e), agency)
        raise
    if res["status"] != "ok":
        reason = str(res.get("reason") or res["status"])
        await _fail(slot, reason, agency)
        return {"status": "error", "reason": reason, "slot_id": slot_id}

    post_id, of_post_id = int(res["local_post_id"]), res["of_post_id"]
    async with get_session() as s:
        posted_at = (await s.get(Post, post_id)).posted_at  # Auto Post has just committed this row
        moved = await move_slot(
            s, slot, "posting",
            {"status": "posted", "post_id": post_id, "of_post_id": of_post_id, "posted_at": posted_at,
             "remove_at": _when(res["delete_at"])},
            action="s4s.slot_post", audit={"actor": "system", "post_id": post_id, "of_post_id": of_post_id},
            agency_user_id=agency, employee_id=None,
        )
    if not moved:
        # Another run ended the slot while this post was in flight; its end
        # stands. The post itself is Auto Post's row, removed by its unsend job.
        log.warning("s4s_post: slot %s left `posting` during its post (post_id=%s)", slot_id, post_id)
        return {"status": "error", "reason": "slot_left_posting", "slot_id": slot_id, "post_id": post_id}
    await ax.enqueue_job(str(account_id), "s4s_check", payload={"slot_id": slot_id},
                         run_at=_when(res["delete_at"]) - CHECK_BEFORE_REMOVAL)
    return {"status": "ok", "slot_id": slot_id, "post_id": post_id, "of_post_id": of_post_id,
            "remove_at": res["delete_at"]}
