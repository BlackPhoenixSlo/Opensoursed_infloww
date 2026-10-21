# Fansly wire recipes (captured, not inferred)

Every entry here was taken off a live frame or request. The run that produced it
is named. Do not add an entry from reading the JS bundle.

Auth headers on every apiv3 call (from `POST /api/v1/message/ack`, run-20260901-1940):

```
authorization:        <session token>          # same value as fansly_session.json .token
fansly-client-id:     900521399312150528       # = localStorage device_device_id
fansly-session-id:    900521453779398657
fansly-client-check:  1d25443307032d           # derived; the relay already recomputes this
Content-Type:         application/json
```

---

## Realtime socket — `wss://wsv3.fansly.com/?v=3`

Origin `https://fansly.com`. No auth headers on the handshake; auth is in-band.

```
OUT  {"t":1,"d":"{\"token\":\"<session token>\",\"v\":3}"}
IN   {"t":1,"d":"{\"session\":{...,\"websocketSessionId\":\"...\"}}"}
OUT  p                                  # keepalive, bare literal — see cadence note below
IN   {"t":2,"d":"{\"lastPing\":<ms>}"}
```

**Envelope for everything else — `t:10000`, and the payload is TRIPLE-encoded:**

```
{"t":10000,"d":"{\"serviceId\":<N>,\"event\":\"<JSON string>\"}"}
                 ^ d is a JSON string   ^ event is a JSON string INSIDE that string
```

So decoding is: `json.loads(frame)["d"]` → `json.loads(that)["event"]` → `json.loads(that)`.

### serviceId map (confirmed by capture)

Matches the ServiceIds table the vault album names came from (`PostService:1,
MessageService:5`) — so the same enum governs both.

| serviceId | service | seen event types |
|---|---|---|
| 3 | FollowService | `type:2` follow added, `type:3` follow removed |
| 4 | read receipts | `type:2` `ackCommand` (inner `type:1`=delivered, `type:2`=read), `type:4` `userSettings` |
| 5 | MessageService | `type:1` `message`, `type:10` deleted, `type:22` `typingAnnounceEvent` |
| 8 | presence/status | `type:1` `status` |

### 🔑 ONE namespace: `notification type == serviceId × 1000 + eventType`

The WS `serviceId`, the REST notification `type`, and the vault album `type` are
all the same enum. The parity doc already established `album type = 1000 ×
serviceId` (PostService:1 → 1000, MessageService:5 → 5000). The notification
codes decompose the same way, and the FollowService capture pins it on both sides:

| notification type | = service × 1000 + event | corroboration |
|---|---|---|
| 3002 / 3003 "Followers" | svc **3**, ev 2 / 3 | WS `serviceId:3 type:2` (follow) and `type:3` (unfollow) observed — BUT the REST row for a follow is **3003**, not 3002, and an unfollow emits NO row (it deletes the 3003 row). The namespace holds for the service, **not** for the event digit. See "Two-account evidence" below. |
| 1002 Likes, 1004 Post Replies, 1005 Post Quotes | svc 1 (Post) | album type 1000 = Posts |
| 5003 Likes | svc 5 (Message) | album type 5000 = Messages |
| 2007 / 2008 Media Purchases | svc 2 (Media), ev 7 / 8 | album 2007 = Purchases |
| 7001 Tips | svc **7**, ev 1 | — |
| 15006 / 15007 / 15011 / 15016 | svc 15 (Subscriptions) | — |
| 24001/24002, 32007, 45012 | svc 24 / 32 / 45 | — |

**Consequence for the relay:** a tip should arrive on the socket as
`serviceId:7 type:1`, and a media purchase as `serviceId:2 type:7|8` — a
REALTIME trigger for `tip_reward` and for the PPV unlock chip, alongside polling
`/notifications`.

Confidence: the arithmetic holds for all 12 notification codes and agrees with
the independently-derived album enum, and the follow pair is observed on both
sides. The tip/purchase serviceIds are **predicted, not observed** — no tip or
purchase has happened on this account. Confirm before shipping.

### Captured events

**typing announce** (serviceId 5, type 22):
```json
{"type":22,"typingAnnounceEvent":{
  "accountId":"700237824869654528","groupId":"700241627807342593",
  "lastAnnounce":1788284544531}}
```

**read receipt** (serviceId 4, type 2):
```json
{"type":2,"ackCommand":{
  "groupId":"700241627807342593","messageIds":["900522640977133571"],
  "userId":"700237824869654528","userReadReceiptsEnabled":true,
  "type":2,"recipients":[{"userId":...}]}}
```

**message** (serviceId 5, type 1) — run-20260901-1948:
```json
{"type":1,"message":{"type":1,"attachments":[],"content":"hey",
  "groupId":"700241627807342593","senderId":"700237824869654528","inReplyTo":"",
  "interactions":[{"groupId":"...","userId":"500365665494917120",
                   "readAt":0,"deliveredAt":0,"messageId":"900528581705445378"}],
  "id":"900528581705445378","createdAt":1788284926.39,"embeds":[]}}
```
**Our own sends ECHO back on this socket** — same as OF. Any relay pump MUST
dedupe against its own sends or every outbound is persisted twice.
`createdAt` is float epoch SECONDS, not ms. Ids are snowflake strings.

**INBOUND is the SAME event with a different `senderId`** — observed
(run-20260901-2049), not inferred:
```json
{"type":1,"message":{
  "type":1,"senderId":"500251712226222080",        ← the fan, not us
  "groupId":"900544249083420672","id":"900544249226047488",
  "correlationId":"900544249037303808",
  "attachments":[{"contentType":1,"contentId":"700306063047811072",
                  "messageId":"900544249226047488","pos":0}],
  "interactions":[{"groupId":...,"userId":"<us>","readAt":0,"deliveredAt":0,
                   "messageId":...}],
  "createdAt":1788288661.818,"embeds":[],"content":"..."}}
```
Direction is `senderId != own accountId`. On an outbound send `correlationId`
was `"0"`; on this inbound it carried a real id.

