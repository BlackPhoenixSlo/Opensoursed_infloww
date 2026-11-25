from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0056_quota_audit"
down_revision: str | Sequence[str] | None = "0055_translation_cache"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PK = ["account_id", "fan_id", "day", "reason", "enforced"]


def _create(name: str = "quota_audit") -> None:
    op.create_table(
        name,
        sa.Column("account_id", sa.String, primary_key=True, nullable=False),
        sa.Column("fan_id", sa.BigInteger, primary_key=True, nullable=False),
        sa.Column("day", sa.String, primary_key=True, nullable=False),
        sa.Column("reason", sa.String, primary_key=True, nullable=False),
        sa.Column("enforced", sa.Boolean, primary_key=True, nullable=False,
                  server_default=sa.text("0")),
        sa.Column("n", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("quota", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("used", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("runway_left", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("wait_h", sa.Float),
        sa.Column("dry_h", sa.Float),
        sa.Column("updated_at", sa.DateTime, nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "quota_audit" not in inspector.get_table_names():
        _create()
        op.create_index("ix_quota_audit_day", "quota_audit",
                        ["account_id", "day", "reason"])
        return

    pk = set(sa.inspect(bind).get_pk_constraint("quota_audit").get(
        "constrained_columns") or [])
    if pk == set(_PK):
        existing = {i["name"] for i in sa.inspect(bind).get_indexes("quota_audit")}
        if "ix_quota_audit_day" not in existing:
            op.create_index("ix_quota_audit_day", "quota_audit",
                            ["account_id", "day", "reason"])
        return

    # SQLite cannot ALTER a PRIMARY KEY: rebuild, re-aggregating by the new key (n summed; shadow vs enforced already conflated by the old key, cannot be un-mixed).
    op.rename_table("quota_audit", "quota_audit_old")
    _create()
    op.execute(
        """
        INSERT INTO quota_audit
            (account_id, fan_id, day, reason, enforced, n, quota, used,
             runway_left, wait_h, dry_h, updated_at)
        SELECT account_id, fan_id, day, reason,
               COALESCE(enforced, 0),
               SUM(COALESCE(n, 0)),
               MAX(COALESCE(quota, 0)), MAX(COALESCE(used, 0)),
               MAX(COALESCE(runway_left, 0)),
               MAX(wait_h), MAX(dry_h), MAX(updated_at)
          FROM quota_audit_old
         GROUP BY account_id, fan_id, day, reason, COALESCE(enforced, 0)
        """
    )
    op.drop_table("quota_audit_old")
    op.create_index("ix_quota_audit_day", "quota_audit",
                    ["account_id", "day", "reason"])


def downgrade() -> None:
    bind = op.get_bind()
    if "quota_audit" in sa.inspect(bind).get_table_names():
        op.drop_table("quota_audit")
