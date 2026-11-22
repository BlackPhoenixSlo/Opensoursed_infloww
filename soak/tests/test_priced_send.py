"""FakeOF's chat send refuses a priced message with no media and no locked text, as OnlyFans does (measured on the Live
proof run 11-22: 400 "You have no paid content. Please add some paid media or text."). Media or lockedText passes; a
free text-only send passes. Requests go through the fake's real routes (signature check included)."""
import time

import _path  # noqa: F401
from starlette.testclient import TestClient

from soak import ids
from soak.fake_of.app import FakeOF
from soak.fake_of.signing import sign_value
from soak.world import World

NO_PAID = {"error": {"code": 0, "message": "You have no paid content. Please add some paid media or text."}}


def main() -> int:
    fake = FakeOF(World(seed=1))
    client = TestClient(fake.build())
    path = f"/api2/v2/chats/{ids.fan_id(1)}/messages"

    def send(body: dict) -> tuple[int, dict]:
        t = str(int(time.time() * 1000))
        uid = str(fake.world.creator_id)
        h = {"user-id": uid, "x-hash": fake.x_hash, "time": t,
             "sign": sign_value(fake.rules, time_ms=t, path_qs=path, user_id=uid)}
        r = client.request("POST", path, headers=h, json=body)
        return r.status_code, r.json()

    base = {"text": "<p>x</p>", "lockedText": False, "mediaFiles": [], "price": 3.0}
    assert send(base) == (400, NO_PAID), send(base)
    assert send({**base, "mediaFiles": [1]})[0] == 200
    assert send({**base, "lockedText": True})[0] == 200
    assert send({**base, "price": 0})[0] == 200
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
