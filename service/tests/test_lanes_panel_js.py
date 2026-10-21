#!/usr/bin/env python3
"""
The Concurrency panel's inline JavaScript, actually executed.
Plain-assert, no pytest (repo convention).

WHY THIS EXISTS. `lane_config_api._PAGE` carries ~440 lines of JS that nothing
could run, and it became the highest-risk part of the change by evidence, not
theory: two defects landed there in consecutive review rounds, and both were
found by a human reading it rather than by anything automated.

  • `renderRestart()` rendered the bold, invented claim "this relay is not pid 1"
    plus a budget of "0 of 0" whenever the FIRST load merely failed — a
    diagnosis manufactured from a payload that never arrived.
  • `load()` cleared the error banner synchronously on call, and two call sites
    invoke it right after showing an error. The 429 "restart refused" detail and
    the 80s "it never came back" warning were both wiped in the same turn,
    leaving a destructive button that refuses in total silence.

Neither is reachable from Python, and a mutation run over the whole change set
killed 26 of 27 mutants — the survivor being exactly this file's territory. So
this suite stubs a DOM and `fetch`, runs the real script under `node --check`'s
big brother (`node:vm`), and asserts what an operator would actually see.

NOT a browser and deliberately not one. No jsdom, no headless Chrome, no new
dependency — `node` is already required by this repo, and the stub is ~70 lines.
If node is absent the suite SKIPS rather than fails: it must never be the reason
a Python-only checkout goes red.

Cases:
  case_a_failed_first_load_does_not_diagnose_the_relay
  case_a_refused_restart_keeps_its_reason_on_screen
  case_a_restart_that_never_returns_keeps_its_warning
  case_a_successful_load_clears_a_stale_error
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import _harness  # noqa: E402

import lane_config_api  # noqa: E402

_NODE = shutil.which("node")

# The stub. Only what the panel actually touches — a fake DOM whose elements
# remember what was written to them, a scripted `fetch`, and instant timers so a
# 40-iteration poll loop does not take 80 real seconds.
_HARNESS = r"""
const vm = require("node:vm");
const script = require("fs").readFileSync(process.argv[2], "utf8");
const plan = JSON.parse(require("fs").readFileSync(process.argv[3], "utf8"));

function makeEl(id) {
  return { id, innerHTML: "", textContent: "", value: "", disabled: false,
           dataset: {}, style: { display: "" } };
}
const els = {};
const document = {
  getElementById: (id) => (els[id] = els[id] || makeEl(id)),
  querySelectorAll: () => [],
};

// `fetch` replies per ENDPOINT, not from one flat list. The page talks to two
// different routes — the page payload and the cheap restart poll — and a stub
// that ignores the URL hands the poll's body to `load()`, which then throws on
// `j.knobs.map`. That is a harness artifact masquerading as a product bug, and
// routing by URL is what the browser does anyway. Last entry of each list
// repeats, so a poll loop need not be enumerated.
const cursors = {};
const calls = [];
function pick(kind) {
  const list = plan[kind] || [{}];
  const i = cursors[kind] || 0;
  cursors[kind] = i + 1;
  return list[Math.min(i, list.length - 1)];
}
async function fetch(url, opts) {
  const method = (opts && opts.method) || "GET";
  const kind = url.indexOf("/restart") >= 0
    ? (method === "POST" ? "restartPost" : "restartPoll")
    : "config";
  calls.push({ url, method, kind });
  const step = pick(kind);
  if (step.throw) throw new Error(step.throw);
  return {
    ok: step.ok !== false,
    status: step.status || 200,
    json: async () => step.body,
    text: async () => JSON.stringify(step.body),
  };
}

// A FAKE CLOCK, not just instant timers. `waitForBoot` loops on
// `Date.now() - started < 80000`, so timers that fire immediately without
// advancing the clock spin forever — the harness's first version hung exactly
// there. Each stub sleep advances the clock by its own delay, which both makes
// the loop terminate and keeps the elapsed-seconds label truthful.
let clock = 1_000_000;
const FakeDate = { now: () => clock };
const ctx = vm.createContext({
  document, fetch, console,
  setTimeout: (fn, ms) => { clock += (ms || 0); fn(); },
  confirm: () => true,
  navigator: {},
  Date: FakeDate,
  Math, JSON, Number, Set, Object, String, Array, Promise, AbortSignal,
});
vm.runInContext(script, ctx);

