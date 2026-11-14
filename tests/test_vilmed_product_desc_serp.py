"""Offline tests for the Vilmed product-description scenario."""

import json
import threading
import unittest

from sqlalchemy import create_engine, text

from scenarios.vilmed_product_desc.vilmed_product_desc_serp import run_product_descriptions


class ProductDescriptionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE vilmed_description_products ("
                    "row_id INTEGER PRIMARY KEY, keyword TEXT, description TEXT, "
                    "comp_yandex JSON, comp_google JSON)"
                )
            )

    def tearDown(self) -> None:
        self.engine.dispose()

    def add_product(
        self,
        row_id: int,
        keyword: str,
        description: str | None = None,
        yandex: str | None = None,
        google: str | None = None,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO vilmed_description_products "
                    "(row_id, keyword, description, comp_yandex, comp_google) "
                    "VALUES (:row_id, :keyword, :description, :yandex, :google)"
                ),
                {
                    "row_id": row_id,
                    "keyword": keyword,
                    "description": description,
                    "yandex": yandex,
                    "google": google,
                },
            )

    def test_successful_yandex_stores_only_urls_and_skips_google(self) -> None:
        self.add_product(1, "keyword one")
        self.add_product(2, "already described", "Description")
        self.add_product(
            3,
            "already processed",
            yandex='[{"result": "old"}]',
            google='[{"result": "old"}]',
        )
        self.add_product(4, "   ")
        self.add_product(5, "only yandex populated", yandex='[{"url": "https://existing-yandex.test"}]')
        self.add_product(6, "only google populated", google='[{"url": "https://existing-google.test"}]')
        calls: list[tuple[str, list[str], int]] = []

        def search_runner(module_id: str, phrases: list[str], top_n: int) -> list[dict[str, object]]:
            calls.append((module_id, phrases, top_n))
            return [{
                "phrase": phrases[0],
                "results": [{"url": f"https://{module_id}.test", "title": "ignored"}],
                "responses": ["ignored"],
                "error": None,
            }]

        progress: list[dict[str, object]] = []
        result = run_product_descriptions(
            self.engine,
            search_runner=search_runner,
            progress_callback=lambda **values: progress.append(values),
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["total_count"], 6)
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["processed_count"], 1)
        self.assertEqual(calls, [("serp", ["keyword one"], 20)])
        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT comp_yandex, comp_google FROM vilmed_description_products WHERE row_id = 1")
            ).one()
        self.assertEqual(json.loads(row.comp_yandex), ["https://serp.test"])
        self.assertIsNone(row.comp_google)
        self.assertEqual(progress[-1]["processed_count"], 1)

    def test_no_candidates_finishes_without_search_requests(self) -> None:
        self.add_product(1, "finished", "Description", '[{"ok": true}]', '[{"ok": true}]')
        calls: list[str] = []

        def search_runner(module_id: str, phrases: list[str], top_n: int) -> list[dict[str, str]]:
            calls.append(module_id)
            return []

        result = run_product_descriptions(self.engine, search_runner=search_runner)

        self.assertEqual(result["status"], "no_candidates")
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["processed_count"], 0)
        self.assertEqual(calls, [])

    def test_yandex_failure_falls_back_to_google_and_keeps_url_list(self) -> None:
        self.add_product(1, "keyword")
        calls: list[str] = []

        def search_runner(module_id: str, phrases: list[str], top_n: int) -> list[dict[str, object]]:
            calls.append(module_id)
            if module_id == "serp":
                raise RuntimeError("offline test failure")
            return [{
                "phrase": phrases[0],
                "results": [{"url": "https://google.test", "title": "ignored"}],
                "responses": ["ignored"],
                "error": None,
            }]

        result = run_product_descriptions(
            self.engine,
            search_runner=search_runner,
            request_delay_seconds=0,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(calls, ["serp", "google_serp"])
        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT comp_yandex, comp_google FROM vilmed_description_products WHERE row_id = 1")
            ).one()
        self.assertIsNone(row.comp_yandex)
        self.assertEqual(json.loads(row.comp_google), ["https://google.test"])

    def test_consecutive_double_provider_failures_stop_after_five(self) -> None:
        for row_id in range(1, 7):
            self.add_product(row_id, f"keyword {row_id}")
        calls: list[str] = []
        progress: list[dict[str, object]] = []

        def search_runner(module_id: str, phrases: list[str], top_n: int) -> list[dict[str, object]]:
            calls.append(module_id)
            raise RuntimeError("offline test failure")

        result = run_product_descriptions(
            self.engine,
            search_runner=search_runner,
            request_delay_seconds=0,
            progress_callback=lambda **values: progress.append(values),
        )

        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["processed_count"], 5)
        self.assertEqual(result["error_count"], 5)
        self.assertEqual(calls, ["serp", "google_serp"] * 5)
        processed_errors = [item["error_count"] for item in progress if item["processed_count"]]
        self.assertEqual(processed_errors, [1, 2, 3, 4, 5])
        self.assertIn("5 строк подряд", progress[-1]["message"])

    def test_success_resets_consecutive_error_count(self) -> None:
        for row_id, keyword in enumerate(("first", "second", "third", "fourth"), start=1):
            self.add_product(row_id, keyword)
        progress: list[dict[str, object]] = []

        def search_runner(module_id: str, phrases: list[str], top_n: int) -> list[dict[str, object]]:
            if phrases[0] != "third":
                raise RuntimeError("offline test failure")
            return [{
                "phrase": phrases[0],
                "results": [{"url": "https://success.test"}],
                "error": None,
            }]

        result = run_product_descriptions(
            self.engine,
            search_runner=search_runner,
            request_delay_seconds=0,
            progress_callback=lambda **values: progress.append(values),
        )

        processed_errors = [item["error_count"] for item in progress if item["processed_count"]]
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["error_count"], 1)
        self.assertEqual(processed_errors, [1, 2, 0, 1])

    def test_stop_signal_is_checked_before_each_product(self) -> None:
        self.add_product(1, "keyword")
        cancellation = threading.Event()
        cancellation.set()
        calls: list[str] = []

        def search_runner(module_id: str, phrases: list[str], top_n: int) -> list[dict[str, str]]:
            calls.append(module_id)
            return [{"phrase": phrases[0]}]

        result = run_product_descriptions(
            self.engine,
            stop_event=cancellation,
            search_runner=search_runner,
        )

        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["processed_count"], 0)
        self.assertEqual(calls, [])

    def test_search_requests_run_concurrently_up_to_selected_worker_count(self) -> None:
        worker_count = 4
        for row_id in range(1, worker_count + 1):
            self.add_product(row_id, f"keyword {row_id}")
        barrier = threading.Barrier(worker_count)
        lock = threading.Lock()
        active_calls = 0
        maximum_active_calls = 0

        def search_runner(module_id: str, phrases: list[str], top_n: int) -> list[dict[str, object]]:
            nonlocal active_calls, maximum_active_calls
            with lock:
                active_calls += 1
                maximum_active_calls = max(maximum_active_calls, active_calls)
            try:
                barrier.wait(timeout=5)
            finally:
                with lock:
                    active_calls -= 1
            return [{"results": [{"url": f"https://{phrases[0]}.test"}]}]

        result = run_product_descriptions(
            self.engine,
            worker_count=worker_count,
            search_runner=search_runner,
            request_delay_seconds=0,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["processed_count"], worker_count)
        self.assertEqual(maximum_active_calls, worker_count)

    def test_error_limit_scales_with_worker_count(self) -> None:
        worker_count = 2
        for row_id in range(1, 13):
            self.add_product(row_id, f"keyword {row_id}")
        calls: list[str] = []
        calls_lock = threading.Lock()

        def search_runner(module_id: str, phrases: list[str], top_n: int) -> list[dict[str, object]]:
            with calls_lock:
                calls.append(module_id)
            raise RuntimeError("offline test failure")

        result = run_product_descriptions(
            self.engine,
            worker_count=worker_count,
            search_runner=search_runner,
            request_delay_seconds=0,
        )

        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["processed_count"], 5 * worker_count)
        self.assertEqual(result["error_count"], 5 * worker_count)
        self.assertEqual(len(calls), 10 * worker_count)


if __name__ == "__main__":
    unittest.main()
