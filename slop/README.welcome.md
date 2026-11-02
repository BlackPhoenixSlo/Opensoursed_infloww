# slop/: Welcome (send_welcome burst, welcome chatter)

The welcome burst (`automations.send_welcome`, its filters one pure `send_welcome_decide.partition`) and the
welcome chatter (`automations.welcome_chatter_for_info`, the reply loop W7 wakes, its gates one pure
`wcfi_decide.decide`), in the slop harness. The harness, its knobs and its rules are in `README.md`; this file is
only what this flow adds. Each scenario's docstring is its spec (timeline, bypasses).

## Layout

| Path | Role |
|---|---|
| `lib/welcome_relay.py` | OnlyFans' side of a welcome sweep at the offline client (`automation_executor._make_client`), only while a scenario writes `$DEMO_SHOTS_TMP/of-welcome.json` (`{feed: {account: [items, newest first]}, of_welcome_on: [account]}`, read on every call): `notifications` (the subscribe feed, paged, `type` filter), `my_settings` (`replyOnSubscribe`), `message_templates` (`reply_on_subscribe` when OF's welcome is on), `follow_user` (recorded), `get_user` (a free profile for a feed fan), `send_message` (recorded per Creator). `GET /__slop/welcome`: what OF received (sends, follows, feed and settings reads). Without the file every call fails as before. |
| `lib/welcome_burst_faults.py` | The burst's check names and its two faults, both patching `send_welcome_decide.partition` (one `Reads` field blanked). |
| `lib/wcfi_relay.py` | The chatter's part, chained on `lib/automation_relay.py` (loaded after it): its loopback DeepSeek fake also answers a prompt carrying `PERSONA` (fact extract `{}`, a reply of two lines unique to the call, counted `deepseek:wcfi_extract` / `deepseek:wcfi_reply` at `GET /__slop/fake/calls`); a journal of OF's sends for `PERSONA` Creators only, `GET /__slop/wcfi/of-sends` (`[{account_id, fan_id, text, id, t}]`). |
| `lib/wcfi_faults.py` | The chatter's check names and its two faults, patching `wcfi_decide.decide` and wcfi's `write_outbound_attribution`. |
| `seed/welcome_burst.py` | `seed(w, fans, threads, new=, welcomed=, established=, of_on_frac=)`: per Creator `new` subs (no row), `welcomed` renewals (claim + 2 welcome rows, at the NOT-NEW tolerance), `established` renewals (4 out / 10 in, no claim), all in OF's subscribe `feed`; `of_welcome_on` Creators (`round(frac * Creators)`, at least one, never all). Every seeded message older than 2 days. |
| `seed/welcome_chatter.py` | `seed(w, fans, threads, live=)`: per Creator `PERSONA`, Reply Instant on (`webhook_config_json`, no delay), one enabled `welcome_chatter_for_info` rule whose daily sweep fired 30 min ago; then `live` fans without a seeded thread round-robin over the cases open, double, blacklisted, skiplisted, muted, promo, each with its short history and `chats` row. |
| `scenarios/2026-10-30-welcome-burst.py` | The burst scenario. |
| `scenarios/2026-10-30-welcome-chatter-walk.py` | The chatter scenario. |

## Scenarios

- `2026-10-30-welcome-burst`: `agency_inbox` plus `seed/welcome_burst`. The owner raises the DM rate
  (Concurrency panel route) and adds one `send_welcome` rule per Creator (`POST /admin/automation-rules`, every
  300 s, `after_of_welcome`, `stop_on_reply`, no batch cap). Tick 0 on an empty feed, a control pass, then the
  feed is published, `--users` owner `/events` tabs open over `--tab_ramp_s=` (10 s), every Creator's subscribe
  toasts arrive through `POST /__slop/of-ws-frame` (serial per Creator), tick 1 (`POST /__slop/automation-tick`);
  one toast per Creator inside the 60 s poke floor and a pass, the rules' jobs aged by SQL, one more toast and
  tick 2. Checks (`lib/welcome_burst_faults.py`): `ONCE` (one greeting + one follow-back per new sub of an
  OF-welcome-off Creator, nothing for a claimed fan, nothing in tick 2), `ESTABLISHED`, `OF_ON`, `COUNTS`, `POKE`,
  `LIVE`; budget `tick-1 run time per welcome p95` (the scenario's, also vs the last green run). Faults:
  `welcome-burst-rewelcomes` (default; targets `ONCE`), `welcome-to-established` (`ESTABLISHED`). Knobs:
  `--new=`, `--welcomed=`, `--established=` per Creator (SCALES `welcome_burst_<knob>`), `--of_on_frac=` (0.3).
- `2026-10-30-welcome-chatter-walk`: `agency_inbox` plus `seed/welcome_chatter` with `--users` case fans. The
  agency's fake DeepSeek key through `PUT /admin/my-llm-keys`, the DM rate raised; the real supervisor runs
  (`SLOP_SUPERVISOR=1`). Each round every case fan DMs once (`fan_dm.serial`, open loop at `--rate=` DMs/s per
  Creator, 0.25); W7 queues a fan-scoped job and the supervisor answers; a round ends when every open fan's answer
  reached OF and no job of the lane is left. Checks (`lib/wcfi_faults.py`): `TURNS`, `SKIPLISTED`, `DOUBLE`,
  `COUNTS`, `LANDED`; budget `e2e DM frame -> first bubble at OF p95` (the scenario's, also vs the last green
  run). `SLOP_LIVE=1`: every check SKIPs. Faults: `wcfi-skiplist-ignored` (default; targets `SKIPLISTED`, through
  the blacklisted fans), `wcfi-turn-sent-twice` (`DOUBLE`). Knobs: `--rounds=` (2), `--rate=`; no per-scale value
  of its own.
