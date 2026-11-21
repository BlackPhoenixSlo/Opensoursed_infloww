"""capture: the driver's capture-browser part (ticket 07; prove.py calls it): opening the capture browser after
preflight, the `capture [--abort]` command, and the run's output kept for the session-leak check.

`capture` plays one proof's capture steps in the capture browser (no app) and writes each write OnlyFans was sent (or,
with --abort, would have been sent) as `capture-<id>.raw.json` and its scrubbed, checked `.record.json`. A Critical
control's capture is refused without --abort, before anything starts (story 26).
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from capture_record import check_record, scrub
from of_browser import CaptureBrowser, CaptureBrowserStop, RelayGuard, SessionDead, fetch_problems, load_session
from proof_core import READS, critical_capture_refused, critical_write, step_family


class Tee:
    """The run's own stdout and stderr, kept as they are printed for the session-leak check."""

    def __init__(self):
        self.parts: list = []

    def wrap(self, stream):
        tee = self

        class _W:
            def write(self, s):
                tee.parts.append(s)
                return stream.write(s)

            def __getattr__(self, name):
                return getattr(stream, name)

        return _W()

    def text(self) -> str:
        return "".join(self.parts)


OUT = Tee()


def needs_browser(proofs) -> bool:
    return any(p.trigger and step_family(p.trigger[0]) == "browser" for p in proofs)


def opens_capture_browser(capture, proofs, preflight: list) -> bool:
    """Whether a run opens the capture browser: `capture`, or a proof with capture-browser steps, after a clean
    preflight, among the proofs that may start (live_entry `startable`; none left: it never opens); the mode never
    decides it. Its own identity read (`start` here) runs whenever it opens, before
    any step.
    ASSUMPTION (D27 over the spec's "live always"): never by default in live prove/serve; D26 saw the browser kill
    the session once, and ticket 11 starts Relay-only with a signed API read."""
    return not preflight and bool(proofs) and bool(capture or needs_browser(proofs))


def cli_refusal(proof, n_ids: int, fault, abort: bool) -> str | None:
    """`capture`'s CLI checks, before anything starts: one proof, no fault, a Critical control only with --abort."""
    if n_ids != 1 or fault:
        return "capture plays one proof's capture steps (one --proof, no --fault)"
    if why := critical_capture_refused(proof, abort):
        return f"refused: {why}"
    return None if proof.capture_steps else f"{proof.id} declares no capture steps"


def start(pw, session_dir: Path, call, creator: str, evidence: Path, rep: dict, *, fake_origin, fake_sign,
          launch_args):
    """The capture browser, signed in from the session in the run's temp dir, through the Relay's Live guard (`call`:
    prove.py `_relay_client`). Its first load, the session probe (once: a dead session is never probed again) and
    OnlyFans's own identity read run before any step. A stop is added to `rep["preflight"]` (None returned);
    `SessionDead` also writes `session-dead.json`."""
    def probe():
        status, raw = call("GET", "/__proof/session", account=creator)
        try:
            return status, json.loads(raw)
        except ValueError:
            return status, raw.decode("utf-8", "replace")

    cb = CaptureBrowser(pw, load_session(session_dir), RelayGuard(call), creator=creator, fake_origin=fake_origin,
                        fake_sign=fake_sign, probe=probe, launch_args=launch_args)
    try:
        cb.open()
    except CaptureBrowserStop as e:   # SessionDead included: the run stops, never retried
        if isinstance(e, SessionDead):
            (evidence / "session-dead.json").write_text(json.dumps({
                "creator": creator, "state": "dead", "reason": str(e), "retried": False,
                "at": datetime.now(timezone.utc).isoformat()}, indent=1))
        cb.close()
        rep["preflight"].append(f"capture browser: {type(e).__name__}: {e}")
        print(f"ofm-live-proof: capture browser stopped before any step: {e}", flush=True)
        return None
    except BaseException:
        cb.close()
        raise
    print(f"ofm-live-proof: capture browser signed in; probe 200, OnlyFans's /users/me names {creator}", flush=True)
    return cb


