import json
import subprocess
import sys
from pathlib import Path

import pytest

import proof_list
from proof_core import Proof

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
PHASE3 = HERE / "proofs" / "phase3.py"
SWEEP_2026_11_20 = ROOT / "docs" / "of-manager" / "not-yet-sweep-2026-11-20.json"
LIVE_OVERLAY = ROOT / "docs" / "of-manager" / "not-yet-sweep-2026-11-21-live.json"
CAPTURES = ROOT / "docs" / "of-manager" / "captures"

IP = Proof(id="p3.block-by-ip", phase=3, page="settings/security/block_by_ip", control="[TEXTAREA]", kind="live",
           tags=frozenset({"lockout"}))
RESET = Proof(id="p3.reset-stream-key", phase=3, page="settings/streaming", control="Reset", kind="mocked",
              tags=frozenset({"irreversible"}))
PROOFS = (IP, RESET)
PASS = dict(verdict="pass", reason="")
PARKED = dict(verdict="parked", reason="Mocked proof only until the owner's go (D3)")


def record(proof, **verdict):
    return {"id": f"settings--{proof.id[3:]}", "label": proof.control, "pages": [proof.page], "phase": 3,
            "source": "of-js", "proof": {"kind": proof.kind, **verdict}}


def write(folder, *recs):
    folder.mkdir(exist_ok=True)
    for r in recs:
        (folder / f"{r['id']}.json").write_text(json.dumps(r))
    return folder


def sweep(tmp_path, ny):
    f = tmp_path / "sweep.json"
    f.write_text(json.dumps([[page, {"ny": labels, "dis": [], "ro": []}] for page, labels in ny.items()]))
    return f


def run(argv, capsys):
    code = proof_list.main(PROOFS, argv, prog="phase3.py")
    return code, capsys.readouterr().out


def test_record_check_on_phase3_proofs(tmp_path, capsys):
    assert run(["--check-records", str(write(tmp_path / "c", record(IP, **PASS), record(RESET, **PARKED)))], capsys) == \
        (0, "check-records: 2 proofs, 0 problems\n")
    code, out = run(["--check-records", str(write(tmp_path / "d", record(IP, **PASS), record(RESET, verdict="parked")))], capsys)
    assert code == 1 and out.startswith("p3.reset-stream-key: ") and "p3.block-by-ip" not in out, out


@pytest.mark.parametrize("ny, who", [
    ({"settings/security/block_by_ip": [], "settings/streaming": ["Copy key", "Reset"]}, None),
    ({"settings/security/block_by_ip": ["[TEXTAREA]"], "settings/streaming": ["Reset"]}, "p3.block-by-ip"),
    ({"settings/security/block_by_ip": [], "settings/streaming": []}, "p3.reset-stream-key"),
])
def test_sweep_check_on_phase3_proofs(tmp_path, capsys, ny, who):
    d = write(tmp_path / "c", record(IP, **PASS), record(RESET, **PARKED))
    code, out = run(["--check-sweep", str(sweep(tmp_path, ny)), str(d)], capsys)
    assert (code, out.startswith(f"{who}: ")) == (1, True) if who else code == 0, out


def _cli(*args, cwd):
    return subprocess.run([sys.executable, "-I", str(PHASE3), *args], capture_output=True, text=True, cwd=cwd)


def test_the_shipped_command_runs_isolated_on_todays_tree(tmp_path):
    from proofs import phase3
    out = _cli("--ids", cwd=tmp_path)
    assert out.returncode == 0 and out.stdout == ",".join(p.id for p in phase3.PROOFS) + "\n", out
    out = _cli("--check-records", str(CAPTURES), cwd=tmp_path)
    assert out.returncode == 0, out.stdout + out.stderr
    out = _cli("--check-sweep", str(SWEEP_2026_11_20), str(CAPTURES), "--overlay", str(LIVE_OVERLAY), cwd=tmp_path)
    assert out.returncode == 0, out.stdout + out.stderr


def test_the_overlay_replaces_only_its_own_pages_and_the_bare_dated_file_still_fails(tmp_path):
    out = _cli("--check-sweep", str(SWEEP_2026_11_20), str(CAPTURES), cwd=tmp_path)
    assert out.returncode == 1 and "still has the Not-yet title" in out.stdout, out.stdout
    base, ov = json.loads(SWEEP_2026_11_20.read_text()), dict(json.loads(LIVE_OVERLAY.read_text()))
    assert set(ov) <= {p for p, _ in base}
    merged = proof_list.overlaid(base, json.loads(LIVE_OVERLAY.read_text()))
    assert [p for p, _ in merged] == [p for p, _ in base]
    assert [f for p, f in merged if p not in ov] == [f for p, f in base if p not in ov]


def test_phase3_proofs_are_known_to_the_driver():
    from proofs import ALL, phase3
    assert all(ALL[p.id] is p and p.phase == 3 for p in phase3.PROOFS)


