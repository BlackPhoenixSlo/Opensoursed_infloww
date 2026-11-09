"""lib/selection.py tables. venv/bin/python -m pytest slop/lib/test_selection.py"""
from __future__ import annotations

import json

import pytest

from slop.lib import covmap
from slop.lib import selection as sel

SRC = '''import os

X = 1


@decorate
def top(a):
    # a comment
    y = a

    def inner():
        return y
    return inner


class Box:
    size = 3

    async def open(self):
        return 1

    class Lid:
        def shut(self):
            pass
'''
#  1 import os / 3 X = 1 / 6 @decorate / 7 def top / 8 comment / 9 y = a / 11 def inner / 12 return y /
# 13 return inner / 16 class Box / 17 size / 19 async def open / 20 return 1 / 22 class Lid / 23 def shut / 24 pass


def test_defs_qualified():
    assert [(q, s, b, e) for q, s, b, e in sel.defs(SRC)] == [
        ("top", 6, 9, 13), ("top.inner", 11, 12, 12), ("Box.open", 19, 20, 20),
        ("Box.Lid.shut", 23, 24, 24)]


@pytest.mark.parametrize("lines,funcs,module", [
    ([9, 13], ["top"], False),
    ([11], ["top"], False),            # the nested def statement runs when top runs
    ([12], ["top.inner"], False),
    ([7, 1, 3], [], True),             # def lines and module code: import time, no body ran
    ([17], [], True),                  # class body: module level
    ([20, 24], ["Box.Lid.shut", "Box.open"], False),
])
def test_funcs_of_lines(lines, funcs, module):
    assert sel.funcs_of_lines(SRC, lines) == (funcs, module)


DIFF = """diff --git a/service/a.py b/service/a.py
--- a/service/a.py
+++ b/service/a.py
@@ -9 +9 @@ def top(a):
-    y = a
+    y = a + 1
@@ -12,0 +13,2 @@ def top(a):
+    # note
+
@@ -20,2 +21 @@
-x
-y
+z
diff --git a/service/new.py b/service/new.py
new file mode 100644
--- /dev/null
+++ b/service/new.py
@@ -0,0 +1,3 @@
+a
+b
+c
diff --git a/service/gone.py b/service/gone.py
deleted file mode 100644
--- a/service/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-a
-b
"""


def test_parse_hunks():
    assert sel.parse_hunks(DIFF) == {
        "service/a.py": [(9, 1, 9, 1), (12, 0, 13, 2), (20, 2, 21, 1)],
        "service/new.py": [(0, 0, 1, 3)],
        "service/gone.py": [(1, 2, 0, 0)],
    }


QUOTED = """diff --git "a/service/caf\\303\\251.py" "b/service/caf\\303\\251.py"
--- "a/service/caf\\303\\251.py"
+++ "b/service/caf\\303\\251.py"
@@ -3 +3 @@
-x
+y
diff --git a/slop/sp ace.py b/slop/sp ace.py
--- a/slop/sp ace.py\t
+++ b/slop/sp ace.py\t
@@ -1,0 +2 @@
+z
diff --git "a/app/q\\"t.ts" "b/app/q\\"t.ts"
deleted file mode 100644
--- "a/app/q\\"t.ts"
+++ /dev/null
@@ -1 +0,0 @@
-q
"""


def test_parse_hunks_prefixes_and_quoted_paths():
    assert sel.parse_hunks(QUOTED) == {"service/caf\u00e9.py": [(3, 1, 3, 1)], "slop/sp ace.py": [(1, 0, 2, 1)],
                                       'app/q"t.ts': [(1, 1, 0, 0)]}


def _ins(src: str, at: int, text: str) -> str:
    """`text` inserted after line `at` (1-based) of src."""
    ls = src.splitlines(keepends=True)
    return "".join(ls[:at] + [text] + ls[at:])


