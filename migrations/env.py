"""Настройка Alembic с адресом базы из окружения приложения."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from config.config import get_database_url
from shared.database import normalize_database_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = get_database_url()
if database_url is None:
    raise RuntimeError("Перед запуском миграций задайте переменную DATABASE_URL")
database_url = normalize_database_url(database_url)

# ConfigParser в Alembic воспринимает знак процента как маркер подстановки.
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
target_metadata = None


def run_migrations_offline() -> None:
    """Формирует SQL-код миграции без подключения к базе данных."""
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Выполняет миграции через временное соединение SQLAlchemy."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    try:
        with connectable.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
