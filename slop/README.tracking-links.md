# slop/: Tracking links

Our `/t/<slug>` redirect links (`tracking_links_api`) under a click storm and OnlyFans' own tracking links with
per-link earnings (`of_tracking_api`, Growth > Tracking links), in the slop harness. The harness, its knobs and its
rules are in `README.md`; this file is only what this flow adds. The scenario's docstring is its spec (load,
attribution rule, bypasses).

## Layout

| Path | Role |
|---|---|
| `seed/tracking_campaigns.py` | `seed(w, creators, tmp, links=, campaigns=, claimed=, hot_per_day=)`: ours by SQL (per Creator `links` `tracking_links` rows, custom numeric slugs, 1..40 past `tracking_clicks` each over 14 days with a hand-labelled referer / user agent / country, one at least between 00:00 and 04:00 UTC, plus one `hot` link of `hot_per_day` clicks a day over 90 days with 300 country×app×ref combinations; `click_count` equal; raw label columns, some NULL for the boot classifier); OnlyFans' in `<tmp>/of-campaigns.json` (+ `of-me.json`): per Creator `campaigns` links, newest first, every 4th with no subscriber, the second oldest deactivated 20 days after it opened, the oldest topped up to 61 claimers (two claimers pages) with free-trial claimers who never paid; `claimed` fans each claiming 1..3 links, their ledger as the payouts ingest and the WS pump write it, plus a few fans who claimed nothing. |
| `lib/tracking_relay.py` | OnlyFans' `/campaigns` side, only when the run wrote `of-campaigns.json`: `tracking_links` (paged, deleted only `with_deleted`, this run's creates first), `campaign_claimers` (paged), `create_tracking_link`, each waiting `latency_s` (50 ms, a guess); `GET /__slop/tracking-calls` answers what OF received (`campaigns` per Creator, `claimers` offsets per link, in order). Cloudflare Turnstile's siteverify (bot check before redirect) at its wire: with `TURNSTILE_SECRET_KEY` set (the scenario's `RELAY_ENV`), it points the product's `TURNSTILE_VERIFY_URL` env seam at `POST /__slop/fake/turnstile-siteverify` (30 ms, a guess; passes iff the secret is the relay's and the token starts `pass-`); `GET /__slop/turnstile-calls` answers what it received. |
| `lib/tracking_faults.py` | The check names (`CLICKS`, `REDIRECT`, `BY_DAY`, `EARNINGS`, `CLAIMERS`, `CREATED`, `CLIENT_IP`, `GATE_CREATE`, `GATE_PAGE`, `GATE_VERIFY`, `GATE_COUNT`, `GATE_THROTTLE`, `STATS_SUMMARY`, `STATS_BREAKDOWN`, `STATS_INVARIANT`) and the faults (below). |
| `scenarios/2026-11-01-tracking-links-clicks.py` | The scenario; its `_oracle` (per OF link's figures from the seed alone, and how often each branch of the attribution rule decided a sale). |

## Scenarios

- `2026-11-01-tracking-links-clicks`: `agency_inbox` plus `seed/tracking_campaigns`. `--users` anonymous clients
  (no cookie, redirects not followed) send `--clicks=` `GET /t/<slug>`, open loop at `--rate=` clicks/s (`0`: a
  closed loop, the relay's saturation), links by uneven seeded weights. Meanwhile `max(3, --users // 10)` owners
  (a pool of 4 each): wave 1, every owner opens each Creator's earnings at once (the cold first open among them);
  one OF link created per Creator (`POST /admin/of-tracking-links`); wave 2, each owner reloads its home Creator's
  Links list and one link's Details; then browsing until the storm ends. Bot check: `--gated=` (2) links per
  Creator made through the real Create with a scheme-less `ofl.ink/...` target (even ones `bot_check` at
  create, odd ones by `PATCH`), and `--gated_clicks=` (clicks / 10) fans, each visit from its own address, at a
  tenth of the rate, each GET the gate page then POST `/verify` (3 in 4 tokens pass); after the storm one fresh
  address posts `VERIFY_CAPACITY` + 3 failing verifies to one gated link. With UI, /growth/tracking-links, the Redirect
  links tab: the summary cards (screenshots `tracking-links-summary`, `tracking-links-trigger`), the hot link's Analytics
  (`tracking-links-stats-30d`, `tracking-links-settled`), and the same on a 390 x 844 phone (`tracking-links-phone-summary`,
  `tracking-links-phone-stats`). Twenty timed 90-day reads of the hot link have a 600 ms p95 budget. The owner's `report_tz` is America/New_York (PUT before the storm); 1 in 20 clicks
  skips Cloudflare with a forged CF-IPCountry (must be filed XX). Checks
  (`lib/tracking_faults.py`): `CLICKS` (rows, `click_count`, list == seeded + the 302s answered), `REDIRECT`,
  `BY_DAY` (30-day series per New York day), `STATS_SUMMARY` (today / 7 / 30 days, sparklines, top link per Creator),
  `STATS_BREAKDOWN` (Opened in / Came from / Country == the hand labels after the boot classifies seeded NULL labels), `STATS_INVARIANT` (analytics buckets == range raw rows; all raw rows == `click_count`), `CREATED`, `EARNINGS` (the oracle; INFRA unless every branch of the rule occurs in the seed),
  `CLAIMERS` (one walk per link with subscribers, `ceil(n / 50)` pages, none for zero-subscriber or created
  links), `GATE_CREATE` (stored `https://<target>`, bot_check listed), `GATE_PAGE` (200, no Location, no target
  in the body, no-store), `GATE_VERIFY` (pass → 200 its own target, fail → 403, one siteverify call per
  verify, counted before the throttle probe), `GATE_COUNT` (gated clicks == passes), `GATE_THROTTLE` (the probe:
  the first `VERIFY_CAPACITY` 403, the last 3 429 with Retry-After, siteverify + `VERIFY_CAPACITY` only, no click), and the UI checks (UI == API only: the Analytics' 30-day total
  == API == DB, its bars and top Opened in row, the summary cards, the phone with no sideways scroll; a gated row's
  badge and toggle, screenshot `tracking-links-gated-row`); budgets (`/t/`, earnings and the stats reads' p95 under
  the storm, the stats reads after it, p95 vs the last green run) are the scenario's. Faults: `tracking-classify-raises` (`STATS_BREAKDOWN`; REDIRECT and CLICKS stay green), `tracking-click-lost-1-in-20` (default; targets
  `CLICKS`, `BY_DAY`, `STATS_SUMMARY`, `STATS_BREAKDOWN`, `GATE_COUNT`; the stock no-unexpected-Traceback check goes red too), `of-tracking-claimers-no-memo`
  (`CLAIMERS`), `of-tracking-spend-first-link` (`EARNINGS`),
  `client-addr-cdn-header-ignored` (`CLIENT_IP`, `STATS_BREAKDOWN`), `tracking-bot-check-fails-open` (`GATE_VERIFY`,
  `GATE_COUNT`, `STATS_SUMMARY`, `GATE_THROTTLE`), `tracking-stats-utc-days` (`BY_DAY`, `STATS_SUMMARY`),
  `tracking-verify-unthrottled` (`GATE_THROTTLE`). Knobs: `--links=`,
  `--campaigns=`, `--claimed=`, `--clicks=`, `--hot_per_day=` (each defaults to SCALES `tracking_links_<knob>`), `--rate=` 100/250/400 (small /
  medium / huge).
