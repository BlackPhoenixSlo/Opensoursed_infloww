# Future plan: Creator subgroups + multi-box agencies (NOT built — YAGNI, 2026-10-25)

Idea: group Creators into subgroups (one subgroup per Creator), let a subgroup's
workers see only their subgroup's Creators in "All models", and run subgroups on
separate boxes under one agency account, while the owner Dashboard still totals
every Creator.

## What already exists
- Employee groups: nested tree `employee_groups` (`service/db/models.py` ~3037),
  one group per employee via `employees.group_id`. UI: `app/components/settings/EmployeesTab.tsx`,
  API: `service/employee_groups_api.py`.
- Employee→Creator visibility: `chatter_account_access` allowlist, enforced per
  request in `service/auth.py` (`clamp_account_filter`). A chatter's All inbox
  already equals their allowed Creators.
- Creator grouping: only a UI "Tag" (`app/lib/creatorProfiles.ts`), not enforced.
- Dashboard: owner stats total all Creators (`service/stats.py`); sales accept `group_id`.
- Boxes: one relay = one DB = one whole agency (`deploy/fleet/README.md`). Only
  cross-shard call is fleet `whois` (`service/fleet_api.py`, `FLEET_SECRET`).

## Smallest change set when needed
1. `account_groups(account_id PK, group_id → employee_groups.id)` — PK enforces
   one group per Creator. `PUT /admin/employee-groups/creators {group_id|null, account_ids[]}`
   next to `set_members`; Creators column + batch action mirroring the employee one.
   Fold Tags into this.
2. Derive access in `_load_identity_from_db` (`service/chatters.py` ~312):
   intersect allowed Creators with the chatter's group's Creators. One point feeds
   `/chatter/me/accounts`, inbox, request gate. Empty group = today's behaviour.
   Emit `assignment_changed` on writes.
3. Inbox: add a group scope to `ScopeContext` (today `all | model`).
4. Dashboard: owners unaffected. If workers must see combined stats, split an
   inbox-only account set from the stats gate.
5. Boxes: SQLite single-writer, so relays cannot share a DB. Cheapest path: one
   subgroup = one shard as its own agency (as today) + `/auth/fleet/stats` behind
   `FLEET_SECRET`, summed by the front shard into a combined owner Dashboard.
   A true single agency across relays (shared identity, Creator→box assignment,
   extended `oi-epoch` fencing) is a large rebuild — avoid.

## Open question
Request text said a subgroup's Creators "cannot be shown in all models"; assumed
meaning: workers see only their own subgroup's Creators in All models.
