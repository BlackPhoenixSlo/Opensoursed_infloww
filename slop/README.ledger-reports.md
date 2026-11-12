# slop/: Ledger reports at volume

Fan reports (Top fans, Traffic), the Tips tab (tips list, top tippers), the Message dashboard's paid broadcasts,
Sales records and the exports, read by many owners of two Agencies over a big ledger, every figure against an
oracle the harness computes in SQL (from the rules, never importing a product function). The harness, its knobs
and its rules are in `README.md`; this file is only what this flow adds. The scenario's docstring is its spec
(the oracle's rules, strict budgets, bypasses).

## Layout

| Path | Role |
|---|---|
| `seed/ledger_bulk.py` | `seed(w, creators, n=, runs=, recipients=)`: `transactions` (`n` rows over 60 days, spread by fan count; the ingest's kinds with KIND_CATALOG's description prefixes; cleared, pending for the last 7 days, and the reversals; ledger rows with OF's net / fee, 1 in 200 net 0; 1 in 10 tips a WS-pump row with no net, linked to its inbound message), paid mass (`runs` closed `mass_runs` per Creator, one outbound copy per recipient, buyers' copies bought with their linked `ppv_message` sale, 1 in 8 since reversed), `link_claimers` (1 in 5 fans, 1 in 10 of those a second claim). Deterministic (`w.rng("ledger_bulk")`); counts in `w.data["ledger_bulk"]`. |
| `lib/ledger_reports_faults.py` | The check names (rank and CSV checks one per route, so each fault targets only the route it breaks) and its faults (below), each patching a product module attribute looked up at call time or, client side, the load-more sentinel's served JS. |
| `scenarios/2026-11-01-ledger-reports-volume.py` | The scenario; its SQL oracles (`oracle_fans`, `oracle_tips`, ...) and independent crowd/isolated budgets. |

The owner crowd is the scenario's own `_owner` (no actor reads these routes); its think time is
`actors/reports.THINK_S`.

## Scenarios

- `2026-11-01-ledger-reports-volume`: `multi_agency_big_models` (Agency 0 = the UI's owner with the 3 big
  Creators, Agency 1 = the scope probe) plus `seed/ledger_bulk` on all 20 Creators and `seed/earnings` on
  Agencies 0 and 1's (`history_days` 40, connected 5 days ago). Load (stage `load`): `--users` owners, half each
  Agency, each its own pool, reading fan-report, tips-list + top-tippers, paid-messages, sales-records or an export
  (CSV, or `POST /admin/stats/xlsx`); every list and CSV a crowd read answers is scanned for another Agency's
  Creator. Then the checks against the oracle (route labels `check `). Checks
  (`lib/ledger_reports_faults.py`): `FAN_TOTALS`, `FAN_RANK`, `FAN_CSV`, `TRAFFIC`, `TIPS`, `TIPS_CSV`,
  `TOP_TOTALS`, `TOP_RANK`, `TOP_CSV`, `PAID`, `SALES`, `XLSX`, `SCOPE`; with UI, `UI_TOTALS` (Fan reports' Total
  spend cells == the rows the page read == oracle), `UI_SIDE` (its Download report file == oracle) and
  `PAGE_ERR_BOUNDED` (the Message dashboard's Tips tab list, next pages answering 500 at the browser's wire, foot in
  view `PAGE_ERR_WAIT_S`: <= 2 next-page requests, Load more offered and, once lifted, loading that page's rows),
  screenshots `fan-reports-settled`, `fan-reports-download-trigger`, `message-dashboard`, `sales-records`,
  `page-error-trigger`, `page-error-settled`. Budgets: p95
  fan-report, tips-list and top-tippers under the crowd, plus p95 vs the last green run over the report routes,
  all in the scenario. Crowd budgets remain 1500/800/800 ms; separate isolated probes enforce the
  same thresholds with all responses 200. Missing samples/probes fail. All Creators, including big
  Creators, remain eligible for crowd fan-report reads and CSV exports. Historical known-red reasons
  live in `evidence/fd3-integration/ledger-contract/historical-contract.txt`, not executable waivers. Faults: `fan-report-counts-refunds` (default; targets `FAN_TOTALS`, `FAN_RANK`, `FAN_CSV`,
  `TRAFFIC`), `top-tippers-crosses-agency` (`SCOPE`, `TOP_TOTALS`, `TOP_RANK`, `TOP_CSV`),
  `fan-report-csv-truncates` (`FAN_CSV`), `fan-report-latest-claim` (traffic credits each spender's newest claim;
  `TRAFFIC`), `loadmore-refires-on-error` (client: the sentinel loses its error gate; `PAGE_ERR_BOUNDED`). Knobs: `--n=` ledger rows, `--runs=` paid broadcasts
  per Creator, `--recipients=` per broadcast (SCALES `ledger_reports_rows`, `ledger_reports_runs`,
  `ledger_reports_recipients`), `--load_s=` crowd seconds 20 / 60 / 90 (small / medium / huge).
