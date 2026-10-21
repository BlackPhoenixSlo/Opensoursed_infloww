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
tomorrow's date, 6:30 pm and a description sends exactly one `POST /api/of/v2/streams` `{description, scheduledDate,
isShowTips: true}` and lands on `/of-manager/queue`. A second pass runs in the all-models
scope (`chatterly:scope` removed before every load): typing a display name and clicking SAVE sends no PATCH and shows
"Select a model to save changes", the welcome message switch sends nothing, shows that note and flips back, and the filled
schedule form's SCHEDULE sends nothing and shows that note too (screenshots `inapp-writes.png`, `inapp-writes-fans.png`,
`inapp-writes-schedule-invalid.png`, `inapp-writes-schedule-filled.png`, `inapp-writes-schedule-queue.png`,
`inapp-writes-all-models-schedule.png`):

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
6. All Creators (`chatterly:scope` removed before every load): typing "Synthetic link" and clicking "Create Link"
   sends nothing, shows "Select a model to save changes" and stays on the modal; 4 holds too; the Tracking links tab
   shows no row and OF's "No results :(".
7. No console errors in either pass.

It prints one `{"check","want","got"}` line per check and exits 1 on a failure (screenshots
`inapp-settings-writes-tracking-filled.png`, `-tracking-tab.png`, `-all-models-tracking.png`, `-promotion.png`,
`-bundle.png`, `-trial.png` (and `-all-models-` each), `-rows-tracking.png`, `-rows-trials.png`,
`-rows-promotion.png`, `-all-models-rows-tracking.png`, all `inapp-settings-writes-*`):

    python3 -I scripts/of-mirror-check/settings_writes.py

dark.py checks that the frame follows our theme (`chatterly:theme` dark, then light) with OF's own `m-mode-dark` on its `<html>` on home, messages/chat, settings/fans and settings/display, with no light first paint (an init script in every frame records the `<html>` class when the parser finishes,
readyState `interactive`, and at DOMContentLoaded, both before any load event: dark must have `m-mode-dark` then; window-level
listeners, since the frame's page reuses the window of its initial about:blank, where alone Playwright runs init scripts),
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
enabled again, the draft is kept and the page stays on New post. All-Creators scope (`chatterly:scope` removed before every
load): Post and the schedule dialog's Next send nothing, show "Select a model to save changes" and store no draft; the tag
dialog shows no rows (never the captured examples) and no `tagged-friend-users` request is made. No console errors,
except exactly one failed 502 load in each of the Tag list failure and Error cases (screenshots `inapp-post-typed.png`,
`inapp-post-posted.png`, `inapp-post-schedule.png`, `inapp-post-scheduled.png`, `inapp-post-validation.png`,
`inapp-post-tags.png`, `inapp-post-tagged.png`, `inapp-post-tags-failed.png`, `inapp-post-save-later.png`,
`inapp-post-labels.png`, `inapp-post-poll.png`,
`inapp-post-error.png`, `inapp-post-all-creators.png`, `inapp-post-all-creators-next.png`, `inapp-post-all-creators-tags.png`):

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
"All media" alone, never the captured "List <n>" folders, in both scopes. All-Creators scope (`chatterly:scope` removed
before every load): the dialog shows no tile (never the capture's 21 example tiles) and no vault request is made. No
console errors in either pass
(screenshots `post-vault-tiles.png`, `post-vault-picked.png`, `post-vault-search.png`, `post-vault-composer.png`,
`post-vault-reopened.png`, `post-vault-all-creators.png`):

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
7. All Creators (`chatterly:scope` removed before every load): clicking "Add media" fires no file chooser within 1s,
   sends no upload, and `#oi-note` reads "Select a model to save changes".
8. No console errors (but a 502's own resource line, and after a reload the dead `blob:` URL's); no request left
   localhost.
9. Dedupe hit: with vault id 42 seeded in the draft before load, an upload answered
   `{"ready":true,"deduped":true,"vault_id":42,"send_with":[42]}` is appended as returned: Post sends `media_files` `[42, 42]`.
