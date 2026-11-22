"""Seam 2: the Live guard policy (`decide`), the Proof shape and `order`, as table tests.

Expected verdicts come from the spec's nine classes (docs/spec/ofm-not-yet/phase-00-live-capture-proof-harness.md,
Implementation Decisions) and ticket 01; the paths stand for the spec's pattern families.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from proof_core import Proof, Request, Run, Write, decide, order

HERE = Path(__file__).parent
AT = datetime(2026, 11, 21, 3, 10, tzinfo=timezone.utc)
QUIET = datetime(2026, 11, 21, 3, 0, tzinfo=timezone.utc)  # the run's declared quiet hour starts here
FAN = "555"
YES = lambda before, after: True  # noqa: E731


def P(arm=(), undo=(), tags=(), kind="live", id="p.x", reads=()):
    return Proof(id=id, phase=0, page="collections/index", control="x", kind=kind, tags=frozenset(tags),
                 reads=tuple(reads), arm=tuple(arm), undo=tuple(undo), effect=YES if arm else None)


def R(method, path, body=None, host="onlyfans.com", at=AT):
    return Request(method=method, host=host, path=path, body=body, at=at)


def armed(method, path, body_must=None, undo=(Write("DELETE", "/api2/v2/lists/{id}"),), **kw):
    """A proof arming exactly this one write, with an undo unless told otherwise."""
    return P(arm=[Write(method, path, body_must=body_must)], undo=undo, **kw)


def sched(minutes):
    return {"isScheduled": 1, "scheduledDate": (AT + timedelta(minutes=minutes)).isoformat()}


QD = sched(35)["scheduledDate"]   # a queued message's date, past POST_LEAD


LIST = armed("POST", "/api2/v2/lists")
TRACER = P(arm=[Write("POST", "/api2/v2/lists")], undo=[Write("DELETE", "/api2/v2/lists/{id}")], id="tracer.create-list")
IRREV = P(arm=[Write("POST", "/api2/v2/posts/{id}/report")], tags={"irreversible"}, id="chat.report")
QUEUE = armed("POST", "/api2/v2/messages/queue")
PUBLISH = armed("PUT", "/api2/v2/schedules/{id}/publish", tags={"post", "delete_at_once"}, id="queue.publish-now")
NOW_POST = armed("POST", "/api2/v2/posts", tags={"post", "delete_at_once"}, id="post.now")
FAN_RUN = dict(proof_fan=FAN, quiet_hour=QUIET)
IPS = {"ips": ["192.0.2.1"]}  # TEST-NET-1, owner-proxy Q8
# ticket 30: an upload (arm 0) then a post (arm 1); the post's DELETE reverses arm 1, the hide arms 0 and 1.
HIDE = Write("PUT", "/api2/v2/vault/media/hidden", body_must={"mediaIds": ["{media}"]}, relay_method="POST",
             relay="/admin/vault-ai/items/{media}/hide", relay_body={"account_id": "{account}"}, reverses=(0, 1))
RECORD = P(arm=[Write("POST", "/api2/v2/upload/signed/create"), Write("POST", "/api2/v2/posts")],
        undo=[Write("DELETE", "/api2/v2/posts/{id}", relay="/api/of/v2/posts/{id}", reverses=(1,)), HIDE],
        tags={"post"}, id="p2.record")
# post 9 created by the post arm (1), upload id 55 by the upload arm (0), media 77 read off the post
MEDIA77 = dict(created=frozenset({"9", "55"}), created_by={0: frozenset({"55"}), 1: frozenset({"9"})},
               keys={"media": frozenset({"77"})})
UNBLOCK = Write("DELETE", "/api2/v2/streams/users/{id}/block")
L2 = P(id="sec.forgot-tag", arm=[Write("PATCH", "/api2/v2/users/me/blocked-ips", body_must=IPS)],
       undo=[Write("PATCH", "/api2/v2/users/me/blocked-ips", body_must={"ips": []})])


CASES = [
    # 1. host: onlyfans.com or its subdomains; another host only by exact name, never by wildcard
    ("off-host", R("GET", "/x", host="example.com"), Run(), "refused", "host"),
    ("look-alike host", R("GET", "/x", host="onlyfans.com.evil.com"), Run(), "refused", "host"),
    ("wildcard host never armed", R("GET", "/x", host="a.cdn.example.net"), Run(hosts=("*.cdn.example.net",)),
     "refused", "host"),
    # ticket 53: a named host takes only the armed Write naming it, never a read
    ("named host, read", R("GET", "/x", host="a.cdn.example.net"), Run(hosts=("a.cdn.example.net",)), "refused", "host"),
    ("subdomain", R("GET", "/api2/v2/lists", host="www.onlyfans.com"), Run(), "read", "read"),
    ("off-host write, armed", R("POST", "/api2/v2/lists", host="example.com"), Run(proof=LIST), "refused", "host"),
    # 2. reads pass; a Critical GET only when the proof names it
    ("GET", R("GET", "/api2/v2/lists"), Run(), "read", "read"),
    ("HEAD", R("HEAD", "/api2/v2/lists"), Run(), "read", "read"),
    ("OPTIONS", R("OPTIONS", "/api2/v2/lists"), Run(), "read", "read"),
    ("Statements payout history read", R("GET", "/api2/v2/payouts/requests"), Run(), "read", "read"),
    ("Critical GET not named", R("GET", "/api2/v2/users/me/dac7"), Run(proof=P()), "refused", "critical_read"),
    ("Critical GET, no proof", R("GET", "/api2/v2/bank/accounts"), Run(), "refused", "critical_read"),
    ("GET on a Relay backstop path", R("GET", "/api2/v2/users/logout"), Run(proof=P()), "refused", "critical_read"),
    ("GET on a Relay backstop path, named in reads", R("GET", "/api2/v2/log"),
     Run(proof=P(reads=["/api2/v2/log"])), "refused", "critical_read"),
    ("GET to the OF bug reporter host", R("GET", "/x", host="bugs.onlyfans.com"), Run(), "refused", "critical_read"),
    ("GET /sessions is a read", R("GET", "/api2/v2/sessions"), Run(), "read", "read"),
    ("dac7 inside a CDN hash is not a topic", R("GET", "/files/a/ab/ab0e1d7dac71acfe/760x1352_ff_frame_0.jpg", host="cdn2.onlyfans.com"),
     Run(proof=P()), "read", "read"),
    ("Critical GET /payouts/dac7 not named", R("GET", "/api2/v2/payouts/dac7"), Run(proof=P()), "refused", "critical_read"),
    ("Critical GET named in reads", R("GET", "/api2/v2/users/me/dac7"),
     Run(proof=P(reads=["/api2/v2/users/me/dac7"])), "read", "read"),
    ("Critical GET named by template", R("GET", "/api2/v2/bank/accounts/42"),
     Run(proof=P(reads=["/api2/v2/bank/accounts/{id}"])), "read", "read"),
    # 3. Critical: capture-abort mode answers an aborted capture (asserted in its own test below)
    ("PATCH /users/me harmless key, armed", R("PATCH", "/api2/v2/users/me", {"about": "hi"}),
     Run(proof=armed("PATCH", "/api2/v2/users/me", undo=[Write("PATCH", "/api2/v2/users/me")])), "allow", "allow"),
    ("same-path undo once the write is spent", R("PATCH", "/api2/v2/users/me", {"about": ""}),
     Run(proof=armed("PATCH", "/api2/v2/users/me", undo=[Write("PATCH", "/api2/v2/users/me")]),
         spent={("arm", 0): 1}), "reversal", "reversal"),
    # ticket 07: under `capture --abort` every write past class 3 is recorded, never sent (any origin); reads pass
    ("capture --abort: armed write", R("POST", "/api2/v2/lists"), Run(proof=LIST, capture_abort=True),
     "refused", "capture_abort"),
    ("capture --abort: unarmed write", R("DELETE", "/api2/v2/lists/1"), Run(capture_abort=True),
     "refused", "capture_abort"),
    ("capture --abort: the armed proof's undo", R("DELETE", "/api2/v2/lists/9"),
     Run(proof=LIST, capture_abort=True, spent={("arm", 0): 1}, created=frozenset({"9"})), "refused", "capture_abort"),
    ("capture --abort: Critical stays critical", R("POST", "/api2/v2/payouts/requests", {"withdrawal_amount": 1}),
     Run(proof=LIST, capture_abort=True), "refused", "critical"),
    ("capture --abort: a read passes", R("GET", "/api2/v2/lists"), Run(proof=LIST, capture_abort=True),
     "read", "read"),
    # 4. arming, count, undo, irreversible under the owner's named go
    ("no armed proof", R("POST", "/api2/v2/lists"), Run(), "refused", "unarmed"),
    ("write not armed", R("POST", "/api2/v2/vault/lists"), Run(proof=LIST), "refused", "unarmed"),
    ("OF telemetry (Relay backstop), unarmed", R("POST", "/api2/v2/log", {}), Run(proof=LIST), "refused", "critical"),
    ("armed write, first", R("POST", "/api2/v2/lists"), Run(proof=LIST), "allow", "allow"),
    ("over count (default one)", R("POST", "/api2/v2/lists"), Run(proof=LIST, spent={("arm", 0): 1}),
     "refused", "over_count"),
    ("under a max of two", R("POST", "/api2/v2/lists"),
     Run(proof=P(arm=[Write("POST", "/api2/v2/lists", max=2)], undo=[Write("DELETE", "/api2/v2/lists/{id}")]),
         spent={("arm", 0): 1}), "allow", "allow"),
    ("over a max of two", R("POST", "/api2/v2/lists"),
     Run(proof=P(arm=[Write("POST", "/api2/v2/lists", max=2)], undo=[Write("DELETE", "/api2/v2/lists/{id}")]),
         spent={("arm", 0): 2}), "refused", "over_count"),
    ("armed body differs", R("POST", "/api2/v2/lists", {"name": "real list"}),
     Run(proof=armed("POST", "/api2/v2/lists", body_must={"name": "oi-proof-r1"})), "refused", "unarmed"),
    ("armed body matches", R("POST", "/api2/v2/lists", {"name": "oi-proof-r1"}),
     Run(proof=armed("POST", "/api2/v2/lists", body_must={"name": "oi-proof-r1"})), "allow", "allow"),
    ("armed write, proof declares no undo", R("POST", "/api2/v2/lists"),
     Run(proof=armed("POST", "/api2/v2/lists", undo=())), "refused", "no_undo"),
    ("irreversible, go names it", R("POST", "/api2/v2/posts/9/report"),
     Run(proof=IRREV, owner_go=frozenset({"chat.report"})), "allow", "allow"),
    ("irreversible, go names another", R("POST", "/api2/v2/posts/9/report"),
     Run(proof=IRREV, owner_go=frozenset({"chat.other"})), "refused", "no_undo"),
    ("irreversible, no go", R("POST", "/api2/v2/posts/9/report"), Run(proof=IRREV), "refused", "no_undo"),
    ("irreversible on a Critical path, go given", R("POST", "/api2/v2/payouts/requests"),
     Run(proof=P(arm=[Write("POST", "/api2/v2/payouts/requests")], tags={"irreversible"}, id="stmt.withdraw"),
         owner_go=frozenset({"stmt.withdraw"})), "refused", "critical"),
    ("irreversible on the Relay backstop (non-GET /sessions), go given", R("DELETE", "/api2/v2/sessions"),
     Run(proof=P(arm=[Write("DELETE", "/api2/v2/sessions")], tags={"irreversible", "lockout"}, id="sec.close-all"),
         owner_go=frozenset({"sec.close-all"}), lockout=True), "refused", "critical"),
    ("irreversible on the Relay backstop (/log), go given", R("POST", "/api2/v2/log"),
     Run(proof=P(arm=[Write("POST", "/api2/v2/log")], tags={"irreversible"}, id="x.log"),
         owner_go=frozenset({"x.log"})), "refused", "critical"),
    # 5. kinds; stream and lockout by tag or by the guard's own path lists
    ("OAuth proof, armed write", R("POST", "/api2/v2/lists"), Run(proof=armed("POST", "/api2/v2/lists", kind="oauth")),
     "refused", "oauth"),
    ("mocked proof under --of live", R("POST", "/api2/v2/lists"),
     Run(proof=armed("POST", "/api2/v2/lists", kind="mocked")), "refused", "mocked"),
    ("mocked proof under --of fake", R("POST", "/api2/v2/lists"),
     Run(proof=armed("POST", "/api2/v2/lists", kind="mocked"), of="fake"), "allow", "allow"),
    ("stream by tag, no go", R("POST", "/api2/v2/x/live", {"a": 1}),
     Run(proof=armed("POST", "/api2/v2/x/live", body_must={"a": 1}, tags={"stream_start"})), "refused", "stream"),
    ("stream by tag, go and pinned body", R("POST", "/api2/v2/x/live", {"a": 1}),
     Run(proof=armed("POST", "/api2/v2/x/live", body_must={"a": 1}, tags={"stream_start"}),
         owner_go=frozenset({"stream"})), "allow", "allow"),
    ("stream by tag, go, other body", R("POST", "/api2/v2/x/live", {"a": 2}),
     Run(proof=armed("POST", "/api2/v2/x/live", body_must={"a": 1}, tags={"stream_start"}),
         owner_go=frozenset({"stream"})), "refused", "unarmed"),
    ("stream by path, tag forgotten, go, no body_must", R("POST", "/api2/v2/streams", {"description": "x"}),
     Run(proof=armed("POST", "/api2/v2/streams"), owner_go=frozenset({"stream"})), "refused", "stream"),
    ("stream by path, tag forgotten, go and pinned body", R("POST", "/api2/v2/streams", {"description": "x"}),
     Run(proof=armed("POST", "/api2/v2/streams", body_must={"description": "x"}), owner_go=frozenset({"stream"})),
     "allow", "allow"),
    ("stream by path, pinned body, no go", R("POST", "/api2/v2/streams", {"description": "x"}),
     Run(proof=armed("POST", "/api2/v2/streams", body_must={"description": "x"})), "refused", "stream"),
    ("lockout by tag, no --lockout", R("POST", "/api2/v2/users/me/settings/geo", {"v": "AQ"}),
     Run(proof=armed("POST", "/api2/v2/users/me/settings/geo", body_must={"v": "AQ"}, tags={"lockout"})),
     "refused", "lockout"),
    ("lockout by tag, --lockout and pinned body", R("POST", "/api2/v2/users/me/settings/geo", {"v": "AQ"}),
     Run(proof=armed("POST", "/api2/v2/users/me/settings/geo", body_must={"v": "AQ"}, tags={"lockout"}),
         lockout=True), "allow", "allow"),
    ("lockout by tag, --lockout, no body_must", R("POST", "/api2/v2/users/me/settings/geo", {"v": "AQ"}),
     Run(proof=armed("POST", "/api2/v2/users/me/settings/geo", tags={"lockout"}), lockout=True), "refused", "lockout"),
    ("lockout by tag, --lockout, other body", R("POST", "/api2/v2/users/me/settings/geo", {"v": "DE"}),
     Run(proof=armed("POST", "/api2/v2/users/me/settings/geo", body_must={"v": "AQ"}, tags={"lockout"}),
         lockout=True), "refused", "unarmed"),
    ("lockout by path, tag forgotten, --lockout, no body_must", R("PATCH", "/api2/v2/users/me/blocked-ips", IPS),
     Run(proof=armed("PATCH", "/api2/v2/users/me/blocked-ips"), lockout=True), "refused", "lockout"),
    ("lockout by path, tag forgotten, --lockout and pinned body", R("PATCH", "/api2/v2/users/me/blocked-ips", IPS),
     Run(proof=armed("PATCH", "/api2/v2/users/me/blocked-ips", body_must=IPS), lockout=True), "allow", "allow"),
    ("lockout by path, pinned body, no --lockout", R("PATCH", "/api2/v2/users/me/blocked-ips", IPS),
     Run(proof=armed("PATCH", "/api2/v2/users/me/blocked-ips", body_must=IPS)), "refused", "lockout"),
    ("lockout by body key, tag forgotten, no body_must", R("PATCH", "/api2/v2/users/me/settings/security",
                                                           {"blockedCountries": ["AQ"]}),
     Run(proof=armed("PATCH", "/api2/v2/users/me/settings/security"), lockout=True), "refused", "lockout"),
    ("same-path lockout revert, pinned, after the write", R("PATCH", "/api2/v2/users/me/blocked-ips", {"ips": []}),
     Run(proof=L2, lockout=True, spent={("arm", 0): 1}), "reversal", "reversal"),
    ("same-path lockout write again, after the write", R("PATCH", "/api2/v2/users/me/blocked-ips", IPS),
     Run(proof=L2, lockout=True, spent={("arm", 0): 1}), "refused", "over_count"),
    ("same-path lockout revert body before the write", R("PATCH", "/api2/v2/users/me/blocked-ips", {"ips": []}),
     Run(proof=L2, lockout=True), "refused", "unarmed"),
    # 6. messages: the Proof fan alone; publish only for an id this proof created
    ("chat send, Proof fan unset", R("POST", f"/api2/v2/chats/{FAN}/messages", {"text": "hi"}),
     Run(proof=armed("POST", "/api2/v2/chats/{fan}/messages", tags={"message"})), "refused", "mass_message"),
    ("chat send to the Proof fan", R("POST", f"/api2/v2/chats/{FAN}/messages", {"text": "hi"}),
     Run(proof=armed("POST", "/api2/v2/chats/{fan}/messages", tags={"message"}), proof_fan=FAN), "allow", "allow"),
    ("chat send to another Fan", R("POST", "/api2/v2/chats/556/messages", {"text": "hi"}),
     Run(proof=armed("POST", "/api2/v2/chats/{fan}/messages", tags={"message"}), proof_fan=FAN),
     "refused", "mass_message"),
    # ticket 73: stream block path segment = u{Proof fan}
    ("stream block of the Proof fan", R("POST", f"/api2/v2/streams/users/u{FAN}/block"),
     Run(proof=armed("POST", "/api2/v2/streams/users/{fan}/block"), proof_fan=FAN), "allow", "allow"),
    ("stream block of another user", R("POST", "/api2/v2/streams/users/someone/block"),
     Run(proof=armed("POST", "/api2/v2/streams/users/{fan}/block"), proof_fan=FAN), "refused", "mass_message"),
    ("stream block, Proof fan unset", R("POST", f"/api2/v2/streams/users/u{FAN}/block"),
     Run(proof=armed("POST", "/api2/v2/streams/users/{fan}/block")), "refused", "mass_message"),
    # ticket 73: the unblock undo's row id = the Proof fan's user id; another created id is refused
    ("stream unblock of the Proof fan", R("DELETE", f"/api2/v2/streams/users/{FAN}/block"),
     Run(proof=armed("POST", "/api2/v2/streams/users/{fan}/block", undo=(UNBLOCK,)), proof_fan=FAN,
         spent={("arm", 0): 1}, created=frozenset({FAN, "556"})), "reversal", "reversal"),
    ("stream unblock of another id", R("DELETE", "/api2/v2/streams/users/556/block"),
     Run(proof=armed("POST", "/api2/v2/streams/users/{fan}/block", undo=(UNBLOCK,)), proof_fan=FAN,
         spent={("arm", 0): 1}, created=frozenset({FAN, "556"})), "refused", "mass_message"),
    ("queue, Proof fan alone, scheduled", R("POST", "/api2/v2/messages/queue",
                                            {"userIds": [555], "userLists": [], "scheduledDate": QD}),
     Run(proof=QUEUE, proof_fan=FAN), "allow", "allow"),
    ("queue, Proof fan unset", R("POST", "/api2/v2/messages/queue",
                                 {"userIds": [555], "userLists": [], "scheduledDate": QD}),
     Run(proof=QUEUE), "refused", "mass_message"),
    ("queue with an extra id", R("POST", "/api2/v2/messages/queue",
                                 {"userIds": [555, 556], "userLists": [], "scheduledDate": QD}),
     Run(proof=QUEUE, proof_fan=FAN), "refused", "mass_message"),
    ("queue with an OF list", R("POST", "/api2/v2/messages/queue",
                                {"userIds": [555], "userLists": ["fans"], "scheduledDate": QD}),
     Run(proof=QUEUE, proof_fan=FAN), "refused", "mass_message"),
    ("queue to a list only", R("POST", "/api2/v2/messages/queue",
                               {"userIds": [], "userLists": [123], "scheduledDate": QD}),
     Run(proof=QUEUE, proof_fan=FAN), "refused", "mass_message"),
    ("queue edit of an item this proof did not create", R("PUT", "/api2/v2/messages/queue/88",
                                                          {"userIds": [555], "userLists": [], "scheduledDate": QD}),
     Run(proof=armed("PUT", "/api2/v2/messages/queue/{id}"), proof_fan=FAN), "refused", "mass_message"),
    ("queue edit of its own item", R("PUT", "/api2/v2/messages/queue/88",
                                     {"userIds": [555], "userLists": [], "scheduledDate": QD}),
     Run(proof=armed("PUT", "/api2/v2/messages/queue/{id}"), proof_fan=FAN, created=frozenset({"88"})),
     "allow", "allow"),
    ("publish, id created in this proof (no Proof fan needed)", R("PUT", "/api2/v2/schedules/777/publish"),
     Run(proof=PUBLISH, quiet_hour=QUIET, created=frozenset({"777"})), "allow", "allow"),
    ("publish, any other id", R("PUT", "/api2/v2/schedules/778/publish"),
     Run(proof=PUBLISH, quiet_hour=QUIET, created=frozenset({"777"})), "refused", "mass_message"),
    # 7. posts: scheduled 30+ minutes ahead, or delete-at-once
    ("post scheduled 29 min ahead", R("POST", "/api2/v2/posts", sched(29)), Run(proof=armed("POST", "/api2/v2/posts")),
     "refused", "post"),
    ("post scheduled 30 min ahead", R("POST", "/api2/v2/posts", sched(30)), Run(proof=armed("POST", "/api2/v2/posts")),
     "allow", "allow"),
    ("post scheduled 31 min ahead", R("POST", "/api2/v2/posts", sched(31)), Run(proof=armed("POST", "/api2/v2/posts")),
     "allow", "allow"),
    ("post with a date but not isScheduled", R("POST", "/api2/v2/posts", {"scheduledDate": sched(31)["scheduledDate"]}),
     Run(proof=armed("POST", "/api2/v2/posts")), "refused", "post"),
    ("post now, no delete-at-once", R("POST", "/api2/v2/posts", {"text": "x"}),
     Run(proof=armed("POST", "/api2/v2/posts", tags={"post"}), quiet_hour=QUIET), "refused", "post"),
    ("post now, delete-at-once", R("POST", "/api2/v2/posts", {"text": "x"}), Run(proof=NOW_POST, quiet_hour=QUIET),
     "allow", "allow"),
    # fan-visible publishes: 2 for the whole effort, one attempt each, quiet hour, immediate undo
    ("fan-visible, second of the effort", R("POST", "/api2/v2/posts", {"text": "x"}),
     Run(proof=NOW_POST, quiet_hour=QUIET, fan_visible_done=("queue.publish-now",)), "allow", "allow"),
    ("fan-visible, third of the effort", R("POST", "/api2/v2/posts", {"text": "x"}),
     Run(proof=NOW_POST, quiet_hour=QUIET, fan_visible_done=("a", "b")), "refused", "fan_visible"),
    ("fan-visible, retry of the same proof", R("POST", "/api2/v2/posts", {"text": "x"}),
     Run(proof=NOW_POST, quiet_hour=QUIET, fan_visible_done=("post.now",)), "refused", "fan_visible"),
    ("fan-visible, no quiet hour declared", R("POST", "/api2/v2/posts", {"text": "x"}), Run(proof=NOW_POST),
     "refused", "fan_visible"),
    ("fan-visible, before the quiet hour", R("POST", "/api2/v2/posts", {"text": "x"}, at=QUIET - timedelta(seconds=1)),
     Run(proof=NOW_POST, quiet_hour=QUIET), "refused", "fan_visible"),
    ("fan-visible, after the quiet hour", R("POST", "/api2/v2/posts", {"text": "x"}, at=QUIET + timedelta(minutes=60)),
     Run(proof=NOW_POST, quiet_hour=QUIET), "refused", "fan_visible"),
    ("publish without an immediate undo declared", R("PUT", "/api2/v2/schedules/777/publish"),
     Run(proof=armed("PUT", "/api2/v2/schedules/{id}/publish", tags={"post"}), quiet_hour=QUIET,
         created=frozenset({"777"})), "refused", "fan_visible"),
    ("queue send-now (no date), no immediate unsend", R("POST", "/api2/v2/messages/queue",
                                                       {"userIds": [555], "userLists": []}),
     Run(proof=QUEUE, **FAN_RUN), "refused", "fan_visible"),
    ("queue send-now, immediate unsend, quiet hour", R("POST", "/api2/v2/messages/queue",
                                                      {"userIds": [555], "userLists": []}),
     Run(proof=armed("POST", "/api2/v2/messages/queue", tags={"message", "delete_at_once"}), **FAN_RUN),
     "allow", "allow"),
    ("tagged fan-visible, outside the quiet hour", R("POST", "/api2/v2/posts/9/cotag-publish", {}, at=QUIET - timedelta(hours=2)),
     Run(proof=armed("POST", "/api2/v2/posts/{id}/cotag-publish", tags={"fan_visible", "delete_at_once"}),
         quiet_hour=QUIET), "refused", "fan_visible"),
    # 8. reversal: matches the declared undo of a write already allowed
    ("reversal of an allowed write", R("DELETE", "/api2/v2/lists/901"),
     Run(proof=TRACER, spent={("arm", 0): 1}, created=frozenset({"901"})), "reversal", "reversal"),
    ("undo of an id this proof did not create", R("DELETE", "/api2/v2/lists/902"),
     Run(proof=TRACER, spent={("arm", 0): 1}, created=frozenset({"901"})), "refused", "unarmed"),
    ("undo before any write was allowed", R("PUT", "/api2/v2/users/me/settings/notifications", {"push": 1}),
     Run(proof=armed("PATCH", "/api2/v2/users/me/settings/notifications",
                     undo=[Write("PUT", "/api2/v2/users/me/settings/notifications")])), "refused", "unarmed"),
    ("second reversal over its count", R("DELETE", "/api2/v2/lists/901"),
     Run(proof=TRACER, spent={("arm", 0): 1, ("undo", 0): 1}, created=frozenset({"901"})), "refused", "over_count"),
    # ticket 30: OF's hide (Remove from vault) as an undo, its pinned body's `{media}` bound to a registered id;
    # ticket 131: each placeholder binds only to ids of its own kind (`{id}` to created, `{media}` to keys["media"])
    ("hide of a registered vault media id", R("PUT", "/api2/v2/vault/media/hidden", {"mediaIds": [77]}),
     Run(proof=RECORD, spent={("arm", 1): 1}, **MEDIA77), "reversal", "reversal"),
    ("hide of a media id not registered", R("PUT", "/api2/v2/vault/media/hidden", {"mediaIds": [78]}),
     Run(proof=RECORD, spent={("arm", 1): 1}, **MEDIA77), "refused", "unarmed"),
    ("hide of two media ids", R("PUT", "/api2/v2/vault/media/hidden", {"mediaIds": [77, 78]}),
     Run(proof=RECORD, spent={("arm", 1): 1}, created=frozenset({"9"}), keys={"media": frozenset({"77", "78"})}),
     "refused", "unarmed"),
    ("hide with an extra body key", R("PUT", "/api2/v2/vault/media/hidden", {"mediaIds": [77], "all": True}),
     Run(proof=RECORD, spent={("arm", 1): 1}, **MEDIA77), "refused", "unarmed"),
    ("hide before any write was allowed", R("PUT", "/api2/v2/vault/media/hidden", {"mediaIds": [77]}),
     Run(proof=RECORD, keys={"media": frozenset({"77"})}), "refused", "unarmed"),
    ("second hide over its count", R("PUT", "/api2/v2/vault/media/hidden", {"mediaIds": [77]}),
     Run(proof=RECORD, spent={("arm", 1): 1, ("undo", 1): 1}, **MEDIA77), "refused", "over_count"),
    ("post DELETE of the created post id", R("DELETE", "/api2/v2/posts/9"),
     Run(proof=RECORD, spent={("arm", 1): 1}, **MEDIA77), "reversal", "reversal"),
    ("post DELETE of a registered media id refused", R("DELETE", "/api2/v2/posts/77"),
     Run(proof=RECORD, spent={("arm", 1): 1}, **MEDIA77), "refused", "unarmed"),
    ("hide of the created post id refused", R("PUT", "/api2/v2/vault/media/hidden", {"mediaIds": [9]}),
     Run(proof=RECORD, spent={("arm", 1): 1}, **MEDIA77), "refused", "unarmed"),
    ("post DELETE of an id an upload arm's reply created refused", R("DELETE", "/api2/v2/posts/55"),
     Run(proof=RECORD, spent={("arm", 1): 1}, **MEDIA77), "refused", "unarmed"),
    ("an arm's pinned body is exact: a brace value is literal", R("POST", "/api2/v2/lists", {"name": "abc"}),
     Run(proof=armed("POST", "/api2/v2/lists", body_must={"name": "{name}"})), "refused", "unarmed"),
    # 9. anything else armed passes
    ("tracer create", R("POST", "/api2/v2/lists", {"name": "oi-proof-r1"}), Run(proof=TRACER), "allow", "allow"),
]


@pytest.mark.parametrize("request_, run, kind, cls", [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_decide(request_, run, kind, cls):
    v = decide(request_, run)
    assert (v.kind, v.cls) == (kind, cls), v.reason
    assert v.reason


CRITICAL = [
    ("POST", "/api2/v2/payouts/requests", {"amount": 20}),       # withdrawal
    ("PATCH", "/api2/v2/payouts/requests", {"frequency": "x"}),  # payout frequency
    ("POST", "/api2/v2/bank/accounts", {}),
    ("POST", "/api2/v2/payments/cards", {}),
    ("PUT", "/api2/v2/payment-methods/default", {}),
    ("POST", "/api2/v2/payouts/methods", {}),
    ("POST", "/api2/v2/users/me/dac7", {}),
    ("POST", "/api2/v2/support/tickets", {}),
    ("PATCH", "/api2/v2/users/me/password", {}),
    ("POST", "/api2/v2/users/me/email", {}),
    ("POST", "/api2/v2/users/me/phone", {}),
    ("PATCH", "/api2/v2/users/me/username", {}),
    ("POST", "/api2/v2/users/me/2fa", {}),
    ("POST", "/api2/v2/users/me/passwordless", {}),
    ("POST", "/api2/v2/users/delete/request", {}),               # Relay backstop
    ("POST", "/api2/v2/users/logout", {}),                       # Relay backstop
    ("PATCH", "/api2/v2/users/me", {"username": "x"}),           # sign-in keys on a profile update
    ("PATCH", "/api2/v2/users/me", {"email": "x"}),
    ("PATCH", "/api2/v2/users/me", {"phone": "x"}),
    ("PATCH", "/api2/v2/users/me", {"password": "x", "about": "y"}),
]
EVERY_FLAG = dict(of="live", proof_fan=FAN, owner_go=frozenset({"stream", "p.x"}), lockout=True, quiet_hour=QUIET)


@pytest.mark.parametrize("method,path,body", CRITICAL, ids=[f"{m} {p} {sorted(b)}" for m, p, b in CRITICAL])
@pytest.mark.parametrize("arming", ["unarmed", "armed", "armed irreversible, every flag"])
def test_critical_refused_armed_or_not(method, path, body, arming):
    if arming == "unarmed":
        run = Run()
    elif arming == "armed":
        run = Run(proof=armed(method, path, undo=[Write(method, path)]))
    else:
        run = Run(proof=P(arm=[Write(method, path)], tags={"irreversible"}), **EVERY_FLAG)
    v = decide(R(method, path, body), run)
    assert (v.kind, v.cls, v.capture) == ("refused", "critical", "")


@pytest.mark.parametrize("method,path,body", CRITICAL[:3], ids=[p for _, p, _ in CRITICAL[:3]])
def test_critical_in_capture_abort_mode_is_an_aborted_capture(method, path, body):
    v = decide(R(method, path, body), Run(proof=armed(method, path, undo=[Write(method, path)]), capture_abort=True))
    assert (v.kind, v.cls, v.capture) == ("refused", "critical", "aborted")


DENIED = [  # service/of_client.py:343-360 `_denied`, one row per path
    ("bugs.onlyfans.com", "POST", "/api2/v2/report"),
    ("onlyfans.com", "POST", "/api2/v2/users/logout"),
    ("onlyfans.com", "POST", "/api2/v2/users/delete/request"),
    ("onlyfans.com", "POST", "/api2/v2/log"),
    ("onlyfans.com", "DELETE", "/api2/v2/sessions"),
    ("onlyfans.com", "PATCH", "/api2/v2/sessions/7"),
]


@pytest.mark.parametrize("host,method,path", DENIED, ids=[f"{m} {h}{p}" for h, m, p in DENIED])
@pytest.mark.parametrize("abort", [False, True], ids=["live", "capture-abort"])
def test_relay_backstop_refused_with_every_flag_pin_and_go(host, method, path, abort):
    body = {"k": 1}
    proof = P(arm=[Write(method, path, body_must=body)], undo=[Write(method, path, body_must={"k": 0})],
              tags={"lockout", "irreversible", "stream_start"})
    run = Run(proof=proof, capture_abort=abort, **EVERY_FLAG)
    for p in (proof, P(arm=[Write(method, path, body_must=body)], tags={"lockout", "irreversible"})):
        v = decide(R(method, path, body, host=host), Run(**{**run.__dict__, "proof": p}))
        assert (v.kind, v.cls, v.capture) == ("refused", "critical", "aborted" if abort else "")
        assert "backstop" in v.reason


def test_irreversible_allow_is_marked_not_reversible_owner_go():
    v = decide(R("POST", "/api2/v2/posts/9/report"), Run(proof=IRREV, owner_go=frozenset({"chat.report"})))
    assert v.reason == "not reversible, owner go"


def test_mocked_under_live_is_recorded_not_run_live():
    v = decide(R("POST", "/api2/v2/lists"), Run(proof=armed("POST", "/api2/v2/lists", kind="mocked")))
    assert "mocked: not run live" in v.reason


@pytest.mark.parametrize("request_, run, fan_visible", [
    (R("POST", "/api2/v2/posts", {"text": "x"}), Run(proof=NOW_POST, quiet_hour=QUIET), True),
    (R("PUT", "/api2/v2/schedules/777/publish"), Run(proof=PUBLISH, quiet_hour=QUIET, created=frozenset({"777"})), True),
    (R("POST", "/api2/v2/posts", sched(31)), Run(proof=armed("POST", "/api2/v2/posts")), False),
    (R("POST", "/api2/v2/lists"), Run(proof=LIST), False),
], ids=["post now", "publish", "scheduled post", "list"])
def test_allowed_fan_visible_publish_is_flagged_for_the_effort_count(request_, run, fan_visible):
    v = decide(request_, run)
    assert v.kind == "allow" and v.fan_visible is fan_visible


# A post or queue write is not fan-visible only when scheduled at least POST_LEAD ahead, never on isScheduled alone
# (review round 2): a near, past or unreadable date publishes now, so delete_at_once meets the cap and quiet hour.
NEAR = {"+1 min": sched(1), "past": sched(-5), "malformed": {"isScheduled": 1, "scheduledDate": "soon"},
        "no isScheduled": {"scheduledDate": sched(45)["scheduledDate"]}}


@pytest.mark.parametrize("of", ["live", "fake"])
@pytest.mark.parametrize("body", NEAR.values(), ids=NEAR.keys())
def test_delete_at_once_post_near_scheduled_is_fan_visible(body, of):
    req = R("POST", "/api2/v2/posts", body)
    v = decide(req, Run(proof=NOW_POST, of=of))   # no quiet hour declared
    assert (v.kind, v.cls) == ("refused", "fan_visible"), v.reason
    v = decide(req, Run(proof=NOW_POST, of=of, quiet_hour=QUIET))
    assert (v.kind, v.fan_visible) == ("allow", True), v.reason
    v = decide(req, Run(proof=NOW_POST, of=of, quiet_hour=QUIET, fan_visible_done=("post.now",)))
    assert (v.kind, v.cls) == ("refused", "fan_visible"), v.reason   # one attempt
    v = decide(req, Run(proof=NOW_POST, of=of, quiet_hour=QUIET, fan_visible_done=("a", "b")))
    assert (v.kind, v.cls) == ("refused", "fan_visible"), v.reason   # the effort's cap


@pytest.mark.parametrize("of", ["live", "fake"])
def test_delete_at_once_post_far_scheduled_is_not_fan_visible(of):
    v = decide(R("POST", "/api2/v2/posts", sched(31)), Run(proof=NOW_POST, of=of))
    assert (v.kind, v.fan_visible) == ("allow", False), v.reason


def test_verdict_names_the_spent_key():
    assert decide(R("POST", "/api2/v2/lists"), Run(proof=TRACER)).key == ("arm", 0)
    rev = decide(R("DELETE", "/api2/v2/lists/901"), Run(proof=TRACER, spent={("arm", 0): 1}, created=frozenset({"901"})))
    assert rev.key == ("undo", 0)


@pytest.mark.parametrize("kw", [dict(kind="manual"), dict(tags=frozenset({"lockot"})),
                                dict(arm=(Write("POST", "/api2/v2/lists"),), effect=None)],
                         ids=["unknown kind", "unknown tag", "armed write without effect"])
def test_proof_shape_rejects_bad_definitions(kw):
    base = dict(id="p", phase=0, page="collections/index", control="x", kind="live")
    with pytest.raises(ValueError):
        Proof(**{**base, **kw})


A, B = P(id="a"), P(id="b")
L1 = P(id="sec.block-ip", tags={"lockout"})


def test_order_puts_lockout_proofs_last_tag_or_path():
    assert [p.id for p in order([L1, A, L2, B])] == ["a", "b", "sec.block-ip", "sec.forgot-tag"]


def test_order_refuses_a_non_lockout_proof_after_a_lockout_one():
    with pytest.raises(ValueError, match="'a' after"):
        order([A], ran=[L1])
    assert [p.id for p in order([L2], ran=[L1])] == ["sec.forgot-tag"]


def test_no_script_takes_a_stdlib_module_name():
    scripts = [p.stem for p in HERE.glob("*.py")]
    assert "proof_core" in scripts
    assert [s for s in scripts if s in sys.stdlib_module_names] == []


# ── ticket 03: the driver's wire check (step 9), the Undo log fold and its Markdown, the tracer's effect ──
from proof_core import wire_problems  # noqa: E402
from undo_log import undo_markdown, undo_rows  # noqa: E402


def W(method, path, verdict="allow", cls=None, status=200, reason=""):
    """One folded wire log line, as GET /__proof/wire answers it."""
    return {"origin": "relay", "method": method, "host": "onlyfans.com", "path": path, "query": "", "body": None,
            "status": status, "verdict": verdict, "class": cls or verdict, "reason": reason, "proof": "p"}


READ_PROOF = P(id="p.read")


@pytest.mark.parametrize("proof, entries, errors, want", [
    (TRACER, [W("GET", "/api2/v2/lists", "read"), W("POST", "/api2/v2/lists")], [], []),
    (TRACER, [W("GET", "/api2/v2/lists", "read")], [], ["no write sent; armed: POST /api2/v2/lists"]),
    (TRACER, [W("POST", "/api2/v2/labels", "refused", "unarmed", None, "POST /labels is not armed")], [],
     ["no write sent; armed: POST /api2/v2/lists",
      "refused by the Live guard: POST /api2/v2/labels (unarmed: POST /labels is not armed)"]),
    (TRACER, [W("POST", "/api2/v2/lists"), W("POST", "/api2/v2/lists", "refused", "over_count", None, "spent")], [],
     ["refused by the Live guard: POST /api2/v2/lists (over_count: spent)"]),
    (READ_PROOF, [W("GET", "/api2/v2/lists", "read")], [], []),
    (READ_PROOF, [W("GET", "/api2/v2/lists", "read"), W("POST", "/api2/v2/lists", "refused", "unarmed")], [],
     ["refused by the Live guard: POST /api2/v2/lists (unarmed: )", "read proof sent a write: POST /api2/v2/lists"]),
    (TRACER, [], [("POST", "/api/of/v2/lists", 403)],
     ["no write sent; armed: POST /api2/v2/lists",
      "Relay's own backstop refused POST /api/of/v2/lists (403): no wire line, nothing reached OnlyFans"]),
    (TRACER, [W("POST", "/api2/v2/lists", status=500)], [("POST", "/api/of/v2/lists", 502)], []),
    (TRACER, [W("GET", "/api2/v2/lists", "read"), W("POST", "/api2/v2/lists")], [("GET", "/api/of/v2/vault", 502)], []),
], ids=["armed write sent", "no write", "other write refused", "double click over count", "read proof, reads only",
        "read proof with a stray write", "backstop: error with no wire line", "OF error has its wire line",
        "a read error with its read line"])
def test_wire_problems(proof, entries, errors, want):
    assert wire_problems(proof, entries, errors) == want


def test_undo_rows_fold_snapshots_last_wins_in_row_order():
    lines = [{"row": 2, "proof": "b", "state": "pending"}, {"row": 1, "proof": "a", "state": "pending"},
             {"row": 1, "proof": "a", "state": "undone", "of_id": "7"}, {"row": 2, "proof": "b", "state": "FAILED"}]
    assert [(r["row"], r["state"]) for r in undo_rows(lines)] == [(1, "undone"), (2, "FAILED")]
    assert undo_rows(lines)[0]["of_id"] == "7"


def test_undo_markdown_one_table_row_per_entry():
    row = {"row": 1, "proof": "tracer.create-list", "write": {"method": "POST", "path": "/api2/v2/lists",
           "narrowed": "none"}, "of_id": "900000000000000001",
           "reversal": {"method": "DELETE", "path": "/api2/v2/lists/900000000000000001", "status": 200},
           "reads": {"before": ["Soak list 1"], "after_write": ["Soak list 1", "oi-proof-x"],
                     "after_undo": ["Soak list 1"], "equal": True},
           "state": "undone", "evidence": ["trigger.png", "settled.png"]}
    md = undo_markdown([row]).splitlines()
    assert md[0].startswith("| # | proof | write |") and len(md) == 3
    cells = [c.strip() for c in md[2].strip("|").split("|")]
    assert cells[:4] == ["1", "tracer.create-list", "POST /api2/v2/lists", "none"]
    assert "DELETE /api2/v2/lists/900000000000000001 → 200" in cells and "yes" in cells and "undone" in cells
    assert undo_markdown([{"row": 2, "proof": "p", "state": "pending", "write": {"method": "POST",
                                                                                  "path": "/x|y"}}]).count("\\|") == 1


# ── verify_undo: the row-closing decision (undone iff it returns no problems) ──
from undo_log import append_jsonl, read_undo_log, reads_equal, verify_undo  # noqa: E402

BEFORE = [["1", "Soak list 1"]]
AFTER = [["1", "Soak list 1"], ["2", "oi-proof-x"]]


def ROW_(effect=True, reversal=("DELETE", "/api2/v2/lists/2"), before=BEFORE, after_undo=BEFORE, seq=3):
    """A row as the driver hands it to verify_undo before closing it; its reversal names the wire seq it caused."""
    rev = {"method": reversal[0], "path": reversal[1], "seq": seq} if reversal else {}
    return {"row": 1, "proof": "tracer.create-list", "write": {"method": "POST", "path": "/api2/v2/lists"},
            "of_id": "2", "effect": effect, "reversal": rev,
            "reads": {"before": before, "after_write": AFTER, "after_undo": after_undo}}


def WQ(seq, method, path, verdict="allow", cls=None, status=200):
    return {**W(method, path, verdict, cls, status), "seq": seq}


DEL_OK = WQ(3, "DELETE", "/api2/v2/lists/2", "reversal")


@pytest.mark.parametrize("wire, row, want", [
    ([DEL_OK], ROW_(), []),
    ([DEL_OK], ROW_(before=[("1", "Soak list 1")]), []),
    ([DEL_OK], ROW_(effect=False),
     ["row 1: no-op write: the declared effect did not hold after POST /api2/v2/lists"]),
    ([DEL_OK], ROW_(after_undo=AFTER), ["row 1: the after-undo read differs from the before read"]),
    ([WQ(3, "DELETE", "/api2/v2/lists/2", "reversal", status=500)], ROW_(after_undo=AFTER),
     ["row 1: reversal DELETE /api2/v2/lists/2 answered 500",
      "row 1: the after-undo read differs from the before read"]),
    ([], ROW_(reversal=None, after_undo=AFTER),
     ["row 1: no reversal of POST /api2/v2/lists on the wire",
      "row 1: the after-undo read differs from the before read"]),
    ([WQ(3, "DELETE", "/api2/v2/lists/2", "refused", "unarmed", "refused")], ROW_(after_undo=AFTER),
     ["row 1: no reversal of POST /api2/v2/lists on the wire",
      "row 1: the after-undo read differs from the before read"]),
    ([DEL_OK], ROW_(seq=None), ["row 1: no reversal of POST /api2/v2/lists on the wire"]),
    ([DEL_OK, WQ(7, "DELETE", "/api2/v2/lists/2", "reversal", status=500)], ROW_(seq=7),
     ["row 1: reversal DELETE /api2/v2/lists/2 answered 500"]),
], ids=["complete", "tuples equal their JSON lists", "no-op write", "no-op undo", "failed reversal",
        "no reversal sent", "reversal refused by the guard", "the undo caused no line: an earlier one does not count",
        "its own line failed: an earlier 2xx does not count"])
def test_verify_undo(wire, row, want):
    assert verify_undo(wire, [row]) == want


# ticket 30: a row reversed by more than one request (the post's DELETE, then the hide) checks each on the wire.
HIDE_OK = WQ(4, "PUT", "/api2/v2/vault/media/hidden", "reversal")
TWO = [{"method": "DELETE", "path": "/api2/v2/lists/2", "seq": 3},
       {"method": "PUT", "path": "/api2/v2/vault/media/hidden", "seq": 4}]
UNSENT = {**TWO[1], "seq": None}   # the hide's Relay call caused no wire line


@pytest.mark.parametrize("wire, revs, want", [
    ([DEL_OK, HIDE_OK], TWO, []),
    ([DEL_OK], TWO, ["row 1: no reversal of POST /api2/v2/lists on the wire (PUT /api2/v2/vault/media/hidden)"]),
    ([DEL_OK, WQ(4, "PUT", "/api2/v2/vault/media/hidden", "reversal", status=404)], TWO,
     ["row 1: reversal PUT /api2/v2/vault/media/hidden answered 404"]),
    ([HIDE_OK], TWO[1:], []),
    ([DEL_OK], [], ["row 1: no reversal of POST /api2/v2/lists on the wire"]),
    # ticket 131: the hide is id-less (one path for video and voice); only the line this row's undo caused counts
    ([HIDE_OK, WQ(9, "DELETE", "/api2/v2/lists/2", "reversal")], [{**TWO[0], "seq": 9}, UNSENT],
     ["row 1: no reversal of POST /api2/v2/lists on the wire (PUT /api2/v2/vault/media/hidden)"]),
    ([HIDE_OK, WQ(9, "DELETE", "/api2/v2/lists/2", "reversal"), WQ(10, "PUT", "/api2/v2/vault/media/hidden", "reversal",
                                                                     status=404)],
     [{**TWO[0], "seq": 9}, {**TWO[1], "seq": 10}], ["row 1: reversal PUT /api2/v2/vault/media/hidden answered 404"]),
], ids=["both 2xx", "the hide never sent", "the hide failed", "a shared hide alone (an upload row)",
        "none sent (the hide had no media id)", "an earlier proof's identical hide does not count (none caused)",
        "an earlier proof's identical hide does not count (own failed)"])
def test_verify_undo_checks_every_reversal(wire, revs, want):
    row = {k: v for k, v in ROW_().items() if k != "reversal"} | {"reversals": revs}
    assert verify_undo(wire, [row]) == want


def test_reads_equal_compares_json_values():
    assert reads_equal([("1", "a")], [["1", "a"]]) and reads_equal({"b": 1, "a": 2}, {"a": 2, "b": 1})
    assert not reads_equal([("1", "a")], [["1", "b"]]) and not reads_equal(None, [])


def test_undo_log_append_then_read_folds_snapshots(tmp_path):
    log = tmp_path / "undo-log.jsonl"
    assert read_undo_log(log) == []
    append_jsonl(log, {"row": 1, "proof": "p", "state": "pending"})
    append_jsonl(log, {"row": 1, "proof": "p", "state": "undone"})
    assert read_undo_log(log) == [{"row": 1, "proof": "p", "state": "undone"}]


# ── ticket 05: the whole Undo log check (complete, missing, failed, pending), earlier runs, the lock ──
from proof_core import NOT_REVERSIBLE, lock_decision  # noqa: E402
from undo_log import check_undo_log, pending_rows  # noqa: E402


def WS(seq, method, path, verdict="allow", status=200):
    return {**W(method, path, verdict, status=status), "seq": seq}


def LOG_ROW(state="undone", of_id="2", after_undo=BEFORE, **kw):
    """A row as the Undo log folds it: one allowed write (wire line 2), its reads, its state."""
    return {"row": 1, "proof": "tracer.create-list", "state": state, "wire_seq": 2, "of_id": of_id,
            "write": {"method": "POST", "path": "/api2/v2/lists", "narrowed": "none"},
            "reads": {"before": BEFORE, "after_write": AFTER, "after_undo": after_undo}, **kw}


WIRE_OK = [WS(1, "GET", "/api2/v2/lists", "read"), WS(2, "POST", "/api2/v2/lists"),
           WS(3, "DELETE", "/api2/v2/lists/2", "reversal")]
PENDING_LOST = ("row 1 (tracer.create-list) pending: POST /api2/v2/lists (OnlyFans id unknown, reply lost: "
                "ConnectionError) may be left on the account; check it, then clear the row by hand")


@pytest.mark.parametrize("wire, rows, want", [
    (WIRE_OK, [LOG_ROW()], []),
    (WIRE_OK, [LOG_ROW(state=NOT_REVERSIBLE)], []),
    (WIRE_OK[:2] + [WS(4, "POST", "/api2/v2/labels", "refused")], [LOG_ROW()], []),
    (WIRE_OK, [], ["wire line 2: POST /api2/v2/lists was allowed with no Undo log row"]),
    ([WS(2, "POST", "/api2/v2/lists"), WS(3, "DELETE", "/api2/v2/lists/2", "reversal", 500)],
     [LOG_ROW(state="FAILED", after_undo=AFTER)],
     ['row 1 (tracer.create-list) FAILED, owner action: POST /api2/v2/lists (OnlyFans id 2) left on the account: '
      '["2","oi-proof-x"]']),
    ([WS(2, "POST", "/api2/v2/lists", status="error: ConnectionError")],
     [LOG_ROW(state="pending", of_id=None, after_undo=None, write_status="reply lost: ConnectionError")],
     [PENDING_LOST]),
    ([WS(2, "POST", "/api2/v2/lists"), WS(5, "POST", "/api2/v2/lists")],
     [LOG_ROW(state="session lost")],
     ["row 1 (tracer.create-list) session lost: POST /api2/v2/lists (OnlyFans id 2) not confirmed undone",
      "wire line 5: POST /api2/v2/lists was allowed with no Undo log row"]),
    ([WS(2, "POST", "/api2/v2/lists"), WS(3, "DELETE", "/api2/v2/lists/2", "reversal")],
     [LOG_ROW(state="FAILED", effect=False)],
     ["row 1 (tracer.create-list) FAILED, owner action: confirm POST /api2/v2/lists (OnlyFans id 2) is gone; the "
      "after-undo read shows nothing left"]),
    ([WS(2, "POST", "/api2/v2/lists", status="error: ConnectionError")],
     [LOG_ROW(state="FAILED", of_id=None, write_status="reply lost: ConnectionError",
              found_refused="the Relay refused found id 7: 409 found id refused")],
     ["row 1 (tracer.create-list) FAILED, owner action: confirm POST /api2/v2/lists (OnlyFans id unknown, reply lost: "
      "ConnectionError) is gone; the after-undo read shows nothing left; the Relay refused found id 7: 409 found id "
      "refused"]),
    ([WS(2, "POST", "/api2/v2/lists")], [LOG_ROW(state="FAILED", after_undo={"x": 1})],
     ["row 1 (tracer.create-list) FAILED, owner action: confirm POST /api2/v2/lists (OnlyFans id 2) is gone; the "
      "after-undo read shows no list to compare"]),
], ids=["complete", "not reversible, owner go", "refusals need no row", "missing row", "failed undo",
        "pending (reply lost)", "session lost and a missing row", "failed, nothing left",
        "failed, found id refused", "failed, reads not lists"])
def test_check_undo_log(wire, rows, want):
    assert check_undo_log(wire, rows) == want


# ticket 30: which undo Writes reverse a row, by the arm index the Relay stamps on it; the settle order; the finder.
from undo_log import needs_row_id, row_undos, undo_order  # noqa: E402

UP, POST_ROW = {"row": 1, "arm": 0}, {"row": 2, "arm": 1}


@pytest.mark.parametrize("row, want", [
    (UP, [1]), (POST_ROW, [0, 1]), ({"row": 3}, []), ({"row": 4, "arm": 7}, []),
], ids=["upload row: the hide", "post row: DELETE then the hide", "no arm stamp", "an arm no undo names"])
def test_row_undos_by_the_stamped_arm(row, want):
    assert [i for i, _ in row_undos(RECORD, row)] == want


def test_row_undos_with_reverses_unset_take_every_row():
    assert [i for i, _ in row_undos(TRACER, {"row": 1})] == [0]
    assert [i for i, _ in row_undos(TRACER, {"row": 1, "arm": 0})] == [0]


@pytest.mark.parametrize("rows, want", [
    ([UP, POST_ROW], [2, 1]),
    ([UP | {"row": 1}, UP | {"row": 3}, UP | {"row": 4}, POST_ROW | {"row": 5}], [5, 1, 3, 4]),
    ([{"row": 1}, UP | {"row": 2}], [2, 1]),
], ids=["the post first (DELETE, then the hide), the upload after", "three upload rows keep open order",
        "a row with no undo goes last"])
def test_undo_order(rows, want):
    assert [r["row"] for r in undo_order(RECORD, rows)] == want


@pytest.mark.parametrize("proof, row, want", [
    (RECORD, POST_ROW, True), (RECORD, UP, False), (RECORD, {"row": 3}, False),
    (P(arm=[Write("POST", "/api2/v2/lists")], undo=[Write("DELETE", "/api2/v2/lists/{id}", relay="/api/of/v2/lists/{id}")]),
     {"row": 1, "arm": 0}, True),
], ids=["post row: DELETE by id", "upload row: the hide, keyed on the read", "no undo", "tracer"])
def test_needs_row_id(proof, row, want):
    assert needs_row_id(proof, row) is want


from undo_log import row_undo_hits  # noqa: E402

T0 = datetime(2026, 11, 21, 3, 0, tzinfo=timezone.utc)


def HIT(method, path, t, body=None, status=200):
    return {"method": method, "path": path, "query": "", "body": body, "tagged": False, "status": status,
            "t": (T0 + timedelta(seconds=t)).timestamp()}


def CLOSED(arm, of_id, keys=None, opened=10, closed=20):
    at = lambda s: (T0 + timedelta(seconds=s)).isoformat()  # noqa: E731
    return {"row": 1, "arm": arm, "of_id": of_id, "keys": keys or {}, "opened": at(opened), "closed": at(closed)}


DEL9, HIDE77 = HIT("DELETE", "/api2/v2/posts/9", 15), HIT("PUT", "/api2/v2/vault/media/hidden", 16, {"mediaIds": [77]})


@pytest.mark.parametrize("row, hits, want", [
    (CLOSED(1, "9", {"media": "77"}), [DEL9, HIDE77], [DEL9, HIDE77]),
    (CLOSED(0, None, {"media": "77"}, opened=5), [DEL9, HIDE77], [HIDE77]),
    (CLOSED(1, "9", {"media": "77"}), [HIT("PUT", "/api2/v2/vault/media/hidden", 3, {"mediaIds": [77]}), DEL9], [DEL9]),
    (CLOSED(1, "9", {"media": "77"}), [HIT("PUT", "/api2/v2/vault/media/hidden", 21, {"mediaIds": [77]})], []),
    (CLOSED(1, "9", {"media": "77"}), [HIT("PUT", "/api2/v2/vault/media/hidden", 16, {"mediaIds": [78]})], []),
    (CLOSED(1, "9", {"media": "77"}), [HIT("DELETE", "/api2/v2/posts/8", 15)], []),
    (CLOSED(1, "9"), [HIDE77], []),
], ids=["post row: DELETE then the hide", "upload row: the post row's hide, inside its window",
        "a hide before the row opened (an earlier proof's)", "a hide after the row closed",
        "a hide of another media id", "a DELETE of another post", "no media id read: no hide counts"])
def test_row_undo_hits(row, hits, want):
    assert row_undo_hits(RECORD, row, hits) == want


def test_pending_rows_name_only_pending_rows():
    rows = [LOG_ROW(), LOG_ROW(state="FAILED", after_undo=AFTER) | {"row": 2},
            LOG_ROW(state="pending", of_id=None, after_undo=None, write_status="reply lost: ConnectionError")
            | {"row": 3}]
    assert pending_rows(rows) == [PENDING_LOST.replace("row 1", "row 3")]
    assert pending_rows([LOG_ROW(state="pending")]) == [
        "row 1 (tracer.create-list) pending: POST /api2/v2/lists (OnlyFans id 2) may be left on the account; "
        "check it, then clear the row by hand"]
    # cleared by hand: a snapshot appended to that log, folded last-wins
    assert pending_rows(undo_rows([LOG_ROW(state="pending"), {"row": 1, "state": "cleared by hand"}])) == []


HELD = {"pid": 4242, "evidence": "slop/evidence/X"}


@pytest.mark.parametrize("held, alive, want", [
    (None, False, ("take", "")),
    (HELD, True, ("refuse", "lock held by pid 4242 (slop/evidence/X): one run at a time")),
    (HELD, False, ("take", "stale lock of pid 4242 (slop/evidence/X) taken over")),
    ({}, False, ("refuse", "lock unreadable (no pid): remove it by hand once no run is going")),
    ({"pid": "x"}, True, ("refuse", "lock unreadable (no pid): remove it by hand once no run is going")),
], ids=["free", "held by a live run", "stale", "empty lock", "garbage pid"])
def test_lock_decision(held, alive, want):
    assert lock_decision(held, alive) == want


# ── ticket 04: the drills (story 39), the fake-only refusal under live, the guard census (story 38) ──
from proof_core import census, fake_only_refused  # noqa: E402

LISTED = lambda body: bool((body or {}).get("userLists"))  # noqa: E731
MASS = Proof(id="drill.mass", phase=0, page="mass-messages/index", control="x", kind="live", fake_only=True,
             arm=(Write("POST", "/api2/v2/messages/queue"),), undo=(Write("DELETE", "/api2/v2/messages/queue/{id}"),),
             refused_as="mass_message", refused_body=LISTED)
WITHDRAW = Proof(id="drill.withdraw", phase=0, page="statements/index", control="x", kind="live", fake_only=True,
                 arm=(Write("POST", "/api2/v2/payouts/requests"),), refused_as="critical")


def WB(method, path, verdict, cls, body):
    return {**W(method, path, verdict, cls, "refused" if verdict == "refused" else 200), "body": body}


def test_drill_shape_is_fake_only_and_needs_no_effect():
    assert MASS.effect is None and MASS.fake_only
    with pytest.raises(ValueError, match="fake_only"):
        Proof(id="d", phase=0, page="p", control="x", kind="live", arm=(Write("POST", "/api2/v2/x"),),
              refused_as="critical")


@pytest.mark.parametrize("field,steps", [
    ("trigger", (("relay", "GET", "/api/of/v2/x", None), ("click", "button"))),
    ("trigger", (("fetch", "GET", "/api2/v2/lists", None, "sent"), ("click", "button"))),   # ticket 07
    ("trigger", (("hand-off", "#a"), ("relay", "GET", "/api/of/v2/x", None))),
    ("capture_steps", (("fetch", "GET", "/api2/v2/lists", None, "sent"), ("fill", "input", "x"))),
])
def test_a_trigger_never_mixes_step_families(field, steps):
    with pytest.raises(ValueError, match="never a mix"):
        Proof(id="m", phase=0, page="p", control="x", kind="live", **{field: steps})
    Proof(id="ok", phase=0, page="p", control="x", kind="live",
          **{field: (("fetch", "GET", "/a", None, "sent"), ("hand-off", "#a"))})


def test_a_fake_only_proof_is_refused_under_live_before_anything_starts():
    assert fake_only_refused([TRACER, MASS, WITHDRAW], "live") == [
        "drill.mass is fake-only: --of live never starts it", "drill.withdraw is fake-only: --of live never starts it"]
    assert fake_only_refused([TRACER, MASS, WITHDRAW], "fake") == []
    assert fake_only_refused([TRACER], "live") == []


Q = "/api2/v2/messages/queue"


@pytest.mark.parametrize("proof, entries, errors, want", [
    (MASS, [W("GET", "/api2/v2/lists", "read"), WB("POST", Q, "refused", "mass_message", {"userLists": ["7"]})],
     [("POST", "/api/of/v2/messages/queue", 403)], []),
    (MASS, [WB("POST", Q, "refused", "mass_message", {"userLists": []})], [],
     ["drill.mass: POST /api2/v2/messages/queue was not refused as mass_message with its outbound body logged",
      "refused by the Live guard: POST /api2/v2/messages/queue (mass_message: )"]),
    (MASS, [WB("POST", Q, "refused", "unarmed", {"userLists": ["7"]})], [],
     ["drill.mass: POST /api2/v2/messages/queue was not refused as mass_message with its outbound body logged",
      "refused by the Live guard: POST /api2/v2/messages/queue (unarmed: )"]),
    (MASS, [WB("POST", Q, "allow", "allow", {"userLists": ["7"]})], [],
     ["drill.mass: POST /api2/v2/messages/queue was not refused as mass_message with its outbound body logged",
      "drill.mass: POST /api2/v2/messages/queue was forwarded to OnlyFans"]),
    (WITHDRAW, [WB("POST", "/api2/v2/payouts/requests", "refused", "critical", {"withdrawal_amount": 1})],
     [("POST", "/api/of/v2/payouts/requests", 403)], []),
    (WITHDRAW, [WB("POST", "/api2/v2/lists", "refused", "unarmed", None),
                WB("POST", "/api2/v2/payouts/requests", "refused", "critical", {"withdrawal_amount": 1})], [],
     ["refused by the Live guard: POST /api2/v2/lists (unarmed: )"]),
    (WITHDRAW, [], [("POST", "/api/of/v2/payouts/requests", 403)],
     ["drill.withdraw: POST /api2/v2/payouts/requests was not refused as critical with its outbound body logged",
      "Relay's own backstop refused POST /api/of/v2/payouts/requests (403): no wire line, nothing reached OnlyFans"]),
], ids=["mass refused with its list", "mass body carries no list", "mass refused as another class",
        "mass forwarded", "withdrawal refused as Critical", "another refusal in the drill's window",
        "withdrawal never reached the guard"])
def test_wire_problems_of_a_drill(proof, entries, errors, want):
    assert wire_problems(proof, entries, errors) == want


# Phase 3 ticket 63: a Mocked drill on the Relay's own backstop (`_denied`), e.g. Close all sessions until ticket 81.
CLOSE = Proof(id="drill.close", phase=3, page="settings/account/sessions", control="x", kind="mocked",
              tags=frozenset({"irreversible"}), arm=(Write("DELETE", "/api2/v2/sessions"),), refused_as="backstop",
              trigger=(("click", "#x"),))


def test_a_mocked_drill_needs_no_fake_only_and_is_recorded_not_run_live():
    from proof_core import not_started
    assert not CLOSE.fake_only and fake_only_refused([CLOSE], "live") == []
    assert (not_started(CLOSE, "live"), not_started(CLOSE, "fake")) == ("mocked: not run live", None)


# Ticket 134: a proof with no trigger (p1.engagement.msg.search, messages.more.*, fixture.message-parked) never
# starts, so run_proof never reads its trigger[0] or opens a page; the earlier reasons still win. A non-Mocked one is
# not parked here: live_entry refuses it (test_live_entry).
NO_TRIGGER_MOCKED = P(kind="mocked", id="p.search")
NO_TRIGGER_MESSAGE = armed("POST", "/api2/v2/chats/{fan}/messages", undo=(Write("DELETE", "/api2/v2/messages/{id}"),),
                           tags={"message"}, id="p.msg")
WITH_TRIGGER = Proof(id="p.t", phase=0, page="collections/index", control="x", kind="live", trigger=(("click", "#x"),))


@pytest.mark.parametrize("proof, of, fan, want", [
    (NO_TRIGGER_MOCKED, "fake", None, "mocked: no trigger; covered by the Mirror check"),
    (NO_TRIGGER_MOCKED, "live", None, "mocked: not run live"),
    (NO_TRIGGER_MESSAGE, "fake", None, "parked: Proof fan unset; the run never picks a Fan (--proof-fan names it)"),
    (NO_TRIGGER_MESSAGE, "fake", FAN, None),
    (WITH_TRIGGER, "fake", None, None),
], ids=["mocked, fake", "mocked, live", "live, no Proof fan", "live, Proof fan named", "with a trigger"])
def test_a_proof_with_no_trigger_never_starts(proof, of, fan, want):
    from proof_core import not_started
    assert not_started(proof, of, fan) == want


@pytest.mark.parametrize("entries, errors, want", [
    ([W("GET", "/api2/v2/sessions", "read")], [("DELETE", "/api/of/v2/sessions", 403)], []),
    ([], [], ["drill.close: DELETE /api2/v2/sessions was not refused by the Relay's own backstop (403, no wire line)"]),
    ([], [("DELETE", "/api/of/v2/sessions", 502)],
     ["drill.close: DELETE /api2/v2/sessions was not refused by the Relay's own backstop (403, no wire line)"]),
    ([W("DELETE", "/api2/v2/sessions", "refused", "critical", "refused")], [("DELETE", "/api/of/v2/sessions", 403)],
     ["drill.close: DELETE /api2/v2/sessions was not refused by the Relay's own backstop (403, no wire line)",
      "drill.close: DELETE /api2/v2/sessions reached the Live guard (refused)"]),
    ([W("DELETE", "/api2/v2/sessions")], [],
     ["drill.close: DELETE /api2/v2/sessions was not refused by the Relay's own backstop (403, no wire line)",
      "drill.close: DELETE /api2/v2/sessions reached the Live guard (allow)"]),
], ids=["backstop 403, no wire line", "nothing sent", "an OF error, not the backstop", "refused by the guard instead",
        "forwarded"])
def test_wire_problems_of_a_backstop_drill(entries, errors, want):
    assert wire_problems(CLOSE, entries, errors) == want


def H(method, path, tagged=False):
    """One FakeOF hit as fake_layer's Recorder records it."""
    return {"method": method, "path": path, "query": "", "body": None, "tagged": tagged, "status": 200}


