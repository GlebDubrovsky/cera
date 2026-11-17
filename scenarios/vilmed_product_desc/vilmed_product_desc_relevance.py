"""Расчёт метрик релевантности для товаров из таблицы Vilmed.

Публичная точка входа обрабатывает подходящие товары до пяти параллельными
потоками. Запросы к сайтам выполняются в workers, а обновление БД и прогресс
сериализованы в управляющем потоке.
"""
from __future__ import annotations

import contextvars
import json
import threading
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from sqlalchemy import Engine, text

from config.config import RELEVANCE_AGGREGATOR_DOMAINS, RELEVANCE_EXCLUDED_WORDS
from modules.relevance_analyzer import run_analysis

TABLE_NAME = "vilmed_description_products"
MAX_WORKERS = 5
_COUNT_TOTAL = text(f"SELECT COUNT(*) FROM {TABLE_NAME}")
_SELECT_CANDIDATES = text(
    f"SELECT row_id, url, keyword, comp_yandex, comp_google FROM {TABLE_NAME} "
    "WHERE COALESCE(TRIM(description), '') = '' "
    "AND COALESCE(TRIM(important_words), '') = '' "
    "AND (comp_yandex IS NOT NULL OR comp_google IS NOT NULL) ORDER BY row_id"
)


def _parse_url_list(value: Any) -> list[str]:
    """Читает сохранённый JSON-список URL из JSON/JSONB или текста."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(value, (list, tuple)):
        return []
    urls = []
    for item in value:
        candidate = item.get("url") if isinstance(item, dict) else item
        if isinstance(candidate, str) and candidate.strip():
            urls.append(candidate.strip())
    return urls


def _host(value: str) -> str:
    parsed = urlparse(value)
    hostname = (parsed.hostname or urlparse(f"//{value}").hostname or "").lower().rstrip(".")
    return hostname[4:] if hostname.startswith("www.") else hostname


_AGGREGATOR_HOSTS = {_host(domain) for domain in RELEVANCE_AGGREGATOR_DOMAINS}


def _is_aggregator(url: str) -> bool:
    hostname = _host(url)
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in _AGGREGATOR_HOSTS)


def _competitors(row: Mapping[str, Any], target_url: str) -> list[str]:
    """Выбирает первую пригодную выдачу, исключая агрегаторы и дубликаты."""
    target = target_url.strip().rstrip("/").lower()
    for field in ("comp_yandex", "comp_google"):
        cleaned, seen = [], set()
        for url in _parse_url_list(row[field]):
            normalized = url.rstrip("/").lower()
            if not _is_aggregator(url) and normalized != target and normalized not in seen:
                cleaned.append(url)
                seen.add(normalized)
        if cleaned:
            return cleaned
    return []


def _important_words(result: Any) -> list[str]:
    """Выбирает слова по показателям конкурентного покрытия анализатора."""
    return [
        representative
        for representative, forms in result.word_forms.items()
        if forms.get("total", {}).get("number_occurrences", 0) >= 3
        and forms.get("total", {}).get("avg_in_total_competitors", 0) >= 1
        and forms.get("total", {}).get("total_repeat_main_page", 0) == 0
    ]


def _target_metrics(result: Any) -> tuple[float, float, float]:
    target = next((page for page in result.sites.values() if page.get("main_page")), None)
    if target is None or not isinstance(target.get("density"), dict):
        raise ValueError("Результат анализа не содержит метрики целевой страницы.")
    return float(target["main_points"]), float(target["coverage"]), float(target["density"]["density_main_percent"])


def run_product_description_relevance(
    engine: Engine,
    worker_count: int = 1,
    *,
    stop_event: threading.Event | None = None,
    progress_callback: Callable[..., None] | None = None,
    analysis_runner: Callable[[Mapping[str, Any]], Any] = run_analysis,
) -> dict[str, int | str]:
    """Анализирует строки с SERP-URL параллельно и записывает рассчитанные метрики.

    Число workers ограничено пятью. Сетевая часть не использует соединение БД;
    запись каждого результата делается одним управляющим потоком, а остановка
    проверяется при запуске задач и между партиями уже запущенных анализов.
    """
    if not 1 <= worker_count <= MAX_WORKERS:
        raise ValueError(f"Количество потоков должно быть от 1 до {MAX_WORKERS}.")
    cancellation = stop_event or threading.Event()
    report = progress_callback or (lambda **_: None)
    with engine.connect() as connection:
        total_count = int(connection.execute(_COUNT_TOTAL).scalar_one())
        rows = connection.execute(_SELECT_CANDIDATES).mappings().all()
    candidates = [row for row in rows if _parse_url_list(row["comp_yandex"]) or _parse_url_list(row["comp_google"])]
    candidate_count, processed_count, error_count = len(candidates), 0, 0
    report(total_count=total_count, candidate_count=candidate_count, processed_count=0, error_count=0,
           message="Подходящих товаров нет" if not candidates else f"Потоков анализа: {worker_count}")
    print(f"[VILMED_PRODUCT_DESC_RELEVANCE][START][INFO] Подходящих товаров: {candidate_count} из {total_count}; потоков: {worker_count}.", flush=True)
    if not candidates:
        print("[VILMED_PRODUCT_DESC_RELEVANCE][FINISH][SUCCESS] Анализ не требуется.", flush=True)
        return {"status": "no_candidates", "total_count": total_count, "candidate_count": 0, "processed_count": 0, "error_count": 0}

    def analyze_candidate(index: int, row: Mapping[str, Any]) -> tuple[Any, dict[str, Any] | None, int, str | None, bool]:
        row_id = row["row_id"]
        if cancellation.is_set():
            return row_id, None, 0, None, True
        print(f"[VILMED_PRODUCT_DESC_RELEVANCE][PRODUCT][START] Товар {index}/{candidate_count}; row_id={row_id}.", flush=True)
        try:
            target_url = row["url"].strip() if isinstance(row["url"], str) else ""
            keyword = row["keyword"].strip() if isinstance(row["keyword"], str) else ""
            competitors = _competitors(row, target_url)
            if not target_url or not keyword or not competitors:
                raise ValueError("Недостаточно URL или сайтов-конкурентов после фильтрации.")
            print(f"[VILMED_PRODUCT_DESC_RELEVANCE][ANALYSIS][START] Товар {index}/{candidate_count}; row_id={row_id}.", flush=True)
            result = analysis_runner({"link": target_url, "phrase": keyword, "sites": competitors, "list_words": RELEVANCE_EXCLUDED_WORDS})
            score, reach, density = _target_metrics(result)
            important_words = _important_words(result)
            values: dict[str, Any] = {"score": score, "reach": reach, "density": density, "row_id": row_id}
            if important_words:
                values["important_words"] = json.dumps(important_words, ensure_ascii=False)
            return row_id, values, len(important_words), None, False
        except Exception as error:
            return row_id, None, 0, type(error).__name__, False

    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="vilmed-relevance") as executor:
        for batch_start in range(0, candidate_count, worker_count):
            if cancellation.is_set():
                break
            batch = candidates[batch_start:batch_start + worker_count]
            futures = {}
            for offset, row in enumerate(batch):
                context = contextvars.copy_context()
                future = executor.submit(context.run, analyze_candidate, batch_start + offset + 1, row)
                futures[future] = row
            for future in as_completed(futures):
                try:
                    row_id, values, word_count, failure, interrupted = future.result()
                except CancelledError:
                    continue
                if interrupted:
                    continue
                processed_count += 1
                outcome = "SUCCESS"
                if failure is None and values is not None:
                    assignments = "score_before = :score, reach_before = :reach, density_before = :density"
                    if "important_words" in values:
                        assignments += ", important_words = :important_words"
                    try:
                        with engine.begin() as connection:
                            connection.execute(text(f"UPDATE {TABLE_NAME} SET {assignments} WHERE row_id = :row_id"), values)
                    except Exception as error:
                        failure = type(error).__name__
                if failure is not None:
                    error_count += 1
                    outcome = "FAILURE"
                    print(f"[VILMED_PRODUCT_DESC_RELEVANCE][ANALYSIS][FAILURE] row_id={row_id}; ошибка: {failure}.", flush=True)
                else:
                    print(f"[VILMED_PRODUCT_DESC_RELEVANCE][ANALYSIS][SUCCESS] row_id={row_id}; важных слов: {word_count}.", flush=True)
                report(total_count=total_count, candidate_count=candidate_count, processed_count=processed_count,
                       error_count=error_count, message=f"Обработано {processed_count} из {candidate_count}; ошибок: {error_count}; потоков: {worker_count}")
                print(f"[VILMED_PRODUCT_DESC_RELEVANCE][PRODUCT][{outcome}] Обработано {processed_count}/{candidate_count}; row_id={row_id}; ошибок: {error_count}.", flush=True)

    final_status = "stopped" if cancellation.is_set() else "completed"
    print(f"[VILMED_PRODUCT_DESC_RELEVANCE][FINISH][{'STOPPED' if final_status == 'stopped' else 'SUCCESS'}] Обработано: {processed_count}; ошибок: {error_count}; всего подходящих: {candidate_count}.", flush=True)
    return {"status": final_status, "total_count": total_count, "candidate_count": candidate_count, "processed_count": processed_count, "error_count": error_count}
