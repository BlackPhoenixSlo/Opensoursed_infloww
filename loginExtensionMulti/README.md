# Inflowwww Login Capture (OF + Fansly)

Dual-platform login capture for the Inflowwww relay. The OnlyFans path is the
proven 1.2.0 extension verbatim; the Fansly path is added alongside it.

## Load it
Chrome → `chrome://extensions` → Developer mode → **Load unpacked** → pick this
folder.

## OnlyFans (unchanged)
1. Click **Log in to OnlyFans**, sign in.
2. Open a chat so the page fires a signed `/api2/v2/` request.
3. **Copy curl** → paste into the relay's Setup tab (paste-curl).

## Fansly (new)
1. Click **Log in to Fansly**, sign in (password + the one-time email code).
2. The content script lifts the session out of `localStorage`
   (`session_active_session` + `device_device_id`) — no signing needed.
3. **Copy Fansly session** → gives you the exact JSON the relay stores.
4. In the relay web app, go to **Setup → Connect Fansly**, paste the copied
   JSON into the box, and click **Connect Fansly account**. (That card POSTs to
   `/admin/session/fansly` for you.)

   Fallback if you're scripting without the UI:
   ```
   curl -X POST <relay>/admin/session/fansly \
     -H 'content-type: application/json' \
     -d '<paste the copied JSON>'
   ```
   Either way the relay writes `sessions/accounts/<accountId>/fansly_session.json`,
   stamps the account `platform=fansly` + the creator's display name, links
   ownership, and the inbox starts serving Fansly data through the same UI.

## Multiple accounts (both platforms)
One switcher serves both sites. They differ in exactly one respect — where the
browser keeps the session — so `background.js` declares that difference once in
a `PLATFORMS` descriptor and every flow is written against it:

| | OnlyFans | Fansly |
| --- | --- | --- |
| session lives in | cookies | page `localStorage` |
| reached via | `chrome.cookies` | `chrome.scripting` (MAIN world) |

1. **+ Save current & log in to another** — files the live session under its
   account id, clears it, and reloads so you get a clean login screen. The site
   is never told to log out, so the saved session stays valid.
2. Sign in to the next account; it appears in the list on its own.
3. **Use** swaps that session back in and reloads — the page returns signed in
   as that account, and the copy button immediately yields its material.
4. **×** forgets a saved login locally (it does not log the account out).

Fansly's device id (`device_device_id`) is deliberately left alone across
switches: Fansly ties rate limits to it, and the real client keeps one per
browser.

Which account is "active" is pinned in `activeAccounts`, written only by these
explicit flows. The capture keys stay purely observational — that separation is
what lets the list refresh itself reactively without a switch ever racing it.


## What each file does
| file | world | role |
| ---- | ----- | ---- |
| `interceptor.js` / `bridge.js` | MAIN / ISOLATED | OF capture (headers + signing rules) |
| `fansly_interceptor.js` / `fansly_bridge.js` | MAIN / ISOLATED | Fansly capture (localStorage session + live headers) |
| `popup.{html,js}` | — | both panels: OF curl + Fansly session |
| `background.js` | worker | the `PLATFORMS` descriptor + one generic set of account flows (snapshot / save / switch / forget) shared by both sites |

The Fansly capture never needs `fansly-client-check` — that's derived, and the
relay recomputes it. Only the token, session id, account id, device id and user
agent are captured.
