"""Повторный анализ релевантности после вставки описания Vilmed.

Обрабатывает строки со статусом ``inserted``, уже рассчитанным score_before
и пустым score_after. Результаты записываются только после успешного анализа
целевой страницы и конкурентов.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy import Engine, text

from config.config import RELEVANCE_EXCLUDED_WORDS
from modules.relevance_analyzer import run_analysis
from scenarios.vilmed_product_desc.vilmed_product_desc_relevance import (
    _competitors,
    _parse_url_list,
    _target_metrics,
)

TABLE_NAME = "vilmed_description_products"
_SELECT_TOTAL = text(f"SELECT COUNT(*) FROM {TABLE_NAME}")
_SELECT_CANDIDATES = text(
    f"SELECT row_id, url, keyword, comp_yandex, comp_google, score_before "
    f"FROM {TABLE_NAME} WHERE desc_status = 'inserted' "
    "AND score_before IS NOT NULL AND score_after IS NULL "
    "AND (comp_yandex IS NOT NULL OR comp_google IS NOT NULL) "
    "ORDER BY row_id"
)
_UPDATE_AFTER = text(
    f"UPDATE {TABLE_NAME} SET score_after = :score_after, "
    "reach_after = :reach_after, density_after = :density_after, "
    "score_delta = :score_delta "
    "WHERE row_id = :row_id AND score_after IS NULL"
)


def run_product_description_relevance_after(
    engine: Engine,
    *,
    stop_event: threading.Event | None = None,
    progress_callback: Callable[..., None] | None = None,
    analysis_runner: Callable[[Mapping[str, Any]], Any] = run_analysis,
) -> dict[str, int | str]:
    """Вычисляет after-метрики и дельту для завершённых вставок Vilmed.

    Для каждой строки используются URL товара и keyword, а сайты-конкуренты
    берутся из comp_yandex с fallback на comp_google после удаления агрегаторов.
    Остановка проверяется между товарами; ошибка одной строки не прерывает пакет.
    """
    cancellation = stop_event or threading.Event()
    report = progress_callback or (lambda **_: None)

    # Этап 1: отбираются только завершённые вставки с исходной метрикой и
    # отсутствующим результатом повторного анализа; лимит на пакет не задаётся.
    with engine.connect() as connection:
        total_count = int(connection.execute(_SELECT_TOTAL).scalar_one())
        rows = connection.execute(_SELECT_CANDIDATES).mappings().all()
    candidates = [
        row for row in rows
        if _parse_url_list(row["comp_yandex"]) or _parse_url_list(row["comp_google"])
    ]
    candidate_count = len(candidates)
    processed_count = 0
    error_count = 0
    report(
        total_count=total_count,
        candidate_count=candidate_count,
        processed_count=processed_count,
        error_count=error_count,
        message="Подходящих товаров нет" if not candidate_count else "Подготовлен список для повторного анализа",
    )
    print(
        f"[VILMED_PRODUCT_DESC_RELEVANCE_AFTER][START][INFO] "
        f"Подходящих товаров: {candidate_count} из {total_count}.",
        flush=True,
    )
    if not candidate_count:
        print(
            "[VILMED_PRODUCT_DESC_RELEVANCE_AFTER][FINISH][SUCCESS] Анализ не требуется.",
            flush=True,
        )
        return {
            "status": "no_candidates",
            "total_count": total_count,
            "candidate_count": 0,
            "processed_count": 0,
            "error_count": 0,
        }

    # Этап 2: каждый товар анализируется независимо; after-поля обновляются
    # одной транзакцией, чтобы не оставить частично записанный набор метрик.
    for candidate_index, row in enumerate(candidates, start=1):
        if cancellation.is_set():
            break
        processed_count += 1
        row_id = row["row_id"]
        outcome = "SUCCESS"
        print(
            f"[VILMED_PRODUCT_DESC_RELEVANCE_AFTER][PRODUCT][START] "
            f"Товар {candidate_index}/{candidate_count}; row_id={row_id}.",
            flush=True,
        )
        try:
            target_url = row["url"].strip() if isinstance(row["url"], str) else ""
            keyword = row["keyword"].strip() if isinstance(row["keyword"], str) else ""
            competitor_urls = _competitors(row, target_url)
            if not target_url or not keyword or not competitor_urls:
                raise ValueError("Недостаточно URL или сайтов-конкурентов после фильтрации.")

            result = analysis_runner({
                "link": target_url,
                "phrase": keyword,
                "sites": competitor_urls,
                "list_words": RELEVANCE_EXCLUDED_WORDS,
            })
            score_after, reach_after, density_after = _target_metrics(result)
            score_delta = score_after - float(row["score_before"])
            with engine.begin() as connection:
                update_result = connection.execute(_UPDATE_AFTER, {
                    "score_after": score_after,
                    "reach_after": reach_after,
                    "density_after": density_after,
                    "score_delta": score_delta,
                    "row_id": row_id,
                })
                if update_result.rowcount != 1:
                    raise RuntimeError("Строка уже обновлена или больше не соответствует выборке.")
            print(
                f"[VILMED_PRODUCT_DESC_RELEVANCE_AFTER][ANALYSIS][SUCCESS] "
                f"Товар {candidate_index}/{candidate_count}; row_id={row_id}; "
                f"score_delta={score_delta}.",
                flush=True,
            )
        except Exception as error:
            error_count += 1
            outcome = "FAILURE"
            print(
                f"[VILMED_PRODUCT_DESC_RELEVANCE_AFTER][ANALYSIS][FAILURE] "
                f"Товар {candidate_index}/{candidate_count}; row_id={row_id}; "
                f"ошибка: {type(error).__name__}.",
                flush=True,
            )

        report(
            total_count=total_count,
            candidate_count=candidate_count,
            processed_count=processed_count,
            error_count=error_count,
            message=f"Обработано {processed_count} из {candidate_count}; ошибок: {error_count}",
        )
        print(
            f"[VILMED_PRODUCT_DESC_RELEVANCE_AFTER][PRODUCT][{outcome}] "
            f"Обработано {processed_count}/{candidate_count}; row_id={row_id}; "
            f"ошибок: {error_count}.",
            flush=True,
        )

    final_status = "stopped" if cancellation.is_set() else "completed"
    print(
        f"[VILMED_PRODUCT_DESC_RELEVANCE_AFTER][FINISH]["
        f"{'STOPPED' if final_status == 'stopped' else 'SUCCESS'}] "
        f"Обработано: {processed_count}; ошибок: {error_count}; "
        f"всего подходящих: {candidate_count}.",
        flush=True,
    )
    return {
        "status": final_status,
        "total_count": total_count,
        "candidate_count": candidate_count,
        "processed_count": processed_count,
        "error_count": error_count,
    }
