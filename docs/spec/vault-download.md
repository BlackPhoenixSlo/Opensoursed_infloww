# Vault download (Vault Pro): design and real-account findings

Vault Pro (`/growth/vault-pro`) downloads selected items, one folder from the rail, or the whole vault to a folder the
user picks, as `<creator>/<folder>/<mediaId>.<ext>`, full quality, with progress, cancel, a queue of further jobs, a
list of items without a file and Retry.

## Entry points and the one gate

- **Header button** (`vault-header-download`, left of Learn, styled like it): "Download full vault" under All media,
  "Download full folder" (mode folder, that folder) when a rail folder is selected; a selected folder not yet in the
  loaded folder list: off (`FOLDER_LOADING`), never a guessed name. Phone portrait: the icon, the
  label `max-sm:sr-only`. The manage panel portals it into the page header (`VaultManagePanel` `headerSlot`), so it
  knows the selected folder and Creator; like every control it starts the app's one `useVaultDownload`
  (`VaultDownloadProvider` in `app/layout.tsx`, see Lifetime). While a folder-sink run is busy it reads "Add full
  vault / folder to queue". No Creator: disabled, titled why.
- **Creator switch** (#428): the run keeps its own account and Creator (the `start` action puts them in the state;
  Retry, re-sign, the links file and the folder sink use them), so picking another Creator neither aborts it nor
  drops unsaved phone files; the card stays up titled "<creator>: <label>". The other Creator's Download controls
  queue behind it (folder sink); on a phone they are off by the same gate while it runs ("A download is running: Ava
  · 12/40") or holds unsaved phone files ("Save the downloaded files first").
- **Selection** (`VaultSelectionBar` Download selected) and the rail row menu's **Download folder** stay: the row menu
  downloads any folder without selecting it first (always listed; off with the gate's reason). Row menu and header
  start through one `scopeArgs` in `VaultManagePanel`. The toolbar's whole-vault icon is gone.
- **Gate**: `downloadGate(state, sink, mode, count, access)` in `vaultDownloadReducer.ts` is the one rule for all
  three: no sink → `DOWNLOAD_OFF`; a picker open → `BUSY_OFF`; a phone run listing / running → `busyOff` (a folder
  run busy is not off: the press queues); a finished phone run's
  unsaved batches → `UNSAVED_OFF`; phone and
  not a selection → `SHARE_MODE_OFF` (`desktopOnly`, the rail item reads "Download folder (desktop only)"); phone
  over 20 → `SHARE_COUNT_OFF`; whole vault for a folder-limited chatter, or one whose folder access is not read yet
  or failed (`dlAccess`) → `RESTRICTED_OFF` ("Your access is by folder: download a folder"). The reason is the
  disabled control's `title`.

## Findings, 2026-11-08, a real account (no proxy), Chromium (Playwright) on http://127.0.0.1:3001

Signed urls came from the running relay container's OF client (`docker exec ... client_pool.get(aid).vault_media(...)`,
GETs only). Each Policy names `AWS:SourceIp` = this machine's public IP /32 (the relay in Docker leaves by the host's IP).

