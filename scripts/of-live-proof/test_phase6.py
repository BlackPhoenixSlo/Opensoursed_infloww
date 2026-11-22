"""Ticket 94: Phase 6's proof list (proofs/phase6.py), the driver parking an id with no definition yet, the
spec's Acceptance record check (`record_problems`, docs/spec/ofm-not-yet/phase-06-unproven-live-check.md) on the
committed records and on planted bad ones, the vault--thumbnails judge (`thumbnails_check`), and its `images` step
(`ui_steps.collect_tiles`) over lazy tiles below the fold. Ticket 95: the Tips, story strip, highlights and payout-row
judges, each passing, failing on its planted variant and parking with no precondition.
"""
import ast
import json
import subprocess
import sys
from urllib.parse import quote, urlsplit

import pytest

import proof_list
import prove
import ui_steps
from proofs import ALL, PENDING, phase6

SPEC_IDS = ["vault--thumbnails", "notifications--tips", "home--story-strip", "profile--highlights",
            "statements--payout-rows", "vault--customize-order-save", "new-post--upload",
            "new-post--dedupe-duplicate-id", "new-post--cotag-scheduled",
            "new-post--cotag-immediate", "queue--publish-now", "queue--send-message-right-now"]


def test_ids_cli_prints_the_twelve_in_proof_order():
    out = subprocess.run([sys.executable, "-I", str(phase6.HERE / "proofs" / "phase6.py"), "--ids"],
                         capture_output=True, text=True, check=True).stdout.strip()
    ids = out.split(",")
    assert ids == list(phase6.IDS) and sorted(ids) == sorted(SPEC_IDS) and len(ids) == 12
    # Proof order: reads first, Fan-reaching writes last, Publish now (proof D) before the immediate Co-tag.
    assert ids[0] == "vault--thumbnails" and ids[-1] == "queue--send-message-right-now"
    assert ids.index("queue--publish-now") < ids.index("new-post--cotag-immediate")


READS = ["vault--thumbnails", "notifications--tips", "home--story-strip", "profile--highlights",
         "statements--payout-rows"]


def test_the_reads_are_defined_and_the_rest_are_pending():
    defined = [p.id for p in phase6.PROOFS]   # tickets 95-100 append theirs (D29)
    assert defined[:len(READS)] == READS
    assert {"vault--customize-order-save", "queue--send-message-right-now"} <= set(defined)   # tickets 96, 100
    assert set(defined) <= set(ALL) and set(defined) <= set(SPEC_IDS)
    assert PENDING == frozenset(SPEC_IDS) - set(defined)
    assert all(not p.arm for p in phase6.PROOFS if p.id in READS)   # the reads: zero writes
    assert phase6.PROFILE_HIGHLIGHTS.branches == ("row", "playback")


def test_driver_takes_pending_ids_to_park_and_still_refuses_unknown(monkeypatch, capsys):
    ran = []
    monkeypatch.setattr(prove, "prove", lambda ids, fault, fan, **k: ran.append(ids) or 0)   # ticket 09: of, session_src, serve
    monkeypatch.setattr(prove.os, "setpriority", lambda *a: None)
    assert prove.main(["--of", "fake", "--proof", ",".join(phase6.IDS)]) == 0
    assert ran == [list(phase6.IDS)]
    assert prove.main(["--of", "fake", "--proof", "vault--thumbnails,no-such-proof"]) == 2
    assert "unknown proof ['no-such-proof']" in capsys.readouterr().err


def test_cdn_suffixes_match_the_relay():
    tree = ast.parse((phase6.ROOT / "service" / "of_client.py").read_text())
    relay = next(ast.literal_eval(n.value) for n in ast.walk(tree) if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "OF_CDN_SUFFIXES" for t in n.targets))
    assert tuple(phase6.CDN_SUFFIXES) == tuple(relay)


def test_committed_records_pass_the_spec_check():
    assert phase6.record_problems() == []
    recs = proof_list.load_records(phase6.CAPTURES)[0]
    for proof in phase6.PROOFS:   # proof_list finds each defined proof's record by label and page
        assert proof_list.record_of(proof, recs)[0] == f"{proof.id}.json"
    reasons = {i: json.loads((phase6.CAPTURES / f"{i}.json").read_text())["proof"].get("reason", "") for i in SPEC_IDS}
    assert "owner sheet item 1 (Proof fan)" in reasons["queue--send-message-right-now"]
    for i in ("new-post--cotag-scheduled", "new-post--cotag-immediate"):
        assert "owner sheet item 4 (Co-tag partner)" in reasons[i]


