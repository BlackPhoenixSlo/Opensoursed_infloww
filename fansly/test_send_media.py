from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

from fansly_client import FanslyAPIError, FanslySession
from fansly_shim import FanslyShimClient, check_sendable, of_messages_page

HERE = Path(__file__).resolve().parent
DEFAULT_HAR = HERE / "vault and send.har"
US = "700237824869654528"      # our account, in the capture
FAN = "900108301660352512"     # the recipient, in the capture
GROUP = "900234531911344131"
MEDIA = "900290681742675973"


def _captured(har_path: Path, path: str) -> list[dict]:
    har = json.loads(har_path.read_text())
    out = []
    for entry in har["log"]["entries"]:
        req = entry["request"]
        if req["method"] != "POST" or urlsplit(req["url"]).path != path:
            continue
        text = (req.get("postData") or {}).get("text")
        if text:
            out.append(json.loads(text))
    return out


def _session_doing(put_fn):
    class _Session:
        proxies: dict = {}

        def put(self, url, data=None, headers=None, timeout=None):
            return put_fn(url, data=data, headers=headers, timeout=timeout)

        def close(self):
            pass

    return _Session


def _client() -> tuple[FanslyShimClient, list]:
    c = FanslyShimClient(FanslySession({
        "accountId": US, "token": "t", "check_key": "k", "device_id": "d",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    }))
    calls: list[tuple[str, str, object]] = []

    def fake(method, path, *, params=None, json_body=None, **_kw):
        calls.append((method, path, json_body))
        if path == "/media" and method == "GET":
            return [{"id": MEDIA, "type": 1, "status": 1, "mimetype": "image/jpeg",
                     "locations": [], "variants": []}]
        if path == "/account/media":
            return [{"id": f"ACCTMEDIA{len(calls)}"}]
        if path == "/message":
            return {"id": "1", "groupId": GROUP, "senderId": US,
                    "content": "", "createdAt": 1.0, "attachments": []}
        raise AssertionError(f"unexpected call {method} {path}")

    c._request = fake
    c._known_group_ids.add(GROUP)
    c._group_to_fan[GROUP] = FAN
    return c, calls