@pytest.mark.parametrize("wire, hits, want", [
    ([W("GET", "/api2/v2/lists", "read"), W("POST", "/api2/v2/lists"), W("DELETE", "/api2/v2/lists/9", "reversal")],
     [H("GET", "/api2/v2/lists"), H("POST", "/api2/v2/lists"), H("DELETE", "/api2/v2/lists/9")], []),
    ([{**W("GET", "/api2/v2/lists", "read"), "origin": "driver"}], [H("GET", "/api2/v2/lists", tagged=True)], []),
    ([], [H("GET", "/api2/v2/lists", tagged=True)],
     ["tagged FakeOF hit with no driver wire line (a driver read that skipped the Relay): GET /api2/v2/lists"]),
    ([{**W("GET", "/api2/v2/lists", "read"), "origin": "driver"}], [H("GET", "/api2/v2/lists")],
     ["FakeOF hit with no forwarded wire line (bypassed the guard): GET /api2/v2/lists"]),
    ([W("GET", "/api2/v2/lists", "read")], [H("GET", "/api2/v2/lists"), H("GET", "/api2/v2/me")],
     ["FakeOF hit with no forwarded wire line (bypassed the guard): GET /api2/v2/me"]),
    ([W("GET", "/api2/v2/lists", "read")], [H("GET", "/api2/v2/lists"), H("GET", "/api2/v2/lists")],
     ["FakeOF hit with no forwarded wire line (bypassed the guard): GET /api2/v2/lists"]),
    ([W("POST", "/api2/v2/payouts/requests", "refused", "critical", "refused")],
     [H("POST", "/api2/v2/payouts/requests")], ["refused request reached FakeOF: POST /api2/v2/payouts/requests"]),
    ([W("POST", Q), W("POST", Q, "refused", "mass_message", "refused")], [H("POST", Q), H("POST", Q)],
     ["refused request reached FakeOF: POST /api2/v2/messages/queue"]),
    ([W("POST", Q, "refused", "mass_message", "refused")], [], []),
], ids=["every hit forwarded", "a tagged driver read through the Relay", "a tagged read that skipped the Relay",
        "a driver line never covers the app's untagged hit", "a hit missing from the wire log",
        "one forwarded line, two hits", "a refused entry among the hits", "refused beside a forwarded twin",
        "refused and absent"])
