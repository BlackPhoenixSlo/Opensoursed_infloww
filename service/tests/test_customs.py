#!/usr/bin/env python3
"""test_customs.py — the owed-custom ledger, `fans.customs_owed_at`.

The product for a creator with a bought-out vault: he tips $100-$200 and gets a
VOICE NOTE made for him. Fulfilment is manual, so the system's whole job is
notice / mark / stop selling / let a human clear it.

Every case here is anchored to something real:
  • the TICK-SURVIVAL case is the bug that made this feature inert for days —
    the ledger was a " Custom" suffix on `custom_nickname`, and the chat engines
    rebuild that field from structured facts every 60s. Prod: 204 watcher runs,
    zero surviving marks.
  • the audio-only discriminator comes from the product being a voice note, and
    from the clear loop having settled real debts on unrelated free videos

Run:  ./venv/bin/python service/tests/test_customs.py
"""
import _harness  # noqa: F401 — MUST be first

_harness.bootstrap()

from datetime import datetime, timedelta  # noqa: E402

from automations import _customs as CU  # noqa: E402
from db.models import Fan  # noqa: E402


def case_a_nickname_can_never_be_mistaken_for_the_ledger():
    """THE bug this module exists to not have, in its new form.

    The ledger used to be a " Custom" suffix on `fans.custom_nickname` and these
    functions took `str | None`. A call site left un-migrated is the failure this
    module most needs to prevent: it would read as "nothing owed" and a man who
    paid $200 would be silently forgotten.

    So the parameter is typed and the attribute is read DIRECTLY — no
    `getattr(..., None)` fallback to turn a wrong type into a quiet False. A
    stray nickname raises at the first line it reaches. There is no guard to
    write and none to keep in sync; the contract enforces itself."""
    for fn in (CU.is_owed, CU.mark, CU.clear):
        for bad in ("Alex Custom", "Kyle 3/13 Photoset Custom", ""):
            try:
                fn(bad)
            except AttributeError:
                pass
            else:
                raise AssertionError(
                    f"{fn.__name__}({bad!r}) accepted a nickname — a silent "
                    "wrong answer is exactly what the column move removed")

    # And the string that used to mean "owed" now means nothing at all. This
    # exact nickname is live on account 114838426 — a HUMAN's note about a
    # photoset, on an account with no customs automation. Under the suffix rule
    # it was an owed voice note; it must not become one now.
    f = Fan(account_id="114838426", fan_id=27550310,
            custom_nickname="Kyle 3/13 Photoset Custom")
    assert not CU.is_owed(f)


def case_mark_and_clear_round_trip():
    """mark() is idempotent — the scanner re-runs over the same tip every tick,
    and a second mark must not move the "waiting since" clock the queue ages by.

    It stamps the TIP's time, not now: stamping utcnow() on every sweep would
    reset every fan's wait to zero every 15 minutes, and the operator would never
    see a debt get old."""
    tipped = datetime(2026, 8, 5, 9, 0, 0)
    f = Fan(account_id="a", fan_id=1)
    assert not CU.is_owed(f), "a fresh fan owes nothing"

    assert CU.mark(f, tipped) is True
    assert CU.is_owed(f)
    assert f.customs_owed_at == tipped

    # Idempotent, AND it does not move the clock.
    assert CU.mark(f, datetime(2026, 8, 5, 23, 0, 0)) is False
    assert f.customs_owed_at == tipped

    # Clearing blanks the debt AND stamps settled. Both, or customs_watch
    # re-marks the same tip on its next sweep and the Sent click undoes itself.
    assert CU.clear(f) is True
    assert not CU.is_owed(f)
    assert f.customs_owed_at is None
    assert f.customs_cleared_at is not None
    assert CU.clear(f) is False, "clearing twice is not a second delivery"

    # None is answerable, so callers holding a maybe-missing fan need no guard.
    assert CU.is_owed(None) is False
    assert CU.mark(None) is False
    assert CU.clear(None) is False


