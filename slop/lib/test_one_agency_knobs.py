from __future__ import annotations

import asyncio
import sqlite3
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from slop.lib.cli import load  # noqa: E402
from slop.seed import World, agency  # noqa: E402
from slop.seed.profiles import one_agency, one_agency_split  # noqa: E402

CROWD = load(ROOT / "slop" / "scenarios" / "2026-10-24-chatter-crowd.py")


@pytest.fixture(scope="module")
def schema(tmp_path_factory) -> Path:
    sys.path.insert(0, str(ROOT / "service"))
    from sqlalchemy import create_engine
    from db.models import Base
    db = tmp_path_factory.mktemp("schema") / "relay.db"
    eng = create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(eng)
    eng.dispose()
    return db


@pytest.fixture(autouse=True)
def no_relay(monkeypatch):
    async def register(http, username: str) -> str:
        uid = str(uuid.uuid4())
        con = sqlite3.connect(http.db)
        with con:
            con.execute("INSERT INTO users(id, username, password, created_at, last_seen_at) "
                        "VALUES (?, ?, 'x', '2026-01-01', '2026-01-01')", (uid, username))
        con.close()
        return uid

    class Http:
        def __init__(self, url, rec=None, **_kw):
            self.c = SimpleNamespace(base_url=url, cookies={})
            self.rec, self.db = rec, Http.db

    monkeypatch.setattr(agency, "_register", register)
    monkeypatch.setattr("slop.lib.client.Http", Http)
    return Http


def world(tmp_path: Path, schema: Path, no_relay, name: str = "s01", knobs: dict | None = None) -> World:
    d = tmp_path / name
    (d / "sessions").mkdir(parents=True)
    db = d / "relay.db"
    db.write_bytes(schema.read_bytes())
    no_relay.db = db
    w = World(db=db, sessions=d / "sessions", seed=1, scale="small", stream=name, user_prefix=f"{name}o",
              owner=no_relay(f"http://{name}"))
    if knobs is not None:
        w.data["one_agency"] = knobs
    return w


def seed_one(tmp_path, schema, no_relay, knobs=None) -> World:
    return asyncio.run(one_agency.build(world(tmp_path, schema, no_relay, knobs=knobs)))


def main_creators(w: World) -> list[dict]:
    return [c for c in w.data["creators"] if c["owner"] == w.user_id]


def db_creators(w: World) -> int:
    con = sqlite3.connect(w.db)
    try:
        return con.execute("SELECT count(*) FROM user_accounts WHERE user_id = ?", (w.user_id,)).fetchone()[0]
    finally:
        con.close()


def plan(ws: list[World]) -> object:
    shards = [SimpleNamespace(idx=i, id=f"s0{i + 1}", url=f"http://s0{i + 1}") for i in range(len(ws))]
    ctx = SimpleNamespace(shards=shards)
    return CROWD.Plan(ctx, ws, 8, tuple(range(len(ws))), grants=ws[0].data.get("grants", "narrow"))


def test_defaults_are_todays_world(tmp_path, schema, no_relay):
    w = seed_one(tmp_path, schema, no_relay)
    cs = main_creators(w)
    assert (len(cs), sum(c["big"] for c in cs), db_creators(w)) == (50, 9, 50)
    assert CROWD.rates(w) == {c["id"]: 50 if c["big"] else 5 for c in w.data["creators"]}
    assert w.data["grants"] == "narrow"
    assert {len(r["account_ids"]) for r in plan([w]).recs} == {2}


@pytest.mark.parametrize("knobs,models,big", [({"models": 8}, 8, 8), ({"models": 8, "big": 2}, 8, 2),
                                              ({"models": 4, "big": 0}, 4, 0)])
def test_models_and_big_knobs_change_the_seeded_creators(tmp_path, schema, no_relay, knobs, models, big):
    w = seed_one(tmp_path, schema, no_relay, knobs)
    cs = main_creators(w)
    assert (len(cs), sum(c["big"] for c in cs), db_creators(w)) == (models, big, models)
    fans = {c["id"]: len(w.data["fans"][c["id"]]) for c in cs}
    assert {fans[c["id"]] for c in cs if c["big"]} <= {w.size["big_fans_per_creator"]}
    assert {fans[c["id"]] for c in cs if not c["big"]} <= {w.size["fans_per_creator"]}
    assert len(w.data["creators"]) == models + one_agency.NEIGHBOUR_MODELS


def test_unseeded_rates_use_profile_defaults():
    w = SimpleNamespace(data={"creators": [{"id": "big", "big": True}, {"id": "normal", "big": False}]})
    assert CROWD.rates(w) == {"big": one_agency.BIG_DPM, "normal": one_agency.DPM}


def test_dpm_knob_sets_every_normal_creators_flood_rate(tmp_path, schema, no_relay):
    w = seed_one(tmp_path, schema, no_relay, {"models": 4, "big": 1, "dpm": 20})
    r = CROWD.rates(w)
    assert sorted(r[c["id"]] for c in main_creators(w)) == [20, 20, 20, 50]


