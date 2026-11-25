import shutil
import subprocess
import sys

import pytest

from comment_gate_common import JS, OTHER, PY, PY_PRUNED, REPO, SH_PRUNED, TSX, TSX_PRUNED, commit, git, read, repo, run, write


def test_pure_comment_prune_passes(repo):
    write(repo, "a.py", PY_PRUNED)
    write(repo, "b.tsx", TSX_PRUNED)
    write(repo, "c.sh", SH_PRUNED)
    write(repo, "d.mjs", JS.replace("// plain\n", ""))
    r = run(repo, "comment_equality.py", "HEAD")
    assert r.returncode == 0, r.stderr
    assert "4 ok, 0 failed" in r.stdout


@pytest.mark.parametrize("name,text,why", [
    ("a.py", PY_PRUNED.replace("return x + 1", "return x + 2"), "python AST differs"),
    ("a.py", PY_PRUNED.replace('"""Route doc."""', '"""Route."""'), "python AST differs"),
    ("a.py", PY_PRUNED.replace('"""Inherited schema doc."""', "pass"), "python AST differs"),
    ("a.py", PY_PRUNED.replace("  # noqa: F401", ""), "allowlisted comment changed"),
    ("b.tsx", TSX_PRUNED.replace("\n      {/* between */}\n", "\n"), "TS AST differs"),
    ("b.tsx", TSX_PRUNED.replace("// @ts-nocheck\n", ""), "allowlisted comment changed"),
    ("b.tsx", TSX_PRUNED.replace("`// not ${x} comment`", "`not ${x} comment`"), "TS AST differs"),
    ("d.mjs", JS.replace("/** @type {number} */\n", ""), "allowlisted comment changed"),
    ("c.sh", SH_PRUNED.replace("# keep\n", ""), "shell code differs"),
])
def test_code_or_allowlist_change_fails(repo, name, text, why):
    write(repo, name, text)
    r = run(repo, "comment_equality.py", "HEAD")
    assert r.returncode == 1
    assert why in r.stderr, r.stderr


def test_jsx_comment_removal_keeping_render_passes(repo):
    write(repo, "b.tsx", TSX.replace("      {/* jsx comment */}\n", ""))
    assert run(repo, "comment_equality.py", "HEAD").returncode == 0


STRIP_IN = {
    "e.tsx": 'const s = "😀"; // c\nexport const A = () => (\n  <div>\n    {/* drop */}\n    <p>😀a{/* keep */}b</p>\n'
             '    <p>// text</p>\n  </div>\n);\n',
    "g.py": 'def f():\r\n    """Doc."""\r\n\r\n\r\ndef g():  # c\r\n    return 1\r\n',
    "prove.py": '"""Usage: prove [--x]."""\n# drop\ndef main():\n    """Main doc."""\n    return 1\n',
    "use_prove.py": "import prove\n\nUSAGE = prove.__doc__\n",
    "h.py": "﻿# c\nx = 1\n",
    "i.ts": '///  <reference types="node" />\n// c\nexport const i = 1;\n',
    "k.py": '"""Only a docstring."""\n',
}


STRIP_OUT = {
    "e.tsx": 'const s = "😀";\nexport const A = () => (\n  <div>\n    <p>😀a{/* keep */}b</p>\n'
             '    <p>// text</p>\n  </div>\n);\n',
    "g.py": "def f():\r\n    pass\r\n\r\n\r\ndef g():\r\n    return 1\r\n",
    "prove.py": '"""Usage: prove [--x]."""\ndef main():\n    """Main doc."""\n    return 1\n',
    "use_prove.py": "import prove\n\nUSAGE = prove.__doc__\n",
    "h.py": "﻿x = 1\n",
    "i.ts": '///  <reference types="node" />\nexport const i = 1;\n',
    "k.py": "",
}


def test_strip_round_trip_then_gate_passes(repo):
    commit(repo, STRIP_IN)
    r = run(repo, "comment_strip.py", "--no-pr-skip", "src")
    assert r.returncode == 0, r.stderr
    assert "LEFT" not in r.stderr, r.stderr
    for name, want in STRIP_OUT.items():
        assert read(repo, name) == want, name
    g = run(repo, "comment_equality.py", "HEAD")
    assert g.returncode == 0, g.stderr


def test_strip_reports_one_line_docstring_partial(repo):
    commit(repo, {"j.py": 'def f(): """Doc."""\n'})
    r = run(repo, "comment_strip.py", "--no-pr-skip", "src/j.py")
    assert r.returncode == 0 and "PARTIAL src/j.py: 1" in r.stderr, r.stderr
    assert read(repo, "j.py") == 'def f(): """Doc."""\n'


def test_cross_module_doc_reader_protects_docstrings(repo):
    commit(repo, {"prove.py": STRIP_IN["prove.py"], "use_prove.py": STRIP_IN["use_prove.py"]})
    write(repo, "prove.py", STRIP_IN["prove.py"].replace('    """Main doc."""\n', ""))
    r = run(repo, "comment_equality.py", "HEAD")
    assert r.returncode == 1 and "python AST differs" in r.stderr


@pytest.mark.parametrize("files,name,text,why", [
    ({}, "a.py", PY.replace("import os  # noqa: F401\n", "import os\n# noqa: F401\n"), "moved"),
    ({"k.ts": "// @ts-expect-error\nconst a: number = 'x';\nconst b = 1;\n"}, "k.ts",
     "const a: number = 'x';\n// @ts-expect-error\nconst b = 1;\n", "moved"),
    ({"l.py": "# c\n# d\n# -*- coding: utf-8 -*-\nx = 1\n"}, "l.py", "# -*- coding: utf-8 -*-\nx = 1\n",
     "moved"),
    ({"m.tsx": "export const M = () => <div>a{/* c */}b</div>;\n"}, "m.tsx",
     "export const M = () => <div>ab</div>;\n", "TS AST differs"),
    ({"n.tsx": "export const N = () => <div>a\tb</div>;\n"}, "n.tsx",
     "export const N = () => <div>a b</div>;\n", "TS AST differs"),
    ({"o.sh": "echo $(( $a*2 ))\n"}, "o.sh", "echo $((a*2))\n", "shell code differs"),
    ({"p.py": "x = 1\r\ny = 2\r\n"}, "p.py", "x = 1\ny = 2\n", "line endings changed"),
])
def test_placement_and_encoding_changes_fail(repo, files, name, text, why):
    if files:
        commit(repo, files)
    write(repo, name, text)
    r = run(repo, "comment_equality.py", "HEAD")
    assert r.returncode == 1 and why in r.stderr, r.stderr


