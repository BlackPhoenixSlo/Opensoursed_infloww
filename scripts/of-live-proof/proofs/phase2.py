"""Phase 2's proofs (docs/spec/ofm-not-yet/phase-02-content-chat-writes.md): one `Proof` per control and page group,
each naming its sweep `page` and `control` label, kind `live`, or `mocked` for no-OF-write and parked rows (Phase 0's
format, data only). Each Phase 2 control ticket adds its own; empty until then (ticket 29). Its capture record is
`docs/of-manager/captures/<section>--<control-slug>.json` with the same label and page.

    ./venv/bin/python -I scripts/of-live-proof/proofs/phase2.py --ids | --check-records <dir> | --check-sweep <sweep> <dir>

(proof_list.py says what each does.)
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from proof_core import OFM_NEW_WRITES, Proof, Write, marker_problem, read_id_query  # noqa: E402,F401

PROOFS = ()

# ticket 31: the chat list header's More (the sort toggle), the chat header's More and each message's More, on the
# messages list, its dropdown and folders dialog, the chat page and each of its State pages (every variant checked). The
# More opens a menu and sends nothing itself (mocked); its items are the chat page's, each sending what it sends there.
# ASSUMPTION: the sweep labels all three "More", so one proof and one record per page cover the page's Mores together
# (they lose the Not-yet title together, on ticket 54's Live proof; rung 5); overturned if ticket 54 must drop them one
# by one, which then needs a record id on Proof (proof_list.py's own ASSUMPTION).
MESSAGES_MORE_PAGES = ("messages/index", "messages/state-filter-dropdown", "messages/state-folders", "messages/chat",
                       "messages/chat/gallery", "messages/chat/pinned", "messages/chat/state-header-menu",
                       "messages/chat/state-price", "messages/chat/state-schedule", "messages/chat/state-tag-people",
                       "messages/chat/state-vault")
PROOFS += tuple(Proof(id=f"messages.more.{p.removeprefix('messages/').replace('/', '.')}", phase=2, page=p,
                      control="More", kind="mocked") for p in MESSAGES_MORE_PAGES)
# ticket 30
# Record video and Record voice (Home and its State pages, New post): one proof per control for the Home page group
# (the sweep's page; New post's buttons never had the Not-yet title). The recording goes up through the existing upload
# (`service/of_upload.py` upload_media: signed create, the storage PUT, the convert claim) and rides a Scheduled post at
# least a month ahead (the schedule calendar's next month, its first day), deleted before it fires. The post's text is
# the run's marker so the effect and the lost-reply finder know it.
# Undo (D30; spec per-control table): the post's DELETE, then OF's own "Remove from vault" (`PUT /vault/media/hidden`
# {"mediaIds": [<id>]}, `service/of_sends.py` hide_vault_media, through the Relay's `POST /admin/vault-ai/items/{id}/
# hide`) on the vault item the upload made. The hide is ONE-WAY: OF has no unhide, and the item is hidden, not
# destroyed (fans never see the vault either way). Its media id is in no upload reply (a fresh upload answers
# `vault_id: null`, `service/of_upload.py:696`; OF lists the id on the post that carries the claim, `service/
# of_upload.py:852-853`), so it is read off the created post (the post row's OnlyFans id) in the after-write read
# (`vault_media`) and registered with the Relay as kind `media`, which binds the hide's body to it alone (ticket 131).
# The post row's undo is DELETE then the hide; each upload row's undo is that same hide (by the row's arm index,
# `Write.reverses`), not sent again.
# OF lists a dated scheduled post only in `GET /schedules` (`service/of_reads.py` schedules), never in
# `GET /schedules/later/post` (the saved-for-later list, `publishDateTime` null): measured live 2026-11-21, ticket 136
# (docs/of-manager/captures/queue--scheduled-post-endpoint.json). `/schedules` honours `filter[publishDate]` ..
# `filter[publishDateEnd]` in `filter[timeZone]`, ignores `limit` and `offset` (all rows in range come back) and answers
# `{list, syncInProcess}`, no `hasMore`; so one read over SCHEDULE_WINDOW, no offset paging. Its rows are queue
# rows {id, type, publishDateTime, createdDateTime, entity}, each wrapping its post in `entity` (`id`, `text`,
# `rawText`), the row's own `id` not the post's (app/lib/__fixtures__/of/queue-schedules-2026-11.json). The calendar
# also holds scheduled chats (service/of_reads.py `schedules`), so only `type: "post"` rows are read. A row with no
# `type`, or a post row without `entity`, fails the read, never read as a post.
# ASSUMPTION: today-1d .. today+45d covers every date a Phase 2 proof schedules (the Record and labels proofs pick the
# calendar's next month's first day, at most 31 days out; the day before absorbs a UTC/local day edge) (rung 5);
# overturned by a proof that schedules further out, which then widens SCHEDULE_WINDOW.
# The time zone is the capture browser's (`timezone_id="UTC"`, prove.py and of_browser.py new_context), as OF's Queue
# page sends its browser's.
# ASSUMPTION: the post's `media` list carries each vault media `id` (rung 4: `materialize_to_vault` reads `media[].id`
# off the post itself; the capture is a text-only post); overturned by the Live proof's read, which then names it.
# ticket 53: the storage PUT, measured on the live run of 2026-11-21 (the Relay's wire log, seq 45, refused there as
# off-host): host `of2transcoder.s3-accelerate.amazonaws.com` (also `service/of_upload.py:29` `_S3_BASE`), path
# `/upload/<creator>/<uuid>/<id>/<file name>`, OF's key with the Creator's id spliced in (`service/of_upload.py`
# request_signed_upload). The PUT arm names its host (`Write.host`, S3_HOST; so `Proof.hosts`), carried as
# `facts.upload_host` by both Record capture records; the Relay's arm puts it in Run.hosts only while this proof is
# armed, and the Live guard takes that host for the PUT arm alone, the PUT arm on that host alone. convert.onlyfans.com
# (the claim) passes as an onlyfans.com subdomain.
# ASSUMPTION: Record voice's PUT goes to the same host and path shape (rung 3: the same upload_media and `_S3_BASE`;
# only Record video's was measured); overturned by a Record voice live run whose PUT goes elsewhere.
# ASSUMPTION: the Relay's hide route passes its mirror check in the proof's temp DB (no vault rows collected:
# `vault_of_folders._reject_foreign_media`'s escape hatch) (rung 4: if it refuses, no hide reaches OF and the upload
# rows close FAILED, owner action); overturned by a Live proof whose hide the Relay refuses, which then needs the item
# mirrored first.
MARKER = "oi-proof-"
POST_EDITOR = "[contenteditable][aria-label='Textbox field']"
RECORD_BUTTON = {"Record video": ".b-chat__video-message__preview .vjs-record-button",
                 "Record voice": ".js-chat__audiorecord-panel .b-float-panel__btn-record"}
UPLOAD, POST = (0, 1, 2), 3   # arm indexes: signed create, storage PUT, convert claim; the post
S3_HOST = "of2transcoder.s3-accelerate.amazonaws.com"   # the storage PUT's host (ticket 53, measured)
# The Relay's upload_media writes, in order (UPLOAD's indexes): every proof that uploads arms these (ticket 67's cover).
UPLOAD_ARMS = (Write("POST", "/api2/v2/upload/signed/create"),
               Write("PUT", "/upload/{creator}/{key}/{part}/{file}", host=S3_HOST),
               Write("POST", "/file/upload"))
# Seconds after Stop before Schedule: Schedule is a link (`target=_top`, home/state-schedule), so the page it leaves
# must already hold the attached recording; its three upload writes go out at least the guard's 5 s pace apart.
# ASSUMPTION: 15 s covers a few-second recording's upload at that pace (rung 1: the fake run, two 5 s gaps; rung 5);
# overturned by a run whose draft reaches Schedule without the recording, which then waits for the composer's thumb.
UPLOAD_WAIT = 15


SCHEDULE_WINDOW = (-1, 45)   # days from today (UTC): `/schedules`' publishDate .. publishDateEnd
SCHEDULE_TZ = "UTC"   # the capture browser's time zone


def scheduled_post_items(get, today=None):
    """Every dated scheduled post, as OF's own post dicts: one `GET /schedules` over SCHEDULE_WINDOW in SCHEDULE_TZ
    (OF ignores limit/offset there and answers every row in range), each queue row's `entity` (the row's own `id` is
    the queue's, not the post's). `/schedules` is the calendar of scheduled chats AND posts (service/of_reads.py
    `schedules`), so only `type: "post"` rows count; another type (a scheduled chat) is skipped. A row with no `type`,
    or a post row without `entity`, raises: not OF's captured shape, never read as a post. Shared Phase 2 plumbing:
    `read_scheduled_posts` and ticket 35's `read_post_extras`."""
    today = today or datetime.now(timezone.utc).date()
    start, end = (today + timedelta(days=d) for d in SCHEDULE_WINDOW)
    page = get("/api2/v2/schedules", {"filter[publishDate]": start.isoformat(),
                                      "filter[publishDateEnd]": end.isoformat(),
                                      "filter[timeZone]": SCHEDULE_TZ, "limit": 100})
    items = (page.get("list") if isinstance(page, dict) else page) or []
    untyped = [x for x in items if not (isinstance(x, dict) and isinstance(x.get("type"), str))]
    if untyped:
        raise ValueError(f"scheduled row without `type` (not OF's captured shape): {str(untyped[0])[:200]}")
    rows = [x for x in items if x["type"] == "post"]
    bare = [x for x in rows if not isinstance(x.get("entity"), dict)]
    if bare:
        raise ValueError(f"scheduled-post row without `entity` (not OF's captured shape): {str(bare[0])[:200]}")
    return [x["entity"] for x in rows if "id" in x["entity"]]


