"""Vault Refresh's break-it-once faults (scenarios/2026-11-05-vault-refresh.py): lib/faults.py merges `register(Fault)`
into FAULTS. Every check the scenario records is named here and the scenario imports it."""
from __future__ import annotations

REFRESH_FOLDER = ("vault refresh: after Vault Pro's Refresh the folder rail shows the folder made on OnlyFans since "
                  "the page loaded (desktop and phone), absent before")
REFRESH_MEDIA = ("vault refresh: after Refresh the grid's first tiles are the media made on OnlyFans since, newest "
                 "first, and the mirror holds them in that new folder (DB)")
REFRESH_WIRE = ("vault refresh: one Refresh click = one POST /admin/vault-ai/sync (200, mirror, every new media "
                "counted), OnlyFans got a fresh folder list and a newest-first media read after the click, and the "
                "relay re-cached the folder list (DB)")
REFRESH_FAIL_SHOWN = ("vault refresh: a Refresh while OnlyFans' vault listing fails (500) says so in Vault Pro "
                      "(\"Couldn't reach OnlyFans, showing saved vault\", desktop and phone) and the grid stays")
ALL_COUNTS = ("vault all media: Vault Pro's \"All media\" row shows the whole vault's per-type counts OnlyFans "
              "answers (`all` on GET /api/of/v2/vault/lists, as the browser got it, after Refresh), desktop and phone, "
              "and under it the type chips of an empty type are off")
ALL_TAP = ("vault all media: on a phone (and desktop) tapping a folder then \"All media\" shows the whole vault in "
           "the grid (newest first, in view), and tapping \"All media\" again keeps it")
THUMBS_RELOAD = ("vault picker: page 1 served from the relay's cache with expired thumb urls (CDN 403) reloads "
                 "itself once (one cache invalidate), the CDN then serves each of those paths 200 and every top "
                 "tile draws (desktop and phone); the relay's cached page 1 is the fresh one (DB)")
PICKER_FAILURE = "vault_picker_refresh_pending_single_post_and_failure_note"
SEARCH_PENDING = ("vault search: a caption search only OnlyFans' own search answers spins \"Searching OnlyFans…\" "
                  "in the empty grid while that search is in flight, and never shows \"No data\" from typing to the "
                  "filled grid (desktop and phone)")
SEARCH_FILLS = ("vault search: once OnlyFans answered, the grid is exactly its hits newest first, the spinner gone, "
                "and the mirror holds the term on those media (DB of_terms)")
SYNC_LOAD = ("vault refresh at volume: --users owners pressing Refresh at once on the load Creators: every POST "
             "/admin/vault-ai/sync 200, and each mirror then holds exactly OnlyFans' media (nothing dropped, no "
             "extra, folder membership as OF's)")
SYNC_COALESCED = ("vault refresh at volume: at least five concurrent Refresh presses per Creator start no more "
                  "than two offset-zero OF media walks")

# The app's own code (served unminified by `next dev`), the fix's seams (app/hooks/vaultRefresh.ts,
# app/hooks/useThumbAutoRefresh.ts). `browser_files=2`: `next dev` bundles both modules into each served chunk that
# imports them, and this scenario loads two: app/growth/vault-pro/page.js (Vault Pro) and the chat page's lazy
# components_chat_VaultMediaDetails_tsx chunk (the picker); each pattern lands in both.
_SYNC_URL = (r"/admin/vault-ai/sync\?", "/admin/vault-ai/no-such-sync?")
_AUTO_REFRESH = (r"if \(!thumbCooldown\.claim\(accountId, Date\.now\(\)\)\) return arm\(\);", "return;")  # never reloads
_NO_ALL = (r"\ball: d\.all\b", "all: undefined")   # useVaultMedia.ts: the folder list's `all` dropped (pre-fix)
# VaultManagePanel.tsx before 2026-11-11: an empty grid says "No data" while OF's own search still runs.
_SEARCH_NO_SPINNER = (r"(\.length === 0 && )searchingOf\b", r"\1false")
_FAIL_SILENT = (r"(if \(ofUnreachable\(e\)\) )return false;", r"\1return true;")   # OF unreachable reads as synced


def _no_coalesce() -> None:
    """POST /admin/vault-ai/sync walks OF once per press: `vault_ai_api.relay_coalesce` (looked up per call) swapped
    for a pass-through."""
    import types

    import vault_ai_api

    async def each(_key, fetch):
        return await fetch()

    vault_ai_api.relay_coalesce = types.SimpleNamespace(coalesce=each)


def register(Fault) -> dict:
    return {
        # slop/run vault-refresh --break: the pre-fix Refresh (only invalidateVaultGrid; the sync URL 404s and the
        # client falls through to the reload, which the relay answers from its day-long cache and the mirror).
        # Every sync POST 404s, including the deliberate OF-failure phase and the picker's refresh.
        "vault-refresh-cache-only": Fault(None, (REFRESH_FOLDER, REFRESH_MEDIA, REFRESH_WIRE,
                                                REFRESH_FAIL_SHOWN, PICKER_FAILURE),
                                          browser=(_SYNC_URL,), browser_files=2),
        # slop/run vault-refresh --break --fault=vault-refresh-fail-silent: a failed sync shows the old grid, no word
        "vault-refresh-fail-silent": Fault(None, (REFRESH_FAIL_SHOWN,), browser=(_FAIL_SILENT,), browser_files=2),
        # slop/run vault-refresh --break --fault=vault-all-media-no-counts: All media shows "—", every chip on
        "vault-all-media-no-counts": Fault(None, (ALL_COUNTS,), browser=(_NO_ALL,), browser_files=2),
        # slop/run vault-refresh --break --fault=vault-thumbs-no-auto-refresh: a broken thumb never reloads
        "vault-thumbs-no-auto-refresh": Fault(None, (THUMBS_RELOAD,), browser=(_AUTO_REFRESH,), browser_files=2),
        # slop/run vault-refresh --break --fault=vault-search-no-spinner: "No data" until OF's search answered
        "vault-search-no-spinner": Fault(None, (SEARCH_PENDING,), browser=(_SEARCH_NO_SPINNER,), browser_files=1),
        # slop/run vault-refresh --break --fault=vault-sync-no-coalesce --no-ui
        "vault-sync-no-coalesce": Fault(_no_coalesce, (SYNC_COALESCED,)),
    }
