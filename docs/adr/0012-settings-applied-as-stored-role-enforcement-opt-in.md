# Stored Settings are applied as stored, validated on write, and Role enforcement is opt-in per Agency

Status: accepted. Supersedes ADR-0008 for each field the infloww-parity-next-steps plan makes Applied (Phases 2 and 4); ADR-0008 still holds for every field left Not applied yet, and for Security, Billing and Balance actions, which stay Not wired.

ADR-0008 kept every Settings blob inert and warned that values saved while inert "take effect on the day a consumer starts reading them". The plan now wires consumers for `time-tracking`, `sales`, `preferences`, `account`, `messaging` and `roles`. We decided that blobs saved before this are applied as stored, with no migration and no reset, and that from now on the Relay validates each Blob tab against a schema carrying a `version` key and answers 400 on invalid input, while keeping ADR-0007's whole-blob replace. Sales attribution is applied in the read path only, so stored attribution rows are never rewritten. The one exception is `roles`: Permission roles take effect only under Role enforcement, a per-Agency switch that is off by default, with Owner sessions and the Master bypassing role checks. The reason is that most stored values are harmless to apply (a timezone, a week start), but a deny-all Permission role saved while it did nothing would lock a team out on upgrade day, and resetting every Agency's saved values would throw away work done in good faith. The cost is two states to test for every role-gated route, enforced and not, until the owner decides the default.

ASSUMPTION: the owner has not chosen the rollout; "off by default" is the plan's rung-4 answer and is listed under its Needs the human. Overturned if the owner wants Role enforcement on for every Agency at once, which turns this switch into a migration that reviews existing `roles` blobs first.
ADR-0008 reached `main` with Phase 0's merge, and its status line now reads "superseded in part by ADR-0012".

## Considered Options

- **Reset every blob to defaults when its consumer ships.** Rejected: it silently discards what Agencies saved.
- **Apply everything, including roles, at once.** Rejected: the lock-out risk ADR-0008's Consequences names.
- **Migrate the blobs into typed columns first.** Rejected: ADR-0007's YAGNI reasoning still holds, and server-side schema validation gives the safety without a migration per field.
