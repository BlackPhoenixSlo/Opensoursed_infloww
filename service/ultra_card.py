from __future__ import annotations

import copy
import json
from typing import Any, Mapping

import toolbox_decide as td
import toolbox_sends as ts
import ultra_decide as ud
import ultra_judge_decide as uj

def _shown(step: Mapping[str, Any]) -> dict[str, Any]:
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
    return tool.title or " ".join("OF" if w == "of" else w.capitalize() for w in tool.name.split("_"))


def card(plan: ud.Plan, names: Mapping[str, str]) -> list[dict[str, Any]]:
    out, by_id = [], {s["id"]: s for s in plan.steps}
    for s in plan.steps:
        if uj.is_judge(s):
            out.append({"id": s["id"], "tool": uj.JUDGE, "effect": uj.JUDGE, "title": "AI pick",
                        "rows": uj.card_rows(s)})
            continue
        t, a = ud.TOOLS[s["tool"]], s["args"] if ud.TOOLS[s["tool"]].effect == "send" else _shown(s)
        aid = a.get("account_id")
        creator = (f"{names[aid]} ({aid})" if aid in names else aid) if aid else None
        rows: list[list[str]] = [["Creator", str(creator)]] if creator else []
        entry: dict[str, Any] = {"id": s["id"], "tool": t.name, "effect": t.effect, "title": title(t)}
        if t.effect == "send":
            shown: dict[str, Any] = {}
            for r in s.get("refs", ()):
                src, arg = by_id[r["step"]], r["at"][0]
                if arg == uj.SEND_ARG:
                    shown[arg] = uj.media_row(src)
                elif arg == ts.FOLDER_ARG.get(t.name):
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
    done = sum(s["state"] == "done" for s in states)
    odd = [f"{s['id']} {s['state']}" for s in states if s["state"] in ("failed", "uncertain")]
    tail = f"; {', '.join(odd)}" if odd else ""
    return f"Ultra plan {status}: {summary} ({done} of {len(states)} steps done{tail})"
