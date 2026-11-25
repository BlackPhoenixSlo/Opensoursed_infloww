from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import proof_core
from proof_core import Proof, Write
from proofs.phase6_writes import (MARKER, POST_BUTTON, POST_SCHEDULE_LEAD, POSTS_PATH, QUEUE_SEND_NOW, SCHEDULED_TOAST,
                                  _json, _wire, draft_text, schedules)


COTAG_SCHEDULED_ID = "new-post--cotag-scheduled"
COTAG_IMMEDIATE_ID = "new-post--cotag-immediate"
COTAG_SCHEDULED, COTAG_IMMEDIATE = "cotag-scheduled", "cotag-immediate"
COTAG_PAGE = "new-post/state-tag-people"
COTAG_ROW = "label.b-rows-lists__item[data-oi-user='{id}']"
POSTED_TOAST = "Your post has been published"
COTAG_UNNAMED = "Co-tag partner not named (owner sheet item 4)"
COTAG_LIVE_PARK = ("parked — the immediate Co-tag post runs in fake mode only (coordinator ruling 2026-11-21): a live "
                   "fan-visible tagged post waits on ticket 104's attended run (cap 1, neutral text, no media)")
TICKET_06 = ("ticket 06's frequency question stays open: two sends cannot measure how often OnlyFans makes a post "
             "the Relay reported as failed")
TAG_VALIDATION = "open: whether OnlyFans validates Co-tags at create or only at publish (FakeOF stores them unchecked)"
_DRAFT_JS = "(localStorage.getItem('chatterly:scope') || '').replace(/^model:/, '')"


def _tags_of(entity) -> str:
    tags = entity.get("rfTag") if isinstance(entity, dict) else None
    out = []
    for t in tags if isinstance(tags, list) else []:
        v = t.get("id") if isinstance(t, dict) else t
        if str(v).isdigit():
            out.append(int(v))
    return ",".join(str(i) for i in sorted(out))


def _queue_rows(get, only: str | None = None) -> list:
    queue = []
    for i in schedules(get, datetime.now(timezone.utc)):
        pid = (i.get("entity") or {}).get("id")
        if i.get("type") != "post" or (only is not None and str(pid) != only):
            continue
        post = get(f"/api2/v2/posts/{pid}", {})
        queue.append([i["id"], pid, str(post.get("rawText") or post.get("text") or ""), i.get("publishDateTime"),
                      _tags_of(post)])
    return queue


def _profile_rows(get) -> list:
    uid = get("/api2/v2/users/me", {}).get("id")
    got = get(f"/api2/v2/users/{uid}/posts", {"limit": 10})
    rows = got.get("list") if isinstance(got, dict) else got
    return [[p["id"], str(p.get("rawText") or p.get("text") or ""), _tags_of(p)]
            for p in rows or [] if isinstance(p, dict)]


def read_cotag(get, fan) -> dict:
    return {"queue": sorted(_queue_rows(get), key=str), "profile": sorted(_profile_rows(get), key=str)}


def _cotag_posts(read) -> list:
    read = read or {}
    return [(r[1], r[2], r[4]) for r in read.get("queue") or []] + [tuple(r) for r in read.get("profile") or []]


def _new_cotag(before, after) -> list:
    had = {str(p[0]) for p in _cotag_posts(before)}
    return [p for p in _cotag_posts(after) if str(p[0]) not in had]


def cotag_effect(before, after) -> bool:
    return any(MARKER in p[1] for p in _new_cotag(before, after))


def find_cotag(suffix: str):
    def find(before, after, marker):
        want = draft_text(marker, suffix)
        new = [p[0] for p in _new_cotag(before, after) if p[1] == want]
        return new[0] if len(new) == 1 else None
    return find


def cotag_wire_problems(body, partner) -> list:
    if isinstance(body, dict) and not proof_core.cotag_tagged(body):
        return ["the outbound post carries no Co-tag at all"]
    out = [f"outbound: {p}" for p in proof_core.cotag_problems(body, partner)]
    if isinstance(body, dict) and body.get("mediaFiles"):
        out.append(f"the outbound post carries media {body['mediaFiles']!r} (a media-level auto-tag can join)")
    return out


