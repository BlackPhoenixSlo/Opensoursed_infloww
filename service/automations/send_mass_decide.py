"""service/automations/send_mass_decide.py — the pure half of the A10 mass broadcast run.

No DB, no OF, no clock: every function maps a payload + rows already read to a
value. (Named without the sender's module name on purpose: test_audience_coverage
scans for send-primitive tokens and this file sends nothing.) The A10 sender
module owns the reads (funnel row, list members, opener media, the
contact-guard resolution) and the effects (Auto_Exclude sync, mass_runs mint,
the OF broadcast, per-recipient rows), in that order:

    list_ids_of                      -> which DB lists to read
    seed(payload, members...)        -> the pre-guard audience handed to resolve_mass_audience
    plan(payload, funnel, resolved,  -> Plan | Skip   (dedupe, exclusions win, text, media)
         list_ids, opener_media)
    audience_filter / echoed_of      -> the mass_runs forensics JSON / OF's per-fan echo
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from automations._pools import int_list


def list_ids_of(payload: dict) -> tuple[list[int], list[int]]:
    """(list_ids, exclude_list_ids) — our DB list ids whose members to read."""
    return int_list(payload.get("list_ids")), int_list(payload.get("exclude_list_ids"))


def seed(payload: dict, list_members: list[int],
         exclude_members: list[int]) -> tuple[list[int], list[int]]:
    """(included, excluded) before the contact guard: explicit fans + DB-list
    members, explicit excludes + exclude-list members. Order kept, dups kept
    (plan dedupes after the guard)."""
    included = int_list(payload.get("included_users") or payload.get("fan_ids"))
    excluded = int_list(payload.get("excluded_users"))
    return included + list(list_members), excluded + list(exclude_members)


def opener_media_of(opening_media_ids: str | None) -> list[int]:
    """A FunnelAccountMedia.opening_media_ids JSON -> its vault media ids;
    unreadable JSON -> no media. (The opener has no preview slot of its own.)"""
    try:
        return int_list(json.loads(opening_media_ids or "[]"))
    except Exception:
        return []


@dataclass(frozen=True)
class Funnel:
    """The funnel row fields the plan reads."""
    id: int
    opening_message: str | None


@dataclass(frozen=True)
class Skip:
    reason: Literal["no_text", "empty_audience"]


@dataclass(frozen=True)
class Plan:
    funnel_id: int | None
    text: str
    recipients: list[int]          # known fans, deduped, order kept, excludes dropped
    excl_set: frozenset[int]
    list_ids: list[int]
    user_lists: list               # OF list names / ids, passed through
    excluded_user_lists: list      # OF list names / ids, passed through
    online_only: bool
    filters: dict | None
    price: object                  # passed through to OF + _to_cents
    media_files: list[int]
    previews: list[int]
    skipped_answered: list[int]

    @property
    def is_list_audience(self) -> bool:
        return bool(self.user_lists or self.online_only or self.filters)


def plan(payload: dict, *, funnel: Funnel | None, resolved: dict,
         list_ids: list[int], opener_media: list[int]) -> Plan | Skip:
    """The broadcast to make, from the payload, the funnel row,
    resolve_mass_audience's output and the model's opener media (read only for
    a funnel send with no explicit media) — or why there is none."""
    excl_set = set(resolved["excluded_users"])
    seen: set[int] = set()
    recipients: list[int] = []
    for fid in resolved["included_users"]:
        if fid in excl_set or fid in seen:
            continue
        seen.add(fid)
        recipients.append(fid)

    user_lists = payload.get("user_lists") or []
    excluded_user_lists = payload.get("excluded_user_lists") or []
    # Mass Online: OF resolves the audience server-side, so online_only/filters
    # count as an audience even with no explicit recipients/user_lists.
    online_only = bool(payload.get("online_only"))
    filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else None
    text = payload.get("text") or (funnel.opening_message if funnel else None)
    if not text:
        return Skip("no_text")
    if not recipients and not user_lists and not online_only and not filters:
        return Skip("empty_audience")

    # No explicit media but a funnel send → the model's per-account opener media
    # (vault ids are per-account; the funnel only holds shared text).
    media_files = int_list(payload.get("media_files"))
    if not media_files and funnel is not None:
        media_files = list(opener_media)
    return Plan(
        funnel_id=funnel.id if funnel is not None else None,
        text=text,
        recipients=recipients,
        excl_set=frozenset(excl_set),
        list_ids=list_ids,
        user_lists=user_lists,
        excluded_user_lists=excluded_user_lists,
        online_only=online_only,
        filters=filters,
        price=payload.get("price") or 0,
        media_files=media_files,
        previews=int_list(payload.get("previews")),
        skipped_answered=resolved.get("skipped_funnel_responders") or [],
    )


def audience_filter(p: Plan, *, ref, fence: bool) -> str:
    """The mass_runs.audience_filter forensics JSON (key order is the stored
    shape). Takes the post-fence plan: recipients after the include-only
    intersection, excluded_user_lists with the AUTOFENCE / Auto_Exclude ids."""
    return json.dumps({
        "user_lists": list(p.user_lists),
        "included_users": p.recipients,
        "excluded_users": sorted(p.excl_set),
        "list_ids": p.list_ids,
        "ref": str(ref) if ref else None,
        # OF has no per-user exclusion field for a list audience, so every
        # excluded id rides in an OF list; the recipient set itself is read from
        # OF's rosters at close (plans/blast-splice A.2).
        "excluded_user_lists": list(p.excluded_user_lists),
        "fence": fence,
    })


def echoed_of(result) -> list[tuple[int, int]]:
    """(fan_id, message_id) for each per-fan message OF echoed back, in order;
    malformed entries dropped."""
    msgs = result.get("messages") if isinstance(result, dict) else None
    if not isinstance(msgs, list):
        return []
    out: list[tuple[int, int]] = []
    for m in msgs:
        if not isinstance(m, dict):
            continue
        fid_raw = m.get("userId") or m.get("toUserId") or m.get("recipientId")
        mid_raw = m.get("id") or m.get("messageId")
        try:
            out.append((int(fid_raw), int(mid_raw)))
        except (TypeError, ValueError):
            continue
    return out
