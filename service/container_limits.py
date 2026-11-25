# Read only by design: /sys/fs/cgroup is ro, and a docker.sock mount was rejected (root on the host behind an unauthenticated panel).
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_CGROUP = Path("/sys/fs/cgroup")
_HOSTNAME = Path("/etc/hostname")

# cgroup v1 spells "no limit" as a sentinel near 2**63; reading it literally would claim a ~9 EB limit.
_V1_UNLIMITED = 1 << 62


def _read_first(*paths: Path) -> str | None:
    for candidate in paths:
        try:
            return candidate.read_text("utf-8").strip()
        except (OSError, ValueError):
            # ValueError covers UnicodeDecodeError, which is not an OSError and would otherwise 500 the panel.
            continue
    return None


def _cpus() -> tuple[float | None, bool]:
    raw = _read_first(_CGROUP / "cpu.max")
    # None+readable = unlimited, not readable = could not tell: never conflate (unreadable memory.max hides an OOM-kill ceiling).
    if raw is not None:
        parts = raw.split()
        if parts and parts[0] == "max":
            return None, True
        if len(parts) == 2:
            try:
                quota, period = int(parts[0]), int(parts[1])
            except ValueError:
                return None, False
            if quota > 0 and period > 0:
                return round(quota / period, 3), True
        return None, False
    quota_raw = _read_first(_CGROUP / "cpu" / "cpu.cfs_quota_us")
    period_raw = _read_first(_CGROUP / "cpu" / "cpu.cfs_period_us")
    if quota_raw is None or period_raw is None:
        return None, False
    try:
        quota, period = int(quota_raw), int(period_raw)
    except ValueError:
        return None, False
    if quota <= 0:
        return None, True
    if period <= 0:
        return None, False
    return round(quota / period, 3), True


def _mem() -> tuple[int | None, bool]:
    raw = _read_first(_CGROUP / "memory.max",
                      _CGROUP / "memory" / "memory.limit_in_bytes")
    if raw is None:
        return None, False
    if raw == "max":
        return None, True
    try:
        value = int(raw)
    except ValueError:
        return None, False
    if value <= 0:
        return None, False
    return (None, True) if value >= _V1_UNLIMITED else (value, True)


def describe() -> dict[str, Any]:
    cpus, cpus_readable = _cpus()
    mem_bytes, mem_readable = _mem()
    return {
        "cpus": cpus,
        "cpus_readable": cpus_readable,
        "mem_bytes": mem_bytes,
        "mem_readable": mem_readable,
        "host_cpus": os.cpu_count(),
        # Container id = hostname, stripped and cut to 12: it lands on a root shell's command line; only meaningful when a cgroup was readable (bare host: machine name).
        "container_id": (_read_first(_HOSTNAME) or "")[:12],
    }
