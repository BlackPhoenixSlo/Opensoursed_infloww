from __future__ import annotations

ONE_WINNER = ("s4s race: racing answers on one request (accept/decline/skip by the receiver, or accept/decline vs "
              "the sender's cancel): exactly one 2xx, every other 409, and the row ends in the winner's status")
SLOTS_JOBS = ("s4s race: every accepted request has exactly 2 slots (one per side, at slot_at) each with one pending "
              "s4s_post job, every other request none; s4s_post jobs == 2 x accepted, none ran")
DAILY_LIMIT = ("s4s race: booked (not canceled) slots per Creator per UTC day <= its Daily limit after concurrent "
               "accepts, and each over-subscribed Creator got exactly min(senders, limit) accepts")
# service/s4s_common.py MAX_SENT_PER_DAY
CAP = 50
CAP_SEQ = f"s4s race: a Creator's request {CAP + 1} and {CAP + 2} of the UTC day -> 409, {CAP} rows stored"
CAP_RACE = (f"s4s race: concurrent sends across the {CAP}/day boundary store exactly {CAP} requests for that "
            "Creator (the rest 409)")
BLOCKED = ("s4s race: blocked pairs -> 404 both ways on send and proposal; the blocking Agency's Discovery shows "
           "none of its blocked Creators and its /blocks lists exactly them")
AUDIT = ("s4s race: one `actions` row per transition: per request rows == 2xx sends+answers seen, per slot "
         "rows == 200 cancels seen, action names match the verbs")
SLOT_CANCEL = ("s4s race: racing cancels of one slot: exactly one 200 by its poster's owner, the other 409, the "
               "partner's try 404; the partner's slot stays scheduled")
BOXES = ("s4s race: every Agency's Received/Sent boxes list exactly its DB requests (Received without skips), "
         "newest first, status as stored (a skip reads pending to the sender); nothing dropped")
SCHEDULE = "s4s race: GET /schedule lists exactly the Agency's own posting slots in the window, by slot_at"
SENDS = "s4s race: every planned send (race, limit, booking, UI groups) -> 201"
UI_ACCEPT = ("s4s race (UI): Accept on /share-for-share/requests answers 200 and shows 'Share for Share Scheduled!'; "
             "the request is accepted (DB + GET /requests) with 2 slots and 2 pending s4s_post jobs")
UI_PAGES = ("s4s race (UI): /share-for-share/schedule shows the new slot, discover-creators a partner card and none "
            "the Agency blocked, settings the Creator's S4S settings")
DISCOVER = ("s4s race: GET /discover lists every opted-in Creator with a Primary post the Agency did not block, "
            "and no Creator that is not opted in")
PROPOSAL = ("s4s race: GET /requests/proposal answers 06:00 UTC of the first day from tomorrow with room under both "
            "Daily limits, also when tomorrow is full for the partner (at least one probe expects a later day)")


def _accept_unguarded_update() -> None:
    import inspect
    import textwrap

    import s4s_requests_api as m

    src = textwrap.dedent(inspect.getsource(m._transition))
    guard = "S4SRequest.status.in_(movable),"
    if src.count(guard) != 1:
        raise RuntimeError(f"s4s-accept-unguarded-update: the guard {guard!r} is not in _transition once")
    ns: dict = {}
    exec(compile(src.replace(guard, ""), m.__file__, "exec"), m.__dict__, ns)  # noqa: S102 — the fault itself
    m._transition = ns["_transition"]


def _daily_limit_skipped() -> None:
    import s4s_requests_api as m

    async def never_full(s, p, slot_at) -> bool:
        return False

    m._limit_full = never_full


def _send_cap_unlocked() -> None:
    import inspect

    import s4s_requests_api as m
    from db.engine import get_session

    if not hasattr(m, "immediate_session") or "immediate_session()" not in inspect.getsource(m.send_request):
        raise RuntimeError("s4s-send-cap-unlocked: s4s_requests_api.send_request no longer uses immediate_session()")
    m.immediate_session = get_session


def register(Fault) -> dict:
    return {
        "s4s-accept-unguarded-update": Fault(_accept_unguarded_update, (ONE_WINNER, SLOTS_JOBS)),
        "s4s-daily-limit-skipped": Fault(_daily_limit_skipped, (DAILY_LIMIT, PROPOSAL)),
        "s4s-send-cap-unlocked": Fault(_send_cap_unlocked, (CAP_RACE,)),
    }
