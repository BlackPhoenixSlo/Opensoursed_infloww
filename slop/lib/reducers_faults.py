"""The state reducers' break-it-once faults (scenarios/2026-10-29-state-reducers.py): lib/faults.py
merges `register(Fault)` into FAULTS. All are client side: `browser=` rewrites the app's
served JS (actors/ui.py). The check names live here and the scenario imports them, so a target
can never name a check that does not exist.
"""
from __future__ import annotations

MASS_FREE = ("mass composer: a FREE template picked after a PAID one empties the price box and turns the text lock "
             "off (a price typed after it shows the lock unticked)")
MASS_GATE = ("mass composer: Broadcast is disabled with its reason as the title while the text is empty "
             "and while the price is under $3")
MASS_GATE_SEND = ("mass composer: an invalid draft never reaches /messages/queue (Broadcast, if it is ever enabled on "
                  "an empty or under-$3 draft, is clicked, and the send itself refuses it)")
MASS_BODY = ("mass composer: a valid draft's Broadcast POSTs one /messages/queue body with the draft's text, "
             "price, lock and the default audience, for the picked Creator; the relay answers 200, OnlyFans' wire "
             "gets that one mass message and a mass_runs row carries its queue id")
MASS_ALL = ("mass composer: all models on resets the audience (a chip turned off and a Smart List pick) to fans + "
            "following in that one switch, off again leaves the Smart List unpicked, and the all-models Broadcast "
            "reaches OnlyFans' wire once per included model with the default lists and no fan ids")
POST_PRICED = "post composer: a typed price on a text-only post disables Post with 'A paid post needs at least one image'"
POST_ALL = ("post composer: all models on hides the price row (text-only) and the text-only post is accepted "
            "(Post enabled, no 'paid post needs an image')")
POST_BODIES = ("post composer: the all-models Post sends one free text-only POST /posts per included model "
               "(price 0, no media, previews or tags), and each one not failed at the browser's wire reaches "
               "OnlyFans' wire free with that text (relay 200)")
POST_RETRY = ("post composer: after one model's POST /posts answers 500 the modal stays with 'N-1/N succeeded', "
              "and the retry re-posts to that model only (OF's wire ends with one post per model), then closes")
POST_LOCKED = ("post composer: after the partial failure the text box and the ALL-models box are disabled (the content "
               "locked until Start over), and the retry POST carries the original text")
MASS_PARTIAL = ("mass composer: an all-models Broadcast whose one Creator's OF mass queue answers 500 at OF's wire "
                "keeps the modal with 'N-1/N succeeded' (relay 502 for that Creator, 200 for the rest), the text box "
                "and the ALL-models box disabled (content locked)")
MASS_RETRY = ("mass composer: the retry Broadcast reaches OF's wire exactly once more, for the failed Creator only, with "
              "the original text (no duplicate to a Creator that took it: one mass message per Creator in all), then "
              "the modal closes")
MASS_VOLUME = ("mass fan-out at volume (the app's compose/massFanOut.ts + massMessageReducer.ts in node, --users operators "
               "x --scale Creators, one Creator's OF queue answering 500): mid-round an edit and Start over are refused, "
               "round 1 reaches OF's wire once per operator per "
               "other Creator (relay 200, the failed one 502), every operator's content is locked (an edit refused), the "
               "retry goes to the failed Creator only with the original text, and OF's wire ends with exactly one mass "
               "message per operator per Creator")
DUPES_CONFIRM = ("vault duplicates: changing the strictness while 'Remove N copies' is confirming drops the confirm "
                 "('Yes, remove them' gone, the new scan's Remove button back)")
DUPES_PARTIAL = ("vault duplicates: a 2-batch hide whose second batch fails says in the done panel how many the "
                 "first removed ('Removed 250 of 251, then failed: ...'), with no error line of its own")
DUPES_HIDE = ("vault duplicates: 'Yes, remove them' after the strictness change sends exactly one POST "
              "/admin/vault-ai/duplicates/hide, none before it, with the ids ticked on screen at confirm and the "
              "strictness on screen (4)")
GROUP_ACK = ("group: each BroadcastChannel add's ack is truthful (ok exactly when the fan is in the target tab after "
             "it: a full tab refuses, a tab with room takes it, a held fan sent as a string id is taken without a "
             "duplicate)")
GROUP_FANSLY = ("group: a Fansly-style string fan id (past 2^53) sent over the BroadcastChannel is acked ok, lands, "
                "and is still there, as the same string, after the tab reloads")
GROUP_BURST = ("group: a burst of adds posted in one task into a tab with room for 3 (one of them a held fan under "
               "the other id shape) gets acks that exactly match the tab's registry after it: ok fans all held, "
               "refused ones absent, the cap kept, no duplicate")
GROUP_ACK_MS = "group: every add-ack arrives well inside the sender's 400 ms ADD_ACK_TIMEOUT_MS (max <= 150 ms)"
NUDGE_KEEP = ("nudge online: an edit typed while a save is in flight survives the save's config refetch "
              "(Jitter keeps the edit, Delay the saved value)")
NUDGE_STORED = "nudge online: the next Save stores both edits (GET /admin/nudge-config and the account_ai_config row)"
NUDGE_SWITCH = ("nudge online: a save whose PUT lands after a switch to another Creator shows no 'Saved' there, "
                "and back on the saving Creator the form shows the saved Delay")
NUDGE_STALE = ("nudge online: after a landed 'Saved', a switch to a Creator whose config fails to load "
               "shows no 'Saved' under it")
ADMIN_EMPTY = "admin manage: a key roster that loads empty filters live-only to '(0 of N)', not '(N of N)'"
SESSION_NET_KEEP = ("session: a revalidate (window focus) whose /auth/me fails on the network keeps the signed-in "
                    "page and its saved snapshot")
SESSION_401_OUT = ("session: a revalidate answered 401 signs out (the sign-in form in place, the snapshot cleared, "
                   "the relay session untouched)")
