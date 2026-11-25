from __future__ import annotations

try:
    from .vault_faults import RUN_ITEMS
except ImportError:
    from vault_faults import RUN_ITEMS


def _status_drops_items() -> None:
    import vault_import_decide as d

    real = d.status_body

    def dropping(*args, **kw):
        body = real(*args, **kw)
        return {**body, "items": body["items"][:-1]}

    d.status_body = dropping


def register(Fault) -> dict:
    return {
        "vault-import-status-drops-items": Fault(_status_drops_items, (RUN_ITEMS,)),
    }