def read_scheduled_posts(get, fan):
    """Every dated scheduled post as (id, text, its media ids), sorted: OF's `GET /schedules` over SCHEDULE_WINDOW
    (`scheduled_post_items`)."""
    return sorted((str(x["id"]), str(x.get("rawText") or x.get("text") or ""),
                   tuple(sorted(str(m["id"]) for m in x.get("media") or [] if isinstance(m, dict) and m.get("id") is not None)))
                  for x in scheduled_post_items(get))


def _new(before, after):
    """The scheduled posts in `after` and not in `before`, as tuples (a read written to JSON gives lists)."""
    key = lambda r: (r[0], r[1], tuple(r[2]))  # noqa: E731
    return set(map(key, after)) - set(map(key, before))


def one_new_marked_post_with_media(before, after):
    """The declared effect: exactly one scheduled post more, its text the run's marker, carrying one media item."""
    new = _new(before, after)
    return len(new) == 1 and MARKER in next(iter(new))[1] and len(next(iter(new))[2]) == 1


def find_marked_post(before, after, marker):
    """A lost reply's finder (story 53): the one scheduled post new since `before` whose text holds `marker`."""
    new = [r for r in _new(before, after) if marker in r[1]]
    return new[0][0] if len(new) == 1 else None


def vault_media(before, after):
    """The hide's keys (`Proof.undo_keys`): {post id: {"media": its one media item's vault id}} for each new scheduled
    post carrying one media item; the post row takes its own by its OnlyFans id (`read_keys_for`, ticket 131)."""
    return {r[0]: {"media": r[2][0]} for r in _new(before, after) if len(r[2]) == 1}


