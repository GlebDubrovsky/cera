"""Офлайн-тесты повторного анализа метрик товаров Vilmed."""

import json
import threading
import unittest
from types import SimpleNamespace

from sqlalchemy import create_engine, text

from scenarios.vilmed_product_desc.vilmed_product_desc_relevance_after import (
    run_product_description_relevance_after,
)


class ProductDescriptionRelevanceAfterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        with self.engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE vilmed_description_products ("
                "row_id INTEGER PRIMARY KEY, url TEXT, keyword TEXT, desc_status TEXT, "
                "comp_yandex JSON, comp_google JSON, score_before REAL, score_after REAL, "
                "reach_after REAL, density_after REAL, score_delta REAL)"
            ))

    def tearDown(self) -> None:
        self.engine.dispose()

    def add_product(
        self,
        row_id: int,
        *,
        status: str = "inserted",
        score_before: float | None = 50.0,
        score_after: float | None = None,
        yandex: list[str] | None = None,
        google: list[str] | None = None,
        url: str = "https://vilmed.test/product",
        keyword: str = "product keyword",
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO vilmed_description_products "
                "(row_id, url, keyword, desc_status, comp_yandex, comp_google, score_before, score_after) "
                "VALUES (:row_id, :url, :keyword, :status, :yandex, :google, :score_before, :score_after)"
            ), {
                "row_id": row_id,
                "url": url,
                "keyword": keyword,
                "status": status,
                "yandex": json.dumps(yandex) if yandex is not None else None,
                "google": json.dumps(google) if google is not None else None,
                "score_before": score_before,
                "score_after": score_after,
            })

    @staticmethod
    def analysis_result(score: float = 72.5) -> SimpleNamespace:
        return SimpleNamespace(sites={"target": {
            "main_page": True,
            "main_points": score,
            "coverage": 66.25,
            "density": {"density_main_percent": 8.0},
        }})

    def get_saved_values(self, row_id: int) -> tuple[float | None, ...]:
        with self.engine.connect() as connection:
            row = connection.execute(text(
                "SELECT score_after, reach_after, density_after, score_delta "
                "FROM vilmed_description_products WHERE row_id = :row_id"
            ), {"row_id": row_id}).one()
        return tuple(row)

    def test_filters_candidates_cleans_aggregators_and_saves_after_metrics(self) -> None:
        self.add_product(1, yandex=[
            "https://competitor.test/page", "https://www.ozon.ru/product",
            "https://sub.avito.ru/item",
        ], google=["https://google-competitor.test"])
        self.add_product(2, status="missing", yandex=["https://competitor.test"])
        self.add_product(3, score_after=60.0, yandex=["https://competitor.test"])
        self.add_product(4, score_before=None, yandex=["https://competitor.test"])
        calls: list[dict[str, object]] = []

        def analysis_runner(config: dict[str, object]) -> SimpleNamespace:
            calls.append(config)
            return self.analysis_result()

        result = run_product_description_relevance_after(
            self.engine, analysis_runner=analysis_runner,
        )

        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["processed_count"], 1)
        self.assertEqual(calls[0]["link"], "https://vilmed.test/product")
        self.assertEqual(calls[0]["phrase"], "product keyword")
        self.assertEqual(calls[0]["sites"], ["https://competitor.test/page"])
        self.assertTrue(calls[0]["list_words"])
        self.assertEqual(self.get_saved_values(1), (72.5, 66.25, 8.0, 22.5))
        self.assertEqual(self.get_saved_values(2), (None, None, None, None))

    def test_uses_google_when_yandex_contains_only_aggregators(self) -> None:
        self.add_product(
            1,
            yandex=["https://ozon.ru/item"],
            google=["https://google-competitor.test/page"],
        )
        calls: list[list[str]] = []
        result = run_product_description_relevance_after(
            self.engine,
            analysis_runner=lambda config: (
                calls.append(config["sites"]) or self.analysis_result()
            ),
        )

        self.assertEqual(result["error_count"], 0)
        self.assertEqual(calls, [["https://google-competitor.test/page"]])

    def test_row_failure_does_not_abort_batch(self) -> None:
        self.add_product(1, yandex=["https://competitor.test/1"])
        self.add_product(2, yandex=["https://competitor.test/2"])
        calls = 0

        def analysis_runner(_config: dict[str, object]) -> SimpleNamespace:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("offline failure")
            return self.analysis_result()

        result = run_product_description_relevance_after(
            self.engine, analysis_runner=analysis_runner,
        )

        self.assertEqual(result["processed_count"], 2)
        self.assertEqual(result["error_count"], 1)
        self.assertIsNone(self.get_saved_values(1)[0])
        self.assertEqual(self.get_saved_values(2)[0], 72.5)

    def test_stop_is_checked_between_products(self) -> None:
        self.add_product(1, yandex=["https://competitor.test/1"])
        self.add_product(2, yandex=["https://competitor.test/2"])
        stop_event = threading.Event()

        def analysis_runner(_config: dict[str, object]) -> SimpleNamespace:
            stop_event.set()
            return self.analysis_result()

        result = run_product_description_relevance_after(
            self.engine, stop_event=stop_event, analysis_runner=analysis_runner,
        )

        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["processed_count"], 1)
        self.assertIsNone(self.get_saved_values(2)[0])


if __name__ == "__main__":
    unittest.main()
