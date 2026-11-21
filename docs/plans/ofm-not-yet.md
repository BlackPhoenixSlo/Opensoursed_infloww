# OF Manager: every "not yet" control works, proven live on founder

Goal (owner, 2026-11-20, verbatim): Make every OF Manager control that shows "Not available in Inflowwww yet" or "Read-only in Inflowwww for now" actually work, and prove each one live on the owner's OF account founder (80000112, session in service/sessions/accounts/80000112).

Source of scope: headless sweep 2026-11-20 of 154 OF Manager pages on main (scripts/of-mirror-check/dead.py mocks, scope model:1, 1440x900), per-page lists in docs/of-manager/not-yet-sweep-2026-11-20.json (`ny` = shows the Not-yet title, `dis` = disabled only while a form is empty, OF's own behaviour, not in scope). Doc-listed gaps from docs/infloww-parity-matrix.md §3.2 and docs/of-manager/*.md. Release forms was not in the sweep.

The Phases below regroup the owner's scope bullets by risk; every bullet of the owner's message sits in exactly one Phase.

## Method (all Phases)
Capture OF's real request per control from the logged-in account (REA / browser capture), add relay route in service/ + binder in app/lib/ofMirror*.ts, mark data-oi-wired, drop the NOT_YET title in scripts/of-mirror.mjs, update the dead.py and of-mirror-check tests, then drive it on the running app against 80000112 and screenshot the trigger + end state + confirm the OF-side result.

## Hard limits on the live account (59 real subscribers) — all Phases
- Never mass-send, never post to all fans without immediately deleting; prefer a list, a scheduled post deleted before it fires, or the owner-named test fan via included_users.
- Never: Delete account, a real withdrawal or any bank/payout/DAC7 submit, a real password/email/phone change. For these, wire them and prove with the captured request shape + a mocked relay; ask the owner first.
- Go live: ask the owner before any real stream (it notifies subscribers); "Available to" a test list if OF allows.
- Close all sessions and block by IP/country can lock our session out: run them last or against a harmless value, then revert.
- OAuth sign-ins (Google/X/Spotify/MetaMask): hand off to OF's page; no live link.
- Every live write gets undone afterwards (delete post/list/link, unblock, restore setting); log each in the PR.

## Open questions for the owner
Which fan id to use for message/PPV tests; whether a short live stream is OK; whether to skip Bank/account-security entirely as "stays on onlyfans.com".

## Phase 0 — Live capture and proof harness
The Method's shared machinery: capturing OF's request per control from 80000112, the live-proof run on the running app (trigger + end state screenshots, OF-side confirmation), and the undo log that every later Phase's live writes go through. The hard limits are enforced here.

## Phase 1 — Read-only gaps (reads, filters, tabs, search, sort)
Depends on Phase 0.
- Statistics: every disabled sub-tab (stories/streaming engagement, messages mass/direct + search, fans subs/top-fans tabs, visitors guests/users, referrals, earnings radio).
- Statements: date range.
- Notifications: user/post search, the disabled tab, new-events button.
- Collections/Bookmarks: Search, Sort, Compact view, Posts tab; subscribers list search/Filter/Expired/Restricted/Blocked/Promotions/Fan Stats.
- My profile: Compact view, Sort, search posts.
- Messages Basic: Find, filter Select, folders Sort.
- Home: feed-tab Sort; story All/Purchased.

## Phase 2 — Content and chat writes
Depends on Phase 0.
- Home: post ⋯ More, Record video/voice; another creator's post Hide/Report.
- New post: Record video/voice; labels, expiration, target (read-only per docs).
- My profile: Create highlight.
- Messages Basic: chat More, Report, Save for Later, Tag other creators; bubbles' Countdown, Copy as draft, Unsend PPV.
- Vault: list More. Queue: both auto-publish switches + intervals.
- Collections/Bookmarks: Pin to home, More, Create new list from Bookmarks.
- Release forms: Create new release form.

## Phase 3 — OF settings, privacy and links
Depends on Phase 0.
- OF settings: security (restricted/blocked lists, block by country/IP), sessions, messaging Restricted + switch, notification email frequency, profile buttons, social Add button, Spring Store, streaming OBS key copy/reset + Block, Create link, tracking-links Sort/"Shared with you"/create inside the modal, trial-link create inside the modal, the promotion modal's Start campaign/Add bundle.
- OAuth hand-offs: Google/X sign-in, connected accounts, Spotify (settings and My profile), MetaMask/NFT.

## Phase 4 — Go live
Depends on Phase 0.
- Go live: Post to X, Available to, tip goal, show tips, private comments with tips, description, Start Live Video; schedule form Add cover + Search.

## Phase 5 — Money and account-critical (mocked proof only)
Depends on Phase 0.
- Bank: payments, cards, payout types, DAC7, support.
- Statements: support form.
- OF settings account: password, username, email, phone, 2FA passwordless, delete.

## Phase 6 — Live check of built-but-untested controls
Depends on Phase 0.
- Co-tagged post, upload dedupe, vault thumbnails via /img, Tips feed, stories/highlights shapes, Statements invoice/state/reason, Queue Publish now/Send now, Vault custom order save.