def test_census(wire, hits, want):
    assert census(wire, hits) == want


# ── ticket 53: a Write's own host (`Write.host`); `Proof.hosts` derived from the arms ──

S3 = "of2transcoder.s3-accelerate.amazonaws.com"
PUT_PATH = "/upload/7/u/1/rec.webm"
HOSTED = P(arm=[Write("PUT", "/upload/{creator}/{key}/{part}/{file}", host=S3), Write("POST", "/file/upload"),
                Write("POST", "/api2/v2/posts")],
           undo=[Write("DELETE", "/api2/v2/posts/{id}", reverses=(2,))], id="p2.hosted")


def test_proof_hosts_are_its_arms_hosts():
    assert HOSTED.hosts == (S3,) and LIST.hosts == ()


@pytest.mark.parametrize("name, req, run, kind, cls", [
    ("the PUT on its host", R("PUT", PUT_PATH, host=S3), Run(proof=HOSTED, hosts=(S3,)), "allow", "allow"),
    ("the PUT on onlyfans.com, live", R("PUT", PUT_PATH), Run(proof=HOSTED, hosts=(S3,)), "refused", "unarmed"),
    ("the PUT on FakeOF's origin (onlyfans.com), fake", R("PUT", PUT_PATH), Run(proof=HOSTED, hosts=(S3,), of="fake"),
     "allow", "allow"),
    ("another arm's write on the named host", R("POST", "/file/upload", host=S3), Run(proof=HOSTED, hosts=(S3,)),
     "refused", "unarmed"),
    ("the post on the named host", R("POST", "/api2/v2/posts", sched(60), host=S3),
     Run(proof=HOSTED, hosts=(S3,)), "refused", "unarmed"),
    ("another arm's write on the named host, fake", R("POST", "/file/upload", host=S3),
     Run(proof=HOSTED, hosts=(S3,), of="fake"), "refused", "unarmed"),
    ("a read on the named host", R("GET", "/upload/x", host=S3), Run(proof=HOSTED, hosts=(S3,)), "refused", "host"),
    ("the onlyfans.com arm still on onlyfans.com", R("POST", "/file/upload", host="convert.onlyfans.com"),
     Run(proof=HOSTED, hosts=(S3,)), "allow", "allow"),
])
def test_a_named_host_takes_only_the_write_that_names_it(name, req, run, kind, cls):
    v = decide(req, run)
    assert (v.kind, v.cls) == (kind, cls), (name, v)