def test_mode_status_and_untracked_fail(repo):
    (repo / "src" / "c.sh").chmod(0o755)
    (repo / "src" / "d.mjs").unlink()
    (repo / "src" / "new.py").write_text("x = 1\n")
    r = run(repo, "comment_equality.py", "HEAD")
    assert r.returncode == 1
    assert "src/c.sh: mode 100644→100755" in r.stderr
    assert "src/d.mjs: status D" in r.stderr
    assert "src/new.py: untracked file" in r.stderr
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "m")
    r = run(repo, "comment_equality.py", "HEAD~1", "HEAD")
    assert "mode 100644→100755" in r.stderr and "status A" in r.stderr


def test_ts_line_directive_gap_is_kept(repo):
    src = "// @ts-ignore\n/* c */\nconst x: string = 1;\n// drop\nexport const y = x;\n"
    commit(repo, {"r.ts": src})
    write(repo, "r.ts", src.replace("/* c */\n", ""))
    r = run(repo, "comment_equality.py", "HEAD")
    assert r.returncode == 1 and "src/r.ts: allowlisted comment changed or moved" in r.stderr
    write(repo, "r.ts", src)
    assert run(repo, "comment_strip.py", "--no-pr-skip", "src/r.ts").returncode == 0
    assert read(repo, "r.ts") == "// @ts-ignore\n/* c */\nconst x: string = 1;\nexport const y = x;\n"
    assert run(repo, "comment_equality.py", "HEAD").returncode == 0


PROVE = '"""Usage: prove [--x]."""\ndef main():\n    """Main doc."""\n    return 1\n'


@pytest.mark.parametrize("reader,all_docs", [
    ("import prove as p\nU = p.__doc__\n", False),
    ("from pkg import prove as p\nU = p.__doc__\n", False),
    ("import importlib.util\nspec = importlib.util.spec_from_file_location('prove', 'src/prove.py')\n"
     "mod = importlib.util.module_from_spec(spec)\nU = mod.__doc__\n", True),
    ("from h import HANDLERS\nU = HANDLERS['k'].__doc__\n", True),
    ("U = getattr(object, '__doc__')\n", True),
    ("import prove\nU = prove.__doc__\n\n\nclass B:\n    def show(self):\n        return self.g.__doc__\n", True),
    ("import prove\nU = prove.__doc__\n\n\nclass B:\n    def show(self):\n        return type(self).__doc__\n", False),
    ("import prove\nU = prove.__doc__\n\n\ndef h(x):\n    return type(x).__doc__\n", True),
    ("import prove\nU = prove.__doc__\n\n\ndef h(self):\n    return self.__doc__\n", True),
    ("import prove\nU = prove.__doc__\n\n\nclass B:\n    @staticmethod\n    def h(x, self):\n        return self.__doc__\n",
     True),
    ("key = '__doc__'\nU = getattr(object, key)\n", True),
])
def test_doc_reader_aliases_and_unresolved_fail_closed(repo, reader, all_docs):
    commit(repo, {"prove.py": PROVE, "other.py": OTHER, "reader.py": reader, "z.py": "# sentinel\nz = 1\n"})
    r = run(repo, "comment_strip.py", "--no-pr-skip", "src")
    assert r.returncode == 0, r.stderr
    assert read(repo, "z.py") == "z = 1\n"
    assert read(repo, "prove.py") == PROVE
    assert ('"""Other doc."""' in read(repo, "other.py")) is all_docs
    assert run(repo, "comment_equality.py", "HEAD").returncode == 0


def test_doctest_and_tool_decorator_docstrings_kept(repo):
    files = {"dt.py": 'import doctest\n\n\ndef f():\n    """>>> f()\n    1\n    """\n    return 1\n',
             "tl.py": 'from x import tool\n\n\n@tool\ndef f():\n    """Tool description."""\n    return 1\n'}
    commit(repo, {**files, "z.py": "# sentinel\nz = 1\n"})
    r = run(repo, "comment_strip.py", "--no-pr-skip", "src/dt.py", "src/tl.py", "src/z.py")
    assert r.returncode == 0, r.stderr
    assert read(repo, "dt.py") == files["dt.py"] and read(repo, "tl.py") == files["tl.py"]
    assert read(repo, "z.py") == "z = 1\n"


def test_mixed_line_endings_fail_and_strip_leaves_them(repo):
    src = "echo a\nprintf '%s' 'a\r\nb'\n# c\n"
    commit(repo, {"s.sh": src})
    write(repo, "s.sh", src.replace("\r\n", "\n"))
    r = run(repo, "comment_equality.py", "HEAD")
    assert r.returncode == 1 and "mixed line endings" in r.stderr
    write(repo, "s.sh", src)
    r = run(repo, "comment_strip.py", "--no-pr-skip", "src/s.sh")
    assert r.returncode == 1
    assert "LEFT src/s.sh: mixed line endings" in r.stderr and read(repo, "s.sh") == src


def test_ts_parse_errors_are_unparsed_and_left(repo):
    assert run(repo, "comment_budget.py", "--rebaseline").returncode == 0
    commit(repo, {"bad.ts": "// c\nconst = ;\n"})
    r = run(repo, "comment_budget.py", "--check")
    assert r.returncode == 1 and "unparsed: src/bad.ts: TS parse" in r.stderr
    r = run(repo, "comment_strip.py", "--no-pr-skip", "src/bad.ts")
    assert r.returncode == 1
    assert "LEFT src/bad.ts: unparsable: TS parse" in r.stderr and read(repo, "bad.ts") == "// c\nconst = ;\n"


