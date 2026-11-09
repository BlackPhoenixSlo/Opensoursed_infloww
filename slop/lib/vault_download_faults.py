"""Vault Pro download's check names and break-it-once fault (scenarios/2026-11-08-vault-download.py): lib/faults.py
merges `register(Fault)` into FAULTS. The check names live here and the scenario imports them, so a target can
never name a check that does not exist.
"""
from __future__ import annotations

SELECT = ("vault download: Download selected (3 photos + 1 video) saves each as <creator>/<folder>/<id>.<ext> with "
          "the CDN's exact bytes, every one direct (browser -> CDN), 0 relay downloads, the panel settles N of N")
PICK_HINT = ("vault download: while the folder picker is open the card says Chrome refuses Desktop / Documents / "
             "Downloads themselves (New Folder inside them); closing the picker removes it, no download starts")
FOLDER = ("vault download: the rail's Download folder saves exactly that folder's media under <creator>/<folder>/, "
          "exact bytes, all direct, 0 relay downloads")
VAULT = ("vault download: Download whole vault saves every mirror media once (count = mirror, nothing dropped), "
         "exact bytes; each stale-IP url re-signed by id exactly once and still delivered direct")
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


def register(Fault) -> dict:
    return {
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
    }
