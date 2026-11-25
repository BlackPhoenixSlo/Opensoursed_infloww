from __future__ import annotations

from collections.abc import Iterable

REPLY_FUNNEL_KIND = "reply_mass_funnel"

_WALKERS: dict[str, str] = {}
_HOLD_MARKS: set[str] = set()


def register_walker(run_kinds: Iterable[str], walker_kind: str, *, hold_mark: str | None = None) -> None:
    for k in run_kinds:
        if _WALKERS.setdefault(k, walker_kind) != walker_kind:
            raise ValueError(f"run kind {k!r} already walked by {_WALKERS[k]!r}")
    if hold_mark:
        _HOLD_MARKS.add(hold_mark)


def _ensure_loaded() -> None:
    from automation_registry import load_automation_plugins
    load_automation_plugins()


def walker_for(run_kind: str | None) -> str:
    _ensure_loaded()
    return _WALKERS.get(run_kind, REPLY_FUNNEL_KIND) if run_kind is not None else REPLY_FUNNEL_KIND


def has_mark(last_error: str | None, mark: str) -> bool:
    return last_error is not None and (last_error == mark or last_error.startswith(mark + ":"))


def is_hold(last_error: str | None) -> bool:
    _ensure_loaded()
    return any(has_mark(last_error, m) for m in _HOLD_MARKS)
