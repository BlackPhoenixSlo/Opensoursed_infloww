#!/usr/bin/env python3
import _harness  # noqa: F401 — MUST be first

_harness.bootstrap()

from datetime import datetime, timedelta  # noqa: E402

from automations import _customs as CU  # noqa: E402
from db.models import Fan  # noqa: E402


def case_a_nickname_can_never_be_mistaken_for_the_ledger():
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

    f = Fan(account_id="114838426", fan_id=27550310,
            custom_nickname="Kyle 3/13 Photoset Custom")
    assert not CU.is_owed(f)


def case_mark_and_clear_round_trip():
    tipped = datetime(2026, 8, 5, 9, 0, 0)
    f = Fan(account_id="a", fan_id=1)
    assert not CU.is_owed(f), "a fresh fan owes nothing"

    assert CU.mark(f, tipped) is True
    assert CU.is_owed(f)
    assert f.customs_owed_at == tipped

    assert CU.mark(f, datetime(2026, 8, 5, 23, 0, 0)) is False
    assert f.customs_owed_at == tipped

    assert CU.clear(f) is True
    assert not CU.is_owed(f)
    assert f.customs_owed_at is None
    assert f.customs_cleared_at is not None
    assert CU.clear(f) is False, "clearing twice is not a second delivery"

    assert CU.is_owed(None) is False
    assert CU.mark(None) is False
    assert CU.clear(None) is False


def case_the_ledger_survives_a_chat_tick():
    from automations import names

    f = Fan(account_id="8000149", fan_id=800453746, real_name="Dana",
            home_city="Abbotsford", home_country="Canada", his_age="48",
            occupation="journeyman carpenter", of_display_name="Dana")
    f.custom_nickname = names.build_structured_nickname(f)

    CU.mark(f, datetime(2026, 8, 5, 9, 0, 0))
    assert CU.is_owed(f)

    f.custom_nickname = names.build_structured_nickname(f)

    assert CU.is_owed(f), "a chat tick erased the owed custom — the 2026-08-05 bug"
    assert "Custom" not in (f.custom_nickname or ""), f.custom_nickname


def case_only_a_dm_tip_over_the_floor_is_an_order():
    now = datetime(2026, 8, 19, 12, 0, 0)

    def order(cents, min_cents=None):
        rows = [("a", 1, cents, now, None)]
        return ("a", 1) in CU.orders_per_fan(rows, min_cents)

    assert order(5_000)
    assert order(10_000)
    assert order(20_000)
    assert not order(4_999)
    for kind in ("tip_post", "tip_stream", "ppv_message", "subscription"):
        assert kind not in CU.ORDER_KINDS, kind
    assert CU.ORDER_KINDS == ("tip",)
    assert CU.resolve_floor(None) == CU.MIN_CENTS
    assert CU.resolve_floor(15_000) == 15_000
    assert CU.resolve_floor(0) == 1


def case_delivery_is_audio_and_only_audio():
    assert CU.DELIVERY_TYPES == ("audio",)
    assert not hasattr(CU, "is_delivery"), \
        "the Python re-test came back; the SQL filter already decides this"


def case_chat_engines_never_mention_customs():
    import inspect
    from automations import autoreply, welcome_chatter_for_info
    for mod in (autoreply, welcome_chatter_for_info):
        src = inspect.getsource(mod)
        for needle in ("_customs", "custom_owed", "tip_ask"):
            assert needle not in src, f"{mod.__name__}: {needle!r} came back"


def case_female_default_is_untouched():
    import inspect
    from automations import autoreply
    from db.models import Fan
    f = Fan(account_id="a", fan_id=1, of_display_name="Bob")
    assert f.customs_owed_at is None
    assert not CU.is_owed(f)
    src = inspect.getsource(autoreply._build_messages)
    assert "custom" not in src.lower(), "Auto Convo's prompt mentions customs"