SCHEDULE_SLACK = timedelta(minutes=1)


def _schedule_problem(body: dict, scheduled: bool, at) -> str | None:
    when = body.get("scheduledDate")
    if not scheduled:
        return f"the immediate post carries a schedule ({str(when)[:40]})" if body.get("isScheduled") or when else None
    if not body.get("isScheduled") or at is None:
        return "post C is not scheduled"
    try:
        lead = datetime.fromisoformat(str(when or "").replace("Z", "+00:00")) - at
    except (TypeError, ValueError):
        return f"post C's scheduledDate {str(when)[:40]} is unreadable"
    if not proof_core.POST_LEAD <= lead <= POST_SCHEDULE_LEAD + SCHEDULE_SLACK:
        return (f"post C's scheduledDate {str(when)[:40]} is not the draft's "
                f"{int(POST_SCHEDULE_LEAD.total_seconds() // 60)} minutes ahead")
    return None


def cotag_payload(suffix: str):
    def payload(body, run, at=None) -> str | None:
        if isinstance(body, dict):
            if why := proof_core.marker_problem(body.get("text"), run):
                return f"the post: {why}"
            if body.get("text") != draft_text(run.marker, suffix):
                return f"the post's text {str(body.get('text'))[:80]!r} is not the draft's {suffix!r} text"
            if why := _schedule_problem(body, suffix == COTAG_SCHEDULED, at):
                return why
        return next(iter(cotag_wire_problems(body, run.cotag_partner)), None)
    return payload


def cotag_cap_refusal(spent, proof, of: str) -> str | None:
    spent = list(spent)
    if why := proof_core.fan_visible_refusal(spent, proof, of):
        return why
    if QUEUE_SEND_NOW.id not in spent and len(spent) + 1 >= proof_core.FAN_VISIBLE_CAP:
        return (f"the effort's last fan-visible slot (cap {proof_core.FAN_VISIBLE_CAP}, {len(spent)} spent) is kept "
                f"for {QUEUE_SEND_NOW.id}")
    return None


def _cotag_draft(ctx, suffix: str, at: str | None) -> list:
    rec, page = ctx["record"], ctx["page"]
    partner = int(ctx["cotag_partner"])
    rec.update(partner=partner, tag_validation=TAG_VALIDATION)
    draft = {"text": draft_text(ctx["marker"], suffix), "tagged_users": [], "media_files": [], "thumbs": []}
    if at:
        draft["posted_at"] = rec["scheduled_date"] = at
    page.evaluate(f"d => sessionStorage.setItem('oi:new-post:' + {_DRAFT_JS}, JSON.stringify(d))", draft)
    fr = ctx["reload"]()
    fr.locator("label.b-rows-lists__item[data-oi-user]").first.wait_for(state="attached", timeout=60_000)
    row = fr.locator(COTAG_ROW.format(id=partner)).first
    if not row.count():
        ctx["park"](f"Co-tag partner {partner} is not on the Creator's taggable list (GET /posts/tagged-friend-users)")
    box = row.locator("input[type='checkbox']").first
    try:
        box.check(timeout=10_000)
    except Exception:  # noqa: BLE001  (OF's checkbox may be styled over: a click event is its change)
        box.dispatch_event("click")
    tags_js = f"JSON.parse(sessionStorage.getItem('oi:new-post:' + {_DRAFT_JS}) || '{{}}').tagged_users || []"
    try:
        page.wait_for_function(f"p => JSON.stringify({tags_js}) === JSON.stringify([p])", arg=partner, polling=100,
                               timeout=15_000)
    except Exception:  # noqa: BLE001
        got = page.evaluate(f"() => {tags_js}")
        return [f"checking partner {partner}'s row left the draft's tagged_users {got!r}, not [{partner}]"]
    ctx["shot"]("tagged")
    return []