def test_python_directive_moved_across_pass_fails(repo):
    commit(repo, {"t.py": "x = 1  # noqa\npass\n"})
    write(repo, "t.py", "x = 1\npass  # noqa\n")
    r = run(repo, "comment_equality.py", "HEAD")
    assert r.returncode == 1 and "allowlisted comment changed or moved" in r.stderr


def test_sole_docstring_to_pass_keeps_later_directive_anchor(repo):
    commit(repo, {"u.py": 'def f():\n    """Doc."""\n\n\nx = 1  # noqa\n'})
    assert run(repo, "comment_strip.py", "--no-pr-skip", "src/u.py").returncode == 0
    assert read(repo, "u.py") == "def f():\n    pass\n\n\nx = 1  # noqa\n"
    assert run(repo, "comment_equality.py", "HEAD").returncode == 0


def test_one_bad_ts_file_does_not_kill_the_batch(repo):
    import json
    payload = json.dumps([{"path": "a.ts", "text": None}, {"path": "b.ts", "text": "// c\nconst b = 1;\n"}])
    r = subprocess.run(["node", str(repo / "scripts" / "comment_tools.mjs"), "count"], input=payload,
                       capture_output=True, text=True)
    out = json.loads(r.stdout)
    assert r.returncode == 0 and "error" in out["a.ts"] and len(out["b.ts"]["comments"]) == 1


def test_strip_survives_ts_tool_failure(repo):
    import os
    env = {**os.environ, "COMMENT_TOOLS_TS": "/nonexistent/typescript"}
    r = subprocess.run([sys.executable, str(repo / "scripts" / "comment_strip.py"), "--no-pr-skip", "src"],
                       cwd=repo, capture_output=True, text=True, env=env)
    assert r.returncode == 1, r.stderr
    assert "LEFT src/b.tsx: unparsable" in r.stderr and read(repo, "b.tsx") == TSX
    assert read(repo, "a.py") != PY


NBSP = "\u00a0"


