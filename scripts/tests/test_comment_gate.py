import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TOOLS = ["comment_lang.py", "comment_budget.py", "comment_equality.py", "comment_strip.py", "comment_tools.mjs"]

PY = '''"""Mod doc."""
import os  # noqa: F401
# comment
def f(x):
    """Doc."""
    # step
    return x + 1  # trailing


@router.get("/x")
def route():
    """Route doc."""
    return 1


class M(BaseModel):
    """Schema doc."""
    a: int


class N(M):
    """Inherited schema doc."""


def stub():
    """Only a docstring."""
'''

PY_PRUNED = '''import os  # noqa: F401
def f(x):
    return x + 1


@router.get("/x")
def route():
    """Route doc."""
    return 1


class M(BaseModel):
    """Schema doc."""
    a: int


class N(M):
    """Inherited schema doc."""


def stub():
    pass
'''

TSX = '''// @ts-nocheck
/** doc */
export function A() {
  // c
  return (
    <div>
      {/* jsx comment */}
      <span>hi</span>
      foo
      {/* between */}
      bar
    </div>
  );
}
const x = 1 // t
const y = `// not ${x} comment`
'''

TSX_PRUNED = '''// @ts-nocheck
export function A() {
  return (
    <div>
      <span>hi</span>
      foo
      {/* between */}
      bar
    </div>
  );
}
const x = 1
const y = `// not ${x} comment`
'''

JS = '''/** @type {number} */
const n = 1;
// plain
export default n;
'''

SH = '''#!/bin/bash
# hi
x=1 # t
cat <<EOT
# keep
EOT
'''

SH_PRUNED = '''#!/bin/bash
x=1
cat <<EOT
# keep
EOT
'''


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / "scripts").mkdir()
    for t in TOOLS:
        shutil.copy(REPO / "scripts" / t, tmp_path / "scripts" / t)
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "node_modules").symlink_to(REPO / "app" / "node_modules")
    (tmp_path / ".gitignore").write_text("__pycache__/\n")
    (tmp_path / "src").mkdir()
    for name, text in {"a.py": PY, "b.tsx": TSX, "c.sh": SH, "d.mjs": JS}.items():
        (tmp_path / "src" / name).write_text(text)
    git = lambda *a: subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)
    git("init", "-q")
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    return tmp_path


def run(repo, *args):
    return subprocess.run([sys.executable, str(repo / "scripts" / args[0]), *args[1:]], cwd=repo,
                          capture_output=True, text=True)


def write(repo, name, text):
    (repo / "src" / name).write_text(text)


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


def test_budget_check_teaches_and_allow_raises(repo):
    assert run(repo, "comment_budget.py", "--rebaseline").returncode == 0
    assert run(repo, "comment_budget.py", "--check").returncode == 0
    write(repo, "a.py", PY + "# new note\n")
    r = run(repo, "comment_budget.py", "--check")
    assert r.returncode == 1
    assert "Rename/extract instead" in r.stderr and "src/a.py" in r.stderr
    assert run(repo, "comment_budget.py", "--allow", "src/a.py").returncode == 2
    assert run(repo, "comment_budget.py", "--allow", "src/a.py", "--reason", "OF quirk").returncode == 0
    assert run(repo, "comment_budget.py", "--check").returncode == 0


def test_budget_counts(repo):
    run(repo, "comment_budget.py", "--rebaseline")
    import json
    files = json.loads((repo / "scripts" / "comment-budget.json").read_text())["files"]
    assert files["src/a.py"] == 6
    assert files["src/c.sh"] == 2
    assert files["src/d.mjs"] == 1


def git(repo, *a):
    return subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True, text=True).stdout


def commit(repo, files: dict[str, str]):
    for name, text in files.items():
        (repo / "src" / name).write_bytes(text.encode())
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c")


def read(repo, name):
    return (repo / "src" / name).read_bytes().decode()


