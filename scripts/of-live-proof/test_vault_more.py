import time

import pytest
from starlette.testclient import TestClient

import ui_steps
import undo_driver
import undo_log
from fake_layer import Recorder
from live_entry import live_refusal
from proof_core import Proof, Request, Run, Write, decide
from proofs import ALL, phase2
from soak import ids
from soak.fake_of import vault
from soak.fake_of.app import FakeOF
from soak.fake_of.signing import sign_value
from soak.world import World

LISTS = "/api2/v2/vault/lists"
RENAME, DELETE = ALL["vault.more.rename"], ALL["vault.more.delete"]


def _client(fault=None):
    fake = FakeOF(World(seed=1))
    app = fake.build()
    client = TestClient(Recorder(app, fault) if fault else app)

    def call(method, path_qs, json=None):
        t = str(int(time.time() * 1000))
        uid = str(fake.world.creator_id)
        h = {"user-id": uid, "x-hash": fake.x_hash, "time": t,
             "sign": sign_value(fake.rules, time_ms=t, path_qs=path_qs, user_id=uid)}
        return client.request(method, path_qs, headers=h, json=json)
    return call


SOAK_FOLDERS = sorted((str(ids.vault_list_id(n)), f"Soak folder {n}") for n in range(1, vault.FOLDERS + 1))


def _folders(call):
    return phase2.read_folders(lambda path, q: call("GET", f"{path}?view={q['view']}&offset={q['offset']}"
                                                            f"&limit={q['limit']}").json(), None)


def test_fake_folder_create_rename_delete_are_read_back():
    call = _client()
    before = _folders(call)
    assert before == SOAK_FOLDERS
    made = call("POST", LISTS, {"name": "oi-proof-x"})
    assert made.status_code == 200
    f = made.json()
    assert f["type"] == "custom" and f["name"] == "oi-proof-x" and f["canUpdate"] and f["canDelete"]
    assert str(f["id"]) not in {i for i, _ in SOAK_FOLDERS}
    assert _folders(call) == sorted([*before, (str(f["id"]), "oi-proof-x")])
    r = call("PATCH", f"{LISTS}/{f['id']}", {"name": "oi-proof-x renamed"})
    assert r.status_code == 200 and r.json()["name"] == "oi-proof-x renamed" and r.json()["id"] == f["id"]
    assert (str(f["id"]), "oi-proof-x renamed") in _folders(call)
    r = call("DELETE", f"{LISTS}/{f['id']}", {"clearMedia": False})
    assert r.status_code == 200 and r.json() == {"success": True}
    assert _folders(call) == before
    again = call("POST", LISTS, {"name": "second"}).json()
    assert again["id"] != f["id"]
    for method in ("PATCH", "DELETE"):
        assert call(method, f"{LISTS}/{f['id']}", {"name": "z"}).status_code == 404
        assert call(method, f"{LISTS}/{ids.vault_list_id(1)}", {"name": "z"}).status_code == 404


def test_fake_folder_single_read_answers_its_row_or_404():
    call = _client()
    f = call("POST", LISTS, {"name": "oi-proof-x"}).json()
    r = call("GET", f"{LISTS}/{f['id']}")
    assert r.status_code == 200 and r.json()["id"] == f["id"] and r.json()["name"] == "oi-proof-x"
    seeded = call("GET", f"{LISTS}/{ids.vault_list_id(1)}")
    assert seeded.status_code == 200 and seeded.json()["name"] == "Soak folder 1"
    call("DELETE", f"{LISTS}/{f['id']}", {"clearMedia": False})
    assert call("GET", f"{LISTS}/{f['id']}").status_code == 404
    assert call("GET", f"{LISTS}/1").status_code == 404


def test_lost_reply_fault_makes_the_folder_and_drops_the_reply():
    call = _client("lost-reply")
    with pytest.raises(Exception):   # noqa: B017  (the connection is dropped: no reply at all)
        call("POST", LISTS, {"name": "oi-proof-x"})
    assert [n for _, n in _folders(call)].count("oi-proof-x") == 1


