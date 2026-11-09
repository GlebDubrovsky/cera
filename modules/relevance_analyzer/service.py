"""Независимая от HTTP точка запуска анализа релевантности."""

from __future__ import annotations

import ipaddress
from typing import Any, Mapping
from urllib.parse import urlparse

from modules.relevance_analyzer.relevance import Relevance

MAX_COMPETITORS = 50
MAX_EXCLUDED_WORDS = 500


class RelevanceInputError(ValueError):
    """Входная конфигурация анализа не соответствует публичному контракту."""


def _validate_url(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 2048 or any(char.isspace() for char in value):
        raise RelevanceInputError(f'Проверь URL поля «{label}».')
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError:
        raise RelevanceInputError(f'Проверь URL поля «{label}».') from None
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        raise RelevanceInputError(f'Для поля «{label}» нужен публичный URL с протоколом HTTP или HTTPS.')
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise RelevanceInputError(f'Для поля «{label}» нужен публичный URL.')
    if port is not None and not 1 <= port <= 65535:
        raise RelevanceInputError(f'Проверь порт в URL поля «{label}».')
    return value.strip()


def validate_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Проверяет форму входа и возвращает независимую нормализованную копию."""
    if not isinstance(config, Mapping):
        raise RelevanceInputError('Ожидалась конфигурация анализа.')
    if 'link' not in config or 'sites' not in config:
        raise RelevanceInputError('Укажи целевую страницу и не менее одного сайта-конкурента.')
    link = _validate_url(config['link'], 'целевой страницы')
    sites_value = config['sites']
    if isinstance(sites_value, str):
        sites = [line.strip() for line in sites_value.splitlines() if line.strip()]
    elif isinstance(sites_value, (list, tuple)):
        sites = list(sites_value)
    else:
        raise RelevanceInputError('Список сайтов-конкурентов задан неверно.')
    if not sites or len(sites) > MAX_COMPETITORS:
        raise RelevanceInputError(f'Добавь от 1 до {MAX_COMPETITORS} сайтов-конкурентов.')
    normalized_sites = [_validate_url(site, 'сайта-конкурента') for site in sites]
    if len(set(normalized_sites)) != len(normalized_sites) or link in normalized_sites:
        raise RelevanceInputError('Целевой сайт и сайты-конкуренты не должны повторяться.')

    separator_value = config.get('separator', 3)
    if isinstance(separator_value, bool) or not str(separator_value).isdigit() or not 1 <= int(separator_value) <= 12:
        raise RelevanceInputError('Минимальная длина слова должна быть числом от 1 до 12.')
    conjunctions = config.get('conjunctions', False)
    if not isinstance(conjunctions, bool):
        raise RelevanceInputError('Параметр учёта союзов должен быть логическим значением.')
    phrase = config.get('phrase', '')
    if not isinstance(phrase, str) or len(phrase) > 300:
        raise RelevanceInputError('Ключевая фраза должна содержать не более 300 символов.')
    words_value = config.get('list_words', [])
    if not isinstance(words_value, (list, tuple)) or len(words_value) > MAX_EXCLUDED_WORDS:
        raise RelevanceInputError(f'Список исключений должен содержать не более {MAX_EXCLUDED_WORDS} слов.')
    if any(not isinstance(word, str) or len(word) > 100 for word in words_value):
        raise RelevanceInputError('Каждое исключаемое слово должно быть строкой до 100 символов.')
    return {
        'link': link,
        'phrase': phrase.strip(),
        'sites': normalized_sites,
        'separator': int(separator_value),
        'conjunctions': conjunctions,
        'list_words': [word.strip() for word in words_value if word.strip()],
    }


def run_analysis(config: Mapping[str, Any]) -> Relevance:
    """Проверяет конфигурацию и возвращает заполненный результат анализа.

    Прямой контракт для пользовательских сценариев:
    ``run_analysis({link, sites, phrase?, separator?, conjunctions?, list_words?})``.
    Сетевые обращения ограничены проверкой адреса на каждом URL/редиректе.
    """
    normalized = validate_config(config)
    print(
        f"[RELEVANCE_ANALYZER][START][SUCCESS] Запуск анализа для {len(normalized['sites'])} сайтов-конкурентов.",
        flush=True,
    )
    result = Relevance(normalized).run()
    analyzed = sum(not site['danger'] for site in result.sites.values())
    print(
        f'[RELEVANCE_ANALYZER][TOTALS][SUCCESS] Успешно проанализировано страниц: {analyzed}/{len(result.sites)}.',
        flush=True,
    )
    return result
