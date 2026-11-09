"""Разбор конфигурации анализатора из JSON и исходного TXT-формата."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def parse_txt(text: str) -> dict[str, Any]:
    """Разбирает файл «Входные данные.txt» из исходного скрипта."""
    config: dict[str, Any] = {'sites': [], 'list_words': []}
    mode: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if 'посадочная страница' in lowered:
            mode = 'link'
            continue
        if 'ключевая фраза' in lowered:
            mode = 'phrase'
            continue
        if 'список сканируемых сайтов' in lowered:
            mode = 'sites'
            continue
        if 'обрезать слова короче' in lowered:
            match = re.search(r'\d+', line)
            config['separator'] = int(match.group()) if match else 3
            mode = None
            continue
        if 'учитывать союзы' in lowered:
            config['conjunctions'] = lowered.endswith('да')
            mode = None
            continue
        if 'исключать' in lowered:
            mode = 'words'
            continue
        if mode == 'link':
            config['link'] = line
            mode = None
        elif mode == 'phrase':
            config['phrase'] = line
            mode = None
        elif mode == 'sites' and line.startswith(('http://', 'https://')):
            config['sites'].append(line)
        elif mode == 'words' and not re.fullmatch(r'-{3,}', line):
            config['list_words'].append(line)
    return config


def parse_config(text: str, *, file_name: str = '') -> dict[str, Any]:
    """Читает JSON или исходный текстовый формат без доступа к файловой системе."""
    if file_name.lower().endswith('.json'):
        config = json.loads(text)
        if not isinstance(config, dict):
            raise ValueError('Конфигурация JSON должна быть объектом.')
        return config
    return parse_txt(text)


def load_config(path: str | Path) -> dict[str, Any]:
    """Загружает сохранённую конфигурацию для программного запуска."""
    input_path = Path(path)
    return parse_config(input_path.read_text(encoding='utf-8'), file_name=input_path.name)
