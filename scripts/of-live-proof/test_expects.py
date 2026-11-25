import pytest

from expects import ORDER_PARK, Expect, Park, expect_problems, expect_waits, park_problems, resolve_expects
from proof_core import Proof, wire_problems


def _expect_proof(*waits, settled=None):
    return Proof(id="p.sort", phase=3, page="settings/subscription/tracking-links", control="Sort", kind="live",
                 trigger=(("click", "button"), *waits), settled=settled)


def _get(rows_by_sort, calls=None):
    def get(path, query):
        if calls is not None:
            calls.append((path, dict(query)))
        return {"list": [{"name": n} for n in rows_by_sort[query.get("sort", "none")]]}
    return get


NAMES = lambda r: [x["name"] for x in r["list"]]  # noqa: E731
SORT_ROW = "[data-oi-row] .name"
DESC, ASC = {"field": "name", "sort": "desc"}, {"field": "name", "sort": "asc"}


def test_expect_waits_lists_trigger_and_settled_expects_in_run_order():
    desc, asc = Expect("/c", DESC, NAMES), Expect("/c", ASC, NAMES)
    p = _expect_proof(("text", SORT_ROW, desc), ("text", "#oi-toast", "Saved"), settled=("text", SORT_ROW, asc, "page"))
    assert expect_waits(p) == [(1, SORT_ROW, desc), ("settled", SORT_ROW, asc)]
    assert expect_waits(_expect_proof(settled=("text", SORT_ROW, "fixed"))) == []


def test_resolve_expects_reads_only_onlyfans_and_guards_against_its_unsorted_first_row():
    calls = []
    p = _expect_proof(("text", SORT_ROW, Expect("/c", {"limit": 9, **DESC}, NAMES)),
                      settled=("text", SORT_ROW, Expect("/c", {"limit": 9, **ASC}, NAMES)))
    get = _get({"desc": ["Zed", "Mid", "Ann"], "asc": ["Ann", "Mid", "Zed"], "none": ["Mid", "Zed", "Ann"]}, calls)
    assert resolve_expects(expect_waits(p), get) == {1: "Zed", "settled": "Ann"}
    assert calls == [("/c", {"limit": 9, **DESC}), ("/c", {"limit": 9}), ("/c", {"limit": 9, **ASC})]


@pytest.mark.parametrize("rows, why", [
    ({"desc": ["Only"], "none": ["Other"]}, "read 1 row(s)"),
    ({"desc": [], "none": []}, "read 0 row(s)"),
    ({"desc": ["", "Mid"], "none": ["Mid"]}, "first row has no text"),
    ({"desc": ["Zed", "Mid"], "none": [" Zed ", "Mid"]}, "'Zed' is first in /c unsorted too"),
])
def test_resolve_expects_parks_a_wait_that_could_pass_without_the_sort(rows, why):
    p = _expect_proof(settled=("text", SORT_ROW, Expect("/c", DESC, NAMES)))
    with pytest.raises(Park) as e:
        resolve_expects(expect_waits(p), _get(rows))
    assert str(e.value).startswith(ORDER_PARK) and why in str(e.value)


def test_resolve_expects_parks_a_second_wait_the_first_already_shows():
    p = _expect_proof(("text", SORT_ROW, Expect("/c", DESC, NAMES)),
                      settled=("text", SORT_ROW, Expect("/c", ASC, NAMES)))
    with pytest.raises(Park, match="'Zed' is first for the previous wait too"):
        resolve_expects(expect_waits(p), _get({"desc": ["Zed", "Ann"], "asc": ["Zed", "Ann"], "none": ["Mid", "Zed"]}))


def _w(seq, method, path, query="", origin="app"):
    return {"seq": seq, "origin": origin, "method": method, "path": path, "query": query, "verdict": "read"}


def test_a_read_proofs_wire_check_needs_the_apps_get_with_each_expects_field_and_sort():
    p = _expect_proof(("text", SORT_ROW, Expect("/api2/v2/c", {"limit": 9, **DESC}, NAMES)),
                      settled=("text", SORT_ROW, Expect("/api2/v2/c", {"limit": 9, **ASC}, NAMES)))
    both = [_w(1, "GET", "/api2/v2/c", "limit=10&offset=0"), _w(2, "GET", "/api2/v2/c", "limit=10&field=name&sort=desc"),
            _w(3, "GET", "/api2/v2/c", "field=name&sort=asc&limit=10")]
    assert expect_problems(p, both) == []
    client_side = [both[0], _w(4, "GET", "/api2/v2/c", "field=name&sort=asc", origin="driver")]
    probs = expect_problems(p, client_side)
    assert len(probs) == 2 and all("the sort did not reach OnlyFans" in x for x in probs)
    assert expect_problems(p, both[:2]) == ["the app sent no GET /api2/v2/c with {'field': 'name', 'sort': 'asc'}: "
                                            "the sort did not reach OnlyFans"]


@pytest.mark.parametrize("load, keys", [("field=name&sort=desc", DESC), ("limit=10&sort=asc", {"sort": "asc"}),
                                       ("field=created_at", {"field": "created_at"})])
def test_a_read_proofs_wire_check_fails_a_page_that_loads_already_sorted(load, keys):
    p = _expect_proof(("text", SORT_ROW, Expect("/api2/v2/c", DESC, NAMES)),
                      settled=("text", SORT_ROW, Expect("/api2/v2/c", ASC, NAMES)))
    window = [_w(1, "GET", "/api2/v2/c", load), _w(2, "GET", "/api2/v2/c", "field=name&sort=desc"),
              _w(3, "GET", "/api2/v2/c", "field=name&sort=asc")]
    assert expect_problems(p, window) == [f"the app's first GET /api2/v2/c carried {keys} at page load: "
                                          "not the unsorted baseline"]


def test_the_expect_check_runs_beside_wire_problems_not_inside_it():
    p = _expect_proof(settled=("text", SORT_ROW, Expect("/api2/v2/c", DESC, NAMES)))
    assert wire_problems(p, []) == []


@pytest.mark.parametrize("window, undo, bad", [
    ([_w(5, "GET", "/api2/v2/c", origin="driver")], ["none"], 0),
    ([_w(5, "GET", "/api2/v2/c")], ["none"], 1),
    ([_w(5, "PATCH", "/api2/v2/c", origin="driver")], ["none"], 1),
    ([], ["undone"], 1),
])
def test_a_park_counts_only_when_nothing_was_sent_and_no_undo_row_closed(window, undo, bad):
    assert len(park_problems("parked — x", window, undo)) == bad
