"""W30 rollout regressions through the CLI and the fake relay."""

import json
from email.message import Message
from io import BytesIO
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

import rollout
import rollout_core as core
import rollout_decide as decide
from fake_relay import ITEM_MC_REAL, Cr, Fake, journal, kinds, run
from test_script_fill_rollout_fill import A_SEQ, Crash, _crash_on_journal, fill_world, make_backup


@pytest.fixture
def serve_relay(serve, monkeypatch):
    def start(fake):
        try:
            return serve(fake)
        except PermissionError:
            # Some sandboxes deny loopback binds. Keep the real CLI, Relay and
            # wire payloads by substituting only urllib's transport.
            def open_request(request, *, timeout):
                url = urlsplit(request.full_url)
                body = json.loads(request.data) if request.data else None
                cookie = request.get_header("Cookie", "").removeprefix(f"{core.COOKIE}=")
                status, payload, *extra = fake.handle(request.method, url.path, parse_qs(url.query), body, cookie)
                response = BytesIO(json.dumps(payload).encode())
                response.status = status
                response.headers = Message()
                for name, value in (extra[0] if extra else {}).items():
                    response.headers[name] = value
                return response

            monkeypatch.setattr(core._OPENER, "open", open_request)
            return "http://127.0.0.1"

    return start


def test_f2_reconcile_landed_apply_with_fresh_backup(serve_relay, tmp_path, monkeypatch):
    creator, _ = fill_world()
    fake = Fake([creator])
    url = serve_relay(fake)
    scope = ("--creator", creator.id, "--sequence", A_SEQ)
    assert run(url, tmp_path, "plan", *scope) == core.EXIT_DONE
    before = make_backup(tmp_path / "before.db", fake)
    with monkeypatch.context() as crash:
        _crash_on_journal(crash, "apply")
        with pytest.raises(Crash):
            run(url, tmp_path, "apply", "--live", "--backup", before, *scope)
    assert fake.applies == [(creator.id, A_SEQ)]
    assert len(kinds(tmp_path, "apply_intent")) == 1 and not kinds(tmp_path, "apply")

    fresh = make_backup(tmp_path / "after.db", fake)
    result = run(url, tmp_path, "apply", "--live", "--backup", fresh, *scope)
    assert result == core.EXIT_DONE, kinds(tmp_path, "backup")[-1]["reason"]
    (applied,) = kinds(tmp_path, "apply")
    assert applied["reconstructed"] is True
    assert applied["undo"] == fake.last_undo[(creator.id, A_SEQ)]
    assert fake.applies == [(creator.id, A_SEQ)]


