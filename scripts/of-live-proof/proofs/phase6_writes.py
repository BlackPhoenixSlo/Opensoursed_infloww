from __future__ import annotations

import hashlib
import json
import re
import struct
import zlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import proof_core
from proof_core import Proof, Write
from proofs.phase2 import UPLOAD_ARMS
from proofs.phase6_reads import _read


SORT_PATH = "/api2/v2/vault/lists/sort"
SORT_ROUTE = "/admin/vault-ai/of-folders/sort"
FOLDER_SORTS = ("name", "recent", "media", "custom", "default")
FOLDER_ORDERS = ("asc", "desc")
ORDER_ROW = "#oi-custom-order [data-oi-order]"
FOLDER_LINK = ".b-rows-lists__item a[href*='?list=']"


def _dom_values(seen) -> dict:
    return {d.get("items_selector"): [i.get("value") for i in d.get("items") or []] for d in seen.get("dom") or []}


def read_folder_order(get, fan) -> dict:
    ids, sort, order, off = [], None, None, 0
    while True:
        page = get("/api2/v2/vault/lists", {"view": "main", "limit": 50, "offset": off})
        if off == 0:
            sort, order = page.get("sort"), page.get("order")
        items = [x for x in page.get("list") or [] if isinstance(x, dict) and "id" in x]
        ids += [str(x["id"]) for x in items]
        if not page.get("hasMore") or not items:
            return {"sort": sort, "order": order, "ids": ids}
        off += len(items)


def order_unrecoverable(before) -> str | None:
    why = "pre-proof order not recoverable: "
    if not isinstance(before, dict):
        return why + "no folder read"
    if before.get("sort") not in FOLDER_SORTS or before.get("order") not in FOLDER_ORDERS:
        return why + f"the read carries no known sort and order ({before.get('sort')!r}, {before.get('order')!r})"
    if before["sort"] != "custom":
        return why + f"sort is {before['sort']!r}, so the stored custom order is not in the read"
    ids = before.get("ids") or []
    if len(ids) < 2 or len(set(ids)) != len(ids) or not all(str(i).isdigit() for i in ids):
        return why + f"the folder ids cannot be sent back as a custom order ({len(ids)} ids)"
    return None


def order_changed(before, after) -> bool:
    return (isinstance(after, dict) and after.get("sort") == "custom" and sorted(after.get("ids") or []) ==
            sorted(before.get("ids") or []) and after.get("ids") != before.get("ids"))


def restore_steps(before) -> list:
    out = []
    if before.get("sort") == "custom":
        out.append((0, {"account_id": "{account}", "custom_order": [int(i) for i in before["ids"]]},
                    lambda fresh: fresh.get("sort") == "custom" and fresh.get("ids") == before["ids"]))
    out.append((0, {"account_id": "{account}", "sort": before["sort"], "order": before["order"]},
                lambda fresh: fresh == before))
    return out


def customize_order_check(seen) -> dict:
    return {"problems": _order_problems(seen), "parked": None, "record": {}}


def _order_problems(seen) -> list:
    out = []
    saved = [e.get("body") for e in seen.get("wire") or []
             if e.get("verdict") == "allow" and e.get("method") == "POST" and e.get("path") == SORT_PATH]
    if len(saved) != 1:
        return [f"{len(saved)} allowed POST {SORT_PATH} in the window, want 1 (the Save)"]
    body = saved[0]
    if not (isinstance(body, dict) and set(body) == {"customOrder", "sort"} and body["sort"] == "custom"
            and isinstance(body["customOrder"], list) and all(isinstance(i, int) for i in body["customOrder"])):
        return [f"the Save's body is not {{customOrder: [ints], sort: 'custom'}}: {json.dumps(body)[:300]}"]
    want = [str(i) for i in body["customOrder"]]
    dom = _dom_values(seen)
    shown = dom.get(ORDER_ROW)
    if shown is None:
        out.append("no Customize order rows recorded before the drag")
    elif sorted(shown) != sorted(want):
        out.append(f"the Save sent other folders than Customize order showed ({shown} vs {want})")
    elif shown == want:
        out.append("the Save sent the order shown before the drag: the drag changed nothing")
    links = dom.get(FOLDER_LINK)
    if links is None:
        out.append("no folder rows recorded after the reload")
    else:
        got = [q for h in links for q in [urlsplit(h or "").query] if q]
        got = [p.split("=", 1)[1] for q in got for p in q.split("&") if p.startswith("list=")]
        got = [i for i in dict.fromkeys(got) if i in want]
        if got != want:
            out.append(f"after the reload the folders are not in the saved order ({got} vs {want})")
    return out


