# Static values — Fansly

The Fansly twin of [../STATIC_VALUES.md](../STATIC_VALUES.md). Same purpose: one
map of every constant the auth path depends on, so when something breaks you
know which value to change and where it lives.

Unlike the OF file, this one is also the write-up the brief asked for — the
header map, the signed-string spec, and where the constants came from all live
here rather than in a separate `NOTES.md`.

Every row is tagged:

- **✅** — reproduced from our own capture. `test_har_replay.py` rebuilds the
  browser's requests and asserts on them; **30/30 `fansly-client-check` digests
  and 11/11 captured writes match**.
- **📄** — read straight out of `main.14d24b3e179efdb7.js` (fetched
  2026-08-31) but not exercised by the capture. Solid, unproven.
- **❓** — still unknown.

Re-run the gate any time:

```
../venv/bin/python test_har_replay.py            # replay + verify, offline
../venv/bin/python bootstrap_from_har.py X.har --chunk main.js
```

---

## 1. Where the session lives

Fansly does not authenticate with cookies. One `localStorage` blob carries
everything, and two separate Angular interceptors read from it:

| what | value | tag |
| ---- | ----- | --- |
| localStorage key | `session_active_session` | ✅ |
| key construction | storage helper prefix `session_` + `active_session` | 📄 |
| blob shape | `{"id", "accountId", "deviceId", "token", "metadata"}` | 📄 |
| `token` → | `authorization: <token>` — **raw, no `Bearer ` prefix** | 📄 |
| `id` → | `fansly-session-id` header | ✅ |
| `accountId` → | us, the sender | ✅ |
| device id key | `device_device_id` (prefix `device_` + `device_id`) | 📄 |
| storage prefix default | `fansly_` when a service passes no override | 📄 |

To read it, on an authenticated tab:

```js
JSON.parse(localStorage.session_active_session)   // .token, .id, .accountId
```

🚨 **Chromium's "Export HAR (sanitized)" strips `authorization`.** Our capture
came out that way — everything else survived, and the signer verified against
it, but the token has to be supplied separately
([bootstrap_from_har.py](bootstrap_from_har.py) says so and takes `--token`).

The email 2FA ("login from a new device") gate is completed once, by a human, in
a real browser. It produces the blob above and is never automated around.

---

## 2. API constants

