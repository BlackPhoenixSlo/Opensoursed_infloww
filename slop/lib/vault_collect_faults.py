from __future__ import annotations

PACING = "collect_pacing"
ONE_AT_A_TIME = "collect_one_at_a_time"
SKIPS_BUSY = "collect_skips_busy"
FILLS_MIRROR = "collect_fills_mirror"
THUMBS_WARM = "collect_thumbs_warm"
RESUME = "collect_resume"
REWARM = "rewarm_after_switch"
USER_P95 = "user_read_p95"
SECOND_OPEN = "thumbs_second_open_zero_cdn"
ROTATION = "thumbs_survive_rotation"
DEAD_LINK = "thumbs_dead_link_refreshed_once"
RESTRICTED = "thumbs_restricted_chatter_404"
SCOPED = "vault_pro_restricted_chatter_scoped"
PROXY = "proxy_change_invalidates"
STALE_IP = "proxy_change_previews_resign"
UI_TILES = "ui: picker tiles are /admin/vault-ai/thumb (all 200, cold fills disk, second + phone open 0 CDN)"
GIF_PICKER = "ui_gif_picker_caps_attached_loops_and_detaches_offscreen"
UI_HOVER = "ui_hover_scrub_after_proxy_change"
GIF_TILES = "ui_gif_tiles_loop_while_on_screen"
GIF_DETAILS = "ui_gif_details_loops_inline"
GIF_CDN_ONCE = "ui_gif_clip_crosses_cdn_once"


def _need(mod, *names: str) -> None:
    for n in names:
        if not hasattr(mod, n):
            raise RuntimeError(f"slop fault: {mod.__name__}.{n} is gone; update lib/vault_collect_faults.py")


def _unpaced() -> None:
    import vault_collect

    _need(vault_collect, "GAP_S")
    vault_collect.GAP_S = 0


def _ignores_user() -> None:
    import vault_collect

    _need(vault_collect, "_user_active_at")
    vault_collect._user_active_at = lambda aid: None


def _no_rewarm_on_switch() -> None:
    import vault_collect

    _need(vault_collect, "request_rewarm")
    vault_collect.request_rewarm = lambda aid: None


def _thumb_keyed_by_signed_url() -> None:
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
    import vault_stills

    _need(vault_stills, "resolve_fresh", "Fresh")

    async def no_resign(account_id, media_id, client, *, mark_gone=True):
        return vault_stills.Fresh(None, "fetch_failed")

    vault_stills.resolve_fresh = no_resign


def _preview_no_resign() -> None:
    import cdn_resign

    _need(cdn_resign, "resign", "current")

    async def none(account_id, media_id, failed_u, client):
        return None

    cdn_resign.resign = none
    cdn_resign.current = lambda account_id, u: u


def _range_cache_off() -> None:
    import img_clip

    _need(img_clip, "RANGE_CACHE_MAX_BYTES")
    img_clip.RANGE_CACHE_MAX_BYTES = 0


def _folder_gate_off() -> None:
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
        "no-rewarm-on-switch": Fault(_no_rewarm_on_switch, (REWARM,)),
        "thumb-keyed-by-signed-url": Fault(_thumb_keyed_by_signed_url, (ROTATION,)),
        "thumb-no-resign": Fault(_thumb_no_resign, (DEAD_LINK, STALE_IP, UI_HOVER)),
        "preview-no-resign": Fault(_preview_no_resign, (STALE_IP, UI_HOVER)),
        "vault-chatter-folder-gate-off": Fault(_folder_gate_off, (RESTRICTED, SCOPED)),
        # next dev serves each module as a JS string (eval): quotes as \".
        "gif-shown-as-still": Fault(None, (GIF_TILES, GIF_DETAILS), browser=(
            (r'(m\.type !== \\?"video\\?") && m\.type !== \\?"gif\\?"', r'\1'),)),
        "gif-range-cache-off": Fault(_range_cache_off, (GIF_CDN_ONCE,)),
    }