VAULT_CUSTOMIZE_ORDER = Proof(
    id="vault--customize-order-save", phase=6, page="vault/state-lists-sort-dropdown",
    control="Customize order Save", kind="live",
    arm=(Write("POST", SORT_PATH),),
    narrowing="the Proof Creator's own folder order only (no Fan sees it); restored to the pre-proof order",
    trigger=(("click", ".of-state-menu .v-list-item:has-text('Customize order')"),
             ("frame", "vault/index"),
             ("dom", "#oi-custom-order", ORDER_ROW, (("value", "@data-oi-order"),)),
             ("drag", f"{ORDER_ROW}:last-child [data-oi-drag]", f":nth-match({ORDER_ROW}, 1)"),
             ("click", "button[aria-label='Save order']"),
             ("gone", "#oi-custom-order"),
             ("goto", "vault/index"),
             ("dom", FOLDER_LINK, FOLDER_LINK, (("value", "@href"),))),
    of_read=read_folder_order,
    effect=order_changed,
    undo=(Write("POST", SORT_PATH, max=2, relay=SORT_ROUTE),),
    undo_steps=restore_steps,
    check=customize_order_check,
    precheck=order_unrecoverable,
)



MARKER = "oi-proof-"
QUEUE_PAGE = "queue/state-tab-messages"
QUEUE_LEAD = proof_core.POST_LEAD + timedelta(minutes=5)  # the guard refuses a queue write under POST_LEAD ahead
QUEUE_ROW = "[data-oi-queue-target='{qid}']"
QUEUE_MORE = "[at-attr='more_menu']"
SEND_NOW = "#oi-queue-menu [at-attr='message_now']"


def _json(raw) -> dict:
    try:
        v = json.loads(raw or b"null")
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


def queue_when(now: datetime) -> datetime | None:
    when = now + QUEUE_LEAD
    return when if when.date() == now.date() else None


def schedules(get, now: datetime) -> list:
    return get(*proof_core.read_id_query("schedule", None, None, now)).get("list") or []


def _thread(get, fan) -> list:
    return get(*proof_core.read_id_query("message", None, fan)).get("list") or []


def read_fan_and_queue(get, fan):
    return {"chat": [[str(m["id"]), str(m.get("text") or ""), str(m["queueId"]) if m.get("queueId") else None]
                     for m in (_thread(get, fan) if fan else [])],
            "queue": sorted([str(i["id"]), str((i.get("entity") or {}).get("id"))]
                            for i in schedules(get, datetime.now(timezone.utc)) if i.get("type") == "chat")}


def _new(before, after, key) -> list:
    had = {tuple(x) for x in (before or {}).get(key) or []}
    return [x for x in (after or {}).get(key) or [] if tuple(x) not in had]


def queue_send_effect(before, after) -> bool:
    return any(MARKER in m[1] for m in _new(before, after, "chat")) or bool(_new(before, after, "queue"))


def find_queued(before, after, marker):
    sent = [m for m in _new(before, after, "chat") if marker in m[1] and m[2]]
    if len(sent) == 1:
        return sent[0][2]
    queued = _new(before, after, "queue")
    return queued[0][1] if len(queued) == 1 else None


def released_message(after, of_id, fan):
    mine = [m[0] for m in (after or {}).get("chat") or [] if m[2] == str(of_id)]
    return {"message": mine[0] if len(mine) == 1 else None}


def audience_problem(audience, fan) -> str | None:
    if audience.get("userLists"):
        return f"the queued item's audience has lists {audience['userLists']}"
    if [str(u) for u in audience.get("userIds") or []] != [str(fan)]:
        return f"the queued item's audience is {audience.get('userIds')}, not the Proof fan {fan} alone"
    return None


