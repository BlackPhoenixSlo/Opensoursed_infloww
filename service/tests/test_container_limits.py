#!/usr/bin/env python3
"""
`container_limits` — what the container's cgroup says it is limited to.
Plain-assert, no pytest (repo convention).

Why this suite exists. This module has exactly one wrong answer available to it,
and it is the plausible one: reporting **"no limit"** for a cgroup file it merely
failed to open. "Unlimited" and "could not tell" send an operator to opposite
conclusions — one says there is headroom to spend, the other says go and look —
and the panel renders them differently only because every reader returns
`(value, readable)` instead of a bare `None`.

The first version of this code got that right for CPU and wrong for memory: a
single `readable` flag was derived from the CPU read alone, so a container under
`mem_limit: 2g` whose `memory.max` was unparseable rendered "memory: no limit"
next to a correctly-shown CPU ceiling. That is the worse half to get wrong —
`docker-compose.yml` calls `mem_limit` "the one that BITES: exceeding it is an
OOM-kill, not a slowdown". `case_unreadable_memory_is_not_unlimited` is that bug,
pinned.

Cases:
  case_cgroup_v2_cpu_is_read
  case_cgroup_v1_cpu_is_read
  case_unreadable_cpu_is_not_unlimited
  case_unreadable_memory_is_not_unlimited
  case_v1_memory_sentinel_is_unlimited_not_nine_exabytes
  case_never_raises_on_any_garbage
  case_container_id_is_stripped_and_truncated
"""
import importlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import _harness  # noqa: E402


def _fresh(cgroup: Path, hostname: Path | None = None):
    """A container_limits pointed at a fake cgroup tree. Re-imported per case so
    one case's `_CGROUP` can never leak into the next."""
    sys.modules.pop("container_limits", None)
    mod = importlib.import_module("container_limits")
    mod._CGROUP = cgroup
    if hostname is not None:
        mod._HOSTNAME = hostname
    return mod


def case_cgroup_v2_cpu_is_read():
    with tempfile.TemporaryDirectory() as d:
        cg = Path(d)
        (cg / "cpu.max").write_text("300000 100000", "utf-8")
        assert _fresh(cg)._cpus() == (3.0, True)

        (cg / "cpu.max").write_text("max 100000", "utf-8")
        assert _fresh(cg)._cpus() == (None, True), "'max' IS unlimited, readably"

        (cg / "cpu.max").write_text("120000 100000", "utf-8")
        assert _fresh(cg)._cpus() == (1.2, True), "the deployed prod value"


def case_cgroup_v1_cpu_is_read():
    """The v1 branch is unreachable on this laptop and on the prod box, so
    nothing else would ever execute it — and a fleet can move hosts."""
    with tempfile.TemporaryDirectory() as d:
        cg = Path(d)
        (cg / "cpu").mkdir()
        (cg / "cpu" / "cpu.cfs_quota_us").write_text("150000", "utf-8")
        (cg / "cpu" / "cpu.cfs_period_us").write_text("100000", "utf-8")
        assert _fresh(cg)._cpus() == (1.5, True)

        (cg / "cpu" / "cpu.cfs_quota_us").write_text("-1", "utf-8")
        assert _fresh(cg)._cpus() == (None, True), "-1 is v1's 'unlimited'"

        (cg / "cpu" / "cpu.cfs_period_us").write_text("0", "utf-8")
        (cg / "cpu" / "cpu.cfs_quota_us").write_text("100000", "utf-8")
        assert _fresh(cg)._cpus() == (None, False), "a zero period is not a divisor"


def case_unreadable_cpu_is_not_unlimited():
    with tempfile.TemporaryDirectory() as d:
        missing = Path(d) / "nothing-here"
        assert _fresh(missing)._cpus() == (None, False), (
            "nothing was read, so the honest answer is 'unknown' — 'no limit' "
            "is the one wrong answer available"
        )
        cg = Path(d)
        for junk in ("banana", "", "1 2 3", "x 100000"):
            (cg / "cpu.max").write_text(junk, "utf-8")
            assert _fresh(cg)._cpus() == (None, False), junk


