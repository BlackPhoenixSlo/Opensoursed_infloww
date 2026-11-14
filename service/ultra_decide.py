"""service/ultra_decide.py — Ultra plans, pure (docs/plans/ultra-mode/issues/06-ultra-loop.md, 05, 13).

A plan = {summary, steps:[{id, tool, args}]}, each step a Toolbox tool (read, write or send) with every arg
pinned. A send step's args are literal, all of them: any value that looks like a reference is refused, so
the card shows exactly what OnlyFans gets (read first, then propose the literal ids). Only a non-send step's
arg may be a reference `"$<step>.<path>"` (a whole string value) to an EARLIER step's result (path: dotted
keys, digits index a list), e.g. `"list_id": "$folder.id"`, never its `account_id`. Validation records each
reference's location in the step (`refs`); nothing else is ever filled. A judge step (no `tool`;
ultra_judge_decide) picks media ids from one Creator's vault_search results; a send's media may be the whole value
"$<judge>.ids". Any step using a judge's picks must carry that Creator's account_id (bio_page_background may take
"$<judge>.ids.0" from a pick_n 1 judge: its page's Creator is checked at run time, owner_check). A rule send's
folder (ts.FOLDER_ARG) may be "$<earlier of_folder_create step>.id" on its own account_id; no other send ref.

  validate_plan   raw → Plan, or PlanError naming each bad step/field (a step's null keys dropped first;
                  unknown tool, args the tool's pydantic model refuses, bad / forward / self references, a
                  reference in a send step, Creators not the owner's, a step after a rule send: RULES_LAST)
  resolve         a recorded reference → its value in the earlier results (KeyError "$step.path": missing)
  substitute      a step's args with its recorded references filled from earlier results (KeyError: missing)
  started         a step's state just before its call (a send's filled refs as `resolved`, for may_send)
  owner_check     the row a step names whose Creator the executor reads before the call (PAGE_PICK's page)
  digest          sha256 over the canonical post-chain plan: what the owner's OK must echo
  plan_path       the app page of a plan (/ultra/plans/<id>): MCP open_url and the end notification's link
  outcome         a step's call result → done | failed | uncertain (a send that may have gone out, a write with
                  no answer)
  error_text      a failed call's error detail → one plain sentence ("OnlyFans answered 500: …"), capped
  step_end        a step's call result → its stored state {id, state, open_url, error?, result?, note?}
  may_send        whether a send call is a `started` step of a `running` plan, with that step's tool and args
  close           a run's states once it stopped: started → uncertain, pending → skipped (end, crash, restart)
  (what the owner reads — the card, the end line: ultra_card)
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
import ultra_judge_decide as uj
from ultra_schema import MAX_STEPS, MAX_SUMMARY, TOOL_KEYS

OK_TTL = timedelta(minutes=10)  # awaiting_ok → expired
OK_TTL_TEXT = f"{int(OK_TTL.total_seconds() // 60)} minutes"  # how tool descriptions say it
STEP_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
REF = re.compile(r"^\$([a-z][a-z0-9_]{0,31})\.([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)$")
# What a reader could take for a reference ("$x.y", " $x.y"): refused anywhere in a send step. "$5 off" is text.
LOOKS_REF = re.compile(r"^\s*\$[A-Za-z_][A-Za-z0-9_]*\.")
SEND_LITERAL = ("a send step takes literal values only (no $step.path; media_files may be \"$<judge step>.ids\", "
                "a rule's folder \"$<earlier of_folder_create step>.id\"): read first, then propose the literal value")
FOLDER_MAKER = "of_folder_create"  # the step whose result id a rule's folder arg (ts.FOLDER_ARG) may take
# The one step a judge's single pick may fill ("$<judge>.ids.0"): tool, that arg, and the arg naming the bio page
# whose Creator must be the judge's (owner_check).
PAGE_PICK = ("bio_page_background", "media_id", "pid")
TOOLS = {t.name: t for t in td.TOOLS}
RULES_LAST = ("auto_mass / auto_story switch on a rule that starts at once, so they are the plan's last steps "
              "(only other auto_mass / auto_story steps may follow)")

# Plan status: awaiting_ok → running → done | failed | cancelled | interrupted; awaiting_ok → expired | cancelled.
# In-app plans start `planning` (the model reads, then submits); `capped` = it hit a turn/spend cap first.
# A confirm judge parks a run `needs_you` until the owner's pick (→ running) or cancel.
PlanStatus = Literal["planning", "awaiting_ok", "running", "needs_you", "done", "failed", "cancelled", "interrupted",
                     "expired", "capped"]
FINAL: frozenset[PlanStatus] = frozenset({"done", "failed", "cancelled", "interrupted", "expired", "capped"})
RUN_LIVE: frozenset[PlanStatus] = frozenset({"running", "needs_you"})  # approved, its executor still going
LIVE: frozenset[PlanStatus] = RUN_LIVE | {"planning"}  # a background task owns it: a relay start interrupts it
# Step state: pending → started → done | failed | uncertain; pending → skipped (the run stopped first).
StepState = Literal["pending", "started", "needs_you", "done", "failed", "uncertain", "skipped"]


class PlanError(Exception):
    """Refused plan: one {step, field, error} per problem (step "" = the plan itself)."""

    def __init__(self, errors: list[dict[str, str]]):
        super().__init__("; ".join(f"{e['step'] or 'plan'}.{e['field']}: {e['error']}" for e in errors))
        self.errors = errors


@dataclass(frozen=True)
class Plan:
    summary: str
    steps: tuple[dict[str, Any], ...]  # {id, tool, args, refs?} | judge; refs: [{at: [key|index…], step, path}]

    def as_json(self) -> dict[str, Any]:
        return {"summary": self.summary, "steps": [dict(s) for s in self.steps]}

    def raw(self) -> dict[str, Any]:
        """The plan as a client would propose it (no recorded refs): validate_plan's input."""
        return {"summary": self.summary, "steps": [{k: v for k, v in s.items() if k != "refs"} for s in self.steps]}


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


