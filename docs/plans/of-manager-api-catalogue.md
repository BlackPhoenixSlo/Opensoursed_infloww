# OF Manager: OnlyFans creator web API catalogue

This catalogue lists the OnlyFans `/api2/v2` calls behind each action in the OF Manager mirror (`/of-manager/*`). It was
recovered statically from OF's public web bundle, build `202610091632-c45cc0ac3f`. It is the input for wiring the
controls that `docs/plans/of-manager-connectors.md` left read-only because their request body was not known.

Scope: each entry gives the endpoint, method, request body and query fields, and the response fields that OF's own
client reads. This catalogue does not cover request signing, sign headers or TLS fingerprinting. Every request goes
through the relay's existing client, which signs it. No call was made to OnlyFans.

## Sources and method

- Bundle: the SiteSucker dump held only `app.js`, `2313.js` and 58 `chunk-vendors-*` files under
  `static2.onlyfans.com/static/prod/f/202610091632-c45cc0ac3f/`. Every lazy route chunk (`MakeFeedPost-*`,
  `chats-send-*`, `vault-lists`, `settings-*` and so on) was missing; only their `.css` files were captured. The
  `of-live-capture*` folders contain no JS at all.
- The webpack runtime in `app.js` (`__webpack_require__.u`, public path `https://static2.onlyfans.com/static/prod/f/202610091632-c45cc0ac3f/`)
  maps 398 named chunks. A further 479 numeric chunk ids are referenced through `s.e(<id>)`. All 398 named chunks and
  459 of the numeric ones were fetched as public static JS into `/tmp/oi-rea/` (never committed). The other 20 numeric
  ids returned non-200, most likely because they are CSS-only. The post composer is `MakeFeedPost-72b1f13f.js`
  (chunk 63596, logic) plus `MakeFeedPost-017397ff.js` (chunk 43483, template and upload helper). The story editor is
  `24785.js`. The highlight editors are `52715.js` and `90403.js`.
- HTTP client: module `977434`, export `Ay` (an axios instance). `XV` is `"/api2/v2"`, `Zq(obj)` builds the query
  string, and `Jg` is 10, the default `limit`. The request interceptors in that module are signed by the existing relay
  client and were not read.
- Extraction: a script listed every `X.Ay.<method>(` call site: 641 in named chunks (612 of them in `app.js`) plus 24
  in numeric chunks. For each call it recorded the owning webpack module, the local function and the export alias.
  Body shapes were then read where the components build them (`getDataObject`, `654685.Os`, `prepareMultipleUserMessageData`,
  `uploadFinishHandler` and others). Every module id and symbol below is from this build.
- REA: `analyze_javascript_application` (directory mode, evidence `ev_b728ae45dcb984e0c3bcb6fc6984f02cd63750a5b55d8b331e4e2996277e5732`)
  parsed all 400 named files: 2.35M AST nodes, 3,703 webpack modules recovered from chunk registrations, and no parse
  failures. `trace_application_feature` (seed: module `977434`) gave the chunk-to-module import graph. For example,
  chunk 43483 contains modules 533242 and 511627, both of which import `977434`, and it loads async chunks 29610, 40134
  and 68937. REA's request family kept 0 relations because axios-through-`Ay` is not one of its HTTP sinks.
  `trace_javascript_semantics` on `votingOptions` came back `ambiguous`: Vue `this.*` receivers are not resolved, and
  the semantic budget was partial. `recover_javascript_sources` needs Linux x64 and this host is darwin, so it was not
  run. `analyze_web_bundle` needs a live CDP page, so it was not used.

## Status legend

| Status | Meaning |
|---|---|
| **WIRED** | The OF Manager mirror (`app/lib/ofMirror*.ts`) already sends this call through the relay |
| **APP** | A relay route exists and another part of Inflowwww (Messages Pro, compose, etc.) uses it; the mirror control is read-only |
| **RELAY** | A relay route (`service/server.py`, `/api/of/v2/...`) exists; no UI uses it |
| **CLIENT** | An `of_client.py` method exists but there is no relay route |
| **MISSING** | Nothing in our repo |
| **DRIFT** | Our relay sends a different shape from what OF's web client sends (details are in the row) |