PARKED = {"kind": "live", "verdict": "parked", "undo": "none", "reason": "Live proof pending"}


@pytest.mark.parametrize("planted, flagged", [
    ({"verdict": "parked", "reason": ""}, True),                                     # parked without a reason
    ({"verdict": "pass", "evidence": ""}, True),                                     # pass without evidence
    ({"verdict": "pass", "kind": "mocked", "evidence": "slop/evidence/x"}, True),    # pass, not live
    ({"verdict": "pass", "evidence": "slop/evidence/x", "undo": "FAILED"}, True),    # a FAILED undo
    ({"verdict": "fail", "reason": "x"}, True),
    ({"verdict": "pass", "evidence": "slop/evidence/x", "undo": "undone"}, False),
])
def test_record_check_flags_planted_bad_records(tmp_path, planted, flagged):
    for i in SPEC_IDS:
        (tmp_path / f"{i}.json").write_text(json.dumps({"id": i, "proof": PARKED}))
    (tmp_path / "home--story-strip.json").write_text(json.dumps({"proof": {**PARKED, **planted}}))
    bad = phase6.record_problems(tmp_path)
    assert [i for i, _ in bad] == (["home--story-strip"] if flagged else [])


def test_record_check_publish_now_pass_needs_its_hidden_dedupe_branch(tmp_path):
    for i in SPEC_IDS:
        (tmp_path / f"{i}.json").write_text(json.dumps({"proof": PARKED}))
    passed = {"kind": "live", "verdict": "pass", "evidence": "slop/evidence/x", "undo": "undone"}
    (tmp_path / "queue--publish-now.json").write_text(json.dumps({"proof": {**passed, "branches": {"publish-now": "pass"}}}))
    assert phase6.record_problems(tmp_path) == [("queue--publish-now", "no hidden-dedupe branch")]
    (tmp_path / "queue--publish-now.json").write_text(
        json.dumps({"proof": {**passed, "branches": {"publish-now": "pass", "hidden-dedupe": "pass"}}}))
    assert phase6.record_problems(tmp_path) == []


def test_record_check_missing_record_and_cli_exit(tmp_path):
    for i in SPEC_IDS[1:]:
        (tmp_path / f"{i}.json").write_text(json.dumps({"proof": PARKED}))
    assert [i for i, _ in phase6.record_problems(tmp_path)] == ["vault--thumbnails"]
    assert phase6.main(["--check-records", str(tmp_path)]) == 1
    assert phase6.main([f"--check-records={tmp_path}"]) == 1   # the `=` form runs the spec check too
    assert phase6.main(["--check-records", str(phase6.CAPTURES)]) == 0
    assert phase6.main([f"--check-records={phase6.CAPTURES}"]) == 0
    assert phase6.main(["--check-records", str(tmp_path / "missing")]) == 2


APP = "http://127.0.0.1:3000"


def img(n, cache="HIT"):
    """(tile src, the Relay's /img response for it)."""
    src = f"{APP}/img?u=https%3A%2F%2Ffake-cdn.ofcdn.com%2F{n}.png&account_id=1"
    return src, {"url": src, "status": 200, "cache": cache}


def seen(tiles, responses, offhost=()):
    return {"origins": [APP], "images": [{"page": "vault/index", "tiles": tiles}],
            "responses": list(responses), "offhost": list(offhost)}


def tile(src, complete=True, width=8):
    return {"src": src, "complete": complete, "width": width}


def test_thumbnails_check_passes_with_a_cold_relay_tile():
    (s1, r1), (s2, r2) = img(1, "MISS"), img(2, "HIT")
    sq = f"{APP}/admin/vault-ai/thumb?media_id=1"
    other = {"url": f"{APP}/api/of/v2/users/notifications/count", "status": 404, "cache": None}   # not a tile's
    assert phase6.thumbnails_check(seen([tile(s1), tile(s2), tile(sq)], [r1, r2, other])) == \
        {"problems": [], "parked": None, "record": {}}


