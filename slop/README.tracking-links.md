# slop/: Tracking links

Our `/t/<slug>` redirect links (`tracking_links_api`) under a click storm and OnlyFans' own tracking links with
per-link earnings (`of_tracking_api`, Growth > Tracking links), in the slop harness. The harness, its knobs and its
rules are in `README.md`; this file is only what this flow adds. The scenario's docstring is its spec (load,
attribution rule, bypasses).

## Layout

| Path | Role |
|---|---|
| `seed/tracking_campaigns.py` | `seed(w, creators, tmp, links=, campaigns=, claimed=)`: ours by SQL (per Creator `links` `tracking_links` rows, custom numeric slugs, 0..40 past `tracking_clicks` each over 14 days, `click_count` equal); OnlyFans' in `<tmp>/of-campaigns.json` (+ `of-me.json`): per Creator `campaigns` links, newest first, every 4th with no subscriber, the second oldest deactivated 20 days after it opened, the oldest topped up to 61 claimers (two claimers pages) with free-trial claimers who never paid; `claimed` fans each claiming 1..3 links, their ledger as the payouts ingest and the WS pump write it, plus a few fans who claimed nothing. |
| `lib/tracking_relay.py` | OnlyFans' `/campaigns` side, only when the run wrote `of-campaigns.json`: `tracking_links` (paged, deleted only `with_deleted`, this run's creates first), `campaign_claimers` (paged), `create_tracking_link`, each waiting `latency_s` (50 ms, a guess); `GET /__slop/tracking-calls` answers what OF received (`campaigns` per Creator, `claimers` offsets per link, in order). |
| `lib/tracking_faults.py` | The check names (`CLICKS`, `REDIRECT`, `BY_DAY`, `EARNINGS`, `CLAIMERS`, `CREATED`) and three faults (below). |
| `scenarios/2026-11-01-tracking-links-clicks.py` | The scenario; its `_oracle` (per OF link's figures from the seed alone, and how often each branch of the attribution rule decided a sale). |

## Scenarios

- `2026-11-01-tracking-links-clicks`: `agency_inbox` plus `seed/tracking_campaigns`. `--users` anonymous clients
  (no cookie, redirects not followed) send `--clicks=` `GET /t/<slug>`, open loop at `--rate=` clicks/s (`0`: a
  closed loop, the relay's saturation), links by uneven seeded weights. Meanwhile `max(3, --users // 10)` owners
  (a pool of 4 each): wave 1, every owner opens each Creator's earnings at once (the cold first open among them);
  one OF link created per Creator (`POST /admin/of-tracking-links`); wave 2, each owner reloads its home Creator's
  Links list and one link's Details; then browsing until the storm ends. With UI, /growth/tracking-links, Custom
  redirect links (screenshot `tracking-links-trigger`), a link's Analytics (`tracking-links-settled`). Checks
  (`lib/tracking_faults.py`): `CLICKS` (rows, `click_count`, list == seeded + the 302s answered), `REDIRECT`,
  `BY_DAY`, `CREATED`, `EARNINGS` (the oracle; INFRA unless every branch of the rule occurs in the seed),
  `CLAIMERS` (one walk per link with subscribers, `ceil(n / 50)` pages, none for zero-subscriber or created
  links), and the UI check (the Analytics' total clicks == API == DB); budgets (`/t/` and earnings p95 under the
  storm, p95 vs the last green run) are the scenario's. Faults: `tracking-click-lost-1-in-20` (default; targets
  `CLICKS`, `BY_DAY`; the stock no-unexpected-Traceback check goes red too), `of-tracking-claimers-no-memo`
  (`CLAIMERS`), `of-tracking-spend-first-link` (`EARNINGS`). Knobs: `--links=`, `--campaigns=`,
  `--claimed=`, `--clicks=` (each defaults to SCALES `tracking_links_<knob>`), `--rate=` 100/250/400 (small /
  medium / huge).
