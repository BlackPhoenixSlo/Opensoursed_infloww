"""Audit credential scrub — no key value left in `actions.payload_json`

W30 F1: the audit middleware snapshot kept every value whose NAME did not look
secret, so Setup → Keys writes stored the keys themselves: PUT /admin/my-llm-keys
`{typesafe: "<key>"}`, the founder's PUT /admin/users/{id}/llm-keys (keys nested in
`providers`), PUT /admin/secrets (HELP_ASSISTANT_*_KEY), POST /admin/proxies/bulk (pasted
host:port:user:pass lines), POST /admin/session/fansly (token, check_key), and POST
/admin/session/bootstrap's pasted curl (OF cookies; a body over 4 KB was stored as raw
text). /admin/audit returns the column. Data only: on those rows a key-write payload
keeps each name with "set" / "cleared" (a `***` stays), a bootstrap payload its
`curl` / cookie / token / password / secret / api_key values as "***"; an unparseable
payload (cut at 4 KB) becomes NULL. Every other row is untouched.

Boxes upgrade through db.engine's init_db, which runs `scrub` below once
(`data_migrations` marker `20261122_audit_credential_scrub`); this file runs the same
on a manual `alembic upgrade head`. Idempotent. Downgrade: no-op (values are gone).

Revision ID: 0134_audit_credential_scrub
Revises: 0133_tracking_clicks_unclassified
Create Date: 2026-11-22
"""
from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0134_audit_credential_scrub"
down_revision: str | Sequence[str] | None = "0133_tracking_clicks_unclassified"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# audit_log's rule as of this revision (copied: a migration is frozen).
# Keys-only routes (audit_log.credential_write): every value becomes "set"/"cleared".
# The bulk proxy paste carried host:port:user:pass lines; the Fansly session its check_key.
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
    """Rewrite the credential rows' payloads (`conn`: a sync connection in a
    transaction). Returns rows changed."""
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
    pass
