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
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("COMMENT_BASE", "origin/main")
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
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    return tmp_path


def run(repo, *args):
    return subprocess.run([sys.executable, str(repo / "scripts" / args[0]), *args[1:]], cwd=repo,
                          capture_output=True, text=True)


def write(repo, name, text):
    (repo / "src" / name).write_text(text)


def git(repo, *a):
    return subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True, text=True).stdout


def commit(repo, files: dict[str, str]):
    for name, text in files.items():
        (repo / "src" / name).write_bytes(text.encode())
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c")


def read(repo, name):
    return (repo / "src" / name).read_bytes().decode()


OTHER = 'def g():\n    """Other doc."""\n    return 1\n'
