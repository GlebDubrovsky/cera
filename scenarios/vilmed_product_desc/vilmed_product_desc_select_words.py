"""Отбор важных слов для товаров Vilmed через OpenAI-совместимый API.

Публичная точка входа выбирает товары с несколькими important_words и пустым
select_imp_words, подставляет данные в общий prompt и сохраняет проверенный
список как JSON-массив. Для каждого товара выполняется до трёх попыток получить
валидный ответ; пять последовательных ошибок товаров останавливают пакет.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy import Engine, text

from modules.openai_api import chat_completion
from shared.prompt_templates import load_prompt_template, render_prompt_template

TABLE_NAME = "vilmed_description_products"
PROMPT_TEMPLATE_NAME = "prompt_select_important_words_3.md"
MAX_ATTEMPTS_PER_PRODUCT = 3
MAX_CONSECUTIVE_ERRORS = 5
ITERATION_DELAY_SECONDS = 1.0

_COUNT_TOTAL = text(f"SELECT COUNT(*) FROM {TABLE_NAME}")
_SELECT_CANDIDATES = text(
    f"SELECT row_id, product_name, important_words FROM {TABLE_NAME} "
    "WHERE COALESCE(TRIM(important_words), '') <> '' "
    "AND COALESCE(TRIM(select_imp_words), '') = '' ORDER BY row_id"
)


def _parse_word_list(value: Any) -> list[str]:
    """Возвращает слова из JSON-массива или пустой список при некорректном поле."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    words = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return words if len(words) == len(value) else []


def _validate_answer(answer: Any, source_word_count: int) -> list[str]:
    """Принимает только непустой однострочный список через запятую разумной длины."""
    if not isinstance(answer, str) or not answer.strip() or "\n" in answer or "\r" in answer:
        raise ValueError("Ответ должен быть непустым списком в одну строку.")
    if answer.lstrip().startswith(("-", "*", "•", "[", "{")):
        raise ValueError("Ответ содержит разметку вместо простого списка.")
    words = [word.strip() for word in answer.split(",")]
    if any(not word for word in words) or len(words) > source_word_count:
        raise ValueError("Список ответа пуст или длиннее исходного списка.")
    return words


