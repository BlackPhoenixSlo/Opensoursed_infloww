#!/usr/bin/env python3
"""report_recipe_decide: the report recipe's pure rules (tables).

Run: ./venv/bin/python service/tests/test_report_recipe_decide.py   (exit 0 = green)
"""
from __future__ import annotations

import _harness  # MUST be first

from datetime import date, datetime  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

import report_recipe_decide as d  # noqa: E402

TODAY = date(2026, 11, 13)  # a Friday


def _recipe(**raw):
    raw.setdefault("dataset", "sales")
    raw.setdefault("window", {"preset": "last_7_days"})
    r, errors = d.parse_recipe(raw)
    assert r is not None, errors
    return r


def case_parse_errors_per_field():
    table = [
        ({"dataset": "departed_subs", "window": {"preset": "today"}}, "dataset", "nearest is fan_spend"),
        ({"dataset": "sales", "window": {"preset": "forever"}}, "window", "unknown preset"),
        ({"dataset": "sales", "window": {"from": "2026-11-05", "to": "2026-11-01"}}, "window", "before"),
        ({"dataset": "sales", "window": {"from": "2026-02-30", "to": "2026-03-01"}}, "window", "not a date"),
        ({"dataset": "sales", "window": {"from": "yesterday", "to": "2026-03-01"}}, "window", "YYYY-MM-DD"),
        ({"dataset": "sales", "window": {"preset": "today"}, "kinds": ["dance"]}, "kinds", "unknown kind dance"),
        ({"dataset": "chat_activity", "window": {"preset": "today"}, "kinds": ["ppv"]}, "kinds", "no kinds"),
        ({"dataset": "sales", "window": {"preset": "today"}, "employees": [3]}, "employees", "no Employees"),
        ({"dataset": "chat_activity", "window": {"preset": "today"}, "employees": ["Ana"]}, "employees", "ids"),
        ({"dataset": "sales", "window": {"preset": "today"}, "group_by": ["employee"]}, "group_by", "unknown key"),
        ({"dataset": "sales", "window": {"preset": "today"}, "group_by": ["day", "month"]}, "group_by", "at most one"),
        ({"dataset": "fan_spend", "window": {"preset": "today"}, "group_by": ["creator"]}, "group_by", "always by"),
        ({"dataset": "sales", "window": {"preset": "today"}, "metrics": ["messages"]}, "metrics", "unknown metric"),
        ({"dataset": "sales", "window": {"preset": "today"}, "sort": "chars"}, "sort", "group_by keys or metrics"),
        # fan_spend sorts + cuts in SQL: a key sort there would cut the wrong rows (review F1).
        ({"dataset": "fan_spend", "window": {"preset": "today"}, "sort": "fan", "limit": 1}, "sort", "chosen metrics"),
        ({"dataset": "fan_spend", "window": {"preset": "today"}, "sort": "creator"}, "sort", "chosen metrics"),
        ({"dataset": "sales", "window": {"preset": "today"}, "limit": 0}, "limit", "1 to"),
        ({"dataset": "sales", "window": {"preset": "today"}, "limit": True}, "limit", "1 to"),
        ({"dataset": "sales", "window": {"preset": "today"}, "creators": [1]}, "creators", "Creator ids"),
        ({"dataset": "sales", "window": {"preset": "today"}, "creators": [str(i) for i in range(51)]},
         "creators", "at most 50"),
        ({"dataset": "sales", "window": {"preset": "today"}, "sql": "drop"}, "sql", "unknown field"),
    ]
    for raw, field, want in table:
        r, errors = d.parse_recipe(raw)
        assert r is None, raw
        assert want in errors.get(field, ""), (raw, errors)
    assert d.parse_recipe("x") == (None, {"recipe": "must be an object"})


def case_parse_defaults_and_dedupe():
    r = _recipe(creators=["1", "1", "2"], kinds=["ppv", "ppv"])
    assert r.creators == ("1", "2") and r.kinds == ("ppv",)
    assert r.group_by == ("creator",) and r.metrics == ("gross", "net_or_80", "sales")
    f = _recipe(dataset="fan_spend", group_by=["creator", "fan"], sort="tips", limit=10)
    assert f.group_by == ("creator", "fan") and f.sort == "tips" and f.limit == 10
    c = _recipe(dataset="chat_activity", employees=[4, 4, 5], group_by=["employee", "hour"])
    assert c.employees == (4, 5) and c.group_by == ("employee", "hour")
    assert _recipe(window={"from": "2026-11-01", "to": "2026-11-03"}).window == ("range", "2026-11-01", "2026-11-03")
    assert d.parse_recipe(r.as_dict())[0] == r  # round trip


