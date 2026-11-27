# Release 1: what works, what is off

Draft. Not signed yet.

Release 1 splits the agency's Creators across several Relays (Cells).
Most of the app works as today.
20 parts are switched off and 9 work with a gap.

## Switched off (20)

**Agency calls without a front-door route**
Some agency tools require a front-door route before they can work in cell mode.

65 app call sites are marked off.

**Public tracking links (/t/...)**
Fans who tap a tracking link get an error page. Links need an agency-wide id first.

**Shared stats links (/share/...)**
Stats links you shared stop opening. They need an agency-wide lookup first.

**Bio pages (link-in-bio sites)**
Bio sites stop loading and cannot be edited. Their web addresses need an agency-wide lookup first.

**Reads across every Creator**
Screens that read every Creator at once do not load: dashboard, chatting and per-employee stats, live revenue, Excel export, Full AI rules list, proxy list, AI key status, a user's Creator list. The Creator list and All inbox stay.

**Auto clock-out**
Idle chatters are not clocked out on their own: their last activity sits on other Cells. Chatters clock out by hand.

**S4S requests between Creators**
Shout-for-shout swaps name two Creators who may sit on different Cells.

**Auto-reply**
Fans get no automatic replies. Reason: after a crash it could send one twice.

**Welcome-for-info message**
No welcome-for-info message. Reason: after a crash it could send it twice.

**Follow-ups**
No automatic follow-ups. Reason: after a crash it could send one twice.

**Send vault media to a fan (upload)**
Uploads that need a temporary feed post are refused until posts have send ids. Uploads linked to a fan use a send id for the message.

**Online nudge**
No nudges when a fan comes online. Reason: after a crash it could send one twice.

**Purchase follow-up**
No thank-you after a purchase. Reason: after a crash it could send it twice.

**Remote login**
Logging a Creator in from the app is off until it is checked (Phase 1).

**Translate**
Translating a message is off until it is checked (Phase 1).

**Leak tracker**
The Leak tracker is off in cell mode: its pages and routes answer as if it did not exist.

**Copy or import saved replies**
Copying replies to other Creators and importing them from a file are off.

**Small tools not checked yet**
Off until checked (Phase 1): image proxy, Full AI content prep, standard vault folders, vault cache reset.

**API docs pages**
The relay's /docs pages are off in cell mode.

**Clock-event sales reassignment**
Reassignment by Clock event is off because its sales can span Cells. Sales selected by Creator can still be reassigned.

## Works with a gap (9)

**Creator list (roster)**
Reads several Creators at once: works, but a down Cell's Creators show as missing.

**All inbox**
Reads several Creators at once: works, but a down Cell's Creators show as missing.

**Split inbox**
One Creator's split inbox works. Group edits are off until the Front door fans writes out; other Cells' split-inbox caches also miss a newly saved default.

**Payroll and shift records**
Records and timesheets show, but finalising pay waits until every Creator's sales are fresh.

**Feed posts and stories**
Feed post creation and story publication are refused in Cell mode until they have send ids.

**S4S profiles and promo posts**
Profiles work. Publishing promo posts is refused in Cell mode until feed posts have send ids.

**Proxies**
The proxy list is off (see Reads across every Creator); edits work, a down Cell's Creators show as missing.

**Connect a Creator (sessions)**
Fansly session import is refused in Cell mode because the platform is not admitted.

**Relay health and housekeeping**
Per-Relay tools. Perf log upload names several Creators: a down Cell's Creators are marked missing.

## Works as today (27)

- Sign-in and security
- Team and access
- Shifts and clock-in
- Agency settings and alerts
- Chat with a fan
- Mass messages
- Scheduled sends
- Priority mass
- Funnels
- Lifecycle messages
- Welcome message
- Full AI
- Automation rules
- Smart lists and OF lists
- Saved replies
- Vault library
- Customs
- Auto-follow
- Promotions and trials
- Tracking link stats
- Stats and reports per Creator
- Sales ingest
- Creator settings
- AI assistant
- Support chat
- OF profile, fans and streams
- Live updates

## To sign

Say "yes, Release 1 features signed" in the build chat.
We record your name, the date and the table's fingerprint
(short form: `85262cde2eaf22b0`).
Any change to the table needs a new yes.

## What is in each part

Generated from `service/cell_features.json` by
`scripts/cell_scope_scan.py --features`. Do not edit by hand.

<details><summary>Agency calls without a front-door route (off; no members)</summary>


</details>

<details><summary>Public tracking links (/t/...) (off; 2 routes, 1 job)</summary>

- `GET /t/{slug}`
- `POST /t/{slug}/verify`
- `tracking-click-classify`

</details>

<details><summary>Shared stats links (/share/...) (off; 4 routes)</summary>

- `DELETE /admin/link-shares/{share_id}`
- `GET /admin/link-shares`
- `GET /share/{key}/data`
- `POST /admin/link-shares`

</details>

<details><summary>Bio pages (link-in-bio sites) (off; 23 routes)</summary>

- `DELETE /admin/bio-pages/{pid}`
- `DELETE /admin/bio-pages/{pid}/avatar`
- `DELETE /admin/bio-pages/{pid}/background`
- `DELETE /admin/bio-pages/{pid}/domain`
- `DELETE /admin/bio-pages/{pid}/links/{lid}`
- `DELETE /admin/bio-pages/{pid}/links/{lid}/background`
- `GET /admin/bio-pages`
- `GET /admin/bio-pages/files/{collection}/{rid}/{filename}`
- `GET /admin/bio-pages/stock/{name}`
- `GET /admin/bio-pages/{pid}`
- `PATCH /admin/bio-pages/{pid}`
- `PATCH /admin/bio-pages/{pid}/links/{lid}`
- `POST /admin/bio-pages`
- `POST /admin/bio-pages/{pid}/avatar`
- `POST /admin/bio-pages/{pid}/avatar/vault`
- `POST /admin/bio-pages/{pid}/background`
- `POST /admin/bio-pages/{pid}/background/vault`
- `POST /admin/bio-pages/{pid}/domain/check`
- `POST /admin/bio-pages/{pid}/links`
- `POST /admin/bio-pages/{pid}/links/{lid}/background`
- `POST /admin/bio-pages/{pid}/links/{lid}/background/vault`
- `PUT /admin/bio-pages/{pid}/domain`
- `PUT /admin/bio-pages/{pid}/links/order`

