#!/usr/bin/env python3
"""Comment + docstring line budget per file (owner rule: no comments unless the why is non-obvious).

  scripts/comment_budget.py [--report [DIR]] [--json]   totals per top-level dir (default)
  scripts/comment_budget.py --check           fail if any file grew, a new file has comments, or a file is unparsed
  scripts/comment_budget.py --growth BASE     fail if a budget rose since BASE without a new/changed --allow
  scripts/comment_budget.py --lower [PATH...] shrink budgets to current counts (never raises), drop deleted files
  scripts/comment_budget.py --allow FILE --reason "..."   raise FILE's budget to its count
  scripts/comment_budget.py --rebaseline      rewrite scripts/comment-budget.json from the tree
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict

from comment_lang import ROOT, git, py_context, read_text, scan_files, texts_at, tracked

BUDGET = ROOT / "scripts" / "comment-budget.json"
BUDGET_REL = "scripts/comment-budget.json"

TEACHER = ("Comment added in {loc}. Rename/extract instead; history goes in the commit msg; only a "
           "one-line non-obvious why (OF quirk, owner decision, invariant) is allowed — add it to the "
           "budget with `scripts/comment_budget.py --allow {file} --reason \"...\"` and say why in the PR.")


def load_budget(text: str | None = None) -> dict:
    if text is None and BUDGET.exists():
        text = BUDGET.read_text()
    b = json.loads(text) if text else {}
    return {"files": b.get("files", {}), "allow": b.get("allow", {})}


def save_budget(b: dict) -> None:
    b["files"] = dict(sorted((k, v) for k, v in b["files"].items() if v))
    b["allow"] = dict(sorted(b["allow"].items()))
    b["total"] = sum(b["files"].values())
    BUDGET.write_text(json.dumps(b, indent=1, ensure_ascii=False) + "\n")


def counts(paths: list[str]):
    ctx = py_context(list(texts_at(None, only_py=True).values()))
    scans, errors = scan_files({p: read_text(p) for p in paths}, ctx)
    return {p: len(s.lines) for p, s in scans.items()}, scans, errors


def in_scope(p: str, scopes: list[str]) -> bool:
    return not scopes or any(p == s.rstrip("/") or p.startswith(s.rstrip("/") + "/") for s in scopes)


def report(by_file: dict[str, int], prefix: str | None) -> None:
    agg: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for p, n in by_file.items():
        if prefix and not p.startswith(prefix.rstrip("/") + "/"):
            continue
        parts = p.split("/")
        key = "/".join(parts[:(prefix.count("/") + 2) if prefix else 1]) if len(parts) > 1 else "."
        agg[key][0] += n
        agg[key][1] += 1
    for k, (n, f) in sorted(agg.items(), key=lambda kv: -kv[1][0]):
        print(f"{n:8d}  {f:5d} files  {k}")
    print(f"{sum(v[0] for v in agg.values()):8d}  total")


def growth(base_rev: str) -> int:
    git("rev-parse", "--verify", "--quiet", f"{base_rev}^{{commit}}")
    if subprocess.run(["git", "cat-file", "-e", f"{base_rev}:{BUDGET_REL}"], cwd=ROOT,
                      capture_output=True).returncode != 0:
        print(f"no {BUDGET_REL} in {base_rev}: growth check passes")
        return 0
    base = load_budget(git("show", f"{base_rev}:{BUDGET_REL}"))
    head = load_budget()
    bad = [p for p, n in head["files"].items() if n > base["files"].get(p, 0)
           and (p not in head["allow"] or head["allow"][p] == base["allow"].get(p))]
    for p in bad:
        print(f"{p}: budget {base['files'].get(p, 0)}→{head['files'][p]} without a new --allow reason",
              file=sys.stderr)
    if bad:
        return 1
    print("comment budget growth OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true")
    g.add_argument("--growth", metavar="BASE")
    g.add_argument("--lower", nargs="*", metavar="PATH")
    g.add_argument("--allow", metavar="FILE")
    g.add_argument("--rebaseline", action="store_true")
    g.add_argument("--report", nargs="?", const="", default=None, metavar="DIR")
    ap.add_argument("--reason")
    ap.add_argument("--json", action="store_true", help="with --report: per-file counts as JSON")
    a = ap.parse_args()
    if a.reason and not a.allow:
        ap.error("--reason needs --allow")

    if a.growth:
        return growth(a.growth)

    budget = load_budget()

    if a.allow:
        if not a.reason:
            ap.error("--allow needs --reason")
        c, err = {}, {}
        if a.allow in tracked([a.allow]):
            c, _, err = counts([a.allow])
        if a.allow not in c:
            print(err.get(a.allow, f"{a.allow}: not a tracked source file"), file=sys.stderr)
            return 1
        budget["files"][a.allow] = c[a.allow]
        budget["allow"][a.allow] = a.reason
        save_budget(budget)
        print(f"{a.allow}: budget {c[a.allow]} ({a.reason})")
        return 0

    if a.lower is not None:
        c, _, _ = counts([p for p in tracked() if in_scope(p, a.lower)])
        for p in list(budget["files"]):
            if not in_scope(p, a.lower):
                continue
            if not (ROOT / p).is_file():
                del budget["files"][p]
            elif p in c:
                budget["files"][p] = min(budget["files"][p], c[p])
        save_budget(budget)
        print(f"lowered: total {budget['total']}")
        return 0

    c, scans, errors = counts(tracked())

    if a.check:
        fails = []
        for p, n in c.items():
            limit = budget["files"].get(p, 0)
            if n > limit:
                lines = scans[p].lines
                loc = f"{p}:{lines[-1] if lines else '?'}" if limit == 0 else f"{p} ({limit}→{n})"
                fails.append(TEACHER.format(loc=loc, file=p))
        fails += [f"unparsed: {p}: {e}" for p, e in sorted(errors.items())]
        if fails:
            print("\n".join(fails), file=sys.stderr)
            print(f"\ncomment budget: {len(fails)} problem(s)", file=sys.stderr)
            return 1
        print(f"comment budget OK: {sum(c.values())} lines (budget {sum(budget['files'].values())})")
        return 0

    if a.rebaseline:
        budget["files"] = c
        save_budget(budget)
        print(f"budget written: {budget['total']} lines in {len(c)} files; {len(errors)} unparsed")
    elif a.json:
        print(json.dumps(c, indent=0))
    else:
        report(c, a.report or None)
    for p, e in errors.items():
        print(f"unparsed: {p}: {e}", file=sys.stderr)
    return 1 if a.rebaseline and errors else 0


if __name__ == "__main__":
    sys.exit(main())
