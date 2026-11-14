"""Расчёт метрик релевантности для товаров из таблицы Vilmed.

Публичная точка входа ``run_product_description_relevance`` выбирает строки
без description и important_words, где есть хотя бы один SERP-список. Для каждой
строки исключает сайты-агрегаторы, запускает анализатор на URL товара и сохраняет
метрики целевой страницы и слова, отсутствующие на ней, но встречающиеся у конкурентов.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from sqlalchemy import Engine, text

from config.config import RELEVANCE_AGGREGATOR_DOMAINS, RELEVANCE_EXCLUDED_WORDS
from modules.relevance_analyzer import run_analysis

TABLE_NAME = "vilmed_description_products"

_COUNT_TOTAL = text(f"SELECT COUNT(*) FROM {TABLE_NAME}")
_SELECT_CANDIDATES = text(
    f"SELECT row_id, url, keyword, comp_yandex, comp_google FROM {TABLE_NAME} "
    "WHERE COALESCE(TRIM(description), '') = '' "
    "AND COALESCE(TRIM(important_words), '') = '' "
    "AND (comp_yandex IS NOT NULL OR comp_google IS NOT NULL) "
    "ORDER BY row_id"
)


def _parse_url_list(value: Any) -> list[str]:
    """Читает сохранённый JSON-список URL из JSON/JSONB или текстовой колонки."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(value, (list, tuple)):
        return []

    urls: list[str] = []
    for item in value:
        candidate = item.get("url") if isinstance(item, dict) else item
        if isinstance(candidate, str) and candidate.strip():
            urls.append(candidate.strip())
    return urls


def _host(value: str) -> str:
    """Нормализует hostname для проверки домена, не учитывая www и регистр."""
    parsed = urlparse(value)
    hostname = parsed.hostname or urlparse(f"//{value}").hostname or ""
    hostname = hostname.lower().rstrip(".")
    return hostname[4:] if hostname.startswith("www.") else hostname


_AGGREGATOR_HOSTS = {_host(domain) for domain in RELEVANCE_AGGREGATOR_DOMAINS}


def _is_aggregator(url: str) -> bool:
    hostname = _host(url)
    return any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in _AGGREGATOR_HOSTS
    )


def _competitors(row: Mapping[str, Any], target_url: str) -> list[str]:
    """Выбирает первую пригодную выдачу, убирая агрегаторы и дубликаты."""
    target = target_url.strip().rstrip("/").lower()
    for field in ("comp_yandex", "comp_google"):
        urls = _parse_url_list(row[field])
        cleaned: list[str] = []
        seen: set[str] = set()
        for url in urls:
            normalized = url.rstrip("/").lower()
            if not _is_aggregator(url) and normalized != target and normalized not in seen:
                cleaned.append(url)
                seen.add(normalized)
        if cleaned:
            return cleaned
    return []


def _important_words(result: Any) -> list[str]:
    """Выбирает одну форму на группу по агрегатным показателям анализатора."""
    words: list[str] = []
    for representative, word_forms in result.word_forms.items():
        totals = word_forms.get("total", {})
        # В TLP столбец «Пересечение» начинается с числа доменов; здесь
        # используем его исходное числовое поле, а не экспортную строку с доменами.
        overlap_count = totals.get("number_occurrences", 0)
        if (
            overlap_count >= 3
            and totals.get("avg_in_total_competitors", 0) >= 1
            and totals.get("total_repeat_main_page", 0) == 0
        ):
            words.append(representative)
    return words


def _target_metrics(result: Any) -> tuple[float, float, float]:
    target_page = next(
        (page for page in result.sites.values() if page.get("main_page")),
        None,
    )
    if target_page is None:
        raise ValueError("Результат анализа не содержит целевую страницу.")
    density = target_page.get("density")
    if not isinstance(density, dict):
        raise ValueError("Результат анализа не содержит показатель плотности.")
    return (
        float(target_page["main_points"]),
        float(target_page["coverage"]),
        float(density["density_main_percent"]),
    )