</details>

<details><summary>Reads across every Creator (off; 11 routes)</summary>

- `GET /admin/accounts/roster-counts`
- `GET /admin/full-ai/rules`
- `GET /admin/proxies`
- `GET /admin/rev/live`
- `GET /admin/screens/dashboard`
- `GET /admin/stats/attribution-coverage/recent`
- `GET /admin/stats/chatting-stats`
- `GET /admin/stats/per-employee`
- `GET /admin/users/llm-key-status`
- `GET /admin/users/{user_id}/accounts`
- `POST /admin/stats/xlsx`

</details>

<details><summary>Auto clock-out (off; no members)</summary>


</details>

<details><summary>S4S requests between Creators (off; 13 routes, 1 job)</summary>

- `DELETE /admin/s4s/blocks/{profile_id}`
- `GET /admin/s4s/blocks`
- `GET /admin/s4s/discover`
- `GET /admin/s4s/requests`
- `GET /admin/s4s/requests/proposal`
- `GET /admin/s4s/schedule`
- `POST /admin/s4s/blocks`
- `POST /admin/s4s/requests`
- `POST /admin/s4s/requests/{request_id}/accept`
- `POST /admin/s4s/requests/{request_id}/cancel`
- `POST /admin/s4s/requests/{request_id}/decline`
- `POST /admin/s4s/requests/{request_id}/skip`
- `POST /admin/s4s/slots/{slot_id}/cancel`
- `automation:s4s_check`

</details>

<details><summary>Auto-reply (off; 2 routes, 1 job, 1 send kind)</summary>

- `GET /admin/autoreply-config`
- `PUT /admin/autoreply-config`
- `automation:autoreply`
- `autoreply`

</details>

<details><summary>Welcome-for-info message (off; 1 job, 2 send kinds)</summary>

- `automation:welcome_chatter_for_info`
- `welcome_chatter`
- `welcome_closing_ppv`

</details>

<details><summary>Follow-ups (off; 1 job, 1 send kind)</summary>

- `automation:send_followup`
- `followup`

</details>

<details><summary>Send vault media to a fan (upload) (off; 5 routes, 1 job, 1 send kind)</summary>

- `GET /api/of/v2/vault/upload/drive/list`
- `GET /api/of/v2/vault/upload/fan`
- `GET /api/of/v2/vault/upload/status`
- `POST /api/of/v2/vault/upload/batch`
- `POST /api/of/v2/vault/upload/batch/append`
- `vault-sweep`
- `vault_send`

</details>

<details><summary>Online nudge (off; 4 routes, 2 jobs, 1 send kind)</summary>

- `GET /admin/nudge-config`
- `POST /admin/nudge-config/preview`
- `PUT /admin/nudge-config`
- `PUT /admin/nudge-config/bulk`
- `automation:nudge_online`
- `automation:nudge_online_fire`
- `nudge`

</details>

<details><summary>Purchase follow-up (off; 2 routes, 1 job, 1 send kind)</summary>

- `GET /admin/purchase-followup-config`
- `PUT /admin/purchase-followup-config`
- `automation:purchase_followup`
- `purchase_followup`

</details>

<details><summary>Remote login (off; 8 routes)</summary>

- `GET /admin/login/remote/queue`
- `GET /admin/login/remote/queue/{queue_id}`
- `GET /admin/login/remote/{job_id}`
- `POST /admin/login/remote/queue`
- `POST /admin/login/remote/queue/{queue_id}/cancel`
- `POST /admin/login/remote/start`
- `POST /admin/login/remote/{job_id}/cancel`
- `POST /admin/login/remote/{job_id}/otp`

</details>

<details><summary>Translate (off; 1 route)</summary>

- `POST /admin/translate`

</details>

<details><summary>Leak tracker (off; 11 routes, 2 jobs)</summary>

- `DELETE /admin/leaks/watches/{account_id}`
- `GET /admin/leaks/all`
- `GET /admin/leaks/offer-video/{part}`
- `GET /admin/leaks/roster`
- `GET /admin/leaks/setup`
- `GET /admin/leaks/watches/{account_id}`
- `GET /admin/leaks/watches/{account_id}/offer`
- `POST /admin/leaks/watches/{account_id}/offer-snooze`
- `POST /admin/leaks/watches/{account_id}/tracking`
- `PUT /admin/leaks/key`
- `PUT /admin/leaks/watches/{account_id}`
- `leak-watch-sync`
- `leak-watch-tombstones`

</details>

<details><summary>Copy or import saved replies (off; 3 routes)</summary>

- `GET /admin/saved-replies/import-template`
- `POST /admin/saved-replies/copy`
- `POST /admin/saved-replies/import`

</details>

<details><summary>Small tools not checked yet (off; 6 routes)</summary>

- `GET /admin/full-ai/prepare-content/status`
- `GET /admin/vault-ai/standard-folders`
- `GET /img`
- `POST /admin/full-ai/prepare-content`
- `POST /admin/vault-ai/standard-folders/sync`
- `POST /admin/vault/cache/invalidate`

</details>

<details><summary>API docs pages (off; 8 routes)</summary>

- `GET /docs`
- `GET /docs/oauth2-redirect`
- `GET /openapi.json`
- `GET /redoc`
- `HEAD /docs`
- `HEAD /docs/oauth2-redirect`
- `HEAD /openapi.json`
- `HEAD /redoc`

</details>

<details><summary>Clock-event sales reassignment (off; no members)</summary>


</details>

<details><summary>Creator list (roster) (partial; 1 route)</summary>

- `GET /admin/accounts`

</details>

<details><summary>All inbox (partial; 3 routes)</summary>

- `GET /admin/chats/recent`
- `GET /admin/screens/inbox`
- `POST /admin/view-lease`

</details>

<details><summary>Split inbox (partial; 3 routes)</summary>

