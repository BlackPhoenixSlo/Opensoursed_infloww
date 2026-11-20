# The Shared refresher reads only Open-tab Creators, once per Creator per Cycle for every tab

**Status: proposed** (2026-11-20, `.scratch/watched-creator-refresher/goal.md` D1–D5, D8, owner decisions binding; study `.scratch/all-models-of-budget/REPORT.md` §3 on `study/all-models-of-budget`; nothing built yet).

Under All Models every tab reads its Creators' chats window, money rail and counts on its own: a later open costs 62–92 OF calls at 10 Creators (measured) and ~230–370 at 50 (inferred), each chatter's truth ages on its own clock, and a chat read on OF web reached no tab in 45 s (measured, slop `2026-11-20-all-models-shared-inbox`). We decided the Relay runs one Shared refresher: it reads only Open-tab Creators, skips Dead sessions, reads each at most once per Cycle (~120 s under a View lease, ~10 min otherwise, never under 60 s) however many Employees and tabs see it, paces through the per-exit gate at background priority, spread evenly over the Cycle and backing off on 429, and publishes on the Event stream only what changed. It leans on the Live connection, which brings DMs and counters at 0 OF calls, and only reconciles; whether the counter frame can be the Unread total is the plan's open Q1. Why: one shared read per Creator makes the truth the same in every tab and the cost flat in chatters, and reading only where a tab is open keeps the added cost at ~14 calls/min at 50 Creators (13k–20k/day, inferred/guess), which the owner accepted. The cost: its Caller kind is a new Cost group, so `of_calls_vs_baseline` trips until a human re-pins the Baseline run after deploy (the spec writes the step); a Creator nobody has open is only as current as its Live connection and its next App-open warm. Going back means a new budget decision and another re-pin.

## Considered Options

- **A. Every Creator, 120 s, 2 reads each (unread list page + notification count).** Rejected: 72k calls/day at 50 Creators (inferred), more than all of AE today (66.5k/day, measured), for screens nobody has open.
- **A'. Every Creator, 60 s.** Rejected: 144k/day (inferred), and at the floor itself.
- **B. Open-tab Creators, 2 reads each per 120 s.** Rejected: ~48k/day (guess); polls the list each Cycle for what the Live connection brings free.
- **Per-tab reads, as today.** Rejected: cost grows with chatters and every tab's truth ages separately.