def test_fake_folders_are_per_instance():
    a, b = _client(), _client()
    a("POST", LISTS, {"name": "only in a"})
    assert _folders(b) == SOAK_FOLDERS


def test_rename_ignored_fault_answers_200_and_keeps_the_name():
    call = _client("rename-ignored")
    f = call("POST", LISTS, {"name": "oi-proof-x"}).json()
    r = call("PATCH", f"{LISTS}/{f['id']}", {"name": "oi-proof-x renamed"})
    assert r.status_code == 200 and r.json() == {"id": f["id"], "type": "custom", "name": "oi-proof-x renamed"}
    assert (str(f["id"]), "oi-proof-x") in _folders(call)
    assert not phase2.renamed_folder([], _folders(call))


def test_effects_and_finder():
    seed = [("1", "Soak folder 1")]
    made = [*seed, ("9", "oi-proof-r1")]
    renamed = [*seed, ("9", "oi-proof-r1 renamed")]
    assert phase2.renamed_folder(seed, renamed)
    assert not phase2.renamed_folder(seed, made)
    assert not phase2.renamed_folder(seed, seed)
    assert not phase2.renamed_folder(seed, [*renamed, ("10", "oi-proof-r1 renamed")])
    assert phase2.folder_gone(seed, seed)
    assert not phase2.folder_gone(seed, made)
    assert phase2.find_marked_folder(seed, renamed, "oi-proof-r1") == "9"
    assert phase2.find_marked_folder(seed, seed, "oi-proof-r1") is None


def test_the_two_proofs_run_on_a_created_folder_in_fake_mode_only():
    for p in (RENAME, DELETE):
        assert (p.page, p.control, p.kind) == ("vault/list", "More", "live")
        assert p.undo[0].relay == "/admin/vault-ai/of-folders/{id}?account_id={account}"
        assert p.trigger[0][0] == "click"
        assert ("goto", "vault/list?list={id}") in p.trigger
        assert live_refusal(p, "live", None) is None
        assert live_refusal(p, "fake", None) is None
    assert [w.method for w in RENAME.arm] == ["POST", "PATCH"] and RENAME.arm[1].path.endswith("/{created}")
    assert [w.method for w in DELETE.arm] == ["POST"] and DELETE.trigger[-1] == (
        "accept", "#oi-menu [data-oi-value='delete']", 'Delete the folder "')
    assert ("frame", "vault/state-add-list") in RENAME.trigger[RENAME.trigger.index(("click", "#oi-menu [data-oi-value='rename']")):]
    assert not any("oi-vault-rename" in str(step) for step in RENAME.trigger)
    assert RENAME.settled[-1] == "vault/index"


def test_ticket_30_helpers_keep_their_own_new_post_set():
    after = [["1", "oi-proof-x", ["5"]]]
    assert phase2.vault_media([], after) == {"1": {"media": "5"}}
    assert phase2.one_new_marked_post_with_media([], after)
    assert phase2.find_marked_post([], after, "oi-proof-x") == "1"
    assert phase2.MARKER == "oi-proof-" and not hasattr(phase2, "_MARKER")


def _req(method, path):
    return Request(method, "onlyfans.com", path)


@pytest.mark.parametrize("method, path, run, verdict, cls", [
    ("PATCH", f"{LISTS}/9", Run(proof=RENAME, of="fake", spent={("arm", 0): 1}, created=frozenset({"9"})),
     "allow", "allow"),
    ("PATCH", f"{LISTS}/5", Run(proof=RENAME, of="fake", spent={("arm", 0): 1}, created=frozenset({"9"})),
     "refused", "unarmed"),
    ("PATCH", f"{LISTS}/9", Run(proof=RENAME, of="fake"), "refused", "unarmed"),
    ("DELETE", f"{LISTS}/9", Run(proof=DELETE, of="fake", spent={("arm", 0): 1}, created=frozenset({"9"})),
     "reversal", "reversal"),
    ("DELETE", f"{LISTS}/5", Run(proof=DELETE, of="fake", spent={("arm", 0): 1}, created=frozenset({"9"})),
     "refused", "unarmed"),
    ("DELETE", f"{LISTS}/9", Run(proof=DELETE, of="fake", spent={("arm", 0): 1, ("undo", 0): 1},
                                 created=frozenset({"9"})), "refused", "over_count"),
])
def test_guard_binds_the_folder_writes_to_the_created_folder(method, path, run, verdict, cls):
    v = decide(_req(method, path), run)
    assert (v.kind, v.cls) == (verdict, cls), v.reason