def test_the_named_hosts_put_leaves_the_post_arm_unspent():
    """A write on the named host never uses up another arm's one send (reviewer finding 1)."""
    run = Run(proof=HOSTED, hosts=(S3,))
    assert decide(R("POST", "/api2/v2/posts", sched(60), host=S3), run).key is None
    assert decide(R("POST", "/api2/v2/posts", sched(60)), run).kind == "allow"


@pytest.mark.parametrize("host", ["*.example.net", "Store.example.net", "store.example.net.", "store.example.net:443",
                                  "user@store.example.net", "store.example.net/x", "", "localhost", " store.example.net"])
def test_a_write_host_is_an_exact_lowercase_host_name(host):
    with pytest.raises(ValueError, match="exact lowercase host name"):
        Write("PUT", "/upload/{file}", host=host)


@pytest.mark.parametrize("query, want", [
    ("", ""),
    ("offset=0&limit=50", "offset=0&limit=50"),
    ("X-Amz-Signature=abc&x-amz-security-token=t&limit=1", "X-Amz-Signature=REDACTED&x-amz-security-token=REDACTED&limit=1"),
    ("Expires=1&Signature=s&Key-Pair-Id=k&Policy=p", "Expires=1&Signature=REDACTED&Key-Pair-Id=REDACTED&Policy=REDACTED"),
    ("access_token=a&uploadToken=b&sig=c&X-Goog-Credential=d", "access_token=REDACTED&uploadToken=REDACTED&sig=REDACTED"
     "&X-Goog-Credential=REDACTED"),
    ("X-Amz-Signature", "X-Amz-Signature"),            # a bare name holds no value
])
def test_redact_query_keeps_names_and_drops_secret_values(query, want):
    from proof_core import redact_query
    assert redact_query(query) == want