def _cotag_unnamed(ctx) -> None:
    if not str(ctx.get("cotag_partner") or "").isdigit():
        ctx["park"](COTAG_UNNAMED)


def cotag_scheduled_draft(ctx) -> list:
    _cotag_unnamed(ctx)
    at = (datetime.now(timezone.utc) + POST_SCHEDULE_LEAD).replace(microsecond=0).isoformat()
    return _cotag_draft(ctx, COTAG_SCHEDULED, at)


def cotag_immediate_draft(ctx) -> list:
    _cotag_unnamed(ctx)
    if ctx["of"] != "fake":
        ctx["park"](COTAG_LIVE_PARK)
    if why := cotag_cap_refusal(ctx["fan_visible_spent"](), NEW_POST_COTAG_IMMEDIATE, ctx["of"]):
        ctx["park"](f"fan-visible cap: {why}")
    return _cotag_draft(ctx, COTAG_IMMEDIATE, None)


def _cotag_post(ctx, suffix: str, toast: str) -> tuple:
    rec, page, fr = ctx["record"], ctx["page"], ctx["frame"]
    partner, want = int(ctx["cotag_partner"]), draft_text(ctx["marker"], suffix)
    before = read_cotag(ctx["of_get"], None)
    fr.wait_for_function(f"() => {{ const b = document.querySelector(\"{POST_BUTTON}\"); return b && !b.disabled; }}",
                         polling=100, timeout=60_000)
    seq0 = max((e["seq"] for e in _wire(ctx)), default=0)
    with page.expect_response(lambda r: r.request.method == "POST" and urlsplit(r.url).path == "/api/of/v2/posts",
                              timeout=120_000) as got:
        fr.locator(POST_BUTTON).first.click(timeout=30_000)
    status, body = got.value.status, _json(got.value.body())
    lines = [e for e in _wire(ctx) if e["seq"] > seq0 and e["method"] == "POST" and e["path"] == POSTS_PATH]
    sent = [e.get("body") if isinstance(e.get("body"), dict) else {} for e in lines]
    rec["post"] = {"app_status": status, "id": body.get("id"),
                   "wire": [{"verdict": e["verdict"], "class": e.get("class"), "status": e.get("status"),
                             "rfTag": b.get("rfTag"), "userTags": b.get("userTags")} for e, b in zip(lines, sent)]}
    out = [f"the guard refused the post: {e.get('class')}: {e.get('reason')}" for e in lines if e["verdict"] != "allow"]
    if len(lines) != 1:
        out.append(f"Post put {len(lines)} POST /posts lines on the wire, not one (app {status})")
    for e in lines:
        out += cotag_wire_problems(e.get("body"), partner)
    if not 200 <= status < 300:
        made = [p[0] for p in _new_cotag(before, read_cotag(ctx["of_get"], None)) if p[1] == want]
        wire = lines[0].get("status") if lines else None
        rec["ambiguous_failure"] = {"app_status": status, "wire_status": wire, "found_by_marker": made}
        rec["ticket_06"] = (f"ambiguous failure seen: the Relay reported {wire or status} and OnlyFans "
                            + (f"made the post anyway ({made[0]})" if made else "shows no post")
                            + "; one observation, frequency stays open")
        return out + [f"Post answered {status} (wire {wire}): never retried; "
                      + (f"post {made[0]} found by its marker, left to the after-write read and undone" if made
                         else "no post found by its marker")], None
    rec["ambiguous_failure"], rec["ticket_06"] = None, f"no ambiguous failure seen; {TICKET_06}"
    try:
        fr.get_by_text(toast).first.wait_for(state="visible", timeout=30_000)
    except Exception:  # noqa: BLE001
        out.append(f"no {toast!r} toast after Post answered {status}")
    return out, str(body.get("id") or "")