@pytest.mark.parametrize("name,base,head,why", [
    ("m1.py", "x = 1  # c\n", "x = 2\n", "python AST differs"),
    ("m2.ts", "export function f() {\n  return /*\n*/ 1;\n}\n", "export function f() {\n  return 1;\n}\n", "differs"),
    ("m3.tsx", f"export const A = () => <p>a\n{NBSP}\nb</p>;\n", f"export const A = () => <p>a {NBSP} b</p>;\n",
     "TS emit"),
    ("m4.tsx", f"export const A = () => <p>a\n {NBSP}b</p>;\n", f"export const A = () => <p>a {NBSP}b</p>;\n",
     "TS emit"),
    ("m5.sh", "x=1 # c\necho $x\n", "x=2\necho $x\n", "shell code differs"),
    ("d1.py", "x: int = 'a'  # type: ignore\n", "x: int = 'a'\n", "allowlisted"),
    ("d2.ts", "// eslint-disable-next-line no-console\nconsole.log(1);\n", "console.log(1);\n", "allowlisted"),
    ("d3.py", "#!/usr/bin/env python3\nx = 1\n", "x = 1\n", "shebang line changed"),
    ("d4.sh", "#!/bin/bash\necho a\n", "echo a\n", "shebang line changed"),
    ("d5.mjs", "#!/usr/bin/env node\nconsole.log(1);\n", "console.log(1);\n", "shebang line changed"),
    ("d6.sh", "# shellcheck disable=SC2086\necho $a\necho $b\n", "echo $a\n# shellcheck disable=SC2086\necho $b\n",
     "allowlisted"),
    ("d7.ts", "export const a = /*#__PURE__*/ f();\n", "export const a = f();\n", "allowlisted"),
    ("d8.ts", '/// <reference types="node" />\nexport const i = 1;\n', "export const i = 1;\n", "allowlisted"),
    ("d9.tsx", "/** @jsx h1 */\n/** @jsx h2 */\nexport const x = <p/>;\n",
     "/** @jsx h2 */\n/** @jsx h1 */\nexport const x = <p/>;\n", "differs"),
    ("d10.js", "// @ts-check\n// @ts-nocheck\nexport const x = 1;\n", "// @ts-nocheck\n// @ts-check\nexport const x = 1;\n",
     "allowlisted comment changed or moved"),
    ("v1.py", "x = 1  # c\n", "x = (\n", "head does not compile"),
    ("v2.py", "# c\nreturn 1\n", "return 1\n", "head does not compile"),
    ("v3.mjs", "// c\nconst x: number = 1;\nexport default x;\n", "const x: number = 1;\nexport default x;\n",
     "unparsable"),
    ("v4.sh", "# c\necho @(a|b)\n", "echo @(a|b)\n", "bash -n fails on head"),
    ("v5.py", "x = 1\r# c\ry = 2\r", "x = 1\ry = 2\r", "bare CR"),
    ("e1.py", "# coding: latin-1\ns = 'é'\n", "# coding: latin-1\ns = '\\u00e9'\n", "encoding iso-8859-1"),
    ("f1.sh", "#!/bin/bash\n# Usage: f1\n# more\ncase $1 in -h) sed -n '2,3p' \"$0\" ;; esac\n",
     "#!/bin/bash\n# Usage: f1\ncase $1 in -h) sed -n '2,3p' \"$0\" ;; esac\n", "reads its own source"),
    ("f2.sh", "#!/bin/bash\n# prose\nprintf '%s\\n' \"$LINENO\"\n", "#!/bin/bash\nprintf '%s\\n' \"$LINENO\"\n",
     "reads its own source"),
    ("f3.py", "# note\nprint(open(__file__).read())\n", "print(open(__file__).read())\n", "reads its own source"),
    ("f4.py", 'import inspect\n\n\ndef f():\n    """Doc."""\n    return inspect.getsource(f)\n',
     "import inspect\n\n\ndef f():\n    return inspect.getsource(f)\n", "reads its own source"),
    ("d11.py", "# pylint: skip-file\nprint(undefined_name)\n", "print(undefined_name)\n", "allowlisted"),
    ("d12.py", "# noinspection PyUnresolvedReferences\nimport x\n", "import x\n", "allowlisted"),
    ("d13.ts", "// oxlint-disable-next-line no-console\nconsole.log(1);\n", "console.log(1);\n", "allowlisted"),
    ("d14.ts", "// deno-lint-ignore no-explicit-any\nexport const a: any = 1;\n", "export const a: any = 1;\n",
     "allowlisted"),
    ("d15.mjs", '// @ts-check\n/** @import { Foo } from "./foo" */\n/** @type {Foo} */\nexport let x;\n',
     "// @ts-check\n/** @type {Foo} */\nexport let x;\n", "allowlisted"),
    ("d16.py", "x = 1  # legacy # noqa: E501\n", "x = 1\n", "allowlisted"),
    ("r1.py", '"""Usage: r1."""\nimport argparse\nargparse.ArgumentParser(description=__doc__)\n',
     "import argparse\nargparse.ArgumentParser(description=__doc__)\n", "python AST differs"),
    ("r2.py", 'import typer\n\n\ndef cmd():\n    """Help."""\n    return 1\n',
     "import typer\n\n\ndef cmd():\n    return 1\n", "python AST differs"),
    ("r3.py", 'import click\n\n\n' '@click.command()\ndef cmd():\n    """Help."""\n    return 1\n',
     "import click\n\n\n" "@click.command()\ndef cmd():\n    return 1\n", "python AST differs"),
    ("r4.py", 'def handler():\n    """Route doc."""\n    return 1\n\n\napp.add_api_route("/x", handler)\n',
     'def handler():\n    return 1\n\n\napp.add_api_route("/x", handler)\n', "python AST differs"),
    ("r5.py", 'from x import tool\n\n\n@tool\ndef f():\n    """Tool description."""\n    return 1\n',
     "from x import tool\n\n\n@tool\ndef f():\n    return 1\n", "python AST differs"),
    ("r6.py", 'import doctest\n\n\ndef f():\n    """>>> f()\n    1\n    """\n    return 1\n',
     "import doctest\n\n\ndef f():\n    return 1\n", "python AST differs"),
    ("r7.py", 'from inspect import getdoc as describe\n\n\ndef f():\n    """Help."""\n    return describe(f)\n',
     "from inspect import getdoc as describe\n\n\ndef f():\n    return describe(f)\n", "python AST differs"),
    ("d17.ts", "/*! lib v1 | (c) 2024 Acme */\nexport const a = 1;\n", "export const a = 1;\n", "allowlisted"),
    ("d18.mjs", "//! Copyright Acme\nexport const a = 1;\n", "export const a = 1;\n", "allowlisted"),
    ("d19.ts", "const a = 1;\n// eslint-disable-next-line no-x -- not @license\nconst b = 2;\n",
     "const a = 1;\n// eslint-disable-next-line no-x -- not @license\n\nconst b = 2;\n", "allowlisted"),
    ("d20.ts", '/// @ts-expect-error\nexport const n: number = "x";\n', 'export const n: number = "x";\n', "allowlisted"),
    ("d21.js", "/*\n global x\n*/\nexport default x;\n", "export default x;\n", "allowlisted"),
    ("sb1.py", "#!/usr/bin/env python3\nx = 1  # c\n", " #!/usr/bin/env python3\nx = 1\n", "shebang line changed"),
    ("sb2.sh", "#!/bin/bash\necho a # c\n", " #!/bin/bash\necho a\n", "shebang line changed"),
    ("x1.mjs", "// c\nexport const x = <div />;\n", "export const x = <div />;\n", "JSX in .mjs/.cjs"),
])
def test_hidden_change_or_dropped_directive_fails(repo, name, base, head, why):
    commit(repo, {name: base})
    write(repo, name, head)
    r = run(repo, "comment_equality.py", "HEAD")
    assert r.returncode == 1 and f"FAIL src/{name}:" in r.stderr and why in r.stderr, r.stderr


def test_self_reading_files_are_left_by_strip(repo):
    files = {"f1.sh": "#!/bin/bash\n# Usage: f1\ncase $1 in -h) sed -n '2p' \"$0\" ;; esac\n",
             "f2.sh": "#!/bin/bash\n# prose\nprintf '%s\\n' \"$LINENO\"\n",
             "target.py": "# kept\nx = 1\n",
             "reader.py": "import inspect\nimport target\nS = inspect.getsource(target)\n"}
    commit(repo, {**files, "z.py": "# sentinel\nz = 1\n"})
    assert run(repo, "comment_strip.py", "--no-pr-skip", "src").returncode == 0
    for name, text in files.items():
        assert read(repo, name) == text, name
    assert read(repo, "z.py") == "z = 1\n"
    write(repo, "target.py", "x = 1\n")
    r = run(repo, "comment_equality.py", "HEAD")
    assert r.returncode == 1 and "src/target.py: file reads its own source" in r.stderr


def test_strip_skips_budget_allow_files_and_symlinks(repo):
    commit(repo, {"real.py": "# c\nx = 1\n", "kept.py": "# why\ny = 1\n"})
    (repo / "src" / "link.py").symlink_to("real.py")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "l")
    assert run(repo, "comment_budget.py", "--rebaseline").returncode == 0
    assert run(repo, "comment_budget.py", "--allow", "src/kept.py", "--reason", "OF quirk").returncode == 0
    r = run(repo, "comment_strip.py", "--no-pr-skip", "src/link.py", "src/kept.py")
    assert r.returncode == 0, r.stderr
    assert "SKIP src/link.py: symlink" in r.stdout and "SKIP src/kept.py: budget" in r.stdout
    assert read(repo, "real.py") == "# c\nx = 1\n" and read(repo, "kept.py") == "# why\ny = 1\n"


