from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0006_phase_a_grok_daily_cost_pk"
down_revision: str | Sequence[str] | None = "0005_phase_a_fan_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text(
        """
        CREATE TABLE grok_daily_cost_new (
            day VARCHAR NOT NULL,
            account_id VARCHAR,
            cost_cents INTEGER NOT NULL,
            call_count INTEGER NOT NULL,
            is_capped BOOLEAN NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            CONSTRAINT pk_grok_daily_cost PRIMARY KEY (day, account_id),
            CONSTRAINT fk_grok_daily_cost_account_id_accounts
                FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE
        )
        """
    ))
    op.execute(sa.text(
        """
        INSERT INTO grok_daily_cost_new
            (day, account_id, cost_cents, call_count, is_capped, updated_at)
        SELECT day, NULL, cost_cents, call_count, is_capped, updated_at
          FROM grok_daily_cost
        """
    ))
    op.execute(sa.text("DROP TABLE grok_daily_cost"))
    op.execute(sa.text("ALTER TABLE grok_daily_cost_new RENAME TO grok_daily_cost"))


def downgrade() -> None:
    # Irreversible: per-account split is lost.
    op.execute(sa.text(
        """
        CREATE TABLE grok_daily_cost_old (
            day VARCHAR NOT NULL,
            cost_cents INTEGER NOT NULL,
            call_count INTEGER NOT NULL,
            is_capped BOOLEAN NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            CONSTRAINT pk_grok_daily_cost PRIMARY KEY (day)
        )
        """
    ))
    op.execute(sa.text(
        """
        INSERT INTO grok_daily_cost_old
            (day, cost_cents, call_count, is_capped, updated_at)
        SELECT day,
               SUM(cost_cents),
               SUM(call_count),
               MAX(is_capped),
               MAX(updated_at)
          FROM grok_daily_cost
         GROUP BY day
        """
    ))
    op.execute(sa.text("DROP TABLE grok_daily_cost"))
    op.execute(sa.text("ALTER TABLE grok_daily_cost_old RENAME TO grok_daily_cost"))
