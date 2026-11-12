"""Репозиторий справочника категорий Vilmed в базе данных."""

from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import Engine, text

TABLE_NAME = "vilmed_reference_categories"
SOURCE_SHEET = "Готовый список ID"
SOURCE_COLUMNS = ("Название", "ID раздела")


def import_vilmed_reference_categories(
    engine: Engine,
    workbook_path: str | Path,
    *,
    replace_existing: bool = False,
) -> int:
    """Импортирует лист книги, по умолчанию запрещая замену данных.

    Проверка входных данных выполняется до транзакции. Без явной замены
    непустая таблица остаётся нетронутой; замена атомарно удаляет и добавляет
    строки и затрагивает только эту таблицу.
    """
    workbook = pd.read_excel(workbook_path, sheet_name=SOURCE_SHEET)
    missing_columns = [column for column in SOURCE_COLUMNS if column not in workbook.columns]
    if missing_columns:
        raise ValueError(f"Лист {SOURCE_SHEET!r} не содержит обязательные столбцы")

    rows = workbook.loc[:, list(SOURCE_COLUMNS)].dropna().copy()
    rows["Название"] = rows["Название"].astype(str).str.strip()
    rows = rows[rows["Название"] != ""]
    if rows.empty:
        raise ValueError("В листе нет строк для импорта; существующие данные не изменены")

    category_ids = pd.to_numeric(rows["ID раздела"], errors="raise")
    records: list[dict[str, Any]] = []
    for title, category_id in zip(rows["Название"], category_ids, strict=True):
        numeric_id = int(category_id)
        if numeric_id != category_id:
            raise ValueError("Столбец 'ID раздела' должен содержать целые числа")
        records.append({"category_id": numeric_id, "title": title})

    with engine.begin() as connection:
        if replace_existing:
            connection.execute(text(f"DELETE FROM {TABLE_NAME}"))
        else:
            existing_count = connection.execute(
                text(f"SELECT COUNT(*) FROM {TABLE_NAME}")
            ).scalar_one()
            if existing_count:
                raise ValueError("Таблица уже содержит данные; явная замена не подтверждена")
        connection.execute(
            text(
                f"INSERT INTO {TABLE_NAME} (category_id, title) "
                "VALUES (:category_id, :title)"
            ),
            records,
        )

    return len(records)


def list_vilmed_reference_categories(engine: Engine) -> pd.DataFrame:
    """Возвращает строки справочника с названиями столбцов для обработки Vilmed."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                f"SELECT title AS \"Название\", category_id AS \"ID раздела\" "
                f"FROM {TABLE_NAME} ORDER BY row_id"
            )
        ).mappings().all()

    return pd.DataFrame(rows, columns=SOURCE_COLUMNS)
