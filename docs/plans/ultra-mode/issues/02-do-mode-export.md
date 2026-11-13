# Do-mode export intent

Type: grilling
Status: resolved
Blocked by: 01

How does plain Do mode take "sales last 7 days for Anna and Mia" to a confirm card and a CSV download? Where the intent lives in `assistant_draft.py`, what the card shows (row-count preview?), CSV vs xlsx, permission gate (owner-only vs export permission), prompt-catalog entry.

## Answer

**Fourth flow `report_export` inside the existing one-call Do draft** (`service/assistant_draft.py` FLOWS). Rung 3 (house precedent: the 3 existing flows + confirm card, `assistant_draft.py:117`, `DoMode.tsx:123`).

Server
- `Intent.report {dataset, window preset|{from,to}, creators[], employees[], kinds[], group_by?, metrics?, sort?, limit?, format csv|xlsx}` — mirrors the [Report recipe](01-report-recipe.md) fields incl. `employees` and `kinds`. xlsx only when the user says Excel/xlsx/spreadsheet.
- Catalogue text rendered once at import from `report_recipe_decide.CATALOGUE` into the system prompt (sorted, no account data) → prompt stays byte-stable (`assistant_draft.py:42`). `CREATORS:` (Agency nicknames), `EMPLOYEES:`, `TODAY: <date> (<zone>)` go in `user_block` (`:1252`). 3 few-shots.
- Pure `resolve_export(intent, creators, employees, zone, today)`:
  - Every named Creator/Employee must resolve **uniquely** (exact, else single containment; two candidates or a fuzzy-only hit = `unresolved`). Do **not** copy `match_named` (first match wins, `assistant_draft.py:483-499`). Any unresolved name → Download disabled (export `canStart` checks `unresolved`, unlike `doRunReducer.ts:56`).
  - No names → all owned Creators (not the focused one).
  - A requested restriction that fails to parse (kind, employee, window) → refuse with the reason; never drop it into a wider report. Only `sort`/`limit` may be dropped, with an assumption line.
  - Unknown dataset → "not available, nearest is X".
  - Slots carry the recipe with ids and the window **fixed to {from,to} at draft time**, plus format, labels, columns, filename.
- Entry without a focused Creator: `account_id` optional on `POST /admin/assistant/draft`; when absent only `report_export` may come back (other flows → "pick a Creator first"). Client `sendDo` no longer returns early for export-only general focus (`AssistantWidget.tsx:343`).
- Gate: owners only (`get_request_user()` present) → else `EXPORT_NOT_ALLOWED_ANSWER`; `/admin/reports/run` re-checks.
- Vetoed on refine or when no report word is present. Update `UNSUPPORTED_ANSWER`, `DO_HINT`, `draftFrom` fallback.

Client
- `app/components/assistant/doExport.ts` pure (`exportSlotsFrom`, `exportPlanText`, `exportRunBody`) + vitest. `report_export` added to `DoFlowId`/`DoDraft`.
- `doRunReducer` gets an `attempt` counter; the download effect keys on `(draft.id, attempt)`, not the draft object (mass_edit pattern dedupes by object and would hang "Try again", `AssistantWidget.tsx:329-338`). Try again = `attempt+1`. Table tests.
- Effect: `relayFile("/admin/reports/run")` → `saveBlob(filename)` (`app/lib/relay.ts:332`, `app/lib/csv.ts:21`).
- `ExportThread` card: dataset, window from–to + tz, Creators, Employees, kinds, columns, format, notes; Download / Cancel → "Building the file…" → "Downloaded <file>" | error + Try again. No row-count preview (would cost a second run).

Docs/eval, same PR: `docs/prompts/README.md` entries; ~40 export cases + `EXPECT_KEYS` in `scripts/assistant_draft_eval`; `resolve_export` tables in `test_assistant_draft.py`; re-run the full eval on flash before ship (existing flows must not regress).

Demo: `POST /admin/reports/run` classified ALLOWED (read-only, like `/admin/stats/xlsx`). Offline demo export is NOT expected to work: `fake_llm` answers every `help*` purpose with prose (`demo/fake_llm.py:119`), so Do mode is already offline-dead in demo; unchanged.

ASSUMPTION: no names = all owned Creators. ASSUMPTION: offline demo keeps Do mode dead (house precedent, rung 3). ASSUMPTION: general-focus entry via optional `account_id` (rung 5).

Adversary (codex, 2 phases): wrong-Creator fuzzy match → unique resolution required; missing `employees`/`kinds` → added, invalid restriction refuses; Try-again hang → attempt counter; demo claim corrected; general-focus path decided.
