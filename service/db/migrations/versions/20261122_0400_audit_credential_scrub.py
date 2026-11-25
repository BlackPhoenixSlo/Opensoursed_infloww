from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0134_audit_credential_scrub"
down_revision: str | Sequence[str] | None = "0133_tracking_clicks_unclassified"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copy of audit_log's rule as of this revision.
KEY_WRITES = ("PUT /admin/my-llm-keys", "PUT /admin/secrets",
              "POST /admin/proxies/bulk", "POST /admin/session/fansly")
KEY_WRITE_LIKE = "PUT /admin/users/%/llm-keys"
BOOTSTRAP = "POST /admin/session/bootstrap"
SECRET_PARTS = ("password", "token", "secret", "api_key", "cookie", "curl")
DONE = ("set", "cleared", "***")


def _redact(v, keys_only: bool):
    if isinstance(v, dict):
        return {k: "***" if any(s in str(k).lower() for s in SECRET_PARTS) else _redact(x, keys_only)
                for k, x in v.items()}
    if isinstance(v, list):
        return [_redact(x, keys_only) for x in v]
    if keys_only and v not in DONE:
        return "cleared" if v in ("", None) else "set"
    return v


def scrub(conn) -> int:
    if "actions" not in set(sa.inspect(conn).get_table_names()):
        return 0
    rows = conn.execute(sa.text(
        "SELECT id, action, payload_json FROM actions WHERE payload_json IS NOT NULL "
        "AND (action IN :actions OR action LIKE :like)").bindparams(
            sa.bindparam("actions", expanding=True)),
        {"actions": [*KEY_WRITES, BOOTSTRAP], "like": KEY_WRITE_LIKE}).all()
    changed = 0
    for row_id, action, raw in rows:
        try:
            new = json.dumps(_redact(json.loads(raw), action != BOOTSTRAP))
        except ValueError:
            new = None
        if new != raw:
            conn.execute(sa.text("UPDATE actions SET payload_json = :p WHERE id = :id"),
                         {"p": new, "id": row_id})
            changed += 1
    return changed


def upgrade() -> None:
    scrub(op.get_bind())


def downgrade() -> None:
    # No-op: scrubbed values are gone.
    pass