def test_symlink_retarget_fails(repo):
    (repo / "src" / "link.py").symlink_to("a+b")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "l")
    (repo / "src" / "link.py").unlink()
    (repo / "src" / "link.py").symlink_to("a + b")
    r = run(repo, "comment_equality.py", "HEAD")
    assert r.returncode == 1 and "src/link.py: mode 120000: not a regular file" in r.stderr, r.stderr


def test_newline_in_path_fails(repo):
    commit(repo, {"n.py": "x = 1\n", "n.py\nx.py": "# c\ny = 2\n"})
    commit(repo, {"n.py\nx.py": "y = 3\n"})
    r = run(repo, "comment_equality.py", "HEAD~1", "HEAD")
    assert r.returncode == 1 and "newline in path" in r.stderr, r.stderr


def test_deleting_budget_manifest_fails(repo):
    assert run(repo, "comment_budget.py", "--rebaseline").returncode == 0
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "b")
    (repo / "scripts" / "comment-budget.json").unlink()
    r = run(repo, "comment_equality.py", "HEAD")
    assert r.returncode == 1 and "FAIL scripts/comment-budget.json: status D" in r.stderr, r.stderr


def test_equality_reports_ts_tool_failure_and_missing_shfmt(repo, tmp_path):
    import os
    write(repo, "b.tsx", TSX_PRUNED)
    write(repo, "c.sh", SH_PRUNED)
    env = {**os.environ, "COMMENT_TOOLS_TS": "/nonexistent/typescript"}
    r = subprocess.run([sys.executable, str(repo / "scripts" / "comment_equality.py"), "HEAD"], cwd=repo,
                       capture_output=True, text=True, env=env)
    assert r.returncode == 1 and "FAIL src/b.tsx: unparsable" in r.stderr, r.stderr
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("git", "node", "bash"):
        (bin_dir / tool).symlink_to(shutil.which(tool))
    r = subprocess.run([sys.executable, str(repo / "scripts" / "comment_equality.py"), "HEAD"], cwd=repo,
                       capture_output=True, text=True, env={**os.environ, "PATH": str(bin_dir)})
    assert r.returncode == 1 and "FAIL src/c.sh: unparsable: RuntimeError: shfmt not installed" in r.stderr, r.stderr


@pytest.mark.parametrize("reader", [
    "from inspect import getdoc as describe\nfrom other import g\nprint(describe(g))\n",
    "import inspect\nfrom other import g\nd = inspect.getdoc\nprint(d(g))\n",
    "from pydoc import render_doc as r\nfrom other import g\nprint(r(g))\n",
    "import inspect\nfrom other import g\nprint(list(map(inspect.getdoc, [g])))\n",
])
def test_aliased_doc_reader_keeps_docstring(repo, reader):
    commit(repo, {"other.py": OTHER, "reader.py": reader, "z.py": "# sentinel\nz = 1\n"})
    r = run(repo, "comment_strip.py", "--no-pr-skip", "src")
    assert r.returncode == 0, r.stderr
    assert read(repo, "other.py") == OTHER and read(repo, "z.py") == "z = 1\n"
    write(repo, "other.py", OTHER.replace('    """Other doc."""\n', ""))
    r = run(repo, "comment_equality.py", "HEAD")
    assert r.returncode == 1 and "FAIL src/other.py: python AST differs" in r.stderr, r.stderr


PROSE = {
    "w.py": '"""Mentions __doc__ and doctest in prose."""\nimport os  # noqa: F401\n'
            "# TODO: explain why noqa seems tempting\nx = 1  # old pylint: disable notes\n"
            'y: int = "a"  # legacy # type: ignore\ns = "see __doc__"\n\n\ndef f():\n    """Doc."""\n    return 1\n',
    "w.ts": "// we used eslint-disable here, see @ts-ignore history\n// eslint-disable-next-line no-console\n"
            "console.log(1);\n// global state is bad\n/* global window */\nexport const w = 1;\n",
    "w.sh": "#!/bin/bash\n# see shellcheck docs\n# shellcheck disable=SC2086\necho $w\n",
}


PROSE_OUT = {
    "w.py": 'import os  # noqa: F401\nx = 1\ny: int = "a"  # legacy # type: ignore\ns = "see __doc__"\n\n\n'
            "def f():\n    return 1\n",
    "w.ts": "// eslint-disable-next-line no-console\nconsole.log(1);\n/* global window */\nexport const w = 1;\n",
    "w.sh": "#!/bin/bash\n# shellcheck disable=SC2086\necho $w\n",
}


def test_prose_mentioning_directives_or_doc_is_counted_and_stripped(repo):
    import json
    commit(repo, PROSE)
    assert run(repo, "comment_budget.py", "--rebaseline").returncode == 0
    files = json.loads((repo / "scripts" / "comment-budget.json").read_text())["files"]
    assert (files["src/w.py"], files["src/w.ts"], files["src/w.sh"]) == (4, 2, 1)
    (repo / "scripts" / "comment-budget.json").unlink()
    r = run(repo, "comment_strip.py", "--no-pr-skip", "src/w.py", "src/w.ts", "src/w.sh")
    assert r.returncode == 0, r.stderr
    for name, want in PROSE_OUT.items():
        assert read(repo, name) == want, name
    assert run(repo, "comment_equality.py", "HEAD").returncode == 0


def test_model_like_class_docstrings_kept(repo):
    src = ('from dataclasses import dataclass\nfrom enum import Enum, IntEnum\n\n\nclass Color(Enum):\n'
           '    """Color doc."""\n    RED = 1\n\n\nclass Level(IntEnum):\n    """Level doc."""\n    LOW = 1\n\n\n'
           '@dataclass(frozen=True)\nclass P:\n    """P doc."""\n    x: int\n\n\n'
           'class T(SQLModel, table=True):\n    """T doc."""\n    id: int\n\n\ndef f():\n    """Plain doc."""\n    return 1\n')
    commit(repo, {"models.py": src})
    assert run(repo, "comment_strip.py", "--no-pr-skip", "src/models.py").returncode == 0
    assert read(repo, "models.py") == src.replace('    """Plain doc."""\n', "")


