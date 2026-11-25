import asyncio
import json
from datetime import datetime, timezone

import pytest
from starlette.requests import Request as SRequest

import fake_layer
import prove
import undo_driver
from proof_core import Request, Run, decide
from proofs import ALL, phase6
from soak import ids
from soak.fake_of import render, vault

P = phase6.VAULT_CUSTOMIZE_ORDER
BEFORE = {"sort": "custom", "order": "desc", "ids": ["3", "1", "2"]}


def test_defined_with_its_record_label_and_page():
    assert ALL[P.id] is P and P.control == "Customize order Save" and P.page == "vault/state-lists-sort-dropdown"
    assert P.precheck is phase6.order_unrecoverable and P.undo[0].max == 2


def test_read_folder_order_walks_every_page():
    pages = {0: {"sort": "custom", "order": "desc", "list": [{"id": 3}, {"id": 1}], "hasMore": True},
             2: {"list": [{"id": 2}], "hasMore": False}}
    seen = []

    def get(path, q):
        seen.append((path, q["offset"]))
        return pages[q["offset"]]

    assert phase6.read_folder_order(get, None) == BEFORE
    assert seen == [("/api2/v2/vault/lists", 0), ("/api2/v2/vault/lists", 2)]


@pytest.mark.parametrize("before, want", [
    (BEFORE, None),
    (None, "no folder read"),
    ({"ids": ["1", "2"]}, "no known sort and order"),
    ({**BEFORE, "sort": "popular"}, "no known sort and order"),
    ({**BEFORE, "sort": "recent"}, "sort is 'recent'"),
    ({**BEFORE, "ids": ["1"]}, "cannot be sent back"),
    ({**BEFORE, "ids": ["1", "1"]}, "cannot be sent back"),
    ({**BEFORE, "ids": ["1", "x"]}, "cannot be sent back"),
], ids=["stored custom order", "no read", "no sort (OnlyFans dropped it)", "unknown sort", "another sort",
        "one folder", "duplicate ids", "non-numeric id"])
def test_order_unrecoverable(before, want):
    got = phase6.order_unrecoverable(before)
    if want is None:
        assert got is None
    else:
        assert got.startswith("pre-proof order not recoverable: ") and want in got


@pytest.mark.parametrize("after, want", [
    ({"sort": "custom", "order": "desc", "ids": ["1", "3", "2"]}, True),
    (BEFORE, False),
    ({"sort": "recent", "order": "desc", "ids": ["1", "3", "2"]}, False),
    ({"sort": "custom", "order": "desc", "ids": ["1", "3"]}, False),
    (None, False),
], ids=["reordered", "unchanged", "not custom", "a folder lost", "no read"])
def test_order_changed(after, want):
    assert phase6.order_changed(BEFORE, after) is want


def test_restore_steps_custom_order_then_sort_each_with_its_confirm():
    assert P.undo_steps is phase6.restore_steps and P.undo[0].relay_body is None and P.undo_ids is None
    (k1, b1, c1), (k2, b2, c2) = phase6.restore_steps(BEFORE)
    assert (k1, k2) == (0, 0)
    assert b1 == {"account_id": "{account}", "custom_order": [3, 1, 2]}
    assert b2 == {"account_id": "{account}", "sort": "custom", "order": "desc"}
    assert c1(dict(BEFORE)) and not c1({**BEFORE, "ids": ["1", "3", "2"]})
    assert c2(dict(BEFORE)) and not c2({**BEFORE, "order": "asc"})


class _Relay:

    def __init__(self, statuses):
        self.statuses, self.calls, self.lines = list(statuses), [], []

    def __call__(self, method, route, data=None, account=None):
        self.calls.append((method, route, data, account))
        status = self.statuses.pop(0)
        self.lines.append({"seq": len(self.lines) + 1, "method": method, "path": phase6.SORT_PATH, "status": status,
                           "verdict": "reversal"})
        return (200 if status < 300 else 502), b""

    def wire(self):
        return list(self.lines)