@pytest.mark.parametrize("data, want", [
    (None, None),
    (b'{"a": 1}', {"a": 1}),
    ("name=x", "name=x"),
    (b"\xff\xfe\x00video", "<8 bytes>"),
    (b"\x1aE\xdf\xa3\x01\x02", "<6 bytes>"),            # valid UTF-8 by chance, still binary
])
def test_log_body_logs_a_binary_upload_by_length_only(data, want):
    from proof_core import log_body
    assert log_body(data) == want


def test_redact_text_scrubs_presigned_urls_and_s3_error_tags_in_free_text():
    from proof_core import redact_text
    log = ('PUT https://s3.example/upload/a/b?X-Amz-Algorithm=AWS4&x-amz-signature=abc123&partNumber=1 failed\n'
           'S3 PUT failed: 403 <Error><Code>SignatureDoesNotMatch</Code><AWSAccessKeyId>AKIAXYZ</AWSAccessKeyId>'
           '<StringToSign>AWS4-HMAC\nline</StringToSign></Error> token=zzz')
    out = redact_text(log)
    assert "abc123" not in out and "AKIAXYZ" not in out and "AWS4-HMAC" not in out
    assert "x-amz-signature=REDACTED" in out and "partNumber=1" in out
    assert "<AWSAccessKeyId>REDACTED</AWSAccessKeyId>" in out and "SignatureDoesNotMatch" in out


