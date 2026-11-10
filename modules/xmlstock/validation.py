"""Проверка режимов и параметров запросов к четырём инструментам XMLStock."""

from __future__ import annotations

from datetime import datetime
from typing import Any


class XMLStockInputError(ValueError):
    """Параметры не соответствуют контракту инструмента XMLStock."""


ENDPOINTS = {
    'yandex_xml_proxy': 'https://xmlstock.com/yandex/xml/',
    'yandex_live': 'https://xmlstock.com/yandexlive/{format}/',
    'google_xml_search': 'https://xmlstock.com/google/{format}/',
    'yandex_wordstat': 'https://xmlstock.com/wordstat/json/',
}

PARAMETERS = {
    'yandex_xml_proxy': {'query', 'lr', 'page', 'domain', 'device', 'groupby', 'sortby', 'filter', 'noreask'},
    'yandex_live': {'query', 'tbm', 'device', 'lr', 'page', 'ads', 'related', 'within', 'hlword'},
    'google_xml_search': {'query', 'lr', 'device', 'tbm', 'tbs', 'hl', 'related', 'filter', 'safe', 'ai'},
    'yandex_wordstat': {'query', 'pagetype', 'groupby', 'period', 'start', 'end', 'device', 'regions', 'distributionby'},
}


def _choice(params: dict[str, str], name: str, values: set[str]) -> None:
    value = params.get(name)
    if value is not None and value not in values:
        raise XMLStockInputError(f'Параметр {name} имеет недопустимое значение.')


def _integer(params: dict[str, str], name: str, minimum: int, maximum: int) -> None:
    value = params.get(name)
    if value is None:
        return
    try:
        parsed = int(value)
    except ValueError:
        raise XMLStockInputError(f'Параметр {name} должен быть целым числом.') from None
    if not minimum <= parsed <= maximum:
        raise XMLStockInputError(f'Параметр {name} должен быть от {minimum} до {maximum}.')


def _validate_date(value: str, name: str) -> datetime:
    try:
        return datetime.strptime(value, '%d.%m.%Y')
    except ValueError:
        raise XMLStockInputError(f'Параметр {name} должен иметь формат ДД.ММ.ГГГГ.') from None


