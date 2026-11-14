# Halloween pick pipeline

Type: grilling
Status: answered (build, 2026-11-14; owner may veto)
Blocked by: 04

Theme find (AI descriptions first; run describe on undescribed items?), not-nude filter (existing flag?), "best" pick (vision model over thumbnails vs stats), two OF folders 10–20 each, rules from mass folder (48-newest cap), send/post now.

## Answer

**Theme = several `vault_search` queries over AI descriptions, with a new server-side `not_nude` filter on Jev's current reading; "best" = a `judge` plan step over the candidates' descriptions; folders, rules and the post/message now are existing tools pinned as plan steps.**

- **Theme find:** the planner runs `vault_search` (GET `/admin/vault-ai/items`, `service/toolbox_decide.py:170`) a few times (halloween, costume, witch, pumpkin…); the search is a LIKE over description/tags/of_terms (`service/vault_ai_api.py:628-650`). `limit` ≤30 per call (`toolbox_decide.py:126-131`), so 2×20 needs 2+ queries; dedupe by media id.
- **Not nude (only new filter):** `not_nude: bool` on `GET /admin/vault-ai/items` + `VaultSearchArgs`. SQL: `json_extract(ai_fields_json,'$._jev.lane5') = 'free'` AND the reading is current (`$._jev.v` = `vault_jev_rules.VERSION`, status ok; same test as `vault_jev_rules.current`, `service/vault_jev_rules.py:243`), guarded by `json_valid` like `service/vault_pack_picker.py:477-482`. Excludes `review` (NudeNet veto) and every item with no Jev reading (`vault_ai_brief.flags_known`: absence ≠ safe).
  - Not `explicitness_tier` alone: `column_tier` keeps an old describe tier or an operator lock (`service/vault_jev_flags.py:168`).
  - toy/text/feet stay veto-only (owner); `not_nude` also drops `_jev.tags.toy_any = 'y'` (`service/vault_jev_rules.py:148,213`): Jev already sends a toy in the plain lane to review (`:106`), but implied/lingerie + toy can still be free. text/feet stay in.
- **Undescribed items:** never auto-start describe-all (paid, `service/vault_ai_vision.py:1033`). New read tool `describe_all_plan` over the existing free GET `/admin/vault-ai/describe-all/plan` (`:1053`). The plan card shows "N undescribed, not searched" + open_url Vault Pro. Too few candidates (<10 per folder) → the plan says so instead of padding; the owner starts describe and re-asks.
  - Jev runs inside the describe sweeps (`service/vault_jev_pass.py:1-7`), so undescribed items mostly lack Jev too and `not_nude` already excludes them.
- **"Best" pick:** `judge {question, candidates, pick_n}` step (ticket 06 amendment) over the candidates' text descriptions + Jev flags. No vision call over thumbnails (descriptions are the owner's prerequisite; no new per-thumb spend), no stats (no per-media sales signal in vault search).
- **Two folders:** two `of_folder_create` steps (`toolbox_decide.py:206`) with `media_ids = $judge.picks` (10–20 each). Photos only: the rule pool reads the 48 newest non-DRM PHOTOS of a folder (`service/automations/_pools.py:55-66`), so videos in the folder are never sent; 20 < 48, so the cap does not bite.
- **Rules:** `mass_premade` (`media_folder_id`) / `auto_stories` (`folder_id`) / `auto_posts` (`service/automation_catalog.py:281,295,336`) with `$create.id`; send-class rule tools from step 4.
- **One post + one message now:** step-4 send tools `post_create` / `mass_send`, media from a `judge` step with `pick_n=1, confirm=true` → the ~6-thumbnail pick card, AI pick pre-ticked. Text passes the ticket-13 chain at submit.

ASSUMPTION: Jev `lane5 = free` + current reading = "not nude" (owner: "not new" = not nude). Overturned if owner wants `$10` (breasts bare) allowed in a free mass/story.
ASSUMPTION: excluding toy-tagged free items is wanted. Overturned if owner says toy-free shots are fine for masses.
ASSUMPTION: text descriptions are enough to judge "best". Overturned if the pick cards show the owner un-ticking most picks → add a vision judge over the 6 thumbs (paid, owner opt-in).
ASSUMPTION: post/mass text is theme-level (written at plan time, before picks are known). Overturned if owner wants text naming the picked item → needs a post-judge write step.

Deferred: auto-run describe on undescribed items; per-media sales ranking; videos in rule folders (pool is photo-only).

Build: step 5 (`not_nude` param, `describe_all_plan` read tool, `judge` + pick card). Send/rule tools: step 4.
