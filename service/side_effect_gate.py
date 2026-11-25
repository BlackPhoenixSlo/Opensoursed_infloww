from __future__ import annotations

from typing import Any

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
