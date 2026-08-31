import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app import models  # noqa: F401
from app.config import settings
from app.database import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata


def configure(connection=None) -> None:
    context.configure(
        connection=connection,
        url=None if connection is not None else config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        include_schemas=True,
        version_table="alembic_version_agents",
        literal_binds=connection is None,
        dialect_opts={"paramstyle": "named"},
    )


def run_migrations_offline() -> None:
    configure()
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
