from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from automations._pools import int_list


def list_ids_of(payload: dict) -> tuple[list[int], list[int]]:
    return int_list(payload.get("list_ids")), int_list(payload.get("exclude_list_ids"))


def seed(payload: dict, list_members: list[int],
         exclude_members: list[int]) -> tuple[list[int], list[int]]:
    included = int_list(payload.get("included_users") or payload.get("fan_ids"))
    excluded = int_list(payload.get("excluded_users"))
    return included + list(list_members), excluded + list(exclude_members)


def opener_media_of(opening_media_ids: str | None) -> list[int]:
    try:
        return int_list(json.loads(opening_media_ids or "[]"))
    except Exception:
        return []


@dataclass(frozen=True)
class Funnel:
    id: int
    opening_message: str | None


@dataclass(frozen=True)
class Skip:
    reason: Literal["no_text", "empty_audience"]


@dataclass(frozen=True)
class Plan:
    funnel_id: int | None
    text: str
    recipients: list[int]
    excl_set: frozenset[int]
    list_ids: list[int]
    user_lists: list
    excluded_user_lists: list
    online_only: bool
    filters: dict | None
    price: object
    media_files: list[int]
    previews: list[int]
    skipped_answered: list[int]

    @property
    def is_list_audience(self) -> bool:
        # Mass Online: OF resolves the audience server-side, so online_only/filters count with no explicit recipients.
        return bool(self.user_lists or self.online_only or self.filters)


def plan(payload: dict, *, funnel: Funnel | None, resolved: dict,
         list_ids: list[int], opener_media: list[int]) -> Plan | Skip:
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
    online_only = bool(payload.get("online_only"))
    filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else None
    text = payload.get("text") or (funnel.opening_message if funnel else None)
    if not text:
        return Skip("no_text")
    if not recipients and not user_lists and not online_only and not filters:
        return Skip("empty_audience")

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


def audience_filter_json(*, user_lists, included_users, excluded_users,
                         excluded_user_lists, online, filters, list_ids=(),
                         ref=None, fence: bool = False, auto_exclude=None) -> str:
    explicit = bool(included_users) and not (user_lists or online or filters)
    unresolved = [x for x in (excluded_user_lists or [])
                  if not explicit and str(x) != str(auto_exclude)]
    return json.dumps({
        "user_lists": list(user_lists or []),
        "included_users": list(included_users or []),
        "excluded_users": list(excluded_users or []),
        "list_ids": list(list_ids or []),
        "ref": str(ref) if ref else None,
        "excluded_user_lists": list(excluded_user_lists or []),
        "fence": bool(fence),
        "online": bool(online),
        "filters": bool(filters),
        "auto_exclude_list": auto_exclude,
        "unresolved_exclude_lists": unresolved,
    })


def audience_filter(p: Plan, *, ref, fence: bool, auto_exclude=None) -> str:
    return audience_filter_json(
        user_lists=p.user_lists, included_users=p.recipients,
        excluded_users=sorted(p.excl_set), excluded_user_lists=p.excluded_user_lists,
        online=p.online_only, filters=p.filters, list_ids=p.list_ids,
        ref=ref, fence=fence, auto_exclude=auto_exclude)


def echoed_of(result) -> list[tuple[int, int]]:
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


def is_dry_run(payload: dict) -> bool:
    return bool(payload.get("dry_run"))


def dry_run_result(p: Plan) -> dict:
    reason = None
    if p.is_list_audience:
        reason = "online_or_filtered" if p.online_only or p.filters else "list_audience"
    elif p.excluded_user_lists:
        reason = "excluded_lists_unresolved"
    would_send = None if reason else list(p.recipients)
    out = {"status": "ok", "dry_run": True, "sent": 0,
           "would_send": would_send,
           "would_send_count": len(would_send) if would_send is not None else None,
           "audience": "list" if p.is_list_audience else "explicit"}
    if reason:
        out["reason"] = reason
    return out
