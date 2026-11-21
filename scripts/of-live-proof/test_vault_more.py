"""ofm-not-yet ticket 34: the vault folder page's More proofs (proofs/phase2.py vault.more.rename, vault.more.delete),
FakeOF's vault folder writes (soak/fake_of/vault.py), the planted `rename-ignored` fault (fake_layer.py), and the
driver pieces they need: an arm's `{created}` (proof_core `_match`), a goto to the created folder's page
(ui_steps.py `goto_target`) and the trigger's own reversal taken as the undo record (undo_driver `trigger_reversal`).
"""
import time

import pytest
from starlette.testclient import TestClient

import ui_steps
import undo_driver
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


# FakeOF's seeded folders (soak/fake_of/vault.py FOLDERS, ticket 96's folder sort), as read_folders gives them
SOAK_FOLDERS = sorted((str(ids.vault_list_id(n)), f"Soak folder {n}") for n in range(1, vault.FOLDERS + 1))


def _folders(call):
    """The custom folders as (id, name), through the proof's own read."""
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
    assert str(f["id"]) not in {i for i, _ in SOAK_FOLDERS}   # never a seeded folder's id (ticket 96 seeds 3)
    assert _folders(call) == sorted([*before, (str(f["id"]), "oi-proof-x")])
    r = call("PATCH", f"{LISTS}/{f['id']}", {"name": "oi-proof-x renamed"})
    assert r.status_code == 200 and r.json()["name"] == "oi-proof-x renamed" and r.json()["id"] == f["id"]
    assert (str(f["id"]), "oi-proof-x renamed") in _folders(call)
    r = call("DELETE", f"{LISTS}/{f['id']}", {"clearMedia": False})
    assert r.status_code == 200 and r.json() == {"success": True}
    assert _folders(call) == before
    # ids never reused (as OF's); a folder this fake did not create (the seeded one, a gone one) is 404
    again = call("POST", LISTS, {"name": "second"}).json()
    assert again["id"] != f["id"]
    for method in ("PATCH", "DELETE"):
        assert call(method, f"{LISTS}/{f['id']}", {"name": "z"}).status_code == 404
        assert call(method, f"{LISTS}/{ids.vault_list_id(1)}", {"name": "z"}).status_code == 404


def test_fake_folder_single_read_answers_its_row_or_404():
    """GET /vault/lists/{id} (the Relay's found-id read-back, relay_live READ_BACK; answer shape inferred): a created
    or seeded folder's listing row, a gone or unknown id 404."""
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
    assert (str(f["id"]), "oi-proof-x") in _folders(call)   # not applied
    assert not phase2.renamed_folder([], _folders(call))       # not renamed: the proof fails (at settle)


def test_effects_and_finder():
    seed = [("1", "Soak folder 1")]
    made = [*seed, ("9", "oi-proof-r1")]
    renamed = [*seed, ("9", "oi-proof-r1 renamed")]
    assert phase2.renamed_folder(seed, renamed)
    assert not phase2.renamed_folder(seed, made)            # created, never renamed
    assert not phase2.renamed_folder(seed, seed)            # nothing made
    assert not phase2.renamed_folder(seed, [*renamed, ("10", "oi-proof-r1 renamed")])   # two
    assert phase2.folder_gone(seed, seed)
    assert not phase2.folder_gone(seed, made)               # a delete that did nothing
    assert phase2.find_marked_folder(seed, renamed, "oi-proof-r1") == "9"
    assert phase2.find_marked_folder(seed, seed, "oi-proof-r1") is None


def test_the_two_proofs_run_on_a_created_folder_in_fake_mode_only():
    for p in (RENAME, DELETE):
        assert (p.page, p.control, p.kind) == ("vault/list", "More", "live")
        assert p.undo[0].relay == "/admin/vault-ai/of-folders/{id}?account_id={account}"
        assert p.trigger[0][0] == "click"   # the opening page's own control, waited for visible first
        assert ("goto", "vault/list?list={id}") in p.trigger
        # startable live once the live OF-side reader is built (ticket 11), runnable in fake mode
        assert live_refusal(p, "live", None) is None
        assert live_refusal(p, "fake", None) is None
    assert [w.method for w in RENAME.arm] == ["POST", "PATCH"] and RENAME.arm[1].path.endswith("/{created}")
    assert [w.method for w in DELETE.arm] == ["POST"] and DELETE.trigger[-1] == (
        "accept", "#oi-menu [data-oi-value='delete']", 'Delete the folder "')
    # Rename is the action row's: the folder's Rename category modal (state-add-list?edit=1), no dialog of its own
    assert ("frame", "vault/state-add-list") in RENAME.trigger[RENAME.trigger.index(("click", "#oi-menu [data-oi-value='rename']")):]
    assert not any("oi-vault-rename" in str(step) for step in RENAME.trigger)
    assert RENAME.settled[-1] == "vault/index"


