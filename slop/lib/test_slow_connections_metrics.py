"""thread_reads: an older page (`before_id`) is its own read per cursor, never the open's local read; a route read twice
(attribution bare, then `since_id`) stays a duplicate."""
import re

from slop.lib.slow_connections_metrics import thread_reads

LOCAL = (re.compile(r"^/admin/messages/\d+/\d+(\?|/attribution|$)"),)


def _g(path: str, start: float = 0, account: str | None = None) -> dict:
    return {"method": "GET", "path": path, "start": start, "account": account}


def test_one_route_per_creator_is_not_a_dupe():
    """Two Creators' reads of one route (the thread's Creator, another the warm reached) are each one read."""
    r = thread_reads([_g("/api/of/v2/users/notifications?type=tip", account="1"),
                      _g("/api/of/v2/users/notifications?type=tip", account="2")], 100, LOCAL)
    assert r["dupes"] == {}


def test_one_creator_reading_a_route_twice_is_a_dupe_whatever_the_query():
    r = thread_reads([_g("/api/of/v2/users/notifications?type=purchases", account="1"),
                      _g("/api/of/v2/users/notifications?type=tip", account="1"),
                      _g("/api/of/v2/users/notifications?type=tip", account="2")], 100, LOCAL)
    assert r["dupes"] == {"1 /api/of/v2/users/notifications": 2}


def test_attribution_twice_for_one_creator_still_a_dupe():
    r = thread_reads([_g("/admin/messages/1/7/attribution", account="1"),
                      _g("/admin/messages/1/7/attribution?since_id=9", account="1")], 100, LOCAL)
    assert r["dupes"] == {"1 /admin/messages/1/7/attribution": 2}


def test_fill_page_is_not_a_dupe_nor_local():
    r = thread_reads([_g("/api/of/v2/chats/7/messages?limit=30&order=desc"), _g("/admin/screens/chat?account=1&fan=7"),
                      _g("/admin/messages/1/7?limit=30&before_id=5"),
                      _g("/api/of/v2/chats/7/messages?limit=30&order=desc&before_id=5")], 100, LOCAL)
    assert r["dupes"] == {} and r["local"] == [] and r["older"] == 1 and r["bundle"] == 1


def test_same_older_page_twice_is_a_dupe():
    r = thread_reads([_g("/api/of/v2/chats/7/messages?before_id=5"), _g("/api/of/v2/chats/7/messages?before_id=5")],
                     100, LOCAL)
    assert r["dupes"] == {"/api/of/v2/chats/7/messages?before_id=5": 2} and r["older"] == 1


def test_attribution_twice_still_a_dupe_and_local():
    r = thread_reads([_g("/admin/messages/1/7/attribution"), _g("/admin/messages/1/7/attribution?since_id=9")],
                     100, LOCAL)
    assert r["dupes"] == {"/admin/messages/1/7/attribution": 2} and len(r["local"]) == 2 and r["older"] == 0
