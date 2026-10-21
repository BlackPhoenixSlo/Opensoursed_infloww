"""
Pin the Fansly vault-FOLDER write bodies, field by field. Offline.

These six methods are how the vault panel creates/edits albums, and every one
of them is a POST to its own path — Fansly has no PATCH or DELETE here, so a
signature copied from OF's `/vault/lists` would compile and silently 404. The
routes were recovered from the web bundle and verified live once; this test is
what keeps them from drifting afterwards.

What it actually guards, beyond "it calls something":
  * create sends id/accountId null and type 0 (the SERVER assigns all three)
  * rename RE-READS the album first — /vault/albums/edit takes the whole object
    back, so a blind post would blank the description
  * every id crossing the wire is a STRING (snowflakes are above 2^53)
  * sort_vault_lists reports FAILURE rather than pretending a name-sort ran

    ../venv/bin/python test_vault_folders.py
"""
from __future__ import annotations

import sys

import fansly_shim as shim
import fansly_vault

ACCOUNT_ID = "700237824869654528"
ALBUM = "900733426807169025"          # 18 digits: > 2**53
MEDIA = "900611155333562368"

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        failures.append(label)


class FakeClient(shim.FanslyShimClient):
    """Records every _request instead of making one. Replies are keyed by
    (method, path) so a method that fires the WRONG route gets None back and
    fails loudly rather than reading a neighbour's canned reply."""

    def __init__(self, replies=None):
        self.calls: list[tuple] = []
        self.replies = replies or {}

        class _S:
            account_id = ACCOUNT_ID
        self.session = _S()

    def _request(self, method, path, *, params=None, json_body=None, **kw):
        self.calls.append((method, path, params, json_body))
        return self.replies.get((method, path))


def body_of(c: FakeClient, path: str) -> dict:
    for method, p, _params, jb in c.calls:
        if p == path:
            return jb or {}
    return {}


print("1. create_vault_list")
c = FakeClient({("POST", "/vault/albums"): {"id": 900733426807169025, "title": "n"}})
out = c.create_vault_list("n")
b = body_of(c, "/vault/albums")
check("POSTs /vault/albums", ("POST", "/vault/albums") in [(m, p) for m, p, _, _ in c.calls])
check("id is null (server assigns)", b.get("id", "unset") is None, repr(b.get("id")))
check("accountId is null", b.get("accountId", "unset") is None, repr(b.get("accountId")))
check("type is 0", b.get("type") == 0, repr(b.get("type")))
check("title carries the name", b.get("title") == "n")
# The live server echoes the id as a JSON number; JS would lose the last digits
# unless we stringify it here.
check("returned id is a STRING", isinstance(out["id"], str), type(out["id"]).__name__)
check("returned id is exact", out["id"] == ALBUM, out["id"])
check("reported empty, not guessed", out["hasMedia"] is False)
# A created folder and a listed one must be ONE type to callers, or the panel
# ends up branching on where the row came from.
check("row shape matches vault_lists", set(out) == {
    "id", "type", "name", "hasMedia", "mediaCount",
    "photosCount", "videosCount", "gifsCount", "audiosCount",
}, str(sorted(out)))
# The counts are what the panel's folder subtitle is built from; a created
# folder reporting none of them rendered as "empty" either way, but callers
# would have had to branch on the missing keys.
check("created folder carries zeroed counts",
      all(out[k] == 0 for k in
          ("photosCount", "videosCount", "gifsCount", "audiosCount", "mediaCount")))

print("2. add_media_to_vault_list")
c = FakeClient({("POST", "/vault/albums/media"): [{"id": "1"}]})
out = c.add_media_to_vault_list(int(ALBUM), [int(MEDIA)])
b = body_of(c, "/vault/albums/media")
check("albumId is a string", isinstance(b.get("albumId"), str))
check("albumId is exact", b.get("albumId") == ALBUM, str(b.get("albumId")))
check("mediaIds are strings", all(isinstance(m, str) for m in b.get("mediaIds", [])))
check("mediaIds exact", b.get("mediaIds") == [MEDIA], str(b.get("mediaIds")))
check("counts the rows created", out["added"] == 1, str(out))

print("3. add with no ids makes NO call")
c = FakeClient()
out = c.add_media_to_vault_list(ALBUM, [])
check("no request fired", c.calls == [], str(c.calls))
check("still reports success", out == {"success": True, "added": 0}, str(out))

