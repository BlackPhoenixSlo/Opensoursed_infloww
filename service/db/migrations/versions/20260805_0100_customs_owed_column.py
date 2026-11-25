from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0059_customs_owed_column"
down_revision: str | Sequence[str] | None = "0058_ghost_cycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# no backfill on purpose: no fan carries the old nickname suffix, and the one that ends in "Custom" is an operator note, not a debt
def upgrade() -> None:
    op.add_column("fans", sa.Column("customs_owed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("fans", "customs_owed_at")