@pytest.mark.parametrize("name,new,hunk,want", [
    ("modified body line", SRC.replace("    y = a\n", "    y = a * 2\n"), (9, 1, 9, 1), [("top", 9), ("top", 9)]),
    ("comment inserted in a body", _ins(SRC, 9, "    # why\n"), (9, 0, 10, 1), [("top", 10)]),
    ("blank line inserted", _ins(SRC, 3, "\n"), (3, 0, 4, 1), []),
    ("module comment inserted", _ins(SRC, 3, "# hi\n"), (3, 0, 4, 1), []),
    ("module code changed", SRC.replace("X = 1", "X = 2"), (3, 1, 3, 1), [(None, 3), (None, 3)]),
    # a decorator / signature runs when the enclosing body defines the function: module level here
    ("decorator changed", SRC.replace("@decorate", "@other"), (6, 1, 6, 1), [(None, 6), (None, 6)]),
    ("signature changed", SRC.replace("def top(a)", "def top(a, b=0)"), (7, 1, 7, 1), [(None, 7), (None, 7)]),
    ("nested def signature: the enclosing body", SRC.replace("def inner()", "def inner(z=1)"), (11, 1, 11, 1),
     [("top", 11), ("top", 11)]),
    ("new function between two: module level", _ins(SRC, 14, "def fresh():\n    return 2\n\n"), (14, 0, 15, 3),
     [(None, 15), (None, 16)]),
    ("new override in a class: module level", _ins(SRC, 20, "\n    def close(self):\n        return 0\n"),
     (20, 0, 21, 3), [(None, 22), (None, 23)]),
    ("method body", SRC.replace("return 1", "return 2"), (20, 1, 20, 1), [("Box.open", 20), ("Box.open", 20)]),
    ("syntax error: module level", SRC.replace("y = a", "y = ("), (9, 1, 9, 1), [("top", 9), (None, 9)]),
])
def test_py_touched(name, new, hunk, want):
    assert sel.py_touched({"hunks": [hunk], "old": SRC, "new": new}) == want, name


@pytest.mark.parametrize("rel,path,ok", [
    ("app/app/page.tsx", "/", True),
    ("app/app/page.tsx", "/employees", False),
    ("app/app/employees/page.tsx", "/employees", True),
    ("app/app/employees/page.tsx", "/employees/", True),
    ("app/app/employees/page.tsx", "/employees/shifts", False),
    ("app/app/(shell)/employees/page.tsx", "/employees", True),
    ("app/app/settings/[tab]/page.tsx", "/settings/general", True),
    ("app/app/settings/[tab]/page.tsx", "/settings/a/b", False),
    ("app/app/x/[...p]/page.tsx", "/x", False),
    ("app/app/x/[...p]/page.tsx", "/x/a/b", True),
    ("app/app/of-manager/[section]/[[...path]]/page.tsx", "/of-manager/vault", True),
    ("app/app/of-manager/[section]/[[...path]]/page.tsx", "/of-manager/vault/a/b", True),
    ("app/app/creators/layout.tsx", "/creators/proxy", True),
    ("app/app/creators/layout.tsx", "/creatorsx", False),
    ("app/app/layout.tsx", "/anything/at/all", True),
])
def test_routes(rel, path, ok):
    rx, prefix = sel.app_entry(rel)
    assert sel.route_matches(rx, prefix, path) is ok


@pytest.mark.parametrize("rel", ["app/components/x.tsx", "app/app/page.test.tsx", "app/app/x/helper.ts"])
def test_not_route(rel):
    assert sel.app_entry(rel) is None


MAP = {"scenarios": {
    "s-clock": {"sha": "A", "seconds": 60, "pages": ["/employees/shifts"],
                "py": {"service/a.py": ["top"], "slop/lib/stack.py": ["Stack.relay_cmd"], "slop/lib/edge.py": []}},
    "s-vault": {"sha": "A", "seconds": 30, "pages": ["/growth/vault-pro"],
                "py": {"service/a.py": ["Box.open"], "service/v.py": ["top"], "slop/lib/app_ts.py": ["run"],
                       "slop/actors/notif_click.py": ["click"]}},
    # reaches the app's /site-auth route handler over plain HTTP only (no browser)
    "s-api": {"sha": "B", "seconds": 10, "pages": ["/site-auth"], "http_pages": ["/site-auth"],
              "py": {"service/a.py": ["top"]}},
    # 17 more that run Box.open and visit /: 20 mapped, so `flow` is reach by at most 3 of them
    **{f"f{i:02d}": {"sha": "A", "seconds": 100 + i, "pages": ["/"], "py": {"service/a.py": ["Box.open"]}}
       for i in range(17)},
}}
FILLERS = {n for n in MAP["scenarios"] if n.startswith("f")}
EDGES = {
    "app/app/layout.tsx": ["app/components/Shell.tsx"],
    "app/components/Shell.tsx": ["app/lib/fmt.ts"],
    "app/lib/fmt.ts": [],
    "app/middleware.ts": ["app/lib/auth-edge.ts"],
    "app/lib/auth-edge.ts": [],
    "app/app/site-auth/route.ts": [],
    "app/app/page.tsx": ["app/lib/time.ts"],
    "app/app/employees/shifts/page.tsx": ["app/components/shifts/ShiftBar.tsx"],
    "app/components/shifts/ShiftBar.tsx": ["app/lib/time.ts", "app/lib/fmt.ts"],
    "app/app/growth/vault-pro/page.tsx": ["app/lib/time.ts"],
    "app/lib/time.ts": [],
    "app/lib/orphan.ts": [],
}