def test_capture_browser_logs_bodies_through_log_body():
    import of_browser
    assert not hasattr(of_browser, "_json")
    assert of_browser.log_body(b"\x1aE\xdf\xa3 webm") == "<9 bytes>"


# ticket 73: a trigger that types the Proof fan (`{fan}` in a fill step) parks while it is unset, in both modes; the
# fill puts the run's Proof fan and marker in.
TYPES_FAN = Proof(id="p.types-fan", phase=3, page="settings/streaming/blocked", control="Block", kind="live",
                  arm=(Write("POST", "/api2/v2/streams/users/{fan}/block"),),
                  trigger=(("fill", "#input-365", "u{fan}"), ("click", "button[type=submit]")), effect=lambda b, a: True)


def test_a_trigger_typing_the_proof_fan_parks_while_it_is_unset():
    from proof_core import fan_trigger, not_started
    assert fan_trigger(TYPES_FAN) and not fan_trigger(CLOSE)
    for of in ("fake", "live"):
        assert not_started(TYPES_FAN, of, None) == "parked: Proof fan unset; the run never picks a Fan (--proof-fan names it)"
        assert not_started(TYPES_FAN, of, FAN) is None


def test_fill_text_puts_in_the_marker_and_the_proof_fan():
    from proof_core import fill_text
    assert fill_text("u{fan}", "oi-proof-r1", FAN) == f"u{FAN}"
    assert fill_text("{marker} for {fan}", "oi-proof-r1", None) == "oi-proof-r1 for "
    assert fill_text("plain", "m", FAN) == "plain"
    assert fill_text("{handle}", "oi-proof-20261121T010203Z", None) == "oi_proof_20261121t010203z"   # ticket 69


