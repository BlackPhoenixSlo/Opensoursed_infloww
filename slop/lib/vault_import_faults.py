"""The vault import routes' relay-side break-it-once fault (scenarios/2026-10-30-vault-import-reducer.py):
lib/faults.py merges `register(Fault)` into FAULTS. The flow's check names live in lib/vault_faults.py (imported,
never copied), so a target can never name a check that does not exist. Patches a product function's module
attribute in the relay: the routes call `vault_import_decide.<rule>` by module attribute per request.
"""
from __future__ import annotations

try:
    from .vault_faults import RUN_ITEMS
except ImportError:  # inside the relay lib/ is on sys.path, not a package
    from vault_faults import RUN_ITEMS


def _status_drops_items() -> None:
    """GET /api/of/v2/vault/upload/status loses the run's last item from `items`. The counts and `total` are
    built from the whole list before the drop, so the card's summary ('N in vault') is unchanged; only the
    run's own item list (RUN_ITEMS) can see it."""
    import vault_import_decide as d

    real = d.status_body

    def dropping(*args, **kw):
        body = real(*args, **kw)
        return {**body, "items": body["items"][:-1]}

    d.status_body = dropping


def register(Fault) -> dict:
    return {
        # slop/run 2026-10-30-vault-import-reducer --break --fault=vault-import-status-drops-items
        "vault-import-status-drops-items": Fault(_status_drops_items, (RUN_ITEMS,)),
    }