@pytest.mark.parametrize("mutate,why", [
    (lambda b: b["files"].__setitem__("src/a.py", float("nan")), "not a non-negative integer"),
    (lambda b: b["files"].__setitem__("src/a.py", -1), "not a non-negative integer"),
    (lambda b: b["files"].__setitem__("src/a.py", 6.5), "not a non-negative integer"),
    (lambda b: b["files"].__setitem__("src/a.py", True), "not a non-negative integer"),
    (lambda b: b["files"].__setitem__("src/a.py", "6"), "not a non-negative integer"),
    (lambda b: b["allow"].__setitem__("src/a.py", ""), "non-blank string"),
    (lambda b: b["allow"].__setitem__("src/a.py", "  "), "non-blank string"),
    (lambda b: b.__setitem__("files", []), "must be objects"),
])
def test_invalid_budget_manifest_fails(repo, mutate, why):
    import json
    assert run(repo, "comment_budget.py", "--rebaseline").returncode == 0
    budget = repo / "scripts" / "comment-budget.json"
    good = budget.read_text()
    b = json.loads(good)
    mutate(b)
    budget.write_text(json.dumps(b))
    r = run(repo, "comment_budget.py", "--check")
    assert r.returncode == 1 and why in r.stderr and "Traceback" not in r.stderr, r.stderr
    r = run(repo, "comment_strip.py", "--no-pr-skip", "src/a.py")
    assert r.returncode == 1 and why in r.stderr and read(repo, "a.py") == PY, r.stderr
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "bad base")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    budget.write_text(good)
    r = run(repo, "comment_budget.py", "--check")
    assert r.returncode == 1 and ":scripts/comment-budget.json: invalid" in r.stderr, r.stderr


def test_extensionless_shebang_scripts_and_dts_are_counted(repo):
    import json
    (repo / "src" / "vendor").mkdir()
    commit(repo, {"tool": "#!/usr/bin/env bash\n# prose\necho hi\n", "pytool": "#!/usr/bin/env python3\n# prose\nprint(1)\n",
                  "notes": "text # not code\n", "types.d.ts": "// prose\nexport declare const t: number;\n",
                  "vendor/v.d.ts": "// prose\nexport declare const v: number;\n"})
    assert run(repo, "comment_budget.py", "--rebaseline").returncode == 0
    files = json.loads((repo / "scripts" / "comment-budget.json").read_text())["files"]
    assert {k: files.get(k) for k in ("src/tool", "src/pytool", "src/types.d.ts", "src/notes", "src/vendor/v.d.ts")} \
        == {"src/tool": 1, "src/pytool": 1, "src/types.d.ts": 1, "src/notes": None, "src/vendor/v.d.ts": None}
    (repo / "scripts" / "comment-budget.json").unlink()
    r = run(repo, "comment_strip.py", "--no-pr-skip", "src")
    assert r.returncode == 0, r.stderr
    assert read(repo, "tool") == "#!/usr/bin/env bash\necho hi\n"
    assert read(repo, "pytool") == "#!/usr/bin/env python3\nprint(1)\n"
    assert read(repo, "types.d.ts") == "export declare const t: number;\n"
    assert run(repo, "comment_equality.py", "HEAD").returncode == 0
    write(repo, "tool", "#!/usr/bin/env python3\necho hi\n")
    write(repo, "notes", "text\n")
    r = run(repo, "comment_equality.py", "HEAD")
    assert "FAIL src/tool: language changed sh→py" in r.stderr and "FAIL src/notes: non-source file changed" in r.stderr


def test_comment_like_strings_survive_strip(repo):
    files = {"cs.py": "s = \"# x\"  # drop\nt = '''\n# y\n'''\n",
             "cs.ts": "const r = /\\/\\/x/; // drop\nconst u = '/* z */';\nexport { r, u };\n",
             "cs.sh": "#!/bin/bash\ny=${x#y} # drop\necho \"# x\"\necho '# q' # drop\n"}
    want = {"cs.py": "s = \"# x\"\nt = '''\n# y\n'''\n",
            "cs.ts": "const r = /\\/\\/x/;\nconst u = '/* z */';\nexport { r, u };\n",
            "cs.sh": "#!/bin/bash\ny=${x#y}\necho \"# x\"\necho '# q'\n"}
    commit(repo, files)
    r = run(repo, "comment_strip.py", "--no-pr-skip", "src/cs.py", "src/cs.ts", "src/cs.sh")
    assert r.returncode == 0, r.stderr
    for name, text in want.items():
        assert read(repo, name) == text, name
    assert run(repo, "comment_equality.py", "HEAD").returncode == 0


def test_pool_path_matches_serial(monkeypatch):
    monkeypatch.syspath_prepend(str(REPO / "scripts"))
    import comment_equality
    import comment_lang
    src = 'class M:\n    """Kept."""\n\n\ndef f():\n    """Dropped."""\n    return 1  # c\n'
    files = {f"m{i}.py": src for i in range(3)}
    files["s.sh"] = "#!/bin/bash\n# c\necho 1\n"
    ctx = comment_lang.PyContext(model_names={"M"})

    def snap():
        scans, errors = comment_lang.scan_files({p: (comment_lang.lang_of(p), t) for p, t in files.items()}, ctx)
        assert not errors, errors
        return {p: (s.lines, s.prunable, s.protected) for p, s in scans.items()}

    serial = snap()
    monkeypatch.setattr(comment_lang, "POOL_MIN", 0)
    assert snap() == serial and serial["m0.py"][2] == {"M"}
    head = {"m0.py": src.replace('    """Kept."""\n', ""), "m1.py": src.replace("  # c", "")}
    bad = comment_equality.check_pairs({p: ("py", src, t) for p, t in head.items()}, ctx, ctx)
    assert set(bad) == {"m0.py"}, bad


