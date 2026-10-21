# Direct Login: Recreation Spec

This is a self-contained spec for "direct login": getting a creator's OnlyFans
(OF) session into a relay service **without a browser extension**. It is
distilled from a working implementation. It is meant to be copied into a
different but similar project and implemented there, so it names roles and
contracts, not file paths.

Terms used throughout:

- **Relay**: the backend service that holds OF sessions and makes signed OF
  API calls for creators. In the reference it is a Python FastAPI app.
- **Web app**: the operator-facing frontend. In the reference it is Next.js
  with React Query. It talks to the relay under `/admin/*` through a
  same-origin rewrite.
- **Session file / session record**: what the relay stores per OF account
  after a capture: cookies, signed-request headers, and signing rules. Every
  login mode writes **the same shape** the host project's existing capture
  path (for example "paste a curl") writes. Downstream code must not be able
  to tell how a session was obtained.
- **Proxy registry**: the relay's list of egress proxies, each with a label,
  and a binding from OF account to proxy (an account has at most one proxy; a
  proxy may serve many accounts).

Everything here is **additive**. Existing ways to add a session (paste-curl,
antidetect-browser capture, proxied Playwright capture, the extension, the
desktop capture window) stay as they are.

---

## 1. Overview: three modes

| mode | what the relay does | user interaction |
| --- | --- | --- |
| **direct-api** | Signs and POSTs OF's `/api2/v2/users/login` itself over plain HTTPS (Chrome TLS impersonation), through the account's proxy. | None, unless OF wants a 2FA code or a captcha. |
| **remote-browser** | Drives its own proxied Chromium on the relay host, types the credentials into OF's real login form, and only shows the page to the user when a human check appears. | Click the Cloudflare / Google / OF captcha in a popup; type a 2FA code into a field in the web app. |
| **refresh** ("update the curls") | Re-harvests headers and signing rules for an account that is **already logged in** (new `x-of-rev`, rotated `static_param`), using the stored browser profile or the latest session's cookies. | None, unless a challenge appears. |

When each is used:

- **direct-api** is the first attempt for every new login from the web card.
  It is fast and needs no browser on the relay host.
- **remote-browser** is the fallback for anything direct-api cannot finish
  headless. It is also the only path that can **seed signing** for a brand-new
  OF revision (see 4.4).
- **refresh** is a per-account action ("Refresh session") on the accounts
  list. It needs no credentials.

The only UI that ever shows OF's page is the challenge popup, and only while a
captcha is actually on screen.

---

## 2. Decision flow

```
user submits {email, password, proxy choice, nickname?, make_active}
        |
        v
POST /admin/login/direct
   |-- 200 {ok:true, ...}             -> done. Clear the password. Refresh account lists.
   |-- 200 {ok:false, needs:"otp"}    -> POST /admin/login/remote/start (same body)
   |-- 200 {ok:false, needs:"browser"}-> POST /admin/login/remote/start (same body)
   |-- 5xx                            -> POST /admin/login/remote/start (same body)
   '-- 4xx {detail}                   -> show detail, stop (input problem)

remote job: poll GET /admin/login/remote/{job_id}
   state "challenge" (popup:true)  -> open ChallengePopup (SSE frames + input)
   state "otp" (otp_needed:true)   -> show a 2FA field -> POST .../otp {code}
   state "done"                    -> show account id, clear password, refresh lists
   state "error" | "cancelled"     -> show message + "Try again" (reruns the whole flow)
```

Rules that matter:

- direct-api returns `needs:"browser"` for **anything** it cannot positively
  handle: Cloudflare HTML, non-JSON bodies, a missing x-of-rev, a failed x-bc
  fetch, an unseeded revision, a chunk the signer cannot parse, rules that fail
  to verify, and **every OF error code other than the two known 2FA codes**.
  That includes a wrong password (see 4.6). The user then finishes in OF's own
  form, which shows OF's real error.
