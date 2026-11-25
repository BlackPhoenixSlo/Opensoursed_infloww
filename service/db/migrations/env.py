from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

# autogenerate on this wide schema recurses ~1100 deep, past CPython's default 1000
sys.setrecursionlimit(50000)

from alembic import context
from sqlalchemy import engine_from_config, pool

HERE = Path(__file__).resolve().parent
SERVICE_ROOT = HERE.parent.parent
sys.path.insert(0, str(SERVICE_ROOT))
sys.path.insert(0, str(SERVICE_ROOT.parent))

from service.db.models import Base  # noqa: E402  — must come after sys.path patch

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolve_url() -> str:
    # precedence -x url > CHATTERLY_DB_URL > alembic.ini; printed before any DB op so a misrouted run never silently hits prod
    x_args = context.get_x_argument(as_dictionary=True)
    if "url" in x_args:
        url, source = x_args["url"], "-x url="
    elif os.environ.get("CHATTERLY_DB_URL"):
        url, source = os.environ["CHATTERLY_DB_URL"], "CHATTERLY_DB_URL env"
    else:
        url, source = config.get_main_option("sqlalchemy.url"), "alembic.ini default"
    print(f"[alembic env] using DB URL: {url}  (source: {source})", file=sys.stderr)
    return url


def run_migrations_offline() -> None:
    url = _resolve_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {}) or {}
    section["sqlalchemy.url"] = _resolve_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        is_sqlite = connection.dialect.name == "sqlite"
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=is_sqlite,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
