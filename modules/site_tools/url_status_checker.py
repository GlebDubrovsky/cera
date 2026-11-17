"""Проверка HTTP-статуса публичных URL для Python и интерфейса."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from urllib.parse import urljoin

import requests
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from requests import Response
from requests.exceptions import RequestException

from config.config import HEADERS
from shared.page_content import PageFetchError, PageInputError, validate_public_url

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_ATTEMPTS = 3
DEFAULT_PAUSE_SECONDS = 1.0
MAX_REDIRECTS = 5
_REDIRECT_CODES = {301, 302, 303, 307, 308}
_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


class URLStatusCheckError(RuntimeError):
    """Запрос не получил HTTP-ответ после исчерпания повторов."""


class URLStatusChecker:
    """Проверяет один URL или список URL, сохраняя фактические HTTP-коды."""

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        attempts: int = DEFAULT_ATTEMPTS,
        pause_seconds: float = DEFAULT_PAUSE_SECONDS,
        headers: dict[str, str] | None = None,
    ) -> None:
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise ValueError("Таймаут должен быть положительным числом.")
        if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
            raise ValueError("Количество попыток должно быть целым числом не меньше 1.")
        if isinstance(pause_seconds, bool) or not isinstance(pause_seconds, (int, float)) or pause_seconds < 0:
            raise ValueError("Пауза должна быть числом не меньше 0.")
        self.timeout_seconds = float(timeout_seconds)
        self.attempts = attempts
        self.pause_seconds = float(pause_seconds)
        self.headers = dict(HEADERS if headers is None else headers)

    def check_url(self, url: str) -> Response:
        """Возвращает потоковый requests.Response; вызывающий код закрывает его.

        HTTP-коды, включая 4xx, возвращаются как ответ. Повторы применяются к
        сетевым ошибкам и временным ответам, а каждый переход проверяется на
        публичный адрес, чтобы редирект не открыл доступ к внутренней сети.
        """
        current_url = validate_public_url(url)
        last_error: RequestException | None = None

        for attempt in range(self.attempts):
            try:
                response = self._request_following_public_redirects(current_url)
                if response.status_code not in _RETRY_STATUS_CODES or attempt == self.attempts - 1:
                    return response
                response.close()
            except (PageInputError, PageFetchError, URLStatusCheckError):
                raise
            except RequestException as error:
                last_error = error

            if attempt < self.attempts - 1 and self.pause_seconds:
                time.sleep(self.pause_seconds)

        error_type = type(last_error).__name__ if last_error else "RequestException"
        raise URLStatusCheckError(
            f"HTTP-ответ не получен после {self.attempts} попыток ({error_type})."
        ) from None

    def check_urls(
        self,
        urls: Iterable[str],
        *,
        stop_event: threading.Event | None = None,
        progress_callback: Callable[..., None] | None = None,
    ) -> list[dict[str, str | int]]:
        """Проверяет URL по очереди; остановка действует между ссылками."""
        url_list = list(urls)
        results: list[dict[str, str | int]] = []
        error_count = 0
        total_count = len(url_list)
        print(f"[URL_STATUS_CHECKER][START][INFO] Ссылок: {total_count}.", flush=True)
        if progress_callback:
            progress_callback(
                total_count=total_count, candidate_count=total_count,
                processed_count=0, error_count=0, message="Проверка ссылок запущена",
            )

        for index, url in enumerate(url_list, start=1):
            if stop_event and stop_event.is_set():
                print(f"[URL_STATUS_CHECKER][STOP][INFO] Остановка перед ссылкой {index}/{total_count}.", flush=True)
                break
            safe_url = url.strip() if isinstance(url, str) else ""
            print(f"[URL_STATUS_CHECKER][ITEM][START] Ссылка {index}/{total_count}.", flush=True)
            try:
                response = self.check_url(safe_url)
                try:
                    status_code: str | int = response.status_code
                finally:
                    response.close()
                results.append({"url": safe_url, "status_code": status_code})
                print(f"[URL_STATUS_CHECKER][ITEM][SUCCESS] Ссылка {index}/{total_count}; HTTP {status_code}.", flush=True)
            except (PageInputError, PageFetchError, URLStatusCheckError, RequestException, ValueError) as error:
                error_count += 1
                results.append({"url": safe_url, "status_code": "ERROR"})
                print(f"[URL_STATUS_CHECKER][ITEM][FAILURE] Ссылка {index}/{total_count}; ошибка: {type(error).__name__}.", flush=True)

            if progress_callback:
                progress_callback(
                    total_count=total_count, candidate_count=total_count,
                    processed_count=len(results), error_count=error_count,
                    message=f"Обработано {len(results)} из {total_count}",
                )
            if index < total_count and self.pause_seconds:
                if stop_event:
                    stop_event.wait(self.pause_seconds)
                else:
                    time.sleep(self.pause_seconds)

        finish_status = "STOPPED" if stop_event and stop_event.is_set() else "SUCCESS"
        print(
            f"[URL_STATUS_CHECKER][FINISH][{finish_status}] Проверено: {len(results)} из {total_count}; ошибок: {error_count}.",
            flush=True,
        )
        if progress_callback:
            progress_callback(
                total_count=total_count, candidate_count=total_count,
                processed_count=len(results), error_count=error_count,
                message=f"Проверено {len(results)} из {total_count}",
            )
        return results

    def _request_following_public_redirects(self, url: str) -> Response:
        current_url = url
        for redirect_index in range(MAX_REDIRECTS + 1):
            response = requests.get(
                current_url,
                headers=self.headers,
                timeout=self.timeout_seconds,
                allow_redirects=False,
                stream=True,
            )
            if response.status_code not in _REDIRECT_CODES:
                return response
            location = response.headers.get("Location")
            if not location or redirect_index == MAX_REDIRECTS:
                return response
            try:
                next_url = validate_public_url(urljoin(current_url, location))
            finally:
                # Закрываем промежуточный ответ и при разрешённом, и при запрещённом редиректе.
                response.close()
            current_url = next_url
        raise URLStatusCheckError("Превышено допустимое количество перенаправлений.")


def check_url(
    url: str,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    attempts: int = DEFAULT_ATTEMPTS,
    pause_seconds: float = DEFAULT_PAUSE_SECONDS,
) -> Response:
    """Проверяет один публичный URL и возвращает открытый requests.Response."""
    return URLStatusChecker(
        timeout_seconds=timeout_seconds,
        attempts=attempts,
        pause_seconds=pause_seconds,
    ).check_url(url)


def check_urls(
    urls: Iterable[str],
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    attempts: int = DEFAULT_ATTEMPTS,
    pause_seconds: float = DEFAULT_PAUSE_SECONDS,
    stop_event: threading.Event | None = None,
    progress_callback: Callable[..., None] | None = None,
) -> list[dict[str, str | int]]:
    """Проверяет URL; поддерживает остановку и обновление прогресса."""
    return URLStatusChecker(
        timeout_seconds=timeout_seconds,
        attempts=attempts,
        pause_seconds=pause_seconds,
    ).check_urls(urls, stop_event=stop_event, progress_callback=progress_callback)


def write_results_xlsx(path: str | Path, results: Iterable[Mapping[str, object]]) -> Path:
    """Сохраняет таблицу результатов, не позволяя Excel трактовать ввод как формулу."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "URL status"
    worksheet.append(["url", "status_code"])
    for cell in worksheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="0D6EFD")

    for result in results:
        safe_values = []
        for key in ("url", "status_code"):
            value = result.get(key, "")
            if isinstance(value, str) and value[:1] in {"=", "+", "-", "@"}:
                value = "'" + value
            safe_values.append(value)
        worksheet.append(safe_values)

    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    worksheet.column_dimensions["A"].width = 72
    worksheet.column_dimensions["B"].width = 16
    workbook.save(output_path)
    workbook.close()
    return output_path
