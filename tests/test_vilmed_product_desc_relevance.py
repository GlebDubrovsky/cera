"""Офлайн-проверки пакетного анализа релевантности товаров Vilmed."""

import io
import json
import threading
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

from sqlalchemy import create_engine, text

from scenarios.vilmed_product_desc.vilmed_product_desc_relevance import run_product_description_relevance


class ProductDescriptionRelevanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        with self.engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE vilmed_description_products ("
                "row_id INTEGER PRIMARY KEY, url TEXT, keyword TEXT, description TEXT, "
                "important_words TEXT, comp_yandex JSON, comp_google JSON, "
                "score_before REAL, reach_before REAL, density_before REAL)"
            ))

    def tearDown(self) -> None:
        self.engine.dispose()

    def add_product(
        self,
        row_id: int,
        *,
        url: str = "https://vilmed.test/product",
        keyword: str = "product keyword",
        description: str | None = None,
        important_words: str | None = None,
        yandex: str | None = None,
        google: str | None = None,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO vilmed_description_products "
                "(row_id, url, keyword, description, important_words, comp_yandex, comp_google) "
                "VALUES (:row_id, :url, :keyword, :description, :important_words, :yandex, :google)"
            ), {
                "row_id": row_id,
                "url": url,
                "keyword": keyword,
                "description": description,
                "important_words": important_words,
                "yandex": yandex,
                "google": google,
            })

    @staticmethod
    def analysis_result() -> SimpleNamespace:
        return SimpleNamespace(
            sites={"target": {
                "main_page": True,
                "main_points": 72.5,
                "coverage": 66.25,
                "density": {"density_main_percent": 8.0},
            }},
            word_forms={
                "representative": {
                    "representative": {"avg_in_total_competitors": 1, "total_repeat_main_page": 0},
                    "inflected-form": {"avg_in_total_competitors": 1, "total_repeat_main_page": 0},
                    "total": {
                        "number_occurrences": 3,
                        "avg_in_total_competitors": 2,
                        "total_repeat_main_page": 0,
                    },
                },
                "low-average": {
                    "low-average": {"avg_in_total_competitors": 0, "total_repeat_main_page": 0},
                    "total": {
                        "number_occurrences": 3,
                        "avg_in_total_competitors": 0,
                        "total_repeat_main_page": 0,
                    },
                },
                "present": {
                    "present": {"avg_in_total_competitors": 3, "total_repeat_main_page": 1},
                    "total": {
                        "number_occurrences": 3,
                        "avg_in_total_competitors": 3,
                        "total_repeat_main_page": 1,
                    },
                },
                "below-overlap": {
                    "below-overlap": {"avg_in_total_competitors": 1, "total_repeat_main_page": 0},
                    "total": {
                        "number_occurrences": 2,
                        "avg_in_total_competitors": 1,
                        "total_repeat_main_page": 0,
                    },
                },
            },
        )

    def test_uses_yandex_urls_filters_aggregators_and_saves_analysis(self) -> None:
        self.add_product(
            1,
            yandex=json.dumps([
                "https://competitor.test/page",
                "https://www.ozon.ru/product",
                "https://sub.avito.ru/item",
                "https://competitor.test/page/",
            ]),
            google='["https://google-competitor.test"]',
        )
        calls: list[dict[str, object]] = []

        def analysis_runner(config: dict[str, object]) -> SimpleNamespace:
            calls.append(config)
            return self.analysis_result()

        log_output = io.StringIO()
        with redirect_stdout(log_output):
            result = run_product_description_relevance(self.engine, analysis_runner=analysis_runner)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["processed_count"], 1)
        logs = log_output.getvalue()
        self.assertIn("[PRODUCT][START] Товар 1/1; row_id=1.", logs)
        self.assertIn("[ANALYSIS][START] Товар 1/1; row_id=1.", logs)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["link"], "https://vilmed.test/product")
        self.assertEqual(calls[0]["phrase"], "product keyword")
        self.assertEqual(calls[0]["sites"], ["https://competitor.test/page"])
        self.assertTrue(calls[0]["list_words"])
        with self.engine.connect() as connection:
            row = connection.execute(text(
                "SELECT score_before, reach_before, density_before, important_words "
                "FROM vilmed_description_products WHERE row_id = 1"
            )).one()
        self.assertEqual(row.score_before, 72.5)
        self.assertEqual(row.reach_before, 66.25)
        self.assertEqual(row.density_before, 8.0)
        self.assertEqual(json.loads(row.important_words), ["representative"])

    def test_empty_word_selection_does_not_write_empty_json_list(self) -> None:
        self.add_product(1, yandex='["https://competitor.test/page"]')
        empty_selection = self.analysis_result()
        empty_selection.word_forms = {}

        result = run_product_description_relevance(
            self.engine, analysis_runner=lambda _config: empty_selection,
        )

        self.assertEqual(result["error_count"], 0)
        with self.engine.connect() as connection:
            row = connection.execute(text(
                "SELECT score_before, important_words FROM vilmed_description_products "
                "WHERE row_id = 1"
            )).one()
        self.assertEqual(row.score_before, 72.5)
        self.assertIsNone(row.important_words)

    def test_uses_google_if_yandex_is_empty_after_aggregator_filter(self) -> None:
        self.add_product(
            1,
            yandex='["https://ozon.ru/item"]',
            google='["https://google-competitor.test/page"]',
        )
        calls: list[list[str]] = []

        def analysis_runner(config: dict[str, object]) -> SimpleNamespace:
            calls.append(config["sites"])
            return self.analysis_result()

        run_product_description_relevance(self.engine, analysis_runner=analysis_runner)

        self.assertEqual(calls, [["https://google-competitor.test/page"]])

    def test_selects_only_rows_with_empty_description_and_important_words(self) -> None:
        self.add_product(1, yandex='["https://competitor.test"]')
        self.add_product(2, description="Existing", yandex='["https://competitor.test"]')
        self.add_product(3, important_words='["existing"]', yandex='["https://competitor.test"]')
        self.add_product(4)
        processed: list[int] = []

        def analysis_runner(config: dict[str, object]) -> SimpleNamespace:
            processed.append(1)
            return self.analysis_result()

        result = run_product_description_relevance(self.engine, analysis_runner=analysis_runner)

        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["processed_count"], 1)
        self.assertEqual(len(processed), 1)

    def test_analysis_failure_does_not_abort_batch_and_stop_is_checked(self) -> None:
        self.add_product(1, yandex='["https://competitor.test/1"]')
        self.add_product(2, yandex='["https://competitor.test/2"]')
        stop_event = threading.Event()
        calls = 0

        def analysis_runner(config: dict[str, object]) -> SimpleNamespace:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("offline failure")
            stop_event.set()
            return self.analysis_result()

        result = run_product_description_relevance(
            self.engine,
            stop_event=stop_event,
            analysis_runner=analysis_runner,
        )

        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["processed_count"], 2)
        self.assertEqual(result["error_count"], 1)


if __name__ == "__main__":
    unittest.main()