@pytest.mark.parametrize("statuses, sent, state, problem", [
    ([200, 200], 2, "undone", None),
    ([500], 1, "FAILED", 'undo step 1 (%s {"account_id": "acct", "custom_order": [3, 1, 2]}) answered 502'),
], ids=["both restored", "the first answered 500: the sort is never sent"])
def test_settle_sends_the_restore_steps_with_the_account_and_stops_on_a_refusal(statuses, sent, state, problem):
    w = _Relay(statuses)
    res, reads = {"problems": [], "screens": []}, []
    row = {"row": 1, "arm": 0, "write": {"method": "POST", "path": phase6.SORT_PATH}, "of_id": None}
    (c,) = undo_driver.settle_rows(P, [row], w, w.wire, lambda tag: reads.append(tag) or dict(BEFORE), creator="acct",
                                   before=BEFORE, after={**BEFORE, "ids": ["1", "3", "2"]}, effect=True, keys={},
                                   sent={}, res=res)
    assert [(m, r, a) for m, r, _, a in w.calls] == [("POST", phase6.SORT_ROUTE, "acct")] * sent
    assert [d for _, _, d, _ in w.calls] == [{"account_id": "acct", "custom_order": [3, 1, 2]},
                                             {"account_id": "acct", "sort": "custom", "order": "desc"}][:sent]
    assert c["state"] == state and len(c["reversals"]) == sent
    assert reads == [f"after-undo-step-{n}" for n in range(1, (sent if state == "undone" else 0) + 1)] + ["after-undo"]
    if problem:
        assert any(problem % phase6.SORT_ROUTE in p for p in res["problems"]), res["problems"]



def test_settle_of_no_rows_sends_no_restore_step():
    w = _Relay([200, 200])
    res = {"problems": [], "screens": []}
    assert undo_driver.settle_rows(P, [], w, w.wire, lambda tag: pytest.fail("no read"), creator="acct", before=BEFORE,
                                   after=None, effect=None, keys={}, sent={}, res=res) == []
    assert w.calls == [] and "sequence" not in res

def _seen(body, shown, links):
    wire = [{"verdict": "allow", "method": "POST", "path": phase6.SORT_PATH, "body": body}]
    return {"wire": wire, "dom": [{"items_selector": phase6.ORDER_ROW, "items": [{"value": v} for v in shown]},
                                  {"items_selector": phase6.FOLDER_LINK, "items": [{"value": v} for v in links]}]}


def _links(order):
    return ["/of-manager/vault?list=701"] + [f"/of-manager/vault?list={i}" for i in order] + ["/of-manager/vault?list=701"]


@pytest.mark.parametrize("seen, want", [
    (_seen({"customOrder": [2, 3, 1], "sort": "custom"}, ["3", "1", "2"], _links(["2", "3", "1"])), []),
    (_seen({"customOrder": [3, 1, 2], "sort": "custom"}, ["3", "1", "2"], _links(["3", "1", "2"])),
     ["drag changed nothing"]),
    (_seen({"customOrder": [2, 3, 1], "sort": "custom"}, ["3", "1", "2"], _links(["3", "1", "2"])),
     ["not in the saved order"]),
    (_seen({"customOrder": ["2", "3", "1"], "sort": "custom"}, ["3", "1", "2"], _links(["2", "3", "1"])),
     ["not {customOrder"]),
    (_seen({"sort": "name", "order": "asc"}, ["3", "1", "2"], _links(["2", "3", "1"])), ["not {customOrder"]),
    (_seen({"customOrder": [2, 3], "sort": "custom"}, ["3", "1", "2"], _links(["2", "3"])), ["other folders"]),
    ({"wire": [], "dom": []}, ["0 allowed POST"]),
], ids=["saved and kept", "no drag", "lost on reload", "string ids", "a sort pick, not a custom order",
        "a folder dropped", "no Save"])
def test_customize_order_check(seen, want):
    whole = phase6.customize_order_check(seen)
    assert whole["parked"] is None and whole["record"] == {}
    got = whole["problems"]
    assert len(got) == len(want) and all(w in g for w, g in zip(want, got)), got



def _decide(body, run):
    return decide(Request("POST", "onlyfans.com", phase6.SORT_PATH, body, datetime.now(timezone.utc)), run)


