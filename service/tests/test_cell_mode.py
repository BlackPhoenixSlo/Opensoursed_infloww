import _harness

import contextlib  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import socket  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import urllib.request  # noqa: E402
from pathlib import Path  # noqa: E402

import cell_mode  # noqa: E402
import platforms  # noqa: E402

SERVICE = Path(__file__).resolve().parents[1]
FLEET_PY = SERVICE.parent / "deploy/fleet/fleet.py"
CELL_ENV = ("OI_CELL_MAP", "OI_CELL_ID", "OI_CELL_ROLE", "OI_ACCOUNTS")


def _placement(**over) -> dict:
    doc = {"schema": 1, "agency": "acme", "generation": 1, "written_at": "2026-11-26T10:00:00Z", "by": "fleet.py",
           "min_cell_proto": 1,
           "cells": {"s01": {"box": "b1", "epoch": 1, "relay": "127.0.0.1:18701", "role": "control", "state": "live"},
                     "s02": {"box": "b1", "epoch": 1, "relay": "127.0.0.1:18702", "role": "data", "state": "live"}},
           "accounts": {"onlyfans:111": "s02", "onlyfans:222": "s02"}}
    doc.update(over)
    return doc


@contextlib.contextmanager
def _cell_env(doc: dict | str | None, **env: str):
    old = {k: os.environ.get(k) for k in CELL_ENV}
    with tempfile.TemporaryDirectory() as t:
        path = Path(t) / "placement.json"
        if doc is not None:
            path.write_text(doc if isinstance(doc, str) else json.dumps(doc))
        for k in CELL_ENV:
            os.environ.pop(k, None)
        os.environ.update({"OI_CELL_MAP": str(path), **env})
        try:
            yield path
        finally:
            for k, v in old.items():
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v


def _refused(needle: str) -> None:
    try:
        cell_mode.boot_check()
    except SystemExit as e:
        assert e.code != 0 and needle in str(e.code), e.code
        return
    raise AssertionError(f"boot_check passed; expected a refusal naming {needle!r}")


def case_fleet_platforms_pinned_to_service_platforms():
    spec = importlib.util.spec_from_file_location("fleet_pin", FLEET_PY)
    fleet = importlib.util.module_from_spec(spec)
    sys.modules["fleet_pin"] = fleet
    try:
        spec.loader.exec_module(fleet)
    finally:
        sys.modules.pop("fleet_pin", None)
    assert fleet.PLATFORMS == platforms.KEYS, (fleet.PLATFORMS, platforms.KEYS)


def case_good_map_passes():
    with _cell_env(_placement(), OI_CELL_ID="s02", OI_CELL_ROLE="data", OI_ACCOUNTS="onlyfans:111"):
        assert cell_mode.boot_check() is None
    with _cell_env(_placement(), OI_CELL_ID="s01", OI_CELL_ROLE="control", OI_ACCOUNTS=""):
        assert cell_mode.boot_check() is None


def case_unreadable_map_refused():
    with _cell_env(None, OI_CELL_ID="s02", OI_CELL_ROLE="data"):
        _refused("unreadable")
    with _cell_env("{not json", OI_CELL_ID="s02", OI_CELL_ROLE="data"):
        _refused("unreadable")
    with _cell_env(_placement(schema=2), OI_CELL_ID="s02", OI_CELL_ROLE="data"):
        _refused("not Placement v1")
    with _cell_env(None, OI_CELL_ID="s02", OI_CELL_ROLE="data") as path:
        path.mkdir()
        _refused("unreadable")


def case_missing_or_empty_agency_refused():
    missing = _placement()
    del missing["agency"]
    for doc in (missing, _placement(agency=""), _placement(agency=" ")):
        with _cell_env(doc, OI_CELL_ID="s02", OI_CELL_ROLE="data"):
            _refused("agency")


def case_missing_or_unknown_cell_id_refused():
    with _cell_env(_placement(), OI_CELL_ROLE="data"):
        _refused("OI_CELL_ID is unset")
    with _cell_env(_placement(), OI_CELL_ID="s09", OI_CELL_ROLE="data"):
        _refused("Cell s09 is not in")


def case_role_mismatch_refused():
    with _cell_env(_placement(), OI_CELL_ID="s02", OI_CELL_ROLE="control"):
        _refused("role 'data'")
    with _cell_env(_placement(), OI_CELL_ID="s01"):
        _refused("OI_CELL_ROLE=''")


def case_proto_above_relay_refused():
    with _cell_env(_placement(min_cell_proto=cell_mode.CELL_PROTO + 1), OI_CELL_ID="s02", OI_CELL_ROLE="data"):
        _refused(f"min_cell_proto {cell_mode.CELL_PROTO + 1}")


def case_ownership_comes_from_oi_accounts_never_placement():
    with _cell_env(_placement(), OI_CELL_ID="s02", OI_CELL_ROLE="data", OI_ACCOUNTS="onlyfans:111"):
        cell_mode.boot_check()
        assert cell_mode.owned("onlyfans", "111")
        assert not cell_mode.owned("onlyfans", "222"), "in Placement for s02 but not in OI_ACCOUNTS"
        assert not cell_mode.owned("fansly", "111")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def case_uvicorn_exits_nonzero_before_binding_on_each_refusal():
    bad = {
        "unreadable": (None, {"OI_CELL_ID": "s02", "OI_CELL_ROLE": "data"}),
        "missing id": (_placement(), {"OI_CELL_ROLE": "data"}),
        "role mismatch": (_placement(), {"OI_CELL_ID": "s02", "OI_CELL_ROLE": "control"}),
        "proto too high": (_placement(min_cell_proto=2), {"OI_CELL_ID": "s02", "OI_CELL_ROLE": "data"}),
    }
    for name, (doc, env) in bad.items():
        port = _free_port()
        with _cell_env(doc, **env):
            r = subprocess.run([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(port)],
                               cwd=SERVICE, env=dict(os.environ), capture_output=True, text=True, timeout=180)
        out = r.stdout + r.stderr
        assert r.returncode != 0, (name, r.returncode, out[-2000:])
        assert "Cells: refusing to start" in out, (name, out[-2000:])
        assert "Uvicorn running" not in out and "Application startup" not in out, (name, out[-2000:])
        with socket.socket() as s:
            assert s.connect_ex(("127.0.0.1", port)) != 0, f"{name}: something listens on {port}"


def case_uvicorn_serves_control_cell_with_empty_oi_accounts():
    port = _free_port()
    with _cell_env(_placement(), OI_CELL_ID="s01", OI_CELL_ROLE="control", OI_ACCOUNTS=""):
        p = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(port)],
                             cwd=SERVICE, env=dict(os.environ), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 180
            while True:
                assert p.poll() is None, f"control Cell exited {p.returncode}"
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/livez", timeout=5) as r:
                        assert r.status == 200
                        break
                except OSError:
                    assert time.monotonic() < deadline, "control Cell never answered /livez"
                    time.sleep(0.5)
        finally:
            p.terminate()
            p.wait(30)


_harness.run()