def _record(control, slug):
    return Proof(
        id=f"p2.record-{slug}", phase=2, page="home/index", control=control, kind="live", tags=frozenset({"post", OFM_NEW_WRITES}),
        arm=(*UPLOAD_ARMS, Write("POST", "/api2/v2/posts")),
        trigger=(("fill", POST_EDITOR, "{marker}"),
                 ("click", f"button[aria-label='{control}']"),
                 ("click", RECORD_BUTTON[control]),
                 ("wait", 2),
                 ("click", RECORD_BUTTON[control]),
                 ("wait", UPLOAD_WAIT),
                 ("click", "a[at-attr='scheduled_msg']"),
                 ("frame", "home/state-schedule"),
                 ("click", ".vdatetime-calendar__navigation--next"),
                 ("click", ".vdatetime-calendar__month__day:not(.vdatetime-calendar__month__day--disabled)"),
                 ("click", ".vdatetime-popup__actions__button--confirm button"),
                 ("frame", "home/index"),
                 ("click", "button[at-attr='submit_post']")),
        settled=("text", "#oi-toast", "Your post is scheduled for"),
        of_read=read_scheduled_posts,
        effect=one_new_marked_post_with_media,
        undo=(Write("DELETE", "/api2/v2/posts/{id}", relay="/api/of/v2/posts/{id}", reverses=(POST,)),
              Write("PUT", "/api2/v2/vault/media/hidden", body_must={"mediaIds": ["{media}"]}, relay_method="POST",
                    relay="/admin/vault-ai/items/{media}/hide", relay_body={"account_id": "{account}"},
                    reverses=(*UPLOAD, POST))),
        find=find_marked_post,
        undo_keys=vault_media,
    )


PROOFS += (_record("Record video", "video"), _record("Record voice", "voice"))

# ticket 34: the vault folder page's header More (vault/list?list=<id>, the one header More there). Its menu's Rename
# and Delete send the vault list's own routes (POST /admin/vault-ai/of-folders/<id>/rename {account_id, name}, DELETE
# /admin/vault-ai/of-folders/<id>?account_id=), which the Relay sends on as OF's PATCH and DELETE /vault/lists/<id>
# (service/of_sends.py rename_vault_list, delete_vault_list). Both proofs work on a folder the run creates through the
# page's own "Create new category" (POST /vault/lists {name}, the marker), never a pre-existing one. Rename opens the
# folder's Rename category modal (state-add-list?edit=1, as the action row's RENAME), whose Save opens the Vault on the
# renamed folder; Delete is confirmed (the step accepts only OF's folder-delete confirm). The rename's PATCH
# is armed on `{created}` (proof_core `_match`), the delete is the create's declared undo (class 8). Live runs refuse
# them until the live OF-side reader (ticket 11, live_entry LIVE_READER_MISSING); fake mode runs them on soak's FakeOF.
# Undo: the proof-created folder's DELETE through the Relay's own route, one request for both rows of the rename (the
# create's and the PATCH's, deduped by undo_driver); for vault.more.delete the UI's Delete is that DELETE (undo_driver
# `trigger_reversal` takes it as the record), so the run sends no second one.
_VAULT_LISTS = "/api2/v2/vault/lists"
_FOLDER_TITLE = ".l-main-content.m-r-side .g-page-title > span"
_OPEN_ROW = ".b-rows-lists__item a[aria-current='page'] .b-rows-lists__item__name"   # the folder column's open folder
_RENAMED = " renamed"