def _ref(value: Any) -> tuple[str, str] | None:
    """A whole-string reference "$<step>.<path>" → (step, path); anything else None."""
    m = REF.match(value) if isinstance(value, str) else None
    return (m.group(1), m.group(2)) if m else None


def _judged(sid: str, tool: td.Tool, args: Mapping[str, Any], judges: set[str],
            seen: Mapping[str, Mapping[str, Any]]) -> list[dict[str, str]]:
    """A step using judges' picks must be on each judge's Creator: its literal account_id is theirs (a bio page
    background: its page's Creator, checked at run time, owner_check)."""
    if tool.name == PAGE_PICK[0]:
        return []
    if "account_id" not in tool.args.model_fields:
        return [_err(sid, "args", "a judge step's picks go only to a step with an account_id (its Creator)")]
    want = {j: uj.account(seen[j], seen) for j in sorted(judges)}
    return [_err(sid, "account_id", f"must be {a!r}: the Creator judge step {j!r} picks from")
            for j, a in want.items() if a is not None and args.get("account_id") != a]


def _folder_ref(r: tuple[str, str], seen: Mapping[str, Mapping[str, Any]], args: Mapping[str, Any]) -> str | None:
    """Why a rule's folder reference is refused (None: it is an earlier FOLDER_MAKER step's id, same Creator)."""
    src = seen.get(r[0]) or {}
    if src.get("tool") == FOLDER_MAKER and r[1] == "id" and src["args"].get("account_id") == args.get("account_id"):
        return None
    return f"a literal folder id, or \"$<earlier {FOLDER_MAKER} step>.id\" with this step's account_id"


def _judge_path(tool: td.Tool, loc: tuple, path: str, judge: Mapping[str, Any]) -> bool:
    """A judge's result in a non-send step: "ids" (its list); as PAGE_PICK's arg only "ids.0" (its one pick, pick_n
    1): that arg holds one id."""
    if (tool.name, *loc) == PAGE_PICK[:2]:
        return path == "ids.0" and judge.get("pick_n") == 1
    return path == "ids"


