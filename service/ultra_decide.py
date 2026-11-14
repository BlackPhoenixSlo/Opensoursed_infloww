"""service/ultra_decide.py — Ultra plans, pure (docs/plans/ultra-mode/issues/06-ultra-loop.md, 05, 13).

A plan = {summary, steps:[{id, tool, args}]}, each step a Toolbox tool (read, write or send) with every arg
pinned. A send step's args are literal, all of them: any value that looks like a reference is refused, so
the card shows exactly what OnlyFans gets (read first, then propose the literal ids). Only a non-send step's
arg may be a reference `"$<step>.<path>"` (a whole string value) to an EARLIER step's result (path: dotted
keys, digits index a list), e.g. `"list_id": "$folder.id"`, never its `account_id`. Validation records each
reference's location in the step (`refs`); nothing else is ever filled.

  validate_plan   raw → Plan, or PlanError naming each bad step/field (unknown tool, args the tool's
                  pydantic model refuses, bad / forward / self references, a reference in a send step,
                  Creators not the owner's)
  substitute      a non-send step's args with its recorded references filled from earlier results (KeyError:
                  missing); a send step's args unchanged
  digest          sha256 over the canonical post-chain plan: what the owner's OK must echo
  plan_path       the app page of a plan (/ultra/plans/<id>): MCP open_url and the end notification's link
  outcome         a step's call result → done | failed | uncertain (a send that may have gone out)
  error_text      a failed call's error detail → one plain sentence ("OnlyFans answered 500: …"), capped
  step_end        a step's call result → its stored state {id, state, open_url, error?, result?, note?}
  may_send        whether a send call is a `started` step of a `running` plan, with that step's tool and args
  close           a run's states once it stopped: started → uncertain, pending → skipped (end, crash, restart)
  card            the plan card's rows, from the steps (never the summary)
  report_text     the end notification's one line, from the step states
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal, Mapping

from pydantic import ValidationError

import toolbox_decide as td
import toolbox_sends as ts

MAX_STEPS = 20
MAX_SUMMARY = 500
OK_TTL = timedelta(minutes=10)  # awaiting_ok → expired
OK_TTL_TEXT = f"{int(OK_TTL.total_seconds() // 60)} minutes"  # how tool descriptions say it
STEP_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
REF = re.compile(r"^\$([a-z][a-z0-9_]{0,31})\.([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)$")
# What a reader could take for a reference ("$x.y", " $x.y"): refused anywhere in a send step. "$5 off" is text.
LOOKS_REF = re.compile(r"^\s*\$[A-Za-z_][A-Za-z0-9_]*\.")
SEND_LITERAL = "a send step takes literal values only (no $step.path): read first, then propose the literal value"
TOOLS = {t.name: t for t in td.TOOLS}

# Plan status: awaiting_ok → running → done | failed | cancelled | interrupted; awaiting_ok → expired | cancelled.
PlanStatus = Literal["awaiting_ok", "running", "done", "failed", "cancelled", "interrupted", "expired"]
FINAL: frozenset[PlanStatus] = frozenset({"done", "failed", "cancelled", "interrupted", "expired"})
# Step state: pending → started → done | failed | uncertain; pending → skipped (the run stopped first).
StepState = Literal["pending", "started", "done", "failed", "uncertain", "skipped"]


class PlanError(Exception):
    """Refused plan: one {step, field, error} per problem (step "" = the plan itself)."""

    def __init__(self, errors: list[dict[str, str]]):
        super().__init__("; ".join(f"{e['step'] or 'plan'}.{e['field']}: {e['error']}" for e in errors))
        self.errors = errors


@dataclass(frozen=True)
class Plan:
    summary: str
    steps: tuple[dict[str, Any], ...]  # {id, tool, args, refs?}; refs: [{at: [key|index…], step, path}]

    def as_json(self) -> dict[str, Any]:
        return {"summary": self.summary, "steps": [dict(s) for s in self.steps]}

    def raw(self) -> dict[str, Any]:
        """The plan as a client would propose it (no recorded refs): validate_plan's input."""
        return {"summary": self.summary, "steps": [{k: s[k] for k in ("id", "tool", "args")} for s in self.steps]}


def _strings(value: Any, loc: tuple = ()) -> list[tuple[tuple, str]]:
    """Every (location, string) inside an args value."""
    if isinstance(value, str):
        return [(loc, value)]
    if isinstance(value, Mapping):
        return [r for k, v in value.items() for r in _strings(v, (*loc, k))]
    if isinstance(value, list):
        return [r for i, v in enumerate(value) for r in _strings(v, (*loc, i))]
    return []


