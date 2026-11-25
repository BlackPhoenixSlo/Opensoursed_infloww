from __future__ import annotations

from typing import Any

_COUNT_KEYS = {"photo": "photosCount", "video": "videosCount",
               "gif": "gifsCount", "audio": "audiosCount"}

_EMPTY_COUNTS: dict[str, Any] = {
    **dict.fromkeys(_COUNT_KEYS.values(), 0), "mediaCount": 0, "hasMedia": False,
}


def _of_media(account_media: dict) -> dict:
    # late import: fansly_shim imports this module to build its client
    from fansly_shim import of_media
    return of_media(account_media)


class VaultMixin:


    def _vault_media_payload(self, *, album_id: str | None = None) -> list:
        params: dict[str, Any] = {"accountId": str(self.session.account_id)}
        if album_id:
            # albumId, not albumIds: albumIds is SILENTLY IGNORED and returns the whole library (verified live)
            params["albumId"] = str(album_id)
        out = self._request("GET", "/media/vault", params=params)
        return out if isinstance(out, list) else []


    _VAULT_ALBUM_NAMES = {
        # Literal enum from the web bundle. Do NOT add `1: "Posts"`: Posts is 1000; type 1 is a real custom album and the Posts tile is synthetic client-side.
        "38000": "All",
        "5000": "Messages",
        "1000": "Posts",
        "2007": "Purchases",
    }

    def _albums(self) -> list[dict]:
        albums = self._request(
            "GET", "/vault/albums",
            params={"accountId": str(self.session.account_id)},
        )
        rows = [a for a in (albums or []) if isinstance(a, dict) and a.get("id")]
        rows.sort(key=lambda a: a.get("pos") or 0)
        return rows

    def vault_lists(self, *, view: str = "main", limit: int = 10,
                    offset: int = 0, **_ignored: Any) -> dict:
        albums = self._albums()
        page_albums = albums[offset:offset + limit] if limit else albums
        page = [{**self._album_row(a), **self._album_counts(a)} for a in page_albums]
        return {"list": page, "hasMore": offset + len(page) < len(albums)}

    def _album_row(self, a: dict) -> dict:
        # title is null in the API; an unknown type is "custom" (Create returns type null, not 0); built-ins must be classified identically here and in listStates or the mirror misfiles items
        atype = str(a.get("type") or "")
        return {
            # STRING id: snowflakes exceed 2^53, a float coercion lands on a different album
            "id": str(a.get("id") or ""),
            "type": ("purchases" if atype == "2007"
                     else "builtin" if atype in self._VAULT_ALBUM_NAMES
                     else "custom"),
            "name": (a.get("title")
                     or self._VAULT_ALBUM_NAMES.get(atype)
                     or f"Album {atype}"),
        }

    def _album_contents(self, albums: list[dict]) -> dict[str, list[dict]]:
        # per-album cache: itemCount is stale and membership exists only as an albumId-filtered read; every album write drops it
        cache = getattr(self, "_albums_media", None)
        if cache is None:
            cache = self._albums_media = {}
        for a in albums:
            aid = str(a.get("id") or "")
            if not aid or aid in cache:
                continue
            try:
                media = self._vault_media_payload(album_id=aid)
            except Exception:
                media = []
            cache[aid] = [m for m in media if isinstance(m, dict) and m.get("id")]
        return cache

    def _album_counts(self, album: dict) -> dict:
        tally = dict(_EMPTY_COUNTS)
        for m in self._album_contents([album]).get(str(album.get("id") or ""), []):
            kind = _of_media({"id": m["id"], "media": m, "access": True}).get("type")
            key = _COUNT_KEYS.get(kind)
            if key:
                tally[key] += 1
            tally["mediaCount"] += 1
        tally["hasMedia"] = tally["mediaCount"] > 0
        return tally

    def _album_membership(self) -> dict[str, list[dict]]:
        albums = self._albums()
        contents = self._album_contents(albums)
        out: dict[str, list[dict]] = {}
        for a in albums:
            state = {**self._album_row(a), "hasMedia": True}
            for m in contents.get(state["id"], []):
                out.setdefault(str(m["id"]), []).append(state)
        return out

    def _vault_write(self, path: str, body: dict) -> Any:
        # every album mutation goes through here so none forgets to drop the _album_contents cache
        out = self._request("POST", path, json_body=body)
        self._albums_media = None
        return out

    def vault_media(self, *, limit: int = 24, offset: int = 0,
                    type: str = "all", list_id: int | None = None,
                    **_ignored: Any) -> dict:
        member_of = self._album_membership()
        items = []
        for m in self._vault_media_payload(album_id=str(list_id) if list_id is not None else None):
            if not isinstance(m, dict) or not m.get("id"):
                continue
            om = _of_media({"id": m["id"], "media": m, "access": True})
            if type and type != "all" and om.get("type") != type:
                continue
            om["isReady"] = True
            om["hasError"] = False
            om["listStates"] = member_of.get(str(m["id"]), [])
            items.append(om)
        page = items[offset:offset + limit] if limit else items
        return {"list": page, "hasMore": offset + len(page) < len(items)}

    def vault_media_by_id(self, media_id: str | int, **_ignored: Any) -> dict:
        rows = self._request("GET", "/media", params={"ids": str(media_id)})
        row = rows[0] if isinstance(rows, list) and rows else None
        if not isinstance(row, dict) or not row.get("id"):
            return {}
        om = _of_media({"id": row["id"], "media": row, "access": True})
        om["isReady"] = True
        om["hasError"] = False
        return om

    def _of_media_for_ids(self, media_ids: list) -> list:
        ids = [str(m) for m in media_ids if m]
        if not ids:
            return []
        # Treat a failed readback GET as missing media so an already-delivered send stays successful.
        try:
            rows = self._request("GET", "/media", params={"ids": ",".join(ids)}) or []
        except Exception:
            return []
        by_id = {str(r.get("id")): r for r in rows if isinstance(r, dict) and r.get("id")}
        out = []
        for mid in ids:
            raw = by_id.get(mid)
            if raw:
                out.append(_of_media({"id": raw["id"], "media": raw, "access": True}))
        return out


    def create_vault_list(self, name: str) -> dict:
        album = self._vault_write("/vault/albums", {
            "id": None,
            "title": name,
            "description": "",
            "accountId": None,
            "type": 0,
        }) or {}
        return {
            "id": str(album.get("id") or ""),
            "type": "custom",
            "name": album.get("title") or name,
            **_EMPTY_COUNTS,
        }

    def _album_media(self, path: str, list_id: Any, media_ids: list,
                     counted: str) -> dict:
        ids = [str(m) for m in (media_ids or []) if m]
        if not ids:
            return {"success": True, counted: 0}
        rows = self._vault_write(path, {"albumId": str(list_id), "mediaIds": ids})
        return {"success": True,
                counted: len(rows) if isinstance(rows, list) else len(ids)}

    def add_media_to_vault_list(self, list_id: Any, media_ids: list) -> dict:
        return self._album_media("/vault/albums/media", list_id, media_ids, "added")

    def remove_media_from_vault_list(self, list_id: Any, media_ids: list) -> dict:
        return self._album_media("/vault/albums/media/delete", list_id, media_ids, "removed")

    def rename_vault_list(self, list_id: Any, name: str) -> dict:
        # edit takes the WHOLE album back; re-read it so description and type survive a rename
        current = next((a for a in self._albums()
                        if str(a["id"]) == str(list_id)), {})
        updated = self._vault_write("/vault/albums/edit", {
            "id": str(list_id),
            "title": name,
            "description": current.get("description") or "",
            "accountId": str(self.session.account_id),
            "type": current.get("type") if current.get("type") is not None else 0,
        }) or {}
        return {
            "id": str(updated.get("id") or list_id),
            "name": updated.get("title") or name,
            "type": "custom",
        }

    def delete_vault_list(self, list_id: Any, clear_media: bool = False) -> dict:
        # Fansly has no clearMedia: deleting an album never deletes its media, so the flag is ignored
        self._vault_write("/vault/albums/delete", {"albumId": str(list_id)})
        return {"success": True}

    def sort_vault_lists(self, sort: str = "recent", order: str = "desc") -> dict:
        # no name sort endpoint (only /vault/albums/order moves one album); reporting success would show an order the server never applied
        return {"success": False, "unsupported": "fansly_sort_by_name"}

    def set_vault_lists_custom_order(self, list_ids: list) -> dict:
        cur = [str(a["id"]) for a in self._albums()]
        want = [str(i) for i in (list_ids or []) if str(i) in cur]
        if not want:
            return {"success": True, "moves": 0}
        moves = 0
        for target_index, album_id in enumerate(want):
            old = cur.index(album_id)
            if old == target_index:
                continue
            self._vault_write("/vault/albums/order",
                              {"oldPos": old, "newPos": target_index})
            cur.insert(target_index, cur.pop(old))
            moves += 1
        return {"success": True, "moves": moves}

    def vault_media_processing(self, **_ignored: Any) -> dict:
        return {"list": [], "hasMore": False}
