from __future__ import annotations

SELECT = ("vault download: Download selected (3 photos + 1 video) under All media saves each as "
          "<creator>/<folder>/<id>.<ext>, a copy in each of its custom folders (fetched once), with the CDN's exact "
          "bytes, every one direct (browser -> CDN), 0 relay downloads, the panel settles N of N")
SELECT_IN_FOLDER = ("vault download: Download selected inside a rail folder saves every ticked media under "
                    "<creator>/<that folder>/ only (not each media's first OF folder, no copies elsewhere), exact bytes")
PICK_HINT = ("vault download: while the folder picker is open the card says Chrome refuses Desktop / Documents / "
             "Downloads themselves (New Folder inside them); closing the picker removes it, no download starts")
FOLDER = ("vault download: the rail's Download folder saves exactly that folder's media under <creator>/<folder>/, "
          "exact bytes, all direct, 0 relay downloads")
VAULT = ("vault download: the Extras drawer's Download full vault fetches every mirror media once (count = mirror, nothing "
         "dropped) and writes it into each of its custom folders (a copy per folder, else Unfiled), exact bytes; the "
         "stale-IP urls re-signed by their listing window (one OF read per window, 0 by-id) and still delivered direct")
SWITCH = ("vault download: picking another Creator while a whole-vault download runs leaves it running: every "
          "media of the first Creator lands once with exact bytes, the card (titled with that Creator) ends done, 0 "
          "failed, never cancelled; the other Creator's grid shows with its Extras drawer item \"Add full vault to queue\" on")
QUEUE_STALL = ("vault download queue: one relay CDN response throttled to zero bytes mid-body ends that item `stalled` "
               "(no file, no .crswap) while the rest of the job lands; the job finishes with exactly 1 stalled, 0 "
               "failed, and the job queued after it (another Creator's folder) starts on its own, the stalled item's retry job "
               "queued behind it")
QUEUE_NAV = ("vault download queue: leaving Vault Pro for another page mid-run keeps the run (the global card shows "
             "it, same job, with Open Vault Pro), and coming back finds the same job, which then finishes; the retry job "
             "runs last")
QUEUE_CREATORS = ("vault download queue: a selection of Creator B then a folder of Creator A queued behind it, into one "
                  "picked folder: each job's files under its own Creator's folder, exact bytes, nothing dropped, no "
                  "stray file")
PROXIED = ("vault download: a proxied Creator's Download selected never touches the CDN from the browser (0 browser "
           "CDN fetches): every file streamed by the relay through the Creator's proxy, exact bytes")
PHONE_CAP = ("vault download, phone (no folder picker, files shareable): Download selected on at 20 ticked, off at 21 "
             "with the visible reason; Download folder / the Extras drawer's Download full vault off with theirs")
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
OPEN_FOLDER = ("vault download: the card's Open folder opens the computer's file window in that run's own folder "
               "(selection: <creator>/, a folder download: <creator>/<folder>/), holding its links files (folder: "
               "and every media file), after the run and mid-run (another Creator on screen); the done card names "
               "that path (\"Saved in ...\")")
HEADER_SCOPE = ("vault download, the Extras drawer's full download (`vault-extras-download`): under All media it reads "
                "\"Download full vault\" and its run's listing requests carry no folder id; with a rail folder selected "
                "it reads \"Download full folder\", its listing requests carry exactly that folder's id and it saves "
                "exactly that folder's media (exact bytes, all direct, 0 relay downloads); trigger + settled shots each")
PHONE_HEADER = ("vault download, phone 390x844 portrait: the Extras drawer's Download full vault is visible (icon and "
                "label), disabled, titled with the desktop-only reason")
RELAY_LOAD = ("vault download: --users concurrent relay downloads (GET /admin/vault-ai/download): every one 200, "
              "attachment named <id>.<ext>, the exact bytes, none dropped")