def _defaults(tool: td.Tool, args: Mapping[str, Any]) -> dict[str, Any]:
    """A send's args with every omitted field's default written in: the stored plan, its sha, the card and the
    request all carry the same explicit values."""
    return {**{k: f.get_default(call_default_factory=True) for k, f in tool.args.model_fields.items()
               if not f.is_required()}, **args}


def _check_step(raw: Any, seen: dict[str, dict[str, Any]],
                owned: frozenset[str]) -> tuple[dict[str, Any] | None, list]:
    """`seen`: earlier step id → its checked step."""
    if not isinstance(raw, Mapping) or ("tool" in raw and set(raw) - TOOL_KEYS):
        return None, [_err("", "steps", "each step is {id, tool, args} or a judge {id, question, candidates, pick_n, "
                                        "confirm}")]
    sid, name, args = raw.get("id"), raw.get("tool"), raw.get("args", {})
    if not isinstance(sid, str) or not STEP_ID.match(sid):
        return None, [_err(str(sid), "id", "a step id is 1-32 of a-z 0-9 _, starting with a letter")]
    if sid in seen:
        return None, [_err(sid, "id", "duplicate step id")]
    if uj.is_judge(raw):
        cands = raw.get("candidates")
        step, errs = uj.check(raw, sid, seen, [_ref(v) for v in (cands if isinstance(cands, list) else [cands])])
        return step, [_err(sid, f, e) for f, e in errs]
    tool = TOOLS.get(name) if isinstance(name, str) else None
    if tool is None:
        return None, [_err(sid, "tool", f"unknown tool {name!r}")]
    if not isinstance(args, Mapping):
        return None, [_err(sid, "args", "must be an object")]
    errors, ref_locs, refs, judges = [], [], [], set()
    is_judge = lambda name: name in seen and uj.is_judge(seen[name])  # noqa: E731
    folder = ts.FOLDER_ARG.get(tool.name)
    for loc, value in _strings(args):
        field, r = ".".join(map(str, loc)), _ref(value)
        if tool.effect == "send":
            if (loc == (uj.SEND_ARG,) and uj.SEND_ARG in tool.args.model_fields and r
                    and is_judge(r[0]) and r[1] == "ids"):
                ref_locs.append(loc)  # a judge's picks as the whole media value
                refs.append({"at": list(loc), "step": r[0], "path": "ids"})
                judges.add(r[0])
            elif loc == (folder,) and r:  # a rule's folder: the id an earlier step made
                ref_locs.append(loc)
                if why := _folder_ref(r, seen, args):
                    errors.append(_err(sid, field, why))
                else:
                    refs.append({"at": list(loc), "step": r[0], "path": "id"})
            elif LOOKS_REF.match(value):
                errors.append(_err(sid, field, SEND_LITERAL))
                ref_locs.append(loc)
            continue
        if not r:
            continue
        ref_locs.append(loc)
        if loc[0] == "account_id":
            errors.append(_err(sid, field, "must be a literal value, not a reference"))
        elif r[0] not in seen:
            errors.append(_err(sid, field, f"references step {r[0]!r}, which does not run before this one"))
        elif is_judge(r[0]) and not _judge_path(tool, loc, r[1], seen[r[0]]):
            errors.append(_err(sid, field, f"a judge step's result is \"${r[0]}.ids\" (\"${r[0]}.ids.0\": its one "
                                           f"pick, pick_n 1, only as {'.'.join(PAGE_PICK[:2])})"))
        else:
            refs.append({"at": list(loc), "step": r[0], "path": r[1]})
            if is_judge(r[0]):
                judges.add(r[0])
    if judges:
        errors += _judged(sid, tool, args, judges, seen)
    try:
        tool.args.model_validate(dict(args))
    except ValidationError as e:
        for x in e.errors():
            loc = tuple(x["loc"])
            # A reference's type is checked at run time (toolbox.call validates the filled args before any
            # request); a field holding one also skips the model's cross-field checks until then.
            if not any(loc[:len(r)] == r for r in ref_locs if r):
                errors.append(_err(sid, ".".join(map(str, loc)) or "args", x["msg"]))
    if tool.effect == "send" and any(x["at"] == [uj.SEND_ARG] for x in refs) and args.get("previews"):
        errors.append(_err(sid, "previews", "must be empty when media_files is a judge step's picks"))
    aid = args.get("account_id")
    if isinstance(aid, str) and aid not in owned:
        errors.append(_err(sid, "account_id", "not one of your Creators"))
    step = {"id": sid, "tool": tool.name, "args": _defaults(tool, args) if tool.effect == "send" else dict(args)}
    return ({**step, "refs": refs} if refs else step), errors


