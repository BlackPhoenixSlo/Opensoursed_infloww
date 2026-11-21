"""Phase 0's proofs: the tracer, Collections "Create new list" (docs/spec/ofm-not-yet/phase-00-...md, story 50), and
the fake-only drills (story 39).

Trigger steps run in the control's Mirror frame: ("click", selector), ("fill", selector, text). `{marker}` in a text
is the run's `oi-proof-<run>` value. ("relay", method, route, body) calls one existing Relay route as the scoped
Creator; no page is opened when every step is one. Its `body` is JSON, or a callable given the before read.
Capture-browser steps (of_browser.py, ticket 07) run in the capture browser instead: ("fetch", method, path, body,
expect) sends one request from the fake-mode drill page (path and body may be callables given the before read; expect
is "sent" or the Live guard class that must abort it), and ("hand-off", selector) clicks an OAuth hand-off there.
`settled` is ("text", selector, wanted text) in the same frame, or None. `of_read(get, fan)` reads OnlyFans's side
with `get(path, query) -> JSON`, one signed GET, and returns a comparable value; `fan` is the Proof fan id or None
(ticket 100; most readers ignore it). None reads nothing.
"""
from proof_core import Proof, Write

MARKER = "oi-proof-"
DIALOG = "[data-oi-dialog]"


def read_lists(get, fan):
    """Every custom list as (id, name), sorted: OnlyFans's `GET /lists` (`{list, hasMore}`), paged."""
    rows, off = [], 0
    while True:
        page = get("/api2/v2/lists", {"offset": off, "limit": 50, "skip_users": "all", "format": "infinite"})
        items = page.get("list") or []
        rows += [(str(x["id"]), str(x.get("name") or "")) for x in items if isinstance(x, dict) and "id" in x]
        if not page.get("hasMore") or not items:
            return sorted(rows)
        off += len(items)


def one_new_marked_list(before, after):
    """The declared effect: exactly one list more, named with the run's marker (a no-op write cannot pass)."""
    new = set(map(tuple, after)) - set(map(tuple, before))
    return len(new) == 1 and next(iter(new))[1].startswith(MARKER)


def find_marked_list(before, after, marker):
    """A lost reply's finder (story 53): the one list new since `before` named exactly `marker`, else None."""
    new = [r for r in set(map(tuple, after)) - set(map(tuple, before)) if r[1] == marker]
    return new[0][0] if len(new) == 1 else None


TRACER = Proof(
    id="tracer.create-list", phase=0, page="collections/index", control="Create new list", kind="live",
    arm=(Write("POST", "/api2/v2/lists"),),
    trigger=(("click", "button[aria-label='Create new list']"),
             ("fill", f"{DIALOG} input", "{marker}"),
             ("click", f"{DIALOG} button[type=submit]")),
    settled=("text", "#oi-note", "List created"),
    of_read=read_lists,
    effect=one_new_marked_list,
    undo=(Write("DELETE", "/api2/v2/lists/{id}", relay="/api/of/v2/lists/{id}"),),
    find=find_marked_list,
    # Fake-mode capture against the drill page; the Known body of service/of_sends.py `create_list`. Live capture
    # steps (clicks on onlyfans.com/my/collections) are parked with --of live (ticket 09).
    capture_steps=(("fetch", "POST", "/api2/v2/lists", {"name": "{marker}"}, "sent"),),
)


def _listed(body):
    """The mass drill's logged outbound body carries a non-empty OF list (`userLists`, service/of_sends.py)."""
    return isinstance(body, dict) and bool(body.get("userLists"))


# The drills (story 39): fake-only, armed on purpose through the Relay's existing routes, passing only when the Live
# guard refuses them with their class and FakeOF never sees them.
# The mass drill declares the real cancel (`DELETE /messages/queue/{id}`) as its undo so its write gets past class 4
# (no undo) and reaches class 6; fake mode arms FakeOF's fan 1 as the Proof fan, so class 6 refuses it for its list.
DRILL_MASS = Proof(
    id="drill.mass-to-list", phase=0, page="messages/send", control="Mass message to an OF list (drill)",
    kind="live", fake_only=True,
    arm=(Write("POST", "/api2/v2/messages/queue"),),
    undo=(Write("DELETE", "/api2/v2/messages/queue/{id}", relay="/api/of/v2/messages/queue/{id}"),),
    of_read=read_lists,
    # the Relay's field is `user_lists` (service/mass_queue_api.py), sent on as `userLists`; a real FakeOF list id
    trigger=(("relay", "POST", "/api/of/v2/messages/queue",
              lambda lists: {"text": "oi-proof drill", "user_lists": [lists[0][0]]}),),
    refused_as="mass_message", refused_body=_listed,
)

DRILL_WITHDRAWAL = Proof(
    id="drill.withdrawal", phase=0, page="statements/payouts", control="Request withdrawal (drill)",
    kind="live", fake_only=True,
    arm=(Write("POST", "/api2/v2/payouts/requests"),),
    trigger=(("relay", "POST", "/api/of/v2/payouts/requests", {"withdrawal_amount": 1}),),
    refused_as="critical",
)

PROOFS = (TRACER, DRILL_MASS, DRILL_WITHDRAWAL)

# ── ticket 07 ──
# The capture browser drill: from the loopback drill page on FakeOF's origin, a Critical write and an unarmed write
# (an existing list's delete, before any write of this proof) are aborted by the Live guard and never reach FakeOF;
# the armed tracer write goes through and is undone through the Relay like the tracer's. Known bodies only
# (service/of_sends.py `request_payout`, `create_list`; the delete is bodyless).
DRILL_BROWSER = Proof(
    id="drill.browser", phase=0, page="collections/index", control="Capture browser drill", kind="live",
    fake_only=True,
    arm=TRACER.arm,
    trigger=(("fetch", "POST", "/api2/v2/payouts/requests", {"withdrawal_amount": 1}, "critical"),
             ("fetch", "DELETE", lambda lists: f"/api2/v2/lists/{lists[0][0]}", None, "unarmed"),
             ("fetch", "POST", "/api2/v2/lists", {"name": "{marker}"}, "sent")),
    of_read=read_lists, effect=one_new_marked_list, undo=TRACER.undo, find=find_marked_list,
)

# An OAuth hand-off (story 17): its click opens OnlyFans's own page (here the fake origin, which counts as
# onlyfans.com) in a new tab; the capture browser records that navigation and aborts it, and nothing is written.
DRILL_OAUTH = Proof(
    id="drill.oauth-hand-off", phase=0, page="settings/account", control="OAuth hand-off (drill)", kind="oauth",
    fake_only=True,
    trigger=(("hand-off", "#ofm-hand-off"),),
)

PROOFS += (DRILL_BROWSER, DRILL_OAUTH)