def _cotag_shown(ctx, pid: str, key: str, want: str):
    at, get = (1 if key == "queue" else 0), ctx["of_get"]
    for _ in range(20):
        rows = _queue_rows(get, pid) if key == "queue" else _profile_rows(get)
        row = next((r for r in rows if str(r[at]) == pid and r[at + 1] == want), None)
        if row is not None:
            return row
        ctx["page"].wait_for_timeout(500)
    return None


def cotag_scheduled_post(ctx) -> list:
    rec, partner = ctx["record"], str(ctx["cotag_partner"])
    out, pid = _cotag_post(ctx, COTAG_SCHEDULED, SCHEDULED_TOAST)
    if pid is None:
        return out
    row = _cotag_shown(ctx, pid, "queue", draft_text(ctx["marker"], COTAG_SCHEDULED))
    if row is None:
        return out + [f"post {pid} never showed in GET /schedules"]
    ctx["shot"]("scheduled")
    rec["queue_row"] = {"publishDateTime": row[3], "tags": row[4]}
    try:
        same = (datetime.fromisoformat(str(row[3]).replace("Z", "+00:00"))
                == datetime.fromisoformat(rec["scheduled_date"]))
    except ValueError:
        same = False
    if not same:
        out.append(f"post {pid} is queued for {row[3]}, not the chosen {rec['scheduled_date']}")
    if row[4] != partner:
        out.append(f"post {pid}'s read carries tags {row[4]!r}, not the partner {partner} alone")
    return out


def cotag_immediate_post(ctx) -> list:
    rec, partner = ctx["record"], str(ctx["cotag_partner"])
    out, pid = _cotag_post(ctx, COTAG_IMMEDIATE, POSTED_TOAST)
    if pid is None:
        return out
    row = _cotag_shown(ctx, pid, "profile", draft_text(ctx["marker"], COTAG_IMMEDIATE))
    if row is None:
        return out + [f"post {pid} never showed on the profile"]
    ctx["shot"]("published")
    rec["profile_row"] = {"tags": row[2]}
    if row[2] != partner:
        out.append(f"post {pid}'s read carries tags {row[2]!r}, not the partner {partner} alone")
    return out


_COTAG_UNDO = (Write("DELETE", f"{POSTS_PATH}/{{id}}", relay="/api/of/v2/posts/{id}"),)

NEW_POST_COTAG_SCHEDULED = Proof(
    id=COTAG_SCHEDULED_ID, phase=6, page=COTAG_PAGE, control="Co-tag on a scheduled post", kind="live",
    tags=frozenset({"post"}),
    narrowing="the Proof Creator's own free text post (no media), Co-tagged with the owner's named partner only, "
              "Scheduled 45 min ahead (no Fan sees it), deleted before it fires",
    arm=(Write("POST", POSTS_PATH, payload=cotag_payload(COTAG_SCHEDULED)),),
    trigger=(("call", cotag_scheduled_draft), ("goto", "new-post/index"), ("call", cotag_scheduled_post)),
    of_read=read_cotag,
    effect=cotag_effect,
    undo=_COTAG_UNDO,
    find=find_cotag(COTAG_SCHEDULED),
    may_tag=True,
)

NEW_POST_COTAG_IMMEDIATE = Proof(
    id=COTAG_IMMEDIATE_ID, phase=6, page=COTAG_PAGE, control="Co-tag on an immediate post", kind="live",
    tags=frozenset({"post", "delete_at_once"}),
    narrowing="the Proof Creator's own free text post (no media), Co-tagged with the owner's named partner only, "
              "published inside the run's quiet hour and deleted within 60 s",
    arm=(Write("POST", POSTS_PATH, payload=cotag_payload(COTAG_IMMEDIATE)),),
    trigger=(("call", cotag_immediate_draft), ("goto", "new-post/index"), ("call", cotag_immediate_post)),
    of_read=read_cotag,
    effect=cotag_effect,
    undo=_COTAG_UNDO,
    find=find_cotag(COTAG_IMMEDIATE),
    may_tag=True,
)


PROOFS = (NEW_POST_COTAG_SCHEDULED, NEW_POST_COTAG_IMMEDIATE)
