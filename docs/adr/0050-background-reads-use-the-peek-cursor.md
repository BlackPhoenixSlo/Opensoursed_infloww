# Background reads use the Peek cursor, because a first-page thread GET marks the chat read

**Status: proposed** (2026-11-22, `docs/spec/creator-badges/goal.txt` Phase A, D22, D23, D25, D26 in `.scratch/creator-badges/evidence/fable-r3-final.md`; replaces the rule recorded at `service/webhook_dispatch.py:79` and `:372`; nothing built yet).

The code holds that a scrape GET "does NOT mark the chat read on OF (owner confirmed 2026-11-07)", and sweeps, the after-blast scrape, convo review and the app's prefetches read threads freely on that basis. Two sandbox rounds measured the opposite: `GET /chats/{fan}/messages` without an `id` cursor marks the chat read, including a full sweep walk's first request (3/3) and the `order=asc&offset=0` backfill page (3/3), while `id=9223372036854775807` returned the newest page and left the chat unread (10/10). OnlyFans cannot tell a scrape from an Employee opening the chat. We decided every Background read passes the Peek cursor: `scrape_chats._fetch_recent_end` page 1, the after-blast scrape, `convo_review_fetch`, and the app's unread, hover and Focus prefetch through a Relay `peek=1` parameter; the ascending backfill runs only on chats already read and waits on unread ones; Focus mode loads with peek and keeps marking read after the first send. A Click read still marks read on purpose. Why: the Red circle is worthless if our own reads keep clearing it, and the Peek cursor costs nothing extra where skipping prefetch would cost the operator speed. The cost: every new thread reader must remember the cursor (the `badge_drift` Watch check flags a counter drop within 2 s of an un-peeked first-page GET); an unread chat's deep history waits until it is read; and the peek page's equality with the plain first page is measured only on a 3-message chat, so Phase A's acceptance checks a long thread.
Owner accepted the sandbox findings incl. the peek cursor 2026-11-22 (goal.txt OWNER AMENDMENTS): this rule replaces the 11-07 "scrape ≠ read" rule.

## Considered Options

- **Keep the 11-07 rule.** Rejected: measured false 3/3, 3/3 and 10/10.
- **Stop Background reads on unread chats.** Rejected: slower Fan List and Focus for the operator, while the Peek cursor reads them without marking.
- **Re-mark chats unread after reading.** Rejected: an extra write per read, a visible flicker on OnlyFans, and a race with a real read.
