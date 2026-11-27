#!/usr/bin/env python3
import os
import sys
from pathlib import Path

REMOVAL_REPO = os.environ.get("REMOVAL_REPO", "").strip()
if not REMOVAL_REPO or not Path(REMOVAL_REPO).is_dir():
    print("SKIP  REMOVAL_REPO not set")
    raise SystemExit(0)

import _harness  # noqa: E402

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

from sqlalchemy import select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import account_page  # noqa: E402
import accounts as account_registry  # noqa: E402
import leak_tracker  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, LeakWatch, LeakWatchTombstone, UserAccount  # noqa: E402

STUB = Path("app") / "tests" / "tracker_stub_server.py"
CLI = Path("app") / "tracker_cli.py"
DEAD = "http://127.0.0.1:9"
OUT = os.environ.get("LEAK_E2E_OUT", "").strip()

IDS = fx.seed_two_agencies()
AGENCY = IDS["agency_a_owner"]
MIRA = IDS["creator_a"]
ROWAN = "1000003"
OWNER = fx.login_owner("agency_a_owner")
MIRA_IDENTITY = {"username": "mira.example", "display_name": "Mira Example", "aliases": [], "verified": False}
ROWAN_IDENTITY = {"username": "rowan_example", "display_name": "Rowan Example", "aliases": [], "verified": False}


def _python(repo: Path) -> str:
    for venv in (".venv", "venv"):
        if (py := repo / venv / "bin" / "python").is_file():
            return str(py)
    return shutil.which("python3") or sys.executable


def _copy_of_checkout(repo: Path, dest: Path) -> str:
    ref = os.environ.get("REMOVAL_REF", "").strip() or "origin/main"
    tar = subprocess.run(["git", "-C", str(repo), "archive", ref, "app"], capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(dest)], input=tar, check=True)
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", ref], capture_output=True, text=True,
                         check=True).stdout
    return f"{ref} {sha.strip()}"