def test_wired_trial_create_proof_is_known_and_recorded():
    from proofs import ALL, phase3
    assert [p.id for p in phase3.WIRED_PROOFS] == ["settings--trial-create-link"]
    assert all(ALL[p.id] is p and p not in phase3.PROOFS for p in phase3.WIRED_PROOFS)
    assert proof_list.check_records(phase3.WIRED_PROOFS, CAPTURES) == []


@pytest.mark.parametrize("after, effect, found", [
    ([("9", "oi-proof-M", 1, 1)], True, "9"),
    ([("9", "oi-proof-M", 1, 7)], False, "9"),
    ([("9", "someone else", 1, 1)], False, None),
    ([("9", "oi-proof-M", 1, 1), ("10", "oi-proof-M", 1, 1)], False, None),
])
def test_trial_effect_and_finder(after, effect, found):
    from proofs import phase3
    before = [("1", "old link", 7, 7)]
    assert phase3.one_new_marked_trial(before, before + after) is effect
    assert phase3.find_marked_trial(before, before + after, "oi-proof-M") == found


def _liked(i, url):
    return {"id": i, "sort": 0, "url": url, "title": " - YouTube", "description": "a page's meta description",
            "image": {"src": "", "thumbs": {"c50": "", "c144": ""}, "width": 0, "height": 0}}


def test_liked_link_without_link_key_is_read_and_found_by_its_url():
    from proofs import phase3
    marker = "oi-proof-M"
    old = _liked(1, "https://www.imdb.com/title/tt1/")
    new = _liked(9, phase3._LIKED_URL + marker)
    assert "link" not in new
    before = phase3.read_liked(lambda path, q: [old], None)
    after = phase3.read_liked(lambda path, q: [old, new], None)
    assert after == [("1", old["url"]), ("9", new["url"])]
    assert phase3.one_new_marked_link(before, after) is True
    assert phase3.find_marked_link(before, after, marker) == "9"
    assert phase3.find_marked_link(before, after, "oi-proof-other") is None


_OLD = {"header": "https://public.onlyfans.com/files/e/ef/old/header.jpg", "headerSize": {"width": 1280, "height": 720}}
_NEW = "https://public.onlyfans.com/files/a/ab/new/header.jpg"
_BACK = "https://public.onlyfans.com/files/b/bc/back/header.jpg"


def _png(w, h, tail=b""):
    import struct
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h) + b"\x08\x02\0\0\0" + tail


_KEPT = _png(1280, 720, b"owner")


_ITEM = (200, json.dumps({"processId": "p9", "host": "convert.onlyfans.com"}).encode())


def _cover_call(pictures, calls, upload=_ITEM):
    from urllib.parse import unquote

    def call(method, route, data=None, account=None, form=None):
        calls.append((method, route, data, account, form))
        if route.startswith("/img?u="):
            got = pictures.get(unquote(route[len("/img?u="):]))
            return (200, got) if got is not None else (404, b"")
        if route == "/api/of/v2/users/me/profile-image":
            return upload
        return 200, b"{}"
    return call


@pytest.mark.parametrize("after_undo, back", [
    ({"header": None, "headerSize": {"width": 1280, "height": 720}}, False),
    ({"header": "", "headerSize": None}, False),
    (None, False),
    ({"header": _NEW, "headerSize": {"width": 1, "height": 1}}, True),
])
def test_cover_undo_holds_only_with_a_cover_back(after_undo, back):
    from proofs import phase3
    from undo_log import verify_undo
    assert phase3.cover_back(_OLD, after_undo) is back
    row = {"row": 1, "effect": True, "reversals": [{"method": "PATCH", "path": "/api2/v2/users/me", "seq": 5}],
           "reads": {"before": _OLD, "after_undo": after_undo}}
    wire = [{"seq": 5, "verdict": "reversal", "method": "PATCH", "path": "/api2/v2/users/me", "status": 200}]
    assert (verify_undo(wire, [row], phase3.COVER.same) == []) is back


def _wire_after_patch(wire, calls):
    return lambda: wire if any(c[0] == "PATCH" for c in calls) else []


def _cover_undo(tmp_path, pictures, after_undo, *, arm=3, after=None, upload=None, reads=None, clock=None):
    import undo_driver
    from proofs import phase3
    calls = []
    call = _cover_call(pictures, calls, *([upload] if upload else []))
    kept = undo_driver.keep(phase3.COVER, _OLD, call, "c1", tmp_path)
    calls.clear()
    wire = [{"seq": 7, "verdict": "reversal", "method": "PATCH", "path": "/api2/v2/users/me", "status": 200}]
    res = {"problems": [], "screens": []}
    row = {"row": 1, "arm": arm, "of_id": None, "write": {"method": "PATCH", "path": "/api2/v2/users/me"}}
    seq, now = list(reads or [after_undo]), clock if clock is not None else [0.0]

    def read(tag):
        return seq.pop(0) if len(seq) > 1 else seq[0]

    def sleep(s):
        now[0] += s
    closed, = undo_driver.settle_rows(phase3.COVER, [row], call, _wire_after_patch(wire, calls), read, creator="c1",
                                      before=_OLD, after=after or {**_OLD, "header": _NEW}, effect=True, keys={},
                                      sent={}, res=res, kept=kept, folder=tmp_path, clock=lambda: now[0], sleep=sleep)
    return closed, calls, res


