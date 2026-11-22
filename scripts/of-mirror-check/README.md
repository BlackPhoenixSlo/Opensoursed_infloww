# of-mirror-check

Headless checks for OF Manager (the mirrored OnlyFans creator UI: home, go live, new post, notifications, messages, vault, queue, collections, statements, statistics, bank, profile, settings).
They fake the login by mocking `/auth/me`, `/chatter/me*` and `/admin/employees`
with Playwright routes, so no relay is needed. Needs a Next dev server
(port from env `PORT`, default 3091). Both exit non-zero on a failed check
(unexpected URL or iframe page, no iframe, a switch or input that does not respond):

    cd app && npx next dev --webpack -p 3091
    python3 -I scripts/of-mirror-check/render.py fans account/2fa    # settings pages; screenshots to /tmp/of-mirror-shots
    python3 -I scripts/of-mirror-check/render.py /of-manager/statistics /of-manager/messages/chat   # any OF Manager path
    python3 -I scripts/of-mirror-check/navigate.py                   # click-through: nav, tabs, switch + input, modal, dropdown state open/close, back,
                                                                     # sidebar > Vault, a notifications tab, two chat rows (the chat's header shows each row's name, the list marks it current; it stays through the price dialog and its Cancel), statistics tabs, sidebar > Go live,
                                                                     # page states (new post: schedule / poll / expiration, messages sort menu) open and close; the queue's Messages tab toggles in place, Messages saved for later and back
                                                                     # OF's own left nav hidden in the frame (as Infloww); sidebar > New post, Home, home's GO LIVE and back, the streaming dashboard > SCHEDULE (the schedule form) > back, sidebar > OF settings

Live proofs and Request captures reach OnlyFans, so they are never a Mirror check: `scripts/of-live-proof/README.md`.

The generator's own guard runs without a server or inputs: `node scripts/of-mirror.mjs --check` (committed pages: hosts, emails, IPs, handles, links, amounts, digit runs; pages vs `app/lib/of-mirror-pages.ts`).

navigate.py also runs with a single-model scope (`chatterly:scope` = `model:acc1`) and a mocked
`/api/of/v2/users/me`, and checks the frame shows that model's username, name, price and bio
(screenshot `inapp-live-identity.png`).

settings_values.py checks the settings values the same way: scope `model:acc1`, the relay's settings
sources (`/users/me`, `/users/me/settings`, `/users/settings/notifications/toast`) mocked with synthetic
values, and the mapped controls (`app/lib/ofMirrorSettings.ts`) on fans, messaging, streaming,
notifications/toast and security/watermarks checked in the frame (screenshot `inapp-settings-values.png`):

    python3 -I scripts/of-mirror-check/settings_values.py

writes.py checks the write-through (`app/lib/ofMirrorWrites.ts`) with the same mocks and scope, recording the
relay writes: typing a display name and clicking OF's SAVE sends `PATCH /api/of/v2/users/me` `{"name": ...}` (and the
page's name then shows it), the welcome message switch sends `PATCH /api/of/v2/users/me/reply-on-subscribe` `{"enabled": true}`, fans' auto follow
back toggle sends `PATCH /api/of/v2/users/me/settings/security` `{"isAutoFollowBack": true}`, a toast notification toggle
sends `PATCH /api/of/v2/users/settings/notifications` `{"notifications": {"toast": [{"code": "new_tips", "value": true}]}}`,
subscription shows the mocked price and its Save, after the confirm, sends `PATCH /api/of/v2/users/me` `{"subscribePrice": 12.5}`
(`app/lib/ofMirrorSettingsWrites.ts`); profile's Save, the welcome switch, the toggles and the price Save each show
OF's success toast "Changes were saved" and stay on the page; the unmapped web push permission switch is
disabled with the tooltip "Not available in Inflowwww yet" (`inapp-writes-price.png`, `inapp-writes-webpush.png`); the stream schedule form's
SCHEDULE (`streaming/dashboard/create`) sends nothing and shows "Enter a date and a time" while the form is empty, and with
tomorrow picked in the Date field's day popup (written as OF's "Oct 13, 2026"), 18:30 in the Time field's time input and a
description sends exactly one `POST /api/of/v2/streams` `{description, scheduledDate,
isShowTips: true}` and lands on `/of-manager/queue`. No All-models pass: OF Manager has no All scope; a saved "all" shows the first live creator (owner 2026-11-20, origin/main 77e5df419) (screenshots `inapp-writes.png`, `inapp-writes-fans.png`,
`inapp-writes-schedule-invalid.png`, `inapp-writes-schedule-filled.png`, `inapp-writes-schedule-queue.png`):

    python3 -I scripts/of-mirror-check/writes.py

settings_writes.py checks the OF settings > Subscription modals (`app/lib/ofMirrorWrites.ts` `SUBMITS`), the ones
with no Known body, and the relay's rows (`app/lib/ofMirrorSubscription.ts`) with the same login mocks; the relay's
`POST /api/of/v2/campaigns` is mocked (200 `{"id":1}`), and so are synthetic GETs (`ROWS`: `/users/me`, one tracking
link, one free trial link, and in `/users/me` one promotion and one bundle, as OF reads them); every unmocked `/api/**` returns `[]`, any request to a host
other than localhost is aborted and fails the check (even one whose path a mock matches), and every non-GET `/api/**`
request is recorded with its method, path, JSON body and `X-Account-Id`. Checks, scope `model:1` unless noted:

1. "Create new tracking link" (`subscription/tracking-links/modal-1`): "Create Link" is disabled until a name is typed
   and enabled once "Synthetic link" is; the name's label then floats clear of it and the counter reads "14 / 100".
2. Clicking it sends exactly one `POST /api/of/v2/campaigns` `{"name":"Synthetic link"}` (no `code`) with
   `X-Account-Id: 1` and lands on the Tracking links tab (`/of-manager/settings/subscription/tracking-links`).
3. Opening the modal again, typing the name and pressing Enter sends exactly one more such POST and lands on the tab
   too (a native form submit never reloads the frame).
4. The offer dialogs (`OFFERS`, `app/lib/ofMirrorOffers.ts`, OF's own bodies read from its bundle): the promotion modal's
   "Start campaign" (`subscription/promotion-campaign/modal-1`) and the free trial modal's "Create link"
   (`trial-links/modal-1`) are enabled; a click sends exactly one `POST /api/of/v2/promotions` (`/trials`) with OF's
   default body and `X-Account-Id: 1` (answered by the mock) and lands on its tab. The bundle modal's "Save"
   (`.../modal-2`) is disabled with OF's reason while users/me settings offer no bundle.
5. The rows: the Tracking links tab shows the synthetic link (name, counts) and no "No results :("; its Copy link shows
   OF's toast "Link copied"; its Delete asks in OF's ModalConfirm (nothing sent until its Delete is clicked) and sends exactly one `DELETE
   /api/of/v2/campaigns/7` with `X-Account-Id: 1`, removes the row and stays on the tab. The Free trial links tab and
   the promotion page show their synthetic rows (the promotion's title, the bundle's "$20.35 USD total for 3 months").
6. (Retired) No All-models pass: OF Manager has no All scope; a saved "all" shows the first live creator (owner 2026-11-20, origin/main 77e5df419).
7. No console errors.

It prints one `{"check","want","got"}` line per check and exits 1 on a failure (screenshots
`inapp-settings-writes-tracking-filled.png`, `-tracking-tab.png`, `-promotion.png`,
`-bundle.png`, `-trial.png`, `-rows-tracking.png`, `-rows-trials.png`,
`-rows-promotion.png`, all `inapp-settings-writes-*`):

    python3 -I scripts/of-mirror-check/settings_writes.py

dark.py checks that the frame follows our theme (`chatterly:theme` dark, then light) with OF's own `m-mode-dark` on its `<html>` on home, messages/chat, settings/fans and settings/display, with no light first paint (a script a route puts first in each mirror page's `<head>` records the `<html>` class when the
parser finishes, readyState `interactive`, and at DOMContentLoaded, both before any load event: dark must have `m-mode-dark` then;
not an init script: the frame's page reuses the window of its initial about:blank, where alone Playwright runs those, and
window listeners added there recorded nothing on 3 of the 4 pages; with the generator's boot script stripped these rows fail),
and, live, no light frame: in dark, a CDP screencast (`Page.startScreencast`, every frame) runs from navigation start until the
mirror frame has loaded, and every frame after the `<iframe>` element exists must have a mean luminance under 0.4 inside the
frame's box (Pillow decodes the PNGs, else a canvas in a throwaway page; it prints frame count and max luminance, and fails with
the boot script removed); the same screencast is also measured over the whole viewport (our dark grey chrome included), every
frame from navigation start: each must be at most the page's steady state (a screenshot once loaded) + 0.1 and under 0.4
(it prints frames, max full-viewport luminance and steady state per page; the run reloads first, since the display switch
check leaves the page light); and that display's "Dark mode" switch flips our theme (screenshots `dark-*.png`, `light-*.png`):

    python3 -I scripts/of-mirror-check/dark.py

data.py checks the real rows (`app/lib/ofMirrorData.ts`) with the same login mocks and scope `model:1`: the relay's
`/chats`, `/chats/<id>`, `/chats/<id>/messages`, `/vault/lists`, `/lists` and `/lists/<id>/users` mocked with synthetic rows
(3 chats "Alpha One", "Beta Two", "Gamma Three", 4 messages, 2 vault folders, 2 lists of 2 users). The chats page shows
exactly those 3 rows (no `Fan ` text); clicking "Beta Two" opens `/of-manager/messages/chat?chat=<id>` with that header,
the open row marked and the 4 messages in order (the model's on the right, the fan's on the left); the price dialog's link
keeps `?chat=` and its page keeps the header; the vault shows All media and the 2 folders, and a clicked folder
(`/of-manager/vault?list=<id>`) is marked; collections shows the 2 lists, and clicking one
(`/of-manager/collections/user-lists/list?list=<id>`) shows its title, the lists with it marked, and its 2 users.
Every relay call must carry `X-Account-Id: 1`; no console errors (screenshots `inapp-data-chats.png`, `inapp-data-chat.png`,
`inapp-data-chat-price.png`, `inapp-data-vault.png`, `inapp-data-lists.png`, `inapp-data-list-users.png`):

    python3 -I scripts/of-mirror-check/data.py