def _f(new: str, hunk) -> dict:
    return {"hunks": [hunk], "old": SRC, "new": new}


BODY = _f(SRC.replace("    y = a\n", "    y = a * 2\n"), (9, 1, 9, 1))
MODULE = _f(SRC.replace("X = 1", "X = 2"), (3, 1, 3, 1))
OPEN = _f(SRC.replace("return 1", "return 2"), (20, 1, 20, 1))
DECOR = _f(SRC.replace("@decorate", "@other"), (6, 1, 6, 1))
OVERRIDE = _f(_ins(SRC, 20, "\n    def close(self):\n        return 0\n"), (20, 0, 21, 3))
ALL = set(MAP["scenarios"])
BROWSER = {n for n, e in MAP["scenarios"].items() if set(e["pages"]) - set(e.get("http_pages", ()))}
PAGES = {n for n, e in MAP["scenarios"].items() if e["pages"]}
UNC = "NOT VERIFIED (no scenario reaches): "
SWEPT = {q for q, *_ in sel.defs(SRC)}  # names the map sha's file had
RENAMED = SRC.replace("def top(a)", "def top2(a)")  # renamed on main after the sweep
ADDED = _ins(SRC, 14, "def fresh():\n    return 2\n\n")  # added on main after the sweep (body L16)


