"""Генерация HTML-описаний товаров Vilmed через OpenAI-совместимый API.

Публичный сценарий обрабатывает строки со списком выбранных слов и статусом
``missing``, проверяет HTML-ответ и сохраняет его в существующее поле ``html_desc``.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy import Engine, text

from modules.openai_api import chat_completion
from shared.prompt_templates import load_prompt_template, render_prompt_template

TABLE_NAME = "vilmed_description_products"
PROMPT_TEMPLATE_NAME = "prmpt_for_product_vilmed_1.md"
MAX_ATTEMPTS_PER_PRODUCT = 3
MAX_CONSECUTIVE_ERRORS = 5
ITERATION_DELAY_SECONDS = 1.0

_COUNT_TOTAL = text(f"SELECT COUNT(*) FROM {TABLE_NAME}")
_SELECT_CANDIDATES = text(
    f"SELECT row_id, url, product_name, package, specifications, select_imp_words "
    f"FROM {TABLE_NAME} WHERE COALESCE(TRIM(select_imp_words), '') <> '' "
    "AND desc_status = 'missing' ORDER BY row_id"
)


def _parse_words(value: Any) -> list[str]:
    """Проверяет сохранённый JSON-массив выбранных слов."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    words = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return words if len(words) == len(value) else []


def _render_product_prompt(template: str, row: Mapping[str, Any], words: list[str]) -> str:
    """Подставляет обязательные данные и убирает заголовки отсутствующих полей."""
    package = row["package"] if isinstance(row["package"], str) else ""
    specifications = row["specifications"] if isinstance(row["specifications"], str) else ""
    rendered_template = template.replace(
        "{{Комплектация товара:}}",
        "Комплектация товара:" if package.strip() else "",
    ).replace(
        "{{Характеристики товара:}}",
        "Характеристики товара:" if specifications.strip() else "",
    )
    variables = {
        "link": row["url"].strip(),
        "name": row["product_name"].strip(),
        "configuration": package,
        "characteristic": specifications,
        "words_list": ", ".join(words),
    }
    return render_prompt_template(rendered_template, variables)


