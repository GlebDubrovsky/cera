"""Сбор URL поисковой выдачи для строк Vilmed без описания и результатов поиска.

Публичная точка входа ``run_product_descriptions`` выбирает товары с пустым
``description``, непустым ``keyword`` и пустыми JSONB-полями обоих провайдеров.
Для каждого товара сначала выполняется поиск Yandex; Google используется только
при ошибке Yandex. При пяти строках подряд без успешного ответа обоих провайдеров
сценарий останавливается. В таблицу сохраняются только URL органических результатов.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from sqlalchemy import JSON, Engine, bindparam, text

from modules.xmlriver.service import run_module

TABLE_NAME = "vilmed_description_products"

_COUNT_TOTAL = text(f"SELECT COUNT(*) FROM {TABLE_NAME}")
_SELECT_CANDIDATES = text(
    f"SELECT row_id, keyword FROM {TABLE_NAME} "
    "WHERE COALESCE(TRIM(description), '') = '' "
    "AND COALESCE(TRIM(keyword), '') <> '' "
    "AND comp_yandex IS NULL AND comp_google IS NULL "
    "ORDER BY row_id"
)


def _extract_urls(value: Any) -> list[str] | None:
    """Возвращает URL из успешного ответа; ``None`` означает ошибку модуля."""
    if (
        not isinstance(value, list)
        or len(value) != 1
        or not isinstance(value[0], dict)
        or value[0].get("error")
    ):
        return None

    results = value[0].get("results")
    if not isinstance(results, list):
        return None
    return [
        result["url"].strip()
        for result in results
        if isinstance(result, dict)
        and isinstance(result.get("url"), str)
        and result["url"].strip()
    ]


def run_product_descriptions(
    engine: Engine,
    *,
    stop_event: threading.Event | None = None,
    progress_callback: Callable[..., None] | None = None,
    search_runner: Callable[..., list[dict[str, Any]]] = run_module,
    top_n: int = 20,
    request_delay_seconds: float = 1.5,
) -> dict[str, int | str]:
    """Сохраняет URL выдачи и переключает провайдера при ошибке Yandex.

    Этапы: выбрать строки с пустыми description и обоими SERP-полями; запросить
    Yandex, а Google — только при ошибке; сохранять URL и обновлять прогресс.
    Счётчик ошибок отражает только подряд идущие строки без успешного ответа.
    После пяти таких строк сценарий прекращает запросы к предположительно
    недоступному сервису; пауза между вызовами снижает вероятность ограничений API.
    """
    cancellation = stop_event or threading.Event()
    report = progress_callback or (lambda **_: None)
    with engine.connect() as connection:
        total_count = int(connection.execute(_COUNT_TOTAL).scalar_one())
        candidates = connection.execute(_SELECT_CANDIDATES).mappings().all()

    candidate_count = len(candidates)
    processed_count = 0
    consecutive_error_count = 0
    report(
        total_count=total_count,
        candidate_count=candidate_count,
        processed_count=processed_count,
        error_count=consecutive_error_count,
        message="Подходящих товаров нет" if candidate_count == 0 else "Получен список товаров для обработки",
    )
    print(
        f"[VILMED_DESCRIPTIONS][START][INFO] Подходящих товаров: {candidate_count} из {total_count}.",
        flush=True,
    )

    if candidate_count == 0:
        print("[VILMED_DESCRIPTIONS][FINISH][SUCCESS] Обработка не требуется.", flush=True)
        return {
            "status": "no_candidates",
            "total_count": total_count,
            "candidate_count": 0,
            "processed_count": 0,
            "error_count": 0,
        }

    last_request_at: float | None = None
    for candidate_index, candidate in enumerate(candidates, start=1):
        if cancellation.is_set():
            break

        row_id = candidate["row_id"]
        keyword = candidate["keyword"].strip()
        results: dict[str, list[str]] = {}
        interrupted = False

        # Yandex is primary; Google runs only if that request fails or its response is invalid.
        for module_id, column_name in (("serp", "comp_yandex"), ("google_serp", "comp_google")):
            if last_request_at is not None:
                remaining_delay = max(
                    0.0, request_delay_seconds - (time.monotonic() - last_request_at)
                )
                if cancellation.wait(remaining_delay):
                    interrupted = True
                    break
            if cancellation.is_set():
                interrupted = True
                break

            print(
                f"[VILMED_DESCRIPTIONS][SEARCH][START] Товар {candidate_index}/{candidate_count}: {module_id}.",
                flush=True,
            )
            try:
                module_results = search_runner(module_id, [keyword], top_n=top_n)
            except Exception as error:
                urls = None
                failure_detail = type(error).__name__
            else:
                urls = _extract_urls(module_results)
                failure_detail = "некорректный ответ" if urls is None else ""
            last_request_at = time.monotonic()

            if urls is not None:
                results[column_name] = urls
                print(
                    f"[VILMED_DESCRIPTIONS][SEARCH][SUCCESS] Товар {candidate_index}/{candidate_count}: {module_id}, URL: {len(urls)}.",
                    flush=True,
                )
                break

            print(
                f"[VILMED_DESCRIPTIONS][SEARCH][FAILURE] Товар {candidate_index}/{candidate_count}: {module_id}, {failure_detail}.",
                flush=True,
            )

        if interrupted:
            break

        if results:
            assignments = ", ".join(f"{column} = :{column}" for column in results)
            statement = text(
                f"UPDATE {TABLE_NAME} SET {assignments} WHERE row_id = :row_id"
            )
            for column in results:
                statement = statement.bindparams(bindparam(column, type_=JSON))
            update_values: dict[str, Any] = {"row_id": row_id, **results}
            with engine.begin() as connection:
                connection.execute(statement, update_values)

        processed_count += 1
        if results:
            consecutive_error_count = 0
            outcome = "SUCCESS"
        else:
            consecutive_error_count += 1
            outcome = "FAILURE"

        message = (
            f"Обработано {processed_count} из {candidate_count}; "
            f"ошибок подряд: {consecutive_error_count}"
        )
        reached_error_limit = consecutive_error_count >= 5
        if reached_error_limit:
            message = "Остановлено: 5 строк подряд без успешного ответа от Yandex и Google"
        report(
            total_count=total_count,
            candidate_count=candidate_count,
            processed_count=processed_count,
            error_count=consecutive_error_count,
            message=message,
        )
        print(
            f"[VILMED_DESCRIPTIONS][PRODUCT][{outcome}] Товар {candidate_index}/{candidate_count}; "
            f"ошибок подряд: {consecutive_error_count}.",
            flush=True,
        )
        if reached_error_limit:
            print(
                "[VILMED_DESCRIPTIONS][CIRCUIT_BREAKER][STOPPED] "
                "Пять строк подряд завершились без ответа от обоих провайдеров.",
                flush=True,
            )
            cancellation.set()
            break

    final_status = "stopped" if cancellation.is_set() else "completed"
    print(
        f"[VILMED_DESCRIPTIONS][FINISH][{('STOPPED' if final_status == 'stopped' else 'SUCCESS')}] "
        f"Обработано: {processed_count}; ошибок подряд: {consecutive_error_count}; "
        f"всего подходящих: {candidate_count}.",
        flush=True,
    )
    return {
        "status": final_status,
        "total_count": total_count,
        "candidate_count": candidate_count,
        "processed_count": processed_count,
        "error_count": consecutive_error_count,
    }
