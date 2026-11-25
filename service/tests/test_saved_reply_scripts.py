#!/usr/bin/env python3
import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import _agency_fixtures as fx  # noqa: E402

IDS = fx.seed_two_agencies()
A = IDS["creator_a"]
B = IDS["creator_b"]


def _list(c, acc=A) -> list[dict]:
    r = c.get(f"/admin/saved-replies?account_id={acc}")
    assert r.status_code == 200, r.text
    return r.json()["list"]


def _new(c, **body) -> dict:
    r = c.post(f"/admin/saved-replies?account_id={A}", json={"text": "hi", **body})
    assert r.status_code == 200, r.text
    return r.json()


def _relabel(c, acc=A, **body):
    return c.post(f"/admin/saved-replies/relabel?account_id={acc}", json=body)


def _wipe(c) -> None:
    for r in _list(c):
        assert c.delete(f"/admin/saved-replies/{r['id']}").status_code == 200


def case_tags_and_notes_round_trip_and_a_put_without_them_keeps_them():
    c = fx.login_owner("agency_a_owner")
    _wipe(c)
    row = _new(c, title="ask name", tags=[" Opener ", "Opener", "", "VIP"], notes="only after 9pm")
    assert row["tags"] == ["Opener", "VIP"], row
    assert row["notes"] == "only after 9pm", row
    r = c.put(f"/admin/saved-replies/{row['id']}", json={"text": "hello"})
    assert r.status_code == 200, r.text
    assert r.json()["tags"] == ["Opener", "VIP"] and r.json()["notes"] == "only after 9pm", r.json()
    r = c.put(f"/admin/saved-replies/{row['id']}", json={"text": "hello", "tags": [], "notes": ""})
    assert r.json()["tags"] == [] and r.json()["notes"] is None, r.json()
    assert _new(c)["tags"] == []


def case_a_tag_over_32_or_notes_over_256_characters_is_rejected():
    c = fx.login_owner("agency_a_owner")
    r = c.post(f"/admin/saved-replies?account_id={A}", json={"text": "x", "tags": ["x" * 33]})
    assert r.status_code == 400, r.text
    r = c.post(f"/admin/saved-replies?account_id={A}", json={"text": "x", "notes": "x" * 257})
    assert r.status_code == 422, r.text


def case_tag_rename_delete_add_and_remove_from_one_script():
    c = fx.login_owner("agency_a_owner")
    _wipe(c)
    a = _new(c, title="a", tags=["Opener"])
    b = _new(c, title="b", tags=["Opener", "VIP"])
    z = _new(c, title="z")
    r = _relabel(c, kind="tag", **{"from": "Opener"}, to="VIP")
    assert r.status_code == 200 and r.json() == {"updated": 2}, r.text
    tags = {x["title"]: x["tags"] for x in _list(c)}
    assert tags == {"a": ["VIP"], "b": ["VIP"], "z": []}, tags
    assert _relabel(c, kind="tag", to="Night", ids=[a["id"], z["id"]]).json() == {"updated": 2}
    assert _relabel(c, kind="tag", **{"from": "VIP"}, ids=[b["id"]]).json() == {"updated": 1}
    tags = {x["title"]: x["tags"] for x in _list(c)}
    assert tags == {"a": ["VIP", "Night"], "b": [], "z": ["Night"]}, tags
    assert _relabel(c, kind="tag", **{"from": "Night"}).json() == {"updated": 2}
    assert {x["title"]: x["tags"] for x in _list(c)} == {"a": ["VIP"], "b": [], "z": []}
    assert _relabel(c, kind="tag", to="x").status_code == 400
    assert _relabel(c, kind="tag", to="x" * 33, ids=[a["id"]]).status_code == 400


def case_sequence_rename_clash_and_ungroup():
    c = fx.login_owner("agency_a_owner")
    _wipe(c)
    _new(c, title="s1", script_id="New Sub", script_step=1)
    _new(c, title="s2", script_id="New Sub", script_step=2)
    _new(c, title="o1", script_id="Other", script_step=1)
    assert _relabel(c, kind="sequence", **{"from": "New Sub"}, to="Other").status_code == 409
    assert _relabel(c, kind="sequence", **{"from": "New Sub"}, to="Welcome").json() == {"updated": 2}
    seq = {x["title"]: (x["script_id"], x["script_step"]) for x in _list(c)}
    assert seq == {"s1": ("Welcome", 1), "s2": ("Welcome", 2), "o1": ("Other", 1)}, seq
    assert _relabel(c, kind="sequence", **{"from": "Welcome"}).json() == {"updated": 2}
    seq = {x["title"]: (x["script_id"], x["script_step"]) for x in _list(c)}
    assert seq == {"s1": (None, None), "s2": (None, None), "o1": ("Other", 1)}, seq
    assert _relabel(c, kind="sequence", to="x", ids=[1]).status_code == 400


