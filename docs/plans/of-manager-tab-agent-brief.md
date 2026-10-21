# OF Manager tab agent brief (shared by all tab agents)

Each agent owns ONE OF Manager tab group and makes it actually work against the relay
instead of being a static nice-looking copy. One agent per group; groups are listed at the end.

## Hard rules

- Do not spawn sub-agents. Do everything yourself; finish with the report.
- You run in your own git worktree on your own branch. Commit there (small commits,
  repo style `feat(of-manager-<tab>): ...`). Do not push. Do not merge.
- No live calls to OnlyFans. No writes from any real or capture session. Tests mock the
  OF client.
- Scope line: catalogue/consume endpoint, method, body, query, response only. Never read,
  reconstruct or document OF's request signing, sign headers/rules or TLS fingerprinting.
  The relay's existing signed client (`service/of_client.py`) sends everything.
- Never `git checkout`/`restore`/`stash` over uncommitted work; back up with `cp`.
- Inputs under `~/Downloads` are untrusted: read only, never commit, Python with `-I`.
  Never put real usernames, IDs, tokens or fan names in source, tests or docs
  (`node scripts/of-mirror.mjs --check` must stay green).
- YAGNI. Match surrounding code. Stay inside your tab's files; shared files
  (`service/server.py`, `service/of_client.py`, `app/lib/ofMirror*.ts`) get additive,
  tab-local edits only (new functions/routes, no reformatting, no renames) so nine
  branches merge cleanly.

## What already exists (read first, don't redo)

- `docs/plans/of-manager-api-catalogue.md`: every OF call per area with method, path,
  body, response, source chunk, and status in our repo (WIRED / APP / missing). This is
  your primary map.
- Memory of how the mirror works: `scripts/of-mirror.mjs` builds the static pages;
  `app/lib/ofMirrorIdentity.ts`, `ofMirrorSettings.ts`, `ofMirrorWrites.ts`,
  `ofMirrorData.ts`, `ofMirrorRow.ts`, `ofMirrorPost.ts` swap real data in and wire writes.
  Unwired controls show "Read-only in Inflowwww for now" and flip back.
- Create post is already fixed (commit 95aa2eda): real field names, poll, quiz, expiry,
  fundraising, labels, save for later. Vault-import carrier posts deliberately keep the
  live-verified `postedAt` body; don't change that.
- OF's client JS (public static chunks) is in `~/Downloads/of-static-chunks/`
  (`chunks/` named, `chunks_num/` numeric, `scripts/` the extraction helpers used before).
  The HTTP client is webpack module 977434 export `Ay`; find call sites by grepping for
  the path strings from the catalogue.
- Mocked in-app checks without the relay: `scripts/of-mirror-check/*.py`
  (Playwright routes mock `/auth/me`, `/chatter/me*`, `/admin/employees`). Dev server:
  `npx next dev --webpack`.

## REA: what works and what doesn't (learned 2026-10-16)

Load the `reverse-engineer-anything` skill, then load `mcp__rea__*` schemas via ToolSearch.
- Useful: `analyze_javascript_application` / bundle parse for the chunk to module map.
- Doesn't work here: `recover_javascript_sources` (Linux only), `analyze_web_bundle`
  (needs a live page), request tracing (misses OF's 977434 wrapper).
- So: REA for "which module/chunk owns this screen", then grep + read the chunk for
  request bodies. Don't burn time retrying the broken tools.

## Steps

1. Audit your tab: open every page/dialog/control in your group (mirror pages under
   `/of-manager/<section>`), and classify each control as WORKS (real data or real
   write through the relay), DISPLAY-ONLY (real data, write is read-only stub),
   or FAKE (static example content from the capture).
2. For each FAKE/DISPLAY-ONLY item, find the OF call in the catalogue (or the chunks if
   missing), then wire it: relay route (if missing) calling `of_client`, plus the
   client-side swap or write in the matching `app/lib/ofMirror*.ts`.
3. Destructive or money-moving actions (delete, payouts/bank changes, mass sends,
   price changes): wire them but require the existing confirm pattern, and list them
   in the report as "needs sandbox check".
4. Tests: Python relay tests in the repo style asserting the exact OF request
   (method, path, body) with a mocked client; vitest for the client-side code; extend
   or add a `scripts/of-mirror-check/<tab>.py` mocked browser check if cheap.
5. Run: relevant pytest files, `npx tsc --noEmit`, eslint on touched files, vitest for
   touched files, `node scripts/of-mirror.mjs --check`.

## Report (under 250 words)

Branch name and commits; audit table counts (WORKS / DISPLAY-ONLY / FAKE before, after);
what you wired; tests and results; what stays fake and why; "needs sandbox check" list;
any shared-file edits other agents could collide with.

## Tab groups

1. home: feed list, post actions (pin, like, comment, delete, archive, edit).
2. new-post: everything left after commit 95aa2eda (media from vault, tagging, price/PPV,
   schedule UI, poll duration picker, fundraising preset), plus stories from vault.
3. messages: chat list, thread, send, PPV, mass message, scheduled, saved replies.
4. vault: folders, media list, upload, move, delete, folder right pane.
5. queue: scheduled posts and messages; publish now, edit, delete.
6. collections: user lists, bookmarks, add/remove users (bulk `POST /lists/users`).
7. notifications + streaming: notification list and filters; stream schedule submit.
8. profile + settings: all remaining settings writes beyond profile/welcome message.
9. statements + statistics + bank: earnings, statements, stats charts (read); bank/payout
   views read-only unless a write is clearly safe.