SESSION_BOOT_OUT = ("session: a reload whose /auth/me fails on the network shows the retry screen, not the sign-in "
                    "form, and keeps the snapshot; the next reload with the relay reachable signs back in")
ADMIN_ROSTER_FAILED = ("admin manage: a key roster that FAILS keeps every row and live-only says the filter is off "
                       "('key status unavailable — filter off' and the error line), never '(N of N)'")
ADMIN_GATE = ("admin manage: a signed-in owner who is not the master opening /admin/manage by URL sees exactly one "
              "'master account required' line, no rows and no error, and the browser fires no /admin/users or "
              "/admin/users/llm-key-status request")
ADMIN_USERS_FAILED = ("admin manage: a failed first /admin/users load shows its error, with no skeleton left and no "
                      "'No users registered yet.'")
AUTOREPLY_RELOAD = ("auto-reply: after Save and a reload the form shows every edited value (switch, delay, randomise, "
                    "folder, caps, new-fan window, photo options, a Human style box)")
AUTOREPLY_STORED = ("auto-reply: GET /admin/autoreply-config holds every edited value (cents, a [d, 2d] range, the "
                    "ticked folder id) with the stored blob's other knobs kept, and GET /admin/style-config the box")
AUTOREPLY_INFLIGHT = ("auto-reply: a Human style box toggled while the style save is in flight stays toggled after it "
                      "lands, 'Saved' stays off meanwhile, and the next Save PUTs and stores it (GET /admin/style-config)")
AUTOREPLY_DRAFT_INFLIGHT = ("auto-reply: a Delay typed while the settings PUT is in flight is kept and keeps 'Saved' off "
                            "once it lands; the next Save shows 'Saved' and stores it (GET /admin/autoreply-config)")
GTKF_INFLIGHT = ("get to know fans: a cutoff, caption and price typed while the rule PATCH is in flight are kept and keep "
                 "'Saved' off once it lands; the next Save shows 'Saved' and stores them (GET /admin/automation-rules)")
PM_SWITCH = ("priority mass: switching 'Post as' from one Creator to another drops the first one's list picks "
             "(the POST carries the second Creator's picks on the default audience only)")
PM_ROW = "priority mass: the run row's audience (priority_mass_runs.audience_json) is the lists the POST sent"
FL_SEED = ("funnel start: 'Start funnel' is disabled until the Creator's lists land; then its MASSDMEXCLUDE list is "
           "pre-ticked in Exclude and All fans in Send to, Exclude offers no OF built-in (All fans / Following), "
           "and Start is enabled")
FL_SWITCH = ("funnel start: switching Creator with the panel open resets its audience and pre-ticks the new "
             "Creator's MASSDMEXCLUDE; the queue POST carries only that Creator's lists")
FRAME_PAGE1 = ("frame_filter_resets_page: tracking links on page 3, a Source pick and then 'Show deactivated links' "
               "each put the pager on page 1 showing page 1 of the filtered rows")
AF_OFFSET0 = ("autofollow_sort_resets_offset: auto-follow details on page 3 (offset 40), a sort header click and a "
              "range change each send the next /admin/auto-follow/records with offset=0, answered with page 1 as the DB "
              "orders it; Reset (a key already read, so maybe from cache) shows page 1 too")
CLOCK_INVERTED = ("clock records: an edit whose clock out is before its clock in is refused inline ('Clock out must "
                  "be after clock in.'), no PATCH leaves the browser, the clock_events row unchanged")
CLOCK_SAVED = ("clock records: a valid clock-out edit sends one PATCH /admin/shifts/clock-events/{id} with only "
               "out_utc, the relay answers 2xx and the clock_events row holds the new out_utc")
VAULT_DRAG = ("vault folder rail: each Customize-order drag moves the dragged folder into the hovered folder's slot "
              "(the rail shows the expected order mid-customize)")
VAULT_CANCEL = "vault folder rail: Cancel puts the rail back in OF's order and writes nothing (no sort at the relay or OF)"
VAULT_SORT = ("vault folder rail: Done POSTs one /admin/vault-ai/of-folders/sort whose custom_order is the dragged order, "
              "and OF gets it as {customOrder, sort: custom}")
VAULT_RELOAD = ("vault folder rail: after a reload the rail shows the new order, read from OF again "
                "(the relay's vault-lists cache dropped by the sort)")
VAULT_QUICK_RELOAD = ("vault folder rail: a reload 1 s after Done (QUICK_RELOAD_MS, under the app's query snapshot "
                      "throttle, PERSIST_THROTTLE_MS) shows the new order, from its first paint")
VAULT_SORT_LABEL = "vault folder rail: the sort label ('Custom' after Done) survives a reload (kept per Creator)"
VAULT_MIRROR_SORT_LABEL = ("vault folder rail: a folder sort set on the OF-mirror Vault page ('Name', one sort POST) is "
                           "the rail's label after")
PREMADE_ROWS = ("premade composer: added rows and text variants, a removed variant and a removed row leave the "
                "expected rows on screen (captions, prices, delays)")
PREMADE_PAYLOAD = ("premade composer: Use in rule + Create POSTs one /admin/automation-rules whose posts[] are the "
                   "rows' items (order, text/texts, price, delays, hours to live)")
PREMADE_STORED = "premade composer: the created rule's posts[] are stored as sent (GET /admin/automation-rules and the automation_rules row)"
FANLIST_SCOPE = ("fan list: a Creator switch while the old Creator's next page is in flight never shows an old "
                 "Creator row (sampled every frame from the switch), the old page lands after, and the settled list "
                 "is the new Creator's first page; no 5xx")
FANLIST_LOAD_MORE = ("fan list: 'Load more conversations' clicked asks OF for offset 25 and that page's Fans join the "
                     "list")
FANLIST_RETURN = ("fan list: Creator A's next page, in flight when the owner switched to Creator B, is on A's list when "
                  "the owner comes back to A, and still after the warm-up's refetch there")