| name | value | where | tag |
| ---- | ----- | ----- | --- |
| `API_BASE` | `https://apiv3.fansly.com/api/v1` | [fansly_client.py:40](fansly_client.py#L40) | ✅ |
| admin base | `https://adminv2.fansly.com/api/v1` | bundle const `Ee_adminApiBaseUrl` | 📄 |
| `ORIGIN` | `https://fansly.com` | [fansly_client.py:41](fansly_client.py#L41) | ✅ |
| `REFERER` | `https://fansly.com/` | [fansly_client.py:42](fansly_client.py#L42) | ✅ |
| `DEFAULT_TIMEOUT_S` | `30` | [fansly_client.py:43](fansly_client.py#L43) | — |
| `NGSW_PARAMS` | `ngsw-bypass=true` on **every** call | [fansly_client.py:46](fansly_client.py#L46) | ✅ |
| `Accept` | `application/json, text/plain, */*` | [fansly_client.py:169](fansly_client.py#L169) | ✅ |
| `Content-Type` | `application/json` — **only when there is a body** | [fansly_client.py:182](fansly_client.py#L182) | ✅ |
| `MESSAGE_TYPE_TEXT` | `1` | [fansly_client.py:50](fansly_client.py#L50) | ✅ |
| response envelope | `{"success": true, "response": …}`; failures carry `{"error": {"code", "details"}}` | [fansly_client.py:239](fansly_client.py#L239) | ✅ |
| User-Agent | **not a constant** — must match the capturing browser | | ✅ |
| TLS impersonation | not needed. Plain `requests` reproduces every call; no `curl_cffi` | | ✅ |

The four Fansly headers, all attached by one interceptor (`class tQ`):

| header | contents | § |
| ------ | -------- | - |
| `fansly-client-id` | device id | §5 |
| `fansly-client-ts` | jittered client clock, ms | §6 |
| `fansly-client-check` | the signature | §3 |
| `fansly-session-id` | session blob's `id` | §7 |

CORS preflight: the browser sends an `OPTIONS` before each call with
`Access-Control-Request-Headers: authorization,fansly-client-check,fansly-client-id,fansly-client-ts,fansly-session-id`.
Ours does not, and every replayed call is byte-identical without it — the
preflight is the browser's, not the app's.

---

## 3. The signature: `fansly-client-check`

The OF analogue is the sha-1 + 32-index checksum in
[../service/of_signer.py](../service/of_signer.py). Fansly's is much weaker.

**Signed string** — [fansly_signer.py:131](fansly_signer.py#L131) ✅:

```
f"{check_key}_{url_path}_{device_id}"
```

`url_path` is `new URL(url).pathname`. **Path only.** No method, no body, no
query string, no timestamp. Three consequences, all confirmed in the capture:

1. The digest is **stable per path** and the client caches it (LRU 100 —
   [fansly_signer.py:191](fansly_signer.py#L191)). Every `POST /api/v1/message`
   in our HAR carries the identical `1fdc56c42db2db`.
2. It rotates only when the check key or the device id rotates.
3. `fansly-client-ts` is sent but is **not** hashed, so clock skew cannot break
   a signature.

Worked example, against the (gitignored) test capture's device id:

```
cyrb53("necvac-govry3-tybkYz_/api/v1/message_700174924320792578").toString(16)
  = 1fdc56c42db2db          # the exact header the browser sent
```

**Hash: cyrb53** — a 53-bit non-cryptographic string hash, not sha-1.
[fansly_signer.py:103](fansly_signer.py#L103):

| constant | value | line |
| -------- | ----- | ---- |
| seed | `0` | — |
| `h1` init | `0xDEADBEEF` (3735928559) | [64](fansly_signer.py#L64) |
| `h2` init | `0x41C6CE57` (1103547991) | [65](fansly_signer.py#L65) |
| per-char multiplier h1 | `2654435761` | [66](fansly_signer.py#L66) |
| per-char multiplier h2 | `1597334677` | [67](fansly_signer.py#L67) |
| finalizer A | `2246822507` | [68](fansly_signer.py#L68) |
| finalizer B | `3266489909` | [69](fansly_signer.py#L69) |
| return | `4294967296 * (2097151 & h2) + (h1 >>> 0)` | [124](fansly_signer.py#L124) |

Two porting traps, both handled and both silent if you get them wrong:

- All arithmetic is JS `Math.imul` 32-bit-signed, and `>>>` is *unsigned*.
  Plain Python ints overflow into bignums and produce a wrong digest with no error.
- `charCodeAt` yields UTF-16 code units; `ord()` diverges above the BMP. Every
  input we sign is ASCII, so it does not bite here — do not reuse `cyrb53()`
  on arbitrary user text without fixing that.

Header value is JS `.toString(16)` — plain lowercase hex, no leading zeros,
which is exactly Python's `f"{n:x}"`.

---

## 4. The check key (Fansly's `2313.js`)

| name | value | where | tag |
| ---- | ----- | ----- | --- |
| `CHECK_KEY` | `necvac-govry3-tybkYz` | [fansly_signer.py:60](fansly_signer.py#L60) | ✅ |
| bundle discovery | regex `main\.[0-9a-f]+\.js` over `https://fansly.com/` or `/ngsw.json` | [fansly_signer.py:238](fansly_signer.py#L238) | ✅ |
| chunk URL | `https://fansly.com/main.<hash>.js` | | ✅ |
| chunk in this capture | `main.14d24b3e179efdb7.js` (6.6 MB) | | ✅ |

🚨 **The key is assigned twice, and the first assignment is a decoy.** In the
constructor of `class tQ`:

```js
this.checkKey_ = ["fySzis","oybZy8"].reverse().join("-") + "-bubayf";
// → "oybZy8-fySzis-bubayf"   ← decoy, overwritten below
...
let i = [];
i.push("necvac"), i.push("govry3"), i.push("tybkYz");
this.checkKey_ = i.join("-");
// → "necvac-govry3-tybkYz"   ← live
```

So we do not pick one. [`candidate_check_keys()`](fansly_signer.py#L253) returns
**both**, and [`derive_check_key()`](fansly_signer.py#L343) keeps whichever
reproduces the captured digests — the decoy is rejected because it computes
`580cc7ac8b2f9` for a path the browser signed as `1fdc56c42db2db`. This is the
Fansly analogue of OF's `derive_rules_from_chunk`, and it is the reason a
rotation is a re-run rather than a debugging session.

`ngsw.json` (the Angular service-worker manifest) is the more reliable place to
find the bundle name than the homepage HTML — the `<script src>` shape has moved
before, the manifest has not.

There is **no `rev` pin** the way OF has `x_of_rev`; the content-hashed filename
*is* the version check.

---

## 5. Device id — `fansly-client-id`

| what | value | where | tag |
| ---- | ----- | ----- | --- |
| source | `GET /api/v1/device/id` | [fansly_client.py:251](fansly_client.py#L251) | 📄 |
| headers on that call | **no `fansly-*` headers** — it is the bootstrap, it cannot sign itself | [fansly_client.py:264](fansly_client.py#L264) | 📄 |
| `DEVICE_ID_TTL_S` | `180 * 60` | [fansly_client.py:54](fansly_client.py#L54) | 📄 |

Our capture reuses a cached id throughout, so the fetch itself is 📄. Cache it
and persist the fetch time — re-fetching per run draws 429s, and it is an input
to every digest in §3, so a rotation invalidates the whole digest cache
([fansly_client.py:161](fansly_client.py#L161) rebuilds it).

---

## 6. Client timestamp — `fansly-client-ts`

```js
this.currentCachedTimestamp_ = Date.now() + (5e3 - Math.floor(1e4 * Math.random()));
setInterval(function(){
  let e = Date.now() + (5e3 - Math.floor(1e4*Math.random()));
  e > o.currentCachedTimestamp_ && (o.currentCachedTimestamp_ = e);
}, 3e3);
```

| name | value | where | tag |
| ---- | ----- | ----- | --- |
| jitter | `+5000 − floor(10000 × random())`, i.e. **±5 s** | [fansly_signer.py:73](fansly_signer.py#L73) | 📄 |
| refresh interval | `3` s, **monotonic** — kept only if greater | [fansly_signer.py:75](fansly_signer.py#L75) | ✅ |
| server drift correction | applied only past `30` s of skew | [fansly_signer.py:78](fansly_signer.py#L78) | 📄 |

Confirmed in the capture: requests inside a tick carry an *identical*
`fansly-client-ts`, and the value walks forward in ~10 s steps. A naive
`int(time()*1000)` per request is therefore a fingerprint — the real client is
never that precise, and never that fresh. [`ClientTimestamp`](fansly_signer.py#L164)
reproduces the cache + jitter rather than stamping each call.

---

## 7. Session id — `fansly-session-id`

🚨 **Correction to the public reverse-engineering.** The 2024 open-source client
obtains this over a WebSocket (`{"t":1,"d":"{token}"}` → `response.session.id`).
That is no longer how it works, and implementing it would have been wasted work:

```js
getSessionId(){ let o = this.sessionService.getActiveSession(); return o ? o.id : ""; }
```

It is just the `id` field of the §1 localStorage blob — same place as the token,
no handshake at all ✅. Sent on every call. The public source's "not on
`/account/me`" carve-out does not appear in the current bundle.

---

## 8. WebSocket — the realtime push (new messages, notifications)

This is the Fansly analogue of [../service/of_ws.py](../service/of_ws.py). Not
wired up here yet, but fully mapped from the bundle so a pump is a copy job, not
a research job. **Fansly has no webhooks** — the string does not exist in the
bundle. Like OF, it gives you a client WebSocket; you build the fan-out (OF's is
`server.py` `_WEBHOOKS_FILE`, see [§5](../STATIC_VALUES.md)).

| name | value | tag |
| ---- | ----- | --- |
| realtime URI | `wss://wsv3.fansly.com?v=3` — **one fixed host** (OF is per-shard) | 📄 |
| chat-room URI | `wss://chatws.fansly.com?v=3` — live-stream chat, separate | 📄 |
| **codec** | **plain JSON** — `decodeMessage`/`encodeMessage` are just `JSON.parse`/`stringify`; the schema-name arg is ignored. No protobuf. | 📄 |
| auth frame | on open: `{"t":1,"d":"{\"token\":\"<token>\",\"v\":3}"}` — the `d` is a JSON **string** (double-encoded), token from the §1 blob | 📄 |
| auth reply | `{"t":1,...}` `SessionVerifiedEvent` → connected | 📄 |
| keepalive | client sends the text frame `"p"` every **20–25 s** (`randomIntFromInterval(20000,25000)`); server replies `{"t":2,...}` | 📄 |
| dead timeout | no ping reply for **30 s** → reset the socket | 📄 |
| reconnect | backoff ×2, floor 1.5 s, **cap 15 s** | 📄 |

**Envelope** — every frame is `EventWrapper {t, d}`, `t` is the opcode:

| `t` | event | meaning |
| --- | ----- | ------- |
| `0` | ErrorEvent | protocol error |
| `1` | SessionVerifiedEvent | auth accepted |
| `2` | PingResponseEvent | keepalive pong |
| `10000` | **ServiceEvent** | a real push — see below |
| `10001` | batch | `d` is an array of nested EventWrappers, handled recursively |

A **ServiceEvent** (`t:10000`) is `{serviceId, event}` where `event` is *another*
JSON string `{type, ...}`. `serviceId` picks the subsystem — the full enum has
40+, the ones that matter here:

| serviceId | service | key event types |
| --------- | ------- | --------------- |
| `5` | **MessageService** | `type:1` → **new message, full object inline** (`i.message`); `22` → typing; `3`/`4` → like add/remove |
| `9` | NotificationService | notifications |
| `3` | FollowerService | follow / unfollow |
| `4` | GroupService | thread changes |
| `8` | OnlineStatusService | `type:1` → someone's online status |
| `7` / `6` | Tipping / Wallet | tips, balance |

🚨 **A new DM carries the whole message**, not a "go fetch" signal:
`{"t":10000,"d":"{\"serviceId\":5,\"event\":\"{\\\"type\\\":1,\\\"message\\\":{…}}\"}"}`
→ `onMessageCreate(message)`. So a pump can emit the message immediately, no
follow-up REST read.

**Polling fallback** (if you skip the WS): REST `/notifications`,
`/notifications/ack`, `/notifications/unack`, and `/messaging/groups` (§9) with
its `unreadCount` per thread.

This is *simpler* than OF's WS: plain JSON (OF is heavier), one fixed host (OF is
per-shard), and the message arrives inline.

---

## 9. The recreated calls

Every one of these is replayed against the capture by
[test_har_replay.py](test_har_replay.py) ✅.

### Send a text message — `POST /api/v1/message`

```json
{"type": 1, "attachments": [], "likes": [], "content": "heey",
 "groupId": "700241627807342593", "scheduledFor": 0, "inReplyTo": null,
 "createdAt": 1788190933.738}
```

🚨 `createdAt` is epoch **seconds with a millisecond fraction** — not the
millisecond integer the rest of the API uses. Response returns the message `id`,
`senderId` and per-recipient `interactions`.
[fansly_client.py:364](fansly_client.py#L364)

### Typing indicator — `POST /api/v1/message/typing`

`{"groupId": "…"}` → `{"success": true, "response": null}`. The browser fires it
before each send. [fansly_client.py:359](fansly_client.py#L359)

### Open a DM thread — `POST /api/v1/group`

```json
{"users": [{"userId": "<us>", "permissionFlags": 0},
           {"userId": "<them>", "permissionFlags": 0}],
 "recipients": [], "lastMessage": null, "userSettings": null, "type": 1}
```

Send `permissionFlags: 0`; the server answers `65535` for both members and
returns the group `id`. [fansly_client.py:333](fansly_client.py#L333)

### Find an existing thread — `GET /api/v1/messaging/groups`

`sortOrder=1&flags=0&subscriptionTierId=&listIds=&search=&limit=20&offset=0` →
rows keyed by `partnerAccountId` / `groupId`.
[fansly_client.py:289](fansly_client.py#L289)

### Follow — `POST /api/v1/account/{accountId}/followers`

**No body**, despite being a POST — no `content-type` either. Response:
`{followerId, accountId, id, accountSortOrder}`.
[fansly_client.py:306](fansly_client.py#L306)

`422 {"code": 5, "details": "you can not follow"}` is Fansly refusing the
relationship (already following, blocked, self). It is *not* a signing failure —
the capture contains one, and the digest on it was correct.

### Unfollow — `POST /api/v1/account/{accountId}/followers/remove`

No body. Response: `{followerId, accountId, id, createdAt}`.
[fansly_client.py:314](fansly_client.py#L314)

### Deliberately absent

No purchases, tips, paid-message pricing or wallet calls. The capture contains
`/payments/wallets` and `/orders/products`; they are not wired up, and adding
one needs its own review.

---

## 10. Files

| file | holds |
| ---- | ----- |
| [fansly_signer.py](fansly_signer.py) | §3 cyrb53 + §4 key derivation + §6 clock + `verify_samples()`. Pure, no I/O — mirrors [../service/of_signer.py](../service/of_signer.py). |
| [fansly_client.py](fansly_client.py) | §1 session + §2 headers + §9 calls. Mirrors [../service/of_client.py](../service/of_client.py). |
| [bootstrap_from_har.py](bootstrap_from_har.py) | HAR → `sessions/session.json`, verifying the signer in the same pass. The paste-curl analogue. |
| [test_har_replay.py](test_har_replay.py) | the gate: rebuild every captured write, assert it matches. |
| `sessions/session.json` | captured session, `0600`, gitignored. |

🚨 **[.gitignore](.gitignore) gotcha:** it ignores `*.json` at *every* depth
here, not just `sessions/`. Right for captured material — but a fixture or
config JSON you mean to commit gets dropped silently. Force-add it or give it
another extension.

---

## 11. OF ↔ Fansly delta

Why this was not a copy-paste port:

| dimension | OnlyFans | Fansly |
| --------- | -------- | ------ |
| auth carrier | cookies (`sess`, `auth_id`) + `x-bc` + `App-Token` | one `authorization` header from `localStorage` |
| signed over | path + query + `user_id` + `time` | `check_key` + path + `device_id` |
| algorithm | sha-1, 32 checksum indexes mod 40 | cyrb53, 53-bit, non-crypto |
| freshness | per-request — `time` is in the digest | per-path, cached; time is not hashed |
| constants from | `2313.js`, pinned to `x_of_rev` | `main.<hash>.js`, content-hashed name |
| obfuscation | dense numeric cluster to scrape | a decoy assignment to reject |
| device identity | `X-Hash` per user from `cdn2.onlyfans.com/hash` | `fansly-client-id` from `/device/id`, 180-min TTL |
| session handshake | none | none either — it is a field in the token blob (§7) |
| TLS fingerprint | `curl_cffi` impersonation required | plain `requests` works |
| human-in-the-loop | paste-curl capture | paste-curl capture **+ one-time email 2FA** |

The one that cost real time: **the decoy check key**. The one that saved it:
the session id turning out to be a field, not a WebSocket round-trip.

---

## 12. Not constants

Per-session, captured, never hard-coded:

- `token`, `id` (session), `accountId` — the §1 blob
- `user_agent` (must match the capturing browser), and the `sec-ch-ua*` /
  `accept-language` hints stored alongside it
- `device_id` + its fetch timestamp
- `fansly-client-ts` (jittered per §6)
- `check_key` — scraped per bundle, so treat it as session state and re-scrape
  on a 403/422 storm

---

## 13. Sources

- **Our own capture** — `fanslycalls.har` (gitignored) and
  `main.14d24b3e179efdb7.js`, fetched 2026-08-31. Everything ✅ or 📄 above
  comes from these.
- [prof79/fansly-downloader-ng](https://github.com/prof79/fansly-downloader-ng)
  — the public prior art (last touched March 2024). It got the cyrb53 constants,
  the signed-string shape and the `session_active_session` key right; §7 (the
  WebSocket session handshake) is **stale** and §4's literal-matching check-key
  regex no longer describes the bundle.

Scope is unchanged from [BRIEF.md](BRIEF.md): accounts we control and are
permitted to operate, no 2FA bypass, no brute force, no DoS-scale volume.
