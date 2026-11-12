"""Безопасный импорт пяти независимых листов книги Vilmed в отдельные таблицы."""

from __future__ import annotations

import argparse
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from config.config import get_database_url
from shared.database import create_database_engine, normalize_database_url

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKBOOK = PROJECT_ROOT / "worksheets" / "work_vilmed.xlsx"
BATCH_SIZE = 500

SHEET_IMPORTS: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    ("Плитка тегов", "vilmed_tag_tiles", (("Ссылка", "link_text"),)),
    (
        "categories_id",
        "vilmed_categories",
        (
            ("Название", "category_name"),
            ("Активность", "activity"),
            ("Символьный код", "symbol_code"),
            ("Элементов", "element_count"),
            ("Дата изменения", "modified_at"),
            ("ID раздела", "category_id"),
            ("Уровень", "level"),
            ("Скрыть из меню и категорий вывод", "hide_from_menu_and_categories"),
            ("Название для меню", "menu_name"),
            ("Скрыть только из меню", "hide_only_from_menu"),
        ),
    ),
    (
        "bar_tags",
        "vilmed_bar_tags",
        (
            ("Address", "address"),
            ("h1", "h1"),
            ("main_cat", "main_category"),
            ("parent_cat", "parent_category"),
            ("normal_form", "normal_form"),
        ),
    ),
    (
        "menu_categories",
        "vilmed_menu_categories",
        (
            ("Название", "category_name"),
            ("Активность", "activity"),
            ("Символьный код", "symbol_code"),
            ("Элементов", "element_count"),
            ("Дата изменения", "modified_at"),
            ("ID раздела", "category_id"),
            ("Уровень", "level"),
            ("Скрыть из меню и категорий вывод", "hide_from_menu_and_categories"),
            ("Название для меню", "menu_name"),
            ("Скрыть только из меню", "hide_only_from_menu"),
        ),
    ),
    (
        "all_products",
        "vilmed_products",
        (
            ("Название", "product_name"),
            ("Символьный код", "symbol_code"),
            ("Детальное описание", "description"),
            ("ID", "product_id"),
            ("Артикул", "sku"),
            ("Комплектация", "package"),
            ("Характеристики", "specifications"),
            ("Ключевая фраза", "keyword"),
            ("Категория", "category"),
        ),
    ),
)


def _cell_to_text(value: Any) -> str | None:
    """Сохраняет значение ячейки в текстовом столбце без потери целых ID."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    return str(value)


def _validate_workbook(workbook: Any) -> None:
    """Проверяет наличие всех листов и точное совпадение заголовков до записи."""
    for sheet_name, _, columns in SHEET_IMPORTS:
        if sheet_name not in workbook.sheetnames:
            raise ValueError(f"В книге отсутствует лист {sheet_name!r}")
        worksheet = workbook[sheet_name]
        actual_headers = tuple(
            str(value).strip() if value is not None else ""
            for value in next(worksheet.iter_rows(min_row=1, max_row=1, values_only=True))
        )
        expected_headers = tuple(source_name for source_name, _ in columns)
        if actual_headers[: len(expected_headers)] != expected_headers:
            raise ValueError(f"Заголовки листа {sheet_name!r} отличаются от ожидаемых")


def import_vilmed_workbook_sheets(
    engine: Engine,
    workbook_path: str | Path,
) -> dict[str, int | None]:
    """Импортирует каждый лист только в пустую таблицу; заполненные таблицы пропускает.

    Каждая таблица импортируется отдельной транзакцией. Поэтому сбой одного листа
    откатывает только его строки, а повторный запуск безопасно продолжает остальные.
    Возвращает количество добавленных строк; для пропущенной таблицы возвращает None.
    """
    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    results: dict[str, int | None] = {}
    try:
        _validate_workbook(workbook)
        for sheet_name, table_name, columns in SHEET_IMPORTS:
            print(f"[VILMED][DB_IMPORT][START] Импорт листа {sheet_name}", flush=True)
            column_names = tuple(column_name for _, column_name in columns)
            placeholders = ", ".join(f":{name}" for name in column_names)
            column_sql = ", ".join(f'"{name}"' for name in column_names)
            insert_statement = text(
                f'INSERT INTO "{table_name}" ({column_sql}) VALUES ({placeholders})'
            )
            imported_count = 0
            batch: list[dict[str, str | None]] = []

            with engine.begin() as connection:
                connection.execute(text(f'LOCK TABLE "{table_name}" IN EXCLUSIVE MODE'))
                existing_count = connection.execute(
                    text(f'SELECT COUNT(*) FROM "{table_name}"')
                ).scalar_one()
                if existing_count:
                    results[table_name] = None
                    print(
                        f"[VILMED][DB_IMPORT][SKIP] Таблица {table_name} уже содержит строк: {existing_count}",
                        flush=True,
                    )
                    continue

                worksheet = workbook[sheet_name]
                for values in worksheet.iter_rows(min_row=2, values_only=True):
                    row_values = values[: len(columns)]
                    if not any(value is not None and value != "" for value in row_values):
                        continue
                    record = {
                        column_names[index]: _cell_to_text(row_values[index])
                        if index < len(row_values)
                        else None
                        for index in range(len(column_names))
                    }
                    batch.append(record)
                    if len(batch) >= BATCH_SIZE:
                        connection.execute(insert_statement, batch)
                        imported_count += len(batch)
                        batch.clear()

                if batch:
                    connection.execute(insert_statement, batch)
                    imported_count += len(batch)
                if imported_count == 0:
                    raise ValueError(f"В листе {sheet_name!r} нет строк для импорта")

            results[table_name] = imported_count
            print(
                f"[VILMED][DB_IMPORT][SUCCESS] Таблица {table_name}: добавлено строк {imported_count}",
                flush=True,
            )
    finally:
        workbook.close()
    return results


def main() -> int:
    """Запускает импорт после явной сверки имени целевой базы."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=DEFAULT_WORKBOOK)
    parser.add_argument("--target-database", required=True, help="имя базы PostgreSQL")
    arguments = parser.parse_args()
    if not arguments.file.is_file():
        parser.error("файл книги для импорта не найден")

    database_url = get_database_url()
    if database_url is None:
        parser.error("DATABASE_URL не задан в окружении приложения")
    parsed_url = make_url(normalize_database_url(database_url))
    if parsed_url.get_backend_name() != "postgresql":
        parser.error("импорт разрешён только в PostgreSQL")
    if parsed_url.database != arguments.target_database:
        parser.error("имя базы в DATABASE_URL не совпадает с --target-database")

    engine = create_database_engine(database_url)
    try:
        print("[VILMED][DB_IMPORT][START] Начинаю перенос пяти листов книги", flush=True)
        results = import_vilmed_workbook_sheets(engine, arguments.file)
    except Exception as error:
        print(
            f"[VILMED][DB_IMPORT][ERROR] Импорт прерван; тип ошибки: {type(error).__name__}",
            flush=True,
        )
        return 1
    finally:
        engine.dispose()

    imported_total = sum(count for count in results.values() if count is not None)
    skipped_total = sum(count is None for count in results.values())
    print(
        f"[VILMED][DB_IMPORT][SUCCESS] Перенос завершён; добавлено строк: {imported_total}; пропущено заполненных таблиц: {skipped_total}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