@pytest.mark.parametrize("name,hunks,changed,untracked,want,warns", [
    ("function hunk: only scenarios that ran it, per their own sha",
     {"A": {"service/a.py": BODY}}, {"A": ["service/a.py"], "B": []}, [], {"s-clock": "flow"}, []),
    ("same file, both shas changed",
     {"A": {"service/a.py": BODY}, "B": {"service/a.py": BODY}}, {"A": ["service/a.py"], "B": ["service/a.py"]},
     [], {"s-clock": "flow", "s-api": "flow"}, []),
    ("function most scenarios run: shared", {"A": {"service/a.py": OPEN}}, {"A": ["service/a.py"]}, [],
     {n: "shared" for n in FILLERS | {"s-vault"}}, []),
    ("module level of a file most load: shared, every scenario listing it",
     {"A": {"service/a.py": MODULE}}, {"A": ["service/a.py"]}, [], {n: "shared" for n in ALL - {"s-api"}}, []),
    ("module level of a file one loads: flow", {"A": {"service/v.py": MODULE}}, {"A": ["service/v.py"]}, [],
     {"s-vault": "flow"}, []),
    ("body hunk in a function nobody ran: warned per function",
     {"A": {"service/a.py": _f(SRC.replace("pass", "return 0"), (24, 1, 24, 1))}}, {"A": ["service/a.py"]}, [],
     {}, ["not executed by any scenario: service/a.py::Box.Lid.shut"]),
    ("file no scenario lists: uncovered", {"A": {"service/z.py": BODY}}, {"A": ["service/z.py"]}, [], {},
     [UNC + "service/z.py"]),
    ("decorator hunk: module level, every scenario listing the file", {"A": {"service/v.py": DECOR}},
     {"A": ["service/v.py"]}, [], {"s-vault": "flow"}, []),
    ("new override: module level", {"A": {"service/v.py": OVERRIDE}}, {"A": ["service/v.py"]}, [],
     {"s-vault": "flow"}, []),
    ("renamed file: old path every line (conservative), new path uncovered",
     {"A": {"service/v.py": {"hunks": [(1, 24, 0, 0)], "old": SRC, "new": None},
            "service/v2.py": {"hunks": [(0, 0, 1, 24)], "old": None, "new": SRC}}},
     {"A": ["service/v.py", "service/v2.py"]}, [], {"s-vault": "flow"},
     [f"not executed by any scenario: service/v.py::{q}" for q in ("Box.Lid.shut", "Box.open", "top.inner")]
     + [UNC + "service/v2.py"]),
    ("out-of-root files: ignored", {}, {"A": ["requirements.txt", "web/a.ts", "deploy/other/x.sh"]}, [], {}, []),
    ("deploy/fleet: the scenarios running the edge or boxes", {}, {"A": ["deploy/fleet/templates/Caddyfile.tmpl"]},
     [], {"s-clock": "flow"}, []),
    ("desktop: the scenarios clicking notifications", {}, {"A": ["desktop/lib/notify.js"]}, [], {"s-vault": "flow"},
     []),
    ("slop/lib .mjs: the scenarios running app_ts", {}, {"A": ["slop/lib/focus_ts.mjs"]}, [], {"s-vault": "flow"},
     []),
    ("fetch-guard.cjs: every browser scenario", {}, {"A": ["scripts/demo-shots/fetch-guard.cjs"]}, [],
     {n: "layout" for n in BROWSER}, []),
    ("non-py runtime file under service/: every scenario, shared, warned", {},
     {"A": ["service/db/migrations/0042.sql"], "B": ["service/db/migrations/0042.sql"]}, [],
     {n: "shared" for n in ALL}, ["non-.py runtime file, every scenario picked: service/db/migrations/0042.sql"]),
    ("layout + route file: the route's flow beats layout", {}, {"A": ["app/lib/fmt.ts"]}, [],
     {**{n: "layout" for n in BROWSER}, "s-clock": "flow"}, []),
    ("middleware tree: layout", {}, {"A": ["app/lib/auth-edge.ts"]}, [], {n: "layout" for n in BROWSER}, []),
    ("fonts and public/: layout", {}, {"A": ["app/app/fonts/x.woff2", "app/public/logo.svg"]}, [],
     {n: "layout" for n in BROWSER}, []),
    ("app tooling config ignored", {}, {"A": ["app/vitest.config.ts", "app/eslint.config.mjs", "app/next-env.d.ts",
                                              "app/vitest.setup.ts", "app/playwright.config.ts"]}, [], {}, []),
    ("route.ts reached over HTTP", {}, {"B": ["app/app/site-auth/route.ts"]}, [], {"s-api": "flow"}, []),
    ("deleted app file: every scenario with pages, layout, warned", {}, {"A": ["app/components/Gone.tsx"],
                                                                         "B": ["app/components/Gone.tsx"]}, [],
     {n: "layout" for n in PAGES}, ["deleted app file: conservative pick: app/components/Gone.tsx"]),
    ("component one route uses: flow", {}, {"A": ["app/components/shifts/ShiftBar.tsx"]}, [], {"s-clock": "flow"}, []),
    ("lib three routes use: / is shared, the others flow", {}, {"A": ["app/lib/time.ts"]}, [],
     {"s-clock": "flow", "s-vault": "flow", **{n: "shared" for n in FILLERS}}, []),
    ("root layout tree: layout, every scenario a browser drove", {}, {"A": ["app/components/Shell.tsx"]}, [],
     {n: "layout" for n in BROWSER}, []),
    ("app config: layout", {}, {"A": ["app/next.config.ts"]}, [], {n: "layout" for n in BROWSER}, []),
    ("app file no route reaches: uncovered", {}, {"A": ["app/lib/orphan.ts"]}, [], {}, [UNC + "app/lib/orphan.ts"]),
    ("app tests ignored", {}, {"A": ["app/lib/time.test.ts", "app/test-utils.tsx"]}, [], {}, []),
    ("docs, web, readmes ignored", {}, {"A": ["docs/x.md", "web/a.ts", "slop/README.md", "service/tests/test_a.py"]},
     [], {}, []),
    ("scenario file changed: own", {}, {"A": ["slop/scenarios/s-vault.py"]}, [], {"s-vault": "own"}, []),
    ("own beats shared", {"A": {"service/a.py": OPEN}}, {"A": ["service/a.py", "slop/scenarios/f03.py"]}, [],
     {**{n: "shared" for n in FILLERS | {"s-vault"}}, "f03": "own"}, []),
    ("new scenario (untracked): own", {}, {"A": []}, ["slop/scenarios/s-new.py"], {"s-new": "own"}, []),
    ("untracked service file: uncovered", {}, {"A": []}, ["service/fresh.py"], {}, [UNC + "service/fresh.py"]),
    # diff base (merge-base) != map sha: the map is matched by name against the map sha's file
    ("base != map sha, function the sweep saw: its runners", {"A": {"service/a.py": {**BODY, "map_known": SWEPT}}},
     {"A": ["service/a.py"]}, [], {"s-clock": "flow"}, []),
    ("function renamed since the sweep: module level",
     {"A": {"service/v.py": {"hunks": [(9, 1, 9, 1)], "old": RENAMED, "new": RENAMED.replace("y = a\n", "y = 0\n"),
                             "map_known": SWEPT}}}, {"A": ["service/v.py"]}, [], {"s-vault": "flow"}, []),
    ("function at base but not at the map sha: module level",
     {"A": {"service/v.py": {"hunks": [(16, 1, 16, 1)], "old": ADDED, "new": ADDED.replace("return 2", "return 3"),
                             "map_known": SWEPT}}}, {"A": ["service/v.py"]}, [], {"s-vault": "flow"}, []),
    ("same rename, base == map sha (no map_known): not executed",
     {"A": {"service/v.py": {"hunks": [(9, 1, 9, 1)], "old": RENAMED, "new": RENAMED.replace("y = a\n", "y = 0\n")}}},
     {"A": ["service/v.py"]}, [], {}, ["not executed by any scenario: service/v.py::top2"]),
])
def test_pick(name, hunks, changed, untracked, want, warns):
    deleted = {"app/components/Gone.tsx", "service/v.py"}
    picked, got = sel.pick(MAP, hunks, EDGES, changed, untracked, deleted)
    assert {n: sel.tier(r) for n, r in picked.items()} == want, name
    assert got == sorted(w if w.startswith("NOT VERIFIED ") else "WARN " + w for w in warns), name


