"""Команда импорта справочного листа Vilmed из книги Excel."""

from __future__ import annotations

import argparse
from pathlib import Path

from config.config import get_database_url
from modules.vilmed.repository import import_vilmed_reference_categories
from shared.database import create_database_engine, normalize_database_url
from sqlalchemy import text
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKBOOK = PROJECT_ROOT / "worksheets" / "work_vilmed.xlsx"


def main() -> int:
    """Импортирует лист справочника после явной проверки целевой базы."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=DEFAULT_WORKBOOK)
    parser.add_argument(
        "--target-database",
        required=True,
        help="имя базы PostgreSQL; должно совпадать с DATABASE_URL",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="заменить существующие строки в vilmed_reference_categories",
    )
    parser.add_argument(
        "--backup-confirmed",
        action="store_true",
        help="подтвердить наличие резервной копии перед заменой строк",
    )
    arguments = parser.parse_args()

    if not arguments.file.is_file():
        parser.error("файл для импорта не найден")

    database_url = get_database_url()
    if database_url is None:
        parser.error("DATABASE_URL не задан в окружении приложения")
    parsed_url = make_url(normalize_database_url(database_url))
    if parsed_url.get_backend_name() != "postgresql":
        parser.error("импорт Vilmed разрешён только в PostgreSQL")
    if parsed_url.database != arguments.target_database:
        parser.error("имя базы в DATABASE_URL не совпадает с --target-database")
    if arguments.replace and not arguments.backup_confirmed:
        parser.error("перед --replace создай резервную копию и укажи --backup-confirmed")

    engine = create_database_engine(database_url)
    try:
        with engine.connect() as connection:
            existing_count = connection.execute(
                text("SELECT COUNT(*) FROM vilmed_reference_categories")
            ).scalar_one()
        if existing_count and not arguments.replace:
            parser.error("таблица уже содержит данные; для замены нужны --replace и резервная копия")
        imported_count = import_vilmed_reference_categories(
            engine,
            arguments.file,
            replace_existing=arguments.replace,
        )
    except Exception:
        print(
            "[VILMED][DB_IMPORT][ERROR] Импорт не выполнен",
            flush=True,
        )
        return 1
    finally:
        engine.dispose()

    print(
        f"[VILMED][DB_IMPORT][SUCCESS] Импортировано строк: {imported_count}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