10. After an accepted upload, Schedule then Cancel: back on New post the strip shows one loaded `blob:` thumb and Post
    sends the claim in `media_files`.
11. After an accepted upload and a full reload (its `blob:` URL dead), the strip holds one 64px grey square with no
    broken `<img>` left visible, and the draft's `media_files` still holds the claim.

It prints one `{"check","want","got"}` line per check and exits 1 on a failure (screenshots `inapp-post-upload-thumb.png`,
`inapp-post-upload-refused.png`, `inapp-post-upload-round-trip.png`, `inapp-post-upload-reloaded.png`,
`inapp-post-upload-all-creators.png`). The State pages' copies of "Add media" (in the composer under each
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
7. All Creators (`chatterly:scope` removed before every load), on `home` and on `new-post`: clicking "Add to story" fires
   no file chooser within 1s, sends nothing and the note reads the grey "Select a model to save changes", visible, right
   after the strip. No console errors.
8. My profile (`profile`, scope `model:1`): "Create highlight" is disabled with the tooltip "Not available in Inflowwww
   yet"; a dispatched click fires no file chooser within 1s, sends nothing and shows no note. "Story archive" carries
   `data-oi-wired`; a click opens the in-place archive box right after the strip, sends nothing but GETs, shows no note
   and stays on the page. No console errors. The strip's tiles are covered in both scopes by
   `app/lib/ofMirrorStory.test.ts` and `app/lib/ofMirrorProfile.test.ts`, as are
   Home's "Start profile promotion" (disabled, with the tooltip "Not available in Inflowwww yet") and New post's
   "Go live", "Send message", "Start profile promotion" and "Create new trial link" links.

It prints one `{"check","want","got"}` line per check and exits 1 on a failure (screenshots `inapp-story-home.png`,
`inapp-story-new-post.png`, `inapp-story-home-error.png`, `inapp-story-new-post-error.png`, `inapp-story-all-models.png`,
`inapp-story-all-models-new-post.png`, `inapp-story-profile.png`):

    python3 -I scripts/of-mirror-check/story.py

