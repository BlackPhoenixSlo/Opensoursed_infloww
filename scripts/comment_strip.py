#!/usr/bin/env python3
"""Strip prunable comments + docstrings from the given files/dirs (allowlist and runtime docstrings
stay). Fails closed: a file whose result fails the equality check is left untouched (LEFT); a
docstring sharing its line with code is kept (PARTIAL); a {/* */} between two JSX texts is kept.

  scripts/comment_strip.py <path>... [--skip-file LIST]... [--pr-repo OWNER/NAME]... [--no-pr-skip]

Skips files touched by open PRs in every GitHub remote's repo plus each --pr-repo, and every path
listed in a --skip-file.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

from functools import partial

from comment_budget import load_budget
from comment_equality import check_js, check_native
from comment_lang import (MARK, ROOT, PyContext, git, has_bom, native_scan, pmap, py_context_at, read_text,
                          scan_files, source_langs, tracked, write_text)

GH_REMOTE = re.compile(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?$")


def remote_repos() -> list[str]:
    out = []
    for line in git("remote", "-v").splitlines():
        m = GH_REMOTE.search(line.split()[1]) if len(line.split()) > 1 else None
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return out


def open_pr_paths(repos: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for repo in repos:
        nums = subprocess.run(["gh", "pr", "list", "-R", repo, "--state", "open", "--json", "number",
                               "--jq", ".[].number", "-L", "200"], capture_output=True, text=True,
                              check=True).stdout.split()
        for n in nums:
            files = subprocess.run(["gh", "api", "--paginate", f"repos/{repo}/pulls/{n}/files",
                                    "--jq", ".[].filename"], capture_output=True, text=True,
                                   check=True).stdout.split("\n")
            for f in filter(None, files):
                out.setdefault(f, f"{repo.split('/')[1]}#{n}")
    return out


def apply(text: str, spans: list[tuple[int, int, str]]) -> str:
    for a, b, repl in sorted(spans, reverse=True):
        if repl == MARK and a > 0 and b < len(text) and text[a - 1] == " " and text[b] == " " \
                and text[:a].rstrip(" ")[-1:] not in ("\n", ""):
            b += 1
        text = text[:a] + repl + text[b:]
    out = []
    for line in text.split("\n"):
        if MARK in line:
            cr = "\r" if line.endswith("\r") else ""
            line = line[:len(line) - len(cr)].replace(MARK, "").rstrip(" \t")
            if not line.strip():
                continue
            line += cr
        out.append(line)
    res = "\n".join(out)
    if not re.match(r"\ufeff?\r?\n", text):
        bom = "\ufeff" if has_bom(res) else ""
        res = bom + re.sub(r"^(?:[ \t]*\r?\n)+", "", res[len(bom):])
    return res


def _strip_native(ctx: PyContext, item: tuple[str, str, str]):
    p, lang, text = item
    try:
        scan = native_scan(p, lang, text, ctx)
        new = apply(text, scan.prunable)
        if new == text:
            return p, None, None, scan.partial
        err = check_native(p, lang, text, new, ctx, ctx)
        return p, (None if err else new), err, scan.partial
    except Exception as e:
        return p, None, f"unparsable: {type(e).__name__}: {e}", 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--skip-file", action="append", default=[], help="newline list of repo paths to leave alone")
    ap.add_argument("--pr-repo", action="append", default=[], help="extra OWNER/NAME whose open PRs to skip")
    ap.add_argument("--no-pr-skip", action="store_true", help="don't query open PRs")
    a = ap.parse_args()
    skip: dict[str, str] = {}
    for f in a.skip_file:
        with open(f) as fh:
            skip.update({line.strip(): f"skip-file {f}" for line in fh if line.strip()})
    if not a.no_pr_skip:
        skip.update(open_pr_paths(remote_repos() + a.pr_repo))
    skip.update({p: "budget --allow reason" for p in load_budget()["allow"]})
    all_files = tracked(a.paths)
    skip.update({p: "symlink" for p in all_files if (ROOT / p).is_symlink()})
    for p in all_files:
        if p in skip:
            print(f"SKIP {p}: {skip[p]}")
    files = [p for p in all_files if p not in skip]
    texts = {p: read_text(p) for p in files}
    langs, failed = source_langs(texts)
    failed.update({p: "NUL byte in file" for p in langs if MARK in texts[p]})
    texts = {p: t for p, t in texts.items() if p not in failed}

    ctx = py_context_at(None)
    new: dict[str, str] = {}
    parts: dict[str, int] = {}
    native = [(p, langs[p], t) for p, t in texts.items() if langs[p] != "js"]
    for p, n, err, part in pmap(partial(_strip_native, ctx), native):
        if err:
            failed[p] = err
        elif n is not None:
            new[p] = n
        if part:
            parts[p] = part

    js = {p: t for p, t in texts.items() if langs[p] == "js"}
    scans, errors = scan_files({p: ("js", t) for p, t in js.items()}, ctx, "ranges")
    failed.update({p: f"unparsable: {e}" for p, e in errors.items()})
    js_pairs = {}
    for p, s in scans.items():
        n = apply(js[p], s.prunable)
        if n != js[p]:
            js_pairs[p] = (js[p], n)
    js_bad = check_js(js_pairs)
    failed.update(js_bad)
    new.update({p: n for p, (_, n) in js_pairs.items() if p not in js_bad})

    for p, n in new.items():
        write_text(p, n)
    for p, e in sorted(failed.items()):
        print(f"LEFT {p}: {e}", file=sys.stderr)
    for p, n in sorted(parts.items()):
        print(f"PARTIAL {p}: {n} docstring(s) share a line with code, kept", file=sys.stderr)
    print(f"stripped {len(new)} files; {len(failed)} left for hand edit; {len(parts)} partial; "
          f"{len(files) - len(new) - len(failed)} had nothing")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