FANLIST_REWARM = ("fan list: back on Creator A (a list that has paged), picking A's tab refetches A's list (the "
                  "warm-up's invalidation: a /chats offset-0 read for A after the click) and the badge agrees with "
                  "it (badge == unread rows shown among A's first page, after an unread change made while on B)")
BELL_CLEARS = ("bell: N fan DM arrivals show N on the top bar badge; opening the bell clears it (one "
               "chatterly:notif-cleared per open) and it stays clear after close")
AGENCY_READ = ("bell agency tab: 'Mark all read' is one POST /admin/agency-notifications/read-all 2xx, every seeded "
               "row gets read_at, GET unread is 0 and the badge is gone after close")
CHAT_REFUSED_SHOWN = ("chat composer: a paid, tagged schedule the relay refuses after the chatter opened another "
                      "Fan's chat shows its notice there (the Fan's name, the reason, the text, no Restore)")
CHAT_REFUSED_RESTORED = ("chat composer: back in the chat it was written in, Restore brings the refused schedule back "
                         "whole (text, price, lock, tag, schedule), and scheduling it again enqueues one scheduled_send "
                         "row carrying them (relay 200)")

SMARTLIST_STALE = ("smart list editor: a rule edit after Preview count drops the shown count "
                   "(no 'fans match' until Preview count runs again)")
SMARTLIST_GATE = ("smart list editor: a 'between' with one bound, or upper < lower, disables Save and Preview "
                  "count with its reason; no smart list is written (no POST, the route and smart_lists rows unchanged)")
SMARTLIST_SAVED = ("smart list editor: a full 'between' saves: one POST /admin/smart-lists 200, the list in "
                   "GET /admin/smart-lists and its smart_lists row with the bounds in cents")
SCRIPTS_RENAME = ("scripts: a page-only tag renamed after a refetch landed mid-prompt (another session gave it its "
                  "first script) goes to the server: one POST /admin/saved-replies/relabel {tag, from, to} 200, the "
                  "script carries the new name and not the old (route and saved_replies row), the sidebar shows it")
SCRIPTS_REMOVE_OK = ("scripts: Remove from tag on a ticked script: one relabel POST 200 with its id, it leaves the tag "
                     "(route, row and list); when another session puts it back, the refetched row shows it unticked")
SCRIPTS_REMOVE_FAIL = ("scripts: a Remove from tag answered 500 keeps the script in the tag (route and row), in the "
                       "list, its box ticked and the selection bar at 'Selected 1', with the error shown")

# Tier 2, batch 2 (docs/reducer-scan.md): VaultManagePanel editor/browse, the shared useHoverPreview
VM_TICKS = ("vault manage: switching the media type clears the ticked files (no Selected bar on the new view, "
            "none ticked back on All)")
VM_PRICE = ("vault manage: letters typed as a price are not a $0 price (Save & lock stays off; with a description "
            "edit the PATCH carries only the description and the row keeps no price)")
REDESCRIBE_SHOWS = ("vault editor: a Re-describe on an untouched editor shows the new tags and description, and nothing "
                    "reads as edited (Save & lock stays off)")
REDESCRIBE_KEEPS = ("vault editor: a description typed before a Re-describe stays on screen, and Save & lock sends only it "
                    "(PATCH /admin/vault-ai/items/{id} fields = description, the vault_items row has it)")
PICKER_SHIMMER = ("vault picker: a hovered video whose storyboard frame 0 fails drops the build shimmer and its countdown "
                  "(the tile falls back to its thumb)")

_WS = r"(?:\\n|\s)*"  # whitespace as next dev serves it: real, or `\n` inside a module's eval string
# Files this scenario loads that serve app/hooks/useVaultCache.ts (and vaultFolderSort.ts with it): the
# MassMessageComposer chunk, the OF Manager layout and the page chunks of the Message dashboard, Auto funnel, Auto
# post, Get to know fans, Scripts, Smart Messages, Vault Pro and OF Manager (measured, run
# 20261030T134926Z-2026-10-29-state-reducers-break-3aff). `browser_files` of every fault patching either.
USE_VAULT_CACHE_FILES = 10