# ofm-not-yet ticket 101: reads, then writes no Fan can see, then Fan-reaching writes, then Lockout, whatever the
# given order; within a group a `canon` id order (the proof list's) wins over the caller's.
RD = P(id="read")
INV = armed("POST", "/api2/v2/lists", id="invisible")
DAO = armed("POST", "/api2/v2/posts", id="at-once", tags={"delete_at_once", "post"})
MSG = armed("POST", "/api2/v2/messages/queue", id="msg", tags={"message"})
PUB = armed("PUT", "/api2/v2/schedules/{id}/publish", id="publish")


@pytest.mark.parametrize("p, group", [(RD, 0), (INV, 1), (DAO, 2), (MSG, 2), (PUB, 2), (L1, 3)],
                         ids=["read", "fan-invisible write", "delete-at-once", "message", "schedule publish",
                              "lockout"])
def test_order_group(p, group):
    from proof_core import order_group
    assert order_group(p) == group


def test_order_runs_reads_then_invisible_then_fan_reaching_then_lockout_whatever_the_given_order():
    got = [p.id for p in order([L1, PUB, MSG, INV, DAO, RD])]
    assert got == ["read", "invisible", "publish", "msg", "at-once", "sec.block-ip"]


def test_order_canon_fixes_the_order_inside_a_group():
    got = [p.id for p in order([MSG, DAO, PUB, INV, RD], canon=("read", "invisible", "at-once", "publish", "msg"))]
    assert got == ["read", "invisible", "at-once", "publish", "msg"]
    # ids outside canon keep the given order, after the canon ones of their group
    X = armed("POST", "/api2/v2/trials", id="x")
    assert [p.id for p in order([X, INV], canon=("invisible",))] == ["invisible", "x"]


