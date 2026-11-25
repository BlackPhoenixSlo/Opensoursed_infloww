import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from proof_core import OFM_NEW_WRITES, Proof, Write, marker_problem, read_id_query  # noqa: E402,F401

PROOFS = ()

MESSAGES_MORE_PAGES = ("messages/index", "messages/state-filter-dropdown", "messages/state-folders", "messages/chat",
                       "messages/chat/gallery", "messages/chat/pinned", "messages/chat/state-header-menu",
                       "messages/chat/state-price", "messages/chat/state-schedule", "messages/chat/state-tag-people",
                       "messages/chat/state-vault")
PROOFS += tuple(Proof(id=f"messages.more.{p.removeprefix('messages/').replace('/', '.')}", phase=2, page=p,
                      control="More", kind="mocked") for p in MESSAGES_MORE_PAGES)
MARKER = "oi-proof-"
POST_EDITOR = "[contenteditable][aria-label='Textbox field']"
RECORD_BUTTON = {"Record video": ".b-chat__video-message__preview .vjs-record-button",
                 "Record voice": ".js-chat__audiorecord-panel .b-float-panel__btn-record"}
UPLOAD, POST = (0, 1, 2), 3
S3_HOST = "of2transcoder.s3-accelerate.amazonaws.com"
UPLOAD_ARMS = (Write("POST", "/api2/v2/upload/signed/create"),
               Write("PUT", "/upload/{creator}/{key}/{part}/{file}", host=S3_HOST),
               Write("POST", "/file/upload"))
UPLOAD_WAIT = 15


# OF lists dated scheduled posts only in GET /schedules (not /schedules/later/post) and ignores limit/offset there.
SCHEDULE_WINDOW = (-1, 45)
SCHEDULE_TZ = "UTC"


def scheduled_post_items(get, today=None):
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
    return sorted((str(x["id"]), str(x.get("rawText") or x.get("text") or ""),
                   tuple(sorted(str(m["id"]) for m in x.get("media") or [] if isinstance(m, dict) and m.get("id") is not None)))
                  for x in scheduled_post_items(get))


def _new(before, after):
    key = lambda r: (r[0], r[1], tuple(r[2]))  # noqa: E731
    return set(map(key, after)) - set(map(key, before))


def one_new_marked_post_with_media(before, after):
    new = _new(before, after)
    return len(new) == 1 and MARKER in next(iter(new))[1] and len(next(iter(new))[2]) == 1


def find_marked_post(before, after, marker):
    new = [r for r in _new(before, after) if marker in r[1]]
    return new[0][0] if len(new) == 1 else None


def vault_media(before, after):
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

_VAULT_LISTS = "/api2/v2/vault/lists"
_FOLDER_TITLE = ".l-main-content.m-r-side .g-page-title > span"
_OPEN_ROW = ".b-rows-lists__item a[aria-current='page'] .b-rows-lists__item__name"
_RENAMED = " renamed"


def read_folders(get, fan):
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
    return set(map(tuple, after)) - set(map(tuple, before))


def renamed_folder(before, after):
    new = _new_folders(before, after)
    return len(new) == 1 and next(iter(new))[1].startswith(MARKER) and next(iter(new))[1].endswith(_RENAMED)


def folder_gone(before, after):
    return list(map(tuple, after)) == list(map(tuple, before)) and not any(n.startswith(MARKER) for _, n in after)


def find_marked_folder(before, after, marker):
    new = [r for r in _new_folders(before, after) if r[1].startswith(marker)]
    return new[0][0] if len(new) == 1 else None


_CREATE = Write("POST", _VAULT_LISTS)
_DELETE = Write("DELETE", _VAULT_LISTS + "/{id}", relay="/admin/vault-ai/of-folders/{id}?account_id={account}")
_MORE = ".l-main-content.m-r-side [at-attr='list_dropdown'] > button"
_NAME, _SAVE = ".modal input[at-attr='input'][data-oi-wired]", ".modal-footer button[type='submit']"
_CREATE_STEPS = (("click", "a[aria-label='Create new category']"),
                 ("frame", "vault/state-add-list"),
                 ("fill", _NAME, "{marker}"),
                 ("click", _SAVE),
                 ("frame", "vault/index"),
                 ("goto", "vault/list?list={id}"),
                 ("text", _FOLDER_TITLE, MARKER))
PROOFS += (
    Proof(id="vault.more.rename", phase=2, page="vault/list", control="More", kind="live", tags=frozenset({OFM_NEW_WRITES}),
          arm=(_CREATE, Write("PATCH", _VAULT_LISTS + "/{created}")),
          trigger=(*_CREATE_STEPS,
                   ("click", _MORE),
                   ("click", "#oi-menu [data-oi-value='rename']"),
                   ("frame", "vault/state-add-list"),
                   ("text", ".modal-title", "Rename category"),
                   ("fill", _NAME, "{marker}" + _RENAMED),
                   ("click", _SAVE)),
          settled=("text", _OPEN_ROW, _RENAMED.strip(), "vault/index"),
          of_read=read_folders, effect=renamed_folder, undo=(_DELETE,), find=find_marked_folder),
    Proof(id="vault.more.delete", phase=2, page="vault/list", control="More", kind="live", tags=frozenset({OFM_NEW_WRITES}),
          arm=(_CREATE,),
          trigger=(*_CREATE_STEPS,
                   ("click", _MORE),
                   ("accept", "#oi-menu [data-oi-value='delete']", 'Delete the folder "')),
          settled=("text", _FOLDER_TITLE, "All media", "vault/index"),
          of_read=read_folders, effect=folder_gone, undo=(_DELETE,), find=find_marked_folder),
)
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