def read_folders(get, fan):
    """Every custom vault folder as (id, name), sorted: OnlyFans's `GET /vault/lists` (`{list, hasMore}`, `view=main`
    mandatory, service/of_reads.py `vault_lists`), paged."""
    rows, off = [], 0
    while True:
        page = get(_VAULT_LISTS, {"view": "main", "offset": off, "limit": 50})
        items = page.get("list") or []
        rows += [(str(x["id"]), str(x.get("name") or "")) for x in items
                 if isinstance(x, dict) and "id" in x and x.get("type") == "custom"]
        if not page.get("hasMore") or not items:
            return sorted(rows)
        off += len(items)


def _new_folders(before, after):
    """The folders in `after` and not in `before` (a read written to JSON gives lists)."""
    return set(map(tuple, after)) - set(map(tuple, before))


def renamed_folder(before, after):
    """vault.more.rename's effect: exactly one folder more, its name the marker renamed (the create alone, or a rename
    FakeOF ignored, cannot pass)."""
    new = _new_folders(before, after)
    return len(new) == 1 and next(iter(new))[1].startswith(MARKER) and next(iter(new))[1].endswith(_RENAMED)


def folder_gone(before, after):
    """vault.more.delete's effect: the folders read as before, no marked folder left (a delete FakeOF ignored fails)."""
    return list(map(tuple, after)) == list(map(tuple, before)) and not any(n.startswith(MARKER) for _, n in after)


def find_marked_folder(before, after, marker):
    """A lost reply's finder (story 53): the one folder new since `before` whose name starts with `marker`, else None."""
    new = [r for r in _new_folders(before, after) if r[1].startswith(marker)]
    return new[0][0] if len(new) == 1 else None


_CREATE = Write("POST", _VAULT_LISTS)
_DELETE = Write("DELETE", _VAULT_LISTS + "/{id}", relay="/admin/vault-ai/of-folders/{id}?account_id={account}")
_MORE = ".l-main-content.m-r-side [at-attr='list_dropdown'] > button"
# the folder the run creates, through vault/list's own "Create new category" (a top link to vault/state-add-list),
# landing on the Vault with it open (vault/index); then its own page, vault/list?list=<the created id>
# the name field once bindFolderForm wired it (a fill before that leaves Save off: measured flake 11-21)
_NAME, _SAVE = ".modal input[at-attr='input'][data-oi-wired]", ".modal-footer button[type='submit']"
_CREATE_STEPS = (("click", "a[aria-label='Create new category']"),
                 ("frame", "vault/state-add-list"),
                 ("fill", _NAME, "{marker}"),
                 ("click", _SAVE),
                 ("frame", "vault/index"),
                 ("goto", "vault/list?list={id}"),
                 ("text", _FOLDER_TITLE, MARKER))   # its page drew the folder (the menu knows it)
PROOFS += (
    Proof(id="vault.more.rename", phase=2, page="vault/list", control="More", kind="live", tags=frozenset({OFM_NEW_WRITES}),
          arm=(_CREATE, Write("PATCH", _VAULT_LISTS + "/{created}")),
          trigger=(*_CREATE_STEPS,
                   ("click", _MORE),
                   ("click", "#oi-menu [data-oi-value='rename']"),
                   ("frame", "vault/state-add-list"),   # the folder's Rename category modal (?edit=1)
                   ("text", ".modal-title", "Rename category"),
                   ("fill", _NAME, "{marker}" + _RENAMED),
                   ("click", _SAVE)),
          settled=("text", _OPEN_ROW, _RENAMED.strip(), "vault/index"),   # Save opens the Vault on the renamed folder
          of_read=read_folders, effect=renamed_folder, undo=(_DELETE,), find=find_marked_folder),
    Proof(id="vault.more.delete", phase=2, page="vault/list", control="More", kind="live", tags=frozenset({OFM_NEW_WRITES}),
          arm=(_CREATE,),
          trigger=(*_CREATE_STEPS,
                   ("click", _MORE),
                   ("accept", "#oi-menu [data-oi-value='delete']", 'Delete the folder "')),
          settled=("text", _FOLDER_TITLE, "All media", "vault/index"),
          of_read=read_folders, effect=folder_gone, undo=(_DELETE,), find=find_marked_folder),
)
# ticket 32
# New message's list page (messages/send/state-list-dropdown): its nine composer tools, proven on the Mass draft only.
# The list Send is never run (ADR-0042: never a mass message): no proof here arms a write. Scheduled messages, Message
# price, Add media from vault and Format Text are read proofs (no arm; story 32: zero writes). Scheduled messages settles
# on the line under the editor; the price and vault buttons settle on the dialog the click opened (ticket 61's landed
# page: its frame exists only after the list button's navigation, no reload), their picks New message's own proofs';
# Format Text settles on New message's open Format text panel (`?format=1`), the format itself content_writes'.
# ASSUMPTION: Add media, Record video and Record voice are mocked: their draft effect is an upload, an OnlyFans write
# (signed create, storage PUT, convert claim) with no undo off a sent message or post (ticket 30's hide reads the vault
# id off the post), so no draft-only Live proof exists (rung 4); overturned by ticket 53 naming an undo for a bare upload.
# ASSUMPTION: Add GIF and Tag other creators are mocked: their picks need a Giphy read (third party, no FakeOF route)
# and the Creator's taggable creators (no FakeOF route), so no definition passes in fake mode (rung 4); overturned by
# FakeOF serving those reads, which then makes them read proofs like the price's.
LIST_PAGE = "messages/send/state-list-dropdown"
LIST_SUMMARY = "#oi-chat-summary"
PROOFS += (
    Proof(id="p2.list-schedule", phase=2, page=LIST_PAGE, control="Scheduled messages", kind="live",
          trigger=(("click", "button[at-attr='scheduled_msg']"),
                   ("click", ".custom-datepicker-button-save-later")),
          settled=("text", LIST_SUMMARY, "Saved for later")),
    Proof(id="p2.list-price", phase=2, page=LIST_PAGE, control="Message price", kind="live",
          trigger=(("click", "[at-attr='price_btn']"),),
          settled=("text", ".modal.show .modal-title", "MESSAGE PRICE", "messages/send/state-price")),
    Proof(id="p2.list-vault", phase=2, page=LIST_PAGE, control="Add media from vault", kind="live",
          trigger=(("click", "[at-attr='add_vault_media']"),),
          settled=("text", ".modal-header .g-page-title", "Vault", "messages/send/state-vault")),
    Proof(id="p2.list-format", phase=2, page=LIST_PAGE, control="Format Text", kind="live",
          trigger=(("click", "button[aria-label='Format Text']"),),
          settled=("text", "[data-oi-format-panel].b-form-editor", "Default", "messages/send")),
    *(Proof(id=f"p2.list-{slug}", phase=2, page=LIST_PAGE, control=control, kind="mocked")
      for control, slug in (("Add media", "add-media"), ("Record video", "record-video"), ("Record voice", "record-voice"),
                            ("Add GIF", "gif"), ("Tag other creators", "tag"))),
)

