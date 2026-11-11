"""Vault Pro download's check names and break-it-once fault (scenarios/2026-11-08-vault-download.py): lib/faults.py
merges `register(Fault)` into FAULTS. The check names live here and the scenario imports them, so a target can
never name a check that does not exist.
"""
from __future__ import annotations

SELECT = ("vault download: Download selected (3 photos + 1 video) saves each as <creator>/<folder>/<id>.<ext> with "
          "the CDN's exact bytes, every one direct (browser -> CDN), 0 relay downloads, the panel settles N of N")
SELECT_IN_FOLDER = ("vault download: Download selected inside a rail folder saves every ticked media under "
                    "<creator>/<that folder>/ only (not each media's first OF folder, no copies elsewhere), exact bytes")
PICK_HINT = ("vault download: while the folder picker is open the card says Chrome refuses Desktop / Documents / "
             "Downloads themselves (New Folder inside them); closing the picker removes it, no download starts")
FOLDER = ("vault download: the rail's Download folder saves exactly that folder's media under <creator>/<folder>/, "
          "exact bytes, all direct, 0 relay downloads")
VAULT = ("vault download: Download whole vault fetches every mirror media once (count = mirror, nothing dropped) and "
         "writes it into each of its custom folders (a copy per folder, else Unfiled), exact bytes; the stale-IP urls re-signed by their listing window (one OF read per window, 0 by-id) and still delivered direct")
SWITCH = ("vault download: picking another Creator while a whole-vault download runs leaves it running: every "
          "media of the first Creator lands once with exact bytes, the card (titled with that Creator) ends done, 0 "
          "failed, never cancelled; the other Creator's grid shows with its Download off (\"A download is running\")")
PROXIED = ("vault download: a proxied Creator's Download selected never touches the CDN from the browser (0 browser "
           "CDN fetches): every file streamed by the relay through the Creator's proxy, exact bytes")
PHONE_CAP = ("vault download, phone (no folder picker, files shareable): Download selected on at 20 ticked, off at 21 "
             "with the visible reason; Download folder / whole vault off with theirs")
PHONE_SHARE = ("vault download, phone: a selection of photos + 2 videos > budget/2 fetched through the same source "
               "chain (proxied: 0 browser CDN fetches) into >= 2 share batches, each saved by a tap inside its "
               "activation; every file shared exactly once as <id>.<ext> with its MIME and exact size; a dismissed "
               "sheet keeps the button; no 5xx")
LINKS = ("vault download links file: every desktop run (select / folder / whole vault / proxied) writes "
         "links-valid-*.txt + .html before its first media file, one line / row per item (every id once); a direct "
         "Creator's lines are its CDN urls (unexpired), a proxied Creator's the app relay url (no CDN host); a link "
         "from the html opens (CDN: 200 in the browser; app: 200 attachment, exact bytes, logged in)")
PHONE_LINKS = ("vault download links file, phone: Save links hands links-*.txt (text/plain) + .html (text/html) to "
               "their own share sheet before any media batch, inside the tap; one line per selected item, every "
               "one the app relay url (proxied Creator, no CDN host)")
RELAY_LOAD = ("vault download: --users concurrent relay downloads (GET /admin/vault-ai/download): every one 200, "
              "attachment named <id>.<ext>, the exact bytes, none dropped")

RELAY_STALE = ("vault download: --users concurrent relay downloads of a proxied Creator's EXPIRED urls spread over "
               "its vault, under OF's per-account rate limit: every one 200 with the exact bytes, one OF listing read "
               "per 100-item window touched, 0 by-id reads, 0 OF 429s")


def _resign_by_id() -> None:
    """cdn_resign's listing-window path off: every stale file is one by-id read again (AE 2026-11-10: 118 reads)."""
    import cdn_resign

    async def miss(*_a, **_k) -> str:
        return "miss"
    cdn_resign._via_page = miss