def case_unreadable_memory_is_not_unlimited():
    """The bug this suite exists for: memory must carry its OWN readable flag.
    A readable cpu.max beside an unparseable memory.max must not borrow the
    former's confidence."""
    with tempfile.TemporaryDirectory() as d:
        cg = Path(d)
        (cg / "cpu.max").write_text("120000 100000", "utf-8")
        for junk in ("banana", "", "0", "-1"):
            (cg / "memory.max").write_text(junk, "utf-8")
            limits = _fresh(cg).describe()
            assert limits["cpus"] == 1.2 and limits["cpus_readable"] is True, limits
            assert limits["mem_bytes"] is None, limits
            assert limits["mem_readable"] is False, (
                f"memory.max={junk!r} is unreadable, and rendering it as "
                f"'no limit' is an OOM-kill an operator was told not to expect"
            )

        # THE DOMINANT REAL-WORLD PATH, and it had zero coverage: the file is
        # simply ABSENT. Review regressed `if raw is None: return None, False`
        # to `return None, True` and this suite stayed green — the same species
        # of defanged assertion this module exists to prevent. The CPU reader's
        # mirror branch was covered; memory's was not, on the reader the module
        # docstring calls out as mattering most.
        (cg / "memory.max").unlink()
        limits = _fresh(cg).describe()
        assert limits["mem_bytes"] is None, limits
        assert limits["mem_readable"] is False, (
            "an ABSENT memory.max is 'could not tell', not 'no limit'"
        )
        # A directory where the file belongs is the other unreadable shape.
        (cg / "memory.max").mkdir()
        assert _fresh(cg)._mem() == (None, False), _fresh(cg)._mem()
        (cg / "memory.max").rmdir()

        (cg / "memory.max").write_text("max", "utf-8")
        limits = _fresh(cg).describe()
        assert (limits["mem_bytes"], limits["mem_readable"]) == (None, True), limits

        (cg / "memory.max").write_text(str(2 * 1024**3), "utf-8")
        limits = _fresh(cg).describe()
        assert (limits["mem_bytes"], limits["mem_readable"]) == (2 * 1024**3, True), limits


def case_v1_memory_sentinel_is_unlimited_not_nine_exabytes():
    with tempfile.TemporaryDirectory() as d:
        cg = Path(d)
        (cg / "memory.max").write_text(str((1 << 63) - 4096), "utf-8")
        assert _fresh(cg)._mem() == (None, True), (
            "cgroup v1 spells 'unlimited' as a sentinel near 2**63 — reporting "
            "it literally claims a ~9 exabyte ceiling"
        )


def case_never_raises_on_any_garbage():
    """It feeds a page. A box whose cgroup files are missing, empty, binary or
    a directory must render 'unknown', not 500 the panel that shows every other
    ceiling. Asserts the VALUES, not just that keys exist — key presence alone
    would pass if the parser returned 999.0 for "banana"."""
    with tempfile.TemporaryDirectory() as d:
        cg = Path(d)
        # Split per reader, because the two files have different grammars: "1"
        # is nonsense for cpu.max (which needs "quota period") and a perfectly
        # legal — if absurd — one-byte ceiling for memory.max. Asserting one
        # junk list against both would demand the memory reader THROW AWAY a
        # number it can read, which is the opposite of this module's job.
        cpu_junk = ("", "   ", "banana", "1", "1 2 3", "-1 0", "0 0", "��")
        mem_junk = ("", "   ", "banana", "1 2 3", "-1", "0", "��")
        for junk in cpu_junk:
            (cg / "cpu.max").write_text(junk, "utf-8")
            limits = _fresh(cg).describe()               # must not raise
            assert limits["cpus"] is None, (junk, limits)
            assert limits["cpus_readable"] is False, (junk, limits)
        for junk in mem_junk:
            (cg / "memory.max").write_text(junk, "utf-8")
            limits = _fresh(cg).describe()               # must not raise
            assert limits["mem_bytes"] is None, (junk, limits)
            assert limits["mem_readable"] is False, (junk, limits)

        # A directory where a file belongs raises IsADirectoryError, an OSError.
        (cg / "cpu.max").unlink()
        (cg / "cpu.max").mkdir()
        assert _fresh(cg).describe()["cpus_readable"] is False


def case_container_id_is_stripped_and_truncated():
    """This string is pasted onto a root shell's command line as
    `docker update --cpus=N <id>`. A trailing newline or a full 64-char id
    makes that command wrong."""
    with tempfile.TemporaryDirectory() as d:
        cg = Path(d)
        (cg / "cpu.max").write_text("max 100000", "utf-8")
        host = Path(d) / "hostname"
        host.write_text("2d71b4e59aa9\n", "utf-8")
        assert _fresh(cg, host).describe()["container_id"] == "2d71b4e59aa9"

        host.write_text("a" * 64 + "\n", "utf-8")
        assert _fresh(cg, host).describe()["container_id"] == "a" * 12

        host.unlink()
        assert _fresh(cg, host).describe()["container_id"] == "", (
            "no hostname must be an empty string, not None — the panel builds "
            "a command out of it"
        )


_harness.run(
    case_cgroup_v2_cpu_is_read,
    case_cgroup_v1_cpu_is_read,
    case_unreadable_cpu_is_not_unlimited,
    case_unreadable_memory_is_not_unlimited,
    case_v1_memory_sentinel_is_unlimited_not_nine_exabytes,
    case_never_raises_on_any_garbage,
    case_container_id_is_stripped_and_truncated,
)