def run_product_description_relevance(
    engine: Engine,
    *,
    stop_event: threading.Event | None = None,
    progress_callback: Callable[..., None] | None = None,
    analysis_runner: Callable[[Mapping[str, Any]], Any] = run_analysis,
) -> dict[str, int | str]:
    """Анализирует подходящие товары и записывает метрики в ту же строку.

    Сценарий использует URL и keyword товара, выбранные SERP-конкуренты и список
    исключений из общей конфигурации. Ошибка отдельной строки журналируется и не
    прерывает пакет; остановка проверяется между товарами, так как сам анализ
    выполняет синхронные сетевые загрузки страниц.
    """
    cancellation = stop_event or threading.Event()
    report = progress_callback or (lambda **_: None)
    with engine.connect() as connection:
        total_count = int(connection.execute(_COUNT_TOTAL).scalar_one())
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
        message="Подходящих товаров нет" if not candidate_count else "Получен список товаров для анализа",
    )
    print(
        f"[VILMED_PRODUCT_DESC_RELEVANCE][START][INFO] Подходящих товаров: {candidate_count} из {total_count}.",
        flush=True,
    )

    if not candidate_count:
        print("[VILMED_PRODUCT_DESC_RELEVANCE][FINISH][SUCCESS] Анализ не требуется.", flush=True)
        return {
            "status": "no_candidates",
            "total_count": total_count,
            "candidate_count": 0,
            "processed_count": 0,
            "error_count": 0,
        }

    for candidate_index, row in enumerate(candidates, start=1):
        if cancellation.is_set():
            break

        processed_count += 1
        row_id = row["row_id"]
        print(
            f"[VILMED_PRODUCT_DESC_RELEVANCE][PRODUCT][START] Товар {candidate_index}/{candidate_count}; "
            f"row_id={row_id}.",
            flush=True,
        )
        try:
            target_url = row["url"].strip() if isinstance(row["url"], str) else ""
            keyword = row["keyword"].strip() if isinstance(row["keyword"], str) else ""
            competitors = _competitors(row, target_url)
            if not target_url or not keyword or not competitors:
                raise ValueError("Недостаточно URL или сайтов-конкурентов после фильтрации.")

            print(
                f"[VILMED_PRODUCT_DESC_RELEVANCE][ANALYSIS][START] Товар {candidate_index}/{candidate_count}; "
                f"row_id={row_id}.",
                flush=True,
            )
            result = analysis_runner({
                "link": target_url,
                "phrase": keyword,
                "sites": competitors,
                "list_words": RELEVANCE_EXCLUDED_WORDS,
            })
            score, reach, density = _target_metrics(result)
            important_words = _important_words(result)
            update_fields = (
                "score_before = :score, reach_before = :reach, density_before = :density"
            )
            parameters: dict[str, Any] = {
                "score": score,
                "reach": reach,
                "density": density,
                "row_id": row_id,
            }
            # An empty selection is not a completed result: keep important_words
            # blank so later scenarios do not mistake it for analyzed data.
            if important_words:
                update_fields += ", important_words = :important_words"
                parameters["important_words"] = json.dumps(
                    important_words, ensure_ascii=False
                )
            with engine.begin() as connection:
                connection.execute(
                    text(
                        f"UPDATE {TABLE_NAME} SET {update_fields} WHERE row_id = :row_id"
                    ),
                    parameters,
                )
            outcome = "SUCCESS"
            print(
                f"[VILMED_PRODUCT_DESC_RELEVANCE][ANALYSIS][SUCCESS] Товар {candidate_index}/{candidate_count}; "
                f"row_id={row_id}; важных слов: {len(important_words)}.",
                flush=True,
            )
        except Exception as error:
            error_count += 1
            outcome = "FAILURE"
            print(
                f"[VILMED_PRODUCT_DESC_RELEVANCE][ANALYSIS][FAILURE] Товар {candidate_index}/{candidate_count}; "
                f"row_id={row_id}; ошибка: {type(error).__name__}.",
                flush=True,
            )

        report(
            total_count=total_count,
            candidate_count=candidate_count,
            processed_count=processed_count,
            error_count=error_count,
            message=(
                f"Обработано {processed_count} из {candidate_count}; ошибок: {error_count}"
            ),
        )
        print(
            f"[VILMED_PRODUCT_DESC_RELEVANCE][PRODUCT][{outcome}] "
            f"Обработано {processed_count}/{candidate_count}; row_id={row_id}; "
            f"ошибок: {error_count}.",
            flush=True,
        )

    final_status = "stopped" if cancellation.is_set() else "completed"
    print(
        f"[VILMED_PRODUCT_DESC_RELEVANCE][FINISH][{'STOPPED' if final_status == 'stopped' else 'SUCCESS'}] "
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