def test_thumbnails_check_cold_counts_even_if_a_later_page_hits():
    (s1, r1) = img(1, "MISS")
    v = seen([tile(s1)], [r1, {**r1, "cache": "HIT"}])
    assert phase6.thumbnails_check(v)["problems"] == []


@pytest.mark.parametrize("why, build", [
    ("tile src on a CDN host", lambda: seen([tile("https://fake-cdn.ofcdn.com/1.png"), tile(img(2)[0])],
                                            [img(2, "MISS")[1]])),
    ("not through the Relay", lambda: seen([tile("http://127.0.0.1:9/elsewhere.png"), tile(img(2)[0])],
                                           [img(2, "MISS")[1]])),
    ("did not load", lambda: seen([tile(img(1)[0], width=0)], [img(1, "MISS")[1]])),
    ("answered 400 (host not allowed)", lambda: seen([tile(img(1)[0])], [{**img(1, "MISS")[1], "status": 400}])),
    ("browser request to an OnlyFans CDN host", lambda: seen([tile(img(1)[0])], [img(1, "MISS")[1]],
                                                             [{"url": "https://cdn2.onlyfans.com/x.jpg"}])),
    ("no tile loaded through a cold /img", lambda: seen([tile(img(1)[0])], [img(1, "HIT")[1]])),
    ("no vault tile", lambda: seen([], [img(1, "MISS")[1]])),
])
def test_thumbnails_check_fails(why, build):
    problems = phase6.thumbnails_check(build())["problems"]
    assert any(why in p for p in problems), problems


# ── ticket 95: the feed and profile read checks ──

def ok(body):
    return {"status": 200, "body": body}


def relay_img(u, loaded=True):
    return {"src": f"{APP}/img?u={quote(u, safe='')}&account_id=1", "complete": loaded, "width": 8 if loaded else 0}


def tip_row(n):
    return {"type": "tip", "text": "{NAME} sent you a tip of {AMOUNT}",
            "replacePairs": {"{NAME}": f"Fan {n}", "{AMOUNT}": "$5.00"},
            "user": {"name": f"Fan {n}", "username": f"fan{n}"}}


def tip_item(n, icon="icon-price"):
    return {"name": f" Fan {n} ", "handle": f" @fan{n} ", "text": f"Fan {n} sent you a tip of $5.00", "icon": icon,
            "icon_use": None, "_imgs": []}


def tips_seen(tip, tipped, items):
    return {"of_read": {"tip": tip, "tipped": tipped}, "dom": [{"items": items}]}


def test_tips_check_pass_records_both_filters():
    got = phase6.tips_check(tips_seen(ok({"list": [tip_row(1), tip_row(2)]}), ok({"list": [tip_row(1)]}),
                                      [tip_item(1), tip_item(2)]))
    assert got["problems"] == [] and got["parked"] is None
    r = got["record"]["results"]
    assert r["tip"] == {"status": 200, "rows": 2, "types": ["tip"], "answer": "accepted"}
    assert r["tipped"]["rows"] == 1 and r["agree"]


@pytest.mark.parametrize("why, tip, items", [
    ("do not equal OnlyFans's", [tip_row(1)], [tip_item(1), {**tip_item(9), "text": "Planted fan commented"}]),
    ("has a commented row", [tip_row(1), {**tip_row(9), "type": "commented"}], [tip_item(1), tip_item(9)]),
    ("has no tip badge", [tip_row(1)], [tip_item(1, icon=None)]),
    ("do not equal OnlyFans's", [tip_row(1)], []),
])
def test_tips_check_fails(why, tip, items):
    got = phase6.tips_check(tips_seen(ok({"list": tip}), ok({"list": []}), items))
    assert any(why in p for p in got["problems"]), got
    assert not got["record"]["results"]["agree"]


def test_tips_check_parks_with_no_tip_and_fails_on_tipped_only():
    got = phase6.tips_check(tips_seen(ok({"list": []}), ok({"list": []}), []))
    assert got["problems"] == [] and "no tip notification" in got["parked"]
    assert got["record"]["results"]["tip"]["answer"] == "accepted-but-empty"
    got = phase6.tips_check(tips_seen(ok({"list": []}), ok({"list": [tip_row(1)]}), []))
    assert any("wrong filter" in p for p in got["problems"]) and got["parked"] is None
    got = phase6.tips_check(tips_seen({"status": 403, "body": None}, ok({"list": []}), []))
    assert any("refused the type=tip read: 403" in p for p in got["problems"]) and got["parked"] is None