from proof_core import NEVER_TITLED, NEVER_TITLED_SEP  # noqa: E402

EXTRAS_DAYS, EXTRAS_TARGET = 7, 25
_EXTRAS_SUMMARY = "#oi-post-summary"
_EXTRAS_SAVE = ".modal.show .modal-footer button[data-oi-wired]"
_EXTRAS_TAB = ".modal.show .b-tabs__nav__link[data-oi-wired]"
_EXTRAS_FIELD = ".modal.show input[at-attr='input'][data-oi-wired]"
_EXTRAS_ROW = "label.b-rows-lists__item[data-oi-label]"
_EXTRAS_NEXT = ".vdatetime-popup__actions__button--confirm button"
_EXTRAS_LABELS = ("Add labels", "Expiration period", "Your target")


def _extras_days(post):
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
    states = [s if isinstance(s, dict) else {"id": s} for s in post.get("labelStates") or []]
    return sorted(str(s["id"]) for s in states if s.get("id") is not None and s.get("isAdded") is not False)


def read_post_extras(get, fan):
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
                   ("text", _EXTRAS_ROW, " posts"),
                   ("click", _EXTRAS_ROW),
                   ("click", ".modal.show .modal-footer a[href='/of-manager/new-post']"),
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

_THREAD = "/api2/v2/chats/{fan}/messages"
_OWN = ".b-chat__message.m-from-me"
_MINE = f"{_OWN}:has-text('{MARKER}')"
_TILE = ".modal.show .b-photos__item.m-checkbox-control"


def read_marked_messages(get, fan) -> dict:
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
    was, now = ((r.get("_page") if isinstance(r, dict) else None) for r in (before, later))
    if not (isinstance(was, dict) and isinstance(now, dict)):
        return False
    if not now.get("more"):
        return True
    oldest, newest = now.get("oldest"), was.get("newest")
    return isinstance(oldest, int) and isinstance(newest, int) and oldest <= newest


PPV_PRICE = 3


def ppv_payload(body, run, at=None) -> str | None:
    if not isinstance(body, dict):
        return f"the send body is not a JSON object: {str(body)[:80]}"
    if why := marker_problem(body.get("text"), run):
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
    return not _marked(before) and not _marked(after) and _covers(before, after)


def ppv_same(before, after_undo) -> bool:
    return _marked(before) == _marked(after_undo) and _covers(before, after_undo)


def find_marked_ppv(before, after, marker):
    new = [r for r in set(_marked(after)) - set(_marked(before)) if marker in r[1] and r[2]]
    return new[0][0] if len(new) == 1 else None


PROOFS += (
    Proof(id="p2.bubble-countdown", phase=2, page="messages/chat", control="Countdown", kind="mocked", tags=frozenset({OFM_NEW_WRITES})),
    Proof(id="p2.bubble-copy-draft", phase=2, page="messages/chat", control="Copy as draft", kind="mocked", tags=frozenset({OFM_NEW_WRITES})),
    Proof(id="p2.bubble-unsend-ppv", phase=2, page="messages/chat", control="Unsend PPV", kind="live",
          tags=frozenset({"message", "delete_at_once", OFM_NEW_WRITES}),
          arm=(Write("POST", _THREAD, payload=ppv_payload),),
          trigger=(("text", "button[at-attr='send_btn']", ""),
                   ("goto", "messages/chat?chat={fan}"),
                   ("click", "[at-attr='add_vault_media']"),
                   ("frame", "messages/chat/state-vault"),
                   ("click", f"{_TILE}[data-oi-media][data-oi-wired]"),
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
                   ("text", POST_EDITOR, MARKER),
                   ("text", "#oi-chat-summary", f"Price: ${PPV_PRICE}"),
                   ("click", f"{_MINE} button[data-oi-bubble='unsend-ppv']"),
                   ("click", "#oi-msg-confirm .modal-footer button:has-text('Unsend')")),
          settled=("text", "#oi-note", "Unsent"),
          of_read=read_marked_messages, effect=ppv_gone,
          same=ppv_same,
          undo=(Write("DELETE", "/api2/v2/messages/{id}", max=2, relay="/api/of/v2/messages/{id}"),),
          find=find_marked_ppv),
)

if __name__ == "__main__":
    import proof_list
    sys.exit(proof_list.main(PROOFS, sys.argv[1:], prog="phase2.py"))
