"""Общий запуск XMLRiver-модулей для интерфейса и кодовых сценариев."""

from __future__ import annotations

from typing import Any, Literal, Sequence

from config.config import XMLRIVER_KEY, XMLRIVER_USER
from modules.xmlriver.registry import get_module
from modules.xmlriver.settings import SEARCH_SETTINGS, SETTINGS


class XMLRiverConfigurationError(RuntimeError):
    """Секреты интеграции не настроены в окружении приложения."""


def run_module(
    module_id: str,
    phrases: Sequence[str],
    *,
    top_n: int = 10,
    frequency_mode: Literal["base", "both", "phrasal"] = "base",
) -> list[dict[str, Any]]:
    """Валидирует параметры запуска и вызывает выбранный модуль.

    Функция не привязана к HTTP: будущие Python-сценарии смогут вызывать её
    напрямую, а веб-маршрут запускает её в отдельном потоке.
    """
    spec = get_module(module_id)
    if not phrases or any(not isinstance(phrase, str) or not phrase.strip() for phrase in phrases):
        raise ValueError("Список фраз должен содержать только непустые строки.")
    if not XMLRIVER_USER or not XMLRIVER_KEY:
        raise XMLRiverConfigurationError("Не настроены учётные данные XMLRiver в окружении приложения.")

    if module_id != "frequency" and frequency_mode != "base":
        raise ValueError("Режим частотности доступен только для модуля frequency.")
    settings = SEARCH_SETTINGS if module_id == "serp" else SETTINGS
    arguments: dict[str, Any] = {
        "user_id": XMLRIVER_USER,
        "api_key": XMLRIVER_KEY,
        "settings": dict(settings),
    }
    if module_id == "frequency" and frequency_mode != "base":
        arguments["mode"] = frequency_mode
    if module_id == "serp":
        if top_n not in {10, 20, 30}:
            raise ValueError("Количество результатов должно быть 10, 20 или 30.")
        arguments["top_n"] = top_n

    print(f"[XMLRIVER][{module_id.upper()}][START] Запуск для {len(phrases)} фраз.", flush=True)
    results = spec.function(phrases, **arguments)
    print(f"[XMLRIVER][{module_id.upper()}][SUCCESS] Получено результатов: {len(results)}.", flush=True)
    return results
