"""Сбор популярных запросов из Яндекс Wordstat через XMLRiver."""

from __future__ import annotations

import json
import time
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_URL = "https://xmlriver.com/wordstat/new/json"
_TRANSIENT_CODES = {101, 110, 500}


class XMLRiverPopularError(RuntimeError):
    """Ошибка API XMLRiver или сетевого запроса популярных фраз."""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


def _extract_popular(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Извлекает список популярных фраз из поддерживаемых форматов ответа."""
    popular = response.get("popular")
    if isinstance(popular, list):
        return popular

    table = response.get("table")
    if isinstance(table, dict):
        table_data = table.get("tableData")
        if isinstance(table_data, dict):
            popular = table_data.get("popular")
            if isinstance(popular, list):
                return popular
    return []


def _request_popular(
    phrase: str,
    *,
    user_id: str,
    api_key: str,
    settings: Mapping[str, Any] | None,
    timeout: float,
    retries: int,
    retry_delay: float,
) -> dict[str, Any]:
    if not phrase or not phrase.strip():
        raise ValueError("Поисковая фраза не должна быть пустой.")
    if retries < 0:
        raise ValueError("Количество повторных попыток не может быть отрицательным.")

    params: dict[str, Any] = {
        "user": user_id,
        "key": api_key,
        "query": phrase.strip(),
        "pagetype": "words",
    }
    for name, value in (settings or {}).items():
        if name != "pagetype" and value is not None and value != "":
            params[name] = value

    request = Request(
        f"{API_URL}?{urlencode(params)}",
        headers={"Accept": "application/json", "User-Agent": "xmlriver-popular-client/1.0"},
        method="GET",
    )

    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise XMLRiverPopularError("XMLRiver вернул JSON в неожиданном формате.")
            if "error" in payload or "code" in payload:
                try:
                    code = int(payload.get("code"))
                except (TypeError, ValueError):
                    code = None
                message = str(payload.get("error", "Ошибка API XMLRiver."))
                if code in _TRANSIENT_CODES and attempt < retries:
                    time.sleep(retry_delay * (attempt + 1))
                    continue
                raise XMLRiverPopularError(message, code=code)
            return payload
        except HTTPError as error:
            if (error.code == 429 or error.code >= 500) and attempt < retries:
                time.sleep(retry_delay * (attempt + 1))
                continue
            raise XMLRiverPopularError(f"XMLRiver вернул HTTP-код {error.code}.") from None
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            if attempt < retries:
                time.sleep(retry_delay * (attempt + 1))
                continue
            raise XMLRiverPopularError(
                f"Ошибка запроса к XMLRiver ({type(error).__name__})."
            ) from None

    raise XMLRiverPopularError("Не удалось выполнить запрос к XMLRiver после повторных попыток.")


def fetch_popular_queries(
    phrases: Sequence[str],
    *,
    user_id: str,
    api_key: str,
    settings: Mapping[str, Any] | None = None,
    timeout: float = 30,
    retries: int = 2,
    retry_delay: float = 1,
) -> list[dict[str, Any]]:
    """Собирает популярные и похожие запросы отдельно для каждой фразы.

    Каждый элемент результата содержит исходную фразу, список ``popular``,
    полный JSON-ответ XMLRiver и поле ``error`` (пустое при успехе).
    """
    if not user_id or not api_key:
        raise ValueError("Не заданы user_id и api_key.")

    phrase_count = len(phrases)
    print(f"[XMLRIVER][POPULAR][START] Начат сбор фраз для {phrase_count} исходных запросов.", flush=True)
    results: list[dict[str, Any]] = []
    # Ошибка отдельной фразы не останавливает пакет: частичный отчёт полезен для остальных запросов.
    for index, phrase in enumerate(phrases, start=1):
        print(f"[XMLRIVER][POPULAR][REQUEST] Запрос {index}/{phrase_count} отправляется.", flush=True)
        try:
            response = _request_popular(
                phrase,
                user_id=user_id,
                api_key=api_key,
                settings=settings,
                timeout=timeout,
                retries=retries,
                retry_delay=retry_delay,
            )
            popular_phrases = _extract_popular(response)
            results.append({
                "phrase": phrase,
                "popular": popular_phrases,
                "response": response,
                "error": None,
            })
            print(f"[XMLRIVER][POPULAR][SUCCESS] Запрос {index}/{phrase_count}: найдено {len(popular_phrases)} фраз.", flush=True)
        except (XMLRiverPopularError, ValueError) as error:
            results.append({
                "phrase": phrase,
                "popular": [],
                "response": None,
                "error": str(error),
            })
            print(f"[XMLRIVER][POPULAR][ERROR] Запрос {index}/{phrase_count} завершился с {type(error).__name__}.", flush=True)
    print(f"[XMLRIVER][POPULAR][FINAL] Обработка завершена: {len(results)} результатов.", flush=True)
    return results