print("4. remove_media_from_vault_list")
c = FakeClient({("POST", "/vault/albums/media/delete"): [{"mediaId": MEDIA}]})
out = c.remove_media_from_vault_list(ALBUM, [MEDIA])
b = body_of(c, "/vault/albums/media/delete")
check("hits /media/delete, not /media", b.get("albumId") == ALBUM and b.get("mediaIds") == [MEDIA])
check("counts removals", out["removed"] == 1)

print("5. rename_vault_list re-reads before editing")
c = FakeClient({
    ("GET", "/vault/albums"): [
        {"id": ALBUM, "title": "old", "description": "KEEP ME", "type": 7},
        {"id": "999", "title": "other", "description": "not this one", "type": 3},
    ],
    ("POST", "/vault/albums/edit"): {"id": ALBUM, "title": "new"},
})
out = c.rename_vault_list(ALBUM, "new")
paths = [p for _m, p, _pa, _b in c.calls]
check("GETs /vault/albums first", paths[0] == "/vault/albums", str(paths))
check("then POSTs /vault/albums/edit", paths[1] == "/vault/albums/edit", str(paths))
b = body_of(c, "/vault/albums/edit")
check("title updated", b.get("title") == "new")
# The whole object goes back, so anything we fail to carry is BLANKED server-side.
check("description PRESERVED", b.get("description") == "KEEP ME", repr(b.get("description")))
check("type PRESERVED", b.get("type") == 7, repr(b.get("type")))
check("matched the right album", b.get("id") == ALBUM)
check("accountId is ours", b.get("accountId") == ACCOUNT_ID)
check("returned name", out["name"] == "new")

print("6. rename when the album is not in the listing")
c = FakeClient({("GET", "/vault/albums"): [], ("POST", "/vault/albums/edit"): {}})
out = c.rename_vault_list(ALBUM, "new")
b = body_of(c, "/vault/albums/edit")
check("still sends a valid body", b.get("title") == "new" and b.get("id") == ALBUM)
check("type falls back to 0, not None", b.get("type") == 0, repr(b.get("type")))
check("returns the requested name", out["name"] == "new")

print("7. delete_vault_list")
c = FakeClient({("POST", "/vault/albums/delete"): {"id": ALBUM}})
out = c.delete_vault_list(ALBUM, clear_media=True)
b = body_of(c, "/vault/albums/delete")
check("sends albumId only", b == {"albumId": ALBUM}, str(b))
# Fansly never deletes media with an album; accepting the flag and quietly
# doing the same thing is the honest behaviour, but it must not LOOK honoured.
check("clear_media not forwarded", "clearMedia" not in b)
check("reports success", out == {"success": True})

print("8. sort_vault_lists refuses rather than lying")
c = FakeClient()
out = c.sort_vault_lists("name", "asc")
check("fires no request", c.calls == [], str(c.calls))
check("success is False", out.get("success") is False, str(out))
check("says why", "unsupported" in out, str(out))

print("9. set_vault_lists_custom_order replays moves")
albums = [
    {"id": "A", "pos": 0}, {"id": "B", "pos": 1},
    {"id": "C", "pos": 2}, {"id": "D", "pos": 3},
]
c = FakeClient({("GET", "/vault/albums"): albums, ("POST", "/vault/albums/order"): None})
out = c.set_vault_lists_custom_order(["C", "A"])
moves = [b for m, p, _pa, b in c.calls if p == "/vault/albums/order"]
check("moved C to the front", moves and moves[0] == {"oldPos": 2, "newPos": 0}, str(moves))
# After C moves to 0 the list is C,A,B,D — A is already at index 1, so a second
# move would be a no-op the server still has to process.
check("no redundant move for A", len(moves) == 1, str(moves))
check("reports the count", out["moves"] == 1, str(out))

print("10. custom order ignores ids that are not ours")
c = FakeClient({("GET", "/vault/albums"): albums, ("POST", "/vault/albums/order"): None})
out = c.set_vault_lists_custom_order(["ZZZ"])
check("no moves fired", not [p for _m, p, _pa, _b in c.calls if p == "/vault/albums/order"])
check("reports zero", out["moves"] == 0, str(out))