def test_ticket_30_helpers_keep_their_own_new_post_set():
    """phase2's folder diff is `_new_folders`; ticket 30's helpers still diff posts by (id, text, media) off JSON lists."""
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
    # never a folder the proof did not create
    ("PATCH", f"{LISTS}/5", Run(proof=RENAME, of="fake", spent={("arm", 0): 1}, created=frozenset({"9"})),
     "refused", "unarmed"),
    ("PATCH", f"{LISTS}/9", Run(proof=RENAME, of="fake"), "refused", "unarmed"),
    # the delete proof's UI Delete is the create's declared undo (class 8), on the created id only
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
    v = decide(_req("DELETE", f"{LISTS}/8"), run)   # created, but by an arm this undo does not reverse
    assert (v.kind, v.cls) == ("refused", "unarmed"), v.reason


class _Dialog:
    def __init__(self, kind, message):
        self.type, self.message, self.did = kind, message, None

    def accept(self):
        self.did = "accept"

    def dismiss(self):
        self.did = "dismiss"


class _Page:
    """Playwright's page as click_confirm uses it: dialog listeners, on/remove_listener, a wait."""
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
    (_Dialog("confirm", "Remove 2 media from the vault? OnlyFans has no undo."), "dismiss", False),   # another confirm
    (_Dialog("alert", 'Delete the folder "x"?'), "dismiss", False),                                   # not a confirm
    (None, None, False),                                                                              # no dialog
])
def test_click_confirm_accepts_only_the_wanted_confirm(dialog, did, ok):
    page = _Page()
    if ok:
        ui_steps.click_confirm(page, _Loc(page, dialog), WANT, wait_ms=100)
    else:
        with pytest.raises(RuntimeError, match="accept: wanted a confirm"):
            ui_steps.click_confirm(page, _Loc(page, dialog), WANT, wait_ms=100)
    assert (dialog.did if dialog else None) == did
    assert page.listeners == []   # removed even when the step fails


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
    ([_line(2)], None),                                  # before the row's write (an earlier proof's)
    ([_line(5, path=f"{LISTS}/8")], None),               # another folder
    ([_line(5, verdict="allow")], None),
    ([_line(5, status=None)], None),                     # still in flight
    ([_line(6), _line(5)], 5),
    ([_line(5, status=500)], 5),                         # verify_undo names the status
])
def test_trigger_reversal(lines, want):
    got = undo_driver.trigger_reversal(UNDO, {"row": 1, "wire_seq": 3}, f"{LISTS}/9", lines)
    assert (got or {}).get("seq") == want


def test_trigger_reversal_only_for_an_id_bound_undo():
    hide = Write("PUT", "/api2/v2/vault/media/hidden", relay="/admin/vault-ai/items/{media}/hide")
    line = _line(5, path="/api2/v2/vault/media/hidden", method="PUT")
    assert undo_driver.trigger_reversal(hide, {"row": 1, "wire_seq": 3}, "/api2/v2/vault/media/hidden", [line]) is None


def test_send_takes_the_trigger_reversal_and_sends_nothing():
    calls = []
    row = {"row": 1, "arm": 0, "wire_seq": 3, "of_id": "9"}
    values = lambda r: {"id": "9", "account": "c1"}  # noqa: E731
    [(revs, unsent)] = undo_driver._send_all(DELETE, [row], lambda *a, **k: calls.append(a) or (200, "{}"),
                                             lambda: [_line(5)], values, {}, "c1", None)
    assert calls == [] and unsent is None
    assert revs == [{"method": "DELETE", "path": f"{LISTS}/9", "status": 200, "seq": 5, "relay": None,
                     "relay_status": None, "by": "trigger"}]
    # no trigger reversal on the wire: the undo goes through the Relay's own route
    wire = [[], [_line(7)]]
    [(revs, _)] = undo_driver._send_all(RENAME, [row], lambda *a, **k: calls.append(a) or (200, "{}"),
                                        lambda: wire[0] if not calls else wire[1], values, {}, "c1", None)
    assert calls == [("DELETE", "/admin/vault-ai/of-folders/9?account_id=c1", None)]
    assert revs[0]["seq"] == 7 and revs[0]["relay"] == "/admin/vault-ai/of-folders/9?account_id=c1"
