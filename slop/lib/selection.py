"""`slop/run --changed`: which scenarios a diff can reach, from slop/map.json. Pure: no git, no
files; lib/covmap.py gathers the inputs. Not `select.py`: slop/lib is on the relay's sys.path,
where that name would shadow the stdlib's `select`. README "Which scenarios to run".

Python (service/, slop/, scripts/demo-shots/): a changed line inside a function body picks the
scenarios whose map lists that file and function (it executed under coverage); a changed line
outside every body (module level, a decorator or signature: those run when the enclosing body
runs, the module's for a top-level def), or in a function the map's sha did not have, picks every
scenario listing the file. Blank lines, and comment lines at module level, change nothing.
App (app/): a changed file picks the scenarios whose recorded pages match a route page (or layout
prefix) that imports it, transitively; the root layout's and middleware's trees every scenario
with pages. Runtime non-.py files: RUNTIME. A scenario whose own file changed is always picked.
"""
from __future__ import annotations

import ast
import re
from pathlib import PurePosixPath

PY_ROOTS = ("service/", "slop/", "scripts/demo-shots/")
APP = "app/"
SCEN = "slop/scenarios/"
ROOTS = PY_ROOTS + ("deploy/fleet/", "desktop/", APP)  # what a diff is read under (lib/covmap.py DIFF_ROOTS)
# app/ files every page loads (config, deps, fonts, static): treated as the root layout.
APP_LAYOUT_FILES = re.compile(r"app/(next\.config\.\w+|package\.json|pnpm-lock\.yaml|postcss\.config\.\w+|"
                              r"tsconfig\.json|app/globals\.css|app/fonts/.+|public/.+)$")
# Entry points whose import trees every page runs: the root layout and the middleware.
APP_ROOT_ENTRIES = re.compile(r"app/(app/layout|middleware|proxy)\.(tsx|ts|jsx|js)$")
APP_TEST = re.compile(r"(\.test\.|(^|/)test-utils\.tsx$|(^|/)test-import-graph\.ts$|(^|/)vitest\.)")
APP_IGNORED = re.compile(r"app/(eslint\.config\.mjs|next-env\.d\.ts|[^/]+\.config\.[^/]+)$")  # after APP_LAYOUT_FILES
PREFIX_FILES = {"layout", "template", "loading", "error", "not-found", "default", "global-error"}
EXACT_FILES = {"page", "route"}
# Non-.py files the stack runs, and who runs them: PAGES every scenario with pages, else the scenarios
# whose map lists one of these Python files. Any other non-.py file under service/ or slop/: every scenario.
PAGES = ()
RUNTIME = ((re.compile(r"scripts/demo-shots/fetch-guard\.cjs$"), PAGES),
           (re.compile(r"deploy/fleet/"), ("slop/lib/box.py", "slop/lib/edge.py")),
           (re.compile(r"desktop/"), ("slop/actors/notif_click.py",)),
           (re.compile(r"slop/lib/[^/]+\.mjs$"), ("slop/lib/app_ts.py",)),
           # the bio sidecar's static page (html/js/css/icons): only service/bio_pages/assets.py reads it
           (re.compile(r"service/bio_pages/public/"), ("service/bio_pages/assets.py",)))


# ---------- python: functions by line ----------

def defs(src: str) -> list[tuple[str, int, int, int]]:
    """Every def / async def: (qualified name, first line incl. decorators, first body line, last line).
    Qualified: Class.method, outer.inner. Raises SyntaxError."""
    out: list[tuple[str, int, int, int]] = []

    def walk(node, prefix: str) -> None:
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                q = prefix + ch.name
                start = min([ch.lineno] + [d.lineno for d in ch.decorator_list])
                out.append((q, start, ch.body[0].lineno, ch.end_lineno or ch.lineno))
                walk(ch, q + ".")
            elif isinstance(ch, ast.ClassDef):
                walk(ch, prefix + ch.name + ".")
            else:
                walk(ch, prefix)
    walk(ast.parse(src), "")
    return out