def story(uid, n, watched=False):
    return {"id": n, "userId": uid, "isWatched": watched,
            "media": [{"files": {"thumb": {"url": f"https://fake-cdn.ofcdn.com/s{n}/t.png"},
                                 "full": {"url": f"https://fake-cdn.ofcdn.com/s{n}/f.png"}}}]}


def strip_seen(stubs, items, tiles, relay_status=200):
    return {"of_read": {"map": stubs if isinstance(stubs, dict) else ok(stubs), "items": ok(items)},
            "dom": [{"items": tiles}], "responses": [{"url": f"{APP}/api/of/v2/stories", "status": relay_status}]}


def strip_tile(uid, stories, viewed=False):
    first = next((s for s in stories if not s["isWatched"]), stories[0])
    return {"user": str(uid), "story": json.dumps([{}] * len(stories)), "name": "x",
            "viewed": "b-story-item" + (" m-viewed" if viewed else ""),
            "_imgs": [relay_img(first["media"][0]["files"]["thumb"]["url"])]}


STRIP = {1: [story(1, 11), story(1, 12)], 2: [story(2, 21, True)]}
STUBS = [{"userId": 1, "storyId": 11, "isWatched": False}, {"userId": 2, "storyId": 21, "isWatched": True}]
ITEMS = STRIP[1] + STRIP[2]


def test_strip_check_pass():
    got = phase6.strip_check(strip_seen(STUBS, ITEMS, [strip_tile(1, STRIP[1]), strip_tile(2, STRIP[2], True)]))
    assert got["problems"] == [] and got["parked"] is None and got["record"]["relay_stories"] == "matching"


@pytest.mark.parametrize("why, tiles", [
    ("has no tile", [strip_tile(2, STRIP[2], True)]),                                    # the planted strip-miss
    ("is not on OnlyFans's strip", [strip_tile(1, STRIP[1]), strip_tile(2, STRIP[2], True), strip_tile(3, STRIP[2])]),
    ("carries 1 stories, OnlyFans 2", [{**strip_tile(1, STRIP[1]), "story": "[{}]"}, strip_tile(2, STRIP[2], True)]),
    ("watched mark", [strip_tile(1, STRIP[1]), strip_tile(2, STRIP[2])]),
    ("still is not", [{**strip_tile(1, STRIP[1]), "_imgs": [relay_img("https://fake-cdn.ofcdn.com/x.png")]},
                      strip_tile(2, STRIP[2], True)]),
    ("did not load", [{**strip_tile(1, STRIP[1]), "_imgs": [{**strip_tile(1, STRIP[1])["_imgs"][0], "width": 0}]},
                      strip_tile(2, STRIP[2], True)]),
])
def test_strip_check_fails(why, tiles):
    got = phase6.strip_check(strip_seen(STUBS, ITEMS, tiles))
    assert any(why in p for p in got["problems"]), got
    assert got["record"]["relay_stories"] == "differs"


def test_strip_check_records_an_empty_relay_strip():
    got = phase6.strip_check(strip_seen(STUBS, ITEMS, []))
    assert got["record"]["relay_stories"] == "empty" and got["problems"]


def test_strip_check_parks_on_no_story_and_on_a_refused_strip_read():
    got = phase6.strip_check(strip_seen([], [], []))
    assert got["problems"] == [] and "no story" in got["parked"]
    got = phase6.strip_check(strip_seen({"status": 404, "body": None}, [], [], relay_status=404))
    assert got["problems"] == [] and phase6.NEEDS_CAPTURE in got["parked"]
    assert got["record"]["relay_stories"] == "refused"


@pytest.mark.parametrize("stubs, why", [
    ({"status": 403, "body": None}, "OnlyFans's strip read answered 403"),
    ([], "OnlyFans's strip is empty"),
], ids=["refused read", "empty strip"])
def test_strip_check_fails_on_tiles_with_no_onlyfans_strip(stubs, why):
    got = phase6.strip_check(strip_seen(stubs, [], [strip_tile(1, STRIP[1])]))
    assert got["parked"] is None and any(why in p for p in got["problems"]), got