- On `needs:"otp"` the web UI does **not** resend to direct-api with `otp`. A
  resend starts a fresh cookie session, and the field name OF uses for the code
  is unconfirmed. 2FA is handed to the remote browser, which types the code
  into OF's real 2FA form.
- Only input validation is a 4xx: missing email or password, an unknown
  `proxy_label`, a malformed pasted `proxy` line, or a pasted proxy the caller
  does not own.

---

## 3. HTTP API contract

All routes live under `/admin/` and sit behind the same auth as the relay's
existing session-bootstrap endpoint (see section 8). Bodies are JSON.

### 3.1 `POST /admin/login/direct`

Request:

| field | type | required | meaning |
| --- | --- | --- | --- |
| `email` | string | yes | OF account email |
| `password` | string | yes | OF password. Never stored or logged. |
| `otp` | string | no | 2FA code for a resend. Best-effort; the web UI never sends it. |
| `proxy_label` | string | no | Registry label to route the login through. |
| `proxy` | string | no | One pasted proxy line (any format in 5.3). Used only when `proxy_label` is empty: the relay registers it and continues as if `proxy_label` had been sent. |
| `static_param_override` | string | no | Operator-supplied `static_param` for an unseeded revision. A reusable signing profile is still required (4.4). |
| `nickname` | string | no | Friendly label stored in account meta. |
| `make_active` | bool | no, default `true` | Make this the relay's active account. |

Responses:

```
200 {ok:true,  account_id, user_id, x_of_rev, session_file}
200 {ok:false, needs:"otp",     message}
200 {ok:false, needs:"browser", message}
400 {detail}   missing email/password; unknown proxy_label; bad pasted proxy ("proxy: <reason>")
403 {detail}   pasted proxy label exists and is not the caller's ("proxy: not your proxy" /
               "proxy: shared default proxy is read-only")
500 {detail}   unexpected exception ("<ExceptionType>: <message>"); the web UI treats any 5xx
               as "fall back to remote-browser"
```

On success, before answering, the relay:

1. Binds the proxy (if any) to the new account. This happens **before** the
   account's API client is loaded, so the fresh client already uses the proxy.
2. Runs the same post-bootstrap hooks the existing bootstrap endpoint runs:
   drop any cached client for the account, clear a "session dead" flag, load
   the client, restart the account's live event pump, sync and link the
   account to the signed-in user.
3. Echoes `user_id` and `x_of_rev` from the freshly loaded client.

### 3.2 `POST /admin/login/remote/start`

Request: `{email, password, proxy_label?, proxy?, account_id?, nickname?, make_active?=true}`

- `account_id` is a hint: "re-log this account in its stored browser profile".
  When present it must pass the account-ownership check.
- `proxy` works exactly as in 3.1.

Responses:

```
200 {job_id}
400 {detail}   missing email/password; unknown proxy_label; bad pasted proxy
401/403        account_id not owned by the caller (ownership gate)
403 {detail}   pasted proxy not owned by the caller
409 {detail}   "A login or refresh is already running for this OnlyFans account"
```

### 3.3 `POST /admin/session/refresh`

Request: `{account_id}`. No credentials.

Responses: `200 {job_id}`, `401/403` from the ownership gate, `409` busy,
`400` when `account_id` is empty.

### 3.4 `GET /admin/login/remote/{job_id}`

```
200 {job_id, state, message, popup, otp_needed, result?, error?}
    state:      "starting" | "typing" | "challenge" | "otp" | "capturing" | "done" | "error" | "cancelled"
    popup:      true only while a human check is on screen (state "challenge")
    otp_needed: true only while waiting for a 2FA code (state "otp")
    result:     {account_id, user_id, x_of_rev, session_file}   present only when state == "done"
    error:      string                                          present only when state == "error"
404 {detail}  unknown or expired job ("finished jobs expire after 10 minutes")
403 {detail}  "not your login job"
```

`message` is a short human status line, always scrubbed of the password.