def main(argv: list[str]) -> int:
    har = Path(argv[1]) if len(argv) > 1 else DEFAULT_HAR
    fails: list[str] = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    if har.exists():
        grants = _captured(har, "/api/v1/account/media")
        msgs = _captured(har, "/api/v1/message")
        check(grants and msgs, "no /account/media or /message POSTs in the HAR")
        free = next((g[0] for g in grants
                     if not g[0]["permissions"]["permissionFlags"]), None)
        paid = next((g[0] for g in grants
                     if g[0]["permissions"]["permissionFlags"]), None)
        check(free is not None, "HAR has no FREE grant to compare against")
        check(paid is not None, "HAR has no PAID grant to compare against")
    else:
        print(f"note: {har.name} absent — comparing against inlined constants",
              file=sys.stderr)
        free = paid = None

    c, calls = _client()
    c.send_message(GROUP, text="", media_files=[MEDIA])
    order = [p for _, p, _ in calls if p != "/media"]
    check(order == ["/account/media", "/message"],
          f"free send should be grant-then-message, got {order}")
    grant = calls[0][2][0]
    check(grant["mediaId"] == MEDIA, "grant must carry the vault mediaId")
    check(grant["permissionFlags"] == 8, "envelope permissionFlags must be 8")
    check(grant["price"] == 0, "top-level grant price is always 0")
    check(grant["permissions"]["permissionFlags"] == [],
          "a free grant carries NO permission flags")
    check(sorted(w["accountId"] for w in grant["whitelist"]) == sorted([US, FAN]),
          "whitelist must name both us and the recipient")
    att = next(b for _, p_, b in calls if p_ == "/message")["attachments"]
    check(len(att) == 1 and att[0]["contentId"] == "ACCTMEDIA1",
          "message must attach the ACCOUNTMEDIA id, never the raw mediaId")
    check(att[0]["contentId"] != MEDIA,
          "attaching the raw mediaId is accepted by Fansly and delivers a dead "
          "attachment — this is the regression this test exists for")
    check(att[0]["contentType"] == 1 and att[0]["pos"] == 0,
          "attachment must be contentType 1 at pos 0")
    if free is not None:
        check(grant.keys() == free.keys(),
              f"free grant keys drifted from the capture: "
              f"{set(grant) ^ set(free)}")

    c, calls = _client()
    c.send_message(GROUP, text="", media_files=[MEDIA], price=101)
    pf = calls[0][2][0]["permissions"]["permissionFlags"]
    check(len(pf) == 1, "a paid grant carries exactly one permission flag")
    # Fansly prices in 1/1000 dollars, on the grant (a doubly-encoded blob), not the message
    check(pf[0]["price"] == 101000,
          f"$101 must wire as 101000 (1 USD = 1000), got {pf[0]['price']}")
    check(pf[0]["type"] == 0 and pf[0]["flags"] == 3,
          "captured paid grant is type 0 / flags 3")
    check(pf[0]["metadata"] == '{"1":"{\\"price\\":101000}"}',
          f"metadata is DOUBLY json-encoded; got {pf[0]['metadata']!r}")
    check(calls[0][2][0]["price"] == 0,
          "the top-level price stays 0 even on a PPV — the price is in the flag")
    if paid is not None:
        check(pf[0] == {k: paid["permissions"]["permissionFlags"][0][k]
                        for k in pf[0]},
              "paid permission flag drifted from the captured browser body")

    c, calls = _client()
    c.send_message(GROUP, text="", media_files=[MEDIA], price=24.99)
    check(calls[0][2][0]["permissions"]["permissionFlags"][0]["price"] == 24990,
          "$24.99 must wire as 24990")

    c, calls = _client()
    c.send_message(GROUP, text="", media_files=[MEDIA, MEDIA])
    check([p for _, p, _ in calls if p != "/media"]
          == ["/account/media", "/account/media", "/message"],
          "each attachment needs its OWN grant")
    att = next(b for _, p_, b in calls if p_ == "/message")["attachments"]
    check([a["pos"] for a in att] == [0, 1], "attachments must be pos-ordered")
    check([a["contentId"] for a in att] == ["ACCTMEDIA1", "ACCTMEDIA2"],
          "each attachment must carry its own envelope id, in order")

    c, calls = _client()
    c.send_message(GROUP, text="", media_files=["AAA", "BBB", "CCC"],
                   price=20, previews=["AAA"])
    grants = [b[0] for _, p_, b in calls if p_ == "/account/media"]
    check(len(grants) == 3, "one grant per attachment on a teaser send")
    by_media = {g["mediaId"]: g["permissions"]["permissionFlags"] for g in grants}
    check(by_media["AAA"] == [], "the previewed media must get a FREE grant")
    check(by_media["BBB"] and by_media["CCC"],
          "non-preview attachments must stay PRICED")
    check(by_media["BBB"][0]["price"] == 20000, "$20 must wire as 20000")
    check(all(g["previewId"] is None for g in grants),
          "previewId stays null — the browser never set it; previews are "
          "expressed as free sibling grants, not as a blurred stand-in")

    c, calls = _client()
    c.send_message(GROUP, text="", media_files=["AAA", "BBB"], previews=["AAA"])
    grants = [b[0] for _, p_, b in calls if p_ == "/account/media"]
    check(all(g["permissions"]["permissionFlags"] == [] for g in grants),
          "every grant on a free send is free, previews or not")

    for kwargs, why in [
        ({"price": 5},
         "a paid send with no media (the tease would go out FREE)"),
        ({"media_files": [{"processId": "x", "host": "h"}]},
         "an OF fresh-upload claim (only upload_media's vault id is sendable)"),
        ({"media_files": [MEDIA], "locked_text": True},
         "locked_text (Fansly always shows text)"),
        ({"media_files": ["AAA", "BBB"], "price": 10,
          "previews": ["AAA", "BBB"]},
         "a paid send whose every attachment is a free preview (the fan would "
         "pay nothing and get everything while the UI reports a sale)"),
    ]:
        c, _ = _client()
        try:
            c.send_message(GROUP, text="hi", **kwargs)
            fails.append(f"should have refused {why}")
        except FanslyAPIError:
            pass

    for kwargs, should_pass, label in [
        ({"media_files": [], "price": 0}, True, "plain text"),
        ({"media_files": [1, 2], "price": 0}, True, "free media"),
        ({"media_files": [1, 2], "price": 0, "previews": [1]}, True,
         "previews on a FREE send are a harmless no-op"),
        ({"media_files": [1, 2], "price": 20}, True, "paid media, none free"),
        ({"media_files": [1, 2], "price": 20, "previews": [1]}, True,
         "paid media with a 1-of-2 teaser"),
        ({"media_files": [1, 2], "price": 20, "previews": [9]}, True,
         "a preview id not among the attachments is ignored, not fatal"),
        ({"media_files": [], "price": 20}, False, "paid with no media"),
        ({"media_files": [1, 2], "price": 20, "previews": [1, 2]}, False,
         "paid with EVERY attachment previewed"),
        ({"media_files": [{"processId": "x", "host": "h"}], "price": 0}, False,
         "an OF fresh-upload claim (processId/host, no vault id)"),
        ({"media_files": [{"vault_id": MEDIA, "send_with": [MEDIA]}],
          "price": 0}, True,
         "a fresh Fansly upload result (dict naming a vault id) — the "
         "refusal that used to block every fresh upload is gone"),
        ({"media_files": [{"mediaId": MEDIA}], "price": 20}, True,
         "a paid send of a dict-shaped vault id"),
        ({"media_files": [{"mediaId": MEDIA}], "price": 20,
          "previews": [MEDIA]}, False,
         "paid + every attachment previewed, even when dict-shaped"),
    ]:
        try:
            check_sendable(**kwargs)
            passed = True
        except FanslyAPIError:
            passed = False
        check(passed is should_pass,
              f"check_sendable {'allows' if should_pass else 'refuses'}: {label}")

    c, calls = _client()
    c.send_message(GROUP, text="just words")
    check([p for _, p, _ in calls] == ["/message"],
          "a text-only send must not mint a grant, nor look media up")
    check(calls[0][2]["attachments"] == [],
          "a text-only send must carry no attachments")

    c, calls = _client()
    sent = c.send_message(GROUP, text="", media_files=[MEDIA], price=101)
    check(sent["price"] == 101.0,
          f"send response reports the price charged (got {sent['price']})")
    check(sent["isFree"] is False, "a paid send is not reported isFree")
    check(len(sent.get("media") or []) == 1,
          "send response carries the media, so the sent tile does not vanish")
    check(sent.get("mediaCount") == 1, "mediaCount matches")

    c, calls = _client()
    sent = c.send_message(GROUP, text="just words")
    check(not sent.get("media"), "a text-only send response carries no media")
    check(sent["price"] == 0 and sent["isFree"] is True,
          "a free send is reported free")

    def _grant(gid, amount):
        flags = ([] if not amount else
                 [{"type": 0, "flags": 11, "price": amount,
                   "metadata": '{"1":"{\\"price\\":%d}"}' % amount}])
        return {"id": gid, "accountId": US, "mediaId": MEDIA,
                "permissions": {"permissionFlags": flags},
                "media": {"id": MEDIA, "type": 1, "status": 1,
                          "mimetype": "image/jpeg", "locations": [],
                          "variants": []}}

    payload = {
        "messages": [
            {"id": "m_paid", "senderId": US, "content": "", "createdAt": 1.0,
             "attachments": [{"contentId": "g_paid", "contentType": 1, "pos": 0}]},
            {"id": "m_free", "senderId": US, "content": "", "createdAt": 1.0,
             "attachments": [{"contentId": "g_free", "contentType": 1, "pos": 0}]},
            {"id": "m_teaser", "senderId": US, "content": "", "createdAt": 1.0,
             "attachments": [{"contentId": "g_free", "contentType": 1, "pos": 0},
                             {"contentId": "g_paid", "contentType": 1, "pos": 1}]},
            {"id": "m_text", "senderId": US, "content": "hi", "createdAt": 1.0,
             "attachments": []},
            {"id": "m_two_paid", "senderId": US, "content": "", "createdAt": 1.0,
             "attachments": [{"contentId": "g_paid", "contentType": 1, "pos": 0},
                             {"contentId": "g_paid2", "contentType": 1, "pos": 1}]},
        ],
        "accountMedia": [_grant("g_paid", 101000), _grant("g_free", 0),
                         _grant("g_paid2", 101000)],
        "accountMediaBundles": [],
    }
    page = {m["id"]: m for m in of_messages_page(payload, account_id=US, limit=10)["list"]}
    check(page["m_paid"]["price"] == 101.0,
          f"a 101000-unit grant reads back as $101.00 (got {page['m_paid']['price']})")
    check(page["m_paid"]["isFree"] is False, "a priced message is not isFree")
    # isOpened was hardcoded True: a priced message must not read as unlocked until a purchase is proven
    check(page["m_paid"]["isOpened"] is False,
          "a PPV is NOT 'opened' just because we sent it (the false-unlocked bug)")
    check(page["m_free"]["isOpened"] is True,
          "a free message stays opened — isPPV is false so no chip renders")
    for mid in ("m_paid", "m_two_paid", "m_teaser"):
        row = page[mid]
        unlocked = (row["price"] or 0) > 0 and (row.get("isOpened") or row.get("isPaid"))
        check(not unlocked, f"{mid} renders the 🔒 chip, never '✓ unlocked'")
    check(page["m_free"]["price"] == 0 and page["m_free"]["isFree"] is True,
          "a free grant stays free")
    check(page["m_text"]["price"] == 0, "a text-only message stays free")
    check(page["m_two_paid"]["price"] == 101.0,
          f"a $101 set of TWO priced grants is a $101 message, not $202 — the "
          f"fan unlocks the message once (got {page['m_two_paid']['price']})")
    check(page["m_teaser"]["previews"] == ["g_free"],
          f"the free grant beside a paid one is reported as the teaser "
          f"(got {page['m_teaser']['previews']})")
    check(page["m_two_paid"]["previews"] == [],
          "a fully-locked set has no teaser")
    check(page["m_free"]["previews"] == [],
          "a FREE message has no teaser — nothing is locked to contrast with")
    check(page["m_text"]["previews"] == [], "a text-only message has no teaser")
    teaser_ids = page["m_teaser"]["previews"]
    check(bool(teaser_ids) and teaser_ids[0] != MEDIA,
          "previews carry GRANT ids (what of_media puts in tile.id), not vault mediaIds")
    check(page["m_teaser"]["price"] == 101.0,
          f"a free teaser beside a $101 grant is a $101 message, not $0 or $202 "
          f"(got {page['m_teaser']['price']})")

    from fansly_shim import of_message
    reply_to = "900511561790234625"
    r = of_message({"id": "9", "senderId": US, "content": "", "createdAt": 1.0,
                    "attachments": [], "inReplyTo": reply_to}, account_id=US)
    # must be a string: adjacent snowflakes collapse to the same JS float
    check("replyToMessageId" in r,
          "of_message emits replyToMessageId (the name OFMessage declares)")
    check("replyOnMessageId" not in r,
          "the old replyOnMessageId name is gone — nothing in the app read it")
    check(r.get("replyToMessageId") == reply_to,
          f"reply id is the exact snowflake STRING (got {r.get('replyToMessageId')!r})")
    check(isinstance(r.get("replyToMessageId"), str), "reply id is a str, not an int")
    # the collapse this guards against, asserted rather than asserted-about
    check(float(reply_to) == float("900511561790234626"),
          "two adjacent snowflakes DO collapse under float — the reason the "
          "MessageList id map had to become string-keyed")
    plain = of_message({"id": "9", "senderId": US, "content": "", "createdAt": 1.0,
                        "attachments": []}, account_id=US)
    check(plain.get("replyToMessageId") is None,
          "a non-reply carries a null reply id, not a stray value")

    c, calls = _client()
    c.send_message(GROUP, text="", media_files=[{"mediaId": MEDIA}])
    grants = [b[0] for _, p_, b in calls if p_ == "/account/media"]
    check(len(grants) == 1 and grants[0]["mediaId"] == MEDIA,
          "a {mediaId} dict mints one grant for exactly that vault id")

    import tempfile
    from fansly_client import MEDIA_BASE
    UPLOAD_ID = "900551936026308608"
    VAULT_ID = "900551952321183744"
    S3_ETAG = '"93bf238fb9eff41e29ff1f73af3f5e60"'

    def _upload_client(*, part_size: int, n_parts: int, statuses: list[int]):
        c, calls = _client()
        puts: list[tuple[str, bytes, dict]] = []
        polls = iter(statuses)

        def fake(method, path, *, params=None, json_body=None, base=None, **_kw):
            calls.append((method, path, json_body, base))
            if path == "/media/upload/create":
                return {"id": UPLOAD_ID, "type": 1, "partSize": part_size,
                        "status": 2, "mimeType": json_body["mimeType"],
                        "parts": [{"index": i, "uploadUrl": f"https://s3/{i}"}
                                  for i in range(n_parts)]}
            if path == "/media/upload/complete":
                return {"id": UPLOAD_ID, "status": 3, "mediaId": None}
            if path == f"/media/upload/{UPLOAD_ID}":
                st = next(polls)
                return {"id": UPLOAD_ID, "status": st, "mimeType": "image/png",
                        "bucketKey": f"{US}/{UPLOAD_ID}",
                        "mediaId": VAULT_ID if st == 6 else None}
            if path == "/media" and method == "GET":
                return [{"id": VAULT_ID, "type": 1, "status": 1,
                         "mimetype": "image/jpeg", "width": 4, "height": 4,
                         "locations": [], "variants": []}]
            raise AssertionError(f"unexpected call {method} {path}")

        class _Resp:
            ok = True
            status_code = 200
            text = ""
            headers = {"ETag": S3_ETAG}

        lock = threading.Lock()

        def put(url, data=None, headers=None, timeout=None):
            with lock:
                puts.append((url, data, headers or {}))
            return _Resp()

        c._request = fake
        c._upload_session = _session_doing(put)

        def _no(*_a, **_kw):
            raise AssertionError(
                "a part went through the client's SHARED http session")
        c.http.put = _no
        return c, calls, puts

    with tempfile.TemporaryDirectory() as td:
        img = Path(td) / "zz-test.png"
        img.write_bytes(b"\x89PNG" + b"\0" * 175)
        c, calls, puts = _upload_client(part_size=20971520, n_parts=1,
                                        statuses=[3, 4, 5, 6])
        res = c.upload_media(img, poll_interval_s=0)

        create = next(b for m, p_, b, base in calls if p_ == "/media/upload/create")
        check(all(base == MEDIA_BASE for _, p_, _, base in calls
                  if p_.startswith("/media/upload")),
              "every upload step goes to mediav2, not apiv3")
        check(create == {
            "fileSize": 179, "mimeType": "image/png", "fileName": "zz-test.png",
            "uploadFormData": {"formInputs": [
                {"type": 1001, "value": "false"}, {"type": 1002, "value": "false"},
                {"type": 1003, "value": ""}, {"type": 1004, "value": ""},
                {"type": 1005, "value": '""'}]}},
            f"upload/create body matches the capture (got {create})")
        check(len(puts) == 1 and puts[0][0] == "https://s3/0"
              and puts[0][1] == img.read_bytes(),
              "one part -> one PUT of the whole file to its presigned url")
        check("authorization" not in {k.lower() for k in puts[0][2]}
              and "fansly-client-check" not in {k.lower() for k in puts[0][2]},
              "the S3 PUT carries no Fansly auth (the presign IS the auth)")
        complete = next(b for m, p_, b, _ in calls if p_ == "/media/upload/complete")
        check(complete == {"id": UPLOAD_ID, "type": 1, "partSize": 20971520,
                           "status": 0, "parts": [{"index": 0, "eTag": S3_ETAG}],
                           "waitForComplete": 0},
              f"upload/complete body matches the capture (got {complete})")
        check(complete["parts"][0]["eTag"].startswith('"'),
              "the eTag is echoed quoted, exactly as S3 returned it")
        n_polls = sum(1 for _, p_, _, _ in calls if p_ == f"/media/upload/{UPLOAD_ID}")
        check(n_polls == 4, f"polled until status 6 (got {n_polls} polls)")
        check(res["vault_id"] == VAULT_ID and res["send_with"] == [VAULT_ID],
              "returns the assigned vault mediaId, not the upload id")
        check(isinstance(res["vault_id"], str), "vault id is a big-int-safe str")
        check(res["ready"] is True and res["deduped"] is False, "OF result shape")
        check(res["media"].get("id") == VAULT_ID
              and res["stored_mime"] == "image/png",
              "readback carries what the vault stored")
        c2, calls2 = _client()
        c2.send_message(GROUP, text="", media_files=res["send_with"])
        check([b[0]["mediaId"] for _, p_, b in calls2 if p_ == "/account/media"]
              == [VAULT_ID], "upload -> send_with -> grant path, no new logic")

        big = Path(td) / "zz-big.bin"
        big.write_bytes(bytes(range(256)) * 10)
        c, calls, puts = _upload_client(part_size=1000, n_parts=3, statuses=[6])
        res = c.upload_media(big, poll_interval_s=0)
        by_url = {u: d for u, d, _h in puts}
        raw = big.read_bytes()
        check(by_url == {"https://s3/0": raw[0:1000],
                         "https://s3/1": raw[1000:2000],
                         "https://s3/2": raw[2000:2560]},
              "a >partSize file is sliced by index into every part")
        complete = next(b for m, p_, b, _ in calls if p_ == "/media/upload/complete")
        check(complete["parts"] == [{"index": i, "eTag": S3_ETAG} for i in range(3)],
              "complete echoes every part's ETag by index")

        c, calls, puts = _upload_client(part_size=1000, n_parts=3, statuses=[6])
        c.upload_media(big, poll_interval_s=0)
        check(sum(len(d) for _, d, _h in puts) == big.stat().st_size,
              "the parts together cover the file exactly once")

        c, calls, puts = _upload_client(part_size=1000, n_parts=3, statuses=[6])
        blown = {"n": 0}
        real_put = c._upload_session().put

        def _blip_once_on_part_1(url, data=None, headers=None, timeout=None):
            if url.endswith("/1") and blown["n"] < 2:
                blown["n"] += 1
                raise OSError("proxy CONNECT blip")
            return real_put(url, data=data, headers=headers, timeout=timeout)

        c._upload_session = _session_doing(_blip_once_on_part_1)
        res = c.upload_media(big, poll_interval_s=0)
        check(blown["n"] == 2 and res["vault_id"] == VAULT_ID,
              "a transport blip on one part is retried, not fatal")

        c, calls, puts = _upload_client(part_size=1000, n_parts=3, statuses=[6])

        refused: list[str] = []

        def _refuse(url, data=None, headers=None, timeout=None):
            refused.append(url)

            class R:
                ok = False
                status_code = 403
                text = "expired presign"
                headers: dict = {}
            return R()

        c._upload_session = _session_doing(_refuse)
        try:
            c.upload_media(big, poll_interval_s=0)
            fails.append("a 403 from S3 must fail the upload, not be swallowed")
        except FanslyAPIError:
            pass
        check(len(refused) == 3,
              "a real S3 refusal is re-raised at once, never retried per part "
              f"(got {len(refused)} PUTs for 3 parts)")
        check(not any(p_ == "/media/upload/complete" for _, p_, _, _ in calls),
              "a failed part must never reach upload/complete")
        c, calls, puts = _upload_client(part_size=1000, n_parts=1, statuses=[6])
        try:
            c.upload_media(big, poll_interval_s=0)
            fails.append("a part list that can't hold the file must be refused")
        except FanslyAPIError:
            pass
        check(not puts, "…and refused BEFORE any byte was PUT")
        c, calls, puts = _upload_client(part_size=20971520, n_parts=1,
                                        statuses=[3] * 50)
        try:
            c.upload_media(img, poll_interval_s=0, poll_timeout_s=0)
            fails.append("an upload that never reaches status 6 must raise")
        except FanslyAPIError:
            pass

    for f in fails:
        print(f"  FAIL {f}", file=sys.stderr)
    if fails:
        print(f"{len(fails)} check(s) failed", file=sys.stderr)
        return 1
    print("all send-media checks passed — grant-then-attach matches the capture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