def test_guard_allows_the_save_then_two_undo_calls_and_refuses_a_fourth():
    run = Run(proof=P, of="fake")
    got = []
    for body in ({"customOrder": [2, 3, 1], "sort": "custom"}, {"customOrder": [3, 1, 2], "sort": "custom"},
                 {"sort": "custom", "order": "desc"}, {"sort": "name", "order": "asc"}):
        v = _decide(body, run)
        got.append((v.kind, v.cls))
        if v.kind != "refused":
            run = Run(proof=P, of="fake", spent={**run.spent, v.key: run.spent.get(v.key, 0) + 1})
    assert [k for k, _ in got] == ["allow", "reversal", "reversal", "refused"] and got[-1][1] == "over_count"


def test_guard_refuses_the_sort_with_no_proof_armed():
    v = _decide({"sort": "name", "order": "asc"}, Run(proof=None, of="fake"))
    assert v.kind == "refused" and v.cls == "unarmed"



class _Fake:
    def __init__(self):
        self.logged = []

    def _log(self, req, status, modelled, body=None):
        self.logged.append((req.method, req.url.path, status, body))


def _req(method, path, query="", body=None):
    raw = json.dumps(body).encode() if body is not None else b""

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    return SRequest({"type": "http", "method": method, "path": path, "query_string": query.encode(), "headers": [],
                     "scheme": "http", "server": ("127.0.0.1", 80)}, receive)


def _lists(fake, query="view=main&limit=50"):
    return asyncio.run(vault._lists(fake, _req("GET", "/api2/v2/vault/lists", query), lambda req, d: d))


def _sort(fake, body):
    return asyncio.run(vault._sort(fake, _req("POST", "/api2/v2/vault/lists/sort", body=body), None)).status_code


def test_fake_starts_on_a_stored_custom_order_that_is_not_the_default():
    fake = _Fake()
    d = _lists(fake)
    default = [r["id"] for r in vault._rows(render._tpl("vault-lists.json"))]
    got = [r["id"] for r in d["list"]]
    assert d["sort"] == "custom" and d["order"] == "desc" and d["hasMore"] is False
    assert sorted(got) == sorted(default) and got != default and got[0] == ids.vault_list_id(vault.FOLDERS)
    p0, p1 = _lists(fake, "limit=4&offset=0"), _lists(fake, "limit=50&offset=4")
    assert p0["hasMore"] is True and [r["id"] for r in p0["list"] + p1["list"]] == got


def test_fake_sort_takes_the_two_relay_bodies_and_refuses_others():
    fake = _Fake()
    new = [r["id"] for r in _lists(fake)["list"]][::-1]
    assert _sort(fake, {"customOrder": new, "sort": "custom"}) == 200
    assert [r["id"] for r in _lists(fake)["list"]] == new
    assert _sort(fake, {"sort": "name", "order": "asc"}) == 200
    d = _lists(fake)
    assert (d["sort"], d["order"]) == ("name", "asc")
    bad = ({"customOrder": new, "sort": "name"}, {"customOrder": [str(i) for i in new], "sort": "custom"},
           {"customOrder": [new[0], new[0]], "sort": "custom"}, {"customOrder": [999999], "sort": "custom"},
           {"customOrder": [], "sort": "custom"}, {"sort": "popular", "order": "asc"}, {"sort": "name"},
           {"customOrder": new}, None)
    for b in bad:
        assert _sort(fake, b) == 400, b
    assert (fake._vault_order["sort"], fake._vault_order["order"], fake._vault_order["custom"]) == ("name", "asc", new)
    assert [x[2] for x in fake.logged if x[1].endswith("/sort")] == [200, 200] + [400] * len(bad)