def send_now(ctx) -> list:
    rec, fan, call, marker, of_get = ctx["record"], str(ctx["proof_fan"]), ctx["call"], ctx["marker"], ctx["of_get"]
    now = datetime.now(timezone.utc)
    when = queue_when(now)
    if when is None:
        ctx["park"](f"queueing {QUEUE_LEAD} ahead crosses UTC midnight (the queue row would be on tomorrow's page)")
    status, raw = call("POST", "/api/of/v2/messages/queue", {"text": marker, "scheduled_date": when.isoformat(),
                                                             "user_ids": [int(fan)], "user_lists": [], "price": 0})
    qid = str(_json(raw).get("id") or "")
    rec["queued"] = {"status": status, "id": qid, "scheduled_date": when.isoformat()}
    if status >= 300 or not qid:
        return [f"queueing the message answered {status}: {raw[:200]!r}"]
    got = _read(of_get, f"/api2/v2/messages/queue/{qid}", {"format": "scheduled"})
    item = got["body"] if isinstance(got["body"], dict) else {}
    rec["audience"] = audience = {"userIds": item.get("userIds"), "userLists": item.get("userLists") or []}
    if got["status"] != 200 or not item:
        return [f"the queued item's read answered {got['status']}: Send now not clicked"]
    if why := audience_problem(audience, fan):
        return [f"{why}: Send now not clicked (audience {json.dumps(audience)})"]
    sid = next((str(i["id"]) for i in schedules(of_get, now)
                if str((i.get("entity") or {}).get("id")) == qid and i.get("id") is not None), None)
    rec["schedule"] = sid
    if sid is None:
        return [f"no schedule item for queued message {qid} in GET /schedules: Send now not clicked"]
    if bad := ctx["read_id"]("schedule", sid, qid):
        return bad
    fr = ctx["reload"]()
    row = fr.locator(QUEUE_ROW.format(qid=qid)).first
    row.wait_for(state="visible", timeout=60_000)
    rec["row_schedule"] = shown = row.get_attribute("data-oi-queue-schedule")
    if shown != sid:
        return [f"the queue row of {qid} carries schedule {shown!r}, not its item's {sid}: Send now not clicked"]
    row.locator(QUEUE_MORE).first.click(timeout=30_000)
    button = fr.locator(SEND_NOW).first
    button.wait_for(state="visible", timeout=30_000)
    ctx["shot"]("menu")
    page = ctx["page"]
    page.once("dialog", lambda d: d.accept())
    with page.expect_response(lambda r: r.request.method == "PUT" and urlsplit(r.url).path.startswith(
            "/api/of/v2/schedules/") and urlsplit(r.url).path.endswith("/publish"), timeout=60_000) as got:
        button.click(timeout=30_000)
    published = urlsplit(got.value.url).path.split("/")[-2]
    rec["published"] = {"schedule": published, "status": got.value.status}
    out = []
    if published != sid:
        out.append(f"Send now published schedule {published}, not the queued item's {sid}")
    if not 200 <= got.value.status < 300:
        return out + [f"Send now answered {got.value.status}"]
    for _ in range(60):
        m = next((m for m in _thread(ctx["of_get"], fan) if marker in str(m.get("text") or "")), None)
        if m is not None:
            rec["delivered"] = {"message": str(m["id"]), "queueId": m.get("queueId")}
            if str(m.get("queueId")) != qid:
                out.append(f"the delivered message {m['id']} carries queueId {m.get('queueId')}, not {qid}")
            return out
        page.wait_for_timeout(500)
    return out + ["the message never reached the Proof fan's chat"]


QUEUE_SEND_NOW = Proof(
    id="queue--send-message-right-now", phase=6, page=QUEUE_PAGE, control="Send message right now", kind="live",
    tags=frozenset({"message", "delete_at_once"}),
    arm=(Write("POST", "/api2/v2/messages/queue"), Write("PUT", "/api2/v2/schedules/{id}/publish")),
    trigger=(("call", send_now),),
    of_read=read_fan_and_queue,
    effect=queue_send_effect,
    undo=(Write("DELETE", "/api2/v2/messages/queue/{id}", relay="/api/of/v2/messages/queue/{id}"),
          Write("DELETE", "/api2/v2/messages/{message}", relay="/api/of/v2/messages/{message}",
                relay_body={"withUserId": "{fan}"})),
    find=find_queued,
    undo_ids=released_message,
    binds=frozenset({"schedule", "message"}),
)



POST_SCHEDULE_LEAD = proof_core.POST_LEAD + timedelta(minutes=15)
POSTS_PATH = "/api2/v2/posts"
PICK = "body > input[type=file][data-oi-wired][accept='image/*,video/*,audio/*']"
POST_BUTTON = "button[at-attr='submit_post']"
SCHEDULED_TOAST = "Your post is scheduled for"
UPLOAD_SUFFIX, DEDUPE_SUFFIX = "upload", "dedupe"


def read_posts_and_vault(get, fan) -> dict:
    queue = []
    for i in schedules(get, datetime.now(timezone.utc)):
        if i.get("type") != "post":
            continue
        pid = (i.get("entity") or {}).get("id")
        post = get(f"/api2/v2/posts/{pid}", {})
        text = str(post.get("rawText") or post.get("text") or "")
        queue.append([i["id"], pid, text, *[m["id"] for m in post.get("media") or []]])
    vault = get("/api2/v2/vault/media", {"limit": 100}).get("list") or []
    return {"queue": sorted(queue), "vault": sorted(m["id"] for m in vault)}


def new_posts(before, after) -> list:
    return [r[1] for r in _new(before, after, "queue")]


def _media(row) -> list:
    return list(row[3:])


def draft_text(marker: str, suffix: str) -> str:
    return f"{marker} {suffix}"


def new_media(before, after) -> list:
    had = set((before or {}).get("vault") or [])
    return [m for m in (after or {}).get("vault") or [] if m not in had]


def upload_effect(before, after) -> bool:
    fresh = set(new_media(before, after))
    return any(fresh & set(_media(r)) for r in _new(before, after, "queue"))


def find_new_post(suffix: str):
    def find(before, after, marker):
        want = draft_text(marker, suffix)
        new = [r[1] for r in _new(before, after, "queue") if r[2] == want]
        return new[0] if len(new) == 1 else None
    return find


