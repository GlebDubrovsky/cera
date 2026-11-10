"""Независимый от FastAPI клиент для четырёх API XMLStock."""

from __future__ import annotations

from typing import Any

import requests

from modules.xmlstock.settings import XMLStockConfigurationError, get_settings
from modules.xmlstock.validation import ENDPOINTS, XMLStockInputError, validate_request

MAX_RESPONSE_BYTES = 10 * 1024 * 1024


class XMLStockAPIError(RuntimeError):
    """Сетевой сбой или непригодный ответ сервиса XMLStock."""


def request_xmlstock(
    tool: str,
    params: dict[str, Any],
    *,
    output_format: str = 'xml',
    method: str = 'GET',
) -> dict[str, Any]:
    """Выполняет запрос к одному из фиксированных API-инструментов XMLStock.

    Аргументы запроса передаются через ``params``; учётные данные загружаются
    только из серверного окружения. Результат содержит статус и тело ответа,
    поэтому JSON, XML и HTML можно обработать вызывающим сценарием самостоятельно.
    """
    print('[XMLSTOCK][VALIDATION][START] Проверка инструмента и параметров запроса.', flush=True)
    normalized, selected_format, selected_method = validate_request(tool, params, output_format, method)
    settings = get_settings()
    endpoint = ENDPOINTS[tool].format(format=selected_format)
    request_params = {'user': settings.user, 'key': settings.key, **normalized}

    print(f'[XMLSTOCK][REQUEST][START] Отправка запроса к инструменту {tool}.', flush=True)
    try:
        if selected_method == 'GET':
            response = requests.get(
                endpoint,
                params=request_params,
                timeout=settings.timeout_seconds,
                allow_redirects=False,
            )
        else:
            response = requests.post(
                endpoint,
                data=request_params,
                timeout=settings.timeout_seconds,
                allow_redirects=False,
            )
        body_bytes = response.content
        if len(body_bytes) > MAX_RESPONSE_BYTES:
            print('[XMLSTOCK][RESPONSE][FAILURE] Ответ превысил допустимый размер.', flush=True)
            raise XMLStockAPIError('Ответ XMLStock превышает допустимый размер 10 МБ.')
        body = response.text
    except requests.RequestException as error:
        print(f'[XMLSTOCK][REQUEST][FAILURE] Сетевой запрос завершён ошибкой {type(error).__name__}.', flush=True)
        raise XMLStockAPIError('Не удалось связаться с XMLStock.') from None

    # Защищаем даже ошибочный текстовый ответ провайдера от случайного отражения
    # учётных данных в UI или вызывающем сценарии.
    for credential in (settings.key, settings.user):
        if len(credential) >= 4:
            body = body.replace(credential, '[скрыто]')

    print(
        f'[XMLSTOCK][RESPONSE][SUCCESS] Получен ответ со статусом {response.status_code} '
        f'({len(body_bytes)} байт).',
        flush=True,
    )
    return {
        'tool': tool,
        'method': selected_method,
        'format': selected_format,
        'status_code': response.status_code,
        'content_type': response.headers.get('content-type', 'application/octet-stream'),
        'body': body,
    }


__all__ = [
    'XMLStockAPIError',
    'XMLStockConfigurationError',
    'XMLStockInputError',
    'request_xmlstock',
]