def innermost(ds, line: int) -> str | None:
    """The innermost def whose body holds `line`. None = module level. A decorator or signature line
    is in the enclosing body (it runs when that body defines the function), not the function's."""
    best = None
    for q, _start, b0, end in ds:
        if b0 <= line <= end and (best is None or b0 >= best[1]):
            best = (q, b0)
    return best[0] if best else None


def funcs_of_lines(src: str, lines) -> tuple[list[str], bool]:
    """(sorted functions whose body ran, any module-level line ran) for executed `lines`."""
    ds = defs(src)
    fs, module = set(), False
    for ln in lines:
        q = innermost(ds, ln)
        if q:
            fs.add(q)
        else:
            module = True
    return sorted(fs), module


def _unquote(s: str) -> str:
    """A path as `git diff` prints it: C-quoted (octal bytes) when it has odd characters; a
    trailing tab when it has a space."""
    s = s.rstrip("\t")
    if not (len(s) > 1 and s[0] == s[-1] == '"'):
        return s
    out, i, s = bytearray(), 0, s[1:-1]
    esc = {"n": b"\n", "t": b"\t", '"': b'"', "\\": b"\\", "a": b"\a", "b": b"\b", "f": b"\f", "r": b"\r",
           "v": b"\v"}
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            if s[i + 1:i + 4].isdigit() and len(s[i + 1:i + 4]) == 3:
                out.append(int(s[i + 1:i + 4], 8))
                i += 4
                continue
            out += esc.get(s[i + 1], s[i + 1].encode())
            i += 2
            continue
        out += c.encode()
        i += 1
    return out.decode("utf-8", "replace")


def parse_hunks(diff: str) -> dict[str, list[tuple[int, int, int, int]]]:
    """`git diff -U0 --src-prefix=a/ --dst-prefix=b/` -> {path: [(old_start, old_len, new_start,
    new_len)]}. Path is the new side (the old side for a deletion); quoted paths unquoted."""
    out: dict[str, list] = {}
    cur = None
    old_path = None
    for line in diff.splitlines():
        if line.startswith("--- "):
            p = _unquote(line[4:])
            old_path = p[2:] if p.startswith("a/") else None
        elif line.startswith("+++ "):
            p = _unquote(line[4:])
            cur = p[2:] if p.startswith("b/") else old_path
            if cur:
                out.setdefault(cur, [])
        elif line.startswith("@@") and cur:
            m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if m:
                a, b, c, d = m.groups()
                out[cur].append((int(a), 1 if b is None else int(b), int(c), 1 if d is None else int(d)))
    return out


def _touched(src: str | None, lines, known: set[str] | None = None) -> list[tuple[str | None, int]]:
    """[(function or None for module level, line)] for changed `lines` of `src`. A function not in
    `known` (the names the map's sha had; None: no such limit) is new: module level."""
    if src is None:
        return []
    text = src.splitlines()
    try:
        ds = defs(src)
    except SyntaxError:
        return [(None, ln) for ln in lines if 0 < ln <= len(text) and text[ln - 1].strip()]
    out = []
    for ln in lines:
        s = text[ln - 1].strip() if 0 < ln <= len(text) else ""
        if not s:
            continue
        q = innermost(ds, ln)
        if q is not None and known is not None and q not in known:
            q = None
        if q is None and s.startswith("#"):
            continue
        out.append((q, ln))
    return out


def py_touched(f: dict) -> list[tuple[str | None, int]]:
    """Functions (None = module level) and lines a file's hunks touch: old-side lines in the old
    file, new-side lines in the new one (a pure insertion is judged by where it lands; inside a
    function the old file did not have, at module level)."""
    try:
        known = {q for q, *_ in defs(f["old"])} if f.get("old") is not None else set()
    except SyntaxError:
        known = None
    out = []
    for a, b, c, d in f.get("hunks", ()):
        out += _touched(f.get("old"), range(a, a + b))
        out += _touched(f.get("new"), range(c, c + d), known)
    return out


# ---------- app: routes and the import graph ----------

