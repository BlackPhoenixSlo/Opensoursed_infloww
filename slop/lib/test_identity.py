"""Run identity (lib/identity.py) on a throwaway git repo: what changes `source_id`, what `env_id` keeps."""
import base64
import json
import os
import subprocess
import sys

import pytest

from slop.lib import identity, recovery


def _git(repo, *a):
    subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / "app").mkdir(parents=True)
    (r / "venv/bin").mkdir(parents=True)
    (r / ".gitignore").write_text("venv\napp/.next/\napp/node_modules/\napp/.env*.local\napp/next-env.d.ts\n"
                                  "slop/evidence/\n")
    (r / "app/tsconfig.json").write_text('{"a": 1}\n')
    (r / "service.py").write_text("x = 1\n")
    (r / "python3.12").write_text("")
    (r / "python3.13").write_text("")
    os.symlink(r / "python3.12", r / "venv/bin/python")
    _git(r, "init", "-q")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    return r


def _lock(repo, pid):
    """The app lock as lib/stack.py writes it."""
    (repo / "app/.next").mkdir(parents=True, exist_ok=True)
    (repo / identity.APP_LOCK).write_text(f"pid {pid} since 12:00:00: slop/run x\n")


def _holder(repo, pid, originals):
    """Another run's app lock and saved originals, as lib/stack.py and lib/recovery.py AppFiles leave them."""
    _lock(repo, pid)
    (repo / identity.APP_STATE).write_text(json.dumps({"originals": {
        k: None if v is None else base64.b64encode(v).decode() for k, v in originals.items()}}))


def _files(repo):
    return recovery.AppFiles(repo / "app", identity.APP_FILES, repo / identity.APP_STATE)


def _dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_source_id_is_stable_and_ignores_ignored_output(repo):
    a = identity.source_id(repo)
    (repo / "slop/evidence").mkdir(parents=True)
    (repo / "slop/evidence/run.txt").write_text("a run's own output")
    assert identity.source_id(repo) == a


@pytest.mark.parametrize("change", [
    "head", "tracked_edit", "untracked_file", "app_env_file", "lock_sha", "venv_python", "tsconfig_edit",
    "next_env_edit"])
def test_source_id_changes_with_every_input(repo, change):
    a = identity.source_id(repo)
    if change == "head":
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "next")
    elif change == "tracked_edit":
        (repo / "service.py").write_text("x = 2\n")
    elif change == "untracked_file":
        (repo / "probe").write_text("")
    elif change == "app_env_file":  # ignored, but `next` loads it
        (repo / "app/.env.local").write_text("NEXT_PUBLIC_X=1\n")
    elif change == "lock_sha":
        (repo / "app/node_modules").mkdir()
        (repo / "app/node_modules" / identity.LOCK_SHA).write_text("abc\n")
    elif change == "venv_python":
        os.unlink(repo / "venv/bin/python")
        os.symlink(repo / "python3.13", repo / "venv/bin/python")
    elif change == "tsconfig_edit":  # nobody holds the app lock: a developer's edit
        (repo / "app/tsconfig.json").write_text('{"a": 2}\n')
    elif change == "next_env_edit":  # ignored, but read by the app build
        (repo / "app/next-env.d.ts").write_text("// edited\n")
    assert identity.source_id(repo) != a, change


def test_live_holders_rewrite_reads_as_its_saved_originals(repo):
    a = identity.source_id(repo)
    _holder(repo, os.getpid(), {"tsconfig.json": b'{"a": 1}\n', "next-env.d.ts": None})
    (repo / "app/tsconfig.json").write_text('{"a": 1, "include": [".next/types"]}\n')  # `next dev`'s rewrite
    (repo / "app/next-env.d.ts").write_text("/// <reference types=\"next\" />\n")
    assert identity.source_id(repo) == a