@pytest.mark.parametrize("body", [
    {"list": STUBS}, [{"userId": 1}], [{"storyId": 11}], ["1"], {"userId": 1, "storyId": 11},
], ids=["wrapped", "no storyId", "no userId", "not dicts", "a dict"])
def test_strip_check_parks_needs_capture_on_another_answer_shape(body):
    for tiles in ([], [strip_tile(1, STRIP[1])]):
        got = phase6.strip_check(strip_seen(ok(body), [], tiles))
        assert got["problems"] == [] and phase6.NEEDS_CAPTURE in got["parked"], got


def test_read_strip_reads_no_items_for_another_answer_shape():
    seen = []

    def get(path, q):
        seen.append(path)
        return [{"userId": 1}]
    assert "items" not in phase6.read_strip(get, None) and seen == ["/api2/v2/stories/map"]


H1 = {"id": 7, "title": "One", "cover": "https://fake-cdn.ofcdn.com/h1/t.png"}
H2 = {"id": 8, "title": "Two", "cover": "https://fake-cdn.ofcdn.com/h2/t.png"}
PLAY = {**H1, "stories": [story(0, 31), story(0, 32)]}


def hl_tile(h, cover=True):
    return {"id": str(h["id"]), "title": f" {h['title']} ", "cover": relay_img(h["cover"])["src"] if cover else None,
            "_imgs": [relay_img(h["cover"])] if cover else []}


VIEWER = {"bars": 2, "media": relay_img("https://fake-cdn.ofcdn.com/s31/f.png")["src"], "title": "x",
          "_imgs": [relay_img("https://fake-cdn.ofcdn.com/s31/f.png")]}


def hl_seen(rows, tiles, viewer=VIEWER, play=PLAY):
    read = {"me": {"status": 200, "id": 1}, "row": rows if "status" in rows else ok(rows)}
    if play is not None:
        read["playback"] = ok(play)
    return {"of_read": read, "dom": [{"items": tiles}, {"items": [viewer] if viewer else []}]}


def test_highlights_check_pass_both_branches():
    got = phase6.highlights_check(hl_seen({"list": [H1, H2]}, [hl_tile(H1), hl_tile(H2)]))
    assert got["problems"] == [] and got["record"]["branches"] == {"row": "pass", "playback": "pass"}


@pytest.mark.parametrize("why, branches, tiles, viewer", [
    ("(cover)", {"row": "fail", "playback": "pass"}, [hl_tile(H1, cover=False), hl_tile(H2)], VIEWER),  # planted
    ("differ from OnlyFans's", {"row": "fail", "playback": "pass"}, [hl_tile(H1)], VIEWER),
    ("opened no viewer", {"row": "pass", "playback": "fail"}, [hl_tile(H1), hl_tile(H2)], None),
    ("shows 1 bars", {"row": "pass", "playback": "fail"}, [hl_tile(H1), hl_tile(H2)], {**VIEWER, "bars": 1}),
    ("first story", {"row": "pass", "playback": "fail"}, [hl_tile(H1), hl_tile(H2)],
     {**VIEWER, "media": relay_img("https://fake-cdn.ofcdn.com/x.png")["src"]}),
])
def test_highlights_check_fails_per_branch(why, branches, tiles, viewer):
    got = phase6.highlights_check(hl_seen({"list": [H1, H2]}, tiles, viewer))
    assert any(why in p for p in got["problems"]), got
    assert got["record"]["branches"] == branches


def test_highlights_check_parks_both_branches_with_no_highlight():
    got = phase6.highlights_check(hl_seen({"list": []}, [], None, None))
    assert got["problems"] == [] and got["parked"] == "no highlight on the Proof Creator"
    assert got["record"]["branches"] == {b: "parked: no highlight on the Proof Creator" for b in ("row", "playback")}
    got = phase6.highlights_check(hl_seen({"status": 500, "body": None}, [], None, None))
    assert got["problems"] and got["parked"] is None


def test_highlights_check_fails_on_tiles_with_no_onlyfans_highlight():
    got = phase6.highlights_check(hl_seen({"list": []}, [hl_tile(H1)], None, None))
    assert got["parked"] is None and any("OnlyFans has no highlight" in p for p in got["problems"])
    assert got["record"]["branches"] == {"row": "fail", "playback": "fail"}


