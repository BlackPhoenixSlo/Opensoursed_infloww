# slop/: Mass placeholders and OF's echo

A mass message's optimistic placeholders fold into OnlyFans' echo exactly once: the composer's broadcast to
explicit fans writes one placeholder-band stub per recipient (`attribution.write_mass_optimistic_rows`), and
when the inbox's chat-list read reconciles that send as a chat's last message the real row adopts its stub
(`attribution.adopt_thread_placeholders` -> `attribution_pair.pair_placeholders`: nearest-first, `<br />` ==
`\n`, the 6 h bound). The same scenario also checks the composer's `excluded_users` (`EXCL`) and, in a
dry-run tail, `send_mass_message` dry runs (`DRY_NO_SEND`, `DRY_LIST`). The harness, its knobs and its rules are
in `README.md`; this file is only what this flow adds. The scenario's docstring is its spec (bypasses).

## Layout

| Path | Role |
|---|---|
| `seed/mass_placeholders.py` | `seed(w, fans_by_aid, body_of, at)`: per Creator one closed `mass_runs` row (status `ok`, an explicit-fan composer send's `audience_filter`) and one stub per recipient in `write_mass_optimistic_rows`' shape (message_id `_MASS_PLACEHOLDER_BASE + run`, `temp_id mass:<run>:<fan>`, plain `\n`), whose echo never came (prod's common case). Returns `{account_id: mass_run_id}`. `PLACEHOLDER_BASE` / `PLACEHOLDER_CEIL`: the service's band, read off `service/attribution.py` by ast. |
| `lib/attribution_pair_faults.py` | The check name `PH_ONCE` and the fault `placeholder-pair-ignores-window` (`attribution._MAX_ADOPT_SECONDS` 10 years: pairing ordered by distance but no longer bounded). |
| `lib/mass_queue_faults.py` | The check name and its fault (below), patching the composer queue's pure decide and audience resolver in the relay. |
| `seed/mass_dry_run.py` | `seed(w, fences, of_list_id_base=)`: the dry-run tail's two audience fences per Creator by SQL: `massdm` fans on its MASSdmEXCLUDE list, `autofence` fans left out of an enforce-mode `automation_include` list (with `account_ai_config` audience_mode 'enforce'). |
| `lib/mass_dry_run_faults.py` | The check names and its faults (below), each patching a `send_mass_decide` attribute in the relay. |
| `scenarios/2026-10-31-mass-placeholder-echo.py` | The scenario. |

## Scenarios

- `2026-10-31-mass-placeholder-echo`: `agency_inbox`, each Creator with a captured session (`seed/of_sessions`,
  `OF_WIRE`: the relay's real OFClient against `lib/of_wire.py`). Per Creator, first `seed/mass_placeholders`: a
  2-day-old closed run with run 0's caption, its stubs on STALE fans plus BOTH fans. Then 3 broadcasts per
  Creator through `POST /api/of/v2/messages/queue` (owner session, `user_ids`), each a multi-line caption to its
  own fresh fans (run 0's include the BOTH fans), the last `--excluded=` of them also in the body's
  `excluded_users`. OF's chat list then shows every recipient's copy as the last
  message (`\n` -> `<br />\n`), and every STALE fan a Creator's own OF-web send of run 0's caption. `--users`
  open inboxes load one (Creator, page) of `GET /api/of/v2/chats` once, then head-poll page 0 without `refresh`
  (`useHeadPagePoll`, compressed), until every fresh stub is gone. Checks: the scenario's "every broadcast
  answered 200 and left one placeholder per recipient" (one per sent recipient, none on any other non-excluded
  fan), `EXCL`
  (`lib/mass_queue_faults.py`; per excluded fan no row of its run, no OF wire `userIds` naming it, each run's
  `recipient_count` == its sent ids; skipped at `--excluded=0`) and `PH_ONCE` (`lib/attribution_pair_faults.py`: each
  recipient's stub gone, OF's row carries its run, one out row and one thread bubble per caption via `GET
  /admin/messages/{aid}/{fan}`; BOTH and STALE fans keep the 2-day-old stub, STALE's OF row carries no run);
  budgets: echo visible -> every placeholder adopted, `GET /api/of/v2/chats`, `POST /api/of/v2/messages/queue`,
  `GET /admin/messages/:id/:id` p95, all in the scenario, also vs the last green run. Then the dry-run tail (after
  every check above is recorded): per Creator `seed/mass_dry_run` fences and a FakeOF custom list (`--dry_fresh=`
  untouched fans, `--dry_guard=` fans inside the 6 h contact guard, both fences); max(`--users`, 2 per Creator)
  concurrent `POST /admin/automation/enqueue` `send_mass_message` dry runs, explicit (`--dry_excluded=` fresh fans
  as `excluded_users`) and list, drained by `/__slop/automation-tick`, then one real enqueue per Creator of the
  explicit payload. Checks (`lib/mass_dry_run_faults.py`): `DRY_NO_SEND` (no OF queue frame or list write, no new
  `mass_runs` / out row, every run `dry_run` with sent 0), `DRY_LIST` (list runs: would_send None, reason
  `list_audience`; explicit runs: roster - guard - fences - excluded, in roster order, == the real send's wire `userIds`); budget: `POST
  /admin/automation/enqueue` p95 (in the scenario). Faults:
  `placeholder-pair-ignores-window` (default; targets `PH_ONCE`), `mass-queue-excluded-kept` (`EXCL`),
  `mass-dry-run-ignored` (a dry run sends; `DRY_NO_SEND`, `DRY_LIST`), `mass-dry-run-list-claims-reach` (`DRY_LIST`).
  Knobs, per Creator: `--per_run=` fresh recipients per run, `--stale=` STALE fans, `--both=` BOTH fans,
  `--excluded=` (each defaults to SCALES `mass_placeholder_<knob>`), `--dry_fresh=`, `--dry_guard=`, `--dry_fence=`,
  `--dry_excluded=` (SCALES `mass_dry_run_<knob>`).