def test_side_effect_import_picks_through_app_edges(tmp_path):
    app = tmp_path / "app"
    (app / "app" / "employees" / "shifts").mkdir(parents=True)
    (app / "app" / "employees" / "shifts" / "page.tsx").write_text('import "./shifts.css";\nexport default 1;\n')
    (app / "app" / "employees" / "shifts" / "shifts.css").write_text(".x{}\n")
    edges = covmap.app_edges(app)
    assert edges["app/app/employees/shifts/page.tsx"] == ["app/app/employees/shifts/shifts.css"]
    picked, _ = sel.pick(MAP, {}, edges, {"A": ["app/app/employees/shifts/shifts.css"]}, [])
    assert {n: sel.tier(r) for n, r in picked.items()} == {"s-clock": "flow"}


@pytest.mark.parametrize("reasons,ui", [
    ([("flow", "app: /x <- a.tsx (visited by 1/20)")], True),
    ([("layout", "app: every page <- globals.css")], True),
    ([("flow", "app (http): /site-auth <- app/site-auth/route.ts (visited by 1/20)")], False),
    ([("layout", "app: every page <- x"), ("flow", "service/a.py::top (hunk @ L9; run by 2/20)")], False),
])
def test_needs_ui(reasons, ui):
    assert sel.needs_ui(reasons) is ui


def test_reasons():
    picked, _ = sel.pick(MAP, {"A": {"service/a.py": BODY}}, EDGES,
                         {"A": ["service/a.py", "app/components/shifts/ShiftBar.tsx"]}, [])
    assert picked["s-clock"] == [("flow", "app: /employees/shifts <- components/shifts/ShiftBar.tsx (visited by 1/20)"),
                                 ("flow", "service/a.py::top (hunk @ L9; run by 2/20)")]
    picked, _ = sel.pick(MAP, {}, EDGES, {"B": ["app/app/site-auth/route.ts"]}, [])
    assert picked == {"s-api": [("flow", "app (http): /site-auth <- app/site-auth/route.ts (visited by 1/20)")]}


S = {"o": 500, "fl": 400, "sh1": 100, "sh2": 300, "sh3": 50, "la1": 10, "la2": 20, "un": None}
P = {"o": [("own", "x")], "fl": [("flow", "x")], "sh1": [("shared", "x")], "sh2": [("shared", "x")],
     "sh3": [("shared", "x"), ("layout", "y")], "la1": [("layout", "x")], "la2": [("layout", "x")],
     "un": [("own", "x")]}