def payout(state, amount, inv, reason=None):
    return {"invoiceId": inv, "createdAt": "2026-11-20T00:00:00+00:00", "amount": amount, "state": state,
            "rejectReason": reason}


def pay_item(state, amount, inv, reason=None):
    mark = "pending" if state == "new" else state
    return {"invoice": f" {inv} ", "amount": f" ${amount:.2f} ", **{s: int(s == mark) for s in phase6.PAYOUT_STATES},
            "text": f"Nov 20 {inv} ${amount:.2f}" + (f" Reason: {reason}" if reason else "")}


PAY = [("approved", 85.23, "11"), ("new", 40, "12"), ("rejected", 12.5, "13", "Not verified")]
REF = [("approved", 7.25, "51")]


def pay_seen(pay, ref, shown_pay, shown_ref):
    return {"of_read": {"statements/payouts": ok({"list": [payout(*p) for p in pay]}),
                        "statements/referrals": ok({"list": [payout(*p) for p in ref]})},
            "dom": [{"items": shown_pay}, {"items": shown_ref}]}


def test_payouts_check_pass_lists_observed_and_unobserved():
    got = phase6.payouts_check(pay_seen(PAY, REF, [pay_item(*p) for p in PAY], [pay_item(*p) for p in REF]))
    assert got["problems"] == [] and got["parked"] is None
    p, r = got["record"]["statements/payouts"], got["record"]["statements/referrals"]
    assert p["observed"] == {"fields": list(phase6.PAYOUT_FIELDS), "states": list(phase6.PAYOUT_STATES)}
    assert p["unobserved"] == {"fields": [], "states": []}
    assert r["observed"]["states"] == ["approved"]
    assert r["unobserved"] == {"fields": ["rejectReason"], "states": ["pending", "rejected"]}


@pytest.mark.parametrize("why, shown", [
    ("row 1 invoice", [{**pay_item(*REF[0]), "invoice": ""}]),                 # the planted payout-field
    ("row 1 amount", [pay_item("approved", 7.5, "51")]),
    ("row 1 state mark ['pending']", [pay_item("new", 7.25, "51")]),
    ("shows 0 rows, OnlyFans 1", []),
])
def test_payouts_check_fails(why, shown):
    got = phase6.payouts_check(pay_seen([], REF, [], shown))
    assert any(why in p for p in got["problems"]), got


def test_payouts_check_reject_reason_and_park():
    got = phase6.payouts_check(pay_seen([PAY[2]], [], [pay_item("rejected", 12.5, "13")], []))
    assert any("reject reason" in p for p in got["problems"])
    got = phase6.payouts_check(pay_seen([], [], [], []))
    assert got["problems"] == [] and "no payout request" in got["parked"]
    assert got["record"]["statements/payouts"]["unobserved"]["states"] == list(phase6.PAYOUT_STATES)


# ── the `images` step in a real browser ──

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def test_images_step_scrolls_lazy_tiles_below_the_fold_into_loading(pw):
    """Measured live: the Mirror's tiles carry OF's loading="lazy", so the ones below the fold of the Mirror frame never
    started loading and the check flagged them. The step scrolls each one into view; every tile loads."""
    sel = "[data-oi-media] .b-photos__item__img"
    tiles = "".join(f'<div data-oi-media="{n}" style="height:300px"><img loading="lazy" class="b-photos__item__img" '
                    f'src="http://mirror.test/img?n={n}"></div>' for n in range(24))
    pages = {"/": '<iframe src="http://mirror.test/frame" style="width:800px;height:600px;border:0"></iframe>',
             "/frame": f"<body>{tiles}</body>"}
    served = []

    def route(r):
        u = urlsplit(r.request.url)
        if u.path == "/img":
            served.append(u.query)
            return r.fulfill(status=200, content_type="image/png", body=PNG)
        r.fulfill(status=200, content_type="text/html", body=pages[u.path])

    b = pw.chromium.launch()
    try:
        page = b.new_page(viewport={"width": 800, "height": 600})
        page.route("http://mirror.test/**", route)
        page.goto("http://mirror.test/", wait_until="load")
        fr = next(f for f in page.frames if f.url.endswith("/frame"))
        fr.locator(sel).first.wait_for(state="visible")
        page.wait_for_timeout(500)
        before = fr.evaluate("s => [...document.querySelectorAll(s)].filter(i => !i.complete).length", sel)
        assert before > 10, "the fixture's tiles below the fold should still be unloaded (lazy)"
        got = ui_steps.collect_tiles(fr, sel, timeout_ms=15_000)
    finally:
        b.close()
    assert len(got) == 24 and all(t["complete"] and t["width"] > 0 for t in got), got
    assert len(set(served)) == 24


