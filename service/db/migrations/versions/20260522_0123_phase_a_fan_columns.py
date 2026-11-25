from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0005_phase_a_fan_columns"
down_revision: str | Sequence[str] | None = "0004_perf_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("chats", schema=None) as batch_op:
        batch_op.add_column(sa.Column("preview_updated_at", sa.DateTime(), nullable=True))

    with op.batch_alter_table("fans", schema=None) as batch_op:
        batch_op.add_column(sa.Column("occupation", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("employer", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("relationship_status", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("partner_name", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("has_kids", sa.Boolean(), nullable=True))
        batch_op.add_column(
            # server_default required: the batch rebuild copies existing rows, and NOT NULL would otherwise get NULL and abort the migration.
            sa.Column("family_names", sa.Text(), nullable=False, server_default="{}")
        )
        batch_op.add_column(
            sa.Column("pets", sa.Text(), nullable=False, server_default="[]")
        )
        batch_op.add_column(sa.Column("mood_at_last_message", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("sentiment_trend", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("relationship_stage", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("communication_style", sa.Text(), nullable=False, server_default="{}")
        )
        batch_op.add_column(sa.Column("automation_paused_until", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("persona_age_claimed", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("persona_location_claimed", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("persona_job_claimed", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("profile_last_synced_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("grok_facts_updated_at", sa.DateTime(), nullable=True))
        batch_op.create_index(
            "ix_fans_paused_until",
            ["account_id", "automation_paused_until"],
            unique=False,
            sqlite_where=sa.text("automation_paused_until IS NOT NULL"),
            postgresql_where=sa.text("automation_paused_until IS NOT NULL"),
        )
        batch_op.create_index(
            "ix_fans_relationship_stage",
            ["account_id", "relationship_stage"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("fans", schema=None) as batch_op:
        batch_op.drop_index("ix_fans_relationship_stage")
        batch_op.drop_index(
            "ix_fans_paused_until",
            sqlite_where=sa.text("automation_paused_until IS NOT NULL"),
            postgresql_where=sa.text("automation_paused_until IS NOT NULL"),
        )
        batch_op.drop_column("grok_facts_updated_at")
        batch_op.drop_column("profile_last_synced_at")
        batch_op.drop_column("persona_job_claimed")
        batch_op.drop_column("persona_location_claimed")
        batch_op.drop_column("persona_age_claimed")
        batch_op.drop_column("automation_paused_until")
        batch_op.drop_column("communication_style")
        batch_op.drop_column("relationship_stage")
        batch_op.drop_column("sentiment_trend")
        batch_op.drop_column("mood_at_last_message")
        batch_op.drop_column("pets")
        batch_op.drop_column("family_names")
        batch_op.drop_column("has_kids")
        batch_op.drop_column("partner_name")
        batch_op.drop_column("relationship_status")
        batch_op.drop_column("employer")
        batch_op.drop_column("occupation")

    with op.batch_alter_table("chats", schema=None) as batch_op:
        batch_op.drop_column("preview_updated_at")