def case_sort_key_is_the_one_ordering():
    # shape and fan_spend's SQL ORDER BY both read sort_key (review F1): sort, else the time key, else metrics[0].
    assert d.sort_key(_recipe(dataset="fan_spend", metrics=["tips"], limit=1)) == "tips"
    assert d.sort_key(_recipe(dataset="fan_spend", metrics=["total", "tips"], sort="tips")) == "tips"
    assert d.sort_key(_recipe(group_by=["creator", "day"])) == "day"
    assert d.sort_key(_recipe(group_by=["creator"], sort="creator")) == "creator"
    assert d.order_label(_recipe(dataset="fan_spend", metrics=["tips"])) == "Tips ($), high to low"
    assert d.order_label(_recipe(group_by=["creator", "week"])) == "Week of, oldest first"
    assert d.order_label(_recipe(group_by=["creator"], sort="creator")) == "Creator, A to Z"


def case_resolve_window_presets():
    table = [
        ("today", "monday", (TODAY, TODAY)),
        ("yesterday", "monday", (date(2026, 11, 12), date(2026, 11, 12))),
        ("this_week", "monday", (date(2026, 11, 9), date(2026, 11, 15))),
        ("this_week", "sunday", (date(2026, 11, 8), date(2026, 11, 14))),
        ("this_month", "monday", (date(2026, 11, 1), date(2026, 11, 30))),
        ("last_7_days", "monday", (date(2026, 11, 7), TODAY)),
        ("last_30_days", "monday", (date(2026, 10, 15), TODAY)),
        ("last_90_days", "monday", (date(2026, 8, 16), TODAY)),
        ("last_365_days", "monday", (date(2025, 11, 14), TODAY)),
    ]
    for preset, ws, want in table:
        got, err = d.resolve_window(_recipe(window={"preset": preset}), TODAY, ws)
        assert (got, err) == (want, None), (preset, got, err)
    dec = date(2026, 12, 3)
    assert d.resolve_window(_recipe(window={"preset": "this_month"}), dec)[0] == (date(2026, 12, 1), date(2026, 12, 31))


def case_resolve_window_caps():
    table = [
        ("sales", {"preset": "last_365_days"}, (), None),
        ("sales", {"from": "2025-01-01", "to": "2026-02-05"}, (), "at most 400"),  # 401 days
        ("employee_sales", {"preset": "last_90_days"}, (), None),
        ("employee_sales", {"from": "2026-08-01", "to": "2026-11-01"}, (), "at most 92"),  # 93 days
        ("chat_activity", {"preset": "last_30_days"}, ("hour",), None),
        ("chat_activity", {"preset": "last_90_days"}, ("hour",), "by hour"),
    ]
    for ds, window, group_by, want in table:
        got, err = d.resolve_window(_recipe(dataset=ds, window=window, group_by=list(group_by)), TODAY)
        assert (err is None) == (want is None) and (want is None or want in err), (ds, window, err)
        assert (got is None) == (want is not None)


def case_today_in_zone():
    now = datetime(2026, 11, 13, 23, 30)
    assert d.today_in(None, now) == date(2026, 11, 13)
    assert d.today_in(ZoneInfo("Asia/Tokyo"), now) == date(2026, 11, 14)
    assert d.today_in(ZoneInfo("America/Los_Angeles"), datetime(2026, 11, 13, 3)) == date(2026, 11, 12)


def case_clamp_creators():
    owned = {"a", "b", "c"}
    table = [
        ((), owned, set(), False, (["a", "b", "c"], None)),
        (("b",), owned, set(), False, (["b"], None)),
        (("b", "z"), owned, set(), False, (None, "not one of your Creators: z")),
        ((), set(), set(), False, ([], None)),
        ((), owned, {"b"}, False, (["a", "b", "c"], None)),
        ((), owned, {"b"}, True, (None, "Creator b is shared")),
        (("a",), owned, {"b"}, True, (["a"], None)),
    ]
    for named, own, co, refuse, want in table:
        got = d.clamp_creators(named, own, co_owned=co, refuse_co_owned=refuse)
        assert got[0] == want[0] and (got[1] or "").startswith(want[1] or ""), (named, got)
    many = {str(i) for i in range(51)}
    assert d.clamp_creators((), many)[1].startswith("at most 50")


def case_kind_maps_match_the_engines():
    from attribution_backfill import PPV_KINDS, REVENUE_KINDS, TIP_KINDS
    from sales_attribution import SUBSCRIPTION_KINDS
    from stats_per_model import _kind_bucket
    assert set(d.LEDGER_KINDS) == set(REVENUE_KINDS) | set(SUBSCRIPTION_KINDS)
    for k in (*d.LEDGER_KINDS, None, "", "unknown"):
        assert d.sales_kind(k) == _kind_bucket(k), k
    assert d.ledger_kinds(("ppv",)) == PPV_KINDS
    assert d.ledger_kinds(("tip",)) == TIP_KINDS
    assert d.ledger_kinds(("subscription",)) == ("subscription", "rebill")
    assert d.ledger_kinds(("other",)) == ("custom", "referral")
    for name, ds in d.CATALOGUE.items():
        for k in ds.kinds:
            assert k in d.KIND_LABELS, (name, k)
        kind_of = d.sales_kind if name == "sales" else d.ledger_kind
        assert set(ds.kinds) <= {kind_of(k) for k in d.LEDGER_KINDS}, name