def test_cover_undo_does_not_pass_the_kept_bytes_themselves_after_a_re_upload(tmp_path):
    import undo_driver
    clock = [0.0]
    closed, _, res = _cover_undo(tmp_path, {_OLD["header"]: _KEPT, _BACK: _KEPT}, {**_OLD, "header": _BACK},
                                 clock=clock)
    assert closed["state"] == "FAILED" and closed["reads"]["equal"] is False
    assert any("byte-identical" in p for p in res["problems"]), res["problems"]
    assert clock[0] >= undo_driver.RESTORE_WAIT


def _pic(kind="gradient", size=(64, 36), fmt="JPEG", quality=95):
    import io
    from PIL import Image
    if kind == "gradient":
        im = Image.linear_gradient("L").resize(size).convert("RGB")
    else:
        im = Image.new("RGB", size, (128, 128, 128))
    out = io.BytesIO()
    im.save(out, fmt, **({"quality": quality} if fmt == "JPEG" else {}))
    return out.getvalue()


def _reencode(data, quality=70):
    import io
    from PIL import Image
    out = io.BytesIO()
    Image.open(io.BytesIO(data)).convert("RGB").save(out, "JPEG", quality=quality)
    return out.getvalue()


_ORIG = _pic()
_GREY = _pic("grey")


@pytest.mark.parametrize("got, ok, why", [
    (_ORIG, True, None),
    (_reencode(_ORIG), True, None),
    (_pic(fmt="PNG"), True, None),
    (_GREY, False, "mean abs pixel diff"),
    (_pic(size=(32, 18)), False, "size 32x18, kept 64x36"),
    (b"\xff\xd8\xff not a picture", False, "does not decode"),
])
def test_picture_match_is_same_size_and_close_pixels(got, ok, why):
    import undo_driver
    m = undo_driver.picture_match(_ORIG, got)
    assert m["ok"] is ok and (m["why"] is None if why is None else why in m["why"]), m
    assert m["kept"]["sha256"] and m["restored"]["sha256"]
    if ok and got != _ORIG:
        assert m["mean_abs_diff"] < undo_driver.RESTORE_MAX_DIFF


def test_picture_match_passes_identical_bytes_without_decoding_unless_reuploaded():
    import undo_driver
    m = undo_driver.picture_match(b"x", b"x")
    assert m["ok"] is True and m["why"] is None and m["mean_abs_diff"] == 0.0
    m = undo_driver.picture_match(_ORIG, _ORIG, reuploaded=True)
    assert m["ok"] is False and "byte-identical" in m["why"]
    assert undo_driver.picture_match(_ORIG, _reencode(_ORIG), reuploaded=True)["ok"] is True


def test_picture_match_threshold_sits_between_noise_and_another_picture():
    import undo_driver
    assert 5 < undo_driver.RESTORE_MAX_DIFF < 60
    assert undo_driver.picture_match(_ORIG, _GREY)["mean_abs_diff"] > undo_driver.RESTORE_MAX_DIFF


def _old_kept(pictures):
    return {_OLD["header"]: _ORIG, **pictures}


def test_cover_undo_waits_out_a_stale_cover_then_passes_a_re_encoded_restore(tmp_path):
    import hashlib
    stale = {**_OLD, "header": _NEW}
    back = _reencode(_ORIG)
    clock = [0.0]
    closed, _, res = _cover_undo(tmp_path, _old_kept({_NEW: _GREY, _BACK: back}), None,
                                 reads=[stale, stale, {**_OLD, "header": _BACK}], clock=clock)
    assert closed["state"] == "undone" and res["problems"] == [] and closed["reads"]["equal"] is True, res
    pic = closed["reads"]["pictures"]["3"]
    assert pic["kept"]["sha256"] == hashlib.sha256(_ORIG).hexdigest()
    assert pic["restored"]["sha256"] == hashlib.sha256(back).hexdigest() != pic["kept"]["sha256"]
    assert pic["mean_abs_diff"] < 12 and pic["polls"] == 3 and 0 < clock[0] < 60
    assert closed["reads"]["after_undo"]["header"] == _BACK
    assert (tmp_path / "undo-3-after.jpg").read_bytes() == back
    assert "settings--profile-cover-avatar/undo-3-after.jpg" in closed["evidence"]


