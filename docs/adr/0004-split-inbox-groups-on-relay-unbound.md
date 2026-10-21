# Split Inbox groups are stored per Creator on the relay and are not bound to Employees

Infloww's Split Inbox divides one Creator's Fans into 1 to 9 Split Inbox groups. Assigning Employees to groups is verbal only, and the app records no binding (`docs/infloww-screens.md` §3.3, C[H262029]). We build the UI plus the group assignments only. Assignments are stored per Creator on the relay, beside the Creator's account config, so that every Employee and every device sees the same split. Groups carry no Employee binding and grant no permissions, which matches Infloww. A later binding would need a data migration and auth changes, and that is why this decision is recorded.

## Considered Options

- **`localStorage`.** Rejected because each Employee and each device would see its own split, which defeats the purpose of splitting.
- **Bind groups to Employees.** Rejected because Infloww does not bind them, and binding would reach into roles and the relay's auth.

## Consequences

- The relay's account-config store has no free slot today. `PUT /admin/account-config` upserts the AI "Brain" row from an allowlist, and unknown keys are dropped (`service/account_config_api.py:465`). Storing groups therefore needs a service change, under the plan's exception for a proven-missing relay endpoint.
- ASSUMPTION: by house precedent, that change is a per-feature JSON column on the same `account_ai_config` row with its own GET/PUT route, as `nudge_config_json` has with `/admin/nudge-config` (`service/nudge_config_api.py:110`, `:129`). This is overturned if the Phase 2 spec finds a better existing store. The schema change is only written into this working tree and is never run against a real database.