def case_the_ledger_survives_a_chat_tick():
    """⚠️ THE REGRESSION TEST FOR THE BUG THAT MADE THIS FEATURE INERT.

    `customs_watch` marked a fan; the chat engine — every 60s, against the watcher's
    900s — called `_maybe_push_nickname`, which rebuilds the display name from
    structured facts via `names.build_structured_nickname`. That function knows
    only real facts, so a trailing " Custom" was dropped, pushed to OnlyFans, and
    written back over our own row. The debt was gone about a minute after it was
    recorded, on both surfaces. Prod after days live: 204 runs, zero marks.

    The fix is that the ledger is a column no nickname writer touches. This test
    runs the REAL rebuild against a marked fan and asserts the debt is still
    there — it fails on any future change that puts the marker back in a name."""
    from automations import names

    f = Fan(account_id="8000149", fan_id=800453746, real_name="Dana",
            home_city="Abbotsford", home_country="Canada", his_age="48",
            occupation="journeyman carpenter", of_display_name="Dana")
    f.custom_nickname = names.build_structured_nickname(f)

    CU.mark(f, datetime(2026, 8, 5, 9, 0, 0))
    assert CU.is_owed(f)

    # The chat tick: rebuild the nickname and write it back, exactly as
    # `_maybe_push_nickname` does.
    f.custom_nickname = names.build_structured_nickname(f)

    assert CU.is_owed(f), "a chat tick erased the owed custom — the 2026-08-05 bug"
    # And the fan is not renamed to the marker either. Under the suffix rule a fan
    # with no known facts became literally "Custom", and was then greeted as
    # "Custom" by the very next reply.
    assert "Custom" not in (f.custom_nickname or ""), f.custom_nickname


def case_only_a_dm_tip_over_the_floor_is_an_order():
    """A $200 tip on a POST is a man being generous about a photo. A $200 tip in
    the DM is a man ordering a voice note. Counting both inflates the queue with
    work nobody promised. The order decision is `orders_per_fan` (kind filtering
    happens in the callers' SQL via ORDER_KINDS); the floor rule is
    `resolve_floor`."""
    now = datetime(2026, 8, 19, 12, 0, 0)

    def order(cents, min_cents=None):
        rows = [("a", 1, cents, now, None)]
        return ("a", 1) in CU.orders_per_fan(rows, min_cents)

    assert order(5_000)
    assert order(10_000)
    assert order(20_000)
    assert not order(4_999)
    # kind gating lives in ORDER_KINDS — the callers' SQL filters on it, so a
    # post/stream tip never reaches the burst function at all.
    for kind in ("tip_post", "tip_stream", "ppv_message", "subscription"):
        assert kind not in CU.ORDER_KINDS, kind
    assert CU.ORDER_KINDS == ("tip",)
    # The floor rule: default MIN_CENTS, per-account override, floored at 1¢.
    assert CU.resolve_floor(None) == CU.MIN_CENTS
    assert CU.resolve_floor(15_000) == 15_000
    assert CU.resolve_floor(0) == 1


def case_delivery_is_audio_and_only_audio():
    """The product is a voice note (operator ruling 2026-08-05, "we should sell
    only voice messages"), so a voice note is the only thing that can settle one.

    A FREE VIDEO used to count too, for a "short video" product that is not being
    built, and it was a live false-clear: the watcher's clear loop fell back to
    its 72h sweep window when the originating tip aged out, so ANY free outbound
    video in three days settled an older debt.

    Only the TUPLE is asserted here. The predicate that used to sit beside it is
    deleted: with one audio-only type it had decayed into `type == "audio"` with
    two ignored parameters, while its only caller already filtered on this tuple
    in SQL. `test_customs_watch.case_no_video_priced_or_free_ever_clears_a_debt`
    covers the behaviour through the real query, which is better evidence."""
    assert CU.DELIVERY_TYPES == ("audio",)
    assert not hasattr(CU, "is_delivery"), \
        "the Python re-test came back; the SQL filter already decides this"


def case_chat_engines_never_mention_customs():
    """The brake has to be CODE, not guidance: a prompt line telling a model not
    to sell is a suggestion. The chat engines ("no selling") offer nothing paid,
    so they never mention customs or a tip-ask at all."""
    import inspect
    from automations import autoreply, welcome_chatter_for_info
    for mod in (autoreply, welcome_chatter_for_info):
        src = inspect.getsource(mod)
        for needle in ("_customs", "custom_owed", "tip_ask"):
            assert needle not in src, f"{mod.__name__}: {needle!r} came back"


def case_female_default_is_untouched():
    """Auto Convo's prompt has no customs surface at all, so a fan with or
    without the marker gets the same prompt builder — there is no flag to set."""
    import inspect
    from automations import autoreply
    from db.models import Fan
    f = Fan(account_id="a", fan_id=1, of_display_name="Bob")
    assert f.customs_owed_at is None
    assert not CU.is_owed(f)
    src = inspect.getsource(autoreply._build_messages)
    assert "custom" not in src.lower(), "Auto Convo's prompt mentions customs"