def _normal(raw: Any) -> Any:
    """A step as the schema lets a client send it (ultra_schema.PlanStep: every key optional, nullable): a key
    set to null is left out, and a step with no tool drops an empty `args` (a judge). Nothing else changes."""
    if not isinstance(raw, Mapping):
        return raw
    out = {k: v for k, v in raw.items() if v is not None}
    if "tool" not in out and out.get("args") == {}:
        del out["args"]
    return out


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
    out, seen = [], {}
    for raw_step in steps:
        step, errs = _check_step(_normal(raw_step), seen, owned)
        errors += errs
        if step is not None:
            out.append(step)
            seen[step["id"]] = step
    first = next((i for i, s in enumerate(out) if s.get("tool") in ts.RULE_KIND), None)
    if first is not None and (after := [s["id"] for s in out[first:] if s.get("tool") not in ts.RULE_KIND]):
        errors.append(_err(out[first]["id"], "tool", f"{RULES_LAST}: move {', '.join(after)} before it"))
    if errors:
        raise PlanError(errors)
    return Plan(summary.strip(), tuple(out))


def resolve(ref: Mapping[str, Any], results: Mapping[str, Any]) -> Any:
    """A recorded reference {step, path} → the value at `path` in that step's result (path: dotted keys, digits
    index a list); KeyError("$step.path") when absent."""
    obj, name = results.get(ref["step"]), f"${ref['step']}.{ref['path']}"
    if ref["step"] not in results:
        raise KeyError(name)
    for part in ref["path"].split("."):
        if isinstance(obj, list) and part.isdigit() and int(part) < len(obj):
            obj = obj[int(part)]
        elif isinstance(obj, Mapping) and part in obj:
            obj = obj[part]
        else:
            raise KeyError(name)
    return obj


def substitute(step: Mapping[str, Any], results: Mapping[str, Any]) -> dict[str, Any]:
    """`step`'s args with each reference validation recorded (`refs`) filled from the earlier step's result at its
    path (KeyError "$step.path" when absent). No string is re-read: a value only looking like a reference stays
    as written."""
    args = copy.deepcopy(dict(step["args"]))
    for r in step.get("refs", ()):
        value = resolve(r, results)
        *head, last = r["at"]
        node = args
        for k in head:
            node = node[k]
        node[last] = value
    return args


def started(step: Mapping[str, Any], args: Mapping[str, Any]) -> dict[str, Any]:
    """A tool step's state just before its call. A send records each filled reference's value (`resolved`:
    judge media, a made folder's id), which may_send checks against the source step's stored result."""
    out: dict[str, Any] = {"id": step["id"], "state": "started"}
    if TOOLS[step["tool"]].effect == "send" and step.get("refs"):
        out["resolved"] = {r["at"][0]: args[r["at"][0]] for r in step["refs"]}
    return out


@dataclass(frozen=True)
class OwnerCheck:
    """Before a step's call the row `ref` of `kind` (ultra_run reads its account_id) must be on Creator `want`;
    else the step fails with `refused`."""
    kind: Literal["bio_page"]
    ref: Any
    want: str

    @property
    def refused(self) -> str:
        return f"bio page {self.ref} is not on the Creator ({self.want}) the AI pick came from"


