"""Офлайн-тесты репозитория справочника Vilmed."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from modules.vilmed.repository import (
    import_vilmed_reference_categories,
    list_vilmed_reference_categories,
)


class VilmedRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE vilmed_reference_categories ("
                    "row_id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "category_id INTEGER NOT NULL, title TEXT NOT NULL)"
                )
            )
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workbook_path = Path(self.temp_dir.name) / "work_vilmed.xlsx"

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temp_dir.cleanup()

    def write_workbook(self, rows: list[dict[str, object]]) -> None:
        pd.DataFrame(rows).to_excel(self.workbook_path, index=False, sheet_name="Готовый список ID")

    def test_import_filters_blank_rows_and_returns_application_columns(self) -> None:
        self.write_workbook(
            [
                {"Название": " A", "ID раздела": 123},
                {"Название": "", "ID раздела": 456},
                {"Название": None, "ID раздела": 789},
            ]
        )

        imported_count = import_vilmed_reference_categories(self.engine, self.workbook_path)
        result = list_vilmed_reference_categories(self.engine)

        self.assertEqual(imported_count, 1)
        self.assertEqual(list(result.columns), ["Название", "ID раздела"])
        self.assertEqual(result.to_dict("records"), [{"Название": "A", "ID раздела": 123}])

    def test_reimport_requires_explicit_replacement(self) -> None:
        self.write_workbook([{"Название": "First", "ID раздела": 1}])
        import_vilmed_reference_categories(self.engine, self.workbook_path)
        self.write_workbook([{"Название": "Second", "ID раздела": 2}])

        with self.assertRaises(ValueError):
            import_vilmed_reference_categories(self.engine, self.workbook_path)
        self.assertEqual(
            list_vilmed_reference_categories(self.engine).to_dict("records"),
            [{"Название": "First", "ID раздела": 1}],
        )

        import_vilmed_reference_categories(
            self.engine,
            self.workbook_path,
            replace_existing=True,
        )
        result = list_vilmed_reference_categories(self.engine)
        self.assertEqual(result.to_dict("records"), [{"Название": "Second", "ID раздела": 2}])

    def test_invalid_workbook_does_not_delete_existing_data(self) -> None:
        self.write_workbook([{"Название": "Existing", "ID раздела": 1}])
        import_vilmed_reference_categories(self.engine, self.workbook_path)
        self.write_workbook([{"Название": "Missing id"}])

        with self.assertRaises(ValueError):
            import_vilmed_reference_categories(self.engine, self.workbook_path)

        result = list_vilmed_reference_categories(self.engine)
        self.assertEqual(result.to_dict("records"), [{"Название": "Existing", "ID раздела": 1}])

    def test_empty_import_is_rejected_without_clearing_table(self) -> None:
        self.write_workbook([{"Название": "Existing", "ID раздела": 1}])
        import_vilmed_reference_categories(self.engine, self.workbook_path)
        self.write_workbook([{"Название": "", "ID раздела": 2}])

        with self.assertRaises(ValueError):
            import_vilmed_reference_categories(self.engine, self.workbook_path)

        self.assertEqual(
            list_vilmed_reference_categories(self.engine).to_dict("records"),
            [{"Название": "Existing", "ID раздела": 1}],
        )


if __name__ == "__main__":
    unittest.main()