### 3.5 `POST /admin/login/remote/{job_id}/otp`

Request: `{code}` (non-empty string). Responses: `200 {ok:true}`; `409` when the
job is not in state `otp`; `422` for an empty code (schema validation);
`404`/`403` as in 3.4.

### 3.6 `POST /admin/login/remote/{job_id}/cancel`

No body. `200 {ok:true}`. Cancels from any state, including while waiting for
a 2FA code. `404`/`403` as in 3.4.

### 3.7 `POST /admin/login/remote/{job_id}/input`

Request is one of the shapes in 6.6. Responses: `200 {ok:true}`; `409` "no
challenge on screen" when `popup` is false; `400` for a bad shape; `404`/`403`
as in 3.4. The UI treats inputs as fire-and-forget and ignores the response.

### 3.8 `GET /admin/login/remote/{job_id}/screen` (SSE)

`text/event-stream` with headers `Cache-Control: no-cache, no-transform`,
`X-Accel-Buffering: no`, `Connection: keep-alive`.

```
event: state
data: <the GET /admin/login/remote/{job_id} body>

event: frame
data: {"b64":"<base64 JPEG>","w":<viewport CSS px width>,"h":<viewport CSS px height>}

: ping            (comment line after 15 s with nothing sent)
```

- A `state` event is sent first and then on every state change.
- A `frame` event is sent for every new screencast frame while `popup` is true.
- The stream **ends** once the popup closes or the job reaches a final state.
  An open on a job with no popup sends one `state` event and ends.
- `404`/`403` as in 3.4.
- SSE is plain HTTP, so it passes through an ordinary rewrite or reverse
  proxy. No WebSocket pass-through is needed. Input goes over POST.
- `EventSource` cannot set headers, so any perimeter token must ride in the
  query string (8.3).

### 3.9 `POST /admin/proxies/bulk`

Request: `{text, scheme?="http"}`. One proxy per line.

```
200 {added:[{label, host, port, scheme, username}], errors:[{line, text_redacted, reason}]}
```

- Lines are whitespace-trimmed. Blank lines and lines starting with `#` are
  skipped.
- `line` is 1-based and counts every line of `text`, including skipped ones.
- `added` never contains a password. `text_redacted` is the failed line passed
  through the redaction rule (5.4).
- A per-line `ValueError` (parse failure) or ownership failure goes to
  `errors`; the other lines still go through.
- If anything was added, the relay drops its cached API clients so none keep
  dialing an old proxy definition.

---

## 4. OnlyFans login protocol (as currently known)

Every OF web build ships a JavaScript bundle whose path carries a revision
string. The relay reads that bundle read-only to recover what the browser
attaches to its own API calls, then reproduces the same request shape from the
server. **V** marks a fact confirmed from the bundle or from live behaviour.
**G** marks a guess or inference that is *unconfirmed* — re-check every G
against the live site before relying on it, because the login-form code is
lazy-loaded and was not present in the captured bundle.

### 4.1 Endpoint and signing identity

- **(V)** Login is a `POST` to the OF API login path (`/api2/v2/users/login`),
  and it is a signed `/api2/v2/*` request like any other.
- **(V)** Before login there is no authenticated user, so the signing identity
  is user id **0**. Both the `sign` user id and the `x-hash` lookup use
  `authUserId || 0`.

### 4.2 Headers and cookies required before login

| header / cookie | **V/G** | where it comes from |
| --- | --- | --- |
| `app-token` | V | A hard-coded constant string in the bundle. It is the **same value for all accounts** and changes only when OF ships a new one. Treat it as a configured constant per project, re-read from the current bundle; do not hardcode a stale literal. |
| `x-of-rev` | V | The build revision. Same value as the revision segment in the bundle's own URL path. Read it off the homepage HTML. |
| `x-bc` | V | A **server-issued** key fetched with a `GET` to the OF CDN key path (credentials off), which the browser caches in `localStorage`. It is *not* a client-computed hash. |
| `x-hash` | V | A `GET` to the OF CDN hash path with the user id as a query param (0 pre-login). |
| `sign` / `time` | V | Computed locally by the signer (4.3) over `(static_param, time, path, user_id)`. |
| cookies | V | The homepage `GET` seeds the anonymous cookies; OF sets the auth cookies on a successful login. The relay replays whatever ends up in the jar, exactly like its paste-a-curl path. |

