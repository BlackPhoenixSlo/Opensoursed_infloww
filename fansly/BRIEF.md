# Fansly web-API signing — reverse-engineering brief

**Your job:** figure out how `fansly.com`'s web client authenticates its API
calls, then produce a pure-Python signer + minimal client that can make
authenticated requests on behalf of an account **we are authorized to operate**
(our own / managed creator accounts). This is the Fansly twin of the OnlyFans
work already in this repo — read that first, it's the template:

- [service/of_signer.py](../service/of_signer.py) — the reverse-engineered OF
  request signer (`sign(url, user_id, rules)` → `{"sign", "time"}`), derived
  from OF's obfuscated `2313.js` checksum module.
- [service/of_client.py](../service/of_client.py) — how the signer + captured
  cookies + `App-Token`/`X-Hash`/`X-Bc` headers turn into live REST calls.
- [service/session_bootstrap.py](../service/session_bootstrap.py) — how a real
  logged-in session (cookies + sign-rules) is captured and stored.
- [STATIC_VALUES.md](../STATIC_VALUES.md) §2–§3 — the map of every OF auth
  constant and where it lives.

Mirror that architecture for Fansly. Do **not** attempt to defeat, bypass, or
brute-force Fansly's email 2FA / "login from a new device" check — a human
completes that once in a real browser and we capture the resulting session.
Scope is limited to accounts we control and are permitted to automate.

## Context (screenshots in this folder)

- `login.png` — the Fansly login modal (username/email + password, plus
  X / Google / Twitch OAuth options).
- `2fa.png` — the "Login from a new device" step: Fansly emails a verification
  code that the human types in once. This is the trust step we complete
  manually, then reuse the session — never something to automate around.

> The password shown in the login screenshot has been exposed in chat — rotate
> it before doing anything else, and never commit either screenshot (see
> `.gitignore`).

## What we need to learn

1. **Auth material.** After a real login, which cookies / tokens carry the
   session? (Fansly's web client is known to send an `Authorization`-style
   token in a request header rather than pure cookies — confirm exactly what,
   where it's stored in the browser, and how long it lives.)
2. **Per-request signing.** Does Fansly sign each API call (an equivalent of
   OF's `Sign` + `Time` + checksum)? If so:
   - which header(s) carry the signature,
   - what the signed string is (method? path? body? timestamp? account id?),
   - which webpack/JS chunk computes it, and the exact algorithm
     (hash, constants, index tables) — the OF analogue is the 32-index
     sha-1 checksum in `2313.js`.
3. **Device / client identifiers.** Any `deviceId`, fingerprint, or
   `check-key` header the client attaches, and where it's generated.
4. **Base URLs + versioning.** API host(s), path prefix, any `rev`/build hash
   the signing constants are pinned to (OF pins to `x_of_rev`).

## Method

1. **Capture, don't attack.** Log in as normal in a real browser (human does
   email + password + the one-time 2FA). Open DevTools → Network, load
   Messages/feed so the client fires authenticated XHRs. Export a HAR.
2. **Diff the headers.** For a handful of captured requests, list every
   non-standard request header and cookie. Identify which are static per
   session vs. recomputed per request (the recomputed ones are the signature /
   timestamp).
3. **Find the signer in JS.** Grep the site's bundled chunks for the header
   name(s) from step 2; trace back to the function that builds them. Recover
   the algorithm and any constant tables the way `derive_rules_from_chunk`
   does for OF.
4. **Port + verify.** Write `fansly_signer.py` (pure functions, no I/O) and a
   `verify_rules()` that recomputes the signature for every captured sample and
   asserts it matches the header we actually observed. Only once samples pass
   do we trust it.
5. **Wire a minimal client.** `fansly_client.py`: takes a captured session +
   the signer, makes one authenticated GET (e.g. `/api/v1/account` equivalent)
   and prints the JSON. That's the proof of life.

## Deliverables

- `fansly/fansly_signer.py` — signer + rule-derivation + verify, no I/O.
- `fansly/fansly_client.py` — minimal authenticated client using it.
- `fansly/NOTES.md` — the header/cookie map, the signed-string spec, the chunk
  URL the constants came from, and anything Fansly does that OF doesn't.
- Keep it private in the same spirit as `of_signer.py`'s docstring note.

## Guardrails

- Authorized accounts only. If this is ever pointed at accounts we don't
  control, stop — that's not what this is for.
- No 2FA bypass, no credential brute-forcing, no DoS-scale request volume
  against Fansly.
- Nothing secret gets committed: sessions, HARs, screenshots, credentials all
  stay local (`.gitignore` already covers them).
