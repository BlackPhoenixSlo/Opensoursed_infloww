from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Iterable, Mapping
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
LIVE_CHECK_LANES: frozenset[str] = frozenset({"priority_mass", "nudge_online"})
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


def live_check_gated(account_id: str, method: str) -> bool:
    from platforms import for_account

    return is_live_check_name(for_account(account_id), method)


def _ungranted(account_id: str, method: str, target: Target | None) -> str | None:
    targets = live_check_targets(account_id, method)
    return None if (target in targets if target is not None else targets) else _lacks(method)


def live_check_ungranted(account_id: str, method: str, target: Target | None = None) -> str | None:
    return _ungranted(account_id, method, target) if live_check_gated(account_id, method) else None


def live_check_fan(account_id: str, method: str, fan_id: int) -> str | None:
    return live_check(account_id, method, frozenset({str(fan_id)})) if live_check_gated(account_id, method) else None


def _list_target(list_id: Any) -> ListTarget | None:
    return None if list_id is None else ListTarget(str(list_id))


def delete_list_ungranted(account_id: str, list_id: Any = None) -> str | None:
    return live_check_ungranted(account_id, "delete_list", _list_target(list_id))


def delete_list_refusal(account_id: str, list_id: Any, client: Any,
                        read: Callable[[], ListAudience]) -> str | None:
    verdict, reason = classify(client, "delete_list")
    if verdict != "live_check" and reason:
        return reason
    if not live_check_gated(account_id, "delete_list"):
        return None
    return _ungranted(account_id, "delete_list", _list_target(list_id)) or live_check(account_id, "delete_list", read())


def delete_list_checked(account_id: str, list_id: Any, client: Any,
                        read: Callable[[], ListAudience]) -> str | None:
    if reason := delete_list_refusal(account_id, list_id, client, read):
        return reason
    client.delete_list(list_id)
    return None


def is_live_check_name(platform: platforms.Platform, name: str) -> bool:
    if platform.backend is None:
        return False
    return name in LIVE_CHECK_LANES or classify(platform.backend.Shim, name)[0] == "live_check"


def branch_refusal(account_id: str, method: str, branch: str) -> str | None:
    from platforms import for_account

    backend = for_account(account_id).backend
    blocked = getattr(getattr(backend.Shim, method, None), "platform_blocked_branches", {}) if backend else {}
    return f"{PLATFORM_LACKS_PREFIX}{method}:{branch}" if branch in blocked else None


def send_refusal(platform: platforms.Platform, payload: Mapping[str, Any], *,
                 would_cotag: bool = False) -> str | None:
    from platforms import UnknownPlatform, unknown_reason

    if isinstance(platform, UnknownPlatform):
        return unknown_reason(platform.key)
    if platform.backend is None:
        return None
    return platform.backend.Shim.send_refusal(
        {**payload, "tagged_users": payload.get("tagged_users") or would_cotag})


def burst_refusal(account_id: str, fan_id: int, parts: Iterable[Mapping[str, Any]] = ()) -> str | None:
    from audiences import lacks_reason
    from platforms import UnknownPlatform, for_account, unknown_reason
    import media_cotag

    platform = for_account(account_id)
    if isinstance(platform, UnknownPlatform):
        return unknown_reason(platform.key)
    backend = platform.backend
    if backend is None:
        return None
    if classify(backend.Shim, "send_message")[0] not in ("built", "live_check"):
        return _lacks("send_message")
    if reason := live_check_fan(account_id, "send_message", fan_id):
        return reason
    for part in parts:
        media = list(part.get("media_files") or [])
        if reason := send_refusal(platform, part, would_cotag=media_cotag.would_cotag(account_id, media)):
            return reason
        try:
            backend.check_sendable(media_files=media, price=part.get("price") or 0, previews=part.get("previews"))
        except backend.APIError as e:
            if reason := lacks_reason(e):
                return reason
            raise
    return None


def burst_run_reason(refused: str | None, sent: int) -> dict[str, str]:
    if refused is None:
        return {}
    return {"reason": f"partial:{refused}" if sent else refused}


def refuse_if_platform_lacks(account_id: str, name: str, what: str) -> None:
    from platforms import refusal_for_account

    raise_if_refused(refusal_for_account(account_id, name), what)


def raise_if_refused(reason: str | None, what: str) -> None:
    if reason is not None:
        from fastapi import HTTPException

        raise HTTPException(status_code=501, detail=f"{what}: not on this platform")