def case_a_second_order_on_another_day_is_not_swallowed():
    """The BitchBoi99 bug: $100 yesterday + $100 today is TWO voice notes owed,
    and the queue showed one.

    `orders_per_fan` returns a single tuple per fan — it takes the newest row as
    the anchor and folds in only what sits inside the 30-minute burst window, so
    an order from the previous day hits neither branch and is dropped. The second
    order had nowhere else to surface either: `customs_api._unmarked` subtracts
    fans who are already owed. Measured on the laptop DB, 2 fans and $285 of
    paid-for work were invisible.

    `bursts_per_fan` is the counting function. `orders_per_fan` is deliberately
    NOT changed — `customs_watch` uses its anchor as the delivery cutoff, and
    `test_customs_watch.case_an_order_is_the_burst_total_not_the_biggest_tip`
    pins its single-burst contract."""
    now = datetime(2026, 9, 2, 12, 0, 0)

    def rows(*spec):
        # (cents, minutes_ago, msg_id), newest first — the order both burst
        # functions require.
        return [("a", 1, c, now - timedelta(minutes=m), i) for c, m, i in spec]

    # THE BUG. Two $100s a day apart.
    two_days = rows((10_000, 0, 501), (10_000, 1_440, 500))
    assert CU.orders_per_fan(two_days)[("a", 1)][0] == 10_000, \
        "the old function is single-burst by contract; do not 'fix' it here"
    got = CU.bursts_per_fan(two_days)[("a", 1)]
    assert len(got) == 2, got
    assert sum(b[0] for b in got) == 20_000
    # Newest first, so the row's anchor opens the thread at the most recent ask.
    assert got[0][1] > got[1][1]
    assert got[0][2] == 501

    # BURST_MINUTES is NOT the bug and must not be widened: tips inside the
    # window are still ONE order, because the amount buys LENGTH, not count.
    stacked = CU.bursts_per_fan(rows((6_000, 0, 2), (6_000, 5, 1)))[("a", 1)]
    assert stacked == [(12_000, now, 2)], stacked

    # The floor is still tested on the burst TOTAL, per order. A lone sub-floor
    # tip on another day is generosity, not a second voice note.
    kept = CU.bursts_per_fan(rows((10_000, 0, 3), (2_000, 1_440, 4)))[("a", 1)]
    assert len(kept) == 1 and kept[0][0] == 10_000, kept

    # The prod case from `mark`'s docstring: three orders, $530, shown as one.
    three = CU.bursts_per_fan(
        rows((15_000, 0, 9), (20_000, 2_880, 8), (18_000, 4_320, 7)))[("a", 1)]
    assert len(three) == 3 and sum(b[0] for b in three) == 53_000, three

    # A fan with nothing qualifying is absent entirely, not present-and-empty.
    assert CU.bursts_per_fan(rows((2_000, 0, 1))) == {}

    # ── THE CHAIN. Four $50 tips, 20 minutes apart each, spanning 60 minutes.
    # Every gap is inside BURST_MINUTES but the chain is not, so the anchor's
    # window closes after the 20-minute one and the rest OPEN new orders.
    #
    # This is what the two functions used to disagree about. `orders_per_fan`
    # DROPPED the overflow (one $100 order, $100 of paid work invisible), while
    # `bursts_per_fan` opened bursts for it — and `bursts_per_fan`'s own
    # docstring claimed they shared a rule. They share one walk now, so
    # `orders_per_fan` is exactly this walk's first element and cannot drift.
    chain = rows((5_000, 0, 604), (5_000, 20, 603),
                 (5_000, 40, 602), (5_000, 60, 601))
    walked = CU.bursts_per_fan(chain, min_cents=1)[("a", 1)]
    assert [b[0] for b in walked] == [10_000, 10_000], walked
    newest = CU.orders_per_fan(chain, min_cents=1)[("a", 1)]
    # DOCUMENTS the invariant; it does not DETECT drift. `orders_per_fan` returns
    # `bursts[0]` of this very walk, so no input can make these two disagree —
    # the equality holds by construction, not by agreement. If the shared walk is
    # ever unshared, this line keeps passing; the pin that would actually catch
    # that is the floor/anchor contract asserted just below.
    assert newest == walked[0], (newest, walked[0])
    # And the anchor the WATCH marks off is still the newest tip — the delivery
    # cutoff must not move, whatever the count does.
    assert newest[1] == now and newest[2] == 604, newest