def test_cover_undo_fails_a_restore_that_serves_another_picture(tmp_path):
    import undo_driver
    from urllib.parse import quote
    clock = [0.0]
    closed, calls, res = _cover_undo(tmp_path, _old_kept({_NEW: _pic(size=(64, 36), quality=50), _BACK: _GREY}),
                                     None, reads=[{**_OLD, "header": _BACK}], clock=clock)
    assert closed["state"] == "FAILED" and closed["reads"]["equal"] is False
    assert any("not the kept one" in p for p in res["problems"]), res["problems"]
    assert clock[0] >= undo_driver.RESTORE_WAIT and [c[1] for c in calls].count("/img?u=" + quote(_BACK, safe="")) == 1


def test_cover_undo_fails_when_the_cover_never_leaves_the_after_write_picture(tmp_path):
    import undo_driver
    clock = [0.0]
    closed, calls, res = _cover_undo(tmp_path, _old_kept({_NEW: _GREY}), {**_OLD, "header": _NEW}, clock=clock)
    assert closed["state"] == "FAILED"
    assert any("no after-undo read named a cover" in p for p in res["problems"]), res["problems"]
    assert undo_driver.RESTORE_WAIT <= clock[0] < undo_driver.RESTORE_WAIT + undo_driver.RESTORE_STEP + 1
    assert not [c for c in calls if c[1].startswith("/img")]


def test_a_later_cover_row_passes_on_the_restore_already_served(tmp_path):
    import undo_driver
    from proofs import phase3
    calls = []
    call = _cover_call(_old_kept({_NEW: _GREY, _BACK: _reencode(_ORIG)}), calls)
    kept = undo_driver.keep(phase3.COVER, _OLD, call, "c1", tmp_path)
    wire = [{"seq": 7, "verdict": "reversal", "method": "PATCH", "path": "/api2/v2/users/me", "status": 200}]
    res, sent, now = {"problems": [], "screens": []}, {}, [0.0]
    for n, arm in ((1, 3), (2, 0)):
        row = {"row": n, "arm": arm, "of_id": None, "write": {"method": "PATCH", "path": "/api2/v2/users/me"}}
        undo_driver.settle_rows(phase3.COVER, [row], call, _wire_after_patch(wire, calls),
                                lambda tag: {**_OLD, "header": _BACK}, creator="c1", before=_OLD,
                                after={**_OLD, "header": _NEW}, effect=True, keys={}, sent=sent, res=res, kept=kept,
                                folder=tmp_path, clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s))
    assert res["problems"] == [] and [c["state"] for c in res["closed"]] == ["undone", "undone"]
    from urllib.parse import quote
    assert not [c for c in calls if c[1] == "/img?u=" + quote(_NEW, safe="")] and now[0] == 0
    assert [c[0] for c in calls].count("PATCH") == 1


@pytest.mark.parametrize("restored", [
    _png(1, 1),
    _png(1280, 720, b"re-encoded"),
])
def test_cover_undo_fails_a_restore_that_is_not_the_kept_picture(tmp_path, restored):
    closed, _, res = _cover_undo(tmp_path, {_OLD["header"]: _KEPT, _BACK: restored}, {**_OLD, "header": _BACK})
    assert closed["state"] == "FAILED" and closed["reads"]["equal"] is False
    assert any("not the kept one" in p for p in res["problems"]), res["problems"]


def test_cover_undo_fails_when_the_restored_picture_does_not_read_back(tmp_path):
    closed, _, res = _cover_undo(tmp_path, {_OLD["header"]: _KEPT}, {**_OLD, "header": _BACK})
    assert closed["state"] == "FAILED" and any("did not read back" in p for p in res["problems"])


def _evidence(tmp_path, data=_ORIG, name="undo-3-before.jpg"):
    d = tmp_path / "ev" / "settings--profile-cover-avatar"
    d.mkdir(parents=True)
    (d / name).write_bytes(data)
    return tmp_path / "ev"


@pytest.mark.parametrize("served, ok", [
    (_ORIG, True), (_reencode(_ORIG), True), (_GREY, False), (_pic(size=(32, 18)), False),
])
def test_reverify_compares_the_served_cover_with_the_kept_one_and_writes_nothing(tmp_path, served, ok):
    import undo_driver
    from proofs import phase3
    calls = []
    call = _cover_call({_BACK: served}, calls)
    got = undo_driver.reverify(phase3.COVER, _evidence(tmp_path), lambda: {**_OLD, "header": _BACK}, call, "c1")
    assert got["ok"] is ok, got
    assert got["kept_file"] == "settings--profile-cover-avatar/undo-3-before.jpg"
    assert got["kept"]["sha256"] and got["restored"]["sha256"]
    assert [c[0] for c in calls] == ["GET"] and all(c[2] is None and c[4] is None for c in calls)


@pytest.mark.parametrize("read, why", [
    ({"header": None, "headerSize": None}, "shows no cover"),
    ({**_OLD, "header": _NEW}, "answered 404"),
])
def test_reverify_fails_without_a_served_picture(tmp_path, read, why):
    import undo_driver
    from proofs import phase3
    got = undo_driver.reverify(phase3.COVER, _evidence(tmp_path), lambda: read, _cover_call({_BACK: _ORIG}, []), "c1")
    assert got["ok"] is False and why in got["why"], got


