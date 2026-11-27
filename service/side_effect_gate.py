from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import platforms

log = logging.getLogger(__name__)

PLATFORM_LACKS_PREFIX = "platform_lacks:"
PLATFORM_UNKNOWN_PREFIX = "platform_unknown:"

_ABSENT = object()
_MARKERS = (("unsupported", "platform_unsupported"), ("blocked", "platform_blocked"),
            ("live_check", "platform_live_check"))


def classify(client: Any, name: str) -> tuple[str, str | None]:
    attr = getattr(client, name, _ABSENT)
    if attr is _ABSENT:
        return "missing", f"{name} is not on this platform"
    for verdict, marker in _MARKERS:
        reason = getattr(attr, marker, None)
        if reason:
            return verdict, reason
    return "built", None


def refusal(client: Any, name: str) -> str | None:
    return classify(client, name)[1]


@dataclass(frozen=True)
class FanTarget:
    fan_id: str


@dataclass(frozen=True)
class ListTarget:
    list_id: str


Target = FanTarget | ListTarget


@dataclass(frozen=True)
class ListAudience:
    list_id: str
    member_ids: frozenset[str]
    complete: bool


LIVE_CHECK_ENV = "PLATFORM_LIVE_CHECK"
LIVE_CHECK_LANES: frozenset[str] = frozenset({"priority_mass"})
_LIST_TARGET_METHODS = frozenset({"delete_list"})
_WARNED: set[str] = set()
_BAD_PART = re.compile(r"[:=\s]")


def _parse_grant(entry: str) -> tuple[str, str, Target] | None:
    aid, method, target = (entry.split(":", 2) + ["", ""])[:3]
    kind, _, tid = target.partition("=")
    if not (aid and method and tid) or method != method.lower() or any(
            _BAD_PART.search(p) for p in (aid, method, tid)):
        return None
    if kind == "fan" and method not in _LIST_TARGET_METHODS:
        return aid, method, FanTarget(tid)
    if kind == "list" and method in _LIST_TARGET_METHODS:
        return aid, method, ListTarget(tid)
    return None


def _grants() -> list[tuple[str, str, Target]]:
    out = []
    for entry in os.environ.get(LIVE_CHECK_ENV, "").split(","):
        if not (entry := entry.strip()):
            continue
        if (grant := _parse_grant(entry)) is not None:
            out.append(grant)
        elif entry not in _WARNED:
            _WARNED.add(entry)
            log.warning("%s entry %r ignored: needs <aid>:<method>:fan=<id> or <aid>:delete_list:list=<id>",
                        LIVE_CHECK_ENV, entry)
    return out


def live_check_targets(account_id: str, method: str) -> frozenset[Target]:
    return frozenset(t for a, m, t in _grants() if a == account_id and m == method)


def live_check_methods(account_id: str) -> frozenset[str]:
    return frozenset(m for a, m, _ in _grants() if a == account_id)


def live_check(account_id: str, method: str, audience: frozenset[str] | ListAudience) -> str | None:
    grants = [(m, t) for a, m, t in _grants() if a == account_id]
    targets = {t for m, t in grants if m == method}
    if isinstance(audience, ListAudience):
        if audience.complete is not True or not isinstance(audience.member_ids, frozenset):
            return _lacks(method)
        members = audience.member_ids
        fans = {t.fan_id for _, t in grants if isinstance(t, FanTarget)}
        if ListTarget(audience.list_id) in targets and members <= fans:
            return None
    elif isinstance(audience, frozenset):
        members = audience
    else:
        return _lacks(method)
    if len(members) == 1 and FanTarget(next(iter(members))) in targets:
        return None
    return _lacks(method)


def _lacks(method: str) -> str:
    return f"{PLATFORM_LACKS_PREFIX}{method}"


def _delete_list_gated(account_id: str) -> bool:
    from platforms import for_account

    return is_live_check_name(for_account(account_id), "delete_list")


def _delete_list_ungranted(account_id: str, list_id: Any) -> str | None:
    targets = live_check_targets(account_id, "delete_list")
    granted = bool(targets) if list_id is None else ListTarget(str(list_id)) in targets
    return None if granted else _lacks("delete_list")


def delete_list_ungranted(account_id: str, list_id: Any = None) -> str | None:
    return _delete_list_ungranted(account_id, list_id) if _delete_list_gated(account_id) else None


def delete_list_refusal(account_id: str, list_id: Any, read: Callable[[], ListAudience]) -> str | None:
    if not _delete_list_gated(account_id):
        return None
    return _delete_list_ungranted(account_id, list_id) or live_check(account_id, "delete_list", read())


def is_live_check_name(platform: platforms.Platform, name: str) -> bool:
    if platform.backend is None:
        return False
    return name in LIVE_CHECK_LANES or classify(platform.backend.Shim, name)[0] == "live_check"


def send_refusal(platform: platforms.Platform, payload: Mapping[str, Any], *,
                 would_cotag: bool = False) -> str | None:
    from platforms import UnknownPlatform, unknown_reason

    if isinstance(platform, UnknownPlatform):
        return unknown_reason(platform.key)
    if platform.backend is None:
        return None
    return platform.backend.Shim.send_refusal(
        {**payload, "tagged_users": payload.get("tagged_users") or would_cotag})


def refuse_if_platform_lacks(account_id: str, name: str, what: str) -> None:
    from platforms import refusal_for_account

    raise_if_refused(refusal_for_account(account_id, name), what)


def raise_if_refused(reason: str | None, what: str) -> None:
    if reason is not None:
        from fastapi import HTTPException

        raise HTTPException(status_code=501, detail=f"{what}: not on this platform")
