# Report recipe: shape and Agency scoping

Type: domain-modeling
Status: resolved 2026-11-13
Blocked by: none

What is a **report recipe** — the structured thing an LLM fills from "report however the client asks" — and how is it executed so it can only ever read the asking Agency's Creators? Spec over a dataset catalogue vs read-only SQL vs extending existing export endpoints. Which datasets/columns/filters/grouping/metrics, which output formats, row caps.

## Answer

**Recipe over a fixed dataset catalogue.** The LLM fills enum keys only; code builds every query. Rejected: LLM-written SQL (SQLite has no row-level security, `users`/`user_accounts` share the DB, report meaning lives in Python — `service/msg_stats.py:80` omits the Creator predicate for `None`); widening `?format=csv` endpoints (fixed shapes; fan CSV ignores `limit`, `service/stats_fans.py:122`; Creator/Employee CSV is built in the browser, `app/lib/reportExport.ts`). Rung: 1 (observation) + 3 (house: Do mode = model emits intents, server validates, `service/assistant_draft.py:34`).

Recipe: `{dataset, window:{preset}|{from,to}, creators?, employees?, kinds?, group_by?, metrics?, sort?, limit?}`; format is a separate `run()` argument.

**v1 catalogue** (each = one existing engine):
| dataset | engine | group_by | metrics |
|---|---|---|---|
| `sales` | Creator-report path incl. OF top-ups (`service/stats_per_model.py:198`), kinds via `stats_per_model._kind_bucket` | creator, kind, day/week/month | gross, net, net_or_80, fee, sales |
| `employee_sales` | `sales_attribution.credited_sales(grouped=True, bucket=…)` — always pass a bucket (`service/sales_attribution.py:408-447`) | employee, creator, kind, day/week/month | earnings, sales |
| `chat_activity` | `msg_stats.send_stats(edges=…)` (Employee direct sends; send-date cohorts) | employee, creator, day/week/month/hour | messages, ppvs_sent, ppvs_unlocked, unlock_rate (= Σunlocked/Σppvs after grouping, 0 PPVs → blank), chars |
| `fan_spend` | spend query lifted from `stats_fans.fan_report` into shared `fan_spend_q` | fixed creator+fan | total, net_or_80, tips, ppv, subs; sort+limit in SQL |

`kinds` is a **per-dataset mapping table** in the decide module (ledger kinds are `ppv_message`/`ppv_post`…, `service/attribution_backfill.py:20-27`; Creator and fan reports bucket `ppv_post`/`tip_post` differently, `service/stats_per_model.py:47-64` vs `service/stats_fans.py:148`), never passed through.

**Scoping (structural, not prompt):**
1. `run(ctx, recipe)`; `ctx` from `owner_context`, never the recipe.
2. Owned set = `agency_account_ids(s, ctx.agency_user_id)` (`service/agency_scope.py:11`), not the principal's `account_ids` (a Master's spans everything, `service/auth.py:614`).
3. Named foreign Creator → refused; none named → all owned; >50 → refused.
4. One choke point hands engines a non-empty `list[str]`; empty owned set → empty table, no engine call.
5. **Employee dimension defaults to the Agency's own Employees** (`Employee.user_id == ctx.agency_user_id`) whether or not `employees` is given — a co-owned Creator's other-Agency senders never appear (`service/msg_stats.py:80-89`, co-ownership `service/db/models.py:2735`).
6. `employee_sales` refuses Creators co-owned with another Agency in v1 (attribution reads the first billable owner's settings, `service/sales_attribution.py:233-265`).
7. The executor checks itself: tenant middleware scans query+path only (`service/server.py:510-560`).

**Formats/caps:** csv via `csv_export.stream_csv` (formula guard, 50k + TRUNCATED, `service/csv_export.py:27,37`); xlsx via `xlsx_io.write_xlsx`; json for MCP/Ultra `{columns, rows≤200, row_count, truncated, window{from,to,tz}}`. Money in dollars. Window ≤400 days for `sales`/`chat_activity`/`fan_spend`, ≤92 days for `employee_sales` (its fallback loads rows with `.all()`); one report run at a time per Agency.

**Time zone:** zone + week_start from `applied_blob(…, "preferences")`, UTC fallback; presets mirror `app/lib/dateRange.ts`; `stats_window.parse_bound(zone=)`; **fractional-offset zones fall back to minute rereading**, as `stats_employees.py:149` does (`local_days` returns `None`, `service/tx_rollup.py:503-521`).

**Unsupported asks** (e.g. departed subscribers — not stored, `service/stats_fans.py:125`): `GET /admin/reports/catalogue` is the help bot's closed book; it says "not available" and offers the nearest dataset.

**Files:** `service/report_recipe_decide.py` (pure: CATALOGUE, kind maps, `parse_recipe` with per-field errors for LLM repair, `resolve_window`, `clamp_creators`, `shape`, `filename`), `service/report_recipe.py` (`run`), `service/report_recipe_api.py` (`POST /admin/reports/run` under `permissions.ACTIONS["export"]`, `GET /admin/reports/catalogue`). Plain-script tests: decide tables + two seeded Agencies sharing a Creator (foreign Creator refused, Master sees own links only, no engine gets `None`, no other-Agency Employee row).

ASSUMPTION: owners only in v1 (map Notes say Ultra/MCP owners-only; Do-mode export inherits it). Overturned if chatters with "export" permission should get it — falls: Do-mode export.
ASSUMPTION: `chat_activity` = Employee direct sends only (mass/auto PPVs excluded, as Infloww's chatting stats). Overturned if owner wants mass PPVs — add a `ppv_messages` dataset.
ASSUMPTION: 92-day cap + one run per Agency are enough to bound execution. Overturned by a slow run on AE-sized data.

**Adversary (codex, 2 phases):** P0 Employee leak via co-owned Creators — accept (rule 5). P1 attribution reads other Agency settings — accept (rule 6). P1 fractional zones — accept. P1 kind enums not executable — accept (mapping tables). P2 employee time bucket — accept. P2 unbounded execution — partial (caps + one-at-a-time; no streaming rewrite). Phase-1: OF top-ups — accept (sales follows Creator reports, rung 3); unsupported-request behaviour — accept.