def post_media(before, after) -> dict:
    fresh = set(new_media(before, after))
    out = {}
    for r in _new(before, after, "queue"):
        held = set(_media(r))
        if len(held) == 1 and held <= fresh:
            out[str(r[1])] = {"media": _media(r)[0]}
    return out


def proof_png(marker: str, proof_id: str, side: int = 16) -> bytes:
    seed = hashlib.sha256(f"{marker}:{proof_id}".encode()).digest()

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes(seed[(y * side + x) % len(seed)] for x in range(side)) for y in range(side))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", side, side, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _seed_draft(ctx, text: str) -> str:
    at = (datetime.now(timezone.utc) + POST_SCHEDULE_LEAD).replace(microsecond=0).isoformat()
    ctx["page"].evaluate("([text, at]) => { const id = (localStorage.getItem('chatterly:scope') || '')"
                         ".replace(/^model:/, ''); sessionStorage.setItem('oi:new-post:' + id, JSON.stringify("
                         "{text, tagged_users: [], media_files: [], thumbs: [], posted_at: at})); }", [text, at])
    return at


def _draft_media(page) -> list:
    return page.evaluate("() => { const id = (localStorage.getItem('chatterly:scope') || '').replace(/^model:/, ''); "
                         "return (JSON.parse(sessionStorage.getItem('oi:new-post:' + id) || '{}').media_files) || []; }")


def _wait_media(page, n: int) -> None:
    page.wait_for_function("n => { const id = (localStorage.getItem('chatterly:scope') || '').replace(/^model:/, '');"
                           " const d = JSON.parse(sessionStorage.getItem('oi:new-post:' + id) || '{}');"
                           " return (d.media_files || []).length >= n; }", arg=n, polling=100, timeout=60_000)


def _upload(ctx, fr, png: bytes, name: str) -> dict:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    page = ctx["page"]
    for attempt in range(1, 7):
        try:
            with page.expect_request(lambda r: r.method == "POST" and urlsplit(r.url).path == "/api/of/v2/upload",
                                     timeout=15_000) as sent:
                fr.locator(PICK).last.set_input_files({"name": name, "mimeType": "image/png", "buffer": png})
            break
        except PlaywrightTimeout:
            continue
    else:
        raise RuntimeError("Add media sent no upload after 6 picks")
    ctx["record"].setdefault("picks", []).append(attempt)
    got = sent.value.response()
    if got is None:
        return {"status": 0, "body": {}}
    return {"status": got.status, "body": _json(got.body())}


def _post(ctx, fr) -> dict:
    page = ctx["page"]
    fr.wait_for_function(f"() => {{ const b = document.querySelector(\"{POST_BUTTON}\"); return b && !b.disabled; }}",
                         polling=100, timeout=60_000)
    with page.expect_response(lambda r: r.request.method == "POST" and urlsplit(r.url).path == "/api/of/v2/posts",
                              timeout=120_000) as got:
        fr.locator(POST_BUTTON).first.click(timeout=30_000)
    out = {"status": got.value.status, "body": _json(got.value.body())}
    if 200 <= out["status"] < 300:
        fr.get_by_text(SCHEDULED_TOAST).first.wait_for(state="visible", timeout=30_000)
    return out


def upload_post(ctx) -> list:
    rec, marker = ctx["record"], ctx["marker"]
    rec["scheduled_date"] = _seed_draft(ctx, draft_text(marker, UPLOAD_SUFFIX))
    fr = ctx["reload"]()
    before = read_posts_and_vault(ctx["of_get"], None)
    up = _upload(ctx, fr, proof_png(marker, NEW_POST_UPLOAD_ID), "oi-proof-upload.png")
    rec["upload"] = {"status": up["status"], "deduped": up["body"].get("deduped"), "ready": up["body"].get("ready")}
    if up["status"] >= 300 or up["body"].get("ready") is not True:
        return [f"the upload answered {up['status']}: {json.dumps(up['body'])[:200]}"]
    _wait_media(ctx["page"], 1)
    ctx["shot"]("attached")
    sent = _post(ctx, fr)
    rec["post"] = {"status": sent["status"], "id": sent["body"].get("id")}
    if sent["status"] >= 300:
        return [f"Post answered {sent['status']}: {json.dumps(sent['body'])[:200]}"]
    after = read_posts_and_vault(ctx["of_get"], None)
    rec["queue"] = shown = [r for r in _new(before, after, "queue")]
    rec["medium"] = media = new_media(before, after)
    if len(shown) != 1 or len(media) != 1 or _media(shown[0]) != media:
        return [f"the queue does not show one new post holding the one new medium (posts {shown}, new media {media})"]
    return []


def _wire(ctx) -> list:
    status, raw = ctx["call"]("GET", "/__proof/wire")
    return json.loads(raw).get("wire") or [] if status == 200 else []


def dedupe_draft(ctx) -> list:
    ctx["record"]["scheduled_date"] = _seed_draft(ctx, draft_text(ctx["marker"], DEDUPE_SUFFIX))
    return []