def test_created_binds_to_the_creating_arms_ids_in_undo_paths_too():
    w = Write("DELETE", LISTS + "/{created}", reverses=(0,))
    proof = Proof(id="t.created", phase=2, page="vault/list", control="More", kind="live",
                  arm=(Write("POST", LISTS), Write("POST", LISTS + "/other")), undo=(w,), effect=lambda b, a: True)
    run = Run(proof=proof, of="fake", spent={("arm", 0): 1, ("arm", 1): 1}, created=frozenset({"9", "8"}),
              created_by={0: frozenset({"9"}), 1: frozenset({"8"})})
    assert decide(_req("DELETE", f"{LISTS}/9"), run).kind == "reversal"
    v = decide(_req("DELETE", f"{LISTS}/8"), run)
    assert (v.kind, v.cls) == ("refused", "unarmed"), v.reason


class _Dialog:
    def __init__(self, kind, message):
        self.type, self.message, self.did = kind, message, None

    def accept(self):
        self.did = "accept"

    def dismiss(self):
        self.did = "dismiss"


class _Page:
    def __init__(self):
        self.listeners = []

    def on(self, event, f):
        assert event == "dialog"
        self.listeners.append(f)

    def remove_listener(self, event, f):
        self.listeners.remove(f)

    def wait_for_timeout(self, ms):
        pass


class _Loc:
    def __init__(self, page, dialog):
        self.page, self.dialog = page, dialog

    def click(self, timeout):
        if self.dialog:
            for f in list(self.page.listeners):
                f(self.dialog)


WANT = 'Delete the folder "'


@pytest.mark.parametrize("dialog, did, ok", [
    (_Dialog("confirm", 'Delete the folder "x"? Its media stay in the vault.'), "accept", True),
    (_Dialog("confirm", "Remove 2 media from the vault? OnlyFans has no undo."), "dismiss", False),
    (_Dialog("alert", 'Delete the folder "x"?'), "dismiss", False),
    (None, None, False),
])
def test_click_confirm_accepts_only_the_wanted_confirm(dialog, did, ok):
    page = _Page()
    if ok:
        ui_steps.click_confirm(page, _Loc(page, dialog), WANT, wait_ms=100)
    else:
        with pytest.raises(RuntimeError, match="accept: wanted a confirm"):
            ui_steps.click_confirm(page, _Loc(page, dialog), WANT, wait_ms=100)
    assert (dialog.did if dialog else None) == did
    assert page.listeners == []


def test_click_confirm_removes_its_listener_when_the_click_raises():
    page = _Page()

    class Boom(_Loc):
        def click(self, timeout):
            raise TimeoutError("not clickable")
    with pytest.raises(TimeoutError):
        ui_steps.click_confirm(page, Boom(page, None), WANT)
    assert page.listeners == []


def test_goto_target_fills_the_newest_created_id():
    assert ui_steps.goto_target("vault/list", lambda: []) == "vault/list"
    rows = [{"row": 2, "of_id": "9"}, {"row": 1, "of_id": "7"}, {"row": 3, "of_id": None}]
    assert ui_steps.goto_target("vault/list?list={id}", lambda: rows) == "vault/list?list=9"
    seen = []
    later = iter([[], [{"row": 1, "of_id": "4"}]])
    assert ui_steps.goto_target("vault/list?list={id}", lambda: next(later), sleep=seen.append) == "vault/list?list=4"
    assert seen == [0.25]
    with pytest.raises(RuntimeError, match="no OnlyFans id"):
        ui_steps.goto_target("vault/list?list={id}", lambda: [], timeout_s=0, sleep=lambda s: None)


