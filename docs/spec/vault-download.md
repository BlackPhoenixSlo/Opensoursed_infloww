# Vault download (Vault Pro): design and real-account findings

Vault Pro (`/growth/vault-pro`) downloads selected items, one folder from the rail, or the whole vault to a folder the
user picks, as `<creator>/<folder>/<mediaId>.<ext>`, full quality, with progress, cancel, a failed list and Retry
failed.

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
| Real videos all had `files.full.url` (no DRM-only item in the first page) | DRM-only videos (no `full.url`) are reported as failed "DRM", not downloaded | measured for 3 items / inferred for the rest |

## Design (as built)

- **Sink**: `showDirectoryPicker({mode: "readwrite"})` once, then per item `getDirectoryHandle` for creator and folder,
  `getFileHandle(<id>.<ext>, {create})`, `response.body.pipeTo(await fh.createWritable())`. Nothing is buffered in
  memory. Chromium/Edge only. Elsewhere the button says why it's off.
- **Source per item** (the reducer's `sourceFor`): **direct by default** when `GET /admin/vault-ai/download/info`
  says `direct` (the account's egress is Direct, no proxy). Measured above: CDN CORS allows it, and the bytes skip the
  relay. On a direct failure (TypeError / non-2xx) it calls `GET /admin/vault-ai/download/resign` (one OF listing read per 100-item window, else by id,
  `cdn_resign`, no bytes) and retries direct once. Then it uses `GET /admin/vault-ai/download` (relay stream through
  the account's client/proxy, `Content-Disposition: attachment`, a 403 re-signs once, never read whole, one
  `VAULT_DOWNLOAD` slot per stream). After 2 items fail direct even after a re-sign, direct turns off for the rest of
  the run (no 2 OF reads per item on a box whose IP doesn't match). Proxied account: relay only, and the browser never
  touches the CDN. Each item records `direct` or `relay`.
- **Listing**: selection = the grid's ticked tiles. Folder / whole vault page the same source the grid reads: the
  mirror (`/admin/vault-ai/items`, 500 per page, no OF call), or live OF (`/api/of/v2/vault/media`, 100 per page,
  `LIVE_PAGE_GAP_MS` = 1.5 s between pages). Both are folder-gated server-side for restricted chatters, and the
  download routes 404 a media outside the chatter's folders.
- **Folder in the path**: the folder downloaded. For a selection or the whole vault, the item's first custom OF
  folder (`listStates`), else `Unfiled`. The whole vault keeps one copy per media.
- **State**: `app/components/vault/vaultDownloadReducer.ts` (pure, typed `Action` union, vitest tables). The runner
  `vaultDownload.ts` only dispatches.

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
  logged in to the app; `&t=` when the page runs on a share token). No full url (DRM-only): "no link (DRM)".
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
  "Download folder (desktop only)"). `downloadOff()` is the one rule.
- **Fetch**: the same queue and source chain (`sourceFor`: direct, re-sign, relay; DRM 422 = failed), only the sink
  differs: the counted body goes into a `File` `<id>.<ext>` with the MIME by extension (`mimeFor`: image/jpeg,
  image/png, image/gif, video/mp4, video/quicktime...; iOS offers Save Image/Video only for real types).
- **Batches**: each fetched file joins the open batch (completion order); a file that would push it past
  `SHARE_BATCH_BYTES` (200 MB, tune there) seals it and opens the next; a batch at the budget seals, so a bigger file
  is a batch alone. The run's end (or Cancel) seals the open batch. A sealed batch shows "Save 1–8"; the tap calls
  `navigator.share({files})` straight from the click (iOS needs the tap's transient activation). Resolved: the batch's
  files are dropped and the next button shows. `AbortError` (sheet dismissed): nothing changes, the button stays.
- **Memory**: workers hold before the next file while unsaved batches hold `SHARE_HELD_BYTES` (2 batches), so at most
  ~2 batches + the files in flight sit in memory.
- **Not done**: zip, one-by-one anchor downloads, folder / whole vault on phones. Real iOS memory limits and the
  Save to Photos step are untested (slop stubs `navigator.share`).

## Proof

- Unit: `service/tests/test_vault_download.py` (streaming, lazy body, 403 re-sign once, DRM 422, chatter folder gate,
  auth, resign), `app/components/vault/vaultDownloadReducer.test.ts`, `vaultDownload.test.ts` (source chain, strikes,
  proxied relay-only, short body, cancel, retry, paging).
- Slop: `slop/scenarios/2026-11-08-vault-download.py` (README.vault.md): all 3 modes through the UI on a fake CDN,
  plus a proxied Creator (relay only), `--users` concurrent relay downloads, and the phone sink (390x844 Chromium
  mobile emulation, picker deleted, `navigator.share` stubbed: the 20 cap, >= 2 batches, dismiss keeps the button).
- Live: `scripts/vault-download-live.py` (the real account, real CDN, real UI; GETs only toward OnlyFans). The owner
  must see the account in `GET /admin/accounts`. Whole vault (`--modes vault`) pre-counts sizes with paced Range-0
  GETs and aborts if saving 2x the vault (the OPFS stub's copy + the exported copy) would leave < 20 GB free.
  The stub's Chromium profile is on disk (an incognito context keeps OPFS in memory); files leave OPFS through a
  loopback PUT sink in the script (browser-download export stalled after 20 files on the real vault).
