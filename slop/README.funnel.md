# slop/: House funnel walk

The house funnel walker (`automations.reply_mass_funnel`, its per-fan status machine `funnel_decide.decide()`) in the
slop harness. The harness, its knobs and its rules are in `README.md`; this file is only what this flow adds. The
scenario's docstring is its spec (bypasses).

## Layout

| Path | Role |
|---|---|
| `seed/house_funnel.py` | House funnel history by SQL: one 3-step funnel and per Creator one funnel broadcast to every fan without a seeded thread, as the rows the product leaves (funnel, `funnel_account_media`, `mass_runs`, one outbound row per recipient, the walking fans' `funnel_state`, sent steps, answers and `chats` row); `seed_jump` (the branching broadcast), `seed_kill` (the KILL phase's third funnel). |
| `lib/funnel_relay.py` | The house funnel's relay part: the walker runs through `POST /__slop/run-automation` on `lib/automation_relay.py`'s offline walker client (a priced send kept per fan, `of_ppv`); declared pacing bypass `_STEP_GAP_S` to 0.2 s. |
| `lib/funnel_faults.py` | The walk's check names and its fault (below), patching `funnel_decide.decide()` in the relay. |
| `lib/funnel_jump_faults.py` | The `next`-jump check name and its fault (below), patching `funnel_decide`. |
| `scenarios/2026-10-30-house-funnel-walk.py` | The scenario. |

## Scenarios

- `2026-10-30-house-funnel-walk`: the house funnel walker (`automations.reply_mass_funnel`, its
  per-fan status machine the pure `decide()` of `service/automations/funnel_decide.py`,
  Non-React #9). `agency_inbox` + `seed/house_funnel.py`: one 3-step funnel (two lines, one
  line, a $24 PPV), one broadcast per Creator to every unthreaded fan, one case each; `--users`
  fans answer through the pump (`fan_dm.say`), then one `reply_mass_funnel` tick per Creator at
  once and a second right after. Checks: a new replier is enrolled with step 1's two lines, a
  silent one never walks; an answer earns exactly the next step, no answer reschedules (+4 min);
  the PPV step sends one priced PPV (fake OF's `of_ppv` agrees) and ends the walk; a buyer is
  halted `offer_taken`; a walk past the script's end closes; rows = lines earned = the runs'
  `advanced`; tick 2 moves nobody. Budget: run time per due fan (`automation_runs`). Bypasses:
  `lib/funnel_relay.py` (the 4 s line gap to 0.2 s), the buyer's unlock seeded as the
  rows purchase_notifications' `_flip_paid` leaves. Fault `house-funnel-offer-taken-ignored` (`lib/funnel_faults.py`).
  Then held-out fans jump from step 1 to step 5 on a branching broadcast's keyword (`seed_jump`); quiet at their
  next check, they must reschedule on the sent step's intervals; fault `house-funnel-jump-waits-prev-step`
  (`lib/funnel_jump_faults.py`: the pre-F1 c - 1 rule) targets only that check.
  KILL, last (`README.send-once.md`): on each of the first 4 Creators `seed/house_funnel.py` `seed_kill`'s third
  funnel and broadcast, three walking fans on its PPV step and one `control` fan: `partial` (bubble 1 refused 400),
  `partial_noid` (the same, the PPV answered without its id), `kill` (the PPV taken, never answered; on the last KILL
  Creator bubble 1 hangs instead, the landed fan). After the restart a DM per `kill`, `partial_noid` and `control`
  fan and one welcome chatter run per KILL Creator, then two funnel ticks before the owner's list and Retry. Checks
  (`lib/send_marker_faults.py`): `FUNNEL_ONCE`, `FUNNEL_MARKED`, `FUNNEL_SETTLED`, `FUNNEL_RETRY`, `FUNNEL_PARTIAL`,
  `FUNNEL_PARTIAL_NOID`, `FUNNEL_PARKED_QUIET`, and the scenario's own KILLED. Faked: the agency's fake DeepSeek key
  and `lib/wcfi_relay.py`'s answer. Faults: `funnel-partial-requeued` (`FUNNEL_ONCE`, `FUNNEL_PARTIAL`,
  `FUNNEL_PARTIAL_NOID`), `funnel-noid-not-counted` (`FUNNEL_ONCE`, `FUNNEL_PARTIAL_NOID`),
  `funnel-marker-sets-status` (`FUNNEL_PARKED_QUIET`), `funnel-sending-marker-ignored` (`FUNNEL_ONCE`,
  `FUNNEL_MARKED`, `FUNNEL_SETTLED`, `FUNNEL_RETRY`, `FUNNEL_PARTIAL_NOID`), `funnel-settle-skips-lookup`
  (`FUNNEL_SETTLED`).