print("11. every album read goes through the one canonical reader")
# The drift this guards: three call sites used to spell out GET /vault/albums
# by hand and two had already lost the accountId param the third sent. If a
# future edit re-inlines the GET, one of these two checks fails.
for label, call in (
    ("rename", lambda c: c.rename_vault_list(ALBUM, "x")),
    ("custom order", lambda c: c.set_vault_lists_custom_order([ALBUM])),
    ("vault_lists", lambda c: c.vault_lists(limit=50)),
):
    c = FakeClient({
        ("GET", "/vault/albums"): [{"id": ALBUM, "title": "t", "description": "d",
                                    "type": 7, "pos": 0, "itemCount": 1}],
        ("POST", "/vault/albums/edit"): {"id": ALBUM},
        ("POST", "/vault/albums/order"): None,
    })
    call(c)
    gets = [(pa or {}) for m, p, pa, _b in c.calls if (m, p) == ("GET", "/vault/albums")]
    check(f"{label}: sends accountId", gets and all("accountId" in g for g in gets), str(gets))
    check(f"{label}: reads albums once", len(gets) == 1, str(len(gets)))

print("12. _albums defends the shape once, for everyone")
c = FakeClient({("GET", "/vault/albums"): None})
check("None listing -> empty, no crash", c._albums() == [])
c = FakeClient({("GET", "/vault/albums"): [{"id": "B", "pos": 2}, {"id": "A", "pos": 1},
                                           {"no_id": 1}, "junk"]})
got = c._albums()
check("drops rows with no id and non-dicts", [a["id"] for a in got] == ["A", "B"], str(got))
check("position-ordered", [a["pos"] for a in got] == [1, 2], str(got))

print("13a. a folder holding media reports per-kind counts, not \"empty\"")
# The bug: vault_lists returned only {id,type,name,hasMedia}, and the panel's
# folder subtitle is built ONLY from photosCount/videosCount/gifsCount/
# audiosCount. With those absent, every folder rendered "empty" while its media
# sat right there in the grid. Counts come from the album's OWN media, because
# live `itemCount` is both stale (reported 1 for an album returning 2) and a
# single total with no per-kind split.
c = FakeClient({
    ("GET", "/vault/albums"): [{"id": ALBUM, "title": "Album 1", "type": None,
                                "pos": 0, "itemCount": 0}],
    ("GET", "/media/vault"): [{"id": "1", "type": 1}, {"id": "2", "type": 1},
                              {"id": "3", "type": 2}],
})
row = c.vault_lists(limit=50)["list"][0]
check("photos counted", row["photosCount"] == 2, str(row))
check("videos counted", row["videosCount"] == 1, str(row))
check("total counted", row["mediaCount"] == 3, str(row))
# itemCount said 0; the media say otherwise, and the media win.
check("hasMedia follows the media, not itemCount", row["hasMedia"] is True, str(row))
check("filters by albumId, never albumIds",
      [(pa or {}).get("albumId") for m, pth, pa, _b in c.calls
       if pth == "/media/vault"] == [ALBUM],
      str([pa for m, pth, pa, _b in c.calls if pth == "/media/vault"]))

print("13b. counting is paid for the PAGE, not the whole album list")
c = FakeClient({
    ("GET", "/vault/albums"): [{"id": str(i), "title": f"a{i}", "type": None,
                                "pos": i, "itemCount": 0} for i in range(10)],
    ("GET", "/media/vault"): [],
})
c.vault_lists(limit=2)
check("one media read per album on the page",
      len([1 for m, pth, _pa, _b in c.calls if pth == "/media/vault"]) == 2,
      str(len([1 for m, pth, _pa, _b in c.calls if pth == "/media/vault"])))

print("13c. an unreadable album degrades to empty instead of 500ing")
class Boom(FakeClient):
    def _request(self, method, path, *, params=None, json_body=None, **kw):
        if path == "/media/vault":
            raise RuntimeError("fansly said no")
        return super()._request(method, path, params=params, json_body=json_body, **kw)

c = Boom({("GET", "/vault/albums"): [{"id": ALBUM, "title": "t", "type": None,
                                      "pos": 0, "itemCount": 5}]})
row = c.vault_lists(limit=50)["list"][0]
check("still lists the folder", row["id"] == ALBUM)
check("counts zeroed, not guessed from itemCount", row["mediaCount"] == 0, str(row))