def test_f5_crash_after_describe_post_preserves_fleet_ceiling(serve_relay, tmp_path, monkeypatch):
    creator = Cr("100", "alice", describable=2 * decide.STEP, per_poll=decide.STEP)
    fake = Fake([creator])
    url = serve_relay(fake)
    ceiling = decide.STEP * ITEM_MC_REAL
    args = ("describe", "--live", "--ceiling-cents", str(ceiling // decide.MC_PER_CENT),
            "--item-mc", str(ITEM_MC_REAL))
    relay_call = core.Relay.call

    def lose_start_response(self, method, path, *args, **kwargs):
        response = relay_call(self, method, path, *args, **kwargs)
        if method == "POST" and path == f"{core.VAULT}/describe-all" and response.status == 200:
            raise Crash(path)
        return response

    with monkeypatch.context() as crash:
        crash.setattr(core.Relay, "call", lose_start_response)
        with pytest.raises(Crash):
            run(url, tmp_path, *args)
    assert creator.running_target == decide.STEP
    fake.tick(creator)  # The relay finishes billing while the driver is down.
    assert creator.spent == ceiling

    run(url, tmp_path, *args)
    counted = decide.resume(journal(tmp_path))["spent_mc"]
    assert creator.spent == counted == ceiling, (
        f"relay billed {creator.spent} mc, journal counted {counted} mc, ceiling {ceiling} mc"
    )


@pytest.mark.parametrize("lost", [0, 502])
def test_f34_lost_describe_start_answer_keeps_the_reservation_in_flight(serve_relay, tmp_path, monkeypatch, lost):
    """W30 F34: the relay accepts and bills the start, the driver sees a transport error (0) or a 5xx and runs on:
    the reservation is never closed at zero spend; one paid start, journal spend == billed == ceiling."""
    creator = Cr("100", "alice", describable=2 * decide.STEP, per_poll=decide.STEP)
    fake = Fake([creator])
    url = serve_relay(fake)
    ceiling = decide.STEP * ITEM_MC_REAL
    args = ("describe", "--live", "--ceiling-cents", str(ceiling // decide.MC_PER_CENT),
            "--item-mc", str(ITEM_MC_REAL))
    relay_call = core.Relay.call
    lost_once = []

    def lose_start_answer(self, method, path, *a, **kw):
        response = relay_call(self, method, path, *a, **kw)
        if method == "POST" and path == f"{core.VAULT}/describe-all" and response.status == 200 and not lost_once:
            lost_once.append(path)
            fake.tick(creator)  # the relay bills the whole step before the driver reads anything again
            self.last_status = lost
            return core.Resp(lost, {"error": "URLError"} if lost == 0 else None)
        return response

    with monkeypatch.context() as m:
        m.setattr(core.Relay, "call", lose_start_answer)
        monkeypatch.setattr(core, "POLL_S", 0)
        run(url, tmp_path, *args)
    run(url, tmp_path, *args)
    starts = [e for e in fake.events if e[0] == "start"]
    counted = decide.resume(journal(tmp_path))["spent_mc"]
    assert len(starts) == 1, starts
    assert creator.spent == counted == ceiling, (
        f"relay billed {creator.spent} mc, journal counted {counted} mc, ceiling {ceiling} mc"
    )
    assert not [ln for ln in journal(tmp_path) if ln.get("outcome") == "not_started"]


@pytest.mark.parametrize("kill", [False, True])
def test_f40_lost_start_settles_against_its_own_baseline(serve_relay, tmp_path, monkeypatch, kill):
    """W30 F40 (+F37 with `kill`): the start answer is lost while the relay's POST still waits on coverage before
    claiming, so status reads idle and the recount is zero; the POST then claims and bills, and the retry gets 409.
    The reservation settles against the ORIGINAL start's baseline: one paid start, journal spend == billed <= the
    ceiling. With `kill` the driver dies right after the lost answer; the next run still knows the start was lost."""
    creator = Cr("100", "alice", describable=2 * decide.STEP, per_poll=decide.STEP // 2)
    fake = Fake([creator])
    url = serve_relay(fake)
    ceiling = decide.STEP * ITEM_MC_REAL
    args = ("describe", "--live", "--ceiling-cents", str(ceiling // decide.MC_PER_CENT),
            "--item-mc", str(ITEM_MC_REAL))
    relay_call = core.Relay.call
    held = {}   # the POST the relay is still working on: {"target": t, "recounts": n}

    def lose_start_answer(self, method, path, *a, **kw):
        if method == "POST" and path == f"{core.VAULT}/describe-all" and not held and not fake.events:
            held.update(target=kw["body"]["target"], recounts=0)
            self.last_status = 0
            return core.Resp(0, {"error": "URLError"})
        if held.get("target") and path == f"{core.VAULT}/describe-all/plan":
            held["recounts"] += 1
        response = relay_call(self, method, path, *a, **kw)
        if held.get("target") and held["recounts"] == 1 and not fake.events:
            # the held POST claims after the driver's first look at the lost start, and bills half a step
            fake.start(creator, held["target"])
            fake.tick(creator)
        return response

    monkeypatch.setattr(core, "POLL_S", 0)
    with monkeypatch.context() as m:
        m.setattr(core.Relay, "call", lose_start_answer)
        if kill:
            def die_after_lost(self, method, path, *a, **kw):
                r = lose_start_answer(self, method, path, *a, **kw)
                if held and method == "POST":
                    raise Crash(path)
                return r
            m.setattr(core.Relay, "call", die_after_lost)
            with pytest.raises(Crash):
                run(url, tmp_path, *args)
            m.setattr(core.Relay, "call", lose_start_answer)
            in_flight = decide.resume(journal(tmp_path))["creators"][creator.id]
            assert in_flight["state"] == "running" and in_flight["sweep"].get("lost_start") is not None, in_flight
        run(url, tmp_path, *args)
    run(url, tmp_path, *args)
    starts = [e for e in fake.events if e[0] == "start"]
    counted = decide.resume(journal(tmp_path))["spent_mc"]
    assert len(starts) == 1, starts
    assert creator.spent == counted <= ceiling, (
        f"relay billed {creator.spent} mc, journal counted {counted} mc, ceiling {ceiling} mc"
    )


def test_f6_collect_still_running_reaches_a_wait_limit(serve_relay, tmp_path, monkeypatch):
    class RunningRelay(Fake):
        def collect_tick(self, creator):
            pass  # The healthy status endpoint always reports running.

    creator = Cr("100", "alice", complete=False)
    fake = RunningRelay([creator])
    url = serve_relay(fake)
    started = core.now()
    elapsed = 0

    def advance(seconds):
        nonlocal elapsed
        elapsed += seconds
        if elapsed > 24 * 60 * 60:
            polls = len(fake.hits.get((f"{core.VAULT}/collect/status", creator.id), []))
            pytest.fail(f"Collect still polling after 24 simulated hours and {polls} healthy running replies")

    def wall_time():
        return started + elapsed

    monkeypatch.setattr(core, "POLL_S", 5 * 60)
    monkeypatch.setattr(core, "now", wall_time)
    monkeypatch.setattr(rollout, "now", wall_time)
    monkeypatch.setattr(rollout, "time", SimpleNamespace(sleep=advance, monotonic=lambda: elapsed, time=wall_time))

    result = run(url, tmp_path, "collect", "--live")
    pending = kinds(tmp_path, "open")
    pauses = kinds(tmp_path, "pause")
    assert creator.collect["running"] and not creator.complete
    assert result == core.EXIT_PAUSED or (result == core.EXIT_DONE and pending)
    assert any(entry.get("reason") for entry in pauses + pending)


def test_f44_describe_still_running_pauses_at_a_wait_limit_with_the_reservation_kept(serve_relay, tmp_path,
                                                                                     monkeypatch):
    """W30 F44: a stranded describe flag answers 200 `running: true` forever; the run stops awaiting it at a wait
    limit and pauses (exit 3) with the sweep_start still in flight (reserved), and the next run awaits it."""
    class Stranded(Fake):
        stuck = True

        def tick(self, c):
            if not self.stuck:
                super().tick(c)

    creator = Cr("100", "alice", describable=2 * decide.STEP, per_poll=decide.STEP)
    fake = Stranded([creator])
    url = serve_relay(fake)
    started, elapsed = core.now(), 0

    def advance(seconds):
        nonlocal elapsed
        elapsed += seconds
        if elapsed > 24 * 60 * 60:
            pytest.fail(f"describe still polling after 24 simulated hours ({fake.status_polls} running replies)")

    def wall_time():
        return started + elapsed

    monkeypatch.setattr(core, "POLL_S", 5 * 60)
    monkeypatch.setattr(core, "now", wall_time)
    monkeypatch.setattr(rollout, "now", wall_time)
    monkeypatch.setattr(rollout, "time", SimpleNamespace(sleep=advance, monotonic=lambda: elapsed, time=wall_time))
    args = ("describe", "--live", "--item-mc", str(ITEM_MC_REAL))
    assert run(url, tmp_path, *args) == core.EXIT_PAUSED
    assert kinds(tmp_path, "pause")[-1]["reason"] == "describe_still_running"
    st = decide.resume(journal(tmp_path))
    assert st["creators"][creator.id]["state"] == "running" and not kinds(tmp_path, "sweep"), st["creators"]
    fake.stuck = False
    run(url, tmp_path, *args)
    assert len([e for e in fake.events if e[0] == "start"]) >= 1 and kinds(tmp_path, "sweep")
    assert creator.spent == decide.resume(journal(tmp_path))["spent_mc"]


def test_f49_back_to_back_healthy_sweeps_never_hit_the_wait_limit(serve_relay, tmp_path, monkeypatch):
    """W30 F49: the wait limit is per sweep: two healthy sweeps of one Creator, each under DESCRIBE_WAIT_S but
    together over it, run to done without a `describe_still_running` pause."""
    per_poll = 14   # 18 polls (1.5 h at 5 min) per 250-item sweep: each under 2 h, both together over it
    creator = Cr("100", "alice", describable=2 * decide.STEP, per_poll=per_poll)
    fake = Fake([creator])
    url = serve_relay(fake)
    started, elapsed = core.now(), 0

    def advance(seconds):
        nonlocal elapsed
        elapsed += seconds

    def wall_time():
        return started + elapsed

    monkeypatch.setattr(core, "POLL_S", 5 * 60)
    monkeypatch.setattr(core, "now", wall_time)
    monkeypatch.setattr(rollout, "now", wall_time)
    monkeypatch.setattr(rollout, "time", SimpleNamespace(sleep=advance, monotonic=lambda: elapsed, time=wall_time))
    assert run(url, tmp_path, "describe", "--live", "--item-mc", str(ITEM_MC_REAL)) == core.EXIT_DONE, \
        kinds(tmp_path, "pause")
    assert len(kinds(tmp_path, "sweep")) == 2 and elapsed > decide.DESCRIBE_WAIT_S
