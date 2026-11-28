# Support chat photos (owner 2026-11-28)

Owner: "add option to all to append photos" — CRM users (Support tab in help widget) and the owner (hub at inflowwww.com/support, also proxied from other hosts) can attach photos to a support message.

## Decisions
- P1 Up to 4 photos per message, text optional when ≥1 photo. Picker (`accept="image/*" multiple`, phone camera roll) + paste image into the text box. No other file types.
- P2 Hub is the only place that decodes: Pillow open with `Image.MAX_IMAGE_PIXELS = 40_000_000` and bomb warning → error, `ImageOps.exif_transpose`, drop alpha-less EXIF/metadata, downscale longest side ≤ 2048, re-encode JPEG q85 (PNG kept as PNG only if it has transparency → else JPEG). Accept only decoded formats JPEG/PNG/WEBP/GIF/HEIF-if-Pillow-supports (first frame). SVG/anything else → 400 "Only photos". Raw cap 10 MB each, enforced before parse at both relay and hub (stream-count, not trust Content-Length).
- P3 Storage: hub SQLite `photos(id INTEGER PK, message_id, mime, w, h, data BLOB)`; message rows return `photos: [{id,w,h}]`. No retention/cleanup (YAGNI). Existing send cap (20 msgs / 10 min / user) bounds volume.
- P4 Upload paths: CRM → Next → relay `POST /admin/support/messages` multipart (`text`, `photos[]`) via `relay.uploadForm`; relay checks size/count, forwards multipart to hub `POST /support/api/instance/messages` with bearer token + identity from session (never from client). Owner → hub `POST /support/api/threads/{id}/reply` multipart with owner cookie. JSON body stays accepted for text-only (back-compat with AE until both hosts redeploy).
- P5 Serving: hub `GET /support/api/photos/{id}` (owner cookie) and `GET /support/api/instance/photos/{id}?instance&user_key` (token + photo must belong to that thread, else 404). Relay `GET /admin/support/photos/{id}` → session identity → hub → bytes. Response headers: exact stored mime, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none'`, `Cache-Control: private, max-age=86400`, `Content-Disposition: inline`.
- P6 UI: CRM SupportPanel — photo button left of input, thumbnails with ✕ before send, sent photos render as tappable thumbnails (open full in new tab). State in `supportReducer.ts` (repo reducer rule). Hub page — same, textContent-only rendering, `<img src>` same-origin (CSP img-src 'self' already).
- P7 Summarise: photo shows as "[photo]" in transcript; no vision call.
- P8 Cell mode: new relay routes go to control Cell (cellRoute.ts CONTROL_WRITES, fleet.py, cell_scope.json, route golden, relayCallSites).
- P9 Theme (owner 2026-11-28 "make this widget black too if black screen is set"): CRM theme = dark unless `<html data-theme="light">` (localStorage `chatterly:theme`). Support panel (and its help-widget surface) must use theme tokens so dark CRM → dark panel, light → light. Hub stays dark.
- P10 Live updates (owner "make it update asap, no need refresh"): poll while visible — hub open thread 4 s, hub list 10 s; CRM Support panel open thread 4 s; launcher unread poll stays 60 s. Merge by message id, keep scroll position unless at bottom, don't clobber the draft.

## Risks
- Internet-facing upload on hub → decompression bomb, polyglot/HTML-as-image (re-encode kills), memory (10 MB × 4 × concurrent). Diff review: codex + reviewer.
- Next proxy body limit already 256 MB (app/next.config proxyClientMaxBodySize).
- Leak gate: no real names/emails in tests.

## Decision log
- F1 2026-11-28 plan check → continue with changes, all adopted (supersede P1–P5 where they conflict):
  - Client downscale: CRM + hub page draw to canvas → JPEG ≤2048 px longest side, q≈0.85 (picker and paste share one function). Hub cap 3 MB/photo, max 4, JPEG only.
  - Hub still decodes + re-encodes: `Image.open(fp, formats=["JPEG"])`, check `im.size` (≤ 2048² ×1.1 guard, reject bigger) before `load()`, exif_transpose, convert RGB (flatten white), save JPEG q85 no EXIF. Never touch PIL globals (`MAX_IMAGE_PIXELS`/warning filters). Decode in threadpool behind a 2-slot semaphore, outside `BEGIN IMMEDIATE`.
  - Auth before parse: photo handlers are `async def h(request)`: auth → Content-Length reject → counting receive wrapper → `request.form(max_files=4)` (pattern: service/server.py ~5750, service/mcp_api.py ~377).
  - New sibling multipart routes; live JSON routes untouched. Deploy hub (public) first, then AE.
  - Drop HEIF, GIF, PNG-alpha, mime column (always image/jpeg).
  - Relay photo forward gets its own timeout (≈30 s).
  - Owner photo GET: validate session before reserving a throttle slot (no 429 on parallel thumbnails, a proxying host shares one IP).
  - Hub page previews via data: URLs; CSP unchanged (no blob:).
  - Row queries never select `data`; index `photos(message_id)`; refuse new photos when hub DB file > SUPPORT_HUB_MAX_DB_GB (default 2).