# ticket 35: New post's ADD LABELS, EXPIRATION PERIOD and Fundraising target, sent on a Scheduled post the run makes on
# the Proof Creator through the composer (new-post/index and its State pages), read back off OnlyFans. The composer's
# body is the existing one (app/lib/ofMirrorPostDraft.ts collectPost: `label_ids`, `expire_days`, `fund_raising_target`,
# `posted_at`), which the Relay's `POST /api/of/v2/posts` sends on as OF's `labelIds`, `expireDays`,
# `fundRaisingTargetAmount` + `fundRaisingTipsPresets` and `isScheduled` + `scheduledDate` (service/of_sends.py
# `_post_body`). The trigger picks the 7 days tab, types a $25 target, ticks the labels dialog's first row (the Relay's
# list of the Creator's own labels, in its order), schedules the post on the next month's first day and posts the
# marker; the effect fails unless the one new post reads back with exactly that label, 7 days and $25 (a 2xx that drops
# a field fails: fake_layer's post-drop-* faults). Undo (D30): the post's DELETE, before it fires (class 7 deadline).
# Why the docs called them read-only: docs/infloww-parity-matrix.md §3.2 New post said "labels, poll, quiz, expiration
# and target read-only" (write and states columns, until this ticket), which spec phase-02 line 10 ("§3.2 still calls
# them read-only and none was proven live") and line 297 ("Observed stale doc") name as stale. They were Wired before
# this effort and never carried the Not-yet title: every new-post/* page has `ny: []` in
# docs/of-manager/not-yet-sweep-2026-11-20.json, and spec line 10 lists only Record video/voice as New post's Not-yet
# controls. Hence NEVER_TITLED: proof_list --check-sweep wants each of the three sweep labels (the `control`, joined by
# NEVER_TITLED_SEP) absent from `ny` and present on the page's mirror HTML, with or without a Live pass.
# The read is `scheduled_post_items` (each queue row's `entity`, so the id found and deleted is the post's, never the
# queue row's). ASSUMPTION: OF's post gives the labels as `labelStates[]` items `{id, isAdded}` (a bare id also
# counts), the expiry as `expiredAt` = `postedAt` + the days, and the target as `fundRaising.target`; a field never sent
# is absent or null (rung 4: docs/plans/of-manager-api-catalogue.md's Posts reply keys, from OF's JS; the captured
# entity in app/lib/__fixtures__/of/queue-saved-post-item.json has none of the three); overturned by ticket 53's Live
# read, which then names the fields.
# ASSUMPTION: the Proof Creator has at least one label of its own (rung 5: two in new-post-labels.json, read
# 2026-10-17); overturned by a Live run whose labels dialog shows no row, which then needs a label made first.

from proof_core import NEVER_TITLED, NEVER_TITLED_SEP  # noqa: E402

