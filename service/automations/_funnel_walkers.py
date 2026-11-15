"""automations/_funnel_walkers.py — which automation walks a mass run's funnel, and when a walk is held.

Shared by every reader of `funnel_state` that is not the walker itself (Full AI's owner check):

  - `register_walker(run_kinds, walker_kind, *, hold_mark=None)`: a walker module, at import, names
    the `mass_runs.automation_kind`s it walks and the `last_error` mark it writes on a held walk.
  - `walker_for(run_kind) -> str`: the walker's rule kind; an unregistered run (a plain mass,
    `None`) is walked by `reply_mass_funnel`.
  - `has_mark(last_error, mark)`: `last_error` is `mark`, or it with a `:<reason>`.
  - `is_hold(last_error)`: `last_error` carries any registered hold mark.

The walker modules are automation plugins, so the readers load them first
(`automation_registry.load_automation_plugins`, idempotent).
"""
from __future__ import annotations

from collections.abc import Iterable

REPLY_FUNNEL_KIND = "reply_mass_funnel"

_WALKERS: dict[str, str] = {}       # mass run kind -> walker rule kind
_HOLD_MARKS: set[str] = set()


def register_walker(run_kinds: Iterable[str], walker_kind: str, *, hold_mark: str | None = None) -> None:
    """Map each run kind to `walker_kind` (once; another walker for the same kind raises)."""
    for k in run_kinds:
        if _WALKERS.setdefault(k, walker_kind) != walker_kind:
            raise ValueError(f"run kind {k!r} already walked by {_WALKERS[k]!r}")
    if hold_mark:
        _HOLD_MARKS.add(hold_mark)


def _ensure_loaded() -> None:
    from automation_registry import load_automation_plugins
    load_automation_plugins()


def walker_for(run_kind: str | None) -> str:
    """The rule kind of the automation that walks a run of `run_kind`."""
    _ensure_loaded()
    return _WALKERS.get(run_kind, REPLY_FUNNEL_KIND) if run_kind is not None else REPLY_FUNNEL_KIND


def has_mark(last_error: str | None, mark: str) -> bool:
    """`last_error` is `mark`, or it with a `:<reason>`."""
    return last_error is not None and (last_error == mark or last_error.startswith(mark + ":"))


def is_hold(last_error: str | None) -> bool:
    """`last_error` marks a held walk (any registered walker's hold mark)."""
    _ensure_loaded()
    return any(has_mark(last_error, m) for m in _HOLD_MARKS)
