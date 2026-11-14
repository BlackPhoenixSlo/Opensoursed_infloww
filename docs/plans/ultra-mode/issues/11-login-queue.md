# Sequential login queue

Type: grilling
Status: answered (build, 2026-11-14; owner may veto)
Blocked by: 03

Pasted logins → parsed without passwords reaching the LLM → sequential Browserbase jobs → OTP card → 5-min not-logged-in notice. Where parsing happens, how the queue survives, how secrets are held.

## Answer

**A paste card posts the logins to a new server route `POST /admin/login/remote/queue` that parses them, holds passwords in memory only, and runs the existing Browserbase `start_login` one at a time; the LLM never sees the paste and only gets an open_url to the card.**

- **Where parsing happens:** server-side, in one pure parser (`email<sep>password` per line; `:`/tab/space/`|`; dedupe emails; bad lines returned by line number, never echoed). Route under `/admin/login`, already audit-skipped because the start body carries the OF password (`service/audit_log.py:40-42`). Same principal rule as `/admin/login/remote/*` (`service/remote_login_api.py:102-145`).
- **Keeping the paste out of the LLM:** Ultra's chat box and `POST /admin/ultra/plans` run the same parser before any model call. A message holding a login line is refused ("paste logins in the Connect card"), and the user's text is not stored. The planner may emit an `open_url` step to the paste card ("connect N models"), nothing else. MCP: no OF-login tool; a tool answer may carry the paste card's open_url (`connect_account` is the Inflowwww-account link, `service/mcp_api.py:12`, not OF).
- **Sequential run:** one queue per owner; a worker awaits each job before starting the next. It calls `remote_login.start_login(email, password, principal, backend="browserbase")` with the default proxy (Inflowwww pool, `remote_login_api._resolve_proxy("", "")` `:85`; never force a proxy, owner memory). A second job for the same email already raises `RemoteLoginConflict` (`service/remote_login.py:171,332`).
- **Secrets:** each password lives on the in-memory queue entry until its job starts, then only as the worker-thread local `start_login` already uses (`remote_login.py:1-50`, `scrub()`). Entry cleared on start, cancel and queue end. Never in DB, audit, logs, `plan_json`, notify text or the queue's GET answer (emails + states only).
- **OTP card:** job state `otp` → a needs_you card with the code box POSTing to the existing `/admin/login/remote/{id}/otp` (`remote_login_api.py:145`) + the live-view link. Reuse status/OTP pieces of `app/components/setup/BrowserbaseLoginCard.tsx`, not the card itself (it starts its own job and cancels on unmount). Must work on phone portrait.
- **5-min notice:** the job's own window is 285 s (`remote_login.py:103`; Browserbase session 300 s). A job ending error/timeout/not-logged-in → `notifications_api.notify(owner, [Notice(kind="ultra_needs_you", text="<email> not logged in after 5 min", …)])` (`service/notifications_api.py:142`) + a card, then the queue moves on. No auto-retry; retry = re-paste that line.
- **How the queue survives:** it does not. `_jobs` is in memory (`remote_login.py:315`) and passwords are never stored, so a relay restart drops the queue; the card shows `interrupted` with done/left emails and the owner re-pastes the rest (same no-resume rule as ticket 06).
- **After login:** steps on the new accounts (folders, bio pages) are a later plan; account ids do not exist at plan time.

ASSUMPTION: one Browserbase session at a time is fast enough (≈1–5 min per model, so 10 models ≈ ≤50 min). Overturned if owner wants parallel → a concurrency knob on the same worker.
ASSUMPTION: losing the queue on restart is fine (deploys ≤10 min, rare). Overturned if a deploy mid-queue bites → store emails (never passwords) so the card lists what to re-paste.
ASSUMPTION: no captchas on Browserbase login (owner). Overturned if a job reports one → treat as error + notice.

Deferred: parallel jobs; persistence; CSV upload; per-line proxy choice.

Build: step 5 (queue route + parser + paste/OTP cards + notice). Step 6 `login` is the Inflowwww account login, not OF; it does not touch this.