def test_picture_size_decodes_png_jpeg_and_gif():
    import struct
    import undo_driver
    jpeg = (b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 4) + b"JF"
            + b"\xff\xc0" + struct.pack(">HBHH", 17, 8, 720, 1280) + b"\0" * 12)
    assert undo_driver.picture_size(_png(640, 480)) == (640, 480)
    assert undo_driver.picture_size(jpeg) == (1280, 720)
    assert undo_driver.picture_size(b"GIF89a" + struct.pack("<HH", 3, 2)) == (3, 2)
    assert undo_driver.picture_size(b"<html>") is None


def test_cover_effect_needs_a_prior_cover_that_changed():
    from proofs import phase3
    assert phase3.cover_set(_OLD, {**_OLD, "header": _NEW}) is True
    assert phase3.cover_set(_OLD, _OLD) is False
    assert phase3.cover_set({"header": None, "headerSize": None}, {**_OLD, "header": _NEW}) is False


def test_cover_undo_uploads_the_kept_picture_and_patches_its_item(tmp_path):
    import undo_driver
    from proofs import phase3
    calls = []
    call = _cover_call({_OLD["header"]: _KEPT}, calls)
    kept = undo_driver.keep(phase3.COVER, _OLD, call, "c1", tmp_path)
    i = len(phase3.COVER.undo) - 1
    assert kept == {i: (f"undo-{i}-before.png", _KEPT, "image/png")} and (tmp_path / kept[i][0]).read_bytes() == _KEPT
    assert calls[0][:2] == ("GET", "/img?u=https%3A%2F%2Fpublic.onlyfans.com%2Ffiles%2Fe%2Fef%2Fold%2Fheader.jpg")
    calls.clear()
    wire = [[], [{"seq": 7, "method": "PATCH", "path": "/api2/v2/users/me", "status": 200}]]
    (revs, unsent), = undo_driver._send_all(phase3.COVER, [{"row": 1, "arm": 3}], call,
                                            lambda: wire[1] if calls else wire[0], lambda r: {"account": "c1"}, {},
                                            "c1", _OLD, kept)
    (m1, r1, d1, a1, form), (m2, r2, body, a2, _) = calls
    assert (m1, r1, d1, a1) == ("POST", "/api/of/v2/users/me/profile-image", None, "c1")
    assert form[0].startswith("multipart/form-data; boundary=") and _KEPT in form[1] and b'name="kind"' in form[1]
    assert (m2, r2, body, a2) == ("PATCH", "/api/of/v2/users/me", {"header": {"processId": "p9",
                                                                             "host": "convert.onlyfans.com"}}, "c1")
    assert unsent is None and revs[0]["seq"] == 7 and revs[0]["at"] > 0


@pytest.mark.parametrize("upload", [
    (502, b"{}"),
    (200, b"null"), (200, b'""'), (200, b"{}"),
    (200, b'{"processId": ""}'), (200, b'{"processId": null}'), (200, b"[]"), (200, b"<html>"),
])
def test_cover_undo_refused_upload_sends_no_patch(tmp_path, upload):
    import undo_driver
    from proofs import phase3
    calls = []
    call = _cover_call({}, calls, upload)
    i = len(phase3.COVER.undo) - 1
    (revs, _), = undo_driver._send_all(phase3.COVER, [{"row": 1, "arm": 3}], call, lambda: [],
                                       lambda r: {"account": "c1"}, {}, "c1", _OLD, {i: ("x.png", _KEPT, "image/png")})
    assert [c[1] for c in calls] == ["/api/of/v2/users/me/profile-image"]
    assert revs[0]["seq"] is None and revs[0]["relay_status"] == upload[0] and revs[0]["refused"]


_LATE = {
    "stale prior cover, then the re-encoded restore": ([_OLD, _OLD, {**_OLD, "header": _BACK}], "undone", 3),
    "stale prior cover until the deadline": ([_OLD], "FAILED", None),
    "the late test cover, then the restore": ([_OLD, {**_OLD, "header": _NEW}, {**_OLD, "header": _BACK}], "undone", 3),
}


