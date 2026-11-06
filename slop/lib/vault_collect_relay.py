"""The vault week-cache flows' relay part (scenarios/2026-11-05-vault-collect.py, 2026-11-05-vault-thumbs.py):
lib/relay.py imports it before the service. Inert unless the run's RELAY_ENV sets SLOP_VAULT_STILLS=1.

At import (before vault_stills reads its env), with SLOP_VAULT_STILLS=1 and $DEMO_SHOTS_TMP set:
  1. vault_stills' permanent stores (VAULT_THUMB_DIR / VAULT_IMAGE_DIR / VAULT_POSTER_DIR) and
     storyboard's STORYBOARD_DIR -> $DEMO_SHOTS_TMP/vault-stills/{thumbs,images,posters,storyboards}
     (`stills_dir(tmp)`), never the laptop's shared /tmp/of-relay-vault-*. A relay restart keeps them
     (same $DEMO_SHOTS_TMP): that is the durability the flow is about.
  2. (wire) the collector's periodic started on relay startup (CHATTERLY_TEST_MODE skips the product's own
     registration in server._start_event_pumps).

Nothing is served here: the scenarios read the temp SQLite (vault_cache_runs, vault_items,
vault_response_cache), the stills dirs, lib/of_wire's records and img_relay's /__slop/img/calls.

The scenarios arm lib/img_relay.py with `pictures=True` (vault_stills keeps only bodies with image magic).

Bypasses (declared): the collector's periodic is started here, not by server._start_event_pumps (same call, same knobs).
"""
import os
from pathlib import Path

DIRS = {"VAULT_THUMB_DIR": "thumbs", "VAULT_IMAGE_DIR": "images", "VAULT_POSTER_DIR": "posters",
        "STORYBOARD_DIR": "storyboards"}


def stills_dir(tmp) -> Path:
    return Path(tmp) / "vault-stills"


def _on() -> bool:
    return os.environ.get("SLOP_VAULT_STILLS") == "1" and bool(os.environ.get("DEMO_SHOTS_TMP"))


if _on():
    for _var, _sub in DIRS.items():
        _d = stills_dir(os.environ["DEMO_SHOTS_TMP"]) / _sub
        _d.mkdir(parents=True, exist_ok=True)
        os.environ[_var] = str(_d)


def wire(app, loopback, relay) -> None:
    """2. The collector's periodic, as server._start_event_pumps registers it (same `_periodic`, label, TICK_S and
    FIRST_AFTER_S): CHATTERLY_TEST_MODE=1 skips that whole function in a slop relay. Only with SLOP_VAULT_STILLS=1
    and vault_collect.ENABLED (VAULT_COLLECT_ENABLED != 0)."""
    if not _on():
        return

    async def start() -> None:
        import asyncio

        import relay_host
        import vault_collect

        if vault_collect.ENABLED:
            srv = relay_host.live_server()
            asyncio.create_task(srv._periodic("vault collect", vault_collect.TICK_S, vault_collect.tick,
                                              first_after_s=vault_collect.FIRST_AFTER_S), name="vault-collect")

    app.on_event("startup")(start)
