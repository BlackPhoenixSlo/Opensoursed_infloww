"""service/s4s_common.py — the owner-only check, JSON body reader and
Discovery listing rule every Share for Share router uses (`s4s_api`,
`s4s_media`, `s4s_requests_api`, `s4s_schedule_api`), and the pure Send and
answer rules of `s4s_requests_api` (`request_refusal`, `next_status`: a
refusal is returned as a `Refuse`, which the route raises). A leaf: it
imports no S4S module, so the routers form a plain chain (s4s_api →
s4s_schedule_api → s4s_requests_api) with no cycle.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, NamedTuple

from fastapi import Request
from sqlalchemy import select

from db.models import S4SBlock, S4SProfile, UserAccount
from employees import AgencyContext, json_object, owner_context


_OWNER_ONLY = "only the agency owner manages Share for Share"

OPEN = ("pending", "skipped")
# Infloww's limit (`s4s0096`): requests one Creator sends per UTC day.
MAX_SENT_PER_DAY = 50
# verb → (the box of its party, the statuses it moves a request from, the
# new status): the receiver answers only a pending request, the sender
# cancels any open one (a skip reads pending to it).
VERBS = {
    "accept": ("received", ("pending",), "accepted"),
    "skip": ("received", ("pending",), "skipped"),
    "decline": ("received", ("pending",), "declined"),
    "cancel": ("sent", OPEN, "cancelled"),
}


async def _owner_context(account_id: str | None = None) -> AgencyContext:
    return await owner_context(account_id, _OWNER_ONLY)


async def _json_object(request: Request) -> dict[str, Any]:
    return await json_object(request, 400)


def listed_to(agency_user_id: str) -> tuple:
    """The conditions on `S4SProfile` for a Creator Discovery lists to this
    Agency (ADR-0011): opted in, visible, still linked to an Agency, and not
    blocked by this Agency. The Primary-post join is the caller's."""
    in_agency = select(UserAccount.account_id).where(UserAccount.account_id == S4SProfile.account_id).exists()
    blocked = select(S4SBlock.account_id).where(S4SBlock.agency_user_id == agency_user_id)
    return (S4SProfile.opted_in.is_(True), S4SProfile.discovery_visible.is_(True), in_agency,
            S4SProfile.account_id.not_in(blocked))


class Refuse(NamedTuple):
    """A refusal of the pure rules below: the route raises it as an
    HTTPException with this status and detail."""
    status: int
    detail: str


def partner_refusal(from_id: str, partner_account_id: str, blocked: bool) -> Refuse | None:
    """Send's and the proposal's refusal of a listed partner: 400 for the
    sender's own Creator, then 404 for a block either way (it reads as a
    partner that is not there, as Discovery hides it too)."""
    if partner_account_id == from_id:
        return Refuse(400, "a Creator cannot send an S4S request to itself")
    if blocked:
        return Refuse(404, "partner not found")
    return None


def daily_full(booked: int, limit: int) -> bool:
    """Is a Creator's Daily limit full on a day it has `booked` slots on?"""
    return booked >= limit


def request_refusal(*, from_p: S4SProfile | None, to_p: S4SProfile, sent_today: int, primaries: bool,
                    slot_at: datetime, now: datetime, open_pair: bool, booked_from: int,
                    booked_to: int) -> Refuse | None:
    """Send's first 409 after the partner checks, in this order: the day's
    MAX_SENT_PER_DAY, both opt-ins, both Primary posts, a past `slot_at`, an
    open request to the same partner, then the sender's and the partner's
    `daily_full` against the slots each has booked on that day."""
    if sent_today >= MAX_SENT_PER_DAY:
        return Refuse(409, f"a Creator sends at most {MAX_SENT_PER_DAY} S4S requests a day (UTC)")
    if from_p is None or not from_p.opted_in or not to_p.opted_in:
        return Refuse(409, "both Creators must be opted in to Share for Share")
    if not primaries:
        return Refuse(409, "both Creators need a Primary post")
    if slot_at <= now:
        return Refuse(409, "the proposed time has passed")
    if open_pair:
        return Refuse(409, "an open request to this partner already exists")
    if daily_full(booked_from, from_p.daily_limit) or daily_full(booked_to, to_p.daily_limit):
        return Refuse(409, "a Daily limit is full on that day")
    return None


def next_status(current: str | None, verb: str, box: str | None) -> str | Refuse:
    """The status `verb` moves a request in `current` status to, for a caller
    holding it in `box` (`received`, `sent`, or None: no party, or no row):
    404 unless `box` is the verb's (the receiver answers, the sender
    cancels), else 409 unless `current` is one the verb moves from."""
    verb_box, movable, new = VERBS[verb]
    if box != verb_box:
        return Refuse(404, "request not found")
    if current not in movable:
        return Refuse(409, "this request is no longer pending")
    return new
