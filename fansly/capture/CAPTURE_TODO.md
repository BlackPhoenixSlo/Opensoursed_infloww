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
| 1.6 | typing frame (IN) | ⛔ | **Not producible by us.** The IN typing frame requires the COUNTERPARTY to type while we record; we cannot make another person type. Structure is known from the OUT side: the broadcast we captured is `serviceId:5 type:22 typingAnnounceEvent{accountId,groupId,lastAnnounce}` carrying OUR accountId — a fan typing emits the same event with theirs (same relationship §1.3 proved for messages). Expected, NOT observed. Closes for free if it ever fires while a recorder is attached. |
| 1.7 | notification push | ⛔ | **Not producible on this account.** Every notification type requires a THIRD PARTY to act on us (follow us, like, tip, buy, subscribe) — verified: our own follow generated notifications for THEM, and `/notifications` gained no row. 0 followers, 0 subscribers, so none can be manufactured. **Substantially answered anyway**: notification-bearing events push per-service as ServiceEvents, and `notification type == serviceId×1000 + eventType` — observed on both sides for follows (WS `serviceId:3 type:2/3` ↔ notification 3002/3003). See RECIPES. |
| 1.8 | subscribe / room-join frames | ✅ | **No subscribe/join frame exists.** After `t:1` auth the client sends only `p` keepalives, yet receives events for a group it never named → the socket is a per-account firehose. Relay needs no per-group subscription tracking. Also: duplicate frames are normal (same ackCommand 4x in 3s) — dedupe on (serviceId, type, messageIds). |
| 1.9 | ping cadence + reconnect/resume | ✅ | **CAPTURED run-20260901-1953.** Reconnect = ~1.5s delay, then a FULL re-auth (`t:1` with the same token); `session.id` constant, `websocketSessionId` newly minted each connect and never echoed back → **no resume protocol**, a plain retry loop is correct. Ping cadence **CORRECTED**: not 25.0s — measured 20–45s across 4 runs, consistent with an idle timer reset by other traffic. Implement as unconditional `p` every ≤20s. |
| 1.10 | tip / purchase push | ⛔ | **Requires spending real money.** A tip or purchase cannot be manufactured without a charge, and the loop is forbidden from spending. Predicted shape from the namespace rule: tip = `serviceId:7 type:1`, media purchase = `serviceId:2 type:7|8`. Unconfirmed. |

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
| 3.4 | `follow_user`, `unfollow_user`, `like_post`, `like_message`, `resubscribe_user`, `recent_expired_subscribers` | ⛔ | 4 of 6 captured (follow_user ✅, unfollow_user ✅, like_message ✅). `like_post` needs a post WITH media, which needs a vault upload that CANNOT be deleted (§3.11) — permanent litter on the user's account for a minor row. `resubscribe_user` + `recent_expired_subscribers` need expired subscriptions; this account has 0 subscribers and 0 expired. Terminal without a populated account. |
| 3.5 | `iter_online_subscribers` | ⛔ | Mechanism identified and fields proven (`lastSeenAt` recency, NOT `statusId` — a dormant control account also reports `statusId:1`). Cannot be exercised: `/subscribers` returns `{totalActive:0,totalExpired:0,total:0}`, so there are no subscribers to iterate. Terminal without a populated account. |
| 3.6 | `send_mass_message` | ⛔ | Endpoint family found (`POST /message/broadcast`; `GET /message/broadcast/scheduled` confirmed 200). The composer is NOT reachable on this account — three UI surfaces checked — presumably gated on having subscribers (0 here). The send BODY cannot be captured without actually blasting, which is forbidden. Terminal without a subscriber-bearing account. |
| 3.7 | `create_post` | ✅ | **CAPTURED run-20260901-2049.** `POST /api/v1/post` with `{content,fypFlags,inReplyTo,quotedPostId,attachments,scheduledFor,expiresAt,postReplyPermissionFlags,pinned,wallIds,pinWallIds}`. `wallIds` is REQUIRED (the profile wall id, from the account's `walls`). `scheduledFor:0` = post now; non-zero schedules it. Test post created and DELETED (verified gone). |
| 3.8 | `post_story_from_url` | ⛔ | Read/delete/view/order endpoints known (`/stories`, `/stories/order`, `/mediastories`, `/mediastory/delete`, `/mediastory/view`); **no create path exists in the client bundle**, and no story composer is reachable on web (the profile "+ New" is Create New Album). Story creation appears to be mobile-app-only. The media-upload prerequisite IS now solved (§3.11), so this needs the create call observed from the mobile client. |
| 3.9 | `delete_post`, `delete_story` | ⛔ | `delete_post` ✅ (`POST /post/{id}/delete`, no body). `delete_story` cannot be captured because no story can be CREATED on web (§3.8) — nothing to delete. `/mediastory/delete` is the known path. |
| 3.10 | `cancel_scheduled` | ✅ | ✅ **CAPTURED run-20260901-2049** (post lane). Schedule via the normal create with a non-zero `scheduledFor`, which is **MILLISECONDS** (readback: "Will send on Tuesday, Sep 8, 2026"). `GET /api/v1/post/scheduled` → `{scheduledPosts:[{postId,accountId,status,postTemplate,scheduledFor}]}`. Cancel = `POST /api/v1/post/scheduled/{postId}/cancel` (no body) → status 3. Verified queue 1→0. ⚠️ `POST /post/{id}/delete` on a SCHEDULED post 422s `{code:99,'error getting post'}` — a queued post is not a post. **Third distinct delete shape** (message=body, post=path/delete, scheduled=path/cancel). Mass lane: `/message/broadcast/scheduled` read confirmed (§3.6); its cancel not captured (cannot create a broadcast on this account). |
| 3.11 | `hide_vault_media`, `vault_media_lookup_hash` | ⛔ | **MEDIA UPLOAD ✅ FULLY CAPTURED** — the project's biggest gap, see RECIPES. `hide_vault_media` is terminal: **no vault-delete endpoint exists in the client**. `/vault/albums/media/delete` only UNLINKS from an album (verified — media remained), and `/account/media/{id}/delete` wants an accountMedia GRANT id, not a vault mediaId. `vault_media_lookup_hash` has no counterpart either. ⚠️ vault uploads appear PERMANENT — an operational constraint for any relay media send. Leftover: `zz-capture-test.jpeg` in the vault. |
| 3.12 | `create_promo` | ⛔ | Endpoint found (`POST /api/v1/subscriptions/promotions` via `editPlanPromotion`). Cannot be exercised: a promo is a discount ON a subscription plan and `account.subscriptionTiers` is EMPTY. Capturing it requires creating a subscription tier — configuring the user's monetization and pricing — which is outside a capture session's remit. Needs the user to set up a tier. |

## 4. Earnings / sales row shape

| # | item | status | note |
|---|---|---|---|
| 4.1 | endpoints located | ✅ | `GET /api/v1/account/wallets/earnings/stats?before&after&limit&offset` and `/monthlystats?before&after`. Supersedes the seven 404'd probes in the parity doc. |
| 4.2 | populated row shape | ⛔ | **Requires real revenue.** `GET /account/wallets/earnings/{stats,monthlystats}` are confirmed live (§4.1) but return `totalGross:0` / `[]` because this account has never earned. A populated row shape cannot be produced without a real transaction, and the loop cannot spend. |

## 5. Native features worth knowing before we rebuild them

| # | item | status | note |
|---|---|---|---|
| 5.1 | `GET /api/v1/message/automated` | ✅ | ✅ **FULL CRUD CAPTURED + VERIFIED LIVE** (run-20260901-2049). Fansly's native welcome-bot; the client calls it `chatBotApiService_`. `GET /api/v1/message/automated` (list), `POST /message/automated` (create), `/message/automated/edit`, `POST /message/automated/{id}/delete` with body `{}`. Create body: `{id:null,accountId:null,delay:0,triggerType:3,messageTemplate:{content,attachments:[]}}`. **triggerType 3 = on follow** — matches §1.3, where following a creator instantly delivered her welcome DM. Create/delete return a bare STRING not the object, so re-GET the list for the new id. Round trip verified: create 200 → listed → delete 200 → list empty. `messageTemplate.attachments` accepts media, so a welcome DM can carry a vault mediaId (§3.11). |
| 5.2 | notification type-code map | ✅ | ✅ **Full type→label map recovered** from the client's own `this.filters=[…]` table in `main.<hash>.js`, and `15011` CONFIRMED against live data (the row's stated done-condition). 24001/24002=Fansly Alerts, 1002/2002/5003=Likes, 1004=Post Replies, 1005=Post Quotes, **7001=Tips**, 3002/3003=Followers, **2007/2008=Media Purchases**, 15006/15016=Subscribers, 15007=Expired Subscriptions, 15011=Promotions, 32007=Locked Text Purchases, 45012=Stream Ticket Purchases. 🔑 **7001 and 2007/2008 route around two blockers the parity doc calls dead ends** — tips and the PPV 'fan actually paid' signal, both of which it reports as unavailable because every sales endpoint 404s. `metadata` shape for those codes is UNVERIFIED (null on every 15011 seen). |

## Done condition
Every row ✅ or ⛔. §1.10 and §4.2 may end ⛔ ("needs a real money event, not
forceable on a test account") — that is an acceptable terminal state, but only
after it is stated explicitly with the reason.