post.py checks New post (`app/lib/ofMirrorPost.ts`) with the same login mocks and scope `model:1`; every unmocked
`/api/**` returns `[]`, and any request to a host other than localhost is aborted and fails the check. Run 1: Post is
disabled at first; typing "Synthetic post" in OF's editor enables it and keeps the Post draft in `sessionStorage`
(`oi:new-post:1`); pressing Post sends exactly one `POST /api/of/v2/posts` with `{"text":"Synthetic post","media_files":[],"price":0}`
and `X-Account-Id: 1`, stays on `/of-manager/new-post` with the composer empty and OF's toast "Your post has been
published", and the draft key is gone. Run 2 (schedule): type the text, open
Schedule (the captured calendar, re-rendered for the current month), move to tomorrow, click it, type "6:30 pm" in the time
tab and press Next; back on the composer the text is restored and the grey "Scheduled for <date> 6:30 PM · Clear" summary
shows; Schedule then Cancel leaves it unchanged; Tag other creators lists the mocked Relay's synthetic "Alpha One" (901)
and "Beta Two" (902) in OF's row markup from one `GET /api/of/v2/posts/tagged-friend-users?limit=50&offset=0` with
`X-Account-Id: 1`, with no "List <n>" example text; checking Alpha One and pressing Close adds "Tagged: Alpha One" to the
summary; Post sends exactly one `POST /api/of/v2/posts` whose `posted_at` equals Python's
`datetime(tomorrow, 18, 30).astimezone().isoformat()` and whose `tagged_users` is `[901]`, and stays with the toast
"Your post is scheduled for …". Tag list failure: with `tagged-friend-users` answering 502, the tag dialog shows no rows
(never the captured examples), and the following Post carries no `tagged_users`. Validation: Next with today
at 12:00 am (already past) sends nothing, stores no schedule and shows the red "Pick a time at least a minute from now".
Extras: a label picked on `new-post/state-labels` and a poll typed on `new-post/state-poll` with its "3 days" duration go
out with the next Post (`label_ids`, `voting_*`), which stays with the toast; NEW LABEL's name field, the quiz's
correct-answer switch, "+ Add another option" and the formatting tools (disabled, "Not available in Inflowwww yet") are
covered by `app/lib/ofMirrorPost.test.ts`. Error: with the mock answering 502, the page shows the red "Could not post: <relay text>" note, Post is
enabled again, the draft is kept and the page stays on New post. No All-models pass: OF Manager has no All scope; a saved "all" shows the first live creator (owner 2026-11-20, origin/main 77e5df419). No console errors,
except exactly one failed 502 load in each of the Tag list failure and Error cases (screenshots `inapp-post-typed.png`,
`inapp-post-posted.png`, `inapp-post-schedule.png`, `inapp-post-scheduled.png`, `inapp-post-validation.png`,
`inapp-post-tags.png`, `inapp-post-tagged.png`, `inapp-post-tags-failed.png`, `inapp-post-save-later.png`,
`inapp-post-labels.png`, `inapp-post-poll.png`,
`inapp-post-error.png`):

    python3 -I scripts/of-mirror-check/post.py

post_vault.py checks New post's vault dialog (`new-post/state-vault`; `app/lib/ofMirrorData.ts` and `app/lib/ofMirrorPost.ts`)
with the same login mocks; every unmocked `/api/**` returns `[]`, and any request to a host other than localhost is aborted
and fails the check. The relay's `GET /api/of/v2/vault/media` is mocked with 3 synthetic media (ids 61, 62, 63, CDN URLs on
`cdn.example.invalid`, no `_thumb`; only 62 has `_ai.description` "synthetic beach") and `/img` with a 1x1 PNG the script
builds. Single Creator (scope `model:1`): with "Synthetic post" typed, "Add media from vault" opens
`/of-manager/new-post/state-vault`, whose grid shows exactly the 3 media, newest first, each tile stamped `data-oi-media`
with its vault id, wired and dated as on the Vault page, with no example tile left; every tile `<img>` has an `/img?` src
carrying `account_id=1` and loaded (`naturalWidth > 0`), and `/img` was asked for the media's CDN pictures; there is one
vault request, the Vault page's `limit=24`, with `X-Account-Id: 1`. Search ("Search media" opens OF's search box):
" BEACH " leaves only tile 62 shown and clearing shows all 3. Picking 61 and 62, unpicking 61 and picking it again marks
exactly those tiles (OF's `selected` on the tile and its checkbox) and leaves the Post draft (`oi:new-post:1`) with the
text, `media_files` `[62, 61]` and the tiles' own srcs as thumbs, in click order. A search hiding picked tile 61 changes
neither its mark nor the draft, clearing shows all 3 with both still marked, and no further vault request is made. Close
returns to the composer with the text restored and one row of 2 loaded thumbs directly before the actions bar, whose srcs
equal the picked tiles' srcs in click order; reopening the dialog marks exactly 61 and 62 again and leaves the draft
unchanged, and nothing is sent before Post. After Close again, Post sends exactly one `POST /api/of/v2/posts`
`{"text":"Synthetic post","media_files":[62,61],"price":0}` with `X-Account-Id: 1` and stays on New post; the draft is
cleared, the thumbs row is gone and the editor empty. The dialog's folder list is the Relay's (unmocked: `[]`), so it shows
"All media" alone, never the captured "List <n>" folders. No All-models pass: OF Manager has no All scope; a saved "all" shows the first live creator (owner 2026-11-20, origin/main 77e5df419). No console errors
(screenshots `post-vault-tiles.png`, `post-vault-picked.png`, `post-vault-search.png`, `post-vault-composer.png`,
`post-vault-reopened.png`):

    python3 -I scripts/of-mirror-check/post_vault.py

post_upload.py checks New post's "Add media" (`app/lib/ofMirrorPost.ts`) with the same login mocks; every unmocked
`/api/**` returns `[]`, and any request to a host other than localhost is aborted and fails the check (even one whose
path a mock matches). The relay's `POST /api/of/v2/upload` and `POST /api/of/v2/posts` are mocked; the script builds a
1x1 PNG (stdlib `zlib`/`struct`) and hands it to the file chooser as an in-memory file, and parses the multipart upload
body with stdlib `email.parser.BytesParser`. Checks, scope `model:1` unless noted:

1. Clicking "Add media" fires a file chooser whose input has `accept="image/*,video/*,audio/*"` and `multiple`; the button
   carries `data-oi-wired`.
2. Every upload is held (its route kept and fulfilled later). With "Synthetic post" typed, Post is disabled while the
   upload is held and enabled once it is fulfilled with the accepted claim `p1`. With two picks held at once, Post stays
   disabled after the first is refused while the second is in flight, and is enabled once the second fails (502). An
   upload held across a State page round trip (Schedule, then Cancel) keeps Post disabled until it is fulfilled.
3. The mock receives exactly one `POST /api/of/v2/upload` with `X-Account-Id: 1` and one multipart part named `file`,
   filename the PNG's name, bytes equal to the PNG.
4. The attached-media strip shows one loaded thumb whose `src` starts with `blob:`, and Post sends exactly one
   `POST /api/of/v2/posts` with `X-Account-Id: 1` and
   `{"text":"Synthetic post","media_files":[{"processId":"p1","host":"h","name":"n"}],"price":0}`.
5. With "Synthetic post" typed and the accepted claim `p2` attached, a second pick refused with
   `{"ready":false,"send_with":null,"note":"Synthetic refusal"}` shows a red `#oi-note` "Could not upload: Synthetic
   refusal"; the strip, the editor and the `oi:new-post:1` draft's `media_files` (`[p2]`) are unchanged and no post is
   sent within 1s. A refusal with no note reads "Could not upload: upload not ready".
6. An upload answered 502 shows a red `#oi-note` starting "Could not upload:" and adds no thumb; picking the same PNG
   again sends a second upload with the same bytes.
7. (Retired) No All-models pass: OF Manager has no All scope; a saved "all" shows the first live creator (owner 2026-11-20, origin/main 77e5df419).
8. No console errors (but a 502's own resource line, and after a reload the dead `blob:` URL's); no request left
   localhost.
9. Dedupe hit: with vault id 42 seeded in the draft before load, an upload answered
   `{"ready":true,"deduped":true,"vault_id":42,"send_with":[42]}` is appended as returned: Post sends `media_files` `[42, 42]`.
10. After an accepted upload, Schedule then Cancel: back on New post the strip shows one loaded `blob:` thumb and Post
    sends the claim in `media_files`.
11. After an accepted upload and a full reload (its `blob:` URL dead), the strip holds one 64px grey square with no
    broken `<img>` left visible, and the draft's `media_files` still holds the claim.

It prints one `{"check","want","got"}` line per check and exits 1 on a failure (screenshots `inapp-post-upload-thumb.png`,
`inapp-post-upload-refused.png`, `inapp-post-upload-round-trip.png`, `inapp-post-upload-reloaded.png`). The State pages' copies of "Add media" (in the composer under each
`new-post/state-*` dialog) are the same upload button (`app/lib/ofMirrorPost.test.ts`):

    python3 -I scripts/of-mirror-check/post_upload.py

