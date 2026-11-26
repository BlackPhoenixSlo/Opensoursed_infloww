#!/usr/bin/env python3
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # noqa: E401,E702
import _harness  # noqa: E402

_harness.bootstrap()

import contextlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402

import cell_mode  # noqa: E402
import events  # noqa: E402
import events_wire as ew  # noqa: E402

DM = {"api2_chat_message": {"id": 7}, "__account_id": "11"}


@contextlib.contextmanager
def _cell(env: dict | None):
    keys = ("OI_CELL_MAP", "OI_CELL_ID", "OI_ACCOUNTS")
    old = {k: os.environ.get(k) for k in keys}
    was = cell_mode._data_gen
    for k in keys:
        os.environ.pop(k, None)
    os.environ.update(env or {})
    cell_mode._data_gen = 3 if env else None
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        cell_mode._data_gen = was


CELL = {"OI_CELL_MAP": "/nonexistent/placement.json", "OI_CELL_ID": "s02",
        "OI_ACCOUNTS": "onlyfans:11,onlyfans:12"}


async def _published(env: dict | None) -> dict:
    with _cell(env):
        sub = events._register("all", frozenset({"11", "13"}), frozenset())
        try:
            assert events._fanout(dict(DM)) == 1
            got = sub.q.get_nowait()
            frame = got[0] if isinstance(got, events._Batch) else got
            return json.loads(ew.sse_out([frame]).decode().split("data: ", 1)[1])
        finally:
            await events.unsubscribe("all", sub.q)


async def case_env_unset_frame_and_resync_as_main():
    assert await _published(None) == DM
    with _cell(None):
        sub = events._Sub("all", frozenset({"11"}), frozenset())
        assert events._resync(sub) == ew.RESYNC


async def case_cell_mode_frame_carries_cell_and_data_gen():
    got = await _published(CELL)
    assert got == {**DM, "cell": "s02", "data_gen": 3}, got
    assert next(iter(got)) == "api2_chat_message"


async def case_cell_mode_resync_names_only_owned_creators_of_the_stream():
    with _cell(CELL):
        wire = events._resync(events._Sub("all", frozenset({"11", "13"}), frozenset())).decode()
        assert wire.startswith("event: resync\n"), wire
        assert json.loads(wire.split("data: ", 1)[1]) == {"accounts": ["11"], "cell": "s02", "data_gen": 3}
        owner = json.loads(events._resync(events._Sub("all", None, frozenset())).decode().split("data: ", 1)[1])
        assert owner["accounts"] == ["11", "12"], owner
        one = json.loads(events._resync(events._Sub("model:12", None, frozenset())).decode().split("data: ", 1)[1])
        assert one["accounts"] == ["12"], one


_harness.run()