@pytest.mark.parametrize("budget_s,run,skipped", [
    (0, ["o", "un", "fl", "sh3", "sh1", "sh2", "la1", "la2"], []),           # no cap: tier, then seconds
    (60, ["o", "un", "fl"], ["sh3", "sh1", "sh2", "la1", "la2"]),           # own/flow always, even past it
    (1100, ["o", "un", "fl", "sh3", "sh1"], ["sh2", "la1", "la2"]),         # stops at the first that passes
    (1400, ["o", "un", "fl", "sh3", "sh1", "sh2", "la1", "la2"], []),
])
def test_plan(budget_s, run, skipped):
    assert sel.plan(P, S, budget_s) == (run, skipped)


@pytest.mark.parametrize("budget_s,run,skipped", [
    (60, ["a"], ["c", "b"]),          # unknown seconds sort last; once full, it is skipped too
    (100, ["a", "c", "b"], []),       # unknown counts 0 against the budget
])
def test_plan_unknown_seconds(budget_s, run, skipped):
    p = {"a": [("shared", "x")], "b": [("shared", "x")], "c": [("shared", "x")]}
    assert sel.plan(p, {"a": 30, "b": None, "c": 40}, budget_s) == (run, skipped)


# ---------- lib/covmap.py ----------

@pytest.fixture
def app_tree(tmp_path):
    app = tmp_path / "app"
    for rel, src in {
        "lib/x.ts": "export const x = 1;\n",
        "lib/idx/index.tsx": "export default 1;\n",
        "comp/y.tsx": "export default 1;\n",
        "comp/z.tsx": ('import y from "./y";\n// import nope from "./nope"\n/* import gone from "@/lib/x" */\n'
                       'const u = "http://a.b/c"; import "./z.css";\nimport idx from "@/lib/idx";\n'),
        "comp/z.css": ".z{}\n",
        "lib/a.ts": 'export * from "./x.js";\nconst m = await import("@/comp/y");\nimport React from "react";\n',
        "node_modules/pkg/index.js": 'import "../../lib/x";\n',
    }.items():
        (app / rel).parent.mkdir(parents=True, exist_ok=True)
        (app / rel).write_text(src)
    return app


@pytest.mark.parametrize("spec,frm,want", [
    ("@/lib/x", "comp/z.tsx", "app/lib/x.ts"),
    ("./y", "comp/z.tsx", "app/comp/y.tsx"),
    ("../lib/x", "comp/z.tsx", "app/lib/x.ts"),
    ("@/lib/idx", "comp/z.tsx", "app/lib/idx/index.tsx"),
    ("./x.js", "lib/a.ts", "app/lib/x.ts"),            # ESM-style specifier of a .ts source
    ("./z.css", "comp/z.tsx", "app/comp/z.css"),
    ("react", "lib/a.ts", None),
    ("./missing", "lib/a.ts", None),
])
def test_resolve(app_tree, spec, frm, want):
    assert covmap._resolve(spec, frm, app_tree) == want


def test_strip():
    src = '/* block\n import a from "./a" */\nimport b from "./b"; // import c from "./c"\nconst u = "http://x/y";\n'
    out = covmap._strip(src)
    assert '"./a"' not in out and '"./c"' not in out and '"./b"' in out and "http://x/y" in out
    assert out.count("\n") == src.count("\n")


def test_app_edges(app_tree):
    assert covmap.app_edges(app_tree) == {
        "app/comp/y.tsx": [], "app/lib/x.ts": [], "app/lib/idx/index.tsx": [],
        "app/comp/z.tsx": ["app/comp/y.tsx", "app/comp/z.css", "app/lib/idx/index.tsx"],
        "app/lib/a.ts": ["app/comp/y.tsx", "app/lib/x.ts"]}


def test_dump_deterministic():
    a = {"version": 1, "scenarios": {"b": {"sha": "S", "py": {"z.py": ["g", "f"], "a.py": []}, "pages": ["/"]},
                                     "a": {"pages": [], "sha": "S", "py": {}}}}
    b = {"scenarios": {"a": {"sha": "S", "py": {}, "pages": []},
                       "b": {"pages": ["/"], "py": {"a.py": [], "z.py": ["f", "g"]}, "sha": "S"}}, "version": 1}
    assert covmap.dump(a) == covmap.dump(b)
    assert json.loads(covmap.dump(a))["scenarios"]["b"]["py"] == {"a.py": [], "z.py": ["f", "g"]}


