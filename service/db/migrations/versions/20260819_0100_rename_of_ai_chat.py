from collections.abc import Sequence

from alembic import op

revision: str = "0062_rename_of_ai_chat"
down_revision: str | Sequence[str] | None = "0061_rhythm_stepout"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = "of_ai_chat"
_NEW = "welcome_chatter_for_info"

_TOKEN_COLS = (
    ("automation_rules", "kind"),
    ("automation_rules", "name"),
    ("scheduled_jobs", "kind"),
    ("automation_runs", "kind"),
    ("messages", "automation_kind"),
)

# token is only ever a (possibly prefixed) KEY in these, so plain replace is safe
_JSON_COLS = (
    ("account_ai_config", "model_by_purpose"),
    ("account_ai_config", "style_config_json"),
)

# also holds free-text values: quoted-key replace only, never a blanket token replace
_SELL_ON_ASK_OLD = '"of_ai_chat_sell_on_ask"'
_SELL_ON_ASK_NEW = '"welcome_chatter_for_info_sell_on_ask"'


def upgrade() -> None:
    # messages/grok_calls are big: full scans, take the deploy backup first.
    # After prod has run this, delete automation_registry.LEGACY_KINDS["of_ai_chat"].
    for table, col in _TOKEN_COLS:
        op.execute(
            f"UPDATE {table} SET {col} = '{_NEW}' WHERE {col} = '{_OLD}'"
        )
    # purpose also has prefixed variants (of_ai_chat_reply): rewrite prefix, keep suffix
    op.execute(
        f"UPDATE grok_calls SET purpose = '{_NEW}' || substr(purpose, {len(_OLD) + 1}) "
        f"WHERE purpose LIKE '{_OLD}%'"
    )
    for table, col in _JSON_COLS:
        op.execute(
            f"UPDATE {table} SET {col} = replace({col}, '{_OLD}', '{_NEW}') "
            f"WHERE {col} LIKE '%{_OLD}%'"
        )
    op.execute(
        "UPDATE account_ai_config SET ai_chatter_config_json = "
        f"replace(ai_chatter_config_json, '{_SELL_ON_ASK_OLD}', '{_SELL_ON_ASK_NEW}') "
        f"WHERE ai_chatter_config_json LIKE '%{_SELL_ON_ASK_OLD}%'"
    )


def downgrade() -> None:
    for table, col in _TOKEN_COLS:
        op.execute(
            f"UPDATE {table} SET {col} = '{_OLD}' WHERE {col} = '{_NEW}'"
        )
    op.execute(
        f"UPDATE grok_calls SET purpose = '{_OLD}' || substr(purpose, {len(_NEW) + 1}) "
        f"WHERE purpose LIKE '{_NEW}%'"
    )
    for table, col in _JSON_COLS:
        op.execute(
            f"UPDATE {table} SET {col} = replace({col}, '{_NEW}', '{_OLD}') "
            f"WHERE {col} LIKE '%{_NEW}%'"
        )
    op.execute(
        "UPDATE account_ai_config SET ai_chatter_config_json = "
        f"replace(ai_chatter_config_json, '{_SELL_ON_ASK_NEW}', '{_SELL_ON_ASK_OLD}') "
        f"WHERE ai_chatter_config_json LIKE '%{_SELL_ON_ASK_NEW}%'"
    )
