# Full AI Chat is a separate Lane that owns a Treatment fan outright; funnels and mass stay untouched

**Status: proposed** (2026-11-13, `plans/full-ai-chat.md`; owner D19, lane-ownership ticket 02 r1, rollout ticket 12 r3; nothing built yet).

Several Lanes can answer the same Fan today (funnel walks, Get to know fans, Auto-reply), and the earlier design shared one offer ledger and one `sell_brakes.may_sell` across `reply_mass_funnel` and Full AI Chat (ticket 03 r1, Fable R2), plus a post-complaint no-sell stamp in every Lane (ticket 17). We decided that Full AI Chat is its own Lane (D19). A pure `who_owns` precedence picks one replier per Fan at every Evaluation point: stops first (hard skips, Human yield), then a funnel walk only while it advances, the Top spend limit, Full AI Chat, Get to know fans, Auto-reply. It decides who replies, never whether to sell. Exclusivity holds for Treatment fans only: in live Mode the other Lanes Stand down for them, `engine_active` becomes per Fan, and the welcome engine hands them over; Holdout fans keep today's behaviour. Funnel and mass code does not change: Full AI Chat gives way to an advancing walk instead of making walks call `who_owns`, and its Decision ledger and Send-correctness rules are its own, not shared with the funnel send markers. We chose this because the owner wants it separate, the old Lanes must keep working for other Creators and for the holdout (the reason behind ADR-0016 as well), and one replier per Fan is what makes "no double send" and "no Lane collision" checkable. The cost: two offer ledgers exist, a priced message from another Lane is fenced only by single ownership and the shared fan lease, and a mass send can still reach a Fan Full AI Chat owns (it cancels his Pending tease).

ASSUMPTION: ticket 02's row 3 (make_right above funnel walks, with complaint detection run before `who_owns` for every Lane) is left out of the precedence, because D19 keeps complaint handling inside Full AI Chat and D32 makes it a Router question; overturned if the owner wants Make-it-right to pre-empt a funnel walk.

## Considered Options

- **One shared offer ledger and `may_sell` across funnels and Full AI Chat** (ticket 03 r1). Rejected (D19): it changes Lanes that must keep working untouched.
- **A no-sell stamp in every Lane after a complaint** (ticket 17). Dropped (D19, then D32).
- **Walks calling `who_owns` before inserting `funnel_state`** (ticket 02). Dropped (ticket 12 r3): a change inside another Lane.