| Probe (from the page, origin http://127.0.0.1:3001) | Result | Label |
|---|---|---|
| `fetch(photo files.full.url)` | 200, `type: "cors"`, ACAO `*`, 154,122 bytes, the body streamed in 6-7 reads | measured |
| `fetch(video files.full.url)` (source mp4) | 200, cors, ACAO `*`, 2,164,805 bytes = Content-Length, 47 reads | measured |
| `fetch(..., {headers: {Range: "bytes=0-1023"}})` photo / `bytes=1000-2999` video | 206, cors, ACAO `*`, exactly 1,024 / 2,000 bytes | measured |
| `<img src=photo full url>` | loads, 874x1150 | measured |
| Tampered Signature | CloudFront 403 with no ACAO, so `fetch` rejects `TypeError: Failed to fetch` (the page can't tell a 403 from a network error) | measured |
| JS-readable headers on a cors response | content-length, content-type, etag, last-modified; no `content-range` (S3 doesn't expose it) | measured |
| `typeof window.showDirectoryPicker` in Chromium | `"function"` | measured |
| A proxied account's url fetched by the browser | 403 (SourceIp is the proxy's), and it would show OF the operator's IP for that Creator | inferred (not run: no proxied account) |
| Deployed relay with no proxy, browser elsewhere | direct 403s (SourceIp = the server's IP); the app re-signs once, then falls back to the relay | inferred |
| Real videos all had `files.full.url` (no DRM-only item in the first page) | DRM-only videos (no `full.url`) end `drm` ("no file (DRM)"), not downloaded, never counted failed | measured for 3 items / inferred for the rest |

## Design (as built)

- **Sink**: `showDirectoryPicker({mode: "readwrite"})` once, then per item `getDirectoryHandle` for creator and folder,
  `getFileHandle(<id>.<ext>, {create})`, `response.body.pipeTo(await fh.createWritable())`. Nothing is buffered in
  memory. Chromium/Edge only. Elsewhere the button says why it's off.
- **Source per item** (the reducer's `sourceFor`): **direct by default** when `GET /admin/vault-ai/download/info`
  says `direct` (the account's egress is Direct, no proxy). Measured above: CDN CORS allows it, and the bytes skip the
  relay. On a direct failure (TypeError / non-2xx) it calls `GET /admin/vault-ai/download/resign` (one OF listing read per 100-item window, else by id,
  `cdn_resign`, no bytes) and retries direct once. Then it uses `GET /admin/vault-ai/download` (relay stream through
  the account's client/proxy, `Content-Disposition: attachment`, a 403 re-signs once, never read whole, one
  `VAULT_DOWNLOAD` slot per stream). The slot: waited for at most `SLOT_WAIT_S` (45 s, under a 60 s proxy read timeout), then 503 `download_busy`
  (`Retry-After: 30`; the item fails "relay busy (503): Retry takes it again"); released exactly once by
  `_SlotStream` even when the client leaves before the body starts, and only after the upstream close (off the
  loop) has finished, so ended streams never let new ones past the cap while their transfers still close; a stalled
  client send (`SEND_IDLE_S` 120 s) or a stream older than `MAX_STREAM_S` (2 h) ends it. The upstream idle bound is
  curl's low-speed limit. **Resign** follows `/download`'s url rule: a passed `u` is used only when it names this
  media (same file) or, for an unrestricted caller with no mirror row, is on an OF CDN host; else the mirror/by-id
  read. All three download routes 422 an empty `account_id`. After 2 items fail direct even after a re-sign, direct turns off for the rest of
  the run (no 2 OF reads per item on a box whose IP doesn't match). Proxied account: relay only, and the browser never
  touches the CDN. Each item records `direct` or `relay`.
- **Listing**: selection = the grid's ticked tiles. Folder / whole vault page the same source the grid reads: the
  mirror (`/admin/vault-ai/items`, 500 per page, no OF call), or live OF (`/api/of/v2/vault/media`, 100 per page,
  `LIVE_PAGE_GAP_MS` = 1.5 s between pages). A `hasMore` page that adds no new id, or more than `LIST_MAX_PAGES`
  (1000) pages, fails the run "listing incomplete" rather than download part of it as the whole. Both are folder-gated server-side for restricted chatters, and the
  download routes 404 a media outside the chatter's folders.
- **Folder in the path**: the folder downloaded. For a selection or the whole vault, the item's first custom OF
  folder (`listStates`), else `Unfiled`. The whole vault keeps one copy per media.
- **State**: `app/components/vault/vaultDownloadReducer.ts` (pure, typed `Action` union, vitest tables). The runner
  `vaultDownload.ts` and `useVaultDownload` only dispatch (no `useState`s: picker open = `picking`, a flag beside the run: a picker closed for
  another run leaves the finished one below, its card and its Retry; a picker or share-sheet failure
  is a `note`, text only, the run and its files go on; `runError` is the one terminal failure channel, from the
  runner's own promise (a listing error included), aborted first and pinned to the attempt it started). Each run /
  Retry failed bumps `attempt`; item events and the run-level `direct` / `listed` / `links` / `batchSaved` / `runError` carry it, so
  a cancelled run's late results change nothing. `start` is dispatched before the runner's first await (a phone
  double tap finds the run going), and a worker fetches an item only if its own `itemStart` moved it queued→active.
  Cancel during the live page gap rejects at once (`abortableSleep`). Close is refused while files are held; unsaved phone files need the panel's Discard;
  a Creator switch keeps both (the app-level provider). The share sink keeps nothing from an aborted run. The title says
  what happened: "Downloaded / Saved X", "Partly downloaded / saved", "Ready to save", "Nothing saved",
  "Download failed".

## Lifetime, queue, outcomes (2026-11-11)

From a real-UI pass on a client deployment: leaving the page killed the run, a stalled write hung it, a second start just
said "A download is running", switching Creator lost the grid's folder / ticks.

- **Lifetime**: `VaultDownloadProvider` sits in `app/layout.tsx` (inside AuthGate), above every route, so navigating
  never unmounts the run; the card (`aria-label="Vault download"`) shows on every page, with "Open Vault Pro" off
  that page. Each run carries its own Creator (account id, name); picking another Creator never touches it. Sign-out
  unmounts the provider: the run is aborted and the queue dropped. An account leaving `GET /admin/accounts`
  (`VaultDownloadAccountGuard` -> `keepAccounts`) drops its queued jobs and aborts its running one. Nothing survives a
  reload (no persistence; no beforeunload guard).
- **Queue** (folder sink only): a start while a run is busy is `enqueue`d (the buttons read "Add selected / folder to queue",
  the header "Add full vault / folder to queue"; the same job queued twice is ignored, a selection never counts as a duplicate). Jobs run one
  at a time in order, each into the same picked folder (the handle is kept); `queryPermission` before each queued job,
  and a lapsed one pauses the queue with Resume (`requestPermission` needs the click). The card names the next jobs
  ("Next: Ava: Beach · …"), "Cancel current" (the queue goes on) and "Clear queue (N)". The share sink has no queue:
  its buttons stay off with "A download is running: Ava · 12/40". Not built: reorder, per-job cancel, parallel jobs,
  adding to the running job.
- **Stall watchdog** (`vaultDownload.ts`): each item has its own AbortController chained to the run's. No response
  headers within `HEAD_MS` (60 s) or no bytes for `STALL_MS` (20 s, under the relay's 30 s curl low-speed limit) aborts
  that item only: it ends `stalled` and the worker takes the next. The sink write is raced against it too (a hung
  write can't hold the run). A file the item created is removed (`removeEntry`); Chromium's `.crswap` goes on abort.
- **Outcomes** per item: `done`, `failed`, `stalled`, `cancelled`, `drm`. Retry takes failed + stalled + cancelled,
  never `drm`. The title reads "Partly downloaded: …" when short; the counts name each kind; "N without a file"
  lists them with the reason. Finished jobs stay as one line each under the card (last 5); the card is compact and
  closable, never over the grid.
- **Browse memory**: `VaultBrowseMemory` (above VaultProPage's per-Creator remount) keeps each Creator's folder, type,
  search, select mode and ticks for the page's life (`browseMapReducer`). The Photo / Video filter keeps the ticks
  (they hold the media, so hidden ticks still download); a folder or search change clears them; a started (or queued)
  selection clears them. Escape closes the folder ⋯ menu.

## Links file (open items on a computer)

- **What**: `vaultLinksFile.buildLinksFile` (pure): `links-….txt` (`<id>.<ext>  <link>` per item, `#` header) and
  `links-….html` (self-contained, a table, each link `target=_blank`, all text escaped). Same rows.
- **When / where**: right after listing, before the first media. Desktop: into `<creator>/` (a folder download:
  `<creator>/<folder>/`) of the picked folder; a write error never stops the download. Phone: its own "Save links"
  share (txt `text/plain` + html `text/html`; txt only if `canShare` refuses html), not in a media batch (a non-media
  file in a mixed share would cost iOS its Save Image/Video), outside the 20 cap and the batch budget.
- **Link per item**: direct account and the url has > 10 min left: its signed CDN url (opens with no login, but
  only from the IP it is signed for: the relay's egress; on a server that's the server's IP, so the html also lists
  the app link). Proxied account, or an expired / unreadable url: the app link
  `<origin>/admin/vault-ai/download?account_id=&media_id=` (relay stream, re-signs itself, works on any computer
  logged in to the app; `&t=` when the page runs on a share token; built by `downloadPath`, the same as the relay
  fetch). No full url (DRM-only): "no link (DRM)". A refused write shows "Links file not saved." (`links: "failed"`)
  and the "Saved in" line drops the links-file name.
- **Expiry, measured 2026-11-08** (793 real OF vault rows in a local demo DB): DateLessThan = listing hour + 24 h
  (listed 04:30 / 16:32 UTC -> 04:00 / 16:00 next day), 23.5 h after listing, not 2 days. So the name is the
  earliest CDN expiry in the file, `links-valid-until-20261109-1600UTC.*`, or `links-valid-while-logged-in.*` when
  every link is an app link. The header repeats it ("Valid until 2026-11-09 16:00 UTC").

## Phone sink (share sheet)

- **When**: no `showDirectoryPicker`, but `navigator.canShare({files: [File x.jpg image/jpeg]})` is true
  (`downloadSink()` = `"share"`; iOS browsers, Android Chrome, also desktop Safari). Desktop Chrome/Edge keep the
  folder sink.
- **Scope**: a selection of at most `SHARE_MAX_ITEMS` = 20. More: Download is off with "Phone: up to 20 at a time"
  shown in the selection bar. Folder and whole vault stay off (disabled, the reason as title; the rail item reads
  "Download folder (desktop only)"). `downloadGate()` is the one rule. One file at a time (`SHARE_CONCURRENCY`); a
  file over `SHARE_FILE_MAX_BYTES` (200 MB, by Content-Length or counted bytes) fails "Too big for a phone".
- **Fetch**: the same queue and source chain (`sourceFor`: direct, re-sign, relay; DRM 422 = `drm`), only the sink
  differs: the counted body goes into a `File` `<id>.<ext>` with the MIME by extension (`mimeFor`: image/jpeg,
  image/png, image/gif, video/mp4, video/quicktime...; iOS offers Save Image/Video only for real types).
- **Batches**: each fetched file joins the open batch (completion order); a file that would push it past
  `SHARE_BATCH_BYTES` (200 MB, tune there) seals it and opens the next; a batch at the budget seals, so a bigger file
  is a batch alone. The run's end (or Cancel) seals the open batch. A sealed batch shows "Save 1–8"; the tap calls
  `navigator.share({files})` straight from the click (iOS needs the tap's transient activation). Resolved: the batch's
  files are dropped and the next button shows. `AbortError` (sheet dismissed): nothing changes, the button stays.
- **Memory**: workers hold before the next file while unsaved batches hold `SHARE_HELD_BYTES` (2 batches), so at most
  ~2 batches + the one file in flight (<= 200 MB) sit in memory.
- **Not done**: zip, one-by-one anchor downloads, folder / whole vault on phones. Real iOS memory limits and the
  Save to Photos step are untested (slop stubs `navigator.share`).

## Proof

- Unit: `service/tests/test_vault_download.py` (streaming, lazy body, 403 re-sign once, DRM 422, chatter folder gate,
  auth, resign incl. a foreign `u`, empty `account_id` 422, video not gzipped, slot freed on a disconnect before the
  body, full lane 503, slot held until a slow upstream close finishes, a stalled consumer cut by `SEND_IDLE_S`, an
  upstream cut mid-body ends short with no Traceback), `app/components/vault/vaultDownloadReducer.test.ts` (attempts,
  outcomes, queue, retry jobs), `vaultDownload.test.ts` (source chain, strikes, proxied relay-only, short body,
  cancel, retry, paging, stall watchdog, no partial file), `VaultDownloadPanel.test.tsx` (queue into one folder,
  permission pause, unmount aborts, accounts guard), `vaultBrowseReducer.test.ts`.
- Slop: `slop/scenarios/2026-11-08-vault-download.py` (README.vault.md): all 3 modes through the UI (whole vault and
  the pick hint via the header button) on a fake CDN; the header-folder phase (rail folder selected, header reads
  "Download full folder", listing requests carry that folder's id, exactly its media saved: HEADER_SCOPE, broken by
  fault `vault-download-header-ignores-folder`); the phone header (390x844 icon, disabled, desktop-only title:
  PHONE_HEADER); Open folder after the run and mid-run (OPEN_FOLDER, fault `vault-download-open-folder-at-root`);
  the switch phase (A's whole vault running, Creator B picked: A's run finishes whole, B's header button "Add full
  vault to queue": SWITCH, broken by fault `vault-download-switch-aborts-run`),
  plus a proxied Creator (relay only), `--users` concurrent relay downloads, and the phone sink (390x844 Chromium
  mobile emulation, picker deleted, `navigator.share` stubbed: the 20 cap, >= 2 batches, dismiss keeps the button),
  a Creator switch mid-run, and the queue (one CDN response stalled: 1 `stalled`, the next Creator's job starts;
  away to Dashboard and back keeps the run; each job under its own Creator).
- Live: `scripts/vault-download-live.py` (the real account, real CDN, real UI; GETs only toward OnlyFans). The owner
  must see the account in `GET /admin/accounts`. Whole vault (`--modes vault`) pre-counts sizes with paced Range-0
  GETs and aborts if saving 2x the vault (the OPFS stub's copy + the exported copy) would leave < 20 GB free.
  The stub's Chromium profile is on disk (an incognito context keeps OPFS in memory); files leave OPFS through a
  loopback PUT sink in the script (browser-download export stalled after 20 files on the real vault).
