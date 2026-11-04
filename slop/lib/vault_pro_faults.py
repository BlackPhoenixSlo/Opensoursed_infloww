"""Vault Pro at 20k's break-it-once faults (scenarios/2026-11-01-vault-pro-20k.py): lib/faults.py merges
`register(Fault)` into FAULTS. Every correctness check the scenario records is named here and the scenario
imports it, so a target can never name a check that does not exist. The latency budgets are named in the scenario
(budgets live in the scenario file) and no fault targets them; a fault never targets a check still KNOWN_RED in the
scenario.

Deviation (declared): `vault-items-page-overlap` swaps the route's endpoint (`APIRoute.dependant.call`, FastAPI
internals), not a product module attribute: FastAPI keeps its own reference to `vault_ai_api.local_items`, and
the paging (`.limit(limit + 1).offset(offset)`) is inline in it, with no module-level helper to patch.
"""
from __future__ import annotations

PAGING = ("vault pro: every GET /admin/vault-ai/items walk (each filter, each Creator) pages every item exactly "
          "once: full pages with hasMore until the last, no id twice, in the sort's order")
FILTERS = ("vault pro: every items filter (type, sort, search, OF folder, AI folder) returns exactly the SQL set "
           "for it")
DUPES = ("vault pro: GET /duplicates at each strictness (0, 2, 4, 6) == the seed's planted re-upload groups "
         "(originals, copies, planted distances, exact, band, counts)")
HIDE = ("vault pro: POST /duplicates/hide hides exactly the ticked copies (OnlyFans got them, removed_at set); "
        "the keeper, a non-copy and sent copies (no allow_sent) are refused and untouched")
HIDE_STRICT0 = ("vault pro: POST /duplicates/hide at strictness 0 refuses a copy that is one only at 2 (not a "
                "duplicate at 0) and leaves it untouched (no OnlyFans call, removed_at unset)")
SUMMARY_BEFORE = "vault pro: GET /cache/summary == SQL (live count, last sweep) [before]"
SUMMARY_AFTER = "vault pro: GET /cache/summary == SQL (live count, last sweep) [after hide]"
OF_FOLDERS = "vault pro: GET /of-folders == the folders and per-kind counts of the mirror's listStates (SQL)"
FLAGS = ("vault pro: GET /flags-review totals (known flags, graded at this version) == SQL, iffy == the seed's "
         "planted suspects, items all flagged, only_iffy narrows to exactly those")
UI_HIDE = ("vault pro UI: the Duplicates modal shows the relay's sets, and its Remove hides exactly the copies it "
           "sent less the sent ones (DB removed_at, OnlyFans); every keeper kept")


def _items_page_overlap() -> None:
    """GET /admin/vault-ai/items pages overlap: every page past the first starts one row early (offset - 1,
    limit + 1), so each page repeats the previous page's last item. Nothing is lost and every filter still
    returns its whole set; only the paging check (no id twice, full pages) can see it. The route is registered
    before faults apply, so the patch swaps its endpoint (`APIRoute.dependant.call`, which FastAPI calls per
    request) for a wrapper around the product's own `vault_ai_api.local_items`."""
    import server

    route = next(r for r in server.app.routes
                 if getattr(r, "path", None) == "/admin/vault-ai/items" and "GET" in getattr(r, "methods", ()))
    real = route.dependant.call

    async def overlapping(**kw):
        if kw.get("offset"):
            kw = {**kw, "offset": kw["offset"] - 1, "limit": kw["limit"] + 1}
        return await real(**kw)

    route.dependant.call = overlapping


def _dupes_ignore_strictness() -> None:
    """vault_dupes.cluster ignores the strictness asked for: every scan clusters at the default (2), so 0, 4
    and 6 answer 2's sets. `find_duplicates` looks `cluster` up on the module per call."""
    import vault_dupes

    real = vault_dupes.cluster

    def default_only(items, _threshold):
        return real(items, vault_dupes.DEFAULT_THRESHOLD)

    vault_dupes.cluster = default_only


def _hide_threshold_or_default() -> None:
    """POST /duplicates/hide reads its strictness as `int(raw or DEFAULT_THRESHOLD)` again, the pre-W23 line:
    0 is falsy, so a hide at 0 re-clusters at 2 and hides a copy that is no duplicate at 0. GET /duplicates is
    untouched. `hide_duplicates` looks `parse_threshold` up in vault_of_folders' globals per call."""
    import vault_of_folders

    def or_default(raw, default, _top):
        return int(raw or default)

    vault_of_folders.parse_threshold = or_default


def register(Fault) -> dict:
    return {
        # slop/run vault-pro-20k --break (the scenario's FAULT)
        "vault-items-page-overlap": Fault(_items_page_overlap, (PAGING,)),
        # slop/run vault-pro-20k --break --fault=vault-dupes-ignores-strictness
        # (the hide at 0 re-clusters through it too, so HIDE_STRICT0 goes red with DUPES)
        "vault-dupes-ignores-strictness": Fault(_dupes_ignore_strictness, (DUPES, HIDE_STRICT0)),
        # slop/run vault-pro-20k --break --fault=vault-hide-threshold-or-default
        "vault-hide-threshold-or-default": Fault(_hide_threshold_or_default, (HIDE_STRICT0,)),
    }
