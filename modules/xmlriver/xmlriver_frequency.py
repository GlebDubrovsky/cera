"""Сбор частотности фраз через API Wordstat New сервиса XMLRiver."""

from __future__ import annotations

import json
import time
from typing import Any, Literal, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_URL = "https://xmlriver.com/wordstat/new/json"
_TRANSIENT_CODES = {101, 110, 500}
FrequencyMode = Literal["base", "both", "phrasal"]


class XMLRiverError(RuntimeError):
    """Ошибка API XMLRiver или сетевого запроса."""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


def fetch_frequency(
    phrase: str,
    *,
    user_id: str,
    api_key: str,
    settings: Mapping[str, Any] | None = None,
    timeout: float = 30,
    retries: int = 2,
    retry_delay: float = 1,
) -> dict[str, Any]:
    """Запрашивает частотность одной фразы и возвращает JSON с totalValue.

    В ``settings`` можно передать параметры Wordstat New: regions, device,
    period, start и end. Учётные данные не включаются в сообщения об ошибках.
    """
    if not phrase or not phrase.strip():
        raise ValueError("Поисковая фраза не должна быть пустой.")
    if not user_id or not api_key:
        raise ValueError("Не заданы user_id и api_key.")
    if retries < 0:
        raise ValueError("Количество повторных попыток не может быть отрицательным.")

    params: dict[str, Any] = {
        "user": user_id,
        "key": api_key,
        "query": phrase.strip(),
        "pagetype": "history",
    }
    for name, value in (settings or {}).items():
        if value is not None and value != "":
            params[name] = value

    request = Request(
        f"{API_URL}?{urlencode(params)}",
        headers={"Accept": "application/json", "User-Agent": "xmlriver-frequency-client/1.0"},
        method="GET",
    )

    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise XMLRiverError("XMLRiver вернул JSON в неожиданном формате.")
            if "error" in payload or "code" in payload:
                try:
                    code = int(payload.get("code"))
                except (TypeError, ValueError):
                    code = None
                message = str(payload.get("error", "Ошибка API XMLRiver."))
                if code in _TRANSIENT_CODES and attempt < retries:
                    time.sleep(retry_delay * (attempt + 1))
                    continue
                raise XMLRiverError(message, code=code)
            return payload
        except HTTPError as error:
            if error.code == 429 or error.code >= 500:
                if attempt < retries:
                    time.sleep(retry_delay * (attempt + 1))
                    continue
            raise XMLRiverError(f"XMLRiver вернул HTTP-код {error.code}.") from None
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            if attempt < retries:
                time.sleep(retry_delay * (attempt + 1))
                continue
            raise XMLRiverError(f"Ошибка запроса к XMLRiver ({type(error).__name__}).") from None

    raise XMLRiverError("Не удалось выполнить запрос к XMLRiver после повторных попыток.")


def fetch_frequencies(
    phrases: Sequence[str],
    *,
    user_id: str,
    api_key: str,
    settings: Mapping[str, Any] | None = None,
    timeout: float = 30,
    retries: int = 2,
    retry_delay: float = 1,
    mode: FrequencyMode = "base",
) -> list[dict[str, Any]]:
    """Собирает базовую, фразовую или обе частотности для каждого запроса."""
    if mode not in {"base", "both", "phrasal"}:
        raise ValueError("Неизвестный режим сбора частотности.")

    phrase_count = len(phrases)
    print(f"[XMLRIVER][FREQUENCY][START] Начат сбор частотности для {phrase_count} фраз, режим: {mode}.", flush=True)
    results: list[dict[str, Any]] = []
    for index, phrase in enumerate(phrases, start=1):
        result: dict[str, Any] = {
            "phrase": phrase,
            "total_value": None,
            "response": None,
            "error": None,
        }
        if mode in {"both", "phrasal"}:
            result["phrasal_value"] = None
        queries: list[tuple[str, str]] = []
        if mode in {"base", "both"}:
            queries.append(("total_value", phrase))
        if mode in {"phrasal", "both"}:
            # The original phrase remains the report key; only the API query gets quotes.
            queries.append(("phrasal_value", f'"{phrase.strip()}"'))

        errors: list[str] = []
        for value_name, query in queries:
            print(f"[XMLRIVER][FREQUENCY][REQUEST] Запрос {index}/{phrase_count} ({value_name}) отправляется.", flush=True)
            try:
                response = fetch_frequency(
                    query,
                    user_id=user_id,
                    api_key=api_key,
                    settings=settings,
                    timeout=timeout,
                    retries=retries,
                    retry_delay=retry_delay,
                )
                result[value_name] = response.get("totalValue")
                result["response"] = response
                print(f"[XMLRIVER][FREQUENCY][SUCCESS] Запрос {index}/{phrase_count} ({value_name}) завершён.", flush=True)
            except (XMLRiverError, ValueError) as error:
                errors.append(str(error))
                print(f"[XMLRIVER][FREQUENCY][ERROR] Запрос {index}/{phrase_count} ({value_name}) завершился с {type(error).__name__}.", flush=True)

        if errors:
            result["error"] = "; ".join(errors)
        results.append(result)
    print(f"[XMLRIVER][FREQUENCY][FINAL] Обработка завершена: {len(results)} результатов.", flush=True)
    return results
