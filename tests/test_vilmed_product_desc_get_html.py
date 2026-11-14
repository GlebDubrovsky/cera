"""Офлайн-тесты генерации HTML-описаний Vilmed."""

import io
import json
import threading
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock

from sqlalchemy import create_engine, text

from scenarios.vilmed_product_desc.vilmed_product_desc_get_html import (
    run_vilmed_product_desc_get_html,
)


class VilmedGetHtmlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        with self.engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE vilmed_description_products ("
                "row_id INTEGER PRIMARY KEY, url TEXT, product_name TEXT, package TEXT, "
                "specifications TEXT, select_imp_words TEXT, desc_status TEXT, html_desc TEXT)"
            ))

    def tearDown(self) -> None:
        self.engine.dispose()

    def add_product(
        self,
        row_id: int,
        *,
        words: list[str] | None = None,
        status: str = "missing",
        package: str | None = None,
        specifications: str | None = None,
        html_desc: str | None = None,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO vilmed_description_products "
                "(row_id, url, product_name, package, specifications, select_imp_words, "
                "desc_status, html_desc) VALUES (:row_id, :url, :name, :package, :specifications, "
                ":words, :status, :html_desc)"
            ), {
                "row_id": row_id,
                "url": f"https://vilmed.test/product/{row_id}",
                "name": f"Товар {row_id}",
                "package": package,
                "specifications": specifications,
                "words": json.dumps(words, ensure_ascii=False) if words is not None else None,
                "status": status,
                "html_desc": html_desc,
            })

    @staticmethod
    def response(content: str) -> dict[str, object]:
        return {"choices": [{"message": {"content": content}}]}

    def test_renders_prompt_calls_model_and_saves_unfenced_html(self) -> None:
        self.add_product(
            1,
            words=["дерматоскоп", "насадка"],
            package="Насадка, кабель",
            specifications="Питание 2,5 В",
        )
        completion = Mock(return_value=self.response(
            "```html\n<article class=\"vmd-desc\"><p>Описание</p></article>\n```"
        ))

        with redirect_stdout(io.StringIO()):
            result = run_vilmed_product_desc_get_html(
                self.engine, completion_runner=completion, delay_seconds=0,
            )

        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(completion.call_args.kwargs, {
            "temperature": 0.1,
            "max_tokens": 15000,
            "reasoning_enabled": False,
        })
        prompt = completion.call_args.args[0][0]["content"]
        self.assertIn("https://vilmed.test/product/1", prompt)
        self.assertIn("Товар 1", prompt)
        self.assertIn("Комплектация товара:", prompt)
        self.assertIn("Насадка, кабель", prompt)
        self.assertIn("Характеристики товара:", prompt)
        self.assertIn("Питание 2,5 В", prompt)
        self.assertIn("дерматоскоп, насадка", prompt)
        self.assertNotIn("{{", prompt)
        with self.engine.connect() as connection:
            saved = connection.execute(text(
                "SELECT html_desc FROM vilmed_description_products WHERE row_id = 1"
            )).scalar_one()
        self.assertEqual(saved, '<article class="vmd-desc"><p>Описание</p></article>')

    def test_removes_optional_labels_when_data_is_missing(self) -> None:
        self.add_product(1, words=["слово"])
        completion = Mock(return_value=self.response("<article>Текст</article>"))

        with redirect_stdout(io.StringIO()):
            run_vilmed_product_desc_get_html(
                self.engine, completion_runner=completion, delay_seconds=0,
            )

        prompt = completion.call_args.args[0][0]["content"]
        self.assertNotIn("Комплектация товара:", prompt)
        self.assertNotIn("Характеристики товара:", prompt)

    def test_retries_non_html_three_times_and_leaves_result_empty(self) -> None:
        self.add_product(1, words=["слово"])
        completion = Mock(return_value=self.response("Обычный текст без разметки"))

        with redirect_stdout(io.StringIO()):
            result = run_vilmed_product_desc_get_html(
                self.engine, completion_runner=completion, delay_seconds=0,
            )

        self.assertEqual(completion.call_count, 3)
        self.assertEqual(result["error_count"], 1)
        with self.engine.connect() as connection:
            saved = connection.execute(text(
                "SELECT html_desc FROM vilmed_description_products WHERE row_id = 1"
            )).scalar_one()
        self.assertIsNone(saved)

    def test_only_selects_missing_status_with_words(self) -> None:
        self.add_product(1, words=["слово"])
        self.add_product(2, words=["слово"], status="ready")
        self.add_product(3, words=None)
        self.add_product(4, words=["слово"], html_desc="already written")
        completion = Mock(return_value=self.response("<article>Текст</article>"))

        with redirect_stdout(io.StringIO()):
            result = run_vilmed_product_desc_get_html(
                self.engine, completion_runner=completion, delay_seconds=0,
            )

        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["processed_count"], 2)
        self.assertEqual(completion.call_count, 2)

    def test_stops_after_five_consecutive_product_errors(self) -> None:
        for row_id in range(1, 8):
            self.add_product(row_id, words=["слово"])
        completion = Mock(return_value=self.response("не HTML"))

        with redirect_stdout(io.StringIO()):
            result = run_vilmed_product_desc_get_html(
                self.engine, completion_runner=completion, delay_seconds=0,
            )

        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["processed_count"], 5)
        self.assertEqual(result["error_count"], 5)
        self.assertEqual(completion.call_count, 15)

    def test_stop_event_prevents_processing_next_product(self) -> None:
        self.add_product(1, words=["слово"])
        self.add_product(2, words=["слово"])
        stop_event = threading.Event()
        completion = Mock(side_effect=lambda *_args, **_kwargs: (
            stop_event.set() or self.response("<article>Текст</article>")
        ))

        with redirect_stdout(io.StringIO()):
            result = run_vilmed_product_desc_get_html(
                self.engine, stop_event=stop_event, completion_runner=completion,
                delay_seconds=0,
            )

        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["processed_count"], 1)
        self.assertEqual(completion.call_count, 1)


if __name__ == "__main__":
    unittest.main()
