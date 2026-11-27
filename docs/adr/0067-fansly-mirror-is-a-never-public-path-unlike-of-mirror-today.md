# The Fansly mirror is a Never-public path; it ships to AE but not to public, demo or Twin

**Status: accepted** (2026-11-27, `.scratch/fansly-manager-mirror/map.md` Phase 1; ticket 06; built in issues 07 and 08).

`app/public/of-mirror/NOTICE.md` and `docs/OPEN_SOURCING.md:81-86` say the OF mirror never goes public, but nothing enforces it: `check-public-export.sh` is not wired into public-sync or deploy-all, `NEVER_PATHS` in `.claude/skills/public-sync/leak-check.sh` has no mirror entry, and the OF mirror's 397 files are on `public/main` and `twin/main`. Following that precedent would publish the Fansly mirror the same way, and a published file cannot be taken back out of public history. We decided `app/public/fansly-mirror` (no trailing slash, so the `.tmp` stage and a bare file match too) joins the public and strip `NEVER_PATHS` beside `app/public/client-brand/`, and not the AE profile: private main and AE get the copy, while public replay skips it as "never public", the whole-tree gate rejects a public tree holding it, `demo/deploy.sh` rejects such a base, and Twin, merging only gated public commits, never receives it. Route tables and tests still ship; on public a missing page is an iframe 404 and the default-off `fansly_manager` flag hides the nav. We chose the client-brand pattern because it is the only exclusion the gate actually enforces, and AE already serves the OF mirror. The cost: the two mirrors ship differently until the owner decides the OF cleanup, which this decision leaves parked.

## Considered Options

- **Follow the OF mirror precedent (NOTICE plus `check-public-export.sh`).** Rejected: measured not to keep the OF mirror out.
- **Keep it off AE too.** Rejected: AE already serves the OF mirror and the owner asked to ship.