- `GET /admin/split-inbox`
- `PATCH /admin/split-inbox`
- `PUT /admin/split-inbox`

</details>

<details><summary>Payroll and shift records (partial; 4 routes)</summary>

- `GET /admin/shifts/records`
- `GET /admin/shifts/timesheet`
- `POST /admin/ingest/transactions/attribute`
- `POST /admin/ingest/transactions/{tx_id}/attribute`

</details>

<details><summary>Feed posts and stories (partial; 32 routes, 2 jobs)</summary>

- `DELETE /api/of/v2/posts/{post_id}`
- `DELETE /api/of/v2/posts/{post_id}/like`
- `DELETE /api/of/v2/posts/{post_id}/pin`
- `GET /api/of/v2/posts`
- `GET /api/of/v2/posts/bookmarks/all`
- `GET /api/of/v2/posts/buyers`
- `GET /api/of/v2/posts/chart`
- `GET /api/of/v2/posts/likes`
- `GET /api/of/v2/posts/search`
- `GET /api/of/v2/posts/stats`
- `GET /api/of/v2/posts/tagged-friend-users`
- `GET /api/of/v2/posts/tips`
- `GET /api/of/v2/posts/top`
- `GET /api/of/v2/posts/{post_id}`
- `GET /api/of/v2/posts/{post_id}/comments`
- `GET /api/of/v2/stories`
- `GET /api/of/v2/stories/archive`
- `GET /api/of/v2/stories/chart`
- `GET /api/of/v2/stories/highlights/{highlight_id}`
- `GET /api/of/v2/stories/top`
- `GET /api/of/v2/stories/viewers`
- `GET /api/of/v2/users/settings/story`
- `PATCH /api/of/v2/users/settings/story`
- `POST /api/of/v2/posts`
- `POST /api/of/v2/posts/{post_id}/archive`
- `POST /api/of/v2/posts/{post_id}/comments`
- `POST /api/of/v2/posts/{post_id}/like`
- `POST /api/of/v2/posts/{post_id}/pin`
- `POST /api/of/v2/stories`
- `POST /api/of/v2/stories/upload`
- `PUT /api/of/v2/posts/{post_id}`
- `PUT /api/of/v2/queue/posts/{post_id}`
- `automation:auto_posts`
- `automation:auto_stories`

</details>

<details><summary>S4S profiles and promo posts (partial; 8 routes, 1 job)</summary>

- `DELETE /admin/s4s/profiles/{account_id}/posts/{post_id}`
- `GET /admin/s4s/media/{media_id}`
- `GET /admin/s4s/profiles`
- `PATCH /admin/s4s/profiles/{account_id}/posts/{post_id}`
- `POST /admin/s4s/profiles/{account_id}/posts`
- `POST /admin/s4s/profiles/{account_id}/posts/{post_id}/primary`
- `PUT /admin/s4s/profiles/{account_id}`
- `PUT /admin/s4s/profiles/{account_id}/posts/{post_id}/media`
- `automation:s4s_post`

</details>

<details><summary>Proxies (partial; 8 routes, 1 job)</summary>

- `DELETE /admin/proxies/{label}`
- `POST /admin/proxies`
- `POST /admin/proxies/assign`
- `POST /admin/proxies/bulk`
- `POST /admin/proxies/{label}/test`
- `POST /admin/proxies/{label}/unbind`
- `POST /admin/proxy-pool/assign`
- `POST /admin/proxy-pool/unbind`
- `proxy-health-probe`

</details>

<details><summary>Connect a Creator (sessions) (partial; 13 routes, 2 jobs)</summary>

- `DELETE /admin/accounts/{account_id}`
- `DELETE /api/of/v2/sessions`
- `GET /api/of/live-window`
- `GET /api/of/v2/sessions`
- `PATCH /admin/accounts/{account_id}`
- `POST /admin/accounts/active`
- `POST /admin/accounts/{account_id}/active`
- `POST /admin/reload-session`
- `POST /admin/session/bootstrap`
- `POST /admin/session/fansly`
- `POST /api/cell/reservations/handoff`
- `POST /api/of/live-window/session`
- `POST /fleet/reservations`
- `pump-supervisor`
- `reservation-activation-retry`

</details>

<details><summary>Relay health and housekeeping (partial; 30 routes, 8 jobs)</summary>

- `DELETE /admin/errors`
- `GET /`
- `GET /admin/_debug/relay-cache-stats`
- `GET /admin/automation-kinds`
- `GET /admin/coalesce/stats`
- `GET /admin/errors`
- `GET /admin/events/stats`
- `GET /admin/img-cache/disk`
- `GET /admin/img-cache/stats`
- `GET /admin/perflog/recent`
- `GET /admin/priority-lanes/stats`
- `GET /admin/secrets`
- `GET /admin/storyboard/stats`
- `GET /admin/streams`
- `GET /admin/system/switches`
- `GET /api/cell/hold`
- `GET /health`
- `GET /img/by-hash/{h}`
- `GET /img/scrub`
- `GET /lanes-panel`
- `GET /lanes-panel/config`
- `GET /lanes-panel/restart`
- `GET /livez`
- `POST /admin/errors`
- `POST /admin/perflog/ingest`
- `POST /img/scrub/cancel`
- `POST /lanes-panel/config`
- `POST /lanes-panel/restart`
- `PUT /admin/secrets`
- `PUT /admin/system/switches/{name}`
- `audit-retention-evictor`
- `img-cache-evictor`
- `payload-size-cap`
- `perflog-evictor`
- `raw-json-evictor`
- `runtime-switches-load`
- `sqlite-optimize`
- `storyboard-evictor`

</details>

<details><summary>Sign-in and security (works; 26 routes)</summary>

