from __future__ import annotations

from datetime import datetime

# OF message ids, unique across FakeOF instances, as OF's are.
_of_ids = iter(range(9_100_000_000_001, 9_600_000_000_000))


class FakeOF:

    def __init__(self, fail: dict[str, str] | None = None):
        self.user_id = "999"
        self.sent: list[dict] = []
        self.fail = dict(fail or {})
        self.read: list[int] = []
        self.chat: list[dict] = []
        self.reads = 0

    def me(self) -> dict:
        return {"id": int(self.user_id)}

    def mark_chat_read(self, chat_id) -> None:
        self.read.append(int(chat_id))

    def get_messages(self, chat_id, **kw) -> dict:
        self.reads += 1
        return {"list": list(self.chat), "hasMore": False}

    def send_message(self, chat_id, text, **kw) -> dict:
        if text in self.fail:
            raise RuntimeError(self.fail[text])
        self.sent.append({"fan_id": int(chat_id), "text": text, **kw})
        return {"id": next(_of_ids), "text": text,
                "createdAt": datetime.utcnow().isoformat() + "+00:00"}


PREVIEW, IMAGES, VIDEOS = 70, 71, 72
VAULT = {PREVIEW: [701, 702], IMAGES: [711, 712, 713], VIDEOS: [721, 722]}


class VaultOF(FakeOF):

    def __init__(self, fail: dict[str, str] | None = None):
        super().__init__(fail)
        self.vault_calls: list[tuple[int, str]] = []

    def vault_media(self, *, limit=24, offset=0, type="all", list_id=None, **_kw):
        self.vault_calls.append((int(list_id), type))
        ids = VAULT.get(int(list_id), [])
        return {"list": [{"id": i} for i in ids[offset:offset + limit]],
                "hasMore": offset + limit < len(ids)}


class PpvFailOF(VaultOF):

    def __init__(self, error: Exception, *, taken: bool):
        super().__init__()
        self.error, self.taken = error, taken
        self.listed: list[dict] = []
        self.attempts: list[str] = []
        self.read_kw: list[dict] = []

    def send_message(self, chat_id, text, **kw) -> dict:
        if "price" not in kw:
            return super().send_message(chat_id, text, **kw)
        self.attempts.append(text)
        if self.taken:
            self.listed.insert(0, _listed(text, kw["price"], datetime.utcnow(), media=kw.get("media_files")))
        raise self.error

    def get_messages(self, chat_id, **kw) -> dict:
        self.read_kw.append(kw)
        return {"list": list(self.listed), "hasMore": False}


def _listed(text: str, price: float, at: datetime, *, media=None) -> dict:
    return {"id": next(_of_ids), "text": f"<p>{text}</p>", "price": price,
            "fromUser": {"id": 999}, "createdAt": at.isoformat() + "+00:00",
            **({"media": [{"id": m} for m in media]} if media else {})}


UNLISTABLE_403 = "Unable to add user to user list"    # OF's permanent per-fan list refusal


def of_error(status: int, text: str, path: str = "/api2/v2/lists/50/users/2"):
    from types import SimpleNamespace
    from of_client import OFAPIError
    return OFAPIError(f"{status} for https://onlyfans.com{path}\n{text}",
                      response=SimpleNamespace(status_code=status))
