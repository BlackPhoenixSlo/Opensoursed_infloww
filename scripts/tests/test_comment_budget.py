from comment_gate_common import OTHER, PY, PY_PRUNED, commit, git, repo, run, write


def test_budget_check_teaches_and_allow_raises(repo):
    assert run(repo, "comment_budget.py", "--rebaseline").returncode == 0
    assert run(repo, "comment_budget.py", "--check").returncode == 0
    write(repo, "a.py", PY + "# new note\n")
    r = run(repo, "comment_budget.py", "--check")
    assert r.returncode == 1
    assert "Rename/extract instead" in r.stderr and "src/a.py" in r.stderr
    assert run(repo, "comment_budget.py", "--allow", "src/a.py").returncode == 2
    assert run(repo, "comment_budget.py", "--allow", "src/a.py", "--reason", "   ").returncode == 2
    assert run(repo, "comment_budget.py", "--check").returncode == 1
    assert run(repo, "comment_budget.py", "--allow", "src/a.py", "--reason", "OF quirk").returncode == 0
    assert run(repo, "comment_budget.py", "--check").returncode == 0


def test_budget_counts(repo):
    assert run(repo, "comment_budget.py", "--rebaseline").returncode == 0
    import json
    files = json.loads((repo / "scripts" / "comment-budget.json").read_text())["files"]
    assert files["src/a.py"] == 6
    assert files["src/c.sh"] == 2
    assert files["src/d.mjs"] == 1


def test_check_fails_on_unparsed_and_new_file_with_comments(repo):
    assert run(repo, "comment_budget.py", "--rebaseline").returncode == 0
    commit(repo, {"bad.py": "def (:\n", "new.py": "# hi\nx = 1\n"})
    r = run(repo, "comment_budget.py", "--check")
    assert r.returncode == 1
    assert "unparsed: src/bad.py" in r.stderr
    assert "Comment added in src/new.py:1" in r.stderr


def test_lower_never_raises_and_drops_deleted(repo):
    import json
    assert run(repo, "comment_budget.py", "--rebaseline").returncode == 0
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
    assert run(repo, "comment_budget.py", "--rebaseline").returncode == 0
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "b")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    budget = repo / "scripts" / "comment-budget.json"
    b = json.loads(budget.read_text())
    b["files"]["src/a.py"] += 1
    budget.write_text(json.dumps(b))
    r = run(repo, "comment_budget.py", "--check")
    assert r.returncode == 1 and "src/a.py" in r.stderr
    write(repo, "a.py", PY + "# why\n")
    assert run(repo, "comment_budget.py", "--allow", "src/a.py", "--reason", "OF quirk").returncode == 0
    assert run(repo, "comment_budget.py", "--check").returncode == 0


def test_jsx_text_slashes_not_counted(repo):
    commit(repo, {"q.tsx": "export const Q = () => <p>// not /* a */ comment</p>;\n"})
    assert run(repo, "comment_budget.py", "--rebaseline").returncode == 0
    import json
    files = json.loads((repo / "scripts" / "comment-budget.json").read_text())["files"]
    assert "src/q.tsx" not in files


def test_growth_passes_without_base_budget_and_fails_cleanly_on_bad_rev(repo, monkeypatch):
    assert run(repo, "comment_budget.py", "--rebaseline").returncode == 0
    r = run(repo, "comment_budget.py", "--check")
    assert r.returncode == 0 and "growth check passes" in r.stdout
    monkeypatch.setenv("COMMENT_BASE", "no-such-rev")
    r = run(repo, "comment_budget.py", "--check")
    assert r.returncode == 1 and "cannot resolve merge base" in r.stderr and "Traceback" not in r.stderr


def test_growth_needs_changed_reason_and_exact_count(repo):
    import json
    write(repo, "a.py", PY + "# why\n")
    assert run(repo, "comment_budget.py", "--rebaseline").returncode == 0
    assert run(repo, "comment_budget.py", "--allow", "src/a.py", "--reason", "OF quirk").returncode == 0
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "b")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    budget = repo / "scripts" / "comment-budget.json"
    base = json.loads(budget.read_text())
    write(repo, "a.py", PY + "# why\n# more\n")
    for files, reason, why in [(base["files"]["src/a.py"] + 2, " of  QUIRK ", "without a new --allow reason"),
                               (base["files"]["src/a.py"] + 5, "other quirk", "current count")]:
        b = json.loads(json.dumps(base))
        b["files"]["src/a.py"], b["allow"]["src/a.py"] = files, reason
        budget.write_text(json.dumps(b))
        r = run(repo, "comment_budget.py", "--check")
        assert r.returncode == 1 and why in r.stderr, r.stderr
    assert run(repo, "comment_budget.py", "--allow", "src/a.py", "--reason", "second quirk").returncode == 0
    assert run(repo, "comment_budget.py", "--check").returncode == 0


def test_growth_accepts_exact_recount_of_unchanged_file_only(repo):
    import json
    assert run(repo, "comment_budget.py", "--rebaseline").returncode == 0
    budget = repo / "scripts" / "comment-budget.json"
    true = json.loads(budget.read_text())
    low = json.loads(json.dumps(true))
    low["files"]["src/a.py"] -= 2
    budget.write_text(json.dumps(low))
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "b")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    budget.write_text(json.dumps(true))
    r = run(repo, "comment_budget.py", "--check")
    assert r.returncode == 0 and "recount src/a.py" in r.stdout, r.stdout + r.stderr
    over = json.loads(json.dumps(true))
    over["files"]["src/a.py"] += 1
    budget.write_text(json.dumps(over))
    r = run(repo, "comment_budget.py", "--check")
    assert r.returncode == 1 and "current count" in r.stderr, r.stderr
    write(repo, "a.py", PY + "# new\n")
    changed = json.loads(json.dumps(true))
    changed["files"]["src/a.py"] += 1
    budget.write_text(json.dumps(changed))
    r = run(repo, "comment_budget.py", "--check")
    assert r.returncode == 1 and "src/a.py" in r.stderr and "without a new --allow reason" in r.stderr, r.stderr
    write(repo, "a.py", PY)
    write(repo, "n.py", "# new\nx = 1\n")
    fresh = json.loads(json.dumps(true))
    fresh["files"]["src/n.py"] = 1
    budget.write_text(json.dumps(fresh))
    r = run(repo, "comment_budget.py", "--check")
    assert r.returncode == 1 and "src/n.py" in r.stderr and "without a new --allow reason" in r.stderr, r.stderr


