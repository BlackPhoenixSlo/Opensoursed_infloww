# Fansly ↔ OnlyFans parity — build spec

**Goal.** Make the whole UI work identically whether an account is OnlyFans or
Fansly: same messaging, same realtime push (new message, typing, notifications,
tips, online presence), same fan/sub/vault/stats screens. The user picks a
platform per account; nothing above the client layer should care which.

**Method note.** Every OF row below is a real method in
[../service/of_client.py](../service/of_client.py) (2,777 lines, ~130 public
methods) or an event in [../service/of_ws.py](../service/of_ws.py). Every Fansly
row is a real endpoint or `ServiceId` pulled from the live bundle
(`main.14d24b3e179efdb7.js`) and, where marked ✅, exercised against the capture
(see [STATIC_VALUES.md](STATIC_VALUES.md)). No endpoint here is invented.

**Read this first if you read nothing else:** §1 (the one seam), §6 (build
order), §8 (devil's advocate). The call tables (§3–§5) are reference.

---

## 0. The YAGNI thesis

The naïve reading of "match all OF calls" is: port all ~130 `of_client` methods
to Fansly. **Don't.** Three facts kill that plan before it starts:

1. **The UI already funnels through one seam.** The browser never calls OF. It
   calls our relay ([../service/server.py](../service/server.py)), which calls
   `OFClient` via `_load_client(account_id)`
   ([../service/server.py:1202](../service/server.py#L1202)). Swap what that
   returns and the UI is none the wiser. There is exactly **one** place to
   branch on platform, not 130.
2. **Most `of_client` methods back screens nobody uses on a second platform on
   day one.** Chargeback ratios, Spotify links, GIF trending, referral payouts,
   tracking-link revenue stats — real methods, near-zero messaging value. Build
   them when a screen 404s, not before.
3. **The money features are a small core.** DM + realtime + fans + tips is ~20
   methods. That is what "the UI works the same" actually means to a user who
   chats and sells. Everything else is Tier 2+.

So the spec is **tiered by what breaks the core UX**, and the build order (§6)
ships Tier 0 first and stops adding until a real screen demands the next call.

---

## 1. The seam (where the whole thing hooks in)

```
                    ┌── OFClient ─────→ onlyfans.com/api2/v2
browser → server.py ┤   (client_pool)
  (UI routes)       └── FanslyClient ─→ apiv3.fansly.com/api/v1     ← NEW
                        (per-account, chosen by account.platform)

realtime:  of_ws.py  ─┐
           fansly_ws  ─┴→ normalize() → _broadcast_event(server.py:701)
                                          ├→ browser /ws/events
                                          └→ SSE /events
```

**Three** branch points (an earlier draft said two — corrected after the
second-opinion pass, §9):

| seam | file / symbol | change |
| ---- | ------------- | ------ |
| **request client** | [`_load_client`](../service/server.py#L1202) / `client_pool` returns `OFClient` | return a `FanslyClient` when `account.platform == "fansly"`; both satisfy one `PlatformClient` protocol |
| **realtime pump** | [`_ws_pump_for_account`](../service/server.py#L848) hard-imports `from of_ws import OFWebSocket` ([server.py:852](../service/server.py#L852)) | branch here to start `fansly_ws.py` instead |
| **outbound typing** | [`of_ws.emit_typing`](../service/of_ws.py#L203) | Fansly typing is a REST call, not a pump frame (§5) — the `send_typing` method hides both |

🚨 **The event bus downstream of `_broadcast_event` is NOT platform-agnostic —
this was the load-bearing error in the first draft.** The pump does not emit a
neutral dict; it emits an **OF-native frame**, and two consumers read OF's shape
directly:

- [`event_transcoder.transcode`](../service/event_transcoder.py#L121) branches on
  `event_type == "api2_chat_message"` and reads `fromUser.id`, `text`,
  `createdAt`, `isTip`, `tipAmount`, `media`… verbatim.
- [`events.handle_event`](../service/events.py#L129) picks the type via
  `_first_real_key` (first non-`__` key) and routes on the **`__account_id`**
  sentinel ([events.py:143](../service/events.py#L143)).

So the Fansly pump has two honest options, and it must pick one **explicitly**
(§5) — inventing a third neutral schema (as the first draft did) routes to
nothing and silently leaves the inbox empty:

1. **Emulate** — the Fansly pump translates each `ServiceEvent` into an OF-shaped
   `{"api2_chat_message": {...}, "__account_id": ...}` frame. Zero downstream
   change; the emulation cost lives entirely in the pump.
2. **Extend** — teach `event_transcoder` + the browser client a second native
   shape. More invasive, but avoids pretending Fansly is OF.

Recommended: **emulate** for P2 (smaller blast radius), revisit if a second
platform makes the OF-mimicry ugly. Either way, parity is *not* "one normalizer,
no downstream change" — it is one adapter **that speaks the bus's existing OF
dialect**.

### The contract

Define a `PlatformClient` protocol = the **Tier-0/1 method subset** the relay
actually calls (not all 130). `OFClient` already satisfies it by accident;
`FanslyClient` implements it deliberately. Normalize IDs to strings and event
shapes to one schema (§5). The relay codes to the protocol; the account's
`platform` field picks the implementation.

---

## 2. Vocabulary map (the gotcha layer)

The two platforms name the same concepts differently. Get this wrong and every
table below reads wrong.

| concept | OnlyFans | Fansly |
| ------- | -------- | ------ |
| a DM thread | **chat**, keyed by `chat_id` = the fan's `user_id` | **group**, keyed by `groupId` (its own snowflake); the fan is `partnerAccountId` |
| the fan | `user_id` | `accountId` |
| a broadcast | **mass message** | **message/broadcast** |
| auto-DM on subscribe | **welcome message / reply-on-subscribe** | **message/automated** |
| a fan's paid tier | subscription price | **subscription tier** (`subscriptions/tiers`, multi-tier) |
| creator's media library | **vault** | **vault** (`media/vault`) + **albums** (`uservault/albums`) |
| "is typing" | **WS outbound frame** `{"act":"typing"}` | **REST** `POST /message/typing` |
| realtime channel | one WS, per-shard URL | one WS, fixed host, `ServiceId`-tagged |

🚨 **The single biggest adapter cost is the chat↔group identity mismatch.** On
OF a chat *is* the fan; on Fansly you must resolve `accountId → groupId` (find or
create the group, §3) before you can send. The client already does this
(`ensure_group`), but every messaging method must key on it.

---

## 3. Call inventory — messaging (Tier 0, the core)

This is "the UI works the same" for anyone who chats. Status legend:
✅ built & verified · 🟢 endpoint confirmed in bundle, not yet coded ·
🟠 maps with real friction · 🔴 gap / no equivalent.

| capability | `of_client` method | Fansly endpoint | status |
| ---------- | ------------------ | --------------- | ------ |
| who am I | `me()` | `GET /account/me` | ✅ |
| list DM threads | `list_chats()` | `GET /messaging/groups` | 🟢 |
| get one thread | `get_chat()` | `GET /group/{id}/` | 🟢 |
| resolve fan → thread | *(implicit, chat_id=user)* | `find_group_with()` / `POST /group` | 🟠 |
| get messages | `get_messages()` / `iter_messages()` | `GET /message?groupId=` | 🟢 |
| **send text** | `send_message()` | `POST /message` | ✅ |
| **typing indicator** | `emit_typing()` (WS) | `POST /message/typing` | ✅ |
| mark read | `mark_chat_read()` | `POST /message/ack` (`/ack/all`) | 🟢 |
| unsend | `unsend_message()` | `POST /message/delete` | 🟢 |
| like / unlike msg | `like_message()` / `unlike_message()` | `POST /message/like` (`/like/remove`) | 🟢 |
| unread counts | `unread_chat_fan_ids()` | `GET /message/unread` · `/message/undelivered` | 🟢 |
| **welcome / auto-DM** | `upsert_welcome_template()` | `GET/POST /message/automated` (`/edit`) | 🟢 |
| **mass message** | `send_mass_message()` | `POST /message/broadcast` | 🟠 |
| mass-msg history/stats | `mass_message_history()` | `GET /message/broadcast/stats` | 🟢 |
| schedule mass msg | `schedule_mass_message()` | `POST /message/broadcast/scheduled` | 🟢 |
| media in message | `chat_media()` / `send_message(media=)` | `groups/mediaoffers` + upload chain | 🟠 |
| send tip | `send_tip()` | `POST /tips` (`tips/account`) | 🟠 |

🟠 notes:
- **Resolve fan → thread**: `find_group_with()` scans only the **100 most-recent
  groups** ([fansly_client.py:319](fansly_client.py#L319)). A fan outside that
  window returns `None` → `ensure_group` creates a **duplicate** group (unless
  Fansly dedupes server-side, which the capture never proved). Downgraded from ✅
  to 🟠 by the second-opinion pass. Fix: paginate `/messaging/groups` fully, or
  key on a proven server-side dedup, before trusting it in P2.
- **Mass message**: OF takes user-id lists + exclusions; Fansly's `broadcast`
  targets by list/tier. The *audience-selection* logic differs even though the
  send is one call — budget a mapping layer.
- **Media send**: both need the upload pipeline (§4) first. Fansly attaches via
  `mediaoffers`; not yet reversed.
- **Tips**: mechanically simple; deliberately deferred — it moves money, wants
  its own review (same rule that kept it out of `fansly_client.py`).

---

## 4. Call inventory — fans, content, money (Tier 1–2)

Tier 1 = fan-management screens people use daily. Tier 2 = creator-studio
screens (posts, vault, stats, promos) — real, but not "chat works the same."

### Tier 1 — fans & relationships

| capability | `of_client` | Fansly | status |
| ---------- | ----------- | ------ | ------ |
| get user / users | `get_user()` / `list_users()` | `GET /account?ids=` · `?usernames=` | 🟢 |
| **follow / unfollow** | `follow_user()` / `unfollow_user()` | `POST /account/{id}/followers` (`/remove`) | ✅ |
| subscribers list | `subscribers()` | `GET /subscribers` · `/subscriptions` | 🟢 |
| sub counts | `subscription_counts()` | `GET /subscriptions/tiers` | 🟢 |
| **fan note** | `set_fan_note()` | `POST /notes` (`/edit` `/delete`) | 🟢 |
| **fan custom name** | `set_fan_custom_name()` | `POST /updateNickname/v1/` | 🟢 |
| block / restrict | `block_user()` / `restrict_user()` | `POST /account/ignore` · `/ignore` | 🟢 |
| lists (fan lists) | `get_lists()` / `add_user_to_list()` | `GET /lists` · `POST /lists/items/add` | 🟢 |
| labels | `add_label_to_user()` | `POST /lists/aggregate/add` *(lists double as labels)* | 🟠 |
| online subscribers | `iter_online_subscribers()` | WS `OnlineStatusService` (§5) + `GET /streaming/followingstreams/online` | 🟠 |

### Tier 2 — content, vault, stats, promos

| domain | `of_client` (examples) | Fansly | status |
| ------ | ---------------------- | ------ | ------ |
| posts | `list_posts` `create_post` `edit_post` `delete_post` `like_post` `pin_post` `comment_on_post` | `/timelinenew/{id}` `/timeline/home` `POST /post` `/post/scheduled` `/likes` `/postreply/verify` | 🟢 |
| vault | `vault_media` `vault_media_by_id` `vault_lists` `hide_vault_media` | `/media/vault` `/uservault/albumsnew` `/account/media?ids=` `/media/bundle` | 🟢 |
| stories | `my_stories` `post_story` `create_story` | `/mediastories` `POST /mediastory/*` | 🟢 |
| earnings / stats | `earning_stats` `transactions` `payout_balances` `earnings_chart` | `/account/wallets/earnings/*` `/payments/wallets/transactions` | 🟢 |
| subs config | `subscription_bundles` `create_bundle` `create_promo` | `/subscriptions/tiers` `/subscriptions/promotions` `/subscriptions/giftcodes` | 🟢 |
| tracking links | `tracking_links` `create_tracking_link` | `/trackinglinks` (`/claim` `/stats`) | 🟢 |
| templates | `message_templates` `create_template` | 🔴 **no server-side template store found** | 🔴 |
| media upload | `upload_media` `request_signed_upload` `convert_register` | signed-upload chain via `/media` (not reversed) | 🟠 |
| notifications feed | `notifications()` `notifications_count()` | `GET /notifications` `/notifications/ack` `/unack` | 🟢 |

🔴 **Templates**: OF stores message templates server-side; Fansly's bundle shows
no equivalent endpoint. If templates matter cross-platform, store them **in our
DB** and treat OF's server-side store as the exception, not the baseline. (This
is a YAGNI win — one local store beats two server integrations.)

---

## 5. Realtime parity — the push layer

This is what makes the inbox feel live: a new DM appears, "is typing" bubbles,
a tip toast fires — with no refresh. Both platforms do it over one client
WebSocket. **Neither offers HTTP webhooks** ("webhook" appears 0× in Fansly's
bundle; OF has none either). (Our own `webhooks.json` fan-out was removed in
cleanup R7.)

### The two pumps → one normalized event

| | OnlyFans (`of_ws.py`) | Fansly (`fansly_ws.py`, new) |
| --- | --------------------- | ---------------------------- |
| URL | `wss://ws2.onlyfans.com/ws3/N` (per-shard, from `/users/me`) | `wss://wsv3.fansly.com?v=3` (fixed) |
| auth | connect frame with `x-bc` / token | `{"t":1,"d":"{\"token\":\"…\",\"v\":3}"}` |
| codec | JSON | JSON (`decodeMessage`=`JSON.parse`) |
| keepalive | ping ~25 s | text frame `"p"` every 20–25 s; 30 s silence → reconnect |
| envelope | flat `{event_key: payload}` | `{t, d}`; `t:10000` = `ServiceEvent{serviceId, event}` |

**Fansly `ServiceId` → event map** (from the bundle's dispatch, §8 of
STATIC_VALUES):

| ServiceId | event | payload |
| --------- | ----- | ------- |
| **5 MessageService** | `type:1` new message | **full message inline** (no refetch) |
| 5 | `type:22` typing | `typingAnnounceEvent` |
| 5 | `type:3/4` like add/remove | `like` |
| **9 NotificationService** | notification | notification obj |
| 3 FollowerService | follow/unfollow | follower |
| 7 TippingService | tip | tip |
| 6 WalletService | balance change | wallet |
| 8 OnlineStatusService | `type:1` presence | `{accountId, statusId}` |
| 4 / 14 / 15 / 32 | group / order / subscription / story | resp. |

### What the pump must emit — speak the bus's existing dialect 🚨

**Correction (second-opinion pass, §9): there is no neutral schema.** The bus is
OF-shaped (see §1). A Fansly `MessageService type:1` event must be translated
into the **OF-native frame the transcoder already parses**, tagged with the
`__account_id` sentinel the router reads:

```jsonc
// what fansly_ws.py emits into _broadcast_event — NOT a new schema:
{ "api2_chat_message": {          // the key _first_real_key() will return
    "id": 900234348922249216,
    "text": "hey",
    "fromUser": { "id": 500365665494917120, "username": "…" },  // the fan
    "createdAt": "2026-…",
    "isTip": false, "price": 0,   // fill OF's fields from Fansly's message obj
    "media": [], "mediaCount": 0
  },
  "__account_id": "700237824869654528" }   // double-underscore, required to route
```

So the realtime work is a **field-mapper from Fansly's inline message object into
OF's `api2_chat_message` shape** ([event_transcoder.py:222](../service/event_transcoder.py#L222)
documents that shape), not a neutral normalizer. The socket plumbing is still
small (~100 lines — `fansly_client.py` already holds the token + session id); the
**mapper is the real work**, and it inherits every OF field the transcoder reads
(`isTip`/`tipAmount` for tips, `media`/`mediaCount` for attachments). Get a field
wrong and that column of the inbox is wrong.

The envelope also carries `t:1` (session handshake — must be consumed to reach
CONNECTED) and `t:10001` (a **batch array** of nested wrappers — must be
unrolled, or batched events vanish). Both are in the table above; a pump that
handles only `t:10000` silently drops them.

### Typing — the one true asymmetry 🚨

- **Inbound** (fan → us): symmetric. OF `new_message`/`typing` keys, Fansly
  `ServiceId 5 / type 22`. Both normalize to `{"type":"typing"}`.
- **Outbound** (us → fan, "creator is typing"): **different transport.**
  - OF: `emit_typing()` sends a **WS frame** `{"act":"typing","typing_to":id}`
    ([of_ws.py:74](../service/of_ws.py#L74)) — needs the open pump socket.
  - Fansly: `POST /message/typing {"groupId":id}` — a **REST** call, no socket
    needed (already in `fansly_client.py`).

  So the `PlatformClient.send_typing(peer)` method hides two transports. That is
  fine — it is *why* the seam is a method, not a raw socket. Just don't assume
  the Fansly pump must be open to show typing; the REST call stands alone.

---

## 6. Build order (YAGNI phases — ship, then stop)

Each phase is independently shippable and leaves the app working. **Do not start
phase N+1 until a real screen needs it.**

| phase | scope | ship criterion | rough size |
| ----- | ----- | -------------- | ---------- |
| **P0 — send/receive (done-ish)** | `me`, resolve group, send text, typing, follow/unfollow | ✅ already proven live (`fansly_client.py`) | done |
| **P1 — the seam** | new `account.platform` field ([accounts.py](../service/accounts.py) meta has none today); `PlatformClient` protocol; branch **all three** points (§1): `_load_client`, `_ws_pump_for_account`, `emit_typing` | an OF account and a Fansly account both load & `me()` through the relay | S–M |
| **P2 — live inbox (riskiest phase)** | `fansly_ws.py` pump + **OF-frame mapper** (Fansly msg → `api2_chat_message` shape, `__account_id` tag, §5); handle `t:1`/`t:10001`; list threads; get messages; mark read | a Fansly DM persists a Fan/Message row and appears in the UI in realtime, no refresh | **L** (not M — it's frame-emulation, and every Tier-1 fan screen depends on the rows it writes) |
| **P3 — fan ops** | subscribers, fan notes, custom name, block, lists | fan-management screens render for a Fansly account | M |
| **P4 — broadcast** | mass message + audience mapping, welcome/auto-DM | a mass message sends to a Fansly audience | M |
| **P5 — studio (on demand)** | posts, vault, stats, promos — **only the screen someone opens** | that one screen works; others stay 🔴 until opened | L, incremental |
| **never until asked** | tips-out, templates-server, GIF search, Spotify, chargeback ratio, referral payouts | — | — |

**Stop rule.** The definition of done for "UI works the same" is **P0–P4**. P5
is pull-based: a 404 in the UI is the ticket. Anything in "never" is built only
when a user asks by name.

---

## 7. Six Thinking Hats

**⚪ White (facts).** Three branch points, not 130 methods — but the bus they feed
is OF-shaped, so the Fansly pump maps into OF's frame (§5). Fansly REST ≈ 320 endpoints,
strong messaging/fan/vault/notification coverage; JSON WS with a clean
`ServiceId` taxonomy; send + typing + follow already verified live. Confirmed
gaps: server-side templates (🔴), media-upload chain (🟠, not reversed),
mass-message audience model (🟠, differs).

**🔴 Red (gut).** The send working live on the first real token is a strong
signal the platform isn't hostile to this. The chat↔group identity mismatch
*feels* like where bugs will breed. The 320-endpoint surface is intimidating but
mostly irrelevant — trust the tiering.

**⚫ Black (caution / devil's advocate → §8).** Biggest risks: the bundle can
rotate the check key or the WS schema overnight (it did to the public
downloader); the normalizer is where subtle inbox bugs hide; "match all calls"
is a scope trap that YAGNI must actively fight. Templates and upload are real
holes, not hand-waves.

**🟡 Yellow (upside).** The architecture already did the hard part — one seam,
one event bus, one fan-out. Fansly is in several ways *easier* than OF (plain-
JSON WS, fixed host, inline messages, REST typing). A clean `PlatformClient`
protocol also makes a *third* platform cheap later, and forces OF's own client
to grow a real interface (paying down existing debt).

**🟢 Green (creative).** Store templates in *our* DB and make both platforms
consume them — turns a 🔴 gap into a feature. The normalized event schema could
become a documented public webhook contract (`platform` field already carries
it). A contract test could replay both a Fansly HAR and an OF HAR through the
same `PlatformClient` assertions — one test suite, two backends.

**🔵 Blue (process).** Ship P0→P4 in order, each behind the `platform` field so
OF is never at risk. Gate each phase on the "ship criterion" in §6. Re-run the
`STATIC_VALUES` verification (`test_har_replay.py`) whenever the bundle hash
changes. Keep this doc's status column honest — it is the burndown.

---

## 8. Devil's advocate (why this could go wrong)

Argued straight, not softened:

1. **"Match all OF calls" is the wrong goal and will sink the timeline.** Taken
   literally it is ~130 methods × reverse-engineering each Fansly equivalent,
   half of them backing screens no one opens on platform #2. The *right* goal is
   "the core UX is identical." If the team measures success by call-count parity,
   they will spend weeks on chargeback ratios and Spotify links. **Mitigation:**
   §6 stop rule; success = P0–P4, not coverage %.

2. **The abstraction leaks at the identity layer.** OF `chat_id == user_id`;
   Fansly `groupId != accountId`. A `PlatformClient` that pretends these are the
   same will produce "sent to the wrong thread" bugs the moment a fan has two
   groups, or a group is created twice in a race. **Mitigation:** the protocol
   keys messaging on `(account_id, peer_id)` and resolves `thread_id`
   *internally*; never let a caller pass a raw id that means different things per
   platform.

3. **The realtime schema is a moving target.** The public downloader died when
   Fansly changed the check key from a literal to an expression. The WS
   `ServiceId`/`type` codes are equally unversioned. A pump hard-coding
   `type:1 == new message` breaks silently — no error, just a dead inbox.
   **Mitigation:** the normalizer logs unknown `(serviceId, type)` pairs loudly;
   a canary test asserts a known Fansly account still emits `message.new`.

4. **Mass message is not one call, it's an audience engine.** OF's mass-send
   takes explicit user lists with exclusions; Fansly broadcasts to
   lists/tiers. "Send to all fans who tipped last week" may be expressible on one
   and not the other. **Mitigation:** treat P4 audience-mapping as its own design
   task; don't promise identical targeting semantics until it's spiked.

5. **Two live sessions double the auth-fragility surface.** Every account now has
   a token that can rotate, a device id with a TTL, a check key pinned to a
   bundle hash. Twice the "why did this account go silent" pages. **Mitigation:**
   one health probe per platform that does a signed `me()` and surfaces the
   failure mode (401 vs bundle-rotation vs device-id) distinctly.

6. **YAGNI vs. a real promise.** If a customer was *sold* "full Fansly parity,"
   YAGNI-deferring vault/stats/promos is a broken promise, not a clean scope cut.
   **Mitigation:** confirm the actual commitment before hiding behind tiers — the
   tiering is an engineering strategy, not a substitute for knowing what was
   promised.

**The one-line verdict:** the architecture makes this *tractable* (three branch
points into one OF-dialect bus), Fansly is friendlier than OF on the wire, and the dominant risk is not
technical — it is scope discipline. Build P0–P4, keep the status table honest,
and let real 404s pull the rest.

---

## 9. Second-opinion pass

An independent engineer reviewed the first draft against the actual repo and the
Fansly bundle, told to attack it. **Verdict: ship with fixes.** The architecture
and YAGNI framing hold; the draft's "downstream doesn't change at all" claim was
factually wrong and load-bearing. Its findings are already folded into §1, §3,
§5, §6 above. Recorded here so the reasoning isn't lost:

**Confirmed by re-checking the source:**

1. 🔴 **The event bus is OF-shaped, not neutral.**
   [`event_transcoder.transcode`](../service/event_transcoder.py#L121) branches on
   `event_type == "api2_chat_message"` and reads OF fields verbatim;
   [`events.handle_event`](../service/events.py#L143) routes on the `__account_id`
   sentinel via `_first_real_key`. The draft's `{"type":"message.new",…}` schema
   would have routed to nothing — inbox silently empty. → §1, §5 rewritten to
   **emulate OF's frame**.
2. 🟠 **`find_group_with` scans only 100 groups** → duplicate group on the long
   tail. → §3 downgraded ✅→🟠.
3. 🟠 **Three branch points, not one.** `account.platform` doesn't exist yet;
   the pump ([server.py:852](../service/server.py#L852)) and `emit_typing` are
   separate hard imports of `of_ws`. → §1 table, §6 P1 re-scoped.
4. ⚪ **P2 is the riskiest phase and was under-sized** — it's frame-emulation,
   and every Tier-1 fan screen reads the rows it writes. → §6 P2 M→L.

**Strongest single objection (accepted):** the plan's tractability rested on "one
seam, one bus that doesn't change." The bus *is* OF-shaped, so P2 is an
OF-emulation task, not 100 lines of plumbing — and the fan screens inherit that
dependency. The size estimate was the thing most wrong, and it's now corrected.

**Where the draft held up under scrutiny:** the codec really is plain JSON
(`decodeMessage`=`JSON.parse`); the `ServiceIds` enum matches exactly; the auth
frame and the cited line numbers check out; nothing was wrongly deferred by
YAGNI (media/mass-message/templates correctly flagged 🟠/🔴).

**Net:** the honest headline changed from *"two adapters + one normalizer, no
downstream change"* to *"two adapters + one OF-dialect frame-mapper; P2 is the
real work."* Same architecture, truthful sizing.
