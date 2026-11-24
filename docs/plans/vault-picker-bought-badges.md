# Vault picker: bought / sent badges (AE report 2026-11-23)

Chatters can't tell in the picker which media a fan already bought/was sent.

## What exists (measured, code read)
- `vault_sends` (per fan × media; `was_purchased`) + `GET /admin/vault/fan-history` (local DB, no OF) → picker ring + corner pill (`vaultTileStatus.ts`, `VaultPickerTile.tsx`). Bought = green ring + "$X" pill, greyed. Text never says "bought".
- Writers: send-time `POST /admin/vault/sends`; chat-open `POST /admin/vault/sends/backfill` from loaded thread pages (isOpened → was_purchased); `ownership.stamp_*` from purchase notifications (30 s poll of OF purchases feed, already running) + ledger linker.
- OF `GET /chats/{fan}/media?from_user=<creator>&skip_users=all[&purchased=1]` already used by FanDrawer (Sales + Unsold, first 20 each) — frontend-only cache, never lands in DB.

## Gaps
1. Backfill SKIPS existing rows → send-time row (was_purchased NULL) never flips when the thread later shows `isOpened=true`.
2. Only loaded thread pages backfill → older sends/buys (long-tenure fans) invisible.
3. `purchase_notified` SSE does not invalidate `["vault-history"]` → open picker stale until 60 s / reopen.
4. Badge copy: "$12" on green ≠ "BOUGHT".

## Plan
- Backfill inserts missing sends by (media, message) and promotes bought sends to `was_purchased=True`. A changed batch returns history.
- `POST /admin/vault/fan-history/sync {account_id, fan_id}` returns local history. When due, it walks the signed Creator's chat gallery with up to 10 pages of 50 messages, as an `of_pacing.walk` (pages paced per Creator, one retry on OF's 429). Successful walks are cached for 7 days. Any failure, a 429 included, stamps a 1-hour cooldown.
- Chat open warms the fan history cache with the sync response. The relay broadcasts `vault_history_changed {fan_id}` after purchase stamps commit. This event and `transaction_recorded` invalidate the scoped history key.
- Tiles show “BOUGHT” with a paid total when known, “SENT $X” for locked sends, or “SENT FREE” for free sends.

## Calls saved / added
- A due fan adds a walk of up to 10 pages. The first concurrent open owns the walk; repeat opens during the freshness window use the local history.
- FanDrawer keeps its own gallery reads for thumbnails and text.

## Out of scope
Mass-message buys without per-fan media (placeholder rows) — ownership already resolves via MassBroadcastCache.

## Codex review (2026-11-23) → decisions
- Purchase race: `purchase_notified` fires BEFORE the stamp → instead broadcast `vault_history_changed {fan_id}` after a stamp commits (chat + post lanes); frontend invalidates `["vault-history"]` on it and on `transaction_recorded`.
- Backfill client: release tracked message keys after a failed POST; re-submit when a priced message flips isOpened; react to `updated>0` too.
- Persist OF `createdAt` as `sent_at` in backfill + sync (old sends were stamped "now").
- Pill: unlocked → "BOUGHT" (+ total paid if known, never last ask price); locked → "SENT $X"; free → "SENT FREE".
- Sync: pages run inside `of_pacing.walk` (paced per Creator, one 429 retry, held while the Creator's gate cools), persist the failure cooldown (`last_attempt_at`, 1 h) for every failure.
- Proxy sniff dropped: sync is once per 7 d per fan, sniff saves ~nothing and needs sender verification.
- Kept gallery sync despite codex "measure first": owner asked for fetch-on-open-if-uncached.