SELF_READERS = {
    "p1.py": "from pathlib import Path\n# c\nS = Path(__file__).resolve().read_text()\n",
    "p2.py": "import os\n# c\nS = open(os.path.abspath(__file__)).read()\n",
    "p3.py": "from pathlib import Path\n# c\nS = open(Path(__file__)).read()\n",
    "s1.sh": "#!/bin/bash\n# c\nme=$0\nsed -n 2p \"$me\"\n",
    "s2.sh": "#!/bin/bash\n# c\nsed -n 2p \\\n  \"$0\"\n",
    "p4.py": "from pathlib import Path\n# c\nHERE = Path(__file__)\nS = HERE.read_text()\n",
    "p5.py": "# c\nsrc = __file__\nS = open(src).read()\n",
    "p6.py": "import linecache\n# c\nS = linecache.getline(__file__, 1)\n",
    "p7.py": "import subprocess\n# c\nsubprocess.run(['sed', '-n', '1p', __file__])\n",
    "s3.sh": "#!/bin/bash\n# c\necho \"usage: $0\"\n",
    "s4.sh": "#!/bin/bash\n# c\ncat \"$(dirname \"$0\")/$(basename \"$0\")\"\n",
}


DIR_USES = {
    "d1.py": "from pathlib import Path\n# c\nS = (Path(__file__).parent / 'x').read_text()\n",
    "d2.py": "import os\n# c\nS = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'x')).read()\n",
    "d3.py": "from pathlib import Path\n# c\nROOT = Path(__file__).resolve().parents[1]\n",
    "d4.sh": "#!/bin/bash\n# c\ncd \"$(dirname \"$0\")\"\nawk '{print $0}' f\n",
    "d5.sh": "#!/bin/bash\n# c\nn=${0##*/}\nb=$(basename -- \"${BASH_SOURCE[0]}\")\necho \"$n $b\"\n",
}


@pytest.mark.parametrize("name", sorted(SELF_READERS))
def test_indirect_self_reads_freeze_file(repo, name):
    text = SELF_READERS[name]
    commit(repo, {name: text, "z.py": "# sentinel\nz = 1\n", **DIR_USES})
    assert run(repo, "comment_strip.py", "--no-pr-skip", "src").returncode == 0
    assert read(repo, name) == text
    assert read(repo, "z.py") == "z = 1\n"
    for other in DIR_USES:
        assert "# c" not in read(repo, other), other
    write(repo, name, text.replace("# c\n", ""))
    r = run(repo, "comment_equality.py", "HEAD")
    assert r.returncode == 1 and f"src/{name}: file reads its own source" in r.stderr, r.stderr


def test_unknown_language_errors_instead_of_shell_scan(repo, monkeypatch):
    monkeypatch.syspath_prepend(str(REPO / "scripts"))
    import comment_lang
    with pytest.raises(ValueError, match="not a py/sh source"):
        comment_lang.native_scan("notes", "txt", "echo hi\n# c\n", comment_lang.PyContext())
    commit(repo, {"tool": "#!/usr/bin/env node\n// c\nconsole.log(1)\n"})
    write(repo, "tool", "#!/usr/bin/env node\nconsole.log(1)\n")
    r = run(repo, "comment_equality.py", "HEAD")
    assert r.returncode == 1 and "FAIL src/tool: non-source file changed" in r.stderr, r.stderr


@pytest.mark.parametrize("src,unresolved,reads", [
    ("import inspect\ndoc_of = inspect.getdoc\n", True, False),
    ("from inspect import getdoc as doc_of\n", True, False),
    ("import inspect\n\n\ndef f(x):\n    g = inspect.getdoc\n    return g(f)\n", False, True),
    ("x = vars(f)['__doc__']\n", True, True),
    ("x = f.__dict__['__doc__']\n", True, True),
    ("x = getattr(f, '__doc__')\n", True, True),
    ("ok = name == '__doc__'\n", False, False),
    ("try:\n    from inspect import getdoc as g\nexcept ImportError:\n    g = None\n", True, False),
    ("import inspect\nif True:\n    doc_of = inspect.getdoc\n", True, False),
    ("key = '__doc__'\nx = getattr(f, key)\n", True, True),
    ("ok = name in ('__doc__', 'x')\n", False, False),
])
def test_reader_exports_and_doc_string_keys(monkeypatch, src, unresolved, reads):
    import ast
    monkeypatch.syspath_prepend(str(REPO / "scripts"))
    import comment_lang
    tf = comment_lang.tree_facts(ast.parse(src))
    assert (tf.unresolved, tf.reads_docs) == (unresolved, reads)
    assert comment_lang.py_context([src]).all_docs is unresolved


def test_unparsable_context_file_naming_any_doc_reader_protects_all(monkeypatch):
    monkeypatch.syspath_prepend(str(REPO / "scripts"))
    import comment_lang
    assert comment_lang.py_context(["def (:\n    render_doc(x)\n"]).all_docs
    assert not comment_lang.py_context(["def (:\n    x\n"]).all_docs


def test_newline_path_elsewhere_does_not_crash_gate(repo):
    commit(repo, {"a.py": PY + "# extra\n", "n.py\nx.py": "# c\ny = 2\n"})
    write(repo, "a.py", PY)
    r = run(repo, "comment_equality.py", "HEAD")
    assert r.returncode == 0 and "1 ok, 0 failed" in r.stdout, r.stdout + r.stderr
    write(repo, "a.py", PY + "# extra\n")
    r = run(repo, "comment_budget.py", "--check")
    assert r.returncode == 1 and "newline in path" in r.stdout + r.stderr, r.stdout + r.stderr
    r = run(repo, "comment_strip.py", "--no-pr-skip", "src")
    assert r.returncode == 1 and "newline in path" in r.stderr and "# extra" not in read(repo, "a.py"), r.stderr