story.py checks the story strip (`app/lib/ofMirrorPost.ts` `bindStory`) with the same login mocks; every unmocked
`/api/**` returns `[]`, and any request to a host other than localhost is aborted and fails the check (even one whose
path a mock matches). The relay's `POST /api/of/v2/stories/upload` is mocked (200 `{}`) and every non-GET `/api/**`
request is recorded with its method, path, `X-Account-Id` and multipart parts; the script builds a 1x1 PNG (stdlib
`zlib`/`struct`) and hands it to the file chooser as an in-memory file, and parses the multipart body with stdlib
`email.parser.BytesParser`. "Add to story" is the strip's only write: New post's "Go live" and "Send message" are links
to their pages and its other tiles are disabled with the tooltip "Not available in Inflowwww yet"; any other
story-strip tile sends nothing and shows "Read-only in Inflowwww for now" under the strip, in either scope. Checks, scope `model:1`
unless noted, 1-6 on `home` and on `new-post`:

1. "Add to story" carries `data-oi-wired`; clicking it fires a file chooser whose input has `accept="image/*,video/*"`
   and no `multiple`.
2. Setting the PNG sends exactly one non-GET `/api/**` request: `POST /api/of/v2/stories/upload` with `X-Account-Id: 1`
   and one multipart part named `file`, filename the PNG's name, bytes equal to the PNG.
3. The note reads "Added to story" in grey, is visible and sits right after the strip (`.stories-list`).
4. No console errors but the 500's one failed resource load; no request left localhost.
5. Error: the mock answers the next upload 500 `{"detail":"synthetic failure"}` once; picking the same PNG again sends a
   second identical upload, the note reads the red "Could not add: synthetic failure" right after the strip and is still
   there after the grey note's 3s fade, and the tile is enabled again.
6. Neither image nor video: setting a `.txt` file on the chooser sends nothing and the note reads exactly the red "Could
   not add: choose an image or a video" right after the strip, never "Added to story".
7. (Retired) No All-models pass: OF Manager has no All scope; a saved "all" shows the first live creator (owner 2026-11-20, origin/main 77e5df419).
8. My profile (`profile`, scope `model:1`): "Create highlight" is disabled with the tooltip "Not available in Inflowwww
   yet"; a dispatched click fires no file chooser within 1s, sends nothing and shows no note. "Story archive" carries
   `data-oi-wired`; a click opens the in-place archive box right after the strip, sends nothing but GETs, shows no note
   and stays on the page. No console errors. The strip's tiles are covered by
   `app/lib/ofMirrorStory.test.ts` and `app/lib/ofMirrorProfile.test.ts`, as are
   Home's "Start profile promotion" (a link to the promotion dialog over Home, `home/state-promotion`) and New post's
   "Go live", "Send message", "Start profile promotion" and "Create new trial link" links.

It prints one `{"check","want","got"}` line per check and exits 1 on a failure (screenshots `inapp-story-home.png`,
`inapp-story-new-post.png`, `inapp-story-home-error.png`, `inapp-story-new-post-error.png`, `inapp-story-profile.png`):

    python3 -I scripts/of-mirror-check/story.py