def _err(step: str, field: str, error: str) -> dict[str, str]:
    return {"step": step, "field": field, "error": error}


def _check_step(raw: Any, seen: list[str], owned: frozenset[str]) -> tuple[dict[str, Any] | None, list]:
    if not isinstance(raw, Mapping) or set(raw) - {"id", "tool", "args"}:
        return None, [_err("", "steps", "each step is {id, tool, args}")]
    sid, name, args = raw.get("id"), raw.get("tool"), raw.get("args", {})
    if not isinstance(sid, str) or not STEP_ID.match(sid):
        return None, [_err(str(sid), "id", "a step id is 1-32 of a-z 0-9 _, starting with a letter")]
    if sid in seen:
        return None, [_err(sid, "id", "duplicate step id")]
    tool = TOOLS.get(name) if isinstance(name, str) else None
    if tool is None:
        return None, [_err(sid, "tool", f"unknown tool {name!r}")]
    if not isinstance(args, Mapping):
        return None, [_err(sid, "args", "must be an object")]
    errors, ref_locs, refs = [], [], []
    for loc, value in _strings(args):
        field, m = ".".join(map(str, loc)), REF.match(value)
        if tool.effect == "send":
            if LOOKS_REF.match(value):
                errors.append(_err(sid, field, SEND_LITERAL))
                ref_locs.append(loc)
            continue
        if not m:
            continue
        ref_locs.append(loc)
        if loc[0] == "account_id":
            errors.append(_err(sid, field, "must be a literal value, not a reference"))
        elif m.group(1) not in seen:
            errors.append(_err(sid, field, f"references step {m.group(1)!r}, which does not run before this one"))
        else:
            refs.append({"at": list(loc), "step": m.group(1), "path": m.group(2)})
    try:
        tool.args.model_validate(dict(args))
    except ValidationError as e:
        for x in e.errors():
            loc = tuple(x["loc"])
            # A reference's type is checked at run time (toolbox.call validates the filled args before any
            # request); a field holding one also skips the model's cross-field checks until then.
            if not any(loc[:len(r)] == r for r in ref_locs if r):
                errors.append(_err(sid, ".".join(map(str, loc)) or "args", x["msg"]))
    aid = args.get("account_id")
    if isinstance(aid, str) and aid not in owned:
        errors.append(_err(sid, "account_id", "not one of your Creators"))
    step = {"id": sid, "tool": tool.name, "args": dict(args)}
    return ({**step, "refs": refs} if refs else step), errors


def validate_plan(raw: Any, owned: frozenset[str]) -> Plan:
    """`raw` as a Plan, or PlanError. `owned`: the owner's Creator ids (every step's account_id must be one)."""
    if not isinstance(raw, Mapping):
        raise PlanError([_err("", "plan", "must be an object {summary, steps}")])
    summary, steps = raw.get("summary"), raw.get("steps")
    errors: list[dict[str, str]] = []
    if not isinstance(summary, str) or not summary.strip() or len(summary) > MAX_SUMMARY:
        errors.append(_err("", "summary", f"a non-empty string of at most {MAX_SUMMARY} characters"))
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise PlanError([*errors, _err("", "steps", f"a list of 1 to {MAX_STEPS} steps")])
    out, seen = [], []
    for raw_step in steps:
        step, errs = _check_step(raw_step, seen, owned)
        errors += errs
        if step is not None:
            out.append(step)
            seen.append(step["id"])
    if errors:
        raise PlanError(errors)
    return Plan(summary.strip(), tuple(out))


def _get(obj: Any, path: str) -> Any:
    for part in path.split("."):
        if isinstance(obj, list) and part.isdigit() and int(part) < len(obj):
            obj = obj[int(part)]
        elif isinstance(obj, Mapping) and part in obj:
            obj = obj[part]
        else:
            raise KeyError(path)
    return obj


