# Goal plan: OF Manager connectors

Make the OF Manager mirror (`/of-manager/[section]`, static scrubbed copies of the OnlyFans creator
UI) behave like Infloww's OF Manager: every control that does nothing today either writes through
our relay, shows the model's real data, or says "Read-only in Inflowwww for now". Only the mirror
pages change. Nothing else in the app changes except what a Phase below names.

## Ground truth (observation rung; read before any spec)

1. Mirror wiring today: `app/lib/ofMirrorWrites.ts` (header :3-16 says how writes were confirmed;
   `WRITABLE` :28, `SUBMITS` :40, `READ_ONLY` :56, `SELECT_MODEL` :57, `note()` :93, `parseDate`
   :118, `parseTime` :133, `localIso` :149, `bindWrites` :182, handlers `null` in all-models scope
   :311); `app/lib/ofMirrorData.ts` (`DATA_PAGES` :32, `MirrorData` :54, OF HTML to text :129,
   `tileThumb` :388, `applyVaultMedia` :393, `applyData` :489, `useOfData` :518);
   `app/lib/ofMirrorRow.ts` (`ROW_TARGETS` :32, `basePage` :61); `app/lib/ofMirrorIdentity.ts`
   (`OfMe` :19, `useOfIdentity` :121); `app/lib/ofMirrorSettings.ts` (`SOURCE_PATHS` :30,
   `SETTINGS_MAP` :63); route `app/app/of-manager/[section]/[[...path]]/page.tsx` :13-32; hooks
   mounted in `app/components/of-manager/OfMirrorFrame.tsx` :17-22.
2. Generator and guard: `scripts/of-mirror.mjs` (`SECTIONS` :172, `--check` :1411-1451). Checks:
   `scripts/of-mirror-check/*.py` and its `README.md` (Playwright route mocks, `PORT` env default
   3091, screenshots to `/tmp/of-mirror-shots`; `writes.py` records non-GET `/api/**` bodies).
3. Relay: `service/server.py` routes under `/api/of/v2/`; `service/of_client.py` methods. An
   existing caller of the post route: `app/components/compose/PostComposer.tsx:127-135`
   (`media_files`, `price`, `posted_at`, `tagged_users`); `relay.uploadFile` `app/lib/relay.ts:171`;
   upload response type `relay.ts:762`; `proxyImage` `app/lib/mediaUrl.ts:20` (`blob:` passes
   through :22-23) over relay `GET /img` `server.py:3287`.
4. `docs/infloww-screens.md` §3.2 (New post composes "on behalf of the Creator"; Queue shows
   scheduled posts, messages, streams); `docs/routes.md` :13-14. Infloww's My profile (reference
   screenshots outside the repo, never copied) shows the real posts feed and the story strip.
5. Measured in the captured pages (`app/public/of-mirror/pages/`): `new-post/index.html` has the
   editor `[contenteditable][aria-label='Textbox field']` (placeholder "Compose new post..."), the
   `button[at-attr='submit_post']` "Post" (disabled), toolbar `aria-label`s "Add media", "Add media
   from vault", "Schedule post", "Tag other creators", "Add poll", "Add quiz", "Expiration period",
   "Your target", "Format Text", "Record voice", "Record video"; no `type=file` input and no price
   control (`.b-make-post.m-with-free-options`; the page's own menu shows a "$5.00 per month"
   subscription). "Add to story" (`.b-story-item.m-story-item-own`) is on `home/index.html` and
   `new-post/index.html`. `new-post/state-vault` has `input[name='media_vault_search']` and a
   `.b-photos` grid; `state-tag-people` 50 `input.b-input-radio` rows; `state-labels` 2 checkbox
   rows; `state-schedule` buttons Cancel / Save for Later / Next. `collections/index` has
   "Create new list" (its dialog was not captured). `settings/messaging` has only `#autoMessage`.
   Subscription modals: tracking-links/modal-1 `input[name='name']` + "Create Link"; trial-links/
   modal-1 four inputs + "Create link"; promotion-campaign/modal-1 inputs + "Start campaign";
   modal-2 "ADD SUBSCRIPTION BUNDLE" (duration and discount, no price input) + "Save".

