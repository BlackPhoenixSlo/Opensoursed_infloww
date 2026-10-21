# Build Prompt: Direct Login (extension-free OnlyFans login)

Paste this prompt to a coding agent working **inside the target repository**.
It builds the "direct login" feature described in `DIRECT_LOGIN_SPEC.md` (same
folder as this file). Read that spec first — it is the contract. This prompt
tells you how to land it in *this* repo without breaking anything.

---

## Your task

Add an **extension-free** way to log a creator's OnlyFans account into this
project's relay/backend and capture its session, with three modes:

1. **Direct API** — the backend signs and POSTs OF's login itself, through the
   account's proxy. No browser needed.
2. **Remote browser** — when direct can't finish (2FA, captcha, a not-yet-seeded
   revision, any unknown result), the backend drives its own proxied Chromium,
   types the credentials into OF's real form, and shows the page to the user
   **only** while a human check is on screen, as a popup they click to solve.
3. **Session refresh** — re-harvest signing material for an already-logged-in
   account when OF ships a new build. No credentials.

Plus: paste proxies **in bulk** and **inline while linking a creator**, and a
web card that ties it together.

Implement to `DIRECT_LOGIN_SPEC.md`. That file has the API contract, the OF
protocol facts (with what is verified vs. guessed), the signing math, the proxy
rules, the job state machine, challenge detection, the screencast/input model,
refresh, security rules, and tests. Do not re-derive those here — follow them.

## Step 0 — Learn this repo before writing anything

Do not assume the reference project's file names or layout. First inspect the
host repo and adapt:

- **Backend**: what framework and language? Where do routes/routers live and how
  are they mounted? How is the OF API client, the session store, the proxy
  registry, and the account model already represented? Is there an existing
  capture path (paste-a-curl, an extension, a desktop capture)? **Reuse its
  session record shape and its post-capture hooks** — every new mode must write
  the identical record and run the same hooks, so downstream code cannot tell
  how a session was obtained.
- **Signing**: is there already an OF request signer and a per-revision signing
  profile / sample store? If yes, reuse it. If not, build the signer per spec
  section 4.3 and keep it private.
- **Browser automation**: is a proxied headful/headless browser capture already
  present (the thing the extension or a curl-capture replaces)? Reuse its launch
  + proxy + session-harvest code; the remote-browser mode is that capture plus a
  typing/challenge/screencast loop.
- **Frontend**: framework, data-fetching/caching library, how the app talks to
  the backend (same-origin rewrite? base URL?), and how an existing "add
  account" / "add proxy" screen is built. Match those conventions.
- **Auth / perimeter**: how are admin routes gated (operator login, a shared
  access token, an anonymous-admin escape hatch)? How is request-body auditing
  done? You will need to audit-skip the login path and let the SSE route take
  the perimeter token from the query string.
- **Tests**: the backend and frontend test styles and the exact commands to run
  them.

Write a short note of what you found and the names you'll use, then build.

## Step 1 — Rules that are non-negotiable

- **Additive only.** Do not delete, rewrite, or break any existing login,
  capture, extension, or desktop path. Build alongside them. If you refactor a
  shared function to reuse it, keep its existing behaviour byte-for-byte and
  cover it with the existing tests.
- **YAGNI.** Build exactly these three modes + proxy paste + the one web card.
  No extra providers, no captcha-solving service, no settings UI, no
  abstraction you don't use yet.
- **Never store or log the password.** It lives only in the request body, the
  client component state, and the in-memory browser job until the browser
  closes. Keep it out of every log, error, query key, URL, and persistent
  store, and scrub it from job messages. (Spec section 8.)
- **Proxies: one egress.** Cookies minted through a proxy must be *used* through
  the same proxy. Bind the proxy to the account before its API client is first
  loaded. Fetch the signing chunk and the login POST over the same proxied
  client. (Spec sections 4.6, 5.1.)
- **Keep the signer private** if this repo may be open-sourced.
- **No real secrets in code or docs.** The app-token and revision are configured
  constants re-read from the live bundle, not committed literals. Never commit a
  real OF email, password, cookie, or proxy credential.

## Step 2 — Deliverables and acceptance criteria