RELAY_STALE = ("vault download: --users concurrent relay downloads of a proxied Creator's EXPIRED urls spread over "
               "its vault, under OF's per-account rate limit: every one 200 with the exact bytes, one OF listing read "
               "per 100-item window touched, 0 by-id reads, 0 OF 429s")


def _resign_by_id() -> None:
    import cdn_resign

    async def miss(*_a, **_k) -> str:
        return "miss"
    cdn_resign._via_page = miss


DL_FILES = 2

# next dev serves modules inside eval("..."): newlines are the two characters \n, quotes \"
_W = r"(?:\s|\\n)*"
_K = r'\\?"useVaultDownload\.useEffect\\?"'
_UNMOUNT = (r"(?:\{" + _W + _K + ":" + _W + r"\(\)" + _W + "=>" + _W + r"\(\{" + _W + _K + ":" + _W + r"\(\)" + _W
            + "=>" + _W + r"stopRunAndQueue\(\)" + _W + r"\}\)\[" + _K + r"\]" + _W + r"\}\[" + _K + r"\]," + _W
            + r"\[\]"
            + "|" + r"\(\)" + _W + "=>" + _W + r"\(\)" + _W + "=>" + _W + r"stopRunAndQueue\(\)," + _W + r"\[\])")


def register(Fault) -> dict:
    return {
        "vault-download-resign-by-id": Fault(_resign_by_id, (RELAY_STALE, VAULT)),
        "vault-download-selection-ignores-folder": Fault(None, (SELECT_IN_FOLDER,), browser=(
            (r"folder:(?:\s|\\n)*selectedFolder(?:\s|\\n)*\?", "folder: null ?"),
        )),
        "vault-download-direct-ignores-proxy": Fault(None, (PROXIED, PHONE_SHARE), browser=(
            (r"return s\.directAllowed && s\.directStrikes < MAX_DIRECT_STRIKES \?",
             "return s.directStrikes < MAX_DIRECT_STRIKES ?"),
        ), browser_files=DL_FILES),
        "vault-download-share-batch-drops-item": Fault(None, (PHONE_SHARE,), browser=(
            (r"ids:\s*\[(?:\s|\\n)*id(?:\s|\\n)*\],(?:\s|\\n)*bytes,(?:\s|\\n)*sealed:\s*false",
             "ids: [], bytes, sealed: false"),
        ), browser_files=DL_FILES),
        "vault-download-links-cdn-for-proxied": Fault(None, (LINKS, PHONE_LINKS), browser=(
            (r"o\.direct && it\.url && exp !== null", "it.url && exp !== null"),
        ), browser_files=DL_FILES),
        "vault-download-switch-aborts-run": Fault(None, (SWITCH, QUEUE_STALL, QUEUE_NAV, QUEUE_CREATORS), browser=(
            (_UNMOUNT, "() => () => stopRunAndQueue(), [globalThis.localStorage.getItem('vault.accountId')]"),
        ), browser_files=DL_FILES),
        "vault-download-no-stall-watchdog": Fault(None, (QUEUE_STALL,), browser=(
            (r"STALL_MS = 20000", "STALL_MS = 600000"),
        ), browser_files=DL_FILES),
        "vault-download-nav-kills-run": Fault(None, (QUEUE_NAV, QUEUE_CREATORS), browser=(
            (_UNMOUNT, "() => { const p = globalThis.location.pathname; const t = setInterval(() => { "
                       "if (globalThis.location.pathname !== p) stopRunAndQueue(); }, 200); "
                       "return () => { clearInterval(t); stopRunAndQueue(); }; }, []"),
        ), browser_files=DL_FILES),
        "vault-download-open-folder-at-root": Fault(None, (OPEN_FOLDER,), browser=(
            (r"for \(const n of at\.dirs\)", "for (const n of at.dirs.slice(0, 1))"),
        ), browser_files=DL_FILES),
        "vault-download-header-ignores-folder": Fault(None, (HEADER_SCOPE,), browser=(
            (r"dl\.start\(fullScope\)", "dl.start(scopeArgs(null))"),
        )),
    }