| Mirror page | Dead control | Relay route / of_client method | Verdict |
|---|---|---|---|
| new-post | editor + Post | `POST /api/of/v2/posts` server.py:7519, body `_CreatePostBody` :6161; `create_post` of_client.py:2368-2398 | wire |
| new-post | price | `price` field server.py:6166; relay refuses priced posts on a paid page server.py:7506; capture has no price control | no control to wire; send `price: 0` |
| new-post/state-schedule | Next (date, time) | `posted_at` server.py:6169 -> `postedAt` of_client.py:2392 | wire |
| new-post/state-schedule | Save for Later | only `GET /schedules/later/post` server.py:5878; no write method | read-only |
| new-post/state-tag-people | user rows | `GET /posts/tagged-friend-users` server.py:5522 (of_client.py:846); `tagged_users` server.py:6171 -> `_apply_cotags` of_client.py:1427 | wire |
| new-post/state-labels | label rows | `create_post` has no labels field (of_client.py:2368-2398); only `GET /users/{id}/labels` server.py:5594 | read-only |
| new-post/state-vault, "Add media from vault" | tiles, search | `GET /vault/media` server.py:5691; ids into `media_files` server.py:6165; thumbs `/img` server.py:3287 | wire |
| new-post | "Add media" (disk) | `POST /api/of/v2/upload` server.py:7661 -> `upload_media` of_client.py:2679 (`send_with`); dict claims accepted server.py:6163-6165 | wire |
| new-post | poll, quiz, expiration, target, format, voice, video | `expirePeriod`, `fundRaisingTarget`, `votingDueDate` exist in of_client.py:2373-2375 but not in `_CreatePostBody`; poll/quiz bodies unknown | read-only (YAGNI) |
| home, new-post | Add to story | `POST /api/of/v2/stories/upload` server.py:8169 -> `post_story` of_client.py:3454 | wire |
| home, new-post | other story items (Create highlight) | no highlight write method | read-only |
| profile/index | posts feed | `GET /users/{id}/posts` server.py:5555 (of_client.py:875); id from `GET /users/me` server.py:2044 | wire (data) |
| profile/media | media grid | `GET /users/{id}/posts/photos` server.py:5584, `/videos` :5589 | wire (data) |
| queue/* | calendar, tabs, saved-for-later | `GET /schedules` server.py:5883, `/messages/queue` :5992, `/schedules/later/post` :5878, `/schedules/later/chat` :5873 | wire (data) |
| collections/bookmarks/all | posts | `GET /posts/bookmarks/all` server.py:6914 | wire (data) |
| collections/index | Create new list | `POST /lists` server.py:7562 (of_client.py:2440) known, but OF's dialog is not captured | read-only |
| notifications/* | list per tab | `GET /users/notifications?type=` server.py:5359, types all/tips/subscribes/comments/mentions :5363 | wire (data) for those tabs |
| statements/earnings, payouts, referrals | rows | `/payouts/transactions` server.py:5907, `/payouts/requests` :5478, `/payouts/requests/referral` :6931 | wire (data) |
| settings/subscription/tracking-links | Create Link | `POST /campaigns` server.py:6823, `{name}` verified live of_client.py:2135-2145 | wire |
| settings/subscription/trial-links | Create link | `POST /trials` server.py:6846, `_TrialLinkBody` :6835; of_client.py:2166 | wire |
| settings/subscription/promotion-campaign | Start campaign | `POST /promotions` server.py:6800, `_PromoBody` :6792; verified live of_client.py:2099-2120 | wire |
| settings/subscription/promotion-campaign | bundle Save | `_BundleBody` requires `price` server.py:6772; modal has no price | read-only |
| settings/subscription | price Save, row kebab deletes | no price write method; deletes need real row ids, rows are examples | read-only |
| settings/* other toggles and fields | `/users/me/settings`, notifications, security, story, streaming | no write method; `update_profile` verifies `about` only, other keys "likely" of_client.py:2189-2199 | read-only (as today) |

## Constraints (binding)

- Nothing from `~/Downloads` is committed (captures, screenshots, names). Checks use synthetic data
  only ("Alpha One", 1x1 PNGs generated by the script).
- `node scripts/of-mirror.mjs --check` stays green; no committed page under `app/public/of-mirror/`
  is hand-edited (all wiring is runtime DOM in `app/lib/ofMirror*.ts`).
- No new OF endpoint and no guessed OF body. A relay route or body field may be added only when
  `of_client.py` already sends that body; this plan adds none. A control whose body is unknown
  sends nothing and shows "Read-only in Inflowwww for now" (`READ_ONLY`, a toggle flips back).
- Writes only in single-model scope (existing rule, ofMirrorWrites.ts:14-16): in all-models scope a
  wired control sends nothing and shows "Select a model to save changes"; data pages keep the
  examples (ofMirrorData.ts:15-16).
- Every ticket ships a `python3 -I scripts/of-mirror-check/<name>.py` headless check against a
  mocked relay (Playwright routes in the style of `writes.py`), and vitest for any new or changed
  TS lib (`app/lib/*.test.ts`); `pnpm -C app typecheck`, `pnpm -C app lint` (0 errors) and
  `ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run` stay green.
- The run never fetches the network or touches live OF: every relay path a check hits is mocked,
  unmocked `/api/**` returns `[]`, and any request to a non-localhost host fails the check.
- YAGNI: no new dependency, no new UI outside OF's own markup except the minimal pieces a Phase
  names; no edit, delete or pin of existing posts, no story from vault, no list writes.

## Check loop (binding for every ticket)

A ticket is done when, with `cd app && npx next dev --webpack -p $PORT` running:
1. Its check script exits 0 and prints one JSON line per check (`{"check","want","got"}`, as
   `writes.py`), asserting the exact method, path, `X-Account-Id` header and JSON (or multipart
   field) the mocked relay received, plus the all-models pass (nothing sent, `SELECT_MODEL` note).
2. Its vitest file passes; `node scripts/of-mirror.mjs --check` exits 0.
3. The implementer Reads the ticket's PNGs in `/tmp/of-mirror-shots` (OF's look kept, note
   visible; never committed), and updates `scripts/of-mirror-check/README.md` and `docs/routes.md`.

## Phase 0 — New post: text, schedule, tagged users

Target: on `new-post`, typing in the editor enables "Post"; Post sends `POST /api/of/v2/posts`;
the schedule dialog's Next sets the date, "Tag other creators" picks users, and the post goes out.

Decisions:
- New `app/lib/ofMirrorPost.ts` (`collectPost`, `bindPost`), mounted in `OfMirrorFrame.tsx`;
  `note`, `READ_ONLY`, `SELECT_MODEL` are exported from `ofMirrorWrites.ts`, not copied.
- The state dialogs are separate pages, so the draft (text, `posted_at`, `tagged_users`,
  `media_files`, thumbs) lives in `sessionStorage` key `oi:new-post:<accountId>` and is restored
  into the editor on every `new-post/*` load; cleared after a successful post.
- Body is the relay's `_CreatePostBody` shape, same as PostComposer.tsx:127-133: `{text,
  media_files, price: 0, posted_at?, tagged_users?}`; `text` is the editor's paragraphs joined
  with `\n` (`textOf`, ofMirrorWrites.ts:71). No price control is added (capture has none; a paid
  page refuses priced posts, server.py:7506).
- Schedule: `state-schedule`'s date and time fields are parsed with `parseDate`/`parseTime`; Next
  stores `localIso(at)` (at least one minute ahead, else the validation note) and links back.
- Tag people: `state-tag-people` rows are filled from `GET /posts/tagged-friend-users` (template
  row cloned, as `applyData`); a checked row adds its OF user id to `tagged_users`.
- Labels rows, Save for Later, poll, quiz, expiration, target, format, voice, video: `READ_ONLY`.
- After success: an immediate post navigates to `/of-manager/profile`, a scheduled one to
  `/of-manager/queue` (`QUEUE`, ofMirrorWrites.ts:52). On error: Post re-enabled, red
  `Could not post: <message>` note, draft kept.

Acceptance:
- `app/lib/ofMirrorPost.test.ts`: `collectPost` (text only, scheduled, tagged), empty text keeps
  Post disabled, draft round-trip through `sessionStorage`, past date gives the note.
- `python3 -I scripts/of-mirror-check/post.py`: mock receives exactly one `POST
  /api/of/v2/posts` `{"text":"Synthetic post","media_files":[],"price":0}` with `X-Account-Id: 1`,
  lands on `/of-manager/profile`; second run with schedule tomorrow 6:30 pm and one tagged row
  receives `posted_at` (local ISO with offset) and `tagged_users:[<id>]`, lands on the queue; a
  labels checkbox sends nothing and shows `READ_ONLY`; all-models pass sends nothing.

## Phase 1 — media from the vault, thumbnails that load

Target: "Add media from vault" (`new-post/state-vault`) shows the model's vault with real
thumbnails; picked tiles attach to the post and show as thumbs in the composer.

Decisions:
- `DATA_PAGES` gains `"new-post/state-vault": ["vaultMedia"]`; the grid reuses `applyVaultMedia`
  and `tileThumb` (ofMirrorData.ts:388-393) with `proxyImage(url, accountId)`, so every `<img>`
  src is `/img?u=...&account_id=...` (server.py:3287), never an OF CDN URL.
- A tile click toggles OF's selected mark and the media id in the draft's `media_files`;
  `media_vault_search` filters the loaded tiles client-side (no new query param).
- ASSUMPTION: OF's attached-media strip was not captured; the composer shows picked media as a
  row of 64px thumbs above `.b-make-post__actions`, built from the vault tile's own `<img>` markup.

Acceptance:
- `ofMirrorData.test.ts` extended: `new-post/state-vault` maps to `vaultMedia`; tile toggle test.
- `python3 -I scripts/of-mirror-check/post_vault.py`: mock `GET /api/of/v2/vault/media` (3
  synthetic items) and `GET /img*` (a generated 1x1 PNG); every tile `<img>` has
  `naturalWidth > 0` and an `/img?` src with `account_id`; picking 2 tiles then Post sends
  `media_files:[<id1>,<id2>]`; no request leaves localhost.

## Phase 2 — upload from disk

Target: "Add media" opens a file picker; the file uploads through the relay and attaches.

Decisions:
- `of_client.upload_media` exists (of_client.py:2679) and the relay already exposes it as `POST
  /api/of/v2/upload` (server.py:7661), whose `send_with` the post body accepts (server.py:6163-6165).
  So this is wired, not read-only; the stories/upload pattern is not reused for posts.
- A hidden `<input type=file accept="image/*,video/*">` is created by `bindPost`; one file per
  pick; `relay.uploadFile("/api/of/v2/upload", file)` (relay.ts:171); `send_with` entries are
  appended to `media_files`; the thumb is a `blob:` URL (proxyImage passes it through).
- `ready:false` or an error shows the red note with the relay's `note`; Post stays disabled while
  an upload is in flight.

Acceptance:
- `ofMirrorPost.test.ts`: `send_with` merge (ids and claim dicts mixed, order kept).
- `python3 -I scripts/of-mirror-check/post_upload.py`: `set_input_files` with a PNG written to
  /tmp by the script; mock receives multipart `POST /api/of/v2/upload` field `file`, returns
  `{"ready":true,"send_with":[{"processId":"p1","host":"h","name":"n"}]}`; Post then sends
  `media_files:[{"processId":"p1",...}]`; a `ready:false` reply shows its note and sends no post.

## Phase 3 — Add to story

Target: "Add to story" on `home` and `new-post` publishes an image as a story.

Decisions:
- Click opens a hidden `<input type=file accept="image/*">` (the relay documents image stories,
  server.py:8148); `relay.uploadFile("/api/of/v2/stories/upload", file)` (server.py:8169 ->
  `post_story` of_client.py:3454). No caption, mention or question (YAGNI), no story from vault.
- Success: grey "Added to story" note at the story strip; error: red `Could not add: <message>`.
- Other story-strip buttons with no write method (Create highlight): `READ_ONLY`.

Acceptance:
- `ofMirrorPost.test.ts` (story block; the code lives in `ofMirrorPost.ts`): binds on home and
  new-post, ignores other story items.
- `python3 -I scripts/of-mirror-check/story.py`: on home and new-post, mock receives one multipart
  `POST /api/of/v2/stories/upload` field `file` with `X-Account-Id: 1`; "Create highlight" sends
  nothing and shows `READ_ONLY`; all-models pass sends nothing.

## Phase 4 — real data on profile, queue, collections, notifications, statements

Target: with a single model, these pages show that model's rows instead of the captured examples,
as messages, vault and lists already do (ofMirrorData.ts:32-41).

Decisions:
- New `Part`s in `ofMirrorData.ts`, same clone-template-row method and `restore` undo:
  `posts` (profile/index, `GET /users/{id}/posts`, `id` from the `["of-me", accountId]` query),
  `profileMedia` (profile/media, photos + videos merged newest first), `queue` (queue/index
  `GET /schedules` for the shown month; state-tab-messages `/messages/queue`; saved-for-later-posts
  `/schedules/later/post`; saved-for-later-messages `/schedules/later/chat`), `bookmarks`
  (collections/bookmarks/all), `notifications` (index=`all`, tip=`tips`, subscribed=`subscribes`,
  commented=`comments`, mentioned=`mentions`), `transactions` (statements/earnings), `payouts`
  (statements/payouts), `referrals` (statements/referrals).
- Notification tabs with no relay `type` (favorited, purchases, message, tags, deactivated_media)
  keep their examples. Post and media pictures go through `proxyImage`; text through :129.
- Row actions (post kebab, queue delete, withdraw) and "Create new list" are `READ_ONLY`.
- Fields the relay does not return render empty, never invented; each Part's field mapping is a
  measured table in its spec (capture selector -> relay field).

Acceptance:
- `ofMirrorData.test.ts` extended per Part: rows cloned, examples hidden, `restore` puts them back.
- `python3 -I scripts/of-mirror-check/feeds.py`: each page with its routes mocked (2-3 synthetic
  rows) shows exactly those rows (no `Fan ` / lorem example text left in the list), every call
  carries `X-Account-Id: 1`, thumbs load via `/img?`; all-models pass shows the examples and makes
  no relay call for these Parts; no console errors.

## Phase 5 — OF settings writes with known bodies

Target: the subscription modals whose body `of_client.py` already sends are wired; every other
settings control keeps the read-only note (as today).

Decisions:
- `SUBMITS` in `ofMirrorWrites.ts` generalises to page -> `{button, collect, send, then}` so the
  stream form (existing) and the three modals share one path: tracking-links/modal-1 "Create Link"
  -> `POST /api/of/v2/campaigns {name}`; trial-links/modal-1 "Create link" -> `POST
  /api/of/v2/trials {name, subscribe_days, subscribe_counts, expired_at?}`;
  promotion-campaign/modal-1 "Start campaign" -> `POST /api/of/v2/promotions {discount,
  subscribe_counts, subscribe_days, message, type}`. Each input maps by its measured label text;
  an input the spec cannot map leaves that modal read-only.
- On success the modal's own close link is followed and `["of-settings"]` invalidated.
- Bundle Save (relay needs `price`, modal has none), subscription price Save, kebab deletes, and
  all `/users/me/settings`, notification, security, story, streaming controls stay `READ_ONLY`.

Acceptance:
- `ofMirrorWrites.test.ts` extended: the three collectors (valid, missing field note, out-of-range
  discount note), the stream form unchanged.
- `python3 -I scripts/of-mirror-check/settings_writes.py`: mock receives exactly the three bodies
  above; bundle Save sends nothing and shows `READ_ONLY`; all-models pass sends nothing;
  `writes.py` still exits 0.

## Phase 6 — sign-off: no silent control

Target: on every mirror page, a click on a control that is neither a link, a wired control nor a
state opener gives the read-only note; the full suite is green.

Decisions:
- Wired controls carry `data-oi-wired`; a small fallback in `bindWrites` (all pages, not only
  settings) notes `READ_ONLY` for any other clicked `button`, `[role=button]` or checkbox outside
  an `a[href]` (video-player controls excluded); `bindWrites`'s settings `onChange` path is kept.
- `docs/routes.md` OF Manager rows and the check README list what writes, what shows data and
  what is read-only, matching the Ground truth table.

Acceptance:
- `python3 -I scripts/of-mirror-check/dead.py`: for new-post/*, home, profile/*, queue/*,
  collections/*, notifications/*, statements/*, settings/subscription*: every visible enabled
  control, clicked, yields a recorded relay write, a navigation, or the `READ_ONLY` note within
  1s; prints the count per page; exits 1 on a silent control.
- All of `render.py`, `navigate.py`, `settings_values.py`, `writes.py`, `dark.py`, `data.py`,
  `post.py`, `post_vault.py`, `post_upload.py`, `story.py`, `feeds.py`, `settings_writes.py`,
  `dead.py` exit 0; `node scripts/of-mirror.mjs --check`, typecheck, lint, `test:run` green.