Implement the API exactly as in spec section 3. Endpoints (adapt the path
prefix to this repo's admin convention, keep the shapes):

- [ ] `POST .../login/direct` — signs and POSTs OF login through the account's
      proxy. Returns `{ok:true,...}` on success; `{ok:false, needs:"otp"}` /
      `{ok:false, needs:"browser"}` for the two 2FA codes and everything it
      can't finish; `4xx` only for input problems (missing fields, unknown
      proxy label, bad/own-ership-failing pasted proxy). On success it binds the
      proxy first, then runs the existing post-capture hooks. (Spec 3.1, 4.5.)
- [ ] `POST .../login/remote/start` — starts a browser job; `{job_id}`; `409`
      when one is already running for that account/email; ownership-checks any
      `account_id` hint and any pasted proxy. (Spec 3.2, 6.2.)
- [ ] `POST .../session/refresh` — `{account_id}`, no credentials, starts a
      refresh job. (Spec 3.3, 7.)
- [ ] `GET .../login/remote/{job_id}` — status with `state`, `message`,
      `popup`, `otp_needed`, `result?`, `error?`; `404` after expiry; `403` to a
      different principal. (Spec 3.4, 6.2.)
- [ ] `POST .../login/remote/{job_id}/otp` `{code}` — supply a 2FA code.
- [ ] `POST .../login/remote/{job_id}/cancel` — cancel from any state.
- [ ] `POST .../login/remote/{job_id}/input` — replay one mouse/wheel/key event
      (spec 6.5); `409` when no challenge is on screen.
- [ ] `GET .../login/remote/{job_id}/screen` — SSE: `state` + `frame` events;
      token from query string. (Spec 3.8, 6.4.)
- [ ] `POST .../proxies/bulk` `{text, scheme?}` — parse every line format in
      spec 5.3, skip blank/`#` lines, return `{added, errors}` with 1-based line
      numbers and redacted failed lines; drop cached clients if anything was
      added. Both login routes also accept an inline `proxy` line. (Spec 3.9,
      5.)

Backend behaviour:

- [ ] Direct login reuses a per-revision signing profile and re-derives indexes
      from a freshly fetched signing chunk; returns `needs:"browser"` naming the
      revision when none is seeded. (Spec 4.3.)
- [ ] One proxied HTTP client with a current-Chrome TLS fingerprint and a
      matching UA for homepage + key + hash + chunk + login. (Spec 4.6.)
- [ ] The remote job implements the state machine, challenge detection
      (including the closed-shadow-root Turnstile frame check), the settle
      window, form prefill with selector fallbacks, OTP typing, and the
      screencast/input loop. (Spec 6.)
- [ ] Refresh seeds from the stored profile or the latest session's cookies and
      re-derives rules at the new revision. (Spec 7.)

Frontend (match this repo's UI stack):

- [ ] A "direct login" card: submit `{email, password, proxy choice, nickname?,
      make_active}`. Call direct first; on `needs:"otp"`, `needs:"browser"`, or
      any `5xx`, start a remote job with the same fields; a `4xx` shows the
      detail and stops. Never resend `otp` to the direct route.
- [ ] A challenge popup that opens the SSE stream, renders frames to a canvas
      sized to the frame `w×h`, maps pointer/key events back with the spec 6.5
      formula, and has a Cancel button.
- [ ] A status line that shows the 2FA field when `otp_needed`, and an error
      with "Try again".
- [ ] A per-account "Refresh session" action.
- [ ] A "Paste proxies" box (bulk) and a "Paste a new proxy…" option in the
      proxy selects on the account-link and curl-paste cards.
- [ ] Poll the job every ~1.5 s until a final state; on `done` invalidate the
      same caches the existing capture path invalidates (accounts, proxies, and
      any drift/health views). The password lives only in component state and
      the POST bodies.

## Step 3 — Verify before claiming done

Run and report the actual output of:

- [ ] Backend tests for direct login, remote login, and proxy paste (spec 9.1),
      using this repo's test runner.
- [ ] Frontend typecheck, lint, and unit tests.
- [ ] A grep proving no password is logged: search the new backend code for any
      log/print/audit call that could receive the password, and confirm job
      messages/errors are scrubbed.
- [ ] A manual smoke description: start the stack, open the card, submit a
      login, and confirm (a) direct success binds the proxy and refreshes the
      account list, (b) a `needs:"browser"` opens the popup and input reaches the
      page, (c) a `needs:"otp"` shows the 2FA field, (d) pasting proxies in bulk
      adds them and reports per-line errors redacted.

Report what passed, what you couldn't verify (e.g. a live OF call), and any spot
where you had to guess an OF detail marked **(G)** in the spec. Do not commit;
leave the work for review.
