"""Загрузка общих текстовых шаблонов и безопасная подстановка переменных."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

PROMPT_DIRECTORY = Path(__file__).resolve().parent / 'prompts'
_PLACEHOLDER_PATTERN = re.compile(r'\{\{\s*([A-Za-z][A-Za-z0-9_]*)\s*\}\}')
_ANY_PLACEHOLDER_PATTERN = re.compile(r'\{\{.*?\}\}', re.DOTALL)
_TEMPLATE_NAME_PATTERN = re.compile(r'[A-Za-z0-9_-]+\.md')


class PromptTemplateError(ValueError):
    """Шаблон невозможно безопасно загрузить или заполнить."""


def load_prompt_template(template_name: str) -> str:
    """Загружает Markdown-шаблон только из ``shared/prompts``.

    Принимается bare filename, а не произвольный путь, чтобы имена от клиента
    не могли вывести чтение файлов за пределы каталога общих шаблонов.
    """
    if not isinstance(template_name, str) or not _TEMPLATE_NAME_PATTERN.fullmatch(template_name):
        raise PromptTemplateError('Укажи корректное имя Markdown-шаблона.')
    template_path = PROMPT_DIRECTORY / template_name
    try:
        return template_path.read_text(encoding='utf-8')
    except OSError:
        raise PromptTemplateError('Запрошенный шаблон промпта не найден.') from None


def render_prompt_template(template: str, variables: Mapping[str, str]) -> str:
    """Подставляет все ``{{variable}}`` и отклоняет пустые/неизвестные поля."""
    if not isinstance(template, str) or not template.strip():
        raise PromptTemplateError('Шаблон промпта должен быть непустой строкой.')
    if not isinstance(variables, Mapping):
        raise PromptTemplateError('Переменные шаблона должны быть отображением.')
    if any(not isinstance(name, str) or not isinstance(value, str) for name, value in variables.items()):
        raise PromptTemplateError('Имена переменных и их значения должны быть строками.')

    def replace_placeholder(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in variables:
            raise PromptTemplateError(f'Не задана переменная шаблона: {name}.')
        return variables[name]

    rendered = _PLACEHOLDER_PATTERN.sub(replace_placeholder, template)
    if _ANY_PLACEHOLDER_PATTERN.search(rendered):
        raise PromptTemplateError('Шаблон содержит переменную в неподдерживаемом формате.')
    return rendered