def app_entry(rel: str) -> tuple[str, bool] | None:
    """`app/app/<segs>/page.tsx` -> (route regex, prefix?) for a Next route file, else None.
    `(group)` segments dropped, `[x]` one segment, `[...x]` one or more, `[[...x]]` zero or more."""
    p = PurePosixPath(rel)
    if p.parts[:2] != ("app", "app") or p.suffix not in (".tsx", ".ts", ".jsx", ".js"):
        return None
    if p.stem not in PREFIX_FILES | EXACT_FILES:
        return None
    rx = ""
    for seg in p.parts[2:-1]:
        if seg.startswith("(") and seg.endswith(")"):
            continue
        if seg.startswith("[["):
            rx += r"(?:/.*)?"
        elif seg.startswith("[..."):
            rx += r"/.+"
        elif seg.startswith("["):
            rx += r"/[^/]+"
        else:
            rx += "/" + re.escape(seg)
    return rx, p.stem in PREFIX_FILES


def route_matches(rx: str, prefix: bool, path: str) -> bool:
    """A recorded page path against a route (exact, or a layout's prefix); a trailing slash is the same page."""
    return re.fullmatch(rx + (r"(?:/.*)?" if prefix else "/?"), path) is not None


def _walk(app_edges: dict[str, list[str]], start: str) -> set[str]:
    seen, todo = set(), [start]
    while todo:
        x = todo.pop()
        if x not in seen:
            seen.add(x)
            todo += app_edges.get(x, [])
    return seen


def app_reach(app_edges: dict[str, list[str]]) -> dict[str, list[str]]:
    """{file: [route entry files reaching it]} over the import graph (keys repo-relative)."""
    reach: dict[str, set] = {}
    for e in app_edges:
        if app_entry(e) is not None:
            for x in _walk(app_edges, e):
                reach.setdefault(x, set()).add(e)
    return {k: sorted(v) for k, v in reach.items()}


def app_root_tree(app_edges: dict[str, list[str]]) -> set[str]:
    """Files the root layout or the middleware import, transitively (themselves included)."""
    return {x for e in app_edges if APP_ROOT_ENTRIES.match(e) for x in _walk(app_edges, e)}


def _route_label(entry: str) -> str:
    prefix = app_entry(entry)[1]
    label = "/" + "/".join(s for s in PurePosixPath(entry).parts[2:-1] if not (s.startswith("(") and s.endswith(")")))
    return label + ("/*" if prefix and label != "/" else "*" if prefix else "")


# ---------- the pick ----------

def ignored(path: str) -> bool:
    """Files no slop scenario is meant to reach: docs, tests, evidence, the map itself, and anything
    outside ROOTS."""
    p = PurePosixPath(path)
    if not path.startswith(ROOTS) or p.suffix == ".md" or "__pycache__" in p.parts or "node_modules" in p.parts:
        return True
    if path.startswith(APP):
        if APP_LAYOUT_FILES.match(path):
            return False
        return bool(APP_TEST.search(path) or APP_IGNORED.match(path)) or path.startswith("app/.next/")
    return (path.startswith(("slop/evidence/", "service/tests/")) or path in ("slop/map.json", "slop/.gitignore")
            or p.suffix == ".pyc" or p.name.startswith("test_"))


def runtime(path: str):
    """A non-.py runtime file's runners: PAGES, a tuple of Python files, "all", or None (not one)."""
    for rx, who in RUNTIME:
        if rx.match(path):
            return who
    if path.startswith(("service/", "slop/")) and not path.endswith(".py"):
        return "all"
    return None


TIERS = ("own", "flow", "shared", "layout")
FLOW_SHARE = 0.15  # reached through code at most this share of mapped scenarios run: the flow's own


def tier(reasons: list[tuple[str, str]]) -> str:
    """A scenario's tier: its best reason's."""
    return min((t for t, _ in reasons), key=TIERS.index)


def needs_ui(reasons: list[tuple[str, str]]) -> bool:
    """Every reason is a page a browser visited ("app: "): a run without UI cannot reach it."""
    return all(r.startswith("app: ") for _, r in reasons)


