#!/usr/bin/env python3
"""Route-order golden: moving handlers between modules must not reorder routes.

Starlette matches the first route in `server.app.routes` order, so e.g.
`/posts/chart` must stay before `/posts/{post_id}` and
`/users/me/stats/top/post` before `/users/me/stats/top/{kind}`. A router split
(`app.include_router(x.router)`) placed at the wrong spot silently shadows one.

Pins: the ordered (methods, path, endpoint __name__) list over
`server.app.routes`, plus sha1 of `app.openapi()`, equal the committed
test_route_order.golden.json. Both leave out the routes the optional
`*_wiring.py` modules add, so the golden does not depend on which of them a
checkout has; each such module's routes (and their OpenAPI sha1) are pinned in
their own test_route_order.<module>.golden.json, checked only when the module is
present. A wired route is one whose endpoint the module's `wire` binds on a
probe app. Regenerate ONLY for a deliberate route change and say so in the PR:
  ./venv/bin/python service/tests/test_route_order.py --write-golden

Golden refresh (2026-11-09): inspected ce072f9ce -> 40cd38d1e OpenAPI diff:
- GET /admin/stats/per-employee adds optional include_series: bool = false
  (9d5c8d811, dashboard daily employee sales).
- one GET list-detail route describes repeated pages as incomplete
  (f09a18467); description only, no contract change.
Routes/order and all other schema fields are unchanged; Phase 2's schema is
identical to 40cd38d1e. Keep these intentional base changes in the golden.
Phase 3 integration also retains its vault lists/media revalidate query params
and pins/head-read handler descriptions. The combined schema has its own hash;
route order stays unchanged.

Golden refresh (2026-11-10): main 8ab4d6fb4 intentionally adds POST
/admin/agency-notifications/dismiss-all and /{notification_id}/dismiss.
Removing exactly those paths reproduces the prior OpenAPI hash; remaining
routes retain their order. Refresh after integrating main into Phase 2.
Phase 3's hash = that schema plus Phase 3's four GET param/description edits
(measured: OpenAPI diff vs 40cd38d1e is exactly main's two paths + those four).

Golden refresh (2026-11-11): inspected ac38007b9 -> rwl W28-shell-notif OpenAPI diff:
- POST /admin/agency-notifications/dismiss-all takes an optional JSON body
  {up_to_id} (+ its 422); a missing body keeps the old behaviour.
- nudge preview (#416) adds optional `weekday` query + doc wording.
After rebase on main a9ae82cc8: main's own drift since its 094966d87 golden =
help bot routes POST /admin/assistant/draft + GET /admin/assistant/do-caps; inspected, intentional.
Golden refresh (2026-11-11): rwl W28-relay-infra on main 6c68e13ed: only the tracking-link
verify doc adds "429 + Retry-After" (verify throttle); inspected, intentional.
Golden refresh (2026-11-12): merge main 6083d918e into feat/redirect-links-stats: OpenAPI diff
merged-vs-main == base-vs-branch exactly (tracking-links /summary + /{id}/analytics?days, verify body ref);
inspected, intentional.
Golden refresh (2026-11-12): merge main 78eaf88bc into feat/redirect-links-stats: same check, OpenAPI diff
merged-vs-main == base-vs-branch exactly; inspected, intentional.
Golden refresh (2026-11-11, bio admin API): adds the 15 /admin/bio-pages* rows right after the
link-share rows (bio_pages/admin.py); no existing row moves. The base's OpenAPI sha already
mismatched the golden before this change (88bfcd7a… vs 8b932eca…); the new sha includes both.
Golden refresh (2026-11-12): merge feat/bio-pages-port (main 6083d918e + redirect-link stats) into
feat/bio-admin-api: OpenAPI diff merged-vs-bio-pages-port == base-vs-bio-admin-api exactly; inspected.
Golden refresh (2026-11-12): merge feat/bio-pages-port (main 78eaf88bc) into feat/bio-admin-api: same check;
inspected.
Golden refresh (2026-11-12): do-mode mass_edit (spec D11) adds POST /admin/assistant/edit/apply
(assistant_draft.edit_apply); inspected, intentional.
Golden refresh (2026-11-12): merge main 130d15eb4 into ship/fetch-diet-p3 (4421feb87): routes == main's golden
(main adds bio-pages/tracking-stats rows); OpenAPI diff merged-vs-main == base(6d6f8a61d)-vs-P3 exactly
(measured, 18 leaves): P3's four GET edits (vault/lists + vault/media revalidate params, pinned + wall-media
descriptions); inspected, intentional.
Golden refresh (2026-11-12): merge main 46223e71c into p3-final (f5e594c3d): routes == main's golden (611);
OpenAPI diff merged-vs-main == base(6d6f8a61d)-vs-P3(4421feb87) exactly (measured, 18 leaves); inspected.
Golden refresh (2026-11-12, bio vault avatar): adds POST /admin/bio-pages/{pid}/avatar/vault
(bio_pages/admin.avatar_from_vault) after the avatar upload row; no existing row moves; inspected, intentional.
Golden refresh (2026-11-12, bio vault background): adds POST /admin/bio-pages/{pid}/links/{lid}/background/vault
(bio_pages/admin.background_from_vault) after the background upload row; no existing row moves; inspected, intentional.
Golden refresh (2026-11-13, Full AI Chatter page): adds GET /admin/full-ai/today (full_ai_api.full_ai_today)
after the bio-pages rows; no existing row moves; inspected, intentional. After merging main 98b6c5341
(sha green there at 1dfb85f1…) the sha is refreshed to include this route.

Golden refresh (2026-11-13, ultra report recipe): adds POST /admin/reports/run and GET /admin/reports/catalogue
(report_recipe_api); no existing row moves; inspected, intentional.

Golden refresh (2026-11-14, ultra owner tokens): adds GET/POST /admin/owner-tokens and DELETE
/admin/owner-tokens/{token_id} (owner_tokens_api) after the tenant llm-keys rows; OpenAPI diff = those three
paths + schema OwnerTokenCreateBody only (measured: sha1 with them removed == the prior golden); no row moves.

Golden refresh (2026-11-14, ultra toolbox report_file): adds POST /admin/reports/files and GET
/admin/reports/files/{file_id} (report_recipe_api) after the report catalogue row; OpenAPI diff = those two paths +
schema FileBody only (measured: sha1 with them removed == the prior golden); no row moves.

Golden refresh (2026-11-14, ultra MCP server): adds POST /admin/mcp and DELETE,GET /admin/mcp (mcp_api) after
the owner-tokens rows; include_in_schema=False, so the OpenAPI sha1 is unchanged (measured); no row moves.

Golden refresh (2026-11-14, Full AI checkpoint JSON): adds PUT /admin/full-ai/config/checkpoint
(full_ai_api.full_ai_config_put_checkpoint) after the draft PUT row; OpenAPI diff = that path + schema
ConfigCheckpointBody; no existing row moves; inspected, intentional.

Golden refresh (2026-11-14, merge main 713774458 into ultra step 2): main's golden (Full AI routes) plus this
branch's seven rows above, regenerated; diff vs main's golden = those rows + the sha only.

Golden refresh (2026-11-14, Full AI Prepare content): adds POST /admin/full-ai/prepare-content and GET
/admin/full-ai/prepare-content/status (full_ai_api) after the full-ai today row; no existing row moves; inspected,
intentional. Diff vs main's golden (a340051a9) = those two rows + the sha.

Golden refresh (2026-11-14, full-ai 03a ticket 32): adds POST /admin/full-ai/test/turn and GET
/admin/full-ai/test/session (full_ai_api, Test chat) after the Full AI rows; diff = those two rows + the sha.

Golden refresh (2026-11-14, full-ai 03a ticket 37 + 03c ticket 52): adds POST /admin/full-ai/persona/draft and
the four config routes (GET /admin/full-ai/config, PUT …/config/draft, POST …/config/save, POST …/config/rollback)
at the end of the Full AI rows; diff = those rows + the sha.

Golden refresh (2026-11-14, ultra step 4 plans): adds GET /admin/ultra/plans/{plan_id} and POST .../ok, .../cancel
(ultra_api) after the /admin/mcp rows; OpenAPI diff = those paths + schema OkBody only (measured: sha1 with them
removed == the prior golden); no row moves.

Golden refresh (2026-11-14, ultra step 4 R2): _MassScheduleBody gains `require_recipients` (POST
/api/of/v2/messages/queue[/later]); OpenAPI diff = that one schema field (measured: the sha matches the prior
golden without it); no row moves.

Golden refresh (2026-11-14, full-ai 03b ticket 44): adds POST /admin/full-ai/test/settle (full_ai_api, fake
Buy/Decline in the Test chat) after the Test chat rows; diff = that one row + the sha.

Golden refresh (2026-11-14, full-ai 03b ticket 49): adds GET /admin/vault-ai/internal-folders (vault_ai_api,
the Content folders picker) among the vault-ai rows; diff vs main's golden = that one row + the sha.

Golden refresh (2026-11-14, ultra step 5 rwl5 m7): the page backdrop routes /admin/bio-pages/{pid}/background(/vault)
get their own names (upload_page_background, page_background_from_vault, remove_page_background; the link routes
keep theirs); diff = those three names + the sha; inspected, intentional.

Golden refresh (2026-11-14, full-ai folder prices): adds GET + POST /admin/vault-ai/folder-prices (vault_ai_api,
an agency's price per vault folder) right after /admin/vault-ai/internal-folders; diff = those two rows + the sha.

Golden refresh (2026-11-15, fetch-diet P1a onto main 774d6d410): adds POST /admin/view-lease (accounts_admin_api,
the View lease renewal) after the roster-counts row; diff vs main's golden = that one row + the sha.

Golden refresh (2026-11-14, Inflowwww folders editor): the internal-folders routes move to vault_internal_folders,
included from vault_ai_api where the GET stood, so GET /admin/vault-ai/internal-folders keeps its row and its name
list_internal_folders; adds right after it POST /admin/vault-ai/internal-folders (create_internal_folder), POST
…/{folder_id}/rename, DELETE …/{folder_id}, POST …/{folder_id}/add, …/remove, …/reorder; no existing row moves.
OpenAPI diff = those six operations + the GET's description (measured: sha1 with them removed and the old GET
docstring restored == the prior golden).

Golden refresh (2026-11-15, wiring routes left out): routes added by `*_wiring.py`
leave the route list and the OpenAPI sha1; one module's router moved from server.py to its wiring module.
Measured: the full route set is unchanged (670) and every route's first match is the same as before; the
golden diff = the left-out rows + the sha.

Golden refresh (2026-11-15, main 72e46c075): sha only, no route row changes. Measured OpenAPI diff
698ac80d7 -> 72e46c075: #733 adds optional `pair` to schema TestPhoto (full_ai_api test photo
body); #731 rewords GET /admin/saved-replies/overview's description. Nothing else; inspected,
intentional.

Golden refresh (2026-11-15, Full AI ticket 74): adds GET + PUT /admin/full-ai/mode (full_ai_api, the Mode
control); full_ai_api's module docstring changed too; no existing row moves; diff = those two rows + the sha.

Golden refresh (2026-11-15, OnlyFans consent switch shared): its GET + PUT move out of an optional wiring
module's router to of_consent_api as /admin/of-consent/{account_id} (get_of_consent, put_of_consent), included
right after /admin/account-config; no existing row moves; diff = those two rows + the sha (the wiring golden
loses its two consent rows).

Golden refresh (2026-11-15, fetch-diet review H1): POST /admin/view-lease description only (lease gains paced,
selection min age); no route row changes; diff = the sha.
Golden refresh (2026-11-15, fetch-diet review H3): the same description names `purchase_poll.poll_now` (the poll
scheduler moved out of transaction_ingest); no route row changes; diff = the sha.
Golden refresh (2026-11-15, fetch-diet review rwl2 F2/F3): the same description: the selection floor counts any
poll start, gains go through app_open_warm's one per-exit gate (`note_read`); no route row changes; diff = the sha
(measured: HEAD's accounts_admin_api.py with every other change of this fix == the prior golden).
Golden refresh (2026-11-17, Full AI offer details): Test Chat's turn body gains optional `reply_to_n`
(full_ai_api.TestTurn, the reply mark); no route row changes; diff = the sha.
Golden refresh (2026-11-19, promo preempt 09/11): POST /admin/promotions and POST /api/of/v2/promotions
bodies gain optional `resolve_open` ("create anyway"); the raw create/finish docstrings change; no route
row changes; diff = the sha.
Golden refresh (2026-11-19, promo preempt 14/15): POST /admin/promotions' body gains optional `recreate_limit`
and `expect_taken_from`, PATCH /admin/promotions/{id}'s gains `recreate_limit` (its schema description reworded);
no route row changes; diff = the sha (measured: sha1 with those three fields removed and the old PatchBody
description restored == the prior golden).
Golden refresh (2026-11-19, promo preempt 21): POST /admin/promotions' body gains optional `preempt`; PATCH
/admin/promotions/{id}'s gains `preempt`, `auto_reactivate` turns optional, its description reworded; no route
row changes; diff = the sha (HEAD's tree green on the prior golden, measured).
Golden refresh (2026-11-19, Money rail one read per Creator): adds GET /api/of/v2/users/notifications/money
(of_notifications_money) right after /users/notifications/count; no existing row moves; diff = that row + the sha.
Golden refresh (2026-11-21, ofm-not-yet ticket 63): adds DELETE /api/of/v2/sessions (of_close_all_sessions) right after
PATCH /users/settings/story; GET /sessions' description names it; no existing row moves; diff = that row + the sha
(measured: dropping the row and the old description reproduces the prior sha).
Golden refresh (2026-11-21, ofm-not-yet ticket 61): GET /api/of/v2/campaigns gains optional `field` and `sort`
query params (the tracking links Sort); no route row changes; diff = the sha. Merged with ticket 63 (lane p3): both changes, new sha.
Golden refresh (2026-11-21, ofm-not-yet ticket 74): adds GET, POST and DELETE /api/of/v2/campaigns/share-access
(the tracking links "Shared with you" tab and share hint) right after POST /campaigns, before DELETE
/campaigns/{campaign_id}; no existing row moves; diff = those three rows + the sha.
Golden refresh (2026-11-21, ofm-not-yet ticket 66): adds GET /api/of/v2/countries and PUT
/api/of/v2/users/me/settings/security/blocked-countries and .../blocked-ips (Block by country and Block by IP, under
account-lockout) right after DELETE /sessions; no existing row moves; diff = those three rows + the sha.
Golden refresh (2026-11-21, ofm-not-yet ticket 67): adds POST /api/of/v2/users/me/profile-image
(of_upload_profile_image, Edit profile's cover/avatar upload); no existing row moves; diff = that row + the sha.
Golden refresh (2026-11-21, ofm-not-yet ticket 69): adds PUT /api/of/v2/users/social/buttons (of_add_social_button) and
DELETE /api/of/v2/users/social/buttons/{button_id} (of_delete_social_button) right after DELETE /sessions, and GET
/api/of/v2/users/social/buttons (of_social_buttons) right after GET /sessions; no existing row moves; diff = those rows +
the sha.
Golden refresh (2026-11-21, ofm-not-yet ticket 70): adds GET /api/of/v2/users/links (of_users_links) right after GET
/users/settings/story (ahead of the /users/{user_id_or_username} lookup), and PUT /api/of/v2/users/links
(of_add_users_link) and DELETE /api/of/v2/users/links/{link_id} (of_delete_users_link) right after the social buttons'
DELETE; no existing row moves; diff = those rows + the sha.
Golden refresh (2026-11-21, ofm-not-yet ticket 73): adds POST /api/of/v2/streams/users/{username}/block
(of_block_stream_viewer) and DELETE /api/of/v2/streams/users/{user_id}/block (of_unblock_stream_viewer) right after
DELETE /sessions; GET /streams/users/blocked's description names them; no existing row moves; diff = those rows + the sha.
Golden refresh (2026-11-21, ofm-not-yet ticket 76): adds DELETE /api/of/v2/streams/obs/key (of_reset_stream_key)
right after DELETE /sessions, before ticket 73's rows; no existing row moves; diff = that row + the sha.
Golden refresh (2026-11-21, ofm-69f social providers): adds GET /api/of/v2/init (of_init, init's socialMediaProviders
only) right after GET /users/social/buttons; PUT /users/social/buttons' description names the link-or-username rule; no
existing row moves; diff = that row + the sha.
Golden refresh (2026-11-21, lane p3 merge of tickets 74, 75, 66 to 70, 72, 73, 76, 71): every ticket's rows, none moved;
each later ticket's rows sit after the earlier one's (66's blocked-countries/blocked-ips, then 69's, 70's, 76's, 73's,
where each alone sat right after DELETE /sessions); new sha.
Golden refresh (2026-11-21, ofm-not-yet ticket 24): GET /api/of/v2/payouts/stats (of_earning_stats) gains optional
`startDate`/`endDate` queries (OF's own names, sent on as they are); no route row changes; diff = the sha (measured: HEAD's
server.py == the prior golden).
Golden refresh (2026-11-21, ofm-70f): GET /api/of/v2/users/links' description names OF's real item shape ({id, sort,
url, title, ...}, measured live); no route row changes; diff = the sha (measured: HEAD's server.py == the prior golden).
Golden refresh (2026-11-20): one wired golden only: optional query params and body fields (caption language,
kind / language narrowing, per-row tags); docstrings reworded. No route row changes; diff = the sha.
Golden refresh (2026-11-21, OFM_NEW_WRITES_ENABLED switch): adds GET /api/of/ofm-writes (of_ofm_writes_probe) right
before POST /campaigns/share-access; the 13 gated writes take a no-param dependency (no schema change); no existing row
moves; diff = that row + the sha.
Golden refresh (2026-11-21, OFM_NEW_WRITES_ENABLED per Creator): adds GET and PUT /admin/ofm-writes/{account_id}
(get_ofm_writes_creator, put_ofm_writes_creator: a Creator's force-off, Settings › OF Manager writes) right after GET
/api/of/ofm-writes; no existing row moves; diff = those two rows + the sha.

Run: ./venv/bin/python service/tests/test_route_order.py   (exit 0 = green)
Golden refresh (2026-11-20, main c0f0ef88a): adds POST /admin/unconfirmed-sends/dismiss (#882) and
POST /api/of/v2/users/notifications/read (#866); no existing row moves. OpenAPI sha also carries this week's
doc/param edits (#870-#882); route list diff inspected, intentional.
Golden refresh (2026-11-20, recheck fixes): no route added or moved; OpenAPI sha only: dismiss body gains
optional `since`, /admin/perflog/recent + dismiss docstrings; inspected, intentional.
Golden refresh (2026-11-20, All Models open cost): GET /api/of/v2/users/me gains optional `max_age` and a
docstring; no route row changes; diff = the sha.
Golden refresh (2026-11-21, script fill 1a Describe target): GET /admin/vault-ai/describe-all/plan gains optional
`target` and its docstring; no route row changes; diff = the sha (HEAD's tree green on the prior golden, measured).
Golden refresh (2026-11-20, watched-creator-refresher 04): schema FlatAccountDTO (GET /chatter/me/accounts) gains
optional `freshness` (absent unless SHARED_REFRESHER=1); no route row changes; diff = the sha (measured: sha1 with
that field removed == the prior golden).
Golden refresh (2026-11-21, script fill 1b Fill routes): adds POST /admin/saved-replies/fill/plan, /fill/apply and
/fill/undo (script_fill_api) after the bulk-import row; no existing row moves (measured: sha1 with those three
routes removed == the prior golden).
Golden refresh (2026-11-21, merge main into spec/ofm-not-yet): main's golden plus this branch's ofm-not-yet rows
above, regenerated with --write-golden; diff vs main's golden = those rows + the sha.
Golden refresh (2026-11-21, ofm-not-yet rwl r1 #5): PATCH /api/of/v2/users/me's docstring (switch off: `about` as
main sent it); no route row changes; diff = the sha (measured: the old docstring == the prior golden).
Golden refresh (2026-11-22, ofm-not-yet follow-up #7): GET and PUT /admin/ofm-writes/{account_id} move from
server.py to ofm_writes_api's router (included right after of_consent_api's), so their two rows move from after GET
/api/of/ofm-writes to after the of-consent rows; no path shares their prefix; no other row moves; diff = those two
rows, the sha unchanged (measured).
Golden refresh (2026-11-21, Keep running indefinite): schema _PatchBody (PATCH /admin/promotions/{id}) docstring
says the Re-create limit is optional; no route row changes; diff = the sha (measured: the old promotions_api.py
passes the prior golden).
Golden refresh (2026-11-21, merge main into spec/ofm-not-yet again): both refreshes above; regenerated with
--write-golden.
Golden refresh (2026-11-22, ofm-not-yet follow-up): PUT /admin/ofm-writes/{account_id} docstring names every
principal; no route row changes; diff = the sha.
Golden refresh (2026-11-22, rwl W30): one wired module's sha only; OpenAPI diff = one word in a request
body's description, measured; no row moves.
Golden refresh (2026-11-22, rwl W30 vault download): GET /admin/vault-ai/download/resign's docstring adds the
no-`u` / `_u_ok` sentence (cac96823c); no route row changes; re-pinned after rebase on main
(measured: OpenAPI diff vs 539ef7c15 is exactly that description).
Golden refresh (2026-11-22, rwl W30 full-ai-page #6): GET /admin/full-ai/rules' mode enum drops "shadow"
(test | live) and its docstring line says so; no route row changes; diff = the sha.
Golden refresh (2026-11-22, rwl W30 vault-ai-folders): descriptions only (route docstrings in vault_of_folders /
vault_ai_api); no route row changes; diff = the sha. Round 2: /admin/vault-ai/items docstring (not_nude rule).
Golden refresh (2026-11-22, rwl W30 help-bot F1): GET do-caps docstring names every do-mode flow's opt-in
(`can_do`) (690bd1e63); no route row changes; diff = the sha (measured: OpenAPI diff vs 84f8471ff is exactly that
description).
Golden refresh (2026-11-22, rwl W30 smart-messages F30): RetryBody gains required `since` (DismissBody now
inherits it) + the unconfirmed-sends module docstring; no route row changes; diff = the sha.
Golden refresh (2026-11-22, W30-mu #1, re-pinned after rebase on main 53aeb4a9a): POST /api/of/v2/chats/mark-as-read
and POST /api/of/v2/chats/{chat_id}/mark-as-read docstrings say the local unread clears only once the platform took
the write (else 502); no route row changes (measured: OpenAPI diff vs e0ac52fdb is exactly those two descriptions).
Golden refresh (2026-11-22, rwl W30 dashboard-stats F4/F8): GET /admin/stats/fan-report's docstring (growth: a
Creator with OF days has its rows on UTC days) and GET /admin/stats/chatting-stats' (`chatter_ids`); no route row
changes; diff = the sha re-pinned after rebase on main.
Golden refresh (2026-11-22, rwl W30 promos F3): PATCH /admin/promotions/{id} body (_PatchBody) description says
an omitted Re-create limit keeps a Kept campaign's; no route row changes; diff = the sha (measured: OpenAPI diff
vs main's promotions_api is exactly that description).
Golden refresh (2026-11-22, rwl W30 settings-theme F2): GET + DELETE /admin/errors docstrings name
`_errors_where` (was `_errors_scope`); no route row changes; diff = the sha (re-pinned after rebase on #958).
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB before any db import

import difflib  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

# The golden is the harness-env route set. FLEET_SECRET (>=32 chars) mounts
# /auth/fleet/whois (server.py `if fleet_api.enabled()`); the only env-gated
# route registration. Set empty (not popped) before `import server`: db/engine's
# load_dotenv(override=False) would refill a popped key from service/.env.
os.environ["FLEET_SECRET"] = ""

import server  # noqa: E402 — registers routers + middleware
from fastapi import FastAPI  # noqa: E402

import relay_hooks  # noqa: E402

GOLDEN = Path(__file__).with_name("test_route_order.golden.json")
WRITE = "--write-golden" in sys.argv
WANT = None if WRITE else json.loads(GOLDEN.read_text())


def _wired() -> dict[str, list]:
    """{wiring module: the server.app routes it added}, by endpoint: what its
    `wire` binds on a probe app."""
    out = {}
    for mod in relay_hooks.import_wirings():
        probe = FastAPI()
        mod.wire(probe)
        ends = {getattr(r, "endpoint", None) for r in probe.router.routes} - {None}
        added = [r for r in server.app.routes if getattr(r, "endpoint", None) in ends]
        if added:
            out[mod.__name__] = added
    return out


WIRED = _wired()
_WIRED_IDS = {id(r) for added in WIRED.values() for r in added}


def _shared_routes() -> list:
    return [r for r in server.app.routes if id(r) not in _WIRED_IDS]


def _routes(routes: list) -> list:
    out = []
    for r in routes:
        methods = sorted(getattr(r, "methods", None) or [])
        endpoint = getattr(r, "endpoint", None)
        name = getattr(endpoint, "__name__", None) or type(r).__name__
        out.append([",".join(methods), r.path, name])
    return out


def _openapi_sha1(routes: list) -> str:
    app = server.app
    saved = app.router.routes
    app.router.routes, app.openapi_schema = routes, None
    try:
        spec = json.dumps(app.openapi(), sort_keys=True).encode()
    finally:
        app.router.routes, app.openapi_schema = saved, None
    return hashlib.sha1(spec).hexdigest()


def _golden(routes: list) -> str:
    rows = ",\n  ".join(json.dumps(r) for r in _routes(routes))
    return f'{{"openapi_sha1": "{_openapi_sha1(routes)}",\n "routes": [\n  {rows}\n]}}\n'


def _wired_golden(name: str) -> Path:
    return GOLDEN.with_name(f"test_route_order.{name}.golden.json")


def _check_rows(want: dict, routes: list, label: str) -> None:
    got_rows = [json.dumps(r) for r in _routes(routes)]
    want_rows = [json.dumps(r) for r in want["routes"]]
    if got_rows != want_rows:
        diff = "\n".join(difflib.unified_diff(want_rows, got_rows, "golden", label, lineterm=""))
        raise AssertionError(f"route order changed:\n{diff}")


def case_route_order_matches_golden():
    _check_rows(WANT, _shared_routes(), "server.app.routes")


def case_openapi_sha1_matches_golden():
    got, want = _openapi_sha1(_shared_routes()), WANT["openapi_sha1"]
    assert got == want, f"app.openapi() changed: sha1 {got} != golden {want}"


def case_wired_routes_match_their_goldens():
    """Each present wiring module that adds routes has its own golden."""
    for name, routes in WIRED.items():
        path = _wired_golden(name)
        assert path.exists(), f"{name} adds routes but {path.name} is missing (--write-golden)"
        want = json.loads(path.read_text())
        _check_rows(want, routes, name)
        got = _openapi_sha1(routes)
        assert got == want["openapi_sha1"], f"{name} openapi changed: sha1 {got} != golden {want['openapi_sha1']}"


if __name__ == "__main__" and WRITE:
    GOLDEN.write_text(_golden(_shared_routes()))
    print(f"wrote {GOLDEN}")
    for name, routes in WIRED.items():
        _wired_golden(name).write_text(_golden(routes))
        print(f"wrote {_wired_golden(name)}")
    sys.exit(0)

_harness.run()
