"""mass_runs.crawl_outcome — the Audience crawl's outcome per run (fetch-diet P2b)

One nullable string: the crawl stamps its `audience_crawl_end` outcome on the run, so the next send of
the Creator can skip a crawl after an `incomplete` / `deadline` verdict and the boot re-crawl leaves
finished crawls alone. NULL on every older row (no crawl verdict). The relay DB never runs alembic;
its additive-column catch-up (`db.engine.init_db`) adds this column too. Self-contained (no app
import), inspector-guarded + idempotent.

Revision ID: 0112_mass_run_crawl_outcome
Revises: 0111_tx_scan_full_walk_failures
Create Date: 2026-11-11
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0112_mass_run_crawl_outcome"
down_revision: str | Sequence[str] | None = "0111_tx_scan_full_walk_failures"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE, _COL = "mass_runs", "crawl_outcome"


def _live() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    if _COL not in _live():
        op.add_column(_TABLE, sa.Column(_COL, sa.String(), nullable=True))


def downgrade() -> None:
    if _COL in _live():
        op.drop_column(_TABLE, _COL)
