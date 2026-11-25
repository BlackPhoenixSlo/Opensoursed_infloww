from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0011_phase_c_automation_employee"
down_revision: str | Sequence[str] | None = "0010_b5_unsend_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# idempotent: display_name has no unique constraint; runtime looks the row up by display_name, never id
def upgrade() -> None:
    op.execute(sa.text(
        "INSERT OR IGNORE INTO employees "
        "(display_name, color, is_active, created_at) "
        "VALUES ('Automation', '#808080', 0, CURRENT_TIMESTAMP)"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "DELETE FROM employees "
        "WHERE display_name = 'Automation' AND is_active = 0"
    ))