def register(Fault) -> dict:
    return {
        # slop/run 2026-10-29-state-reducers --break (the scenario's FAULT)
        # app/components/compose/massMessageReducer.ts `pickTemplate`: a FREE template keeps the draft's price
        # and text lock (the pre-reducer bug), so the PAID template's $25 + lock survive. Only the free-template
        # check goes red: the gate and body checks retype the price themselves. Anchored on the mass reducer's
        # own `pickTemplate` -> `addGif` case pair: lib/composeDraft.ts is shared (bundled in the Smart Messages
        # chunk AND the dashboard's), and postComposerReducer.ts / chat/composerDraft.ts have a pickTemplate
        # case too, but followed by other cases, so exactly one served file is rewritten.
        "free-template-keeps-price": Fault(None, (MASS_FREE,), browser=(
            (r'(case \\?"pickTemplate\\?":(?:\\n|\s)*return )([^;]*?\(s, a\.t\));((?:\\n|\s)*case \\?"addGif\\?":)',
             r"\1((n) => a.t.price > 0 ? n : { ...n, price: s.price, lockedText: s.lockedText })(\2);\3"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=mass-broadcast-ignores-invalid
        # app/components/compose/MassMessageComposer.tsx: Broadcast's `disabled` stops reading validateMass, so
        # an empty or under-$3 draft shows an enabled button (its title still says why). Only the gate check
        # goes red: the scenario clicks the enabled button and the send mutation's own validateMass guard
        # refuses it (MASS_GATE_SEND stays green, untargeted), and the body check sends a valid one.
        "mass-broadcast-ignores-invalid": Fault(None, (MASS_GATE,), browser=(
            (r"disabled: send\.isPending \|\| invalid !== null", "disabled: send.isPending"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=mass-reset-keeps-smart-pick
        # app/components/compose/massMessageReducer.ts `audienceReset`: the Smart List include pick survives the
        # reset, so all models on -> off leaves it picked. Only the all-models check goes red: the other mass
        # drafts never pick a Smart List. Anchored on `...(0, <audienceReducer import>.resetAudience)(s),
        # smartInclude`, which only audienceReset has (audienceReducer's own setAccount calls it unqualified,
        # followed by `accountId:`), so exactly one served file (the dynamic MassMessageComposer chunk) is
        # rewritten.
        "mass-reset-keeps-smart-pick": Fault(None, (MASS_ALL,), browser=(
            (r"(\.\.\.\(0,\s*[\w$]+\.resetAudience\)\(s\),(?:\\n|\s)*)smartInclude: new Set\(\),", r"\1"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=dupes-threshold-keeps-confirm
        # app/components/vault/duplicatesReducer.ts: a strictness change keeps the phase, so "Yes, remove
        # them" stays armed over a different scan; clicking it sends the old scan's 2 ids at strictness 2
        # while the screen ticks 3 at strictness 4 (the hide is answered at the browser's wire).
        "dupes-threshold-keeps-confirm": Fault(None, (DUPES_CONFIRM, DUPES_HIDE), browser=(
            (r"threshold: action\.v,((?:\\n|\s)*)deselected: new Set\(\),((?:\\n|\s)*)phase: IDLE",
             r"threshold: action.v,\1deselected: new Set(),\2phase: state.phase"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=group-full-add-acks-ok
        # app/app/group/slotsReducer.ts `add`: a full tab acks ok:true for a fan it refused, so the sender
        # opens no overflow tab and the fan is lost (the ack no longer says what the tab did). The full-tab
        # case and the burst's adds past the cap go red; the Fansly and latency checks do not.
        "group-full-add-acks-ok": Fault(None, (GROUP_ACK, GROUP_BURST), browser=(
            (r"(state\.slots\.length >= \S*GROUP_SLOT_CAP\S*\) return owe\(state, action\.reqId, )false",
             r"\1true"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=post-retry-reposts-all
        # app/components/compose/fanOut.ts `fanOutTargets` (shared by PostComposer, MassMessageComposer and
        # PremadeComposer): a retry targets every included model again (the pre-fix bug), so the models that
        # already took it get a duplicate. The first round is the same (no results yet), so only the retry
        # checks go red: Post's, Mass's and the volume run's (the module in node). `next dev` serves the
        # module in the dynamic MassMessageComposer chunk and the message-dashboard and auto-post page
        # chunks: 3 files (measured); in node it is the one source file.
        "post-retry-reposts-all": Fault(None, (POST_RETRY, MASS_RETRY, MASS_VOLUME), browser=(
            (r"return includedIds\.filter\(\(id\)\s*=>\s*!done\.has\(id\)\)", "return includedIds"),
        ), browser_files=3, ts_files=1),
        # slop/run 2026-10-29-state-reducers --break --fault=fanout-content-unlocked
        # app/components/compose/fanOut.ts `fanOutLocked`: never locked, so after a partial fan-out the
        # fieldset and the ALL-models box stay enabled, the reducers take an edit, and the retry carries the
        # edited text to the failed models while the others kept the original. The scenario types the edit
        # only when the box is enabled. Only the new lock checks go red: the retry targets are
        # fanOutTargets' (POST_RETRY stays green). 3 files and 1 node module, as above.
        "fanout-content-unlocked": Fault(None, (MASS_PARTIAL, MASS_RETRY, POST_LOCKED, MASS_VOLUME), browser=(
            (r"return s\.progress !== null \|\| \(s\.results\?\.some\(\(r\)\s*=>\s*r\.ok\)\s*\?\?\s*false\)",
             "return false"),
        ), browser_files=3, ts_files=1),
        # slop/run 2026-10-29-state-reducers --break --fault=fanout-inflight-unlocked
        # app/components/compose/fanOut.ts `fanOutLocked`: a round in flight no longer locks (the pre-fix rule:
        # only a success locked), so an edit typed mid-round lands, and the retry carries it to the failed
        # models while the others took the original. Only the volume check goes red: it is the one that edits
        # mid-round (the browser sections edit only between rounds). 3 files and 1 node module, as above.
        "fanout-inflight-unlocked": Fault(None, (MASS_VOLUME,), browser=(
            (r"return s\.progress !== null \|\| \(s\.results", "return (s.results"),
        ), browser_files=3, ts_files=1),
        # slop/run 2026-10-29-state-reducers --break --fault=fanout-startover-in-flight
        # app/components/compose/fanOut.ts `discardResults`: Start over runs while a round is in flight (the
        # pre-fix reducer), so a retry's results land on nothing and round 1's successes are forgotten (the
        # next send would repeat them). Only the volume check goes red (its mid-round Start over). 3 files and
        # 1 node module, as above.
        "fanout-startover-in-flight": Fault(None, (MASS_VOLUME,), browser=(
            (r"return s\.progress !== null \|\| s\.results === null \?", "return s.results === null ?"),
        ), browser_files=3, ts_files=1),
        # slop/run 2026-10-29-state-reducers --break --fault=mass-retry-resends-all
        # app/components/compose/massFanOut.ts `massFanOutRound`: all models broadcast from every included
        # model whatever the results (the pre-fix Mass bug: its retry re-sent to the models that took it).
        # The Mass retry checks go red, 1b's and the volume run's (it calls massFanOutRound): the first round
        # is the same, and Post has its own targets. One file (the dynamic MassMessageComposer chunk) and one
        # node module. The results argument becomes null (fanOutTargets(null, ids) = every id); next dev calls
        # the import as `(0, m.fanOutTargets)(`, node sees the TS before vite's SSR rewrite (`fanOutTargets(`).
        # No leading `[\w$]+`: on the served chunks' long inline source-map runs it backtracked quadratically
        # (a run hung 15 min).
        "mass-retry-resends-all": Fault(None, (MASS_RETRY, MASS_VOLUME), browser=(
            (r"(fanOutTargets\)?\()form\.results(, includedIds\))", r"\1null\2"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=nudge-hydrate-overwrites
        # app/components/settings/nudgeOnlineReducer.ts `hydrate`: a refetch overwrites a draft with
        # unsaved edits, so the Jitter typed during the save is lost (and so never stored by the next Save).
        "nudge-hydrate-overwrites": Fault(None, (NUDGE_KEEP, NUDGE_STORED), browser=(
            (r"if \(hasUnsavedEdits\(state\)\)", "if (false)"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=admin-failed-roster-reads-count
        # app/app/admin/manage/manageReducer.ts `filterNote`: a missing roster reads as a count again (the
        # pre-fix label), so live-only over a FAILED roster shows "(N of N)" as if it had filtered.
        "admin-failed-roster-reads-count": Fault(None, (ADMIN_ROSTER_FAILED,), browser=(
            (r"if \(s\.keyStatus === null\) return ", "if (false) return "),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=admin-users-failed-keeps-skeleton
        # app/app/admin/manage/page.tsx: the skeleton shows whenever rows === null (F2, the pre-fix
        # condition), so a FAILED first /admin/users load leaves the skeleton drawn under its error.
        # The lookahead pins the `refreshing ?` that picks the 5-row TableSkeleton (not the Refresh
        # button's spinner or label), and only the manage page's module.
        "admin-users-failed-keeps-skeleton": Fault(None, (ADMIN_USERS_FAILED,), browser=(
            (r"refreshing \?(?=[^?:]{0,200}?TableSkeleton)", "true ?"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=admin-manage-ungated
        # app/app/admin/manage/page.tsx `AdminUsersPage`: the master gate reverted (every session counts as the
        # master), so a non-master opening the page fires both master-only reads (each 403) instead of one line.
        "admin-manage-ungated": Fault(None, (ADMIN_GATE,), browser=(
            (r"if \(me\?\.is_admin !== true\)", "if (false)"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=revalidate-neterror-signs-out
        # app/contexts/userSessionReducer.ts `netError`: a revalidate's network error signs out like a
        # refusal, so one dropped /auth/me on a window focus throws the owner onto the sign-in form.
        # The boot rule (its own branch) and the 401 rule are untouched. `next dev` serves the module
        # in the root layout's chunk and again in each page chunk importing UserContext: one file per page
        # this scenario opens plus the layout's, 16 (measured 2026-10-30, with Get to know fans; a section opening
        # another page moves it).
        "revalidate-neterror-signs-out": Fault(None, (SESSION_NET_KEEP,), browser=(
            (r"return \{(?:\\n|\s)*state: \{(?:\\n|\s)*\.\.\.state,(?:\\n|\s)*revalidating: false(?:\\n|\s)*\},"
             r"(?:\\n|\s)*effects: \[\](?:\\n|\s)*\}",
             "return commit({ ...state, revalidating: false }, null)"),
        ), browser_files=16, ts_files=1),  # node: the Mass volume path loads it once (measured)
        # slop/run 2026-10-29-state-reducers --break --fault=fanlist-placeholder-crosses-creators
        # app/hooks/useChatList.ts `placeholderData`: the previous key's rows stand in across a Creator
        # switch too (`keepPreviousData` as before the branch), so the old Creator's rows stay on
        # screen until the new one's first page answers. `next dev` serves the hook in the page chunks
        # of /group, Smart Messages, Messages Pro and Get to know fans (through lib/ofMirrorChat), the pages this
        # scenario opens: 4 files (measured).
        "fanlist-placeholder-crosses-creators": Fault(None, (FANLIST_SCOPE,), browser=(
            (r'\(scope\.kind !== \\?"model\\?" \|\| prevKey\[2\] === scopeKey\[2\]\)', "true"),
        ), browser_files=4),
        # slop/run 2026-10-29-state-reducers --break --fault=bell-open-keeps-badge
        # app/components/notificationBellReducer.ts: `open` keeps the arrivals and `cleared` (the open's own
        # chatterly:notif-cleared) zeroes nothing, so opening the bell leaves the badge as it was. Served in
        # the root layout's chunk (the top bar) and Messages Pro's: 2 files (measured).
        "bell-open-keeps-badge": Fault(None, (BELL_CLEARS,), browser=(
            (r"return \{((?:\\n|\s)*)open: true,((?:\\n|\s)*)pane,((?:\\n|\s)*)arrivals: 0,",
             r"return {\1open: true,\2pane,\3arrivals: state.arrivals,"),
            (r"return state\.arrivals === 0 \? state : \{(?:\\n|\s)*\.\.\.state,(?:\\n|\s)*arrivals: 0(?:\\n|\s)*\};",
             "return state;"),
        ), browser_files=2),
        # slop/run 2026-10-29-state-reducers --break --fault=refused-schedule-lost-on-switch
        # app/components/chat/Composer.tsx: the Composer's unmount no longer drops its last draft
        # (`latestRef.current = null`), so `afterRefusedSchedule` reads the closed chat's emptied draft and a
        # schedule refused after a chat switch is "put back" into the closed chat (only its text survives,
        # in sessionStorage) and offered nowhere, as before 2026-10-30.
        "refused-schedule-lost-on-switch": Fault(None, (CHAT_REFUSED_SHOWN, CHAT_REFUSED_RESTORED), browser=(
            (r"latestRef\.current = null;", "void 0;"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=autoreply-payload-drops-field
        # app/components/growth/autoReplyForm.ts `buildPayload`: "Don't reply to photo-only messages" is
        # sent as off whatever the draft holds, so it is never stored and the reload shows it off.
        "autoreply-payload-drops-field": Fault(None, (AUTOREPLY_RELOAD, AUTOREPLY_STORED), browser=(
            (r"skip_photo_only: d\.skipPhotoOnly", "skip_photo_only: false"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=autoreply-style-save-wipes-edits
        # app/components/automations/humanStyle.ts `dropSaved`: a landed style save drops every edit (the
        # pre-fix `setStyleEdits({})`), so the box toggled while it was in flight snaps back to the stored value.
        # Served in the Auto-reply and Get to know fans page chunks: 2 files.
        "autoreply-style-save-wipes-edits": Fault(None, (AUTOREPLY_INFLIGHT,), browser=(
            (r"wrote\.get\(k\)\s*!==\s*v", "false"),
        ), browser_files=2),
        # slop/run 2026-10-29-state-reducers --break --fault=style-saved-ignores-edits
        # app/components/automations/HumanStyleBlock.tsx `clean`: the boxes still unsaved stop counting (the box itself
        # is kept), so a box toggled while the style save is in flight shows "Saved" once it lands. Served in the
        # Auto-reply and Get to know fans page chunks: 2 files.
        "style-saved-ignores-edits": Fault(None, (AUTOREPLY_INFLIGHT,), browser=(
            (r"(!m\.isError && )Object\.keys\(edits\)\.length === 0", r"\1true"),
        ), browser_files=2),
        # slop/run 2026-10-29-state-reducers --break --fault=inflight-edit-shows-saved
        # app/components/automations/sentDraft.ts `unsaved` (both forms'): only "no Save yet" counts (the draft
        # compare dropped, as the pre-reducer gates), so a field typed while the save is in flight shows "Saved" once
        # it lands. Served in the Auto-reply and Get to know fans page chunks: 2 files.
        "inflight-edit-shows-saved": Fault(None, (AUTOREPLY_DRAFT_INFLIGHT, GTKF_INFLIGHT), browser=(
            (r"s\.draft !== s\.sent", "s.sent === null"),
        ), browser_files=2),
        # slop/run 2026-10-29-state-reducers --break --fault=nudge-save-ok-any-account
        # app/components/settings/nudgeOnlineReducer.ts `saveOk`: a save landing after an account
        # switch is applied to the account now shown, so B says "Saved" for A's write.
        "nudge-save-ok-any-account": Fault(None, (NUDGE_SWITCH,), browser=(
            (r"if \(action\.accountId !== state\.accountId \|\| state\.saving === null\) return state;"
             r"(?=(?:\\n|\s)*return \{(?:\\n|\s)*\.\.\.state,(?:\\n|\s)*save: \{(?:\\n|\s)*ok: true)", ""),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=nudge-switch-keeps-verdict
        # app/components/settings/nudgeOnlineReducer.ts `account`: the picker's reset keeps the old
        # account's save verdict, so with no config arriving for the new one its "Saved" stands there.
        # A save in flight has no verdict yet, so the mid-save switch check stays green.
        "nudge-switch-keeps-verdict": Fault(None, (NUDGE_STALE,), browser=(
            (r"selected: state\.selected,((?:\\n|\s)*)bulkMsg: state\.bulkMsg",
             r"save: state.save, selected: state.selected,\1bulkMsg: state.bulkMsg"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=audience-setaccount-keeps-lists
        # app/components/audience/audienceReducer.ts `setAccount`: a real account change keeps the old
        # Creator's includes / excludes, so Priority mass sends their list ids under the new one. The
        # funnel panel is keyed per Creator (a fresh reducer), so its switch check stays green; the mass
        # reducer delegates setAccount here but resets the audience after it, and the post reducer reads
        # only `isAccountSwitch` (green too). The module is served in three page chunks (growth/smart-messages,
        # growth/auto-funnel, analytics/message-dashboard for PostComposer's `isAccountSwitch`; measured),
        # hence 3 files (the MassMessageComposer chunk on disk holds it too, yet the served one never matched:
        # measured).
        "audience-setaccount-keeps-lists": Fault(None, (PM_SWITCH,), browser=(
            (r"\.\.\.resetAudience\(s\),((?:\\n|\s)*)accountId: a\.id", r"...s,\1accountId: a.id"),
        ), browser_files=3, ts_files=1),  # node: the Mass volume path loads it once (measured)
        # slop/run 2026-10-29-state-reducers --break --fault=funnel-panel-unkeyed
        # app/components/automations/FunnelEditor.tsx: the FunnelLaunchPanel loses its
        # `key={accountId}`, so a Creator switch keeps the old Creator's audience (no setAccount
        # in the panel). Only the funnel switch check goes red: its seed check runs before the switch.
        "funnel-panel-unkeyed": Fault(None, (FL_SWITCH,), browser=(
            (r'onClose: \(\)=>setLaunching\(null\)((?:\\n|\s)*)\}, accountId \?\? \\?"\\?"',
             r"onClose: ()=>setLaunching(null)\1}, undefined"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=funnel-start-before-seed
        # app/components/automations/FunnelLaunchPanel.tsx: Start no longer waits for the MASSDMEXCLUDE
        # seed, so it is enabled while the lists load. Only the funnel seed check goes red.
        "funnel-start-before-seed": Fault(None, (FL_SEED,), browser=(
            (r"disabled: send\.isPending \|\| !accountId \|\| !seeded", "disabled: send.isPending || !accountId"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=paged-filter-keeps-page
        # app/components/growth/pagedFilters.ts `pagedReducer`: a filter `set` keeps the page (the pre-reducer bug of
        # a setter that forgets setPage(1)), so the tracking-links frame stays on page 3 (clamped) and auto-follow
        # details keep offset=40. The one module is served in the two pages' chunks, hence 2 files.
        "paged-filter-keeps-page": Fault(None, (FRAME_PAGE1, AF_OFFSET0), browser=(
            (r"(\.\.\.a\.patch,(?:\\n|\s)*)page: 1", r"\1page: s.page"),
        ), browser_files=2),
        # slop/run 2026-10-29-state-reducers --break --fault=clock-out-before-in-allowed
        # app/components/stats/recordEditor.ts `validateRecord`: the inverted-interval rule dropped, so the
        # inverted edit is PATCHed (the relay's own 422 still keeps the row). The valid edit is untouched.
        "clock-out-before-in-allowed": Fault(None, (CLOCK_INVERTED,), browser=(
            (r"if \(outUtc && Date\.parse\(outUtc\) <= Date\.parse\(inUtc\)\)", "if (false)"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=move-folder-off-by-one
        # app/components/vault/vaultFolderOrder.ts `moveFolder`: the dragged folder lands one slot after the
        # hovered one, so the rail, the sort body and OF's order after the reload all miss the dragged order.
        # Cancel still restores OF's order.
        "move-folder-off-by-one": Fault(None, (VAULT_DRAG, VAULT_SORT, VAULT_RELOAD), browser=(
            (r"next\.splice\(j, 0, from\)", "next.splice(j + 1, 0, from)"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=vault-order-not-saved-for-reload
        # app/hooks/useVaultCache.ts `invalidateVaultGrid`: no `flushPersistedCache()` (rqPersister itself is in
        # every page chunk, so the call is cut, not the function), so Done's new order is in the cache but not in the
        # query snapshot until its throttled save: a reload 1 s later restores the snapshot from before it and paints
        # the old order first (the rail then reads its folder list again at mount). The settled reload
        # (PERSIST_SETTLE_MS on) and the labels stay green.
        "vault-order-not-saved-for-reload": Fault(None, (VAULT_QUICK_RELOAD,), browser=(
            (r"\(0,\s*[\w$]+\.flushPersistedCache\)\(\)", "void 0"),
        ), browser_files=USE_VAULT_CACHE_FILES),
        # slop/run 2026-10-29-state-reducers --break --fault=vault-sort-label-not-read
        # app/components/vault/vaultFolderSort.ts `loadFolderSort`: the stored sort is never read (the pre-fix
        # label), so after a reload the rail says "Default" though OF has the custom order, and back from the
        # OF-mirror Vault page's sort it says "Default" too.
        "vault-sort-label-not-read": Fault(None, (VAULT_SORT_LABEL, VAULT_MIRROR_SORT_LABEL), browser=(
            (r"return parseFolderSort\(window\.localStorage\.getItem\(folderSortKey\(accountId\)\)\);",
             "return DEFAULT_FOLDER_SORT;"),
        ), browser_files=USE_VAULT_CACHE_FILES),
        # slop/run 2026-10-29-state-reducers --break --fault=dupes-later-batch-fail-throws
        # app/hooks/useVaultCache.ts `hideDuplicates`: a later batch that fails throws as the first one does (the
        # pre-fix code), so the modal shows the error alone and not what the earlier batch removed.
        "dupes-later-batch-fail-throws": Fault(None, (DUPES_PARTIAL,), browser=(
            (r"if \(i === 0\) throw e;", "throw e;"),
        ), browser_files=USE_VAULT_CACHE_FILES),
        # slop/run 2026-10-29-state-reducers --break --fault=fanlist-load-more-click-no-op
        # app/components/chat/FanList.tsx `loadMoreClick`: "Load more conversations" asks for no page, so A's next
        # page is never in flight (the switch checks have nothing to hold) and B's page two never comes. FanList is
        # served in the /group and Messages Pro page chunks: 2 files (measured).
        "fanlist-load-more-click-no-op": Fault(None, (FANLIST_SCOPE, FANLIST_LOAD_MORE, FANLIST_RETURN), browser=(
            (r":\s*\(\)\s*=>\s*q\.loadMore\(\);", ": () => {};"),
        ), browser_files=2),
        # slop/run 2026-10-29-state-reducers --break --fault=fanlist-switch-drops-next-page
        # app/hooks/useChatList.ts queryFn: the signal is read for every list again (the pre-fix destructuring), so
        # React Query cancels and rolls back A's next page once the switch to B leaves A's key unobserved: back on A
        # the list is one page short. Served in the same 3 page chunks as fanlist-placeholder-crosses-creators.
        "fanlist-switch-drops-next-page": Fault(None, (FANLIST_RETURN,), browser=(
            (r"signal: query \? ctx\.signal : undefined", "signal: ctx.signal && (query ? ctx.signal : undefined)"),
        ), browser_files=3),
        # slop/run 2026-10-29-state-reducers --break --fault=warmup-refetch-drops-next-page
        # app/hooks/useCreatorWarmUp.ts `warmUpMayRefetch`: the post-bust invalidation refetches a list loading its
        # next page too (the pre-fix code), which cancels that page: A's page in flight when its warm-up bust lands is
        # dropped, so back on A (whose refetch re-reads only the head) the list is one page short.
        "warmup-refetch-drops-next-page": Fault(None, (FANLIST_RETURN,), browser=(
            (r'return !\(q\.state\.fetchStatus !== \\?"idle\\?" && q\.state\.fetchMeta\?\.fetchMore\);', "return true;"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=warmup-skips-paged-list
        # app/hooks/useCreatorWarmUp.ts `warmUpMayRefetch`: the round-1 predicate, `fetchMeta.fetchMore` alone. React
        # Query keeps that meta after the page settles, so a list that ever paged is never refetched by a warm-up
        # again: back on A nothing re-reads A's list (badge and list can disagree). Its page 2 stays.
        "warmup-skips-paged-list": Fault(None, (FANLIST_REWARM,), browser=(
            (r'return !\(q\.state\.fetchStatus !== \\?"idle\\?" && q\.state\.fetchMeta\?\.fetchMore\);',
             "return !q.state.fetchMeta?.fetchMore;"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=premade-remove-drops-wrong-row
        # app/components/compose/premadeRows.ts `rowsReducer` remove: the row after the clicked one goes, so
        # removing Post 2 of 3 keeps Post 2 and drops Post 3, on screen and in the rule.
        "premade-remove-drops-wrong-row": Fault(None, (PREMADE_ROWS, PREMADE_PAYLOAD, PREMADE_STORED), browser=(
            (r"rows\.filter\(\(_,\s*idx\)\s*=>\s*idx !== a\.i\)", "rows.filter((_, idx) => idx !== a.i + 1)"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=rowToItem-drops-price
        # app/components/compose/premadeRows.ts `rowToItem`: the price is never put on the item, so a PPV post is
        # saved free. The form still shows the price (only the payload and the stored rule go red).
        "rowToItem-drops-price": Fault(None, (PREMADE_PAYLOAD, PREMADE_STORED), browser=(
            (r"if \(Number\.isFinite\(price\) && price > 0\) item\.price = price;", "/* slop: price dropped */"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=smartlist-edit-keeps-preview
        # app/components/growth/smartListEditorState.ts `edited`: a rules edit keeps the last preview (the
        # pre-reducer bug), so the count of the old rules stays on screen.
        "smartlist-edit-keeps-preview": Fault(None, (SMARTLIST_STALE,), browser=(
            (r"\.\.\.patch,((?:\\n|\s)*)rev: s\.rev \+ 1,((?:\\n|\s)*)preview: null",
             r"...patch,\1rev: s.rev + 1,\2preview: s.preview"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=smartlist-between-unchecked
        # app/components/growth/smartListEditorState.ts `validateRule`: every rule valid (the pre-reducer bug),
        # so a one-bound between saves as [lower, 0].
        "smartlist-between-unchecked": Fault(None, (SMARTLIST_GATE,), browser=(
            (r'if \(kind === \\?"enum\\?" \|\| kind === \\?"tag\\?"\) return null;', "return null;"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=vault-type-keeps-ticks
        # app/components/vault/vaultBrowseReducer.ts `view`: a new folder / type / search keeps the ticks (the
        # pre-reducer bug: "Selected 2" over a grid showing none of them).
        "vault-type-keeps-ticks": Fault(None, (VM_TICKS,), browser=(
            (rf"\.\.\.patch,{_WS}selected: NONE", "...patch, selected: state.selected"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=vault-letters-price-zero
        # app/components/vault/vaultItemEditorReducer.ts `parsePriceCents`: letters parse as $0 (Number("") is 0),
        # so "abc" turns Save & lock on and goes out as suggested_price_cents 0.
        "vault-letters-price-zero": Fault(None, (VM_PRICE,), browser=(
            (r'if \(digits === \\?"\\?"\) return undefined;', "if (false) return undefined;"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=redescribe-keeps-old-text
        # vaultItemEditorReducer.ts `refresh`, as the old editor did: the inputs keep their own copy while the
        # baseline follows the describe, so the old text stays up and every changed field reads edited.
        "redescribe-keeps-old-text": Fault(None, (REDESCRIBE_SHOWS,), browser=(
            (r"draft\[f\] = base\[f\] = action\.fields\[f\];", "base[f] = action.fields[f];"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=redescribe-overwrites-edit
        # vaultItemEditorReducer.ts `refresh`: an edited field follows the describe too, so the operator's typing
        # is replaced by the AI's text.
        "redescribe-overwrites-edit": Fault(None, (REDESCRIBE_KEEPS,), browser=(
            (r"if \(state\.draft\[f\] !== state\.base\[f\] \|\| ", "if ("),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=picker-shimmer-stuck
        # app/hooks/useHoverPreview.ts `frameError` on frame 0: the storyboard stays "loading", so the build shimmer
        # and its countdown never leave (the pre-reducer bug). The one hook is bundled into each page that mounts a
        # vault picker, preview or the fan drawer: in a full run the mass composer chunk, the Messages dashboard,
        # Auto Funnel, Auto Post, Get to know fans, Scripts, Smart Messages, Vault Pro and Messages Pro (measured:
        # 20261030T122324Z-2026-10-29-state-reducers-break-f2a6).
        "picker-shimmer-stuck": Fault(None, (PICKER_SHIMMER,), browser=(
            (rf"return \{{{_WS}\.\.\.state,{_WS}scrub: \\?\"failed\\?\"{_WS}\}};", "return state;"),
        ), browser_files=9),
        # slop/run 2026-10-29-state-reducers --break --fault=scripts-remove-unchecks-on-failure
        # app/components/growth/ScriptsPage.tsx `removeScripts`: the uncheck runs before the relabel POST is
        # answered (the pre-fix uncheck at click), so a failed remove loses the ticks. Only the failed-remove check
        # goes red: a successful remove unchecks either way.
        "scripts-remove-unchecks-on-failure": Fault(None, (SCRIPTS_REMOVE_FAIL,), browser=(
            (r"(await relabelM\.mutateAsync\(\{(?:\\n|\s)*kind,(?:\\n|\s)*from,(?:\\n|\s)*ids(?:\\n|\s)*\}\);)"
             r'((?:\\n|\s)*)(dispatch\(\{(?:\\n|\s)*type: \\?"check\\?",(?:\\n|\s)*ids,(?:\\n|\s)*on: false(?:\\n|\s)*\}\);)',
             r"\3\2\1"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=scripts-rename-stale-prompt
        # app/components/growth/ScriptsPage.tsx: the name modal's props (and `onOk`) are frozen when it opens (the
        # pre-fix closure), so a refetch under the open prompt is not seen: a tag that got its first script meanwhile
        # still reads page-only and its rename never reaches the server. Only the rename check goes red.
        "scripts-rename-stale-prompt": Fault(None, (SCRIPTS_RENAME,), browser=(
            (r"promptProps\(namePrompt\)",
             "(globalThis.__slopPrompt?.[0] === namePrompt ? globalThis.__slopPrompt[1]"
             " : (globalThis.__slopPrompt = [namePrompt, promptProps(namePrompt)])[1])"),
        )),
    }
