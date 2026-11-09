"""Настройки OpenAI-совместимого API; секреты читаются только из окружения."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class OpenAISettings:
    """Параметры подключения, необходимые для одного chat completion-запроса."""

    api_key: str
    base_url: str
    default_model: str
    timeout_seconds: float


class OpenAIConfigurationError(ValueError):
    """Настройки OpenAI-совместимого API отсутствуют или имеют неверный формат."""


def get_settings() -> OpenAISettings:
    """Читает настройки на каждый вызов, чтобы использовать актуальное окружение."""
    api_key = os.getenv('OPENAI_API_KEY', '').strip()
    base_url = os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1').strip().rstrip('/')
    default_model = os.getenv('OPENAI_MODEL', '').strip()
    timeout_value = os.getenv('OPENAI_TIMEOUT_SECONDS', '60').strip()

    if not api_key:
        raise OpenAIConfigurationError('Не задан ключ API (OPENAI_API_KEY).')
    parsed_url = urlparse(base_url)
    if parsed_url.scheme != 'https' or not parsed_url.hostname or parsed_url.username or parsed_url.password:
        raise OpenAIConfigurationError('OPENAI_BASE_URL должен быть HTTPS-адресом API.')
    if not default_model or len(default_model) > 100:
        raise OpenAIConfigurationError('OPENAI_MODEL должен содержать от 1 до 100 символов.')
    try:
        timeout_seconds = float(timeout_value)
    except ValueError:
        raise OpenAIConfigurationError('OPENAI_TIMEOUT_SECONDS должен быть положительным числом.') from None
    if not 0 < timeout_seconds <= 600:
        raise OpenAIConfigurationError('OPENAI_TIMEOUT_SECONDS должен быть в диапазоне от 0 до 600.')

    return OpenAISettings(
        api_key=api_key,
        base_url=base_url,
        default_model=default_model,
        timeout_seconds=timeout_seconds,
    )
