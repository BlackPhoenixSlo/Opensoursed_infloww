# Bio page background

Type: grilling
Status: answered (build, 2026-11-14; owner may veto)
Blocked by: none

Page-level background picture for bio pages: model field, vault pick endpoint (mirror avatar/vault), public render, SFW pick by Ultra.

## Answer

**Add `BioProfile.background_image` with upload / vault / delete routes that mirror the avatar ones, render it as the public page's backdrop at every width, and expose one Toolbox write tool `bio_page_background`; Ultra picks the photo through the ticket-09 `not_nude` search + a `judge` step.**

- **Model:** `background_image: Mapped[str]` String NOT NULL default `''` on `BioProfile` (`service/db/models.py:3980`), same shape as `BioLink.background_image` (`:4023`). One Alembic migration chained after whatever head exists when step 5 lands (today 0118 `20261114_0100_owner_tokens.py`; step 4 may add one).
- **Routes (mirror avatar, `service/bio_pages/admin.py`):**
  - `POST /admin/bio-pages/{pid}/background` upload, like `/{pid}/avatar` (`:508`), resized to `BACKGROUND_SIDE` 1080 (`service/bio_pages/images.py:14`).
  - `POST /{pid}/background/vault {media_id}` like `/{pid}/avatar/vault` (`:562-570`): `_vault_image(owner, pid, request, BACKGROUND_SIDE)` (`:539`, photos only, 415 else) + `_set_file` (`:477`) + `_audit_as`.
  - `DELETE /{pid}/background` like `DELETE /{pid}/avatar` (`:573`).
- **Output:** `_page` gains `background_url` (`admin.py:209-229`); `store._PROFILE_COLS` adds `background_image` (`service/bio_pages/store.py:20`); public JSON adds `backgroundUrl` next to `avatarUrl` (`service/bio_pages/decide.py:301`).
- **Public render:** `script.js` sets `--backdrop-url` from `backgroundUrl` when set, else the avatar as today (`service/bio_pages/public/script.js:139-145`), and adds a body class that shows the backdrop at every width, dimmed for text legibility. Today the page backdrop is a blurred avatar on desktop only (`public/style.css` `body::before` in `@media (min-width: 768px)`, `:516-536`); phone portrait has none. No background set → page unchanged.
- **Editor:** a Background row in `app/components/growth/bio/BioProfileCard.tsx` copying the avatar row (upload, "Pick from vault" `VaultPicker`, Remove, `:34-91`); `bioPreviewModel.ts` `PreviewProfile` gains `backgroundUrl`.
- **Toolbox:** `bio_page_background` (effect write, `replaces=True`, args `tw.BioVaultImageArgs` = pid + media_id, open `/growth/bio-pages/{pid}`), same as `bio_avatar_from_vault` (`service/toolbox_decide.py:217`). No `check` (`_set_file` always writes a new name; build-log step 3). Bearer allowlist follows from TOOLS (`token_auth.write_refusal`).
- **SFW pick by Ultra:** `vault_search` with `not_nude=true` (ticket 09) on the page's Creator, preferring stories-lane items (`vault_scripts.PURPOSE_LANES` stories = sfw→suggestive, "safe enough to post publicly", `service/vault_scripts.py:1351`), photos only. `judge pick_n=1`; with `confirm` → the ~6-thumbnail card. "Each model missing one" = `bio_pages_list` / `bio_page_get` where `background_url` is empty.

ASSUMPTION: Jev `free` + current reading is SFW enough for a public page. Overturned if owner wants stricter (e.g. `explicitness_tier = sfw` only) → add the tier to the same search, no new route.
ASSUMPTION: a dimmed full-bleed photo keeps links readable on phone. Overturned by the step-5 phone screenshot → blur it like the desktop backdrop.
ASSUMPTION: one page-level picture, no per-breakpoint crops or video. Overturned if owner asks for focal point/video.

Deferred: background video, focal-point crop, custom domain linking.

Build: step 5 (column + migration + 3 routes + render + editor row + tool); can ship as a step-3-style write tool at the start of step 5.