def run_vilmed_product_desc_select_words(
    engine: Engine,
    *,
    stop_event: threading.Event | None = None,
    progress_callback: Callable[..., None] | None = None,
    completion_runner: Callable[..., Mapping[str, Any]] = chat_completion,
    delay_seconds: float = ITERATION_DELAY_SECONDS,
) -> dict[str, int | str]:
    """Выбирает важные слова и сохраняет результат в ``select_imp_words``.

    Для одной строки допускаются три попытки получить и проверить ответ. Только
    окончательная неудача товара или ошибка записи увеличивает общий счётчик и
    последовательную серию; корректный сохранённый ответ сбрасывает серию. Пауза
    между товарами позволяет обработчику быстро отреагировать на stop.
    """
    cancellation = stop_event or threading.Event()
    report = progress_callback or (lambda **_: None)
    template = load_prompt_template(PROMPT_TEMPLATE_NAME)
    with engine.connect() as connection:
        total_count = int(connection.execute(_COUNT_TOTAL).scalar_one())
        rows = connection.execute(_SELECT_CANDIDATES).mappings().all()

    candidates = [
        row for row in rows
        if len(_parse_word_list(row["important_words"])) > 1
    ]
    candidate_count = len(candidates)
    processed_count = 0
    error_count = 0
    consecutive_errors = 0
    report(
        total_count=total_count,
        candidate_count=candidate_count,
        processed_count=processed_count,
        error_count=error_count,
        message=f"Подходящих товаров: {candidate_count} из {total_count}.",
    )
    print(
        f"[VILMED_PRODUCT_DESC_SELECT_WORDS][START][INFO] "
        f"Подходящих товаров: {candidate_count} из {total_count}.",
        flush=True,
    )

    for index, row in enumerate(candidates, start=1):
        if cancellation.is_set():
            break
        row_id = row["row_id"]
        processed_count += 1
        print(
            f"[VILMED_PRODUCT_DESC_SELECT_WORDS][PRODUCT][START] "
            f"Товар {index}/{candidate_count}; row_id={row_id}.",
            flush=True,
        )
        try:
            words = _parse_word_list(row["important_words"])
            product_name = row["product_name"]
            if len(words) <= 1 or not isinstance(product_name, str) or not product_name.strip():
                raise ValueError("Недостаточно данных товара для подстановки в prompt.")
            prompt = render_prompt_template(
                template,
                {"product_name": product_name.strip(), "words_list": ", ".join(words)},
            )
            selected_words: list[str] | None = None
            last_attempt_error: Exception | None = None
            successful_attempt = 0
            for attempt in range(1, MAX_ATTEMPTS_PER_PRODUCT + 1):
                try:
                    response = completion_runner(
                        [{"role": "user", "content": prompt}],
                        temperature=0.1,
                        max_tokens=10000,
                        reasoning_enabled=False,
                    )
                    choices = response.get("choices")
                    answer = choices[0].get("message", {}).get("content") if choices else None
                    selected_words = _validate_answer(answer, len(words))
                    successful_attempt = attempt
                    print(
                        f"[VILMED_PRODUCT_DESC_SELECT_WORDS][ATTEMPT][SUCCESS] "
                        f"row_id={row_id}; попытка {attempt}/{MAX_ATTEMPTS_PER_PRODUCT}.",
                        flush=True,
                    )
                    break
                except Exception as attempt_error:
                    last_attempt_error = attempt_error
                    print(
                        f"[VILMED_PRODUCT_DESC_SELECT_WORDS][ATTEMPT][FAILURE] "
                        f"row_id={row_id}; попытка {attempt}/{MAX_ATTEMPTS_PER_PRODUCT}; "
                        f"ошибка: {type(attempt_error).__name__}.",
                        flush=True,
                    )
            if selected_words is None:
                raise last_attempt_error or ValueError("Не удалось получить валидный список слов.")
            with engine.begin() as connection:
                connection.execute(
                    text(
                        f"UPDATE {TABLE_NAME} SET select_imp_words = :selected_words "
                        "WHERE row_id = :row_id"
                    ),
                    {
                        "selected_words": json.dumps(selected_words, ensure_ascii=False),
                        "row_id": row_id,
                    },
                )
            consecutive_errors = 0
            outcome = "SUCCESS"
            print(
                f"[VILMED_PRODUCT_DESC_SELECT_WORDS][PRODUCT][SUCCESS] "
                f"Товар {index}/{candidate_count}; row_id={row_id}; "
                f"попытка: {successful_attempt}/{MAX_ATTEMPTS_PER_PRODUCT}; "
                f"отобрано слов: {len(selected_words)}.",
                flush=True,
            )
        except Exception as error:
            error_count += 1
            consecutive_errors += 1
            outcome = "FAILURE"
            print(
                f"[VILMED_PRODUCT_DESC_SELECT_WORDS][PRODUCT][FAILURE] "
                f"Товар {index}/{candidate_count}; row_id={row_id}; "
                f"ошибка: {type(error).__name__}; подряд: {consecutive_errors}.",
                flush=True,
            )

        report(
            total_count=total_count,
            candidate_count=candidate_count,
            processed_count=processed_count,
            error_count=error_count,
            message=f"Обработано {processed_count}/{candidate_count}; ошибок: {error_count}.",
        )
        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            cancellation.set()
            print(
                f"[VILMED_PRODUCT_DESC_SELECT_WORDS][STOP][FAILURE] "
                f"Остановка после {consecutive_errors} последовательных ошибок.",
                flush=True,
            )
            break
        if index < candidate_count and cancellation.wait(delay_seconds):
            break

    was_stopped = cancellation.is_set()
    final_status = "stopped" if was_stopped or consecutive_errors >= MAX_CONSECUTIVE_ERRORS else "completed"
    print(
        f"[VILMED_PRODUCT_DESC_SELECT_WORDS][FINISH][{'STOPPED' if final_status == 'stopped' else 'SUCCESS'}] "
        f"Обработано: {processed_count}; ошибок: {error_count}; всего подходящих: {candidate_count}.",
        flush=True,
    )
    return {
        "status": final_status,
        "total_count": total_count,
        "candidate_count": candidate_count,
        "processed_count": processed_count,
        "error_count": error_count,
    }


__all__ = ["run_vilmed_product_desc_select_words"]
