"""The vault week-cache flows' break-it-once faults (scenarios/2026-11-05-vault-collect.py,
2026-11-05-vault-thumbs.py): lib/faults.py merges `register(Fault)` into FAULTS. Check names live here and the
scenarios import them. Each patches one product module attribute inside the relay; a missing attribute raises
(the relay fails to boot: INFRA, never a silent no-op fault).
"""
from __future__ import annotations

PACING = "collect_pacing"
ONE_AT_A_TIME = "collect_one_at_a_time"
SKIPS_BUSY = "collect_skips_busy"
FILLS_MIRROR = "collect_fills_mirror"
THUMBS_WARM = "collect_thumbs_warm"
RESUME = "collect_resume"
USER_P95 = "user_read_p95"
SECOND_OPEN = "thumbs_second_open_zero_cdn"
ROTATION = "thumbs_survive_rotation"
DEAD_LINK = "thumbs_dead_link_refreshed_once"
RESTRICTED = "thumbs_restricted_chatter_404"
SCOPED = "vault_pro_restricted_chatter_scoped"
PROXY = "proxy_change_invalidates"


def _need(mod, *names: str) -> None:
    for n in names:
        if not hasattr(mod, n):
            raise RuntimeError(f"slop fault: {mod.__name__}.{n} is gone; update lib/vault_collect_faults.py")


def _unpaced() -> None:
    """The collector's gap between OF calls is 0: it walks a vault as fast as OF answers."""
    import vault_collect

    _need(vault_collect, "GAP_S")
    vault_collect.GAP_S = 0


def _ignores_user() -> None:
    """The collector never sees anyone using an account (the user-lane timestamp reads as None)."""
    import vault_collect

    _need(vault_collect, "_user_active_at")
    vault_collect._user_active_at = lambda aid: None


def _thumb_keyed_by_signed_url() -> None:
    """The permanent thumb is stored under the mirror's CURRENT signed url (sha1), not the media id: OF re-signing
    the url (every listing) strands the stored file."""
    import hashlib
    import os
    import sqlite3

    import vault_stills

    _need(vault_stills, "thumb_path")
    real = vault_stills.thumb_path
    db = os.environ["CHATTERLY_DB_URL"].removeprefix("sqlite:///")

    def keyed(account_id, media_id):
        con = sqlite3.connect(db)
        try:
            row = con.execute("SELECT thumb_url FROM vault_items WHERE account_id=? AND media_id=?",
                              (str(account_id), int(media_id))).fetchone()
        finally:
            con.close()
        p = real(account_id, media_id)
        return p.with_name(f"{media_id}-{hashlib.sha1(row[0].encode()).hexdigest()[:12]}.jpg") if row and row[0] else p

    vault_stills.thumb_path = keyed


def _thumb_no_resign() -> None:
    """A dead thumb url is never re-signed through /vault/media/{id}: the by-id read answers nothing."""
    import vault_stills

    _need(vault_stills, "resolve_fresh", "Fresh")

    async def no_resign(account_id, media_id, client, *, mark_gone=True):
        return vault_stills.Fresh(None, "fetch_failed")

    vault_stills.resolve_fresh = no_resign


def _folder_gate_off() -> None:
    """The chatter folder gate answers "no restriction" on every mirror route (vault_ai_api: the listing, stills,
    search-of, the pack picker, disputes, flags review; vault: media-stats): a restricted chatter sees, counts and
    writes the whole vault (bug class: a route that forgot the gate, or a gate that abstains)."""
    import vault
    import vault_ai_api

    _need(vault_ai_api, "allowed_folder_ids_for_chatter")
    _need(vault, "allowed_folder_ids_for_chatter")

    async def unrestricted(account_id):
        return None

    vault_ai_api.allowed_folder_ids_for_chatter = unrestricted
    vault.allowed_folder_ids_for_chatter = unrestricted


def register(Fault) -> dict:
    return {
        "collect-unpaced": Fault(_unpaced, (PACING,)),
        "collect-ignores-user": Fault(_ignores_user, (SKIPS_BUSY,)),
        "thumb-keyed-by-signed-url": Fault(_thumb_keyed_by_signed_url, (ROTATION,)),
        "thumb-no-resign": Fault(_thumb_no_resign, (DEAD_LINK,)),
        # slop/run vault-thumbs --break --fault=vault-chatter-folder-gate-off: both gate checks go red.
        "vault-chatter-folder-gate-off": Fault(_folder_gate_off, (RESTRICTED, SCOPED)),
    }