class Service:
    def __init__(self, repo: Path):
        self.tmp = Path(tempfile.mkdtemp(prefix="leak_e2e_"))
        try:
            self._start(repo)
        except BaseException:
            self.stop()
            raise

    def _start(self, repo: Path) -> None:
        self.src = self.tmp / "src"
        self.src.mkdir()
        self.source = _copy_of_checkout(repo, self.src)
        self.py = _python(repo)
        self.db = self.tmp / "tracker.db"
        no_proxy = "127.0.0.1,localhost"
        self.env = {"PATH": os.environ.get("PATH", ""), "HOME": str(self.tmp), "TMPDIR": str(self.tmp),
                    "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "TRACKER_PAID_TENANTS": "",
                    "BROWSERBASE_API_KEY": "", "BROWSERBASE_PROJECT_ID": "",
                    "HTTP_PROXY": DEAD, "HTTPS_PROXY": DEAD, "http_proxy": DEAD, "https_proxy": DEAD,
                    "NO_PROXY": no_proxy, "no_proxy": no_proxy}
        self.log = self.tmp / "server.log"
        out = self.tmp / "server.out"
        with open(out, "w") as o, open(self.log, "w") as e:
            self.proc = subprocess.Popen([self.py, str(STUB), "--port", "0", "--db", str(self.db)], cwd=self.src,
                                         env=self.env, stdout=o, stderr=e, stdin=subprocess.DEVNULL)
        deadline = time.monotonic() + 60
        lines: list[str] = []
        while time.monotonic() < deadline and self.proc.poll() is None:
            lines = out.read_text().splitlines()
            if any(x.startswith("TRACKER_STUB_FETCH=") for x in lines):
                break
            time.sleep(0.2)
        else:
            raise RuntimeError(f"tracker did not start: {self.tail()}")
        self.base = lines[0].strip()
        assert self.base.startswith("http://127.0.0.1:"), self.base

    def tail(self) -> str:
        try:
            return self.log.read_text()[-2000:]
        except OSError:
            return ""

    def cli(self, *args: str) -> str:
        r = subprocess.run([self.py, str(CLI), *args], cwd=self.src, env={**self.env, "TRACKER_DB": str(self.db)},
                           capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, (args[:2], r.stderr[-1000:])
        return r.stdout.strip()

    def http(self, method: str, path: str, key: str | None = None, body: object = None) -> tuple[int, object]:
        req = urllib.request.Request(self.base + path, method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {key}"} if key else {})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=120) as r:
                status, raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        return status, json.loads(raw) if raw else None

    def daily(self, at: str) -> dict:
        status, body = self.http("POST", f"/__tracker/daily?at={at}")
        assert status == 200 and isinstance(body, dict), (status, body)
        return body

    def fetch_answers(self, table: dict) -> None:
        assert self.http("POST", "/__tracker/fetch", body=table)[0] == 200

    def watch_row(self, watch_id: str) -> dict:
        with sqlite3.connect(f"file:{self.db}?mode=ro", uri=True) as c:
            c.row_factory = sqlite3.Row
            return dict(c.execute("SELECT * FROM watches WHERE watch_id = ?", (watch_id,)).fetchone())

    def stop(self) -> None:
        proc = getattr(self, "proc", None)
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(self.tmp, ignore_errors=True)


SVC = Service(Path(REMOVAL_REPO).expanduser().resolve())
os.environ.update(LEAK_TRACKER_URL=SVC.base, LEAK_TRACKER_ENABLED="1")
os.environ.pop("OI_CELL_MAP", None)
EVIDENCE: dict = {"source": SVC.source, "tracker": "loopback", "steps": [], "passed": False}


def _step(name: str, **facts) -> None:
    EVIDENCE["steps"].append({"step": name, **facts})


def _no_live() -> None:
    async def none(_account_id: str):
        return None
    account_page.of_me = none


def _add_rowan() -> None:
    (account_registry.ACCOUNTS_DIR / ROWAN).mkdir(exist_ok=True)

    async def _add():
        async with get_session() as s:
            s.add(Account(id=ROWAN, nickname="rowan", color="#aaaaaa"))
        async with get_session() as s:
            s.add(UserAccount(user_id=AGENCY, account_id=ROWAN))
    asyncio.run(_add())


def _watch_id(account_id: str) -> str:
    async def _read():
        async with get_session() as s:
            return await s.scalar(select(LeakWatch.watch_id).where(LeakWatch.account_id == account_id))
    return asyncio.run(_read())


def _stones() -> dict[str, LeakWatchTombstone]:
    async def _read():
        async with get_session() as s:
            return {t.watch_id: t for t in (await s.execute(select(LeakWatchTombstone))).scalars()}
    return asyncio.run(_read())


def _roster() -> dict:
    r = OWNER.get("/admin/leaks/roster")
    assert r.status_code == 200, r.text
    return r.json()


def _row(roster: dict, account_id: str) -> dict:
    (row,) = [x for x in roster["rows"] if x["account_id"] == account_id]
    return row


def _drill(account_id: str) -> list[dict]:
    r = OWNER.get(f"/admin/leaks/watches/{account_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tracked"] is True and body["stale"] is False, body
    return body["leaks"]


def _service_watches(key: str) -> set[str]:
    status, body = SVC.http("GET", "/v1/creators", key)
    assert status == 200, (status, body)
    return {c["watch_id"] for c in body["creators"]}


def _day(d, hh: int) -> str:
    return f"{d.isoformat()}T{hh:02d}:00:00Z"


def case_enrol_to_delete_across_both_repos():
    _no_live()
    _add_rowan()
    fx.store_blob(AGENCY, "flags", {"leak_tracker": True})
    fx.store_blob(AGENCY, "roles", {"enforce": True, "roles": [], "assignments": {}})
    try:
        tenant = SVC.cli("tenant", "add", "Fixture Agency")
        key = SVC.cli("key", "issue", tenant)
        assert tenant.startswith("tn_") and leak_tracker.KEY_SHAPE.fullmatch(key), tenant
        _step("cli", tenant_id=tenant, key_issued=True)

        assert OWNER.get("/admin/leaks/setup").json()["key"] == "missing"
        r = OWNER.put("/admin/leaks/key", json={"key": key})
        assert r.status_code == 200 and r.json()["key"] == "set" and key not in r.text, r.text
        assert asyncio.run(leak_tracker.bound_tenant(AGENCY)) == tenant
        setup = OWNER.get("/admin/leaks/setup").json()
        assert setup["key"] == "set" and setup["masked"] and key not in json.dumps(setup), setup
        _step("connect", bound_tenant=tenant, setup_key=setup["key"])

        r = OWNER.put(f"/admin/leaks/watches/{MIRA}", json={**MIRA_IDENTITY, "consent": True})
        assert (r.status_code, r.json()) == (200, {"synced": True}), r.text
        mira = _watch_id(MIRA)
        roster = _roster()
        seeded = _row(roster, MIRA)
        counts = seeded["counts"]
        assert seeded["seeded"] is True and seeded["reachable"] is True and seeded["last_checked_at"], seeded
        assert counts["found_on_first_scan"] > 0 and counts["live"] > 0, counts
        _step("enrol_and_seed", watch_id=mira, synced=True, counts=counts, last_checked_at=seeded["last_checked_at"])

        os.environ["LEAK_TRACKER_URL"] = DEAD
        r = OWNER.put(f"/admin/leaks/watches/{ROWAN}", json={**ROWAN_IDENTITY, "consent": True})
        os.environ["LEAK_TRACKER_URL"] = SVC.base
        assert (r.status_code, r.json()) == (200, {"synced": False}), r.text
        rowan = _watch_id(ROWAN)
        assert rowan not in _service_watches(key)
        asyncio.run(leak_tracker.sync_watches())
        assert rowan in _service_watches(key)
        assert _row(_roster(), ROWAN)["seeded"] is True
        _step("enrol_while_down_then_sync", watch_id=rowan, pushed_by_sync=True)

        leaks = _drill(MIRA)
        pages = [x for x in leaks if x["kind"] == "page" and x["pill"] == "live" and "google_web" in x["sources"]]
        assert pages, leaks
        target = pages[0]
        SVC.fetch_answers({target["url"]: 404, "*": 200})

        day1 = datetime.now(timezone.utc).date() + timedelta(days=1)
        day2 = day1 + timedelta(days=1)
        first = SVC.daily(_day(day1, 5))
        assert first["probed"] >= 1 and first["fetched"] >= 1, first
        again = SVC.daily(_day(day1, 6))
        assert (again["probed"], again["fetched"], again["seeded"]) == (0, 0, 0), again
        after1 = _row(_roster(), MIRA)
        assert after1["last_checked_at"] > seeded["last_checked_at"], (after1, seeded)
        assert after1["last_checked_at"].startswith(day1.isoformat()), after1
        assert {x["leak_id"]: x["pill"] for x in _drill(MIRA)}[target["leak_id"]] == "live", "one dead probe never calls it gone"
        _step("daily_pass", day=day1.isoformat(), first=first, same_day_again=again,
              last_checked_at=after1["last_checked_at"])

        second = SVC.daily(_day(day2, 5))
        assert second["probed"] >= 1, second
        after2 = _row(_roster(), MIRA)
        assert after2["last_checked_at"].startswith(day2.isoformat()), after2
        pill = {x["leak_id"]: x["pill"] for x in _drill(MIRA)}[target["leak_id"]]
        assert pill == "cached", pill
        assert after2["counts"]["cached"] == 1, after2["counts"]
        r = OWNER.get("/admin/leaks/all")
        assert r.status_code == 200, r.text
        all_models = r.json()["leaks"]
        assert {x["account_id"] for x in all_models} <= {MIRA, ROWAN} and all_models, all_models
        assert {x["pill"] for x in all_models if x["leak_id"] == target["leak_id"]} == {"cached"}
        _step("second_dead_probe", day=day2.isoformat(), pill=pill, counts=after2["counts"],
              last_checked_at=after2["last_checked_at"], all_models_leaks=len(all_models))

        r = OWNER.delete(f"/admin/leaks/watches/{MIRA}")
        assert (r.status_code, r.json()) == (200, {"tracked": False}), r.text
        stone = _stones()[mira]
        roster = _roster()
        assert MIRA not in {x["account_id"] for x in roster["rows"]}
        assert MIRA in {x["account_id"] for x in roster["untracked"]}
        assert mira in _service_watches(key), "the route only writes the tombstone"
        asyncio.run(leak_tracker.land_tombstones())
        assert mira not in _stones()
        listed = _service_watches(key)
        assert mira not in listed and rowan in listed, listed
        status, body = SVC.http("GET", f"/v1/creators/{mira}", key)
        assert (status, body) == (410, {"error": "watch_deleted"}), (status, body)
        assert SVC.http("DELETE", f"/v1/watches/{mira}", key)[0] == 204
        status, body = SVC.http("PUT", f"/v1/watches/{mira}", key, {"account_id": MIRA, "platform": "onlyfans",
                                                                     "username": MIRA_IDENTITY["username"],
                                                                     "verified": False, "display_name": "",
                                                                     "aliases": [], "paused": False})
        assert (status, body) == (410, {"error": "watch_deleted"}), (status, body)
        row = SVC.watch_row(mira)
        asked = stone.requested_at.replace(tzinfo=timezone.utc)
        purge_after = datetime.fromisoformat(row["purge_after"].replace("Z", "+00:00"))
        assert row["deleted_at"] and abs(purge_after - asked - timedelta(days=30)) <= timedelta(seconds=1), row
        dry = json.loads(SVC.cli("purge", "--dry-run"))
        assert dry["watches"] == [] and dry["deleted_ids"] == [], dry
        _step("delete", watch_id=mira, tombstone_landed=True, service_lists=sorted(listed), read_after=410,
              requested_at=asked.isoformat(), purge_after=row["purge_after"], purge_dry_run=dry)
        EVIDENCE["passed"] = True
    except BaseException:
        EVIDENCE["service_log_tail"] = SVC.tail()
        raise
    finally:
        if OUT:
            Path(OUT).parent.mkdir(parents=True, exist_ok=True)
            Path(OUT).write_text(json.dumps(EVIDENCE, indent=2, default=str) + "\n")


if __name__ == "__main__":
    try:
        _harness.run()
    finally:
        SVC.stop()