def case_a_second_order_on_another_day_is_not_swallowed():
    now = datetime(2026, 9, 2, 12, 0, 0)

    def rows(*spec):
        return [("a", 1, c, now - timedelta(minutes=m), i) for c, m, i in spec]

    two_days = rows((10_000, 0, 501), (10_000, 1_440, 500))
    assert CU.orders_per_fan(two_days)[("a", 1)][0] == 10_000, \
        "the old function is single-burst by contract; do not 'fix' it here"
    got = CU.bursts_per_fan(two_days)[("a", 1)]
    assert len(got) == 2, got
    assert sum(b[0] for b in got) == 20_000
    assert got[0][1] > got[1][1]
    assert got[0][2] == 501

    # Tips inside BURST_MINUTES are one order; the summed amount buys length.
    stacked = CU.bursts_per_fan(rows((6_000, 0, 2), (6_000, 5, 1)))[("a", 1)]
    assert stacked == [(12_000, now, 2)], stacked

    kept = CU.bursts_per_fan(rows((10_000, 0, 3), (2_000, 1_440, 4)))[("a", 1)]
    assert len(kept) == 1 and kept[0][0] == 10_000, kept

    three = CU.bursts_per_fan(
        rows((15_000, 0, 9), (20_000, 2_880, 8), (18_000, 4_320, 7)))[("a", 1)]
    assert len(three) == 3 and sum(b[0] for b in three) == 53_000, three

    assert CU.bursts_per_fan(rows((2_000, 0, 1))) == {}

    chain = rows((5_000, 0, 604), (5_000, 20, 603),
                 (5_000, 40, 602), (5_000, 60, 601))
    walked = CU.bursts_per_fan(chain, min_cents=1)[("a", 1)]
    assert [b[0] for b in walked] == [10_000, 10_000], walked
    newest = CU.orders_per_fan(chain, min_cents=1)[("a", 1)]
    assert newest == walked[0], (newest, walked[0])
    assert newest[1] == now and newest[2] == 604, newest


def case_refunded_money_is_not_owed_work():
    import inspect

    import customs_api

    assert CU.SETTLED_STATUSES == ("cleared", "pending")
    from automations import customs_watch
    assert customs_watch._SETTLED_STATUSES is CU.SETTLED_STATUSES

    src = inspect.getsource(customs_api)
    tip_queries = src.count("Transaction.kind.in_(_customs.ORDER_KINDS)")
    settled = src.count("Transaction.status.in_(_customs.SETTLED_STATUSES)")
    assert tip_queries > 0 and settled == tip_queries, (
        f"{tip_queries} tip queries but only {settled} filter settled money — "
        "a tip query without the status filter shows refunded work as owed")


def case_the_brief_reaches_the_message_that_placed_the_order():
    import inspect

    import customs_api

    src = inspect.getsource(customs_api.customs_brief)
    assert "bursts[-1][1].isoformat()" in src, \
        "the brief must anchor on the oldest outstanding order, not the newest tip"
    assert "_BRIEF_BEFORE" in src and "_BRIEF_AFTER" in src

    sig = inspect.signature(customs_api.customs_context)
    for name, const in (("before", customs_api._BRIEF_BEFORE),
                        ("after", customs_api._BRIEF_AFTER)):
        ceiling = next(m.le for m in sig.parameters[name].default.metadata
                       if hasattr(m, "le"))
        assert const <= ceiling, f"{name}={const} exceeds the endpoint cap {ceiling}"
    assert (customs_api._BRIEF_BEFORE, customs_api._BRIEF_AFTER) == (100, 100), \
        "the operator asked for 100 messages either side of the tip"
    assert "customs_order(" in src, \
        "the brief must merge in the whole-thread order span, not just the window"
    assert '"HIM"' in src and '"US"' in src

    assert "found_request" in src
    assert '"found_request": bool(brief.get("found_request", True))' in src, \
        "a model that omits the field must degrade to the old behaviour"
    assert "NEVER state, guess, split or total any dollar amount" in src

    assert "NEVER state, guess, split or total any dollar amount" in src
    assert '"paid_cents": paid_cents' in src

    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "lines[-40:]" not in code and "said[-40:]" not in code, \
        "tail-truncation drops the request the window was widened to reach"
    assert "lines[:head]" in code, "keep the OLDEST lines — the ask precedes the tip"

    whole = inspect.getsource(customs_api)
    assert whole.count("select(Transaction.account_id, Transaction.fan_id,") == 1, \
        "tip queries must go through _order_tips_q"


_harness.run()
