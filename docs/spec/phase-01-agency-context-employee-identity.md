# Phase 01 — Agency context and server-side employee identity

**Objective.** The Relay has one helper that answers "which Agency, which Employee, owner or Master" for a request from the session alone, and one shared two-Agency test fixture that later Phases use for their cross-agency negative cases.

## Problem Statement

Agency isolation is solid for Creator-scoped resources: `assert_account_owned` and the account isolation middleware refuse any Creator outside the caller's Agency. The next Phases (Shifts, S4S, Role enforcement) add rows that belong to an Agency but not to a single Creator, and the Relay has no single answer to "whose Agency is this request?":

- An Owner session's Agency is its own `users` row. Nothing names it as such; each router re-reads `require_user().id` (the Settings router does this for its blobs).
- A Chatter session can be linked to several Agencies (`ChatterIdentity.owner_user_ids`), and no helper says which one the request acts in.
- The Employee behind a request comes from three paths in the employees module's `resolve_outbound_employee_id`. A chatter resolves server-side to its Mirror Employee. An owner's client-picked `X-Employee-Id` is trusted after an ownership check. An unauthenticated caller's header is taken as-is.

The roadmap gate says identity comes "from server-side session context, never a trusted client-supplied employee or agency id". Without a shared helper, each later Phase would rebuild tenancy on its own, and one of them would end up trusting a header. Nor is there a shared fixture that proves Agency A cannot read or write Agency B's rows, so each Phase would seed its own and drift.

## Solution

From an Employee's point of view nothing visible changes in this Phase. What changes is the guarantee behind every screen the later Phases add:

- An owner who opens Shifts or S4S sees and changes only their own Agency's rows, whatever ids the browser sends.
- A chatter linked to two Agencies acts in the Agency that holds the Creator they are working. Their clock-ins and requests are recorded against their own Mirror Employee in that Agency, never against an id the client picked.
- A request with no session gets 401 from every new endpoint, even on deployments that set `ALLOW_ANONYMOUS_ADMIN`.

For developers, the Relay gains `agency_context`, a single call returning the Agency context, plus a test fixture module that seeds two Agencies and a Master and logs any of them in.

## User Stories

1. As an owner, I want every new agency-scoped endpoint to derive my Agency from my session, so that a forged agency id in a header, query or body cannot read or write another Agency's rows.
2. As an owner, I want the Relay to treat me as the Agency and not as an Employee, so that an action I take is never credited to an Employee I picked in the roster.
3. As an owner, I want an `X-Employee-Id` header on a request to be ignored by `agency_context`, so that the client-picked roster choice cannot become an identity on the new endpoints.
4. As a chatter linked to one Agency, I want the Relay to know my Agency and my Mirror Employee without my naming either, so that Dashboard cards and clock actions work on any screen.
5. As a chatter linked to two Agencies, I want the Agency to be chosen by the Creator I am working, so that my actions land in the Agency that holds that Creator.
6. As a chatter linked to two Agencies, I want a clear 400 when a request names no Creator and the Agency is ambiguous, so that the Relay never guesses which Agency I meant.
7. As a chatter, I want a Creator I cannot access to be refused with 403, so that naming another Agency's Creator cannot move me into that Agency.
8. As a chatter, I want my Mirror Employee created on first use if it does not exist yet, so that my first clock-in or request in a new Agency does not fail.
9. As a chatter, I want any `X-Employee-Id` I send ignored, so that I cannot act as a colleague.
10. As a chatter whose links to every Agency were removed, I want a 403 rather than a context with no Agency, so that an orphaned chatter account reaches nothing.
11. As a person with both an owner cookie and a chatter cookie in one browser, I want the owner session to win, as it already does for Creator access, so that my identity is not mixed between the two.
12. As the Master, I want `agency_context` to say I am the Master while keeping my own Agency as the Agency, so that later Phases can decide explicitly where Master sees across Agencies instead of inheriting it by accident.
13. As the Master impersonating an owner, I want `agency_context` to return the impersonated owner's Agency, so that what I see while impersonating matches what that owner sees (mutations stay blocked by the existing impersonation gate).
14. As an anonymous caller, I want every endpoint built on `agency_context` to answer 401, so that no new surface inherits the `ALLOW_ANONYMOUS_ADMIN` escape hatch.
15. As an internal cron or curl caller of the existing chat-send paths, I want the unauthenticated `X-Employee-Id` fallback left exactly as it is, so that existing automations keep their attribution.
16. As an owner sending chat messages, I want the existing roster pick (`X-Employee-Id`) for "Sent by" attribution to keep working, so that this Phase does not change chat attribution.
17. As a developer of Phase 2, 3 or 4, I want one async call that returns `{agency_user_id, employee_id, is_owner, is_master}`, so that my router does not re-derive tenancy.
18. As a developer of a later Phase, I want a fixture that seeds Agency A and Agency B, each with an owner, a chatter and a Creator, plus a chatter linked to both and a Master, so that my cross-agency 403/404 cases are a few lines each.
19. As a developer, I want the fixture to log in any seeded principal and hand back a test client carrying the real session cookie, so that my tests go through the real session middleware and not through patched ContextVars.
20. As a reviewer, I want the fixture to use neutral, obviously fake names and ids, so that no real creator, fan or account name appears in tests or logs.
21. As a reviewer, I want the Phase's own tests to prove each `agency_context` rule through an HTTP request, so that the guarantee is tested where later endpoints will rely on it.