def test_bare_legal_banner_is_prunable(repo):
    commit(repo, {"lg.ts": "/*! lib v1 */\nexport const a = 1;\n", "z.py": "# sentinel\nz = 1\n"})
    r = run(repo, "comment_strip.py", "--no-pr-skip", "src")
    assert r.returncode == 0, r.stderr
    assert read(repo, "lg.ts") == "export const a = 1;\n" and read(repo, "z.py") == "z = 1\n"
    r = run(repo, "comment_equality.py", "HEAD")
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("src,names,unresolved", [
    ("import inspect\nfrom t import f\ninspect.getsource(f)\n", {"f"}, False),
    ("from inspect import getsource as source\nfrom t import f\nsource(f)\n", {"f"}, True),
    ("import inspect\nfrom t import f\n\n\ndef h():\n    g = inspect.getsource\n    return g(f)\n", {"f"}, False),
    ("import inspect\nfrom t import f\nlist(map(inspect.getsource, [f]))\n", set(), True),
])
def test_source_reader_aliases_resolve_or_fail_closed(monkeypatch, src, names, unresolved):
    import ast
    monkeypatch.syspath_prepend(str(REPO / "scripts"))
    import comment_lang
    tf = comment_lang.tree_facts(ast.parse(src))
    assert (tf.src_names, tf.src_unresolved) == (names, unresolved)
    ctx = comment_lang.py_context([src])
    assert ctx.all_src is unresolved
    assert comment_lang.py_scan("u.py", "# c\nu = 1\n", ctx).frozen is unresolved


def test_aliased_source_reader_freezes_target(repo):
    target = "# c\ndef f():\n    return 1\n"
    reader = "from t import f\n\n\ndef show():\n    from inspect import getsource as source\n    return source(f)\n"
    commit(repo, {"t.py": target, "r.py": reader, "z.py": "# sentinel\nz = 1\n"})
    assert run(repo, "comment_strip.py", "--no-pr-skip", "src").returncode == 0
    assert read(repo, "t.py") == target and read(repo, "z.py") == "z = 1\n"
    write(repo, "t.py", target.replace("# c\n", ""))
    r = run(repo, "comment_equality.py", "HEAD")
    assert r.returncode == 1 and "src/t.py: file reads its own source" in r.stderr, r.stderr


def test_budget_counts_docs_hidden_only_by_repo_wide_fallback(repo):
    import json
    commit(repo, {"other.py": OTHER, "reader.py": "from inspect import getdoc as describe\n"})
    assert run(repo, "comment_budget.py", "--rebaseline").returncode == 0
    assert json.loads((repo / "scripts" / "comment-budget.json").read_text())["files"].get("src/other.py") == 1
    assert run(repo, "comment_strip.py", "--no-pr-skip", "src/other.py").returncode == 0
    assert read(repo, "other.py") == OTHER


def test_crlf_shell_comment_edit_fails_and_strip_leaves_it(repo):
    src = "true # note\r\necho a\r\n"
    commit(repo, {"cr.sh": src})
    r = run(repo, "comment_strip.py", "--no-pr-skip", "src/cr.sh")
    assert r.returncode == 1 and "LEFT src/cr.sh: CR in shell script" in r.stderr, r.stderr
    assert (repo / "src" / "cr.sh").read_bytes() == src.encode()
    (repo / "src" / "cr.sh").write_bytes(b"true\r\necho a\r\n")
    r = run(repo, "comment_equality.py", "HEAD")
    assert r.returncode == 1 and "FAIL src/cr.sh: CR in shell script" in r.stderr, r.stderr


def test_help_assignment_alias_keeps_docstrings(repo):
    import json
    reader = OTHER.replace("g()", "f()") + "h = help\nh(f)\n"
    commit(repo, {"other.py": OTHER, "reader.py": reader})
    r = run(repo, "comment_budget.py", "--report", "--json")
    assert json.loads(r.stdout)["src/reader.py"] == 0
    r = run(repo, "comment_strip.py", "--no-pr-skip", "src")
    assert r.returncode == 0, r.stderr
    assert read(repo, "reader.py") == reader and read(repo, "other.py") == OTHER


def test_unrelated_help_method_does_not_protect_docstring(repo):
    commit(repo, {"other.py": OTHER + "obj.help(g)\n"})
    r = run(repo, "comment_strip.py", "--no-pr-skip", "src/other.py")
    assert r.returncode == 0, r.stderr
    assert read(repo, "other.py") == 'def g():\n    return 1\nobj.help(g)\n'


@pytest.mark.parametrize("reader,target", [
    ("help(f)", False),
    ("help('missing_module')", False),
    ("help('missing.other')", False),
    ("help('src.other')", True),
    ("import other\nhelp(other)", True),
    ("import pydoc as pd\npd.doc('other')", True),
    ("from pydoc import doc as show\nshow('other')", True),
])
def test_help_and_pydoc_keep_runtime_docstrings(repo, reader, target):
    import json
    local = '"""Reader doc."""\ndef f():\n    """Local doc."""\n    return 1\n' + reader + "\n"
    commit(repo, {"reader.py": local, "other.py": OTHER})
    r = run(repo, "comment_budget.py", "--report", "--json")
    counts = json.loads(r.stdout)
    assert counts["src/reader.py"] == 0
    assert counts["src/other.py"] == int(not target)
    r = run(repo, "comment_strip.py", "--no-pr-skip", "src/reader.py", "src/other.py")
    assert r.returncode == 0, r.stderr
    assert read(repo, "reader.py") == local
    assert read(repo, "other.py") == (OTHER if target else "def g():\n    return 1\n")


def test_cadence_directive_is_uncounted_and_preserved(repo):
    src = "x = 1  # cadence-ok: intentional\n"
    commit(repo, {"cadence.py": src + "# prose\n"})
    r = run(repo, "comment_budget.py", "--report", "--json")
    import json
    assert json.loads(r.stdout)["src/cadence.py"] == 1
    assert run(repo, "comment_strip.py", "--no-pr-skip", "src/cadence.py").returncode == 0
    assert read(repo, "cadence.py") == src


@pytest.mark.parametrize("revisions", [("src/a.py",), ("HEAD", "src/a.py"), ("HEAD:src/a.py",)])
def test_equality_rejects_non_commit_revisions(repo, revisions):
    r = run(repo, "comment_equality.py", *revisions)
    assert r.returncode == 1 and "not a commit" in r.stderr, r.stderr
