#!/usr/bin/env python3
"""Prove each changed file is code-equivalent to base: comments and prunable docstrings may be removed
or edited, nothing else.

  scripts/comment_equality.py <base> [<head>]   head defaults to the working tree

py: ast.dump with prunable docstrings stripped (runtime docstrings, from base and head repo-wide
context, count as code; head must compile); ts/tsx/js: TypeScript AST walk + removeComments
transpile emit (jsx react); sh: bash -n on head + shfmt AST without positions/comments. Files that
read their own source or $LINENO must be unchanged. Allowlisted comments must stay byte-identical,
in order, at the same code position; line endings, BOM and regular file modes unchanged; only
modified tracked files. Exit 1 on anything else.
"""
from __future__ import annotations

import argparse
import io
import subprocess
import sys
import tokenize

from functools import partial

from comment_lang import (REGULAR_MODES, _split_bom, blobs, encode, git, has_bom, is_candidate, lang_of,
                          line_kinds, pmap, py_code, py_context_at, py_scan, read_text, scan_files, sh_ast,
                          sh_scan, PyContext)

SKIP = {"scripts/comment-budget.json", "docs/comment-prune.md"}


def diff_raw(base: str, head: str | None) -> list[tuple[str, str, str, str]]:
    parts = git("diff", "--raw", "-z", "--no-renames", base, *([head] if head else []), "--").split("\0")
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
    if has_bom(a) != has_bom(b):
        return "BOM changed"
    fa, fb = (_split_bom(t)[1].split("\n", 1)[0] for t in (a, b))
    if (fa.lstrip().startswith("#!") or fb.lstrip().startswith("#!")) and fa != fb:
        return "shebang line changed"
    return None


def _frozen(sa, sb, a: str, b: str) -> str | None:
    if (sa.frozen or sb.frozen) and a != b:
        return "file reads its own source or $LINENO at runtime: edit by hand"
    return None


def check_native(p: str, lang: str, a: str, b: str, ctx_a: PyContext, ctx_b: PyContext) -> str | None:
    err = _common(a, b)
    if err:
        return err
    if lang == "py":
        for t in (a, b):
            enc = tokenize.detect_encoding(io.BytesIO(encode(t)).readline)[0]
            if enc not in ("utf-8", "utf-8-sig"):
                return f"encoding {enc}: edit by hand"
        try:
            compile(_split_bom(b)[1], p, "exec", dont_inherit=True)
        except SyntaxError as e:
            return f"head does not compile: {e}"
        sa, sb = py_scan(p, a, ctx_a), py_scan(p, b, ctx_b)
        keep = None if sa.protected is None or sb.protected is None else sa.protected | sb.protected
        differs = py_code(a, keep) != py_code(b, keep) and "python AST differs (docstrings stripped)"
    elif lang == "sh":
        if "\r" in a or "\r" in b:
            return "CR in shell script: edit by hand"
        if subprocess.run(["bash", "-n"], input=encode(b), capture_output=True).returncode != 0:
            return "bash -n fails on head"
        sa, sb = sh_scan(p, a), sh_scan(p, b)
        differs = sh_ast(p, a) != sh_ast(p, b) and "shell code differs (shfmt AST)"
    else:
        return f"not a py/sh source ({lang})"
    err = _frozen(sa, sb, a, b) or differs
    if err:
        return err
    if sa.allowed_keys != sb.allowed_keys:
        return "allowlisted comment changed or moved"
    return None


def _native_job(ctxs: tuple[PyContext, PyContext], item: tuple[str, str, str, str]):
    p, lang, a, b = item
    ctx_a, ctx_b = ctxs
    try:
        return p, check_native(p, lang, a, b, ctx_a, ctx_b)
    except Exception as e:
        return p, f"unparsable: {type(e).__name__}: {e}"


def check_js(pairs: dict[str, tuple[str, str]]) -> dict[str, str]:
    if not pairs:
        return {}
    bad: dict[str, str] = {}
    da, ea = scan_files({p: ("js", a) for p, (a, _) in pairs.items()}, PyContext(), "dump")
    db, eb = scan_files({p: ("js", b) for p, (_, b) in pairs.items()}, PyContext(), "dump")
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
        elif x["emit"] != y["emit"]:
            bad[p] = "TS emit (removeComments) differs"
        elif da[p].allowed_keys != db[p].allowed_keys:
            bad[p] = "allowlisted comment changed or moved"
    return bad


def check_pairs(pairs: dict[str, tuple[str, str, str]], ctx_a: PyContext, ctx_b: PyContext
                ) -> dict[str, str]:
    native = [(p, lang, a, b) for p, (lang, a, b) in pairs.items() if lang != "js"]
    bad = {p: e for p, e in pmap(partial(_native_job, (ctx_a, ctx_b)), native) if e}
    bad.update(check_js({p: (a, b) for p, (lang, a, b) in pairs.items() if lang == "js"}))
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base")
    ap.add_argument("head", nargs="?")
    a = ap.parse_args()

    for arg in ("base", "head"):
        rev = getattr(a, arg)
        if rev is not None:
            try:
                setattr(a, arg, git("rev-parse", "--verify", "--quiet", "--end-of-options",
                                    f"{rev}^{{commit}}").strip())
            except subprocess.CalledProcessError:
                print(f"{arg} {rev!r}: not a commit", file=sys.stderr)
                return 1

    fails: dict[str, str] = {}
    if a.head is None:
        for p in git("ls-files", "-z", "--others", "--exclude-standard").split("\0"):
            if p:
                fails[p] = "untracked file"
    paths = []
    for ma, mb, st, p in diff_raw(a.base, a.head):
        if st != "M":
            fails[p] = f"status {st}: prune PRs may only modify files"
        elif ma != mb:
            fails[p] = f"mode {ma}→{mb}"
        elif ma not in REGULAR_MODES:
            fails[p] = f"mode {ma}: not a regular file"
        elif "\n" in p:
            fails[p] = "newline in path"
        elif p in SKIP:
            continue
        elif not is_candidate(p):
            fails[p] = "non-source file changed"
        else:
            paths.append(p)

    pairs: dict[str, tuple[str, str, str]] = {}
    if paths:
        before = blobs(a.base, paths)
        after = blobs(a.head, paths) if a.head else {p: read_text(p) for p in paths}
        for p in paths:
            la, lb = lang_of(p, before[p]), lang_of(p, after[p])
            if la is None and lb is None:
                fails[p] = "non-source file changed"
            elif la != lb:
                fails[p] = f"language changed {la}→{lb}"
            else:
                pairs[p] = (la, before[p], after[p])
    ctx_a = ctx_b = PyContext()
    if any(lang == "py" for lang, _, _ in pairs.values()):
        ctx_a, ctx_b = py_context_at(a.base), py_context_at(a.head)
    bad = check_pairs(pairs, ctx_a, ctx_b)
    fails.update(bad)

    for p, e in sorted(fails.items()):
        print(f"FAIL {p}: {e}", file=sys.stderr)
    print(f"comment equality: {len(pairs) - len(bad)} ok, {len(fails)} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