def finish(cb, evidence: Path, rep: dict) -> None:
    """Always (the driver's finally): capture-browser.jsonl, the browser's off-host aborts into the report, close."""
    if cb is None:
        return
    with open(evidence / "capture-browser.jsonl", "w") as f:
        for x in cb.exchanges:
            f.write(json.dumps(x, default=str) + "\n")
    rep.setdefault("offhost", []).extend({"via": "capture-browser", "url": x["url"]} for x in cb.offhost())
    try:
        cb.close()
    except Exception:  # noqa: BLE001  (already gone with Playwright)
        pass


def play(step, cb, before, marker: str, wire, res: dict) -> set:
    """One capture-browser trigger step of run_proof: ("fetch", method, path, body, expect) from the fake-mode drill
    page, checked against its expectation, or ("hand-off", selector), an OAuth hand-off's click (story 17). Returns the
    wire seqs it expected aborted, which run_proof leaves out of the step-9 window."""
    if step[0] == "hand-off":
        cb.click_hand_off(step[1])
        return set()
    _, method, path, body, expect = step
    path = path(before) if callable(path) else path
    body = body(before) if callable(body) else body
    if body is not None:
        body = json.loads(json.dumps(body).replace("{marker}", marker))
    s0 = max((e["seq"] for e in wire()), default=0)
    status = cb.send(method, path, body)
    lines = [e for e in wire() if e["seq"] > s0 and e.get("origin") == "of-browser"
             and e["method"] == method.upper() and e["path"] == path]
    res["problems"] += fetch_problems(method, path, expect, status, lines)
    res.setdefault("browser", []).append({"method": method.upper(), "path": path, "expect": expect, "status": status})
    return {e["seq"] for e in lines if e.get("verdict") == "refused"} if expect != "sent" else set()


def run_capture(proof, run_proof, cb, creator: str, evidence: Path, run_id: str, proof_fan, abort: bool) -> dict:
    """One proof's capture steps, run as its trigger by `run_proof(proof, capture_abort)` (prove.py), then each write
    the capture browser recorded as a raw capture and its capture record. Abort mode arms the proof with
    capture_abort (the guard refuses every write: `capture_abort`, a Critical one `critical`) and runs it as a read
    proof whose OnlyFans side must read the same after."""
    steps = tuple((*st[:4], "critical" if isinstance(st[2], str) and critical_write(*st[1:4]) else "capture_abort")
                  if abort and st[0] == "fetch" and st[4] == "sent" else st for st in proof.capture_steps)
    n0 = len(cb.exchanges)
    r = run_proof(replace(proof, trigger=steps, settled=None, **({"arm": (), "effect": None} if abort else {})), abort)
    r["capture"] = "abort" if abort else "send"
    writes = [x for x in cb.exchanges[n0:] if x["method"] not in READS and x.get("class") not in ("offhost", "oauth")]
    if not writes:
        r["problems"].append("capture: the capture browser recorded no write")
    for i, x in enumerate(writes, 1):
        name = f"capture-{proof.id}" + (f"-{i}" if len(writes) > 1 else "")
        raw = {"id": f"{proof.page.split('/')[0]}--{proof.control.lower().replace(' ', '-')}",
               "section": proof.page.split("/")[0], "label": proof.control, "pages": [proof.page],
               "phase": proof.phase, "source": "aborted" if x["aborted"] else "live",
               "captured": datetime.now(timezone.utc).date().isoformat(),
               "request": {"method": x["method"], "url": x["url"], "headers": x["headers"], "body": x["body"]},
               "response": cb.raw.get(x["seq"]),
               "proof": {"id": proof.id, "kind": proof.kind, "verdict": "pass" if r["state"] == "pass" else "fail",
                         "evidence": f"slop/evidence/{evidence.name}",
                         "undo": "undone" if r["undo"] == ["undone"] else "none" if x["aborted"] else "FAILED"},
               "guard": {"verdict": x["verdict"], "class": x["class"], "aborted": x["aborted"]}}
        (evidence / f"{name}.raw.json").write_text(json.dumps(raw, indent=1, default=str))
        rec = scrub(raw, {"creator": creator, "fan": proof_fan, "run": run_id})
        (evidence / f"{name}.record.json").write_text(json.dumps(rec, indent=1, default=str))
        r["problems"] += [f"capture record {name}: {q}" for q in check_record(rec)]
        r.setdefault("records", []).append(f"{name}.record.json")
    if r["state"] == "pass" and r["problems"]:
        r["state"] = "fail"
    return r
