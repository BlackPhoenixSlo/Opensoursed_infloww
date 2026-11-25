from __future__ import annotations

from typing import Any

PLATFORM_LACKS_PREFIX = "platform_lacks:"

_ABSENT = object()
_MARKERS = (("unsupported", "fansly_unsupported"), ("blocked", "fansly_blocked"))


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


def refuse_if_platform_lacks(account_id: str, name: str, what: str) -> None:
    from platforms import refusal_for_account

    raise_if_refused(refusal_for_account(account_id, name), what)


def raise_if_refused(reason: str | None, what: str) -> None:
    if reason is not None:
        from fastapi import HTTPException

        raise HTTPException(status_code=501, detail=f"{what}: not on this platform")