Also seen: **`serviceId:4 type:4`** = `userSettings`
`{groupId,userId,userSettings:{hidden:0}}`, emitted when a new group appears.

---

## Automated messages — Fansly's NATIVE welcome-bot (full CRUD, verified live)

The client calls this service `chatBotApiService_`. This is Fansly's own
auto-reply feature, and it may be a better substrate for welcome/auto-reply on
the Fansly path than re-implementing the relay's queue.

```
GET  /api/v1/message/automated                    → {"response":[ …rules… ]}
POST /api/v1/message/automated                    create
POST /api/v1/message/automated/edit               edit
POST /api/v1/message/automated/{id}/delete   {}   delete (body is literally {})
```

Create body (the client's own `createModel`, confirmed by a live round trip):
```json
{"id":null,"accountId":null,"delay":0,"triggerType":3,
 "messageTemplate":{"content":"Thank you for following.","attachments":[]}}
```
* `triggerType: 3` = **on follow** — matches the behaviour observed when
  following a creator instantly delivered her welcome DM (§1.3).
* `delay` is in the model; 0 = immediate. Other trigger types not enumerated.
* `messageTemplate.attachments` accepts media, so a welcome DM can carry a
  vault `mediaId` from the upload flow above.

Create returns a bare string (`"automated message created"`), NOT the object —
re-`GET` the list to obtain the new `id`. Delete likewise returns
`"automated message deleted"`.

Verified end to end: create → 200, list → 1 row with the right content, delete →
200, list → 0.

---

## Notification type codes — recovered from the client's own filter table

```
GET /api/v1/notifications?before=0&after=0&type=
→ {"notifications":[{id,accountId,type,correlationId,correlationGroupId,
                     acknowledgedAt,createdAt,metadata}]}
GET /api/v1/notifications/unack          → badge
```

`type` map, lifted from `this.filters=[…]` in `main.<hash>.js` (the client's own
type→label table, so these are Fansly's names, not guesses):

| type(s) | meaning |
|---|---|
| 24001, 24002 | Fansly Alerts |
| 1002, 2002, 5003 | Likes |
| 1004 | Post Replies |
| 1005 | Post Quotes |
| **7001** | **Tips** |
| 3002, 3003 | Followers |
| **2007, 2008** | **Media Purchases** |
| 15006, 15016 | Subscribers |
| 15007 | Expired Subscriptions |
| 15011 | Promotions |

**Observed live, 2026-09-02 (second account `fantester` as counterparty):**
3003 (follow), 5003 (message like), 1002 (post like), 1004 (post reply), 15011.
`metadata` was null on every one of them. Everything else in this table is
still the client's label, not a captured row.
| 32007 | Locked Text Purchases |
| 45012 | Stream Ticket Purchases |

### 🔑 This is a route around two blockers the parity doc calls dead ends

`FANSLY_PARITY_STATUS.md` records that **tips** and the **PPV "fan actually
paid" signal** are both blocked because every creator-side sales endpoint 404s
(`/account/media/purchases`, `/purchases`, `/statements`, `/account/sales`,
`/payments/statements`, `/messagepurchases`, …), and `transactions()` is an empty
stub as a result.

But notifications carry those events directly:
* **`7001` = Tips** → a trigger for `tip_reward` / `tip_ladder` that does not
  need the transactions ledger at all.
* **`2007, 2008` = Media Purchases** → the "the fan bought it" signal the unlock
  chip needs, which the doc says has no source.

Both are POLLABLE over plain REST (`/notifications`), and both should also push
over the WS as `t:10000` ServiceEvents once the socket is wired.

**Not yet verified**: no tip or purchase has occurred on this account, so the
`metadata` payload for 7001/2007/2008 is unseen — `metadata` was `null` on every
15011 row observed. Confirm the shape against a real event before shipping.

---

## Unread counting — `total` is NOT the unread count

Measured with 3 genuinely-unread messages outstanding:

```
GET /message/unread   → {"total": 0,  "messageInteractions":[ 3 rows ]}
GET /messaging/groups → luz melinda unreadCount:1 , bonnie blue unreadCount:2
```

`total` reported **0** while three messages were unread, so it counts something
else (or is unused). The trustworthy signals, which agree with each other:

* per-group **`unreadCount`** on `/messaging/groups` — 1 + 2 = 3, and
* the number of `messageInteractions` rows whose `userId` is our own account
  and whose `readAt` is null — 3.

Drive the inbox badge from `unreadCount`; never from `total`. (Same shape of
trap as `statusId`: the obviously-named field is the wrong one.)

**presence** (serviceId 8, type 1) — fires ~every 95s unprompted:
```json
{"type":1,"status":{"accountId":"700237824869654528","statusId":1,
  "lastSeenAt":1788284489386,"updatedAt":1788284489386}}
```

### Keepalive cadence — NOT a fixed interval

Measured OUT-`p` gaps across four runs: `25.0, 25.0, 25.0, 23.95, 24.92, 24.04,
21.38, 42.69, 22.34, 20.03, 45.06, 30.6, 40.32, 37.84`. Range 20–45s.
An earlier note in this file claimed "exactly 25.0s" — that was one quiet window
and it is **wrong**. The pattern fits an idle timer reset by other traffic (long
gaps only occur when service events were flowing). Safe implementation: send `p`
unconditionally every ≤20s; do not try to reproduce the client's timer.

### Reconnect: full re-auth, no resume

Forced by closing the socket from JS (see note below). Sequence:
```
<Closed>
  ~1.5s later
<Created> → <HandshakeRequest> → <HandshakeResponse>
OUT {"t":1,"d":"{\"token\":\"<same token>\",\"v\":3}"}
IN  {"t":1,"d":"{\"session\":{... "websocketSessionId":"<NEW>" ...}}"}
```
`session.id` is constant across reconnects (900521453779398657 in every run);
`websocketSessionId` is **newly minted each connect** and the client never sends
it back. So there is no resume protocol — a dropped pump just re-auths with the
same token. Relay reconnect can be a plain retry loop.

**Capture note:** `Network.emulateNetworkConditions {offline:true}` does NOT tear
down an already-established WebSocket — the fansly socket kept pinging straight
through a 12s "offline" window, and the Closed/handshake events that appeared
belonged to Intercom's socket. To force a real disconnect, inject at
document_start via `Page.addScriptToEvaluateOnNewDocument` a wrapper that pushes
every `new WebSocket` into `window.__socks`, reload, then call `.close()` on the
wsv3 one.

### No subscribe/join frame exists

After the `t:1` auth the client sends **nothing** but `p` keepalives, yet
receives events for a group it never named. The socket is a per-account
firehose: one connection gets everything for the account. The relay does not
need to track per-group subscriptions.

### Duplicate frames are normal

The same `ackCommand` arrived 4x within 3s (identical payload). Dedupe by
`(serviceId, event.type, messageIds)` — do not treat repeats as new events.

---

## `POST /api/v1/message` — send

```
POST https://apiv3.fansly.com/api/v1/message?ngsw-bypass=true
{"type":1,"attachments":[],"likes":[],"content":"hey",
 "groupId":"700241627807342593","scheduledFor":0,"inReplyTo":null,
 "createdAt":1788284926.278}
→ {"success":true,"response":{...message object...}}
```
Note `likes:[]` and a float-seconds `createdAt` that the browser sends; the
response echoes the message WITHOUT `embeds`, while the WS event includes it.

---

## `POST /api/v1/status` — announce own presence

```
POST https://apiv3.fansly.com/api/v1/status?ngsw-bypass=true
{"statusId":1}
→ {"success":true,"response":{"accountId","statusId":1,"lastSeenAt","updatedAt"}}
```
`statusId:1` = online. Broadcast as the serviceId-8 event. Relevant to §3.5
(`iter_online_subscribers`) — this is the WRITE side; the read side is still open.

---

## `POST /api/v1/message/typing` — emit the typing indicator

```
POST https://apiv3.fansly.com/api/v1/message/typing?ngsw-bypass=true
{"groupId":"700241627807342593"}
→ 200
```

**The indicator is sent over REST, not the socket.** The server then broadcasts
the `serviceId:5 type:22` frame above to the group. This means the relay can
implement `emit_typing` for Fansly **without any WebSocket** — unlike OF, where
`of_ws.send_typing` must push a frame on the live pump.

Not yet measured: re-announce interval, and how the indicator clears (OF's
auto-clears; assume nothing here until captured).

---

## `POST /api/v1/message/ack` — mark messages read

```
POST https://apiv3.fansly.com/api/v1/message/ack?ngsw-bypass=true
{"messageIds":["900522640977133571"],"type":2}
→ {"success":true}
```

Takes **message ids, not a group id** — which is why every group-shaped probe
(`/message/markread`, `/messaging/groups/markread`, `/messaging/groups/{id}/read`)
404'd. `type:2` is the ack kind; it matches `ackCommand.type` in the WS
broadcast. `type:1` is presumably "delivered" (the `deliveredAt` stamp seen
without a `readAt`) — NOT yet confirmed, do not ship that assumption.

Fires automatically when the web client opens a thread.

---

## Reads confirmed this run

| endpoint | note |
|---|---|
| `GET /api/v1/notifications?before=0&after=0&type=` | real rows: `{id,accountId,type,correlationId,correlationGroupId,acknowledgedAt,createdAt,metadata}`. `type:15011` seen. |
| `GET /api/v1/notifications/unack` | badge source |
| `GET /api/v1/message/unread?limit&offset&before` | `{total, messageInteractions:[{messageId,groupId,userId,deliveredAt,readAt,deletedAt,attachments}]}` |
| `GET /api/v1/message/automated` | Fansly's NATIVE automated-message feature. `[]` on this account. |
| `GET /api/v1/lists/account?itemId=` | lists; `[]` here. `messaging/groups` accepts `listIds=`. |
| `GET /api/v1/account/wallets/earnings/stats?before&after&limit&offset` | earnings ledger; `[]` (no revenue) |
| `GET /api/v1/account/wallets/earnings/monthlystats?before&after` | `{year,month,totalGross,totalNet,topPercent,maxTopPercent,brackets}` |
| `GET /api/v1/group/{groupId}/` | single group |
| `GET /api/v1/streaming/followingstreams/online` | presence — check for §3.5 |

---

## Message + thread action inventory (run-20260901-1959)

What the UI actually offers, which bounds what the shim can implement.

**Per-message (on hover):** reply · heart/like · `+` → emoji reaction picker
(😂 😮 😢 ❤️ 🔥 👍 👎) · trash/delete.
**There is no pin.** OF's `pin_message`/`unpin_message`/`get_pinned_messages`
have no Fansly counterpart — make them permanent no-ops (done; the chat's Pin
route reaches them). `automations/_pins.py` is since retired.

**Thread `···` menu:** Mark as Unread · Mute · Disable Read Receipts ·
Add to List · Notes · Earnings · Tips · Block · Unfollow · Subscribe to · VIP.

Roadmap this gives us (each still needs its request captured):
| shim method | UI path |
|---|---|
| `add_user_to_list` | thread ··· → Add to List |
| `unsend_message` | hover message → trash |
| `like_message` | hover message → heart |
| `block_user` | thread ··· → Block |
| `unfollow_user` | thread ··· → Unfollow |
| mark-unread | thread ··· → Mark as Unread (pairs with `/message/ack`) |

---

## `POST /api/v1/message/delete` — unsend a message

```
POST https://apiv3.fansly.com/api/v1/message/delete?ngsw-bypass=true
{"messageId":"900528581705445378"}
→ {"success":true,"response":{ ...full message..., "deletedAt":1788285922 }}
```
UI path: hover your own message → trash → "Are you sure? / Do you want to Delete
this message?" → Yes. Only ONE call fires; the confirm is client-side.

Broadcast as **`serviceId:5 type:10`** carrying the whole deleted message object.
So serviceId 5's type map so far: `1`=message, `10`=message deleted, `22`=typing.

### ⚠️ Timestamp units are MIXED on the same object

From the delete response, verbatim:
```
"createdAt":     1788284926          seconds
"deletedAt":     1788285922          seconds
"interactions[0].deliveredAt": 1788284931529   MILLISECONDS
```
And the same `createdAt` arrives as a FLOAT (`1788284926.39`) on the WS message
event but an INT on REST. Any parser must normalise per-field, not per-object —
treating `deliveredAt` as seconds puts it in the year 58680, and treating
`createdAt` as ms puts it in 1970.

`interactions[].readAt` stayed `0` here while `deliveredAt` was set: 0 means
"not yet", not "unknown".

---

## Message reactions = OF's `like_message`

There is no separate "like". The heart+plus control opens a 7-emoji reaction
picker; picking one IS the like. The emoji elements are `div.emoji <name>`
sprites with NO text content, so a text-based selector finds nothing — select by
class.

```
POST /api/v1/message/like?ngsw-bypass=true
{"messageId":"900522640977133571","type":1}
→ {"success":true,"response":{accountId,messageId,type,groupId,id}}

POST /api/v1/message/like/remove?ngsw-bypass=true
{"messageId":"900522640977133571","type":1}
→ {"success":true,"response":{...same id...}}
```

`type` is the REACTION KIND. Picker order is
`cry-laugh, surprised, sad, heart, fire, thumbs-up, thumbs-down` and **heart is
`type:1`** — captured. Heart is index 3 in that list, so type is NOT the index;
the other six codes are UNKNOWN and must not be guessed.

## Follow / unfollow

```
POST /api/v1/account/{accountId}/followers/remove?ngsw-bypass=true   (no body)
→ {"success":true,"response":{followerId,accountId,id,createdAt}}     UNFOLLOW ✅

POST /api/v1/account/{accountId}/followers?ngsw-bypass=true          (no body)
→ 422 {"success":false,"error":{"code":5,"details":"you can not follow"}}
```
**BOTH CONFIRMED** (run-20260901-2049, net-zero round trip on a free account):
```
POST /api/v1/account/500251712226222080/followers          (no body)
→ {"success":true,"response":{followerId,accountId,id,accountSortOrder,followerSortOrder}}

POST /api/v1/account/500251712226222080/followers/remove   (no body)
→ {"success":true,"response":{followerId,accountId,id,createdAt}}
```

### The 422 is account policy, not a bad request

An earlier note here said follow "has never been observed to succeed" after 422s
on two accounts. That was a sampling problem, not an endpoint problem — **both
test targets happened to be unfollowable**:

| target | result | why |
|---|---|---|
| `wallet` (500140849416269824) | 422 code **2** | reserved/system account |
| `bonnieblue` (500365665494917120) | 422 code **5** | switched to paid-only; free follow no longer offered |
| `LuzMelinda` (500251712226222080), free | **200** | ordinary free creator |

So `follow_user` is shippable. Handle 422 as "this account does not accept a
free follow" — a normal outcome to surface, not a retryable error. The two codes
distinguish the reasons (2 vs 5), though only these two samples are observed.

---

## Lists (OF's `add_user_to_list` family)

`GET /api/v1/lists/account?itemId=` returns ONLY user-created lists. The
Blocked / Muted / VIP / DM Allow rows in the UI are **client-side built-ins**,
not rows from this endpoint — an empty `[]` does not mean "no lists".

```
POST /api/v1/lists?ngsw-bypass=true
{"label":"zz-capture-tmp","description":""}
→ {"success":true,"response":{accountId,type:1,label,id:"900537126601601024"}}
```

Membership is a **batched command API**, and the two directions have
**different payload shapes** — this is the trap:

```
ADD     POST /api/v1/lists/commands?ngsw-bypass=true
{"listCommands":[{"type":1,"listItem":{"id":"<accountId>","listId":"<listId>"}}]}

REMOVE  POST /api/v1/lists/commands?ngsw-bypass=true
{"listCommands":[{"type":2,"listId":"<listId>","itemIds":["<accountId>"]}]}
```
`type:1` = add, singular `listItem{id,listId}`.
`type:2` = remove, `listId` alongside a plural `itemIds[]` array.
Both echo the command array back in `response`. A shim that assumes one shape
for both will silently no-op one direction.

UI path: thread `···` → Add to List → tick the list → Save.

**Not captured:** deleting a list. Its `···` row menu does not respond to a
synthetic `.click()` (likely a CDK overlay wanting a trusted event).

---

## MEDIA UPLOAD — the flow the parity doc records as missing

Four steps, and **a different host**: `mediav2.fansly.com`, not `apiv3`. Any
relay allowlist / client that only knows apiv3 cannot upload.

**1 — create the upload**
```
POST https://mediav2.fansly.com/api/v1/media/upload/create?ngsw-bypass=true
{"fileSize":179,"mimeType":"image/png","fileName":"zz-capture-test.png",
 "uploadFormData":{"formInputs":[
   {"type":1001,"value":"false"},{"type":1002,"value":"false"},
   {"type":1003,"value":""},{"type":1004,"value":""},{"type":1005,"value":"\"\""}]}}
→ {id, accountId, type:1, fileSize, fileName, mimeType,
   partSize:20971520, status:2,
   parts:[{index:0, uploadUrl:"https://fansly-upload.s3-accelerate.amazonaws.com/<acct>/<id>?…"}]}
```
`partSize` is 20 MiB — a larger file returns multiple `parts`, each with its own
presigned URL carrying `partNumber` + `uploadId`.

**2 — PUT the bytes straight to S3** (presigned; no Fansly auth header)
```
PUT <parts[i].uploadUrl>          body = raw file bytes
→ 200, empty body. The ETag is in the RESPONSE HEADER: ETag: "93bf23…"
```

**3 — complete** (echo each part's ETag back, **quotes included**)
```
POST https://mediav2.fansly.com/api/v1/media/upload/complete?ngsw-bypass=true
{"id":"900551936026308608","type":1,"partSize":20971520,"status":0,
 "parts":[{"index":0,"eTag":"\"93bf238fb9eff41e29ff1f73af3f5e60\""}],
 "waitForComplete":0}
→ status 3
```

**4 — poll until ready**
```
GET https://mediav2.fansly.com/api/v1/media/upload/{id}?ngsw-bypass=true
→ status 3 → 4 → 5 → 6
```
`mediaId` is **null until status 6**, then it is assigned — and that `mediaId`
(not the upload `id`) is the vault media you attach to a message or post.

**Fansly TRANSCODES.** A PNG went in; the vault holds
`zz-capture-test.jpeg`, `image/jpeg`. Do not assume the stored mime/extension
matches what you uploaded.

The upload `id` and the resulting `mediaId` are different snowflakes
(`900551936026308608` → `900551952321183744`).

### Vault deletion — NOT solved
- `POST /vault/albums/media/delete {albumId, mediaIds}` → 200, but it only
  UNLINKS from an album; the media stays in the vault (verified).
- `POST /account/media/{id}/delete` (from `deleteAccountMedia` in the bundle)
  → 422 `account media id not found` when given a vault mediaId — that route
  wants an **accountMedia grant id**, which is minted per-send, not the vault id.
  **Verified 2026-09-02: given a grant id it returns 200 and the grant is gone** —
  so a grant minted for a test can be cleaned up even though the vault item cannot.
- No endpoint that removes media from the vault has been found. OF's
  `hide_vault_media` may have no Fansly counterpart, or it is the album unlink.

---

## Posts — create and delete

```
POST /api/v1/post?ngsw-bypass=true
{"content":"test","fypFlags":0,"inReplyTo":null,"quotedPostId":null,
 "attachments":[],"scheduledFor":0,"expiresAt":0,
 "postReplyPermissionFlags":[],"pinned":0,
 "wallIds":["900264702215319552"],"pinWallIds":[]}
→ {"success":true,"response":{accountId,content,...,"id":"900546198725955584",
    mediaLikeCount,totalTipAmount,...}}
```
`wallIds` is required and is the profile's wall id — get it from the account's
`walls` field. `scheduledFor:0` means post now (non-zero schedules it, which is
the same lane as the scheduled-post queue).

```
POST /api/v1/post/{postId}/delete?ngsw-bypass=true      (NO body)
→ {"success":true,"response":null}
```

### ⚠️ Delete is inconsistent across resources — id in PATH vs BODY

| resource | shape |
|---|---|
| message | `POST /message/delete` with body `{"messageId": "..."}` |
| post    | `POST /post/{postId}/delete` with **no body** |

I lost time guessing here: `/post/delete` and `/post/remove` with a
`{"postId"}` body both 404, and `DELETE /post/{id}` is blocked by CORS
preflight. Do not generalise one resource's delete shape to another.

Post `···` menu also offers: Copy post link, **Pin post**, Manage Walls, Edit
post, Delete post. Note POSTS can be pinned even though MESSAGES cannot (§3.2).

## Scheduled posts (OF's `cancel_scheduled`, post lane)

Schedule by giving the ordinary create a non-zero `scheduledFor`:

```
POST /api/v1/post   { ...as above..., "scheduledFor": 1788894787000 }
```
**`scheduledFor` is MILLISECONDS** — confirmed by readback ("Will send on
Tuesday, Sep 8, 2026"). Note the create RESPONSE omits the post `id` for a
scheduled post; get it from the queue as `postId`.

```
GET  /api/v1/post/scheduled?ngsw-bypass=true
→ {"scheduledPosts":[{postId,accountId,status,postTemplate,scheduledFor}],
   "aggregationData":{...}}

POST /api/v1/post/scheduled/{postId}/cancel?ngsw-bypass=true    (NO body)
→ {"success":true,"response":{"scheduledPosts":[{...,"status":3,...}]}}
```
`status:3` = cancelled. Verified: queue went 1 → 0.

### ⚠️ A THIRD distinct delete shape

`POST /post/{id}/delete` on a SCHEDULED post returns
`422 {"code":99,"details":"error getting post"}` — a queued post is not yet a
post. Running tally of this API's delete/cancel shapes:

| resource | shape |
|---|---|
| message | `POST /message/delete` + body `{"messageId"}` |
| live post | `POST /post/{id}/delete`, no body |
| scheduled post | `POST /post/scheduled/{id}/cancel`, no body |

Three resources, three conventions. Derive each one; never generalise.

### Technique: pick a timestamp that is safe under either unit

`scheduledFor`'s unit was unknown, and guessing seconds when it wanted ms would
have put the time in the past and **published immediately**. Instead pick a value
that is in the future under BOTH readings — `1788894787000` is +7 days as ms and
the year ~58000 as seconds. The readback then reveals the true unit at zero risk.
Worth reusing anywhere a timestamp unit is unverified on this API.

---

## Presence — and why `statusId` is NOT the online flag

Every account object (from `GET /account?ids=` and from `/messaging/groups`'s
`aggregationData.accounts`) carries:

```
"statusId":   1
"lastSeenAt": 1788287553000     MILLISECONDS
```

**Do not read `statusId == 1` as "online".** Measured across three accounts:

| account | statusId | lastSeenAt | actually online? |
|---|---|---|---|
| bonnieblue (UI says "Active Now") | 1 | 1788287553000 | yes |
| founder (us, logged in) | 1 | 1788287617000 | yes |
| `wallet` (dormant, never seen) | **1** | **0** | almost certainly not |

`statusId` is 1 for a dormant account too, so it is an account-level status, not
presence. The discriminating field is **`lastSeenAt` recency** (`0` = never
seen); the UI's "Active Now" is almost certainly computed from it. The exact
staleness threshold is NOT captured, and no other `statusId` value has ever been
observed — so the enum is unknown, not "1 = online".

There is **no `/status?ids=` read endpoint** (404). Own-presence is written with
`POST /api/v1/status {"statusId":1}`; others' presence arrives free on any
account object, and live changes push as WS `serviceId:8 type:1`
`{status:{accountId,statusId,lastSeenAt,updatedAt}}`.

So `iter_online_subscribers` would be: `GET /subscribers` → batch
`GET /account?ids=` → filter on `lastSeenAt` recency (NOT `statusId`), with the
serviceId-8 WS event for live updates. **Unverified end-to-end** — this account
has 0 subscribers (`/subscribers` → `{totalActive:0,totalExpired:0,total:0}`).

---

## Mass message — Fansly calls it BROADCAST

OF's `send_mass_message` maps to Fansly's *broadcast*. The UI for it is **not
reachable on this account** — the pencil and the envelope+ on /messages both
open a "Select a List" dialog that merely adds an inbox FILTER chip, and the
Creator Dashboard has no mass-message section. It is presumably gated on having
subscribers (this account has 0).

CONFIRMED live (read):
```
GET /api/v1/message/broadcast/scheduled?ngsw-bypass=true
→ {"success":true,"response":{"scheduledBroadcastMessages":[],"groups":[]}}
GET /api/v1/message/broadcast        → 404 (send path is POST-only)
```

FROM THE JS BUNDLE, NOT YET EXERCISED — treat as a lead:
```
POST /api/v1/message/broadcast              the send
     /api/v1/message/broadcast/scheduled/   scheduled broadcast ops
```
Client symbols: `onMassMessageSend`, `isBroadcast`, `broadcastGroup`,
`getScheduledBroadcastMessages`, `app-broadcast-message-history`. The history
view tracks `stats_total`, `stats_read`, `stats_sales` per broadcast.

**The send body is NOT captured** and cannot be on this account without actually
blasting. Do not ship `send_mass_message` from the path alone.

`/message/broadcast/scheduled` also covers OF's `cancel_scheduled` for the mass
lane — see §3.10.


## Two-account evidence (prompt 06, 2026-09-02) — what a real counterparty proved

Fan `fantester` (900604711209099264) acting on creator `founder`
(700237824869654528), both driven from the CDP rig; creator socket tailed with
`tail_ws.py` (raw frames in `/tmp/creator_ws_raw.jsonl` during the run). Fan-side
request shapes recorded under `out/fan-a*/`.

### Notification PUSH exists: `serviceId 9`

Every REST notification row arrived on the creator's socket first, as
`serviceId:9 type:1 {notification:{...the row...}}`, and the deleted follow row
arrived as `serviceId:9 type:3`. So realtime notifications are wired at the
transport; polling `/notifications` is a fallback, not the only path.

```
{"serviceId":9,"event":{"type":1,"notification":{"accountId":"7899…","type":3003,
  "correlationId":"<follow row id>","correlationGroupId":"<follower id>",
  "lookups":[{"lookupId":"<follow row id>"}],"id":"…"}}}
```

### Which id is the actor — differs per code

| code | correlationId | correlationGroupId | actor |
|---|---|---|---|
| 3003 follow | follow row id | **follower account** | correlationGroupId |
| 1002 post like | **liker account** | post id | correlationId |
| 5003 message like | like row id | message id | none on the row |
| 1004 post reply | reply post id | root post id | none on the row |

The shim's `_NOTIF_ACTOR_FIELD` encodes this; unlisted codes default to
`correlationGroupId`.

### Follow / unfollow, the notification side

- Follow: WS `3/2 {follow:{followerId,accountId,id,accountSortOrder}}` then
  `9/1` with the **3003** row. Label "followed you" is correct.
- Unfollow: WS `3/3` then `9/3` — and the 3003 row is **removed** from
  `/notifications` (7 rows → 6). **There is no unfollow notification.** 3002 has
  never been observed.
- Re-follow from the same account after an unfollow: 200, new row, no 422.

### Message read receipts on the socket

`serviceId:4 type:2 ackCommand{groupId,messageIds[],userId,type,recipients[]}`
where `ackCommand.type` **1 = delivered** (auto, one per message on receipt) and
**2 = read** (our `/message/ack`). Read state propagates to
`/messaging/groups.unreadCount` and `interactions[].readAt` a few seconds AFTER
the ack returns — an immediate re-read still shows the old count. `readAt` is
`0` (not null) while unread, ms when read.

### `/message/unread` is a LIST, not a total

It returns unread interaction rows (`messageId, groupId, userId, deliveredAt,
readAt:null…`). On this account it holds two stale rows Fansly will neither
return from `/message` nor ack, so its length overstates unread by 2 forever.
Per-group `unreadCount` remains the badge source.

### Typing, inbound — captured

```
{"serviceId":5,"event":{"type":22,"typingAnnounceEvent":{"accountId":"<fan>",
  "groupId":"<group>","lastAnnounce":1788331314802}}}
```
Fires once per burst, ~every 5s while typing. Recommendation: still YAGNI — no
automation reads it and the UI has no typing indicator for Fansly today.

### Message like from the fan side — same call

`POST /message/like {"messageId","type":1}` — identical shape from either side.
Liking your OWN message returned 200 (the shim docstring said the API refuses
it; it does not). The creator's like of a fan message arrives on the fan's side
as `serviceId:5 type:3 {like:{accountId,messageId,type,groupId,id}}`.

### Post replies are posts, and nest one level only

Comment = `POST /postreply/verify {"inReplyTo":<post>}` (200, `response:null`)
then `POST /post {..., "inReplyTo":<post>, "wallIds":[]}`; the reply carries
`inReplyToRoot`. Broadcast as `serviceId:1 type:1 {post}` plus the 1004 push.
Verifying `inReplyTo` = a **reply** id → **400 code 99 "error getting posts"**:
there are no nested replies, so 1005 ("Post Quotes") cannot be reached through
the reply path and the fan's post menu exposes no quote action either.
Post like: `POST /likes {"postId"}` → `{accountId,postId,id}`.
Post delete broadcasts `serviceId:1 type:5 {post:{..., "delitionType":0}}`.

### Subscription tiers — there is NO free tier

`POST /subscriptions/tiers` body: `{id:"",accountId:"",name,color,price:<cents>,
pos,maxSubscribers,maxSubscribersReached,subscriptionBenefits[],includedTierIds[],
options[],plans:[{id:"",subscriptionTierId:"",status:1,billingCycle:30,
price:<cents>,useAmounts:0,uses:0,promos:[]}]}` → the tier with ids. The UI
refuses any price under **$5/month** ("minimum subscription price"). A
"free" subscription is a **gift code** on a paid plan:

```
POST /subscriptions/giftcodes
{"id":"","label","planId","price":0,"duration":7,"maxUses":100,
 "newSubscribersOnly":1,"startsAt":0,"endsAt":0}
→ {id,type:1,label,planId,accountId,price:0,paymentMethodRequired:0,duration,
   maxUses,newSubscribersOnly,startsAt,endsAt,status:1,originalPrice:5000,code}
link: https://fansly.com/subscriptions/giftcode/<code>
```

Redeeming from the fan side goes through the generic order flow —
`POST /productorders {"items":[{"productType":15001,"productPrice":0,
"productId":<planId>,"metadata":"<json: subscriptionTierId,planId,giftCode,
autoRenew:1,billingCycle:30,price:0,renewPrice:0,...>"}]}` → an order with
`status:0`, then a "Confirm your Order / Pay" dialog. **Pay on a $0 gift order
is refused without a card on file** — "Payment method required … to claim a
gift subscription" — even though the gift code itself answers
`paymentMethodRequired: 0`. That field describes the code, not the checkout.
**The trial auto-renews at the plan price after `duration` days** unless
cancelled; the fan wallet was $0 with no payment method during this run, so the
subscribe stayed at order `status:0` and no 15006 was produced.

### A6/A7 — the first subscriber (gift-code trial, paid with a card on file)

Fan side: `POST /subscriptions {id:"",accountId:<creator>,subscriberId:"",
subscriptionTierId,planId,promoId:null,giftCode,...}` → **400 code 6101
"no wallets"** until a card exists, then 200 with the subscription
(`status:2`). Creator socket, in order:

```
serviceId 15 type 5 {subscription:{... status:2, price:0, giftCodeFree:true, renewPrice:5000, duration:7}}
serviceId 15 type 5 {subscription:{... status:3, subscriptionTierName, endsAt, subscriptionStreak:0 ...}}
serviceId 9  type 1 {notification:{type:15016, correlationId:<historyId>, correlationGroupId:<subscriber>, metadata:"{\"subscriptionStreak\":0}"}}
```

So a free-trial subscribe is **15016, not 15006** — 15006 is still unobserved.
`metadata` is NON-NULL for the first time: a JSON **string**
`{"subscriptionStreak":0}`. Actor is `correlationGroupId` (same as follows).

Creator side, `GET /subscribers` → `{stats:{totalActive,totalExpired,total},
subscriptions:[row]}` — the real row is `capture/fixtures_subscribers.json`:
`{id,historyId,subscriberId,subscriptionTierId,subscriptionTierName,
subscriptionTierColor,planId,promoId,giftCodeId,paymentMethodId,status:3,
price:0,renewPrice:5000,renewCorrelationId,autoRenew:1,billingCycle:30,
duration:7,renewDate,version,createdAt,updatedAt,endsAt,promo*:null}`.
Money is 1/1000 $, times are **ms** (notification rows are seconds).
`/account/me.subscriberCount` still said 0 minutes later — do not read it.

Gift codes: **disable** = re-POST the whole object to `/subscriptions/giftcodes`
with `status:2` (captured from the Disable button). No delete verb.

The welcome for this fan had ALREADY been sent at 06:17 on the 3003 follow
(`welcome_sent` ledger), so `send_welcome` correctly deduped the 15016 row:
`subscribers_seen:1, new_subscribers:0`. The "Hey J-J-J-Juicy" DM in the fan
inbox IS that welcome — the chain fired end to end on the follow.

### Broadcast — first real send (one-account list)

`POST /message/broadcast` (same body as `/message`, group type 3) **answers a
bare scalar in `response`**, not a message object. On the wire it works:
`serviceId 5 type 1 {message:{type:3, groupId:<broadcast group>, correlationId:<group>}}`
then, per recipient, `{message:{type:2, correlationId:<broadcast msg id>,
groupId:<that fan's DM group>, interactions:[...]}}` — the copy lands in the
ordinary thread with the broadcast id as its correlationId.

### PPV purchase, fan side (B2)

Unlock dialog → `POST /productorders {"items":[{"productType":2010,
"productPrice":3000,"productId":<accountMedia id>,"metadata":null}]}` → order
`status:0`, then the same "Confirm your Order / Pay" dialog as subscriptions.
`productType` **2010** for a message media unlock (15001 was the subscription).
The accountMedia id is the message attachment's `contentId`, not the vault id.

Paid (2026-09-02, $3, real card): the fan client first tops the wallet up in
exactly the order's amount — `POST /orders {correlationId:<productorder>,
items:[{productId:"2",productName:"$0.01 Tipping Balance",quantity:300,price:10}],
walletId,...}` — then buys the grant: `POST /media/<accountMediaId>/order
{"permissionFlagsId":<grant id>}` → `{accountMediaId, correlationAccountId,
productOrderId, creditTransactionId, orderMetadata:{orderType:1,
accountMediaPrice:3000, permissionFlags:{...}}}`. Creator socket, in order:

```
serviceId 2 type 7 {order:{orderId, accountMediaId, correlationAccountId:<creator>, accountId:<buyer>, type:1, orderMetadata:{accountMediaPrice:3000}}}
serviceId 6 type 3 {transaction:{type:2110, destinationWalletId, status:1, amount:3000, destinationTax:2000, destinationAmount:2400, correlationId:<accountMediaId>}}
serviceId 9 type 1 {notification:{type:2007, correlationId:<accountMediaId>, correlationGroupId:<buyer>, metadata:"{\"accountMediaPrice\":3000}"}}
```

So **2007 = media purchase is OBSERVED** (the namespace prediction `serviceId 2
type 7` held for the order frame). `metadata` is the JSON string
`{"accountMediaPrice":<1/1000 $>}`. Actor is `correlationGroupId` (the buyer),
the media is `correlationId`. `destinationTax` is Fansly's cut: 2000 of 3000 =
**20 %** here (labelled tax, and it is the platform fee). 2008 remains
unobserved. Tip (7001) still not observed.

### Subscriber cancels auto-renew (fan side)

Gear on the subscription card → "Don't Renew Subscription" →
`POST /subscription/<subscriptionId>/cancel` (no body) → the subscription with
`autoRenew:0`, `status` still **3** (active until `endsAt`). The creator socket
gets a `serviceId 15 type 5` subscription frame with the new `autoRenew`;
**no notification row** is emitted for a cancel. So `subscribers()` keeps the
fan active (correct) and `subscribedOnData.renew` flips to false.

## Three loose ends closed (2026-09-02, creator rig :9223)

### `/notifications/unack` — per-code unread totals, the bell's source

```
GET /api/v1/notifications/unack
→ [{"type":1002,"total":1},{"type":1004,"total":1},{"type":2007,"total":1},
   {"type":3003,"total":1},{"type":5003,"total":1},{"type":15016,"total":1}]
```
Live with six `acknowledgedAt: null` rows on `/notifications`; the bell showed
**6** = the sum. Earlier captures saw `[]` only because everything was acked.
`notifications_count` keeps deriving from the feed (one fetch, badge == list);
this endpoint is the cross-check.

### "Mark as Unread" is client-local — `mark_chat_unread` stays a no-op

Thread ··· menu → "Mark as Unread" sends
```
POST /api/v1/message/ack {"messageIds":["<oldest fan message>"],"type":4}   → 200
```
(the message it picked was the fan's FIRST message of the thread, not the
newest). The envelope badge went to **1** immediately — and `Page.reload`
cleared it. Server state never moved: `/messaging/groups` row stayed
`unreadCount:0, lastUnreadMessageId:null`, `/message/unread.total` stayed 0.
The same type-4 ack sent from the shim (newest and oldest fan id, both tried)
changed nothing either. So ack `type` is: **1 delivered, 2 read, 4 "unread"
(client hint, no server effect)**. OF's mark-unread cannot be reproduced;
the shim's `{success:true}` no-op is the honest mapping.

Also noticed on the way: the web's message list requests `flags=0` (all) and
`flags=32` (empty here — probably requests/pinned). The shim maps
`filter="unread"` to `flags=2`, which returned this group with `unreadCount:0`
and `flags:6` (bit 2 set), so `flags=2` is a membership bit, **not** an unread
selector. Nothing consumes that filter on Fansly today; left as a note.

### OF account 8000149 on proxy `hu-3` is NOT down

Relay log 08:13–10:15 today: 238 successful `ingest_tx_fast` calls vs 26
final `proxy_error` (after 3 retries) on hu-3, and 4 on hu-2 for 80000112.
The `of-ws` socket logged 4 CONNECT 403s at startup, then connected (no
further `ws error` lines in two hours). Failure mode is an intermittent
`CONNECT tunnel failed, response 403` from the proxy (~10 % of calls),
absorbed by `_proxy_retry`. Nothing to fix in this repo; if it worsens, it is
a proxy-vendor ticket, not a code change.