STRIP_IN = {
    "e.tsx": 'const s = "😀"; // c\nexport const A = () => (\n  <div>\n    {/* drop */}\n    <p>😀a{/* keep */}b</p>\n'
             '    <p>// text</p>\n  </div>\n);\n',
    "f.sh": "#!/bin/bash\r\n# hi\r\nx=1 # t\r\necho $x\r\n",
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
    "f.sh": "#!/bin/bash\r\nx=1\r\necho $x\r\n",
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
    assert "PARTIAL src/j.py: 1" in r.stderr
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
    ({"l.py": "# c\n# d\n# -*- coding: latin-1 -*-\nx = 1\n"}, "l.py", "# -*- coding: latin-1 -*-\nx = 1\n",
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


def test_check_fails_on_unparsed_and_new_file_with_comments(repo):
    assert run(repo, "comment_budget.py", "--rebaseline").returncode == 0
    commit(repo, {"bad.py": "def (:\n", "new.py": "# hi\nx = 1\n"})
    r = run(repo, "comment_budget.py", "--check")
    assert r.returncode == 1
    assert "unparsed: src/bad.py" in r.stderr
    assert "Comment added in src/new.py:1" in r.stderr


def test_lower_never_raises_and_drops_deleted(repo):
    import json
    run(repo, "comment_budget.py", "--rebaseline")
    budget = repo / "scripts" / "comment-budget.json"
    before = json.loads(budget.read_text())["files"]
    write(repo, "a.py", PY + "# more\n")
    git(repo, "rm", "-q", "src/c.sh")
    assert run(repo, "comment_budget.py", "--lower", "src/a.py", "src/c.sh").returncode == 0
    after = json.loads(budget.read_text())["files"]
    assert after["src/a.py"] == before["src/a.py"]
    assert "src/c.sh" not in after
    write(repo, "a.py", PY_PRUNED)
    assert run(repo, "comment_budget.py", "--lower").returncode == 0
    assert json.loads(budget.read_text())["files"].get("src/a.py", 0) < before["src/a.py"]


def test_growth_needs_new_allow_reason(repo):
    import json
    run(repo, "comment_budget.py", "--rebaseline")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "b")
    budget = repo / "scripts" / "comment-budget.json"
    b = json.loads(budget.read_text())
    b["files"]["src/a.py"] += 1
    budget.write_text(json.dumps(b))
    r = run(repo, "comment_budget.py", "--growth", "HEAD")
    assert r.returncode == 1 and "src/a.py" in r.stderr
    write(repo, "a.py", PY + "# why\n")
    assert run(repo, "comment_budget.py", "--allow", "src/a.py", "--reason", "OF quirk").returncode == 0
    assert run(repo, "comment_budget.py", "--growth", "HEAD").returncode == 0


def test_jsx_text_slashes_not_counted(repo):
    commit(repo, {"q.tsx": "export const Q = () => <p>// not /* a */ comment</p>;\n"})
    run(repo, "comment_budget.py", "--rebaseline")
    import json
    files = json.loads((repo / "scripts" / "comment-budget.json").read_text())["files"]
    assert "src/q.tsx" not in files


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
OTHER = 'def g():\n    """Other doc."""\n    return 1\n'


@pytest.mark.parametrize("reader,all_docs", [
    ("import prove as p\nU = p.__doc__\n", False),
    ("from pkg import prove as p\nU = p.__doc__\n", False),
    ("import importlib.util\nspec = importlib.util.spec_from_file_location('prove', 'src/prove.py')\n"
     "mod = importlib.util.module_from_spec(spec)\nU = mod.__doc__\n", True),
    ("from h import HANDLERS\nU = HANDLERS['k'].__doc__\n", True),
    ("U = getattr(object, '__doc__')\n", True),
    ("import prove\nU = prove.__doc__\n\n\nclass B:\n    def show(self):\n        return self.g.__doc__\n", True),
])
def test_doc_reader_aliases_and_unresolved_fail_closed(repo, reader, all_docs):
    commit(repo, {"prove.py": PROVE, "other.py": OTHER, "reader.py": reader})
    run(repo, "comment_strip.py", "--no-pr-skip", "src")
    assert read(repo, "prove.py") == PROVE
    assert ('"""Other doc."""' in read(repo, "other.py")) is all_docs
    assert run(repo, "comment_equality.py", "HEAD").returncode == 0


def test_doctest_and_tool_decorator_docstrings_kept(repo):
    files = {"dt.py": 'import doctest\n\n\ndef f():\n    """>>> f()\n    1\n    """\n    return 1\n',
             "tl.py": 'from x import tool\n\n\n@tool\ndef f():\n    """Tool description."""\n    return 1\n'}
    commit(repo, files)
    run(repo, "comment_strip.py", "--no-pr-skip", "src/dt.py", "src/tl.py")
    assert read(repo, "dt.py") == files["dt.py"] and read(repo, "tl.py") == files["tl.py"]


def test_mixed_line_endings_fail_and_strip_leaves_them(repo):
    src = "echo a\nprintf '%s' 'a\r\nb'\n# c\n"
    commit(repo, {"s.sh": src})
    write(repo, "s.sh", src.replace("\r\n", "\n"))
    r = run(repo, "comment_equality.py", "HEAD")
    assert r.returncode == 1 and "mixed line endings" in r.stderr
    write(repo, "s.sh", src)
    r = run(repo, "comment_strip.py", "--no-pr-skip", "src/s.sh")
    assert "LEFT src/s.sh: mixed line endings" in r.stderr and read(repo, "s.sh") == src


def test_growth_passes_without_base_budget_and_raises_on_bad_rev(repo):
    run(repo, "comment_budget.py", "--rebaseline")
    r = run(repo, "comment_budget.py", "--growth", "HEAD")
    assert r.returncode == 0 and "growth check passes" in r.stdout
    r = run(repo, "comment_budget.py", "--growth", "no-such-rev")
    assert r.returncode != 0 and "CalledProcessError" in r.stderr


def test_ts_parse_errors_are_unparsed_and_left(repo):
    run(repo, "comment_budget.py", "--rebaseline")
    commit(repo, {"bad.ts": "// c\nconst = ;\n"})
    r = run(repo, "comment_budget.py", "--check")
    assert r.returncode == 1 and "unparsed: src/bad.ts: TS parse" in r.stderr
    r = run(repo, "comment_strip.py", "--no-pr-skip", "src/bad.ts")
    assert "LEFT src/bad.ts: unparsable: TS parse" in r.stderr and read(repo, "bad.ts") == "// c\nconst = ;\n"


def test_workflow_and_run_tests_probe_the_budget_file():
    wf = (REPO / ".github" / "workflows" / "comment-budget.yml").read_text()
    rt = (REPO / "scripts" / "run-tests.sh").read_text()
    assert "[ -f scripts/comment-budget.json ]" in wf and "REVIEW.md" not in wf
    assert '[ -f "$ROOT/scripts/comment-budget.json" ]' in rt


def test_python_directive_moved_across_pass_fails(repo):
    commit(repo, {"t.py": "x = 1  # noqa\npass\n"})
    write(repo, "t.py", "x = 1\npass  # noqa\n")
    r = run(repo, "comment_equality.py", "HEAD")
    assert r.returncode == 1 and "allowlisted comment changed or moved" in r.stderr


def test_sole_docstring_to_pass_keeps_later_directive_anchor(repo):
    commit(repo, {"u.py": 'def f():\n    """Doc."""\n\n\nx = 1  # noqa\n'})
    run(repo, "comment_strip.py", "--no-pr-skip", "src/u.py")
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
    assert r.returncode == 0, r.stderr
    assert "LEFT src/b.tsx: unparsable" in r.stderr and read(repo, "b.tsx") == TSX
    assert read(repo, "a.py") != PY
