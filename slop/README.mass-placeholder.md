# slop/: Mass placeholders and OF's echo

A mass message's optimistic placeholders fold into OnlyFans' echo exactly once: the composer's broadcast to
explicit fans writes one placeholder-band stub per recipient (`attribution.write_mass_optimistic_rows`), and
when the inbox's chat-list read reconciles that send as a chat's last message the real row adopts its stub
(`attribution.adopt_thread_placeholders` -> `attribution_pair.pair_placeholders`: nearest-first, `<br />` ==
`\n`, the 6 h bound). The harness, its knobs and its rules are in `README.md`; this file is only what this flow
adds. The scenario's docstring is its spec (bypasses).

## Layout

| Path | Role |
|---|---|
| `seed/mass_placeholders.py` | `seed(w, fans_by_aid, body_of, at)`: per Creator one closed `mass_runs` row (status `ok`, an explicit-fan composer send's `audience_filter`) and one stub per recipient in `write_mass_optimistic_rows`' shape (message_id `_MASS_PLACEHOLDER_BASE + run`, `temp_id mass:<run>:<fan>`, plain `\n`), whose echo never came (prod's common case). Returns `{account_id: mass_run_id}`. `PLACEHOLDER_BASE` / `PLACEHOLDER_CEIL`: the service's band, read off `service/attribution.py` by ast. |
| `lib/attribution_pair_faults.py` | The check name `PH_ONCE` and the fault `placeholder-pair-ignores-window` (`attribution._MAX_ADOPT_SECONDS` 10 years: pairing ordered by distance but no longer bounded). |
| `scenarios/2026-10-31-mass-placeholder-echo.py` | The scenario. |

## Scenarios

- `2026-10-31-mass-placeholder-echo`: `agency_inbox`, each Creator with a captured session (`seed/of_sessions`,
  `OF_WIRE`: the relay's real OFClient against `lib/of_wire.py`). Per Creator, first `seed/mass_placeholders`: a
  2-day-old closed run with run 0's caption, its stubs on STALE fans plus BOTH fans. Then 3 broadcasts per
  Creator through `POST /api/of/v2/messages/queue` (owner session, `user_ids`), each a multi-line caption to its
  own fresh fans (run 0's include the BOTH fans). OF's chat list then shows every recipient's copy as the last
  message (`\n` -> `<br />\n`), and every STALE fan a Creator's own OF-web send of run 0's caption. `--users`
  open inboxes load one (Creator, page) of `GET /api/of/v2/chats` once, then head-poll page 0 without `refresh`
  (`useHeadPagePoll`, compressed), until every fresh stub is gone. Checks: the scenario's "every broadcast
  answered 200 and left one placeholder per recipient" and `PH_ONCE` (`lib/attribution_pair_faults.py`: each
  recipient's stub gone, OF's row carries its run, one out row and one thread bubble per caption via `GET
  /admin/messages/{aid}/{fan}`; BOTH and STALE fans keep the 2-day-old stub, STALE's OF row carries no run);
  budgets: echo visible -> every placeholder adopted, `GET /api/of/v2/chats`, `POST /api/of/v2/messages/queue`,
  `GET /admin/messages/:id/:id` p95, all in the scenario, also vs the last green run. Fault:
  `placeholder-pair-ignores-window` (default; targets `PH_ONCE`). Knobs, per Creator: `--per_run=` fresh
  recipients per run, `--stale=` STALE fans, `--both=` BOTH fans (each defaults to SCALES `mass_placeholder_<knob>`).