def validate_request(
    tool: str,
    params: dict[str, Any],
    output_format: str,
    method: str,
) -> tuple[dict[str, str], str, str]:
    """Нормализует ввод и ограничивает запрос поддерживаемым API-инструментом."""
    if not isinstance(tool, str) or tool not in ENDPOINTS:
        raise XMLStockInputError('Выбран неизвестный инструмент XMLStock.')
    if not isinstance(params, dict):
        raise XMLStockInputError('Параметры запроса должны быть объектом.')

    formats = {'xml'} if tool == 'yandex_xml_proxy' else {'json'} if tool == 'yandex_wordstat' else {'xml', 'json', 'html'}
    if not isinstance(output_format, str) or output_format not in formats:
        raise XMLStockInputError('Выбранный формат ответа не поддерживается этим инструментом.')
    allowed_methods = {'GET', 'POST'} if tool == 'yandex_xml_proxy' else {'GET'}
    normalized_method = method.upper() if isinstance(method, str) else ''
    if normalized_method not in allowed_methods:
        raise XMLStockInputError('Выбранный HTTP-метод не поддерживается этим инструментом.')

    unknown = set(params) - PARAMETERS[tool]
    if unknown:
        raise XMLStockInputError('Запрос содержит неподдерживаемые параметры.')
    normalized: dict[str, str] = {}
    for name, value in params.items():
        if value is None or value == '':
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise XMLStockInputError(f'Параметр {name} должен быть строкой или числом.')
        text = str(value).strip()
        if len(text) > 400:
            raise XMLStockInputError(f'Параметр {name} не должен превышать 400 символов.')
        if text:
            normalized[name] = text

    query = normalized.get('query', '')
    query_required = not (tool == 'yandex_wordstat' and normalized.get('pagetype', 'words') == 'regionsTree')
    if query_required and not query:
        raise XMLStockInputError('Укажи поисковый запрос.')
    if len(query) > 400:
        raise XMLStockInputError('Запрос не должен превышать 400 символов.')
    if tool in {'yandex_xml_proxy', 'yandex_live', 'google_xml_search'} and len(query.split()) > 40:
        raise XMLStockInputError('Запрос не должен превышать 40 слов.')

    if tool == 'yandex_xml_proxy':
        _integer(normalized, 'lr', 0, 2_147_483_647)
        _integer(normalized, 'page', 0, 2_147_483_647)
        _choice(normalized, 'domain', {'ru', 'by', 'kz', 'com.tr'})
        _choice(normalized, 'device', {'desktop', 'mobile', 'tablet', 'iphone', 'android'})
        _integer(normalized, 'groupby', 10, 100)
        if 'groupby' in normalized and int(normalized['groupby']) % 10:
            raise XMLStockInputError('Параметр groupby должен быть кратен 10.')
        _choice(normalized, 'sortby', {'rlv', 'tm'})
        _choice(normalized, 'filter', {'moderate', 'none', 'strict'})
        _choice(normalized, 'noreask', {'0', '1'})
    elif tool == 'yandex_live':
        _choice(normalized, 'tbm', {'images', 'video', 'turbo'})
        _choice(normalized, 'device', {'desktop', 'mobile'})
        _integer(normalized, 'lr', 0, 2_147_483_647)
        _integer(normalized, 'page', 0, 2_147_483_647)
        _choice(normalized, 'ads', {'0', '1'})
        _choice(normalized, 'related', {'0', '1'})
        _choice(normalized, 'within', {'77', '1', '2'})
        _choice(normalized, 'hlword', {'0', '1'})
        if output_format == 'html' and normalized.get('tbm') != 'turbo':
            raise XMLStockInputError('HTML-формат Яндекс Live доступен только в режиме Turbo.')
        if output_format == 'html' and 'within' in normalized:
            raise XMLStockInputError('Фильтр within недоступен для HTML-формата.')
    elif tool == 'google_xml_search':
        _integer(normalized, 'lr', 0, 2_147_483_647)
        _choice(normalized, 'device', {'desktop', 'mobile'})
        _choice(normalized, 'tbm', {'images', 'news', 'video'})
        _choice(normalized, 'related', {'0', '1'})
        _choice(normalized, 'filter', {'0', '1'})
        _choice(normalized, 'safe', {'on', 'off', 'active'})
        _choice(normalized, 'ai', {'0', '1'})
    else:
        _choice(normalized, 'pagetype', {'words', 'history', 'regions', 'regionsTree'})
        page_type = normalized.get('pagetype', 'words')
        _integer(normalized, 'groupby', 1, 2000)
        if 'groupby' in normalized and page_type != 'words':
            raise XMLStockInputError('Параметр groupby поддерживается только для pagetype=words.')
        _choice(normalized, 'period', {'day', 'week', 'month'})
        if ('start' in normalized) != ('end' in normalized):
            raise XMLStockInputError('Параметры start и end нужно указывать вместе.')
        if page_type != 'history' and any(key in normalized for key in ('period', 'start', 'end')):
            raise XMLStockInputError('period, start и end поддерживаются только для pagetype=history.')
        if 'start' in normalized:
            if _validate_date(normalized['start'], 'start') > _validate_date(normalized['end'], 'end'):
                raise XMLStockInputError('Дата start не может быть позже даты end.')
        device_values = {'all', 'desktop', 'mobile', 'phone', 'tablet'}
        if 'device' in normalized and not set(normalized['device'].split(',')).issubset(device_values):
            raise XMLStockInputError('Параметр device содержит неподдерживаемый тип устройства.')
        if 'regions' in normalized and normalized['regions'] != 'all':
            regions = normalized['regions'].split(',')
            if len(regions) > 100 or any(not region.lstrip('-').isdigit() for region in regions):
                raise XMLStockInputError('regions должен содержать до 100 числовых ID или значение all.')
        _choice(normalized, 'distributionby', {'all', 'cities', 'regions'})
        if 'distributionby' in normalized and page_type != 'regions':
            raise XMLStockInputError('Параметр distributionby поддерживается только для pagetype=regions.')

    if tool == 'google_xml_search':
        tbs = normalized.get('tbs', '')
        if tbs and tbs not in {'qdr:d', 'qdr:w', 'qdr:m', 'qdr:y'} and not tbs.startswith('cdr:1,cd_min:'):
            raise XMLStockInputError('Параметр tbs должен быть периодом поиска или диапазоном дат cdr.')
        if tbs.startswith('cdr:1,cd_min:') and ',cd_max:' not in tbs:
            raise XMLStockInputError('Диапазон tbs должен содержать cd_min и cd_max.')

    return normalized, output_format, normalized_method
