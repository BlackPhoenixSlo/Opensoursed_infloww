#!/usr/bin/env python3
import importlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import _harness  # noqa: E402


def _fresh(cgroup: Path, hostname: Path | None = None):
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

        # the dominant real-world path: the file is simply absent
        (cg / "memory.max").unlink()
        limits = _fresh(cg).describe()
        assert limits["mem_bytes"] is None, limits
        assert limits["mem_readable"] is False, (
            "an ABSENT memory.max is 'could not tell', not 'no limit'"
        )
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
    with tempfile.TemporaryDirectory() as d:
        cg = Path(d)
        # split per reader: "1" is nonsense for cpu.max but a legal one-byte memory.max
        cpu_junk = ("", "   ", "banana", "1", "1 2 3", "-1 0", "0 0", "��")
        mem_junk = ("", "   ", "banana", "1 2 3", "-1", "0", "��")
        for junk in cpu_junk:
            (cg / "cpu.max").write_text(junk, "utf-8")
            limits = _fresh(cg).describe()
            assert limits["cpus"] is None, (junk, limits)
            assert limits["cpus_readable"] is False, (junk, limits)
        for junk in mem_junk:
            (cg / "memory.max").write_text(junk, "utf-8")
            limits = _fresh(cg).describe()
            assert limits["mem_bytes"] is None, (junk, limits)
            assert limits["mem_readable"] is False, (junk, limits)

        (cg / "cpu.max").unlink()
        (cg / "cpu.max").mkdir()
        assert _fresh(cg).describe()["cpus_readable"] is False


# the id is pasted onto a root shell's `docker update --cpus=N <id>`: a trailing newline or a full 64-char id breaks it
def case_container_id_is_stripped_and_truncated():
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