def substitute(step: Mapping[str, Any], results: Mapping[str, Any]) -> dict[str, Any]:
    """`step`'s args with each reference validation recorded (`refs`) filled from the earlier step's result at its
    path (KeyError "$step.path" when absent). No string is re-read: a value only looking like a reference stays
    as written. A send step's args come back unchanged (it never has a reference)."""
    args = copy.deepcopy(dict(step["args"]))
    if TOOLS[step["tool"]].effect == "send":
        return args
    for r in step.get("refs", ()):
        ref = f"${r['step']}.{r['path']}"
        if r["step"] not in results:
            raise KeyError(ref)
        try:
            value = _get(results[r["step"]], r["path"])
        except KeyError:
            raise KeyError(ref) from None
        *head, last = r["at"]
        node = args
        for k in head:
            node = node[k]
        node[last] = value
    return args


def plan_path(plan_id: str) -> str:
    return f"/ultra/plans/{plan_id}"


def digest(plan_json: Mapping[str, Any]) -> str:
    canon = json.dumps(plan_json, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode()).hexdigest()


def outcome(effect: str, result: Mapping[str, Any] | None) -> StepState:
    """A step's call result (None = it raised, timed out or the connection dropped) → its end state.
    A send that may have reached OnlyFans (no answer, a 5xx, or a 2xx failing its echo check: 502) is
    `uncertain`, never retried; a 4xx refused it. Any other tool's failure is `failed`."""
    status = None if result is None else (result.get("error") or {}).get("status")
    if result is not None and status is None:
        return "done"
    if effect == "send" and (status is None or status >= 500):
        return "uncertain"
    return "failed"


NO_ANSWER = "no answer (timed out or the connection dropped)"
MAX_ERROR = 500  # characters of a step's error sentence


def _of_message(body: Any) -> str:
    """OnlyFans' own words from its error body ({"error": "…"} / {"error": {"message": "…"}} / {"message": "…"});
    a body that is not JSON as written; a JSON body without a message: nothing."""
    text = str(body or "").strip()
    try:
        data = json.loads(text)
    except ValueError:
        return text
    if not isinstance(data, Mapping):
        return ""
    err = data.get("error")
    msg = err.get("message") if isinstance(err, Mapping) else err
    msg = msg if isinstance(msg, str) and msg.strip() else data.get("message")
    return msg.strip() if isinstance(msg, str) else ""


def error_text(detail: Any) -> str:
    """A failed call's error detail → one plain sentence for the page and plan_status (never a raw dict), at most
    MAX_ERROR characters: OF's {upstream_status, upstream_body} reads "OnlyFans answered 500: <its message>"."""
    if detail is None:
        out = NO_ANSWER
    elif isinstance(detail, Mapping) and "upstream_status" in detail:
        up, msg = detail["upstream_status"], _of_message(detail.get("upstream_body"))
        head = (f"OnlyFans answered {up}" if isinstance(up, int) and not isinstance(up, bool)
                else f"The OnlyFans call failed ({str(up).replace('_', ' ')})")
        out = f"{head}: {msg}" if msg else head
    elif isinstance(detail, Mapping):
        errs = detail.get("errors")
        tail = ("; ".join(f"{k}: {error_text(v)}" for k, v in errs.items()) if isinstance(errs, Mapping)
                else error_text(errs) if errs else "")
        head = error_text(detail["detail"]) if detail.get("detail") is not None else ""
        out = ": ".join(p for p in (head, tail) if p) or json.dumps(detail, ensure_ascii=False, default=str)
    elif isinstance(detail, list):
        out = "; ".join(
            (f"{'.'.join(map(str, x['loc'][1:] if x['loc'][:1] == ['body'] else x['loc']))}: {x.get('msg')}"
             if isinstance(x, Mapping) and isinstance(x.get("loc"), list) else error_text(x)) for x in detail)
    else:
        out = str(detail)
    return " ".join(out.split())[:MAX_ERROR]


def step_end(step_id: str, effect: str, result: Mapping[str, Any] | None) -> dict[str, Any]:
    """A step's call result (None = no answer) → its stored state: {id, state, open_url, error?, result?, note?}.
    `result` = {id}: the id a done step made (a send's OnlyFans mass message / post id), so it can be found
    again; only a short scalar, never the body. `note`: a done mass that went to fewer fans than approved
    (toolbox_sends.kept_note)."""
    state = outcome(effect, result)
    out: dict[str, Any] = {"id": step_id, "state": state, "open_url": (result or {}).get("open_url")}
    if state != "done":
        err = (result or {}).get("error") or {"detail": NO_ANSWER}
        out["error"] = error_text(err.get("detail"))
    else:
        if isinstance(rid := result.get("id"), (int, str)) and not isinstance(rid, bool) and len(str(rid)) <= 64:
            out["result"] = {"id": rid}
        if effect == "send" and (note := ts.kept_note(result)):
            out["note"] = note
    return out