def _killed_run(repo):
    """A run SIGKILLed past `next dev`'s rewrite: its state and rewrites stay, its pid is gone."""
    (repo / "app/.next").mkdir(parents=True, exist_ok=True)
    f = _files(repo)
    f.save()
    _lock(repo, _dead_pid())
    (repo / "app/tsconfig.json").write_text('{"a": 1, "include": [".next/types"]}\n')
    (repo / "app/next-env.d.ts").write_text("/// <reference types=\"next\" />\n")
    f.note_written()


def _next_run(repo):
    """The next run's stack: takes the lock (its _reap undoes the leftovers), `next dev` rewrites, it exits."""
    f = _files(repo)
    f.save()
    _lock(repo, os.getpid())
    (repo / "app/tsconfig.json").write_text('{"a": 1, "include": [".next/types"]}\n')
    f.note_written()
    f.restore()


def test_first_run_after_a_killed_run_reads_one_source_start_and_end(repo):
    """The killed run's unchanged rewrite reads as the originals its reaper restores: not `raced`."""
    a = identity.source_id(repo)
    _killed_run(repo)
    start = identity.source_id(repo)
    _next_run(repo)
    assert start == identity.source_id(repo) == a
    assert (repo / "app/tsconfig.json").read_text() == '{"a": 1}\n'


def test_developer_edit_after_a_killed_run_counts_as_disk(repo):
    a = identity.source_id(repo)
    _killed_run(repo)
    (repo / "app/tsconfig.json").write_text('{"a": 2}\n')  # the reaper keeps it (WARN): the run's source
    start = identity.source_id(repo)
    _next_run(repo)
    assert start == identity.source_id(repo) != a
    assert (repo / "app/tsconfig.json").read_text() == '{"a": 2}\n'


@pytest.mark.parametrize("state", [
    "{", "[]", '{"originals": []}', '{"originals": {"tsconfig.json": 5}}',
    '{"originals": {"tsconfig.json": "!!!x"}}', '{"originals": {"next-env.d.ts": 1}, "written": 3}'])
@pytest.mark.parametrize("lock", ["pid {live}", "pid {dead}", "garbage", "pid 0", "pid -1",
                                  "pid 99999999999999999999999"])
def test_malformed_lock_or_state_reads_as_disk_and_never_raises(repo, state, lock):
    a = identity.source_id(repo)
    (repo / "app/.next").mkdir()
    (repo / identity.APP_LOCK).write_text(lock.format(live=os.getpid(), dead=_dead_pid()))
    (repo / identity.APP_STATE).write_text(state)
    assert identity.source_id(repo) == a
    assert (repo / identity.APP_STATE).read_text() == state  # read-only: never discarded outside a stack


def test_saved_original_absent_and_empty_differ(repo):
    (repo / "app/next-env.d.ts").write_text("")
    empty = identity.source_id(repo)
    (repo / "app/next-env.d.ts").unlink()
    absent = identity.source_id(repo)
    assert empty != absent
    (repo / "app/next-env.d.ts").write_text("/// <reference types=\"next\" />\n")  # a live run's rewrite
    _holder(repo, os.getpid(), {"tsconfig.json": b'{"a": 1}\n', "next-env.d.ts": b""})
    assert identity.source_id(repo) == empty
    _holder(repo, os.getpid(), {"tsconfig.json": b'{"a": 1}\n', "next-env.d.ts": None})
    assert identity.source_id(repo) == absent


def test_env_id_keeps_names_never_values():
    secret = "s3cr3t-value"
    h, names = identity.env_id({"PATH": "/bin", "OPENAI_API_KEY": secret})
    assert names == ["OPENAI_API_KEY", "PATH"]
    assert secret not in h and all("=" not in n for n in names)


@pytest.mark.parametrize("name", ["CLAUDE_CODE_SESSION_ID", "T3CODE_CLI_PATH", "TERM_PROGRAM", "SHLVL", "PWD",
                                  "_", "XPC_SERVICE_NAME", "__CF_USER_TEXT_ENCODING", "SLOP_LOCK_WAIT_S",
                                  "SLOP_SHARE_WAIT_S", *identity.GATE_ENV])
def test_env_id_ignores_noise_bookkeeping_and_admission_waits(name):
    base = {"PATH": "/bin"}
    assert identity.env_id({**base, name: "1"}) == identity.env_id(base)