(async () => {
  await new Promise((r) => setImmediate(r));       // let the trailing load() settle
  if (plan.then) { await ctx[plan.then](); }
  await new Promise((r) => setImmediate(r));
  const out = {};
  for (const id of Object.keys(els))
    out[id] = { text: els[id].textContent, html: els[id].innerHTML,
                display: els[id].style.display, disabled: els[id].disabled };
  console.log("---RESULT---" + JSON.stringify({ els: out, calls }));
})();
"""


def _run(plan: dict) -> dict:
    """Execute the real panel script under the stub and return what the DOM
    ended up holding."""
    js = re.search(r"<script>(.*?)</script>", lane_config_api._PAGE, re.S).group(1)
    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "panel.js"
        script.write_text(js, "utf-8")
        planfile = Path(d) / "plan.json"
        planfile.write_text(json.dumps(plan), "utf-8")
        runner = Path(d) / "run.js"
        runner.write_text(_HARNESS, "utf-8")
        proc = subprocess.run(
            [_NODE, str(runner), str(script), str(planfile)],
            capture_output=True, text=True, timeout=60,
        )
    assert "---RESULT---" in proc.stdout, (proc.stdout[-2000:], proc.stderr[-2000:])
    return json.loads(proc.stdout.split("---RESULT---", 1)[1])


def _payload(**over):
    body = {
        "knobs": [], "restart_required": False, "path": "/tmp/lane_config.json",
        "history": [],
        "container": {"cpus": None, "cpus_readable": False, "mem_bytes": None,
                      "mem_readable": False, "host_cpus": 4, "container_id": ""},
        "restart": {"budget": {"used": 0, "limit": 2, "remaining": 2,
                               "window_s": 3600, "retry_after_s": 0},
                    "boot_id": "1-100.000", "can_restart": True,
                    "path": "/tmp/lane_restarts.json"},
    }
    body.update(over)
    return body


def case_a_failed_first_load_does_not_diagnose_the_relay():
    """No payload is not a diagnosis. Rendering "this relay is not pid 1" from
    an absent `last` is the same sin `container_limits` exists to avoid —
    "unlimited" reported for a file that merely would not open."""
    if not _NODE:
        print("[skip] node not available")
        return
    result = _run({"config": [{"throw": "network down"}]})
    note = result["els"].get("restartnote", {})
    assert "not pid 1" not in (note.get("html") or ""), (
        f"the panel diagnosed the deployment from a payload it never got: "
        f"{note.get('html')!r}"
    )
    budget = result["els"].get("restartbudget", {})
    assert (budget.get("text") or "") == "", (
        f"an invented budget was rendered: {budget.get('text')!r}"
    )
    assert result["els"]["restartbtn"]["disabled"] is True
    assert result["els"]["err"]["display"] == "block", "the failure must be shown"


def case_a_refused_restart_keeps_its_reason_on_screen():
    """A destructive button that refuses in silence is the dead end this whole
    panel exists to remove. `load()` runs synchronously on call, so an
    unconditional banner-clear at its top wiped the 429 detail in the same turn.
    """
    if not _NODE:
        print("[skip] node not available")
        return
    result = _run({
        "config": [{"body": _payload()}],
        "restartPost": [{"ok": False, "status": 429,
                         "body": {"detail": "2 restarts per hour is the limit — "
                                            "1800s until the next one frees"}}],
        "then": "restart",
    })
    err = result["els"]["err"]
    assert err["display"] == "block", "the refusal was hidden — operator sees nothing"
    assert "limit" in (err["text"] or ""), (
        f"the refusal detail did not survive the reload: {err['text']!r}"
    )


def case_a_restart_that_never_returns_keeps_its_warning():
    """The relay answers but `boot_id` never changes: the poll must time out AND
    leave the message telling the operator to go look at the container."""
    if not _NODE:
        print("[skip] node not available")
        return
    same = _payload()
    result = _run({
        "config": [{"body": same}],
        "restartPost": [{"body": {"restarting": True, **same["restart"]}}],
        # Every poll answers with the SAME boot_id: the relay is up, but it is
        # the process we asked to leave. The wait must expire, not settle.
        "restartPoll": [{"body": same["restart"]}],
        "then": "restart",
    })
    err = result["els"]["err"]
    assert err["display"] == "block", "an 80s wait ended in total silence"
    assert "has not come back" in (err["text"] or ""), (
        f"the timeout warning was wiped by the reload: {err['text']!r}"
    )


def case_a_successful_load_clears_a_stale_error():
    """The other half — the clear must still happen on an ordinary reload, or a
    resolved error stays on screen forever."""
    if not _NODE:
        print("[skip] node not available")
        return
    result = _run({
        "config": [
            {"throw": "network down"},      # first load fails -> banner shown
            {"body": _payload()},           # a later load succeeds
        ],
        "then": "load",
    })
    assert result["els"]["err"]["display"] == "none", (
        "a stale error survived a successful reload"
    )


_harness.run(
    case_a_failed_first_load_does_not_diagnose_the_relay,
    case_a_refused_restart_keeps_its_reason_on_screen,
    case_a_restart_that_never_returns_keeps_its_warning,
    case_a_successful_load_clears_a_stale_error,
)