## Implementation Decisions

- **Owns.**
  - The employees module (`service/employees.py`). It gains `agency_context` and an `AgencyContext` value. Its Mirror Employee get-or-create is split out of `resolve_chatter_employee_id` so that it can be called with an Agency directly.
  - A new test fixture module, `service/tests/_agency_fixtures.py`. It is not a test file, following `_gc_fixtures.py`.
  - A new test file, `service/tests/test_agency_context.py`.
- **What "which role" means here.** The plan's goal asks for "which agency, which Employee, which role". In this Phase "role" is the principal kind only: Owner, Master, or Chatter (both flags False). The Permission role a chatter holds through Settings is resolved by Phase 4's `require_permission` from `employee_id`, not carried in this context.
- **Interfaces.**
  - `async agency_context(*, account_id: str | None = None) -> AgencyContext`, in the employees module. It reads only `get_request_user()` and `get_request_chatter()` (the ContextVars the session middlewares set from signed cookies), plus the database. It never reads a header, query or body. A caller that has a Creator in its path, query or body passes that id as `account_id`.
  - `AgencyContext` is a frozen value:

    ```python
    @dataclass(frozen=True)
    class AgencyContext:
        agency_user_id: str        # users.id of the Agency
        employee_id: int | None    # Mirror Employee for a Chatter session; None for an Owner session
        is_owner: bool             # True for an Owner session (Master included)
        is_master: bool            # users.is_admin
    ```

  - The Mirror Employee get-or-create becomes `get_or_create_mirror_employee(chatter_id, owner_user_id, *, display_name, color) -> int | None`, carrying today's steps 2 and 3 (SELECT, INSERT, IntegrityError re-SELECT) unchanged. `resolve_chatter_employee_id` keeps its signature and behaviour (pick the alphabetically first linked owner that holds the Creator), then calls it. `resolve_outbound_employee_id` is not changed.
- **Schema.** None. The plan's ASSUMPTION already notes that `Employee.user_id` is the owning Agency, not the person. The partial unique index `uq_employees_chatter_owner` on (chatter_id, user_id) keeps one Mirror Employee per chatter and Agency only where Alembic created it. The Mirror Employee get-or-create's docstring (`service/employees.py:671-685`, `get_or_create_mirror_employee`) says databases brought up by `create_all()` may lack it, and two racing first calls can then insert two rows. This Phase does not change that. The guarantee it tests is the sequential one: a second call returns the first call's id. On a database that already holds duplicate Mirror Employees, the fast-path SELECT raises inside the get-or-create's catch-all, which returns None, so `agency_context` answers 503 for that chatter and Agency rather than picking one of the rows.
- **Contracts.** Nothing new crosses the Relay boundary in this Phase. Endpoints built on `agency_context` in later Phases inherit these responses, checked in this order:
  1. **401 `sign in required`.** Neither an Owner session nor a Chatter session is present. `ALLOW_ANONYMOUS_ADMIN` does not change this.
  2. **403 `not your account`.** `account_id` is given and fails `assert_account_owned` for the active principal.
  3. **403 `chatter is not linked to an agency`.** A Chatter session has no linked owners.
  4. **400 `name a creator to choose the agency`.** A Chatter session is linked to more than one owner and no `account_id` is given.