UNDO = Write("DELETE", LISTS + "/{id}", relay="/admin/vault-ai/of-folders/{id}?account_id={account}")


def _line(seq, path=f"{LISTS}/9", verdict="reversal", status=200, method="DELETE"):
    return {"seq": seq, "method": method, "path": path, "verdict": verdict, "status": status}


@pytest.mark.parametrize("lines, want", [
    ([_line(5)], 5),
    ([_line(2)], None),
    ([_line(5, path=f"{LISTS}/8")], None),
    ([_line(5, verdict="allow")], None),
    ([_line(5, status=None)], None),
    ([_line(6), _line(5)], 5),
    ([_line(5, status=500)], 5),
])
def test_trigger_reversal(lines, want):
    got = undo_driver.trigger_reversal(UNDO, {"row": 1, "wire_seq": 3}, f"{LISTS}/9", lines)
    assert (got or {}).get("seq") == want


def test_trigger_reversal_only_for_an_id_bound_undo():
    hide = Write("PUT", "/api2/v2/vault/media/hidden", relay="/admin/vault-ai/items/{media}/hide")
    line = _line(5, path="/api2/v2/vault/media/hidden", method="PUT")
    assert undo_driver.trigger_reversal(hide, {"row": 1, "wire_seq": 3}, "/api2/v2/vault/media/hidden", [line]) is None



PPV, MSG = ALL["p2.bubble-unsend-ppv"], "/api2/v2/messages/9"


@pytest.mark.parametrize("status, shown, sends", [
    (500, [("9", "oi-proof-r", 3)], True),
    (500, [], False),
    (500, None, False),
    (200, [("9", "oi-proof-r", 3)], True),
    (200, [], False),
    (200, None, False),
])
def test_a_failed_in_page_unsend_is_no_undo_the_driver_sends_its_own_while_the_ppv_shows(status, shown, sends):
    calls, reads = [], []

    def read(tag):
        reads.append(tag)
        if shown is None:
            raise RuntimeError("read failed")
        return shown
    wire = [_line(5, path=MSG, status=status)]
    row = {"row": 1, "arm": 0, "wire_seq": 3, "of_id": "9"}
    [(revs, unsent)] = undo_driver._send_all(
        PPV, [row], lambda *a, **k: calls.append(a) or wire.append(_line(8, path=MSG)) or (200, "{}"),
        lambda: wire, lambda r: {"id": "9", "account": "c1"}, {}, "c1", None, read=read)
    assert unsent is None and reads == ["before-undo-retry"]
    if sends:
        assert calls == [("DELETE", "/api/of/v2/messages/9", None)]
        assert (revs[0]["seq"], revs[0]["status"], revs[0]["relay"]) == (8, 200, "/api/of/v2/messages/9")
    else:
        assert calls == [] and (revs[0]["seq"], revs[0]["status"], revs[0]["by"]) == (5, status, "trigger")


def _thread(ids, more, marked=()):
    page = {"list": [{"id": i, "text": "oi-proof-r" if i in marked else "hi", "price": 3 if i in marked else 0}
                     for i in ids], "hasMore": more}
    return lambda path, params: page


_BEFORE = (range(20, 10, -1), True)