- `GET /.well-known/oauth-authorization-server`
- `GET /.well-known/oauth-protected-resource`
- `GET /.well-known/oauth-protected-resource/admin/mcp`
- `GET /auth/2fa`
- `GET /auth/cells`
- `GET /auth/fleet/whois`
- `GET /auth/me`
- `GET /auth/oauth/authorize`
- `GET /chatter/invite/{token}`
- `POST /auth/2fa/activate`
- `POST /auth/2fa/disable`
- `POST /auth/2fa/init`
- `POST /auth/2fa/login`
- `POST /auth/2fa/recovery-codes`
- `POST /auth/actor`
- `POST /auth/login`
- `POST /auth/logout`
- `POST /auth/oauth/authorize`
- `POST /auth/oauth/register`
- `POST /auth/oauth/token`
- `POST /auth/register`
- `POST /auth/sessions/revoke-others`
- `POST /auth/sign-in`
- `POST /chatter/login`
- `POST /chatter/logout`
- `POST /chatter/register`

</details>

<details><summary>Team and access (works; 36 routes, 2 jobs)</summary>

- `DELETE /admin/chatters/invites/{token}`
- `DELETE /admin/employee-groups/{group_id}`
- `DELETE /admin/employees/{employee_id}`
- `DELETE /admin/impersonate`
- `DELETE /admin/users/{user_id}`
- `DELETE /admin/users/{user_id}/accounts/{account_id}`
- `GET /admin/audit`
- `GET /admin/chatters/invites`
- `GET /admin/chatters/{chatter_id}/access`
- `GET /admin/employee-groups`
- `GET /admin/employees`
- `GET /admin/employees/{employee_id}/access`
- `GET /admin/users`
- `GET /admin/users/{user_id}/llm-keys`
- `GET /chatter/me`
- `GET /chatter/me/accounts`
- `GET /chatter/me/folder-access`
- `GET /fleet/agency-copy`
- `PATCH /admin/employee-groups/{group_id}`
- `PATCH /admin/employees/{employee_id}`
- `POST /admin/chatters/invite`
- `POST /admin/chatters/invites/{token}/resend`
- `POST /admin/chatters/link`
- `POST /admin/employee-groups`
- `POST /admin/employees`
- `POST /admin/employees/login`
- `POST /admin/employees/{employee_id}/2fa/reset`
- `POST /admin/employees/{employee_id}/password`
- `POST /admin/impersonate`
- `POST /admin/users/{user_id}/accounts`
- `PUT /admin/chatters/{chatter_id}/account-access`
- `PUT /admin/chatters/{chatter_id}/folder-access`
- `PUT /admin/employee-groups/members`
- `PUT /admin/employees/{employee_id}/access`
- `PUT /admin/employees/{employee_id}/setup`
- `PUT /admin/users/{user_id}/llm-keys`
- `agency-copy-poll`
- `grant-age-watch`

</details>

<details><summary>Shifts and clock-in (works; 13 routes, 1 job)</summary>

- `DELETE /admin/shifts/clock-events/{clock_event_id}`
- `GET /admin/shifts`
- `GET /admin/shifts/clock-events`
- `GET /admin/shifts/clock-status`
- `GET /admin/shifts/clocked-in`
- `GET /admin/shifts/me`
- `PATCH /admin/shifts/clock-events/{clock_event_id}`
- `PATCH /admin/shifts/{shift_id}`
- `POST /admin/shifts`
- `POST /admin/shifts/clock-heartbeat`
- `POST /admin/shifts/clock-in`
- `POST /admin/shifts/clock-out`
- `POST /admin/shifts/{shift_id}/cancel`
- `clock-in-missed`

</details>

<details><summary>Agency settings and alerts (works; 29 routes, 1 job)</summary>

- `DELETE /admin/mcp`
- `DELETE /admin/owner-tokens/{token_id}`
- `DELETE /push/subscription`
- `GET /admin/agency-notifications`
- `GET /admin/ai-key-status`
- `GET /admin/mcp`
- `GET /admin/my-llm-keys`
- `GET /admin/owner-tokens`
- `GET /admin/sensitive-words`
- `GET /admin/sensitive-words/export`
- `GET /admin/sensitive-words/template`
- `GET /admin/settings/applied`
- `GET /admin/settings/{tab}`
- `GET /push/key`
- `POST /admin/agency-notifications/dismiss-all`
- `POST /admin/agency-notifications/read-all`
- `POST /admin/agency-notifications/{notification_id}/dismiss`
- `POST /admin/agency-notifications/{notification_id}/read`
- `POST /admin/mcp`
- `POST /admin/owner-tokens`
- `POST /admin/sensitive-words/add`
- `POST /admin/sensitive-words/delete`
- `POST /admin/sensitive-words/import`
- `POST /admin/sensitive-words/update`
- `POST /push/test`
- `PUT /admin/mcp`
- `PUT /admin/my-llm-keys`
- `PUT /admin/settings/{tab}`
- `PUT /push/subscription`
- `push-send`

</details>

<details><summary>Chat with a fan (works; 50 routes, 4 send kinds)</summary>

