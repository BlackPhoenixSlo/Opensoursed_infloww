from __future__ import annotations

from datetime import datetime
from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0078_shift_scope_versions"
down_revision: str | Sequence[str] | None = "0077_tx_credit_rollup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABS = "('sales', 'time-tracking')"
_TS = "%Y-%m-%d %H:%M:%S.%f"
_IX = "ix_settings_versions_user_tab"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "cancelled_dates" not in {c["name"] for c in inspector.get_columns("shifts")}:
        op.add_column("shifts", sa.Column("cancelled_dates", sa.Text(), nullable=True))
    if "settings_versions" not in inspector.get_table_names():
        op.create_table(
            "settings_versions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("tab", sa.String(), nullable=False),
            sa.Column("effective_from", sa.DateTime(), nullable=False),
            sa.Column("config_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index(_IX, "settings_versions", ["user_id", "tab", "effective_from"])
    bind.execute(sa.text(
        "INSERT INTO settings_versions (user_id, tab, effective_from, config_json, created_at) "
        "SELECT u.user_id, u.tab, CASE WHEN EXISTS (SELECT 1 FROM settings_versions v "
        "  WHERE v.user_id = u.user_id AND v.tab = u.tab) THEN u.updated_at ELSE :epoch END, "
        f"u.config_json, u.updated_at FROM user_settings u WHERE u.tab IN {_TABS} ORDER BY u.user_id, u.tab"),
        {"epoch": datetime(1970, 1, 1).strftime(_TS)})
    bind.execute(sa.text(f"DELETE FROM user_settings WHERE tab IN {_TABS}"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # Lossy downgrade: only the version in effect now is kept; other versions and every "This shift" exception are lost.
    if "settings_versions" in inspector.get_table_names():
        bind.execute(sa.text(
            "INSERT OR REPLACE INTO user_settings (user_id, tab, config_json, updated_at) "
            "SELECT v.user_id, v.tab, v.config_json, v.created_at FROM settings_versions v "
            "WHERE v.id = (SELECT w.id FROM settings_versions w "
            "              WHERE w.user_id = v.user_id AND w.tab = v.tab AND w.effective_from <= :now "
            "              ORDER BY w.effective_from DESC, w.id DESC LIMIT 1)"),
            {"now": datetime.utcnow().strftime(_TS)})
        op.drop_index(_IX, table_name="settings_versions")
        op.drop_table("settings_versions")
    if "cancelled_dates" in {c["name"] for c in inspector.get_columns("shifts")}:
        op.drop_column("shifts", "cancelled_dates")
