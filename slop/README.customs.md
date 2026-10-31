# slop: the owed-customs queue (Messages dashboard > Customs)

| Path | Role |
|---|---|
| `seed/customs.py` | `seed(w, n)`: n owed fans by SQL, as customs_watch + the transcoder + transaction_ingest leave them (thread with the ask, the tip message and its `transactions` row, an enabled `customs_watch` rule, `fans.customs_owed_at` = the tip's time). Each fan's lines carry his own tag and call name, so a pane or clipboard shows whose thread it is. `write_of_truth(path, fan)` writes `of-truth.jsonl` (his newest message, as OF holds it) so a Pull's real scrape (`rescrape-now`) has an OF side to read. |
| `lib/customs_relay.py` | DeepSeek's wire for `POST /admin/customs/brief` only: a loopback fake answering the brief's prompt in its schema (0.4 s); any other prompt is forwarded to the fake it replaced when that one is on loopback, else 503. Nothing with `SLOP_LIVE=1`. |
| `lib/customs_faults.py` | Client side. `customs-pane-seq-unguarded`: the pane reducer's seq guard removed, so a late reply for row A lands in row B's pane. `customs-pull-reopens-stale`: Pull's check for a newer open / close removed, so A's ok rescrape reopens A over B and asks for a paid brief. |
| `scenarios/2026-10-30-customs-pane-race.py` | Read A, then Read B with A's replies held at the browser's wire until after B's: B's pane, the Copy gate and the copied handoff. Then Pull on A (rescrape held), Hide + Read B, rescrape answers ok: A reopens nothing. Its docstring has the timeline and bypasses. |

The brief bills the Agency's own key, so a scenario stores a fake one through the real
`PUT /admin/my-llm-keys` first (without it the brief is a 424 `tenant_key_missing`).
