"""Общие вспомогательные средства для работы приложения с базой данных."""

from sqlalchemy import Engine, create_engine, text


def normalize_database_url(database_url: str) -> str:
    """Указывает драйвер psycopg 3 для стандартных адресов PostgreSQL."""
    normalized_url = database_url.strip()
    if normalized_url.startswith("postgres://"):
        return "postgresql+psycopg://" + normalized_url.removeprefix("postgres://")
    if normalized_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + normalized_url.removeprefix("postgresql://")
    return normalized_url


def create_database_engine(database_url: str) -> Engine:
    """Создаёт движок с отложенным подключением по адресу из окружения.

    Сетевое соединение открывается только при первом обращении к движку,
    поэтому приложение может запуститься, даже если PostgreSQL недоступен.
    """
    normalized_url = normalize_database_url(database_url)
    if not normalized_url:
        raise ValueError("Переменная DATABASE_URL не должна быть пустой")

    return create_engine(normalized_url, pool_pre_ping=True)


def check_database_connection(engine: Engine) -> None:
    """Проверяет соединение простым запросом и передаёт ошибку SQLAlchemy выше."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