- **Resolution rules.**
  - **Owner session (User cookie present; it wins over a chatter cookie, as in `_actor_account_ids`).** `agency_user_id` is the user's id, `employee_id` is None, `is_owner` is True, and `is_master` is `user.is_admin`. A named `account_id` only has to pass `assert_account_owned`. It never moves the owner into another Agency.
  - **Impersonation.** It needs no special case. The session middleware already overlays the impersonated user onto `get_request_user()`, so the context is the impersonated owner's. The existing middleware still 403s mutations while impersonating.
  - **Chatter session.**
    - The candidate Agencies are `owner_user_ids`.
    - With an `account_id`, after `assert_account_owned`, the Agency is the alphabetically first candidate that holds the Creator in `user_accounts` and whose Chatter Access allowlist for this chatter (`_account_restrictions_for`, applied by `_filter_owner_accounts` in the chatters module) does not exclude it. Without the allowlist filter, a Creator held by two of the chatter's Agencies and allowed under only the alphabetically later one would resolve to the earlier Agency, where the chatter has no access to it. `resolve_chatter_employee_id` keeps its unfiltered tie-break unchanged, so in that one cross-grant edge chat-send attribution and `agency_context` can name different Agencies.
    - Without an `account_id`, exactly one candidate is the Agency.
    - `employee_id` comes from `get_or_create_mirror_employee(chatter.id, agency_user_id, display_name=chatter.display_name or chatter.username, color=chatter.color)`. When that returns None (the database error path), `agency_context` raises 503 rather than returning a context with no Employee.
    - `is_owner` and `is_master` are False.
  - **Master.** `is_master` is True and `agency_user_id` is the Master's own id. Whether a Master reads across Agencies on a given endpoint is that endpoint's decision, made explicitly on `is_master` (Phase 4's role bypass and ADR-0012 say Owner and Master bypass role checks).
- **Placement.** `agency_context` sits in the employees module beside the Mirror Employee resolver, not in the auth module. Rung 3: the employees module already holds the get-or-create, imports `get_request_user` from the auth module and reaches `get_request_chatter` by a lazy import, while the auth module must stay free of a load-time `chatters` import (see its `_actor_account_ids` docstring).
- **Async.** `agency_context` is called as `await agency_context(...)` inside a handler, not as a FastAPI dependency. Rung 3: `require_user` and `require_master` are called inline the same way.
- **What it does not touch.** The account isolation middleware, `assert_account_owned`, `clamp_account_filter`, the chat-send attribution path and its owner `X-Employee-Id` pick, and the unauthenticated header fallback for internal callers are all unchanged.

## Testing Decisions

- **One seam: the Relay over HTTP with real session cookies.** `test_agency_context.py` registers a probe route on the Relay app inside the test process only. The route returns `agency_context(account_id=<query param>)` as JSON, or the error status. Each case logs in a seeded principal through `/auth/login` or `/chatter/login` and calls the probe, so the real session middleware and the real chatter middleware build the context. No ContextVar is set by hand, and no production route is added.
- Cases (each a `case_*`, plain-assert, `_harness.run()`):
  - Owner A gets Agency A, `employee_id` null, `is_owner` true, `is_master` false.
  - Owner A naming Creator A gets Agency A (a named own Creator is accepted, not just tolerated when absent).
  - Owner A naming Creator B gets 403.
  - Owner A sending `X-Employee-Id` of an Employee in A or in B still gets `employee_id` null.
  - Chatter A gets Agency A and a Mirror Employee whose row has `user_id` A and `chatter_id` A. A second call returns the same id, so no duplicate row is created.
  - Chatter A sending `X-Employee-Id` of another Employee gets its own Mirror Employee.
  - Chatter A naming Creator B gets 403.
  - Chatter A restricted by a Chatter Access allowlist away from a second Creator in Agency A gets 403 naming it, so the check is the chatter's real account set and not only its Agency links.
  - A Creator seeded into both Agencies' `user_accounts` (the cross-grant edge), with `chatter_ab` allowlisted out of it under the alphabetically first Agency, resolves to the other Agency.
  - When `get_or_create_mirror_employee` is patched in the test to return None (standing in for the database error path), a chatter call gets 503.
  - The two-Agency chatter with no Creator gets 400. Naming Creator A gives Agency A, naming Creator B gives Agency B, and the two Mirror Employees are different.
  - A chatter with every link removed gets 403.
  - A client carrying both owner A's and chatter B's cookies resolves as owner A.
  - The Master gets `is_master` true with its own Agency.
  - The Master impersonating owner B gets Agency B.
  - An anonymous caller gets 401, and still gets 401 with `ALLOW_ANONYMOUS_ADMIN=1` set for the call.
- **Attribution regression through the same seam.** This Phase refactors the get-or-create under `resolve_outbound_employee_id`, and no existing suite covers its owner or unauthenticated header paths (`test_chatter_auth.py:282-316` checks only that a chatter's header is ignored). So the test file mounts a second probe route that returns `resolve_outbound_employee_id(request, account_id)`, with cases:
  - Owner A sending `X-Employee-Id` of an Employee in A gets that id; of an Employee in B gets null.
  - An anonymous caller sending a digit `X-Employee-Id` gets that id back (the internal fallback, unchanged).
  - Chatter A naming Creator A gets the same id that `agency_context` returned for it.
- **Fixture contract (`_agency_fixtures.py`).** Importers bootstrap `_harness` first. Later Phases use it for cross-agency 403/404 cases on every route except S4S Discovery, which ADR-0011 makes the one deliberate cross-agency read. There the fixture serves the positive case instead: Agency A sees Agency B's opted-in Creator, and only the ADR's projection fields. It provides:
  - `seed_two_agencies()`, which returns a plain mapping of ids for: owner A and owner B; Creator A and Creator B (an `accounts` row plus a `user_accounts` link each, and an on-disk account directory in a temp sessions tree so the isolation middleware's `is_account` check is real); chatter A linked to A only; chatter B linked to B only; a chatter linked to both; and a Master user.
  - `login_owner(name)` and `login_chatter(name)`, each returning a test client with the real cookie.
  - Names and ids are neutral and obviously fake, for example `agency_a_owner`, `chatter_ab` and digit-only Creator ids such as `1000001`. Later Phases import this module rather than seeding their own two Agencies.
- **Regression.** The existing suites that exercise identity and isolation are re-run unchanged: `test_account_isolation_gate.py`, `test_chatter_access.py`, `test_chatter_auth.py` (it covers the chatter-side `X-Employee-Id` drop; the owner and anonymous paths are covered by the new probe cases above) and `test_settings_api.py`.
- **Prior art.** `service/tests/_harness.py` (temp DB, `make_client`, `run`). `service/tests/_gc_fixtures.py` (shared, non-test fixture module). `service/tests/test_settings_api.py` (`_seed_user`, `_seed_chatter`, `/auth/login`). `service/tests/test_chatter_access.py` (`/chatter/login`, dual-cookie client, chatter linked to two owners). `service/tests/test_account_isolation_gate.py` (sandboxed on-disk account tree).

## Acceptance

```sh
cd <repo>
./venv/bin/python service/tests/test_agency_context.py
./venv/bin/python service/tests/test_account_isolation_gate.py
./venv/bin/python service/tests/test_chatter_access.py
./venv/bin/python service/tests/test_chatter_auth.py
./venv/bin/python service/tests/test_settings_api.py
test -f service/tests/_agency_fixtures.py
grep -q '^async def agency_context' service/employees.py
grep -q '^async def get_or_create_mirror_employee' service/employees.py
# No header read inside agency_context: the function body must not mention request headers.
./venv/bin/python - <<'PY'
import ast, pathlib
src = pathlib.Path("service/employees.py").read_text()
fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "agency_context")
body = ast.get_source_segment(src, fn).lower()
assert "header" not in body and "x-employee-id" not in body, "agency_context reads a header"
PY
```

## Depends on

- Phase 0. It merges `t3code/recreate-infloww-ui-prompt` into `main`. That merge brings the chatter session (`service/chatters.py` with `owner_user_ids`), the Mirror Employee resolver in `service/employees.py`, `require_master`, the impersonation overlay, `service/tests/_harness.py` and the regression suites this Phase re-runs.

## Out of Scope

- Enforcing Permission roles or Role enforcement. Phase 4 builds `require_permission` on this context.
- Changing the owner `X-Employee-Id` pick for chat-send attribution. The plan keeps it, and Phase 0's matrix records it. It stays attribution metadata on chat sends only ("Sent by"); it is never an actor identity on an endpoint built on `agency_context`, which does not read it.
- Changing the unauthenticated `X-Employee-Id` fallback for internal cron callers. The plan leaves it untouched.
- New auth, 2FA or session management. The plan cuts these, and Settings keeps them Not wired.
- An owner-to-Employee link that would let owners clock in as themselves. It needs a new identity model the plan does not ask for (the plan's ASSUMPTION).
- A production endpoint that returns the Agency context (for example a "whoami"). YAGNI: `/auth/me` and `/chatter/me` already tell the app who is signed in, and no later Phase's UI needs the Agency id itself.
- Retrofitting existing agency-wide routers (Settings, roster) onto `agency_context`. They already key on the session user and are correct. Moving them is churn with no behaviour change.
- Agency selection by a raw agency id. The plan forbids it: the request names an account instead.

## Further Notes

ASSUMPTION: the signature is `agency_context(*, account_id=None)` with no `request` parameter, although the plan writes `agency_context(request)`. The session identity lives in ContextVars that the middlewares set, and `require_user` and `require_master` take no request either. Rung 3. Overturned if a later Phase needs something only the request object carries, in which case `request` is added as a first positional parameter.

ASSUMPTION: the helper lives in the employees module rather than the auth module. Rung 3: the Mirror Employee resolver and the lazy `chatters` import are already there. Overturned if the owner prefers all tenancy helpers in the auth module, which needs only a move and a re-export.

ASSUMPTION: a chatter linked to more than one Agency who names no Creator gets 400 instead of a default Agency. Rung 4: refusing is reversible, while a silent default could file a clock-in under the wrong Agency. Overturned if the owner wants a remembered "current agency" per chatter, which would need a stored preference.

ASSUMPTION: when a Creator is held by two of a chatter's linked Agencies, the alphabetically first owner id wins. Rung 3: `resolve_chatter_employee_id` already uses that tie-break, so attribution and Agency context agree. Overturned if cross-grants are removed or the owner picks another rule.

ASSUMPTION: the Master's `agency_user_id` is its own id. A Master naming another Agency's Creator is not moved into that Agency. Rung 4: cross-Agency power stays an explicit per-endpoint decision on `is_master`, not an implicit default. Overturned if the owner wants the Master to act inside whichever Agency holds the named Creator.

ASSUMPTION: Mirror Employee creation on first use stays a write inside a read path, as it already is for chat-send. Rung 3 (the glossary's "created on first use" and the existing resolver). Overturned if a later Phase needs a read-only context, which would add a `create=False` flag.

ASSUMPTION: the Phase's tests drive `agency_context` through a probe route that the test file mounts on the Relay app, rather than through a production endpoint. Rung 5: no new surface. Overturned if a later Phase's real endpoint lands first and can serve as the seam.

ASSUMPTION: a database failure while resolving the Mirror Employee answers 503. Rung 4: failing closed is reversible, while a null Employee on a clock action would record an unattributed event. Overturned if the owner prefers a degraded context with `employee_id` null.

ASSUMPTION: the chatter's Agency for a named Creator is filtered by its Chatter Access allowlist before the alphabetical tie-break, while `resolve_chatter_employee_id` keeps its unfiltered tie-break. Rung 4: leaving the existing attribution path untouched is cheaper to undo than changing it in a Phase that promises not to. Overturned if the owner wants the two to agree in the cross-grant edge, which means applying the same filter inside `resolve_chatter_employee_id`.

## Review

Reviewer: codex, 2026-10-16. Raw outputs: `.scratch/infloww-parity-next-steps/review/phase-01-blind.md` and `phase-01-draft.md`.

Blind call:
- Alternatives (owner-as-Agency, Creator-selects-Agency, reject-or-select on ambiguity, Master as global actor, owner-as-Employee): **reject** as a finding. The spec takes the plan's model and decides each fork explicitly (400 on ambiguity, Master keeps its own Agency, owners are not Employees), with an ASSUMPTION line for each.
- The owner `X-Employee-Id` path is an unstated exception to the identity gate: **partial**. The plan itself keeps it (plan Phase 1 Out of scope), so it stays. Out of Scope now states it is attribution metadata on chat sends only and never an actor identity on endpoints built on `agency_context`.
- "Which role" is underspecified: **accept**. Implementation Decisions now say "role" here is the principal kind (Owner, Master, Chatter), and the Permission role is Phase 4's, resolved from `employee_id`.
- The fixture does not cover multi-agency chatter, Master, dual cookie, inaccessible Creator or header injection: **reject**. The plan's fixture line omits them, but the spec's fixture and case list already include each one.
- "Every later Phase asserts cross-agency 403/404" conflicts with ADR-0011's Discovery read: **accept**. The fixture contract now names Discovery as the exception and gives it a positive projection-only case.
- The helper's failure contract is missing: **reject**. Contracts lists 401, 403 (account), 403 (no links), 400 (ambiguous) in order, plus 503, and the tie-break is decided.
- Test the seam and at least one agency-scoped route: **partial**. The seam is the Relay over HTTP with real cookies, as asked. No agency-scoped route exists in this Phase (no production route is added), so route-level cases belong to Phases 2-4, which the fixture exists for.
- Falsified if a multi-agency chatter has no Creator or Master has no target Agency: **reject**. Both are decided (400; Master's own id) and tested.
- `service/db/` missing from the snapshot: **reject**. It is an artifact of the sparse review workspace; `service/db/models.py` is tracked in the repo (`git ls-files service/db`).

Draft call:
1. One Mirror Employee per chatter and Agency is not guaranteed where the partial index is missing: **accept**. The Schema bullet now narrows the guarantee to sequential calls and states the duplicate-row outcome (503).
2. No case shows an owner naming their own Creator: **accept**. Case added.
3. No case for a Creator excluded by the chatter's Chatter Access allowlist: **accept**. Case added. It also exposed a real gap: the alphabetical tie-break ignored the allowlist. The resolution rule now filters by the allowlist, with a cross-grant case and an ASSUMPTION line.
4. The regression list does not exercise the owner and unauthenticated `X-Employee-Id` paths: **accept**. Verified: `test_chatter_auth.py:282-316` covers only the chatter drop. A second probe route over `resolve_outbound_employee_id` with owner, anonymous and chatter cases was added, and the regression note was corrected.
5. The 503 branch has no test: **accept**. Case added (get-or-create patched to return None).

### Six hats

Six-hats report, 2026-10-16 (`.scratch/infloww-parity-next-steps/review/six-hats.md`), reconciled as the Adversary brief does.

- Black (phase-01/02), contract mismatch: Phase 2 calls `agency_context(request)` and Phase 1 defines `agency_context(*, account_id=None)`: **accept**. Phase 1's signature stands. Rung 3: the session lives in ContextVars, and `require_user` / `require_master` take no request. The binding part of the plan's line is "from the session alone, no header input", and the keyword-only form keeps it. Phase 2 is rewritten to call `await agency_context(account_id=...)` (Reuses, Interfaces, Depends on). No change here.
- Yellow (identity solved once from the session, one shared two-agency fixture, Discovery the single named exception): **accept**, no change.
