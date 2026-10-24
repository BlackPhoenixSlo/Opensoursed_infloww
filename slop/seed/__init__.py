"""Composable seeders. One file per entity; each takes the World, a size and a
named RNG stream, writes rows, and returns what later seeders/actors need.

Bulk rows go straight into the run's temp SQLite (same as scripts/demo-shots/seed.py,
fast enough for 50k fans); anything the relay validates goes through its API.
Determinism: World.rng(name) is seeded from (--seed, name), so adding a new
seeder never shifts the numbers an existing one draws.
"""
from __future__ import annotations

import hashlib
import random
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Sizes per --scale. Seeders read only the keys they own; add keys as you need them.
SCALES: dict[str, dict[str, float]] = {
    "small":  {"creators": 3,  "fans_per_creator": 50,   "thread_frac": 0.6, "history_msgs": 4,
               "big_fans_per_creator": 2_000},
    "medium": {"creators": 10, "fans_per_creator": 500,  "thread_frac": 0.5, "history_msgs": 6,
               "big_fans_per_creator": 10_000},
    "huge":   {"creators": 10, "fans_per_creator": 5000, "thread_frac": 0.4, "history_msgs": 6,
               "big_fans_per_creator": 50_000},
}


@dataclass
class World:
    db: Path
    sessions: Path
    seed: int
    scale: str
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0))
    user_id: str | None = None        # the Agency's users.id (seed/agency.py)
    owner: object | None = None       # lib.client.Http signed in as the owner
    data: dict = field(default_factory=dict)  # seeder outputs: creators, fans, threads, ...

    @property
    def size(self) -> dict[str, float]:
        return SCALES[self.scale]

    def rng(self, name: str) -> random.Random:
        h = hashlib.sha256(f"{self.seed}:{name}".encode()).hexdigest()
        return random.Random(int(h[:16], 16))

    def sql(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db, timeout=30)
        con.execute("PRAGMA foreign_keys=ON")
        return con


def ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")