EXTRAS_DAYS, EXTRAS_TARGET = 7, 25
_EXTRAS_SUMMARY = "#oi-post-summary"   # the composer's "Scheduled for … · Expires after … · Target: … · Labels: …"
_EXTRAS_SAVE = ".modal.show .modal-footer button[data-oi-wired]"   # the value dialogs' Save, once bound
_EXTRAS_TAB = ".modal.show .b-tabs__nav__link[data-oi-wired]"   # EXPIRATION PERIOD's No limit … 30 days tabs
_EXTRAS_FIELD = ".modal.show input[at-attr='input'][data-oi-wired]"   # the target's field
_EXTRAS_ROW = "label.b-rows-lists__item[data-oi-label]"   # a labels dialog row (one per Relay label)
_EXTRAS_NEXT = ".vdatetime-popup__actions__button--confirm button"
# the three controls' sweep labels (their aria-labels on new-post/index.html), each checked absent from `ny`
_EXTRAS_LABELS = ("Add labels", "Expiration period", "Your target")


def _extras_days(post):
    """The post's expiry in whole days (`expiredAt` - `postedAt`), None when it has none."""
    try:
        gap = datetime.fromisoformat(str(post["expiredAt"])) - datetime.fromisoformat(str(post["postedAt"]))
    except (KeyError, TypeError, ValueError):
        return None
    return round(gap.total_seconds() / 86400)


def _extras_target(post):
    target = (post.get("fundRaising") or {}).get("target") if isinstance(post.get("fundRaising"), dict) else None
    try:
        return float(target) if target is not None else None
    except (TypeError, ValueError):
        return None


def _extras_labels_of(post):
    """A post's label ids, sorted (`labelStates` items `{id, isAdded}`, or bare ids; an `isAdded: false` one is not)."""
    states = [s if isinstance(s, dict) else {"id": s} for s in post.get("labelStates") or []]
    return sorted(str(s["id"]) for s in states if s.get("id") is not None and s.get("isAdded") is not False)


def read_post_extras(get, fan):
    """The Creator's own labels as [id, name] in OF's order (`GET /labels`, the list the labels dialog shows), and every
    dated scheduled post as [id, text, its label ids sorted, expiry days, target] (`GET /schedules` over
    SCHEDULE_WINDOW, `scheduled_post_items`), sorted."""
    page = get("/api2/v2/labels", {})
    items = (page.get("list") if isinstance(page, dict) else page) or []
    labels = [[str(x["id"]), str(x.get("name") or "")] for x in items
              if isinstance(x, dict) and str(x.get("id", "")).isdigit()]
    posts = [[str(x["id"]), str(x.get("rawText") or x.get("text") or ""), _extras_labels_of(x), _extras_days(x),
              _extras_target(x)] for x in scheduled_post_items(get)]
    return {"labels": labels, "posts": sorted(posts)}


def _new_extras_posts(before, after):
    old = {str(r[0]) for r in before["posts"]}
    return [r for r in after["posts"] if str(r[0]) not in old]


def post_extras_held(before, after):
    """The declared effect: exactly one scheduled post more, its text the marker, read back with the first label of the
    Creator's own (the dialog's first row), EXTRAS_DAYS days and an EXTRAS_TARGET target; a dropped field fails."""
    new = _new_extras_posts(before, after)
    if len(new) != 1 or not after["labels"]:
        return False
    _, text, ids, days, target = new[0]
    return MARKER in text and list(ids) == [after["labels"][0][0]] and days == EXTRAS_DAYS and target == EXTRAS_TARGET


PROOFS += (
    Proof(id="p2.post-labels-expiry-target", phase=2, page="new-post/index", control=NEVER_TITLED_SEP.join(_EXTRAS_LABELS),
          kind="live", tags=frozenset({"post", NEVER_TITLED}),
          arm=(Write("POST", "/api2/v2/posts"),),
          trigger=(("click", "a[aria-label='Expiration period']"),
                   ("frame", "new-post/state-expiration"),
                   ("text", _EXTRAS_TAB, "No limit"),
                   ("click", f"{_EXTRAS_TAB}:has-text('{EXTRAS_DAYS} days')"),
                   ("click", _EXTRAS_SAVE),
                   ("frame", "new-post/index"),
                   ("text", _EXTRAS_SUMMARY, f"Expires after {EXTRAS_DAYS} days"),
                   ("click", "a[aria-label='Your target']"),
                   ("frame", "new-post/state-target"),
                   ("fill", _EXTRAS_FIELD, str(EXTRAS_TARGET)),
                   ("click", _EXTRAS_SAVE),
                   ("frame", "new-post/index"),
                   ("text", _EXTRAS_SUMMARY, f"Target: ${EXTRAS_TARGET}"),
                   ("click", "a[aria-label='Add labels']"),
                   ("frame", "new-post/state-labels"),
                   ("text", _EXTRAS_ROW, " posts"),   # the Relay's labels drew
                   ("click", _EXTRAS_ROW),
                   ("click", ".modal.show .modal-footer a[href='/of-manager/new-post']"),   # Close
                   ("frame", "new-post/index"),
                   ("text", _EXTRAS_SUMMARY, "Labels: "),
                   ("click", "a[at-attr='scheduled_msg']"),
                   ("frame", "new-post/state-schedule"),
                   ("text", f"{_EXTRAS_NEXT}[data-oi-wired]", "Next"),
                   ("click", ".vdatetime-calendar__navigation--next"),
                   ("click", ".vdatetime-calendar__month__day:not(.vdatetime-calendar__month__day--disabled)"),
                   ("click", _EXTRAS_NEXT),
                   ("frame", "new-post/index"),
                   ("text", _EXTRAS_SUMMARY, "Scheduled for"),
                   ("fill", POST_EDITOR, "{marker}"),
                   ("click", "button[at-attr='submit_post']")),
          settled=("text", "#oi-toast", "Your post is scheduled for"),
          of_read=read_post_extras, effect=post_extras_held,
          undo=(Write("DELETE", "/api2/v2/posts/{id}", relay="/api/of/v2/posts/{id}"),),
          find=lambda before, after, marker: find_marked_post(before["posts"], after["posts"], marker)),
)

