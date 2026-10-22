# Proxies

The relay routes each OnlyFans account through at most one proxy from the registry
(`service/proxies.py`, `service/proxies.json`); one proxy may serve many accounts.
Creators › Add creator › Proxy selection offers three choices:

| choice | what the account egresses through |
| --- | --- |
| **Inflowwww proxy** (default when the relay has a pool) | one proxy from the relay's env pool, the least-used, kept |
| **No proxy (server IP)** (default without a pool) | the relay's own server IP |
| **Custom proxy** | one of your proxies from Creators › Custom proxy |

Accounts are linked with the Chatterly Login Capture extension and the **Paste cURL**
card (`POST /admin/session/bootstrap {mode:"paste-curl"}`), or with **Try Browserbase
login** (below). The relay image ships no browser.

## Browserbase login

Add creator › sign-in › **Try Browserbase login**: the creator's OnlyFans email and
password; the proxy is the flow's Proxy selection (the card has no picker of its own).
It needs no extension, so on a phone it is the sign-in step's only form (Paste cURL is
desktop-only). `POST /admin/login/remote/start {backend:"browserbase", proxy,
proxy_label}` (`service/remote_login.py`) creates a Browserbase session on
Browserbase's managed proxies (`proxies: true`), drives it over CDP with Playwright's
`connect_over_cdp`, and fills in OnlyFans' login form. Any Cloudflare / captcha / 2FA
check is solved by a person in Browserbase's live view, shown in the card while the job
runs; `solveCaptchas` is always false. Once logged in, the login extension's own
`interceptor.js` (added as an init script) supplies the signed headers and
`x-relay-static-param`, the chosen proxy is bound to the account, and the session is
saved by `session_bootstrap.from_request` and `server.post_bootstrap_hooks`, the
paste-curl path.

- `proxy`: `"infloww"` binds with `proxies.assign_pool` and `"custom"` (+ `proxy_label`)
  with `proxies.assign_account`, the registry calls behind `POST /admin/proxy-pool/assign`
  and `/admin/proxies/assign` that Paste cURL's attach step makes; `"none"` binds nothing
  (a row's re-login sends it, so the account keeps its proxy). Omitted: `"custom"` when
  `proxy_label` is given, else the flow's default (`"infloww"` with a pool, else
  `"none"`). `"infloww"` without a pool is a 409 before any session; a custom label gets
  the same visibility check as binding one (another user's is a 404).

- Needs `BROWSERBASE_API_KEY` and `BROWSERBASE_PROJECT_ID` in the relay's env (503
  without them), on a plan that includes proxies.
