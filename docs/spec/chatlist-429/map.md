# Chat-list deep-page 429s — wayfinder map

## Destination
A decided, ticketed fix plan so the inbox chat list never auto-loads pages a chatter did not ask for, stops OF rate-limiting a busy Creator on hops, and keeps deeper pages reachable on demand. Bundle the owner approved 2026-11-26: dynamic 2–4 page auto-load cap, trim cached deep pages, dedupe page requests, caller tag, relay refusal of page ≥5 without an explicit click, no long 429 hold. Plus a verdict on each out-of-the-box idea.
ASSUMPTION: destination is the plan only (no code); rejected reading: "build it now" — no `--execute` given.

## Notes
- Evidence (measured, AE relay journal 2026-11-25 19:40–00:00Z, sanitized): one busy Creator ("Creator A", ~500 OF calls/h, mostly background scrape_chats) took all 429s; 29 of 39 relay list holds at offset 100/125; one Split Inbox chatter hopping 3 Creators every 30–60 s; each hop walks offsets 0–75, often 3–4 identical same-second requests; offset 100 → OF 429 → gate ~40 s → 502; 48 failed loads in ~4 h; relay 429 hold 1.0 s.
- Prior debate (Fable, Codex Astra, devil's advocate, six hats) lives outside git in the T3 worktree `.scratch/chatlist-429/` (has real ids, kept out of this map).
- Owner: 30 s hold too long; loves client cap + dedupe; wants dynamic 2–4 not fixed 4; asks if out-of-the-box ideas are needed.

## Decisions so far
Adversary: Codex Astra (gpt-6.2-astra) blind [astra-phase1.md](astra-phase1.md) + with drafts [astra-phase2.md](astra-phase2.md).
- [Dynamic auto-load cap 2–4](issues/01-dynamic-autoload-cap.md): 2 pages; 3–4 only while <8 rows visible; never >4 auto; then 1 page per click/fresh scroll; one budget for every auto path.
- [Trim cached deep pages](issues/02-trim-cached-deep-pages.md): reframed — cap the replay walk in the queryFn (deep cached pages returned without network), no data trim.
- [Dedupe page requests](issues/03-dedupe-page-requests.md): join in-flight fetches + queued explicit continuation; one post-bust head refresh per hop.
- [Relay refuses deep pages without a click](issues/04-relay-deep-page-refusal.md): 428 at offset ≥ 4×limit without `X-List-Intent: explicit`; fan-out-safe; chat-list wait ≤5 s.
- [Caller tag and prod proof](issues/05-caller-tag-and-proof.md): `X-List-Caller` on the real fetch, through bundles; new `chatlist_deep_auto` watch check.
- [Out-of-the-box ideas](issues/06-ootb-ideas-verdict.md): none needed now; merged unread view already exists; a/e later on measured triggers; b/c drop; f folded into 04.

## Not yet specified
- Implementation tickets (spec-auto) for 01–05 as one client PR + one relay PR; slop not needed (no volume change).
- Fail-fast on offset>0 pages (give up in ~1 s, keep rows, show Load more) — deferred unless 429s persist after the bundle.
- Old open tabs keep the old bundle until reload — covered only if the relay refusal ships.

## Out of scope
- Long 429 holds (owner veto).
- Any OF write behaviour.

## Needs the human
- 8 visible rows as the "enough" target for pages 3–4 (01) — owner taste.
- ≤5 s chat-list wait before "OnlyFans busy, try again" (04) — owner said 30 s too long; confirm 5.

## Assumptions to veto
- 02 replay cap returns cached deep pages during refetch: not adversary-reviewed (reconciliation); a duplicate-row/rank-shift test overturns it → 02 falls back to persisted-snapshot trim.
- 5 s wait budget (04): frequent failed explicit deep clicks overturn it → 04, 05 thresholds.
- 8-row target (01): Load-more clicks right after 2 pages on most hops overturn it.
- Search under the 4-page budget (01): missed search matches overturn it.
- Old tabs see "reload to load older chats" (04) until reload.
- Destination is plan-only.

## Tickets
- [Dynamic auto-load cap 2–4](issues/01-dynamic-autoload-cap.md)
- [Trim cached deep pages](issues/02-trim-cached-deep-pages.md) — blocked by 01
- [Dedupe page requests](issues/03-dedupe-page-requests.md)
- [Relay refuses deep pages without a click](issues/04-relay-deep-page-refusal.md) — blocked by 01
- [Caller tag and prod proof](issues/05-caller-tag-and-proof.md)
- [Out-of-the-box ideas: needed or not](issues/06-ootb-ideas-verdict.md)