@pytest.mark.parametrize("arm", [0, 1, 2, 3])
@pytest.mark.parametrize("case", list(_LATE))
def test_cover_undo_re_uploads_and_waits_when_the_after_write_read_shows_the_prior_cover(tmp_path, arm, case):
    import undo_driver
    from urllib.parse import unquote
    reads, state, polls = _LATE[case]
    clock = [0.0]
    closed, calls, res = _cover_undo(tmp_path, _old_kept({_NEW: _GREY, _BACK: _reencode(_ORIG)}), None, arm=arm,
                                     after=_OLD, reads=reads, clock=clock)
    assert [c[:2] for c in calls[:2]] == [("POST", "/api/of/v2/users/me/profile-image"),
                                          ("PATCH", "/api/of/v2/users/me")]
    fetched = [unquote(c[1][len("/img?u="):]) for c in calls[2:]]
    assert all(c[0] == "GET" for c in calls[2:]) and len(fetched) == len(set(fetched)) and _OLD["header"] not in fetched
    assert closed["state"] == state and bool(res["problems"]) is (state == "FAILED"), res["problems"]
    pic = closed["reads"]["pictures"]["3"]
    if polls is None:
        assert clock[0] >= undo_driver.RESTORE_WAIT and pic["restored"] is None
    else:
        assert pic["polls"] == polls and pic["ok"] and clock[0] < undo_driver.RESTORE_WAIT
    assert (_NEW in fetched) is (case == "the late test cover, then the restore")