def test_py_reach_paths(tmp_path):
    from coverage import CoverageData
    sel_py = covmap.ROOT / "slop" / "lib" / "selection.py"
    body = next(b for q, _s, b, _e in sel.defs(sel_py.read_text()) if q == "tier")
    d = CoverageData(str(tmp_path / ".coverage.x"))
    d.add_lines({str(sel_py): [body], str(tmp_path / "outside.py"): [1],
                 str(covmap.ROOT / "slop" / "evidence" / "r" / "x.py"): [1],
                 str(covmap.ROOT / "service" / "never_ran.py"): []})
    d.write()
    assert covmap.py_reach(tmp_path) == {"slop/lib/selection.py": ["tier"]}


@pytest.fixture
def git_repo(tmp_path):
    import subprocess
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True).stdout.strip()
    git("init", "-b", "main")
    git("config", "user.email", "slop@example.test")
    git("config", "user.name", "Slop")
    return git


def test_gather_git_tree_and_worktree(tmp_path, monkeypatch, git_repo):
    git = git_repo
    service = tmp_path / "service"
    service.mkdir()
    for name in ("committed.py", "staged.py", "unstaged.py", "deleted.py"):
        (service / name).write_text("def f():\n    return 1\n")
    git("add", ".")
    git("commit", "-m", "base")
    base = git("rev-parse", "HEAD")
    git("checkout", "-b", "feature")
    (service / "committed.py").write_text("def f():\n    return 2\n")
    git("commit", "-am", "branch")
    (service / "staged.py").write_text("def f():\n    return 3\n")
    git("add", "service/staged.py")
    (service / "unstaged.py").write_text("def f():\n    return 4\n")
    (service / "deleted.py").unlink()
    (service / "untracked.py").write_text("def f():\n    return 5\n")
    monkeypatch.setattr(covmap, "ROOT", tmp_path)
    monkeypatch.setattr(covmap, "app_edges", lambda: {})
    gathered = covmap.gather({"scenarios": {"x": {"sha": base}}})
    changed = set(gathered["changed"][base])
    assert changed == {"service/committed.py", "service/staged.py", "service/unstaged.py",
                       "service/deleted.py"}
    assert gathered["untracked"] == ["service/untracked.py"]
    assert gathered["deleted"] == {"service/deleted.py"}
    assert gathered["hunks"][base]["service/committed.py"]["old"].endswith("return 1\n")
    assert gathered["hunks"][base]["service/committed.py"]["new"].endswith("return 2\n")
    assert gathered["map_age"][base] == 1


def test_gather_missing_only_old_files_or_dynamic_loads(tmp_path, monkeypatch, git_repo):
    git = git_repo
    (tmp_path / "service").mkdir()
    (tmp_path / "service/anchor.py").write_text("x = 1\n")
    git("add", ".")
    git("commit", "-m", "map")
    map_sha = git("rev-parse", "HEAD")
    (tmp_path / "service/later.py").write_text("def clip():\n    return 1\n")
    (tmp_path / "slop/scenarios").mkdir(parents=True)
    (tmp_path / "slop/scenarios/new_flow.py").write_text("x = 1\n")
    git("add", ".")
    git("commit", "-m", "base")
    git("checkout", "-b", "feature")
    (tmp_path / "service/later.py").write_text("def clip():\n    return 2\n")
    (tmp_path / "slop/scenarios/new_flow.py").write_text("x = 2\n")
    (tmp_path / "slop/seed").mkdir(parents=True)
    (tmp_path / "slop/seed/new.py").write_text("x = 1\n")
    (tmp_path / "service/automations").mkdir()
    (tmp_path / "service/automations/new.py").write_text("x = 1\n")
    monkeypatch.setattr(covmap, "ROOT", tmp_path)
    monkeypatch.setattr(covmap, "app_edges", lambda: {})
    gathered = covmap.gather({"scenarios": {"x": {"sha": map_sha}}})
    assert gathered["map_missing"][map_sha] == {"service/later.py", "service/automations/new.py"}


