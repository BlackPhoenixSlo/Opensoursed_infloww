"""FakeOF's Streaming > Blocked users surface (ticket 73): Block a username (by username or OF's `u<id>` handle)
shows in the next read, a row's DELETE removes it, an unknown name 404s. Requests go through the fake's real routes
(signature check included)."""
import time

import _path  # noqa: F401
from starlette.testclient import TestClient

from soak import ids
from soak.fake_of.app import FakeOF
from soak.fake_of.signing import sign_value
from soak.world import World


def main() -> int:
    fake = FakeOF(World(seed=1))
    client = TestClient(fake.build())

    def call(method: str, path_qs: str, want: int = 200):
        t = str(int(time.time() * 1000))
        uid = str(fake.world.creator_id)
        h = {"user-id": uid, "x-hash": fake.x_hash, "time": t,
             "sign": sign_value(fake.rules, time_ms=t, path_qs=path_qs, user_id=uid)}
        r = client.request(method, path_qs, headers=h)
        assert r.status_code == want, (method, path_qs, r.status_code, r.text[:200])
        return r.json()

    fan1, fan2 = ids.fan_id(1), ids.fan_id(2)
    assert call("GET", "/api2/v2/streams/users/blocked?limit=10") == {"list": [], "hasMore": False}
    assert call("POST", f"/api2/v2/streams/users/u{fan1}/block") == {"success": True}
    assert call("POST", "/api2/v2/streams/users/soakfan2/block") == {"success": True}
    call("POST", "/api2/v2/streams/users/nosuchfan/block", want=404)
    page = call("GET", "/api2/v2/streams/users/blocked?limit=10")
    assert [(u["id"], u["username"]) for u in page["list"]] == [(fan2, "soakfan2"), (fan1, "soakfan1")], page
    assert [u["id"] for u in call("GET", "/api2/v2/streams/users/blocked?limit=1&offset=1")["list"]] == [fan1]
    assert call("GET", "/api2/v2/streams/users/blocked?limit=1")["hasMore"] is True
    assert [u["id"] for u in call("GET", "/api2/v2/streams/users/blocked?limit=10&query=fan1")["list"]] == [fan1]
    assert call("DELETE", f"/api2/v2/streams/users/{fan1}/block") == {"success": True}
    call("DELETE", f"/api2/v2/streams/users/{fan1}/block", want=404)
    assert [u["id"] for u in call("GET", "/api2/v2/streams/users/blocked?limit=10")["list"]] == [fan2]
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
