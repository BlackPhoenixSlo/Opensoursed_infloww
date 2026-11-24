#!/usr/bin/env python3
"""Prove a diff only removed/edited comments: code identical per changed file.

  scripts/comment_equality.py <base> [<head>]   head defaults to the working tree

py: ast.dump with prunable docstrings stripped (runtime docstrings, from base and head repo-wide
context, count as code); ts/tsx/js: TypeScript AST walk (JSX whitespace per React) + removeComments
printer; sh: bash -n + shfmt AST without positions/comments. Allowlisted comments must stay
byte-identical at the same code position; line endings, BOM and file modes unchanged; only
modified tracked files. Exit 1 on anything else.
"""
from __future__ import annotations

import argparse
import subprocess
import sys

from comment_lang import (JS_EXTS, blobs, encode, git, is_source, line_kinds, pmap, py_code, py_context,
                          py_scan, read_text, scan_files, sh_ast, sh_scan, state, texts_at, PyContext)

SKIP = {"scripts/comment-budget.json", "docs/comment-prune.md"}


def diff_raw(base: str, head: str | None) -> list[tuple[str, str, str, str]]:
    parts = git("diff", "--raw", "-z", "--no-renames", base, *([head] if head else [])).split("\0")
    out = []
    for i in range(0, len(parts) - 1, 2):
        meta, path = parts[i], parts[i + 1]
        if not meta:
            continue
        ma, mb, _, _, st = meta.lstrip(":").split()
        out.append((ma, mb, st, path))
    return out


def _common(a: str, b: str) -> str | None:
    ka = line_kinds(a)
    if len(ka) > 1 and a != b:
        return "mixed line endings: edit by hand"
    if not line_kinds(b) <= ka:
        return "line endings changed"
    if a.startswith("﻿") != b.startswith("﻿"):
        return "BOM changed"
    return None


def check_native(p: str, a: str, b: str, ctx_a: PyContext, ctx_b: PyContext) -> str | None:
    err = _common(a, b)
    if err:
        return err
    if p.endswith(".py"):
        sa, sb = py_scan(p, a, ctx_a), py_scan(p, b, ctx_b)
        keep = None if sa.protected is None or sb.protected is None else sa.protected | sb.protected
        if py_code(a, keep) != py_code(b, keep):
            return "python AST differs (docstrings stripped)"
    else:
        if subprocess.run(["bash", "-n"], input=encode(b), capture_output=True).returncode != 0 \
                and subprocess.run(["bash", "-n"], input=encode(a), capture_output=True).returncode == 0:
            return "bash -n fails on head"
        sa, sb = sh_scan(p, a), sh_scan(p, b)
        if sh_ast(p, a) != sh_ast(p, b):
            return "shell code differs (shfmt AST)"
    if sa.allowed_keys != sb.allowed_keys:
        return "allowlisted comment changed or moved"
    return None


def _native_job(item: tuple[str, str, str]):
    p, a, b = item
    ctx_a, ctx_b = state()
    try:
        return p, check_native(p, a, b, ctx_a, ctx_b)
    except Exception as e:
        return p, f"unparsable: {type(e).__name__}: {e}"


def check_js(pairs: dict[str, tuple[str, str]]) -> dict[str, str]:
    if not pairs:
        return {}
    bad: dict[str, str] = {}
    try:
        da, ea = scan_files({p: a for p, (a, _) in pairs.items()}, PyContext(), "dump")
        db, eb = scan_files({p: b for p, (_, b) in pairs.items()}, PyContext(), "dump")
    except Exception as e:
        return {p: f"TS tool failed: {e}" for p in pairs}
    for p, (a, b) in pairs.items():
        if p not in da or p not in db:
            bad[p] = f"unparsable: {ea.get(p) or eb.get(p)}"
            continue
        x, y = da[p].dump, db[p].dump
        err = _common(a, b)
        if err:
            bad[p] = err
        elif x["sig"] != y["sig"]:
            bad[p] = "TS AST differs"
        elif not p.endswith((".tsx", ".jsx")) and x["printed"] != y["printed"]:
            bad[p] = "TS printer (removeComments) output differs"
        elif da[p].allowed_keys != db[p].allowed_keys:
            bad[p] = "allowlisted comment changed or moved"
    return bad


def check_pairs(pairs: dict[str, tuple[str, str]], ctx_a: PyContext, ctx_b: PyContext) -> dict[str, str]:
    native = [(p, a, b) for p, (a, b) in pairs.items() if not p.endswith(JS_EXTS)]
    bad = {p: e for p, e in pmap(_native_job, native, (ctx_a, ctx_b)) if e}
    bad.update(check_js({p: ab for p, ab in pairs.items() if p.endswith(JS_EXTS)}))
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base")
    ap.add_argument("head", nargs="?")
    a = ap.parse_args()

    fails: dict[str, str] = {}
    if a.head is None:
        for p in git("ls-files", "-z", "--others", "--exclude-standard").split("\0"):
            if p:
                fails[p] = "untracked file"
    paths = []
    for ma, mb, st, p in diff_raw(a.base, a.head):
        if p in SKIP:
            continue
        if st != "M":
            fails[p] = f"status {st}: prune PRs may only modify files"
        elif ma != mb:
            fails[p] = f"mode {ma}→{mb}"
        elif not is_source(p):
            fails[p] = "non-source file changed"
        else:
            paths.append(p)

    pairs: dict[str, tuple[str, str]] = {}
    if paths:
        before = blobs(a.base, paths)
        after = blobs(a.head, paths) if a.head else {p: read_text(p) for p in paths}
        pairs = {p: (before[p], after[p]) for p in paths}
    ctx_a = ctx_b = PyContext()
    if any(p.endswith(".py") for p in paths):
        ctx_a = py_context(list(texts_at(a.base, only_py=True).values()))
        ctx_b = py_context(list(texts_at(a.head, only_py=True).values()))
    bad = check_pairs(pairs, ctx_a, ctx_b)
    fails.update(bad)

    for p, e in sorted(fails.items()):
        print(f"FAIL {p}: {e}", file=sys.stderr)
    print(f"comment equality: {len(pairs) - len(bad)} ok, {len(fails)} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