def may_send(plan_json: Mapping[str, Any], status: PlanStatus, states: list[dict[str, Any]], step_id: str, tool: str,
             args: Mapping[str, Any]) -> bool:
    """A send runs only as the `started` step `step_id` of a `running` plan (the executor writes `started` just
    before the call), with exactly the tool and the literal args that step holds."""
    step = next((s for s in plan_json.get("steps", ()) if s.get("id") == step_id), None)
    state = next((s.get("state") for s in states if s.get("id") == step_id), None)
    return (status == "running" and state == "started" and step is not None and step.get("tool") == tool
            and step.get("args") == dict(args))


def initial_states(plan: Plan) -> list[dict[str, Any]]:
    return [{"id": s["id"], "state": "pending"} for s in plan.steps]


def close(states: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A stopped run's states: a `started` step got no clear end (`uncertain`), a `pending` one never ran
    (`skipped`). The executor's end (normal or crashed), a cancel of a lost run and a relay start all use it."""
    after = {"started": "uncertain", "pending": "skipped"}
    return [{**s, "state": after.get(s["state"], s["state"])} for s in states]


def expired(status: PlanStatus, created_at: datetime, now: datetime) -> bool:
    return status == "awaiting_ok" and now - created_at > OK_TTL


def recovered(status: PlanStatus, states: list[dict[str, Any]]) -> tuple[PlanStatus, list[dict[str, Any]]]:
    """A relay start: a `running` plan is `interrupted`, a `started` step `uncertain`, a `pending` one
    `skipped`; no resume."""
    return (status, states) if status != "running" else ("interrupted", close(states))


def _shown(step: Mapping[str, Any]) -> dict[str, Any]:
    """A non-send step's args for the card: each recorded reference reads "from step <id>"; a list arg made only
    of references to one step reads "from step <id>" (one) or "N from step <id>"."""
    args = copy.deepcopy(dict(step["args"]))
    refs = step.get("refs", ())
    for r in refs:
        *head, last = r["at"]
        node = args
        for k in head:
            node = node[k]
        node[last] = f"from step {r['step']}"
    for key, v in args.items():
        mine = [r["step"] for r in refs if len(r["at"]) == 2 and r["at"][0] == key]
        if isinstance(v, list) and v and len(mine) == len(v) and len(set(mine)) == 1:
            args[key] = f"from step {mine[0]}" if len(v) == 1 else f"{len(v)} from step {mine[0]}"
    return args


def title(tool: td.Tool) -> str:
    """A step's card heading: the tool's own title, else its name in Title Case ("of" → "OF")."""
    return tool.title or " ".join("OF" if w == "of" else w.capitalize() for w in tool.name.split("_"))


def card(plan: Plan, names: Mapping[str, str]) -> list[dict[str, Any]]:
    """One card per step: {id, tool, effect, title, rows:[[label, value]], text?}. A send (literal args only)
    shows its Creator, audience with the fan ids, price, media ids, schedule and its FULL text; any other step
    shows every arg (labelled by its name), a reference as "from step <id>"."""
    out = []
    for s in plan.steps:
        t, a = TOOLS[s["tool"]], s["args"] if TOOLS[s["tool"]].effect == "send" else _shown(s)
        creator = names.get(a.get("account_id"), a.get("account_id")) if a.get("account_id") else None
        rows: list[list[str]] = [["Creator", str(creator)]] if creator else []
        entry: dict[str, Any] = {"id": s["id"], "tool": t.name, "effect": t.effect, "title": title(t)}
        if t.effect == "send":
            rows += ts.card_rows(t.text_kind, a)
            entry["text"] = a.get(t.model_text[0], "")
        else:
            rows += [[k, v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)]
                     for k, v in a.items() if k != "account_id"]
        out.append({**entry, "rows": rows})
    return out


def report_text(summary: str, status: PlanStatus, states: list[dict[str, Any]]) -> str:
    """The notification's one line: the plan's status, its summary and how many steps ended done."""
    done = sum(s["state"] == "done" for s in states)
    odd = [f"{s['id']} {s['state']}" for s in states if s["state"] in ("failed", "uncertain")]
    tail = f"; {', '.join(odd)}" if odd else ""
    return f"Ultra plan {status}: {summary} ({done} of {len(states)} steps done{tail})"