Shared shapes:
- `mediaFiles[]` items can be any of these: a vault media id (number); a fresh upload claim
  `{processId, host, name, extra, thumbId?, customThumbId?, hash?|etag?+size?}`; an existing video `{id, thumbId?}`; or
  a pre-converted video `{url, thumbId, previewUrl, videoUploadHost}`. The relay's `/upload` `send_with` produces the
  claim form.
- Tags (release forms) come from `14562.m(releaseFormsData)`, which returns `{rfTag: id[] (creators), rfGuest: id[]
  (guests), rfPartner: id[] (links and documents)}`. Posts, messages and stories all spread this object into their body.
- List calls take `limit` (default 10), `offset` and often `skip_users=all` and `format=infinite`. Their responses are
  `{list, hasMore, nextOffset?}`, or a bare array.

## 1. Posts (new post, profile feed, post kebab)

Source: `app.js` module `458723`, unless the row says otherwise. Body built by `MakeFeedPost-72b1f13f.js` `getDataObject()`.

| Action | Method | Path | Body / query (types) | Response key fields | Source | Status |
|---|---|---|---|---|---|---|
| Create post (text, media, price/PPV, preview, poll, quiz, fundraising target, expiry, schedule, save-for-later, labels, tags) | POST | `/posts` | `text?: str`; `mediaFiles?: mediaFile[]`; `price?: number`; `preview: (id\|processId\|"poll")[]` (free teasers on a priced post; `"poll"` makes the poll free); `labelIds?: int[]`; `isScheduled?: 1` + `scheduledDate?: str` (date-picker value); Save-for-later: `isScheduled: 1, isPublishedWithPeriod: 1`, with no date; `expireDays?: int` (expiry period, days); poll: `votingType: 1` poll, `2` quiz; `votingOptions: str[]`; `votingDue?: int` (days, default 7); `votingCorrectIndex?: int` (quiz only); fundraising: `fundRaisingTargetAmount: number`, `fundRaisingTipsPresets: number[]`; `lockedText?: bool` (priced post); `rfTag/rfGuest/rfPartner: int[]`; `mediaEditorFiles?: {[processId]: {baseFile, stickers}}`; `saveUploads?: bool`; `tweetSend?: bool`; `isConsentAccepted?: bool` | post: `id`, `labelStates[]`, `postedAt`, `expiredAt`, `voting{options[{id,name,isCorrect}],finishedAt}`, `fundRaising{target,presets}`; errors `error.message`, `errors.text[0]` | `458723.S` (export `pD`); body `MakeFeedPost-72b1f13f.js getDataObject` | WIRED for `{text, mediaFiles, price:0, tags}` (`ofMirrorPost.ts:701` → relay `POST /posts`). DRIFT: relay `create_post` (`of_client.py:2368`) sends `postedAt`, `expirePeriod`, `fundRaisingTarget` and `votingDueDate`, but OF's client sends `isScheduled+scheduledDate`, `expireDays`, `fundRaisingTargetAmount+fundRaisingTipsPresets` and `votingDue`. Poll, quiz, labels and save-for-later are MISSING from `_CreatePostBody` |
| Edit post | PUT | `/posts/{id}` | same body as create | post object | `458723.m` (`px`) | RELAY (text, price, mediaFiles only) |
| Delete post | DELETE | `/posts/{id}` | none | `success`, `counters` | `458723.y` (`ys`) | APP |
| Pin / unpin post (toggle) | POST | `/posts/{id}/pin?format=status` | none | `success` | `458723.h` (`c8`) | RELAY. DRIFT: relay unpins with `DELETE /posts/{id}/pin`, but OF's client toggles with the same POST |
| Reorder pinned | POST | `/posts/pinned/sort?format=ids` | `{order: int[]}` | `success` | `458723.b` | MISSING |
| Archive / unarchive (also private archive) | POST | `/posts/{id}/archive` or `/unarchive` | query `action=private_archive?` | `counters`, `labelStates` | `458723.E` (`hf`) | MISSING |
| Hide post | PUT | `/posts/{id}/hide` | none | `success` | `458723.v` | MISSING |
| Like (favorite) | POST | `/posts/{id}/favorites/{authorId}` | none | `success`, `isFavorite` | `458723.p` | RELAY (`/posts/{id}/like`; relay unlike uses DELETE, while OF's client re-POSTs) |
| Vote in poll / quiz | POST | `/posts/{id}/vote` | `{optionId: int}` | `success` | `458723.g` (`Hg`); caller `additionally.js voteHandler` | MISSING |
| Poll voters | GET | `/posts/{id}/voters[/{optionId}]` | `limit, offset, ...` | `{list, hasMore}` | `458723.O` | MISSING |
| Fundraising contributors count | GET | `/posts/{id}/fund-raising-contributors/count` | none | count | `458723._` | MISSING |
| Post buyers / tips / likers | GET | `/posts/{id}/buyers`, `/tips`, `/favorites` | `limit, offset` | `{list, hasMore}` | `458723.R`, `.A`, `.I` | MISSING |
| Post stats | GET | `/posts/{id}/stats?withChart=true` | none | stats object | `977600.q` | MISSING |
| List comments | GET | `/posts/{id}/comments` | `limit, offset, sort=desc, skip_users=all, format=infinite` | `{list, hasMore, nextOffset}` | `692492.n` (`rq`) | RELAY |
| Post a comment | POST | `/posts/{id}/comments` | `{text: str, answerTo?: commentId, giphyId?: str}` | comment `id` | `692492.a` (`tP`); body from `comments/sendComment` in `notifications-b80f15b3.js` | RELAY (text only) |
| Bookmark / unbookmark | POST / DELETE | `/posts/{id}/bookmarks` | `{chat_group_id?}` (DELETE: `data.chat_group_id`) | `success` | `458723.T/P/C/w` | MISSING |
| Taggable creators | GET | `/posts/tagged-friend-users` | query object | `{list}` | `783434.p` | WIRED (`ofMirrorPost.ts:19`) |
| Tag search / release forms | GET | `/release-forms`, `/release-forms/mentions` | query | `{list}` | `783434.f`, `.I` | MISSING |
| Publish a save-for-later post now | PUT | `/schedules/{id}/publish` | none | `success` | `409363.u` (`V9`) | MISSING |
| Posts by label / type (profile feed) | GET | `/users/{id}/posts[/photos\|videos]` | `limit, order=publish_date_desc, skip_users=all, format=infinite, label?, pinned?` | `{list, hasMore}` | `202600.h`, `.f` | WIRED (data) |

### Post labels (new-post/state-labels)

These are post labels. OF web uses `/labels` for posts, not for fans.

| Action | Method | Path | Body / query | Response | Source | Status |
|---|---|---|---|---|---|---|
| List labels | GET | `/labels` | `limit, offset, query` or `ids, offset, query` | `{list[{id,name,postsCount}], hasMore}` | `91019.E` | RELAY (`GET /labels`). DRIFT: relay documents it as "fan labels" |
| Create label | POST | `/labels` | `{name: str}` | label `id` | `91019.P` | MISSING |
| Rename / delete label | PATCH / DELETE | `/labels/{id}` | `{name}` / none | label / `success` | `91019.C`, `.R` | MISSING |
| Add posts to label | POST | `/labels/{id}/posts` | `{posts: int[]}` | `success` | `91019.b` | MISSING |
| Remove post from label | DELETE | `/labels/{id}/post/{postId}` | none | `success` | `91019.O` | MISSING |
| Sort labels | POST | `/labels/sort` | order object | `success` | `91019._` | MISSING |
| Labels on a user | GET | `/users/{id}/labels` | `limit, offset, non-empty=1` | `{list}` | `91019.T` | RELAY |

Note: the relay's `POST/DELETE /labels/{id}/users/{uid}` (`of_client.py:2464`) has no call site in this OF build.

## 2. Upload (composer "Add media", vault upload, story)

| Action | Method | Path | Body | Response | Source | Status |
|---|---|---|---|---|---|---|
| Presigned multipart create | POST | `/upload/signed/create` | create payload (file meta) | presigned target(s) | `511627._s`, in `MakeFeedPost-017397ff.js`, `8532.js`, `85610.js` | CLIENT (`of_client.py:2534`, used inside relay upload) |
| Presigned PUT part | PUT | (presigned URL, not api2) | file bytes, `Content-Type` | ETag | `511627.Rq` | CLIENT |
| Presigned finish | POST | `/upload/signed/finish` | finish payload | `{processId, ...}` | `511627.dd` | CLIENT |
| Convert-host upload (gives `processId/host/name/extra`) | POST | convert host from init config (`uploadPath` / `reUploadPath`), not api2 | multipart | claim | `21914.js` uploader | WIRED (relay `POST /upload`, `ofMirrorPost.ts:30`) |
| Upload dedupe | GET | `/vault/media/hash` | query | match | `551564.i` | CLIENT |

## 3. Messages (single PPV, mass message, scheduled, save-for-later)

Source: `app.js` module `204607`. The single-chat body is built by `chats.js` `654685.Os`. The mass-message body is
built by `chats-send-017397ff.js` `prepareMultipleUserMessageData`.

| Action | Method | Path | Body / query | Response | Source | Status |
|---|---|---|---|---|---|---|
| Send message / PPV to one fan | POST | `/chats/{userId}/messages` | `text: str`; `lockedText?: bool`; `mediaFiles: mediaFile[]`; `price: number` (PPV); `previews: id[]` (free media on a PPV); `rfTag/rfGuest/rfPartner`; `isForward: bool`; `giphyId?`; `replyToMessageId?: int`; `mediaEditorFiles?`; `saveUploads?`; `isConsentAccepted?`; scheduled one-to-one: `isScheduled: 1, scheduledDate`; save-for-later: `isPublishedWithPeriod: 1` | message object (`id`, `media`, `price`, `isOpened`) | `204607.l` (`_z`); vuex `chats/sendChatMessage` | APP (Messages Pro); mirror `messages/*` is data-only |
| Mass message / scheduled / save-for-later | POST | `/messages/queue` | everything in the single-message body, plus `userLists: (listId)[]`; `excludedLists?: (listId\|"last24h")[]`; `userIds?: int[]`; `excludeUserIds?: int[]`; `recent?: 1`; audience shortcuts (one of): `fundRaisingPostId`, `awards: "y/m"`, `queueBuyers: [id]`, `postDonators`, `postBuyers`, `postLiked`, `campaignClaimers`, `postVoters: str[]`, `storyViewers`, `storyDonators`, `streamViewers`, `streamDonators`, `promoClaimed`, `trialClaimed`; `scheduledSubscribedOn?: ISO`; `filters?: {recent:1, ...}`; `recommenders?: 1`; `releaseForms?` | queue item `id`, `pending` | `204607.g` (`HI`); `chats-send-017397ff.js sendScheduleMessage` | APP |
| Edit scheduled mass message | PUT | `/messages/queue/{id}` | same as above | queue item | `204607.y` (`W9`) | MISSING |
| Cancel scheduled / unsent | DELETE | `/messages/queue/{id}` | none | `success` | `204607.S` (`po`) | APP |
| Queue list / one item | GET | `/messages/queue`, `/messages/queue/{id}?format=scheduled` | none | array / item | `204607.h`, `.f` | WIRED (`ofMirrorFeeds.ts:49`) |
| Audience size estimate | POST | `/messages/queue/size` | `{queueBuyers}` | count | `204607._` | MISSING |
| Queue buyers | GET | `/messages/queue/{id}/buyers` | `limit, offset, marker` | `{list}` | `204607.b` | MISSING |
| Unsend message | DELETE | `/messages/{id}` | `data.withUserId?` | `success` | `204607.m` (`gQ`) | APP |
| Like / unlike message | POST / DELETE | `/messages/{id}/like` | `{withUserId}` | `success`, `isLiked` | `204607.E/T` | APP |
| Pin / unpin message | POST / DELETE | `/messages/{id}/pin[/user/{uid}]` | none | `success` | `204607.R/O` | APP |
| Unpin all in chat | DELETE | `/chats/{id}/messages/pin` | none | `success` | `204607.k` | MISSING |
| Hide message | PUT | `/messages/{id}/hide` | body | `success` | `204607.M` | MISSING |
| Mark read / unread / all read | POST / DELETE / POST | `/chats/{id}/mark-as-read`, `/chats/mark-as-read` | all-read: filter object | `success` | `204607.v/I/A` | APP |
| Hide / mute / unmute / delete chat | POST / POST / DELETE / DELETE | `/chats/{id}/hide`, `/chats/{id}/mute`, `/chats/{ids}` | none | `success` | `204607.P/C/w/u` | APP (delete chat MISSING) |
| Chat list / users / messages / search / media | GET | `/chats`, `/chats/users`, `/chats/{id}/messages`, `/messages/search`, `/media/{type}` | `limit, offset, list_id, skip_users, order, last_id` | `{list, hasMore}` | `204607.n/a/o/d/L` | WIRED (chats, messages) / APP |
| Saved replies / welcome message | GET / POST / DELETE | `/messages/templates`, `/messages/templates/reply_on_subscribe`, `/messages/templates/{id}` | template body | template | `610023.l/d/u` | APP; reply-on-subscribe WIRED |
| Messaging settings | PATCH | `/users/me/settings/messages` | settings object | settings | `610023.m` (`Wl`) | MISSING |

## 4. Queue (calendar, save-for-later)

| Action | Method | Path | Body / query | Response | Source | Status |
|---|---|---|---|---|---|---|
| Calendar | GET | `/schedules` | `publish_date, publish_date_end, time_zone, limit`, `filter[type][0]=stream`, `filter[timeZone]` | `{list[{entity, type, date}]}` | `409363.c`, `.m` | WIRED (`ofMirrorFeeds.ts:37`) |
| Day counters | GET | `/schedules/counters` | same params | counts by day | `409363.d` | RELAY |
| Saved for later (posts / chats) | GET | `/schedules/later/{post\|chat}` | `limit` | `{list}` | `409363.l` | WIRED |
| Publish now | PUT | `/schedules/{id}/publish` (`id`: the schedule item's own id, not its entity's) | none | `success` | `409363.u` | WIRED (queue row menu, `ofMirrorQueue.ts`; relay `of_publish_schedule`) |
| Pin a save-for-later post | POST | `/posts/{id}/pin?format=status` | none | `success` | `458723.h` | WIRED (queue row menu) |
| Delete a queued post / message | DELETE | `/posts/{id}`, `/messages/queue/{id}` (`id`: the entity's) | none | `success` | see above | WIRED (queue row menu, after a confirm) |

## 5. Vault (media, folders, move, remove)

Source: `app.js` module `551564`.

| Action | Method | Path | Body / query | Response | Source | Status |
|---|---|---|---|---|---|---|
| List media | GET | `/vault/media` | `limit, offset, list_id?, sort?, order?, type?, query?` | `{list[{id,type,files,listStates}], hasMore}` | `551564.n` | WIRED |
| Media item / its posts / buyers | GET | `/vault/media/{id}`, `/{id}/posts`, `/{id}/buyers` | query | item / `{list}` | `551564.y/a/T` | RELAY (item) / MISSING |
| Remove from vault | PUT | `/vault/media/hidden` | `{mediaIds: int[]}` | `success` | `551564.o` | CLIENT (`of_client.py:1107`) |
| Folders list / one | GET | `/vault/lists`, `/vault/lists/{id}` | `view=main, limit, offset` | `{list[{id,name,type,videosCount,photosCount}]}` | `551564.c/d` | WIRED (list) |
| Create folder | POST | `/vault/lists` | `{name: str}` | list `id`, `name` | `551564.l` (`Rt`) | CLIENT (`of_client.py:1137`) |
| Rename folder | PATCH | `/vault/lists/{id}` | `{name}` | list `id` | `551564.u` | CLIENT |
| Delete folder | DELETE | `/vault/lists/{id}` | `data: {clearMedia: bool}` | `success` | `551564.m` | CLIENT |
| Add media to folder (move = add to target + remove from source) | POST | `/vault/lists/{id}/media` | `{mediaIds: int[]}` | updated list (`id`) | `551564.p` (`F8`) | CLIENT |
| Remove media from folder | DELETE | `/vault/lists/{id}/media` | `data: {mediaIds: int[]}` | updated list | `551564.h` (`Lg`) | MISSING |
| Sort folders | POST | `/vault/lists/sort` | `{sort?, order?, ...}` | `success` | `551564.f` | CLIENT |
| Attach tags to media | PUT | `/vault/media/{id}/attach` | `{rfTag, rfGuest, rfPartner}` | media | `551564.S` (`j1`) | MISSING |
| Types / processing / release forms | GET | `/vault/media/types`, `/processing`, `/{id}/release-forms` | none | counts / array | `551564.g/v/I` | RELAY / MISSING |
| Upload to vault | (convert host, see Upload) | | | | | RELAY (`/vault/upload/batch`, `/vault/upload/status`) |

## 6. Collections: user lists and bookmarks

Source: `app.js` modules `138255` (lists) and `191666` (bookmark categories).

| Action | Method | Path | Body / query | Response | Source | Status |
|---|---|---|---|---|---|---|
| Lists / one / users | GET | `/lists`, `/lists/{id}`, `/lists/{id}/users` | `limit, offset, query, type, filter, format=infinite` | `{list, hasMore}` | `138255.l/u/m` | WIRED |
| Create list | POST | `/lists` | `{name: str}` | list `id` | `138255.p` (`BL`) | RELAY |
| Rename list | PATCH | `/lists/{id}` | `{name}` | list `id` | `138255.h` (`EL`) | RELAY (APP for pin-chat) |
| Delete list / clear its users | DELETE | `/lists/{id}`, `/lists/{id}/users` | none | `success` | `138255.f/g` | RELAY / MISSING |
| Add / remove user | POST / DELETE | `/lists/{id}/users/{uid}` | none | `success` | `138255.v/I` | APP |
| Bulk add users to lists | POST | `/lists/users` | object of key → id[] (key meaning not resolved statically) | same keys → id[] | `138255.E` (`OF`) | MISSING |
| Sort lists / list users | POST | `/lists/sort`, `/lists/{id}/sort` | order object | `success` | `138255.y/S` | MISSING |
| Pin user in list / pinned sort | POST | `/lists/{id}/users/{uid}/pin`, `/users/pinned/sort` | `{order}` | `success` | `138255.T/P` | MISSING |
| Add audience to list (post buyers, voters, story, campaign, top fans, subscribers) | POST | `/lists/{id}/users/post/{postId}/{type}[/{optionId}]` etc. | stream: `{tippedOver, subscribedOver}`; subscribers: filters | `success` | `138255.L/b/O/k/M/D/U/V/w/_` | MISSING |
| Bookmark categories CRUD | GET / POST / PATCH / DELETE | `/posts/bookmarks/categories[/{id}]` | `{name}` | category `id` | `191666.E/P/C/w` | RELAY (GET) / MISSING |
| Put post in category / remove | POST / DELETE | `/posts/bookmarks/categories/{cid}/{postId}` | `{chat_group_id?}` | `success` | `191666._/L/b/R` | MISSING |
| Bookmarked posts | GET | `/posts/bookmarks/all` | `limit, offset` | `{list}` | (`458723` `/posts` family) | WIRED |

## 7. Settings writes

Source: `app.js` module `202600`. Key routing for toggles is in `settings-story.js` module `289051`.

| Action | Method | Path | Body | Response | Source | Status |
|---|---|---|---|---|---|---|
| Profile and general toggles (`about`, `name`, `subscribePrice`, `isPrivate`, `showSubscribersCount`, `muteTags*`, `commentsOnlyForPayers`, …) | PATCH | `/users/me` | `{<key>: value}` | updated user / key echo | `202600.o` (`Qp`, vuex `users/patchUser`) | WIRED (mirror `ProfilePatch`; non-security toggles and the subscription price Save, behind a confirm, in `ofMirrorSettingsWrites.ts`) |
| Security-section toggles (`isSuggestionsOptOut`, `phoneOtp`, `isPrivate`, `showPostsTips`, `showFriendsToSubscribers`, `showSubscribesOffers`, `showSubscribersCount`, `isWantComments`, `isAutoFollowBack`, `unfollowAutoFollowBack`, `coStreamingRequestFrom`, `showMediaCount`, `isDrmEnabled`, `requireFaceIdForPayoutUpdate`) | PATCH | `/users/me/settings/security` | `{<key>: value}` | `success` or key echo | `202600.d` (`CI`, `users/patchUserMeBySection`); list in `289051` | WIRED (`ofMirrorSettingsWrites.ts`) |
| Settings section replace | PUT | `/users/me/settings/{section}` | section object | result | `202600.c` (`q7`) | WIRED for `security` (watermarks Save `{hasWatermarkPhoto, hasWatermarkVideo, watermarkText?, watermarkPosition}`) |
| Notification toggles | PATCH | `/users/settings/notifications` | `{notifications: {<transport>: [{code, value}]}}` (transport is email, webpush, toast, sms…) | `success` | `202600.H` (`K2`) | WIRED (email items send 1/false or a digest's hours; email masters send `{field: value}` here too) |
| Default post / chat expiry | PATCH | `/users/settings/post`, `/users/settings/chat` | `{period: int}` | settings | `202600.te`, `.re` | MISSING (GET RELAY) |
| Story replies | PATCH | `/users/settings/story` | `{allowReplyFrom: str}` | settings | `202600.ae` (`k_`) | WIRED (`subscribers` / `nobody`) |
| Calls settings | PATCH | `/users/settings/calls` | object | settings | `202600.ce` | MISSING |
| Subscription bundle create / edit / delete | POST / PUT / DELETE | `/subscriptions/bundles[/{id}]` | `{duration/months, discount, ...}` | bundle `id` | `112995.d/u/m` | RELAY (POST, DELETE); PUT MISSING |
| Promotion create / finish / delete | POST / POST / DELETE | `/promotions`, `/promotions/{id}/finish`, `/promotions/{id}` | create: promo object | promo `id` / `success` | `732952.n/a/i` | RELAY (create, delete); finish MISSING |
| Free-trial link create / delete / update | POST / DELETE / PUT | `/trials`, `/trials/{id}` | trial object | trial `id` | `616150.L/R/O` | RELAY (create, delete) |
| Tracking link create / delete | POST / DELETE | `/campaigns`, `/campaigns/{id}` | `{name, ...}` | campaign `id` | `616150.v/w` | WIRED (create) / RELAY (delete) |
| Session list / log out others | GET / DELETE | `/sessions` | none | list / `success` | `settings-sessions.js` `205489.l/d` | MISSING |

## 8. Stories and highlights

Source: `app.js` module `502365`. Body built in `24785.js` (`uploadFinishHandler`, `createStoryByFileId`).

| Action | Method | Path | Body | Response | Source | Status |
|---|---|---|---|---|---|---|
| Publish story (upload or from vault) | POST | `/stories` | `mediaFiles: [vaultId \| {processId, name, host, extra}]`; `canvasHeight?`, `canvasWidth?`; `question?: {...}`; `answer?: {...}`; `texts?: {...}`; `post?: {...}` (share a post); `rfTag/rfGuest/rfPartner`; `mediaEditorFiles?`; `saveUploads?`; `isConsentAccepted?`. From vault the body is just `{mediaFiles: [vaultId]}` | story `id`, `media`, `isReady` | `502365.n` (`ko`), vuex `stories/createStory` | RELAY (`POST /stories`, `media_files`); image upload WIRED (`/stories/upload`); from-vault MISSING in UI |
| Delete story | DELETE | `/stories/{id}` | none | `success`, `highlights[]` | `502365.m` (`Cn`) | CLIENT (`of_client.py:3449`) |
| Archive | GET | `/stories/archive` | `limit, marker` | `{list, hasMore}` | `502365.d` | RELAY |
| Create / update highlight | POST / PUT | `/stories/highlights`, `/stories/highlights/{id}` | `{title: str, storyIds: int[], coverStoryId? \| thumbSourceId?, id?}` | highlight `id` | `502365.S` (`F1`) / `.I` (`oP`); `52715.js`, `90403.js` | MISSING |
| Add story to highlight / remove / delete | PATCH / DELETE / DELETE | `/stories/highlights/{id}`, `/stories/highlights/{hid}/{storyId}`, `/stories/highlights/{id}` | patch body | `success` | `502365.v/A/y` | MISSING |
| Story answers, viewer block | GET / DELETE / POST | `/stories/{id}/answer`, `/stories/answer/{id}`, `/stories/users/{uid}/block` | `limit, offset` | `{list}` | `502365.w/_/T/P` | MISSING |

## 9. Streaming schedule

Source: `app.js` modules `565144` and `622365`. Body built in `streaming-create-edit-schedule-b35596cd.js` `save()`.

| Action | Method | Path | Body | Response | Source | Status |
|---|---|---|---|---|---|---|
| Schedule stream | POST | `/streams` | `{description: str, scheduledDate: str (local ISO with offset), mediaFiles?: [upload], isConsentAccepted?, isShowTips: true}` | stream `id`, `scheduledAt` | `565144.b` (`x$`) | WIRED (`ofMirrorWrites.ts:76`) |
| Edit scheduled stream | PATCH | `/streams/{id}` | `{description, scheduledDate, mediaFiles?}` | stream | `565144.k` (`K4`) | MISSING |
| Delete scheduled stream | DELETE | `/streams/{id}` | none | `success` | `622365.o` | MISSING |
| Reminders | GET | `/streams/reminder` | query | `{list}` | `409363.p` | RELAY |
| Past live streams (dashboard) | GET | `/users/{id}/streams` | `limit=8, offset, skip_users=all` | `{list[{id, media, viewsCount, startedAt}], hasMore}` | `202600.mQ` (`Ie`) | WIRED (`ofMirrorFeeds.ts` `applyPastStreams`) |
| Notifications tab list | GET | `/users/notifications` | `limit, fromId, type, related_user, skip_users, format=infinite`; `type` is the tab's route name (`tip`, `purchases`, `favorited`, `message`, `deactivated_media`, ...; none on All) | `{list, hasMore}` | `202600` (`Tr`), types in `463670` | WIRED (all tabs) |
| Notifications Tags tab | GET | `/release-forms/mentions` | `limit, offset, fromId, related_user, skip_users=all, format=infinite` | `{list, hasMore, lastId}` | `783434.OM` | WIRED |
| Notification tab counts | GET | `/users/notifications/count` | none | `{all, <type>: n}` | `202600` (`Ge`) | WIRED (Tags uses `/users/me` `newTagsCount`) |
| Mark notifications read (by type / by id) | POST | `/users/notifications/read[/{type}]`, `/users/notifications/{id}/read/` | none | `{counters}` / `{success, counters}` | `202600` (`B`, `F`) | MISSING (OF calls it on opening a tab; not mirrored) |
| Start a live stream | POST | `/streams` | `{room, primaryPartnerId, isShowTips, canSendPrivateWithTip, includeUserListIds?, …}` | stream | `565144._` (`XI`) | out of scope (live video) |

## Counts

| Area | Catalogued calls (rows above, some rows group several) | Distinct call sites in the bundle |
|---|---|---|
| Posts and post labels | 29 | 33 (`458723`, `692492`, `91019`) + composer |
| Upload | 5 | 3 api2 + convert host |
| Messages | 18 | 30 (`204607`) + `610023` |
| Queue | 6 | 5 (`409363`) |
| Vault | 14 | 20 (`551564`) |
| Collections (lists, bookmarks) | 12 | 27 (`138255`) + 11 (`191666`) |
| Settings | 12 | about 25 relevant in `202600`, `112995`, `732952`, `616150` |
| Stories | 6 | 24 (`502365`) |
| Streaming schedule | 5 | 2 of the 51 in `565144` (the rest are live-stream) |

Total bundle call sites: 641 in named chunks plus 24 in numeric chunks. Some of these fall outside OF Manager: legal
inquiry, log, payouts banking and statistics.

## Next to wire (prioritized)

1. **Post extras on `POST /posts`.** Add OF's real keys to `_CreatePostBody` and `create_post`: `votingType`,
   `votingOptions`, `votingDue`, `votingCorrectIndex`, `expireDays`, `fundRaisingTargetAmount`,
   `fundRaisingTipsPresets`, `labelIds`, `isScheduled` + `scheduledDate`, and `isPublishedWithPeriod`. Fix the DRIFT
   keys (`postedAt`, `expirePeriod`, `fundRaisingTarget`, `votingDueDate`). Then the poll, quiz, target, expiration,
   labels and Save for Later controls on `new-post/*` can leave `READ_ONLY`. Before switching scheduling away from
   `postedAt`, re-verify it on the sandbox account: relay comments mark `preview` as confirmed live, but `postedAt` has
   no such note.
2. **Post labels.** Add relay `POST /labels {name}` and reuse `GET /labels` to fill `new-post/state-labels`; the chosen
   ids go out as `labelIds`.
3. **Story from vault.** The relay `POST /stories` already takes `media_files`. The mirror sends
   `{media_files: [vaultId]}`, which is OF's own `createStoryByFileId` shape. No new relay code is needed.
4. **Vault folder writes.** Add relay routes over the existing `of_client` methods: create, rename and delete folder;
   add media to a folder; `PUT /vault/media/hidden`. Also add `DELETE /vault/lists/{id}/media {mediaIds}`, so "move"
   becomes add plus remove.
5. **Queue row actions.** Add `PUT /schedules/{id}/publish` (publish now) and `PUT /messages/queue/{id}` (edit). Wire
   the existing `DELETE /messages/queue/{id}` and `DELETE /posts/{id}` to the queue kebab. "Create new list"
   (`POST /lists {name}`, relay exists) is a cheap follow-on.

Also worth fixing: pin and unpin should both use `POST /posts/{id}/pin?format=status`, as OF's toggle does. The relay's
"fan labels" naming for `/labels` is wrong in this build. The security-section toggles need
`PATCH /users/me/settings/security`, and notification toggles need `PATCH /users/settings/notifications`.