- The login itself runs on Browserbase's network; our proxy is never sent to
  Browserbase (the owner's call). It is attached to the account before the session is
  saved, so all later traffic for the account egresses through it, as with an
  extension-captured login. (Sending our proxy as Browserbase's external proxy was dropped: IPRoyal ISP
  proxies that work from the relay answer Browserbase's connect with 403.)
- A session that can't be created, or an OnlyFans page that won't load, fails the job
  at once with the error.
- The password is never stored, logged or audited (`/admin/login` is audit-skipped)
  and is scrubbed from every job message. `/admin/login` is owner-only for chatters.
- `backend` defaults to `"local"`, which this build refuses (501): no local browser.
- The session lives about 5 minutes (Browserbase's default); the login, the human's
  part included, must land within about 3¾ minutes; the rest is kept for the capture.
- `service/scripts/browserbase_of_smoketest.py` creates the same managed-proxy session,
  prints its egress IP and checks that OnlyFans' login form renders (exit 0 on PASS, 2
  when the session is refused, 1 otherwise);
  `service/scripts/browserbase_of_login_attended.py` (env `OF_EMAIL`, `OF_PASSWORD`)
  is one attended login on the same session that saves and binds nothing.

## Inflowwww proxy pool

Set on the relay (for the local stack: `your local env file`; for the repo's
`docker-compose.yml`: the compose-level `.env`):

```
INFLOWW_PROXIES=host1:port1:user1:pass1,user2:pass2@host2:port2,socks5://host3:port3
```

Any number of proxy lines in any format below, separated by commas or newlines; all
are synced. Read at relay startup (also with `CHATTERLY_TEST_MODE=1`), before anything
loads an OnlyFans client. Blank and `#` lines are skipped. A line that doesn't parse is
logged (password redacted) and blocks the sync (below).

- Commas separate proxies, so a password can't contain one; put each proxy on its own
  line instead (newline-separated value).
- If a password contains `$`, single-quote the value (`INFLOWW_PROXIES='host:port:user:pa$s'`)
  so the shell or compose doesn't expand it.
- At startup the lines are seeded into the registry as system entries labelled
  `infloww-<hash of scheme/user/host/port>` with `pool: true` and no owner. A password
  change keeps the label and its accounts; changing the scheme, user, host or port makes a
  new label, so that proxy counts as removed and its accounts are re-picked.
- A proxy removed from a valid env is dropped, and each account that was on it is
  re-bound to a random remaining pool proxy.
- Fails closed: while pool entries exist, an unset or empty `INFLOWW_PROXIES`, or one
  with any line that doesn't parse, leaves the pool and every binding untouched and logs a WARNING.
  Only `INFLOWW_PROXIES=none` clears the pool (its accounts are left with no proxy).
- A `proxies.json` that exists but does not parse is never rewritten by the sync (an
  ERROR is logged). Registry writes truncate and rewrite the file in place (then fsync),
  never a rename: Docker bind-mounts `proxies.json` as a single file, where a rename
  fails.
- A NEW user proxy can't take a label of the generated form `infloww-<8 hex digits>`
  (400 from `POST /admin/proxies`, a per-line error from `/bulk`). Any other label is
  fine, and an existing non-pool entry keeps and edits whatever label it has. The sync
  never adopts a non-pool entry that already holds a pool label.
- Pool entries never appear in `GET /admin/proxies` (not even as shared defaults), and
  the generic routes (`POST /admin/proxies`, `DELETE`, `/assign`, `/{label}/unbind`,
  `/{label}/test`, `/bulk`) treat them as absent or read-only. `GET /health` (single and
  `?all_accounts=1`) reports an account on one as `proxy: {pool: true}`: no label, url or
  egress IP. Network errors for such an account (502/504 `upstream_body`, the health
  rows' `error`) read "Inflowwww proxy unreachable"; the real text is logged on the relay.
- `proxies.scrub_pool_secrets` replaces each pool proxy's host, `host:port`, username and
  password (tokens of 4+ characters) with `[inflowwww-proxy]` in text the relay stores or
  serves: other network-error bodies, `/admin/errors` rows (`POST /admin/errors` and the
  unhandled-error middleware), and automation run/job records (`stats_json`,
  `error_text`, `last_error`). It is cached on the registry file's mtime and returns the
  text unchanged when there is no pool.
- Pool entries are not mirrored into the SQL `proxies` table (`db/import_legacy.py`);
  rows mirrored earlier are deleted on the next import.
- `GET /admin/proxies` → `pool: {size, account_ids}`: how many pool proxies the relay
  holds and which of the viewer's accounts are on one. With `size: 0` the UI shows the
  Inflowwww proxy option disabled.

```
POST /admin/proxy-pool/assign  {account_id}  → {ok, kept}   # 409 when the pool is empty
POST /admin/proxy-pool/unbind  {account_id}  → {ok, removed}
```

`assign` keeps the account's current pool proxy (`kept: true`); otherwise it picks the
least-used one, the pool proxy whose IP (`verified_ip`, else host) the fewest other
accounts leave from (bindings on any proxy count), ties at random, and binds it (moving
the account off any custom proxy). A new account so gets an IP of its own while the pool
has one free. The app
calls it, then `POST /admin/reload-session`, in Paste cURL's attach step (Add creator:
after the IP-change confirm and the capture, before onboarding is queued and the flow
moves on) or on Save (Change proxy, enabled once `GET /admin/proxies` has answered).
The linked step then reads the account's proxy back from `GET /admin/proxies` (an error
line if that read fails).

Every registry write that changes an account's egress (these two routes, `/assign`,
`/{label}/unbind`, a proxy edit, the startup pool sync) applies at once: `proxies.save`
calls the relay's `on_switch` hook, which evicts that account's pooled client and, when
its chat WebSocket pump is running, restarts it, so the socket reconnects on the new
route (`ws-pump[<id>]: proxy changed, reconnecting on the new route`) together with the
REST calls. Before, the socket stayed on the old route until the relay restarted.

## Paste many at once

```
POST /admin/proxies/bulk
  {text, scheme?="http"}            # one proxy per line; blank lines and lines starting with # are skipped
  → {added:[{label, host, port, scheme, username?}], errors:[{line, text_redacted, reason}]}
```

Accepted line formats (whitespace-trimmed; a trailing `label` after a space or tab is optional):

| line | parsed as |
| --- | --- |
| `scheme://user:pass@host:port` | scheme from the line |
| `user:pass@host:port` | body `scheme` |
| `host:port:user:pass` | body `scheme` (the common provider export) |
| `host:port@user:pass` | body `scheme` |
| `host:port` | no auth |

Label defaults to `host:port`; an existing label is upserted (same as `POST /admin/proxies`).

### Web UI

- `ProxiesTable` (`/creators/proxy`) has a **Paste proxies** box: textarea + scheme select
  (http default) + **Add all** → `POST /admin/proxies/bulk {text, scheme}`. It shows
  "Added N: labels" and one `Line n: reason` row per error, then invalidates `proxies`.
  The textarea is kept when any line failed, cleared otherwise.
- `PasteCurlCard`'s proxy select ends with **Paste a new proxy…**, which reveals one
  input. The card first posts `{text: line, scheme:"http"}` to `/admin/proxies/bulk` and
  uses `added[0].label` for its usual assign step; a bulk error (or no `added`) is shown
  as the card's error and the bootstrap is not sent. When the Add creator flow picked
  Inflowwww proxy, the select is hidden and the card's `attach` prop does the pool bind in
  the same attach step. A failed attach (custom or pool) is shown in the card with
  **Retry** (re-runs bind + reload; a bind that worked but a reload that failed says so)
  and **Continue** (goes on without the proxy, still queueing "Onboard recent" if ticked).
- The pasted text can hold proxy passwords: it lives only in component state and POST
  bodies, never in a query key, mutation variable or URL.
