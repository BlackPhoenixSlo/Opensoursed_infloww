"""Vault Pro download's check names and break-it-once fault (scenarios/2026-11-08-vault-download.py): lib/faults.py
merges `register(Fault)` into FAULTS. The check names live here and the scenario imports them, so a target can
never name a check that does not exist.
"""
from __future__ import annotations

SELECT = ("vault download: Download selected (3 photos + 1 video) saves each as <creator>/<folder>/<id>.<ext> with "
          "the CDN's exact bytes, every one direct (browser -> CDN), 0 relay downloads, the panel settles N of N")
FOLDER = ("vault download: the rail's Download folder saves exactly that folder's media under <creator>/<folder>/, "
          "exact bytes, all direct, 0 relay downloads")
VAULT = ("vault download: Download whole vault saves every mirror media once (count = mirror, nothing dropped), "
         "exact bytes; each stale-IP url re-signed by id exactly once and still delivered direct")
PROXIED = ("vault download: a proxied Creator's Download selected never touches the CDN from the browser (0 browser "
           "CDN fetches): every file streamed by the relay through the Creator's proxy, exact bytes")
RELAY_LOAD = ("vault download: --users concurrent relay downloads (GET /admin/vault-ai/download): every one 200, "
              "attachment named <id>.<ext>, the exact bytes, none dropped")


def register(Fault) -> dict:
    return {
        # slop/run 2026-11-08-vault-download --break (the scenario's FAULT)
        # app/components/vault/vaultDownloadReducer.ts `sourceFor`: the proxy rule dropped, so a proxied Creator's
        # browser fetches OF's CDN itself (403 for the proxy-signed url, a re-sign, a strike, then the relay: the
        # files still land, the operator's IP was shown to OF).
        "vault-download-direct-ignores-proxy": Fault(None, (PROXIED,), browser=(
            (r"return s\.directAllowed && s\.directStrikes < MAX_DIRECT_STRIKES \?",
             "return s.directStrikes < MAX_DIRECT_STRIKES ?"),
        )),
    }
