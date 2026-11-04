#!/usr/bin/env python3
"""push_decide (pure): should_push matrix, outcome table, retry delays, SSRF guard, Seen LRU/TTL.
Run: venv/bin/python -m pytest service/tests/test_push_decide.py -q"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # pytest: tests/ is a package
import _harness  # noqa: E402,F401  (first: temp DB)

from types import SimpleNamespace as NS

import push_decide as pd

N = NS(account_id="1", type_key="purchases", tag="1:9001")


def _sub(types=("purchases", "message"), platforms=None):
    return NS(types=frozenset(types), platforms=platforms or {})


def test_should_push_matrix():
    acc = frozenset({"1"})
    assert pd.should_push(_sub(), N, acc, "onlyfans", pd.Seen())
    assert not pd.should_push(_sub(), N, None, "onlyfans", None), "dead session"
    assert not pd.should_push(_sub(), N, frozenset({"2"}), "onlyfans", None), "out of scope"
    assert not pd.should_push(_sub(), N, frozenset(), "onlyfans", None), "no accounts"
    assert not pd.should_push(_sub(types=()), N, acc, "onlyfans", None), "push off"
    assert not pd.should_push(_sub(types=("message",)), N, acc, "onlyfans", None), "type off"
    assert not pd.should_push(_sub(platforms={"onlyfans": False}), N, acc, "onlyfans", None)
    assert pd.should_push(_sub(platforms={"fansly": False}), N, acc, "onlyfans", None)
    unknown = NS(account_id="1", type_key=None, tag="1:x")
    assert not pd.should_push(_sub(types=("message", "purchases")), unknown, acc, "onlyfans", None), \
        "an OF type the app can't name is never pushed (pushTypes)"
    seen = pd.Seen()
    seen.add(N.tag, 0.0)
    assert not pd.should_push(_sub(), N, acc, "onlyfans", seen, 10.0), "deduped"
    assert pd.should_push(_sub(), N, acc, "onlyfans", seen, pd.DEDUPE_TTL_S + 1), "TTL lapsed"


def test_outcome_table():
    table = {None: "retry", 200: "ok", 201: "ok", 202: "ok", 400: "fail", 403: "fail", 404: "prune",
             410: "prune", 413: "fail", 429: "retry", 500: "retry", 503: "retry"}
    assert {s: pd.outcome(s) for s in table} == table


def test_retry_delay():
    assert pd.retry_delay(0) == 1.0 and pd.retry_delay(1) == 4.0 and pd.retry_delay(2) is None
    assert pd.retry_delay(0, "7") == 7.0 and pd.retry_delay(0, "999") == pd.RETRY_AFTER_MAX_S
    assert pd.retry_delay(0, "Wed, 21 Oct 2015 07:28:00 GMT") == 1.0
    assert pd.retry_delay(2, "3") is None


def test_endpoint_allowed():
    H = pd.DEFAULT_HOSTS
    ok = ["https://fcm.googleapis.com/fcm/send/abc", "https://web.push.apple.com/QK",
          "https://api.push.apple.com/x", "https://wns2-par02p.notify.windows.com/w/?token=1",
          "https://updates.push.services.mozilla.com/wpush/v2/x", "https://fcm.googleapis.com:443/x"]
    # userinfo URLs built with {}: a literal user@host reads as an email to the public leak gate
    bad = ["http://fcm.googleapis.com/x", "https://fcm.googleapis.com:8443/x",
           *(f"https://{ui}@fcm.googleapis.com/x" for ui in ("user", "a:b")),
           "https://fcm.googleapis.com.evil.com/x", "https://evilfcm.googleapis.com/x",
           "https://push.apple.com/x", "https://evilpush.apple.com/x", "https://127.0.0.1/x",
           "http://localhost:9/x", "https://10.0.0.1/x", "ftp://fcm.googleapis.com/x",
           "https://fcm.googleapis.com/" + "a" * pd.ENDPOINT_MAX, "", None, 42, "https:///x",
           "https://[::1/x"]
    assert [u for u in ok if not pd.endpoint_allowed(u, H)] == []
    assert [u for u in bad if pd.endpoint_allowed(u, H)] == []
    lo = pd.parse_hosts("127.0.0.1, fcm.googleapis.com")
    assert pd.endpoint_allowed("http://127.0.0.1:8123/push/1", lo)
    assert not pd.endpoint_allowed("http://localhost:8123/push/1", lo), "only the listed loopback"
    assert not pd.endpoint_allowed("http://fcm.googleapis.com/x", lo)
    assert pd.parse_hosts("") == H and pd.parse_hosts(None) == H


def test_seen_lru_ttl():
    s = pd.Seen()
    for i in range(pd.DEDUPE_MAX + 5):
        s.add(f"t{i}", 0.0)
    assert not s.has("t0", 1.0) and not s.has("t4", 1.0) and s.has("t5", 1.0)
    assert s.has(f"t{pd.DEDUPE_MAX + 4}", 1.0)
    assert not s.has("t5", pd.DEDUPE_TTL_S)


def test_shard_stable():
    assert pd.shard("abc", 8) == pd.shard("abc", 8) and 0 <= pd.shard("abc", 8) < 8
    assert len({pd.shard(f"s{i}", 8) for i in range(200)}) == 8


if __name__ == "__main__":
    import sys
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if fails else 0)