@pytest.mark.parametrize("before, img", [
    ({"header": None, "headerSize": None}, (200, b"\x89PNG\r\n\x1a\n")),
    (_OLD, (403, b"")),
    (_OLD, (200, b"<html>")),
    (_OLD, (200, b"\xff\xd8\xff" + b"0" * (5 * 1024 * 1024))),
])
def test_cover_proof_stops_before_its_trigger_without_a_picture_to_put_back(tmp_path, before, img):
    import undo_driver
    from proofs import phase3
    with pytest.raises(RuntimeError):
        undo_driver.keep(phase3.COVER, before, lambda *a, **k: img, "c1", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_cover_undo_upload_is_a_reversal_once_the_arms_are_spent():
    from proof_core import Request, Run, decide
    from proofs import phase2, phase3
    run = Run(proof=phase3.COVER, of="fake", spent={("arm", i): 1 for i in range(4)}, hosts=phase3.COVER.hosts)
    for method, host, path in [("POST", "onlyfans.com", "/api2/v2/upload/signed/create"),
                               ("PUT", phase2.S3_HOST, "/upload/c1/u/1/cover.png"),
                               ("POST", "convert.onlyfans.com", "/file/upload"),
                               ("PATCH", "onlyfans.com", "/api2/v2/users/me")]:
        assert decide(Request(method, host, path, {}), run).kind == "reversal", path


def _iso(t):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def _hit(t, m, p, body=None):
    return {"t": t, "method": m, "path": p, "status": 200, "body": body or {}}


def test_cover_fake_row_check_tells_the_undo_from_the_write_by_time():
    import undo_driver
    from proofs import phase3
    t0 = 1_000.0
    plain = [_hit(t0 + 1, "POST", "/api2/v2/upload/signed/create"), _hit(t0 + 2, "PATCH", "/api2/v2/users/me"),
             _hit(t0 + 11, "POST", "/api2/v2/upload/signed/create"), _hit(t0 + 12, "PATCH", "/api2/v2/users/me")]
    rev = {"method": "PATCH", "path": "/api2/v2/users/me", "seq": 9, "status": 200, "at": t0 + 10}
    rows = [{"row": n, "arm": arm, "of_id": None, "opened": _iso(t0 + n), "closed": _iso(t0 + 20), "reversals": [rev],
             "write": {"method": m, "path": p}} for n, arm, m, p in [(1, 0, "POST", "/api2/v2/upload/signed/create"),
                                                                       (2, 3, "PATCH", "/api2/v2/users/me")]]
    assert [undo_driver.row_problem(phase3.COVER, c, rows, plain) for c in rows] == [None, None]
    no_undo = [{**c, "reversals": [{**rev, "at": t0 + 30}]} for c in rows]
    assert all(undo_driver.row_problem(phase3.COVER, c, no_undo, plain[:2]) for c in no_undo)
    late = plain + [_hit(t0 + 14, "PATCH", "/api2/v2/users/me")]
    assert undo_driver.row_problem(phase3.COVER, rows[1], rows, late)


def test_fake_row_check_finds_a_late_write_for_any_proof():
    import undo_driver
    from proofs import phase3
    p = next(x for x in phase3.PROOFS if x.undo and callable(x.undo[0].relay_body) and x.undo[0].reverses is None
             and len(x.arm) == 1)
    path = p.arm[0].path
    t0 = 1_000.0
    rev = {"method": p.arm[0].method, "path": path, "seq": 9, "status": 200, "at": t0 + 10}
    row = {"row": 1, "arm": 0, "of_id": None, "opened": _iso(t0), "closed": _iso(t0 + 20), "reversals": [rev],
           "write": {"method": p.arm[0].method, "path": path}}
    plain = [_hit(t0 + 1, p.arm[0].method, path, {"v": 1}), _hit(t0 + 11, p.arm[0].method, path, {"v": 0})]
    assert undo_driver.row_problem(p, row, [row], plain) is None
    assert undo_driver.row_problem(p, row, [row], plain + [_hit(t0 + 12, p.arm[0].method, path, {"v": 1})])


def _timing_rows(t0, spec):
    return [{"row": n, "arm": arm, "of_id": oid, "opened": _iso(t0 + n), "closed": _iso(t0 + 20), "reversals": revs,
             "write": {"method": m, "path": p}, **({"keys": keys} if keys else {})}
            for n, arm, m, p, oid, revs, keys in spec]


def _timing_case(name):
    from proofs import phase2
    t0, lists = 1_000.0, "/api2/v2/vault/lists"
    by_id = {p.id: p for p in phase2.PROOFS}
    if name == "ticket 34":
        rec = {"method": "DELETE", "path": f"{lists}/f1", "status": 200, "seq": 7, "by": "trigger"}
        rows = _timing_rows(t0, [(1, 0, "POST", lists, "f1", [rec], None)])
        ok = [_hit(t0 + 2, "POST", lists), _hit(t0 + 5, "DELETE", f"{lists}/f1")]
        return by_id["vault.more.delete"], rows, ok, ok + [_hit(t0 + 6, "POST", lists)]
    if name == "vault.more.rename":
        rec = {"method": "DELETE", "path": f"{lists}/f1", "status": 200, "seq": 9, "at": t0 + 10}
        rows = _timing_rows(t0, [(1, 0, "POST", lists, "f1", [rec], None),
                                 (2, 1, "PATCH", f"{lists}/f1", "f1", [rec], None)])
        ok = [_hit(t0 + 2, "POST", lists), _hit(t0 + 4, "PATCH", f"{lists}/f1"), _hit(t0 + 11, "DELETE", f"{lists}/f1")]
        return by_id["vault.more.rename"], rows, ok, ok + [_hit(t0 + 12, "PATCH", f"{lists}/f1")]
    assert name == "ticket 30"
    hidden = "/api2/v2/vault/media/hidden"
    delete = {"method": "DELETE", "path": "/api2/v2/posts/p1", "status": 200, "seq": 9, "at": t0 + 10}
    hide = {"method": "PUT", "path": hidden, "status": 200, "seq": 10, "at": t0 + 10.5}
    keys = {"media": "m1"}
    rows = _timing_rows(t0, [(1, 0, "POST", "/api2/v2/upload/signed/create", None, [hide], keys),
                             (2, 2, "POST", "/file/upload", None, [hide], keys),
                             (3, 3, "POST", "/api2/v2/posts", "p1", [delete, hide], keys)])
    ok = [_hit(t0 + 1.5, "POST", "/api2/v2/upload/signed/create"), _hit(t0 + 2.5, "POST", "/file/upload"),
          _hit(t0 + 4, "POST", "/api2/v2/posts"), _hit(t0 + 11, "DELETE", "/api2/v2/posts/p1"),
          _hit(t0 + 12, "PUT", hidden, {"mediaIds": ["m1"]})]
    return by_id["p2.record-video"], rows, ok, ok + [_hit(t0 + 13, "POST", "/file/upload")]


@pytest.mark.parametrize("name, late_row", [("ticket 34", 1), ("vault.more.rename", 2), ("ticket 30", 2)])
def test_fake_row_check_time_rule_table(name, late_row):
    import undo_driver
    proof, rows, ok, bad = _timing_case(name)
    assert [undo_driver.row_problem(proof, c, rows, ok) for c in rows] == [None] * len(rows)
    row = next(c for c in rows if c["row"] == late_row)
    assert undo_driver.row_problem(proof, row, rows, bad)
T61_IDS = ("settings--tracking-links-sort", "settings--tracking-links-sort-modal", "settings--tracking-links-sort-radios",
           "settings--trial-links-sort-radios")


def _fake_get(start=None):
    import time
    from urllib.parse import urlencode
    from starlette.testclient import TestClient
    from soak.fake_of.app import FakeOF
    from soak.fake_of.signing import sign_value
    from soak.world import World
    fake = FakeOF(World(seed=1))
    if start:
        start(fake)
    client = TestClient(fake.build())

    def get(path, query):
        pq = f"{path}?{urlencode(query)}" if query else path
        t, uid = str(int(time.time() * 1000)), str(fake.world.creator_id)
        return client.get(pq, headers={"user-id": uid, "x-hash": fake.x_hash, "time": t,
                                       "sign": sign_value(fake.rules, time_ms=t, path_qs=pq, user_id=uid)}).json()
    return get


def test_ticket_61_sort_waits_hold_no_fixed_row_name():
    from expects import Expect, expect_waits
    from proofs import ALL
    for pid in T61_IDS:
        p = ALL[pid]
        texts = [s for s in p.trigger if s[0] == "text"] + [p.settled]
        assert texts and all(isinstance(s[2], Expect) for s in texts), pid
        assert len(expect_waits(p)) == len(texts), pid


@pytest.mark.parametrize("pid, want", [
    ("settings--tracking-links-sort", {2: "Zeta link", "settled": "Alpha link"}),
    ("settings--tracking-links-sort-modal", {"settled": "Zeta link"}),
    ("settings--tracking-links-sort-radios", {"settled": "Zeta link"}),
    ("settings--trial-links-sort-radios", {"settled": "Alpha trial"}),
])
def test_ticket_61_sort_waits_resolve_from_fakeofs_sorted_read(pid, want):
    from expects import expect_waits, resolve_expects
    from proofs import ALL
    assert resolve_expects(expect_waits(ALL[pid]), _fake_get()) == want


def test_ticket_61_sort_parks_when_onlyfans_unsorted_order_has_the_same_first_row():
    from expects import Park, expect_waits, resolve_expects
    from proofs import ALL
    waits = expect_waits(ALL["settings--tracking-links-sort-radios"])
    real = _fake_get()

    def get(path, query):
        return real(path, {**query, "field": "name", "sort": "desc"} if "sort" not in query else query)
    with pytest.raises(Park, match="is first in /api2/v2/campaigns unsorted too"):
        resolve_expects(waits, get)


_BOTH = "parked — needs capture (ticket 12 sitting): Email notifications switch body, New Likes Summary switch body"


@pytest.mark.parametrize("before, why", [
    ({"email": False, "isEnabled": False, "value": 0}, _BOTH),
    ({"email": True, "isEnabled": False, "value": 0},
     "parked — needs capture (ticket 12 sitting): New Likes Summary switch body"),
    ({"email": False, "isEnabled": True, "value": 12},
     "parked — needs capture (ticket 12 sitting): Email notifications switch body"),
    (None, TypeError),
    ({"isEnabled": False, "value": 0}, KeyError),
    ({"email": True, "isEnabled": True, "value": 24}, "parked — New Likes Summary is at 24 hours"),
    ({"email": True, "isEnabled": True, "value": 12}, None),
])
def test_ticket_60_frequency_parks_unless_both_switches_are_on_below_24_hours(before, why):
    from proofs.phase3 import FREQUENCY
    if isinstance(why, type):
        with pytest.raises(why):
            FREQUENCY.ready(before)
        return
    got = FREQUENCY.ready(before)
    assert got == why if why is None or why.endswith("body") else got.startswith(why)


@pytest.mark.parametrize("drop", ["isEnabled", "value", "isEmailNotificationsEnabled"])
def test_ticket_60_frequencys_read_raises_on_a_missing_key(drop):
    from proofs.phase3 import FREQUENCY
    item = {"code": "new_likes_digest", "isEnabled": True, "value": 12}
    settings = {"isEmailNotificationsEnabled": True}
    item.pop(drop, None), settings.pop(drop, None)
    replies = {"/api2/v2/users/settings/notifications/email": [{"items": [item]}], "/api2/v2/users/me/settings": settings}
    with pytest.raises(KeyError):
        FREQUENCY.of_read(lambda path, q: replies[path], None)


def test_ticket_60_frequency_is_ready_on_fakeofs_default_account_and_parks_on_email_off():
    from proofs.phase3 import FREQUENCY
    from soak.fake_of.settings import email_off
    before = FREQUENCY.of_read(_fake_get(), None)
    assert before == {"isEnabled": True, "value": 12, "email": True} and FREQUENCY.ready(before) is None
    off = FREQUENCY.of_read(_fake_get(email_off), None)
    assert off == {"isEnabled": False, "value": 0, "email": False} and FREQUENCY.ready(off) == _BOTH


def test_ticket_60_email_off_is_a_start_state_whose_run_passes_only_when_frequency_parks():
    from fake_layer import FAULTS, STATES, Recorder, start_state_problems
    from proofs.phase3 import FREQUENCY
    from soak.fake_of.app import FakeOF
    from soak.world import World
    assert "email-off" not in FAULTS
    start, pid = STATES["email-off"]
    assert pid == FREQUENCY.id and FREQUENCY.of_read(_fake_get(start), None) == {"isEnabled": False, "value": 0, "email": False}
    with pytest.raises(ValueError):
        Recorder(FakeOF(World(seed=1)).build(), "email-off")
    assert start_state_problems("email-off", [{"proof": pid, "reason": "parked — ..."}]) == []
    assert start_state_problems("email-off", []) == ["start state email-off: settings--email-update-frequency did not park"]
    assert start_state_problems("email-off", [{"proof": "settings--tracking-links-sort"}]) != []



def test_the_proof_picture_is_an_intact_png_and_fakeof_refuses_a_corrupt_one():
    import prove
    import undo_driver
    from soak.fake_of.posts import png_intact
    assert png_intact(prove.PIXEL_PNG) and undo_driver.picture_size(prove.PIXEL_PNG) == (1280, 720)
    bad = bytearray(prove.PIXEL_PNG)
    bad[-20] ^= 0xFF
    assert not png_intact(bytes(bad)) and not png_intact(prove.PIXEL_PNG[:-6]) and png_intact(b"\xff\xd8\xff jpeg")