@pytest.mark.parametrize("name", ["PATH", "SLOP_GATE", "SLOP_GATE_EXCLUSIVE", "SLOP_MAX_THREADS_PROC",
                                  "SLOP_MAX_THREADS_PROC_HARD", "SLOP_MAX_THREADS_TOTAL", "SLOP_MAX_SOCKETS_RUN",
                                  "PLAYWRIGHT_NODEJS_PATH", "SLOP_PW_NODE", "PROXY_FLAP_BAD_PCT", "CONDA_PREFIX"])
def test_env_id_counts_guard_policy_runtime_and_unknown_vars(name):
    base = {"PATH": "/bin", name: "1"} if name != "PATH" else {"PATH": "/bin"}
    changed = {**base, name: "2"}
    assert identity.env_id(changed)[0] != identity.env_id(base)[0]


A, B = "a" * 64, "b" * 64
CUR = {"source_id": A, "env_id": "E", "env_names": ["PATH", "X"]}


@pytest.mark.parametrize("base,want", [
    ({}, "recorded before Run identity (no source_id)"),
    ({"source_id": None, "source_id_end": None, "env_id": "E", "env_names": ["PATH", "X"]}, "could not be read"),
    ({"source_id": A, "source_id_end": None, "env_id": "E", "env_names": ["PATH", "X"]}, "could not be read"),
    ({"source_id": A, "source_id_end": B, "env_id": "E", "env_names": ["PATH", "X"]}, "source_id != source_id_end"),
    ({"source_id": B, "source_id_end": B, "env_id": "E", "env_names": ["PATH", "X"]}, "source differs"),
    ({"source_id": A, "source_id_end": A, "env_id": "F", "env_names": ["PATH"]}, "added ['X'], removed []"),
    ({"source_id": A, "source_id_end": A, "env_id": "F", "env_names": ["PATH", "X", "Y"]}, "removed ['Y']"),
    ({"source_id": A, "source_id_end": A, "env_id": "F", "env_names": ["PATH", "X"]},
     "env value changed (values are not stored)"),
])
def test_baseline_problem_names_the_part_that_differs(base, want):
    assert want in identity.baseline_problem(base, CUR)


def test_env_problems_never_say_source():
    """slop/README's cross-shell rule tells an env refusal from a source refusal by the word."""
    for base in ({"source_id": A, "source_id_end": A, "env_id": "F", "env_names": ["PATH"]},
                 {"source_id": A, "source_id_end": A, "env_id": "F", "env_names": ["PATH", "X"]}):
        why = identity.baseline_problem(base, CUR)
        assert "env" in why and "source" not in why


def test_unreadable_current_source_is_named():
    base = {"source_id": A, "source_id_end": A, "env_id": "E", "env_names": ["PATH", "X"]}
    assert "this checkout's source could not be read now" in identity.baseline_problem(base, {**CUR, "source_id": None})


def test_equal_identity_is_no_problem():
    assert identity.baseline_problem({"source_id": A, "source_id_end": A, "env_id": "E",
                                      "env_names": ["X", "PATH"]}, CUR) is None


@pytest.mark.parametrize("runs,ok", [
    ([{"source_id": A, "source_id_end": A}, {"source_id": A, "source_id_end": A}], True),
    ([{"source_id": A, "source_id_end": A}, {"source_id": B, "source_id_end": B}], False),
    ([{"source_id": A, "source_id_end": A}, {"source_id": A, "source_id_end": B}], False),
    ([{"source_id": A, "source_id_end": B}, {"source_id": B, "source_id_end": B}], False),
    ([{"source_id": None, "source_id_end": None}, {"source_id": None, "source_id_end": None}], False),
])
def test_raced(runs, ok):
    assert (identity.raced(runs) is None) is ok


def test_unreadable_source_is_not_called_raced():
    why = identity.raced([{"source_id": A, "source_id_end": A}, {"source_id": None, "source_id_end": A}])
    assert why.startswith("source unreadable")
