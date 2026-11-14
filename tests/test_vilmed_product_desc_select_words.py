"""Офлайн-тесты сценария отбора важных слов Vilmed."""

import io
import json
import threading
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock

from sqlalchemy import create_engine, text

from scenarios.vilmed_product_desc.vilmed_product_desc_select_words import (
    run_vilmed_product_desc_select_words,
)


class VilmedSelectWordsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        with self.engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE vilmed_description_products ("
                "row_id INTEGER PRIMARY KEY, product_name TEXT, important_words TEXT, "
                "select_imp_words TEXT)"
            ))

    def tearDown(self) -> None:
        self.engine.dispose()

    def add_product(
        self,
        row_id: int,
        words: list[str] | None,
        selected: str | None = None,
        product_name: str = "Товар Vilmed",
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO vilmed_description_products "
                "(row_id, product_name, important_words, select_imp_words) "
                "VALUES (:row_id, :product_name, :important_words, :selected)"
            ), {
                "row_id": row_id,
                "product_name": product_name,
                "important_words": json.dumps(words, ensure_ascii=False) if words is not None else None,
                "selected": selected,
            })

    @staticmethod
    def valid_response(content: str = "дерматоскоп, насадка") -> dict[str, object]:
        return {"choices": [{"message": {"content": content}}]}

    def test_selects_eligible_rows_renders_prompt_and_saves_json_list(self) -> None:
        self.add_product(1, ["дерматоскоп", "насадка", "светодиод"])
        self.add_product(2, ["одно слово"])
        self.add_product(3, ["слово", "насадка"], selected='["ранее выбрано"]')
        completion = Mock(return_value=self.valid_response())

        with redirect_stdout(io.StringIO()):
            result = run_vilmed_product_desc_select_words(
                self.engine, completion_runner=completion, delay_seconds=0,
            )

        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["processed_count"], 1)
        self.assertEqual(completion.call_args.kwargs, {
            "temperature": 0.1,
            "max_tokens": 10000,
            "reasoning_enabled": False,
        })
        prompt = completion.call_args.args[0][0]["content"]
        self.assertIn("Товар Vilmed", prompt)
        self.assertIn("дерматоскоп, насадка, светодиод", prompt)
        with self.engine.connect() as connection:
            saved = connection.execute(text(
                "SELECT select_imp_words FROM vilmed_description_products WHERE row_id = 1"
            )).scalar_one()
        self.assertEqual(json.loads(saved), ["дерматоскоп", "насадка"])

    def test_rejects_response_that_is_not_a_plain_list(self) -> None:
        self.add_product(1, ["слово один", "слово два"])
        completion = Mock(return_value=self.valid_response("- слово один"))

        with redirect_stdout(io.StringIO()):
            result = run_vilmed_product_desc_select_words(
                self.engine, completion_runner=completion, delay_seconds=0,
            )

        self.assertEqual(result["error_count"], 1)
        self.assertEqual(completion.call_count, 3)
        with self.engine.connect() as connection:
            saved = connection.execute(text(
                "SELECT select_imp_words FROM vilmed_description_products WHERE row_id = 1"
            )).scalar_one()
        self.assertIsNone(saved)

    def test_empty_model_answer_is_an_error_and_leaves_cell_empty(self) -> None:
        self.add_product(1, ["слово один", "слово два"])
        completion = Mock(return_value=self.valid_response("  "))

        with redirect_stdout(io.StringIO()):
            result = run_vilmed_product_desc_select_words(
                self.engine, completion_runner=completion, delay_seconds=0,
            )

        self.assertEqual(result["error_count"], 1)
        self.assertEqual(completion.call_count, 3)
        with self.engine.connect() as connection:
            saved = connection.execute(text(
                "SELECT select_imp_words FROM vilmed_description_products WHERE row_id = 1"
            )).scalar_one()
        self.assertIsNone(saved)

    def test_stops_after_five_consecutive_errors(self) -> None:
        for row_id in range(1, 8):
            self.add_product(row_id, ["слово один", "слово два"])
        completion = Mock(return_value=self.valid_response("одно, два, три"))

        with redirect_stdout(io.StringIO()):
            result = run_vilmed_product_desc_select_words(
                self.engine, completion_runner=completion, delay_seconds=0,
            )

        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["processed_count"], 5)
        self.assertEqual(result["error_count"], 5)
        self.assertEqual(completion.call_count, 15)

    def test_success_resets_consecutive_error_counter(self) -> None:
        for row_id in range(1, 7):
            self.add_product(row_id, ["слово один", "слово два"])
        invalid = self.valid_response("- неверно")
        completion = Mock(side_effect=[
            invalid, invalid, invalid,
            invalid, invalid, invalid,
            self.valid_response("слово один"),
            invalid, invalid, invalid,
            invalid, invalid, invalid,
            self.valid_response("слово два"),
        ])

        with redirect_stdout(io.StringIO()):
            result = run_vilmed_product_desc_select_words(
                self.engine, completion_runner=completion, delay_seconds=0,
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["processed_count"], 6)
        self.assertEqual(result["error_count"], 4)
        self.assertEqual(completion.call_count, 14)

    def test_retries_and_saves_when_later_attempt_is_valid(self) -> None:
        self.add_product(1, ["слово один", "слово два"])
        completion = Mock(side_effect=[
            self.valid_response("  "),
            self.valid_response("- невалидно"),
            self.valid_response("слово один"),
        ])

        with redirect_stdout(io.StringIO()):
            result = run_vilmed_product_desc_select_words(
                self.engine, completion_runner=completion, delay_seconds=0,
            )

        self.assertEqual(result["error_count"], 0)
        self.assertEqual(completion.call_count, 3)
        with self.engine.connect() as connection:
            saved = connection.execute(text(
                "SELECT select_imp_words FROM vilmed_description_products WHERE row_id = 1"
            )).scalar_one()
        self.assertEqual(json.loads(saved), ["слово один"])

    def test_stop_event_prevents_next_product_after_delay(self) -> None:
        self.add_product(1, ["слово один", "слово два"])
        self.add_product(2, ["слово один", "слово два"])
        stop_event = threading.Event()
        completion = Mock(side_effect=lambda *_args, **_kwargs: (
            stop_event.set() or self.valid_response("слово один")
        ))

        with redirect_stdout(io.StringIO()):
            result = run_vilmed_product_desc_select_words(
                self.engine,
                stop_event=stop_event,
                completion_runner=completion,
                delay_seconds=0,
            )

        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["processed_count"], 1)
        self.assertEqual(completion.call_count, 1)


if __name__ == "__main__":
    unittest.main()