- `DELETE /api/of/v2/chats/{chat_id}`
- `DELETE /api/of/v2/chats/{chat_id}/hide`
- `DELETE /api/of/v2/chats/{chat_id}/mark-as-read`
- `DELETE /api/of/v2/chats/{chat_id}/messages/pin`
- `DELETE /api/of/v2/chats/{chat_id}/mute`
- `DELETE /api/of/v2/messages/{message_id}`
- `DELETE /api/of/v2/messages/{message_id}/bookmark`
- `DELETE /api/of/v2/messages/{message_id}/like`
- `DELETE /api/of/v2/messages/{message_id}/pin/user/{user_id}`
- `GET /admin/fans/{account_id}/by-ids`
- `GET /admin/fans/{account_id}/spend-batch`
- `GET /admin/fans/{account_id}/{fan_id}`
- `GET /admin/fans/{account_id}/{fan_id}/insights`
- `GET /admin/fans/{account_id}/{fan_id}/ppv-history`
- `GET /admin/messages/{account_id}/{fan_id}`
- `GET /admin/messages/{account_id}/{fan_id}/attribution`
- `GET /admin/screens/chat`
- `GET /admin/unconfirmed-sends`
- `GET /api/of/v2/automation-restrict/{fan_id}`
- `GET /api/of/v2/chats`
- `GET /api/of/v2/chats/folders`
- `GET /api/of/v2/chats/{chat_id}`
- `GET /api/of/v2/chats/{chat_id}/media`
- `GET /api/of/v2/chats/{chat_id}/media/{kind}`
- `GET /api/of/v2/chats/{chat_id}/messages`
- `GET /api/of/v2/chats/{chat_id}/messages/search`
- `GET /api/of/v2/chats/{chat_id}/pinned`
- `GET /api/of/v2/giphy/proxy/gifs/search`
- `GET /api/of/v2/giphy/proxy/gifs/trending`
- `GET /api/of/v2/labels`
- `PATCH /admin/fans/{account_id}/{fan_id}`
- `POST /admin/copilot/{account_id}/{fan_id}/suggest`
- `POST /admin/messages/{account_id}/{fan_id}/mark-read`
- `POST /admin/messages/{account_id}/{fan_id}/rescrape-now`
- `POST /admin/unconfirmed-sends/dismiss`
- `POST /admin/unconfirmed-sends/resolve`
- `POST /admin/unconfirmed-sends/retry`
- `POST /api/of/v2/chats/mark-as-read`
- `POST /api/of/v2/chats/{chat_id}/hide`
- `POST /api/of/v2/chats/{chat_id}/mark-as-read`
- `POST /api/of/v2/chats/{chat_id}/messages`
- `POST /api/of/v2/chats/{chat_id}/messages/scheduled`
- `POST /api/of/v2/chats/{chat_id}/mute`
- `POST /api/of/v2/labels`
- `POST /api/of/v2/labels/sort`
- `POST /api/of/v2/messages/{message_id}/bookmark`
- `POST /api/of/v2/messages/{message_id}/like`
- `POST /api/of/v2/messages/{message_id}/pin/user/{user_id}`
- `POST /api/of/v2/upload`
- `PUT /api/of/v2/messages/{message_id}/hide`
- `composer`
- `composer_shim`
- `native_schedule`
- `restrict_ack`

</details>

<details><summary>Mass messages (works; 17 routes, 3 jobs, 4 send kinds)</summary>

- `DELETE /admin/do-not-mass`
- `DELETE /api/of/v2/messages/queue/{queue_id}`
- `GET /admin/do-not-mass`
- `GET /admin/mass-messages`
- `GET /admin/paid-messages`
- `GET /api/of/v2/messages/queue`
- `GET /api/of/v2/messages/queue/buyers`
- `GET /api/of/v2/messages/queue/chart`
- `GET /api/of/v2/messages/queue/{queue_id:int}`
- `GET /api/of/v2/messages/templates`
- `POST /admin/do-not-mass`
- `POST /admin/mass-exclude/sync`
- `POST /admin/mass-messages/refresh`
- `POST /admin/messages/detect-mass`
- `POST /api/of/v2/messages/queue`
- `POST /api/of/v2/messages/queue/later`
- `PUT /api/of/v2/messages/queue/{queue_id:int}`
- `automation:mass_premade`
- `automation:send_mass_message`
- `automation:unsend_messages`
- `manual_mass_schedule`
- `manual_mass_send`
- `mass_job`
- `mass_premade`

</details>

<details><summary>Scheduled sends (works; 7 routes, 1 job, 2 send kinds)</summary>

- `DELETE /api/of/v2/scheduled-sends/{job_id}`
- `GET /api/of/v2/scheduled-sends`
- `GET /api/of/v2/schedules`
- `GET /api/of/v2/schedules/later/chat`
- `GET /api/of/v2/schedules/later/post`
- `POST /api/of/v2/scheduled-sends`
- `PUT /api/of/v2/schedules/{schedule_id}/publish`
- `automation:scheduled_send`
- `publish_now`
- `scheduled_send`

</details>

<details><summary>Priority mass (works; 4 routes, 1 job, 1 send kind)</summary>

- `GET /admin/priority-mass/runs`
- `POST /admin/priority-mass/runs`
- `POST /admin/priority-mass/runs/{run_id}/cancel`
- `POST /admin/priority-mass/runs/{run_id}/resume`
- `automation:priority_mass`
- `priority_mass`

</details>

<details><summary>Funnels (works; 8 routes, 1 job, 1 send kind)</summary>

- `DELETE /admin/funnels/{funnel_id}`
- `DELETE /admin/funnels/{funnel_id}/media/{account_id}`
- `GET /admin/funnels`
- `GET /admin/funnels/{funnel_id}`
- `GET /admin/funnels/{funnel_id}/media/{account_id}`
- `POST /admin/funnels`
- `PUT /admin/funnels/{funnel_id}`
- `PUT /admin/funnels/{funnel_id}/media/{account_id}`
- `automation:reply_mass_funnel`
- `funnel`

</details>

<details><summary>Lifecycle messages (works; 3 routes, 4 jobs, 2 send kinds)</summary>

- `GET /admin/lifecycle-message-config`
- `GET /admin/lifecycle-message-config/buyers`
- `PUT /admin/lifecycle-message-config`
- `automation:birthday_message`
- `automation:expired_message`
- `automation:expiry_message`
- `automation:resubscribe_message`
- `lifecycle`
- `lifecycle_initial`

</details>

<details><summary>Welcome message (works; 1 job, 1 send kind)</summary>

- `automation:send_welcome`
- `send_welcome`

</details>

<details><summary>Full AI (works; 15 routes, 2 jobs, 2 send kinds)</summary>

- `GET /admin/full-ai/config`
- `GET /admin/full-ai/mode`
- `GET /admin/full-ai/revenue`
- `GET /admin/full-ai/test/session`
- `GET /admin/full-ai/today`
- `POST /admin/full-ai/config/rollback`
- `POST /admin/full-ai/config/save`
- `POST /admin/full-ai/persona/draft`
- `POST /admin/full-ai/test/photo`
- `POST /admin/full-ai/test/settle`
- `POST /admin/full-ai/test/turn`
- `PUT /admin/full-ai/config/audience`
- `PUT /admin/full-ai/config/checkpoint`
- `PUT /admin/full-ai/config/draft`
- `PUT /admin/full-ai/mode`
- `automation:full_ai_chat`
- `full-ai-catchup-boot`
- `full_ai_live`
- `full_ai_ppv`

</details>