def test_check_uses_merge_base_and_rejects_growth(repo, monkeypatch):
    import json
    write(repo, "a.py", PY + "# allowance slack\n")
    assert run(repo, "comment_budget.py", "--rebaseline").returncode == 0
    commit(repo, {"a.py": PY})
    git(repo, "switch", "-qc", "comparison")
    commit(repo, {"a.py": PY + "# comparison tip\n"})
    git(repo, "switch", "-q", "-")
    commit(repo, {"a.py": PY + "# extra\n"})
    monkeypatch.setenv("COMMENT_BASE", "comparison")
    r = run(repo, "comment_budget.py", "--check")
    assert r.returncode == 1 and "grew from 6 to 7" in r.stderr, r.stderr

    budget = repo / "scripts" / "comment-budget.json"
    manifest = json.loads(budget.read_text())
    manifest["files"]["src/a.py"] += 1
    budget.write_text(json.dumps(manifest))
    r = run(repo, "comment_budget.py", "--check")
    assert r.returncode == 1 and "without a new --allow reason" in r.stderr, r.stderr

    assert run(repo, "comment_budget.py", "--allow", "src/a.py", "--reason", "OF quirk").returncode == 0
    assert run(repo, "comment_budget.py", "--check").returncode == 0
    monkeypatch.setenv("COMMENT_BASE", "missing")
    r = run(repo, "comment_budget.py", "--check")
    assert r.returncode == 1 and "merge base" in r.stderr, r.stderr


def test_check_counts_untracked_and_skips_ignored(repo):
    (repo / ".gitignore").write_text("__pycache__/\nignored.py\n")
    write(repo, "ignored.py", "# ignored\n")
    assert run(repo, "comment_budget.py", "--rebaseline").returncode == 0
    assert run(repo, "comment_budget.py", "--check").returncode == 0
    write(repo, "new.py", "# new\n")
    r = run(repo, "comment_budget.py", "--check")
    assert r.returncode == 1 and "src/new.py" in r.stderr and "ignored.py" not in r.stderr, r.stderr


def test_budget_modes_agree_with_untracked_doc_reader(repo):
    import json
    commit(repo, {"other.py": OTHER})
    assert run(repo, "comment_budget.py", "--rebaseline").returncode == 0
    commit(repo, {})
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    write(repo, "other.py", OTHER + "# one\n# two\n")
    write(repo, "reader.py", "from other import g\nhelp(g)\n")
    r = run(repo, "comment_budget.py", "--report", "--json")
    assert json.loads(r.stdout)["src/other.py"] == 2
    budget = repo / "scripts" / "comment-budget.json"
    manifest = json.loads(budget.read_text())
    manifest["files"]["src/other.py"] = 3
    manifest["allow"]["src/other.py"] = "OF quirk"
    budget.write_text(json.dumps(manifest))
    r = run(repo, "comment_budget.py", "--check")
    assert r.returncode == 1 and "≠ current count 2; use --allow" in r.stderr, r.stderr
    r = run(repo, "comment_budget.py", "--allow", "src/other.py", "--reason", "OF quirk")
    assert r.returncode == 0 and "budget 2" in r.stdout, r.stderr
    r = run(repo, "comment_budget.py", "--check")
    assert r.returncode == 0, r.stderr


def test_growth_uses_renamed_file_baseline(repo):
    import json
    assert run(repo, "comment_budget.py", "--rebaseline").returncode == 0
    assert run(repo, "comment_budget.py", "--allow", "src/a.py", "--reason", "OF quirk").returncode == 0
    commit(repo, {})
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(repo, "mv", "src/a.py", "src/renamed.py")
    budget = repo / "scripts" / "comment-budget.json"
    manifest = json.loads(budget.read_text())
    for key in ("files", "allow"):
        manifest[key]["src/renamed.py"] = manifest[key].pop("src/a.py")
    budget.write_text(json.dumps(manifest))
    assert run(repo, "comment_budget.py", "--check").returncode == 0
    write(repo, "renamed.py", PY + "# extra\n")
    assert run(repo, "comment_budget.py", "--allow", "src/renamed.py", "--reason", "OF quirk").returncode == 0
    r = run(repo, "comment_budget.py", "--check")
    assert r.returncode == 1 and "without a new --allow reason" in r.stderr, r.stderr


def test_rebaseline_needs_force_to_replace_manifest(repo):
    assert run(repo, "comment_budget.py", "--rebaseline").returncode == 0
    write(repo, "a.py", PY + "# extra\n")
    budget = repo / "scripts" / "comment-budget.json"
    before = budget.read_bytes()
    r = run(repo, "comment_budget.py", "--rebaseline")
    assert r.returncode == 1 and "--force" in r.stderr, r.stderr
    assert budget.read_bytes() == before
    assert run(repo, "comment_budget.py", "--rebaseline", "--force").returncode == 0
    assert budget.read_bytes() != before