def dedupe_first(ctx) -> list:
    rec, marker, page = ctx["record"], ctx["marker"], ctx["page"]
    fr = ctx["frame"]
    before = read_posts_and_vault(ctx["of_get"], None)
    up = _upload(ctx, fr, proof_png(marker, NEW_POST_DEDUPE_ID), "oi-proof-dedupe.png")
    rec["upload_1"] = {"status": up["status"], "deduped": up["body"].get("deduped"), "ready": up["body"].get("ready")}
    if up["status"] >= 300 or up["body"].get("ready") is not True:
        return [f"the first upload answered {up['status']}: {json.dumps(up['body'])[:200]}"]
    _wait_media(page, 1)
    sent = _post(ctx, fr)
    rec["post_1"] = {"status": sent["status"], "id": sent["body"].get("id")}
    if sent["status"] >= 300:
        return [f"the first Post answered {sent['status']}: {json.dumps(sent['body'])[:200]}"]
    media = new_media(before, read_posts_and_vault(ctx["of_get"], None))
    if len(media) != 1:
        return [f"the first post filed {len(media)} new vault items, not one: {media}"]
    rec["x"] = media[0]
    _seed_draft(ctx, draft_text(marker, DEDUPE_SUFFIX))
    status, _ = ctx["call"]("POST", "/admin/vault/cache/invalidate")
    return [] if status == 200 else [f"the vault cache invalidate answered {status}"]


def dedupe_pick(ctx) -> list:
    x = ctx["record"]["x"]
    tile = ctx["frame"].locator(f"[data-oi-media='{x}']").first
    tile.wait_for(state="visible", timeout=60_000)
    tile.click(timeout=30_000)
    _wait_media(ctx["page"], 1)
    ctx["shot"]("picked")
    got = _draft_media(ctx["page"])
    return [] if got == [x] else [f"the vault dialog's pick left the draft's media {got}, not [{x}]"]


def dedupe_second(ctx) -> list:
    rec, marker, page = ctx["record"], ctx["marker"], ctx["page"]
    x, fr = rec["x"], ctx["frame"]
    up = _upload(ctx, fr, proof_png(marker, NEW_POST_DEDUPE_ID), "oi-proof-dedupe.png")
    b = up["body"]
    rec["upload_2"] = {"status": up["status"], "deduped": b.get("deduped"), "vault_id": b.get("vault_id"),
                       "send_with": b.get("send_with")}
    if up["status"] >= 300 or b.get("deduped") is not True or str(b.get("vault_id")) != str(x):
        return [f"the second upload was not a dedupe hit to {x}: {up['status']} {json.dumps(b)[:200]}"]
    _wait_media(page, 2)
    ctx["shot"]("attached")
    seq0 = max((e["seq"] for e in _wire(ctx)), default=0)
    sent = _post(ctx, fr)
    lines = [e for e in _wire(ctx) if e["seq"] > seq0 and e["method"] == "POST" and e["path"] == POSTS_PATH
             and e["verdict"] == "allow"]
    body = (lines[-1].get("body") if lines else None) or {}
    rec["outbound_media"] = media = body.get("mediaFiles") if isinstance(body, dict) else None
    out = []
    if media != [x, x]:
        out.append(f"the second post's outbound body carries {media}, not X_B's id {x} twice")
    rec["accepted"] = accepted = 200 <= sent["status"] < 300
    of_status = lines[-1].get("status") if lines else None
    rec["post_2"] = {"status": sent["status"], "of_status": of_status, "id": sent["body"].get("id")}
    if not accepted:
        return out + [f"OnlyFans refused the post holding X_B twice: {of_status} (Relay {sent['status']}) "
                      f"{json.dumps(sent['body'])[:200]}"]
    held = ctx["of_get"](f"{POSTS_PATH}/{sent['body'].get('id')}", {}).get("media") or []
    rec["accepted_media"] = len(held)
    return out


NEW_POST_UPLOAD_ID = "new-post--upload"
NEW_POST_DEDUPE_ID = "new-post--dedupe-duplicate-id"


def _post_undo(posts: int) -> tuple:
    return (Write("DELETE", f"{POSTS_PATH}/{{id}}", max=posts, relay="/api/of/v2/posts/{id}", reverses=(3,)),
            Write("PUT", "/api2/v2/vault/media/hidden", body_must={"mediaIds": ["{media}"]}, relay_method="POST",
                  relay="/admin/vault-ai/items/{media}/hide", relay_body={"account_id": "{account}"},
                  reverses=(0, 1, 2, 3)))


_NARROWING = "the Proof Creator's own free post, Scheduled 45 min ahead (no Fan sees it), deleted before it fires"

