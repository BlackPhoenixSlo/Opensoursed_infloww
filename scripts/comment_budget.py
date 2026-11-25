#!/usr/bin/env python3
"""Comment + docstring line budget per file (owner rule: no comments unless the why is non-obvious).

  scripts/comment_budget.py [--report [DIR]] [--json]   totals per top-level dir (default)
  scripts/comment_budget.py --check           fail if any file grew, a new file has comments, or a file is unparsed
  scripts/comment_budget.py --lower [PATH...] shrink budgets to current counts (never raises), drop deleted files
  scripts/comment_budget.py --allow FILE --reason "..."   raise FILE's budget to its count
  scripts/comment_budget.py --rebaseline      initialize scripts/comment-budget.json (--force to replace)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from dataclasses import replace

from comment_lang import (ROOT, PyContext, blobs, git, is_candidate, lang_of,
                          py_context_at, read_text, scan_files, source_langs, tracked)

BUDGET = ROOT / "scripts" / "comment-budget.json"
BUDGET_REL = "scripts/comment-budget.json"

TEACHER = ("Comment added in {loc}. Rename/extract instead; history goes in the commit msg; only a "
           "one-line non-obvious why (OF quirk, owner decision, invariant) is allowed — add it to the "
           "budget with `scripts/comment_budget.py --allow {file} --reason \"...\"` and say why in the PR.")


def load_budget(text: str | None = None, where: str = BUDGET_REL) -> dict:
    if text is None and BUDGET.exists():
        text = BUDGET.read_text()
    try:
        b = json.loads(text) if text else {}
    except ValueError as e:
        raise SystemExit(f"{where}: invalid JSON: {e}")
    files, allow = (b.get("files", {}), b.get("allow", {})) if isinstance(b, dict) else (None, None)
    bad = [] if isinstance(files, dict) and isinstance(allow, dict) else ["files/allow must be objects"]
    if not bad:
        bad += [f"files[{p!r}] = {n!r}: not a non-negative integer" for p, n in files.items()
                if type(n) is not int or n < 0]
        bad += [f"allow[{p!r}] = {r!r}: reason must be a non-blank string" for p, r in allow.items()
                if not isinstance(r, str) or not r.strip()]
    if bad:
        raise SystemExit(f"{where}: invalid budget manifest:\n  " + "\n  ".join(bad))
    return {"files": files, "allow": allow}


def save_budget(b: dict) -> None:
    b["files"] = dict(sorted((k, v) for k, v in b["files"].items() if v))
    b["allow"] = dict(sorted(b["allow"].items()))
    b["total"] = sum(b["files"].values())
    BUDGET.write_text(json.dumps(b, indent=1, ensure_ascii=False) + "\n")


def counts(paths: list[str]):
    return _counts({p: read_text(p) for p in paths}, py_context_at(None, untracked=True))


def _counts(texts: dict[str, str], ctx: PyContext):
    ctx = replace(ctx, all_docs=False)
    langs, errors = source_langs(texts)
    scans, scan_errors = scan_files({p: (lang, texts[p]) for p, lang in langs.items()}, ctx)
    errors.update(scan_errors)
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


def _norm(reason: str | None) -> str:
    return " ".join((reason or "").split()).casefold()


def _changed_paths(base_rev: str) -> dict[str, str | None]:
    fields = iter(git("diff", "-M", "--name-status", "-z", base_rev, "--").split("\0")[:-1])
    changed = {}
    for status in fields:
        old = next(fields)
        path = next(fields) if status.startswith(("R", "C")) else old
        changed[path] = None if status.startswith(("A", "C")) else old
    return changed


def _base_counts(base_rev, candidates):
    paths = sorted({p for p in candidates if p and is_candidate(p)})
    texts = {p: t for p, t in blobs(base_rev, [p for p in paths if "\n" not in p]).items() if lang_of(p, t)}
    ctx = py_context_at(base_rev) if any(
        lang_of(p, t) == "py" for p, t in texts.items()) else PyContext()
    actual, _, errors = _counts(texts, ctx)
    errors.update((p, "newline in path") for p in paths if "\n" in p)
    return actual, errors


def growth(base_rev: str, head: dict, actual: dict[str, int]) -> int:
    if subprocess.run(["git", "cat-file", "-e", f"{base_rev}:{BUDGET_REL}"], cwd=ROOT,
                      capture_output=True).returncode != 0:
        print(f"no {BUDGET_REL} in {base_rev}: growth check passes")
        return 0
    base = load_budget(git("show", f"{base_rev}:{BUDGET_REL}"), f"{base_rev}:{BUDGET_REL}")
    changed = _changed_paths(base_rev)

    def old_path(p: str) -> str | None:
        return changed.get(p, p)

    def old_budget(p: str) -> int:
        return base["files"].get(old_path(p), 0)

    def new_reason(p: str) -> bool:
        return p in head["allow"] and _norm(head["allow"][p]) != _norm(base["allow"].get(old_path(p)))

    changed.update(dict.fromkeys(actual.keys() - changed.keys() - set(tracked())))
    raised = {p for p, n in head["files"].items() if n > old_budget(p)}
    candidates = {p for p in changed if actual.get(p, 0)
                  and not (new_reason(p) and actual[p] == head["files"].get(p))}
    previous, errors = _base_counts(base_rev, (changed[p] for p in candidates))
    bad = []
    for p in sorted(raised | candidates):
        old, limit, n = old_path(p), head["files"].get(p, 0), actual.get(p)
        reason = new_reason(p)
        if p in raised and p in changed and not reason:
            bad.append(f"{p}: budget {old_budget(p)}→{limit} without a new --allow reason")
        elif p in raised and n != limit:
            bad.append(f"{p}: budget {limit} ≠ current count {n}; use --allow")
        elif old in errors:
            bad.append(f"unparsed at base: {old}: {errors[old]}")
        elif p in candidates and n > previous.get(old, 0):
            if reason:
                bad.append(f"{p}: budget {limit} ≠ current count {n}; use --allow")
            else:
                bad.append(f"{p}: grew from {previous.get(old, 0)} to {n} comment lines "
                           "without a new --allow reason")
        elif p in raised and p not in changed and not reason:
            print(f"recount {p}: {old_budget(p)}→{limit}, file unchanged since {base_rev}")
    if bad:
        print("\n".join(bad), file=sys.stderr)
        return 1
    print("comment budget growth OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true")
    g.add_argument("--lower", nargs="*", metavar="PATH")
    g.add_argument("--allow", metavar="FILE")
    g.add_argument("--rebaseline", action="store_true")
    g.add_argument("--report", nargs="?", const="", default=None, metavar="DIR")
    ap.add_argument("--reason")
    ap.add_argument("--force", action="store_true", help="replace an existing baseline with --rebaseline")
    ap.add_argument("--json", action="store_true", help="with --report: per-file counts as JSON")
    a = ap.parse_args()
    if a.reason and not a.allow:
        ap.error("--reason needs --allow")

    if a.force and not a.rebaseline:
        ap.error("--force needs --rebaseline")
    exists = BUDGET.exists()
    budget = load_budget()

    if a.allow:
        if not (a.reason or "").strip():
            ap.error("--allow needs a non-blank --reason")
        c, err = {}, {}
        if a.allow in tracked([a.allow], untracked=True):
            c, _, err = counts([a.allow])
        if a.allow not in c:
            print(err.get(a.allow, f"{a.allow}: not a source file"), file=sys.stderr)
            return 1
        budget["files"][a.allow] = c[a.allow]
        budget["allow"][a.allow] = a.reason
        save_budget(budget)
        print(f"{a.allow}: budget {c[a.allow]} ({a.reason})")
        return 0

    if a.lower is not None:
        c, _, _ = counts([p for p in tracked(untracked=True) if in_scope(p, a.lower)])
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

    base_rev = None
    if a.check and exists:
        ref = os.environ.get("COMMENT_BASE") or "origin/main"
        try:
            base_rev = git("merge-base", "--", "HEAD", ref).strip()
        except subprocess.CalledProcessError:
            print(f"comment budget: cannot resolve merge base of HEAD and {ref!r}", file=sys.stderr)
            return 1

    c, scans, errors = counts(tracked(untracked=True))

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
        if base_rev and growth(base_rev, budget, c):
            return 1
        print(f"comment budget OK: {sum(c.values())} lines (budget {sum(budget['files'].values())})")
        return 0

    if a.rebaseline:
        if exists and not a.force:
            print(f"{BUDGET_REL} already exists; use --lower, --allow, or --rebaseline --force", file=sys.stderr)
            return 1
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