def test_broad_grants_give_every_chatter_every_creator(tmp_path, schema, no_relay):
    w = seed_one(tmp_path, schema, no_relay, {"models": 5, "big": 1, "grants": "broad"})
    p = plan([w])
    mine = {c["id"] for c in main_creators(w)}
    assert len(p.recs) == 8 and all(set(r["account_ids"]) == mine for r in p.recs)
    narrow = plan([seed_one(tmp_path / "n", schema, no_relay, {"models": 5, "big": 1})])
    assert {len(r["account_ids"]) for r in narrow.recs} == {2}


def test_mixed_grants_split_the_crowd_half_narrow_half_broad(tmp_path, schema, no_relay):
    w = seed_one(tmp_path, schema, no_relay, {"models": 5, "big": 0, "grants": "mixed"})
    mine = {c["id"] for c in main_creators(w)}
    sizes = [len(r["account_ids"]) for r in plan([w]).recs]
    assert sorted(sizes) == [2] * 4 + [len(mine)] * 4


@pytest.mark.parametrize("knobs", [{"models": 1}, {"models": 4, "big": 5}, {"big": -1}, {"dpm": 0},
                                   {"grants": "wide"}])
def test_bad_knobs_refused_before_seeding(knobs):
    with pytest.raises(ValueError):
        one_agency.shape(knobs)


def test_split_layout_is_two_relays_one_owner_tab_each(tmp_path, schema, no_relay):
    params = {"layout": "one-agency-split"}
    assert CROWD.shards_for(params) == 2 and CROWD.boxes_for(params) == {"b1": (0, 1)}
    assert CROWD.boxes_for({"layout": "three-shard"}) == {"b1": (0, 1, 2)}
    ws = [world(tmp_path, schema, no_relay, n, {"dpm": 7}) for n in ("s01", "s02")]
    seeded = asyncio.run(_split(ws, no_relay))
    assert [len(main_creators(w)) for w in seeded] == [15, 15]
    assert [sum(c["big"] for c in main_creators(w)) for w in seeded] == [5, 4]
    assert all(CROWD.rates(w)[c["id"]] == 7 for w in seeded for c in main_creators(w) if not c["big"])
    shards = [SimpleNamespace(idx=i, id=f"s0{i + 1}") for i in range(2)]
    sides = CROWD.owner_sides(seeded, shards)
    assert [i for i, _ in sides] == [0, 1]
    assert [a for _, a in sides] == [w.user_id for w in seeded] and len({a for _, a in sides}) == 2
    p = plan(seeded)
    assert [sum(r["shard"] == i for r in p.recs) for i in (0, 1)] == [4, 4]
    assert all(set(r["account_ids"]) <= {c["id"] for c in main_creators(seeded[r["shard"]])} for r in p.recs)


async def _split(ws: list[World], no_relay) -> list[World]:
    orig = one_agency.build

    async def build(w):
        no_relay.db = w.db
        return await orig(w)
    one_agency.build = build
    try:
        return await one_agency_split.build_fleet(ws)
    finally:
        one_agency.build = orig


def test_split_models_knob_halves_models_and_big(tmp_path, schema, no_relay):
    ws = [world(tmp_path, schema, no_relay, n, {"models": 9, "big": 3}) for n in ("s01", "s02")]
    seeded = asyncio.run(_split(ws, no_relay))
    assert [len(main_creators(w)) for w in seeded] == [5, 4]
    assert [sum(c["big"] for c in main_creators(w)) for w in seeded] == [2, 1]


def _ctx(params: dict, scale: str = "small"):
    return SimpleNamespace(params=params, scale=scale,
                           param=lambda k, d: type(d)(params.get(k, d)) if d is not None else params.get(k, d))


def test_soak_runs_only_when_its_param_is_set():
    ladder = [2, 4, 6, 8]
    plain = CROWD.schedule(ladder, 15.0, 120.0)
    assert plain == CROWD.schedule(ladder, 15.0, 120.0, 0.0)
    assert [x[0] for x in plain] == [f"s{k}{tail}" for k, n in enumerate(ladder, 1)
                                     for tail in (f"-ramp-{n}ch", f"-{n}ch")]
    assert CROWD.resolve_knobs(_ctx({"layout": "one-agency"}, "medium"), "one-agency").soak_s == 0.0
    k = CROWD.resolve_knobs(_ctx({"layout": "one-agency", "soak_s": "900"}, "medium"), "one-agency")
    soaked = CROWD.schedule(ladder, k.ramp_s, k.hold_s, k.soak_s)
    assert soaked[:-1] == plain and soaked[-1] == ("s5-soak-8ch", 8, "hold", 900.0)


def test_campaign_layouts_refuse_shape_knobs_and_keep_their_knobs():
    with pytest.raises(ValueError, match="one-agency layouts only"):
        CROWD.resolve_knobs(_ctx({"models": "30"}), "three-shard")
    assert CROWD.resolve_knobs(_ctx({}, "medium"), "three-shard") == CROWD.Knobs("three-shard", 15.0, 120.0)
    k = CROWD.resolve_knobs(_ctx({"models": "30", "grants": "broad"}), "one-agency-split")
    assert k.shape == {"models": "30", "big": None, "dpm": None, "grants": "broad"}
