from __future__ import annotations

import asyncio
import secrets
import weakref
from dataclasses import dataclass, field

from slop.lib.client import Http
from slop.lib.push_wire import b64

DEFAULT_TYPES = ("purchases", "tip")


@dataclass
class PushDevice:
    name: str
    kind: str
    username: str
    password: str
    agency: int
    scope: frozenset
    types: tuple = DEFAULT_TYPES
    platforms: dict = field(default_factory=lambda: {"onlyfans": True, "fansly": True})
    http: Http | None = None
    sub_id: str | None = None
    priv: object = None
    auth: bytes = b""
    put_status: int | None = None

    def keys(self) -> dict:
        from cryptography.hazmat.primitives import serialization
        pub = self.priv.public_key().public_bytes(serialization.Encoding.X962,
                                                  serialization.PublicFormat.UncompressedPoint)
        return {"p256dh": b64(pub), "auth": b64(self.auth)}

    def wants(self, account_id: str, type_key: str | None, platform: str = "onlyfans") -> bool:
        return account_id in self.scope and type_key is not None and type_key in self.types \
            and self.platforms.get(platform, True)


# session = (principal, issued ms), no nonce: two same-user sign-ins in one ms share a cookie and one logout deletes both subs; serialize them, 2 ms apart. Locks per event loop: --break runs baseline and fault on separate loops
_SAME_USER: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[tuple[str, str], asyncio.Lock]]" = \
    weakref.WeakKeyDictionary()


async def sign_in(dev: PushDevice, base: str, rec) -> None:
    from cryptography.hazmat.primitives.asymmetric import ec
    dev.http = Http(base, rec, limits=4)
    route = "/auth/login" if dev.kind == "user" else "/chatter/login"
    locks = _SAME_USER.setdefault(asyncio.get_running_loop(), {})
    async with locks.setdefault((dev.kind, dev.username), asyncio.Lock()):
        r = await dev.http.post(route, json={"username": dev.username, "password": dev.password})
        r.raise_for_status()
        await asyncio.sleep(0.002)
    if dev.priv is None:
        dev.priv, dev.auth = ec.generate_private_key(ec.SECP256R1()), secrets.token_bytes(16)


async def subscribe(dev: PushDevice, wire) -> int:
    wire.device(dev.name, dev.priv, dev.auth)
    r = await dev.http.put("/push/subscription", json={
        "endpoint": wire.endpoint(dev.name), "keys": dev.keys(), "types": list(dev.types),
        "platforms": dev.platforms})
    dev.put_status = r.status_code
    if r.status_code == 200:
        dev.sub_id = r.json()["id"]
    return r.status_code