### 4.3 Request signing

The signer is a pure, I/O-free function. It reproduces the bundle's own
checksum so OF accepts the request as coming from its web client. Inputs:

- `static_param` — a per-revision string lifted from the bundle's signing
  chunk. **(V)**
- `start`, `end` — per-revision fixed affixes of the `sign` header. **(V)**
- `checksum_indexes` (32 integers) and `checksum_constant` (one signed
  integer) — derived by parsing the obfuscated signing chunk and solving the
  constant against at least one captured `(sha1Hex, checksumValue)` **sample**.
  **(V)**

The `sign` header is built as:

```
payload   = static_param + "\n" + time_ms + "\n" + request_path + "\n" + user_id
sha1_hex  = sha1(payload)                       # lowercase hex
checksum  = sum(charCode(sha1_hex[i]) for i in checksum_indexes) + checksum_constant
sign      = start + ":" + sha1_hex + ":" + hex(abs(checksum)) + ":" + end
time      = time_ms                             # same millis used in payload
```

`request_path` is the URL path plus `?query` if any. `user_id` is 0 pre-login.

**Deriving the rules for a new revision.** The checksum constant's sign is
ambiguous from the chunk alone (the live code takes an absolute value), so you
need one real sample to disambiguate it. In this system that sample comes from
a **per-revision signing profile** captured by any account that is already live
at the current revision (the extension, a paste-a-curl, or the remote browser
all produce one). The indexes are re-derived from the freshly fetched signing
chunk each time. Consequences:

- The signer needs a reusable profile (`static_param`, `start`, `end`, one
  sample) for the current revision. The first account at a new revision must be
  brought in by a path that captures a sample (remote browser). After that,
  direct-api works for every account at that revision.
- An `static_param_override` input lets an operator supply the one string for a
  not-yet-seeded revision, but a profile for `start`/`end`/sample must still
  exist, so in practice seeding comes first.
- If no profile exists for the current revision, direct-api returns
  `needs:"browser"` naming the revision, and the flow falls to the remote
  browser, which harvests the profile.

**Keep this module private.** Publishing the exact derivation makes it cheaper
for OF to rotate the scheme. If the surrounding project is open-sourced, keep
the signer out of the public tree.

### 4.4 Login body and captcha

- **(G)** Body is `{email, password}` (plus a 2FA `code` on a retry — field
  name *unconfirmed*). A solved-captcha token is attached only when the live
  provider demands one; that field name is *unconfirmed* too. The relay does
  **not** solve captchas in the direct path — it hands any captcha to the
  remote browser where a human solves it.
- **(V)** The set of possible captcha providers is listed by an `init` API call
  (Google reCAPTCHA V2/V3/enterprise, hCaptcha, Cloudflare Turnstile, GeeTest).
  Which one is live is account- and risk-dependent.

### 4.5 Response classification

| outcome | detected by | **V/G** | maps to |
| --- | --- | --- | --- |
| success | JSON user object with an `id`; auth cookies now set | V | `ok:true` |
| 2FA required | HTTP 400 with an OF `error.code` of **105** (body has `error.otpState`) or **101** (body has `error.payload.otpState`) | V | `needs:"otp"` |
| Cloudflare / captcha interstitial | HTTP 403, `content-type: text/html`, a `cf-ray` header ("Just a moment…") | V | `needs:"browser"` |
| anything else | non-JSON body, or any OF error code that is not 101/105 | — | `needs:"browser"` |

