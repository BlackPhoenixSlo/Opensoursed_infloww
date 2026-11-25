import time
from datetime import timedelta
from urllib.parse import urlencode

import _path  # noqa: F401
from starlette.testclient import TestClient

from soak.fake_of.app import FakeOF
from soak.fake_of.signing import sign_value
from soak.world import World, now_utc


def main() -> int:
    fake = FakeOF(World(seed=1))
    client = TestClient(fake.build())

    def get(**q):
        path_qs = "/api2/v2/payouts/stats" + (f"?{urlencode(q)}" if q else "")
        t = str(int(time.time() * 1000))
        uid = str(fake.world.creator_id)
        h = {"user-id": uid, "x-hash": fake.x_hash, "time": t,
             "sign": sign_value(fake.rules, time_ms=t, path_qs=path_qs, user_id=uid)}
        r = client.get(path_qs, headers=h)
        assert r.status_code == 200, (path_qs, r.status_code, r.text[:200])
        return r.json()["list"]

    def all_(body):
        return body["total"]["all"]

    whole = get()
    assert all_(whole) == {"total_net": 312.0, "total_gross": 390.0}, all_(whole)
    assert len(whole["months"]) >= 3 and all(k.isdigit() for k in whole["months"]), whole["months"].keys()
    m = next(iter(whole["months"].values()))
    assert {"total_net", "total_gross"} <= m.keys() and all({"time", "net", "gross"} == i.keys()
                                                           for k, v in m.items() if isinstance(v, list) for i in v)
    assert set(whole["total"]) - {"all"} <= {"subscribes", "tips", "chat_messages"}
    assert get(by="day") == whole

    today = now_utc()
    day = today.strftime("%Y-%m-%d")
    assert get(by="day", start=day, end=day) == whole
    ranged = get(by="day", startDate=day, endDate=day)
    assert all_(ranged) == {"total_net": 4.0, "total_gross": 5.0}, all_(ranged)
    assert all_(ranged) != all_(whole) and len(ranged["months"]) == 1
    fmt = "%Y-%m-%d %H:%M:%S"
    assert all_(get(startDate=day + " 00:00:00", endDate=today.strftime(fmt))) == all_(ranged)
    early = today - timedelta(minutes=2)
    if early.strftime("%Y-%m-%d") == day:
        assert all_(get(startDate=day + " 00:00:00", endDate=early.strftime(fmt))) == {"total_net": 0, "total_gross": 0}
    cut = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    after, before = all_(get(startDate=cut)), all_(get(endDate=(today - timedelta(days=31)).strftime("%Y-%m-%d")))
    assert round(after["total_gross"] + before["total_gross"], 2) == all_(whole)["total_gross"], (after, before)
    fake.world.ledger(kind="tip", fid=fake.world.fans[0].id, dollars=25.0, at=today)
    assert all_(get(startDate=day, endDate=day)) == {"total_net": 24.0, "total_gross": 30.0}
    assert get()["total"]["tips"]["total_gross"] >= 25.0
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
