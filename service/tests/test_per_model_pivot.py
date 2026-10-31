#!/usr/bin/env python3
"""Per-model's pure pivot (`stats_per_model.pivot_models` / `empty_model_row`):
table cases over hand-built read rows, no DB reads, no network.

  pending    a pending sale is revenue, and pending_* is a subset of it
  refunds    a reversal is no revenue; it shows as refunded_cents / _net_cents
  net        OF's net summed, rows with no net counted (net_missing_count)
  OF top-up  `_of_top_ups`' rows add to revenue and net, not to pending,
             refunds or PPV conversions
  zero       a Creator with no traffic is still listed, every field zero / null
  tie        equal revenue keeps the accounts' read order
  engagement off: no ppvs_sent / fans_chatted / avg_reply_seconds keys at all
  subs       active subs null when no source has a signal; ltv / arpu by _safe_div
  source     `pick_active_subs_source`: expires_at, else the 31-day fallback, else unavailable
  patch      a patch on `stats._of_top_ups` reaches `stats.per_model` (slop fault of-zero-erases-db-sale)

Run: ./venv/bin/python service/tests/test_per_model_pivot.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import inspect  # noqa: E402
from datetime import datetime  # noqa: E402
from types import SimpleNamespace as R  # noqa: E402

import of_stats_daily as osd  # noqa: E402
import stats  # noqa: E402
import stats_ops  # noqa: E402
import stats_per_model as spm  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account  # noqa: E402

A, B, C = "acct_a", "acct_b", "acct_c"
ENGAGEMENT_KEYS = {"ppvs_sent", "fans_chatted", "avg_reply_seconds"}


def _sum(aid, kind, status, gross, net=None, net_missing=0, sales=1):
    return R(account_id=aid, kind=kind, status=status, gross_cents=gross, net_cents=net,
             net_missing=net_missing, sales=sales)


# Every read empty; a case names only the reads it fills (pivot_models takes keywords only).
NO_READS = dict(acct_rows=[], r_sums=[], top=[], r_new=[], r_act=[], r_msg=[], r_reply=[], r_pending=[],
                r_spend=[], r_of={}, active_subs_source="unavailable", engagement=False)
ROW_KEYS = {
    "account_id", "display_name", "revenue_by_kind", "pending_by_kind", "total_revenue_cents",
    "total_net_revenue_cents", "net_missing_count", "messages_sent", "ppv_conversions", "new_subs_count",
    "active_subs_count", "ltv_cents", "arpu_cents", "pending_revenue_cents", "pending_clears_by", "refunded_cents",
    "refunded_net_cents", "spenders_count", "avg_spend_per_spender_cents", "avg_spend_per_transaction_cents",
    "of_visitors", "of_renewals", "of_new_sub_conversion_pct", "of_renew_on", "of_renew_on_pct",
}
BUCKETS = {"ppv", "post", "tip", "subscription", "rebill", "custom"}


def one(rows, aid):
    got = [r for r in rows if r["account_id"] == aid]
    assert len(got) == 1, (aid, rows)
    return got[0]


def pivot(acct_rows, sums=(), top=(), **reads):
    return spm.pivot_models(**{**NO_READS, "acct_rows": list(acct_rows), "r_sums": list(sums), "top": list(top),
                               **reads})


def case_stats_keeps_its_names_and_pivot_takes_keywords_only():
    assert stats.per_model is spm.per_model
    assert stats._kind_bucket is spm._kind_bucket
    assert stats.per_automation is stats_ops.per_automation
    params = inspect.signature(spm.pivot_models).parameters.values()
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in params), params
    try:
        spm.pivot_models(*NO_READS.values())
    except TypeError:
        pass
    else:
        raise AssertionError("pivot_models took positional reads")


def case_pending_is_a_subset_of_revenue():
    for sums, total, pending, ppv_pending in [
        ([_sum(A, "ppv_message", "cleared", 1000), _sum(A, "ppv_message", "pending", 500)], 1500, 500, 500),
        ([_sum(A, "tip", "pending", 700)], 700, 700, 0),
        ([_sum(A, "subscription", "cleared", 900)], 900, 0, 0),
    ]:
        row = one(pivot([(A, "a")], sums), A)
        assert row["total_revenue_cents"] == total, (sums, row)
        assert row["pending_revenue_cents"] == pending, (sums, row)
        assert row["pending_by_kind"]["ppv"] == ppv_pending, (sums, row)
        assert sum(row["pending_by_kind"].values()) == pending, row
        assert sum(row["revenue_by_kind"].values()) == total, row
        assert all(row["pending_by_kind"][k] <= row["revenue_by_kind"][k] for k in row["pending_by_kind"]), row


def case_reversals_are_no_revenue_but_refunds():
    for status in ("chargedback", "refunded", "refund_pending"):
        row = one(pivot([(A, "a")], [_sum(A, "ppv_message", "cleared", 1000, net=800),
                                     _sum(A, "ppv_message", status, 400, net=320)]), A)
        assert row["total_revenue_cents"] == 1000, (status, row)
        assert row["total_net_revenue_cents"] == 800, (status, row)
        assert row["ppv_conversions"] == 1, (status, row)
        assert (row["refunded_cents"], row["refunded_net_cents"]) == (400, 320), (status, row)
        assert row["pending_revenue_cents"] == 0, (status, row)


def case_net_summed_and_net_missing_flagged():
    row = one(pivot([(A, "a")], [_sum(A, "tip", "cleared", 1000, net=800),
                                 _sum(A, "tip", "pending", 500, net=None, net_missing=2, sales=2)]), A)
    assert row["total_revenue_cents"] == 1500, row
    assert row["total_net_revenue_cents"] == 800, row
    assert row["net_missing_count"] == 2, row


def case_kinds_bucket_and_ppv_conversions_count_ppv_sales():
    row = one(pivot([(A, "a")], [
        _sum(A, "ppv_message", "cleared", 100, sales=3), _sum(A, "ppv_post", "pending", 200, sales=2),
        _sum(A, "tip_post", "cleared", 50), _sum(A, "tip", "cleared", 10), _sum(A, "rebill", "cleared", 7),
        _sum(A, "weird", "cleared", 1), _sum(A, None, "cleared", 2),
        _sum(A, "ppv_message", "chargedback", 999, sales=9),
    ]), A)
    assert row["revenue_by_kind"] == {"ppv": 100, "post": 250, "tip": 10, "subscription": 0, "rebill": 7,
                                      "custom": 3}, row
    assert row["ppv_conversions"] == 5, row


def case_of_top_up_adds_to_revenue_and_net_only():
    sums = [_sum(A, "ppv_message", "pending", 1000, net=800, sales=4)]
    top = [{"account_id": A, "kind": "tip", "gross_cents": 300, "net_cents": 240},
           {"account_id": A, "kind": "ppv_post", "gross_cents": 50, "net_cents": 40},
           {"account_id": B, "kind": "subscription", "gross_cents": 900, "net_cents": 720}]
    rows = pivot([(A, "a")], sums, top)
    a, b = one(rows, A), one(rows, B)
    assert a["total_revenue_cents"] == 1350 and a["total_net_revenue_cents"] == 1080, a
    assert a["revenue_by_kind"]["tip"] == 300 and a["revenue_by_kind"]["post"] == 50, a
    assert a["pending_revenue_cents"] == 1000 and a["ppv_conversions"] == 4 and a["refunded_cents"] == 0, a
    # A Creator OF alone names still gets a row (display_name unknown).
    assert b["display_name"] is None and b["revenue_by_kind"]["subscription"] == 900, b
    no_top = one(pivot([(A, "a")], sums), A)
    assert no_top["total_revenue_cents"] == 1000, no_top


def case_zero_traffic_creator_listed_every_field_zero_or_null():
    rows = pivot([(A, "a"), (B, "b")], [_sum(A, "tip", "cleared", 100)])
    assert [r["account_id"] for r in rows] == [A, B], rows
    b = one(rows, B)
    assert set(b) == ROW_KEYS, set(b) ^ ROW_KEYS
    assert b["revenue_by_kind"] == dict.fromkeys(BUCKETS, 0), b
    assert b["pending_by_kind"] == dict.fromkeys(BUCKETS, 0), b
    assert b["display_name"] == "b", b
    nulls = {"ltv_cents", "arpu_cents", "active_subs_count", "pending_clears_by", "avg_spend_per_spender_cents",
             "avg_spend_per_transaction_cents", "of_visitors", "of_renewals", "of_new_sub_conversion_pct",
             "of_renew_on", "of_renew_on_pct"}
    for k in ROW_KEYS - {"account_id", "display_name", "revenue_by_kind", "pending_by_kind"}:
        assert b[k] == (None if k in nulls else 0), (k, b[k])
        assert b[k] is None or type(b[k]) is int, (k, b[k])


def case_equal_revenue_keeps_the_accounts_read_order():
    for accts in ([(A, "a"), (B, "b"), (C, "c")], [(C, "c"), (A, "a"), (B, "b")]):
        sums = [_sum(aid, "tip", "cleared", 500) for aid, _ in accts]
        assert [r["account_id"] for r in pivot(accts, sums)] == [aid for aid, _ in accts], accts
    rows = pivot([(A, "a"), (B, "b"), (C, "c")], [_sum(C, "tip", "cleared", 900)])
    assert [r["account_id"] for r in rows] == [C, A, B], rows


def case_empty_row_engagement_and_active_subs():
    for engagement, known, has_keys, active in [
        (False, False, False, None), (False, True, False, 0), (True, False, True, None), (True, True, True, 0),
    ]:
        row = spm.empty_model_row(C, engagement=engagement, active_subs_known=known)
        assert (ENGAGEMENT_KEYS <= set(row)) is has_keys, (engagement, row)
        assert not (ENGAGEMENT_KEYS & set(row)) or has_keys, (engagement, row)
        assert row["active_subs_count"] == active, (known, row)
        if engagement:
            assert (row["ppvs_sent"], row["fans_chatted"], row["avg_reply_seconds"]) == (0, 0, None), row
        assert row["total_revenue_cents"] == 0 and row["ltv_cents"] is None and row["arpu_cents"] is None, row


def case_engagement_off_reads_messages_sent_and_no_engagement_keys():
    row = one(pivot([(A, "a")], r_msg=[R(account_id=A, messages_sent=12)]), A)
    assert row["messages_sent"] == 12 and not (ENGAGEMENT_KEYS & set(row)), row


def case_engagement_on_reads_sends_and_reply_average():
    rows = pivot([(A, "a"), (B, "b")],
                 r_msg=[R(account_id=A, messages=9, ppvs=None, fans=4)],
                 r_reply=[R(account_id=A, replies=2, reply_seconds=30.0),
                          R(account_id=A, replies=1, reply_seconds=None),
                          R(account_id=B, replies=0, reply_seconds=0)],
                 engagement=True)
    a, b = one(rows, A), one(rows, B)
    assert (a["messages_sent"], a["ppvs_sent"], a["fans_chatted"], a["avg_reply_seconds"]) == (9, 0, 4, 10), a
    assert b["avg_reply_seconds"] is None and b["ppvs_sent"] == 0, b


def case_subs_ltv_arpu():
    sums = [_sum(A, "subscription", "cleared", 1000)]
    for source, act, active, arpu in [
        ("unavailable", [R(account_id=A, active_subs=5)], None, None),
        ("subscription_expires_at", [R(account_id=A, active_subs=3)], 3, 333),
        ("transactions_31d", [R(account_id=A, active_subs=0)], 0, None),
    ]:
        row = one(pivot([(A, "a")], sums, r_new=[R(account_id=A, new_subs=4)], r_act=act,
                        active_subs_source=source), A)
        assert row["new_subs_count"] == 4 and row["ltv_cents"] == 250, row
        assert row["active_subs_count"] == active and row["arpu_cents"] == arpu, (source, row)


def case_active_subs_source_prefers_expires_at_then_the_31_day_fallback():
    def act(*counts):
        return [R(account_id=A, active_subs=n) for n in counts]
    for r_act, r_act_tx, want in [
        ([], [], "unavailable"),
        (act(0, None), act(0), "unavailable"),
        (act(1), [], "subscription_expires_at"),
        (act(0, 2), act(5), "subscription_expires_at"),
        ([], act(3), "transactions_31d"),
        (act(0, None), act(None, 1), "transactions_31d"),
    ]:
        assert spm.pick_active_subs_source(r_act, r_act_tx) == want, (r_act, r_act_tx, want)


def case_pending_clears_spenders_and_of_figures():
    figures = {"of_visitors": 40, "of_renewals": 2, "of_new_sub_conversion_pct": 5.0, "of_renew_on": 7,
               "of_renew_on_pct": 70.0}
    row = one(pivot([(A, "a")],
                    r_pending=[R(account_id=A, clears="2026-03-10 12:00:00")],
                    r_spend=[R(account_id=A, spenders=3, cents=1000, sales=4)],
                    r_of={A: figures}), A)
    assert row["pending_clears_by"] == "2026-03-10", row
    assert (row["spenders_count"], row["avg_spend_per_spender_cents"],
            row["avg_spend_per_transaction_cents"]) == (3, 333, 250), row
    assert {k: row[k] for k in figures} == figures, row
    none = one(pivot([(A, "a")], r_pending=[R(account_id=A, clears=None)]), A)
    assert none["pending_clears_by"] is None, none


def case_a_patch_on_stats_of_top_ups_reaches_per_model():
    D = "7400001"

    async def seed():
        async with get_session() as s:
            s.add(Account(id=D, nickname="patched", created_at=datetime(2026, 6, 1)))
            await s.commit()
        # One stored OF day (every category, and their total), so per_model asks for top-ups.
        await osd._upsert_earnings(D, {"2026-06-10": {**{c: (0, 0, 0) for c in osd.EARNINGS},
                                                      osd.TOTAL: (0, 0, 0)}}, datetime(2026, 6, 20))
    asyncio.run(seed())
    calls, real = [], stats._of_top_ups

    async def fake(s, cells, dims):
        calls.append(dims)
        return [{"account_id": D, "kind": "tip", "gross_cents": 4321, "net_cents": 1234}]
    stats._of_top_ups = fake
    try:
        pm = asyncio.run(stats.per_model(from_="2026-06-10", to="2026-06-10", account_id=D, engagement=False))
    finally:
        stats._of_top_ups = real
    assert calls == [("account_id",)], calls
    (row,) = pm["per_model"]
    assert (row["total_revenue_cents"], row["total_net_revenue_cents"]) == (4321, 1234), row
    assert row["revenue_by_kind"]["tip"] == 4321, row


_harness.run()