# ticket 33: Infloww's own bubble extras on the chat page (ofMirrorBubbleExtras bubbleExtras): the unsend Countdown and
# Copy as draft write nothing on OnlyFans (mocked: their Mirror check rows, content_writes.py); Unsend PPV is a live
# definition on one PPV to the Proof fan, parked until the owner names the Proof fan (ticket 54). It sends the PPV through
# the chat's own composer (price dialog, Send's confirm), checks the bubble's Countdown, copies it as a draft (the
# composer's line shows its price), then Unsend PPV, confirmed: the UI's DELETE /messages/{id} is the send's declared
# undo (class 8; undo_driver `trigger_reversal` takes it as the record when answered 2xx, so the run sends no
# second one; answered otherwise, the driver sends its own while the read still shows the PPV: the undo's max 2).
# The PPV's text is the run's marker; delete-at-once forces the undo within the minute whatever step the proof is on.
# The PPV carries the first tile of the chat's own vault dialog (Add media from vault, Add): OnlyFans answers a priced
# message with no media and no locked text 400 "You have no paid content. Please add some paid media or text." (measured
# on the Live run, 11-22; FakeOF now answers the same). The tile is an existing vault item, sent to the Proof fan locked
# behind the $3 price until the unsend. The guard holds the send to that payload (ppv_payload).
# All three keep the Not-yet title until a Live pass (D1): the mocked ones never drop it. All three are behind
# OFM_NEW_WRITES_ENABLED (UI-only, ofMirrorNewWrites): off, none is drawn (main); phase_check's switch-off pass pins it.
# The controls are drawn from the thread's data only (an own bubble): the sweep (dead.py, the proof list's --check-sweep)
# opens messages/chat on its synthetic chat with my own PPV (dead.py SWEEP_QUERY, dead_messages.py), and content_writes.py's
# check 1 opens the chat with its synthetic thread (phase_check VIEWS).
_THREAD = "/api2/v2/chats/{fan}/messages"   # the Proof fan's send (the arm keeps {fan})
_OWN = ".b-chat__message.m-from-me"
_MINE = f"{_OWN}:has-text('{MARKER}')"   # the run's PPV bubble (a Playwright locator)
_TILE = ".modal.show .b-photos__item.m-checkbox-control"   # the chat vault dialog's tile (ofMirrorChatShared VAULT_TILE)


def read_marked_messages(get, fan) -> dict:
    """The Proof fan's latest messages carrying the marker, as {"marked": [(id, text, price)], sorted, "_page":
    {"newest", "oldest", "more"}}: OnlyFans's `GET /chats/{fan}/messages` (`{list, hasMore}`, service/of_reads.py),
    read as proof_core.read_id_query's (one page). W30 W2: "_page" keeps what the page covers (its newest and oldest
    message ids, None when unreadable; `more`: OF's hasMore), so a message pushed past it is never read as gone
    (`_covers`). A `_` key is the read's bookkeeping: undo_driver.still_shown never takes it for an item (W30 S3)."""
    page = get(*read_id_query("message", None, fan)) or {}
    msgs = [m for m in page.get("list") or [] if isinstance(m, dict) and "id" in m]
    ids = [int(m["id"]) for m in msgs if str(m["id"]).isdigit()]
    return {"marked": sorted((str(m["id"]), str(m.get("text") or ""), m.get("price") or 0) for m in msgs
                             if MARKER in str(m.get("text") or "")),
            "_page": {"newest": max(ids) if ids else None,
                      "oldest": min(ids) if ids and len(ids) == len(msgs) else None,
                      "more": bool(page.get("hasMore"))}}


def _marked(read) -> list:
    return [tuple(r) for r in (read or {}).get("marked") or []] if isinstance(read, dict) else []


def _covers(before, later) -> bool:
    """W30 W2: whether `later`'s page reaches back to `before`'s newest message, so every message since `before` (the
    PPV) was read: `later` saw the whole thread, or its oldest id is at or below `before`'s newest. Unreadable: no."""
    was, now = ((r.get("_page") if isinstance(r, dict) else None) for r in (before, later))
    if not (isinstance(was, dict) and isinstance(now, dict)):
        return False
    if not now.get("more"):
        return True
    oldest, newest = now.get("oldest"), was.get("newest")
    return isinstance(oldest, int) and isinstance(newest, int) and oldest <= newest   # an empty `before` + more: unknown