<details><summary>Automation rules (works; 12 routes, 6 jobs)</summary>

- `DELETE /admin/automation-rules/{rule_id}`
- `GET /admin/automation-rules`
- `GET /admin/cell/restore-gap`
- `GET /admin/system/automations`
- `GET /admin/system/runs`
- `PATCH /admin/automation-rules/{rule_id}`
- `POST /admin/automation-rules`
- `POST /admin/automation-rules/switch`
- `POST /admin/automation-rules/{rule_id}/run-now`
- `POST /admin/automation/enqueue`
- `POST /admin/cell-holds/release`
- `POST /admin/cell/restore-gap/confirm`
- `automation-exec`
- `automation:apply_profiles`
- `automation:gen_info`
- `automation:process_old_fans`
- `automation:scrape_chats`
- `automation:scrape_fan`

</details>

<details><summary>Smart lists and OF lists (works; 20 routes, 1 job)</summary>

- `DELETE /admin/smart-lists/{list_id}`
- `DELETE /api/of/v2/lists/{list_id}`
- `DELETE /api/of/v2/lists/{list_id}/users`
- `DELETE /api/of/v2/lists/{list_id}/users/{user_id}`
- `GET /admin/smart-lists`
- `GET /admin/smart-lists/{list_id}/resolve`
- `GET /api/of/v2/lists`
- `GET /api/of/v2/lists/{list_id}`
- `GET /api/of/v2/lists/{list_id}/posts`
- `GET /api/of/v2/lists/{list_id}/users`
- `PATCH /admin/smart-lists/{list_id}`
- `PATCH /api/of/v2/lists/{list_id}`
- `PATCH /api/of/v2/lists/{list_id}/pin-chat`
- `POST /admin/smart-lists`
- `POST /admin/smart-lists/preview`
- `POST /admin/smart-lists/{list_id}/activate`
- `POST /admin/smart-lists/{list_id}/deactivate`
- `POST /api/of/v2/lists`
- `POST /api/of/v2/lists/users`
- `POST /api/of/v2/lists/{list_id}/users/{user_id}`
- `automation:smart_list_sync`

</details>

<details><summary>Saved replies (works; 13 routes)</summary>

- `DELETE /admin/saved-replies/{reply_id}`
- `GET /admin/saved-replies`
- `GET /admin/saved-replies/overview`
- `GET /admin/saved-replies/sequences`
- `POST /admin/saved-replies`
- `POST /admin/saved-replies/bulk`
- `POST /admin/saved-replies/delete`
- `POST /admin/saved-replies/fill/apply`
- `POST /admin/saved-replies/fill/plan`
- `POST /admin/saved-replies/fill/undo`
- `POST /admin/saved-replies/relabel`
- `POST /admin/saved-replies/sent`
- `PUT /admin/saved-replies/{reply_id}`

</details>

<details><summary>Vault library (works; 67 routes, 1 job)</summary>

- `DELETE /admin/vault-ai/category-icons/{category}`
- `DELETE /admin/vault-ai/internal-folders/{folder_id}`
- `DELETE /admin/vault-ai/of-folders/{list_id}`
- `GET /admin/vault-ai/cache/summary`
- `GET /admin/vault-ai/category-icons`
- `GET /admin/vault-ai/collect/status`
- `GET /admin/vault-ai/describe-all/plan`
- `GET /admin/vault-ai/describe-all/status`
- `GET /admin/vault-ai/download`
- `GET /admin/vault-ai/download/info`
- `GET /admin/vault-ai/download/resign`
- `GET /admin/vault-ai/duplicates`
- `GET /admin/vault-ai/flags-accuracy`
- `GET /admin/vault-ai/flags-all/status`
- `GET /admin/vault-ai/flags-review`
- `GET /admin/vault-ai/folder-plan`
- `GET /admin/vault-ai/folder-prices`
- `GET /admin/vault-ai/harvest-keywords/status`
- `GET /admin/vault-ai/image`
- `GET /admin/vault-ai/internal-folders`
- `GET /admin/vault-ai/items`
- `GET /admin/vault-ai/of-folders`
- `GET /admin/vault-ai/pack-candidates`
- `GET /admin/vault-ai/poster`
- `GET /admin/vault-ai/settings`
- `GET /admin/vault-ai/tag-facets`
- `GET /admin/vault-ai/thumb`
- `GET /admin/vault/fan-history`
- `GET /admin/vault/media-stats`
- `GET /admin/vault/wall-media`
- `GET /api/of/v2/vault/lists`
- `GET /api/of/v2/vault/media`
- `GET /api/of/v2/vault/media/{media_id}`
- `PATCH /admin/vault-ai/items/{media_id}`
- `POST /admin/vault-ai/category-icons/{category}`
- `POST /admin/vault-ai/collect`
- `POST /admin/vault-ai/collect/continue`
- `POST /admin/vault-ai/collect/stop`
- `POST /admin/vault-ai/describe`
- `POST /admin/vault-ai/describe-all`
- `POST /admin/vault-ai/duplicates/hide`
- `POST /admin/vault-ai/flags-all`
- `POST /admin/vault-ai/flags-review/grade`
- `POST /admin/vault-ai/folder-plan/apply`
- `POST /admin/vault-ai/folder-prices`
- `POST /admin/vault-ai/folders/from-tags`
- `POST /admin/vault-ai/folders/{folder_id}/publish`
- `POST /admin/vault-ai/harvest-keywords`
- `POST /admin/vault-ai/internal-folders`
- `POST /admin/vault-ai/internal-folders/{folder_id}/add`
- `POST /admin/vault-ai/internal-folders/{folder_id}/remove`
- `POST /admin/vault-ai/internal-folders/{folder_id}/rename`
- `POST /admin/vault-ai/internal-folders/{folder_id}/reorder`
- `POST /admin/vault-ai/items/{media_id}/hide`
- `POST /admin/vault-ai/of-folders`
- `POST /admin/vault-ai/of-folders/sort`
- `POST /admin/vault-ai/of-folders/{list_id}/add`
- `POST /admin/vault-ai/of-folders/{list_id}/remove`
- `POST /admin/vault-ai/of-folders/{list_id}/rename`
- `POST /admin/vault-ai/pack-triage`
- `POST /admin/vault-ai/reorder`
- `POST /admin/vault-ai/search-of`
- `POST /admin/vault-ai/sync`
- `POST /admin/vault/fan-history/sync`
- `POST /admin/vault/sends`
- `POST /admin/vault/sends/backfill`
- `PUT /admin/vault-ai/settings`
- `vault-collect`