NEW_POST_UPLOAD = Proof(
    id=NEW_POST_UPLOAD_ID, phase=6, page="new-post/index", control="Upload into a scheduled post", kind="live",
    arm=(*UPLOAD_ARMS, Write("POST", POSTS_PATH)),
    narrowing=_NARROWING,
    trigger=(("call", upload_post),),
    of_read=read_posts_and_vault,
    effect=upload_effect,
    undo=_post_undo(1),
    undo_keys=post_media,
    find=find_new_post(UPLOAD_SUFFIX),
)

NEW_POST_DEDUPE = Proof(
    id=NEW_POST_DEDUPE_ID, phase=6, page="new-post/state-vault", control="Duplicate id after a dedupe hit",
    kind="live",
    arm=(*UPLOAD_ARMS, Write("POST", POSTS_PATH, max=2)),
    narrowing=_NARROWING,
    trigger=(("call", dedupe_draft),
             ("goto", "new-post/index"), ("call", dedupe_first),
             ("goto", "new-post/state-vault"), ("call", dedupe_pick),
             ("goto", "new-post/index"), ("call", dedupe_second)),
    of_read=read_posts_and_vault,
    effect=upload_effect,
    undo=_post_undo(2),
    undo_keys=post_media,
    find=find_new_post(DEDUPE_SUFFIX),
)



QUEUE_PUBLISH_NOW_ID = "queue--publish-now"
PN_FILE, PN_NOW, PN_VISIBLE = "publish-file", "publish-now", "publish-visible"
PUBLISH_NOW = "#oi-queue-menu [at-attr='publish_now']"
_PUBLISH_PATH = re.compile(r"^/api2/v2/schedules/(\d+)/publish$")


def _profile_rows(get) -> list:
    uid = get("/api2/v2/users/me", {}).get("id")
    got = get(f"/api2/v2/users/{uid}/posts", {"limit": 10})
    rows = got.get("list") if isinstance(got, dict) else got
    return [[p["id"], str(p.get("rawText") or p.get("text") or ""), *[m["id"] for m in p.get("media") or []]]
            for p in rows or [] if isinstance(p, dict)]


def read_publish_now(get, fan) -> dict:
    return {**read_posts_and_vault(get, fan), "profile": sorted(_profile_rows(get))}


def _posts_of(read) -> list:
    read = read or {}
    return [(r[1], r[2], list(r[3:])) for r in read.get("queue") or []] + \
           [(r[0], r[1], list(r[2:])) for r in read.get("profile") or []]


def _new_posts(before, after) -> list:
    had = {str(p[0]) for p in _posts_of(before)}
    return [p for p in _posts_of(after) if str(p[0]) not in had]


def publish_now_effect(before, after) -> bool:
    return bool(_new_posts(before, after))


def find_publish_now(before, after, marker):
    want = {draft_text(marker, s) for s in (PN_FILE, PN_NOW, PN_VISIBLE)}
    new = [p[0] for p in _new_posts(before, after) if p[1] in want]
    return new[0] if len(new) == 1 else None


def publish_media(before, after) -> dict:
    had = set((before or {}).get("vault") or [])
    out = {}
    for pid, _, media in _new_posts(before, after):
        if len(set(media)) == 1 and media[0] not in had:
            out[str(pid)] = {"media": media[0]}
    return out


LIVE_PARK = ("parked — needs capture (ticket 12 sitting): live Publish now is text-only (no media), and no capture "
             "record holds a text-only post or queue body (mediaFiles empty) to build it from")


# Live, Publish now allows one fan-visible attempt with no media: parks before any write until a capture record holds a text-only post/queue body.
def pn_draft(ctx) -> list:
    if ctx["of"] != "fake":
        ctx["park"](LIVE_PARK)
    now = datetime.now(timezone.utc)
    if (now + POST_SCHEDULE_LEAD + timedelta(minutes=10)).date() != now.date():
        ctx["park"](f"scheduling {POST_SCHEDULE_LEAD} ahead crosses UTC midnight (D's Queue row on tomorrow's page)")
    ctx["record"]["branches"] = {}
    ctx["record"]["scheduled_date"] = _seed_draft(ctx, draft_text(ctx["marker"], PN_FILE))
    return []


def pn_first(ctx) -> list:
    rec, marker, of_get = ctx["record"], ctx["marker"], ctx["of_get"]
    fr = ctx["frame"]
    before = read_posts_and_vault(of_get, None)
    up = _upload(ctx, fr, proof_png(marker, QUEUE_PUBLISH_NOW_ID), "oi-proof-publish.png")
    rec["upload_1"] = {"status": up["status"], "deduped": up["body"].get("deduped"), "ready": up["body"].get("ready")}
    if up["status"] >= 300 or up["body"].get("ready") is not True:
        return [f"the first upload answered {up['status']}: {json.dumps(up['body'])[:200]}"]
    _wait_media(ctx["page"], 1)
    sent = _post(ctx, fr)
    rec["post_1"] = {"status": sent["status"], "id": sent["body"].get("id")}
    if sent["status"] >= 300:
        return [f"P's Post answered {sent['status']}: {json.dumps(sent['body'])[:200]}"]
    media = new_media(before, read_posts_and_vault(of_get, None))
    if len(media) != 1:
        return [f"P filed {len(media)} new vault items, not one: {media}"]
    rec["x"] = x = media[0]
    ctx["settle"]()
    if x in read_posts_and_vault(of_get, None)["vault"]:
        return [f"X_D {x} is still listed in the vault after Remove from vault"]
    _seed_draft(ctx, draft_text(marker, PN_NOW))
    return []


