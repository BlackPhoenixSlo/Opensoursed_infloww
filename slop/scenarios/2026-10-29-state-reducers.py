"""The six state reducers of 2026-10-29 (docs/reducer-scan.md Tier 1, plus Tier 2's Auto-reply form, the vault
rail and premade rows) and
the shared audience reducer (app/components/audience/audienceReducer.ts) on the real UI: one plain owner,
one browser (1440x900; sections 6-8 in the master's own context), `agency_inbox` (Creators and fans per
Creator by SQL from `--scale`: 3 x 50 small, 10 x 500 medium), the relay's own routes on the slop temp DB,
OnlyFans at its wire (`OF_WIRE`: lib/of_wire.py, each Creator with a captured session, so the
relay's real `OFClient` sends the mass messages and posts). The UI sections are a layout flow (written
for small's 3 Creators); the Mass all-models fan-out is also a volume one (21, also under `--no-ui`):
`--scale` sets its Creators, `--users` its concurrent operators, with a latency budget
(`MASS_FANOUT_P95_MS`).

Seeded: two saved replies and one Smart List ("slop whales", no rules) per Creator through the
real `POST /admin/saved-replies` (PAID: $25, text locked; FREE: no price) and
`POST /admin/smart-lists`, each Creator's OF session file (seed/of_sessions), and Creator 0's
vault mirror by SQL (`vault_items`, as a collect plus `vault_dupes.ensure_hashes` write them: a
set of 3 byte-identical copies, a set of 2 whose hashes are 3 bits apart, 2 loners); Creator 2's the same way (one
set of 252 byte-identical items: 251 copies). Each seeded mirror gets the finished `vault_cache_runs` row a manual
Collect leaves (`_seed_collect_run`): `cache/summary` answers `complete` true, so the picker lists from the mirror
(since 96d1aa972 a mirror without a finished walk lists live, and OF is held at the browser's wire here). Every Creator's OF tracking links on OF's wire (`FakeOF.campaigns`,
lib/of_wire.py) with their Source through the real `PUT /admin/link-meta/batch`; Creator 0's
auto-follow record by SQL (`follow_ping_state`, one row per fan, as `auto_follow.stamp_ping` writes it). Clock records: time tracking on (real `PUT /admin/settings/time-tracking`),
one Employee (real `POST /admin/employees`) and its one closed Clock event by SQL (3 h to 2 h ago, a manual
clock-out on Creator 0, as `/clock-in` + `/clock-out` would leave it).

1. Mass message (Smart Messages > New Message > OF mass message): Broadcast disabled with its reason
   as its title while the text is empty and while the price is $2 (if it is enabled on either, it is
   clicked: no queue POST may leave the browser); then PAID template, a GIF picked, FREE template ->
   the price box empty and the lock gone, the GIF chip still there (a GIF-less template keeps the pick),
   and a $5 typed after it shows the lock unticked; the text retyped, the valid draft ($5, locked) POSTs
   one `/api/of/v2/messages/queue` body with its text, price, lock, the GIF (`giphy_id`) and the default
   audience, the relay answers 200, OF's wire gets one `POST /api2/v2/messages/queue` with them
   (`giphyId`), and a `mass_runs` row holds OF's queue id. Then a
   new draft: "All fans" turned off and the Smart List picked, all models on -> both chips back
   to included; off -> the Smart List unpicked; all models on again and Broadcast -> OF's wire
   gets one mass message per included model, `userLists` fans + following, no `userIds`.
   Screenshots mass-gif-picked, mass-free-template-trigger, mass-free-template-settled, mass-broadcast-sent,
   mass-all-models-reset, mass-all-models-sent.
1b. Mass all-models partial failure (compose/fanOut.ts via MassMessageComposer): a new draft, all models
   on, Creator 1's OF mass queue armed to answer 500 at OF's wire (`FakeOF.fail`), Broadcast -> the relay
   answers 502 for it and 200 for the rest, the modal stays with "N-1/N succeeded", the text box and the
   ALL-models box are disabled and Start over is offered (content locked); the fault cleared, the retry
   Broadcast -> exactly one more queue POST, for Creator 1, with the original text, OF's wire ends with
   one such mass message per Creator, the modal closes. Had the box been enabled, an edit is typed before
   the retry (the operator's edit the lock exists to stop). Screenshots mass-partial-trigger,
   mass-partial-failure, mass-retry-done; bodies in mass-retry-bodies.json.
1c. Mass messages tab bulk unsend (Smart Messages > Mass Messages, `?tab=mass`; components/settings/
   massUnsendRules.ts `bulkTargets`): Creators 0 and 1's cached broadcasts by SQL (seed/mass_broadcast_cache.py,
   as `upsert_many` writes OF's feed: free text, GIF-only, image, paid text, each 5-9 h old; fresh ones (1 h, and
   3 h: under the 4 h gate, an hour's margin for a slow run); an already unsent one; one OF says can no longer
   be unsent; x3 at small, x8 above), Creator 0's model chip on, "Unsend free text >4h" (its count the expected rows'),
   confirm() accepted -> the browser's DELETEs, the relay's answers (200), OF's wire unsends (one per expected
   row, no other) and the cache's `is_canceled` flips are exactly Creator 0's free, image-less, >= 4 h,
   unsendable rows; every other row (Creator 1's matching ones included) unchanged. Screenshots
   mass-bulk-unsend-trigger, mass-bulk-unsend-settled; the id sets in mass-bulk-unsend.json.
2. Post (Messages dashboard > My feed > New post): a typed $10 on a text-only post is refused
   ("A paid post needs at least one image"); "Post from ALL models" hides the price row (all-models
   is text-only), Post is on, and each model's `POST /api/of/v2/posts` is free and text-only and
   reaches OF's wire (`POST /api2/v2/posts`) free with the text. The second Creator's POST is
   answered 500: the modal stays open with "N-1/N succeeded", the text box and the ALL-models box
   disabled (an edit is typed only if not), and the retry Post re-posts that Creator only with the
   original text (on to OF's wire), then closes. Screenshots post-priced-trigger,
   post-all-models, post-partial-failure, post-retry-done.
3. Vault duplicates (Vault Pro > extras > Duplicates): "Remove 2 copies…" then strictness 4 ->
   "Yes, remove them" is gone and the new scan's Remove button is back; then "Remove 3 copies…"
   (when it is there) and "Yes, remove them" -> exactly one hide POST, none before it, whose
   media_ids are the ids ticked on screen at confirm and whose threshold is the one on screen (4).
   Screenshots dupes-confirming, dupes-threshold-changed, dupes-yes-armed, dupes-removed.
3b. Vault duplicates, partial failure: Creator 2's one set of 251 copies (`HIDE_BATCH` 250 + 1), all removed in
   one confirm: the first hide batch (250 ids) is answered 200, the second (1 id) 500 -> the done panel reads
   "Removed 250 of 251, then failed: <the relay's detail>", with no error line of its own. Screenshot
   dupes-partial-failed.
4. /group: three group tabs (8 fans, the cap; 1 fan; 5 fans) and a fourth same-origin page (the
   static /icon.svg, no app code, so next dev's Fast Refresh never reloads it) sending `add` over the
   app's BroadcastChannel as a source tab does: every ack says ok exactly when the fan is in the target tab's
   registry after it (full refuses, room lands, a held fan sent as a string id is taken without a
   duplicate); a Fansly-style string id (past 2^53) lands and survives a reload of its tab as the
   same string; a burst of 6 adds posted in one task into the 5-fan tab (room for 3, one a held fan
   as a string) gets acks that exactly match its registry. Every ack's round trip (post -> ack, in
   the sender's page) is measured; budget max <= 150 ms against the sender's 400 ms timeout.
   Screenshots group-tab-b, group-tab-b-reloaded, group-burst-trigger, group-burst-settled.
5. Nudge (Smart Messages > New Message > Nudge): Delay edited, Save, and while the PUT is in
   flight Jitter edited; the save's own config refetch lands and Jitter keeps the edit; a second
   Save stores both (route and `account_ai_config` row). Then Delay edited again, Save, and while
   that PUT is in flight the editor switches to another Creator: when it lands there is no
   "Saved" on that Creator, and back on the first the form shows the saved Delay (the save
   refreshed the account it wrote). Then Save there lands ("Saved") and the editor switches to a
   third Creator whose config GET fails: no "Saved" under it (the picker resets the verdict, not
   the config's arrival). Screenshots nudge-edit-during-save, nudge-after-refetch,
   nudge-switch-landed, nudge-switch-back, nudge-stale-saved.
6. /admin/manage (6-8 as the master, the second Agency's owner, in a context of its own; the run's
   owner is a plain owner everywhere else): the key-status roster loads EMPTY -> "Only agencies with a live model session"
   shows "(0 of N)", not "(N of N)". Screenshot admin-live-only-empty.
6b. Smart list editor (app/components/growth/smartListEditorState.ts; Growth > Smart lists > Create list):
   Preview count, then a rule value edit -> the count is gone; a `between` with one bound, then
   upper < lower -> Save and Preview count disabled with the reason, no POST, GET /admin/smart-lists
   and the smart_lists rows unchanged; the bounds filled -> Save POSTs once, the list is in the
   route and its row holds the bounds in cents. Screenshots smartlist-previewed (the trigger),
   smartlist-edit-drops-preview, smartlist-between-one-bound, smartlist-between-inverted,
   smartlist-between-saved.
7. /admin/manage, the roster call FAILS (403): every row stays, the error line says "Key status
   unavailable", and live-only checked reads "(key status unavailable — filter off)", never
   "(N of N)". Screenshots admin-roster-failed-trigger (loaded, box not yet checked),
   admin-roster-failed-settled.
8. /admin/manage, the FIRST /admin/users load FAILS (502, held until the trigger shot): the skeleton
   is drawn while it is in flight; once it fails its error shows, no skeleton is left, no "No users
   registered yet.", Refresh is usable. Screenshots admin-users-failed-trigger (loading),
   admin-users-failed-settled.
8b. /admin/manage opened by URL in the run's own browser as the run's owner (not the master): exactly
   one "master account required" line, no rows, no alert, and the browser fires no /admin/users or
   /admin/users/llm-key-status request (both are master-only on the relay). Screenshots admin-gate-trigger,
   admin-gate-settled.
9. Auto-reply (My Automations > Auto-reply, `?creator=` Creator 0, its blob first PUT through the real
   route with quiet hours and max_nudges): every field edited (header switch, delay, randomise, a
   folder, the folder cap, new fans, its window and cap, both photo options, a Human style box),
   Save, reload: the form shows each edit, and GET /admin/autoreply-config + /admin/style-config
   hold them with the other knobs kept (autoreply-get.json). Screenshots autoreply-edited-trigger,
   autoreply-reloaded-settled. Then Delay typed while the settings PUT (of another Delay) is held: once that
   save settled (its response, the GET its onSuccess refetches, Save enabled again: slop/lib/hold.py) the field keeps the edit
   and "Saved" is off (the Save row reads Save, enabled, no note beside it; after the next Save the same probe reads
   "Saved"); the next Save shows it and stores the Delay. Screenshots autoreply-delay-during-save,
   autoreply-delay-after-save. Then a box (Human style) toggled while another's style PUT is held stays
   toggled once that save settled (a wipe would be its onSuccess, `dropSaved`), "Saved" stays off, and the
   next Save PUTs and stores it. Screenshots autoreply-style-during-save, autoreply-style-landed,
   autoreply-style-after-save.
9b. Get to know fans (My AI Chatter > Get to know fans, `?creator=` Creator 0). First on a 390x844 phone, dark:
   no rule, the Automation card's switch off -> the settings show the catalog defaults; cutoff, caption and price
   typed, Save -> one POST /admin/automation-rules with is_enabled false, no switch call, the DB row parked with
   them; switch on then off -> the same row on, then off, the values kept on screen and stored. Screenshots
   gtkf-off-no-rule, gtkf-off-saved, gtkf-on-off-kept. Then (desktop) the switch wakes that rule: cutoff typed,
   Save, and while its rule PATCH is held the cutoff, the closing caption and the price typed; once that save
   settled the fields keep them and "Saved" is off; the next Save
   shows it and GET /admin/automation-rules holds them (price in cents). Screenshots gtkf-edit-during-save,
   gtkf-after-save, gtkf-resaved.
10. Priority mass (Smart Messages > New Message > Priority mass message): 'Post as' Creator 1,
   include and exclude its lists (Creator 1's "massdmexclude " pre-ticked), then 'Post as' Creator 0,
   include VIP, exclude Whales, Send -> the POST (parsed) carries fans + following + VIP and excludes
   Creator 0's pre-ticked MASSDMEXCLUDE (9103) and Whales only (no Creator 1 id), and its run row's audience is those lists. Screenshots audience-pm-switch-trigger,
   audience-pm-switch-settled, audience-pm-sent; bodies in audience-pm-bodies.json.
11. Auto Funnel, Creator 0, Start: "Start funnel" disabled while OF's lists are held, then
   MASSDMEXCLUDE pre-ticked in Exclude, All fans in Send to, no built-in in Exclude, and Start
   enabled; include VIP, then the creator column picks Creator 1 with the panel open:
   the audience resets (All fans only) and its "massdmexclude " list is pre-ticked; include and
   exclude one list each, Start funnel -> the queue POST (parsed) carries only Creator 1's lists.
   Chip state is read off aria-pressed. Screenshots audience-fl-trigger, audience-fl-switch-settled,
   audience-fl-sent; bodies in audience-fl-bodies.json.
11b. Funnel media (FunnelMediaPane + funnelMediaReducer), Auto Funnel, Creator 0: the first funnel's Media,
   the opener's Pick media, vault tile 9020, Attach, Save media -> "Saved for <Creator>" and
   GET /admin/funnels/{id}/media/{account} holds opening_media_ids [9020]. Screenshot funnel-media-saved;
   the GET in funnel-media.json.
12. Tracking links (app/components/growth/pagedFilters.ts via LinksListFrame's useFrameFilters): 140 links
   per Creator (120 active = 3 pages of 50, 20 deactivated), Source IG on every other active one. On page 3
   a Source pick, then (back on page 3) "Show deactivated links", each leave the pager on page 1 with the
   filtered set's first 50 rows. The list is paged in the browser (one read returns every link), so no
   request carries a page: the requests the change fired are recorded (frame-steps.json) and none may
   carry page/offset. Screenshots frame-page3-trigger, frame-source-page1, frame-page3-before-deactivated,
   frame-deactivated-page1.
13. Auto-follow details (server paged, limit 20 / offset): Creator 0's 50 followed fans. From page 3
   (offset=40) a "Total spend" header click and a Start date each send the next
   /admin/auto-follow/records with offset=0 (and the asked sort / start), answered 200 with page 1 as the
   temp DB orders it; Reset lands on a key the page already read, so React Query may serve it from cache
   with no request: it must show page 1 (pager, and the table's fan ids = the DB's) either way
   (autofollow-steps.json). Screenshots autofollow-page3-trigger, autofollow-sort-page1,
   autofollow-range-page1, autofollow-reset-page1.
14. Clock records (Employee reports > Clocked hours > the Employee's minutes > Edit; RecordEditor's
   `validateRecord`, app/components/stats/recordEditor.ts): a clock out typed 30 min before the clock
   in is refused inline ("Clock out must be after clock in."), no PATCH leaves the browser and the
   `clock_events` row is unchanged; a clock out 15 min earlier than stored sends one
   `PATCH /admin/shifts/clock-events/{id}` with only `out_utc`, the relay answers 2xx and the row
   holds it. Screenshots clock-inverted-refused (the trigger), clock-saved; `clock-patches.json`.
15. Vault folder rail (app/components/vault/vaultFolderOrder.ts `moveFolder` + `customizeReducer`), Creator 1
   on Vault Pro, its 5 OF folders served by lib/of_wire.py through the relay's real OFClient: sort menu >
   Customize order, a drag, Cancel -> OF's order back and no sort written; Customize order, two drags
   (Echo onto Alpha, up; Bravo onto Delta, down), each leaving the rail in `moveFolder`'s order; Done ->
   one POST /admin/vault-ai/of-folders/sort {account_id, custom_order} = that order, and OF's
   POST /api2/v2/vault/lists/sort {customOrder, sort: "custom"}; a reload reads OF again (the sort dropped
   the relay's vault-lists cache) and the rail shows the new order, and the sort label still reads "Custom".
   Then a second order (Bravo onto Echo), Done, and a reload 1 s later (before the app's query snapshot save is
   due): the rail shows that order from its first paint. Last, a sort from another page: OF Manager's Vault (the OF mirror,
   app/lib/ofMirrorVault.ts), its folder sort dropdown > Name -> one sort POST {sort: name}; back on Vault Pro the
   rail's label reads "Name" (both pages save it through `sortOfFolders`). Screenshots vault-customize-trigger,
   vault-order-after-reload, vault-quick-reload-trigger, vault-quick-reload-settled, vault-sort-label-after-mirror.
16. Premade composer (app/components/compose/premadeRows.ts `rowsReducer`, `rowToItem` / `rowsToItems`),
   Creator 2 on Auto Post: New auto post > Compose: Post 1 with variants A, B, C then B removed, $12,
   5 min; Post 2 ($3, 30 min) and Post 3 ($7, 45 min, 6 h to live) added, Post 2 removed -> the form shows
   Posts 1 and 3; Use in rule > Create POSTs one /admin/automation-rules whose posts[] are
   [{texts: [A, C], price 12, delay 5}, {text, price 7, delay 45, hours_to_live 6}], and GET
   /admin/automation-rules and the automation_rules row hold the same. Screenshots premade-compose-trigger,
   premade-rule-saved.
17. Delayed welcome (Smart Messages > New Message > Subscriber welcome, Creator 1): type a message,
   Escape leaves the touched editor open, then Save sends exactly one rule write with that message;
   the dialog shows Saved, and GET /admin/automation-rules and its automation_rules row hold it.
   Screenshots welcome-escape-trigger, welcome-saved; bodies in welcome-rule-bodies.json.
18. Fan List (app/components/chat/fanListPaging.ts, useChatList's placeholder): Messages Pro on
   Creator A (34 chats at small, seed 1), the owner clicks "Load more conversations" (a JS click: a scroll to
   it would page on by itself and hide the button first) and A's offset-25 page is held at the wire; A's tab
   warm-up bust (`/admin/accounts/roster-counts?bust=`, then an invalidation of A's lists) is held at the
   browser's wire until then, so the invalidation lands while that page is in flight and must leave it alone; the owner clicks Creator B's tab, and 0.5 s later A's page lands while B's
   first page is still on its way (B answers in 2.5 s). From the click, every frame and DOM
   mutation once B's tab is selected is sampled: no A row ever; the settled list holds B's first
   page and only B's Fans; no 5xx in the browser session. `fanlist-scope-switch.json`. Then B's "Load more
   conversations" -> B's offset-25 read and its Fans on the list; then back on A's tab, A's page that was held
   across the switch is on A's list. While the owner is on B, one chat on A's head page turns unread on OF (or
   read, if all are unread); back on A (past the badge bust's 8 s cooldown), the tab's badge and the list agree:
   A's tab says the head page's unread count and A's list shows exactly that many unread rows among the head
   page's Fans (the badge folds OF's first 25 chats, `_ROSTER_SCAN_MAX`). Screenshots
   fanlist-a-next-page-in-flight (trigger), fanlist-b-settled, fanlist-b-page2-settled, fanlist-a-back-settled.
18b. Refused schedule after a chat switch (app/components/chat/refusedOffers.ts, Composer): Messages Pro on
   Creator 2, Fan A's chat: PPV $5, lock text, a tagged Creator, text, Timed message +5m, Enter -> the
   scheduled-sends POST is held at the wire while the owner opens Fan B's chat, then refused 400 (the
   relay's Fansly PPV refusal): B shows the notice (A's name, the reason, the text, no Restore) with B's
   input empty; back in A, Restore brings text, price, lock and tag back (no notice left), and Enter
   schedules it through to the relay (200, the body and one new scheduled_jobs scheduled_send row carry
   text, price, lock and tag). `chat-refused.json`. Screenshots chat-refused-other-chat (trigger),
   chat-refused-restored (settled), chat-refused-rescheduled.
18c. Chat PPV send (app/components/chat/Composer.tsx submit, composerSubmit.ts gifPlan): Messages Pro on
   Creator 0, its first Fan's chat: a vault pick (picker tile 9020), a file upload (held at the browser's
   wire), PPV $10, lock text, 2 GIFs, text, Enter -> nothing reaches OF while the upload runs; the upload
   lands -> OF's wire gets one send (text, price, lock, both media, the first GIF), then one GIF-only send
   (the second GIF, no text, price or media), after it; the relay answers 200 to both. `chat-ppv.json` (the
   browser's send bodies and OF's send log). Screenshots chat-ppv-trigger, chat-ppv-settled.
19. Bell (app/components/notificationBellReducer.ts) on the Dashboard: 3 fan DMs to the scoped
   Creator through the pump hook (each waits for its toast) -> the top bar badge reads 3; opening
   the bell clears it (one `chatterly:notif-cleared`) and it stays clear after Escape. Then one
   unread `agency_notifications` row per Creator by SQL (seed/agency_notifications.py), a reload
   -> badge 3; the bell's Agency tab, "Mark all read" -> one POST
   /admin/agency-notifications/read-all 2xx, every seeded row's `read_at` set, GET unread 0, the
   badge gone after Escape. `bell-agency-read.json`. Screenshots bell-badge-trigger,
   bell-open-settled, bell-agency-mark-all-trigger, bell-agency-read-settled.
19b. Scripts (app/components/growth/scriptsPageState.ts, Growth > Scripts) on the Creator the page opens on (the
   first active one): three scripts through the real `POST /admin/saved-replies` (A and B in "slop Keep", C in it
   too). More > Add tag "slop Night" (page-only: no script carries it); another session (the owner's client) tags A
   "slop Night"; on All scripts the seeded FREE template's Delete is held at the browser's wire, Night's Rename opens,
   the Delete goes on to the relay and its refetch lands under the open prompt (Night: 1 script); OK "slop Late" ->
   one relabel POST {tag, from Night, to Late} 200, A carries Late, not Night (route, saved_replies row). On "slop
   Keep": B ticked, Remove from tag -> its relabel POST held at the browser's wire: the bar stays at "Selected 1",
   Add to tag and Remove from tag disabled, one POST (screenshot scripts-remove-busy); released -> 200, B leaves the
   tag; the owner's client puts B back; A ticked, Remove from tag answered 500 at the browser's wire -> A stays
   listed, ticked, "Selected 1", the error shown, its row keeps Keep; C's row Remove (200) refetches: B is back,
   unticked. Then two Creator switches on the creator column (to another world Creator and back), each from A's
   row Remove answered 500 on Keep: settled (error shown, then away and back: no error either side); in flight (POST
   held at the browser's wire: away and back -> A's row still busy; away again, released -> the 500 lands there, no
   error; back -> row free, no error, one POST); A keeps Keep (route). `scripts-relabels.json`.
   Screenshots scripts-rename-prompt-refetched (trigger), scripts-renamed, scripts-remove-failed,
   scripts-remove-settled, scripts-switch-trigger, scripts-switch-other, scripts-switch-settled,
   scripts-switch-inflight-back, scripts-switch-inflight-other, scripts-switch-inflight-settled.
20. Session (app/contexts/userSessionReducer.ts), last since it signs the page out: on Smart
   Messages, a window focus whose /auth/me fails on the network keeps the page and the saved
   snapshot; a focus answered 401 puts the sign-in form in place and clears the snapshot while
   the relay still knows the cookie (GET /auth/me as the owner); a reload whose /auth/me fails
   on the network shows the retry screen `[data-auth-unreachable]` (not the sign-in form, the
   snapshot kept: 0357a072c), and the next reload
   signs back in through the relay. Screenshots session-signed-in (the trigger),
   session-revalidate-neterror, session-revalidate-401, session-boot-neterror,
   session-signed-back-in.
21. Vault manage (app/components/vault/vaultBrowseReducer.ts, vaultItemEditorReducer.ts), Vault Pro on
   Creator 0, run before 20: two files ticked on All, then the Video tab -> no Selected bar there nor back
   on All; item 9021's editor (seeded described) with "abc" as the price -> Save & lock stays off, then a
   description edit -> one PATCH /admin/vault-ai/items/9021 with fields = description only, the row with
   no price. Screenshots vault-ticked-trigger, vault-type-switched, vault-price-letters, vault-price-saved.
22. Vault editor Re-describe (vaultItemEditorReducer.ts `refresh`), item 9021: a Re-describe on the
   untouched editor shows the answer's text and tags with Save & lock off; reopened, a description typed
   first survives the next Re-describe and Save & lock sends only it (the row has it, locked).
   Screenshots redescribe-untouched-trigger, redescribe-untouched-settled, redescribe-edited-trigger,
   redescribe-edited-saved.
23. Vault picker hover (app/hooks/useHoverPreview.ts), the mass composer posting as Creator 1, its one
   video (a 240p source, no OF poster frames) hovered: the storyboard build shimmer shows while frame 0 is
   held, and once frame 0 fails both the shimmer and its countdown leave. Screenshots
   picker-shimmer-trigger, picker-frame-failed.
SKIP (unreachable): the Fan drawer's PPV video hover (FanDrawer `VideoScrubThumb`, the same hook) reads
its sales from /api/of/* chat-media reads ui.py holds; vitest (FanDrawer.scrub.test.tsx) covers it.
24. Mass fan-out at volume (lib/fanout_ts.mjs through lib/app_ts.py, after the browser closed, and in a
   `--no-ui` run): `--users` operators at once, each its own form in the app's massMessageReducer.ts (all
   models on, the text), each round the app's compose/massFanOut.ts `massFanOutRound` (as useMassSend calls
   it: targets, body, runFanOut) to the relay's real `POST /api/of/v2/messages/queue` (owner cookie,
   X-Account-Id) over every Creator. Mid-round (the first send in flight) each operator types an edit and
   clicks Start over: both refused (the text and the earlier round's results stand). Creator 1's OF queue
   answers 500 in round 1: every other send 200 and
   on OF's wire once per operator, Creator 1's 502; each operator's form is locked (an edit refused); the
   retry (its form rebuilt with round 1's results) goes to Creator 1 only, with the original text; OF's
   wire ends with one mass message per operator per Creator; one `mass_runs` row per send. Budget: an
   operator's round 1, start to its last send answered, p95 <= `MASS_FANOUT_P95_MS`. `mass-volume.json`.
25. OF rich text (lib/rich_text_faults.py; app/components/ui/OfRichTextEditor.tsx, components/chat/OfRichText.tsx,
   service/of_rich_text.py). UI: Growth > Scripts > More > Add script, RT_LINES typed, "Hey" Bold + Light blue
   and line 2 Large through the toolbar, OK: the saved_replies row is RT_MARKUP and the row renders it; the same
   on a 390x844 phone context by taps (the toolbar wraps, 44px tools, no sideways scroll). Messages Pro: the
   desktop script picked in the chat opens formatted in the rich editor (no second preview, "Aa" off), Enter ->
   OF's wire gets RT_MARKUP and the textarea is back; "Aa" -> RT_LINES typed (Shift+Enter) and formatted in its
   toolbar, Enter -> RT_MARKUP again, the toolbar stays; "Aa" off, a typed plain message -> plain `<p>` text; a
   fan's formatted DM (pump frame) renders formatted (colour, weight) in its bubble. Phone 390x844: the "Aa" send
   by taps, the toolbar wrapping with 44px tools and the box on screen. Mass composer: the script picked stays
   formatted, Broadcast -> OF's queue wire gets RT_MARKUP (phone: "Aa" + pick, formatted, fits). Fansly (the
   account stamped `platform: fansly` in the browser's /admin/accounts answer, a declared wire fake; the relay
   still sends as OF): no "Aa", the script goes in plain and is sent plain. Screenshots rich-script-*,
   rich-send-*, rich-aa-*, rich-aa-phone-*, rich-mass-*, rich-mass-phone-*, rich-fansly-{desktop,phone}-*;
   `rich-text.json`.
   Volume (after the browser, and `--no-ui`): `--users` operators at once, each a dirty formatted body (foreign
   tags, attributes, classes, a script) and a plain one, as a chat send and as a mass message: OF's wire holds
   every one byte-exact as the allow-list leaves it (expected written by hand), plain stays plain.
26. OF Manager rich text (lib/ofm_rich_text_faults.py; app/lib/ofMirrorChat.ts applyScript, ofMirrorDataChats,
   ofMirrorFormat). OFM_TITLE (RT_MARKUP) seeded through POST /admin/saved-replies. Desktop: the chat
   (`?chat=<fan>&account=`), the Scripts column's pick fills OF's editor formatted (computed blue-1, 20px, bold
   heavier than the line), Send -> OF's wire RT_MARKUP, the sent bubble formatted; OFM_PLAIN picked after -> plain
   `<p>`; a fan's OFM_FAN bubble formatted and the chat list's last message its words. New message (Users tab, one
   fan) and New post (Format text page): "Hey" Bold + Light blue, line 2 Large through OF's panel -> OF's queue /
   posts wire RT_MARKUP. Phone 390x844 (touch): the header's Scripts picker, the chat send and New post the same;
   New message's composer is not shown at 390 (OF's step2; recorded, not judged). The chat typed with its own
   Format text toolbar (OFM_CHAT_TYPED): desktop RT_LINES formatted by selection -> RT_MARKUP; desktop and phone
   Large + Bold on an empty caret, then OFM_CARET_TEXT typed -> OFM_CARET_WIRE (OF's span > strong), the bubble
   Large and bold. Screenshots ofm-{chat,chat-typed,mass,post}-{desktop,phone}-{trigger,settled}; `ofm-rich-text.json`. Bypasses (declared): the chat
   list, a chat's row, its thread (OFM_FAN, then OF's wire sends to that fan) and /users/list are answered at the
   browser's wire from the relay's own chats; the word selection is set by script.
`--set only=<section>[,...]` (SECTIONS keys, `mass-volume`, `rich-volume`) runs just those while iterating; the
rest SKIP as "not selected".

A UI step that cannot complete is FAIL for each check of its section not yet recorded, with a
`failed-<section>` picture.

Bypasses (declared): OnlyFans is lib/of_wire.py (its answers to the mass queue and the post
create are guesses at OF's shape; of_client reads only their `id`; the fans / following
rosters a mass send's recipient record pages are empty; OF's by-id read of Creator 0's seeded
vault media answers them with no file variants, so the tiles render blank); the mass send and the post
create go browser -> relay -> OF's wire unchanged, their browser bodies recorded on the way.
The second Creator's first post create is answered 500 at the browser's wire (OnlyFans failing
one model of a fan-out); its retry goes through. In 1b and 21 Creator 1's mass queue is answered 500 at
OF's wire instead (`FakeOF.fail`; the 500 body is a guess), so the relay's real error path (502) runs. In
21 the operators are node, not browsers: the app's reducer and fan-out runner, only the send is node's
fetch (no React, no confirm()); all operators share the owner's session (one Agency); their sends are
not actor calls (the stock 5xx check does not see the expected 502s; 21 asserts every status itself). Creator 1's vault folder list
(`/api/of/v2/vault/lists`, let through to the relay in the vault section only) and the folder sort
reach lib/of_wire.py too; the fake keeps the last customOrder and lists in it, its sort answer body
is a guess.
Every other `/api/of/*` read stays held (ui.py), so the template picker lists the saved replies
only and the custom fan lists (and so the MASSDMEXCLUDE seed) never load, except where answered below. The Nudge save's PUT is held at the browser's wire until
the second edit is typed (the operator typing while a slow save is in flight), then let through
to the relay unchanged; the third save's PUT likewise until the editor shows the other Creator; Auto-reply's settings PUT the same way,
until the second Delay is typed, and its style PUT until the second box is toggled; Get to know fans' rule PATCH
until the cutoff, caption and price are typed. The third Creator's
`GET /admin/nudge-config` is answered 500 at the browser's wire (a relay that fails that read). Auto-reply's folder picker reads OF's lists (`/api/of/v2/lists`): answered at
the browser's wire with two custom lists. The vault duplicates hide (`POST /admin/vault-ai/duplicates/hide`, OnlyFans'
"remove from vault", no undo; in 3b its second batch is answered 500 there) is answered at the browser's wire after its body is recorded, in the
real route's shape (`hidden` = every id sent, `refused` empty), so it reaches no server, not even the
temp relay (its mirror rows stay, the scan refetch after it shows them again). In 18, Creator A's warm-up
bust (`GET /admin/accounts/roster-counts?bust=`) is held at the browser's wire until A's next page is, then let
through to the relay unchanged. In 10-11, OF's lists (`GET /api/of/v2/lists`) are answered at the
browser's wire per X-Account-Id (Creator 0: VIP, Whales, MASSDMEXCLUDE; Creator 1: two lists and
"massdmexclude "); the funnel opener's queue POST is answered 200 there after its body is
recorded (in 11 the lists answers are held until Start is seen disabled: a slow OF);
the Priority mass POST goes through to the relay unchanged (its first leg never runs:
no supervisor in a slop relay). The empty key roster is answered at the browser's wire: the real route
lists every Agency, so it is never empty on a live deployment with users. The failed roster (403)
and the failed /admin/users (502) of sections 7-8 are answered at the browser's wire too (the relay
is healthy; its own failure modes are not this flow's subject). The master of 6-8 is the second Agency's
owner (real `POST /auth/register`, then `users.is_admin` set by SQL as an operator does; there is no API for
it): /admin/manage and its reads are master-only. The run's owner stays a plain owner, so every other section
runs tenant-scoped. The session's network
errors are Playwright aborts of the browser's /auth/me (`internetdisconnected`) and its 401 is
answered at the browser's wire: the real relay signs a missing cookie out with a 200 `null`,
and never answers a live cookie 401. Clock records' PATCHes are only observed at the browser's wire
(Playwright request/response events) and reach the relay unchanged; its Clock event is SQL, not a
real clock-in (which needs an Employee login and a Shift-free clock-in role). Vault Pro's onboarding
tours are marked seen in localStorage (a returning owner). OnlyFans' /campaigns read is lib/of_wire.py's,
paged from the seeded rows (`FakeOF.campaigns`); the relay's own route, the link meta join and the
browser's paging are the product's. The vault hashes are SQL, not Pillow
over cached thumbs (thumbs live in the global /tmp store the guarded relay does not redirect).
OF's /chats (the Fan List) is answered at the browser's wire from the relay's own
`/admin/chats/recent` (paged by offset/limit, `unread` filtered, other filters empty); A's next
page is held there until after the switch and B's answers wait 2.5 s (a slow proxy, a guess). In 18 the same
rows are A's OF chat window at lib/of_wire.py (`FakeOF.chats`), which the relay's real roster-counts reads for
A's badge, so badge and list come from one OF; the unread flip on A is made there, in both at once.
Message toasts are switched on in localStorage (`chatterly:notif-settings:v1`, default off), as
the bell's Toast settings would; the agency rows are SQL (no SSE push), so the page reloads to
read them. Vault Re-describe (`POST /admin/vault-ai/describe`, a paid LLM call) is answered at the
browser's wire with a fixed description and tags. The picker's storyboard frames (`GET /img/scrub`,
the relay's ffmpeg build of OF's mp4) are answered 502 at the browser's wire (no OF CDN in the stack),
frame 0 held until the shimmer is on screen. Item 9021's describe state (AI fields, tags) and Creator 1's
picker video are SQL, as a describe and a collect leave them; OF's by-id read answers the video.
Scripts: the seeded FREE template of the page's Creator is deleted (its DELETE held at the browser's wire until the
rename prompt is open, then on to the relay unchanged), so no later section may read it; the failed Remove's relabel
POST is answered 500 at the browser's wire (the relay is healthy) and reaches no server; "another session" is the
scenario's owner client on the real relabel route.
In 18b OF's /chats is answered the same way (every Creator, unpaged by filter); OF's
taggable creators (`/api/of/v2/posts/tagged-friend-users`) are answered at the browser's wire with one
(shape a guess); the first scheduled-sends POST is answered 400 at the browser's wire with the relay's own
Fansly refusal text (the seeded Creators are OnlyFans, which the relay never refuses), the second goes to
the relay unchanged (no supervisor fires it).
In 1 Giphy's trending list (`/api/of/v2/giphy/proxy/gifs/*`) is answered at the browser's wire with 1 GIF
(a loopback image); the Broadcast carrying it goes browser -> relay -> OF's wire unchanged.
In 18c OF's /chats is answered the same way; Giphy's trending list (`/api/of/v2/giphy/proxy/gifs/*`, Giphy is
off-host) is answered at the browser's wire with 2 GIFs (loopback images); the upload (`POST /api/of/v2/upload`:
OF's signed upload and S3 PUT are not in lib/of_wire.py) is held, then answered at the browser's wire as a
deduped re-upload of vault item 9021 (`/upload`'s own shape); both chat sends go browser -> relay -> OF's wire
unchanged, their browser bodies recorded on the way.
In 1c the bulk unsend's DELETEs (`/api/of/v2/messages/queue/{id}`) go browser -> relay -> OF's wire unchanged
(lib/of_wire.py's `DELETE /api2/v2/messages/queue/{id}`, each kept in `unsends`; its answer body is a guess).
That DELETE is in THROUGH for the whole run, not only 1c: ui.owner_browser takes one `through=` per browser,
and no other section sends one.

Fault `bulk-unsend-picks-unselected` (`lib/mass_unsend_faults.py`: `bulkTargets` drops the model chips'
scope, so the bulk action unsends Creator 1's matching rows too: only the 1c check).
Faults (client side, `lib/reducers_faults.py`): `free-template-keeps-price` (the scenario's: the
mass reducer's `pickTemplate` keeps the draft's price and lock for a free template),
`template-clears-picked-gifs` (composeDraft.ts `applyTemplate` clears the picked GIFs on a GIF-less template:
only the template-GIF check),
`mass-broadcast-ignores-invalid` (Broadcast's `disabled` stops reading validateMass; the send's own
guard still refuses, so the untargeted no-invalid-send check stays green), `mass-reset-keeps-smart-pick`
(the audience reset keeps the Smart List pick),
`dupes-threshold-keeps-confirm` (a strictness change keeps the confirm, so Yes sends the old scan's ids),
`post-retry-reposts-all` (compose/fanOut.ts `fanOutTargets`: a fan-out retry re-sends to every included model;
Post's, Mass's and the volume retry checks), `fanout-content-unlocked` (`fanOutLocked` never locks: the 1b,
Post and volume lock checks), `fanout-inflight-unlocked` (`fanOutLocked` ignores a round in flight: the volume
check's mid-round edit lands), `fanout-startover-in-flight` (`discardResults` runs mid-round: the volume check's
retry forgets round 1's successes), `mass-retry-resends-all` (compose/massFanOut.ts ignores the results, the
pre-fix Mass retry: the 1b and volume retry checks), `group-full-add-acks-ok` (a full
group tab acks ok for a fan it refused), `nudge-hydrate-overwrites` (a refetch overwrites
a dirty draft), `nudge-save-ok-any-account` (a save landing after an account switch is taken by the
account now shown), `nudge-switch-keeps-verdict` (the picker's reset keeps the old account's save
verdict), `admin-failed-roster-reads-count` (`filterNote` counts on a missing roster, the
pre-fix "(N of N)"), `admin-users-failed-keeps-skeleton` (the skeleton shows whenever rows === null,
so a failed first /admin/users load keeps it drawn), `admin-manage-ungated` (the page's master gate reverted:
a non-master's open fires both reads), `revalidate-neterror-signs-out` (a
revalidate's network error signs out), `autoreply-payload-drops-field` (buildPayload sends photo-only
skip as off), `autoreply-style-save-wipes-edits` (a landed style save wipes every edit),
`style-saved-ignores-edits` (the Human style block's "Saved" half ignores boxes left unsaved),
`inflight-edit-shows-saved` (both forms' `unsaved` drops the draft compare: Auto-reply's Delay and Get to know
fans' checks),
`audience-setaccount-keeps-lists` (a real account change keeps the old Creator's
lists: only the Priority mass switch check; the funnel panel is keyed per Creator),
`funnel-panel-unkeyed` (FunnelEditor drops the panel's `key={accountId}`: only the funnel switch
check), `funnel-start-before-seed` (Start no longer waits for the MASSDMEXCLUDE seed: only the
funnel seed check), `paged-filter-keeps-page` (a filter `set` keeps the page), `clock-out-before-in-allowed` (`validateRecord`
drops the inverted-interval rule),
`move-folder-off-by-one` (`moveFolder` inserts one slot after the hovered folder: the drag, sort and reload
checks), `premade-remove-drops-wrong-row` (remove drops the next row: the rows, payload and stored checks),
`rowToItem-drops-price` (no price on the item: the payload and stored checks),
`smartlist-edit-keeps-preview` (a rule edit keeps the old count), `smartlist-between-unchecked`
(every rule valid, so a one-bound between saves),
`fanlist-placeholder-crosses-creators` (the old Creator's rows stand in across a Creator switch),
`bell-open-keeps-badge` (opening the bell zeroes no arrivals),
`vault-type-keeps-ticks` (a type switch keeps the ticks), `vault-letters-price-zero` (letters parse as $0),
`redescribe-keeps-old-text` (the inputs keep the old text, every field reads edited),
`redescribe-overwrites-edit` (the describe replaces typed text), `picker-shimmer-stuck` (a failed frame 0
keeps the shimmer),
`scripts-remove-unchecks-on-failure` (a failed
Remove from tag drops the ticks, and the selection bar is gone while a remove is in flight: the failed-remove and
bar-busy checks), `scripts-rename-stale-prompt` (the rename prompt acts on the page as it was when
it opened), `scripts-switch-keeps-error` (another Creator keeps the failed remove's error),
`scripts-stale-run-fail` (a remove answered while the page shows another Creator puts its error there),
`scripts-switch-frees-busy` (another Creator drops the busy ids: back, the in-flight row is enabled),
`vault-order-not-saved-for-reload` (a rail write
does not save the query snapshot at once: only the 1 s reload check),
`fanlist-switch-drops-next-page` (the chat list's query fn reads its abort signal for every list, so the page in
flight at a Creator switch is cancelled: only the switch-back check), `warmup-refetch-drops-next-page` (the warm-up's
invalidation refetches a list loading its next page: only the switch-back check), `warmup-skips-paged-list` (the warm-up
never refetches a list that ever paged: only the re-warm check), `vault-sort-label-not-read` (the
stored sort label is never read: only the label check), `vault-sort-label-not-saved-in-sort` (`sortOfFolders`, which
every page's folder sort goes through, saves no label: only the label check), `dupes-later-batch-fail-throws` (a later failed batch throws:
only the partial-failure check), `fanlist-load-more-click-no-op` (Load more asks for nothing: the three fan list
checks),
`refused-schedule-lost-on-switch` (a refusal
after a chat switch is put back into the closed chat, not offered), `trailing-gif-before-upload` (lib/composer_faults.py:
the trailing GIF stops waiting on the send's uploads: only the PPV send check), `rich-text-unsanitized`
(lib/rich_text_faults.py: the send boundary's allow-list is identity: only the rich text volume check), `rich-pick-plain`
(Composer's script pick drops the formatting: only the rich text chat send check); each turns
only its own checks red.
Rich text bypasses (declared): the word selections are set by script (a drag / long-press select on a contenteditable
is the one gesture Playwright cannot make); the toolbar is clicked / tapped for real. OF's /chats is answered at the
browser's wire as in 18c; the chat sends go browser -> relay -> OF's wire unchanged.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import TimeoutError as PwTimeout

from slop.actors import fan_dm, manager, ui
from slop.lib import app_ts
from slop.actors.notif_click import SETTINGS, distinct
from slop.lib.hold import held, recorded, release_settled
from slop.lib.reducers_faults import (ADMIN_EMPTY, ADMIN_GATE, ADMIN_ROSTER_FAILED, ADMIN_USERS_FAILED, AF_OFFSET0,
                                        AGENCY_READ, AUTOREPLY_DRAFT_INFLIGHT, AUTOREPLY_INFLIGHT, AUTOREPLY_RELOAD,
                                        AUTOREPLY_STORED, BELL_CLEARS, CHAT_REFUSED_RESTORED, CHAT_REFUSED_SHOWN,
                                        CLOCK_INVERTED, CLOCK_SAVED, DUPES_CONFIRM, DUPES_HIDE, DUPES_PARTIAL,
                                        FANLIST_LOAD_MORE, FANLIST_RETURN, FANLIST_REWARM, FANLIST_SCOPE, FL_SEED,
                                        FL_SWITCH, FRAME_PAGE1, GROUP_ACK, GROUP_ACK_MS, GROUP_BURST, GROUP_FANSLY,
                                        GTKF_INFLIGHT, GTKF_OFF, MASS_ALL, MASS_BODY, MASS_FREE, MASS_GATE,
                                        MASS_GATE_SEND, MASS_PARTIAL, MASS_RETRY, MASS_TEMPLATE_GIF, MASS_VOLUME,
                                        NUDGE_KEEP,
                                        NUDGE_STALE, NUDGE_STORED,
                                        NUDGE_SWITCH, PM_ROW, PM_SWITCH, POST_ALL, POST_BODIES, POST_LOCKED,
                                        POST_PRICED, POST_RETRY, PREMADE_PAYLOAD, PREMADE_ROWS, PREMADE_STORED,
                                        SCRIPTS_BAR_BUSY, SCRIPTS_REMOVE_FAIL, SCRIPTS_REMOVE_OK, SCRIPTS_RENAME,
                                        SCRIPTS_SWITCH_CLEARS,
                                        SESSION_401_OUT, SESSION_BOOT_OUT, SESSION_NET_KEEP, SMARTLIST_GATE,
                                        SMARTLIST_SAVED, SMARTLIST_STALE, VAULT_CANCEL, VAULT_DRAG, VAULT_QUICK_RELOAD,
                                        VAULT_RELOAD, VAULT_SORT, VAULT_SORT_LABEL, VAULT_MIRROR_SORT_LABEL, PICKER_SHIMMER,
                                        REDESCRIBE_KEEPS, REDESCRIBE_SHOWS, VM_PRICE, VM_TICKS)
from slop.lib.nudge_faults import NUDGE_ABA, NUDGE_ACK_LOST, NUDGE_TAB_CLOSED
from slop.lib.mass_unsend_faults import MASS_BULK_UNSEND
from slop.lib.composer_faults import PPV_SEND_BODY
from slop.lib.rich_text_faults import (RT_AA, RT_AA_PHONE, RT_BUBBLE, RT_FANSLY, RT_MASS, RT_SCRIPT_DESKTOP,
                                      RT_SCRIPT_PHONE, RT_SEND, RT_VOLUME)
from slop.lib.ofm_rich_text_faults import (OFM_BUBBLE, OFM_CHAT_DESKTOP, OFM_CHAT_PHONE, OFM_CHAT_TYPED, OFM_MASS,
                                           OFM_POST)
from slop.seed import agency_notifications, mass_broadcast_cache, of_sessions, ts

PROFILE = "agency_inbox"
UI = True
OF_WIRE = True
FAULT = "free-template-keeps-price"
VIEWPORT = (1440, 900)
WAIT_MS = 120_000  # first visit of a page compiles it in next dev
ACK_BUDGET_MS = 150  # the sender (lib/groupChannel.ts ADD_ACK_TIMEOUT_MS) gives up at 400 ms
SNOWFLAKE = "900234567890123456"  # a Fansly fan id: past 2^53, only exact as a string
PERSIST_SETTLE_MS = 6_000  # app/components/providers.tsx PERSIST_THROTTLE_MS (4 s) + rqPersister's 1 s idle wait

# No fault targets it (proof shot + side effect for the funnel media pane), so the name lives here.
FUNNEL_MEDIA_SAVED = "funnel media: an opener vault pick, Save media -> 'Saved' shown and the GET holds the pick"
WELCOME_SAVED = "delayed welcome: Escape keeps the typed editor open; one Save and route plus row hold the message"
WELCOME_TEXT = "slop welcome after Escape"

SECTIONS = {
    "mass": (MASS_FREE, MASS_GATE, MASS_GATE_SEND, MASS_BODY, MASS_TEMPLATE_GIF, MASS_ALL),
    "mass-retry": (MASS_PARTIAL, MASS_RETRY),
    "mass-unsend": (MASS_BULK_UNSEND,),
    "post": (POST_PRICED, POST_ALL, POST_BODIES, POST_RETRY, POST_LOCKED),
    "dupes": (DUPES_CONFIRM, DUPES_HIDE),
    "dupes-partial": (DUPES_PARTIAL,),
    "group": (GROUP_ACK, GROUP_FANSLY, GROUP_BURST, GROUP_ACK_MS),
    "nudge": (NUDGE_KEEP, NUDGE_STORED, NUDGE_SWITCH, NUDGE_STALE, NUDGE_ABA, NUDGE_TAB_CLOSED, NUDGE_ACK_LOST),
    "admin": (ADMIN_EMPTY,),
    "smartlist": (SMARTLIST_STALE, SMARTLIST_GATE, SMARTLIST_SAVED),
    "admin-roster": (ADMIN_ROSTER_FAILED,),
    "admin-users": (ADMIN_USERS_FAILED,),
    "admin-gate": (ADMIN_GATE,),
    "autoreply": (AUTOREPLY_RELOAD, AUTOREPLY_STORED, AUTOREPLY_DRAFT_INFLIGHT, AUTOREPLY_INFLIGHT),
    "gtkf": (GTKF_OFF, GTKF_INFLIGHT),
    "audience-pm": (PM_SWITCH, PM_ROW),
    "audience-fl": (FL_SEED, FL_SWITCH),
    "funnel-media": (FUNNEL_MEDIA_SAVED,),
    "frame": (FRAME_PAGE1,),
    "autofollow": (AF_OFFSET0,),
    "clock": (CLOCK_INVERTED, CLOCK_SAVED),
    "vault": (VAULT_DRAG, VAULT_CANCEL, VAULT_SORT, VAULT_RELOAD, VAULT_SORT_LABEL, VAULT_QUICK_RELOAD,
              VAULT_MIRROR_SORT_LABEL),
    "premade": (PREMADE_ROWS, PREMADE_PAYLOAD, PREMADE_STORED),
    "welcome": (WELCOME_SAVED,),
    "fanlist": (FANLIST_SCOPE, FANLIST_LOAD_MORE, FANLIST_RETURN, FANLIST_REWARM),
    "chat-refused": (CHAT_REFUSED_SHOWN, CHAT_REFUSED_RESTORED),
    "chat-ppv": (PPV_SEND_BODY,),
    "bell": (BELL_CLEARS, AGENCY_READ),
    "vaultmanage": (VM_TICKS, VM_PRICE),
    "redescribe": (REDESCRIBE_SHOWS, REDESCRIBE_KEEPS),
    "shimmer": (PICKER_SHIMMER,),
    "scripts": (SCRIPTS_RENAME, SCRIPTS_BAR_BUSY, SCRIPTS_REMOVE_OK, SCRIPTS_REMOVE_FAIL, SCRIPTS_SWITCH_CLEARS),
    "session": (SESSION_NET_KEEP, SESSION_401_OUT, SESSION_BOOT_OUT),
    "rich-text": (RT_SCRIPT_DESKTOP, RT_SCRIPT_PHONE, RT_SEND, RT_AA, RT_AA_PHONE, RT_MASS, RT_FANSLY, RT_BUBBLE),
    "ofm-rich-text": (OFM_CHAT_DESKTOP, OFM_CHAT_PHONE, OFM_CHAT_TYPED, OFM_BUBBLE, OFM_MASS, OFM_POST),
}
# Reducer fixes this scenario cannot drive on the real path; each reports SKIP with why.
UNREACHED = {
    "fan drawer: hover preview of a fan's PPV videos (useHoverPreview via VideoScrubThumb)":
        "unreachable: the drawer's PPV video sales come from /api/of/* chat-media reads, which ui.py holds "
        "(never answered); vitest FanDrawer.scrub.test.tsx covers it",
}
LIVE_ONLY = "Only agencies with a live model session"

PAID_TPL = {"title": "slop paid tpl", "text": "slop paid template text", "price": 25, "locked_text": True}
FREE_TPL = {"title": "slop free tpl", "text": "slop free template text", "price": 0, "locked_text": False}
MASS_TEXT = "slop broadcast text"
MASS_ALL_TEXT = "slop all-models broadcast"
MASS_RETRY_TEXT = "slop partial-failure broadcast"
EDIT = " (edited after the partial failure)"  # typed only if the box is not locked
OF_QUEUE = "POST /api2/v2/messages/queue"  # lib/of_wire.py's route label, `fail` key
# Mass fan-out at volume (lib/fanout_ts.mjs): --users operators, each an all-models Broadcast over the
# --scale Creators (agency_inbox: 3 small, 10 medium/huge, fans by SQL), one Creator's OF queue failing.
VOLUME_TEXT = "slop volume broadcast"
VOLUME_TS = Path(__file__).resolve().parents[1] / "lib" / "fanout_ts.mjs"
# End to end: an operator's Broadcast (runFanOut start) to its last Creator's send answered, the relay having
# had OF's wire take it. The sends run in turn per operator, so it grows with the Creators. 30 s is a guess at
# what an operator watching "Sending to k / N…" over 10 Creators tolerates. Measured (OF answers in
# lib/of_wire.py's 50 ms): small x 20 operators 9.3 s; medium x 200 20.8 s (run 20261030T103718Z-...-0432,
# green). Earlier medium x 200 runs at 83 s and 158 s were the host's 1-min load of 80-120 from other work
# (the relay's queue route p50 9 s / p95 42 s then), not the code: a loaded host can still turn it red.
MASS_FANOUT_P95_MS = 30_000
MASS_VOLUME_P95 = (f"mass fan-out at volume: an operator's all-models Broadcast (round 1), from its start to its last "
                   f"Creator's send answered (each after OF's wire took it), p95 <= {MASS_FANOUT_P95_MS} ms")
MASS_VOLUME_RUNS = ("mass fan-out at volume: every queue POST the relay took left its mass_runs row (one per send, "
                    "per Creator: attribution kept under the load)")
# The --no-ui parts (run after the browser): name -> (fn, its checks).
VOLUME_PARTS = {"mass-volume": ("_mass_volume", (MASS_VOLUME, MASS_VOLUME_RUNS, MASS_VOLUME_P95)),
                "rich-volume": ("_rich_volume", (RT_VOLUME,))}
SMART_LIST = "slop whales"
QUEUE = "/api/of/v2/messages/queue"
POSTS = "/api/of/v2/posts"
UNSEND = re.compile(re.escape(QUEUE) + r"/(\d+)")  # the mass unsend (section 1c)
# The writes ui.py lets through to the relay (every other /api/of/ call stays held).
THROUGH = (("POST", re.compile(re.escape(QUEUE))), ("POST", re.compile(re.escape(POSTS))), ("DELETE", UNSEND))
POST_TEXT = "slop text-only post"
PRICE_NOTE = "Minimum $3 USD or free"  # app/lib/sendGuards.ts
HASH_KIND = "thumb/md5+dhash8+ahash8"  # service/vault_dupes.py
SNAPSHOT_KEY = "chatterly:auth-snapshot:v1"  # app/lib/authSnapshot.ts
RETRY = "[data-auth-unreachable]"  # app/components/auth/AuthGate.tsx's retry screen
# OF's lists per Creator index (sections 10-11): (id, name). "massdmexclude " checks the trimmed,
# case-insensitive MASSDMEXCLUDE match.
OF_LISTS = {0: [(9101, "VIP"), (9102, "Whales"), (9103, "MASSDMEXCLUDE")],
            1: [(9201, "C1 regulars"), (9202, "C1 tippers"), (9203, "massdmexclude ")]}
PM_TEXT = "slop priority switch"
CLOCK_EMPLOYEE = "slop clock emp"
INVERTED_MSG = "Clock out must be after clock in."  # app/components/stats/recordEditor.ts
TOURS_SEEN = ("localStorage.setItem('vaultProOnboarding', JSON.stringify({batchUploadEntry: '1', "
              "uploadPageStep: '1', batchEdit: '1', uploadBtn: '1'}));")
# Creator 1's OF vault folders (lib/of_wire.py serves them), in OF's order before any sort.
FOLDERS = [(880001, "slop Alpha"), (880002, "slop Bravo"), (880003, "slop Charlie"), (880004, "slop Delta"),
           (880005, "slop Echo")]
DRAGS = (("slop Echo", "slop Alpha"), ("slop Bravo", "slop Delta"))  # (dragged, dropped on): up, then down
CANCEL_DRAG = ("slop Alpha", "slop Delta")
VAULT_IDS = (9001, 9002, 9003, 9010, 9011, 9020, 9021)  # Creator 0's seeded vault (`_seed_vault`), oldest first
VM_DESC = "slop operator description"
VM_AI = {"description": "slop ai description", "tags": ["slop", "beach"], "explicitness_tier": "safe"}
REDESCRIBE_ANSWERS = (  # POST /admin/vault-ai/describe, answered at the browser's wire (a paid LLM call)
    {"status": "described", "describe_status": "described", "description": "slop redescribed",
     "tags": ["slop", "redescribed"]},
    {"status": "described", "describe_status": "described", "description": "slop redescribed again"},
)
REDESCRIBE_EDIT = "slop typed before the redescribe"
PICKER_VIDEO = 9101  # Creator 1's one vault video: a 240p progressive source, no OF poster frames
QUICK_DRAG = ("slop Bravo", "slop Echo")  # the second order, reloaded QUICK_RELOAD_MS after Done
QUICK_RELOAD_MS = 1_000  # under PERSIST_SETTLE_MS: only a save on Done itself can have the new order on disk
# Post 1: variants A, B, C, then B removed; Post 2 added then removed; Post 3 kept.
PREMADE_WANT = [
    {"texts": ["slop post one A", "slop post one C"], "price": 12, "delay_minutes": 5},
    {"text": "slop post three", "price": 7, "delay_minutes": 45, "hours_to_live": 6},
]


def move_folder(order: list, src, dst) -> list:
    """app/components/vault/vaultFolderOrder.ts `moveFolder`, the spec: `src` into `dst`'s slot."""
    if src == dst or src not in order or dst not in order:
        return order
    i, j = order.index(src), order.index(dst)
    out = list(order)
    out.pop(i)
    out.insert(j, src)
    return out


def _seed_vault(w, aid: str) -> list[int]:
    """Creator 0's vault mirror: set A (3 identical copies, at any strictness), set B (2 copies 3 bits
    apart, only at strictness >= 3), 2 loners. As the collect + ensure_hashes would leave the rows."""
    base_d, base_a = 0x0F0F0F0F0F0F0F0F, 0x3C3C3C3C3C3C3C3C
    items = [  # media_id, md5, dhash, ahash, days ago
        (9001, "a" * 32, base_d, base_a, 60), (9002, "a" * 32, base_d, base_a, 40), (9003, "a" * 32, base_d, base_a, 20),
        (9010, "b" * 32, 0x123456789ABCDEF0, 0x0FEDCBA987654321, 50),
        (9011, "c" * 32, 0x123456789ABCDEF0 ^ 0b111, 0x0FEDCBA987654321 ^ 0b111, 30),
        (9020, "d" * 32, 0xFFFF0000FFFF0000, 0xAAAA5555AAAA5555, 10),
        (9021, "e" * 32, 0x00FF00FF00FF00FF, 0x5555AAAA5555AAAA, 5),
    ]
    _insert_vault_items(w, aid, [(mid, w.now - timedelta(days=days), f"{md5}:{dh:016x}:{ah:016x}")
                                 for mid, md5, dh, ah, days in items])
    # The last loner already described (as a describe leaves it: AI fields, tags projected, status), for the
    # item editor (sections 21-22).
    con = w.sql()
    with con:
        con.execute("UPDATE vault_items SET ai_fields_json=?, tags=?, describe_status='described' "
                    "WHERE account_id=? AND media_id=?",
                    (json.dumps(VM_AI), json.dumps(VM_AI["tags"]), aid, VAULT_IDS[-1]))
    con.close()
    return [mid for mid, *_ in items]


def _insert_vault_items(w, aid: str, rows: list[tuple[int, datetime, str]]) -> None:
    """`vault_items` rows (media_id, created_at, content_hash) as a collect plus `vault_dupes.ensure_hashes` write
    them: photos, never sent, untagged; and the collect's finished run."""
    con = w.sql()
    with con:
        con.executemany(
            "INSERT INTO vault_items (account_id, media_id, kind, tags, send_count, created_at, content_hash,"
            " content_hash_kind, updated_at) VALUES (?, ?, 'photo', '[]', 0, ?, ?, ?, ?)",
            [(aid, mid, ts(created), h, HASH_KIND, ts(w.now)) for mid, created, h in rows])
        _seed_collect_run(con, w, aid, len(rows))
    con.close()


def _seed_collect_run(con, w, aid: str, total: int) -> None:
    """The `vault_cache_runs` row a finished manual Collect leaves (status done, phase done; seed/vault_live.py's
    shape): `vault_runs.full_walk_done` -> `cache/summary` `complete` true, the picker's mirror path."""
    started = w.now - timedelta(hours=2)
    con.execute("INSERT INTO vault_cache_runs(account_id, status, phase, total_seen, upserted, pages_done, started_at,"
                " finished_at) VALUES (?,?,?,?,?,?,?,?)",
                (aid, "done", "done", total, total, max(1, -(-total // 100)), ts(started),
                 ts(started + timedelta(minutes=2))))


HIDE_BATCH = 250  # app/hooks/useVaultCache.ts HIDE_BATCH: ids per hide request
PARTIAL_COPIES = HIDE_BATCH + 1  # the hide goes out in 2 batches
PARTIAL_FAIL = "slop: OnlyFans failed the batch"


def _seed_vault_partial(w, aid: str) -> list[int]:
    """Creator 2's vault mirror: one set of PARTIAL_COPIES + 1 byte-identical items (the oldest is kept)."""
    ids = list(range(9500, 9501 + PARTIAL_COPIES))
    same = f"{'f' * 32}:{0x0123456789ABCDEF:016x}:{0x7E7E7E7E7E7E7E7E:016x}"
    _insert_vault_items(w, aid, [(mid, w.now - timedelta(days=90, minutes=-k), same) for k, mid in enumerate(ids)])
    return ids


def _picker_video(w) -> dict:
    """OF's media item for Creator 1's one vault video: a 240p progressive source, no poster frames
    (`files` empty), so the picker's hover builds a storyboard."""
    return {"id": PICKER_VIDEO, "type": "video", "duration": 30, "canView": True, "isReady": True,
            "createdAt": (w.now - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            "videoSources": {"240": f"https://cdn2.onlyfans.com/files/slop/{PICKER_VIDEO}_240.mp4", "720": None},
            "files": {}}


def _seed_picker_video(w, aid: str) -> dict:
    """Creator 1's vault mirror: the one video as a collect leaves it (OF's media item in raw_json)."""
    raw = _picker_video(w)
    con = w.sql()
    with con:
        con.execute("INSERT INTO vault_items (account_id, media_id, kind, tags, send_count, created_at, raw_json, updated_at)"
                    " VALUES (?, ?, 'video', '[]', 0, ?, ?, ?)",
                    (aid, PICKER_VIDEO, ts(w.now - timedelta(days=3)), json.dumps(raw), ts(w.now)))
        _seed_collect_run(con, w, aid, 1)
    con.close()
    return raw


N_LINKS = 140      # every Creator's OF tracking links: 120 active (3 pages of 50), 20 deactivated (every 7th)
FRAME_PAGE = 50    # LinksListFrame's DEFAULT_PAGE_SIZE
AF_PAGE = 20       # AutoFollowList's PAGE
LINK_ID_BASE = 61_000


def _link_rows(w) -> list[dict]:
    """OF's /campaigns rows, newest first: link i is i days old, deactivated when i % 7 == 0."""
    out = []
    for i in range(N_LINKS, 0, -1):
        created = w.now - timedelta(days=i)
        out.append({"id": LINK_ID_BASE + i, "campaignCode": 7000 + i, "campaignName": f"slop link {i:03d}",
                    "countTransitions": i * 3, "countSubscribers": 0,
                    "createdAt": created.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                    "endDate": (created + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S") if i % 7 == 0 else None,
                    "isDeleted": i % 7 == 0})
    return out


async def _seed_links(ctx, w) -> dict:
    """OF's side of every Creator's tracking links (`FakeOF.campaigns`, lib/of_wire.py), and their Source
    through the real batch edit: every other active link IG, the rest Reddit."""
    rows = _link_rows(w)
    for c in w.data["creators"]:
        ctx.of_wire.campaigns[c["id"]] = rows
    active = [r for r in rows if not r["isDeleted"]]
    ig = [r["id"] for k, r in enumerate(active) if k % 2 == 0]
    reddit = [r["id"] for r in rows if r["id"] not in set(ig)]
    for c in w.data["creators"]:
        for src, ids in (("IG", ig), ("Reddit", reddit)):
            r = await ctx.owner.request("PUT", "/admin/link-meta/batch",
                                        json={"account_id": c["id"], "kind": "campaign", "of_ids": ids, "source": src})
            r.raise_for_status()
    name = lambda r: r["campaignName"]  # noqa: E731
    return {"active": [name(r) for r in active], "all": [name(r) for r in rows],
            "ig": [name(r) for r in active if r["id"] in set(ig)]}


def _seed_follows(w, aid: str) -> None:
    """Auto-follow's record of Creator 0's fans: one `follow_ping_state` row per fan, as `auto_follow.stamp_ping`
    writes it (latest follow, count)."""
    rng = w.rng("reducers-follows")
    con = w.sql()
    with con:
        for f in w.data["fans"][aid]:
            con.execute("INSERT INTO follow_ping_state (account_id, fan_id, last_pinged_at, ping_count) VALUES (?,?,?,?)",
                        (aid, f["id"], ts(w.now - timedelta(minutes=rng.randint(10, 20 * 24 * 60))), rng.randint(1, 3)))
    con.close()


async def _section(ctx, page, name: str, fn) -> None:
    """Run one section; a step that cannot complete fails every check of it not yet recorded."""
    done: set[str] = set()

    def chk(check_name: str, ok: bool, **detail) -> None:
        done.add(check_name)
        ctx.check(check_name, ok, **detail)

    try:
        await fn(chk)
    except Exception as e:  # noqa: BLE001 — a UI step that cannot complete is its checks' FAIL
        try:
            await ui.shot(ctx, page, f"failed-{name}")
        except Exception:  # noqa: BLE001
            pass
        for c in SECTIONS[name]:
            if c not in done:
                ctx.check(c, False, error=f"{type(e).__name__}: {e}"[:600], section=name)


async def _wait_value(loc, want: str, timeout_ms: int = 5_000, attr: str | None = None) -> str | None:
    """The input's value (or its `attr` attribute) once it is `want` (or what it is after the timeout)."""
    read = (lambda: loc.get_attribute(attr)) if attr else loc.input_value
    t_end = asyncio.get_event_loop().time() + timeout_ms / 1000
    v = await read()
    while v != want and asyncio.get_event_loop().time() < t_end:
        await asyncio.sleep(0.1)
        v = await read()
    return v


# A form's SaveRow (automationPage.tsx) as drawn: whether Save is disabled, and the notes beside it ("Saved", a warn,
# the failed save's message). Unsaved edits after a landed save: Save enabled, no note at all; the broken state is the
# same row with "Saved" beside it.
SAVE_ROW_UNSAVED = {"disabled": False, "notes": []}
SAVE_ROW_SAVED = {"disabled": False, "notes": ["Saved"]}


async def _save_row(save) -> dict:
    return await save.evaluate("(b) => ({ disabled: b.disabled, notes: [...b.parentElement.children]"
                               ".filter((x) => x !== b).map((x) => x.textContent.trim()) })")


async def _painted(page) -> None:
    """No CSS transition still running (a switch slides 150 ms) and two frames drawn since: what the DOM
    holds is on screen for the picture."""
    await page.wait_for_function(
        "() => document.getAnimations().every((a) => !(a instanceof CSSTransition) || a.playState !== 'running')",
        timeout=10_000)
    await page.evaluate("() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")


async def _button_state(btn) -> dict:
    return {"disabled": await btn.is_disabled(), "title": await btn.get_attribute("title")}


async def _open_create_message(ctx, page, card: re.Pattern) -> None:
    await page.goto(f"{ctx.app}/growth/smart-messages", wait_until="domcontentloaded")
    await page.get_by_role("button", name="New Message").first.click(timeout=WAIT_MS)
    await page.get_by_role("button", name=card).first.click(timeout=30_000)
    await page.get_by_role("button", name="Next", exact=True).click(timeout=10_000)


async def _pick_template(page, title: str) -> None:
    await page.get_by_title("Insert saved template").first.click(timeout=30_000)
    row = page.get_by_role("button").filter(has_text=title)
    await row.first.wait_for(timeout=30_000)
    await row.first.click()


def _wire(ctx, kind: str) -> dict[str, list[dict]]:
    """OF's wire bodies so far (lib/of_wire.py `queue`, `posts` or `unsends`), per Creator."""
    with ctx.of_wire.lock:
        return {a: list(v) for a, v in getattr(ctx.of_wire, kind).items()}


def _statuses(page, path: str) -> list[int]:
    """The relay's answers to `path` the page saw (POSTs only: the scenario sends nothing else there)."""
    return [st for st, url in page.slop["statuses"] if urlsplit(url).path == path]


async def _chips(page) -> dict:
    """The system audience chips' states (SysChip: "· included" hint = included) and the Smart List's include pick."""
    out = {}
    for label in ("All fans", "Following"):
        t = await page.get_by_role("button", name=re.compile(rf"^(\+ )?{label}")).first.inner_text()
        out[label] = "· included" in t
    smart = page.get_by_role("button", name=SMART_LIST, exact=True)
    out["smart_shown"] = await smart.count() > 0
    out["smart_include"] = (await smart.first.get_attribute("aria-pressed")) == "true" if out["smart_shown"] else None
    return out


def _giphy_gifs(app: str, picks: list[tuple[str, str]]) -> list[dict]:
    """Giphy GIFs (id, title) whose images are the app's own icon (loopback: ui.py aborts off-host images)."""
    img = {"url": f"{app}/icon.svg", "width": "64", "height": "64"}
    return [{"type": "gif", "id": i, "title": t, "images": {"original": img, "fixed_height": img}} for i, t in picks]


def _giphy_route(gifs: list[dict]):
    """(url predicate, handler) answering Giphy's trending list through the relay's proxy with `gifs`
    (Giphy is off-host: answered at the browser's wire)."""
    async def giphy(route):
        await route.fulfill(status=200, content_type="application/json", body=json.dumps(
            {"data": gifs, "pagination": {"total_count": len(gifs), "count": len(gifs), "offset": 0}}))
    return (lambda u: urlsplit(u).path.startswith("/api/of/v2/giphy/proxy/gifs/")), giphy


async def _mass(ctx, page, chk) -> None:
    bodies: list[dict] = []
    gif = _giphy_gifs(ctx.app, [("slopmassgif1", "slop mass gif")])[0]

    async def queue(route):
        if route.request.method == "POST":
            bodies.append({"body": route.request.post_data_json, "account": route.request.headers.get("x-account-id")})
        await route.fallback()  # ui.py's THROUGH: on to the relay, whose OFClient reaches OF's wire

    giphy = _giphy_route([gif])
    await page.route(lambda u: urlsplit(u).path == QUEUE, queue)
    await page.route(*giphy)
    await _open_create_message(ctx, page, re.compile(r"^OF mass message"))
    ta = page.get_by_placeholder("What's the broadcast?")
    await ta.wait_for(timeout=WAIT_MS)
    tpl_btn = page.get_by_title("Insert saved template").first
    await page.wait_for_function("(b) => b && !b.disabled", arg=await tpl_btn.element_handle(), timeout=30_000)
    aid = await page.locator("select:has(option[value])").first.input_value()
    price = page.get_by_placeholder("0 (free)")
    lock = page.get_by_label("Lock the text too (fan must pay to read)")
    send = page.get_by_role("button", name="Broadcast", exact=True)
    clicked: list[str] = []

    async def click_if_enabled(draft: str) -> None:
        """An enabled Broadcast on an invalid draft is clicked: the send's own guard must refuse it."""
        if not await send.is_disabled():
            clicked.append(draft)
            await send.click(timeout=10_000)  # confirm() accepted
            await page.wait_for_timeout(1_000)

    # The gate first, on a draft with no GIF (a GIF alone is a valid draft).
    await ta.fill("")
    empty = await _button_state(send)
    await click_if_enabled("empty text")
    await ta.fill(MASS_TEXT)
    await price.fill("2")
    low = await _button_state(send)
    await click_if_enabled("price $2")
    chk(MASS_GATE, empty == {"disabled": True, "title": "Add text, media, or a GIF"}
        and low == {"disabled": True, "title": PRICE_NOTE}, empty_text=empty, price_2=low)
    chk(MASS_GATE_SEND, not bodies and not _statuses(page, QUEUE), clicked_enabled=clicked,
        queue_posts=len(bodies), relay_statuses=_statuses(page, QUEUE))
    await price.fill("")

    await _pick_template(page, PAID_TPL["title"])
    paid_price = await _wait_value(price, "25")
    paid_lock = await lock.is_checked() if await lock.count() else None
    # A GIF picked after the PAID template: the GIF-less FREE one must keep it.
    remove_gif = page.get_by_role("button", name="Remove GIF", exact=True)
    await page.get_by_role("button", name="GIF picker", exact=True).first.click(timeout=10_000)
    await page.locator(f"button[title='{gif['title']}']").first.click(timeout=30_000)
    await remove_gif.first.wait_for(timeout=10_000)
    gif_chips_before = await remove_gif.count()
    await ui.shot(ctx, page, "mass-gif-picked")
    await page.get_by_title("Insert saved template").first.click()
    await page.get_by_role("button").filter(has_text=FREE_TPL["title"]).first.wait_for(timeout=30_000)
    await ui.shot(ctx, page, "mass-free-template-trigger")
    await page.get_by_role("button").filter(has_text=FREE_TPL["title"]).first.click()
    free_price = await _wait_value(price, "")
    await page.wait_for_timeout(300)
    lock_shown = await lock.count() > 0
    free_lock = await lock.is_checked() if lock_shown else False
    gif_chips_after = await remove_gif.count()
    gif_img_after = await page.locator(f"img[alt='{gif['title']}']").count()
    await ui.shot(ctx, page, "mass-free-template-settled")
    # The lock box only shows on a PPV: type a price, and the FREE template's lock (off) shows.
    await price.fill("5")
    await lock.wait_for(timeout=10_000)
    lock_after_price = await lock.is_checked()
    chk(MASS_FREE, paid_price == "25" and paid_lock is True and free_price == "" and not free_lock
        and lock_after_price is False,
        account=aid, paid_price=paid_price, paid_lock=paid_lock, free_price=free_price,
        lock_shown_after_free=lock_shown, lock_checked_after_free=free_lock,
        lock_checked_after_typing_5=lock_after_price, text=await ta.input_value())

    await ta.fill(MASS_TEXT)
    await price.fill("5")
    await lock.check(timeout=10_000)
    valid = await _button_state(send)
    await send.click(timeout=10_000)  # the confirm() is accepted (page dialog handler)
    await _until(lambda: bodies and len(_wire(ctx, "queue").get(aid, ())) >= 1
                 and _statuses(page, QUEUE), 20)
    await page.wait_for_timeout(500)
    await ui.shot(ctx, page, "mass-broadcast-sent")
    b = bodies[0]["body"] if bodies else {}
    want = {"text": MASS_TEXT, "price": 5, "locked_text": True, "user_lists": ["fans", "following"],
            "excluded_user_lists": [], "media_files": [], "scheduled_date": None}
    got = {k: b.get(k) for k in want}
    wire = _wire(ctx, "queue")
    sent = wire.get(aid, [])
    w0 = sent[0] if sent else {}
    want_wire = {"text": MASS_TEXT, "price": 5, "lockedText": True, "userLists": ["fans", "following"],
                 "userIds": [], "mediaFiles": []}
    got_wire = {k: w0.get(k) for k in want_wire}
    status = _statuses(page, QUEUE)[:1]
    con = ctx.world.sql()
    runs = [dict(zip(("account_id", "queue_id", "status"), r)) for r in con.execute(
        "SELECT account_id, queue_id, status FROM mass_runs WHERE account_id=?", (aid,)).fetchall()]
    con.close()
    (ctx.out / "mass-queue-bodies.json").write_text(json.dumps({"browser": bodies, "of_wire": wire}, indent=2))
    chk(MASS_BODY, valid == {"disabled": False, "title": None} and len(bodies) == 1 and got == want
        and bodies[0]["account"] == aid and status == [200] and sum(map(len, wire.values())) == 1
        and got_wire == want_wire and len(runs) == 1 and runs[0]["queue_id"] == w0.get("id"),
        button=valid, posts=len(bodies), got=got, want=want, account=bodies[0]["account"] if bodies else None,
        picked=aid, relay_status=status, of_wire=got_wire, of_wire_want=want_wire,
        of_wire_sends={a: len(v) for a, v in wire.items()}, mass_runs=runs)
    chk(MASS_TEMPLATE_GIF, gif_chips_before == 1 and gif_chips_after == 1 and gif_img_after == 1
        and b.get("giphy_id") == gif["id"] and w0.get("giphyId") == gif["id"],
        gif_chips_before_free_template=gif_chips_before, gif_chips_after_free_template=gif_chips_after,
        gif_img_after_free_template=gif_img_after, body_giphy_id=b.get("giphy_id"),
        of_wire_giphyId=w0.get("giphyId"), want=gif["id"])

    # All models: the audience resets in the one switch, the Smart List pick with it.
    await _open_create_message(ctx, page, re.compile(r"^OF mass message"))
    await ta.wait_for(timeout=WAIT_MS)
    smart = page.get_by_role("button", name=SMART_LIST, exact=True).first
    await smart.wait_for(timeout=30_000)
    await page.get_by_role("button", name=re.compile(r"^(\+ )?All fans")).first.click()
    await smart.click()
    picked = await _chips(page)
    all_box = page.get_by_label(re.compile(r"Broadcast from ALL models"))
    await all_box.check(timeout=10_000)
    await page.wait_for_timeout(300)
    on = await _chips(page)
    await ui.shot(ctx, page, "mass-all-models-reset")
    await all_box.uncheck(timeout=10_000)
    await smart.wait_for(timeout=30_000)
    off = await _chips(page)
    await all_box.check(timeout=10_000)
    included = await page.get_by_text(re.compile(r"^\(\d+/\d+ included\)$")).first.inner_text()
    n_included = int(re.match(r"\((\d+)/", included).group(1))
    await ta.fill(MASS_ALL_TEXT)
    n0 = len(bodies)
    await send.click(timeout=10_000)
    all_sent = lambda: [x for v in _wire(ctx, "queue").values() for x in v if x.get("text") == MASS_ALL_TEXT]  # noqa: E731
    await _until(lambda: len(all_sent()) >= n_included and len(_statuses(page, QUEUE)) >= 1 + n_included, 30)
    await page.wait_for_timeout(500)
    await ui.shot(ctx, page, "mass-all-models-sent")
    wire = _wire(ctx, "queue")
    (ctx.out / "mass-queue-bodies.json").write_text(json.dumps({"browser": bodies, "of_wire": wire}, indent=2))
    fanout = [{"account": a, "userLists": x.get("userLists"), "userIds": x.get("userIds"), "price": x.get("price")}
              for a, v in wire.items() for x in v if x.get("text") == MASS_ALL_TEXT]
    creators = {c["id"] for c in ctx.world.data["creators"]}
    statuses = _statuses(page, QUEUE)[1:]
    chk(MASS_ALL, picked == {"All fans": False, "Following": True, "smart_shown": True, "smart_include": True}
        and on == {"All fans": True, "Following": True, "smart_shown": False, "smart_include": None}
        and off == {"All fans": True, "Following": True, "smart_shown": True, "smart_include": False}
        and n_included == len(creators) and len(bodies) - n0 == n_included and statuses == [200] * n_included
        and {f["account"] for f in fanout} == creators and len(fanout) == n_included
        and all(f["userLists"] == ["fans", "following"] and f["userIds"] == [] and not f["price"] for f in fanout),
        before_switch=picked, all_models_on=on, all_models_off=off, included=included, relay_statuses=statuses,
        of_wire=fanout)
    await page.unroute(lambda u: urlsplit(u).path == QUEUE)
    await page.unroute(*giphy)


async def _mass_retry(ctx, page, chk) -> None:
    """All models, one Creator's OF mass queue failing at OF's wire: the partial round, the lock, the retry."""
    bodies: list[dict] = []
    creators = [c["id"] for c in ctx.world.data["creators"]]
    failing = creators[1]  # picked from the seed

    async def queue(route):
        if route.request.method == "POST":
            bodies.append({"body": route.request.post_data_json, "account": route.request.headers.get("x-account-id")})
        await route.fallback()  # ui.py's THROUGH: on to the relay, whose OFClient reaches OF's wire

    def sent() -> dict[str, list[str]]:
        return {a: [x.get("text") for x in v if (x.get("text") or "").startswith(MASS_RETRY_TEXT)]
                for a, v in _wire(ctx, "queue").items()}

    def of_500s() -> int:
        with ctx.of_wire.lock:
            return sum(1 for c in ctx.of_wire.calls if c["route"] == OF_QUEUE and c["status"] == 500)

    await page.route(lambda u: urlsplit(u).path == QUEUE, queue)
    await _open_create_message(ctx, page, re.compile(r"^OF mass message"))
    ta = page.get_by_placeholder("What's the broadcast?")
    await ta.wait_for(timeout=WAIT_MS)
    all_box = page.get_by_label(re.compile(r"Broadcast from ALL models"))
    await all_box.check(timeout=10_000)
    included = await page.get_by_text(re.compile(r"^\(\d+/\d+ included\)$")).first.inner_text()
    n = int(re.match(r"\((\d+)/", included).group(1))
    await ta.fill(MASS_RETRY_TEXT)
    send = page.get_by_role("button", name="Broadcast", exact=True)
    s0, f0 = len(_statuses(page, QUEUE)), of_500s()
    with ctx.of_wire.lock:
        ctx.of_wire.fail.add((failing, OF_QUEUE))
    await ui.shot(ctx, page, "mass-partial-trigger")
    try:
        await send.click(timeout=10_000)  # confirm() accepted
        await _until(lambda: len(_statuses(page, QUEUE)) >= s0 + n, 30)
    finally:
        with ctx.of_wire.lock:
            ctx.of_wire.fail.discard((failing, OF_QUEUE))
    summary = page.get_by_text(re.compile(r"^Fan-out results — \d+/\d+ succeeded$"))
    await summary.wait_for(timeout=10_000)
    await _painted(page)
    round1 = {"summary": await summary.inner_text(), "statuses": _statuses(page, QUEUE)[s0:],
              "browser": [x["account"] for x in bodies], "of_wire": sent(), "of_500s": of_500s() - f0,
              "text_disabled": await ta.is_disabled(), "all_models_disabled": await all_box.is_disabled(),
              "start_over": await page.get_by_role("button", name="Start over").count()}
    await ui.shot(ctx, page, "mass-partial-failure")
    if not round1["text_disabled"]:
        await ta.fill(MASS_RETRY_TEXT + EDIT)  # the operator edits between rounds; the lock must prevent it
    others = set(creators) - {failing}
    chk(MASS_PARTIAL, round1["summary"] == f"Fan-out results — {n - 1}/{n} succeeded" and n == len(creators)
        and sorted(round1["browser"]) == sorted(creators) and sorted(round1["statuses"]) == [200] * (n - 1) + [502]
        and round1["of_500s"] == 1 and {a for a, v in round1["of_wire"].items() if v} == others
        and round1["text_disabled"] and round1["all_models_disabled"] and round1["start_over"] == 1,
        included=included, failing=failing, **round1)

    b0, s1 = len(bodies), len(_statuses(page, QUEUE))
    await send.click(timeout=10_000)  # the retry (confirm() accepted)
    await _until(lambda: len(sent().get(failing, ())) >= 1 and len(_statuses(page, QUEUE)) > s1, 15)
    await page.wait_for_timeout(1000)  # a re-send to every model would land within this
    closed = await ta.count() == 0
    await ui.shot(ctx, page, "mass-retry-done")
    retry, wire = bodies[b0:], sent()
    (ctx.out / "mass-retry-bodies.json").write_text(json.dumps({"browser": bodies, "of_wire": wire}, indent=2))
    chk(MASS_RETRY, [x["account"] for x in retry] == [failing]
        and [x["body"].get("text") for x in retry] == [MASS_RETRY_TEXT]
        and _statuses(page, QUEUE)[s1:] == [200] and closed
        and {a: v for a, v in wire.items() if v} == {a: [MASS_RETRY_TEXT] for a in creators},
        retried=[{"account": x["account"], "text": x["body"].get("text")} for x in retry], want=[failing],
        relay_statuses=_statuses(page, QUEUE)[s1:], modal_closed=closed, of_wire=wire)
    await page.unroute(lambda u: urlsplit(u).path == QUEUE)


async def _mass_unsend(ctx, page, chk) -> None:
    """Section 1c: a model chip + a bulk action unsends exactly that Creator's matching rows."""
    creators = [c["id"] for c in ctx.world.data["creators"]]
    picked, other = creators[0], creators[1]
    nick = ctx.world.data["creators"][0]["nickname"]
    copies = ctx.param("unsend_copies", ctx.world.size["state_reducers_unsend_copies"])
    seeded = mass_broadcast_cache.seed(ctx.world, [picked, other], copies)
    # The spec (massUnsendRules.ts `isFreeTextOld` + `isActionable`, in the chip's scope), from the seed.
    want = sorted([a, q] for (a, q), r in seeded.items()
                  if a == picked and r["free"] and not r["media"] and r["hours"] >= 4
                  and r["can_unsend"] and not r["canceled"])
    n0 = {a: len(v) for a, v in _wire(ctx, "unsends").items()}

    def sent() -> list[dict]:  # OF's wire unsends since this section began
        return [{"account": a, "id": x["id"]} for a, v in _wire(ctx, "unsends").items() for x in v[n0.get(a, 0):]]

    browser: list[str] = []

    def on_request(req) -> None:
        if req.method == "DELETE" and UNSEND.fullmatch(urlsplit(req.url).path):
            browser.append(req.url)

    page.on("request", on_request)
    try:
        await page.goto(f"{ctx.app}/growth/smart-messages?tab=mass", wait_until="domcontentloaded")
        await page.get_by_text("slop free text 1.0", exact=True).first.wait_for(timeout=WAIT_MS)
        await page.get_by_role("button", name=nick, exact=True).click(timeout=10_000)
        await page.get_by_text("slop free text 1.0", exact=True).first.wait_for(state="detached", timeout=10_000)
        bulk = page.get_by_role("button", name=re.compile(r"^Unsend free text >4h \(\d+\)$"))
        await bulk.wait_for(timeout=10_000)
        label = await bulk.inner_text()
        listed = await page.locator("tbody tr").count()
        await _painted(page)
        await ui.shot(ctx, page, "mass-bulk-unsend-trigger")
        await bulk.click(timeout=10_000)  # confirm() accepted (the page's dialog handler)
        await _until(lambda: len(sent()) >= len(want), 60)
        await page.get_by_role("button", name=re.compile(r"^Unsend free text >4h \(0\)$")).wait_for(timeout=30_000)
        await page.wait_for_timeout(1_000)  # a pick past the expected rows would land within this
        await _painted(page)
        await ui.shot(ctx, page, "mass-bulk-unsend-settled")
        listed_after = await page.locator("tbody tr").count()
    finally:
        page.remove_listener("request", on_request)
    con = ctx.world.sql()
    db = {(a, q): (bool(c), bool(u)) for a, q, c, u in con.execute(
        "SELECT account_id, queue_id, is_canceled, can_unsend FROM mass_broadcast_cache WHERE queue_id >= ?",
        (mass_broadcast_cache.ID_BASE,)).fetchall()}
    con.close()
    flipped = sorted([a, q] for (a, q), (c, _u) in db.items() if c and not seeded[(a, q)]["canceled"])
    unflipped = sorted([a, q] for (a, q), r in seeded.items() if r["canceled"] and not db[(a, q)][0])
    wire = sorted([x["account"], x["id"]] for x in sent())
    statuses = [st for st, url in page.slop["statuses"] if UNSEND.fullmatch(urlsplit(url).path)]
    browser_ids = sorted(int(UNSEND.fullmatch(urlsplit(u).path).group(1)) for u in browser)
    n = len(want)
    detail = {"chip": nick, "picked": picked, "other": other, "button": label, "rows_listed": listed,
              "rows_listed_after": listed_after, "want": want, "of_wire": wire, "db_flipped": flipped,
              "db_unflipped_canceled": unflipped, "browser_deletes": browser_ids, "relay_statuses": statuses}
    (ctx.out / "mass-bulk-unsend.json").write_text(json.dumps(detail, indent=1))
    chk(MASS_BULK_UNSEND, n > 0 and label == f"Unsend free text >4h ({n})" and wire == want and flipped == want
        and browser_ids == sorted(q for _a, q in want) and statuses == [200] * n and not unflipped,
        **{k: v for k, v in detail.items() if k not in ("want", "of_wire", "db_flipped")},
        want_n=n, of_wire_n=len(wire), flipped_n=len(flipped),
        of_wire_extra=[x for x in wire if x not in want][:10], of_wire_missing=[x for x in want if x not in wire][:10],
        db_extra=[x for x in flipped if x not in want][:10], db_missing=[x for x in want if x not in flipped][:10])


async def _post(ctx, page, chk) -> None:
    bodies: list[dict] = []
    creators = [c["id"] for c in ctx.world.data["creators"]]
    fail_once = {creators[1]}  # its first create is answered 500, picked from the seed

    async def posts(route):
        if route.request.method != "POST":
            return await route.fallback()
        account = route.request.headers.get("x-account-id")
        failed = account in fail_once
        fail_once.discard(account)
        bodies.append({"body": route.request.post_data_json, "account": account, "failed": failed})
        if failed:  # OnlyFans failing one model of the fan-out, answered at the browser's wire
            return await route.fulfill(status=500, content_type="application/json", body=json.dumps({"detail": "slop: OF 500"}))
        await route.fallback()  # ui.py's THROUGH: on to the relay, whose OFClient reaches OF's wire

    def on_wire() -> list[dict]:
        return [{"account": a, "text": x.get("text"), "price": x.get("price")}
                for a, v in _wire(ctx, "posts").items() for x in v]

    await page.route(lambda u: urlsplit(u).path == POSTS, posts)
    await page.goto(f"{ctx.app}/analytics/message-dashboard?tab=myfeed", wait_until="domcontentloaded")
    await page.get_by_role("button", name="New post", exact=True).click(timeout=WAIT_MS)
    ta = page.get_by_placeholder("What's on your feed today?")
    await ta.wait_for(timeout=WAIT_MS)
    btn = page.get_by_role("button", name="Post", exact=True)
    price = page.get_by_placeholder("0 (free)")
    await ta.fill(POST_TEXT)
    await price.fill("10")
    await page.wait_for_timeout(300)
    priced = await _button_state(btn)
    await ui.shot(ctx, page, "post-priced-trigger")
    chk(POST_PRICED, priced == {"disabled": True, "title": "A paid post needs at least one image"}, button=priced)

    await page.get_by_label(re.compile(r"Post from ALL models")).check(timeout=10_000)
    await page.wait_for_timeout(300)
    price_rows = await price.count()
    on = await _button_state(btn)
    included = await page.get_by_text(re.compile(r"^\(\d+/\d+ included\)$")).inner_text()
    await ui.shot(ctx, page, "post-all-models")
    chk(POST_ALL, price_rows == 0 and on == {"disabled": False, "title": None}, price_inputs=price_rows, button=on,
        included=included)

    n_included = int(re.match(r"\((\d+)/", included).group(1))
    await btn.click(timeout=10_000)  # confirm() accepted
    await _until(lambda: len(bodies) >= n_included and len(on_wire()) >= n_included - 1
                 and len(_statuses(page, POSTS)) >= n_included, 20)
    await page.wait_for_timeout(500)
    first, wire_1, statuses_1 = list(bodies), on_wire(), _statuses(page, POSTS)
    summary = page.get_by_text(re.compile(r"^Fan-out results — \d+/\d+ succeeded$"))
    summary_1 = await summary.inner_text(timeout=10_000) if await summary.count() else None
    locked = {"text_disabled": await ta.is_disabled(),
              "all_models_disabled": await page.get_by_label(re.compile(r"Post from ALL models")).is_disabled()}
    await ui.shot(ctx, page, "post-partial-failure")
    if not locked["text_disabled"]:
        await ta.fill(POST_TEXT + EDIT)  # the operator edits between rounds; the lock must prevent it
    passed = set(creators) - {creators[1]}
    chk(POST_BODIES, len(first) == n_included == len(creators)
        and {x["account"] for x in first} == set(creators)
        and all(x["body"].get("price") == 0 and x["body"].get("text") == POST_TEXT and x["body"].get("media_files") == []
                and "previews" not in x["body"] and "tagged_users" not in x["body"] for x in first)
        and sorted(statuses_1) == sorted([200] * (n_included - 1) + [500])
        and len(wire_1) == n_included - 1 and {x["account"] for x in wire_1} == passed
        and all(x["text"] == POST_TEXT and not x["price"] for x in wire_1),
        posts=len(first), included=n_included, bodies=[x["body"] for x in first][:5], relay_statuses=statuses_1,
        of_wire=wire_1)

    await btn.click(timeout=10_000)  # the retry, whatever the first round answered
    await _until(lambda: len(bodies) >= n_included + 1 and len(on_wire()) >= n_included, 10)
    await page.wait_for_timeout(1000)  # a re-post to every model would land within this
    retry = bodies[len(first):]
    wire = on_wire()
    closed = await ta.count() == 0
    await ui.shot(ctx, page, "post-retry-done")
    (ctx.out / "post-bodies.json").write_text(json.dumps({"browser": bodies, "of_wire": _wire(ctx, "posts")}, indent=2))
    chk(POST_RETRY, summary_1 == f"Fan-out results — {n_included - 1}/{n_included} succeeded"
        and [x["account"] for x in retry] == [creators[1]] and not retry[0]["failed"] and closed
        and len(wire) == n_included and {x["account"] for x in wire} == set(creators),
        first_summary=summary_1, retried=[x["account"] for x in retry], want=[creators[1]], modal_closed=closed,
        of_wire=wire)
    chk(POST_LOCKED, locked["text_disabled"] and locked["all_models_disabled"] and bool(retry)
        and all(x["body"].get("text") == POST_TEXT for x in retry)
        and [x["text"] for x in wire if x["account"] == creators[1]] == [POST_TEXT],
        **locked, retry_texts=[x["body"].get("text") for x in retry],
        of_wire_failed_creator=[x["text"] for x in wire if x["account"] == creators[1]])
    await page.unroute(lambda u: urlsplit(u).path == POSTS)


TICKED_DUPES = """() => {
  const modal = [...document.querySelectorAll('[role="dialog"][aria-labelledby]')]
    .find((d) => document.getElementById(d.getAttribute('aria-labelledby'))?.textContent === 'Duplicate media');
  return modal ? [...modal.querySelectorAll('button[aria-pressed="true"]:not([disabled]) > img[alt^="media "]')]
    .map((img) => Number(img.alt.slice(6))) : [];
}"""


async def _hide_ok(route, body: dict) -> None:
    """Answer a duplicates hide in the real route's shape (`hidden` = every id sent, `refused` empty); it never
    reaches anything, not even the temp relay."""
    ids = [int(x) for x in body.get("media_ids") or []]
    await route.fulfill(status=200, content_type="application/json", body=json.dumps(
        {"account_id": body.get("account_id"), "hidden": len(ids), "hidden_ids": ids, "refused": {}}))


async def _open_duplicates(ctx, page, creator, scan: str) -> None:
    """Vault Pro > extras > Duplicates on `creator`, until the scan line reads `scan`."""
    await page.goto(f"{ctx.app}/growth/vault-pro", wait_until="domcontentloaded")
    await ui.pick_creator(page, creator["nickname"], timeout_ms=WAIT_MS)
    await page.get_by_role("button", name=re.compile(r"extras$")).first.click(timeout=WAIT_MS)
    dup_btn = page.get_by_role("button", name="Duplicates", exact=True)
    await page.wait_for_function("(b) => b && !b.disabled", arg=await dup_btn.element_handle(), timeout=WAIT_MS)
    await dup_btn.click()
    await page.get_by_text(scan).wait_for(timeout=WAIT_MS)


async def _dupes(ctx, page, chk) -> None:
    hides: list[dict] = []

    async def hide(route):
        body = route.request.post_data_json or {}
        hides.append(body)
        await _hide_ok(route, body)

    await page.route(lambda u: urlsplit(u).path == "/admin/vault-ai/duplicates/hide", hide)
    await _open_duplicates(ctx, page, ctx.world.data["creators"][0], "1 sets · 2 copies")
    await page.get_by_role("button", name=re.compile(r"^Remove 2 copies from")).click(timeout=10_000)
    yes = page.get_by_role("button", name="Yes, remove them")
    await yes.wait_for(timeout=10_000)
    await ui.shot(ctx, page, "dupes-confirming")
    await page.get_by_label("Match strictness").select_option("4")
    await page.get_by_text("2 sets · 3 copies").wait_for(timeout=30_000)
    await page.wait_for_timeout(500)
    yes_after = await yes.count()
    remove_back = await page.get_by_role("button", name=re.compile(r"^Remove 3 copies from")).count()
    await ui.shot(ctx, page, "dupes-threshold-changed")
    chk(DUPES_CONFIRM, yes_after == 0 and remove_back == 1, yes_remove_buttons=yes_after,
        remove_3_buttons=remove_back)

    # The operator confirms what the screen shows (an armed Yes is clicked as it stands).
    before_yes = len(hides)
    if remove_back:
        await page.get_by_role("button", name=re.compile(r"^Remove 3 copies from")).click(timeout=10_000)
    await yes.wait_for(timeout=10_000)
    shown = await page.evaluate(TICKED_DUPES)
    strictness = await page.get_by_label("Match strictness").input_value()
    removes = await page.get_by_text(re.compile(r"^Removes \d+ from your real vault")).inner_text()
    await ui.shot(ctx, page, "dupes-yes-armed")
    await yes.click(timeout=10_000)
    banner = page.get_by_text(re.compile(r"Removed \d+ cop"))
    await banner.wait_for(timeout=15_000)
    await page.wait_for_timeout(500)
    banner_text = await banner.inner_text()
    await ui.shot(ctx, page, "dupes-removed")
    (ctx.out / "dupes-hide-bodies.json").write_text(json.dumps(hides, indent=2))
    sent = hides[0] if len(hides) == 1 else {}
    sent_ids = [int(x) for x in sent.get("media_ids") or []]
    chk(DUPES_HIDE, before_yes == 0 and len(hides) == 1 and len(shown) == 3 and sorted(sent_ids) == sorted(shown)
        and len(set(sent_ids)) == len(sent_ids) and str(sent.get("threshold")) == strictness == "4",
        hides_before_yes=before_yes, hide_posts=len(hides), sent_ids=sent_ids, sent_threshold=sent.get("threshold"),
        shown_ticked=shown, shown_strictness=strictness, footer=removes, banner=banner_text)


async def _dupes_partial(ctx, page, chk) -> None:
    """Creator 2: all PARTIAL_COPIES copies removed in one confirm; the first batch is answered 200, the second 500."""
    hides: list[dict] = []

    async def hide(route):
        body = route.request.post_data_json or {}
        hides.append(body)
        if len(hides) == 1:
            return await _hide_ok(route, body)
        await route.fulfill(status=500, content_type="application/json", body=json.dumps({"detail": PARTIAL_FAIL}))

    hide_path = lambda u: urlsplit(u).path == "/admin/vault-ai/duplicates/hide"  # noqa: E731
    await page.route(hide_path, hide)
    try:
        await _open_duplicates(ctx, page, ctx.world.data["creators"][2], f"1 sets · {PARTIAL_COPIES} copies")
        await page.get_by_role("button", name=re.compile(rf"^Remove {PARTIAL_COPIES} copies from")).click(timeout=10_000)
        await page.get_by_role("button", name="Yes, remove them").click(timeout=10_000)
        # The hide settles in the done panel, or as an error line of its own (the failure alone).
        done_line = page.get_by_text(re.compile(r"^Removed \d+ "))
        error_line = page.get_by_text(PARTIAL_FAIL, exact=True)
        await done_line.or_(error_line).first.wait_for(timeout=30_000)
        lines = await done_line.all_inner_texts()
        errors = await error_line.all_inner_texts()
        await ui.shot(ctx, page, "dupes-partial-failed")
        await page.get_by_role("dialog", name="Duplicate media").get_by_role(
            "button", name="Done", exact=True).click(timeout=10_000)
    finally:
        await page.unroute(hide_path, hide)
    sizes = [len(h.get("media_ids") or []) for h in hides]
    want = f"Removed {HIDE_BATCH} of {PARTIAL_COPIES}, then failed: {PARTIAL_FAIL}"
    shown = [t.strip() for t in lines]
    chk(DUPES_PARTIAL, sizes == [HIDE_BATCH, PARTIAL_COPIES - HIDE_BATCH] and shown == [want] and not errors,
        batches=sizes, shown=shown, want=want, error_lines=errors[:3])


GROUP_REG = """(id) => { try { return JSON.parse(localStorage.getItem('chatterly:group-tab:' + id)); }
  catch (e) { return null; } }"""
# Post each add in one task, back to back (one add is a burst of one); per add: its ack and the round
# trip in the sender's page (post -> ack received), or null if no ack came within 5 s.
SEND_ADDS = """async ([tabId, accountId, fanIds]) => {
  const ch = new BroadcastChannel('chatterly-group');
  const reqIds = fanIds.map((_, i) => 'slop-' + i + '-' + Math.random().toString(36).slice(2));
  const sent = {}, got = {};
  const done = new Promise((res) => {
    ch.onmessage = (e) => {
      const m = e.data;
      if (!m || m.type !== 'add-ack' || !(m.reqId in sent) || (m.reqId in got)) return;
      got[m.reqId] = { ok: m.ok, ms: performance.now() - sent[m.reqId] };
      if (Object.keys(got).length === reqIds.length) res();
    };
    setTimeout(res, 5000);
  });
  reqIds.forEach((reqId, i) => {
    sent[reqId] = performance.now();
    ch.postMessage({ type: 'add', tabId, reqId, accountId, fanId: fanIds[i] });
  });
  await done; ch.close();
  return reqIds.map((r) => got[r] || null);
}"""


async def _group(ctx, page, chk) -> None:
    creator = ctx.world.data["creators"][0]
    aid = creator["id"]
    fans = [f["id"] for f in ctx.world.data["fans"][aid][:20]]
    tabs = {}
    for key, held in (("a", fans[:8]), ("b", fans[8:9]), ("c", fans[10:15])):
        p = await page.context.new_page()
        await p.goto(f"{ctx.app}/group?slots=" + ",".join(f"{aid}:{f}" for f in held), wait_until="domcontentloaded")
        tabs[key] = p
    ids = {}
    for key, p in tabs.items():
        await p.wait_for_function("() => !!sessionStorage.getItem('chatterly:group-tab-id')", timeout=WAIT_MS)
        ids[key] = await p.evaluate("() => sessionStorage.getItem('chatterly:group-tab-id')")
    # The sender: a same-origin document with no app code (a static asset). next dev full-reloads open app
    # pages when /group first compiles, which killed an evaluate on the owner's page mid-call.
    sender = await page.context.new_page()
    await sender.goto(f"{ctx.app}/icon.svg", wait_until="load")
    tabs["sender"] = sender

    async def registry(key: str) -> list:
        reg = await sender.evaluate(GROUP_REG, ids[key])
        return list((reg or {}).get("slots", []))

    async def slots(key: str) -> list:
        return [(s["accountId"], str(s["fanId"])) for s in await registry(key)]

    async def settle(key: str, n: int, timeout_s: float = 30) -> list:
        t_end = asyncio.get_event_loop().time() + timeout_s
        got = await slots(key)
        while len(got) != n and asyncio.get_event_loop().time() < t_end:
            await asyncio.sleep(0.2)
            got = await slots(key)
        return got

    for key, n in (("a", 8), ("b", 1), ("c", 5)):
        await settle(key, n)

    ack_ms: list[float] = []

    async def send(key: str, fan_ids: list) -> list:
        acks = await sender.evaluate(SEND_ADDS, [ids[key], aid, fan_ids])
        ack_ms.extend(a["ms"] for a in acks if a)
        return acks

    cases = []
    for label, key, fan in (("full tab, new fan", "a", fans[9]), ("tab with room, new fan", "b", fans[9]),
                            ("held fan as a string id", "b", str(fans[8]))):
        before = await slots(key)
        ack = (await send(key, [fan]))[0]
        await sender.wait_for_timeout(800)  # the registry write follows the render
        after = await slots(key)
        landed = (aid, str(fan)) in after
        cases.append({"case": label, "ok": (ack or {}).get("ok"), "landed": landed, "before": len(before),
                      "after": len(after), "dupes": len(after) - len(set(after))})
    await tabs["b"].bring_to_front()
    await ui.shot(ctx, tabs["b"], "group-tab-b")
    want = [(False, False, 8, 8), (True, True, 1, 2), (True, True, 2, 2)]
    got = [(c["ok"], c["landed"], c["before"], c["after"]) for c in cases]
    chk(GROUP_ACK, got == want and all(c["ok"] is c["landed"] and c["dupes"] == 0 for c in cases),
        cases=cases, tab_ids=ids)

    # A Fansly-style fan: acked, held, and still held as the same string after the tab reloads.
    snow_ack = (await send("b", [SNOWFLAKE]))[0]
    before_reload = await settle("b", 3, 10)
    await tabs["b"].reload(wait_until="domcontentloaded")
    await tabs["b"].wait_for_function("() => !!sessionStorage.getItem('chatterly:group-tab-id')", timeout=WAIT_MS)
    after_reload = await settle("b", 3)
    held = [s for s in await registry("b") if s.get("accountId") == aid and str(s.get("fanId")) == SNOWFLAKE]
    stored = await tabs["b"].evaluate("() => JSON.parse(sessionStorage.getItem('chatterly:group-slots') || '[]')")
    await ui.shot(ctx, tabs["b"], "group-tab-b-reloaded")
    chk(GROUP_FANSLY, (snow_ack or {}).get("ok") is True and (aid, SNOWFLAKE) in before_reload
        and len(held) == 1 and held[0]["fanId"] == SNOWFLAKE and len(after_reload) == 3
        and len(set(after_reload)) == 3 and {"accountId": aid, "fanId": SNOWFLAKE} in stored,
        ack=snow_ack, before_reload=before_reload, after_reload=after_reload, registry_snowflake=held,
        session_storage=stored)

    # A burst into tab c (5 held, room for 3), posted in one task: new, new, held-as-string, new, new, new.
    burst = [fans[15], fans[16], str(fans[10]), fans[17], fans[18], fans[19]]
    await tabs["c"].bring_to_front()
    await ui.shot(ctx, tabs["c"], "group-burst-trigger")
    before = await slots("c")
    acks = await send("c", burst)
    after = await settle("c", 8, 10)
    await sender.wait_for_timeout(800)  # a late extra slot (an add acked after the fact) would show here
    after = await slots("c")
    await ui.shot(ctx, tabs["c"], "group-burst-settled")
    oks = [(a or {}).get("ok") for a in acks]
    landed = [(aid, str(f)) in after for f in burst]
    chk(GROUP_BURST, oks == landed == [True, True, True, True, False, False] and len(after) == 8
        and len(set(after)) == 8 and all(x in after for x in before),
        acks=oks, landed=landed, before=len(before), after=len(after), dupes=len(after) - len(set(after)))

    n_sent = 3 + 1 + len(burst)
    worst = max(ack_ms) if ack_ms else None
    srt = sorted(ack_ms)
    ctx.metric("group_ack_ms", {"n": len(ack_ms), "p50": srt[len(srt) // 2] if srt else None, "max": worst,
                                "all": [round(x, 1) for x in ack_ms]})
    chk(GROUP_ACK_MS, len(ack_ms) == n_sent and worst is not None and worst <= ACK_BUDGET_MS,
        budget=True, acks=len(ack_ms), sent=n_sent, max_ms=round(worst or 0, 1),
        p50_ms=round(srt[len(srt) // 2], 1) if srt else None, budget_ms=ACK_BUDGET_MS)
    for p in tabs.values():
        await ui.close_popup(page, p)  # their held /api/of/ calls aborted, not resumed into the relay
    await page.bring_to_front()


async def _nudge(ctx, page, chk) -> None:
    aid = ctx.world.data["creators"][0]["id"]
    before = (await ctx.owner.get(f"/admin/nudge-config?account_id={aid}")).json()
    eff = {**(before.get("defaults") or {}), **(before.get("config") or {})}
    delay_want = int(eff.get("delay_minutes", 4)) + 5
    jitter_want = int(eff.get("jitter_minutes", 3)) + 4
    is_nudge = lambda u: urlsplit(u).path == "/admin/nudge-config"  # noqa: E731

    async def stored(acc: str) -> tuple[dict, dict]:  # (the route's config, the account_ai_config row's)
        route = (await ctx.owner.get(f"/admin/nudge-config?account_id={acc}")).json().get("config") or {}
        con = ctx.world.sql()
        row = con.execute("SELECT nudge_config_json FROM account_ai_config WHERE account_id=?", (acc,)).fetchone()
        con.close()
        return route, json.loads(row[0]) if row and row[0] else {}

    async with held(page, is_nudge, "PUT") as hold:
        await _open_create_message(ctx, page, re.compile(r"^Nudge"))
        # By its heading, not its Delay field: the form is not drawn while the tab waits for a fresh config.
        dialog = page.get_by_role("dialog").filter(has=page.get_by_role("heading", name="Nudge online", exact=True))
        delay = dialog.get_by_label("Delay (min)", exact=True)
        jitter = dialog.get_by_label("Jitter (min)", exact=True)
        await delay.wait_for(timeout=WAIT_MS)
        save = dialog.get_by_role("button", name=re.compile(r"^(Create automation|Save changes)$")).first
        await page.wait_for_function("(b) => b && !b.disabled", arg=await save.element_handle(), timeout=WAIT_MS)
        await delay.fill(str(delay_want))
        await save.click()
        await asyncio.wait_for(hold.seen.wait(), 15)
        await jitter.fill(str(jitter_want))
        await ui.shot(ctx, page, "nudge-edit-during-save")
        await release_settled(page, hold, refetch="/admin/nudge-config", save=save, timeout_ms=30_000)
        shown = {"delay": await delay.input_value(), "jitter": await jitter.input_value()}
        await ui.shot(ctx, page, "nudge-after-refetch")
        chk(NUDGE_KEEP, shown == {"delay": str(delay_want), "jitter": str(jitter_want)}, shown=shown,
            want={"delay": delay_want, "jitter": jitter_want})

        save = dialog.get_by_role("button", name=re.compile(r"^(Create automation|Save changes)$")).first
        async with page.expect_response(lambda r: r.request.method == "PUT" and is_nudge(r.url),
                                        timeout=30_000) as put2:
            await save.click(timeout=10_000)
        status = (await put2.value).status
    aid = (hold.bodies[0] or {}).get("account_id") or aid  # the editor's own account (the page's pick)
    after, row_cfg = await stored(aid)
    pick = lambda c: {"delay": c.get("delay_minutes"), "jitter": c.get("jitter_minutes")}  # noqa: E731
    want = {"delay": delay_want, "jitter": jitter_want}
    chk(NUDGE_STORED, status == 200 and pick(after) == want and pick(row_cfg) == want, put=status,
        route=pick(after), db=pick(row_cfg), want=want, account=aid)

    # Save again and switch Creator while the PUT is held; let it land on the other one.
    other = next(c["id"] for c in ctx.world.data["creators"] if c["id"] != aid)
    o = (await ctx.owner.get(f"/admin/nudge-config?account_id={other}")).json()
    other_delay = str({**(o.get("defaults") or {}), **(o.get("config") or {})}.get("delay_minutes", 4))
    delay3 = delay_want + 1
    picker = dialog.locator("select").filter(has=page.locator(f'option[value="{other}"]'))
    async with held(page, is_nudge, "PUT") as hold:
        await delay.fill(str(delay3))
        await save.click(timeout=10_000)
        await asyncio.wait_for(hold.seen.wait(), 15)
        await picker.select_option(other)
        other_shown = await _wait_value(delay, other_delay, 30_000)
        status3 = await release_settled(page, hold, timeout_ms=30_000)
    await page.wait_for_timeout(1500)
    saved_on_other = await dialog.get_by_text(re.compile(r"^Saved\.$|Saved ✓")).count()
    await ui.shot(ctx, page, "nudge-switch-landed")
    await picker.select_option(aid)
    back = await _wait_value(delay, str(delay3), 30_000)
    await ui.shot(ctx, page, "nudge-switch-back")
    chk(NUDGE_SWITCH, status3 == 200 and other_shown == other_delay and saved_on_other == 0 and back == str(delay3),
        put=status3, other=other, other_delay=other_shown, want_other=other_delay,
        saved_on_other=saved_on_other, back=back, want_back=delay3)

    # A landed save, then a switch to a Creator whose config GET fails: no config ever arrives,
    # so only the pick can clear the first Creator's "Saved".
    third = next(c["id"] for c in ctx.world.data["creators"] if c["id"] not in (aid, other))

    async def down_wire(route):  # the third Creator's config GET answers 500
        req = route.request
        if req.method == "GET" and parse_qs(urlsplit(req.url).query).get("account_id") == [third]:
            return await route.fulfill(status=500, content_type="application/json", body='{"detail":"slop: down"}')
        await route.fallback()

    await page.route(is_nudge, down_wire)
    saved_q = dialog.get_by_text(re.compile(r"^Saved\.$|Saved ✓"))
    async with page.expect_response(lambda r: r.request.method == "PUT" and "/admin/nudge-config" in r.url,
                                    timeout=30_000) as put4:
        await save.click(timeout=10_000)
    status4 = (await put4.value).status
    await saved_q.first.wait_for(timeout=WAIT_MS)
    saved_before = await saved_q.count()
    await picker.select_option(third)
    failed_note = page.get_by_text(re.compile(r"Couldn.t load this account's nudge settings"))
    await failed_note.first.wait_for(timeout=30_000)
    await page.wait_for_timeout(500)
    saved_on_third = await saved_q.count()
    await ui.shot(ctx, page, "nudge-stale-saved")
    chk(NUDGE_STALE, status4 == 200 and saved_before > 0 and saved_on_third == 0,
        put=status4, saved_before=saved_before, saved_on_third=saved_on_third, third=third)
    await page.unroute(is_nudge, down_wire)

    # A -> B -> A while A's save is in flight: back on A the cache holds A's PRE-save config. The PUT is let
    # through while A's refetch is held at the browser's wire (a slow read; bypass, declared) until "Saving…" is
    # gone and painted, and Jitter typed if a form is drawn: a form seeded from that cache would keep Delay at its
    # pre-save value under the edit, and the next Save would write it back over the first save.
    is_a_get = lambda u: is_nudge(u) and parse_qs(urlsplit(u).query).get("account_id") == [aid]  # noqa: E731
    await picker.select_option(aid)
    await page.wait_for_function("(b) => b && !b.disabled", arg=await save.element_handle(), timeout=30_000)
    pre = {"delay": int(await delay.input_value()), "jitter": int(await jitter.input_value())}
    aba_want = {"delay": pre["delay"] + 2, "jitter": pre["jitter"] + 1}
    async with held(page, is_nudge, "PUT") as hold:
        await delay.fill(str(aba_want["delay"]))
        await save.click(timeout=10_000)
        await asyncio.wait_for(hold.seen.wait(), 15)
        await picker.select_option(other)
        await _wait_value(delay, other_delay, 30_000)
        await picker.select_option(aid)
        await page.wait_for_timeout(500)  # a remount refetch, if A's cache went stale, is in flight before the hold
        back_mid_save = await delay.count()
        await ui.shot(ctx, page, "nudge-aba-back-mid-save")
        async with held(page, is_a_get, "GET") as get_hold:
            async with page.expect_response(lambda r: r.request.method == "GET" and is_a_get(r.url),
                                            timeout=30_000) as refetched:
                async with page.expect_response(lambda r: r.request.method == "PUT" and is_nudge(r.url),
                                                timeout=30_000) as put_a:
                    hold.release.set()
                status_a = (await put_a.value).status
                await asyncio.wait_for(get_hold.seen.wait(), 15)
                await dialog.get_by_role("button", name="Saving…", exact=True).first.wait_for(
                    state="hidden", timeout=30_000)
                await _painted(page)
                if await jitter.count():  # a form seeded from the pre-save cache (the fault)
                    await jitter.fill(str(aba_want["jitter"]), timeout=10_000)
                get_hold.release.set()  # no form while the refetch is held: typed below, once it landed
            await refetched.value
        if await jitter.input_value(timeout=30_000) != str(aba_want["jitter"]):
            await jitter.fill(str(aba_want["jitter"]), timeout=30_000)
        await page.wait_for_function("(b) => b && !b.disabled", arg=await save.element_handle(), timeout=30_000)
        await _painted(page)
        shown_aba = {"delay": await delay.input_value(), "jitter": await jitter.input_value()}
        await ui.shot(ctx, page, "nudge-aba-after-refetch")
        async with page.expect_response(lambda r: r.request.method == "PUT" and is_nudge(r.url),
                                        timeout=30_000) as put_b:
            await save.click(timeout=10_000)
        status_b = (await put_b.value).status
    route_aba, db_aba = await stored(aid)
    aba = {"account": aid, "pre": pre, "want": aba_want, "back_mid_save_delay_fields": back_mid_save,
           "shown_after_refetch": shown_aba, "put1": status_a, "put2": status_b, "put_bodies": hold.bodies,
           "route": pick(route_aba), "account_ai_config_row": db_aba}
    (ctx.out / "nudge-aba.json").write_text(json.dumps(aba, indent=2))
    chk(NUDGE_ABA, back_mid_save == 0 and status_a == 200 and status_b == 200
        and shown_aba == {"delay": str(aba_want["delay"]), "jitter": str(aba_want["jitter"])}
        and pick(route_aba) == aba_want and pick(db_aba) == aba_want,
        account=aid, pre=pre, want=aba_want, back_mid_save_delay_fields=back_mid_save,
        shown_after_refetch=shown_aba, put1=status_a, put2=status_b, route=pick(route_aba), db=pick(db_aba))

    # A tab closed mid-save (lib/pendingDraft.ts: the draft is kept in localStorage until a PUT acks it), each on
    # pages of their own (later sections reuse `page`). Bypasses, declared: closing a page is the operator closing the
    # tab (ui.close_popup: its held /api/of/ reads aborted first). A: the Save PUT is held at the browser's wire, then
    # aborted there, THEN the tab closed (Chromium lets a request still paused at the Fetch domain through when its
    # page closes), so it never reaches the relay: what A drives is "the PUT failed at the wire, then the tab closed".
    # A tab unmounted while its PUT is still in flight is vitest's (NudgeOnlineTab.draft.test.tsx). B: the PUT is
    # fetched through to the relay
    # (`route.fetch()`, the write lands) and its answer never fulfilled: the page closes while the request is still
    # paused (were Chromium to resume it at the close, it is the same body again, the same write). Each tab is
    # reopened on a new page of the same context (same localStorage, as a reopened tab).
    draft_key = f"chatterly:nudge-draft:{aid}"
    restored_rx = re.compile(r"Unsaved changes restored")

    async def read_key(p) -> dict | None:  # the kept draft, as Delay values (None: no key)
        raw = await p.evaluate("(k) => localStorage.getItem(k)", draft_key)
        e = json.loads(raw) if raw else None
        return e and {"draft_delay": (e.get("draft") or {}).get("delay_minutes"),
                      "base_delay": (e.get("base") or {}).get("delay_minutes")}

    async def open_tab():
        p = await page.context.new_page()
        await _open_create_message(ctx, p, re.compile(r"^Nudge"))
        dlg = p.get_by_role("dialog").filter(has=p.get_by_role("heading", name="Nudge online", exact=True))
        d = dlg.get_by_label("Delay (min)", exact=True)
        await d.wait_for(timeout=WAIT_MS)
        sv = dlg.get_by_role("button", name=re.compile(r"^(Create automation|Save changes)$")).first
        await p.wait_for_function("(b) => b && !b.disabled", arg=await sv.element_handle(), timeout=WAIT_MS)
        pk = dlg.locator("select").filter(has=p.locator(f'option[value="{aid}"]'))
        if await pk.count() and await pk.first.input_value() != aid:  # the editor's own account
            await pk.first.select_option(aid)
            await p.wait_for_timeout(1000)
            await p.wait_for_function("(b) => b && !b.disabled", arg=await sv.element_handle(), timeout=30_000)
        await _painted(p)
        return p, dlg, d, sv

    async def key_gone(p, secs: float = 3) -> dict | None:  # the kept draft once gone (or as it is after `secs`)
        t_end = time.monotonic() + secs
        k = await read_key(p)
        while k is not None and time.monotonic() < t_end:
            await asyncio.sleep(0.1)
            k = await read_key(p)
        return k

    class Wire:
        """The page's first nudge PUT held at its wire: `seen` once it arrived (`body`); with `fetch_first` fetched
        through to the relay (`fetched`, `relay_status`) and left unanswered; on `go` aborted (`aborted`)."""

        def __init__(self, fetch_first: bool):
            self.fetch_first = fetch_first
            self.seen, self.fetched, self.go, self.aborted = (asyncio.Event() for _ in range(4))
            self.body: dict | None = None
            self.relay_status: int | None = None

        async def handler(self, route):
            if route.request.method != "PUT" or self.seen.is_set():
                return await route.fallback()
            self.body = route.request.post_data_json
            self.seen.set()
            if self.fetch_first:
                self.relay_status = (await route.fetch()).status
                self.fetched.set()
            await self.go.wait()
            try:
                await route.abort()
            except Exception:  # noqa: BLE001 — the page is gone with its request
                pass
            self.aborted.set()

    # A: the PUT aborted at the wire, then the tab closed -> reopened, the typed Delay is back with the restored
    # note; the stored config is still the old one; Save stores it and the kept draft goes.
    route_old, row_old = await stored(aid)
    p2, dlg2, d2, s2 = await open_tab()
    closed_want = int(await d2.input_value()) + 3
    w2 = Wire(fetch_first=False)
    await p2.route(is_nudge, w2.handler)
    await d2.fill(str(closed_want))
    await s2.click(timeout=10_000)
    await asyncio.wait_for(w2.seen.wait(), 15)
    await _painted(p2)
    await ui.shot(ctx, p2, "nudge-tab-closed-trigger")
    key_held = await read_key(p2)
    w2.go.set()
    await asyncio.wait_for(w2.aborted.wait(), 15)  # aborted at the wire before the close
    await ui.close_popup(page, p2)
    route_mid, row_mid = await stored(aid)
    p3, dlg3, d3, s3 = await open_tab()
    note_a = await dlg3.get_by_text(restored_rx).count()
    shown_a = await d3.input_value()
    key_reopen = await read_key(p3)
    await ui.shot(ctx, p3, "nudge-tab-closed-restored")
    async with p3.expect_response(lambda r: r.request.method == "PUT" and is_nudge(r.url), timeout=30_000) as put_c:
        await s3.click(timeout=10_000)
    status_c = (await put_c.value).status
    await dlg3.get_by_text(re.compile(r"^Saved\.$")).first.wait_for(timeout=30_000)
    key_acked = await key_gone(p3)
    note_acked = await dlg3.get_by_text(restored_rx).count()
    await _painted(p3)
    await ui.shot(ctx, p3, "nudge-tab-closed-settled")
    route_c, row_c = await stored(aid)
    old_delay = pick(route_old)["delay"]
    tab_closed = {"account": aid, "typed_delay": closed_want, "old_delay": old_delay,
                  "held_put": pick((w2.body or {}).get("config") or {}),
                  "key_while_held": key_held, "route_after_close": pick(route_mid), "row_after_close": pick(row_mid),
                  "reopened_delay": shown_a, "restored_note": note_a, "key_on_reopen": key_reopen,
                  "put_status": status_c, "key_after_ack": key_acked, "note_after_ack": note_acked,
                  "route_after_ack": pick(route_c), "row_after_ack": pick(row_c)}
    chk(NUDGE_TAB_CLOSED, tab_closed["held_put"]["delay"] == closed_want and pick(route_mid)["delay"] == old_delay
        and pick(row_mid)["delay"] == pick(row_old)["delay"] and shown_a == str(closed_want) and note_a > 0
        and status_c == 200 and key_acked is None and note_acked == 0
        and pick(route_c)["delay"] == closed_want and pick(row_c)["delay"] == closed_want, **tab_closed)

    # B: the PUT reached the relay, its answer never reached the tab (closed) -> reopened on the stored config, no
    # restored note, the kept draft gone.
    lost_want = closed_want + 2
    w3 = Wire(fetch_first=True)
    await p3.route(is_nudge, w3.handler)
    await d3.fill(str(lost_want))
    await s3.click(timeout=10_000)
    await asyncio.wait_for(w3.fetched.wait(), 15)  # the relay answered; the tab has not
    await _painted(p3)
    await ui.shot(ctx, p3, "nudge-ack-lost-trigger")
    key_unacked = await read_key(p3)
    await ui.close_popup(page, p3)
    w3.go.set()
    route_l, row_l = await stored(aid)
    p4, dlg4, d4, _s4 = await open_tab()
    key_lost = await key_gone(p4)
    note_b = await dlg4.get_by_text(restored_rx).count()
    shown_b = await d4.input_value()
    await ui.shot(ctx, p4, "nudge-ack-lost-reopened")
    await ui.close_popup(page, p4)
    ack_lost = {"account": aid, "typed_delay": lost_want, "relay_status": w3.relay_status,
                "key_unacked": key_unacked, "route": pick(route_l), "row": pick(row_l), "reopened_delay": shown_b,
                "restored_note": note_b, "key_on_reopen": key_lost}
    (ctx.out / "nudge-draft.json").write_text(json.dumps({"tab_closed": tab_closed, "ack_lost": ack_lost}, indent=2))
    # `key_unacked` (the draft kept while the answer is pending) is evidence, not the claim: with no stash at all
    # the reopen is the same, and that is NUDGE_TAB_CLOSED's to catch.
    chk(NUDGE_ACK_LOST, w3.relay_status == 200 and pick(route_l)["delay"] == lost_want
        and pick(row_l)["delay"] == lost_want and shown_b == str(lost_want) and note_b == 0 and key_lost is None,
        **ack_lost)
    await page.bring_to_front()


ROSTER = "/admin/users/llm-key-status"
USERS = "/admin/users"


def _manage_main(page):
    """/admin/manage's own <main> (the nearest one around its "Users" heading)."""
    return page.get_by_role("heading", name="Users", exact=True).first.locator("xpath=ancestor::main[1]")


@asynccontextmanager
async def _manage(ctx, page, path: str, handler):
    """/admin/manage opened with the browser's GET of `path` answered by `handler` (any other method falls
    through); yields the page's own <main>. The route goes when the block ends, however it ends."""
    async def route(r):
        if r.request.method != "GET":
            return await r.fallback()
        await handler(r)

    match = lambda u: urlsplit(u).path == path  # noqa: E731
    await page.route(match, route)
    try:
        await page.goto(f"{ctx.app}/admin/manage", wait_until="domcontentloaded")
        yield _manage_main(page)
    finally:
        await page.unroute(match)


async def _admin(ctx, page, chk, master) -> None:
    async def empty(route):
        await route.fulfill(status=200, content_type="application/json", body=json.dumps({"agencies": []}))

    n = len((await master.get(USERS)).json())
    async with _manage(ctx, page, ROSTER, empty) as main:
        box = main.get_by_label(re.compile(LIVE_ONLY))
        await box.wait_for(timeout=WAIT_MS)
        await box.check()
        label = main.locator("label").filter(has_text=LIVE_ONLY)
        await page.wait_for_timeout(500)
        text = await label.inner_text()
        await ui.shot(ctx, page, "admin-live-only-empty")
    m = re.search(r"\((\d+) of (\d+)\)", text)
    chk(ADMIN_EMPTY, n >= 2 and m is not None and (int(m.group(1)), int(m.group(2))) == (0, n),
        label=text, users=n)


async def _admin_roster(ctx, page, chk, master) -> None:
    async def forbidden(route):
        await route.fulfill(status=403, content_type="application/json",
                            body=json.dumps({"detail": "slop: roster forbidden"}))

    names = [u["username"] for u in (await master.get(USERS)).json()]
    async with _manage(ctx, page, ROSTER, forbidden) as main:
        box = main.get_by_label(re.compile(LIVE_ONLY))
        await box.wait_for(timeout=WAIT_MS)
        await main.get_by_role("alert").filter(has_text="Key status unavailable").wait_for(timeout=30_000)
        await ui.shot(ctx, page, "admin-roster-failed-trigger")
        await box.check()
        await page.wait_for_timeout(500)
        text = await main.locator("label").filter(has_text=LIVE_ONLY).inner_text()
        shown = [x for x in names if await main.get_by_text(f"@{x}", exact=True).count()]
        alerts = await main.get_by_role("alert").all_inner_texts()
        await ui.shot(ctx, page, "admin-roster-failed-settled")
        checked = await box.is_checked()
    chk(ADMIN_ROSTER_FAILED, len(names) >= 2 and "(key status unavailable — filter off)" in text
        and not re.search(r"\(\d+ of \d+\)", text) and checked and len(shown) == len(names)
        and any("Key status unavailable" in a for a in alerts),
        label=text, users=len(names), rows_shown=len(shown), alerts=alerts)


async def _admin_users(ctx, page, chk, master) -> None:
    failed: list[str] = []
    release = asyncio.Event()

    async def down(route):  # held until the trigger shot, so it shows the load in flight
        failed.append(route.request.url)
        await release.wait()
        await route.fulfill(status=502, content_type="application/json",
                            body=json.dumps({"detail": "slop: users upstream down"}))

    async with _manage(ctx, page, USERS, down) as main:
        await main.wait_for(timeout=WAIT_MS)
        t_end = asyncio.get_event_loop().time() + 30
        while not failed and asyncio.get_event_loop().time() < t_end:
            await asyncio.sleep(0.1)
        loading_bars = await main.locator(".animate-pulse").count()
        await ui.shot(ctx, page, "admin-users-failed-trigger")
        release.set()
        alert = main.get_by_role("alert")
        await alert.first.wait_for(timeout=30_000)
        await page.wait_for_timeout(1000)  # a skeleton left behind would still be drawn
        alerts = await alert.all_inner_texts()
        pulses = await main.locator(".animate-pulse").count()
        no_users = await main.get_by_text("No users registered yet.").count()
        refresh_off = await main.get_by_role("button", name=re.compile(r"Refresh")).is_disabled()
        await ui.shot(ctx, page, "admin-users-failed-settled")
    chk(ADMIN_USERS_FAILED, bool(failed) and loading_bars > 0
        and any("slop: users upstream down" in a for a in alerts) and pulses == 0 and no_users == 0 and not refresh_off,
        users_calls_failed=len(failed), loading_skeleton_bars=loading_bars, alerts=alerts, skeleton_bars=pulses,
        no_users_text=no_users,
        refresh_disabled=refresh_off)


async def _admin_gate(ctx, page, chk, master) -> None:
    """The run's owner (not the master) opens /admin/manage by URL."""
    names = [u["username"] for u in (await master.get(USERS)).json()]
    fired: list[str] = []

    def on_request(r) -> None:
        if urlsplit(r.url).path in (USERS, ROSTER):
            fired.append(urlsplit(r.url).path)

    page.on("request", on_request)
    try:
        await page.goto(f"{ctx.app}/admin/manage", wait_until="domcontentloaded")
        await ui.shot(ctx, page, "admin-gate-trigger")
        main = _manage_main(page)
        await main.wait_for(timeout=WAIT_MS)
        await main.get_by_text("master account required", exact=True).first.wait_for(timeout=30_000)
        await page.wait_for_timeout(1500)  # a read the gate let through would have fired by now
        lines = await main.get_by_text("master account required", exact=True).count()
        rows = await main.locator("li").count()
        shown = [x for x in names if await main.get_by_text(f"@{x}", exact=True).count()]
        alerts = await main.get_by_role("alert").all_inner_texts()
        await ui.shot(ctx, page, "admin-gate-settled")
    finally:
        page.remove_listener("request", on_request)
    chk(ADMIN_GATE, len(names) >= 2 and lines == 1 and rows == 0 and not shown and not alerts and not fired,
        master_required_lines=lines, rows=rows, rows_named=shown, alerts=alerts, master_reads_fired=fired)


async def _as_master(ctx, page, chk, master, name: str, fn) -> None:
    """`fn` in a context of its own signed in as `master` (closed after, however it ends); its held OF reads and
    off-host aborts land in the run's own lists, so the run's metrics count them."""
    mp = await ui._owner_page(page.context.browser, ctx, VIEWPORT, page.slop["held_of_reads"],
                              page.slop["offhost_aborted"], http=master)
    try:
        mp.context.set_default_navigation_timeout(WAIT_MS)
        await fn(ctx, mp, chk, master)
    except Exception:
        await ui.shot(ctx, mp, f"failed-{name}-master")
        raise
    finally:
        await mp.context.close()


def _seed_clock(w, employee_id: int, account_id: str) -> int:
    """One closed Clock event of the owner's Employee, 3 h ago to 2 h ago (whole minutes), as a manual
    clock-in then clock-out on Creator 0 leave it."""
    t_in = w.now.replace(second=0) - timedelta(hours=3)
    t_out = t_in + timedelta(hours=1)
    con = w.sql()
    with con:
        cid = con.execute(
            "INSERT INTO clock_events (agency_user_id, employee_id, account_id, shift_id, in_utc, out_utc, close_reason,"
            " last_seen_utc) VALUES (?, ?, ?, NULL, ?, ?, 'manual', ?)",
            (w.user_id, employee_id, account_id, ts(t_in), ts(t_out), ts(t_out))).lastrowid
    con.close()
    return cid


def _clock_row(ctx) -> dict:
    con = ctx.world.sql()
    row = con.execute("SELECT in_utc, out_utc, close_reason FROM clock_events WHERE id=?",
                      (ctx.world.data["clock_event_id"],)).fetchone()
    con.close()
    return dict(zip(("in_utc", "out_utc", "close_reason"), row)) if row else {}


def _utc(v: str | None) -> datetime | None:
    """A stored naive-UTC time or a wire ISO time as naive UTC, to the second."""
    if not v:
        return None
    d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    if d.tzinfo is not None:
        d = d.astimezone(timezone.utc).replace(tzinfo=None)
    return d.replace(microsecond=0)


def _shift_input(value: str, minutes: int) -> str:
    """A `datetime-local` value moved by `minutes` (zone-free: the wall clock the input shows)."""
    return (datetime.strptime(value, "%Y-%m-%dT%H:%M") + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M")


async def _clock(ctx, page, chk) -> None:
    path = f"/admin/shifts/clock-events/{ctx.world.data['clock_event_id']}"
    with recorded(page, "PATCH", path) as patches:
        before = _clock_row(ctx)
        await page.goto(f"{ctx.app}/analytics/employee-reports", wait_until="domcontentloaded")
        await page.get_by_title(f"{CLOCK_EMPLOYEE}'s clock records").click(timeout=WAIT_MS)
        dialog = page.get_by_role("dialog").filter(has_text="Clocked hours")
        await dialog.get_by_role("button", name="Edit", exact=True).click(timeout=30_000)
        cin = dialog.get_by_label("Clock in", exact=True)
        cout = dialog.get_by_label("Clock out", exact=True)
        in_v, out_v = await cin.input_value(), await cout.input_value()

        await cout.fill(_shift_input(in_v, -30))
        await dialog.get_by_role("button", name="Save", exact=True).click(timeout=10_000)
        alert = dialog.get_by_role("alert")
        await alert.wait_for(timeout=15_000)
        await page.wait_for_timeout(1000)  # a PATCH, had one left, is answered by now
        shown = await alert.inner_text()
        await ui.shot(ctx, page, "clock-inverted-refused")
        sent = list(patches)
        after_inv = _clock_row(ctx)
        chk(CLOCK_INVERTED, shown == INVERTED_MSG and not sent and after_inv == before,
            alert=shown, patches=sent, db_before=before, db_after=after_inv, typed_out=_shift_input(in_v, -30),
            clock_in=in_v)

        new_out = _shift_input(out_v, -15)
        await cout.fill(new_out)
        n0 = len(patches)
        async with page.expect_response(lambda r: r.request.method == "PATCH" and urlsplit(r.url).path == path,
                                        timeout=30_000) as resp:
            await dialog.get_by_role("button", name="Save", exact=True).click(timeout=10_000)
        status = (await resp.value).status
        await dialog.get_by_text("(edited)").wait_for(timeout=30_000)
        # A quiet window, not a settle wait: a second PATCH the save sent late would land here, and
        # CLOCK_SAVED counts them (one).
        await page.wait_for_timeout(300)
        await _painted(page)
        await ui.shot(ctx, page, "clock-saved")
        after = _clock_row(ctx)
        mine = patches[n0:]
        body = mine[0]["body"] if mine else {}
        (ctx.out / "clock-patches.json").write_text(json.dumps(
            {"patches": patches, "db_before": before, "db_after_inverted": after_inv, "db_after": after}, indent=2))
        chk(CLOCK_SAVED, len(mine) == 1 and 200 <= status < 300 and set(body) == {"out_utc"}
            and _utc(after.get("out_utc")) == _utc(body.get("out_utc")) != _utc(before.get("out_utc"))
            and after.get("in_utc") == before.get("in_utc"),
            patches=mine, relay_status=status, db_before=before, db_after=after, typed_out=new_out, was_out=out_v)


RAIL_NAMES = """(aside) => [...aside.querySelectorAll('div[role=button]')]
  .map((r) => r.querySelector('div[title]')?.getAttribute('title')).filter(Boolean)"""
# An init script, so in place before the Vault page's first script runs: every distinct folder order the rail
# paints on that page load (its first paint is the restored query snapshot's), in `window.__slopRail`.
RAIL_PAINTS = """(() => { if (location.pathname !== '/growth/vault-pro') return;
  const W = window.__slopRail = []; const look = () => {
  const aside = [...document.querySelectorAll('aside')].find((a) => (a.textContent || '').includes('All media'));
  const names = aside ? (""" + RAIL_NAMES + """)(aside) : [];
  if (names.length && JSON.stringify(names) !== JSON.stringify(W[W.length - 1])) W.push(names); };
  new MutationObserver(look).observe(document, { subtree: true, childList: true, attributes: true }); look(); })()"""


async def _vault(ctx, page, chk) -> None:
    creator = ctx.world.data["creators"][1]
    aid = creator["id"]
    names = [n for _, n in FOLDERS]
    id_of = dict((n, i) for i, n in FOLDERS)
    sorts: list[dict] = []
    sort_reqs: list = []  # the same POSTs, for their responses
    fake = ctx.of_wire

    def on_request(req):
        if req.method == "POST" and urlsplit(req.url).path == "/admin/vault-ai/of-folders/sort":
            sorts.append(req.post_data_json)
            sort_reqs.append(req)

    async def lists_through(route):  # this Creator's folder list reaches the relay; any other stays held (ui.py)
        if route.request.headers.get("x-account-id") == aid:
            return await route.continue_()
        await route.fallback()

    def of_reads() -> int:
        with fake.lock:
            return sum(1 for c in fake.calls if c["account"] == aid and c["route"] == "GET /api2/v2/vault/lists")

    lists_path = lambda u: urlsplit(u).path == "/api/of/v2/vault/lists"  # noqa: E731
    await page.route(lists_path, lists_through)
    page.on("request", on_request)
    await page.add_init_script(RAIL_PAINTS)
    aside = page.locator("aside").filter(has_text="All media")

    async def open_rail() -> None:
        await page.goto(f"{ctx.app}/growth/vault-pro", wait_until="domcontentloaded")
        await ui.pick_creator(page, creator["nickname"], timeout_ms=WAIT_MS)
        await aside.get_by_text(names[-1], exact=True).first.wait_for(timeout=WAIT_MS)

    async def rail() -> list:
        return await aside.evaluate(RAIL_NAMES)

    async def sort_label() -> str:
        return (await aside.locator("button[aria-haspopup=menu]").first.inner_text(timeout=10_000)).strip()

    async def customize() -> None:
        await aside.locator("button[aria-haspopup=menu]").first.click(timeout=10_000)
        await page.get_by_role("menuitem", name="Customize order").click(timeout=10_000)
        await aside.locator("div[role=button][draggable=true]").first.wait_for(timeout=10_000)

    async def drag(src: str, dst: str) -> None:
        rows = aside.locator("div[role=button][draggable=true]")
        await rows.filter(has_text=src).first.drag_to(rows.filter(has_text=dst).first, timeout=10_000)
        await page.wait_for_timeout(300)

    try:
        await open_rail()
        shown0 = await rail()
        # Cancel: one drag, then the X; nothing is written.
        await customize()
        await drag(*CANCEL_DRAG)
        mid_cancel = await rail()
        await aside.get_by_role("button", name="Cancel").click(timeout=10_000)
        await page.wait_for_timeout(500)
        after_cancel = await rail()
        with fake.lock:
            of_sorts_cancel = len(fake.vault_sorts.get(aid, []))
        chk(VAULT_CANCEL, shown0 == names and mid_cancel != names and after_cancel == names and not sorts
            and of_sorts_cancel == 0,
            of_order=names, shown=shown0, mid_drag=mid_cancel, after_cancel=after_cancel, sort_posts=list(sorts),
            of_sorts=of_sorts_cancel)

        # Customize: the drags, each checked against moveFolder's slot rule, then Done.
        await customize()
        want, steps = list(names), []
        for src, dst in DRAGS:
            await drag(src, dst)
            want = move_folder(want, src, dst)
            steps.append({"drag": src, "onto": dst, "want": want, "shown": await rail()})
        await ui.shot(ctx, page, "vault-customize-trigger")
        chk(VAULT_DRAG, all(x["shown"] == x["want"] for x in steps), steps=steps)

        reads_before = of_reads()
        t_done = time.time()
        async with page.expect_response(lambda r: r.request.method == "POST"
                                        and urlsplit(r.url).path == "/admin/vault-ai/of-folders/sort",
                                        timeout=30_000) as sort_resp:
            await aside.get_by_role("button", name="Done").click(timeout=10_000)
        status = (await sort_resp.value).status
        await page.wait_for_timeout(1000)
        after_done = await rail()
        label_done = await sort_label()
        with fake.lock:
            of_sorts = [x["body"] for x in fake.vault_sorts.get(aid, [])]
        want_ids = [id_of[n] for n in want]
        body = sorts[0] if sorts else {}
        chk(VAULT_SORT, status == 200 and len(sorts) == 1 and body.get("account_id") == aid
            and body.get("custom_order") == want_ids
            and of_sorts == [{"customOrder": want_ids, "sort": "custom"}],
            http_status=status, posts=sorts, want_ids=want_ids, of_sorts=of_sorts, rail_after_done=after_done)

        with fake.lock:
            read_after_sort = any(c["account"] == aid and c["route"] == "GET /api2/v2/vault/lists" and c["t"] > t_done
                                  for c in fake.calls)
        # The owner reloads PERSIST_SETTLE_MS later, once the snapshot's own throttled save is due too; a reload
        # sooner (QUICK_RELOAD_MS) is VAULT_QUICK_RELOAD below.
        await page.wait_for_timeout(PERSIST_SETTLE_MS)
        await open_rail()
        await page.wait_for_timeout(500)
        reloaded = await rail()
        reads_after = of_reads()
        await ui.shot(ctx, page, "vault-order-after-reload")
        chk(VAULT_RELOAD, reloaded == want and read_after_sort, shown=reloaded, want=want,
            of_order=fake.vault_order.get(aid), of_read_after_sort=read_after_sort,
            of_list_reads_before_done=reads_before, of_list_reads_after_reload=reads_after)
        # No read reports OF's folder sort: the label is the one last set here, kept per Creator across the reload.
        label_reloaded = await sort_label()
        chk(VAULT_SORT_LABEL, label_done == "Custom" and label_reloaded == "Custom",
            after_done=label_done, after_reload=label_reloaded)

        # A second order, and the owner reloads 1 s after Done: before the snapshot's own save is due.
        await customize()
        base = await rail()
        await drag(*QUICK_DRAG)
        want2 = move_folder(base, *QUICK_DRAG)
        dragged2 = await rail()
        await ui.shot(ctx, page, "vault-quick-reload-trigger")
        async with page.expect_response(lambda r: r.request.method == "POST"
                                        and urlsplit(r.url).path == "/admin/vault-ai/of-folders/sort",
                                        timeout=30_000) as sort_resp2:
            await aside.get_by_role("button", name="Done").click(timeout=10_000)
        status2 = (await sort_resp2.value).status
        await page.wait_for_timeout(QUICK_RELOAD_MS)
        await open_rail()
        await page.wait_for_timeout(500)
        quick = await rail()
        # From its first paint: a reload that restored a snapshot from before Done paints the old order first, and
        # only then OF's (the rail reads its folder list again at mount).
        painted = [x for x in await page.evaluate("() => window.__slopRail") if set(x) == set(names)]
        await ui.shot(ctx, page, "vault-quick-reload-settled")
        with fake.lock:
            of_last = [x["body"] for x in fake.vault_sorts.get(aid, [])][-1:]
        chk(VAULT_QUICK_RELOAD, status2 == 200 and dragged2 == want2 and quick == want2 and painted == [want2]
            and of_last == [{"customOrder": [id_of[n] for n in want2], "sort": "custom"}],
            before=base, dragged=dragged2, want=want2, shown_after_reload=quick, painted_after_reload=painted,
            http_status=status2, reload_after_done_ms=QUICK_RELOAD_MS, of_last_sort=of_last)

        # A sort from another page: OF Manager's Vault (the OF mirror) > folder sort dropdown > Name. Back on the
        # rail, its label is that sort (the fake OF does not reorder by name, so the order is not judged here).
        n_sorts, status3, label_mirror = len(sorts), None, None
        mirror = page.frame_locator("iframe[src*='/of-mirror/pages/vault/']")
        by_name = mirror.locator(".of-state-menu .v-list-item").filter(
            has=mirror.locator("input[type=radio][name*='-sort-'][value=name]"))
        await page.goto(f"{ctx.app}/of-manager/vault/state-lists-sort-dropdown?account={aid}",
                        wait_until="domcontentloaded")
        for _ in range(6):  # bound with no handlers (a "select a model" note) until `?account=` scopes the page
            if len(sort_reqs) > n_sorts:  # a click's POST came late: never a second one
                break
            try:
                await by_name.first.wait_for(timeout=WAIT_MS)  # the iframe's load is not in the POST's 5 s
                async with page.expect_request(lambda r: r.method == "POST"
                                               and urlsplit(r.url).path == "/admin/vault-ai/of-folders/sort",
                                               timeout=5_000):
                    await by_name.first.click(timeout=10_000)
            except PwTimeout:
                continue
            break
        if len(sort_reqs) > n_sorts:
            resp3 = await sort_reqs[n_sorts].response()
            status3 = resp3.status if resp3 else None
        if status3 is not None:
            await page.wait_for_timeout(500)
            await open_rail()
            label_mirror = await sort_label()
            await ui.shot(ctx, page, "vault-sort-label-after-mirror")
        mirror_posts = sorts[n_sorts:]
        chk(VAULT_MIRROR_SORT_LABEL, status3 == 200
            and [(x.get("sort"), x.get("custom_order")) for x in mirror_posts] == [("name", None)]
            and label_mirror == "Name",
            mirror_sort_status=status3, mirror_sort_posts=mirror_posts, after_mirror_sort=label_mirror)
    finally:
        page.remove_listener("request", on_request)
        await page.unroute(lists_path)


async def _premade(ctx, page, chk) -> None:
    creator = ctx.world.data["creators"][2]
    aid = creator["id"]
    bodies: list[dict] = []

    def on_request(req):
        if req.method == "POST" and urlsplit(req.url).path == "/admin/automation-rules":
            bodies.append(req.post_data_json)

    page.on("request", on_request)
    try:
        await page.goto(f"{ctx.app}/growth/auto-post", wait_until="domcontentloaded")
        await ui.pick_creator(page, creator["nickname"], timeout_ms=WAIT_MS)
        await page.get_by_role("button", name="New auto post").first.click(timeout=WAIT_MS)
        await page.get_by_role("button", name="Compose", exact=True).click(timeout=30_000)
        form = page.locator("div").filter(has=page.get_by_role("heading", name="Compose auto posts", exact=True)).last
        ta = form.locator("textarea")
        price = form.get_by_placeholder("0 (free)")
        await ta.first.wait_for(timeout=WAIT_MS)
        # Post 1: three variants, the middle one removed; $12, 5 min.
        await ta.nth(0).fill("slop post one A")
        await form.get_by_role("button", name="Add variant").first.click()
        await ta.nth(1).fill("slop post one B")
        await form.get_by_role("button", name="Add variant").first.click()
        await ta.nth(2).fill("slop post one C")
        await form.get_by_role("button", name="Remove variant 2").click()
        await price.nth(0).fill("12")
        await form.get_by_placeholder("0 (now)").fill("5")
        # Post 2 (later removed) and Post 3.
        for text, cents, delay in (("slop post two", "3", "30"), ("slop post three", "7", "45")):
            await form.get_by_role("button", name="Add another post").click()
            await ta.last.fill(text)
            await price.last.fill(cents)
            await form.get_by_placeholder("e.g. 30").last.fill(delay)
        await form.get_by_placeholder("e.g. 6").last.fill("6")
        await form.get_by_role("button", name="Remove", exact=True).nth(1).click()
        await page.wait_for_timeout(300)
        shown = {"texts": [await t.input_value() for t in await ta.all()],
                 "prices": [await p.input_value() for p in await price.all()],
                 "delays": [await form.get_by_placeholder("0 (now)").input_value()]
                 + [await d.input_value() for d in await form.get_by_placeholder("e.g. 30").all()],
                 "hours": [await h.input_value() for h in await form.get_by_placeholder("e.g. 6").all()]}
        await ui.shot(ctx, page, "premade-compose-trigger")
        want_shown = {"texts": ["slop post one A", "slop post one C", "slop post three"], "prices": ["12", "7"],
                      "delays": ["5", "45"], "hours": ["", "6"]}
        chk(PREMADE_ROWS, shown == want_shown, shown=shown, want=want_shown)

        await form.get_by_role("button", name="Use in rule").click(timeout=10_000)
        async with page.expect_response(lambda r: r.request.method == "POST"
                                        and urlsplit(r.url).path == "/admin/automation-rules",
                                        timeout=30_000) as created:
            await page.get_by_role("button", name="Create", exact=True).click(timeout=10_000)
        resp = await created.value
        status, rule = resp.status, await resp.json()
        await page.wait_for_timeout(1000)
        await ui.shot(ctx, page, "premade-rule-saved")
        (ctx.out / "premade-rule-bodies.json").write_text(json.dumps(bodies, indent=2))
        b = bodies[0] if bodies else {}
        chk(PREMADE_PAYLOAD, status == 200 and len(bodies) == 1 and b.get("account_id") == aid
            and b.get("kind") == "auto_posts" and (b.get("payload") or {}).get("posts") == PREMADE_WANT,
            http_status=status, posts=len(bodies), got=(b.get("payload") or {}).get("posts"), want=PREMADE_WANT,
            account=b.get("account_id"), kind=b.get("kind"))

        listed = (await ctx.owner.get(f"/admin/automation-rules?account_id={aid}")).json().get("rules") or []
        mine = [r for r in listed if r.get("id") == rule.get("id")]
        con = ctx.world.sql()
        row = con.execute("SELECT account_id, kind, steps_json FROM automation_rules WHERE id=?",
                          (rule.get("id"),)).fetchone()
        con.close()
        stored = json.loads(row[2]) if row and row[2] else {}
        chk(PREMADE_STORED, len(mine) == 1 and (mine[0].get("payload") or {}).get("posts") == PREMADE_WANT
            and row is not None and row[0] == aid and row[1] == "auto_posts" and stored.get("posts") == PREMADE_WANT,
            rule_id=rule.get("id"), route=(mine[0].get("payload") if mine else None), db=stored,
            db_account=row[0] if row else None, db_kind=row[1] if row else None)
    finally:
        page.remove_listener("request", on_request)


async def _welcome(ctx, page, chk) -> None:
    creator = ctx.world.data["creators"][1]
    aid = creator["id"]
    await page.goto(f"{ctx.app}/growth/smart-messages", wait_until="domcontentloaded")
    await ui.pick_creator(page, creator["nickname"], timeout_ms=WAIT_MS)
    await page.get_by_role("button", name="New Message").click(timeout=WAIT_MS)
    await page.get_by_role("button", name=re.compile(r"^Subscriber welcome")).click(timeout=WAIT_MS)
    await page.get_by_role("button", name="Next", exact=True).click()
    dialog = page.get_by_role("dialog", name="Delayed welcome")
    await dialog.get_by_placeholder("Enter your message...").fill(WELCOME_TEXT, timeout=WAIT_MS)
    await page.keyboard.press("Escape")
    stayed = await dialog.is_visible()
    await ui.shot(ctx, page, "welcome-escape-trigger")

    with recorded(page, "POST", "/admin/automation-rules") as posts, \
            recorded(page, "PATCH", "/admin/automation-rules") as patches:
        await dialog.get_by_role("button", name="Save", exact=True).click()
        await dialog.get_by_text("Saved", exact=True).wait_for(timeout=30_000)
        await _painted(page)
        await ui.shot(ctx, page, "welcome-saved")
    writes = posts + patches
    (ctx.out / "welcome-rule-bodies.json").write_text(json.dumps(writes, indent=2))
    response = (await ctx.owner.get(f"/admin/automation-rules?account_id={aid}"))
    response.raise_for_status()
    rules = [r for r in response.json().get("rules", []) if r.get("kind") == "send_welcome"]
    con = ctx.world.sql()
    rows = con.execute("SELECT id, account_id, kind, steps_json FROM automation_rules "
                       "WHERE account_id=? AND kind=?", (aid, "send_welcome")).fetchall()
    con.close()
    body = writes[0].get("body") or {} if writes else {}
    route_messages = [(r.get("payload") or {}).get("message") for r in rules]
    db_messages = [json.loads(row[3] or "{}").get("message") for row in rows]
    chk(WELCOME_SAVED, stayed and await dialog.is_visible() and len(writes) == 1
        and writes[0]["status"] == 200 and body.get("account_id") == aid
        and (body.get("payload") or {}).get("message") == WELCOME_TEXT
        and len(rules) == 1 and route_messages == [WELCOME_TEXT]
        and len(rows) == 1 and rows[0][1:3] == (aid, "send_welcome")
        and db_messages == [WELCOME_TEXT], stayed_after_escape=stayed, writes=writes,
        route_messages=route_messages, db_messages=db_messages, rows=len(rows), account=aid)


SL_NAME = "slop between list"


def _smart_rows(ctx) -> list[tuple]:
    con = ctx.world.sql()
    rows = con.execute("SELECT id, account_id, name, rules_json FROM smart_lists ORDER BY id").fetchall()
    con.close()
    return rows


async def _smartlist(ctx, page, chk) -> None:
    with recorded(page, "POST", "/admin/smart-lists") as posts:
        await _smartlist_steps(ctx, page, chk, posts)


async def _smartlist_steps(ctx, page, chk, posts: list[dict]) -> None:
    await page.goto(f"{ctx.app}/growth/smart-lists", wait_until="domcontentloaded")
    create = page.get_by_role("button", name="Create list").first
    await create.wait_for(timeout=WAIT_MS)
    await page.wait_for_function("(b) => b && !b.disabled", arg=await create.element_handle(), timeout=WAIT_MS)
    await create.click()
    dlg = page.get_by_role("dialog", name="Create smart list")
    await dlg.get_by_label("Smart list name").fill(SL_NAME)
    preview_btn = dlg.get_by_role("button", name="Preview count")
    save = dlg.get_by_role("button", name="Create smart list")
    count = dlg.get_by_text("fans match")
    async with page.expect_response(lambda r: urlsplit(r.url).path == "/admin/smart-lists/preview",
                                    timeout=30_000) as pv:
        await preview_btn.click()
    pv_resp = await pv.value
    pv_aid = (pv_resp.request.post_data_json or {}).get("account_id")
    await count.wait_for(timeout=10_000)
    shown_before = await count.locator("..").inner_text()
    await ui.shot(ctx, page, "smartlist-previewed")
    await dlg.get_by_label("Value", exact=True).fill("0")
    try:  # the count's going is the positive signal; under the fault it stays, so this times out
        await count.wait_for(state="hidden", timeout=5_000)
    except Exception:  # noqa: BLE001
        pass
    gone = await count.count() == 0
    await ui.shot(ctx, page, "smartlist-edit-drops-preview")
    chk(SMARTLIST_STALE, pv_resp.status == 200 and gone, preview_status=pv_resp.status,
        shown_before=shown_before, count_after_edit_visible=not gone)

    aid = pv_aid or ctx.world.data["creators"][0]["id"]
    route_before = (await ctx.owner.get(f"/admin/smart-lists?account_id={aid}")).json().get("lists", [])
    db_before = _smart_rows(ctx)
    await dlg.get_by_label("Operator", exact=True).select_option("between")
    await dlg.get_by_label("Value", exact=True).fill("10")
    await dlg.get_by_label("Upper value", exact=True).fill("")
    one = {"save": await save.is_disabled(), "preview": await preview_btn.is_disabled(),
           "reason": await dlg.get_by_role("alert").all_inner_texts()}
    await ui.shot(ctx, page, "smartlist-between-one-bound")
    await save.click(force=True, timeout=5_000)  # a click on the disabled button must not write
    await dlg.get_by_label("Upper value", exact=True).fill("5")
    inv = {"save": await save.is_disabled(), "preview": await preview_btn.is_disabled(),
           "reason": await dlg.get_by_role("alert").all_inner_texts()}
    await ui.shot(ctx, page, "smartlist-between-inverted")
    await save.click(force=True, timeout=5_000)

    want = {"match": "all", "rules": [{"field": "lifetime_spend", "op": "between", "value": [1000, 5000]}]}
    is_valid_save = lambda r: (r.request.method == "POST" and urlsplit(r.url).path == "/admin/smart-lists"  # noqa: E731
                               and (r.request.post_data_json or {}).get("rules") == want)
    await dlg.get_by_label("Upper value", exact=True).fill("50")
    async with page.expect_response(is_valid_save, timeout=30_000) as saved:
        await save.click(timeout=10_000)
    # The valid Save's answer is the positive signal: a POST from a forced click above left the browser before it,
    # and any write of it landed before this one did.
    saved_resp = await saved.value
    status = saved_resp.status
    sid = (await saved_resp.json()).get("id")
    await dlg.wait_for(state="hidden", timeout=15_000)
    await page.get_by_text(SL_NAME).first.wait_for(timeout=15_000)
    await ui.shot(ctx, page, "smartlist-between-saved")
    route_after = (await ctx.owner.get(f"/admin/smart-lists?account_id={aid}")).json().get("lists", [])
    db_after = _smart_rows(ctx)
    gate_posts = [p for p in posts if (p["body"] or {}).get("rules") != want]
    route_rest = [l for l in route_after if l["id"] != sid]
    db_rest = [r for r in db_after if r[0] != sid]
    chk(SMARTLIST_GATE, one == {"save": True, "preview": True, "reason": ["Enter both bounds"]}
        and inv == {"save": True, "preview": True, "reason": ["The upper bound must be at least the lower one"]}
        and not gate_posts and route_rest == route_before and db_rest == db_before,
        one_bound=one, inverted=inv, posts=len(gate_posts), route_lists=len(route_rest), db_rows=len(db_rest))

    in_route = [l["rules"] for l in route_after if l["id"] == sid]
    in_db = [json.loads(r[3]) for r in db_after if r[0] == sid and r[1] == aid]
    own = len(posts) - len(gate_posts)  # the gate check owns the forced clicks' POSTs; this counts its own Save
    chk(SMARTLIST_SAVED, status == 200 and own == 1 and in_route == [want] and in_db == [want],
        post=status, posts=own, id=sid, route=in_route, db=in_db, want=want, account=aid)


PAGE = 25  # useChatList's PAGE_SIZE (and the relay's badge window, server._ROSTER_SCAN_MAX)
BUST_COOLDOWN_S = 8.5  # app/hooks/useRosterCounts.ts REFRESH_COOLDOWN_MS (8 s) + margin: a bust sooner is skipped
B_LATENCY_S = 2.5  # Creator B's /chats answer time: a slow proxy (a guess; AE's slow reads measured 6-8 s)
ROW_HANDLE = """(r) => { const h = [...r.querySelectorAll('span')].find(s => /^@\\S+$/.test(s.textContent || ''));
  return h ? h.textContent.slice(1) : null; }"""  # a chat row's Fan handle, without the @
ROW_HANDLES = "() => [...document.querySelectorAll('[data-chat-row]')].map(" + ROW_HANDLE + ")"
# Every frame and every DOM mutation from the click on B's tab: once B's tab is selected (the
# same commit as the scope), a row with an A handle is a leak.
SAMPLER = """([aHandles, bName]) => {
  const A = new Set(aHandles);
  const S = window.__slopFan = { samples: 0, judged: 0, leaks: [], n: 0, t0: Date.now(), on: true };
  const look = () => {
    S.samples++;
    const tab = [...document.querySelectorAll('[role=tab][aria-selected=true]')]
      .some(t => (t.textContent || '').includes(bName));
    if (!tab) return;
    S.judged++;
    const hs = [...document.querySelectorAll('[data-chat-row]')].map(r => {
      const h = [...r.querySelectorAll('span')].find(s => /^@\\S+$/.test(s.textContent || ''));
      return h ? h.textContent.slice(1) : null; });
    const bad = hs.filter(h => h && A.has(h));
    if (bad.length) { S.n++; if (S.leaks.length < 20)
      S.leaks.push({ t: Date.now() - S.t0, a_rows: bad.length, rows: hs.length, sample: bad.slice(0, 3) }); }
  };
  const mo = new MutationObserver(look);
  mo.observe(document.body, { subtree: true, childList: true, characterData: true });
  const tick = () => { if (!S.on) return; look(); requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
  S.stop = () => { S.on = false; mo.disconnect();
    return { samples: S.samples, judged: S.judged, leak_samples: S.n, leaks: S.leaks }; };
}"""


async def _chat_view(ctx, creators) -> dict[str, list[dict]]:
    """Each Creator's chats as the relay holds them (`/admin/chats/recent`), newest first, in
    OF /chats' row shape."""
    out = {}
    for c in creators:
        rows = await manager.recent_chats(ctx.owner, c["id"], 100)
        out[c["id"]] = [{k: v for k, v in r.items() if not k.startswith("_")}
                        | {"canSendMessage": True, "isMutedNotifications": False} for r in rows]
    return out


def _chats_query(req, view) -> tuple[str, int, int, bool, list[dict]]:
    """A /api/of/v2/chats GET as the relay pages it: its Creator, offset, limit, whether it is the plain
    list (no filter, list or search), and the view's rows it matches (a list, search or filter other than
    unread matches none)."""
    q = {k: v[0] for k, v in parse_qs(urlsplit(req.url).query).items()}
    aid = req.headers.get("x-account-id") or ""
    off, lim = int(q.get("offset") or 0), int(q.get("limit") or 10)
    rows = list(view.get(aid, []))
    if q.get("list_id") or q.get("query") or q.get("search") or q.get("filter") not in (None, "unread"):
        rows = []
    elif q.get("filter") == "unread":
        rows = [r for r in rows if r.get("hasUnread")]
    plain = not (q.get("filter") or q.get("list_id") or q.get("query") or q.get("search"))
    return aid, off, lim, plain, rows


async def _serve_chats(route, rows: list[dict], off: int, lim: int) -> None:
    await route.fulfill(status=200, content_type="application/json",
                        body=json.dumps({"list": rows[off:off + lim], "hasMore": off + lim < len(rows)}))


def _unread(row: dict) -> bool:  # app/lib/chatUnread.ts isUnreadChat
    return bool(row.get("hasUnread")) or int(row.get("unreadMessagesCount") or 0) > 0


async def _tab_unread(page, creator) -> int | None:
    """The Creator tab's unread badge, from its title ('<name> — N unread', CreatorTabs)."""
    title = await page.get_by_role("tab", name=creator["nickname"]).first.get_attribute("title", timeout=10_000)
    m = re.search(r"— (\d+) unread$", title or "")
    return int(m.group(1)) if m else None


async def _creator_tab(page, creator) -> None:
    await page.get_by_role("tab", name=creator["nickname"]).first.click(timeout=WAIT_MS)


async def _load_more(more) -> bool:
    """Click "Load more conversations" as it stands at the list's end. A JS click: Playwright's click scrolls
    the button into view first, and that scroll is the user scroll that lets the end-of-list observer page on
    its own, which hides the button before the click lands."""
    try:
        await more.first.wait_for(timeout=15_000)
        await more.first.evaluate("(b) => b.click()")
        return True
    except PwTimeout:  # judged by the caller
        return False


async def _rows_include(page, want: list, timeout_ms: int = 30_000) -> bool:
    try:
        await page.wait_for_function(
            "(W) => { const hs = (" + ROW_HANDLES + ")(); return W.every(h => hs.includes(h)); }",
            arg=want, timeout=timeout_ms)
        return True
    except PwTimeout:  # judged by the caller
        return False


# Lets the page run what a response it just finished resolves (a fetch's `.then`s) before the next step.
AFTER_RESPONSE_TICK = "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r))))"


async def _fanlist(ctx, page, chk) -> None:
    a, b = ctx.world.data["creators"][0], ctx.world.data["creators"][1]
    view = await _chat_view(ctx, (a, b))
    handles = {aid: [r["withUser"]["username"] for r in rows] for aid, rows in view.items()}
    # A's OF chat window (lib/of_wire.py) is the list the browser wire serves: the relay's real roster-counts folds
    # its first 25 chats into A's badge. The same list object, so a row replaced in it is in both.
    fake = ctx.of_wire
    a_set, b_set = set(handles[a["id"]]), set(handles[b["id"]])
    hold = {"armed": False, "seen": asyncio.Event(), "release": asyncio.Event(), "held": [], "landed": []}
    served: list[tuple[str, int, bool]] = []

    async def chats(route):
        req = route.request
        if req.method != "GET":
            return await route.fallback()
        aid, off, lim, plain, rows = _chats_query(req, view)
        served.append((aid, off, plain))
        if aid == a["id"] and plain and off >= PAGE and hold["armed"]:
            hold["held"].append(off)
            hold["seen"].set()
            await hold["release"].wait()  # A's next page, in flight across the switch
        elif aid == b["id"]:
            await asyncio.sleep(B_LATENCY_S)
        try:
            await _serve_chats(route, rows, off, lim)
            if aid == a["id"] and off >= PAGE and hold["release"].is_set():
                hold["landed"].append(off)
        except Exception:  # noqa: BLE001 — the page dropped the request
            pass

    # Picking a Creator's tab warms it (app/hooks/useCreatorWarmUp.ts): its badge bust (a live OF read, seconds),
    # then an invalidation of its chat lists. A's bust is held at the browser's wire until A's next page is in
    # flight, so that invalidation always lands on a list loading its next page (the slow-OF order), which must
    # leave the page alone.
    busts: list[str] = []

    async def roster(route):
        if parse_qs(urlsplit(route.request.url).query).get("bust") == [a["id"]] and not hold["seen"].is_set():
            busts.append("held")
            try:
                await asyncio.wait_for(hold["seen"].wait(), 60)
            except TimeoutError:  # judged by FANLIST_RETURN (busts) and FANLIST_SCOPE (held)
                busts.append("released unpaged")
        await route.fallback()

    chats_path = lambda u: urlsplit(u).path == "/api/of/v2/chats"  # noqa: E731
    roster_path = lambda u: urlsplit(u).path == "/admin/accounts/roster-counts"  # noqa: E731
    await page.route(chats_path, chats)
    await page.route(roster_path, roster)
    with fake.lock:
        fake.chats[a["id"]] = view[a["id"]]
    try:
        n_status = len(page.slop["statuses"])
        await page.goto(f"{ctx.app}/messages-pro", wait_until="domcontentloaded")
        bust = f"/admin/accounts/roster-counts?bust={a['id']}"
        bust_done, clicked, on_a, t_bust = False, False, [], time.monotonic()
        more = page.get_by_role("button", name="Load more conversations")
        try:
            async with page.expect_response(lambda r: bust in r.url, timeout=90_000) as bust_resp:
                await _creator_tab(page, a)
                await page.wait_for_function(
                    "([A, n]) => { const hs = (" + ROW_HANDLES + ")(); return hs.length >= n && hs.every(h => A.includes(h)); }",
                    arg=[handles[a["id"]], min(PAGE, len(a_set))], timeout=WAIT_MS)
                on_a = await page.evaluate(ROW_HANDLES)
                # A's next page: the owner clicks "Load more conversations"; it is held at the wire.
                hold["armed"] = True
                clicked = await _load_more(more)
                try:
                    await asyncio.wait_for(hold["seen"].wait(), 30)
                except TimeoutError:  # judged by FANLIST_SCOPE (held)
                    pass
                await ui.shot(ctx, page, "fanlist-a-next-page-in-flight")
            await (await bust_resp.value).finished()
            await page.evaluate(AFTER_RESPONSE_TICK)  # the warm-up's invalidation has run
            bust_done = True
            t_bust = time.monotonic()
        except PwTimeout:  # no bust for A (judged by FANLIST_RETURN)
            pass
        await page.unroute(roster_path, roster)

        await page.evaluate(SAMPLER, [sorted(a_set), b["nickname"]])
        await _creator_tab(page, b)
        await page.wait_for_timeout(500)
        hold["release"].set()  # A's page lands while B's first page is still on its way
        want_b = handles[b["id"]][:PAGE]
        settled = True
        try:
            await page.wait_for_function(
                "(B) => { const hs = (" + ROW_HANDLES + ")(); return hs.length > 0 && B.every(h => hs.includes(h)); }",
                arg=want_b, timeout=30_000)
        except Exception:  # noqa: BLE001 — judged below
            settled = False
        await page.wait_for_timeout(1500)  # a late page would land here
        sampled = await page.evaluate("() => window.__slopFan.stop()")
        shown = await page.evaluate(ROW_HANDLES)
        await ui.shot(ctx, page, "fanlist-b-settled")

        # B pages on: "Load more conversations" -> B's offset-25 read -> its Fans join the list.
        want_b2 = handles[b["id"]][PAGE:2 * PAGE]
        b_more_clicked = await _load_more(more)
        b_paged = await _rows_include(page, want_b2)
        b_shown = await page.evaluate(ROW_HANDLES)
        b_asked = (b["id"], PAGE, True) in served
        await ui.shot(ctx, page, "fanlist-b-page2-settled")
        chk(FANLIST_LOAD_MORE, len(want_b2) > 0 and b_more_clicked and b_asked and b_paged
            and set(want_b2) <= set(b_shown) and all(h in b_set for h in b_shown),
            b=b["id"], clicked=b_more_clicked, asked_offset_25=b_asked, page2=len(want_b2), shown=len(b_shown),
            missing=sorted(set(want_b2) - set(b_shown))[:5])

        # Back to A, its next page settled: the tab's warm-up refetches A's list (head, then the page after it), and the
        # page that was in flight at the switch is on A's list after that refetch, with no new scroll or click.
        want_a2 = handles[a["id"]][PAGE:2 * PAGE]
        n_served = len(served)

        def a_read(off: int):
            return lambda r: (r.request.method == "GET" and chats_path(r.url) and r.request.headers.get("x-account-id") == a["id"]
                              and parse_qs(urlsplit(r.url).query).get("offset") == [str(off)])
        # Meanwhile on OF one chat of A's head page turns unread (a fan's DM; read, if all are): the badge and the list
        # each change only when re-read. Replaced, not edited in place: the fake serialises rows off its lock.
        head = view[a["id"]][:PAGE]
        i_flip = next((i for i, r in enumerate(head) if not _unread(r)), 0)
        was_unread = _unread(head[i_flip])
        with fake.lock:
            view[a["id"]][i_flip] = {**head[i_flip], "hasUnread": not was_unread, "unreadMessagesCount": 0 if was_unread else 1}
        head = view[a["id"]][:PAGE]
        head_handles = [r["withUser"]["username"] for r in head]
        want_unread = sum(_unread(r) for r in head)
        await asyncio.sleep(max(0.0, BUST_COOLDOWN_S - (time.monotonic() - t_bust)))  # the return's bust is not skipped
        bust_back = asyncio.ensure_future(page.wait_for_event("response", lambda r: bust in r.url, timeout=15_000))
        rereads = [asyncio.ensure_future(page.wait_for_event("response", a_read(off), timeout=15_000)) for off in (0, PAGE)]
        await _creator_tab(page, a)
        rewarmed = [not isinstance(r, Exception) for r in await asyncio.gather(*rereads, return_exceptions=True)]
        busted_back = not isinstance((await asyncio.gather(bust_back, return_exceptions=True))[0], Exception)
        await page.evaluate(AFTER_RESPONSE_TICK)  # the refetch's pages are on the list
        a_back = await _rows_include(page, want_a2, timeout_ms=10_000)
        a_shown = await page.evaluate(ROW_HANDLES)
        await ui.shot(ctx, page, "fanlist-a-back-settled")
        a_reads_back = [x for x in served[n_served:] if x[0] == a["id"]]
        chk(FANLIST_RETURN, len(want_a2) > 0 and busts and set(busts) == {"held"} and bust_done and hold["landed"] and a_back
            and set(want_a2) <= set(a_shown),
            a=a["id"], page2=len(want_a2), shown=len(a_shown), warm_bust=busts, warm_bust_landed_in_flight=bust_done,
            landed_after_switch=hold["landed"], refetched_head_page2=rewarmed, reads_on_return=a_reads_back,
            missing=sorted(set(want_a2) - set(a_shown))[:5])
        # Badge and list agree on A's head page: the tab's count (the bust's fold of OF's first 25) is the number of
        # unread rows the list shows among those Fans, and both carry the flip.
        badge = await _tab_unread(page, a)
        list_unread = await page.evaluate(
            "(H) => [...document.querySelectorAll('[data-chat-row]')].filter(r => H.includes((" + ROW_HANDLE + ")(r))"
            " && r.querySelector('[role=img][aria-label^=\"Unread\"]')).length",
            head_handles)
        chk(FANLIST_REWARM, rewarmed[0] and (a["id"], 0, True) in a_reads_back and busted_back
            and badge == want_unread and list_unread == want_unread,
            a=a["id"], page2_settled_before=hold["landed"], refetched_head_page2=rewarmed, reads_on_return=a_reads_back,
            bust_on_return=busted_back, flipped=head_handles[i_flip], flipped_to_unread=not was_unread,
            head_unread_on_of=want_unread, badge=badge, list_unread_in_head=list_unread)
        fives = [u for st, u in page.slop["statuses"][n_status:] if st >= 500 and "/api/of/" not in u]
        a_on_b = sorted(set(shown) & a_set)
        out = {"a": a["id"], "b": b["id"], "a_chats": len(a_set), "b_chats": len(b_set), "on_a": len(on_a),
               "a_warm_bust": busts, "load_more_clicked": clicked, "held_offsets": hold["held"], "landed_after_switch": hold["landed"],
               "sampler": sampled, "settled": settled, "shown": len(shown), "a_rows_settled": a_on_b[:5],
               "not_b": sorted(h or "" for h in shown if h not in b_set)[:5], "relay_5xx": fives[:5],
               "chats_reads": len(served)}
        (ctx.out / "fanlist-scope-switch.json").write_text(json.dumps(out, indent=2))
        chk(FANLIST_SCOPE, len(a_set) > PAGE and len(b_set) > 0 and hold["held"] and hold["landed"]
            and sampled["judged"] > 0 and sampled["leak_samples"] == 0 and settled and not a_on_b
            and all(h in b_set for h in shown) and set(want_b) <= set(shown) and not fives, **out)
    finally:  # the fake's chat window and the wire routes go with the flow, whatever it raised
        with fake.lock:
            fake.chats.pop(a["id"], None)
        await page.unroute(chats_path, chats)
        await page.unroute(roster_path, roster)


REFUSED_TEXT = "slop refused schedule"
# service/server.py create_scheduled_send's at-schedule-time refusal (a Fansly PPV), verbatim.
FANSLY_NOTE = ("Fansly scheduled sends support text and GIFs for now — PPV price and media attachments aren't wired "
               "on the Fansly path yet.")
TAGGABLE = {"id": 7707, "name": "slop Tagged Kim", "user": {"id": 7707, "name": "slop Tagged Kim", "username": "slopkim"}}
INPUT = 'Press "/" + keyword to quickly search scripts'  # the chat Composer's placeholder
PPV_TEXT = "slop ppv with two gifs"
PPV_PICK = 9020  # Creator 0's last-but-one loner (`_seed_vault`): no duplicate section hides it
PPV_UPLOADED = 9021  # the upload's answer: OF already has the file (deduped), as /upload answers a re-upload
PPV_GIFS = ("slopgif1", "slopgif2")
PPV_UPLOAD_HOLD_S = 3.0  # the upload runs this long after Enter: any send to OF meanwhile is early
# A 1x1 PNG for the file chooser.
PNG_1PX = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
                        "0000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def _scheduled_rows(ctx, aid: str) -> dict[int, dict]:
    """The Creator's scheduled sends' payloads by row id, in id order."""
    con = ctx.world.sql()
    rows = con.execute("SELECT id, payload_json FROM scheduled_jobs WHERE account_id=? AND kind='scheduled_send' "
                       "ORDER BY id", (aid,)).fetchall()
    con.close()
    return {r[0]: json.loads(r[1] or "{}") for r in rows}


async def _chat_refused(ctx, page, chk) -> None:
    """A paid, tagged schedule in Fan A's chat, refused after the owner opened Fan B's: the notice in B,
    then Restore in A brings the whole draft back, and it schedules through the relay."""
    c = ctx.world.data["creators"][2]
    view = await _chat_view(ctx, ctx.world.data["creators"])
    fan_a, fan_b = view[c["id"]][0]["withUser"], view[c["id"]][1]["withUser"]
    hold = {"release": asyncio.Event(), "bodies": []}

    async def chats(route):
        req = route.request
        if req.method != "GET":
            return await route.fallback()
        _aid, off, lim, _plain, rows = _chats_query(req, view)
        await _serve_chats(route, rows, off, lim)

    async def tagged(route):
        await route.fulfill(status=200, content_type="application/json",
                            body=json.dumps({"items": [TAGGABLE], "hasMore": False}))

    async def scheduled(route):
        req = route.request
        if req.method != "POST":
            return await route.fallback()
        hold["bodies"].append(req.post_data_json)
        if len(hold["bodies"]) == 1:  # the first is refused, once the owner is in another chat
            await hold["release"].wait()
            return await route.fulfill(status=400, content_type="application/json",
                                       body=json.dumps({"detail": FANSLY_NOTE}))
        await route.continue_()  # the restored one goes to the relay

    routes = ((lambda u: urlsplit(u).path == "/api/of/v2/chats", chats),
              (lambda u: urlsplit(u).path == "/api/of/v2/posts/tagged-friend-users", tagged),
              (lambda u: urlsplit(u).path == "/api/of/v2/scheduled-sends", scheduled))
    for pat, fn in routes:
        await page.route(pat, fn)
    n_status = len(page.slop["statuses"])
    rows_before = _scheduled_rows(ctx, c["id"])
    box = page.get_by_placeholder(INPUT, exact=True)
    bar = page.get_by_role("toolbar", name="Composer buttons")
    notice = page.get_by_role("alert").filter(has_text="Not scheduled")

    async def open_chat(fan) -> None:
        await page.locator("[data-chat-row]").filter(has_text=f"@{fan['username']}").first.click(timeout=WAIT_MS)
        await box.wait_for(timeout=WAIT_MS)
        await _painted(page)

    try:
        await page.goto(f"{ctx.app}/messages-pro", wait_until="domcontentloaded")
        await _creator_tab(page, c)
        await open_chat(fan_a)
        await bar.get_by_role("button", name="PPV", exact=True).click(timeout=10_000)
        await page.get_by_role("textbox", name="PPV price").fill("5")
        await page.get_by_role("checkbox", name="lock text").check()
        await page.get_by_role("button", name="Tag other Creators", exact=True).click()
        tag_pop = page.get_by_role("region", name="Tag other Creators")
        await tag_pop.get_by_role("button", name=re.compile(TAGGABLE["name"])).click(timeout=30_000)
        await tag_pop.get_by_role("button", name="Add", exact=True).click()
        await box.fill(REFUSED_TEXT)
        await bar.get_by_role("button", name="Timed message", exact=True).click()
        await page.get_by_role("group", name="Send at presets").get_by_role("button", name="+5m").click()
        await box.click()
        await box.press("Enter")
        await _until(lambda: len(hold["bodies"]) >= 1, 30)
        sent = hold["bodies"][0] if hold["bodies"] else None
        await open_chat(fan_b)  # the owner moves on while the schedule is in flight
        hold["release"].set()
        shown = None
        try:
            await notice.first.wait_for(timeout=15_000)
            await _painted(page)
            shown = await notice.first.inner_text()
        except Exception:  # noqa: BLE001 — judged below: no notice in the other chat
            pass
        b_box = await box.input_value()
        b_restore = await notice.get_by_role("button", name="Restore").count()
        await ui.shot(ctx, page, "chat-refused-other-chat")
        names = [n for n in (fan_a.get("name"), fan_a.get("username"), fan_a.get("displayName")) if n]
        out_shown = {"sent": sent, "notice": shown, "b_input": b_box, "b_restore_buttons": b_restore,
                     "fan_a": names, "fan_b": fan_b.get("username")}
        chk(CHAT_REFUSED_SHOWN, bool(sent) and sent.get("price") == 5 and sent.get("tagged_users") == [TAGGABLE["id"]]
            and shown is not None and "Not scheduled in the chat with" in shown and REFUSED_TEXT in shown
            and FANSLY_NOTE in shown and "Open that chat to restore it" in shown and any(n in shown for n in names)
            and b_restore == 0 and b_box == "", **out_shown)

        await open_chat(fan_a)
        restore = notice.get_by_role("button", name="Restore")
        restored, after = False, {}
        try:
            await restore.first.click(timeout=15_000)
            restored = True
        except Exception:  # noqa: BLE001 — judged below: nothing to restore in its own chat
            pass
        if restored:
            await _painted(page)
            after = {"text": await box.input_value(),
                     "price": await page.get_by_role("textbox", name="PPV price").input_value(),
                     "lock": await page.get_by_role("checkbox", name="lock text").is_checked(),
                     "tag": await page.get_by_role("button", name=f"Remove {TAGGABLE['name']}").count(),
                     "notices": await notice.count()}
        else:
            after = {"text": await box.input_value(), "notices": await notice.count()}
        await ui.shot(ctx, page, "chat-refused-restored")
        again, status = None, None
        if restored:
            is_sched = lambda r: (r.request.method == "POST"  # noqa: E731
                                  and urlsplit(r.url).path == "/api/of/v2/scheduled-sends")
            async with page.expect_response(is_sched, timeout=30_000) as resp:
                await box.click()
                await box.press("Enter")
            status = (await resp.value).status
            again = hold["bodies"][-1] if len(hold["bodies"]) >= 2 else None
            await page.get_by_text("Scheduled · sending in").first.wait_for(timeout=15_000)
            await ui.shot(ctx, page, "chat-refused-rescheduled")
        new_rows = [p for i, p in _scheduled_rows(ctx, c["id"]).items() if i not in rows_before]
        fives = [u for st, u in page.slop["statuses"][n_status:] if st >= 500]
        want = {"text": REFUSED_TEXT, "price": 5, "locked_text": True, "tagged_users": [TAGGABLE["id"]]}
        out = {"restored": restored, "after": after, "again": again, "relay_status": status, "rows": new_rows,
               "relay_5xx": fives[:5]}
        (ctx.out / "chat-refused.json").write_text(json.dumps({"shown": out_shown, **out}, indent=2, default=str))
        chk(CHAT_REFUSED_RESTORED, restored and after == {"text": REFUSED_TEXT, "price": "5", "lock": True,
                                                          "tag": 1, "notices": 0}
            and bool(again) and all(again.get(k) == v for k, v in want.items()) and str(again.get("fan_id")) == str(fan_a["id"])
            and status == 200 and len(new_rows) == 1 and all(new_rows[0].get(k) == v for k, v in want.items())
            and str(new_rows[0].get("fan_id")) == str(fan_a["id"]) and not fives, **out)
    finally:
        hold["release"].set()
        for pat, fn in routes:
            await page.unroute(pat, fn)


async def _chat_ppv(ctx, page, chk) -> None:
    """A PPV with a vault pick, an upload still running, a lock and 2 GIFs, sent from Creator 0's first Fan's
    chat: OF's wire gets the message with the first GIF once the upload lands, then the second GIF alone."""
    c = ctx.world.data["creators"][0]
    view = await _chat_view(ctx, ctx.world.data["creators"])
    fan = view[c["id"]][0]["withUser"]
    gifs = _giphy_gifs(ctx.app, [(g, f"slop gif {i + 1}") for i, g in enumerate(PPV_GIFS)])
    hold = {"release": asyncio.Event(), "uploads": 0, "sends": [], "released_t": None}

    async def chats(route):
        req = route.request
        if req.method != "GET":
            return await route.fallback()
        _aid, off, lim, _plain, rows = _chats_query(req, view)
        await _serve_chats(route, rows, off, lim)

    async def upload(route):
        hold["uploads"] += 1
        await hold["release"].wait()
        await route.fulfill(status=200, content_type="application/json", body=json.dumps(
            {"ready": True, "deduped": True, "vault_id": PPV_UPLOADED, "send_with": [PPV_UPLOADED],
             "existing": {"id": PPV_UPLOADED, "type": "photo", "files": None}}))

    async def send(route):
        req = route.request
        if req.method != "POST":
            return await route.fallback()
        hold["sends"].append({"t": time.time(), "body": req.post_data_json})
        await route.continue_()  # to the relay, whose OFClient sends to lib/of_wire.py

    send_path = f"/api/of/v2/chats/{fan['id']}/messages"
    routes = ((lambda u: urlsplit(u).path == "/api/of/v2/chats", chats),
              _giphy_route(gifs),
              (lambda u: urlsplit(u).path == "/api/of/v2/upload", upload),
              (lambda u: urlsplit(u).path == send_path, send))
    for pat, fn in routes:
        await page.route(pat, fn)
    n_status = len(page.slop["statuses"])
    with ctx.of_wire.lock:
        n_wire = len(ctx.of_wire.sends.get(c["id"], []))
    box = page.get_by_placeholder(INPUT, exact=True)
    png = ctx.out / "chat-ppv-upload.png"
    png.write_bytes(PNG_1PX)

    def wire() -> list[dict]:
        with ctx.of_wire.lock:
            return [m for m in ctx.of_wire.sends.get(c["id"], [])[n_wire:] if str(m["fan_id"]) == str(fan["id"])]

    try:
        await page.goto(f"{ctx.app}/messages-pro", wait_until="domcontentloaded")
        await _creator_tab(page, c)
        await page.locator("[data-chat-row]").filter(has_text=f"@{fan['username']}").first.click(timeout=WAIT_MS)
        await box.wait_for(timeout=WAIT_MS)
        await page.get_by_role("button", name="Vault", exact=True).click(timeout=10_000)
        await page.locator(f"[data-tile-id='{PPV_PICK}']").first.click(timeout=WAIT_MS)
        await page.get_by_role("button", name=re.compile(r"^Attach")).last.click(timeout=10_000)
        await page.get_by_label("Upload from computer", exact=True).set_input_files(str(png))
        await _until(lambda: hold["uploads"] >= 1, 30)
        await page.get_by_role("textbox", name="PPV price").fill("10")
        await page.get_by_role("checkbox", name="lock text").check()
        for g in gifs:
            await page.get_by_role("button", name="GIF", exact=True).click(timeout=10_000)
            await page.locator(f"button[title='{g['title']}']").first.click(timeout=30_000)
        await box.fill(PPV_TEXT)
        await _painted(page)
        await ui.shot(ctx, page, "chat-ppv-trigger")
        await box.press("Enter")
        await asyncio.sleep(PPV_UPLOAD_HOLD_S)  # the upload still runs: nothing may reach OF yet
        early = wire()
        hold["released_t"] = time.time()
        hold["release"].set()
        await _until(lambda: len(wire()) >= 2, 30)
        await asyncio.sleep(1.0)  # a third send would land here
        await _painted(page)
        await ui.shot(ctx, page, "chat-ppv-settled")
        got = wire()
        fives = [u for st, u in page.slop["statuses"][n_status:] if st >= 500]
        answered = [st for st, u in page.slop["statuses"][n_status:] if urlsplit(u).path == send_path]
        out = {"fan": fan["id"], "uploads": hold["uploads"], "released_t": hold["released_t"],
               "browser_sends": hold["sends"], "of_wire_early": early, "of_wire_sends": got,
               "relay_statuses": answered, "relay_5xx": fives[:5]}
        (ctx.out / "chat-ppv.json").write_text(json.dumps(out, indent=2, default=str))
        main, trail = (got + [{}, {}])[:2]
        mb, tb = main.get("body") or {}, trail.get("body") or {}
        chk(PPV_SEND_BODY, not early and len(got) == 2 and len(hold["sends"]) == 2
            and main.get("t", 0) >= hold["released_t"] and trail.get("t", 0) >= main.get("t", 0)
            and PPV_TEXT in (mb.get("text") or "") and mb.get("price") == 10 and mb.get("lockedText") is True
            and sorted(mb.get("mediaFiles") or []) == [PPV_PICK, PPV_UPLOADED] and mb.get("giphyId") == PPV_GIFS[0]
            and tb.get("giphyId") == PPV_GIFS[1] and not tb.get("text") and not tb.get("price")
            and not tb.get("mediaFiles") and answered == [200, 200] and not fives,
            early=len(early), sends=len(got), main=mb, trailing=tb, relay_statuses=answered,
            order=[m.get("t") for m in got], released_t=hold["released_t"])
    finally:
        hold["release"].set()
        for pat, fn in routes:
            await page.unroute(pat, fn)


BADGE = '[data-testid="bell-count"]'
N_ARRIVALS = 3


async def _badge(page) -> str | None:
    loc = page.locator(BADGE)
    return (await loc.first.inner_text()).strip() if await loc.count() else None


async def _wait_badge(page, want: str | None, timeout_ms: int = 30_000) -> str | None:
    """The top bar badge's text once it is `want` (None: no badge), or as it is after the timeout."""
    try:
        if want is None:
            await page.wait_for_function(f"() => !document.querySelector('{BADGE}')", timeout=timeout_ms)
        else:
            await page.wait_for_function(
                f"(w) => (document.querySelector('{BADGE}') || {{}}).textContent === w", arg=want, timeout=timeout_ms)
    except Exception:  # noqa: BLE001 — judged by the caller
        pass
    return await _badge(page)


CLEARED_COUNTER = """() => { window.__slopCleared = 0;
  window.addEventListener('chatterly:notif-cleared', () => { window.__slopCleared++; }); }"""


async def _bell(ctx, page, chk) -> None:
    w = ctx.world
    bell = page.locator('button[aria-label="Notifications"]').first
    unread0 = (await ctx.owner.get("/admin/agency-notifications?limit=1")).json().get("unread", 0)

    # Message toasts on, as the bell's Toast settings would (default off; notif_click's bypass).
    await page.goto(f"{ctx.app}/", wait_until="domcontentloaded")
    await page.evaluate("(s) => localStorage.setItem('chatterly:notif-settings:v1', s)", json.dumps(SETTINGS))
    # The DMs come to the Creator in scope (an earlier page may have picked one): the toaster
    # pings only for the scoped Creator, or any under All Models.
    scope = await page.evaluate("() => localStorage.getItem('chatterly:scope')") or "all"
    c = next((x for x in w.data["creators"] if scope == f"model:{x['id']}"), w.data["creators"][0])
    fans = distinct(w.data["fans"][c["id"]])[:N_ARRIVALS + 3]
    await page.goto(f"{ctx.app}/", wait_until="domcontentloaded")
    await bell.wait_for(timeout=WAIT_MS)
    await page.evaluate(CLEARED_COUNTER)
    await page.wait_for_timeout(3000)  # the toaster mounts deferred (1.5 s) and /events connects

    ids = iter(range(fan_dm.INJECT_ID_BASE + 888_000, fan_dm.INJECT_ID_BASE + 889_000))
    statuses, toasts = [], 0
    for f in fans:
        if toasts == N_ARRIVALS:
            break
        text = f"slop bell arrival {f['id']}"
        statuses.append((await fan_dm.inject(ctx.owner, c["id"], fan_dm.frame(next(ids), f, text))).status_code)
        try:  # a DM that shows no toast (the stream not up yet) counts nothing: another Fan DMs
            await page.locator("a.animate-toast-in").filter(has_text=text).first.wait_for(timeout=20_000)
            toasts += 1
        except Exception:  # noqa: BLE001
            pass
    want = str(toasts + unread0)
    before = await _wait_badge(page, want)
    await ui.shot(ctx, page, "bell-badge-trigger")
    await bell.click()
    await page.wait_for_timeout(800)
    expanded = await bell.get_attribute("aria-expanded")
    open_badge = await _badge(page)
    cleared = await page.evaluate("() => window.__slopCleared")
    await ui.shot(ctx, page, "bell-open-settled")
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(800)
    closed_badge = await _badge(page)
    left = str(unread0) if unread0 else None
    chk(BELL_CLEARS, toasts == N_ARRIVALS and all(s < 300 for s in statuses) and before == want
        and expanded == "true" and open_badge == left and closed_badge == left and cleared == 1,
        creator=c["id"], scope=scope, arrivals=toasts, frames=statuses, agency_unread_before=unread0, badge_before=before, want=want,
        aria_expanded=expanded, badge_open=open_badge, badge_after_close=closed_badge, cleared_events=cleared)

    # The owner's Agency notifications: seeded unread, read by the reload, marked read in the panel.
    seeded = agency_notifications.seed(w, w.data["creators"])
    api_before = (await ctx.owner.get("/admin/agency-notifications?limit=50")).json()
    await page.reload(wait_until="domcontentloaded")
    await bell.wait_for(timeout=WAIT_MS)
    m = str(api_before.get("unread"))
    shown = await _wait_badge(page, m)
    await bell.click()
    await page.get_by_role("tab", name="Agency").click(timeout=10_000)
    mark = page.get_by_role("button", name="Mark all read")
    await page.wait_for_function("(b) => b && !b.disabled", arg=await mark.element_handle(), timeout=30_000)
    await ui.shot(ctx, page, "bell-agency-mark-all-trigger")
    async with page.expect_response(lambda r: r.request.method == "POST"
                                    and urlsplit(r.url).path == "/admin/agency-notifications/read-all",
                                    timeout=30_000) as resp:
        await mark.click()
    status = (await resp.value).status
    con = w.sql()
    rows = con.execute(f"SELECT id, read_at FROM agency_notifications WHERE id IN ({','.join('?' * len(seeded))})",
                       seeded).fetchall()
    db_unread = con.execute("SELECT COUNT(*) FROM agency_notifications WHERE agency_user_id=? AND read_at IS NULL",
                            (w.user_id,)).fetchone()[0]
    con.close()
    api_after = (await ctx.owner.get("/admin/agency-notifications?limit=50")).json()
    await page.wait_for_timeout(800)
    await page.keyboard.press("Escape")
    after = await _wait_badge(page, None, 15_000)
    await ui.shot(ctx, page, "bell-agency-read-settled")
    read = [r for r in rows if r[1] is not None]
    (ctx.out / "bell-agency-read.json").write_text(json.dumps(
        {"seeded": seeded, "rows": rows, "status": status, "api_before": api_before.get("unread"),
         "api_after": api_after.get("unread"), "db_unread": db_unread}, indent=2, default=str))
    chk(AGENCY_READ, len(seeded) == len(w.data["creators"]) and shown == m and 200 <= status < 300
        and len(read) == len(seeded) and db_unread == 0 and api_after.get("unread") == 0 and after is None,
        seeded=len(seeded), badge_before=shown, api_unread_before=api_before.get("unread"), read_all=status,
        db_read=len(read), db_unread=db_unread, api_unread_after=api_after.get("unread"), badge_after_close=after,
        sample_read_at=[str(r[1]) for r in rows[:2]])


SCRIPT_KEEP, SCRIPT_NIGHT, SCRIPT_LATE = "slop Keep", "slop Night", "slop Late"
SCRIPT_TITLES = ("slop scr A", "slop scr B", "slop scr C")
RELABEL = "/admin/saved-replies/relabel"
# The selection bar as drawn: its count and each action button's disabled flag (null: no bar). The one probe of
# the bar; the predicates below judge its result.
SELECTION_BAR = """() => { const bar = document.querySelector('[role=toolbar][aria-label=Selection]');
  if (!bar) return null;
  const btns = [...bar.querySelectorAll('button')].filter((x) => x.getAttribute('aria-label') !== 'Clear selection');
  return { selected: (bar.textContent.match(/Selected\\s*(\\d+)/) || [])[1] || null,
           disabled: Object.fromEntries(btns.map((x) => [x.textContent.trim(), x.disabled])) }; }"""
BAR_BUSY = "(bar) => !!bar && Object.values(bar.disabled).some(Boolean)"
BAR_SETTLED = "(bar) => !bar || bar.disabled['Remove from tag'] === false"  # remove no longer busy, or no bar left
# What a Creator switch must not carry over, as drawn: whether the failed run's error text shows, the scripts whose
# remove / delete is disabled (busy) and the listed scripts, each named by its box ("Select <title>").
SWITCH_STATE = """(err) => { const rows = [...document.querySelectorAll('[aria-label="Scripts list"] li')];
  const title = (li) => (li.querySelector('input[type=checkbox][aria-label^="Select "]')?.getAttribute('aria-label')
    || '').slice('Select '.length);
  return { error: document.body.innerText.includes(err),
           busy: rows.filter((li) => [...li.querySelectorAll('button[aria-label^="Remove from"],button[aria-label=Delete]')]
             .some((b) => b.disabled)).map(title),
           titles: rows.map(title) }; }"""


async def _selection_bar(page, until: str, timeout_ms: int) -> dict | None:
    """SELECTION_BAR once `until(bar)` holds (or the wait ran out: the caller judges what it reads)."""
    try:
        await page.wait_for_function(f"() => ({until})(({SELECTION_BAR})())", timeout=timeout_ms)
    except PwTimeout:
        pass
    return await page.evaluate(SELECTION_BAR)


def _script_tags(ctx, ids: list[int]) -> dict[int, list[str]]:
    con = ctx.world.sql()
    rows = con.execute(f"SELECT id, tags_json FROM saved_replies WHERE id IN ({','.join('?' * len(ids))})",
                       ids).fetchall()
    con.close()
    return {r[0]: json.loads(r[1] or "[]") for r in rows}


async def _route_tags(ctx, aid: str) -> dict[int, list[str]]:
    lst = (await ctx.owner.get(f"/admin/saved-replies?account_id={aid}")).json().get("list", [])
    return {r["id"]: r.get("tags") or [] for r in lst}


async def _scripts(ctx, page, chk) -> None:
    # The Creator the page opens on: useScopedAccount takes the first active one with a session.
    accts = [a for a in (await ctx.owner.get("/admin/accounts")).json().get("accounts", [])
             if a.get("has_session") and a.get("is_active", True)]
    aid = accts[0]["id"]
    # The Creator the switch checks pick on the creator column (by nickname, so one of the world's Creators).
    world_ids = {c["id"] for c in ctx.world.data["creators"]}
    other = next(a["id"] for a in accts if a["id"] != aid and a["id"] in world_ids)
    ids = []
    for title in SCRIPT_TITLES:
        r = await ctx.owner.post(f"/admin/saved-replies?account_id={aid}",
                                 json={"title": title, "text": f"{title} text", "tags": [SCRIPT_KEEP]})
        r.raise_for_status()
        ids.append(r.json()["id"])
    a_id, b_id, c_id = ids
    listed = (await ctx.owner.get(f"/admin/saved-replies?account_id={aid}")).json()["list"]
    free_id = next(x["id"] for x in listed if x.get("title") == FREE_TPL["title"])

    fail = {"next": False}

    async def failing_relabel(route):
        if route.request.method == "POST" and fail["next"]:
            fail["next"] = False  # the relay healthy, the answer a refusal: answered at the browser's wire
            return await route.fulfill(status=500, content_type="application/json",
                                       body=json.dumps({"detail": "slop: relabel refused"}))
        await route.fallback()

    is_delete = lambda u: urlsplit(u).path == f"/admin/saved-replies/{free_id}"  # noqa: E731
    is_relabel = lambda u: urlsplit(u).path == RELABEL  # noqa: E731
    # The FREE template's DELETE held until the rename prompt is open; every relabel POST the page sent, with the
    # answer it got.
    async with held(page, is_delete, "DELETE") as hold:
        await page.route(is_relabel, failing_relabel)
        with recorded(page, "POST", RELABEL) as relabels:
            try:
                await _scripts_steps(ctx, page, chk, (aid, other), (a_id, b_id, c_id), relabels, hold, fail)
            finally:
                await page.unroute(is_relabel, failing_relabel)
                (ctx.out / "scripts-relabels.json").write_text(json.dumps(relabels, indent=2))


async def _scripts_steps(ctx, page, chk, creators: tuple, ids: tuple, relabels: list, hold, fail: dict) -> None:
    """`creators`: the page's Creator and the one the switch checks pick; `hold`: lib/hold.py's Hold on the FREE
    template's DELETE; `fail["next"]`: the next relabel POST is answered 500 at the browser."""
    aid = creators[0]
    a_id, b_id, c_id = ids
    a_t, b_t, c_t = SCRIPT_TITLES
    tags_aside = page.locator('aside[aria-label="Tags"]')
    side_row = lambda name: tags_aside.locator("div[role=button]").filter(  # noqa: E731
        has=page.locator("span", has_text=re.compile(f"^{re.escape(name)}$")))
    scripts = page.get_by_role("list", name="Scripts list")
    row = lambda title: scripts.locator("li").filter(has_text=title)  # noqa: E731
    box = lambda title: page.get_by_role("checkbox", name=f"Select {title}", exact=True)  # noqa: E731

    await page.goto(f"{ctx.app}/growth/scripts", wait_until="domcontentloaded")
    await row(FREE_TPL["title"]).first.wait_for(timeout=WAIT_MS)

    # ── rename after a mid-prompt refetch ──
    more = page.get_by_role("button", name="More", exact=True).and_(page.locator("[aria-haspopup=menu]"))
    await more.last.click(timeout=10_000)
    await page.get_by_role("menuitem", name="Add tag").click(timeout=10_000)
    dlg = page.get_by_role("dialog", name="Add tag name")
    await dlg.locator("#script-name-modal-input").fill(SCRIPT_NIGHT)
    await dlg.get_by_role("button", name="OK").click()
    await dlg.wait_for(state="hidden", timeout=10_000)
    await side_row(SCRIPT_NIGHT).wait_for(timeout=10_000)
    r = await ctx.owner.post(f"{RELABEL}?account_id={aid}", json={"kind": "tag", "to": SCRIPT_NIGHT, "ids": [a_id]})
    other_session = r.status_code
    await side_row("All scripts").click()
    await row(FREE_TPL["title"]).first.get_by_role("button", name="Delete").click(timeout=10_000)  # confirm accepted
    await asyncio.wait_for(hold.seen.wait(), 15)
    await side_row(SCRIPT_NIGHT).get_by_role("button", name=f"{SCRIPT_NIGHT} menu").click(timeout=10_000)
    await page.get_by_role("menuitem", name="Rename").click(timeout=10_000)
    prompt = page.get_by_role("dialog", name="Modify tag name")
    await prompt.wait_for(timeout=10_000)
    night_at_open = await side_row(SCRIPT_NIGHT).inner_text()  # the race is real: no script carries Night yet
    async with page.expect_response(lambda x: x.request.method == "GET"
                                    and urlsplit(x.url).path == "/admin/saved-replies", timeout=30_000) as refetch:
        hold.release.set()
    await refetch.value
    try:  # the refetch shows Night carried by A under the open prompt
        await side_row(SCRIPT_NIGHT).filter(has_text="1 script").wait_for(timeout=10_000)
    except Exception:  # noqa: BLE001 — judged below
        pass
    night_before_ok = await side_row(SCRIPT_NIGHT).inner_text() if await side_row(SCRIPT_NIGHT).count() else None
    await ui.shot(ctx, page, "scripts-rename-prompt-refetched")
    n0 = len(relabels)
    await prompt.locator("#script-name-modal-input").fill(SCRIPT_LATE)
    await prompt.get_by_role("button", name="OK").click()
    await prompt.wait_for(state="hidden", timeout=15_000)
    await _until(lambda: all(x["status"] is not None for x in relabels[n0:]), 10)
    try:  # the refetch after the POST shows A under Late
        await side_row(SCRIPT_LATE).filter(has_text="1 script").wait_for(timeout=10_000)
    except Exception:  # noqa: BLE001 — judged below
        pass
    sent = [{"body": x["body"], "status": x["status"], "account": parse_qs(urlsplit(x["url"]).query).get(
        "account_id", [None])[0]} for x in relabels[n0:]]
    late_row = await side_row(SCRIPT_LATE).inner_text() if await side_row(SCRIPT_LATE).count() else None
    night_left = await side_row(SCRIPT_NIGHT).count()
    await ui.shot(ctx, page, "scripts-renamed")
    route_a = (await _route_tags(ctx, aid)).get(a_id)
    db_a = _script_tags(ctx, [a_id]).get(a_id)
    want_tags = [SCRIPT_KEEP, SCRIPT_LATE]
    chk(SCRIPTS_RENAME, other_session == 200 and "0 scripts" in night_at_open
        and night_before_ok is not None and "1 script" in night_before_ok
        and sent == [{"body": {"kind": "tag", "from": SCRIPT_NIGHT, "to": SCRIPT_LATE}, "status": 200, "account": aid}]
        and route_a == want_tags and db_a == want_tags and late_row is not None and "1 script" in late_row
        and night_left == 0,
        other_session=other_session, night_at_open=night_at_open, night_under_prompt=night_before_ok,
        relabel_posts=sent, route=route_a, db=db_a,
        want=want_tags, late_row=late_row, night_rows_after=night_left, account=aid)

    # ── Remove from tag: success, then a failure, then a refetch ──
    await side_row(SCRIPT_KEEP).click()
    for t in (a_t, b_t, c_t):
        await row(t).first.wait_for(timeout=10_000)
    toolbar = page.get_by_role("toolbar", name="Selection")
    await box(b_t).check()
    n1 = len(relabels)
    # B's relabel POST held at the browser's wire: while it is out the bar must stay, every action disabled.
    async with held(page, lambda u: urlsplit(u).path == RELABEL, "POST") as rm_hold:
        await toolbar.get_by_role("button", name="Remove from tag").click(timeout=10_000)  # confirm accepted
        await asyncio.wait_for(rm_hold.seen.wait(), 15)
        # the busy render lands a beat after the fetch left; the POST is held, so busy cannot end meanwhile
        busy_bar = await _selection_bar(page, BAR_BUSY, 5_000)
        await _painted(page)
        await ui.shot(ctx, page, "scripts-remove-busy")
        rm_hold.release.set()
        await row(b_t).first.wait_for(state="detached", timeout=15_000)
    chk(SCRIPTS_BAR_BUSY, busy_bar == {"selected": "1", "disabled": {"Add to tag": True, "Remove from tag": True}}
        and len(rm_hold.bodies) == 1,
        bar_while_held=busy_bar, relabel_bodies=rm_hold.bodies)
    ok_sent = [{"body": x["body"], "status": x["status"]} for x in relabels[n1:]]
    ok_route = (await _route_tags(ctx, aid)).get(b_id)
    ok_db = _script_tags(ctx, [b_id]).get(b_id)
    r = await ctx.owner.post(f"{RELABEL}?account_id={aid}", json={"kind": "tag", "to": SCRIPT_KEEP, "ids": [b_id]})
    put_back = r.status_code

    a_before = (await _route_tags(ctx, aid)).get(a_id)  # Keep and the rename's tag (judged by the rename check)
    await box(a_t).check()
    fail["next"] = True
    n2 = len(relabels)
    await toolbar.get_by_role("button", name="Remove from tag").click(timeout=10_000)
    err = page.get_by_text(re.compile(r"^HTTP 500"))
    await err.first.wait_for(timeout=15_000)
    await _until(lambda: relabels[n2:] and all(x["status"] is not None for x in relabels[n2:]), 10)
    fail_bar = await _selection_bar(page, BAR_SETTLED, 10_000)
    await _painted(page)
    failed = {"listed": await row(a_t).count(), "ticked": await box(a_t).is_checked() if await box(a_t).count() else None,
              "bar": fail_bar, "error": await err.first.inner_text()}
    fail_sent = [{"body": x["body"], "status": x["status"]} for x in relabels[n2:]]
    await ui.shot(ctx, page, "scripts-remove-failed")
    fail_route = (await _route_tags(ctx, aid)).get(a_id)
    fail_db = _script_tags(ctx, [a_id]).get(a_id)
    chk(SCRIPTS_REMOVE_FAIL, failed["listed"] == 1 and failed["ticked"] is True
        and (fail_bar or {}).get("selected") == "1"
        and fail_sent == [{"body": {"kind": "tag", "from": SCRIPT_KEEP, "ids": [a_id]}, "status": 500}]
        and SCRIPT_KEEP in (a_before or []) and fail_route == a_before and fail_db == a_before,
        shown=failed, relabel_posts=fail_sent, route=fail_route, db=fail_db, want=a_before)

    # C's own Remove succeeds and refetches: B (put back by the other session) is listed again, unticked.
    n3 = len(relabels)
    await row(c_t).first.get_by_role("button", name="Remove from tag").click(timeout=10_000)
    await row(c_t).first.wait_for(state="detached", timeout=15_000)
    await row(b_t).first.wait_for(timeout=15_000)
    b_ticked = await box(b_t).is_checked()
    c_sent = [{"body": x["body"], "status": x["status"]} for x in relabels[n3:]]
    await ui.shot(ctx, page, "scripts-remove-settled")
    db_b = _script_tags(ctx, [b_id]).get(b_id)
    chk(SCRIPTS_REMOVE_OK, ok_sent == [{"body": {"kind": "tag", "from": SCRIPT_KEEP, "ids": [b_id]}, "status": 200}]
        and ok_route == [] and ok_db == [] and put_back == 200 and c_sent == [
            {"body": {"kind": "tag", "from": SCRIPT_KEEP, "ids": [c_id]}, "status": 200}]
        and b_ticked is False and db_b == [SCRIPT_KEEP],
        relabel_posts=ok_sent, route_after_remove=ok_route, db_after_remove=ok_db, put_back=put_back,
        refetch_by=c_sent,
        b_ticked_after_refetch=b_ticked, db_b=db_b)

    await _scripts_switch(ctx, page, chk, creators, a_id, relabels, fail, row, side_row)


def _switch_clear(st: dict, title: str) -> bool:
    """SWITCH_STATE read: no error, no busy row, `title` listed."""
    return not st["error"] and st["busy"] == [] and title in st["titles"]


def _switch_on_other(st: dict) -> bool:
    """SWITCH_STATE read on the other Creator: clear, its seeded FREE template listed, none of A's scripts."""
    return _switch_clear(st, FREE_TPL["title"]) and SCRIPT_TITLES[0] not in st["titles"]


async def _scripts_switch(ctx, page, chk, creators: tuple, a_id: int, relabels: list, fail: dict, row,
                          side_row) -> None:
    """Two Creator switches on the page's creator column, each from A's Remove from tag answered 500 (on "slop Keep"):
    settled (`_switch_settled`) then in flight (`_switch_in_flight`); A's script keeps its tag (route)."""
    aid, other = creators
    a_t = SCRIPT_TITLES[0]
    nick = {c["id"]: c["nickname"] for c in ctx.world.data["creators"]}

    async def switch(to: str, err_text: str, shot: str | None = None) -> dict:
        """Picks Creator `to`; on the other Creator, waits for A's rows to go (its list carries the seeded templates,
        not A's scripts), on A for A's row. SWITCH_STATE for `err_text`."""
        await ui.pick_creator(page, nick[to], timeout_ms=WAIT_MS)
        if to == aid:
            await row(a_t).first.wait_for(timeout=WAIT_MS)
        else:
            await row(a_t).first.wait_for(state="detached", timeout=WAIT_MS)
            await row(FREE_TPL["title"]).first.wait_for(timeout=WAIT_MS)
        await _painted(page)
        if shot:
            await ui.shot(ctx, page, shot)
        return await page.evaluate(SWITCH_STATE, err_text)

    a_before = (await _route_tags(ctx, aid)).get(a_id)
    want_sent = [{"body": {"kind": "tag", "from": SCRIPT_KEEP, "ids": [a_id]}, "status": 500}]
    remove_a = row(a_t).first.get_by_role("button", name="Remove from tag")
    settled_ok, settled = await _switch_settled(ctx, page, switch, creators, remove_a, relabels, fail, want_sent)
    flight_ok, flight = await _switch_in_flight(ctx, page, switch, creators, remove_a, side_row, relabels, fail,
                                                want_sent, settled["error"])
    route_a = (await _route_tags(ctx, aid)).get(a_id)
    chk(SCRIPTS_SWITCH_CLEARS, settled_ok and flight_ok and SCRIPT_KEEP in (a_before or []) and route_a == a_before,
        other_creator=other, settled=settled, in_flight=flight, route=route_a, want=a_before)


async def _switch_settled(ctx, page, switch, creators: tuple, remove_a, relabels: list, fail: dict,
                          want_sent: list) -> tuple[bool, dict]:
    """A's remove answered 500, its error shown; then the other Creator and A again: neither shows it."""
    aid, other = creators
    a_t = SCRIPT_TITLES[0]
    fail["next"] = True
    n = len(relabels)
    await remove_a.click(timeout=10_000)  # confirm accepted
    err = page.get_by_text(re.compile(r"^HTTP 500"))
    await err.first.wait_for(timeout=15_000)
    err_text = await err.first.inner_text()
    await _until(lambda: relabels[n:] and all(x["status"] is not None for x in relabels[n:]), 10)
    sent = [{"body": x["body"], "status": x["status"]} for x in relabels[n:]]
    trigger = await page.evaluate(SWITCH_STATE, err_text)
    await _painted(page)
    await ui.shot(ctx, page, "scripts-switch-trigger")
    on_other = await switch(other, err_text, "scripts-switch-other")
    back = await switch(aid, err_text, "scripts-switch-settled")
    ok = (trigger["error"] and a_t in trigger["titles"] and sent == want_sent
          and _switch_on_other(on_other) and _switch_clear(back, a_t))
    return bool(ok), {"error": err_text, "trigger": trigger, "relabel_posts": sent, "on_other": on_other,
                      "back": back}


async def _switch_in_flight(ctx, page, switch, creators: tuple, remove_a, side_row, relabels: list, fail: dict,
                            want_sent: list, err_text: str) -> tuple[bool, dict]:
    """A's remove held at the browser's wire while the owner leaves A and comes back (A's row still busy), then
    leaves again: its 500 lands on the other Creator, which shows no error; back on A the row is free, no error,
    one POST."""
    aid, other = creators
    a_t = SCRIPT_TITLES[0]
    await side_row(SCRIPT_KEEP).click()  # A reopens on All scripts: Remove from tag lives on the tag
    await remove_a.wait_for(timeout=10_000)
    fail["next"] = True
    n = len(relabels)
    async with held(page, lambda u: urlsplit(u).path == RELABEL, "POST") as hold:
        await remove_a.click(timeout=10_000)  # confirm accepted
        await asyncio.wait_for(hold.seen.wait(), 15)
        await switch(other, err_text)
        held_back = await switch(aid, err_text, "scripts-switch-inflight-back")  # A's row still waits for its answer
        await switch(other, err_text)
        hold.release.set()
        await _until(lambda: relabels[n:] and all(x["status"] is not None for x in relabels[n:]), 15)
        try:  # the failure's render, if the page shows it here (it must not): a beat after the answer
            await page.wait_for_function("(e) => document.body.innerText.includes(e)", arg=err_text, timeout=3_000)
        except PwTimeout:
            pass
        landed_other = await page.evaluate(SWITCH_STATE, err_text)
        await ui.shot(ctx, page, "scripts-switch-inflight-other")
    sent = [{"body": x["body"], "status": x["status"]} for x in relabels[n:]]
    await switch(aid, err_text)
    try:  # the run's end frees A's row
        await page.wait_for_function(f"(e) => ({SWITCH_STATE})(e).busy.length === 0", arg=err_text, timeout=10_000)
    except PwTimeout:
        pass
    landed_back = await page.evaluate(SWITCH_STATE, err_text)
    await ui.shot(ctx, page, "scripts-switch-inflight-settled")
    ok = (held_back["busy"] == [a_t] and not held_back["error"] and sent == want_sent
          and _switch_on_other(landed_other) and _switch_clear(landed_back, a_t))
    return bool(ok), {"held_back": held_back, "landed_on_other": landed_other, "landed_back": landed_back,
                      "relabel_posts": sent}


async def _until(cond, timeout_s: float) -> bool:
    loop = asyncio.get_running_loop()
    t_end = loop.time() + timeout_s
    while not cond() and loop.time() < t_end:
        await asyncio.sleep(0.1)
    return cond()


async def _session(ctx, page, chk) -> None:
    mode = {"v": None}
    hits = {"abort": 0, "401": 0}

    async def me(route):
        if mode["v"] == "abort":
            hits["abort"] += 1
            return await route.abort("internetdisconnected")
        if mode["v"] == "401":
            hits["401"] += 1
            return await route.fulfill(status=401, content_type="application/json",
                                       body=json.dumps({"detail": "Not authenticated"}))
        await route.fallback()

    async def focus(kind: str) -> int:
        """Window focus until one /auth/me of `kind` was answered (a revalidate already in flight
        swallows a focus); the count before."""
        before = hits[kind]
        for _ in range(10):
            await page.evaluate("() => window.dispatchEvent(new Event('focus'))")
            if await _until(lambda: hits[kind] > before, 2):
                break
        await page.wait_for_timeout(1000)  # the answer's render
        return hits[kind] - before

    async def seen() -> dict:
        return {"signin_form": await form.count(), "retry_screen": await page.locator(RETRY).count(),
                "shell": await shell.is_visible(),
                "snapshot": await page.evaluate(f"() => localStorage.getItem('{SNAPSHOT_KEY}') !== null")}

    async def signed_in() -> None:
        await shell.wait_for(timeout=WAIT_MS)
        await page.wait_for_function(f"() => localStorage.getItem('{SNAPSHOT_KEY}') !== null", timeout=30_000)

    owner_id = ((await ctx.owner.get("/auth/me")).json() or {}).get("user_id")
    me_path = lambda u: urlsplit(u).path == "/auth/me"  # noqa: E731
    await page.route(me_path, me)
    shell = page.get_by_role("button", name="New Message").first
    form = page.locator('section[aria-label="Sign in"]')
    await page.goto(f"{ctx.app}/growth/smart-messages", wait_until="domcontentloaded")
    await signed_in()
    await ui.shot(ctx, page, "session-signed-in")

    mode["v"] = "abort"
    n = await focus("abort")
    net = await seen()
    await ui.shot(ctx, page, "session-revalidate-neterror")
    chk(SESSION_NET_KEEP, n >= 1 and net == {"signin_form": 0, "retry_screen": 0, "shell": True, "snapshot": True},
        aborted=n, seen=net)

    mode["v"] = "401"
    n = await focus("401")
    await form.wait_for(timeout=15_000)
    out = await seen()
    relay_me = (await ctx.owner.get("/auth/me")).json() or {}
    await ui.shot(ctx, page, "session-revalidate-401")
    chk(SESSION_401_OUT, n >= 1 and out == {"signin_form": 1, "retry_screen": 0, "shell": False, "snapshot": False}
        and relay_me.get("user_id") == owner_id, refused=n, seen=out, relay_me=relay_me, owner=owner_id)

    mode["v"] = None
    await page.reload(wait_until="domcontentloaded")
    await signed_in()  # the real /auth/me signs back in and writes the snapshot
    mode["v"] = "abort"
    before = hits["abort"]
    await page.reload(wait_until="domcontentloaded")
    await page.locator(RETRY).wait_for(timeout=WAIT_MS)
    await page.wait_for_timeout(500)
    boot = await seen()
    await ui.shot(ctx, page, "session-boot-neterror")
    mode["v"] = None
    await page.reload(wait_until="domcontentloaded")
    await signed_in()
    back = await seen()
    await ui.shot(ctx, page, "session-signed-back-in")
    chk(SESSION_BOOT_OUT, hits["abort"] > before and boot == {"signin_form": 0, "retry_screen": 1, "shell": False, "snapshot": True}
        and back == {"signin_form": 0, "retry_screen": 0, "shell": True, "snapshot": True},
        aborted=hits["abort"] - before, boot=boot, back=back)
    await page.unroute(me_path)


AR_LISTS = [{"id": 711, "name": "slop VIP", "type": "custom", "usersCount": 4},
            {"id": 722, "name": "slop Regulars", "type": "custom", "usersCount": 9}]
AR_KEPT = {"quiet_hours_json": [2, 7], "max_nudges": 3}  # knobs the page does not edit; a save must keep them


async def _autoreply(ctx, page, chk) -> None:
    aid = ctx.world.data["creators"][0]["id"]
    r = await ctx.owner.request("PUT", "/admin/autoreply-config", json={"account_id": aid, "config": AR_KEPT})
    r.raise_for_status()

    async def lists(route):
        if route.request.method != "GET":
            return await route.fallback()
        await route.fulfill(status=200, content_type="application/json",
                            body=json.dumps({"list": AR_LISTS, "hasMore": False}))

    is_lists = lambda u: urlsplit(u).path == "/api/of/v2/lists"  # noqa: E731
    await page.route(is_lists, lists)
    await page.goto(f"{ctx.app}/growth/auto-reply?creator={aid}", wait_until="domcontentloaded")
    delay = page.get_by_role("spinbutton", name="Reply delay in minutes")
    await delay.wait_for(timeout=WAIT_MS)
    sw = lambda name: page.get_by_role("switch", name=name, exact=True)  # noqa: E731
    await sw("Human style").wait_for(timeout=WAIT_MS)
    folder = page.get_by_role("checkbox", name=re.compile(r"slop VIP"))
    await folder.wait_for(timeout=WAIT_MS)

    await sw("Auto-reply").click()
    await delay.fill("9")
    await sw("Randomise").click()
    await folder.check()
    await sw("Only if he spent less than").click()
    await page.get_by_role("spinbutton", name="Folder spend cap in dollars").fill("120")
    await sw("New fans").click()
    await page.get_by_role("spinbutton", name="New fan window in hours").fill("48")
    await page.get_by_role("spinbutton", name="New fan spend cap in dollars").fill("7")
    await sw("Describe photos fans send").click()
    await sw("Don't reply to photo-only messages").click()
    await sw("Realistic typos").click()
    for name, want in (("Don't reply to photo-only messages", "true"), ("Realistic typos", "false")):
        await _wait_value(sw(name), want, 10_000, attr="aria-checked")
    await _painted(page)
    await ui.shot(ctx, page, "autoreply-edited-trigger")

    async with page.expect_response(lambda x: x.request.method == "PUT" and "/admin/autoreply-config" in x.url,
                                    timeout=30_000) as put1, \
            page.expect_response(lambda x: x.request.method == "PUT" and "/admin/style-config" in x.url,
                                 timeout=30_000) as put2:
        await page.get_by_role("button", name="Save", exact=True).click()
    puts = {"autoreply": (await put1.value).status, "style": (await put2.value).status}
    await page.get_by_text("Saved", exact=True).wait_for(timeout=30_000)

    got_get = lambda p: lambda x: x.request.method == "GET" and urlsplit(x.url).path == p  # noqa: E731
    async with page.expect_response(got_get("/admin/autoreply-config"), timeout=WAIT_MS) as cfg_get, \
            page.expect_response(got_get("/admin/style-config"), timeout=WAIT_MS) as style_get:
        await page.reload(wait_until="domcontentloaded")
    await cfg_get.value
    await style_get.value
    await delay.wait_for(timeout=WAIT_MS)
    await sw("Human style").wait_for(timeout=WAIT_MS)
    await folder.wait_for(timeout=WAIT_MS)
    # A response event fires on its headers: the form seeds from each read a beat later. Wait (bounded) for one
    # field of each (the config's delay, the style's typos), then judge them all.
    await _wait_value(delay, "9", 10_000)
    await _wait_value(sw("Realistic typos"), "false", 10_000, attr="aria-checked")
    await _painted(page)
    on = lambda name: sw(name).get_attribute("aria-checked")  # noqa: E731
    shown = {
        "enabled": await on("Auto-reply"), "delay": await delay.input_value(), "randomise": await on("Randomise"),
        "folder": await folder.is_checked(), "cap_on": await on("Only if he spent less than"),
        "cap": await page.get_by_role("spinbutton", name="Folder spend cap in dollars").input_value(),
        "new_on": await on("New fans"),
        "new_hours": await page.get_by_role("spinbutton", name="New fan window in hours").input_value(),
        "new_max": await page.get_by_role("spinbutton", name="New fan spend cap in dollars").input_value(),
        "describe": await on("Describe photos fans send"),
        "skip_photo_only": await on("Don't reply to photo-only messages"), "typos": await on("Realistic typos"),
    }
    await ui.shot(ctx, page, "autoreply-reloaded-settled")
    want_shown = {"enabled": "true", "delay": "9", "randomise": "true", "folder": True, "cap_on": "true",
                  "cap": "120", "new_on": "true", "new_hours": "48", "new_max": "7", "describe": "true",
                  "skip_photo_only": "true", "typos": "false"}
    chk(AUTOREPLY_RELOAD, shown == want_shown, shown=shown, want=want_shown,
        diff={k: [shown.get(k), v] for k, v in want_shown.items() if shown.get(k) != v})

    got = (await ctx.owner.get(f"/admin/autoreply-config?account_id={aid}")).json()
    style = (await ctx.owner.get(f"/admin/style-config?account_id={aid}")).json()
    (ctx.out / "autoreply-get.json").write_text(json.dumps({"autoreply": got, "style": style}, indent=2))
    cfg = got.get("config") or {}
    want_cfg = {**AR_KEPT, "enabled": True, "silence_min_minutes": 9, "step_in_max_minutes": 18,
                "folders_enabled": True, "list_ids": [711], "folder_max_spend_cents": 12_000,
                "new_fans_enabled": True, "new_fan_hours": 48, "new_fan_max_spend_cents": 700,
                "describe_photos": True, "skip_photo_only": True}
    typos = (style.get("config") or {}).get("typos_autoreply")
    chk(AUTOREPLY_STORED, puts == {"autoreply": 200, "style": 200} and cfg == want_cfg and typos is False,
        puts=puts, typos_autoreply=typos, account=aid,
        diff={k: [cfg.get(k), want_cfg.get(k)] for k in set(cfg) | set(want_cfg) if cfg.get(k) != want_cfg.get(k)})

    save = page.get_by_role("button", name="Save", exact=True)
    saved_label = page.get_by_text("Saved", exact=True)

    # A Delay typed while the settings PUT is held (the operator typing during a slow save).
    is_cfg = lambda u: urlsplit(u).path == "/admin/autoreply-config"  # noqa: E731
    async with held(page, is_cfg, "PUT") as cfg_hold:
        await delay.fill("11")
        await save.click()
        await asyncio.wait_for(cfg_hold.seen.wait(), 15)
        await delay.fill("13")  # while the PUT is out
        await _wait_value(delay, "13")
        await _painted(page)
        await ui.shot(ctx, page, "autoreply-delay-during-save")
        d_status = await release_settled(page, cfg_hold, refetch="/admin/autoreply-config", save=save)
        d_kept, d_row = await delay.input_value(), await _save_row(save)
        await save.scroll_into_view_if_needed()  # the Save row (no "Saved") in the picture
        await _painted(page)
        await ui.shot(ctx, page, "autoreply-delay-after-save")
        await save.click()
        await saved_label.wait_for(timeout=30_000)
        d_row_resaved = await _save_row(save)  # the probe sees "Saved" when it is there
    d_sent = [((b or {}).get("config") or {}).get("silence_min_minutes") for b in cfg_hold.bodies]
    d_stored = ((await ctx.owner.get(f"/admin/autoreply-config?account_id={aid}")).json()["config"] or {}).get(
        "silence_min_minutes")
    chk(AUTOREPLY_DRAFT_INFLIGHT, d_status == 200 and d_kept == "13" and d_row == SAVE_ROW_UNSAVED
        and d_row_resaved == SAVE_ROW_SAVED and d_sent == [11, 13] and d_stored == 13,
        held_status=d_status, kept_delay=d_kept, save_row_after_held=d_row,
        save_row_after_resave=d_row_resaved, sent_delays=d_sent,
        stored_delay=d_stored, account=aid)

    # A Human style box toggled while the style PUT is held.
    is_style = lambda u: urlsplit(u).path == "/admin/style-config"  # noqa: E731
    async with held(page, is_style, "PUT") as hold:
        await sw("Non-native English").click()
        await save.click()
        await asyncio.wait_for(hold.seen.wait(), 15)
        await sw("Human style").click()  # while the first box's PUT is out
        await _wait_value(sw("Human style"), "false", 10_000, attr="aria-checked")
        await _painted(page)
        await ui.shot(ctx, page, "autoreply-style-during-save")
        held_status = await release_settled(page, hold, refetch="/admin/style-config", save=save)
        kept, style_row = await sw("Human style").get_attribute("aria-checked"), await _save_row(save)
        await save.scroll_into_view_if_needed()
        await _painted(page)
        await ui.shot(ctx, page, "autoreply-style-landed")
        await save.click()  # a wiped edit sends no style PUT at all, so wait on the label, not a response
        await saved_label.wait_for(timeout=30_000)
        style_row_resaved = await _save_row(save)
    resave = [(b or {}).get("config") for b in hold.bodies[1:]]
    await _painted(page)
    await ui.shot(ctx, page, "autoreply-style-after-save")
    style2 = (await ctx.owner.get(f"/admin/style-config?account_id={aid}")).json().get("config") or {}
    pick = {k: style2.get(k) for k in ("autoreply", "nonnative_autoreply")}
    chk(AUTOREPLY_INFLIGHT, held_status == 200 and kept == "false"
        and style_row == SAVE_ROW_UNSAVED and style_row_resaved == SAVE_ROW_SAVED
        and resave == [{"autoreply": False}]
        and pick == {"autoreply": False, "nonnative_autoreply": False},
        held_status=held_status, kept_aria_checked=kept,
        save_row_after_held=style_row, save_row_after_resave=style_row_resaved, resave=resave,
        stored=pick, account=aid)
    await page.unroute(is_lists)


GTKF_KIND = "welcome_chatter_for_info"
GTKF_CAPTION = "slop closing caption"


GTKF_OFF_CAPTION = "slop parked caption"


async def _gtkf_rows(ctx, aid: str) -> list[tuple]:
    """(id, is_enabled, cutoff, caption, price cents) of the Creator's rules of the kind, from the run's DB."""
    import sqlite3
    con = sqlite3.connect(f"file:{ctx.world.db}?mode=ro", uri=True, timeout=30)
    try:
        rows = con.execute("SELECT id, is_enabled, steps_json FROM automation_rules WHERE account_id=? AND kind=? "
                           "ORDER BY id", (str(aid), GTKF_KIND)).fetchall()
    finally:
        con.close()
    out = []
    for rid, on, steps in rows:
        p = json.loads(steps or "{}")
        out.append((rid, int(on), p.get("max_fan_messages"), p.get("closing_ppv_text"),
                    p.get("closing_ppv_price_cents")))
    return out


async def _dark_shot(ctx, page, name: str) -> None:
    # The app's default theme (the harness browser runs light; ai-chatter-nav does the same): dark, phone.
    await page.evaluate("() => { localStorage.setItem('chatterly:theme', 'dark'); "
                        "document.documentElement.removeAttribute('data-theme'); }")
    await _painted(page)
    await ui.shot(ctx, page, name)


async def _gtkf_off(ctx, page, chk, aid: str) -> None:
    """GTKF_OFF on a 390x844 phone: no rule, switch off -> settings shown; Save parks a new rule; on, off keeps it."""
    await page.goto(f"{ctx.app}/growth/get-to-know-fans?creator={aid}", wait_until="domcontentloaded")
    sw = page.get_by_role("switch", name="Get to know fans", exact=True)
    await sw.wait_for(timeout=WAIT_MS)
    await page.wait_for_function("(b) => b && !b.disabled", arg=await sw.element_handle(), timeout=WAIT_MS)
    start = await sw.get_attribute("aria-checked")
    before = await _gtkf_rows(ctx, aid)
    card = await sw.evaluate("(b) => b.closest('section')?.querySelector('h2')?.textContent ?? null")
    in_header = await sw.evaluate("(b) => !!b.closest('header')")
    cutoff = page.get_by_role("spinbutton", name="Message cutoff")
    caption = page.get_by_role("textbox", name="Closing PPV caption")
    price = page.get_by_role("spinbutton", name="Closing PPV price in dollars")
    vals = lambda: asyncio.gather(cutoff.input_value(), caption.input_value(), price.input_value())  # noqa: E731
    try:
        await cutoff.wait_for(timeout=30_000)
    except PwTimeout:
        await _dark_shot(ctx, page, "gtkf-off-no-rule")
        chk(GTKF_OFF, False, switch_before=start, rows_before=before, account=aid,
            why="no Message cutoff with the switch off and no rule")
        return
    seeded = list(await vals())
    await _dark_shot(ctx, page, "gtkf-off-no-rule")

    await cutoff.fill("9")
    await caption.fill(GTKF_OFF_CAPTION)
    await price.fill("7")
    save = page.get_by_role("button", name="Save", exact=True).first
    with recorded(page, "POST", "/admin/automation-rules") as posts, \
            recorded(page, "POST", "/admin/automation-rules/switch") as switches:
        await save.click()
        await page.get_by_text("Saved", exact=True).wait_for(timeout=30_000)
    after_save = await _gtkf_rows(ctx, aid)
    switch_after_save = await sw.get_attribute("aria-checked")
    await save.scroll_into_view_if_needed()
    await _dark_shot(ctx, page, "gtkf-off-saved")

    async def flip(want: str) -> None:
        await sw.click()
        await page.wait_for_function("([b, w]) => b.getAttribute('aria-checked') === w && !b.disabled",
                                     arg=[await sw.element_handle(), want], timeout=30_000)
    await sw.scroll_into_view_if_needed()
    await flip("true")
    on_rows = await _gtkf_rows(ctx, aid)
    await flip("false")
    off_rows = await _gtkf_rows(ctx, aid)
    kept = list(await vals())
    await _dark_shot(ctx, page, "gtkf-on-off-kept")

    want = (9, GTKF_OFF_CAPTION, 700)
    body = (posts[0]["body"] or {}) if posts else {}
    rid = after_save[0][0] if after_save else None
    chk(GTKF_OFF, start == "false" and before == [] and card == "Automation" and not in_header
        and seeded[0] == "10" and seeded[2] == "10" and bool(seeded[1])
        and len(posts) == 1 and body.get("is_enabled") is False and switches == []
        and switch_after_save == "false" and after_save == [(rid, 0, *want)]
        and on_rows == [(rid, 1, *want)] and off_rows == [(rid, 0, *want)] and kept == ["9", GTKF_OFF_CAPTION, "7"],
        switch_before=start, rows_before=before, switch_card=card, in_header=in_header, seeded=seeded,
        posts=[{"status": p["status"], "body": p["body"]} for p in posts], switch_calls=len(switches),
        switch_after_save=switch_after_save, rows_after_save=after_save, rows_on=on_rows, rows_off=off_rows,
        kept=kept, account=aid)


async def _gtkf(ctx, page, chk) -> None:
    aid = ctx.world.data["creators"][0]["id"]
    await page.set_viewport_size({"width": PHONE[0], "height": PHONE[1]})
    try:
        await _gtkf_off(ctx, page, chk, aid)
    finally:
        await page.set_viewport_size({"width": VIEWPORT[0], "height": VIEWPORT[1]})
    # GTKF_INFLIGHT: the rule GTKF_OFF parked (or none, if it failed) is off; the switch wakes or creates it.
    await page.goto(f"{ctx.app}/growth/get-to-know-fans?creator={aid}", wait_until="domcontentloaded")
    header = page.get_by_role("switch", name="Get to know fans", exact=True)
    await header.wait_for(timeout=WAIT_MS)
    await page.wait_for_function("(b) => b && !b.disabled", arg=await header.element_handle(), timeout=WAIT_MS)
    cutoff = page.get_by_role("spinbutton", name="Message cutoff")
    start = await header.get_attribute("aria-checked")  # the world seeds no such rule: off
    if start != "false":  # a click would switch an existing rule off and time out later; fail here instead
        chk(GTKF_INFLIGHT, False, switch_before=start, account=aid, why="rule already on before the test")
        return
    await header.click()  # the real switch wakes the parked rule (creates one from the catalog defaults if none)
    await cutoff.wait_for(timeout=WAIT_MS)
    caption = page.get_by_role("textbox", name="Closing PPV caption")
    price = page.get_by_role("spinbutton", name="Closing PPV price in dollars")
    save = page.get_by_role("button", name="Save", exact=True).first  # the rule's; Model info's is the last
    saved_label = page.get_by_text("Saved", exact=True)

    is_rule = lambda u: re.fullmatch(r"/admin/automation-rules/\d+", urlsplit(u).path) is not None  # noqa: E731
    async with held(page, is_rule, "PATCH") as hold:
        await cutoff.fill("12")
        await save.click()
        await asyncio.wait_for(hold.seen.wait(), 15)
        await cutoff.fill("14")  # while the PATCH is out
        await caption.fill(GTKF_CAPTION)
        await price.fill("15")
        await _wait_value(price, "15")
        await _painted(page)
        await save.scroll_into_view_if_needed()
        await ui.shot(ctx, page, "gtkf-edit-during-save")
        status = await release_settled(page, hold, refetch="/admin/automation-rules", save=save)
        kept = [await cutoff.input_value(), await caption.input_value(), await price.input_value()]
        g_row = await _save_row(save)
        await save.scroll_into_view_if_needed()
        await _painted(page)
        await ui.shot(ctx, page, "gtkf-after-save")
        await save.click()
        await saved_label.wait_for(timeout=30_000)
        g_row_resaved = await _save_row(save)
    await _painted(page)
    await save.scroll_into_view_if_needed()
    await ui.shot(ctx, page, "gtkf-resaved")
    pick = lambda p: [p.get(k) for k in ("max_fan_messages", "closing_ppv_text", "closing_ppv_price_cents")]  # noqa: E731
    sent = [pick((b or {}).get("payload") or {}) for b in hold.bodies]
    rules = (await ctx.owner.get(f"/admin/automation-rules?account_id={aid}")).json()["rules"]
    stored = [pick(x["payload"] or {}) for x in rules if x["kind"] == GTKF_KIND]
    want = [14, GTKF_CAPTION, 1500]
    chk(GTKF_INFLIGHT, start == "false" and status == 200 and kept == ["14", GTKF_CAPTION, "15"]
        and g_row == SAVE_ROW_UNSAVED and g_row_resaved == SAVE_ROW_SAVED
        and len(sent) == 2 and sent[0][0] == 12 and sent[1] == want and stored == [want],
        switch_before=start, held_status=status, kept=kept,
        save_row_after_held=g_row, save_row_after_resave=g_row_resaved, sent=sent,
        stored=stored, account=aid)


def _lists_path(u: str) -> bool:
    return urlsplit(u).path == "/api/of/v2/lists"


async def _answer_lists(page, creators: list[dict]) -> None:
    """OF's lists at the browser's wire, per X-Account-Id (OF_LISTS); unroute with `_lists_path`."""
    by_id = {c["id"]: i for i, c in enumerate(creators)}

    async def lists(route):
        i = by_id.get(route.request.headers.get("x-account-id") or "")
        rows = [{"id": lid, "name": n, "type": "custom", "usersCount": 10} for lid, n in OF_LISTS.get(i, [])]
        await route.fulfill(status=200, content_type="application/json",
                            body=json.dumps({"list": rows, "hasMore": False}))

    await page.route(_lists_path, lists)


def _box(dlg, name: str, side: int):
    """A Priority mass list checkbox in the include (0) or exclude (1) column."""
    return dlg.get_by_role("checkbox", name=re.compile(rf"^{re.escape(name)}")).nth(side)


async def _post_as(dlg, aid: str, first_list: str) -> None:
    await dlg.locator("select").first.select_option(aid, timeout=30_000)
    await _box(dlg, first_list, 0).wait_for(timeout=WAIT_MS)


async def _audience_pm(ctx, page, chk) -> None:
    c = ctx.world.data["creators"]
    bodies: list[dict] = []

    async def runs(route):
        if route.request.method != "POST":
            return await route.fallback()
        bodies.append({"route": "/admin/priority-mass/runs", "body": route.request.post_data_json})
        await route.continue_()

    runs_path = lambda u: urlsplit(u).path == "/admin/priority-mass/runs"  # noqa: E731
    await _answer_lists(page, c)
    await page.route(runs_path, runs)
    await _open_create_message(ctx, page, re.compile(r"^Priority mass message"))
    dlg = page.get_by_role("dialog", name="Priority mass message")
    await dlg.wait_for(timeout=WAIT_MS)
    await _post_as(dlg, c[1]["id"], "C1 regulars")
    await _box(dlg, "C1 regulars", 0).click()
    await _box(dlg, "C1 tippers", 1).click()
    await ui.shot(ctx, page, "audience-pm-switch-trigger")
    await _post_as(dlg, c[0]["id"], "VIP")
    await _box(dlg, "VIP", 0).click()
    try:    # Creator 0's MASSDMEXCLUDE seed lands first, so Whales follows it in the excludes
        excl = await _box(dlg, "MASSDMEXCLUDE", 1).element_handle()
        await page.wait_for_function("(b) => b && b.checked", arg=excl, timeout=15_000)
    except Exception:  # noqa: BLE001 — recorded as PM_SWITCH's failure
        pass
    await _box(dlg, "Whales", 1).click()
    await dlg.get_by_label("Message").fill(PM_TEXT)
    await ui.shot(ctx, page, "audience-pm-switch-settled")
    async with page.expect_response(lambda r: r.request.method == "POST" and "/admin/priority-mass/runs" in r.url,
                                    timeout=30_000) as resp:
        await dlg.get_by_role("button", name="Send", exact=True).click(timeout=10_000)
    status = (await resp.value).status
    await page.wait_for_timeout(500)
    await ui.shot(ctx, page, "audience-pm-sent")
    (ctx.out / "audience-pm-bodies.json").write_text(json.dumps(bodies, indent=2))
    b = bodies[0]["body"] if bodies else {}
    keys = ("account_id", "user_lists", "excluded_user_lists")
    got = {k: b.get(k) for k in keys}
    want = {"account_id": c[0]["id"], "user_lists": ["fans", "following", "9101"], "excluded_user_lists": ["9103", "9102"]}
    chk(PM_SWITCH, status == 200 and len(bodies) == 1 and got == want, http_status=status, posts=len(bodies),
        got=got, want=want)

    con = ctx.world.sql()
    row = con.execute("SELECT audience_json FROM priority_mass_runs WHERE account_id=? AND text=?",
                      (c[0]["id"], PM_TEXT)).fetchone()
    con.close()
    aud = json.loads(row[0]) if row else None
    stored = {k: [str(x) for x in (aud or {}).get(k) or []] for k in keys[1:]}
    chk(PM_ROW, aud is not None and stored == {k: b.get(k) for k in keys[1:]}, row=aud, sent=got)
    await page.unroute(runs_path)
    await page.unroute(_lists_path)


async def _fl_chips(panel) -> dict:
    """The panel's chips, `in:<label>` / `out:<label>` (Send to row first, Exclude second) -> pressed."""
    seen: dict[str, int] = {}
    out = {}
    for label, pressed in await panel.locator("button[aria-pressed]").evaluate_all(
            "bs => bs.map(b => [b.textContent.trim(), b.getAttribute('aria-pressed') === 'true'])"):
        n = seen[label] = seen.get(label, 0) + 1
        out[f"{'in' if n == 1 else 'out'}:{label}"] = pressed
    return out


def _fl_start_btn(page):
    return page.get_by_role("button", name="Start funnel")


async def _fl_enabled(page, ms: int = 15_000) -> bool:
    for _ in range(ms // 250):
        if await _fl_start_btn(page).is_enabled():
            return True
        await page.wait_for_timeout(250)
    return False


async def _fl_start(page, bodies: list[dict]) -> tuple[dict, str]:
    n = len(bodies)
    await _fl_start_btn(page).click(timeout=10_000)  # confirm() accepted
    done = page.get_by_text(re.compile(r"^Funnel started"))
    await done.wait_for(timeout=15_000)
    return (bodies[n] if len(bodies) > n else {}), await done.inner_text()


async def _audience_fl(ctx, page, chk) -> None:
    c = ctx.world.data["creators"]
    bodies: list[dict] = []

    async def queue(route):
        if route.request.method != "POST":
            return await route.fallback()
        bodies.append({"route": "/api/of/v2/messages/queue", "account": route.request.headers.get("x-account-id"),
                       "body": route.request.post_data_json})
        await route.fulfill(status=200, content_type="application/json", body="{}")

    queue_path = lambda u: urlsplit(u).path == "/api/of/v2/messages/queue"  # noqa: E731
    lists_gate = asyncio.Event()  # OF's lists held until Start is seen disabled

    async def hold_lists(route):
        await lists_gate.wait()
        await route.fallback()

    await _answer_lists(page, c)
    await page.route(_lists_path, hold_lists)
    await page.route(queue_path, queue)
    await page.goto(f"{ctx.app}/growth/auto-funnel", wait_until="domcontentloaded", timeout=WAIT_MS)
    await ui.pick_creator(page, c[0]["nickname"], timeout_ms=WAIT_MS)
    await page.get_by_role("button", name="Start", exact=True).first.click(timeout=WAIT_MS)
    heading = page.get_by_role("heading", name=re.compile(r"^Start funnel"))
    panel = page.locator("div").filter(has=heading).filter(has=_fl_start_btn(page)).last
    await _fl_start_btn(page).wait_for(timeout=WAIT_MS)
    disabled_unseeded = await _fl_start_btn(page).is_disabled()
    lists_gate.set()
    await panel.get_by_role("button", name="MASSDMEXCLUDE", pressed=True).wait_for(timeout=WAIT_MS)
    enabled_seeded = await _fl_enabled(page)
    opened = await _fl_chips(panel)
    on = sorted(k for k, v in opened.items() if v)
    chk(FL_SEED, disabled_unseeded and enabled_seeded and on == ["in:All fans", "out:MASSDMEXCLUDE"]
        and "out:All fans" not in opened and "out:Following" not in opened, start_disabled_before_lists=disabled_unseeded,
        start_enabled_after_seed=enabled_seeded, on=on, chips=sorted(opened))

    funnel_name = (await heading.inner_text()).split("·", 1)[1].strip()
    funnels = (await ctx.owner.get("/admin/funnels")).json()["funnels"]
    funnel = next(f for f in funnels if f["name"] == funnel_name)
    await panel.get_by_role("button", name="VIP", exact=True).first.click()
    await ui.shot(ctx, page, "audience-fl-trigger")
    await ui.pick_creator(page, c[1]["nickname"], timeout_ms=WAIT_MS)
    panel_open = await heading.count()
    try:
        await panel.get_by_role("button", name="massdmexclude", pressed=True).wait_for(timeout=15_000)
    except Exception:  # noqa: BLE001 — the check below reports what is on
        pass
    on_after = sorted(k for k, v in (await _fl_chips(panel)).items() if v)
    await ui.shot(ctx, page, "audience-fl-switch-settled")
    await panel.get_by_role("button", name="C1 regulars", exact=True).first.click()
    await panel.get_by_role("button", name="C1 tippers", exact=True).nth(1).click()
    start_enabled = await _fl_enabled(page)
    sent, done = await _fl_start(page, bodies) if start_enabled else ({}, "")
    await ui.shot(ctx, page, "audience-fl-sent")
    (ctx.out / "audience-fl-bodies.json").write_text(json.dumps(bodies, indent=2))
    b = sent.get("body") or {}
    keys = ("text", "user_lists", "excluded_user_lists", "funnel_id")
    got = {k: b.get(k) for k in keys}
    want = {"text": funnel["opening_message"], "user_lists": ["fans", "9201"], "excluded_user_lists": ["9203", "9202"],
            "funnel_id": funnel["id"]}
    chk(FL_SWITCH, panel_open == 1 and on_after == ["in:All fans", "out:massdmexclude"] and len(bodies) == 1
        and got == want and sent.get("account") == c[1]["id"], panel_open_after_switch=panel_open, start_enabled=start_enabled,
        on_after_switch=on_after, posts=len(bodies), got=got, want=want, account=sent.get("account"), done=done)
    await page.unroute(queue_path)
    await page.unroute(_lists_path)


async def _funnel_media(ctx, page, chk) -> None:
    """Section 11b: the opener's vault pick saved through the pane; the GET holds it."""
    c = ctx.world.data["creators"][0]
    await page.goto(f"{ctx.app}/growth/auto-funnel", wait_until="domcontentloaded", timeout=WAIT_MS)
    await ui.pick_creator(page, c["nickname"], timeout_ms=WAIT_MS)
    await page.get_by_role("button", name="Media", exact=True).first.click(timeout=WAIT_MS)
    heading = page.get_by_role("heading", name=re.compile(r"^Funnel media · "))
    await heading.wait_for(timeout=WAIT_MS)
    funnel_name = (await heading.inner_text()).split("·", 1)[1].rsplit(" for ", 1)[0].strip()
    funnels = (await ctx.owner.get("/admin/funnels")).json()["funnels"]
    funnel = next(f for f in funnels if f["name"] == funnel_name)
    pane = page.locator("div").filter(has=heading).filter(has=page.get_by_role("button", name="Save media")).last
    await pane.get_by_role("button", name="Pick media").first.click(timeout=WAIT_MS)  # the opener row is first
    await page.locator(f"[data-tile-id='{PPV_PICK}']").first.click(timeout=WAIT_MS)
    await page.get_by_role("button", name=re.compile(r"^Attach")).last.click(timeout=10_000)
    await pane.get_by_role("button", name="1 picked").first.wait_for(timeout=10_000)
    await pane.get_by_role("button", name="Save media").click(timeout=10_000)
    saved = pane.get_by_text(re.compile(r"^Saved for "))
    await saved.wait_for(timeout=30_000)
    await _painted(page)
    await ui.shot(ctx, page, "funnel-media-saved")
    r = await ctx.owner.get(f"/admin/funnels/{funnel['id']}/media/{c['id']}")
    got = r.json() if r.status_code == 200 else {"status": r.status_code}
    (ctx.out / "funnel-media.json").write_text(json.dumps(got, indent=1))
    chk(FUNNEL_MEDIA_SAVED, r.status_code == 200 and got.get("opening_media_ids") == [PPV_PICK],
        funnel=funnel["id"], account=c["id"], saved=await saved.inner_text(), got=got)


ROW_NAMES = """() => [...document.querySelectorAll('tbody tr')].map((tr) => {
  const s = tr.querySelector('span[title^="slop link "]'); return s ? s.getAttribute('title') : null; })
  .filter(Boolean)"""


async def _pager(page) -> dict:
    nav = page.get_by_role("navigation", name="Pagination")
    cur = nav.locator("[aria-current=page]")
    return {"page": (await cur.inner_text()).strip() if await cur.count() else None,
            "total": (await nav.get_by_text(re.compile(r"^Total: ")).inner_text()).strip()}


async def _settle(page, want_first: str, timeout_ms: int = 5_000) -> tuple[dict, list[str]]:
    """The pager and row names once the first row is `want_first` and page 1 is current (or after the timeout)."""
    t_end = asyncio.get_event_loop().time() + timeout_ms / 1000
    while True:
        names, pg = await page.evaluate(ROW_NAMES), await _pager(page)
        if (names[:1] == [want_first] and pg["page"] == "1") or asyncio.get_event_loop().time() > t_end:
            return pg, names
        await asyncio.sleep(0.1)


async def _frame(ctx, page, chk, links: dict) -> None:
    reqs: list[dict] = []
    rec = {"on": False}

    def on_req(r) -> None:
        path = urlsplit(r.url).path
        if rec["on"] and not path.startswith(("/_next/", "/__nextjs")) and r.resource_type in ("fetch", "xhr", "document"):
            reqs.append({"method": r.method, "url": r.url, "body": r.post_data})

    page.on("request", on_req)
    async with page.expect_request(lambda r: urlsplit(r.url).path == "/admin/of-tracking-links",
                                   timeout=WAIT_MS) as first:
        await page.goto(f"{ctx.app}/growth/tracking-links", wait_until="domcontentloaded")
    aid = parse_qs(urlsplit((await first.value).url).query).get("account_id", [None])[0]
    await page.locator('tbody span[title^="slop link "]').first.wait_for(timeout=WAIT_MS)
    nav = page.get_by_role("navigation", name="Pagination")
    steps = []

    async def from_page3(label: str, want_before: list[str], act, want_after: list[str], total_after: int,
                         trigger: str | None, settled: str) -> None:
        await nav.get_by_role("button", name="Page 3", exact=True).click(timeout=10_000)
        t_end = asyncio.get_event_loop().time() + 5
        while True:
            before_pg, before = await _pager(page), await page.evaluate(ROW_NAMES)
            if (before_pg["page"] == "3" and before == want_before) or asyncio.get_event_loop().time() > t_end:
                break
            await asyncio.sleep(0.1)
        if trigger:
            await ui.shot(ctx, page, trigger)
        n0 = len(reqs)
        rec["on"] = True
        await act()
        after_pg, after = await _settle(page, want_after[0])
        await page.wait_for_timeout(500)  # any read the change fires has left by now
        rec["on"] = False
        await nav.scroll_into_view_if_needed(timeout=5_000)
        await ui.shot(ctx, page, settled)
        fired = reqs[n0:]
        steps.append({"step": label, "before": before_pg, "before_rows": [before[0], before[-1]] if before else [],
                      "before_ok": before_pg["page"] == "3" and before == want_before,
                      "after": after_pg, "after_rows": len(after), "after_first_last": [after[:1], after[-1:]],
                      "after_ok": after_pg == {"page": "1", "total": f"Total: {total_after} records"}
                      and after == want_after[:FRAME_PAGE],
                      "requests": fired, "page_param_in_requests": [x["url"] for x in fired
                                                                    if re.search(r"[?&](page|offset)=", x["url"])
                                                                    or (x["body"] and '"page"' in x["body"])]})

    async def pick_source() -> None:
        await page.get_by_role("combobox", name="Source").click(timeout=10_000)
        await page.get_by_role("option", name="IG", exact=True).click(timeout=10_000)

    async def all_sources() -> None:
        await page.get_by_role("combobox", name="Source").click(timeout=10_000)
        await page.get_by_role("option", name="All sources", exact=True).click(timeout=10_000)

    await from_page3("source IG", links["active"][100:120], pick_source, links["ig"], len(links["ig"]),
                     "frame-page3-trigger", "frame-source-page1")
    await all_sources()
    await _settle(page, links["active"][0])
    await from_page3("show deactivated", links["active"][100:120],
                     lambda: page.get_by_role("switch", name="Show deactivated links").click(timeout=10_000),
                     links["all"], len(links["all"]), "frame-page3-before-deactivated", "frame-deactivated-page1")
    page.remove_listener("request", on_req)
    (ctx.out / "frame-steps.json").write_text(json.dumps({"account": aid, "steps": steps}, indent=2))
    chk(FRAME_PAGE1, len(steps) == 2 and all(x["before_ok"] and x["after_ok"] and not x["page_param_in_requests"]
                                              for x in steps),
        account=aid, steps=[{k: v for k, v in x.items() if k != "requests"} | {"n_requests": len(x["requests"]),
                                                                              "request_urls": [r["url"] for r in x["requests"]]}
                            for x in steps])


async def _autofollow(ctx, page, chk) -> None:
    aid = ctx.world.data["creators"][0]["id"]
    is_records = lambda r: urlsplit(r.url).path == "/admin/auto-follow/records"  # noqa: E731

    def want(q: dict) -> dict:
        """Page 1 of the asked sort and range, straight from the temp DB (the request's own `start`, as the route
        reads it: naive UTC)."""
        col = {"followed_at": "s.last_pinged_at", "spend": "COALESCE(f.lifetime_spend_cents, 0)",
               "expiry": "f.subscription_expires_at"}[q["sort"]]
        lo = q.get("start")
        if lo:
            d = datetime.fromisoformat(lo.replace("Z", "+00:00"))
            lo = ts(d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d)
        where = "s.account_id=?" + (" AND s.last_pinged_at >= ?" if lo else "")
        args = (aid, lo) if lo else (aid,)
        base = (f"FROM follow_ping_state s LEFT JOIN fans f ON f.account_id=s.account_id AND f.fan_id=s.fan_id "
                f"WHERE {where}")
        con = ctx.world.sql()
        n = con.execute(f"SELECT COUNT(*) {base}", args).fetchone()[0]
        ids = [r[0] for r in con.execute(f"SELECT s.fan_id {base} ORDER BY {col} {q['order']}, s.fan_id DESC "
                                         f"LIMIT {AF_PAGE}", args).fetchall()]
        con.close()
        return {"total": n, "fan_ids": ids}

    async def act(fn) -> dict:
        """Do `fn`; the records read it sent (if any: a key the page already holds is served from React Query's
        cache, no request), then the pager and the fan ids the table shows (`@u<fan id>`)."""
        seen: list = []

        def on_resp(r) -> None:
            if is_records(r):
                seen.append(r)

        page.on("response", on_resp)
        await fn()
        t_end = asyncio.get_event_loop().time() + 5
        while not seen and asyncio.get_event_loop().time() < t_end:
            await asyncio.sleep(0.1)
        await page.wait_for_timeout(500)
        page.remove_listener("response", on_resp)
        out = {"url": None, "query": {}, "status": None, "total": None, "fan_ids": None}
        if seen:
            r = seen[-1]
            body = await r.json()
            out = {"url": r.url, "query": {k: v[0] for k, v in parse_qs(urlsplit(r.url).query).items()},
                   "status": r.status, "total": body.get("total"), "fan_ids": [x["fan_id"] for x in body.get("rows", [])]}
        cur = page.get_by_role("navigation", name="Pagination").locator("[aria-current=page]")
        out["requests"] = len(seen)
        out["pager"] = (await cur.inner_text()).strip() if await cur.count() else None
        out["dom_fan_ids"] = [int(m) for m in re.findall(r"@u(\d+)", await page.locator("tbody").inner_text())]
        return out

    async def page3() -> dict:
        return await act(lambda: page.get_by_role("navigation", name="Pagination")
                         .get_by_role("button", name="Page 3", exact=True).click(timeout=10_000))

    async with page.expect_response(is_records, timeout=WAIT_MS):
        await page.goto(f"{ctx.app}/growth/auto-follow", wait_until="domcontentloaded")
        await page.get_by_test_id(f"af-row-{aid}").click(timeout=WAIT_MS)
    await page.get_by_role("navigation", name="Pagination").wait_for(timeout=WAIT_MS)
    start_day = (ctx.world.now - timedelta(days=30)).strftime("%Y-%m-%d")
    steps = []
    p3 = await page3()
    await ui.shot(ctx, page, "autofollow-page3-trigger")
    sort = await act(lambda: page.get_by_role("button", name=re.compile(r"^Total spend")).click(timeout=10_000))
    await ui.shot(ctx, page, "autofollow-sort-page1")
    steps.append({"step": "sort Total spend", "page3": p3, "after": sort,
                  "want": {"sort": "spend", "order": "desc", "offset": "0"}, "db": want(sort["query"] or {"sort": "spend", "order": "desc"})})

    async def range_pick() -> None:
        start = page.get_by_label("Start date", exact=True)
        await start.focus()
        await start.fill(start_day)

    p3 = await page3()
    rng = await act(range_pick)
    await ui.shot(ctx, page, "autofollow-range-page1")
    steps.append({"step": "range start", "page3": p3, "after": rng,
                  "want": {"sort": "spend", "order": "desc", "offset": "0"}, "db": want(rng["query"] or {"sort": "spend", "order": "desc"})})
    p3 = await page3()
    rst = await act(lambda: page.get_by_role("button", name="Reset", exact=True).click(timeout=10_000))
    await ui.shot(ctx, page, "autofollow-reset-page1")
    steps.append({"step": "reset", "page3": p3, "after": rst,
                  "want": None, "db": want({"sort": "spend", "order": "desc"})})
    for x in steps:
        a, q, p3 = x["after"], x["after"]["query"], x["page3"]
        on_page3 = p3["query"].get("offset") == str(2 * AF_PAGE) and p3["pager"] == "3"
        shows_page1 = a["pager"] == "1" and a["dom_fan_ids"] == x["db"]["fan_ids"]
        if x["want"] is None:  # Reset back to a key the page already read: served from cache, no request needed
            asked = a["requests"] == 0 or (q.get("offset") == "0" and "start" not in q)
        else:
            asked = (all(q.get(k) == v for k, v in x["want"].items()) and q.get("limit") == str(AF_PAGE)
                     and a["status"] == 200 and a["total"] == x["db"]["total"] and a["fan_ids"] == x["db"]["fan_ids"])
        x["ok"] = on_page3 and asked and shows_page1
    steps[1]["ok"] = steps[1]["ok"] and steps[1]["after"]["query"].get("start") is not None
    (ctx.out / "autofollow-steps.json").write_text(json.dumps({"account": aid, "steps": steps}, indent=2))
    chk(AF_OFFSET0, all(x["ok"] for x in steps) and len(steps) == 3, account=aid,
        steps=[{"step": x["step"], "ok": x["ok"], "page3_url": x["page3"]["url"], "after_url": x["after"]["url"],
                "after_total": x["after"]["total"], "after_pager": x["after"]["pager"],
                "after_requests": x["after"]["requests"], "db_total": x["db"]["total"],
                "dom_ids_match_db": x["after"]["dom_fan_ids"] == x["db"]["fan_ids"]} for x in steps])


async def _vault_open(ctx, page) -> None:
    """Vault Pro on Creator 0 (the seeded mirror), the grid's tiles drawn."""
    await page.goto(f"{ctx.app}/growth/vault-pro", wait_until="domcontentloaded")
    await ui.pick_creator(page, ctx.world.data["creators"][0]["nickname"], timeout_ms=WAIT_MS)
    await page.get_by_title(f"#{VAULT_IDS[0]} · photo", exact=True).wait_for(timeout=WAIT_MS)


async def _vaultmanage(ctx, page, chk) -> None:
    aid = ctx.world.data["creators"][0]["id"]
    patches: list[dict] = []

    async def patch(route):
        if route.request.method == "PATCH":
            patches.append(route.request.post_data_json or {})
        await route.fallback()

    is_item = lambda u: urlsplit(u).path.startswith("/admin/vault-ai/items/")  # noqa: E731
    await page.route(is_item, patch)
    try:
        await _vault_open(ctx, page)
        tile = lambda mid: page.get_by_title(f"#{mid} · photo", exact=True)  # noqa: E731
        bar = page.get_by_text("Selected", exact=True)
        # 1. Two files ticked on All, then the Video tab.
        await page.get_by_role("button", name="Select", exact=True).click(timeout=10_000)
        await tile(VAULT_IDS[0]).click(timeout=10_000)
        await tile(VAULT_IDS[1]).click(timeout=10_000)
        await bar.wait_for(timeout=10_000)
        ticked = (await bar.locator("xpath=..").inner_text()).split()
        await ui.shot(ctx, page, "vault-ticked-trigger")
        await page.get_by_role("button", name="Video", exact=True).click(timeout=10_000)
        await page.wait_for_timeout(800)
        bars_video = await bar.count()
        await ui.shot(ctx, page, "vault-type-switched")
        await page.get_by_role("button", name="All", exact=True).click(timeout=10_000)
        await tile(VAULT_IDS[0]).wait_for(timeout=30_000)
        await page.wait_for_timeout(500)
        bars_all = await bar.count()
        chk(VM_TICKS, ticked == ["Selected", "2"] and bars_video == 0 and bars_all == 0, bar_before=ticked,
            bars_on_video=bars_video, bars_back_on_all=bars_all)

        # 2. "abc" as the price, then a description edit and Save & lock.
        await page.get_by_role("button", name="Selecting", exact=True).click(timeout=10_000)
        mid = VAULT_IDS[-1]
        await tile(mid).click(timeout=10_000)
        save = page.get_by_role("button", name="Save & lock", exact=True)
        await save.wait_for(timeout=30_000)
        await page.get_by_title(re.compile(r"^Your price for this media")).fill("abc", timeout=10_000)
        await page.wait_for_timeout(300)
        letters_only = await _button_state(save)
        await ui.shot(ctx, page, "vault-price-letters")
        await page.get_by_placeholder("Full description…").fill(VM_DESC, timeout=10_000)
        await page.wait_for_timeout(300)
        with_desc = await _button_state(save)
        async with page.expect_response(lambda r: r.request.method == "PATCH" and is_item(r.url), timeout=30_000) as resp:
            await save.click(timeout=10_000)
        status = (await resp.value).status
        await page.get_by_text(re.compile(r"^Saved — locked")).wait_for(timeout=10_000)
        await ui.shot(ctx, page, "vault-price-saved")
        con = ctx.world.sql()
        row = con.execute("SELECT description, suggested_price_cents, locked_fields_json FROM vault_items "
                          "WHERE account_id=? AND media_id=?", (aid, mid)).fetchone()
        con.close()
        got = {"description": row[0], "price_cents": row[1], "locked": json.loads(row[2] or "[]")} if row else None
        chk(VM_PRICE, letters_only["disabled"] is True and with_desc["disabled"] is False and status == 200
            and [p.get("fields") for p in patches] == [{"description": VM_DESC}]
            and got == {"description": VM_DESC, "price_cents": None, "locked": ["description"]},
            save_with_letters=letters_only, save_with_desc=with_desc, http=status, patches=patches, row=got)
        await page.keyboard.press("Escape")
    finally:
        await page.unroute(is_item)


async def _redescribe(ctx, page, chk) -> None:
    """Item 9021's drawer: a Re-describe on the untouched editor, then (drawer reopened, fresh editor) a description
    typed first and a Re-describe whose answer changes only the description."""
    aid = ctx.world.data["creators"][0]["id"]
    mid = VAULT_IDS[-1]
    asked: list[dict] = []
    patches: list[dict] = []

    async def describe(route):
        asked.append(route.request.post_data_json or {})
        answer = REDESCRIBE_ANSWERS[min(len(asked), len(REDESCRIBE_ANSWERS)) - 1]
        await route.fulfill(status=200, content_type="application/json", body=json.dumps(answer))

    async def patch(route):
        if route.request.method == "PATCH":
            patches.append(route.request.post_data_json or {})
        await route.fallback()

    is_describe = lambda u: urlsplit(u).path == "/admin/vault-ai/describe"  # noqa: E731
    is_item = lambda u: urlsplit(u).path.startswith("/admin/vault-ai/items/")  # noqa: E731
    await page.route(is_describe, describe)
    await page.route(is_item, patch)
    try:
        await _vault_open(ctx, page)
        tile = page.get_by_title(f"#{mid} · photo", exact=True)
        save = page.get_by_role("button", name="Save & lock", exact=True)
        desc = page.get_by_placeholder("Full description…")
        tags = page.get_by_placeholder("comma, separated, tags")
        redo = page.get_by_role("button", name=re.compile(r"^(Re-describe|Describe)$"))
        # 1. Untouched editor, Re-describe.
        await tile.click(timeout=10_000)
        await save.wait_for(timeout=30_000)
        before = {"desc": await desc.input_value(), "tags": await tags.input_value()}
        await ui.shot(ctx, page, "redescribe-untouched-trigger")
        await redo.click(timeout=10_000)
        await page.get_by_role("button", name="Re-describe", exact=True).wait_for(timeout=10_000)
        await page.wait_for_timeout(500)
        shown = {"desc": await desc.input_value(), "tags": await tags.input_value()}
        first = await _button_state(save)
        await ui.shot(ctx, page, "redescribe-untouched-settled")
        chk(REDESCRIBE_SHOWS, len(asked) == 1 and shown == {"desc": "slop redescribed", "tags": "slop, redescribed"}
            and first["disabled"] is True, before=before, after=shown, save=first, describes=list(asked))
        # 2. Reopened (a fresh editor from the grid's read), a description typed, Re-describe.
        await page.get_by_role("button", name="Close details", exact=True).click(timeout=10_000)
        await tile.click(timeout=10_000)
        await save.wait_for(timeout=30_000)
        await desc.fill(REDESCRIBE_EDIT, timeout=10_000)
        tags_typed = await tags.input_value()
        await ui.shot(ctx, page, "redescribe-edited-trigger")
        await redo.click(timeout=10_000)
        t_end = asyncio.get_event_loop().time() + 10
        while len(asked) < 2 and asyncio.get_event_loop().time() < t_end:
            await asyncio.sleep(0.1)
        await page.wait_for_timeout(800)
        kept = {"desc": await desc.input_value(), "tags": await tags.input_value()}
        second = await _button_state(save)
        status = None
        if not second["disabled"]:
            async with page.expect_response(lambda r: r.request.method == "PATCH" and is_item(r.url),
                                            timeout=30_000) as resp:
                await save.click(timeout=10_000)
            status = (await resp.value).status
            await page.get_by_text(re.compile(r"^Saved — locked")).wait_for(timeout=10_000)
        await ui.shot(ctx, page, "redescribe-edited-saved")
        con = ctx.world.sql()
        row = con.execute("SELECT description, locked_fields_json FROM vault_items WHERE account_id=? AND media_id=?",
                          (aid, mid)).fetchone()
        con.close()
        got = {"description": row[0], "locked": "description" in json.loads(row[1] or "[]")} if row else None
        chk(REDESCRIBE_KEEPS, len(asked) == 2 and kept == {"desc": REDESCRIBE_EDIT, "tags": tags_typed}
            and status == 200 and [p.get("fields") for p in patches] == [{"description": REDESCRIBE_EDIT}]
            and got == {"description": REDESCRIBE_EDIT, "locked": True},
            after=kept, save=second, http=status, patches=patches, row=got, describes=len(asked))
        await page.get_by_role("button", name="Close details", exact=True).click(timeout=10_000)
    finally:
        await page.unroute(is_describe)
        await page.unroute(is_item)


async def _shimmer(ctx, page, chk) -> None:
    """The mass composer's vault picker, posting as Creator 1, hovering its video. The storyboard's frames
    (GET /img/scrub, the relay's ffmpeg build of OF's mp4) are answered 502 at the wire: the stack has no OF CDN to
    build from. Frame 0 is held until the shimmer is on screen."""
    c1 = ctx.world.data["creators"][1]
    frames: list[str] = []
    hold = asyncio.Event()

    async def scrub(route):
        frames.append(route.request.url)
        await hold.wait()
        await route.fulfill(status=502, body="slop: storyboard build answered 502 at the wire")

    is_scrub = lambda u: urlsplit(u).path == "/img/scrub"  # noqa: E731
    await page.route(is_scrub, scrub)
    try:
        await _open_create_message(ctx, page, re.compile(r"^OF mass message"))
        await page.get_by_placeholder("What's the broadcast?").wait_for(timeout=WAIT_MS)
        await page.locator("select:has(option[value])").first.select_option(label=c1["nickname"])
        await page.get_by_role("button", name="Add from vault").first.click(timeout=10_000)
        tile = page.locator(f"[data-tile-id='{PICKER_VIDEO}']")
        await tile.hover(timeout=WAIT_MS)
        shimmer = tile.locator(".scrub-shimmer")
        await shimmer.wait_for(timeout=10_000)
        for _ in range(100):
            if frames:
                break
            await asyncio.sleep(0.1)
        building = await shimmer.count()
        await ui.shot(ctx, page, "picker-shimmer-trigger")
        hold.set()
        await page.wait_for_timeout(1_500)
        left = await shimmer.count()
        countdown = await tile.get_by_text(re.compile(r"^(\d+s|…)$")).count()
        await ui.shot(ctx, page, "picker-frame-failed")
        chk(PICKER_SHIMMER, bool(frames) and building == 1 and left == 0 and countdown == 0,
            frames_asked=len(frames), shimmer_while_building=building, shimmer_after_fail=left, countdowns=countdown)
    finally:
        hold.set()
        await page.unroute(is_scrub)


def _p95(xs: list[float]) -> float | None:
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(len(xs) * 0.95))], 1) if xs else None


async def _mass_volume(ctx) -> None:
    """The Mass composer's all-models fan-out at volume (lib/fanout_ts.mjs: the app's reducer and fan-out
    runner in node, the relay's real queue route, OF's wire): --users operators at once over every Creator,
    one Creator's OF queue answering 500 in round 1, then each operator's retry."""
    creators = [c["id"] for c in ctx.world.data["creators"]]
    failing, users = creators[1], max(1, ctx.users)
    cookie = "; ".join(f"{k}={v}" for k, v in ctx.owner.c.cookies.items())
    plan = {"base": ctx.relay, "cookie": cookie, "accounts": creators, "users": users, "text": VOLUME_TEXT,
            "edit": VOLUME_TEXT + EDIT}

    def wire() -> dict[str, list[str]]:
        return {a: [x.get("text") for x in v if (x.get("text") or "").startswith(VOLUME_TEXT)]
                for a, v in _wire(ctx, "queue").items()}

    def of_500s() -> int:
        with ctx.of_wire.lock:
            return sum(1 for c in ctx.of_wire.calls if c["route"] == OF_QUEUE and c["status"] == 500)

    def mass_runs() -> dict[str, int]:
        con = ctx.world.sql()
        try:
            return dict(con.execute("SELECT account_id, COUNT(*) FROM mass_runs GROUP BY account_id").fetchall())
        finally:
            con.close()

    f0, runs0 = of_500s(), mass_runs()
    with ctx.of_wire.lock:
        ctx.of_wire.fail.add((failing, OF_QUEUE))
    try:
        r1 = await app_ts.run(ctx, VOLUME_TS, {**plan, "rounds": None})
    finally:
        with ctx.of_wire.lock:
            ctx.of_wire.fail.discard((failing, OF_QUEUE))
    wire1, fails1 = wire(), of_500s() - f0
    r2 = await app_ts.run(ctx, VOLUME_TS, {**plan, "rounds": [{"text": u["text"], "results": u["results"]}
                                                                for u in r1["users"]]})
    wire2, runs2 = wire(), mass_runs()
    u1, u2 = r1["users"], r2["users"]
    st1 = sorted((s["account"] == failing, s["status"]) for u in u1 for s in u["sends"])
    st2 = [(s["account"], s["status"]) for u in u2 for s in u["sends"]]
    others = [a for a in creators if a != failing]
    # Mid-round the edit and Start over were refused: round 1 had no results yet, the retry kept round 1's.
    mid_ok = (all(u["mid"] == {"text": VOLUME_TEXT, "results": None} for u in u1)
              and all(b["mid"] == {"text": VOLUME_TEXT, "results": a["results"]} for a, b in zip(u1, u2)))
    ok = (len(u1) == len(u2) == users and mid_ok
          and all(u["targets"] == creators for u in u1)
          and st1 == sorted([(False, 200)] * (users * len(others)) + [(True, 502)] * users)
          and fails1 == users
          and {a: len(v) for a, v in wire1.items() if v} == {a: users for a in others}
          and all(u["locked"] and u["text"] == VOLUME_TEXT for u in u1)
          and all(u["targets"] == [failing] for u in u2) and st2 == [(failing, 200)] * users
          and {a: sorted(set(v)) for a, v in wire2.items() if v} == {a: [VOLUME_TEXT] for a in creators}
          and {a: len(v) for a, v in wire2.items() if v} == {a: users for a in creators}
          and r1["body"] and r1["body"].get("user_lists") == ["fans", "following"] and r1["body"].get("price") == 0)
    e2e1 = [u["t1"] - u["t0"] for u in u1]
    e2e2 = [u["t1"] - u["t0"] for u in u2]
    send_ms = [s["t1"] - s["t0"] for u in u1 + u2 for s in u["sends"]]
    detail = {"users": users, "creators": len(creators), "failing": failing, "of_500s_round1": fails1,
              "round1_statuses": dict(sorted({f"{'failed' if f else 'other'} {st}": st1.count((f, st))
                                              for f, st in set(st1)}.items())),
              "round1_of_wire": {a: len(v) for a, v in wire1.items()},
              "round1_locked": sum(1 for u in u1 if u["locked"]),
              "mid_round_refused": mid_ok,
              "mid_round_texts": sorted({u["mid"]["text"] for u in u1 + u2 if u["mid"]}),
              "retry_mid_results_kept": sum(1 for a, b in zip(u1, u2) if b["mid"] and b["mid"]["results"] == a["results"]),
              "round1_text_after_edit": sorted({u["text"] for u in u1}),
              "retry_targets": sorted({tuple(u["targets"]) for u in u2}),
              "retry_statuses": sorted(set(st2)), "of_wire_end": {a: len(v) for a, v in wire2.items()},
              "of_wire_texts": sorted({t for v in wire2.values() for t in v}), "body": r1["body"]}
    ctx.check(MASS_VOLUME, ok, **detail)
    ctx.metric("mass_volume", {"round1_ms_p50": sorted(e2e1)[len(e2e1) // 2], "round1_ms_p95": _p95(e2e1),
                               "round1_ms_max": max(e2e1), "retry_ms_p95": _p95(e2e2),
                               "send_ms_p95": _p95(send_ms), "sends": len(send_ms), **detail})
    (ctx.out / "mass-volume.json").write_text(json.dumps({"round1": u1, "retry": u2}, indent=1))
    # Every queue POST mints its mass_runs row before OF is asked (mass_queue_api._open_mass_run), the failed ones too.
    minted = {a: runs2.get(a, 0) - runs0.get(a, 0) for a in creators}
    want_runs = {a: sum(1 for u in u1 + u2 for x in u["sends"] if x["account"] == a) for a in creators}
    ctx.check(MASS_VOLUME_RUNS, minted == want_runs, minted=minted, sends=want_runs,
              missing=sum(want_runs.values()) - sum(minted.values()))
    p95 = _p95(e2e1)
    ctx.check(MASS_VOLUME_P95, p95 is not None and p95 <= MASS_FANOUT_P95_MS, budget=True,
              p95_ms=p95, max_ms=max(e2e1), retry_p95_ms=_p95(e2e2), send_p95_ms=_p95(send_ms),
              operators=users, creators=len(creators))


# ── OF rich text (lib/rich_text_faults.py) ──
RT_TITLE_DESKTOP = "slop rich desktop"
RT_TITLE_PHONE = "slop rich phone"
RT_LINES = ("Hey babe", "Large line")  # "Hey": Bold + Light blue; line 2: Large
# What the editor saves for RT_LINES so formatted (lib/ofMirrorFormat runsHtml: OF's wire nesting, span > strong).
RT_MARKUP = ('<p><span class="m-editor-fc__blue-1"><strong>Hey</strong></span> babe</p>'
             '<p><span class="m-editor-fs__l">Large line</span></p>')
RT_PLAIN_SEND = "slop rt plain <3 & co"
RT_PLAIN_WIRE = "<p>slop rt plain &lt;3 &amp; co</p>"  # of_client._wrap_text_as_p, as before this change
RT_FAN = '<p><span class="m-editor-fc__blue-2"><strong>slop rt fan</strong></span> says <em>hi</em></p>'
RT_FAN_ID = fan_dm.INJECT_ID_BASE + 777_001
PHONE = (390, 844)
SELECT_WORD = """(el, word) => {
  const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  for (let n = w.nextNode(); n; n = w.nextNode()) {
    const i = n.data.indexOf(word);
    if (i < 0) continue;
    const r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + word.length);
    const s = getSelection(); s.removeAllRanges(); s.addRange(r);
    document.dispatchEvent(new Event("selectionchange"));
    return true;
  }
  return false;
}"""
# The phone toolbar: no sideways scroll (page or toolbar), every tool >= 44 px tall and wide.
PHONE_FIT = """(tb) => ({
  page: [document.documentElement.scrollWidth, window.innerWidth],
  toolbar: [tb.scrollWidth, tb.clientWidth],
  small: [...tb.querySelectorAll(':scope > button')].map((b) => b.getBoundingClientRect())
    .filter((r) => r.height < 44 || r.width < 44).length,
})"""


def _saved_text(ctx, aid: str, title: str) -> str | None:
    con = ctx.world.sql()
    try:
        row = con.execute("SELECT text FROM saved_replies WHERE account_id=? AND title=? ORDER BY id DESC LIMIT 1",
                          (aid, title)).fetchone()
        return row[0] if row else None
    finally:
        con.close()


async def _rt_row_html(page, title: str) -> str | None:
    """The Scripts list row's rendered text (OfRichText's root) once it is formatted, else None."""
    rich = page.get_by_role("list", name="Scripts list").locator("li").filter(has_text=title).locator("[data-of-rich]")
    try:
        await rich.first.wait_for(timeout=30_000)
    except PwTimeout:
        return None
    return await rich.first.inner_html()


async def _rt_make_script(ctx, page, title: str, shot: str, tap: bool) -> dict:
    """Growth > Scripts > More > Add script: RT_LINES typed, "Hey" Bold + Light blue, line 2 Large, all through
    the editor's toolbar (taps on the phone), OK. The word selection is set by script: a drag/long-press select is
    the one gesture Playwright cannot make on a contenteditable (bypass, declared)."""
    press = (lambda loc: loc.tap(timeout=10_000)) if tap else (lambda loc: loc.click(timeout=10_000))
    await page.goto(f"{ctx.app}/growth/scripts", wait_until="domcontentloaded")
    await page.get_by_role("list", name="Scripts list").wait_for(timeout=WAIT_MS)
    more = page.get_by_role("button", name="More", exact=True).and_(page.locator("[aria-haspopup=menu]"))
    await press(more.last)
    await press(page.get_by_role("menuitem", name="Add script"))
    dlg = page.get_by_role("dialog", name="Add script")
    await dlg.locator("#script-name").fill(title)
    ed = dlg.get_by_role("textbox", name=re.compile("^Text"))
    tb = dlg.get_by_role("toolbar", name="Text formatting")
    await press(ed)
    await page.keyboard.type(RT_LINES[0])
    await page.keyboard.press("Enter")
    await page.keyboard.type(RT_LINES[1])
    fit = await tb.evaluate(PHONE_FIT) if tap else None
    assert await ed.evaluate(SELECT_WORD, "Hey"), "no 'Hey' to select"
    await press(tb.get_by_role("button", name="Bold", exact=True))
    await press(tb.get_by_role("button", name="Text color", exact=True))
    await press(tb.get_by_role("menuitemradio", name="Light blue", exact=True))
    assert await ed.evaluate(SELECT_WORD, RT_LINES[1]), "no line 2 to select"
    await press(tb.get_by_role("button", name=re.compile("^Text size")))
    await press(tb.get_by_role("menuitemradio", name="Large", exact=True))
    assert await ed.evaluate(SELECT_WORD, "Hey"), "no 'Hey' to reselect"
    await _painted(page)
    pressed = {"bold": await tb.get_by_role("button", name="Bold", exact=True).get_attribute("aria-pressed"),
               "size": (await tb.get_by_role("button", name=re.compile("^Text size")).inner_text()).strip()}
    await ui.shot(ctx, page, f"{shot}-trigger")
    editor_html = await ed.inner_html()
    await press(dlg.get_by_role("button", name="OK", exact=True))
    await dlg.wait_for(state="hidden", timeout=15_000)
    row = await _rt_row_html(page, title)
    await page.locator("[role=dialog]").wait_for(state="detached", timeout=10_000)  # the modal's fade-out done
    await _painted(page)
    await ui.shot(ctx, page, f"{shot}-settled")
    return {"fit": fit, "pressed": pressed, "editor_html": editor_html, "row_html": row}


def _rt_row_ok(row: str | None) -> bool:
    return bool(row) and '<span class="m-editor-fc__blue-1"><strong>Hey</strong></span>' in row \
        and '<span class="m-editor-fs__l">Large line</span>' in row


async def _rich_text(ctx, page, chk) -> None:
    """Section rich-text: a formatted script on desktop and on a phone, sent from Messages Pro; a fan's formatted
    message received."""
    accts = [a for a in (await ctx.owner.get("/admin/accounts")).json().get("accounts", [])
             if a.get("has_session") and a.get("is_active", True)]
    aid = accts[0]["id"]  # the Creator the Scripts page and the picker open on (useScopedAccount)
    c = next(x for x in ctx.world.data["creators"] if x["id"] == aid)
    out: dict = {"account": aid}
    errs: list = []
    page.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
    page.on("console", lambda m: errs.append(f"console.{m.type}: {m.text}"[:2000]) if m.type == "error" else None)
    (ctx.out / "rich-text-console.json").write_text("[]")
    try:
        await _rich_text_body(ctx, page, chk, aid, c, out)
    finally:
        (ctx.out / "rich-text-console.json").write_text(json.dumps(errs, indent=2))


async def _rich_text_body(ctx, page, chk, aid, c, out) -> None:

    d = await _rt_make_script(ctx, page, RT_TITLE_DESKTOP, "rich-script-desktop", tap=False)
    saved = _saved_text(ctx, aid, RT_TITLE_DESKTOP)
    out["desktop"] = {**d, "saved": saved}
    chk(RT_SCRIPT_DESKTOP, saved == RT_MARKUP and _rt_row_ok(d["row_html"]) and d["pressed"]["bold"] == "true",
        saved=saved, want=RT_MARKUP, row=d["row_html"], pressed=d["pressed"])

    phone = await ui._owner_page(page.context.browser, ctx, PHONE, [], [], touch=True)
    try:
        await phone.context.add_init_script(TOURS_SEEN)
        phone.context.set_default_navigation_timeout(WAIT_MS)
        p = await _rt_make_script(ctx, phone, RT_TITLE_PHONE, "rich-script-phone", tap=True)
    finally:
        await phone.context.close()
    saved_p = _saved_text(ctx, aid, RT_TITLE_PHONE)
    out["phone"] = {**p, "saved": saved_p}
    fit = p["fit"] or {}
    chk(RT_SCRIPT_PHONE, saved_p == RT_MARKUP and _rt_row_ok(p["row_html"])
        and fit.get("page", [1, 0])[0] <= fit.get("page", [0, 0])[1]
        and fit.get("toolbar", [1, 0])[0] <= fit.get("toolbar", [0, 0])[1] and fit.get("small") == 0,
        saved=saved_p, want=RT_MARKUP, row=p["row_html"], fit=fit)

    # ── Messages Pro: pick the desktop script, send; a typed plain message; a fan's formatted DM ──
    view = await _chat_view(ctx, [c])
    fan = view[aid][0]["withUser"]
    send_path = f"/api/of/v2/chats/{fan['id']}/messages"
    browser_sends: list = []

    async def chats(route):
        req = route.request
        if req.method != "GET":
            return await route.fallback()
        _aid, off, lim, _plain, rows = _chats_query(req, view)
        await _serve_chats(route, rows, off, lim)

    async def send(route):
        req = route.request
        if req.method != "POST":
            return await route.fallback()
        browser_sends.append(req.post_data_json)
        await route.continue_()  # to the relay, whose OFClient sends to lib/of_wire.py

    routes = ((lambda u: urlsplit(u).path == "/api/of/v2/chats", chats),
              (lambda u: urlsplit(u).path == send_path, send))
    for pat, fn in routes:
        await page.route(pat, fn)
    with ctx.of_wire.lock:
        n_wire = len(ctx.of_wire.sends.get(aid, []))
    n_status = len(page.slop["statuses"])

    def wire() -> list[str]:
        with ctx.of_wire.lock:
            return [m.get("text") for m in ctx.of_wire.sends.get(aid, [])[n_wire:]
                    if str(m["fan_id"]) == str(fan["id"])]

    try:
        await page.goto(f"{ctx.app}/messages-pro", wait_until="domcontentloaded")
        await _creator_tab(page, c)
        await page.locator("[data-chat-row]").filter(has_text=f"@{fan['username']}").first.click(timeout=WAIT_MS)
        box = page.get_by_placeholder(INPUT, exact=True)
        ta, ed = box.and_(page.locator("textarea")), box.and_(page.locator("[contenteditable]"))
        fmt_bar = page.get_by_role("toolbar", name="Text formatting")
        aa = page.get_by_role("button", name="Aa", exact=True)
        await ta.wait_for(timeout=WAIT_MS)
        errs: dict = {}

        async def step(name, fn):
            """One step; a failure is its own check's (recorded, the box emptied) so the next steps still run."""
            try:
                await fn()
            except Exception as e:  # noqa: BLE001
                errs[name] = f"{type(e).__name__}: {e}"[:600]
                await page.keyboard.press("Escape")
                for loc in (ta, ed):
                    if await loc.count():
                        await loc.fill("")
                await page.wait_for_timeout(3_500)

        async def pick():
            # 1. The desktop script picked: the box is the rich editor, formatted, no second preview, "Aa" still off.
            await _pick_template(page, RT_TITLE_DESKTOP)
            await ed.locator("span.m-editor-fc__blue-1 strong").first.wait_for(timeout=15_000)
            out["pick"] = {"editor_html": await ed.inner_html(),
                           "dup_preview": await page.locator("[data-rich-preview]").count(),
                           "toolbar": await fmt_bar.count(), "aa_pressed": await aa.get_attribute("aria-pressed")}
            await _painted(page)
            await ui.shot(ctx, page, "rich-send-trigger")
            n = len(wire())
            await ed.press("Enter")
            await _until(lambda: len(wire()) > n, 30)
            out["pick"]["wire"] = wire()[n:]
            out["pick"]["browser_text"] = browser_sends[-1].get("text") if browser_sends else None
            await ta.wait_for(timeout=15_000)  # sent with "Aa" off: back to the plain textarea, empty
            out["pick"]["after_send_box"] = await ta.input_value()
            await page.wait_for_timeout(3_500)  # Infloww's send-rate guard: 3 s between a model's sends (claimSendGap)

        async def aa_send():
            # 2. "Aa": type two lines (Shift+Enter), "Hey" Bold + Light blue, line 2 Large, Enter.
            out["aa"] = await _rt_aa_compose(page, ed, fmt_bar, aa, tap=False)
            await _painted(page)
            await ui.shot(ctx, page, "rich-aa-trigger")
            n = len(wire())
            await ed.press("Enter")
            await _until(lambda: len(wire()) > n, 30)
            out["aa"]["wire"] = wire()[n:]
            out["aa"]["browser_text"] = browser_sends[-1].get("text") if browser_sends else None
            await page.wait_for_function("(el) => el.textContent === ''", arg=await ed.element_handle(), timeout=15_000)
            out["aa"] |= {"after_send_toolbar": await fmt_bar.count(), "after_send_editor": await ed.count()}
            await _painted(page)
            await ui.shot(ctx, page, "rich-aa-settled")
            await page.wait_for_timeout(3_500)
            # 3. "Aa" off: the plain textarea back.
            await aa.click()
            await ta.wait_for(timeout=10_000)

        async def plain():
            # 4. A typed plain message (the box is the textarea: "Aa" off, or never on).
            await ta.fill(RT_PLAIN_SEND)
            n = len(wire())
            await ta.press("Enter")
            await _until(lambda: len(wire()) > n, 30)
            out["plain"] = {"wire": wire()[n:], "browser_text": browser_sends[-1].get("text") if browser_sends else None}

        await step("pick", pick)
        await step("aa", aa_send)
        await step("plain", plain)
        r = await fan_dm.inject(ctx.owner, aid, {"api2_chat_message": {
            **fan_dm.frame(RT_FAN_ID, fan, "x")["api2_chat_message"], "text": RT_FAN}})
        out["frame_status"] = r.status_code
        bubble = page.locator("[data-of-rich]").filter(has_text="slop rt fan")
        try:
            await bubble.first.wait_for(timeout=30_000)
            out["bubble_html"] = await bubble.first.inner_html()
            out["bubble_style"] = await bubble.first.locator("span.m-editor-fc__blue-2").evaluate(
                "(s) => { const c = getComputedStyle(s), b = getComputedStyle(s.querySelector('strong') || s.closest('strong'));"
                " return { color: c.color, weight: b.fontWeight }; }")
        except PwTimeout:
            out["bubble_html"] = None
        sent_bubble = page.locator("[data-of-rich]").filter(has_text="Large line")
        out["sent_bubbles"] = await sent_bubble.count()
        out["sent_bubble_html"] = await sent_bubble.last.inner_html() if out["sent_bubbles"] else None
        await asyncio.sleep(1.0)  # a stray extra send would land here
        await _painted(page)
        await ui.shot(ctx, page, "rich-send-settled")
        got = wire()
        fives = [u for st, u in page.slop["statuses"][n_status:] if st >= 500]
        out |= {"fan": fan["id"], "browser_sends": browser_sends, "of_wire_texts": got, "relay_5xx": fives[:5],
                "step_errors": errs}
        pk, a_, pl = out.get("pick") or {}, out.get("aa") or {}, out.get("plain") or {}
        chk(RT_SEND, "pick" not in errs and "plain" not in errs and len(got) == 3
            and pk.get("wire") == [RT_MARKUP] and pk.get("browser_text") == RT_MARKUP
            and pl.get("wire") == [RT_PLAIN_WIRE] and pl.get("browser_text") == RT_PLAIN_SEND
            and _rt_row_ok(pk.get("editor_html")) and pk.get("dup_preview") == 0 and pk.get("toolbar") == 0
            and pk.get("after_send_box") == "" and out["sent_bubbles"] >= 1 and _rt_row_ok(out["sent_bubble_html"])
            and not fives,
            of_wire=got, want=[RT_MARKUP, "(Aa send)", RT_PLAIN_WIRE], pick=pk, plain=pl,
            errors={k: v for k, v in errs.items() if k in ("pick", "plain")},
            sent_bubble=out["sent_bubble_html"], relay_5xx=fives[:5])
        chk(RT_AA, "aa" not in errs and a_.get("wire") == [RT_MARKUP] and a_.get("browser_text") == RT_MARKUP
            and a_.get("toolbar") == 1 and a_.get("pressed") == "true" and a_.get("after_send_toolbar") == 1
            and a_.get("after_send_editor") == 1,
            want=RT_MARKUP, aa=a_, error=errs.get("aa"))
        style = out.get("bubble_style") or {}
        chk(RT_BUBBLE, out["frame_status"] == 200 and bool(out["bubble_html"])
            and '<span class="m-editor-fc__blue-2"><strong>slop rt fan</strong></span> says <em>hi</em>'
            in out["bubble_html"] and style.get("color") == "rgb(27, 152, 224)" and int(style.get("weight", 0)) >= 600,
            bubble=out["bubble_html"], style=style, frame_status=out["frame_status"])
    finally:
        (ctx.out / "rich-text.json").write_text(json.dumps(out, indent=2, default=str))
        for pat, fn in routes:
            await page.unroute(pat, fn)

    browser = page.context.browser
    await _rt_chat_phone(ctx, browser, c, view, fan, chk, out)
    await _rt_mass(ctx, page, browser, aid, chk, out)
    await _rt_fansly(ctx, browser, c, view, fan, chk, out)
    (ctx.out / "rich-text.json").write_text(json.dumps(out, indent=2, default=str))


async def _rt_aa_compose(page, ed, fmt_bar, aa, tap: bool) -> dict:
    """"Aa" on, RT_LINES typed (Shift+Enter between), "Hey" Bold + Light blue, line 2 Large, through the toolbar
    (taps on a phone). The word selection is set by script (bypass, declared: as in `_rt_make_script`)."""
    press = (lambda loc: loc.tap(timeout=10_000)) if tap else (lambda loc: loc.click(timeout=10_000))
    await press(aa)
    await fmt_bar.wait_for(timeout=10_000)
    await ed.wait_for(timeout=10_000)
    await press(ed)
    await page.keyboard.type(RT_LINES[0])
    await page.keyboard.press("Shift+Enter")
    await page.keyboard.type(RT_LINES[1])
    assert await ed.evaluate(SELECT_WORD, "Hey"), "no 'Hey' to select"
    await press(fmt_bar.get_by_role("button", name="Bold", exact=True))
    await press(fmt_bar.get_by_role("button", name="Text color", exact=True))
    await press(fmt_bar.get_by_role("menuitemradio", name="Light blue", exact=True))
    assert await ed.evaluate(SELECT_WORD, RT_LINES[1]), "no line 2 to select"
    await press(fmt_bar.get_by_role("button", name=re.compile("^Text size")))
    await press(fmt_bar.get_by_role("menuitemradio", name="Large", exact=True))
    return {"toolbar": await fmt_bar.count(), "pressed": await aa.get_attribute("aria-pressed"),
            "editor_html": await ed.inner_html()}


# A phone composer: no sideways scroll, the formatting tools >= 44 px, the text box on screen; "Aa"'s size as drawn
# (the chat's is its toolbar row's 34 px icon box, MP.composer.toolbarButton, as every icon beside it).
PHONE_COMPOSER_FIT = """([tb, aa, ed]) => ({
  page: [document.documentElement.scrollWidth, window.innerWidth],
  toolbar: [tb.scrollWidth, tb.clientWidth],
  small: [...tb.querySelectorAll(':scope > button')].map((b) => b.getBoundingClientRect())
    .filter((r) => r.height < 44 || r.width < 44).length,
  aa: [Math.round(aa.getBoundingClientRect().width), Math.round(aa.getBoundingClientRect().height)],
  box: [Math.round(ed.getBoundingClientRect().top), Math.round(ed.getBoundingClientRect().bottom), window.innerHeight],
})"""


def _rt_fit_ok(fit: dict | None) -> bool:
    f = fit or {}
    box = f.get("box") or [0, 1, 0]
    return (f.get("page", [1, 0])[0] <= f.get("page", [0, 0])[1] and f.get("toolbar", [1, 0])[0] <= f.get("toolbar", [0, 0])[1]
            and f.get("small") == 0 and box[0] >= 0 and box[1] <= box[2])


async def _rt_phone(ctx, browser, through=THROUGH, init=()):
    phone = await ui._owner_page(browser, ctx, PHONE, [], [], (TOURS_SEEN, *init), through=through, touch=True)
    phone.context.set_default_navigation_timeout(WAIT_MS)
    phone.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
    return phone


async def _rt_open_chat_phone(ctx, phone, c, view, fan, sends: list | None = None) -> None:
    async def chats(route):
        if route.request.method != "GET":
            return await route.fallback()
        _aid, off, lim, _plain, rows = _chats_query(route.request, view)
        await _serve_chats(route, rows, off, lim)

    async def send(route):
        if route.request.method != "POST":
            return await route.fallback()
        if sends is not None:
            sends.append(route.request.post_data_json)
        await route.continue_()

    await phone.route(lambda u: urlsplit(u).path == "/api/of/v2/chats", chats)
    await phone.route(lambda u: urlsplit(u).path == f"/api/of/v2/chats/{fan['id']}/messages", send)
    await phone.goto(f"{ctx.app}/messages-pro", wait_until="domcontentloaded")
    tab = phone.get_by_role("tab", name=c["nickname"])
    try:
        await tab.first.tap(timeout=30_000)
    except PwTimeout:
        pass  # a phone without the Creator tabs lists every Creator's chats
    await phone.locator("[data-chat-row]").filter(has_text=f"@{fan['username']}").first.tap(timeout=WAIT_MS)


async def _rt_chat_phone(ctx, browser, c, view, fan, chk, out) -> None:
    """Phone portrait: "Aa" tapped, the formatted message tapped together, Enter -> OF's wire gets RT_MARKUP; the
    toolbar wraps (no sideways scroll), every tool and "Aa" >= 44 px, the text box on screen with the toolbar up."""
    aid = c["id"]
    with ctx.of_wire.lock:
        n_wire = len(ctx.of_wire.sends.get(aid, []))
    res: dict = {}
    phone = await _rt_phone(ctx, browser)
    try:
        await phone.wait_for_timeout(3_500)  # the desktop's last send on this model: the 3 s send gap
        await _rt_open_chat_phone(ctx, phone, c, view, fan)
        box = phone.get_by_placeholder(INPUT, exact=True)
        ed = box.and_(phone.locator("[contenteditable]"))
        fmt_bar = phone.get_by_role("toolbar", name="Text formatting")
        aa = phone.get_by_role("button", name="Aa", exact=True)
        await box.wait_for(timeout=WAIT_MS)
        res = await _rt_aa_compose(phone, ed, fmt_bar, aa, tap=True)
        res["fit"] = await phone.evaluate(PHONE_COMPOSER_FIT, [await fmt_bar.element_handle(), await aa.element_handle(),
                                                               await ed.element_handle()])
        await _painted(phone)
        await ui.shot(ctx, phone, "rich-aa-phone-trigger")
        await ed.press("Enter")
        await _until(lambda: len(ctx.of_wire.sends.get(aid, [])) > n_wire, 30)
        await phone.locator("[data-of-rich]").filter(has_text="Large line").last.wait_for(timeout=30_000)
        await _painted(phone)
        await ui.shot(ctx, phone, "rich-aa-phone-settled")
    finally:
        await phone.context.close()
    with ctx.of_wire.lock:
        got = [m.get("text") for m in ctx.of_wire.sends.get(aid, [])[n_wire:] if str(m["fan_id"]) == str(fan["id"])]
    res["of_wire"] = got
    out["aa_phone"] = res
    chk(RT_AA_PHONE, got == [RT_MARKUP] and _rt_fit_ok(res.get("fit")) and res.get("pressed") == "true",
        of_wire=got, want=[RT_MARKUP], fit=res.get("fit"), pressed=res.get("pressed"))


async def _rt_mass(ctx, page, browser, aid: str, chk, out) -> None:
    """Mass message composer: the desktop script picked keeps its formatting (rich editor), Broadcast -> OF's
    queue wire gets RT_MARKUP. Phone: "Aa" tapped shows the wrapping toolbar, the picked script formatted."""
    n_q = len(_wire(ctx, "queue").get(aid, []))
    bodies: list = []

    async def queue(route):
        if route.request.method == "POST":
            bodies.append(route.request.post_data_json)
        await route.fallback()

    res: dict = {}
    is_queue = lambda u: urlsplit(u).path == QUEUE  # noqa: E731 — unroute needs the same object
    await page.route(is_queue, queue)
    try:
        await _open_create_message(ctx, page, re.compile(r"^OF mass message"))
        box = page.get_by_placeholder("What's the broadcast?", exact=True)
        ed = box.and_(page.locator("[contenteditable]"))
        await box.wait_for(timeout=WAIT_MS)
        tpl_btn = page.get_by_title("Insert saved template").first
        await page.wait_for_function("(b) => b && !b.disabled", arg=await tpl_btn.element_handle(), timeout=30_000)
        sel = page.locator("select:has(option[value])").first
        if await sel.input_value() != aid:
            await sel.select_option(aid)
        res["aa_shown"] = await page.get_by_role("button", name="Aa", exact=True).count()
        await _pick_template(page, RT_TITLE_DESKTOP)
        await ed.locator("span.m-editor-fc__blue-1 strong").first.wait_for(timeout=15_000)
        res["editor_html"] = await ed.inner_html()
        await _painted(page)
        await ui.shot(ctx, page, "rich-mass-trigger")
        await page.get_by_role("button", name="Broadcast", exact=True).click(timeout=10_000)
        await _until(lambda: len(_wire(ctx, "queue").get(aid, [])) > n_q, 30)
        await page.wait_for_timeout(500)
        await _painted(page)
        await ui.shot(ctx, page, "rich-mass-settled")
    finally:
        await page.unroute(is_queue, queue)
    sent = _wire(ctx, "queue").get(aid, [])[n_q:]
    res |= {"of_wire": [m.get("text") for m in sent], "browser": [b.get("text") for b in bodies]}

    phone = await _rt_phone(ctx, browser)
    try:
        await _open_create_message(ctx, phone, re.compile(r"^OF mass message"))
        box = phone.get_by_placeholder("What's the broadcast?", exact=True)
        await box.wait_for(timeout=WAIT_MS)
        tpl_btn = phone.get_by_title("Insert saved template").first
        await phone.wait_for_function("(b) => b && !b.disabled", arg=await tpl_btn.element_handle(), timeout=30_000)
        sel = phone.locator("select:has(option[value])").first
        if await sel.input_value() != aid:
            await sel.select_option(aid)
        aa = phone.get_by_role("button", name="Aa", exact=True)
        await aa.tap(timeout=10_000)
        fmt_bar = phone.get_by_role("toolbar", name="Text formatting")
        await fmt_bar.wait_for(timeout=10_000)
        await ui.shot(ctx, phone, "rich-mass-phone-trigger")
        await _pick_template(phone, RT_TITLE_DESKTOP)
        ed = box.and_(phone.locator("[contenteditable]"))
        await ed.locator("span.m-editor-fc__blue-1 strong").first.wait_for(timeout=15_000)
        res["phone"] = {"editor_html": await ed.inner_html(), "fit": await phone.evaluate(PHONE_COMPOSER_FIT, [
            await fmt_bar.element_handle(), await aa.element_handle(), await ed.element_handle()])}
        await _painted(phone)
        await ui.shot(ctx, phone, "rich-mass-phone-settled")
    finally:
        await phone.context.close()
    out["mass"] = res
    ph = res.get("phone") or {}
    chk(RT_MASS, res["of_wire"] == [RT_MARKUP] and res["browser"] == [RT_MARKUP] and res["aa_shown"] == 1
        and _rt_row_ok(res["editor_html"]) and _rt_row_ok(ph.get("editor_html")) and _rt_fit_ok(ph.get("fit"))
        and min((ph.get("fit") or {}).get("aa") or [0]) >= 44,
        of_wire=res["of_wire"], want=[RT_MARKUP], browser=res["browser"], phone=ph)


def _fansly_accounts(aid: str):
    """GET /admin/accounts with Creator `aid` stamped Fansly (the relay's own field, as a Fansly login writes it):
    a fake at the browser's wire, declared (a real Fansly account would send through the Fansly shim)."""
    async def handler(route):
        if route.request.method != "GET":
            return await route.fallback()
        r = await route.fetch()
        body = await r.json()
        for a in body.get("accounts", []):
            if a.get("id") == aid:
                a["platform"] = "fansly"
        await route.fulfill(response=r, body=json.dumps(body))
    return (lambda u: urlsplit(u).path == "/admin/accounts", handler)


async def _rt_fansly(ctx, browser, c, view, fan, chk, out) -> None:
    """A Fansly account (the sidebar on Fansly): no "Aa", no toolbar; the formatted script goes in as its plain
    text in the textarea and is sent plain (no OF markup reaches the wire). Desktop sends; the phone picks."""
    aid = c["id"]
    init = ("localStorage.setItem('chatterly:platform', 'fansly');",)
    res: dict = {}
    for label, viewport, tap in (("desktop", VIEWPORT, False), ("phone", PHONE, True)):
        sends: list = []
        with ctx.of_wire.lock:
            n_wire = len(ctx.of_wire.sends.get(aid, []))
        pg = await (_rt_phone(ctx, browser, init=init) if tap else ui._owner_page(
            browser, ctx, viewport, [], [], (TOURS_SEEN, *init), through=THROUGH))
        try:
            pg.context.set_default_navigation_timeout(WAIT_MS)
            await pg.route(*_fansly_accounts(aid))
            if tap:
                await _rt_open_chat_phone(ctx, pg, c, view, fan)
            else:
                await pg.wait_for_timeout(3_500)  # the send gap after the phone's send on this model
                await _rt_open_chat_phone_desktop(ctx, pg, c, view, fan, sends)
            box = pg.get_by_placeholder(INPUT, exact=True)
            ta = box.and_(pg.locator("textarea"))
            await ta.wait_for(timeout=WAIT_MS)
            r = {"aa": await pg.get_by_role("button", name="Aa", exact=True).count()}
            await _pick_template(pg, RT_TITLE_DESKTOP)
            r["box"] = await _wait_value(ta, "\n".join(RT_LINES))
            r["editor"] = await box.and_(pg.locator("[contenteditable]")).count()
            r["toolbar"] = await pg.get_by_role("toolbar", name="Text formatting").count()
            await _painted(pg)
            await ui.shot(ctx, pg, f"rich-fansly-{label}-trigger")
            if not tap:
                await ta.press("Enter")
                await _until(lambda: len(ctx.of_wire.sends.get(aid, [])) > n_wire, 30)
                await pg.wait_for_function("(el) => el.value === ''", arg=await ta.element_handle(), timeout=15_000)
                with ctx.of_wire.lock:
                    r["of_wire"] = [m.get("text") for m in ctx.of_wire.sends.get(aid, [])[n_wire:]]
                r["browser"] = [b.get("text") for b in sends]
            await _painted(pg)
            await ui.shot(ctx, pg, f"rich-fansly-{label}-settled")
        finally:
            await pg.context.close()
        res[label] = r
    out["fansly"] = res
    d, p = res["desktop"], res["phone"]
    plain = "\n".join(RT_LINES)
    chk(RT_FANSLY, all(x["aa"] == 0 and x["box"] == plain and x["editor"] == 0 and x["toolbar"] == 0 for x in (d, p))
        and d["browser"] == [plain] and len(d["of_wire"]) == 1 and "m-editor" not in d["of_wire"][0]
        and "<strong>" not in d["of_wire"][0], desktop=d, phone=p, want_box=plain)


async def _rt_open_chat_phone_desktop(ctx, pg, c, view, fan, sends: list) -> None:
    """`_rt_open_chat_phone` with clicks (a desktop context has no touch)."""
    async def chats(route):
        if route.request.method != "GET":
            return await route.fallback()
        _aid, off, lim, _plain, rows = _chats_query(route.request, view)
        await _serve_chats(route, rows, off, lim)

    async def send(route):
        if route.request.method != "POST":
            return await route.fallback()
        sends.append(route.request.post_data_json)
        await route.continue_()

    await pg.route(lambda u: urlsplit(u).path == "/api/of/v2/chats", chats)
    await pg.route(lambda u: urlsplit(u).path == f"/api/of/v2/chats/{fan['id']}/messages", send)
    await pg.goto(f"{ctx.app}/messages-pro", wait_until="domcontentloaded")
    await _creator_tab(pg, c)
    await pg.locator("[data-chat-row]").filter(has_text=f"@{fan['username']}").first.click(timeout=WAIT_MS)


# ── OF Manager (the OF mirror) rich text (lib/ofm_rich_text_faults.py) ──
OFM_TITLE = "slop ofm rich"  # the formatted script (RT_MARKUP), seeded through POST /admin/saved-replies
OFM_FAN = '<p><span class="m-editor-fc__blue-2"><strong>slop ofm fan</strong></span> says <em>hi</em></p>'
OFM_PLAIN = {"title": "slop ofm plain", "text": "slop ofm plain text"}  # seeded here: the scripts section deletes FREE_TPL
OFM_FREE_WIRE = f"<p>{OFM_PLAIN['text']}</p>"  # OFM_PLAIN picked: plain text, of_client wraps it as OF's <p>
OFM_FRAME = "iframe[src*='/of-mirror/pages/']"
OFM_EDITOR = "[contenteditable][aria-label='Textbox field']"
OFM_SEND = "button[at-attr='send_btn']"
OFM_POST_BTN = "button[at-attr='submit_post']"
OFM_MASS_ROW = ".b-chats__scroller label.b-rows-lists__item"
OFM_CARET_TEXT = "slop typed big"  # typed after Large + Bold on an empty caret in the chat's Format text toolbar
OFM_CARET_WIRE = f'<p><span class="m-editor-fs__l"><strong>{OFM_CARET_TEXT}</strong></span></p>'  # OF's wire shape
# The caret-typed bubble: OF's Large (20px) and bold heavier than the line's text, no tag shown as text.
OFM_CARET_LOOK = """(root) => { const l = root.querySelector('span.m-editor-fs__l'), b = l && l.querySelector('strong');
  return { large: l ? getComputedStyle(l).fontSize : null, weight: Number(b ? getComputedStyle(b).fontWeight : 0),
           base: Number(getComputedStyle(root.querySelector('p') || root).fontWeight),
           tags: /&lt;|<\\/?(p|strong|span)\\b/.test(root.textContent ?? '') }; }"""
OFM_MODEL_ID = 1  # the Creator's own OF id in a served thread (any id but the fan's: the mirror's "sent" side)
# The formatted spans' computed look (OF's app.css in the mirror): blue-1 #00aff0, blue-2 #1b98e0, fs__l 20px.
OFM_LOOK = """(root) => { const q = (s) => root.querySelector(s); const cs = (el) => el && getComputedStyle(el);
  const b1 = q('span.m-editor-fc__blue-1'), b2 = q('span.m-editor-fc__blue-2'), l = q('span.m-editor-fs__l');
  return { blue1: cs(b1)?.color ?? null, blue2: cs(b2)?.color ?? null,
           weight: Number(cs((b1 || b2)?.querySelector('strong') || (b1 || b2)?.closest('strong'))?.fontWeight ?? 0),
           base: Number(cs((b1 || b2)?.closest('p'))?.fontWeight ?? 0), large: cs(l)?.fontSize ?? null,
           tags: /&lt;|<\\/?(p|strong|span)\\b/.test(root.textContent ?? '') }; }"""


def _ofm_look_ok(look: dict | None, blue: str = "blue1") -> bool:
    want = {"blue1": "rgb(0, 175, 240)", "blue2": "rgb(27, 152, 224)"}[blue]
    # OF's own app.css draws <strong> at 500 over its 400 text: bold is heavier than the line's text.
    return bool(look) and look[blue] == want and look["weight"] > look["base"] and not look["tags"] \
        and (blue == "blue2" or look["large"] == "20px")


# The OF Manager header row: its left group's content ends before the tools start, the tools inside the viewport.
OFM_HEADER_FIT = """() => { const row = document.querySelector('[data-testid=of-manager-chrome] > div:not(style)');
  const [left, right] = [row.children[0], row.children[1]], l = left.getBoundingClientRect(), r = right.getBoundingClientRect();
  return { left_end: Math.round(l.left + left.scrollWidth), tools_start: Math.round(r.left), tools_end: Math.round(r.right),
           width: innerWidth, scripts: !!right.querySelector('[title="Insert saved template"]') }; }"""


# The frame on a phone: no horizontal scroll, OF's Send fully inside it; `wide` = what sticks out past the right edge.
OFM_FRAME_FIT = """() => { const de = document.documentElement, cw = de.clientWidth;
  const send = document.querySelector("button[at-attr='send_btn']")?.getBoundingClientRect();
  const wide = [...document.querySelectorAll('body *')].filter((el) => el.getBoundingClientRect().right > cw + 1
    && el.getBoundingClientRect().width > 0).slice(0, 6).map((el) => `${el.tagName.toLowerCase()}.${[...el.classList].join('.')}`);
  return { scroll_w: de.scrollWidth, client_w: cw, scroll_x: scrollX,
           send_left: send ? Math.round(send.left) : null, send_right: send ? Math.round(send.right) : null, wide }; }"""


def _ofm_fit_ok(f: dict | None) -> bool:
    return bool(f) and f["scroll_w"] <= f["client_w"] and f["scroll_x"] == 0 and f["send_right"] is not None \
        and f["send_left"] >= 0 and f["send_right"] <= f["client_w"]


def _ofm_header_ok(h: dict | None) -> bool:
    return bool(h) and h["left_end"] <= h["tools_start"] and h["tools_end"] <= h["width"]


async def _frame_settled(loc) -> None:
    """The frame's own CSS transitions done (OF fades its placeholder over 0.1 s): `_painted` sees only the app's."""
    await loc.evaluate("() => Promise.all(document.getAnimations().filter((a) => a instanceof CSSTransition)"
                       ".map((a) => a.finished.catch(() => null)))")


async def _ofm_routes(ctx, page, aid: str, view: dict, fan_rx: dict) -> None:
    """The mirror's OF reads at the browser's wire: the chat list (`view`, `fan_rx`'s row last-messaged OFM_FAN), one
    chat's row, and a thread: `fan_rx`'s OFM_FAN, then every chat send OF's wire took for that fan (sent side). The
    chat send itself goes on to the relay (lib/of_wire.py)."""
    rows = {str(r["withUser"]["id"]): r for r in view[aid]}
    t0 = datetime.now(timezone.utc).replace(microsecond=0)

    def thread(fan: str) -> list[dict]:
        msgs = [{"id": 9_900_001, "text": OFM_FAN, "fromUser": {"id": fan_rx["id"]}, "media": [], "mediaCount": 0,
                 "isFree": True, "price": 0, "createdAt": (t0 - timedelta(minutes=5)).isoformat()}] \
            if fan == str(fan_rx["id"]) else []
        with ctx.of_wire.lock:
            sent = [m for m in ctx.of_wire.sends.get(aid, []) if str(m["fan_id"]) == fan]
        msgs += [{"id": 9_900_100 + i, "text": m.get("text"), "fromUser": {"id": OFM_MODEL_ID}, "media": [],
                  "mediaCount": 0, "isFree": True, "price": 0, "createdAt": (t0 + timedelta(seconds=i)).isoformat()}
                 for i, m in enumerate(sent)]
        return msgs[::-1]  # OF's order=desc

    async def handler(route):
        req = route.request
        path = urlsplit(req.url).path
        parts = path.split("/")  # "", api, of, v2, chats, <fan>, messages
        if req.method == "POST" and len(parts) == 7 and parts[6] == "messages":
            return await route.continue_()  # the chat send: to the relay, whose OFClient sends to lib/of_wire.py
        if req.method != "GET":
            return await route.fallback()
        if path == "/api/of/v2/chats":
            _aid, off, lim, _plain, got = _chats_query(req, view)
            return await _serve_chats(route, got, off, lim)
        if path == "/api/of/v2/users/list":  # the partners' names, by id (OF's /users/list answer)
            ids = parse_qs(urlsplit(req.url).query).get("ids", [])
            return await route.fulfill(status=200, content_type="application/json",
                                       body=json.dumps({i: rows[i]["withUser"] for i in ids if i in rows}))
        if len(parts) == 6 and parts[5] in rows:
            return await route.fulfill(status=200, content_type="application/json", body=json.dumps(rows[parts[5]]))
        if len(parts) == 7 and parts[6] == "messages" and parts[5] in rows:
            return await route.fulfill(status=200, content_type="application/json",
                                       body=json.dumps({"list": thread(parts[5]), "hasMore": False}))
        await route.fallback()

    pat = lambda u: urlsplit(u).path.startswith(("/api/of/v2/chats", "/api/of/v2/users/list"))  # noqa: E731
    await page.route(pat, handler)


async def _ofm_format(frame, editor, tap: bool) -> str:
    """RT_LINES typed in OF's editor, the Format text panel open: "Hey" Bold + Light blue, line 2 Large (OF's menus).
    The word selection is set by script (bypass, declared, as section 25). Returns the editor's markup."""
    press = (lambda loc: loc.tap(timeout=10_000)) if tap else (lambda loc: loc.click(timeout=10_000))
    await press(editor)
    await editor.press_sequentially(RT_LINES[0])
    await editor.press("Enter")
    await editor.press_sequentially(RT_LINES[1])
    panel = frame.locator("[data-oi-format-panel], .js-text-editor-toolbar").first
    if not await panel.is_visible():
        await press(frame.locator("button[aria-label='Format Text']").first)
        await panel.wait_for(timeout=15_000)
    menu = frame.locator(".menuable__content__active .v-list-item")  # ofMirrorMenu showMenu's list
    assert await editor.evaluate(SELECT_WORD, "Hey"), "no 'Hey' to select"
    await press(panel.locator("[aria-label='Bold']").first)
    await press(panel.locator("[aria-label='Text Color']").first)
    await press(menu.filter(has_text=re.compile(r"^\s*Light blue\s*$")).first)
    assert await editor.evaluate(SELECT_WORD, RT_LINES[1]), "no line 2 to select"
    await press(panel.locator("[aria-label='Text Size']").first)
    await press(menu.filter(has_text=re.compile(r"^\s*Large\s*$")).first)
    return await editor.inner_html()


async def _ofm_surfaces(ctx, page, aid: str, fans: list[dict], *, tap: bool, tag: str, out: dict) -> None:
    """One viewport's OF Manager surfaces: the chat (a formatted script picked, sent; on desktop a plain one after it),
    New message (Users tab, one fan, formatted text, Send) and New post (Format text, Post)."""
    press = (lambda loc: loc.tap(timeout=10_000)) if tap else (lambda loc: loc.click(timeout=10_000))
    frame = page.frame_locator(OFM_FRAME)
    editor = frame.locator(OFM_EDITOR).first
    o = out.setdefault(tag, {})
    fan = fans[0]

    def wire_sends() -> list[str]:
        with ctx.of_wire.lock:
            return [m.get("text") for m in ctx.of_wire.sends.get(aid, []) if str(m["fan_id"]) == str(fan["id"])]

    async def chat() -> None:
        # Chat: the Scripts picker (desktop: the pinned column; phone: the header) -> OF's editor -> Send.
        await page.goto(f"{ctx.app}/of-manager/messages/chat?chat={fan['id']}&account={aid}", wait_until="domcontentloaded")
        await editor.wait_for(timeout=WAIT_MS)
        if tag == "desktop":
            fan_bubble = frame.locator(".b-chat__message__text-holder").filter(has_text="slop ofm fan").first
            await fan_bubble.wait_for(timeout=30_000)
            # Read once its style is computed (the thread's first paint can be swapped out by a refetch's).
            for _ in range(20):
                o["fan_bubble_html"] = await fan_bubble.inner_html()
                o["fan_bubble_look"] = await fan_bubble.evaluate(OFM_LOOK)
                if o["fan_bubble_look"]["blue2"]:
                    break
                await page.wait_for_timeout(500)
            last = frame.locator(".b-chats__item__last-message__content").filter(has_text="slop ofm fan")
            o["list_last"] = (await last.first.text_content()).strip() if await last.count() else None
        await _pick_template(page, OFM_TITLE)
        await frame.locator(OFM_EDITOR).filter(has_text=RT_LINES[1]).first.wait_for(timeout=15_000)
        o["chat_editor_html"] = await editor.inner_html()
        o["chat_editor_look"] = await editor.evaluate(OFM_LOOK)
        o["header"] = await page.evaluate(OFM_HEADER_FIT)
        await _painted(page)
        await _frame_settled(editor)
        o["fit_trigger"] = await frame.locator("html").evaluate(f"(_) => ({OFM_FRAME_FIT})()")
        await ui.shot(ctx, page, f"ofm-chat-{tag}-trigger")
        n0 = len(wire_sends())
        await press(frame.locator(OFM_SEND).first)
        await _until(lambda: len(wire_sends()) > n0, 30)
        sent = frame.locator(".b-chat__message__text-holder").filter(has_text="Large line").first
        try:
            await sent.wait_for(timeout=30_000)
            o["sent_bubble_html"] = await sent.inner_html()
            o["sent_bubble_look"] = await sent.evaluate(OFM_LOOK)
        except PwTimeout:
            o["sent_bubble_html"] = None
        await _painted(page)
        await _frame_settled(editor)
        o["fit_settled"] = await frame.locator("html").evaluate(f"(_) => ({OFM_FRAME_FIT})()")
        await ui.shot(ctx, page, f"ofm-chat-{tag}-settled")
        if tag == "desktop":  # a plain script after it stays plain
            await page.wait_for_timeout(3_500)
            await _pick_template(page, OFM_PLAIN["title"])
            await frame.locator(OFM_EDITOR).filter(has_text=OFM_PLAIN["text"]).first.wait_for(timeout=15_000)
            o["plain_editor_html"] = await editor.inner_html()
            n1 = len(wire_sends())
            await press(frame.locator(OFM_SEND).first)
            await _until(lambda: len(wire_sends()) > n1, 30)
        o["chat_wire"] = wire_sends()
        await chat_typed()

    async def chat_typed() -> None:
        # The chat's own Format text toolbar, typed (no script): desktop formats selected words (RT_LINES, as New
        # message / New post), then both arm Large + Bold on an empty caret and type (OF's stored mark). Each Send's
        # wire, and the sent bubble's look.
        n0 = len(wire_sends())
        await page.wait_for_timeout(3_500)  # the last send's "Sent" note gone
        panel = frame.locator("[data-oi-format-panel]").first
        menu = frame.locator(".menuable__content__active .v-list-item")
        if tag == "desktop":
            o["typed_editor_html"] = await _ofm_format(frame, editor, tap)
            n = len(wire_sends())
            await press(frame.locator(OFM_SEND).first)
            await _until(lambda: len(wire_sends()) > n, 30)
            await page.wait_for_timeout(3_500)
        await press(editor)
        if not await panel.is_visible():
            await press(frame.locator("button[aria-label='Format Text']").first)
            await panel.wait_for(timeout=15_000)
        await press(panel.locator("[aria-label='Text Size']").first)
        await press(menu.filter(has_text=re.compile(r"^\s*Large\s*$")).first)
        await press(panel.locator("[aria-label='Bold']").first)
        await editor.press_sequentially(OFM_CARET_TEXT)
        o["caret_editor_html"] = await editor.inner_html()
        await _painted(page)
        await _frame_settled(editor)
        await ui.shot(ctx, page, f"ofm-chat-typed-{tag}-trigger")
        n = len(wire_sends())
        await press(frame.locator(OFM_SEND).first)
        await _until(lambda: len(wire_sends()) > n, 30)
        sent = frame.locator(".b-chat__message__text-holder").filter(has_text=OFM_CARET_TEXT).first
        try:
            await sent.wait_for(timeout=30_000)
            o["caret_bubble_html"] = await sent.inner_html()
            o["caret_bubble_look"] = await sent.evaluate(OFM_CARET_LOOK)
        except PwTimeout:
            o["caret_bubble_html"] = None
        await _painted(page)
        await _frame_settled(editor)
        await ui.shot(ctx, page, f"ofm-chat-typed-{tag}-settled")
        o["typed_wire"] = wire_sends()[n0:]

    async def mass() -> None:
        # New message: Users tab, the first fan ticked, the text formatted in OF's Format text panel, Send (confirm).
        with ctx.of_wire.lock:
            nq = len(ctx.of_wire.queue.get(aid, []))
        await page.goto(f"{ctx.app}/of-manager/messages/send?list=users&account={aid}", wait_until="domcontentloaded")
        row = frame.locator(f"{OFM_MASS_ROW}:visible").first
        await row.wait_for(timeout=WAIT_MS)
        await press(row)
        try:
            await editor.wait_for(timeout=30_000)
        except PwTimeout:  # the phone's New message: OF's composer side is not shown at 390 px (reported, not judged)
            o["mass_composer_hidden"] = await frame.locator(".b-chats__conversations").first.evaluate(
                "(el) => ({ display: getComputedStyle(el).display, width: el.getBoundingClientRect().width })")
            await ui.shot(ctx, page, f"ofm-mass-{tag}-trigger")
            await ui.shot(ctx, page, f"ofm-mass-{tag}-settled")
            o["mass_wire"] = None
            return
        o["mass_editor_html"] = await _ofm_format(frame, editor, tap)
        await _painted(page)
        await _frame_settled(editor)
        await ui.shot(ctx, page, f"ofm-mass-{tag}-trigger")
        await press(frame.locator(OFM_SEND).first)
        await _until(lambda: len(_wire(ctx, "queue").get(aid, [])) > nq, 30)
        await page.wait_for_timeout(1_000)
        await _painted(page)
        await _frame_settled(editor)
        await ui.shot(ctx, page, f"ofm-mass-{tag}-settled")
        o["mass_wire"] = [m.get("text") for m in _wire(ctx, "queue").get(aid, [])[nq:]]

    # Each surface on its own: one that cannot complete is recorded and the next still runs.
    for name, step in (("chat", chat), ("mass", mass),
                       ("post", lambda: _ofm_post(ctx, page, aid, frame, editor, tap, tag, o))):
        try:
            await step()
        except Exception as e:  # noqa: BLE001 — judged by the checks from what was recorded
            o[f"{name}_error"] = f"{type(e).__name__}: {e}"[:600]
            await ui.shot(ctx, page, f"failed-ofm-{tag}-{name}")


async def _ofm_post(ctx, page, aid: str, frame, editor, tap: bool, tag: str, o: dict) -> None:
    """New post: Format text (OF's panel page), the text formatted, Post."""
    press = (lambda loc: loc.tap(timeout=10_000)) if tap else (lambda loc: loc.click(timeout=10_000))
    with ctx.of_wire.lock:
        np_ = len(ctx.of_wire.posts.get(aid, []))
    await page.goto(f"{ctx.app}/of-manager/new-post/state-format-text?account={aid}", wait_until="domcontentloaded")
    await editor.wait_for(timeout=WAIT_MS)
    o["post_editor_html"] = await _ofm_format(frame, editor, tap)
    await _painted(page)
    await _frame_settled(editor)
    await ui.shot(ctx, page, f"ofm-post-{tag}-trigger")
    await press(frame.locator(OFM_POST_BTN).first)
    await _until(lambda: len(_wire(ctx, "posts").get(aid, [])) > np_, 30)
    await page.wait_for_timeout(1_000)
    await _painted(page)
    await _frame_settled(editor)
    await ui.shot(ctx, page, f"ofm-post-{tag}-settled")
    o["post_wire"] = [m.get("text") for m in _wire(ctx, "posts").get(aid, [])[np_:]]


async def _ofm_rich_text(ctx, page, chk) -> None:
    """Section ofm-rich-text: OF Manager's chat, New message and New post keep OF's rich text, desktop and phone."""
    accts = [a for a in (await ctx.owner.get("/admin/accounts")).json().get("accounts", [])
             if a.get("has_session") and a.get("is_active", True)]
    aid = accts[0]["id"]
    c = next(x for x in ctx.world.data["creators"] if x["id"] == aid)
    r = await ctx.owner.request("POST", f"/admin/saved-replies?account_id={aid}",
                                json={"title": OFM_TITLE, "text": RT_MARKUP, "price": 0, "locked_text": False})
    r.raise_for_status()
    r = await ctx.owner.request("POST", f"/admin/saved-replies?account_id={aid}",
                                json={**OFM_PLAIN, "price": 0, "locked_text": False})
    r.raise_for_status()
    view = await _chat_view(ctx, [c])
    fan_d, fan_p = view[aid][1]["withUser"], view[aid][2]["withUser"]
    view[aid][1] = {**view[aid][1], "lastMessage": {**(view[aid][1].get("lastMessage") or {}), "text": OFM_FAN}}
    out: dict = {"account": aid, "fans": {"desktop": fan_d["id"], "phone": fan_p["id"]}}
    errs: dict = {}
    fives: list = []
    try:
        # Each viewport in a fresh context: the run's page holds a Scripts list cached before OFM_TITLE was saved.
        for tag, size, fan, touch in (("desktop", VIEWPORT, fan_d, False), ("phone", PHONE, fan_p, True)):
            tab = await ui._owner_page(page.context.browser, ctx, size, [], [], through=THROUGH, touch=touch)
            try:
                await tab.context.add_init_script(TOURS_SEEN)
                tab.context.set_default_navigation_timeout(WAIT_MS)
                tab.on("dialog", lambda dl: asyncio.ensure_future(dl.accept()))
                await _ofm_routes(ctx, tab, aid, view, fan_d)
                try:
                    await _ofm_surfaces(ctx, tab, aid, [fan], tap=touch, tag=tag, out=out)
                except Exception as e:  # noqa: BLE001 — judged below from what was recorded
                    errs[tag] = f"{type(e).__name__}: {e}"[:600]
                    await ui.shot(ctx, tab, f"failed-ofm-{tag}")
                fives += [u for st, u in tab.slop["statuses"] if st >= 500][:5]
            finally:
                await tab.context.close()
        d, p = out.get("desktop", {}), out.get("phone", {})
        out |= {"errors": errs, "relay_5xx": fives}
        chk(OFM_CHAT_DESKTOP, d.get("chat_editor_html") == RT_MARKUP and _ofm_look_ok(d.get("chat_editor_look"))
            and d.get("chat_wire") == [RT_MARKUP, OFM_FREE_WIRE] and _ofm_look_ok(d.get("sent_bubble_look"))
            and "<span" not in (d.get("plain_editor_html") or "<span") and not fives,
            chat_wire=d.get("chat_wire"), want=[RT_MARKUP, OFM_FREE_WIRE], editor=d.get("chat_editor_html"),
            editor_look=d.get("chat_editor_look"), sent_bubble=d.get("sent_bubble_html"),
            sent_look=d.get("sent_bubble_look"), plain_editor=d.get("plain_editor_html"),
            error=errs.get("desktop") or d.get("chat_error"))
        chk(OFM_CHAT_PHONE, p.get("chat_editor_html") == RT_MARKUP and _ofm_look_ok(p.get("chat_editor_look"))
            and p.get("chat_wire") == [RT_MARKUP] and _ofm_look_ok(p.get("sent_bubble_look")) and not fives
            and _ofm_header_ok(p.get("header")) and p["header"]["scripts"]
            and _ofm_fit_ok(p.get("fit_trigger")) and _ofm_fit_ok(p.get("fit_settled")),
            chat_wire=p.get("chat_wire"), want=[RT_MARKUP], editor=p.get("chat_editor_html"), header=p.get("header"),
            fit=[p.get("fit_trigger"), p.get("fit_settled")],
            editor_look=p.get("chat_editor_look"), sent_look=p.get("sent_bubble_look"),
            error=errs.get("phone") or p.get("chat_error"))
        caret_ok = lambda o: (lambda lk: bool(lk) and lk["large"] == "20px" and lk["weight"] > lk["base"]  # noqa: E731
                              and not lk["tags"])(o.get("caret_bubble_look"))
        chk(OFM_CHAT_TYPED, d.get("typed_wire") == [RT_MARKUP, OFM_CARET_WIRE] and p.get("typed_wire") == [OFM_CARET_WIRE]
            and caret_ok(d) and caret_ok(p) and not fives,
            desktop=d.get("typed_wire"), phone=p.get("typed_wire"), want={"desktop": [RT_MARKUP, OFM_CARET_WIRE],
            "phone": [OFM_CARET_WIRE]}, editors=[d.get("typed_editor_html"), d.get("caret_editor_html"),
            p.get("caret_editor_html")], bubbles=[d.get("caret_bubble_html"), p.get("caret_bubble_html")],
            looks=[d.get("caret_bubble_look"), p.get("caret_bubble_look")], error=[d.get("chat_error"), p.get("chat_error")])
        chk(OFM_BUBBLE, _ofm_look_ok(d.get("fan_bubble_look"), "blue2")
            and d.get("fan_bubble_html") == OFM_FAN and d.get("list_last") == "slop ofm fan says hi",
            bubble=d.get("fan_bubble_html"), look=d.get("fan_bubble_look"), list_last=d.get("list_last"))
        chk(OFM_MASS, d.get("mass_wire") == [RT_MARKUP] and not fives,
            desktop=d.get("mass_wire"), phone=p.get("mass_wire"), phone_composer_hidden=p.get("mass_composer_hidden"),
            want=[RT_MARKUP],
            editors=[d.get("mass_editor_html"), p.get("mass_editor_html")], errors=errs, error=d.get("mass_error"))
        chk(OFM_POST, d.get("post_wire") == [RT_MARKUP] and p.get("post_wire") == [RT_MARKUP] and not fives,
            desktop=d.get("post_wire"), phone=p.get("post_wire"), want=[RT_MARKUP],
            editors=[d.get("post_editor_html"), p.get("post_editor_html")], errors=errs,
            error=[d.get("post_error"), p.get("post_error")])
    finally:
        (ctx.out / "ofm-rich-text.json").write_text(json.dumps(out, indent=2, default=str))


def _rt_dirty(i: int) -> tuple[str, str]:
    """Operator i's formatted body as a careless paste leaves it, and what OF's allow-list keeps of it (by hand,
    never by the product's own function)."""
    dirty = (f'<p onclick="x()"><b>slop rt {i}</b> <span class="m-editor-fc__blue-1 evil" style="color:red">blue'
             f'</span><img src=x onerror="a()"><script>alert({i})</script><br/><i>it</i> '
             f'<span class="m-editor-fs__lg">big</span> &lt;3 &amp;</p><p><font color=red>f</font>'
             f'<a href="//e">link</a></p>')
    clean = (f'<p><strong>slop rt {i}</strong> <span class="m-editor-fc__blue-1">blue</span><br><em>it</em> '
             f'<span class="m-editor-fs__lg">big</span> &lt;3 &amp;</p><p>flink</p>')
    return dirty, clean


async def _rich_volume(ctx) -> None:
    """--users operators at once, each on a Creator (round-robin) and one of its fans: a formatted chat send and
    a plain one (POST /api/of/v2/chats/{fan}/messages), a formatted mass message and a plain one (POST
    /api/of/v2/messages/queue, user_ids [fan]), through the relay's real routes to OF's wire. Its own session
    (the owner's cookies) holds a connection per operator, so a request's time is the relay's, never a wait for a
    client-side connection; p95 is kept apart for plain and formatted bodies."""
    creators = ctx.world.data["creators"]
    users = max(1, ctx.users)
    plans = []
    for i in range(users):
        c = creators[i % len(creators)]
        fans = distinct(ctx.world.data["fans"][c["id"]])
        plans.append((i, c["id"], fans[(i // len(creators)) % len(fans)]["id"]))
    statuses: list[tuple[str, int, float]] = []  # (kind "formatted"/"plain", status, ms)
    http = ctx.owner.share(limits=users + 10)

    async def post(kind: str, path: str, aid: str, body: dict) -> None:
        t0 = time.perf_counter()
        r = await http.post(path, headers={"X-Account-Id": aid}, json=body)
        statuses.append((kind, r.status_code, (time.perf_counter() - t0) * 1000))

    async def operator(i: int, aid: str, fan: int) -> None:
        dirty, _ = _rt_dirty(i)
        plain = f"slop rt plain {i} <3 & co"
        # Half the operators go plain first, so neither kind always lands at the front of the burst.
        kinds = [("formatted", dirty), ("plain", plain)][:: 1 if i % 2 == 0 else -1]
        for path, extra in ((f"/api/of/v2/chats/{fan}/messages", {}), ("/api/of/v2/messages/queue", {"user_ids": [fan]})):
            for kind, text in kinds:
                await post(kind, path, aid, {"text": text, **extra})

    with ctx.of_wire.lock:
        n_send = {a: len(v) for a, v in ctx.of_wire.sends.items()}
        n_queue = {a: len(v) for a, v in ctx.of_wire.queue.items()}
    try:
        await asyncio.gather(*(operator(*p) for p in plans))
    finally:
        await http.aclose()
    with ctx.of_wire.lock:
        sends = [m.get("text") or "" for a, v in ctx.of_wire.sends.items() for m in v[n_send.get(a, 0):]]
        queue = [m.get("text") or "" for a, v in ctx.of_wire.queue.items() for m in v[n_queue.get(a, 0):]]
    want_sends = sorted(t for i in range(users) for t in (_rt_dirty(i)[1], f"<p>slop rt plain {i} &lt;3 &amp; co</p>"))
    want_queue = sorted(t for i in range(users) for t in (_rt_dirty(i)[1], f"slop rt plain {i} <3 & co"))
    got_sends = sorted(t for t in sends if "slop rt" in t)
    got_queue = sorted(t for t in queue if "slop rt" in t)
    bad = [s for s in statuses if not 200 <= s[1] < 300]
    wrong = sorted(set(got_sends) - set(want_sends))[:3] + sorted(set(got_queue) - set(want_queue))[:3]
    ctx.check(RT_VOLUME, got_sends == want_sends and got_queue == want_queue and not bad and len(statuses) == 4 * users,
              operators=users, sends=len(got_sends), queue=len(got_queue), want_each=2 * users,
              non_2xx=bad[:5], unexpected=wrong, sample_want=_rt_dirty(0)[1])
    ms = {k: [s[2] for s in statuses if s[0] == k] for k in ("plain", "formatted")}
    ctx.metric("rich_volume", {"operators": users, "requests": len(statuses),
                               **{f"{k}_p95_ms": _p95(v) for k, v in ms.items()},
                               **{f"{k}_max_ms": max(v) if v else None for k, v in ms.items()}})


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    # A second Agency (real POST /auth/register), so "(N of N)" and "(0 of N)" differ by more than one row.
    # Its owner is the master of sections 6-8 (bypass, declared: is_admin by SQL); the run's owner is not.
    from slop.lib.client import Http
    master = Http(ctx.relay, ctx.rec)
    r = await master.post("/auth/register", json={"username": f"{w.user_prefix}{w.seed}r2", "password": "slop-throwaway-password"})
    r.raise_for_status()
    con = w.sql()
    with con:
        con.execute("UPDATE users SET is_admin=1 WHERE id=?", (r.json()["user_id"],))
    con.close()
    for c in w.data["creators"]:  # the templates and a Smart List, through the real routes
        for tpl in (PAID_TPL, FREE_TPL):
            r = await ctx.owner.request("POST", f"/admin/saved-replies?account_id={c['id']}", json=tpl)
            r.raise_for_status()
        r = await ctx.owner.post("/admin/smart-lists", json={"account_id": c["id"], "name": SMART_LIST})
        r.raise_for_status()
    of_sessions.seed(w, w.data["creators"])  # a real OFClient per Creator, talking to lib/of_wire.py
    aid0 = w.data["creators"][0]["id"]
    # OF still has these media: its by-id read (the stills path's re-sign) answers them, with no
    # file variants (bypass, declared: no thumbnails), so a tile render is not OF saying "deleted".
    ctx.of_wire.vault[aid0] = {mid: {"id": mid, "type": "photo", "files": {}} for mid in _seed_vault(w, aid0)}
    aid1 = w.data["creators"][1]["id"]
    ctx.of_wire.vault[aid1] = {PICKER_VIDEO: _seed_picker_video(w, aid1)}
    aid2 = w.data["creators"][2]["id"]
    ctx.of_wire.vault[aid2] = {mid: {"id": mid, "type": "photo", "files": {}} for mid in _seed_vault_partial(w, aid2)}
    links = await _seed_links(ctx, w)
    _seed_follows(w, aid0)
    # Clock records: time tracking on and the Employee through the real routes, its Clock event by SQL.
    r = await ctx.owner.request("PUT", "/admin/settings/time-tracking", json={"enabled": True})
    r.raise_for_status()
    r = await ctx.owner.post("/admin/employees", json={"display_name": CLOCK_EMPLOYEE})
    r.raise_for_status()
    w.data["clock_event_id"] = _seed_clock(w, r.json()["id"], aid0)
    ctx.of_wire.vault_lists[w.data["creators"][1]["id"]] = [
        {"id": fid, "type": "custom", "name": name, "hasMedia": False, "canUpdate": True, "canDelete": True,
         "photosCount": 0, "videosCount": 0, "gifsCount": 0, "audiosCount": 0, "medias": []}
        for fid, name in FOLDERS]

    for name, why in UNREACHED.items():
        ctx.skip(name, why)
    # `--set only=rich-text,rich-volume`: just those sections / volume parts (iterating; a done run selects none).
    only = {x for x in str(ctx.param("only", "")).split(",") if x}
    if only - SECTIONS.keys() - VOLUME_PARTS.keys():
        raise SystemExit(f"slop: only= names no section: {sorted(only - SECTIONS.keys() - VOLUME_PARTS.keys())}")
    picked = lambda name: not only or name in only  # noqa: E731

    async def volume() -> None:
        for name, (fn, checks) in VOLUME_PARTS.items():
            if picked(name):
                await globals()[fn](ctx)
            else:
                for c in checks:
                    ctx.skip(c, f"not selected (only={','.join(sorted(only))})")

    if ctx.app is None:
        for checks in SECTIONS.values():
            for c in checks:
                ctx.skip(c, "--no-ui")
        await volume()
        ctx.metric("of_wire", ctx.of_wire.snapshot())
        return

    async with ui.owner_browser(ctx, viewport=VIEWPORT, through=THROUGH) as page:
        await page.context.add_init_script(TOURS_SEEN)
        page.context.set_default_navigation_timeout(WAIT_MS)  # a goto's first visit compiles the page too
        page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        for name, fn in (("mass", _mass), ("mass-retry", _mass_retry), ("mass-unsend", _mass_unsend),
                         ("post", _post), ("dupes", _dupes),
                         ("dupes-partial", _dupes_partial), ("group", _group),
                         ("nudge", _nudge),
                         ("admin", lambda c, p, k: _as_master(c, p, k, master, "admin", _admin)),
                         ("smartlist", _smartlist),
                         ("admin-roster", lambda c, p, k: _as_master(c, p, k, master, "admin-roster", _admin_roster)),
                         ("admin-users", lambda c, p, k: _as_master(c, p, k, master, "admin-users", _admin_users)),
                         ("admin-gate", lambda c, p, k: _admin_gate(c, p, k, master)), ("autoreply", _autoreply),
                         ("gtkf", _gtkf),
                         ("audience-pm", _audience_pm), ("audience-fl", _audience_fl),
                         ("funnel-media", _funnel_media),
                         ("frame", lambda c, p, k: _frame(c, p, k, links)), ("autofollow", _autofollow),
                         ("clock", _clock), ("vault", _vault), ("premade", _premade),
                         ("welcome", _welcome),
                         ("fanlist", _fanlist), ("chat-refused", _chat_refused), ("chat-ppv", _chat_ppv), ("bell", _bell), ("vaultmanage", _vaultmanage),
                         ("redescribe", _redescribe), ("shimmer", _shimmer), ("scripts", _scripts),
                         ("session", _session), ("rich-text", _rich_text),
                         ("ofm-rich-text", _ofm_rich_text)):
            if not picked(name):
                for c in SECTIONS[name]:
                    ctx.skip(c, f"not selected (only={','.join(sorted(only))})")
                continue
            await _section(ctx, page, name, lambda chk, fn=fn: fn(ctx, page, chk))
        ctx.metric("held_of_reads", len(page.slop["held_of_reads"]))
        ctx.metric("offhost_aborted", len(page.slop["offhost_aborted"]))
    await volume()  # after the browser: its queue sends stay out of the mass sections' counts
    ctx.metric("of_wire", ctx.of_wire.snapshot())