</details>

<details><summary>Customs (works; 5 routes, 1 job)</summary>

- `GET /admin/customs`
- `GET /admin/customs/context`
- `GET /admin/customs/order`
- `POST /admin/customs/brief`
- `POST /admin/customs/clear`
- `automation:customs_watch`

</details>

<details><summary>Auto-follow (works; 2 routes, 1 job)</summary>

- `GET /admin/auto-follow/records`
- `GET /admin/auto-follow/stats`
- `automation:auto_follow`

</details>

<details><summary>Promotions and trials (works; 22 routes, 1 job)</summary>

- `DELETE /admin/promotions/{mirror_id}`
- `DELETE /admin/trial-links/{mirror_id}`
- `DELETE /api/of/v2/promotions/{promo_id}`
- `DELETE /api/of/v2/trials/{trial_id}`
- `GET /admin/promotions`
- `GET /admin/trial-links`
- `GET /api/of/v2/promotions`
- `GET /api/of/v2/promotions/chart`
- `GET /api/of/v2/promotions/claims`
- `GET /api/of/v2/promotions/stats`
- `GET /api/of/v2/trials`
- `GET /api/of/v2/trials/chart`
- `GET /api/of/v2/trials/claims`
- `GET /api/of/v2/trials/share-access`
- `GET /api/of/v2/trials/stats`
- `PATCH /admin/promotions/{mirror_id}`
- `POST /admin/promotions`
- `POST /admin/trial-links`
- `POST /api/of/v2/promotions`
- `POST /api/of/v2/promotions/{promo_id}/finish`
- `POST /api/of/v2/trials`
- `POST /api/of/v2/trials/share-access`
- `automation:promo_reactivate`

</details>

<details><summary>Tracking link stats (works; 25 routes, 1 job)</summary>

- `DELETE /admin/of-tracking-links/{campaign_id}`
- `DELETE /admin/tracking-links/{link_id}`
- `DELETE /api/of/v2/campaigns/share-access`
- `DELETE /api/of/v2/campaigns/{campaign_id}`
- `GET /admin/link-metrics/fans`
- `GET /admin/of-tracking-links`
- `GET /admin/of-tracking-links/earnings`
- `GET /admin/of-tracking-links/{campaign_id}/fans`
- `GET /admin/promo-list`
- `GET /admin/tracking-links`
- `GET /admin/tracking-links/summary`
- `GET /admin/tracking-links/{link_id}/analytics`
- `GET /api/of/v2/campaigns`
- `GET /api/of/v2/campaigns/chart`
- `GET /api/of/v2/campaigns/claimers`
- `GET /api/of/v2/campaigns/share-access`
- `GET /api/of/v2/campaigns/stats`
- `PATCH /admin/tracking-links/{link_id}`
- `POST /admin/of-tracking-links`
- `POST /admin/tracking-links`
- `POST /api/of/v2/campaigns`
- `POST /api/of/v2/campaigns/share-access`
- `PUT /admin/link-meta`
- `PUT /admin/link-meta/batch`
- `PUT /admin/promo-list`
- `link-figures-prewarm`

</details>

<details><summary>Stats and reports per Creator (works; 44 routes, 1 job)</summary>

- `GET /admin/reports/catalogue`
- `GET /admin/reports/files/{file_id}`
- `GET /admin/stats/attribution-coverage`
- `GET /admin/stats/automation-runs`
- `GET /admin/stats/fan-report`
- `GET /admin/stats/grok-calls`
- `GET /admin/stats/grok-cost`
- `GET /admin/stats/per-automation`
- `GET /admin/stats/per-fan-data`
- `GET /admin/stats/per-model`
- `GET /admin/stats/referrals`
- `GET /admin/stats/revenue`
- `GET /admin/stats/sales-records`
- `GET /admin/tips-list`
- `GET /admin/top-tippers`
- `GET /api/of/v2/earnings/chart`
- `GET /api/of/v2/fans-activity/list`
- `GET /api/of/v2/init`
- `GET /api/of/v2/payments/referrals/balance`
- `GET /api/of/v2/payouts/balances`
- `GET /api/of/v2/payouts/chargebacks`
- `GET /api/of/v2/payouts/chargebacks/chart`
- `GET /api/of/v2/payouts/chargebacks/ratio`
- `GET /api/of/v2/payouts/chart`
- `GET /api/of/v2/payouts/check-receive`
- `GET /api/of/v2/payouts/download-approved-invoice`
- `GET /api/of/v2/payouts/referrals/chart`
- `GET /api/of/v2/payouts/requests`
- `GET /api/of/v2/payouts/requests/referral`
- `GET /api/of/v2/payouts/stats`
- `GET /api/of/v2/payouts/transactions`
- `GET /api/of/v2/streaks`
- `GET /api/of/v2/streaks/top`
- `GET /api/of/v2/users/me/profile/stats`
- `GET /api/of/v2/users/me/stats/messages/direct`
- `GET /api/of/v2/users/me/stats/messages/group`
- `GET /api/of/v2/users/me/stats/overview`
- `GET /api/of/v2/users/me/stats/today-activity`
- `GET /api/of/v2/users/me/stats/top/post`
- `GET /api/of/v2/users/me/stats/top/{kind}`
- `PATCH /api/of/v2/payouts/requests`
- `POST /admin/reports/files`
- `POST /admin/reports/run`
- `POST /api/of/v2/payouts/requests`
- `of-stats-daily`

</details>

<details><summary>Sales ingest (works; 7 routes, 2 jobs)</summary>