def pn_second(ctx) -> list:
    rec, marker = ctx["record"], ctx["marker"]
    x, fr = rec["x"], ctx["frame"]
    up = _upload(ctx, fr, proof_png(marker, QUEUE_PUBLISH_NOW_ID), "oi-proof-publish.png")
    b = up["body"]
    rec["upload_2"] = {"status": up["status"], "deduped": b.get("deduped"), "hidden": b.get("hidden"),
                       "vault_id": b.get("vault_id"), "send_with": b.get("send_with")}
    if up["status"] >= 300 or b.get("deduped") is not True or str(b.get("vault_id")) != str(x):
        return [f"the second upload was not a dedupe hit to X_D {x}: {up['status']} {json.dumps(b)[:200]}"]
    if b.get("hidden") is not True:
        return [f"the dedupe hit to the removed X_D {x} does not answer hidden: {json.dumps(b)[:200]}"]
    rec["branches"]["hidden-dedupe"] = "pass"
    _wait_media(ctx["page"], 1)
    return _post_and_register(ctx, fr, "post_d")


def _post_and_register(ctx, fr, name) -> list:
    rec = ctx["record"]
    sent = _post(ctx, fr)
    pid = str(sent["body"].get("id") or "")
    rec[name] = {"status": sent["status"], "id": pid}
    if sent["status"] >= 300 or not pid:
        return [f"{name}'s Post answered {sent['status']}: {json.dumps(sent['body'])[:200]}"]
    sid = next((str(i["id"]) for i in schedules(ctx["of_get"], datetime.now(timezone.utc))
                if i.get("type") == "post" and str((i.get("entity") or {}).get("id")) == pid), None)
    rec[name]["schedule"] = sid
    if sid is None:
        return [f"no schedule item for post {pid} in GET /schedules"]
    return ctx["read_id"]("schedule", sid, pid)


def _publish_now(ctx, pid: str, sid: str, tag: str) -> tuple:
    rec, page, fr = ctx["record"], ctx["page"], ctx["frame"]
    row = fr.locator(QUEUE_ROW.format(qid=pid)).first
    try:
        row.wait_for(state="visible", timeout=20_000)
    except Exception:  # noqa: BLE001  (the queue read the page made before the post: reopened once)
        fr = ctx["reload"]()
        row = fr.locator(QUEUE_ROW.format(qid=pid)).first
        row.wait_for(state="visible", timeout=60_000)
    shown = row.get_attribute("data-oi-queue-schedule")
    rec[f"{tag}_row_schedule"] = shown
    if shown != sid:
        return [f"the Queue row of post {pid} carries schedule {shown!r}, not its item's {sid}: not clicked"], None, None
    row.locator(QUEUE_MORE).first.click(timeout=30_000)
    button = fr.locator(PUBLISH_NOW).first
    button.wait_for(state="visible", timeout=30_000)
    ctx["shot"](f"{tag}-menu")
    seq0 = max((e["seq"] for e in _wire(ctx)), default=0)
    page.once("dialog", lambda d: d.accept())
    with page.expect_response(lambda r: r.request.method == "PUT" and urlsplit(r.url).path.startswith(
            "/api/of/v2/schedules/") and urlsplit(r.url).path.endswith("/publish"), timeout=60_000) as got:
        button.click(timeout=30_000)
    lines = [e for e in _wire(ctx) if e["seq"] > seq0 and e["method"] == "PUT" and _PUBLISH_PATH.match(e["path"])]
    rec[tag] = {"app_status": got.value.status,
                "wire": [{"verdict": e["verdict"], "class": e.get("class"), "path": e["path"],
                          "status": e.get("status")} for e in lines]}
    refused = [e for e in lines if e["verdict"] != "allow"]
    if refused:
        return [f"the guard refused Publish now's PUT {e['path']}: {e.get('class')}: {e.get('reason')}"
                for e in refused], None, None
    if len(lines) != 1:
        return [f"Publish now put {len(lines)} publish lines on the wire, not one (app {got.value.status})"], None, None
    published = _PUBLISH_PATH.match(lines[0]["path"])[1]
    if published != sid:
        return [f"Publish now published schedule {published}, not post {pid}'s {sid}"], None, None
    return [], lines[0].get("status"), _json(got.value.body())


