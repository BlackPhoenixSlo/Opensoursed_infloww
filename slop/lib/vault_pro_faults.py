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
    import vault_dupes

    real = vault_dupes.cluster

    def default_only(items, _threshold):
        return real(items, vault_dupes.DEFAULT_THRESHOLD)

    vault_dupes.cluster = default_only


def _hide_threshold_or_default() -> None:
    import vault_of_folders

    def or_default(raw, default, _top):
        return int(raw or default)

    vault_of_folders.parse_threshold = or_default


def register(Fault) -> dict:
    return {
        "vault-items-page-overlap": Fault(_items_page_overlap, (PAGING,)),
        "vault-dupes-ignores-strictness": Fault(_dupes_ignore_strictness, (DUPES, HIDE_STRICT0)),
        "vault-hide-threshold-or-default": Fault(_hide_threshold_or_default, (HIDE_STRICT0,)),
    }