def _clean_html_answer(answer: Any) -> str:
    """Снимает внешнюю Markdown-обёртку и требует HTML-тег в ответе."""
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("Ответ модели пуст.")
    cleaned = answer.strip()
    fenced = re.fullmatch(r"```(?:html)?\s*\n?(.*?)\n?```", cleaned, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()
    if not cleaned.startswith("<") or not cleaned.endswith(">"):
        raise ValueError("Ответ не выглядит как HTML.")
    if not re.search(r"</?[A-Za-z][^<>]*>", cleaned):
        raise ValueError("В ответе не найден HTML-тег.")
    return cleaned


def run_vilmed_product_desc_get_html(
    engine: Engine,
    *,
    stop_event: threading.Event | None = None,
    progress_callback: Callable[..., None] | None = None,
    completion_runner: Callable[..., Mapping[str, Any]] = chat_completion,
    delay_seconds: float = ITERATION_DELAY_SECONDS,
) -> dict[str, int | str]:
    """Генерирует HTML для товаров со статусом ``missing`` и выбранными словами.

    Проверяются строки таблицы, затем для каждого товара выполняются до трёх
    запросов, пока ответ не окажется HTML. Ошибка товара увеличивает серию ошибок;
    после пяти ошибок подряд сценарий останавливается, а успех сбрасывает серию.
    """
    cancellation = stop_event or threading.Event()
    report = progress_callback or (lambda **_: None)
    template = load_prompt_template(PROMPT_TEMPLATE_NAME)
    with engine.connect() as connection:
        total_count = int(connection.execute(_COUNT_TOTAL).scalar_one())
        candidates = connection.execute(_SELECT_CANDIDATES).mappings().all()

    candidate_count = len(candidates)
    processed_count = 0
    error_count = 0
    consecutive_errors = 0
    report(
        total_count=total_count, candidate_count=candidate_count,
        processed_count=processed_count, error_count=error_count,
        message=f"Подходящих товаров: {candidate_count} из {total_count}.",
    )
    print(
        f"[VILMED_PRODUCT_DESC_GET_HTML][START][INFO] Подходящих товаров: {candidate_count} из {total_count}.",
        flush=True,
    )

    for index, row in enumerate(candidates, start=1):
        if cancellation.is_set():
            break
        row_id = row["row_id"]
        processed_count += 1
        print(
            f"[VILMED_PRODUCT_DESC_GET_HTML][PRODUCT][START] "
            f"Товар {index}/{candidate_count}; row_id={row_id}.", flush=True,
        )
        try:
            if not isinstance(row["url"], str) or not row["url"].strip():
                raise ValueError("Не задан URL товара.")
            if not isinstance(row["product_name"], str) or not row["product_name"].strip():
                raise ValueError("Не задано название товара.")
            words = _parse_words(row["select_imp_words"])
            if not words:
                raise ValueError("Список выбранных слов некорректен.")
            prompt = _render_product_prompt(template, row, words)
            html_desc: str | None = None
            last_error: Exception | None = None
            for attempt in range(1, MAX_ATTEMPTS_PER_PRODUCT + 1):
                try:
                    response = completion_runner(
                        [{"role": "user", "content": prompt}],
                        temperature=0.1,
                        max_tokens=15000,
                        reasoning_enabled=False,
                    )
                    choices = response.get("choices")
                    content = choices[0].get("message", {}).get("content") if choices else None
                    html_desc = _clean_html_answer(content)
                    print(
                        f"[VILMED_PRODUCT_DESC_GET_HTML][ATTEMPT][SUCCESS] "
                        f"row_id={row_id}; попытка {attempt}/{MAX_ATTEMPTS_PER_PRODUCT}.", flush=True,
                    )
                    break
                except Exception as attempt_error:
                    last_error = attempt_error
                    print(
                        f"[VILMED_PRODUCT_DESC_GET_HTML][ATTEMPT][FAILURE] "
                        f"row_id={row_id}; попытка {attempt}/{MAX_ATTEMPTS_PER_PRODUCT}; "
                        f"ошибка: {type(attempt_error).__name__}.", flush=True,
                    )
            if html_desc is None:
                raise last_error or ValueError("Не удалось получить HTML.")
            with engine.begin() as connection:
                connection.execute(
                    text(f"UPDATE {TABLE_NAME} SET html_desc = :html_desc WHERE row_id = :row_id"),
                    {"html_desc": html_desc, "row_id": row_id},
                )
            consecutive_errors = 0
            outcome = "SUCCESS"
            print(
                f"[VILMED_PRODUCT_DESC_GET_HTML][PRODUCT][SUCCESS] "
                f"Товар {index}/{candidate_count}; row_id={row_id}.", flush=True,
            )
        except Exception as error:
            error_count += 1
            consecutive_errors += 1
            outcome = "FAILURE"
            print(
                f"[VILMED_PRODUCT_DESC_GET_HTML][PRODUCT][FAILURE] "
                f"Товар {index}/{candidate_count}; row_id={row_id}; "
                f"ошибка: {type(error).__name__}; подряд: {consecutive_errors}.", flush=True,
            )

        report(
            total_count=total_count, candidate_count=candidate_count,
            processed_count=processed_count, error_count=error_count,
            message=f"Обработано {processed_count}/{candidate_count}; ошибок: {error_count}.",
        )
        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            cancellation.set()
            print(
                f"[VILMED_PRODUCT_DESC_GET_HTML][STOP][FAILURE] "
                f"Остановка после {consecutive_errors} последовательных ошибок.", flush=True,
            )
            break
        if index < candidate_count and cancellation.wait(delay_seconds):
            break

    final_status = "stopped" if cancellation.is_set() else "completed"
    print(
        f"[VILMED_PRODUCT_DESC_GET_HTML][FINISH][{'STOPPED' if final_status == 'stopped' else 'SUCCESS'}] "
        f"Обработано: {processed_count}; ошибок: {error_count}; всего подходящих: {candidate_count}.",
        flush=True,
    )
    return {
        "status": final_status, "total_count": total_count,
        "candidate_count": candidate_count, "processed_count": processed_count,
        "error_count": error_count,
    }


__all__ = ["run_vilmed_product_desc_get_html"]
