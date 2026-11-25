from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0026_llm_provider"
down_revision: str | Sequence[str] | None = "0025_render_media_and_lease"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    gc_cols = {c["name"] for c in inspector.get_columns("grok_calls")}
    if "provider" not in gc_cols:
        op.add_column(
            "grok_calls",
            sa.Column("provider", sa.String, nullable=False, server_default=sa.text("'grok'")),
        )
    if "cache_hit_tokens" not in gc_cols:
        op.add_column("grok_calls", sa.Column("cache_hit_tokens", sa.Integer, nullable=True))
    if "status" not in gc_cols:
        op.add_column(
            "grok_calls",
            sa.Column("status", sa.String, nullable=False, server_default=sa.text("'pending'")),
        )
        op.execute(sa.text(
            "UPDATE grok_calls SET status = CASE "
            "WHEN error_text IS NOT NULL THEN 'error' "
            "WHEN response_json IS NOT NULL THEN 'done' "
            "ELSE 'pending' END"
        ))

    op.execute(sa.text(
        """
        CREATE TABLE grok_daily_cost_new (
            day VARCHAR NOT NULL,
            account_id VARCHAR,
            provider VARCHAR NOT NULL DEFAULT 'grok',
            cost_cents INTEGER NOT NULL,
            call_count INTEGER NOT NULL,
            is_capped BOOLEAN NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            CONSTRAINT pk_grok_daily_cost PRIMARY KEY (day, account_id, provider),
            CONSTRAINT fk_grok_daily_cost_account_id_accounts
                FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE
        )
        """
    ))
    op.execute(sa.text(
        """
        INSERT INTO grok_daily_cost_new
            (day, account_id, provider, cost_cents, call_count, is_capped, updated_at)
        SELECT day, account_id, 'grok', cost_cents, call_count, is_capped, updated_at
          FROM grok_daily_cost
        """
    ))
    op.execute(sa.text("DROP TABLE grok_daily_cost"))
    op.execute(sa.text("ALTER TABLE grok_daily_cost_new RENAME TO grok_daily_cost"))

    if "model_pricing" not in existing_tables:
        op.create_table(
            "model_pricing",
            sa.Column("model", sa.String, nullable=False),
            sa.Column("provider", sa.String, nullable=False),
            sa.Column(
                "input_per_1k_cents", sa.Numeric(12, 6),
                nullable=False, server_default=sa.text("0"),
            ),
            sa.Column(
                "output_per_1k_cents", sa.Numeric(12, 6),
                nullable=False, server_default=sa.text("0"),
            ),
            sa.Column(
                "updated_at", sa.DateTime,
                nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.PrimaryKeyConstraint("model", name="pk_model_pricing"),
        )

    ai_cols = {c["name"] for c in inspector.get_columns("account_ai_config")}
    if "model" not in ai_cols:
        op.add_column("account_ai_config", sa.Column("model", sa.String, nullable=True))
    if "model_by_purpose" not in ai_cols:
        op.add_column("account_ai_config", sa.Column("model_by_purpose", sa.Text, nullable=True))


def downgrade() -> None:
    # Irreversible: per-provider spend split is lost.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    ai_cols = {c["name"] for c in inspector.get_columns("account_ai_config")}
    if "model_by_purpose" in ai_cols:
        op.drop_column("account_ai_config", "model_by_purpose")
    if "model" in ai_cols:
        op.drop_column("account_ai_config", "model")

    if "model_pricing" in existing_tables:
        op.drop_table("model_pricing")

    op.execute(sa.text(
        """
        CREATE TABLE grok_daily_cost_old (
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
        INSERT INTO grok_daily_cost_old
            (day, account_id, cost_cents, call_count, is_capped, updated_at)
        SELECT day, account_id,
               SUM(cost_cents), SUM(call_count), MAX(is_capped), MAX(updated_at)
          FROM grok_daily_cost
         GROUP BY day, account_id
        """
    ))
    op.execute(sa.text("DROP TABLE grok_daily_cost"))
    op.execute(sa.text("ALTER TABLE grok_daily_cost_old RENAME TO grok_daily_cost"))

    gc_cols = {c["name"] for c in inspector.get_columns("grok_calls")}
    if "status" in gc_cols:
        op.drop_column("grok_calls", "status")
    if "cache_hit_tokens" in gc_cols:
        op.drop_column("grok_calls", "cache_hit_tokens")
    if "provider" in gc_cols:
        op.drop_column("grok_calls", "provider")
