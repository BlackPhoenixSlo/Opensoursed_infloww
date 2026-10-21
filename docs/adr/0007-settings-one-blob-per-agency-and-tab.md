# Settings are one opaque JSON blob per Agency and Blob tab

Consequence 1 superseded by ADR-0012 (validated on write).

Infloww's Settings tabs hold dozens of fields across six Blob tabs, and Role Settings implies a roles model with per-Employee assignments. We decided to store all of it in one table, `user_settings` (`user_id` FK CASCADE and `tab` as the composite key, `config_json` Text, `updated_at`), served only by `GET/PUT /admin/settings/{tab}` with an allow-list of the six Blob tabs, where a PUT replaces the whole Settings blob. There are no per-field routes, no roles table and no role column on `employees`: Permission roles and their assignments live inside the `roles` blob, assignments keyed by Employee id and permissions keyed by nav href. The reason is YAGNI. Nothing reads these values yet (ADR-0008), so a schema now would be shaped for consumers that do not exist, and one JSON-as-Text row per key is the house pattern for stored config (`UserLlmKey`, `service/db/models.py:2669`; upsert in `service/webhook_config_api.py:98-115`). Rows are keyed by `users.id`, which is the Agency (`service/db/models.py:2669-2672`), so "Your Preferences" and "Security (personal)" belong to the Agency login, not to each Employee.

## Consequences

- The server does not validate keys inside a blob, so each blob's shape is a contract between its Panel and its tests.
- A future consumer that must query across values (for example "which Employees hold this Permission role") has to parse JSON or migrate the blob into columns.
- A deleted Employee or a renamed route leaves stale keys in the `roles` blob. Deriving the permission pages from the `SIDEBAR` groups keeps the editor from drifting, not the stored keys.
- Because a PUT replaces the whole blob, every Save sends the full object and sits behind the Load gate.

## Considered Options

- **Per-field routes and typed columns.** Rejected: a migration per field for values nothing reads.
- **A roles table plus a role column on `employees`.** Rejected: an enforced-looking schema for permissions nothing enforces, and a schema change to a table every Employee path reads.