print("13d. vault media carry listStates so folder filtering works")
# Fansly raw media have NO album back-reference, so membership is assembled
# from the per-album reads. The mirror derives of_folder_ids from exactly this
# field and the panel filters a folder view through it — without it every item
# mirrored as belonging to nothing and picking a folder filtered nothing away.
c = FakeClient({
    ("GET", "/vault/albums"): [
        {"id": "A1", "title": "Album 1", "type": None, "pos": 0, "itemCount": 1},
        {"id": "B2", "title": None, "type": 5000, "pos": 1, "itemCount": 1},
    ],
    ("GET", "/media/vault"): [{"id": "1", "type": 1}],
})
item = c.vault_media(limit=50)["list"][0]
states = {ls["name"]: ls["type"] for ls in item["listStates"]}
check("names the custom album", states.get("Album 1") == "custom", str(states))
# A built-in mislabelled "custom" would make every item look like it lived in
# "Messages" too, and the mirror keeps only custom entries.
check("built-in is not labelled custom", states.get("Messages") == "builtin", str(states))

print("13e. the album sweep is cached, and every write drops it")
# Memoizing membership is what keeps a PAGINATED vault_media from re-sweeping
# every album per page (20 albums x 60 pages = 1200 reads for an answer that
# never changed). The risk it buys is staleness, so the invalidation is what
# actually needs pinning: a folder edit must be visible on the next read.
c = FakeClient({
    ("GET", "/vault/albums"): [{"id": ALBUM, "title": "t", "type": None,
                                "pos": 0, "itemCount": 1}],
    ("GET", "/media/vault"): [{"id": "1", "type": 1}],
    ("POST", "/vault/albums/media"): [{"id": "1"}],
})
def media_reads():
    return len([1 for _m, p_, _pa, _b in c.calls if p_ == "/media/vault"])
c.vault_lists(limit=50); first = media_reads()
c.vault_lists(limit=50)
check("second read is served from the cache", media_reads() == first, str(media_reads()))
c.add_media_to_vault_list(ALBUM, ["2"])
c.vault_lists(limit=50)
check("a membership write re-reads", media_reads() > first, str(media_reads()))

print("13f. counting a page never sweeps albums off the page")
# The whole reason the slice happens before the counting. A limit=2 page over
# 10 albums must cost 2 album reads, not 10.
c = FakeClient({
    ("GET", "/vault/albums"): [{"id": str(i), "title": f"a{i}", "type": None,
                                "pos": i, "itemCount": 0} for i in range(10)],
    ("GET", "/media/vault"): [],
})
c.vault_lists(limit=2)
check("one media read per album ON THE PAGE",
      len([1 for _m, p_, _pa, _b in c.calls if p_ == "/media/vault"]) == 2,
      str([1 for _m, p_, _pa, _b in c.calls if p_ == "/media/vault"]))
check("the album listing itself is read once",
      len([1 for _m, p_, _pa, _b in c.calls if p_ == "/vault/albums"]) == 1,
      str(len([1 for _m, p_, _pa, _b in c.calls if p_ == "/vault/albums"])))

print("13. the vault seam really is narrow")
# The whole point of splitting VaultMixin out: it needs `_request` + `session`
# and nothing else. Compose it with a bare object and every method must still
# work — if someone reaches for another client attribute, this stops them.
class BareVault(fansly_vault.VaultMixin):
    def __init__(self):
        self.calls = []
        class _S:
            account_id = ACCOUNT_ID
        self.session = _S()

    def _request(self, method, path, *, params=None, json_body=None, **kw):
        self.calls.append((method, path))
        return {"id": ALBUM, "title": "t"} if method == "POST" else [
            {"id": ALBUM, "title": "t", "description": "d", "type": 7,
             "pos": 0, "itemCount": 1}]

v = BareVault()
check("create off a bare mixin", v.create_vault_list("n")["id"] == ALBUM)
check("rename off a bare mixin", v.rename_vault_list(ALBUM, "n")["name"] == "t")
check("lists off a bare mixin", v.vault_lists(limit=5)["list"][0]["id"] == ALBUM)
# The seam is about what the mixin needs FROM THE CLIENT, not about it being
# stateless: `_albums_media` is its own memo (dropped on every album write) and
# is created lazily precisely so a bare compose still works.
check("no client attrs beyond _request/session",
      {"_request", "session", "calls"}.issuperset(
          {a for a in vars(v) if not a.startswith("_albums_")} | {"_request"}),
      str(sorted(vars(v))))

print()
if failures:
    print(f"FAILED {len(failures)}: {failures}")
    sys.exit(1)
print("all vault-folder write bodies pinned")