def register(Fault) -> dict:
    return {
        # slop/run 2026-11-08-vault-download --break --fault=vault-download-resign-by-id (service side)
        "vault-download-resign-by-id": Fault(_resign_by_id, (RELAY_STALE, VAULT)),
        # slop/run 2026-11-08-vault-download --break --fault=vault-download-selection-ignores-folder
        # app/components/vault/VaultManagePanel.tsx Download selected: the rail folder not passed, so each ticked media
        # lands in its own first OF folder (the 2026-11-11 owner report: one folder's picks spread over others).
        "vault-download-selection-ignores-folder": Fault(None, (SELECT_IN_FOLDER,), browser=(
            (r"folder:(?:\s|\\n)*here(?:\s|\\n)*\?", "folder: null ?"),
        )),
        # slop/run 2026-11-08-vault-download --break (the scenario's FAULT)
        # app/components/vault/vaultDownloadReducer.ts `sourceFor`: the proxy rule dropped, so a proxied Creator's
        # browser fetches OF's CDN itself (403 for the proxy-signed url, a re-sign, a strike, then the relay: the
        # files still land, the operator's IP was shown to OF).
        "vault-download-direct-ignores-proxy": Fault(None, (PROXIED, PHONE_SHARE), browser=(
            (r"return s\.directAllowed && s\.directStrikes < MAX_DIRECT_STRIKES \?",
             "return s.directStrikes < MAX_DIRECT_STRIKES ?"),
        )),
        # slop/run 2026-11-08-vault-download --break --fault=vault-download-share-batch-drops-item
        # vaultDownloadReducer.ts `addToBatches`: a file that opens a new batch is counted but not listed, so the
        # share sheet never gets it (fetched, "done", never saved).
        "vault-download-share-batch-drops-item": Fault(None, (PHONE_SHARE,), browser=(
            # `next dev` serves the module inside eval("..."): its newlines are the two characters \n there.
            (r"ids:\s*\[(?:\s|\\n)*id(?:\s|\\n)*\],(?:\s|\\n)*bytes,(?:\s|\\n)*sealed:\s*false",
             "ids: [], bytes, sealed: false"),
        )),
        # slop/run 2026-11-08-vault-download --break --fault=vault-download-links-cdn-for-proxied
        # app/components/vault/vaultLinksFile.ts `linkRows`: the direct rule dropped, so a proxied Creator's links
        # file lists its CDN urls (bound to the proxy's IP: 403 on the owner's computer) instead of the app link.
        "vault-download-links-cdn-for-proxied": Fault(None, (LINKS, PHONE_LINKS), browser=(
            (r"o\.direct && it\.url && exp !== null", "it.url && exp !== null"),
        )),
        # slop/run 2026-11-08-vault-download --break --fault=vault-download-switch-aborts-run
        # The pre-fix layout: app/components/growth/VaultProPage.tsx's per-Creator subtree (the `key={accountId}`
        # div) owns the download. The panel's element type becomes a wrapper (cached on globalThis, so its identity
        # holds across renders) that mounts its own VaultDownloadProvider around VaultManagePanel, so the panel's
        # nearest provider sits under the key: picking another Creator unmounts it, its cleanup aborts the run (part
        # of the files) and its card goes with it (the bug fixed 2026-11-11). The page-level provider stays (idle).
        # One match: from the panel's jsxDEV call to the page's own VaultDownloadProvider below it (the provider's
        # import name), webpack's import names spelled out (a literal start: a bare \w+ there scans a 6 MB chunk for
        # minutes). `next dev` serves the module inside eval("..."): quotes are \" there.
        "vault-download-switch-aborts-run": Fault(None, (SWITCH,), browser=(
            (r"(react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_\d+__)\.jsxDEV\)\("
             r"(_components_vault_VaultManagePanel__WEBPACK_IMPORTED_MODULE_\d+__)\[\\?\"default\\?\"\]([\s\S]*?)"
             r"(_components_vault_VaultDownloadPanel__WEBPACK_IMPORTED_MODULE_\d+__)\.VaultDownloadProvider\b",
             r"\g<1>.jsxDEV)((globalThis.__slopKeyedDl ??= (p) => (0, \g<1>.jsxDEV)(\g<4>.VaultDownloadProvider, "
             r"{ children: (0, \g<1>.jsxDEV)(\g<2>.default, p) }))\g<3>\g<4>.VaultDownloadProvider"),
        )),
    }