def test_images_step_walks_past_a_broken_and_a_hanging_tile(pw):
    """A tile that fails (404) is reported loaded-with-no-width, one whose request never answers stays incomplete, and
    neither keeps the walk from scrolling the tiles after them into loading."""
    sel = "[data-oi-media] .b-photos__item__img"
    tiles = "".join(f'<div data-oi-media="{n}" style="height:300px"><img loading="lazy" class="b-photos__item__img" '
                    f'src="http://mirror.test/img?n={n}"></div>' for n in range(16))
    pages = {"/": '<iframe src="http://mirror.test/frame" style="width:800px;height:600px;border:0"></iframe>',
             "/frame": f"<body>{tiles}</body>"}

    def route(r):
        u = urlsplit(r.request.url)
        if u.path == "/img":
            if u.query == "n=5":
                return r.fulfill(status=404, body="")
            if u.query == "n=8":
                return None   # never answered
            return r.fulfill(status=200, content_type="image/png", body=PNG)
        r.fulfill(status=200, content_type="text/html", body=pages[u.path])

    b = pw.chromium.launch()
    try:
        page = b.new_page(viewport={"width": 800, "height": 600})
        page.route("http://mirror.test/**", route)
        page.goto("http://mirror.test/", wait_until="load")
        fr = next(f for f in page.frames if f.url.endswith("/frame"))
        got = ui_steps.collect_tiles(fr, sel, timeout_ms=6_000)
        marks = fr.evaluate("() => document.querySelectorAll('[data-oi-tile-seen]').length")
    finally:
        b.close()
    assert got[5]["complete"] and got[5]["width"] == 0, got[5]
    assert not got[8]["complete"], got[8]
    assert all(t["complete"] and t["width"] > 0 for n, t in enumerate(got) if n not in (5, 8)), got
    assert marks == 0   # the walk's marks are gone before the settled shot


# ticket 101: the proof list's order is the driver's, not the caller's
def test_driver_order_is_the_proof_list_order_whatever_the_given_order():
    from proof_core import order, order_group
    from proofs import ORDER
    given = [ALL[i] for i in reversed(phase6.IDS)]
    got = [p.id for p in order(given, canon=ORDER)]
    assert got == list(phase6.IDS)
    groups = [order_group(ALL[i]) for i in got]
    assert groups == [0] * 5 + [1] * 4 + [2] * 3   # reads, Fan-invisible writes, Fan-reaching writes


def test_prove_orders_by_the_proof_list():
    src = (phase6.HERE / "prove.py").read_text()
    assert "order([ALL[i] for i in proof_ids if i in ALL], canon=ORDER)" in src


# ticket 101: `--fault delete-500` reaches a Phase 6 run: an undo's DELETE of a list (tracer) or a post (the upload,
# dedupe, Co-tag and Publish now proofs) answers 500, so the run stops on its FAILED row before any Fan-reaching proof
@pytest.mark.parametrize("method, path, fires", [
    ("DELETE", "/api2/v2/lists/901", True), ("DELETE", "/api2/v2/posts/900070000000001", True),
    ("POST", "/api2/v2/posts", False), ("DELETE", "/api2/v2/trials/5", False),
    ("DELETE", "/api2/v2/messages/queue/5", False), ("DELETE", "/api2/v2/posts/7/comments", False),
], ids=["tracer list", "post", "post create", "trial (trial-delete-500's)", "queue item", "a post's sub-path"])
def test_delete_500_fires_on_a_list_or_post_delete(method, path, fires):
    import fake_layer
    hit = {"method": method, "path": path, "tagged": False, "query": "", "body": None}
    assert fake_layer.Recorder(lambda *a: None, "delete-500")._fires(hit) is fires
