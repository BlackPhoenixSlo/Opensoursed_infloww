from __future__ import annotations

from datetime import datetime
from typing import Any, NamedTuple

from fastapi import Request
from sqlalchemy import select

from db.models import S4SBlock, S4SProfile, UserAccount
from employees import AgencyContext, json_object, owner_context


_OWNER_ONLY = "only the agency owner manages Share for Share"

OPEN = ("pending", "skipped")
# Infloww's limit (s4s0096).
MAX_SENT_PER_DAY = 50
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
    in_agency = select(UserAccount.account_id).where(UserAccount.account_id == S4SProfile.account_id).exists()
    blocked = select(S4SBlock.account_id).where(S4SBlock.agency_user_id == agency_user_id)
    return (S4SProfile.opted_in.is_(True), S4SProfile.discovery_visible.is_(True), in_agency,
            S4SProfile.account_id.not_in(blocked))


class Refuse(NamedTuple):
    status: int
    detail: str


def partner_refusal(from_id: str, partner_account_id: str, blocked: bool) -> Refuse | None:
    if partner_account_id == from_id:
        return Refuse(400, "a Creator cannot send an S4S request to itself")
    if blocked:
        return Refuse(404, "partner not found")
    return None


def daily_full(booked: int, limit: int) -> bool:
    return booked >= limit


def request_refusal(*, from_p: S4SProfile | None, to_p: S4SProfile, sent_today: int, primaries: bool,
                    slot_at: datetime, now: datetime, open_pair: bool, booked_from: int,
                    booked_to: int) -> Refuse | None:
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
    verb_box, movable, new = VERBS[verb]
    if box != verb_box:
        return Refuse(404, "request not found")
    if current not in movable:
        return Refuse(409, "this request is no longer pending")
    return new
