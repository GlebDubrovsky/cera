"""Сбор URL поисковой выдачи для строк Vilmed без описания и результатов поиска.

Сценарий выбирает товары с пустым ``description``, непустым ``keyword`` и
пустыми JSONB-полями обоих провайдеров. До десяти независимых товаров можно
обрабатывать одновременно. Для каждого выполняется до пяти попыток Yandex;
Google вызывается один раз только если все попытки Yandex завершились неудачей.
"""

from __future__ import annotations

import contextvars
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
import threading
import time
from typing import Any, Callable

from sqlalchemy import JSON, Engine, bindparam, text

from modules.xmlriver.service import run_module

TABLE_NAME = "vilmed_description_products"
MAX_WORKERS = 10
ERRORS_PER_WORKER = 5

_COUNT_TOTAL = text(f"SELECT COUNT(*) FROM {TABLE_NAME}")
_SELECT_CANDIDATES = text(
    f"SELECT row_id, keyword FROM {TABLE_NAME} "
    "WHERE COALESCE(TRIM(description), '') = '' "
    "AND COALESCE(TRIM(keyword), '') <> '' "
    "AND comp_yandex IS NULL AND comp_google IS NULL "
    "ORDER BY row_id"
)


def _extract_urls(value: Any) -> list[str] | None:
    """Извлекает URL из корректного ответа; ``None`` означает ошибку модуля."""
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
    worker_count: int = 1,
    *,
    stop_event: threading.Event | None = None,
    progress_callback: Callable[..., None] | None = None,
    search_runner: Callable[..., list[dict[str, Any]]] = run_module,
    top_n: int = 20,
    request_delay_seconds: float = 1.5,
) -> dict[str, int | str]:
    """Параллельно собирает SERP и сохраняет URL в столбцы провайдеров.

    Выборка и запись БД остаются в управляющем потоке: worker-потоки выполняют
    только независимые вызовы API. При ``worker_count`` потоках порог остановки
    равен пяти ошибочным товарам подряд на поток, чтобы уже отправленные
    параллельные запросы не приводили к преждевременной остановке.
    """
    if not 1 <= worker_count <= MAX_WORKERS:
        raise ValueError(f"Количество потоков должно быть от 1 до {MAX_WORKERS}.")

    cancellation = stop_event or threading.Event()
    report = progress_callback or (lambda **_: None)
    error_limit = ERRORS_PER_WORKER * worker_count
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
        message=(
            "Подходящих товаров нет"
            if candidate_count == 0
            else f"Подготовлена очередь; потоков: {worker_count}, порог ошибок: {error_limit}"
        ),
    )
    print(
        f"[VILMED_DESCRIPTIONS][START][INFO] Подходящих товаров: {candidate_count} из {total_count}; "
        f"потоков: {worker_count}; порог ошибок подряд: {error_limit}.",
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

    def search_candidate(candidate_index: int, candidate: Any) -> tuple[Any, dict[str, list[str]], bool]:
        """Ищет URL для одного товара; возвращает результаты и флаг прерывания."""
        row_id = candidate["row_id"]
        keyword = candidate["keyword"].strip()
        results: dict[str, list[str]] = {}
        last_request_at: float | None = None

        # Google — резервный источник: сначала полностью исчерпываем пять попыток Yandex.
        for module_id, column_name, max_attempts in (
            ("serp", "comp_yandex", 5),
            ("google_serp", "comp_google", 1),
        ):
            for attempt in range(1, max_attempts + 1):
                if cancellation.is_set():
                    return row_id, results, True
                if last_request_at is not None:
                    remaining_delay = max(
                        0.0, request_delay_seconds - (time.monotonic() - last_request_at)
                    )
                    if cancellation.wait(remaining_delay):
                        return row_id, results, True

                print(
                    f"[VILMED_DESCRIPTIONS][SEARCH][START] Товар {candidate_index}/{candidate_count}: "
                    f"{module_id}, попытка {attempt}/{max_attempts}.",
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
                        f"[VILMED_DESCRIPTIONS][SEARCH][SUCCESS] Товар {candidate_index}/{candidate_count}: "
                        f"{module_id}, попытка {attempt}/{max_attempts}, URL: {len(urls)}.",
                        flush=True,
                    )
                    break
                print(
                    f"[VILMED_DESCRIPTIONS][SEARCH][FAILURE] Товар {candidate_index}/{candidate_count}: "
                    f"{module_id}, попытка {attempt}/{max_attempts}, {failure_detail}.",
                    flush=True,
                )

            if results:
                break
        return row_id, results, False

    breaker_reached = False
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="vilmed-serp") as executor:
        for batch_start in range(0, candidate_count, worker_count):
            if cancellation.is_set():
                break
            batch = candidates[batch_start : batch_start + worker_count]
            futures = {}
            for offset, candidate in enumerate(batch):
                worker_context = contextvars.copy_context()
                future = executor.submit(
                    worker_context.run,
                    search_candidate,
                    batch_start + offset + 1,
                    candidate,
                )
                futures[future] = candidate

            for future in as_completed(futures):
                try:
                    row_id, results, interrupted = future.result()
                except CancelledError:
                    continue
                if interrupted:
                    continue

                if results:
                    assignments = ", ".join(f"{column} = :{column}" for column in results)
                    statement = text(f"UPDATE {TABLE_NAME} SET {assignments} WHERE row_id = :row_id")
                    for column in results:
                        statement = statement.bindparams(bindparam(column, type_=JSON))
                    with engine.begin() as connection:
                        connection.execute(statement, {"row_id": row_id, **results})

                processed_count += 1
                if results:
                    consecutive_error_count = 0
                    outcome = "SUCCESS"
                else:
                    consecutive_error_count += 1
                    outcome = "FAILURE"

                reached_error_limit = consecutive_error_count >= error_limit
                message = (
                    f"Обработано {processed_count} из {candidate_count}; "
                    f"ошибок подряд: {consecutive_error_count} из {error_limit}; потоков: {worker_count}"
                )
                if reached_error_limit:
                    breaker_reached = True
                    message = f"Остановлено: {error_limit} строк подряд без успешного ответа от Yandex и Google"
                    cancellation.set()
                    for pending in futures:
                        if pending is not future:
                            pending.cancel()
                report(
                    total_count=total_count,
                    candidate_count=candidate_count,
                    processed_count=processed_count,
                    error_count=consecutive_error_count,
                    message=message,
                )
                print(
                    f"[VILMED_DESCRIPTIONS][PRODUCT][{outcome}] Обработано {processed_count}/{candidate_count}; "
                    f"ошибок подряд: {consecutive_error_count}/{error_limit}.",
                    flush=True,
                )
                if reached_error_limit:
                    print(
                        f"[VILMED_DESCRIPTIONS][CIRCUIT_BREAKER][STOPPED] "
                        f"{error_limit} строк подряд завершились без ответа от обоих провайдеров.",
                        flush=True,
                    )

            if cancellation.is_set():
                break

    final_status = "stopped" if cancellation.is_set() else "completed"
    print(
        f"[VILMED_DESCRIPTIONS][FINISH][{'STOPPED' if final_status == 'stopped' else 'SUCCESS'}] "
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