def _published(ctx, pid: str, x) -> list:
    rec, page = ctx["record"], ctx["page"]
    for _ in range(60):
        row = next((r for r in _profile_rows(ctx["of_get"]) if str(r[0]) == pid), None)
        if row is not None:
            rec["profile_media"] = row[2:]
            if x is not None:
                rec["hidden_shows"] = str(x) in {str(m) for m in row[2:]}
            ctx["shot"]("published")
            return []
        page.wait_for_timeout(500)
    return [f"post {pid} never showed on the profile after Publish now"]


def pn_publish(ctx) -> list:
    rec = ctx["record"]
    d = rec["post_d"]
    out, status, body = _publish_now(ctx, d["id"], d["schedule"], "publish")
    if out:
        return out
    if isinstance(status, int) and 200 <= status < 300:
        out = _published(ctx, d["id"], rec["x"])
        ctx["settle"]()
        if not out:
            rec["branches"]["publish-now"] = "pass"
        return out
    if not (isinstance(status, int) and 400 <= status < 500):
        app = (rec.get("publish") or {}).get("app_status")
        return [f"Publish now on D: reply lost or 5xx (wire {status}, app {app}); never retried, D left to the "
                f"after-write read and undone"]
    rec["hidden_publish"] = {"status": status, "body": body}
    ctx["settle"]()
    if why := proof_core.fan_visible_refusal(ctx["fan_visible_spent"](), QUEUE_PUBLISH_NOW, ctx["of"]):
        rec["branches"]["publish-now"] = (f"parked: OnlyFans refused D (hidden medium, {status}); the visible "
                                          f"re-run not attempted: {why}")
        return []
    rec["rerun"] = True
    _seed_draft(ctx, draft_text(ctx["marker"], PN_VISIBLE))
    return []


def pn_visible_post(ctx) -> list:
    rec, marker = ctx["record"], ctx["marker"]
    if not rec.get("rerun"):
        return []
    fr = ctx["frame"]
    up = _upload(ctx, fr, proof_png(marker, f"{QUEUE_PUBLISH_NOW_ID}-visible"), "oi-proof-publish-visible.png")
    rec["upload_3"] = {"status": up["status"], "deduped": up["body"].get("deduped"), "ready": up["body"].get("ready")}
    if up["status"] >= 300 or up["body"].get("ready") is not True or up["body"].get("deduped"):
        return [f"the visible upload was not a fresh one: {up['status']} {json.dumps(up['body'])[:200]}"]
    _wait_media(ctx["page"], 1)
    return _post_and_register(ctx, fr, "post_visible")


def pn_publish_visible(ctx) -> list:
    rec = ctx["record"]
    if not rec.get("rerun"):
        return []
    v = rec["post_visible"]
    out, status, _ = _publish_now(ctx, v["id"], v["schedule"], "publish_visible")
    if out:
        return out
    if status is None or not 200 <= status < 300:
        return [f"Publish now on the visible re-run D' answered {status}"]
    out = _published(ctx, v["id"], None)
    ctx["settle"]()
    if not out:
        rec["branches"]["publish-now"] = "pass"
    return out


QUEUE_PUBLISH_NOW = Proof(
    id=QUEUE_PUBLISH_NOW_ID, phase=6, page="queue/index", control="Publish now", kind="live",
    tags=frozenset({"post", "delete_at_once"}),
    branches=("hidden-dedupe", "publish-now"),
    narrowing="the Proof Creator's own free post with its own neutral picture, Scheduled 45 min ahead, published from "
              "the Queue inside the run's quiet hour and deleted within 60 s; the picture Removed from vault",
    arm=(*(replace(w, max=2) for w in UPLOAD_ARMS), Write("POST", POSTS_PATH, max=3),
         Write("PUT", "/api2/v2/schedules/{id}/publish", max=2)),
    trigger=(("call", pn_draft),
             ("goto", "new-post/index"), ("call", pn_first),
             ("goto", "new-post/index"), ("call", pn_second),
             ("goto", "queue/index"), ("call", pn_publish),
             ("goto", "new-post/index"), ("call", pn_visible_post),
             ("goto", "queue/index"), ("call", pn_publish_visible)),
    of_read=read_publish_now,
    effect=publish_now_effect,
    undo=(Write("DELETE", f"{POSTS_PATH}/{{id}}", max=3, relay="/api/of/v2/posts/{id}", reverses=(3, 4)),
          Write("PUT", "/api2/v2/vault/media/hidden", max=3, body_must={"mediaIds": ["{media}"]}, relay_method="POST",
                relay="/admin/vault-ai/items/{media}/hide", relay_body={"account_id": "{account}"},
                reverses=(0, 1, 2, 3, 4))),
    undo_keys=publish_media,
    find=find_publish_now,
    binds=frozenset({"schedule"}),
    fan_visible_max=2,
)


PROOFS = (VAULT_CUSTOMIZE_ORDER, QUEUE_SEND_NOW, NEW_POST_UPLOAD, NEW_POST_DEDUPE, QUEUE_PUBLISH_NOW)
