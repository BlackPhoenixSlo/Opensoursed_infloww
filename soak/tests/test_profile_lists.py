"""FakeOF's Things I Like links (ticket 70): GET /users/links answers OF's real item shape (measured live 2026-11-21:
`{id, sort, url, title, description, image}`, the link in `url`, no `link` key); PUT `{link}` appends one and answers
the full list; DELETE /users/links/{id} removes only it. Social media's buttons (ticket 69): GET /init serves OF's
socialMediaProviders (measured live 2026-11-21); PUT /users/social/buttons with a socialMedia outside them gets OF's 400
(measured: the old host-inferred body `socialMedia: "example"`) and adds nothing; a provider's body is appended. Requests
go through the fake's real routes (signature check included)."""
import time

import _path  # noqa: F401
from starlette.testclient import TestClient

from soak.fake_of.app import FakeOF
from soak.fake_of.profile_lists import INVALID_SOCIAL
from soak.fake_of.signing import sign_value
from soak.world import World

OF_KEYS = {"id", "sort", "url", "title", "description", "image"}


def main() -> int:
    fake = FakeOF(World(seed=1))
    client = TestClient(fake.build())

    def call(method: str, path_qs: str, body=None, want: int = 200):
        t = str(int(time.time() * 1000))
        uid = str(fake.world.creator_id)
        h = {"user-id": uid, "x-hash": fake.x_hash, "time": t,
             "sign": sign_value(fake.rules, time_ms=t, path_qs=path_qs, user_id=uid)}
        r = client.request(method, path_qs, headers=h, json=body)
        assert r.status_code == want, (method, path_qs, r.status_code, r.text[:200])
        return r.json()

    init = call("GET", "/api2/v2/init")
    providers = init["socialMediaProviders"]
    assert init["socialButtonsMaxLimit"] == 10 and len(providers) == 22, init
    assert all(set(p) == {"socialMedia", "label", "isLink", "isShowAt"} for p in providers), providers
    assert providers[0] == {"socialMedia": "instagram", "label": "Instagram", "isLink": False, "isShowAt": False}
    assert {p["socialMedia"] for p in providers if p["isLink"]} == {"amazon", "etsy", "bereal", "vsco"}
    old = {"socialMedia": "example", "label": "oi-proof-r1", "link": "https://example.com/oi-proof-r1", "username": "oi-proof-r1"}
    assert call("PUT", "/api2/v2/users/social/buttons", old, want=400) == INVALID_SOCIAL
    assert call("GET", "/api2/v2/users/social/buttons") == []
    ig = {"socialMedia": "instagram", "label": "oi-proof-r1", "link": "", "username": "oi_proof_r1"}
    reply = call("PUT", "/api2/v2/users/social/buttons", ig)
    assert [{k: x[k] for k in ig} for x in reply] == [ig], reply
    assert call("DELETE", f"/api2/v2/users/social/buttons/{reply[0]['id']}") == {"success": True}
    assert call("GET", "/api2/v2/users/social/buttons") == []

    a, b = "https://www.youtube.com/watch?v=a", "https://www.imdb.com/title/tt1/"
    assert call("GET", "/api2/v2/users/links") == []
    call("PUT", "/api2/v2/users/links", {"link": a})
    reply = call("PUT", "/api2/v2/users/links", {"link": b})
    assert all(set(x) == OF_KEYS for x in reply), reply
    assert set(reply[0]["image"]) == {"src", "thumbs", "width", "height"}, reply[0]
    assert set(reply[0]["image"]["thumbs"]) == {"c50", "c144"}, reply[0]
    listed = call("GET", "/api2/v2/users/links")
    assert listed == reply and [x["url"] for x in listed] == [a, b], listed
    assert call("DELETE", f"/api2/v2/users/links/{listed[0]['id']}") == {"success": True}
    call("DELETE", f"/api2/v2/users/links/{listed[0]['id']}", want=404)
    assert [x["url"] for x in call("GET", "/api2/v2/users/links")] == [b]
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