def case_relabel_is_scoped_to_the_owners_creator():
    _new(fx.login_owner("agency_a_owner"), tags=["VIP"])
    owner_b = fx.login_owner("agency_b_owner")
    r = _relabel(owner_b, acc=A, kind="tag", **{"from": "VIP"})
    assert r.status_code == 403, r.text
    assert _relabel(owner_b, acc=B, kind="tag", **{"from": "VIP"}).json() == {"updated": 0}
    c = fx.login_owner("agency_a_owner")
    assert any(x["tags"] == ["VIP"] for x in _list(c)), "B's relabel touched A's scripts"


def case_text_is_sanitized_and_capped_at_6500_plain_characters():
    c = fx.login_owner("agency_a_owner")
    hostile = '<p><strong onclick="x">hi</strong><img src=x onerror=1><script>y</script></p><ul><li>a</li></ul>'
    clean = "<p><strong>hi</strong></p><p>a</p>"
    row = _new(c, title="rich", text=hostile)
    assert row["text"] == clean, row["text"]
    r = c.put(f"/admin/saved-replies/{row['id']}", json={"text": "<b>x</b><img src=y>"})
    assert r.status_code == 200 and r.json()["text"] == "<p><strong>x</strong></p>", r.text
    assert next(x for x in _list(c) if x["id"] == row["id"])["text"] == "<p><strong>x</strong></p>"
    r = c.put(f"/admin/saved-replies/{row['id']}", json={"text": "<b>x</b><iframe>y</iframe>"})
    assert r.status_code == 200 and r.json()["text"] == "<p>&lt;b&gt;x&lt;/b&gt;&lt;iframe&gt;y&lt;/iframe&gt;</p>", r.text
    span = '<span class="m-editor-fs__l m-editor-fc__blue-1">'
    edge = "<p>" + (span + "x" * 100 + "</span>") * 65 + "</p>"
    assert _new(c, title="edge", text=edge)["text"] == edge
    for body in ({"text": "y" * 6501}, {"text": "<p>" + "y" * 6501 + "</p>"}):
        r = c.post(f"/admin/saved-replies?account_id={A}", json=body)
        assert r.status_code == 400 and "6500" in r.text, r.text
        r = c.put(f"/admin/saved-replies/{row['id']}", json=body)
        assert r.status_code == 400, r.text
    plain = "hey <3 & <VIP20>"
    assert _new(c, title="plain", text=plain)["text"] == plain
    for text in ("<img src=x>", "<font color=red></font>"):
        r = c.post(f"/admin/saved-replies?account_id={A}", json={"text": text})
        assert r.status_code == 400 and "nothing a fan would read" in r.text, (text, r.text)
        assert c.put(f"/admin/saved-replies/{row['id']}", json={"text": text}).status_code == 400
    assert _new(c, title="media", text="<p></p>")["text"] == "<p></p>" and _new(c, title="m2", text="")["text"] == ""
    import server
    from of_rich_text import MARKUP_MAX
    assert server.SendMessageBody.model_fields["text"].metadata[0].max_length == MARKUP_MAX
    big = "<p>" + "<b>" * (MARKUP_MAX // 3) + "</p>"
    for r in (c.post(f"/admin/saved-replies?account_id={A}", json={"text": big}),
              c.put(f"/admin/saved-replies/{row['id']}", json={"text": big})):
        assert r.status_code == 422 and "text" in r.text, r.text[:200]


def case_concurrent_list_reads_share_a_run_and_still_check_ownership_each():
    import asyncio

    import httpx
    import relay_coalesce
    import server
    c = fx.login_owner("agency_a_owner")
    _new(c, title="concurrent", tags=["NS"])
    want = _list(c)
    relay_coalesce.reset_for_tests()

    async def burst():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://testserver",
                                     cookies=dict(c.cookies)) as a, \
                httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://testserver",
                                  cookies=dict(fx.login_owner("agency_b_owner").cookies)) as b:
            return await asyncio.gather(*[a.get(f"/admin/saved-replies?account_id={A}") for _ in range(20)],
                                        b.get(f"/admin/saved-replies?account_id={A}"))

    *mine, theirs = asyncio.run(burst())
    assert [r.status_code for r in mine] == [200] * 20 and {r.text for r in mine} == {mine[0].text}
    assert mine[0].json()["list"] == want, "a coalesced read differs from a lone one"
    assert theirs.status_code == 403, theirs.text
    st = relay_coalesce.stats()
    runs, shared = st["first_calls"].get("saved_replies_list", 0), st["coalesced_hits"].get("saved_replies_list", 0)
    assert runs + shared == 20 and runs < 20, f"20 concurrent reads: {runs} DB reads, {shared} shared"
    _new(c, title="after the burst")
    assert any(x["title"] == "after the burst" for x in _list(c))


_harness.run(
    case_text_is_sanitized_and_capped_at_6500_plain_characters,
    case_tags_and_notes_round_trip_and_a_put_without_them_keeps_them,
    case_a_tag_over_32_or_notes_over_256_characters_is_rejected,
    case_tag_rename_delete_add_and_remove_from_one_script,
    case_sequence_rename_clash_and_ungroup,
    case_relabel_is_scoped_to_the_owners_creator,
    case_concurrent_list_reads_share_a_run_and_still_check_ownership_each,
)