@pytest.mark.parametrize("after, gone", [
    ((range(20, 10, -1), True), True),
    ((range(23, 13, -1), True), True),
    ((range(35, 25, -1), True), False),
    ((range(35, 25, -1), False), True),
    ((range(21, 11, -1), True, (21,)), False),
    (([], True), False),
])
def test_the_ppv_counts_as_gone_only_on_a_page_that_reaches_back_past_the_send(after, gone):
    before = PPV.of_read(_thread(*_BEFORE), "555")
    read = PPV.of_read(_thread(*after), "555")
    assert bool(PPV.effect(before, read)) is gone
    assert bool((PPV.same or undo_log.reads_equal)(before, read)) is gone
    closed = {"row": 1, "effect": True, "reversals": [], "reads": {"before": before, "after_undo": read}}
    differs = any("after-undo read differs" in p for p in undo_log.verify_undo([], [closed], PPV.same))
    assert differs is not gone


@pytest.mark.parametrize("after, gone", [
    ((range(35, 25, -1), True), False),
    ((range(35, 25, -1), False), True),
])
def test_an_empty_chat_before_the_send_proves_nothing_about_a_page_that_says_more(after, gone):
    before = PPV.of_read(_thread([], False), "555")
    read = PPV.of_read(_thread(*after), "555")
    assert bool(PPV.effect(before, read)) is gone
    assert bool((PPV.same or undo_log.reads_equal)(before, read)) is gone


def test_the_ppv_read_page_bounds_are_never_taken_for_a_shown_message():
    got = PPV.of_read(_thread(range(20, 10, -1), True, (14,)), "555")
    assert got == {"marked": [("14", "oi-proof-r", 3)], "_page": {"newest": 20, "oldest": 11, "more": True}}
    assert not undo_driver.still_shown(lambda tag: got, "20") and not undo_driver.still_shown(lambda tag: got, "11")
    assert undo_driver.still_shown(lambda tag: got, "14")
    assert PPV.of_read(_thread([], False), "555")["_page"] == {"newest": None, "oldest": None, "more": False}


def test_a_failed_in_page_reversal_with_no_budget_left_sends_nothing():
    calls, reads = [], []
    [(revs, _)] = undo_driver._send_all(DELETE, [{"row": 1, "arm": 0, "wire_seq": 3, "of_id": "9"}],
                                        lambda *a, **k: calls.append(a) or (200, "{}"), lambda: [_line(5, status=500)],
                                        lambda r: {"id": "9", "account": "c1"}, {}, "c1", None,
                                        read=lambda tag: reads.append(tag) or [["9"]])
    assert calls == reads == [] and revs[0]["status"] == 500


@pytest.mark.parametrize("spent, kind", [(1, "reversal"), (2, "refused")])
def test_the_guard_leaves_the_ppv_undo_room_for_the_drivers_own_delete(spent, kind):
    run = Run(proof=PPV, proof_fan="555", created=frozenset({"9"}), spent={("arm", 0): 1, ("undo", 0): spent})
    v = decide(Request(method="DELETE", host="onlyfans.com", path=MSG, body=None, at=None), run)
    assert v.kind == kind and (kind == "reversal" or v.cls == "over_count"), v


def test_send_takes_the_trigger_reversal_and_sends_nothing():
    calls = []
    row = {"row": 1, "arm": 0, "wire_seq": 3, "of_id": "9"}
    values = lambda r: {"id": "9", "account": "c1"}  # noqa: E731
    [(revs, unsent)] = undo_driver._send_all(DELETE, [row], lambda *a, **k: calls.append(a) or (200, "{}"),
                                             lambda: [_line(5)], values, {}, "c1", None)
    assert calls == [] and unsent is None
    assert revs == [{"method": "DELETE", "path": f"{LISTS}/9", "status": 200, "seq": 5, "relay": None,
                     "relay_status": None, "by": "trigger"}]
    wire = [[], [_line(7)]]
    [(revs, _)] = undo_driver._send_all(RENAME, [row], lambda *a, **k: calls.append(a) or (200, "{}"),
                                        lambda: wire[0] if not calls else wire[1], values, {}, "c1", None)
    assert calls == [("DELETE", "/admin/vault-ai/of-folders/9?account_id=c1", None)]
    assert revs[0]["seq"] == 7 and revs[0]["relay"] == "/admin/vault-ai/of-folders/9?account_id=c1"