collections_writes.py checks collections writes (app/lib/ofMirrorCollections.ts) in the frame, relay mocked: the list page's More menu, a user
card's Lists menu and the header's + (OF's "Create new list" / "Create new label" dialog) send their relay writes.
No All-models pass: OF Manager has no All scope; a saved "all" shows the first live creator (owner 2026-11-20, origin/main 77e5df419).

Mocks the login (as writes.py) and, with scope `model:acc1`: GET /api/of/v2/lists (two synthetic custom lists with
OF's flags, Whales 31 and Regulars 32), GET /lists/31/users (two synthetic users), GET /users/alphaone (id 901) and
POST /lists/users ({"31": [901]}); every other non-GET /api/** is recorded (method, path, X-Account-Id, body) and
answered {"success": true}. Confirm dialogs are accepted. Checks, on collections/user-lists/list?list=31: More lists
Rename list, Add users, Clear list, Delete list; Rename (the dialog holding "Whales") sends PATCH /lists/31 {name};
Add users with "@alphaone" sends POST /lists/users {"31": [901]}; a card's Lists offers "Remove from Whales" and "Add
to Regulars", which send DELETE /lists/31/users/202 and POST /lists/32/users/202; Clear list sends DELETE
/lists/31/users; Delete list sends DELETE /lists/31 and lands on /of-manager/collections, which shows the first list's
users and whose + opens the "Create new list" dialog, whose Save sends POST /lists {name}; Post Labels' + opens
"Create new label", whose Save sends POST /labels {name}. Every write carries X-Account-Id acc1. Screenshots:
/tmp/of-mirror-shots/inapp-collections-more.png, inapp-collections-card.png, inapp-collections-create.png,
inapp-collections-label.png. Exit 1 on a failed check.

    python3 -I scripts/of-mirror-check/collections_writes.py

feeds.py checks the Phase 4 feed pages (`app/lib/ofMirrorData.ts`, `app/lib/ofMirrorFeeds.ts`) with the same login
mocks, the top bar's Creator list (accounts 1 and 2) and `GET /api/of/v2/users/me` per account (`{"id": 1, ...}`,
`{"id": 2, ...}`). Every Relay route these pages read is mocked with 2-3 synthetic rows ("Alpha One" ..., pictures on
`https://cdn.example.invalid/`): `/users/<id>/posts`, `/users/<id>/posts/photos` and `/posts/videos`,
`/posts/bookmarks/all`, `/schedules`, `/schedules/later/post`, `/schedules/later/chat`,
`/users/notifications` (filtered by its `type`, as OF does), `/payouts/transactions`, `/payouts/requests` and
`/payouts/requests/referral`; the Relay's `/img` proxy returns a generated 1x1 PNG (stdlib `zlib`/`struct`). Every
unmocked `/api/**` returns `[]`, and any request to a host other than localhost is aborted and fails the check (even
one whose path a mock matches). Checks, scope `model:1` unless noted:

1. `profile` and `profile/state-more-menu`: exactly account 1's posts, in order ([text, date] per post); no `Fan N`,
   `@fanN` or `Lorem` text in the list; every row picture through `/img?` with `account_id=1` and loaded
   (`naturalWidth > 0`); every relay call carries `X-Account-Id: 1` and each posts request `limit=20`; a post's More
   click shows "Read-only in Inflowwww for now", the button carries no `data-oi-wired`, and only GETs are sent.
2. `profile/media`: exactly account 1's photo and video posts merged, newest first, a post in both lists once, three to
   a row (the still-less post with no picture, the zero-count post with no badge); the sidebar's recent strip keeps its
   3 example tiles; `/posts/photos` and `/posts/videos` are each requested with `limit=24`.
3. `collections/bookmarks/all`: exactly account 1's bookmarked posts in order ([author name, @handle, text, date] per
   post), the author links their OF profile (`https://onlyfans.com/<handle>`, target `_blank`), "No bookmarks yet" hidden, the avatar-less author with no picture; the request carries
   `limit=20`; the borrowed post row is one same-origin GET of `/of-mirror/pages/profile/index.html` and no other page
   is fetched; every bookmark's More (another creator's post) is disabled with the tooltip "Not available in Inflowwww yet" and a click shows no note. On `collections`, "Create new list" opens OF's
   "Create new list" dialog (collections_writes.py checks its write).
4. `statements/earnings`: exactly account 1's transactions in order ([date, time, amount, fee, net, description,
   status tips] per row: money with two decimals, an absent fee or net empty, the fan link as text, the done row
   "Complete", the pending row "Earning will become available in 5 days", the refunded row no status tip), no example
   row, the empty row hidden; OF's pages of 10: two requests, `limit=10` with `offset=0` and `offset=10`.
5. `statements/payouts` and `statements/referrals`: exactly account 1's payout requests in order ([date, time, invoice,
   amount, status class, status text, status icon] per row, OF's fields `invoiceId`, `state`, `rejectReason`: approved
   "Payout has been processed", rejected with its "Reason:" line the payout's `rejectReason` or no line, pending OF's
   `pending` span with only `#icon-loading`); Referrals hides "This list is
   empty" and borrows its row by one same-origin GET of `/of-mirror/pages/statements/payouts.html`, Payouts fetches no
   page; "Request withdrawal" stays disabled (the mocked balances are empty); one request each, exactly `limit=20`.
6. The six queue pages (browser time zone Europe/Ljubljana, the clock fixed at 2026-10-12 12:00): exactly the
   synthetic items by day, soonest first ([day, [[colour mark, time, text] per item]] per section), each mark in OF's
   colour, "Media" for a media-only item, a stream its description, the out-of-month message dropped; the Messages tab
   only the messages, the Streams tab (Messages and Streams selected) the messages and the stream; the month pages'
   block right under the calendar and the right column listing Oct 12's items; the list view's and saved-for-later
   pages' empty states hidden. `/schedules` carries `publish_date=2026-10-01`, `publish_date_end=2026-10-31`, a
   `time_zone` and `limit=50`, the other two routes `limit=50`; each page requests only its own route; the month and
   saved-for-later pages borrow the agenda block by one same-origin GET of `/of-mirror/pages/queue/state-list-view.html`.
7. `notifications`, `notifications/subscribed`, `notifications/commented` and `notifications/mentioned`: exactly
   account 1's notifications of the tab's type, in order ([name, @handle, text, date, unread, badge icon] per row:
   replace pairs applied, the unread mark only on unread ones, the follow and price badges only on subscriptions and
   tips); every fan avatar through `/img?` and loaded, the avatar-less fan with none; each request carries exactly
   `limit=20` and the tab's `type` (`subscribed`, `commented`, `mentioned`; none on All); a tab OF captured empty
   (Comments, Mentions) hides "No notifications currently!" while rows show. `notifications/tip` keeps its 17 example
   rows and requests no notifications (its `type` value is unsettled; ticket 31).
8. Creator switch (top bar switcher, no reload) on `profile` and on `notifications`: account 2 shows only account 2's
   rows and every relay call after the switch carries `X-Account-Id: 2`.
9. (Retired) No All-models pass: OF Manager has no All scope; a saved "all" shows the first live creator (owner 2026-11-20, origin/main 77e5df419).
10. No console errors.

It prints one `{"check","want","got"}` line per check and exits 1 on a failure (screenshots
`/tmp/of-mirror-shots/inapp-feeds-*.png`: one per page, its More or "Create new list" click, the Creator switch). The mocks prove the mapping, not the Relay's shape: the field names the spec marks as guessed
(notification `isRead`; bookmark `author`; saved-for-later `text`, `mediaCount`)
render empty if wrong, never as examples:

    python3 -I scripts/of-mirror-check/feeds.py

queue_menu.py checks the queue rows' More menu (`app/lib/ofMirrorQueue.ts`) with the same login mocks, scope `model:1` and
synthetic wrapped `/schedules` items (answered by their `publish_date` span) and the clock fixed at 2026-10-12 12:00 on
`queue/state-list-view`: the post and message menus' entries, the right column's day, Edit post disabled with "Not
available in Inflowwww yet", Post now's exact `PUT /api/of/v2/schedules/<schedule id>/publish` (and the queue
refetched), Delete post with the confirm dismissed sending nothing and Delete message with it accepted sending exactly
`DELETE /api/of/v2/messages/queue/<message id>`; then on `queue` the month arrows (November asked for by its
`publish_date` span and shown, back greyed out on today's month), a day click (the right column's day and its items)
and the type tabs, all in place and sending nothing (screenshots `inapp-queue-menu.png`, `inapp-queue-november.png`):

    python3 -I scripts/of-mirror-check/queue_menu.py

dead.py is the Phase 6 sign-off: no Silent control (`app/lib/ofMirrorWrites.ts` `bindWrites`' click fallback and change
path). Pages: every page of `new-post`, `home`, `streaming`, `profile`, `queue`, `collections`, `notifications`, `statements`, `statistics`, `messages`, `vault` and `bank`, and
`settings/subscription` with its tabs, modals and states, read from `app/lib/of-mirror-pages.ts` (arguments: only the
pages named, or under a named prefix, e.g. `queue` or `new-post/state-vault`); `sessionStorage` is cleared before each
page. Mocks: the login as in writes.py, `GET /api/of/v2/users/me` (synthetic), `GET /posts/tagged-friend-users` and
`GET /vault/media` (one synthetic "Alpha One" row each, so the Co-tag rows and vault tiles exist), `GET /img` (a 1x1 PNG
the script builds), a v2 Relay for Statistics (`V2`, below) and `[]` for every other `GET /api/**`; every `GET /api/**`
is recorded (path, query, `X-Account-Id`); every non-GET `/api/**` is recorded (method, path, `X-Account-Id`, body) and
answered 200 `{}`; any request to a host other than localhost is aborted and fails the check.
Controls: the frame's visible, enabled `button`, `[role=button]` and `input[type=checkbox]` (not inside `.video-js`; a
hidden checkbox through its visible `label`), clicked one by one with the mouse at their centre; a control under another
layer or gone by its turn is listed as skipped. Before each click `#oi-note` is removed, then for 1s the first outcome
is taken: a Relay write, a file chooser, a top-URL change, a fresh `#oi-note`, or (a `[data-oi-wired]` control) a change
to its own markup, checked state, ancestors' classes or the size of its dialog, poll panel or form; after a navigation or a write the page is loaded again.
Failures, Single Creator (scope `model:1`):

1. Silent control: an unmarked control gives neither the Read-only note ("Read-only in Inflowwww for now") nor a
   navigation to a localhost `/of-manager/` URL.
2. A control in `a[href]` (a link, a State page opener or backdrop) that neither navigates to a localhost
   `/of-manager/` URL nor stays inert (href `#` or the page itself), or shows a note.
3. A `[data-oi-wired]` control that shows the Read-only note, or gives no allow-listed write, navigation, file
   chooser, markup change or other note; or one whose centre is not its own but a State page's backdrop with no dialog,
   menu or focused field open over it (`a.of-state-backdrop` outside `.modal`, no `.of-state-menu` or `.m-focused`): the
   click would go back instead (Home's poll page once took Post's click to Home, so nothing posted). Also an open
   State menu item (`.of-state-menu`, one the menu shows: an item its scroll box clips is a wheel away) whose centre is
   that backdrop: My profile's More menu lay under it, so Statistics and Copy link went back to the profile. Pages whose
   URL redirects (`REDIRECTS` in `app/lib/of-mirror-route.ts`: Following's Users pages) are not swept.
4. A Relay write from an unmarked control, or any write off the allow-list (`POST /api/of/v2/posts`, `/upload`,
   `/stories/upload`, `/campaigns`, `/trials`, `/promotions`, `/streams`); exact bodies stay with each Phase's own check.
5. A measured Wired control (plan Ground truth 5) without `data-oi-wired` on the page that binds it: Post
   (`button[at-attr='submit_post']`, every new-post and home page), "Add media" (every new-post page, `home`), "Add to story"
   (`.b-story-item.m-story-item-own`, home and new-post), the vault search and tiles (`new-post/state-vault`,
   `home/state-vault`), the tag rows (`new-post/state-tag-people`, `home/state-tag-people`), Next
   (`new-post/state-schedule`, `home/state-schedule`), the stream schedule form's SCHEDULE
   (`streaming/dashboard/create`) and Create Link (`settings/subscription/tracking-links/modal-1`).
6. Any console error.

No All-Creators pass: OF Manager has no All creators (owner 2026-11-20). A saved "all" scope shows one creator, the
first with a live session (`OneCreator` in `app/components/of-manager/OfManagerChrome.tsx`), unsaved; phase_check.py's
`one_creator` checks it (run once, from golive.py; see content_writes.py below). `DISABLED` (submits with no Known body) is empty. New post's Record video and Record voice
(the not-supported popup) and its right column search box are marked. `dead.py settings` sweeps every settings page.

Where the rows live (ticket 133): dead.py is the engine only. Each ticket's rows and their mocks live in an area module
beside it, `dead_<area>.py` (`dead_statistics.py`, `dead_home.py`, `dead_messages.py`, `dead_settings.py`,
`dead_notifications.py`, `dead_collections.py`, `dead_content.py`, `dead_golive.py`), which exports any of `PHASE1`, `READS`, `SOURCES`, `V2`, `MARKED`,
`ALLOWED`, `ALLOWED_RE`, `HANDOFF`, `DISABLED` and `SWEPT` (pages that must stay in the sweep), and takes shared helpers (`fx`, `rev`, `SNAP`, `TIPS`, ...) from
`dead_lib.py`, never from `dead` (it runs as `__main__`). dead.py merges them from one explicit `MODULES` tuple, never
a glob, in that order (the rows run in it); a new area is one more module, listed there. A mock path (`SOURCES` and `V2`
together) already present raises at load with the path and both module names. `dead.py --list-rows` prints every
`PHASE1` and `READS` row, the mocks and tables, and the counts, with no browser: diff it before and after a move.

Phase 1 (`docs/spec/ofm-not-yet/phase-01-read-only-gaps.md`, Seam A; each Phase 1 ticket adds its own rows):

- `V2`: the probe `GET /api/of/v2/streaks/top` answers an object (`isV2` in `app/lib/ofMirrorStats.ts`), so the Statistics
  binders ask their phase-2 reads, and each source a Phase 1 tab gates on answers in its real shape from the Statistics
  vitest fixtures (`app/lib/__fixtures__/of/statistics-*.json`): the earnings chart keyed by series, referrals as `{list}`
  per kind (`onlyPerformers`), top stories, streams and subscribers, profile-visitor stats, message stats and their chart
  per kind. A param's other tab answers other rows than its default (another fixture, or the same rows reversed; Top fans:
  `statistics-subs-top-tips.json`, synthetic rows in `/subscribers/top`'s shape), so a dropped param reads the default
  rows. The run's first two check lines test the mock itself; the next two fail a `PHASE1`/`READS` row whose page the
  sweep never opens (a mistyped page) and a `READS` row without `shows`.
- `PHASE1` (Single Creator): `(page, control, status)`, the control `css:<selector>` or the sweep's label (a trailing space:
  a prefix, `"From "`). `pending`: the control is found on its page (Not-yet title or not); `proven`: also
  `data-oi-wired` and no Not-yet title. A row turns `proven` in the change that commits its capture record with a live
  pass (D1). `not-yet` (ticket 16): found, every match still with the Not-yet title (a lost title fails "lost the
  Not-yet title"). A row whose control is missing fails either way.
- `READS` (Single Creator, after the page's sweep): per row, a fresh load, then its `steps`, each `(verb, control[,
  text])` on the control's first match, which the check un-greys itself (no app-side switch), each followed by 1.5s:
  `click`, `fill` (typed, with input events), `set` (the value put in place with no event: text typed before pressing
  Search), `press` (a key on it). Within 5s more it needs every GET of `get`, `[(path, {param: value})]`, made during
  the last step (no `get`: requests unchecked), then the settled snapshot (`SNAP(rows, chart)`: the first visible row,
  every row's cells joined by ` | `, and the chart's visible texts; settled = the same over `SETTLE` polls in a row,
  not the first change) holding every `shows` (required: what only the filtered answer renders) and none of `hides`
  (optional: what only the default answer renders), and no Relay write. A check line names its row by
  page and steps.
- Shown once, when the tracer row (Top fans "Tips") was written, all in one run of `dead.py statistics/fans/top-fans`
  and then reverted: with `by` deleted from `listRoute`'s `subsTop`, READS fails (`get`, `shows` and `hides` false); a
  `proven` row for "More" (still Not-yet) fails "not Wired: 2 unmarked, 2 with the Not-yet title"; a `css:` row for a
  control that does not exist fails "not found"; a row on the page `statistics/fans/top-fan` fails the up-front page
  check.
- ticket 14 (Statistics › Engagement: Messages' Mass/Direct tabs and its search, Stories' and Streaming's `by` tabs):
  a default tab's row (Mass messages, Stories Tips, Streaming Purchases) clicks another tab first and checks only what
  settles. `V2` answers the stories and streams charts per `by` (`rekey`: the fixture's series under another key and
  total), `/stories/top?by=views` with `statistics-stories-top-views.json` (synthetic, `/stories/top`'s shape, another
  first card) and likes/comments with it reversed, `messages/group?query=message 3` with only the matching rows
  (`hits`), and `query=me` with no rows (a 2-character query must never be sent). The search rows, typed in the field
  and put there then submitted with the button, show only the match from 3 characters, every row under 3, and every
  row again when cleared. A missing GET now fails the row instead of raising (the last snapshot is read). Shown once
  each, a run of `dead.py statistics/engagement` (or `.../messages`), then reverted, every run exit 1:
  - `type` dropped from `messagesChart` and `by` from `storiesTop`: Direct messages, Viewers, Likes and Comments
    fail (`get` and `settled` false; `shows` false where the first card or chart differs).
  - `query` dropped from `listRoute`'s `massMessages`: both "message 3" rows (field, and set then button) fail (`get`,
    `settled` and `hides` false).
  - both 3-character gates lowered to 2 (`listRoute`'s `massMessages`, `bindSearch`): both "me" rows fail (`shows`
    false).
- ticket 16 (Messages: Find on the chat header menu's State page, the sort dropdown's Select, the folders dialog's
  Sort): `READS` rows also take `query` (the page opened with it: a State page's `chat=`, the list's `select=1`)
  and `"get": None` (no `GET /api/**` at all during the last step: a client-side control). Its three `PHASE1` rows are `not-yet`: found, every match with the
  Not-yet title (AC6, D1); a READS step on a `not-yet` control checks the same on the row's own load (Find is bound
  only with `?chat=`, which the sweep's load lacks), and the Live pass flips the one status to `proven`. A step whose action fails (a control
  still greyed) fails its row instead of raising. The snapshot reads whichever Mirror page frame is loaded now (`frame_now`, for the steps too: Select opens
  the list). The un-greying also lifts a Not-yet menu item's `aria-disabled` and `v-list-item--disabled`. Shared
  `SOURCES` rows: chat 2001's two "needle" messages and four synthetic chat folders; `V2` answers the search for
  `needle` with only the second message. `V2` answers `/chats` for `list_id=916` only with two synthetic chats (their partners
  in shared `/users/list`), which the two pick rows open (`folder=916&select=1`); no folder the sweep opens has that id,
  so no swept page draws them. On the bare list every row's Clear messages is Silent (its `confirm()` is
  dismissed and the button is unmarked: a gap of the Clear wiring, issue 128).
  Find reads on the header menu only (the other dialog pages' backdrop covers the chat header: the ticket's
  carve-out). Select's rows want no GET: the dropdown's Select (its snapshot throws until the bar is drawn), the bar's
  Cancel and Delete, a row's pick (its box ticked, the URL unchanged: no chat opened) and Select all after it (every
  box, the button now Deselect). Sort's four rows each pick one option (Recent, Name, People each differ from the
  default Custom order, and Custom from Name ascending). `PATCH /lists/{id}/pin-chat` (the dialog's boxes, an existing
  Wired write) is on `ALLOWED_RE`: with the folders in `SOURCES` the sweep's box clicks send it. Open gap: `outcome()`
  judges a click's writes only when a write is its first outcome; a box's change is seen first, so these writes are
  not judged against the allow-list at all (issue 129).
  Shown once, in one run of `dead.py messages/chat/state-header-menu messages/state-filter-dropdown messages/index
  messages/state-folders`, then reverted, exit 1: with the State pages dropped from `useThreadFind`'s pages, Find fails
  (its fill step: the find input "not found"); with select mode never entered, the dropdown's Select
  fails (`settled` and `shows` false) and both select-bar rows fail "not found"; with `sortFolders`' Name branch
  removed, the Name row fails (`shows` and `hides` false).
  Round 2, the same way, each exit 1: with the Not-yet title stripped by the binders (Select, Sort; `dead.py
  messages/state-filter-dropdown messages/state-folders`) both `PHASE1` rows fail "lost the Not-yet title: 1 of 1
  without it" and Select's READS row fails its click (the item still `aria-disabled`); stripped from Find (`dead.py
  messages/chat/state-header-menu`), Find's READS row fails "lost the Not-yet title".
- ticket 15 (Statistics › Fans' Subscriptions and Top fans tabs, Profile visitors' chips, Referrals' kinds, Overview ›
  Earnings's category radio): `PHASE1` rows by selector (their labels repeat on the page), the radio by its sweep label
  `[b-input-radio]`. `V2` answers Top fans' Subscriptions/Posts/Streams ranked by their own measure (`top_by`: Fan U
  leads with $3.00 of it), Subscriptions' New with its own rows (Fan D alone) and, with Profile visitors' Users, a
  chart of their own (`spot`: one non-zero day), and Referred users (`onlyPerformers=0`) with the creators reversed.
  `TIPS(rows, chart, canvas, checked)` is `SNAP`'s snapshot plus the chart's tooltips, read by moving the mouse across
  the canvas (each tooltip's date and `<series> <value>` lines), and the `name`s of the inputs matching `checked` (the
  radio's snapshot: the checked category radios). Referrals' rows have no `get` (both kinds are read on load): they
  assert the shown table's first row. The radio's rows use ticket 16's `get: None` (no GET `/api/**` from the last
  step on; `hit()` is taken again after the settle polls, so the settle window counts: a redraw in place). Dates stay
  out of `shows` (the browser's time zone is not
  pinned). Fans "More" has no row: OF's Fans header menu (statistics-fans.js `m-extra-dropdown`) holds only "Add to
  list" (a write) and the Top Fan card's More is the user-card menu, so both moved to Phase 2 story 51. Shown once
  each, a run of `dead.py <page>`, then reverted, every run exit 1:
  - `by` dropped from `listRoute`'s `subsTop`: Tips, Subscriptions, Messages, Posts and Streams fail (`settled`, `get`, `shows` and `hides` false).
  - the radio's pick added to `statsRoute`'s `earningsChart` (`row`, so a pick reads again): Subscriptions fails (`get`
    and `settled` false).
  - `referralsPage` showing `referredCreators` for both kinds: Referred users fails (`shows` and `hides` false).
- ticket 17 (Notifications, every tab: Search users, the aside's Search users or posts, the Scheduled events widget's
  new-event button): its rows live in `dead_notifications.py` (in `MODULES`),
  and add the step `("back", None)` (the top frame's history back) to the engine. Its 30 `PHASE1` rows are `not-yet` by selector (D1). `V2` answers
  `/users/notifications` with fan 9102's row and, for `related_user=9101`, fan 9101's only (a dropped param shows no
  row: relatedOnly drops 9102's); `SOURCES` answers Tags' `/release-forms/mentions` with both fans' (no param there);
  the users and posts searches answer only `synth`. Rows: Search users on each type tab (button, the form's field
  `synth`, fan 9101 picked: `get` the tab's type plus `related_user=9101`, the URL, only 9101's row, the form showing
  `9101`), on Tags (`get: None`: filtered as read), then Back (`notifications/tip`: the bare URL, 9102's row, no form);
  the aside's `synth` (`get` both searches, the Users and Posts lists); and the new-event click (the top URL
  `/of-manager/home/state-schedule`, no write). Page-shared controls read on `index` only (same markup and
  binder on every tab). Shown once each, a run of `dead.py <pages>` against `next dev -p 3117`, then reverted, every
  run exit 1:
  - `notificationsRoute` sending `related_user` on Tags only (`notifications/tip notifications/tags`): tip's Search
    users fails (`get`, `settled` and `shows` false); Tags' fails (`get` false: a GET in its last step, `settled` false).
  - the binder's navigation as `router.replace`, `bindFeedSearch` not called, the new-event click inert
    (`notifications/index notifications/tip`): Back fails (`shows` and `hides` false); the aside fails (`get`,
    `settled` and `shows` false); new-event fails (`shows` false).
  - the new-event button's title stripped (`notifications/index`): `PHASE1` fails "lost the Not-yet title: 1 of 1
    without it" and new-event's READS rows fail the same.
- ticket 18 (Collections: the Posts tab on index and Fans, Fans' Expired tab, and Search users on index and a list):
  its rows live in `dead_collections.py` (in `MODULES`, D31), using ticket 17's
  `("back", None)`. Posts and Expired are `not-yet` (D1); Search users (already wired) is
  `pending`. `SOURCES` holds three synthetic lists (7000 empty, first, so a bare page opens it and the sweep draws no
  member cards; 7001 Alpha; 7002 Bravo) and one post each for 7001, 7002 and `fans`; `V2` answers list 7001's members
  per `query` (`bravo`: fan 2002 alone) and `/subscribers` per `type` (active: 2001, 2002; expired: 2003). Shown once, a run of `dead.py collections`, then
  reverted, exit 1: with `subscribersPath` dropping the type, the Expired row and Expired > Back fail.
- ticket 132 (Text Color on the format-text State pages flaked under load): not the probe. The composer toolbar's
  ResizeObserver (`bindActionsOverflow`'s `layout`) closed any open menu, so a late layout pass right after the click
  shut Text Color's just-opened list and its markup read unchanged. `layout` now closes More's own menu only (vitest:
  "a resize closes More's own menu only"); dead.py is unchanged. Shown once, a run of `dead.py home/state-format-text
  new-post/state-format-text`, then reverted, exit 1: with Text Color's binder not opening its list, `#5 Text Color`
  fails "no Silent control" on both pages.

It prints one `{"check","want","got"}` line per check, one `{scope, page, controls, links, wired, readonly}` line per
page and one for the pass, and exits 1 on a failure. Screenshots: one per page with a note showing,
`/tmp/of-mirror-shots/inapp-dead-<page, / as __>.png`:

    python3 -I scripts/of-mirror-check/dead.py
    python3 -I scripts/of-mirror-check/dead.py queue new-post/state-vault   # only these pages, or under these prefixes

`--sweep-out <file>` regenerates the Not-yet sweep (`docs/of-manager/not-yet-sweep-2026-11-20.json`'s shape plus `ro`) at
any commit: the same run, with `release-forms` added to the sections (only in this mode; the default run's pages, checks
and output are unchanged), also writes `[[page, {"ny", "dis", "ro"}]]` for every page the Single-Creator pass swept, or
only the pages the arguments name. `ny`: the visible controls with the Not-yet title; `dis`: the visible disabled ones
without it (Empty-form disables); each label once, read as the page opens. `ro`: one entry per control that gave the
Read-only note, so its length is the page's printed `readonly` count. A label is the control's aria-label, text or
placeholder (60 characters), with a date "Mon D, YYYY" read as `{date}`, else `[its first two classes]`, else `[its tag]`;
OF's own left nav (`.l-sidebar`) is left out. A page that ends with no frame (NO IFRAME) is opened once more before it
counts, in this mode only. Known skip: Release forms' row More (the Sort menu, opened earlier in the sweep, covers it;
the close-in-place Escape only closes a `.modal.show[data-oi-data]` dialog, not a State menu).
`sweep_diff.py` compares two sweep files and prints, per section, the `ny` (and, where both files have it, `ro`) controls
removed, added and kept, one JSON line per section, with dates read as `{date}` on both sides; `--expect-ny-unchanged` fails on a page of the old file missing from
the new one or with different `ny`, `--expect-ro-counts <log>` on a `ro` length that is not the `readonly` count dead.py
printed in the same run's Single-Creator pass, or a total `ro` of 0. Table tests: `test_sweep_diff.py` (pytest):

    PORT=3091 python3 -I scripts/of-mirror-check/dead.py --sweep-out /tmp/sweep.json | tee /tmp/dead.log
    PORT=3091 python3 -I scripts/of-mirror-check/dead.py --sweep-out /tmp/sweep.json queue   # only a Phase's own pages
    python3 -I scripts/of-mirror-check/sweep_diff.py --expect-ny-unchanged --expect-ro-counts /tmp/dead.log \
        docs/of-manager/not-yet-sweep-2026-11-20.json /tmp/sweep.json
    ./venv/bin/python -m pytest -q scripts/of-mirror-check/test_sweep_diff.py

dead.py's Phase hooks: each Phase's control tickets add their writes to `ALLOWED` (exact) or `ALLOWED_RE` ((method,
full-match regex), for an id in the path; Stop promotion's `/promotions/<id>/finish` is its first row), their Wired
controls to `MARKED`. The label in sweep files and in phase_check.py is one JS source,
`sweep_diff.py` `LABEL_JS`.

content_writes.py is Phase 2's Mirror check (`docs/spec/ofm-not-yet/phase-02-content-chat-writes.md`, Testing
Decisions), on the shared harness `phase_check.py` (a later Phase's check is one more such tables file). The login and
relay are mocked as in writes.py, `/admin/accounts` lists acc1 and 1 with a session, every non-GET `/api/**` and `/admin/**` request is recorded (method, path, `X-Account-Id`, JSON body) and
answered `{"success": true}` after the Phase's `AFTER` hooks changed the mocked reads (`READS`), so a write's read-back
shows what it changed; any non-localhost request fails the check. Its control list is the Phase 2 proof list
(`scripts/of-live-proof/proofs/phase2.py` `PROOFS`: page, control as the Not-yet sweep labels it): check 1 reads
runtime state (D18): each proof has one capture record, found as `phase2.py --check-sweep` finds it (label and page,
`proof_list.py`), its control is Wired (data-oi-wired) and, with that record's Live-proof pass (`kind: live, verdict:
pass`), has no "Not available in Inflowwww yet" title, else still has it (D1). The switch probe GET
`/api/of/ofm-writes` answers on (OFM_NEW_WRITES_ENABLED, as of-live-proof runs the Relay; dead.py's mock too); a proof
tagged `ofm_new_writes` (Record video and Record voice, the vault folder page's More) is also checked in a switch-off
pass (the probe answered 404): found, not Wired, its Not-yet title kept, nothing sent; one with a `VIEWS` page (ticket
33's own-bubble extras) must not be drawn there, once that page's anchor (phase_check `ANCHORS`, an own bubble on
messages/chat; `anchors=` per proof) is drawn, so a page that drew no data never passes as absent. Its tables, filled by the Phase 2
control tickets: `REQUESTS`: the steps send exactly the proof's capture record's request with `X-Account-Id: 1`, then
the read-back; `RED_NOTES`: a mocked 502 on the write shows the red `#oi-note` and the page keeps its last saved state;
no console errors. With empty tables it loads home/index. No All-Creators pass: OF Manager has no All creators;
phase_check's `one_creator` (run once, from golive.py below) checks a saved "all" scope: with a saved `chatterly:scope` of `all` and `/admin/accounts` listing acc0 (dead session) before acc1 and 1,
typing on home/index (not a stand-in page) and clicking Post sends exactly `POST /api/of/v2/posts` with
`X-Account-Id: acc1` (the first creator with a live session, `OneCreator`), and the scope stays `all` (not saved). `--plant <rows.json>` adds proofs, rows and capture records
(`{"proofs", "records", "requests", "red_notes"}`; a planted record replaces the capture file of the same name) to show a check fails; `--captures <dir>` reads the
records from another folder. Screenshots: `/tmp/of-mirror-shots/inapp-content-writes-*.png`:

    PORT=3091 python3 -I scripts/of-mirror-check/content_writes.py
    PORT=3091 python3 -I scripts/of-mirror-check/content_writes.py --plant /tmp/rows.json

Committed plants: `plants/phase2-clean.json` must print `content-writes ok`; `plants/phase2-fail.json` must exit 1 (missing control, Live pass on an unwired control, title dropped without a pass, proof without a record); `plants/phase2-anchor-missing.json` (chat 9001's messages
served empty) must exit 1 on the switch-off pass's anchor checks.

golive.py is Phase 4's Mirror check (`docs/spec/ofm-not-yet/phase-04-go-live.md`, Testing Decisions; ticket 83), on
the same harness `phase_check.py`: the stream schedule form (`streaming/dashboard/create`), the dashboard
(`streaming/dashboard`) and Go live (`streaming/index`). Its control list is the Phase 4 proof list
(`scripts/of-live-proof/proofs/phase4.py` `PROOFS`), check 1 as content_writes.py's (runtime state, D18; the title
drops only with the record's Live-proof pass, D1). Its tables, filled by the Phase 4 track A control tickets:
`SCHEDULE_FORM` and `DASHBOARD` (control, click, its exact request with `X-Account-Id: 1` or zero requests),
`RED_NOTES`; `GO_LIVE` stays empty until track B's gate
ticket closes (D7). Whatever the tables hold, it loads the three pages, each showing its `LANDMARKS`
control (phase_check `pages`: Schedule, the dashboard's Schedule link, Start Live Video). Every
non-localhost request fails the check. Ticket 84's rows: the schedule form's right column search (Home's), opened
valid by the `?date=&time=` prefill, types and clicks Search, lists the mocked rows with their OF profile links and
sends nothing (no POST /streams). Phase 4's dead.py hooks (`ALLOWED`, `ALLOWED_RE`, `MARKED`, plus ticket 84's `MARKED`, `PHASE1` "not-yet" and `READS` rows for that search, Enter included) and
its `SWEPT` pages (the three Phase 4 pages, checked against the sweep's pages) live in `dead_golive.py` (in `MODULES`). Then
`one_creator` (content_writes.py above; it runs here only). Screenshots: `/tmp/of-mirror-shots/inapp-golive-*.png`:

    PORT=3091 python3 -I scripts/of-mirror-check/golive.py
    PORT=3091 python3 -I scripts/of-mirror-check/golive.py --plant scripts/of-mirror-check/plants/phase4-fail.json

Committed plants: `plants/phase4-clean.json` must print `golive ok`; `plants/phase4-fail.json` must exit 1 (missing
control in a proof and in a row's steps, a Live pass on a control that keeps the title, a parked record whose control
lost it, a request to a non-localhost host, and that request's console error). A plant's `init` marks the format button
(`[g-btn.m-with-round-hover]`) Wired, so the title check fails alone (not Add cover: its real parked record,
`streaming--add-cover.json`, would make a plant's Add cover proof find two records).

What stays Not-yet on the Phase 4 pages (ticket 90; each record parked with its reason in
`docs/of-manager/captures/streaming--*.json`): the schedule form's search box and Search button are wired (ticket 84)
but keep the title until their Live proof (ticket 91, D1); Add cover stays unwired (ticket 85 parked: OF reports
`isScheduledStreamsAllowed` false on the Proof Creator, so no cover body was captured; 86 moot with it); the format
button waits on its panel's State page (ticket 87, rides ticket 28); View stats waits on its modal's State page and a
stats read that answers 200 (ticket 88, rides 28; it answers 403 today); Go live's rows, switches, description and
Start Live Video stay track B (D7: gate open, owner stream go pending). Go live never reads
`GET /api/of/v2/users/settings/streams` (ticket 89 moot, D28). Generator edits for ticket 28:
`.scratch/ofm-not-yet/phase4-generator-edits-for-28.md`.

Phase 1's sections under the v2 mock (`docs/of-manager/not-yet-sweep-2026-11-20-phase1-v2.json`; per-label remainder
in `.scratch/ofm-not-yet/phase1-remainder.md`):

    PORT=3091 python3 -I scripts/of-mirror-check/dead.py --sweep-out /tmp/oi-p1-sweep.json \
        statistics statements notifications collections profile messages home | tee /tmp/oi-p1-dead.txt

settings_privacy.py is Phase 3's Mirror check (`docs/spec/ofm-not-yet/phase-03-settings-privacy-links.md`, Testing
Decisions), on `phase_check.py` (mocks, login, write record, the Phase 3 proof list `proofs/phase3.py` with its
`REQUESTS` and `RED_NOTES`). It adds a Single-Creator pass (no All-Creators pass: OF Manager has no All creators): `TITLES`, every Phase 3 Not-yet control
of the 2026-11-20 sweep, each found with its Not-yet title kept, or dropped with its capture record's Live-proof pass
(runtime state, D18/D1); `ROWS`, one outcome each: exactly one write (the last clicked control Wired), a hand-off URL
(requested and aborted, never loaded, nothing written), clipboard text, or a landing Mirror path plus its Relay GET
(dead.py `READS`' param match) plus at least one row. An opener step is clicked on the page it sits on and its modal
or State menu must show; a row reaching a control by its modal URL fails. `after`/`undo` check the new value on the
settled frame and on a fresh read of the stateful mock (`STATEFUL`: the write's body merged into a mocked read), then
the old value after undo. The synthetic stream key must never appear in any frame's DOM or field value, and Stream
Key shows the mask. Rows with their own `reads` run grouped, one session per distinct `reads`; the rest share the base
session. `--self-test` runs only planted rows (a missing control, a modal-URL row, a Live pass with the title kept, a
parked record with it gone, two capture records for one control, the key in the DOM and a fresh read without its hook
fail; a stateful toggle with undo, an opener, clipboard and land rows pass). Screenshots: `/tmp/of-mirror-shots/inapp-settings-privacy-*.png`:

    PORT=3091 python3 -I scripts/of-mirror-check/settings_privacy.py [--plant rows.json] [--captures dir]
    PORT=3091 python3 -I scripts/of-mirror-check/settings_privacy.py --self-test
    PORT=3091 python3 -I scripts/of-mirror-check/dead.py settings profile | tee /tmp/oi-p3-dead.txt

dead.py's Phase 3 hooks (ticket 57): rows appended to `ALLOWED`/`ALLOWED_RE` and `MARKED` in `# ticket NN`
blocks of `dead_settings.py`, and `HANDOFF` (exact hand-off URLs): a visible `a[data-oi-wired][target=_blank]` to one is swept after the page's own
controls (clicked at its first line box), and a popup to one is a Wired control's or link's outcome, recorded and
aborted; a popup anywhere else still fails as a non-localhost request. Shown once with `HANDOFF` set to Bank's
`BANK_URL` and then reverted: `dead.py bank` passes with each page's "Open banking on onlyfans.com" aborted as a
hand-off; with the hand-off route off as well, it fails "request to a non-localhost host" and "no Silent control".

Phase 3 outcome (ofm-not-yet tickets 57-76, 110; ticket 77). D1 holds throughout: every control below still carries
its Not-yet title at runtime until its capture record shows a Live-proof pass (tickets 78/79, attended), so the sweep
still lists all of them and `phase3.py --check-sweep` expects that. Built means Wired, green in settings_privacy.py
and dead.py, and its proof green in fake mode, except the tip switch: its proof (`phase3.TIP`) is parked outside PROOFS
because OF draws the switch only on a free page and the Proof Creator and FakeOF's proof account are priced (needs a
free account).

- Moved to a write (Relay route, Undo through the Relay): `settings/messaging` tip-from-free-followers switch (`PATCH
  /users/me`, proof parked, see above); `settings/notifications/email` Update frequency (`PATCH /users/settings/notifications`; the menu offers
  the stored hours and 24 until row 9's list lands, ticket 60); `settings/profile` cover/avatar upload and cover
  remove (signed upload then `PATCH /users/me`) and About's format button (`PATCH /users/me` `about`); `settings/social-media`
  Add button / remove (`PUT` / `DELETE /users/social/buttons`); `settings/links` Things I Like Create link / delete
  (`PUT` / `DELETE /users/links`); tracking links' share hint (`POST` / `DELETE /campaigns/share-access`, fake-only
  until the owner names a peer); `settings/streaming/blocked` Block a username and a row's unblock (`POST` / `DELETE
  /streams/users/{u}/block`); Block by country and Block by IP (`PUT /users/me/settings/security`, Lockout controls:
  ordered last, `--lockout`, an explicit Creator pick, pinned harmless values Tuvalu / 192.0.2.1).
- Moved to a read or a browser-only action (no write): tracking links' Sort on the base page, modal-1 and the kebab
  State page and trial links' Sort radios (OF's server-side sort); "Shared with you" on the base page and behind
  modal-1 / kebab; the openers behind the modals and kebabs (ticket 62): tracking "Create new tracking link", trial
  "Create new free trial link" and "Start promotion campaign", the last two against FakeOF's priced proof account
  (record `settings--priced-performer-openers`); Streaming's Copy link
  and Copy key (clipboard only; the key never enters the DOM, Stream Key keeps the mask; spec ASSUMPTION: the owner may
  still want the key off the clipboard, then Copy key goes back to a Read-only note); the OBS server dropdown (OF's
  local `selectedServer`, no request); Reveal password, both `support@onlyfans.com` mailto links and phone Cancel
  (ticket 110). Trial links' Create link (connector tickets 38/46) was already Wired; ticket 64 gave it a proof
  (`settings--trial-create-link`, `WIRED_PROOFS`) and no title to drop.
- Hand-offs (D11: new tab, `noopener noreferrer`, nothing through the Relay, URL in `app/lib/ofMirrorHandoffs.ts`
  only), 12 wired (ticket 58): MetaMask's download link, Streaming's "OBS", the stream chat link and the OBS widgets
  link; Sign in with Google / X and connected accounts' Connect link to OF's own measured settings pages (record
  `settings--handoff-pages`, never OF's `POST /trust`), with connected accounts' username field readonly and Wired,
  opening Connect's hand-off; Sign in with Spotify to OF's Spotify settings page, on Settings and My profile's three
  pages (×4). Parked: Spring Store's "here" (absent from OF's build, ticket 71) and Payment Cards' Add card / Add a
  payment card / Add funds (no URL, D29, ticket 110).
- Mocked proofs (D3/D12; title kept, never started live): Close all sessions (ticket 63: the app sends OF's `DELETE
  /sessions` after OF's ModalConfirm, the Relay's `_denied` backstop answers 403 before the Live guard, the red note
  shows; proof `refused_as="backstop"`) and Reset stream key (ticket 76: `DELETE /streams/obs/key?type=<server>` after
  the confirm, refused by the Live guard as `no_undo` before FakeOF; proof `refused_as="no_undo"`). Their live runs
  are owner-go tickets 81/82.
- Stays a Read-only note or Not-yet with nothing sent, and why: the Restricted / Blocked rows (ticket 65, blocked on
  ticket 22's list views; the sitting measured their OF targets as `/my/collections/user-lists/restricted|blocked`);
  the modal-3 ⋮ (ticket 75: no claimed promotion to open it, checklist rows 11/23; only the Add to list builder exists,
  tagged `inferred`); Spring Store's URL field (ticket 71: absent from OnlyFans's current build); Fully private (ticket
  60: drawn only for a non-adult performer, so not in the sweep; Live proof ticket 78); Add bundle (ticket 62
  `T62_PARKED`: disabled on the priced Proof Creator, all three bundle durations exist); the profile display of social buttons
  and Things I Like links (tickets 69/70: the captured profile page draws none); the empty-form disables (OF's own
  validation) and Welcome message Edit/Delete (`ELSEWHERE.welcome`), out of scope.

Phase 3's fake-mode acceptance (ticket 77) runs the whole proof list in batches of at most 4 over `run.sh`, Lockout
proofs last with `--lockout`, retries a proof alone once only on a `Page.goto` timeout or "no Mirror frame", then runs
`--check-records` and `--check-sweep` (a fresh sweep with `--sweep-port`, else the committed 2026-11-20 one):

    nice -n 10 ./venv/bin/python -I scripts/of-live-proof/accept.py --phase 3 --sweep-port 3091

What writes, what shows data and what is read-only, page by page (from `app/lib/ofMirrorWrites.ts` `WRITABLE` and `SUBMITS`,
`app/lib/ofMirrorSubscription.ts`, `app/lib/ofMirrorPost.ts`, `app/lib/ofMirrorData.ts` `DATA_PAGES`, `app/lib/ofMirrorFeeds.ts`,
`app/lib/ofMirrorSettings.ts` `SETTINGS_MAP`, and the plan's Ground truth table). OF Manager has no All scope; a saved "all"
shows the first live creator (owner 2026-11-20, origin/main 77e5df419). Every control not listed as a write, and not a link, a State page opener or the video player, is
read-only: a click on a button or `[role=button]` shows "Read-only in Inflowwww for now", and a
changed checkbox or field shows it too (a checkbox flips back; new-post's panel fields are also reset).

- `new-post` and `new-post/state-*`. Writes: Post (`POST /api/of/v2/posts` `{text, media_files, price: 0}` plus
  `posted_at` and `tagged_users` when set); "Add media" on `new-post` (`POST /api/of/v2/upload`); "Add to story" (`POST
  /api/of/v2/stories/upload`); `state-schedule`'s Next (stores `posted_at`), `state-tag-people`'s rows (Co-tags) and
  `state-vault`'s tiles and search (vault ids into `media_files`), all sent with Post. Data: `state-vault` the vault
  media (`GET /vault/media?limit=24`), `state-tag-people` the taggable creators (`GET
  /posts/tagged-friend-users?limit=50&offset=0`). Read-only: Save for Later; the labels rows (`state-labels`); the
  poll, quiz, expiration, target and format-text panels' fields and non-link buttons; Record voice, Record video; the
  State pages' copies of "Add media"; the tag dialog's example rows (list loading or failed); the vault dialog's folder
  rows, type tabs, sort and Retry; the strip's "Go live", "Send message", "Start profile promotion" and "Create new
  trial link".
- `home` and `home/state-*`. Writes: "Add to story", the composer's Post and "Add media" (New post's, in place) and its
  dialogs `home/state-vault`, `home/state-tag-people`, `home/state-schedule` (as on New post). Data: the feed, the
  promotions and scheduled events, the strip in OF's order (live streams from `/streams/feed`, the Creator's own stories
  from `/users/{id}/stories`, the creators with new stories, the promotion tile, the creators whose stories are all
  watched, the scheduled streams), the vault dialog's media. Links: "Start profile promotion" (`home/state-promotion`: the promotion campaign dialog over Home, as New post's; Start
  campaign writes `POST /api/of/v2/promotions`, then it and Cancel go back to Home), the Creator's own scheduled stream
  (the queue). Disabled with a tooltip: Add poll,
  Add quiz, Expiration period, Your target, Format Text, Record video and voice. Read-only: live stream tiles and other
  creators' scheduled ones, every other button.
- `profile`, `profile/state-more-menu`, `profile/media`. Writes: the own posts' like, comments and More menu (as Home's).
  Data: `profile` and its State pages the wall posts (`GET /users/<id>/posts?limit=20&format=infinite`, the next page
  by its `tailMarker` as `before_publish_time`), `profile/media` the photo and video posts, all three the counts, the
  bio's location, website and wishlist rows and the label tabs (`/users/me`, `/labels`), the Recent strip, the highlights
  (`/users/<id>/stories/highlights`) and the promotions. Wired in place: "Story archive" (`GET /stories/archive`), Copy
  link to profile, More info (only while the bio is over OF's 85px), Spotify's title, the media tabs, the status menu
  (Available / Invisible: `PATCH /users/me` `{isVisibleOnline}`), the highlight tiles (each plays its stories in the
  viewer, `GET /stories/highlights/<id>`; with no single Creator, its cover). Links: Photos, Videos, Fans, "Go live",
  the More menu's Statistics and QR code (Settings' QR code page). Disabled with the tooltip: "Create highlight" (no
  highlight write), the label tabs but All, the wall's search, compact view and sort, the sidebar search (Sign in with
  Spotify is a hand-off, ticket 58), each post's Labels (no Relay route labels an existing post), Post statistics and bookmark (no Relay
  post-bookmark route); another creator's post's Send Tip (no Relay tip route, and it spends money). The footer's
  Privacy, Cookie Notice and Terms of Service stay `#` (no OF host link in the pages).
- `queue/*`. Writes: none. Data: `queue` and `queue/state-list-view` (`/schedules`), `queue/state-tab-messages`
  (`/messages/queue`), `queue/saved-for-later-posts` and `-messages` (`/schedules/later/post`, `/chat`);
  `queue/state-tab-streams` keeps its capture. Read-only: item and row actions, every other button.
- `collections/*`. Writes (`app/lib/ofMirrorCollections.ts`, collections_writes.py): on `collections` and
  `collections/user-lists/*`, "Create new list" (OF's dialog, `POST /lists`); on `collections/post-labels/*` the "+"
  ("Create new label", `POST /labels`); the list's More (Rename `PATCH /lists/<id>`, Add users `POST /lists/users`,
  Clear `DELETE /lists/<id>/users`, Delete `DELETE /lists/<id>`); a user card's Lists (`POST` / `DELETE
  /lists/<id>/users/<uid>`). Data: `collections` and `collections/user-lists/list` the user lists (`/lists`) and the
  open (else the first) list's users (`/lists/<id>/users`), Fans (`subscribers/active`) the active subscribers
  (`/subscribers?type=active`), the Following pages (`subscriptions` and its chips, captured with no card) redirect to
  the Following list's page (`list?list=following`, `/lists/following/users`; `app/lib/of-mirror-route.ts`
  REDIRECTS); a list page's Send message opens New message with that list ticked (`messages/send?to=<list>`;
  `sendlist-following` redirects there, its `list-users` and `list-exclude` to New message's tabs),
  `collections/post-labels/archived` the labels (`/labels`; a label's posts: OF's "No posts yet"),
  `collections/bookmarks/all` the bookmarked posts. No example list, card or post is kept. Disabled with the tooltip:
  the bookmarks "+", Search, Sort, Filter, Pin to home, the card tools but Lists, a More or Lists with nothing to do.
  Read-only: a bookmark's More.
- `notifications/*`. Writes: none. Data: `notifications`, `notifications/subscribed`, `notifications/commented` and
  `notifications/mentioned` (`/users/notifications`, the tab's `type`); `notifications/tip` and the other tabs keep
  their examples. Read-only: the tab filters' buttons and every other button.
- `statements/*`. Writes: the payout frequency menu (`PATCH /payouts/requests {"withdrawalPeriod": …}`, the old one
  back unless the reply has `success`) and Request withdrawal (manual payouts only, enabled by OF's rule: OF's Manual
  payouts dialog, then `POST /payouts/requests {"withdrawal_amount": …}`, OF's answer or error in its alert). Data:
  `statements/earnings` (`/payouts/transactions?limit=10&offset=…`), `statements/payouts` (`/payouts/requests`),
  `statements/referrals` (`/payouts/requests/referral`), the balances (`/payouts/balances`) and Earning Statistics
  (`/payouts/stats`: All time and a row per month; one row open at a time, a row's head opening it to its chart,
  date range and categories, a category row picking the chart's line). Wired: the balance box
  header (collapse) and Copy link. The sidebar's Chargebacks is Statistics' (`statistics/statements/disputes`, where
  OF redirects `/my/stats/disputes`). Disabled with the tooltip: the payout account menu, Earning Statistics' date
  range and the Billing Support form. Read-only: none.
- `statistics/*` (`app/lib/ofMirrorStats.ts`). Statistics, and each top tab, lands where OF lands it (the generator
  reads OF's redirects from the captures): Statistics and its Statements tab on Statements › Earnings, Engagement on
  Posts, Fans on Subscriptions. Writes: the sidebar's Request withdrawal (Statements', above). Data, for the period picked in OF's period menu
  (wired: data-oi-period): the figures (`/users/me/stats/overview?by=…&start=…&end=…`, `/payouts/stats`), Engagement ›
  Messages' table (`/users/me/stats/messages/group`), Reach › Profile visitors' tables and chart
  (`/users/me/profile/stats`), the Chargebacks ratio, Payout Requests, Referrals and Statistics › Statements ›
  Earnings' table (`/payouts/transactions`); no captured figure is kept (" — " until the relay answers). Disabled with
  the tooltip: the menu's Custom, the payout frequency, the earnings radios, Search messages, Unsend, and every section
  with no relay route (OF's empty state titled "Not available in Inflowwww yet"). Read-only: none.
- `bank/*`. Writes: none, ever (we never write bank details). Data: none (the relay reads no bank account or payout
  system): "Your bank account data" and the selected payout system say they are managed on OnlyFans, Select payout
  system marks no system, Payment Cards' wallet credits show " — " and its latest transactions "Not available in
  Inflowwww yet"; the "account has been approved" box and the "add a new card" alert go. Disabled with the
  tooltip: every CONTINUE, radio, field, Send, Add a payment card, the wallet switch and the `#` links. Read-only: none.
- `settings/subscription*`. Writes: `tracking-links/modal-1`'s Create Link, or Enter in its name (`POST
  /api/of/v2/campaigns` `{name}`); the price Save (`PATCH /api/of/v2/users/me` `{subscribePrice}`); each row's
  Delete or Remove (`DELETE /api/of/v2/{promotions,subscriptions/bundles,campaigns,trials}/{id}`) and Copy link.
  Data: the promotions, bundles, tracking links and free trial links (`app/lib/ofMirrorSubscription.ts`; none: OF's
  "No results :("). Also writing (ofMirrorOffers): `promotion-campaign/modal-1`'s "Start campaign" (`POST /promotions`),
  `promotion-campaign/modal-2`'s "Save" (`POST /subscriptions/bundles`), `trial-links/modal-1`'s "Create link" (`POST
  /trials`), a running promotion's "Stop promotion" (`POST /promotions/{id}/finish`) and a free trial link's share
  (`POST /trials/share-access`); the free trial links' Sort and "Shared with you" read. Disabled: every other control.
- Elsewhere: `settings/profile`'s Save (`PATCH /api/of/v2/users/me`,
  changed fields of name, bio, location, website, wishlist) and `settings/messaging`'s welcome message switch (`PATCH
  /api/of/v2/users/me/reply-on-subscribe`) write (writes.py); `streaming/dashboard/create`'s SCHEDULE writes (`POST
  /api/of/v2/streams`); `messages`, `messages/chat`, `vault`, `vault/list` show Data parts (data.py); the settings pages
  in `SETTINGS_MAP` show the Creator's values (settings_values.py); display's "Dark mode" switches our theme (dark.py);
  the settings toggles mapped in `ofMirrorSettingsWrites.ts` save; `settings/qrcode`'s two switches and Download
  (`ofMirrorQr.ts`) and `settings/display/language`'s radios (`ofMirrorLanguage.ts`) work in the browser only, as OF's;
  `settings/streaming/blocked` reads its list (`GET /streams/users/blocked`); every other settings control is disabled
  with the tooltip "Not available in Inflowwww yet" (`dead.py settings` sweeps them).

Limits by design (not covered by the checks):

- With a single model selected, the messages list, the chat page (header, thread, its list), the vault's folder
  list and the collections user lists (and a list's user cards) show that model's rows from the relay
  (`app/lib/ofMirrorData.ts`): the example row nodes are hidden and a template row is cloned per real row. A chat
  shows text only (a media message shows "Media"); a folder's media, a list's posts and a user's subscription
  details are not shown; the chat header's online status stays the example's. When the relay fails, the examples stay, and then:
- Every chat, vault list and collections list row opens the one captured example page
  (`messages/chat`, `vault/list`, `collections/user-lists/list`): the mirror is static markup. The row's
  link carries `?row=<name>|<handle>` and the page (and its state/modal pages, whose links keep the query)
  shows that name in its header or list title, the handle in the chat partner's @mentions, and marks that
  row current in the list (`app/lib/ofMirrorRow.ts`); the messages, media and members are the example's.
  The chat header itself shows no handle in the capture.
- The profile write fields are all confirmed against live OF: its own Save, captured with the request
  intercepted and rejected before sending, sends `PATCH /api2/v2/users/me` with exactly
  `{name, location, website, wishlist}`; `about` (bio) and the welcome message switch were confirmed
  before. writes.py checks the app's relay calls against mocks.
