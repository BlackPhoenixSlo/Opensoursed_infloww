from proof_core import Proof, Write

MARKER = "oi-proof-"
DIALOG = "[data-oi-dialog]"


def read_lists(get, fan):
    rows, off = [], 0
    while True:
        page = get("/api2/v2/lists", {"offset": off, "limit": 50, "skip_users": "all", "format": "infinite"})
        items = page.get("list") or []
        rows += [(str(x["id"]), str(x.get("name") or "")) for x in items if isinstance(x, dict) and "id" in x]
        if not page.get("hasMore") or not items:
            return sorted(rows)
        off += len(items)


def one_new_marked_list(before, after):
    new = set(map(tuple, after)) - set(map(tuple, before))
    return len(new) == 1 and next(iter(new))[1].startswith(MARKER)


def find_marked_list(before, after, marker):
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
    capture_steps=(("fetch", "POST", "/api2/v2/lists", {"name": "{marker}"}, "sent"),),
)


def _listed(body):
    return isinstance(body, dict) and bool(body.get("userLists"))


DRILL_MASS = Proof(
    id="drill.mass-to-list", phase=0, page="messages/send", control="Mass message to an OF list (drill)",
    kind="live", fake_only=True,
    arm=(Write("POST", "/api2/v2/messages/queue"),),
    undo=(Write("DELETE", "/api2/v2/messages/queue/{id}", relay="/api/of/v2/messages/queue/{id}"),),
    of_read=read_lists,
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

DRILL_BROWSER = Proof(
    id="drill.browser", phase=0, page="collections/index", control="Capture browser drill", kind="live",
    fake_only=True,
    arm=TRACER.arm,
    trigger=(("fetch", "POST", "/api2/v2/payouts/requests", {"withdrawal_amount": 1}, "critical"),
             ("fetch", "DELETE", lambda lists: f"/api2/v2/lists/{lists[0][0]}", None, "unarmed"),
             ("fetch", "POST", "/api2/v2/lists", {"name": "{marker}"}, "sent")),
    of_read=read_lists, effect=one_new_marked_list, undo=TRACER.undo, find=find_marked_list,
)

DRILL_OAUTH = Proof(
    id="drill.oauth-hand-off", phase=0, page="settings/account", control="OAuth hand-off (drill)", kind="oauth",
    fake_only=True,
    trigger=(("hand-off", "#ofm-hand-off"),),
)

PROOFS += (DRILL_BROWSER, DRILL_OAUTH)