def _call(rec, method, path, body=None, tagged=False):
    raw = json.dumps(body).encode() if body is not None else b""
    sent = []

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    async def send(msg):
        sent.append(msg)

    scope = {"type": "http", "method": method, "path": path, "raw_path": path.encode(), "query_string": b"",
             "headers": [(fake_layer.TAG.encode(), b"1")] if tagged else []}
    asyncio.run(rec(scope, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    out = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, json.loads(out) if out else None


async def _app_lists(scope, receive, send):
    body = json.dumps({"sort": "custom", "order": "desc", "hasMore": False,
                       "list": vault._rows(render._tpl("vault-lists.json"))[::-1]}).encode()
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


def test_no_stored_order_drops_sort_and_order_on_tagged_reads_too():
    rec = fake_layer.Recorder(_app_lists, "no-stored-order")
    default = [r["id"] for r in vault._rows(render._tpl("vault-lists.json"))]
    for tagged in (True, False):
        status, d = _call(rec, "GET", "/api2/v2/vault/lists", tagged=tagged)
        assert status == 200 and "sort" not in d and "order" not in d and [r["id"] for r in d["list"]] == default
    assert [h.get("fault") for h in rec.hits] == ["no-stored-order"] * 2
    why = phase6.order_unrecoverable(phase6.read_folder_order(lambda path, q: d, None))
    assert why == "pre-proof order not recoverable: the read carries no known sort and order (None, None)"


async def _app_ok(scope, receive, send):
    await receive()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": b'{"success":true}'})


def test_sort_restore_500_lets_the_save_through_then_answers_500():
    rec = fake_layer.Recorder(_app_ok, "sort-restore-500")
    got = [_call(rec, "POST", "/api2/v2/vault/lists/sort", {"sort": "name", "order": "asc"})[0] for _ in range(3)]
    assert got == [200, 500, 500]
    assert [h.get("fault") for h in rec.hits] == [None, "sort-restore-500", "sort-restore-500"]



def _hit(method, path, t, status=200, tagged=False):
    return {"t": t, "method": method, "path": path, "query": "", "body": None, "tagged": tagged, "status": status}


@pytest.fixture
def bare_harness(monkeypatch):
    monkeypatch.setattr(prove, "census", lambda *a: [])
    monkeypatch.setattr(prove, "pace_problems", lambda *a: [])
    monkeypatch.setattr(prove, "_wire_folded", lambda e: {})


@pytest.mark.parametrize("statuses, steps, want", [
    ([200, 200, 200], 2, 0), ([200, 200], 2, 1), ([200, 500], 1, 1), ([200, 200, 200, 200], 2, 1),
], ids=["save then two undo calls", "an undo call missing", "a 500 (the sequence stopped there)", "an extra call"])
def test_harness_checks_a_restore_sequence_row(bare_harness, tmp_path, statuses, steps, want):
    t0 = datetime.now(timezone.utc).timestamp()
    iso = lambda s: datetime.fromtimestamp(t0 + s, timezone.utc).isoformat()  # noqa: E731
    seq = [{"method": "POST", "path": phase6.SORT_PATH, "sent": t0 + k + 1.5, "done": t0 + k + 2.5}
           for k in range(steps)]
    row = {"row": 1, "arm": 0, "proof": P.id, "opened": iso(0), "closed": iso(30), "of_id": None,
           "write": {"method": "POST", "path": phase6.SORT_PATH}, "reversals": seq}
    hits = [_hit("POST", phase6.SORT_PATH, t0 + 1 + k, s) for k, s in enumerate(statuses)]
    assert len(prove.harness_checks(tmp_path, hits, [{"proof": P.id, "closed": [row]}])) == want


def test_harness_checks_a_proof_parked_on_its_before_read(bare_harness, tmp_path):
    parked = {"proof": P.id, "reason": "pre-proof order not recoverable: x", "read_first": True}
    reads = [_hit("GET", "/api2/v2/vault/lists", 1, tagged=True), _hit("GET", "/api2/v2/vault/lists", 2)]
    assert prove.harness_checks(tmp_path, reads, [parked]) == []
    out = prove.harness_checks(tmp_path, reads + [_hit("POST", phase6.SORT_PATH, 3)], [parked])
    assert out == [f"{P.id}: parked, yet FakeOF received POST {phase6.SORT_PATH}"]


def test_fault_choices_include_the_two_planted_variants(monkeypatch):
    ran = []
    monkeypatch.setattr(prove, "prove", lambda ids, fault, fan, **k: ran.append(fault) or 0)
    monkeypatch.setattr(prove.os, "setpriority", lambda *a: None)
    for f in ("no-stored-order", "sort-restore-500"):
        assert prove.main(["--of", "fake", "--proof", P.id, "--fault", f]) == 0
    assert ran == ["no-stored-order", "sort-restore-500"]
