# Repository review guidance

Root `REVIEW.md` is canonical. `.claude/REVIEW.md` is an identical backup mirror, not an extra set of rules. Update both together. Keep development instructions in `CLAUDE.md`; combine these review rules with the current change's intended behavior.

## Evidence and severity

- Each finding needs severity, file:line, a reachable failure path or concrete structural problem, impact, and what fixed looks like. Label behavior claims measured, inferred, or guess; guesses need investigation before becoming blockers.
- Prioritize data loss, unauthorized access, unintended fan sends/charges, false success, and unbounded external calls. Distinguish introduced defects from pre-existing problems; keep unrelated cleanup out of the fix loop.
- Review coupled state against the reducer rule in `CLAUDE.md`. Prefer simpler existing abstractions; justify structural findings with concrete consequences, not cosmetic preferences.
- Do not duplicate formatter/linter output or demand tests that merely mirror implementation. Check claims in UI copy, docs, logs, and return values against actual behavior.

## Risk checks (apply only to touched behavior)

- Account/agency boundaries: trace ownership and authorization through routes, jobs, caches, and DB queries. An `/admin/` prefix alone is not authorization.
- Fan sends: trace intended recipient, price, deduplication, retry behavior, and outbound bookkeeping. No retry may silently duplicate an external send.
- Vault carriers: creation intent must survive failures; cleanup and reconciliation must handle interrupted runs so temporary posts cannot publish unexpectedly.
- Imports and mirrors: inspect partial writes, append/close races, restart recovery, and preservation of locally edited metadata. A partial sync must not delete unseen records.
- External calls: verify bounded pagination/retries, rate limits, and coalescing. Check refresh/remount paths for repeated calls and cross-account cache contamination.
- Success states: verify the requested write actually happened; exceptions, dropped work, and no-op paths must not masquerade as success.

## Verification

- Select checks by changed behavior. Slop is opt-in: only when the owner asked for it; missing slop is never a finding.
- When slop was requested, follow `slop/README.md`, including applicable fault checks; cite the concrete evidence folder.
- Evidence must be from the PR head, or from a head whose later diff touches no mapped path.
- For runtime changes, exercise the real local path. For a bug fix, show the check fails without the fix and passes with it. UI changes need a settled screenshot and a side-effect check.
- Use local/dev data and stub external effects. Never validate against production or paid services; retain the repository's production approval guards.

## Learning

Promote recurring, verified review lessons here only when they generalize. Keep branch-specific acceptance criteria and findings in per-run review material; revalidate historical prompts before treating their claims as current rules.