**There is no confirmed bad-credentials error code** (the mapping lives in the
lazy-loaded login chunk). So a wrong password is *not* guessed at — it falls to
`needs:"browser"`, and the user sees OF's own error in the real form. This is
deliberate: guessing a code risks mislabelling a soft-block or captcha as "bad
password".

**2FA is not retried in the direct path by the UI.** A resend would start a
fresh cookie session and the `code` field name is unconfirmed, so the web UI
routes 2FA to the remote browser, which types the code into OF's real 2FA
form. The direct path keeps an `otp` parameter for completeness, best-effort.

### 4.6 One session, one egress

Homepage, key fetch, hash fetch, signing-chunk fetch and the login POST all go
through **one** HTTP client bound to the account's proxy. The signing chunk is
therefore fetched from the same egress IP and TLS identity OF will see on the
signed traffic — no side-channel fetch over a different client or IP.

**TLS fingerprint and User-Agent are pinned together.** Use an HTTP client that
presents a current desktop-Chrome TLS handshake, and set the stored
`User-Agent` to exactly the Chrome version that client advertises, so the
handshake and the UA describe one coherent, current Chrome. When you upgrade
the client, bump both in lockstep. In the reference this is `curl_cffi` with a
`chrome146` target and a matching `Chrome/146.0.0.0` UA.

---

## 5. Proxy handling

### 5.1 Same egress for minting and using cookies

**Hard rule.** The cookies for an account are minted through a proxy, and every
later signed request for that account must egress through the **same** proxy. On
a successful login with a proxy, bind the proxy to the new account *before* its
API client is first loaded, so the client is created already pointing at that
proxy. The remote-browser and any other capture path follow the same rule.

### 5.2 Registry model

- A proxy has: `label` (unique key), `scheme`, `host`, `port`, optional
  `username`/`password`.
- An account binds to at most one proxy; a proxy may serve many accounts.
- Re-adding an existing label upserts it and **keeps** existing account
  bindings.
- There may be a shared "default" proxy that is read-only to ordinary callers.

### 5.3 Accepted line formats (bulk and inline)

Whitespace-trimmed; an optional label may trail after a space or tab. Blank
lines and lines starting with `#` are skipped.

| line | parsed as |
| --- | --- |
| `scheme://user:pass@host:port` | scheme taken from the line |
| `user:pass@host:port` | scheme from the request body (default `http`) |
| `host:port:user:pass` | body scheme — the common provider export |
| `host:port@user:pass` | body scheme |
| `host:port` | no auth |

Label defaults to `host:port` when none is given.

### 5.4 Redaction

Any pasted line that fails to parse must be **redacted** before it appears in a
response, log, or error, because the position of the password is unknown:

- If the line has an `@`, mask every `:value` segment (`user:***@host:port`).
- Otherwise, if there are 3+ colon segments, keep the first 2–3 and mask the
  rest (so `host:port:user:pass` → `host:port:***`).
- Preserve any `scheme://` prefix and any trailing label.

---

## 6. Remote-browser job model

The relay runs its own Chromium (via a browser-automation driver) on the relay
host, in a persistent per-account profile, launched through the account's
proxy. It types the credentials into OF's **real** login form and only shows
the page to the user when a human check appears. It is the fallback for
everything direct-api cannot finish, and the only path that seeds a brand-new
revision's signing profile.

### 6.1 State machine

```
Login:   starting → typing → [challenge ↔ typing] → [otp → typing] → capturing → done
Refresh: starting → capturing → [challenge → capturing] → done
Final states: done | error | cancelled
```

- `starting` — launching the proxied browser.
- `typing` — on the login page, filling / submitting the form.
- `challenge` — a human check is on screen. This is the **only** state with
  `popup:true`.
- `otp` — waiting for a 2FA code. Sets `otp_needed:true`, no popup.
- `capturing` — logged in; loading a page that triggers signed API calls so the
  signing headers and a fresh sample can be harvested.
