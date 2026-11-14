"""service/ultra_card.py — what the owner reads about an Ultra plan, pure (docs/plans/ultra-mode/issues/06, 13).

  card         one card per step, from the validated steps (never the summary): a send's rows from
               toolbox_sends.card_rows (a judge's picks as its media row, a made folder as "folder created in
               step X"), any other step's args with each reference read "from step <id>", a judge's question
  title        a step's card heading
  report_text  the end notification's one line, from the step states
"""
from __future__ import annotations

import copy
import json
from typing import Any, Mapping

import toolbox_decide as td
import toolbox_sends as ts
import ultra_decide as ud
import ultra_judge_decide as uj

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


def card(plan: ud.Plan, names: Mapping[str, str]) -> list[dict[str, Any]]:
    """One card per step: {id, tool, effect, title, rows:[[label, value]], text?}. A send (literal args only)
    shows its Creator (nickname + account id), audience with every fan id, price, media ids, schedule and its FULL text; any other step
    shows every arg (labelled by its name), a reference as "from step <id>"."""
    out, by_id = [], {s["id"]: s for s in plan.steps}
    for s in plan.steps:
        if uj.is_judge(s):
            out.append({"id": s["id"], "tool": uj.JUDGE, "effect": uj.JUDGE, "title": "AI pick",
                        "rows": uj.card_rows(s)})
            continue
        t, a = ud.TOOLS[s["tool"]], s["args"] if ud.TOOLS[s["tool"]].effect == "send" else _shown(s)
        aid = a.get("account_id")  # nickname + id: two Creators may share a nickname
        creator = (f"{names[aid]} ({aid})" if aid in names else aid) if aid else None
        rows: list[list[str]] = [["Creator", str(creator)]] if creator else []
        entry: dict[str, Any] = {"id": s["id"], "tool": t.name, "effect": t.effect, "title": title(t)}
        if t.effect == "send":
            shown: dict[str, Any] = {}  # a reference's arg → what the card shows for it
            for r in s.get("refs", ()):
                src, arg = by_id[r["step"]], r["at"][0]
                if arg == uj.SEND_ARG:  # media = a judge's picks
                    shown[arg] = uj.media_row(src)
                elif arg == ts.FOLDER_ARG.get(t.name):  # a rule's folder an earlier step makes
                    shown[arg] = f"folder created in step {src['id']} ({_shown(src).get('name')})"
            rows += ts.card_rows(t.text_kind, a, shown)
        else:
            rows += [[k, v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)]
                     for k, v in a.items() if k != "account_id"]
        if t.model_text:
            entry["text"] = a.get(t.model_text[0], "")
        out.append({**entry, "rows": rows})
    return out


def report_text(summary: str, status: ud.PlanStatus, states: list[dict[str, Any]]) -> str:
    """The notification's one line: the plan's status, its summary and how many steps ended done."""
    done = sum(s["state"] == "done" for s in states)
    odd = [f"{s['id']} {s['state']}" for s in states if s["state"] in ("failed", "uncertain")]
    tail = f"; {', '.join(odd)}" if odd else ""
    return f"Ultra plan {status}: {summary} ({done} of {len(states)} steps done{tail})"