collections.py checks collections writes (app/lib/ofMirrorCollections.ts) in the frame, relay mocked: the list page's More menu, a user
card's Lists menu and the header's + (OF's "Create new list" / "Create new label" dialog) send their relay writes;
with all models nothing is sent.

Mocks the login (as writes.py) and, with scope `model:acc1`: GET /api/of/v2/lists (two synthetic custom lists with
OF's flags, Whales 31 and Regulars 32), GET /lists/31/users (two synthetic users), GET /users/alphaone (id 901) and
POST /lists/users ({"31": [901]}); every other non-GET /api/** is recorded (method, path, X-Account-Id, body) and
answered {"success": true}. Confirm dialogs are accepted. Checks, on collections/user-lists/list?list=31: More lists
Rename list, Add users, Clear list, Delete list; Rename (the dialog holding "Whales") sends PATCH /lists/31 {name};
Add users with "@alphaone" sends POST /lists/users {"31": [901]}; a card's Lists offers "Remove from Whales" and "Add
to Regulars", which send DELETE /lists/31/users/202 and POST /lists/32/users/202; Clear list sends DELETE
/lists/31/users; Delete list sends DELETE /lists/31 and lands on /of-manager/collections, which shows the first list's
users and whose + opens the "Create new list" dialog, whose Save sends POST /lists {name}; Post Labels' + opens
"Create new label", whose Save sends POST /labels {name}. Every write carries X-Account-Id acc1. All models (scope key
removed): the + shows "Select a model to save changes" and nothing is sent. Screenshots:
/tmp/of-mirror-shots/inapp-collections-more.png, inapp-collections-card.png, inapp-collections-create.png,
inapp-collections-label.png. Exit 1 on a failed check.

    python3 -I scripts/of-mirror-check/collections.py

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
   post), the author links `#`, "No bookmarks yet" hidden, the avatar-less author with no picture; the request carries
   `limit=20`; the borrowed post row is one same-origin GET of `/of-mirror/pages/profile/index.html` and no other page
   is fetched; every bookmark's More (another creator's post) is disabled with the tooltip "Not available in Inflowwww yet" and a click shows no note. On `collections`, "Create new list" opens OF's
   "Create new list" dialog (collections.py checks its write); with All Creators it shows "Select a model to save changes".
4. `statements/earnings`: exactly account 1's transactions in order ([date, time, amount, fee, net, description,
   status tips] per row: money with two decimals, an absent fee or net empty, the fan link as text, the done row
   "Complete", the pending row "Earning will become available in 5 days", the refunded row no status tip), no example
   row, the empty row hidden; one request, `limit=20`.
5. `statements/payouts` and `statements/referrals`: exactly account 1's payout requests in order ([date, time, invoice,
   amount, status class, status text, status icon] per row, OF's fields `invoiceId`, `state`, `rejectReason`: approved
   "Payout has been processed", rejected with its "Reason:" line the payout's `rejectReason` or no line, pending OF's
   `pending` span with only `#icon-loading`); Referrals hides "This list is
   empty" and borrows its row by one same-origin GET of `/of-mirror/pages/statements/payouts.html`, Payouts fetches no
   page; "Request withdrawal" stays disabled; one request each, exactly `limit=20`.
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
   rows and every relay call after the switch carries `X-Account-Id: 2`; All Creators shows no post row on `profile`,
   only OF's "No posts yet".
9. All Creators (`chatterly:scope` removed before every load): every page above keeps its example rows or captured
   empty state (`profile` and `profile/media` no post or tile, only "No posts yet"; `statements/earnings` and `payouts`
   no rows, only "No earnings for this period" and "This list is empty"), requests none of these Relay routes (no `/users/me` either) and fetches no template page; "Create new
   list" still shows the Read-only note.
10. No console errors.

It prints one `{"check","want","got"}` line per check and exits 1 on a failure (screenshots
`/tmp/of-mirror-shots/inapp-feeds-*.png`: one per page, its More or "Create new list" click, the Creator switch and
the All Creators pass). The mocks prove the mapping, not the Relay's shape: the field names the spec marks as guessed
(notification `isRead`; bookmark `author`; saved-for-later `text`, `mediaCount`)
render empty if wrong, never as examples:

    python3 -I scripts/of-mirror-check/feeds.py

queue.py checks the queue rows' More menu (`app/lib/ofMirrorQueue.ts`) with the same login mocks, scope `model:1` and
synthetic wrapped `/schedules` items (answered by their `publish_date` span) and the clock fixed at 2026-10-12 12:00 on
`queue/state-list-view`: the post and message menus' entries, the right column's day, Edit post disabled with "Not
available in Inflowwww yet", Post now's exact `PUT /api/of/v2/schedules/<schedule id>/publish` (and the queue
refetched), Delete post with the confirm dismissed sending nothing and Delete message with it accepted sending exactly
`DELETE /api/of/v2/messages/queue/<message id>`; then on `queue` the month arrows (November asked for by its
`publish_date` span and shown, back greyed out on today's month), a day click (the right column's day and its items)
and the type tabs, all in place and sending nothing (screenshots `inapp-queue-menu.png`, `inapp-queue-november.png`):

    python3 -I scripts/of-mirror-check/queue.py

dead.py is the Phase 6 sign-off: no Silent control (`app/lib/ofMirrorWrites.ts` `bindWrites`' click fallback and change
path). Pages: every page of `new-post`, `home`, `streaming`, `profile`, `queue`, `collections`, `notifications`, `statements`, `statistics`, `messages`, `vault` and `bank`, and
`settings/subscription` with its tabs, modals and states, read from `app/lib/of-mirror-pages.ts` (arguments: only the
pages named, or under a named prefix, e.g. `queue` or `new-post/state-vault`); `sessionStorage` is cleared before each
page. Mocks: the login as in writes.py, `GET /api/of/v2/users/me` (synthetic), `GET /posts/tagged-friend-users` and
`GET /vault/media` (one synthetic "Alpha One" row each, so the Co-tag rows and vault tiles exist), `GET /img` (a 1x1 PNG
the script builds) and `[]` for every other `GET /api/**`; every non-GET `/api/**` is recorded (method, path,
`X-Account-Id`, body) and answered 200 `{}`; any request to a host other than localhost is aborted and fails the check.
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
   chooser, markup change or other note.
4. A Relay write from an unmarked control, or any write off the allow-list (`POST /api/of/v2/posts`, `/upload`,
   `/stories/upload`, `/campaigns`, `/trials`, `/promotions`, `/streams`); exact bodies stay with each Phase's own check.
5. A measured Wired control (plan Ground truth 5) without `data-oi-wired` on the page that binds it: Post
   (`button[at-attr='submit_post']`, every new-post and home page), "Add media" (every new-post page, `home`), "Add to story"
   (`.b-story-item.m-story-item-own`, home and new-post), the vault search and tiles (`new-post/state-vault`,
   `home/state-vault`), the tag rows (`new-post/state-tag-people`, `home/state-tag-people`), Next
   (`new-post/state-schedule`, `home/state-schedule`), the stream schedule form's SCHEDULE
   (`streaming/dashboard/create`) and Create Link (`settings/subscription/tracking-links/modal-1`).
6. Any console error.

All Creators (`chatterly:scope` removed before every load): the same pages, sweep and checks 1-4 and 6, and no non-GET
`/api/**` request from a page that does not stand in. A stand-in page (`STAND_IN_SRC` in `app/lib/ofMirrorProfile.ts`,
read as text: New post, Settings, Messages, the Queue, Statistics, the Vault and the rest show the first model with a
session in All models, and their actions are that model's) may write, each write with that model's `X-Account-Id`. The
send controls on the other pages, made sendable first (Post with text typed), give exactly "Select a model to save
changes": Post and Add to story (`home`) and the stream schedule form's SCHEDULE; the New post and Settings ones act as
the stand-in model. `DISABLED` (submits with no Known body) is empty. New post's Record video and Record voice
(the not-supported popup) and its right column search box are marked. `dead.py settings` sweeps every settings page.

It prints one `{"check","want","got"}` line per check, one `{scope, page, controls, links, wired, readonly}` line per
page and one per pass, and exits 1 on a failure. It runs for about 25 minutes for both passes. Screenshots: one per
page with a note showing, `/tmp/of-mirror-shots/inapp-dead-<page, / as __>.png`; the All-Creators pass overwrites a
page's Single-Creator image:

    python3 -I scripts/of-mirror-check/dead.py
    python3 -I scripts/of-mirror-check/dead.py queue new-post/state-vault   # only these pages, or under these prefixes

What writes, what shows data and what is read-only, page by page (from `app/lib/ofMirrorWrites.ts` `WRITABLE` and `SUBMITS`,
`app/lib/ofMirrorSubscription.ts`, `app/lib/ofMirrorPost.ts`, `app/lib/ofMirrorData.ts` `DATA_PAGES`, `app/lib/ofMirrorFeeds.ts`,
`app/lib/ofMirrorSettings.ts` `SETTINGS_MAP`, and the plan's Ground truth table). Writes and Data parts need a single
Creator: in All-Creators scope a write sends nothing and shows "Select a model to save changes", and a Data part keeps
its examples. Every control not listed as a write, and not a link, a State page opener or the video player, is
read-only: in either scope a click on a button or `[role=button]` shows "Read-only in Inflowwww for now", and a
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
  promotions and scheduled events, the vault dialog's media. Disabled with a tooltip: "Start profile promotion", Add poll,
  Add quiz, Expiration period, Your target, Format Text, Record video and voice. Read-only: fans' story tiles, every other
  button.
- `profile`, `profile/state-more-menu`, `profile/media`. Writes: the own posts' like, comments and More menu (as Home's).
  Data: `profile` and its State pages the wall posts (`GET /users/<id>/posts?limit=20`), `profile/media` the photo and
  video posts, all three the counts and label tabs (`/users/me`, `/labels`), the Recent strip, the highlights
  (`/users/<id>/stories/highlights`) and the promotions. Wired in place: "Story archive" (`GET /stories/archive`), Copy
  link to profile, More info, Spotify's title, the media tabs. Links: Photos, Videos, Fans, "Go live", the More menu's
  Statistics. Disabled with the tooltip: "Create highlight" (no highlight write), the highlight tiles, the label tabs
  but All, QR code, the status menu, the wall's search, compact view and sort, the sidebar search, Sign in with Spotify,
  each post's Labels, Post statistics and bookmark.
- `queue/*`. Writes: none. Data: `queue` and `queue/state-list-view` (`/schedules`), `queue/state-tab-messages`
  (`/messages/queue`), `queue/saved-for-later-posts` and `-messages` (`/schedules/later/post`, `/chat`);
  `queue/state-tab-streams` keeps its capture. Read-only: item and row actions, every other button.
- `collections/*`. Writes (`app/lib/ofMirrorCollections.ts`, collections.py): on `collections` and
  `collections/user-lists/*`, "Create new list" (OF's dialog, `POST /lists`); on `collections/post-labels/*` the "+"
  ("Create new label", `POST /labels`); the list's More (Rename `PATCH /lists/<id>`, Add users `POST /lists/users`,
  Clear `DELETE /lists/<id>/users`, Delete `DELETE /lists/<id>`); a user card's Lists (`POST` / `DELETE
  /lists/<id>/users/<uid>`). Data: `collections` and `collections/user-lists/list` the user lists (`/lists`) and the
  open (else the first) list's users (`/lists/<id>/users`), Fans (`subscribers/active`) the active subscribers
  (`/subscribers?type=active`), the Following pages the lists only (no subscriptions read: "Nothing found"),
  `collections/post-labels/archived` the labels (`/labels`; a label's posts: OF's "No posts yet"),
  `collections/bookmarks/all` the bookmarked posts. No example list, card or post is kept. Disabled with the tooltip:
  the bookmarks "+", Search, Sort, Filter, Pin to home, the card tools but Lists, a More or Lists with nothing to do.
  Read-only: a bookmark's More.
- `notifications/*`. Writes: none. Data: `notifications`, `notifications/subscribed`, `notifications/commented` and
  `notifications/mentioned` (`/users/notifications`, the tab's `type`); `notifications/tip` and the other tabs keep
  their examples. Read-only: the tab filters' buttons and every other button.
- `statements/*`. Writes: none. Data: `statements/earnings` (`/payouts/transactions`), `statements/payouts`
  (`/payouts/requests`), `statements/referrals` (`/payouts/requests/referral`). Wired: the balance box header
  (collapse) and Copy link. Disabled with the tooltip: Request withdrawal, the payout frequency and payout account
  menus, Earning Statistics' date range and the Billing Support form. Read-only: none.
- `statistics/*` (`app/lib/ofMirrorStats.ts`). Writes: none. Data, for the period picked in OF's period menu
  (wired: data-oi-period): the figures (`/users/me/stats/overview?by=…&start=…&end=…`, `/payouts/stats`), Engagement ›
  Messages' table (`/users/me/stats/messages/group`), Reach › Profile visitors' tables and chart
  (`/users/me/profile/stats`), the Chargebacks ratio, Payout Requests, Referrals and Statistics › Statements ›
  Earnings' table (`/payouts/transactions`); no captured figure is kept (" — " until the relay answers). Disabled with
  the tooltip: the menu's Custom, Request withdrawal, the earnings radios, Search messages, Unsend, and every section
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
  details are not shown; the chat header's online status stays the example's. With all models, or when the relay fails, the examples stay, and then:
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