def pick(map_doc: dict, hunks_by_sha: dict, app_edges: dict, changed_files: dict, untracked: list[str],
         deleted=frozenset(), map_missing: dict[str, set[str]] | None = None):
    """-> ({scenario: [(tier, reason)]}, [warnings]); reasons best tier first.

    Tiers: `own` its scenario file changed; `flow` reached through a function, a module-level hunk,
    a route or a runtime file's runner that at most FLOW_SHARE of the mapped scenarios run / list /
    visit; `shared` through one more of them run, or a non-.py file under service/ slop/ (every
    scenario); `layout` through the app's root layout or middleware tree, globals.css, fonts,
    public/, app config, fetch-guard.cjs, or a deleted app file (scenarios a browser drove only).
    A route reason beats a layout one.

    map_doc: slop/map.json ({"scenarios": {name: {"sha", "py": {file: [funcs]}, "pages": [...],
    "http_pages": [...]}}}; http_pages: reached over HTTP, no browser: reasons "app (http): ").
    hunks_by_sha: {sha: {file.py: {"hunks": [(a, b, c, d)], "old": src at sha | None, "new": src now | None}}}.
    app_edges: {app file: [app files it imports]} (repo-relative, the tree now).
    changed_files: {sha: [every file changed since sha]}. untracked: files git does not know yet.
    deleted: changed files no longer on disk."""
    scen = map_doc.get("scenarios", {})
    n_all = max(1, len(scen))
    picked: dict[str, list[tuple[str, str]]] = {}
    hit: set[str] = set()
    warns: set[str] = set()
    touched_fns: set[tuple[str, str]] = set()
    reach, root_tree = app_reach(app_edges), app_root_tree(app_edges)
    share: dict = {}

    def runs(key) -> int:
        """How many mapped scenarios run this function (file, q) / list this file (file, None) /
        list any of these files ("any", files) / visit this route entry ("app", entry)."""
        if key not in share:
            a, b = key
            if a == "app":
                rx, prefix = app_entry(b)
                share[key] = sum(any(route_matches(rx, prefix, p) for p in e.get("pages", ())) for e in scen.values())
            elif a == "any":
                share[key] = sum(any(x in e.get("py", {}) for x in b) for e in scen.values())
            else:
                share[key] = sum(b in e.get("py", {}).get(a, ()) if b else a in e.get("py", {})
                                 for e in scen.values())
        return share[key]

    def add(name: str, t: str, why: str, path: str) -> None:
        hit.add(path)
        r = picked.setdefault(name, [])
        if why not in (w for _, w in r):
            r.append((t, why))

    def add_counted(name: str, head: str, detail: str, path: str, key) -> None:
        """Tier by share: `flow` when at most FLOW_SHARE of the mapped scenarios share `key`."""
        k = runs(key)
        add(name, "flow" if k <= FLOW_SHARE * n_all else "shared", f"{head} ({detail} {k}/{n_all})", path)

    all_changed = set(untracked) | {f for fs in changed_files.values() for f in fs}
    map_missing = map_missing or {}
    unknown = {f for f in all_changed if any(f in fs for fs in map_missing.values()) and not ignored(f)}
    warns |= {f"WARN map cannot judge {f} (absent at map sha); refresh: slop/run all --map" for f in unknown}
    for f in sorted(all_changed):  # a scenario's own file: always (new or mapped)
        if f.startswith(SCEN) and f.endswith(".py") and "/" not in f[len(SCEN):]:
            name = PurePosixPath(f).stem
            if not name.startswith("_"):
                add(name, "own", "scenario file changed", f)
    for name, e in sorted(scen.items()):
        sha = e.get("sha")
        files = set(changed_files.get(sha, ())) | set(untracked)
        py, pages, http_pages = e.get("py", {}), e.get("pages", []), set(e.get("http_pages", ()))
        browser = [p for p in pages if p not in http_pages]  # what the layout and fetch-guard serve
        for f in sorted(files):
            if ignored(f):
                continue
            if f in map_missing.get(sha, ()):
                add(name, "shared", f"{f} (absent at map sha: every scenario)", f)
            if f.startswith(APP):
                rel = f[len(APP):]
                if f in deleted or APP_LAYOUT_FILES.match(f) or f in root_tree:
                    if pages if f in deleted else browser:  # a deleted route.ts: http pages too
                        add(name, "layout", f"app: every page <- {rel}" + (" (deleted)" if f in deleted else ""), f)
                    if f in deleted:
                        warns.add(f"WARN deleted app file: conservative pick: {f}")
                for ent in reach.get(f, []):
                    if APP_ROOT_ENTRIES.match(ent):
                        continue  # the root layout itself: the layout reason
                    rx, prefix = app_entry(ent)
                    hits = [p for p in pages if route_matches(rx, prefix, p)]
                    if hits:
                        via = "app (http)" if all(p in http_pages for p in hits) else "app"
                        add_counted(name, f"{via}: {_route_label(ent)} <- {rel}", "visited by", f, ("app", ent))
                continue
            who = runtime(f)
            if who is not None:
                if who == "all":
                    add(name, "shared", f"{f} (non-.py runtime file: every scenario)", f)
                    warns.add(f"WARN non-.py runtime file, every scenario picked: {f}")
                elif who == PAGES:
                    if browser:
                        add(name, "layout", f"app: every page <- {f}", f)
                elif any(x in py for x in who):
                    add_counted(name, f, f"via {', '.join(who)}; listed by", f, ("any", who))
                continue
            if f not in py or not f.endswith(".py"):
                continue
            fd = (hunks_by_sha.get(sha) or {}).get(f)
            if fd is None:  # untracked or no hunks (mode change): the whole file is new to this sha
                add_counted(name, f, "new or rewritten file; loaded by", f, (f, None))
                continue
            done = set()  # one reason per function (its first hunk line)
            known = fd.get("map_known")  # names at the map sha, when the diff base is another commit
            for q, ln in py_touched(fd):
                if q is not None and known is not None and q not in known:
                    q = None  # the sweep never saw this function: module level, like a new one
                if q is not None and q not in py[f]:
                    touched_fns.add((f, q))
                if q in done or (q is not None and q not in py[f]):
                    continue
                done.add(q)
                if q is None:
                    add_counted(name, f, f"module level @ L{ln}; loaded by", f, (f, None))
                else:
                    add_counted(name, f"{f}::{q}", f"hunk @ L{ln}; run by", f, (f, q))
    unexec = {(f, q) for f, q in touched_fns if not runs((f, q))}
    warns |= {f"WARN not executed by any scenario: {f}::{q}" for f, q in unexec}
    for r in picked.values():
        r.sort(key=lambda x: TIERS.index(x[0]))
    unexec_files = {f for f, _ in unexec}
    warns |= {f"NOT VERIFIED (no scenario reaches): {f}" for f in all_changed
              if f not in hit and f not in unexec_files and not ignored(f)
              and not (f.startswith(SCEN) and f.endswith(".py"))}
    return picked, sorted(warns)


def plan(picked: dict[str, list[tuple[str, str]]], seconds: dict[str, float | None], budget_s: float):
    """-> (run, skipped): tier then seconds ascending (unknown last). `own` and `flow` always run;
    `shared` and `layout` run in that order while the running estimate (own/flow included) stays
    within `budget_s` (0 = no cap; an unknown estimate counts 0); from the first that would pass it,
    the rest are skipped."""
    order = sorted(picked, key=lambda n: (TIERS.index(tier(picked[n])), seconds.get(n) is None,
                                          seconds.get(n) or 0, n))
    run, skipped, total, full = [], [], 0.0, False
    for n in order:
        s = seconds.get(n) or 0
        if tier(picked[n]) not in ("own", "flow") and budget_s and (full or total + s > budget_s):
            full = True
            skipped.append(n)
            continue
        run.append(n)
        total += s
    return run, skipped
