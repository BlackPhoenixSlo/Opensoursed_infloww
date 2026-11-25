from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Awaitable, Callable

log = logging.getLogger("of-relay.automation.registry")

Automation = Callable[..., Awaitable[dict]]
_REGISTRY: dict[str, Automation] = {}

# Retired kind -> live name; the one home for renames, delete an entry once prod rows are migrated
LEGACY_KINDS: dict[str, str] = {
    "of_ai_chat": "welcome_chatter_for_info",
}


def canonical_kind(kind: str) -> str:
    return LEGACY_KINDS.get(kind, kind)


def legacy_names(kind: str) -> tuple[str, ...]:
    return tuple(old for old, new in LEGACY_KINDS.items() if new == kind)


def kind_family(kind: str) -> tuple[str, ...]:
    live = canonical_kind(kind)
    return (live,) + legacy_names(live)


def register(kind: str) -> Callable[[Automation], Automation]:
    def deco(fn: Automation) -> Automation:
        prev = _REGISTRY.get(kind)
        if prev is not None and prev is not fn:
            log.warning(
                "automation_kind_reregistered kind=%s old=%s new=%s",
                kind, getattr(prev, "__name__", prev), getattr(fn, "__name__", fn),
            )
        _REGISTRY[kind] = fn
        return fn
    return deco


def get_automation(kind: str) -> Automation | None:
    return _REGISTRY.get(canonical_kind(kind))


def registered_kinds() -> list[str]:
    return sorted(_REGISTRY)


# scrape_chats is known by fiat: it registers from automation_executor, which the rules/transfer APIs never import
def is_registered(kind: str) -> bool:
    load_automation_plugins()
    return canonical_kind(kind) in _REGISTRY or kind == "scrape_chats"


# Tells "failed to load" (loud) from "retired" (inert): both look unregistered
_FAILED_PLUGINS: set[str] = set()


def failed_plugins() -> frozenset[str]:
    return frozenset(_FAILED_PLUGINS)


_PLUGINS_LOADED = False


def load_automation_plugins() -> None:
    global _PLUGINS_LOADED
    if _PLUGINS_LOADED:
        return
    _PLUGINS_LOADED = True
    try:
        import automations
    except Exception:
        log.warning("automations_package_import_failed", exc_info=True)
        return
    for mod in pkgutil.iter_modules(automations.__path__, automations.__name__ + "."):
        try:
            importlib.import_module(mod.name)
            log.info("automation_plugin_loaded module=%s", mod.name)
        except Exception:
            _FAILED_PLUGINS.add(mod.name.rsplit(".", 1)[-1])
            log.warning("automation_plugin_import_failed module=%s", mod.name, exc_info=True)
