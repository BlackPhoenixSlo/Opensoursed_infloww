# Fansly capture backlog — what the rig still has to learn

Same legend as `FANSLY_PARITY_STATUS.md`, and the same honesty rule:
✅ means **captured from a live frame/response and written into a recipe**, not
"we found the button". 🟡 means partially captured. ⬜ not started.

Every ✅ must name the evidence: `out/<run>/<file>` + the frame or endpoint.
A row is NOT ✅ on inference from the JS bundle alone — the bundle tells you
where to look, a captured frame tells you what is true.

Account is a TEST account. Sends, typing, follows, likes, posts, deletes are all
authorized. **Spending money is not** — see Rules in the loop prompt.

---

## 1. Realtime WebSocket `wss://wsv3.fansly.com/?v=3`  ← highest priority
Unblocks: typing indicator, W7 realtime dispatch, notification push, tip trigger.

| # | item | status | note |
|---|---|---|---|
| 1.1 | connect + auth handshake | ✅ | `out/fansly-live/ws.jsonl`. `{"t":1,"d":"{\"token\":..,\"v\":3}"}` — `d` is DOUBLE-encoded JSON. Auth in-band; token is the one already in `fansly_session.json`. |
| 1.2 | keepalive | ✅ | OUT bare literal `p`; IN `{"t":2,"d":"{\"lastPing\":<ms>}"}`. Cadence not yet measured — see 1.9. |
| 1.3 | inbound chat message event | ✅ | **OBSERVED run-20260901-2049** (not inferred). A real inbound landed while recording: following a creator triggered her AUTOMATED welcome DM. Event is `serviceId:5 {"type":1,"message":{...}}` — the SAME shape as an outbound send with `senderId` = the fan (500251712226222080) instead of us. Direction test = `senderId != own accountId`. Inbound carried a real `correlationId` where our own send had `"0"`. Attachment shape `{contentType,contentId,messageId,pos}`. |
| 1.4 | outbound echo event | ✅ | **CAPTURED run-20260901-1948.** Yes — our own send echoes back as `serviceId:5 type:1`. A relay pump MUST dedupe against its own sends or every outbound persists twice (same hazard OF's `event_transcoder` outbound-echo debounce exists for). Send request also captured: `POST /api/v1/message`. |
| 1.5 | **typing frame (OUT)** | ✅ | **CAPTURED run-20260901-1940.** Sent over REST, NOT the socket: `POST /api/v1/message/typing` body `{"groupId":"..."}` → 200. Server then broadcasts `t:10000 serviceId:5 {"type":22,"typingAnnounceEvent":{accountId,groupId,lastAnnounce}}`. **Means the relay can emit typing with no WebSocket at all** — unlike OF. Re-announce interval + how it clears NOT yet measured. Recipe in RECIPES.md. |
| 1.6 | typing frame (IN) | ✅ | ✅ Measured run `fansly-creator-1126b` (2026-11-26) and the 09-02 two-account run: fan typing reaches the creator as `serviceId:5 type:22 typingAnnounceEvent{accountId:<fan>,groupId,lastAnnounce}`, one per ~3–5 s burst. Sender side: `POST /message/typing {groupId}` → `response:null`. RECIPES "Typing, inbound". |
| 1.7 | notification push | ✅ | ✅ Measured 2026-09-02 two-account run: every notification row pushes first as `serviceId:9 type:1 {notification}`, removals as `9/3`. Codes seen: 3003 follow, 1002 post like, 5003 message like, 1004 post reply. RECIPES "Notification PUSH exists: `serviceId 9`". |
| 1.8 | subscribe / room-join frames | ✅ | **No subscribe/join frame exists.** After `t:1` auth the client sends only `p` keepalives, yet receives events for a group it never named → the socket is a per-account firehose. Relay needs no per-group subscription tracking. Also: duplicate frames are normal (same ackCommand 4x in 3s) — dedupe on (serviceId, type, messageIds). |
| 1.9 | ping cadence + reconnect/resume | ✅ | **CAPTURED run-20260901-1953.** Reconnect = ~1.5s delay, then a FULL re-auth (`t:1` with the same token); `session.id` constant, `websocketSessionId` newly minted each connect and never echoed back → **no resume protocol**, a plain retry loop is correct. Ping cadence **CORRECTED**: not 25.0s — measured 20–45s across 4 runs, consistent with an idle timer reset by other traffic. Implement as unconditional `p` every ≤20s. |
| 1.10 | tip / purchase push | ⛔ | Media purchase push ✅ OBSERVED 2026-09-02 (`serviceId 2 type 7` order + `6/3` wallet tx + `9/1` 2007 row, RECIPES PPV section). Tip push (7001): ⬜ deferred (owner 2026-11-27: no more paid proofs; capture passively from real traffic, RECIPES "Paid flow up to 3DS" → "Later, from real traffic"). |

## 2. Read state (closes the 🟡 mark-read row)

| # | item | status | note |
|---|---|---|---|
| 2.1 | what opening a thread actually does | ✅ | **CORRECTED.** Earlier note said no mark-read call fires — WRONG, it was outside the window I sliced. `POST /api/v1/message/ack` DOES fire on thread open. |
| 2.2 | what sets `readAt` | ✅ | `POST /api/v1/message/ack` body `{"messageIds":[...],"type":2}` → `{"success":true}`. Takes MESSAGE IDS, not a group id — which is why every group-shaped probe 404'd. Broadcast echoes as `t:10000 serviceId:4 type:2 ackCommand{groupId,messageIds,userId,userReadReceiptsEnabled,recipients}`. |
| 2.3 | what `total` counts | ✅ | **`total` is NOT the unread count.** With 3 genuinely-unread messages outstanding, `/message/unread` reported `total:0` while returning 3 `messageInteractions` rows, and `/messaging/groups` reported per-group `unreadCount` 1 + 2 = 3. Two independent signals agree (group `unreadCount`, and the count of interaction rows with `userId`=us and `readAt` null); `total` disagrees with both. Drive the badge from `unreadCount`, never `total`. Same trap-shape as `statusId` — the obviously-named field is the wrong one. |
| 2.4 | is there a mark-read write at all | ✅ | Yes — `/message/ack` exists. The shim's no-op is a real gap, not a documented absence. See RECIPES.md. |

## 3. The 20 missing client methods
Each row: perform the action in the browser, capture request line + headers +
body + response, write the recipe into `RECIPES.md`. Group by what they unblock.

| # | method(s) | status | unblocks |
|---|---|---|---|
| 3.1 | `add_user_to_list` (+ remove/get/create) | ✅ | ✅ run-20260901-2021 (create+add+remove+read). `POST /api/v1/lists {label,description}` → `{accountId,type:1,label,id}`. Membership is a BATCHED command API `POST /api/v1/lists/commands`, and **add/remove have DIFFERENT payload shapes**: add `{type:1,listItem:{id,listId}}` (singular object) vs remove `{type:2,listId,itemIds:[...]}` (plural array) — a shim assuming one shape silently no-ops one direction. `GET /api/v1/lists/account?itemId=` returns ONLY user-created lists; Blocked/Muted/VIP/DM-Allow are client-side built-ins, so `[]` ≠ no lists. GAP: deleting a list not captured (row `···` ignores synthetic click). Leftover empty list `zz-capture-tmp` on the account. |
| 3.2 | `pin_message`, `unpin_message` | ⛔ | ⛔ **Fansly has no message pinning.** Verified two ways (run-20260901-1959): (a) hovering a message reveals exactly four actions — reply, heart/like, `+` (which opens an EMOJI REACTION picker 😂😮😢❤️🔥👍👎, not a menu), and trash/delete; (b) the thread-level `···` menu lists Mark as Unread, Mute, Disable Read Receipts, Add to List, Notes, Earnings, Tips, Block, Unfollow, Subscribe to, VIP — no pin. **Implication for the shim:** `pin_message`/`unpin_message`/`get_pinned_messages` should be permanent no-ops returning empty, and `_pins` must be short-circuited for Fansly rather than left to AttributeError inside ai_chatter. (`_pins` and ai_chatter are since retired; the no-ops now serve the chat's Pin route.) |
| 3.3 | `unsend_message` | ✅ | ✅ **CAPTURED run-20260901-2004.** `POST /api/v1/message/delete` `{"messageId":"..."}` → `{success:true, response:{...,deletedAt}}`. One call; the confirm dialog is client-side. Broadcast as `serviceId:5 type:10` with the full message. **Gotcha found: mixed timestamp units on ONE object** — `createdAt`/`deletedAt` in SECONDS, `interactions[].deliveredAt` in MILLISECONDS, and `createdAt` is float on the WS but int on REST. Normalise per-field. |
| 3.4 | `follow_user`, `unfollow_user`, `like_post`, `like_message`, `resubscribe_user`, `recent_expired_subscribers` | 🟡 | 5 of 6: follow_user ✅, unfollow_user ✅, like_message ✅, like_post ✅ (09-02 two-account: `POST /likes {postId}` → `{accountId,postId,id}`, 1002 push), recent_expired_subscribers ✅ (session 1126, status 5). `resubscribe_user`: needs a lapsed PAID sub — ⬜ deferred (owner 2026-11-27: no more paid proofs; capture passively from real traffic, RECIPES "Paid flow up to 3DS" → "Later, from real traffic"). |
| 3.5 | `iter_online_subscribers` | ⛔ | Mechanism identified and fields proven (`lastSeenAt` recency, NOT `statusId` — a dormant control account also reports `statusId:1`). Needs an active subscriber: ⬜ deferred (owner 2026-11-27: no more paid proofs; capture passively from real traffic, RECIPES "Paid flow up to 3DS" → "Later, from real traffic"). |
| 3.6 | `send_mass_message` | ✅ | ✅ **run fansly-creator-1126.** Audience = type-3 group with a list recipient (`POST /group`, idempotent per audience), send = `POST /message/broadcast` (same body as `/message`) → `response:"broadcast sent"`. Scheduled send, queue read, cancel and history (`/message/broadcast/stats`) all captured on a list holding only the test fan. RECIPES "Capture session 1126". |
| 3.7 | `create_post` | ✅ | **CAPTURED run-20260901-2049.** `POST /api/v1/post` with `{content,fypFlags,inReplyTo,quotedPostId,attachments,scheduledFor,expiresAt,postReplyPermissionFlags,pinned,wallIds,pinWallIds}`. `wallIds` is REQUIRED (the profile wall id, from the account's `walls`). `scheduledFor:0` = post now; non-zero schedules it. Test post created and DELETED (verified gone). |
| 3.8 | `post_story_from_url` | ⛔ | Read/delete/view/order endpoints known (`/stories`, `/stories/order`, `/mediastories`, `/mediastory/delete`, `/mediastory/view`); **no create path exists in the client bundle**, and no story composer is reachable on web (the profile "+ New" is Create New Album). Story creation appears to be mobile-app-only. The media-upload prerequisite IS now solved (§3.11), so this needs the create call observed from the mobile client. |
| 3.9 | `delete_post`, `delete_story` | ⛔ | `delete_post` ✅ (`POST /post/{id}/delete`, no body). `delete_story` cannot be captured because no story can be CREATED on web (§3.8) — nothing to delete. `/mediastory/delete` is the known path. |
| 3.10 | `cancel_scheduled` | ✅ | ✅ Post lane: run-20260901-2049 — `POST /post/scheduled/{postId}/cancel`, `scheduledFor` ms, ⚠️ `/post/{id}/delete` on a queued post 422s. **Mass lane ✅ run fansly-creator-1126**: `POST /message/broadcast/scheduled/<id>/cancel` (no body) → row `status:3`, queue 1→0, no socket frame. Distinct path from the post lane. |
| 3.11 | `hide_vault_media`, `vault_media_lookup_hash` | ⛔ | **MEDIA UPLOAD ✅ FULLY CAPTURED** — the project's biggest gap, see RECIPES. `hide_vault_media` is terminal: **no vault-delete endpoint exists in the client**. `/vault/albums/media/delete` only UNLINKS from an album (verified — media remained), and `/account/media/{id}/delete` wants an accountMedia GRANT id, not a vault mediaId. `vault_media_lookup_hash` has no counterpart either. ⚠️ vault uploads appear PERMANENT — an operational constraint for any relay media send. Leftover: `zz-capture-test.jpeg` in the vault. |
| 3.12 | `create_promo` | ✅ | ✅ **run fansly-creator-1126.** `POST /subscriptions/promotions {id:"",description,planId,status:1,duration,maxUses,uses:0,price,startsAt,endsAt}` → promo with id. UI floor $3.00; server rewrites `duration` to the plan cycle (7→30). Promo `900999000000085664` live on the $5 plan until 2026-12-03. |

## 4. Earnings / sales row shape

| # | item | status | note |
|---|---|---|---|
| 4.1 | endpoints located | ✅ | `GET /api/v1/account/wallets/earnings/stats?before&after&limit&offset` and `/monthlystats?before&after`. Supersedes the seven 404'd probes in the parity doc. |
| 4.2 | populated row shape | ✅ | ✅ **2026-11-26, read-only.** After the 2026-09-02 $3 PPV: `earnings/stats` → per-type-per-day rows `{type:2110,totalGross:3000,totalNet:2400,accountId,timestamp}`; `monthlystats` → a rolling-30-day row (`year:0,month:0`) then per-month rows. Fixture `fansly/fixtures/earnings.json`. |

## 5. Native features worth knowing before we rebuild them

| # | item | status | note |
|---|---|---|---|
| 5.1 | `GET /api/v1/message/automated` | ✅ | ✅ **FULL CRUD CAPTURED + VERIFIED LIVE** (run-20260901-2049). Fansly's native welcome-bot; the client calls it `chatBotApiService_`. `GET /api/v1/message/automated` (list), `POST /message/automated` (create), `/message/automated/edit`, `POST /message/automated/{id}/delete` with body `{}`. Create body: `{id:null,accountId:null,delay:0,triggerType:3,messageTemplate:{content,attachments:[]}}`. **triggerType 3 = on follow** — matches §1.3, where following a creator instantly delivered her welcome DM. Create/delete return a bare STRING not the object, so re-GET the list for the new id. Round trip verified: create 200 → listed → delete 200 → list empty. `messageTemplate.attachments` accepts media, so a welcome DM can carry a vault mediaId (§3.11). |
| 5.2 | notification type-code map | ✅ | ✅ **Full type→label map recovered** from the client's own `this.filters=[…]` table in `main.<hash>.js`, and `15011` CONFIRMED against live data (the row's stated done-condition). 24001/24002=Fansly Alerts, 1002/2002/5003=Likes, 1004=Post Replies, 1005=Post Quotes, **7001=Tips**, 3002/3003=Followers, **2007/2008=Media Purchases**, 15006/15016=Subscribers, 15007=Expired Subscriptions, 15011=Promotions, 32007=Locked Text Purchases, 45012=Stream Ticket Purchases. 🔑 **7001 and 2007/2008 route around two blockers the parity doc calls dead ends** — tips and the PPV 'fan actually paid' signal, both of which it reports as unavailable because every sales endpoint 404s. `metadata` shape for those codes is UNVERIFIED (null on every 15011 seen). |

## 6. Phase 1b: the one Capture session and the three Proof purchases

Owner-run, not the loop: the session takes free actions only, and the three
purchases are the only spend. Each Blocked method's capture is named in
`FANSLY_PARITY_STATUS.md` → "Phase 1b verdicts"; these close the ones the
Relay and automations reach first.

**Capture session** — creator and fan accounts in two Chrome profiles, every
request and frame recorded into `RECIPES.md`:

| # | action | closes | status |
|---|---|---|---|
| 6.1 | open a list's members | `list_users_in` (Smart list sync stays off until it is built) | ✅ fansly-creator-1126: `GET /lists/itemsnew?listId=` → bare ids |
| 6.2 | rename a list | `rename_list` | ✅ fansly-creator-1126: `POST /lists/edit` whole list object |
| 6.3 | delete a list (a trusted click on the row `···` menu, §3.1's gap) | `delete_list` | ✅ fansly-creator-1126: `POST /lists/remove {listId}` |
| 6.4 | block, then unblock, the fan account | `block_user`, `unblock_user` | ✅ fansly-creator-1126: `POST /account/ignore` flags 2/0; block severs the follow |
| 6.5 | search for the fan by username | `search_users` | ✅ fansly-creator-1126: `GET /account/search` — creators only, fans not found |
| 6.6 | schedule one broadcast to a list holding only the fan account, read the queue and broadcast history, then cancel it | `schedule_mass_message`, `scheduled_messages`, `queued_message`, `edit_queued_message`, `mass_message_history`, `engagement_messages`, and the unconfirmed `send_mass_message` path; also the broadcast cancel shape `cancel_scheduled` lacks (its post-endpoint hazard) | ✅ fansly-creator-1126: schedule/queue/history/cancel captured, body via in-page fetch |

**Proof purchases** — fan account to creator account, creator side recorded
before and after (notification row, socket frames, wallet frame):

| # | purchase | proves | status |
|---|---|---|---|
| 6.7 | chat PPV | 2007 still carries `accountMediaPrice` (the Banking set); net and fee from the wallet frame | ⬜ deferred (owner 2026-11-27: no more paid proofs; capture passively from real traffic, RECIPES "Paid flow up to 3DS" → "Later, from real traffic"). A fan card + billing address are now saved; every charge needs the owner's 3DS approval — the 2026-11-26 $3 sub attempt cancelled unapproved, $0 charged. |
| 6.8 | paid subscription, not a gift code | the paid-sub code (15006 or 15016) and its price key; once it lapses, `recent_expired_subscribers` and `resubscribe_user` | ⬜ deferred (owner 2026-11-27: no more paid proofs; capture passively from real traffic, RECIPES "Paid flow up to 3DS" → "Later, from real traffic"). A fan card + billing address are now saved; every charge needs the owner's 3DS approval — the 2026-11-26 $3 sub attempt cancelled unapproved, $0 charged. |
| 6.9 | chat tip | 7001's price key, and the unit of a message's `totalTipAmount` | ⬜ deferred (owner 2026-11-27: no more paid proofs; capture passively from real traffic, RECIPES "Paid flow up to 3DS" → "Later, from real traffic"). A fan card + billing address are now saved; every charge needs the owner's 3DS approval — the 2026-11-26 $3 sub attempt cancelled unapproved, $0 charged. |

## Done condition
Every row ✅ or ⛔. §1.10 and §4.2 may end ⛔ ("needs a real money event, not
forceable on a test account") — that is an acceptable terminal state, but only
after it is stated explicitly with the reason.