def test_map_ages_marks_diverged_sha(tmp_path, monkeypatch, git_repo):
    git = git_repo
    (tmp_path / "x").write_text("base")
    git("add", ".")
    git("commit", "-m", "base")
    git("checkout", "-b", "other")
    (tmp_path / "x").write_text("other")
    git("commit", "-am", "other")
    other = git("rev-parse", "HEAD")
    git("checkout", "main")
    (tmp_path / "x").write_text("main")
    git("commit", "-am", "main")
    monkeypatch.setattr(covmap, "ROOT", tmp_path)
    assert covmap.map_ages({"scenarios": {"x": {"sha": other}}}) == {other: None}


def test_map_update_keeps_concurrent_entries_and_no_ui_reach(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    monkeypatch.setattr(covmap, "MAP", tmp_path / "map.json")
    monkeypatch.setattr(covmap, "MAP_LOCK", tmp_path / "map.lock")
    gate = Barrier(2)
    def reach(path):
        gate.wait(timeout=5)
        return {"service/x.py": [path.name]}
    monkeypatch.setattr(covmap, "py_reach", reach)
    names = {"a", "b"}
    def write(name):
        return covmap.update(name, tmp_path / name, sha="s", seconds=1, scale="small",
                             ui=True, pages=[], names=names)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(write, names))
    assert set(covmap.load_map()["scenarios"]) == names
    monkeypatch.setattr(covmap, "py_reach", lambda _: {"service/x.py": ["backend"]})
    covmap.update("a", tmp_path / "a", sha="s", seconds=2, scale="small", ui=False,
                  pages=[], names=names, no_ui_run=True)
    assert covmap.load_map()["scenarios"]["a"]["py"]["service/x.py"] == ["a", "backend"]
    covmap.MAP.write_text("{bad")
    with pytest.raises(covmap.MapInvalid, match="invalid JSON"):
        write("a")


def test_missing_at_map_sha_picks_every_scenario():
    doc = {"scenarios": {"a": {"sha": "old", "py": {}, "pages": []},
                         "b": {"sha": "old", "py": {}, "pages": []}}}
    picked, warnings = sel.pick(doc, {"old": {}}, {}, {"old": ["service/new.py"]}, [],
                                map_missing={"old": {"service/new.py"}})
    assert set(picked) == {"a", "b"}
    assert all(sel.tier(reasons) == "shared" for reasons in picked.values())
    assert any("service/new.py" in w and "slop/run all --map" in w for w in warnings)


def test_mixed_map_shas_keep_precise_flow_reason():
    f = "service/new.py"
    doc = {"scenarios": {"a": {"sha": "old", "py": {}, "pages": []},
                         "b": {"sha": "new", "py": {f: ["clip"]}, "pages": []},
                         "c": {"sha": "new", "py": {}, "pages": []},
                         "d": {"sha": "new", "py": {}, "pages": []},
                         "e": {"sha": "new", "py": {}, "pages": []},
                         "f": {"sha": "new", "py": {}, "pages": []},
                         "g": {"sha": "new", "py": {}, "pages": []}}}
    fd = {"old": {f: {"old": "def clip():\n    return 1\n", "new": "def clip():\n    return 2\n",
                        "hunks": [(2, 1, 2, 1)]}},
          "new": {f: {"old": "def clip():\n    return 1\n", "new": "def clip():\n    return 2\n",
                        "hunks": [(2, 1, 2, 1)]}}}
    picked, _ = sel.pick(doc, fd, {}, {"old": [f], "new": [f]}, [],
                         map_missing={"old": {f}, "new": set()})
    assert sel.tier(picked["b"]) == "flow"
    assert any("::clip" in why for _, why in picked["b"])


def test_proxy_import_tree_is_root_layout():
    doc = {"scenarios": {"a": {"sha": "old", "py": {}, "pages": ["/"]}}}
    edges = {"app/proxy.ts": ["app/lib/headers.ts"], "app/lib/headers.ts": []}
    picked, _ = sel.pick(doc, {}, edges, {"old": ["app/proxy.ts"]}, [])
    assert sel.tier(picked["a"]) == "layout"


def test_volume_tag_before_mapping(tmp_path):
    scenario = tmp_path / "new.py"
    scenario.write_text("P95_VS_LAST = (1.5, 100)\n")
    assert covmap.is_volume(scenario)
    scenario.write_text("def run():\n    P95_VS_LAST = (1.5, 100)\n")
    assert not covmap.is_volume(scenario)
