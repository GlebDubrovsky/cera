"""Сбор органической поисковой выдачи Google через XMLRiver."""

from __future__ import annotations

import time
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET


API_URL = "https://xmlriver.com/search/xml"
_RESULTS_PER_PAGE = 10


class XMLRiverGoogleSERPError(RuntimeError):
    """Ошибка API XMLRiver или сетевого запроса выдачи Google."""


def _request_page(
    phrase: str,
    page: int,
    *,
    user_id: str,
    api_key: str,
    settings: Mapping[str, Any] | None,
    timeout: float,
    retries: int,
    retry_delay: float,
) -> str:
    """Запрашивает одну страницу Google; нумерация страниц XMLRiver начинается с 1."""
    params: dict[str, Any] = {"user": user_id, "key": api_key, "query": phrase, "page": page}
    for name, value in (settings or {}).items():
        if name not in {"user", "key", "query", "page"} and value not in (None, ""):
            params[name] = value

    request = Request(
        f"{API_URL}?{urlencode(params)}",
        headers={"Accept": "application/xml", "User-Agent": "xmlriver-google-serp-client/1.0"},
        method="GET",
    )
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except HTTPError as error:
            if (error.code == 429 or error.code >= 500) and attempt < retries:
                time.sleep(retry_delay * (attempt + 1))
                continue
            raise XMLRiverGoogleSERPError(f"XMLRiver вернул HTTP-код {error.code}.") from None
        except (URLError, TimeoutError) as error:
            if attempt < retries:
                time.sleep(retry_delay * (attempt + 1))
                continue
            raise XMLRiverGoogleSERPError(
                f"Ошибка запроса к XMLRiver ({type(error).__name__})."
            ) from None

    raise XMLRiverGoogleSERPError("Не удалось выполнить запрос к XMLRiver после повторных попыток.")


def _parse_page(xml_text: str) -> list[dict[str, str]]:
    """Преобразует XML выдачи в общий с Яндексом формат результатов."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as error:
        raise XMLRiverGoogleSERPError("XMLRiver вернул некорректный XML.") from error

    error_node = root if root.tag == "error" else root.find(".//error")
    if error_node is not None:
        code_text = error_node.get("code", "")
        message = " ".join(error_node.itertext()).strip() or "Ошибка API XMLRiver."
        if code_text:
            message = f"Код {code_text}: {message}"
        if code_text.isdigit() and int(code_text) == 15:
            return []
        raise XMLRiverGoogleSERPError(message)

    results: list[dict[str, str]] = []
    for doc in root.findall(".//group/doc"):
        content_type = (doc.findtext("contenttype") or "").strip()
        if content_type and content_type != "organic":
            continue
        url = (doc.findtext("url") or "").strip()
        if not url:
            continue
        title_node = doc.find("title")
        title = " ".join("".join(title_node.itertext()).split()) if title_node is not None else ""
        snippet = " ".join(
            " ".join("".join(node.itertext()).split())
            for node in doc.findall("./passages/passage")
        )
        results.append({"url": url, "title": title, "snippet": snippet})
    return results


def fetch_google_search_results(
    phrases: Sequence[str],
    *,
    user_id: str,
    api_key: str,
    top_n: int = 10,
    settings: Mapping[str, Any] | None = None,
    timeout: float = 30,
    retries: int = 2,
    retry_delay: float = 1,
) -> list[dict[str, Any]]:
    """Возвращает до 10, 20 или 30 органических результатов Google на фразу.

    XMLRiver выдаёт по 10 результатов на странице; первая страница имеет номер 1,
    а ``settings`` принимает параметры Google XML API, например ``lr``, ``device``,
    ``country``, ``loc`` и ``domain``. Результаты имеют вид ``phrase/results/responses/error`` и совместимы с
    общим XLSX-экспортом XMLRiver.
    """
    if not user_id or not api_key:
        raise ValueError("Не заданы user_id и api_key.")
    if top_n not in {10, 20, 30}:
        raise ValueError("Параметр top_n должен быть равен 10, 20 или 30.")
    if retries < 0:
        raise ValueError("Количество повторных попыток не может быть отрицательным.")

    phrase_count = len(phrases)
    print(f"[XMLRIVER][GOOGLE_SERP][START] Начат сбор ТОП {top_n} для {phrase_count} фраз.", flush=True)
    results: list[dict[str, Any]] = []
    # Каждая фраза обрабатывается отдельно, чтобы сетевой сбой не отменял весь пакет.
    for phrase_index, phrase in enumerate(phrases, start=1):
        print(f"[XMLRIVER][GOOGLE_SERP][REQUEST] Фраза {phrase_index}/{phrase_count}: подготовка запроса.", flush=True)
        clean_phrase = phrase.strip()
        if not clean_phrase:
            results.append({"phrase": phrase, "results": [], "responses": [], "error": "Поисковая фраза не должна быть пустой."})
            continue

        organic_results: list[dict[str, str]] = []
        responses: list[str] = []
        seen_urls: set[str] = set()
        error_message: str | None = None
        pages_to_fetch = (top_n + _RESULTS_PER_PAGE - 1) // _RESULTS_PER_PAGE
        try:
            for page_index in range(pages_to_fetch):
                page = page_index + 1
                print(f"[XMLRIVER][GOOGLE_SERP][PAGE] Фраза {phrase_index}/{phrase_count}: страница {page}/{pages_to_fetch}.", flush=True)
                xml_text = _request_page(
                    clean_phrase,
                    page,
                    user_id=user_id,
                    api_key=api_key,
                    settings=settings,
                    timeout=timeout,
                    retries=retries,
                    retry_delay=retry_delay,
                )
                responses.append(xml_text)
                page_results = _parse_page(xml_text)
                # Убираем повторы между страницами, сохраняя стабильную нумерацию позиций.
                for item in page_results:
                    if item["url"] in seen_urls:
                        continue
                    seen_urls.add(item["url"])
                    item["position"] = str(len(organic_results) + 1)
                    organic_results.append(item)
                    if len(organic_results) == top_n:
                        break
                if len(organic_results) == top_n or not page_results:
                    break
        except XMLRiverGoogleSERPError as error:
            error_message = str(error)
            print(f"[XMLRIVER][GOOGLE_SERP][ERROR] Фраза {phrase_index}/{phrase_count} завершилась с {type(error).__name__}.", flush=True)

        phrase_result = {
            "phrase": phrase,
            "results": organic_results[:top_n],
            "responses": responses,
            "error": error_message,
        }
        results.append(phrase_result)
        if error_message is None:
            print(f"[XMLRIVER][GOOGLE_SERP][SUCCESS] Фраза {phrase_index}/{phrase_count}: результатов {len(organic_results[:top_n])}.", flush=True)
    print(f"[XMLRIVER][GOOGLE_SERP][FINAL] Обработка завершена: {len(results)} результатов.", flush=True)
    return results