def case_refunded_money_is_not_owed_work():
    """A charged-back tip must never appear as work owed.

    `customs_watch` has always filtered `status in ('cleared','pending')`;
    `customs_api` never did, so a charged-back tip was excluded from MARKING a
    fan owed and included in the AMOUNT shown to the operator. Prod carries 8
    charged-back tips, three at or above the order floor. The filter is one
    constant now, shared by both, so they cannot drift apart again."""
    import inspect

    import customs_api

    assert CU.SETTLED_STATUSES == ("cleared", "pending")
    # The watch aliases the shared constant rather than keeping its own copy.
    from automations import customs_watch
    assert customs_watch._SETTLED_STATUSES is CU.SETTLED_STATUSES

    # EVERY query in this module that reads tips as ORDERS filters on it.
    # Counted rather than named because the failure being prevented is a NEW
    # query landing without the filter — which is exactly how the owed query
    # came to be missing it while the watch had it all along. Asserted as
    # "every tip query", not a fixed number, so adding a query cannot pass by
    # accident and cannot fail merely for existing.
    src = inspect.getsource(customs_api)
    tip_queries = src.count("Transaction.kind.in_(_customs.ORDER_KINDS)")
    settled = src.count("Transaction.status.in_(_customs.SETTLED_STATUSES)")
    assert tip_queries > 0 and settled == tip_queries, (
        f"{tip_queries} tip queries but only {settled} filter settled money — "
        "a tip query without the status filter shows refunded work as owed")


def case_the_brief_reaches_the_message_that_placed_the_order():
    """The operator's case: the fan asked for "naked gym routine, health food"
    in an EARLIER message, then tipped. Anchoring the excerpt on his NEWEST tip
    and reading back a fixed 50 misses the ask on a chatty thread, and the model
    then summarises the wrong conversation — confidently, which is worse than
    saying nothing.

    So the brief anchors on the OLDEST outstanding order and runs forward to
    now, and it is told how many orders are outstanding so two voice notes are
    not collapsed into one."""
    import inspect

    import customs_api

    src = inspect.getsource(customs_api.customs_brief)
    # Anchored on the OLDEST burst — `bursts` is newest-first, so [-1].
    assert "bursts[-1][1].isoformat()" in src, \
        "the brief must anchor on the oldest outstanding order, not the newest tip"
    assert "_BRIEF_BEFORE" in src and "_BRIEF_AFTER" in src

    # The span must be able to cross a long thread, and the endpoint has to
    # actually accept it — a constant above the Query ceiling would 422.
    sig = inspect.signature(customs_api.customs_context)
    for name, const in (("before", customs_api._BRIEF_BEFORE),
                        ("after", customs_api._BRIEF_AFTER)):
        # Pydantic keeps the constraint in `metadata` as annotated-types Le.
        ceiling = next(m.le for m in sig.parameters[name].default.metadata
                       if hasattr(m, "le"))
        assert const <= ceiling, f"{name}={const} exceeds the endpoint cap {ceiling}"
    # Operator spec 2026-09-05: "scrape those 100 messages over the tips before
    # and after". 100 each side, exactly as asked.
    assert (customs_api._BRIEF_BEFORE, customs_api._BRIEF_AFTER) == (100, 100), \
        "the operator asked for 100 messages either side of the tip"
    # A fixed window cannot reach an ask placed weeks before the money (live
    # Blake1: 58 days), so the brief must top the window up with the order's
    # own lines from the whole thread.
    assert "customs_order(" in src, \
        "the brief must merge in the whole-thread order span, not just the window"
    # Both directions, labelled: the creator sets the length after the fan
    # proposes another, and a fan-only transcript films the wrong take.
    assert '"HIM"' in src and '"US"' in src

    # It must be able to say "I cannot see the ask" instead of guessing.
    assert "found_request" in src
    assert '"found_request": bool(brief.get("found_request", True))' in src, \
        "a model that omits the field must degrade to the old behaviour"
    # Money never comes from the model.
    assert "NEVER state, guess, split or total any dollar amount" in src

    # The money still never comes from the model.
    assert "NEVER state, guess, split or total any dollar amount" in src
    assert '"paid_cents": paid_cents' in src

    # ⚠️ THE TRUNCATION MUST KEEP THE OLDEST LINES. This was `said[-40:]`, which
    # silently undid the window fix one line after it was made: the span is
    # weighted BEHIND the anchor precisely because the ask precedes the money,
    # so tail-truncation throws away the message the brief exists to read.
    # Verified on a seeded thread with 80 messages of small talk after the ask.
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "lines[-40:]" not in code and "said[-40:]" not in code, \
        "tail-truncation drops the request the window was widened to reach"
    assert "lines[:head]" in code, "keep the OLDEST lines — the ask precedes the tip"

    # ONE canonical tip query. The settled-money filter lives inside it, so a
    # fourth call site cannot reintroduce the refunded-work bug by forgetting it.
    whole = inspect.getsource(customs_api)
    assert whole.count("select(Transaction.account_id, Transaction.fan_id,") == 1, \
        "tip queries must go through _order_tips_q"


# No hand-maintained list: `run()` with no arguments collects every `case_*` in
# definition order, which is the form the harness prefers precisely because a
# missing entry fails SILENTLY by not running the test.
_harness.run()