PPV_PRICE = 3   # the PPV's declared price, dollars


def ppv_payload(body, run, at=None) -> str | None:
    """p2.bubble-unsend-ppv's declared payload (Write.payload, the guard's class 4): the run's marker in the text,
    priced exactly PPV_PRICE, one medium (locked behind the price), no free preview; else why not (`at` unused)."""
    if not isinstance(body, dict):
        return f"the send body is not a JSON object: {str(body)[:80]}"
    if why := marker_problem(body.get("text"), run):   # this run's exact marker (round 2 #22)
        return f"the send: {why}"
    price = body.get("price")
    try:
        priced = not isinstance(price, bool) and float(price) == PPV_PRICE
    except (TypeError, ValueError):
        priced = False
    if not priced:
        return f"the send's price is {str(price)[:20]}, not the declared {PPV_PRICE}"
    media = body.get("mediaFiles")
    if not isinstance(media, list) or len(media) != 1:
        return f"the send carries mediaFiles {str(media)[:80]}, not one locked medium"
    if body.get("previews"):
        return f"the send carries free previews {str(body['previews'])[:80]}"
    return None


def ppv_gone(before, after):
    """p2.bubble-unsend-ppv's effect: the marked messages read as before, none left (an unsend FakeOF refused fails),
    on a page that reaches back past `before` (W30 W2: a PPV pushed off the page is unknown, never gone)."""
    return not _marked(before) and not _marked(after) and _covers(before, after)


def ppv_same(before, after_undo) -> bool:
    """p2.bubble-unsend-ppv's after-undo check (Proof.same): the marked messages as before, on a page that reaches back
    past `before` (W30 W2: unknown closes the row FAILED, never `undone`)."""
    return _marked(before) == _marked(after_undo) and _covers(before, after_undo)


def find_marked_ppv(before, after, marker):
    """A lost reply's finder (story 53): the one priced message new since `before` whose text holds `marker`."""
    new = [r for r in set(_marked(after)) - set(_marked(before)) if marker in r[1] and r[2]]
    return new[0][0] if len(new) == 1 else None


PROOFS += (
    Proof(id="p2.bubble-countdown", phase=2, page="messages/chat", control="Countdown", kind="mocked", tags=frozenset({OFM_NEW_WRITES})),
    Proof(id="p2.bubble-copy-draft", phase=2, page="messages/chat", control="Copy as draft", kind="mocked", tags=frozenset({OFM_NEW_WRITES})),
    Proof(id="p2.bubble-unsend-ppv", phase=2, page="messages/chat", control="Unsend PPV", kind="live",
          tags=frozenset({"message", "delete_at_once", OFM_NEW_WRITES}),
          arm=(Write("POST", _THREAD, payload=ppv_payload),),
          trigger=(("text", "button[at-attr='send_btn']", ""),   # the bare chat page drew; then the Proof fan's chat
                   ("goto", "messages/chat?chat={fan}"),
                   ("click", "[at-attr='add_vault_media']"),   # OF refuses a priced text-only send: one vault item
                   ("frame", "messages/chat/state-vault"),
                   ("click", f"{_TILE}[data-oi-media][data-oi-wired]"),   # the first real tile, whatever it is
                   ("click", "[data-oi-vault-add]"),
                   ("frame", "messages/chat"),
                   ("text", "#oi-chat-summary", "1 media"),
                   ("fill", POST_EDITOR, "{marker}"),
                   ("click", "a[at-attr='price_btn']"),
                   ("frame", "messages/chat/state-price"),
                   ("fill", ".modal.show input[at-attr='input'][data-oi-wired]", str(PPV_PRICE)),
                   ("click", ".modal.show .modal-footer button"),
                   ("frame", "messages/chat"),
                   ("text", "#oi-chat-summary", f"Price: ${PPV_PRICE}"),
                   ("accept", "button[at-attr='send_btn']", "Send this message to"),
                   ("text", f"{_OWN} [data-oi-bubble='countdown']", ":"),
                   ("click", f"{_MINE} button[data-oi-bubble='copy-draft']"),
                   ("text", POST_EDITOR, MARKER),   # Send emptied the composer; the copy filled it again
                   ("text", "#oi-chat-summary", f"Price: ${PPV_PRICE}"),
                   ("click", f"{_MINE} button[data-oi-bubble='unsend-ppv']"),
                   ("click", "#oi-msg-confirm .modal-footer button:has-text('Unsend')")),
          settled=("text", "#oi-note", "Unsent"),
          of_read=read_marked_messages, effect=ppv_gone,
          same=ppv_same,
          # max 2: the UI's Unsend, then the driver's own when that one was not answered 2xx (follow-up #6)
          undo=(Write("DELETE", "/api2/v2/messages/{id}", max=2, relay="/api/of/v2/messages/{id}"),),
          find=find_marked_ppv),
)

if __name__ == "__main__":
    import proof_list
    sys.exit(proof_list.main(PROOFS, sys.argv[1:], prog="phase2.py"))