- `done` — session captured and persisted. `result` carries the ids.
- `error` / `cancelled` — terminal; `error` carries a scrubbed message.

### 6.2 Concurrency, ownership, expiry

- **One live job per account**, keyed on both the account id and the
  lower-cased email. A second start returns `409`.
- Every per-job route (status, otp, cancel, input, screen) checks the
  **principal** that started the job and returns `403` to anyone else. Resolve
  the principal the same way the account-ownership gate does (signed-in user
  first, then the acting operator). Record it at start. Anonymous-admin
  requests are exempt from the check.
- A `start` with an `account_id` hint means "re-log this account in its stored
  profile"; it must pass the account-ownership check.
- The whole job times out after **10 minutes**. A finished job is dropped from
  memory 10 minutes after it ends; requests for it then `404`.

### 6.3 Challenge detection

One DOM probe per poll classifies the page. A challenge is "visible" when any
of these fire (the first one to fire is logged as the reason):

- page text matches "Just a moment" / "Verify you are human";
- a Cloudflare interstitial / Turnstile node (`#challenge-running`,
  `#challenge-stage`, `#challenge-form`, `.cf-turnstile`, or an iframe from the
  Cloudflare challenges host);
- a **visible** (non-invisible) Google reCAPTCHA, hCaptcha, or GeeTest widget;
- OF's own captcha modal.

Turnstile renders inside a **closed shadow root**, so the light-DOM query can
miss it; a second check walks the browser's frame list for an on-screen
challenge iframe from a known challenge host. The job only treats a challenge
as solved after it has stayed gone for a short settle window (about 1.5 s), and
it re-clicks the form's submit once if a solved challenge left it back on the
form.

### 6.4 Screencast (SSE)

While `popup` is true the page is screencast to the browser over
Server-Sent Events:

- JPEG, quality ~60, frames acked at most every ~200 ms (so a few frames per
  second), capped to the viewport size.
- Viewport is a fixed desktop size (reference: 1366×900 CSS px). The frame
  `w`/`h` sent to the client are the **CSS-pixel viewport size**, not the JPEG's
  own pixel dimensions.
- The SSE stream emits a `state` event first and on every state change, a
  `frame` event per new screencast frame, and a comment "ping" after idle. It
  ends when the popup closes or the job reaches a final state.
- SSE is plain HTTP, so it survives an ordinary same-origin rewrite or reverse
  proxy; no WebSocket pass-through is needed. Because `EventSource` cannot set
  headers, any perimeter token rides in the query string.

### 6.5 Input replay

Input the user makes in the popup is POSTed back and replayed into the page
1:1. Coordinates are **page CSS pixels**, rounded to integers. The canvas
backing store is sized to the frame `w×h` and the JPEG is drawn stretched to
it, so the client maps a pointer event back as:

```
x = round((clientX - rect.left) * w / rect.width)
y = round((clientY - rect.top)  * h / rect.height)
```

Input message shapes:

```
{type:"mouse", action:"down"|"up"|"move", x, y, button:"left"|"middle"|"right"}  # move throttled (~20/s)
{type:"wheel", x, y, dx, dy}                                                      # dx/dy = WheelEvent deltas
{type:"key",   action:"down"|"up", key}                                           # key = KeyboardEvent.key
```

They map onto the driver's `mouse.move/down/up`, `mouse.wheel` (after a move to
`x,y`), and `keyboard.down/up`. Inputs are fire-and-forget; the client ignores
the response. Input is rejected with `409` when no challenge is on screen.

### 6.6 Form prefill and OTP

- The job fills email and password itself: wait for the form, click the
  landing "Log in" if needed, type into candidate selectors (each OF input
  selector falls back to matching by `type=`, since the exact `name`s were not
  in the bundle), read the values back, and retry with a direct value-set if
  typing did not stick. Re-fill after a challenge, and submit only once the
  fields read back correctly.