def owner_check(step: Mapping[str, Any], args: Mapping[str, Any],
                steps: Mapping[str, Mapping[str, Any]]) -> OwnerCheck | None:
    """A PAGE_PICK step using a judge's pick (`args`: its filled args): its bio page must be on the judge's Creator;
    None: nothing to check."""
    if step.get("tool") != PAGE_PICK[0]:
        return None
    judges = [steps[r["step"]] for r in step.get("refs", ()) if uj.is_judge(steps[r["step"]])]
    want = uj.account(judges[0], steps) if judges else None
    return None if want is None else OwnerCheck("bio_page", args.get(PAGE_PICK[2]), want)


def plan_path(plan_id: str) -> str:
    return f"/ultra/plans/{plan_id}"


def digest(plan_json: Mapping[str, Any]) -> str:
    canon = json.dumps(plan_json, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode()).hexdigest()


def outcome(effect: str, result: Mapping[str, Any] | None) -> StepState:
    """A step's call result (None = it raised, timed out or the connection dropped) → its end state.
    A send that may have reached OnlyFans (no answer, a 5xx, or a 2xx failing its echo check: 502) is
    `uncertain`, never retried; a 4xx refused it. A write with no answer may still finish: `uncertain` too.
    Any other failure is `failed`."""
    status = None if result is None else (result.get("error") or {}).get("status")
    if result is not None and status is None:
        return "done"
    if effect == "send" and (status is None or status >= 500):
        return "uncertain"
    if effect == "write" and result is None:
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


def step_end(step_id: str, effect: str, result: Mapping[str, Any] | None,
             resolved: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """A step's call result (None = no answer) → its stored state: {id, state, open_url, error?, result?, note?,
    resolved?}. `result` = {id}: the id a done step made (a send's OnlyFans mass message / post id), so it can be
    found again; only a short scalar, never the body. `note`: a done mass that went to fewer fans than approved
    (toolbox_sends.kept_note). `resolved`: the started state's (started), kept."""
    state = outcome(effect, result)
    out: dict[str, Any] = {"id": step_id, "state": state, "open_url": (result or {}).get("open_url")}
    if resolved:
        out["resolved"] = dict(resolved)
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
    before the call), with exactly the tool and the literal args that step holds. A filled reference (judge media,
    a made folder's id): the value in its source step's `done` result, which the started state's `resolved`
    repeats (the executor writes both first)."""
    step = next((s for s in plan_json.get("steps", ()) if s.get("id") == step_id), None)
    by_id = {s.get("id"): s for s in states}
    state = by_id.get(step_id) or {}
    if not (status == "running" and state.get("state") == "started" and step is not None
            and step.get("tool") == tool):
        return False
    want = copy.deepcopy(dict(step.get("args", {})))
    for r in step.get("refs", ()):
        src = by_id.get(r["step"]) or {}
        try:
            value = resolve(r, {r["step"]: src.get("result")}) if src.get("state") == "done" else None
        except KeyError:
            return False
        if value is None or (state.get("resolved") or {}).get(r["at"][0]) != value:
            return False
        want[r["at"][0]] = value
    return want == dict(args)


def initial_states(plan: Plan) -> list[dict[str, Any]]:
    return [{"id": s["id"], "state": "pending"} for s in plan.steps]


def close(states: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A stopped run's states: a `started` step got no clear end (`uncertain`), a `pending` one never ran
    (`skipped`). The executor's end (normal or crashed), a cancel of a lost run and a relay start all use it."""
    after = {"started": "uncertain", "pending": "skipped", "needs_you": "skipped"}
    return [{**s, "state": after.get(s["state"], s["state"])} for s in states]


def expired(status: PlanStatus, created_at: datetime, now: datetime) -> bool:
    return status == "awaiting_ok" and now - created_at > OK_TTL


def recovered(status: PlanStatus, states: list[dict[str, Any]]) -> tuple[PlanStatus, list[dict[str, Any]]]:
    """A relay start: a `running` / `needs_you` plan is `interrupted`, a `started` step `uncertain`, a `pending`
    (or `needs_you`) one `skipped`; a `planning` one is `interrupted` too (its loop died); no resume."""
    if status == "planning":
        return "interrupted", states
    return ("interrupted", close(states)) if status in RUN_LIVE else (status, states)