# ── follow-up #5: an arm's declared payload (Write.payload, class 4) ──

def _ppv(**kw):
    return {"text": "<p>oi-proof-r</p>", "price": 3, "mediaFiles": [9001], "previews": [], "lockedText": False, **kw}


@pytest.mark.parametrize("body, why", [
    (_ppv(), None),
    (_ppv(price="3"), None),                                   # a numeric string: the same price
    (_ppv(text="<p>hi</p>"), "marker"),
    (_ppv(text="<p>oi-proof-q</p>"), "marker"),                # round 2 #22: another run's marker
    (_ppv(text="<p>oi-proof-rr</p>"), "marker"),               # this run's as a prefix only
    (_ppv(text="oi-proof-r copy"), None),                      # this run's as a whole token
    (_ppv(price=0), "price"),                                  # free media
    (_ppv(price=30), "price"),
    (_ppv(price=True), "price"),
    ({k: v for k, v in _ppv().items() if k != "price"}, "price"),
    (_ppv(previews=[9001]), "free previews"),
    (_ppv(mediaFiles=[]), "one locked medium"),
    (_ppv(mediaFiles=[9001, 9002]), "one locked medium"),
    ("text=oi-proof-r&price=3", "not a JSON object"),
])
def test_the_ppv_send_leaves_only_as_declared(body, why):
    """p2.bubble-unsend-ppv: the guard holds the send to the run's marker, the declared price, one locked medium and no
    free preview (phase2.ppv_payload) before it leaves."""
    from proofs.phase2 import PROOFS as P2
    proof = next(p for p in P2 if p.id == "p2.bubble-unsend-ppv")
    v = decide(R("POST", f"/api2/v2/chats/{FAN}/messages", body), Run(proof=proof, proof_fan=FAN, marker="oi-proof-r"))
    if why is None:
        assert v.kind == "allow", v
    else:
        assert (v.kind, v.cls) == ("refused", "unarmed") and why in v.reason and v.key == ("arm", 0), v


def test_a_payload_proof_armed_with_no_marker_refuses_the_send():
    """Round 2 #22: the payload binds to the marker the arm declared; none armed, nothing leaves."""
    from proofs.phase2 import PROOFS as P2
    proof = next(p for p in P2 if p.id == "p2.bubble-unsend-ppv")
    v = decide(R("POST", f"/api2/v2/chats/{FAN}/messages", _ppv()), Run(proof=proof, proof_fan=FAN))
    assert (v.kind, v.cls) == ("refused", "unarmed") and "no run marker armed" in v.reason, v


def test_a_payload_refuses_outside_it_and_an_arm_without_one_takes_any_body():
    w = Write("POST", "/api2/v2/lists", payload=lambda body, run, at: None if body == {"ok": 1} else "not ok")
    p = P(arm=[w], undo=[Write("DELETE", "/api2/v2/lists/{id}")])
    assert decide(R("POST", "/api2/v2/lists", {"ok": 2}), Run(proof=p)).cls == "unarmed"
    assert decide(R("POST", "/api2/v2/lists", {"ok": 1}), Run(proof=p)).kind == "allow"
    assert decide(R("POST", "/api2/v2/lists", {"any": 1}), Run(proof=armed("POST", "/api2/v2/lists"))).kind == "allow"
