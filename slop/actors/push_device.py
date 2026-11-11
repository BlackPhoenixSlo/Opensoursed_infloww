"""A phone or browser with Web Push on: a real sign-in (owner `POST /auth/login`, Employee `POST
/chatter/login`, each its own cookie, so its own session issue time), its own P-256 key pair + 16-byte
auth secret (what PushManager.subscribe makes; the private half registered with lib/push_wire.py so it
can decrypt), and `PUT /push/subscription` with the types / platforms the bell sends (lib/pushPrefs:
the toast types that are on, the platform switches). `scope`: the Creators the session should see
(the oracle, from the seed: never asked of the relay)."""
from __future__ import annotations

import asyncio
import secrets
import weakref
from dataclasses import dataclass, field

from slop.lib.client import Http
from slop.lib.push_wire import b64

DEFAULT_TYPES = ("purchases", "tip")  # app/lib/notifSettings DEFAULT_NOTIF_SETTINGS.toast


@dataclass
class PushDevice:
    name: str                      # push_wire sub name (endpoint /push/<name>)
    kind: str                      # 'user' | 'chatter'
    username: str
    password: str
    agency: int                    # index in w.data["agencies"]
    scope: frozenset               # Creator ids the session sees (oracle)
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
        """The spec: in scope, type on (an unnamed OF type never), platform on."""
        return account_id in self.scope and type_key is not None and type_key in self.types \
            and self.platforms.get(platform, True)


# per event loop: --break runs baseline and fault in one process, each on its own loop
_SAME_USER: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[tuple[str, str], asyncio.Lock]]" = \
    weakref.WeakKeyDictionary()


async def sign_in(dev: PushDevice, base: str, rec) -> None:
    """A fresh client and a real sign-in: its own cookie. A session is (principal, issued ms) with no
    nonce (service/auth.py _make_cookie), so two devices of one user signing in within the same ms
    share it and one's logout deletes both subscriptions. Same-user sign-ins go one at a time with
    2 ms after each response (the next cookie is minted later on the same clock); users stay parallel."""
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
    """Registers the keys with the push service, then the bell's PUT. Returns the status."""
    wire.device(dev.name, dev.priv, dev.auth)
    r = await dev.http.put("/push/subscription", json={
        "endpoint": wire.endpoint(dev.name), "keys": dev.keys(), "types": list(dev.types),
        "platforms": dev.platforms})
    dev.put_status = r.status_code
    if r.status_code == 200:
        dev.sub_id = r.json()["id"]
    return r.status_code