- If the form cannot be filled or found automatically, the job leaves the
  browser on OF's real form with a message telling the user to finish by hand —
  it never dead-ends.
- On 2FA the job enters `otp`; the code arrives via the otp route and is typed
  into OF's real 2FA field (same selector-fallback approach). If it cannot be
  typed automatically, the user enters it in the window.

---

## 7. Session refresh ("update the curls")

A per-account action that needs **no credentials**. It re-harvests the signing
material for an account that is **already** logged in, for when OF ships a new
revision (new `x-of-rev`, rotated `static_param`):

- Start a browser job for the account that seeds the browser from the account's
  stored profile, or, failing that, from the cookies in the latest session file
  for that account (set on `.onlyfans.com`, with that session's stored UA).
- Open a page that triggers signed API calls, re-derive the signing rules at
  the new revision, and persist a refreshed session record — the **same record
  shape** every other capture path writes.
- If the seeded browser shows the login form instead of a logged-in UI (or
  shows nothing logged-in within ~30 s), end in `error` asking for a full
  login. If a challenge appears, it surfaces as the popup like any other job.

---

## 8. Security rules

1. **Never store or log the password.** It lives only in component state on the
   client, in the two POST bodies, and on the in-memory job until the browser
   closes. It must never appear in a query key, a mutation variable, a URL, a
   log line, an error message, or any persistent store. Scrub it from every
   job message and error.
2. **Redact pasted proxy lines** that fail to parse (5.4) before they reach any
   response or log.
3. **Audit-skip the login paths.** If the backend audit-logs request bodies,
   add the login path prefix to the skip list so passwords are never audited.
4. **Perimeter token.** If the service sits behind a shared access token, the
   SSE stream must accept it in the query string (`EventSource` cannot send
   headers). Everything else can use the normal header.
5. **Operator auth / ownership.** Per-job routes enforce the starting
   principal (6.2). Login and refresh sit behind the same auth as the existing
   session-bootstrap endpoint.
6. **Keep the signer private** (4.3).

---

## 9. Tests and known risks

### 9.1 Test shape

Mirror the host project's existing backend test style. In the reference, each
test file bootstraps a shared harness, uses plain `assert`, and runs
standalone. Cover at least:

- **direct login**: each classification branch (success, otp 101/105,
  Cloudflare 403, unknown error → browser), unseeded-revision → browser,
  proxy-label binding on success, 4xx on missing fields / unknown label / bad
  pasted proxy, and that the password never reaches a log or error string.
- **remote login**: state transitions, the busy guard (409), the ownership
  gate (403), expiry/404, the input-shape parser and the `409` when no
  challenge is up, and OTP routing.
- **proxy paste**: every line format in 5.3, the label default, skipped blank /
  `#` lines, 1-based line numbering in errors, the redaction rule, and that
  bindings survive an upsert.

Frontend: a test for the card's fall-through logic (direct → remote on
`needs:*`/5xx, 4xx shows detail), the job-polling hook (invalidate the right
caches on `done`), and the proxy-paste UI. Run the host project's typecheck,
lint and test commands.

### 9.2 Known risks / unverified

- **(G)** OF login-form input `name`s, the 2FA `code` field name, and the
  captcha token field name are all inferred — the login chunk was not in the
  captured bundle. The remote browser avoids all three by driving OF's real
  form; the direct path guards by routing anything unrecognised to the browser.
- The challenge/captcha class names and error codes can change with any OF
  build; re-verify after a revision bump.
- The remote browser needs the automation driver + a Chromium install on the
  relay host. A slim/headless server image without them makes remote and
  refresh unavailable (`start` ends in `error`); direct-api still works there
  once a revision is seeded.
- A human check can still be shown to the relay's Chromium, especially
  headless. That is expected: it reaches the user as the popup to solve, and is
  not bypassed.
- A one-box-per-digit 2FA input may defeat automatic typing; the user then
  enters the code in the window.