def case_shape_sums_sorts_and_dollars():
    r = _recipe(group_by=["creator"], metrics=["gross", "sales"])
    cells = [{"creator": "a", "gross_cents": 1050, "sales": 1}, {"creator": "b", "gross_cents": 5000, "sales": 2},
             {"creator": "a", "gross_cents": 950, "sales": 3}]
    cols, rows = d.shape(r, cells, {"creator": {"a": "Ana", "b": "Bea"}})
    assert cols == ["Creator", "Gross ($)", "Sales"]
    assert rows == [["Bea", 50.0, 2], ["Ana", 20.0, 4]], rows
    # A key sort runs A to Z; limit cuts after sorting.
    r2 = _recipe(group_by=["creator"], metrics=["gross"], sort="creator", limit=1)
    assert d.shape(r2, cells, {"creator": {"a": "Ana", "b": "Bea"}})[1] == [["Ana", 20.0]]
    # The time key orders by default, ties by the first metric.
    r3 = _recipe(group_by=["kind", "day"], metrics=["gross"])
    cells3 = [{"kind": "tip", "day": "2026-11-02", "gross_cents": 100},
              {"kind": "ppv", "day": "2026-11-01", "gross_cents": 100},
              {"kind": "tip", "day": "2026-11-01", "gross_cents": 300}]
    assert d.shape(r3, cells3)[1] == [["Tips", "2026-11-01", 3.0], ["PPV", "2026-11-01", 1.0],
                                      ["Tips", "2026-11-02", 1.0]]


def case_shape_unlock_rate_after_grouping():
    r = _recipe(dataset="chat_activity", group_by=["employee"], metrics=["ppvs_sent", "unlock_rate"])
    cells = [{"employee": 1, "ppvs": 3, "unlocked": 1}, {"employee": 1, "ppvs": 1, "unlocked": 1},
             {"employee": None, "ppvs": 0, "unlocked": 0, "messages": 4}]
    cols, rows = d.shape(r, cells, {"employee": {1: "Ana"}})
    assert cols == ["Employee", "PPVs sent", "Unlock rate (%)"]
    assert rows == [["Ana", 4, 50.0], ["Unattributed", 0, None]], rows
    # Sorting by a rate puts the blank last.
    r2 = _recipe(dataset="chat_activity", group_by=["employee"], metrics=["unlock_rate"], sort="unlock_rate")
    assert d.shape(r2, cells, {"employee": {1: "Ana"}})[1][-1] == ["Unattributed", None]


def case_labels_and_filename():
    assert d.period_label("2026-11-13", "week") == "2026-11-09"
    assert d.period_label("2026-11-13", "week", "sunday") == "2026-11-08"
    assert d.period_label("2026-11-13", "month") == "2026-11"
    assert d.period_label("2026-11-13", "day") == "2026-11-13"
    tokyo = ZoneInfo("Asia/Tokyo")
    assert d.edge_label(datetime(2026, 11, 12, 15), tokyo, "day") == "2026-11-13"
    assert d.edge_label(datetime(2026, 11, 12, 15), tokyo, "hour") == "2026-11-13 00:00"
    assert d.edge_label(datetime(2026, 10, 31, 15), tokyo, "month") == "2026-11"
    assert d.edge_label(datetime(2026, 11, 1), None, "day") == "2026-11-01"
    assert d.filename("employee_sales", date(2026, 11, 1), date(2026, 11, 7), "xlsx") == \
        "employee-sales_2026-11-01_to_2026-11-07.xlsx"


def case_catalogue_text_is_stable_and_covers_every_dataset():
    t = d.catalogue_text()
    assert t == d.catalogue_text()
    names = [line.split(":")[0][2:] for line in t.splitlines()]
    assert names == sorted(d.CATALOGUE), names
    assert "longest window: 92 days" in t
    j = d.catalogue_json()
    assert [x["dataset"] for x in j["datasets"]] == sorted(d.CATALOGUE)
    assert j["presets"] == list(d.PRESETS)


def case_nearest_dataset():
    for ask, want in [("departed subscribers", "fan_spend"), ("chatter commission", "employee_sales"),
                      ("revenue by model", "sales"), ("sale", "sales"), ("zzz", "sales")]:
        assert d.nearest_dataset(ask) == want, ask


_harness.run()