- `GET /admin/ingest/transactions/health`
- `GET /admin/ingest/transactions/orphan-tips`
- `GET /admin/ingest/transactions/sales-needing-attribution`
- `POST /admin/ingest/transactions/{account_id}/pause`
- `POST /admin/ingest/transactions/{account_id}/resume`
- `POST /admin/ingest/transactions/{account_id}/run`
- `POST /admin/roster/{account_id}/crawl`
- `tx-ingest-fast-poll`
- `tx-ingest-supervisor`

</details>

<details><summary>Creator settings (works; 9 routes)</summary>

- `GET /admin/account-config`
- `GET /admin/of-consent/{account_id}`
- `GET /admin/ofm-writes/{account_id}`
- `GET /admin/style-config`
- `GET /api/of/ofm-writes`
- `PUT /admin/account-config`
- `PUT /admin/of-consent/{account_id}`
- `PUT /admin/ofm-writes/{account_id}`
- `PUT /admin/style-config`

</details>

<details><summary>AI assistant (works; 10 routes)</summary>

- `GET /admin/assistant/do-caps`
- `GET /admin/assistant/history`
- `GET /admin/ultra/plans/{plan_id}`
- `POST /admin/assistant/ask`
- `POST /admin/assistant/draft`
- `POST /admin/assistant/edit/apply`
- `POST /admin/ultra/plans`
- `POST /admin/ultra/plans/{plan_id}/cancel`
- `POST /admin/ultra/plans/{plan_id}/ok`
- `POST /admin/ultra/plans/{plan_id}/pick`

</details>

<details><summary>Support chat (works; 15 routes)</summary>

- `GET /admin/support/thread`
- `GET /admin/support/unread`
- `GET /support`
- `GET /support/api/instance/thread`
- `GET /support/api/instance/unread`
- `GET /support/api/threads`
- `GET /support/api/threads/{thread_id}`
- `POST /admin/support/messages`
- `POST /admin/support/read`
- `POST /support/api/instance/messages`
- `POST /support/api/instance/read`
- `POST /support/api/login`
- `POST /support/api/logout`
- `POST /support/api/summarise`
- `POST /support/api/threads/{thread_id}/reply`

</details>

<details><summary>OF profile, fans and streams (works; 65 routes)</summary>

- `DELETE /api/of/v2/streams/obs/key`
- `DELETE /api/of/v2/streams/users/{user_id}/block`
- `DELETE /api/of/v2/subscriptions/bundles/{bundle_id}`
- `DELETE /api/of/v2/users/links/{link_id}`
- `DELETE /api/of/v2/users/social/buttons/{button_id}`
- `DELETE /api/of/v2/users/{user_id}/block`
- `DELETE /api/of/v2/users/{user_id}/restrict`
- `GET /api/of/v2/countries`
- `GET /api/of/v2/release-forms`
- `GET /api/of/v2/release-forms/mentions`
- `GET /api/of/v2/streams/chart`
- `GET /api/of/v2/streams/feed`
- `GET /api/of/v2/streams/top`
- `GET /api/of/v2/streams/users/blocked`
- `GET /api/of/v2/streams/viewers`
- `GET /api/of/v2/subscribers`
- `GET /api/of/v2/subscriptions/bundles`
- `GET /api/of/v2/subscriptions/count/all`
- `GET /api/of/v2/subscriptions/subscribers/chart`
- `GET /api/of/v2/subscriptions/subscribers/latest`
- `GET /api/of/v2/subscriptions/subscribers/top`
- `GET /api/of/v2/users/links`
- `GET /api/of/v2/users/list`
- `GET /api/of/v2/users/me`
- `GET /api/of/v2/users/me/profile/views/qr`
- `GET /api/of/v2/users/me/referrals`
- `GET /api/of/v2/users/me/settings`
- `GET /api/of/v2/users/me/start-date-model`
- `GET /api/of/v2/users/notifications`
- `GET /api/of/v2/users/notifications/count`
- `GET /api/of/v2/users/notifications/money`
- `GET /api/of/v2/users/performers-search`
- `GET /api/of/v2/users/search`
- `GET /api/of/v2/users/settings/notifications/{transport}`
- `GET /api/of/v2/users/social/buttons`
- `GET /api/of/v2/users/{user_id_or_username}`
- `GET /api/of/v2/users/{user_id}/posts`
- `GET /api/of/v2/users/{user_id}/posts/photos`
- `GET /api/of/v2/users/{user_id}/posts/videos`
- `GET /api/of/v2/users/{user_id}/stories`
- `GET /api/of/v2/users/{user_id}/stories/highlights`
- `GET /api/of/v2/users/{user_id}/streams`
- `PATCH /api/of/v2/release-forms/toggle-show`
- `PATCH /api/of/v2/users/me`
- `PATCH /api/of/v2/users/me/reply-on-subscribe`
- `PATCH /api/of/v2/users/me/settings/security`
- `PATCH /api/of/v2/users/settings/notifications`
- `POST /api/of/v2/guests`
- `POST /api/of/v2/streams`
- `POST /api/of/v2/streams/users/{username}/block`
- `POST /api/of/v2/subscriptions/bundles`
- `POST /api/of/v2/users/me/profile-image`
- `POST /api/of/v2/users/notifications/read`
- `POST /api/of/v2/users/{user_id}/block`
- `POST /api/of/v2/users/{user_id}/restrict`
- `PUT /api/of/v2/subscriptions/bundles/{bundle_id}`
- `PUT /api/of/v2/subscriptions/{user_id}`
- `PUT /api/of/v2/subscriptions/{user_id}/custom-name`
- `PUT /api/of/v2/subscriptions/{user_id}/discount`
- `PUT /api/of/v2/subscriptions/{user_id}/note`
- `PUT /api/of/v2/users/links`
- `PUT /api/of/v2/users/me/settings/security`
- `PUT /api/of/v2/users/me/settings/security/blocked-countries`
- `PUT /api/of/v2/users/me/settings/security/blocked-ips`
- `PUT /api/of/v2/users/social/buttons`

</details>

<details><summary>Live updates (works; 1 route, 4 jobs)</summary>

- `GET /events`
- `badge-reads`
- `chat-sweep-cadence`
- `persist-worker`
- `shared-refresher`

</details>
