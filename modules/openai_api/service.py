"""Клиент OpenAI-совместимого Chat Completions API, независимый от FastAPI."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import requests

from modules.openai_api.settings import OpenAIConfigurationError, get_settings

MAX_MESSAGES = 100
MAX_MESSAGE_LENGTH = 100_000
MAX_TOTAL_CONTENT_LENGTH = 200_000
_ALLOWED_ROLES = {'system', 'user', 'assistant', 'tool'}


class OpenAIInputError(ValueError):
    """Входные данные не соответствуют контракту модуля."""


class OpenAIAPIError(RuntimeError):
    """Запрос к OpenAI-совместимому API завершился ошибкой или некорректным ответом."""


def _validate_messages(messages: Sequence[Mapping[str, object]]) -> list[dict[str, str]]:
    """Ограничивает форму и размер диалога до сетевого вызова и тарификации."""
    if isinstance(messages, (str, bytes)) or not isinstance(messages, Sequence):
        raise OpenAIInputError('messages должен быть списком сообщений.')
    if not messages or len(messages) > MAX_MESSAGES:
        raise OpenAIInputError(f'Число сообщений должно быть от 1 до {MAX_MESSAGES}.')

    normalized: list[dict[str, str]] = []
    total_content_length = 0
    for index, message in enumerate(messages, start=1):
        if not isinstance(message, Mapping):
            raise OpenAIInputError(f'Сообщение {index} должно быть объектом с role и content.')
        role = message.get('role')
        content = message.get('content')
        if not isinstance(role, str) or role not in _ALLOWED_ROLES:
            raise OpenAIInputError(f'У сообщения {index} недопустимая роль.')
        if not isinstance(content, str) or not content.strip():
            raise OpenAIInputError(f'Содержимое сообщения {index} должно быть непустой строкой.')
        if len(content) > MAX_MESSAGE_LENGTH:
            raise OpenAIInputError(f'Сообщение {index} превышает допустимый размер.')
        total_content_length += len(content)
        if total_content_length > MAX_TOTAL_CONTENT_LENGTH:
            raise OpenAIInputError('Общий размер сообщений превышает допустимый предел.')
        normalized.append({'role': role, 'content': content})
    return normalized


def _validate_optional_parameters(
    model: str | None,
    temperature: float | None,
    max_tokens: int | None,
    top_p: float | None,
) -> None:
    if model is not None and (not isinstance(model, str) or not model.strip() or len(model) > 100):
        raise OpenAIInputError('model должен содержать от 1 до 100 символов.')
    if temperature is not None and (isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2):
        raise OpenAIInputError('temperature должна быть числом от 0 до 2.')
    if max_tokens is not None and (isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 65536):
        raise OpenAIInputError('max_tokens должен быть целым числом от 1 до 65536.')
    if top_p is not None and (isinstance(top_p, bool) or not isinstance(top_p, (int, float)) or not 0 <= top_p <= 1):
        raise OpenAIInputError('top_p должна быть числом от 0 до 1.')


def chat_completion(
    messages: Sequence[Mapping[str, object]],
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    top_p: float | None = None,
    reasoning_enabled: bool | None = None,
) -> dict[str, Any]:
    """Отправляет Chat Completions-запрос и возвращает JSON-ответ провайдера.

    ``reasoning_enabled`` управляет рассуждениями вызова: ``None`` сохраняет
    поведение модели, а ``True`` и ``False`` передаются в ``reasoning.enabled``.
    Поддержка явного управления зависит от модели и провайдера.
    """
    print('[OPENAI_API][VALIDATION][START] Проверка сообщений и параметров запроса.', flush=True)
    normalized_messages = _validate_messages(messages)
    _validate_optional_parameters(model, temperature, max_tokens, top_p)
    if reasoning_enabled is not None and not isinstance(reasoning_enabled, bool):
        raise OpenAIInputError('reasoning_enabled должен быть логическим значением или None.')
    settings = get_settings()

    payload: dict[str, object] = {
        'model': model.strip() if model else settings.default_model,
        'messages': normalized_messages,
        'stream': False,
    }
    if temperature is not None:
        payload['temperature'] = temperature
    if max_tokens is not None:
        payload['max_tokens'] = max_tokens
    if top_p is not None:
        payload['top_p'] = top_p
    if reasoning_enabled is not None:
        payload['reasoning'] = {'enabled': reasoning_enabled}

    print(f'[OPENAI_API][REQUEST][START] Отправка запроса ({len(normalized_messages)} сообщений).', flush=True)
    try:
        response = requests.post(
            f'{settings.base_url}/chat/completions',
            headers={
                'Authorization': f'Bearer {settings.api_key}',
                'Content-Type': 'application/json',
            },
            json=payload,
            timeout=settings.timeout_seconds,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        print(f'[OPENAI_API][REQUEST][FAILURE] Сетевой запрос завершён ошибкой {type(error).__name__}.', flush=True)
        raise OpenAIAPIError('Не удалось получить ответ от OpenAI-совместимого API.') from None

    try:
        result = response.json()
    except ValueError:
        print('[OPENAI_API][RESPONSE][FAILURE] API вернул некорректный JSON.', flush=True)
        raise OpenAIAPIError('API вернул ответ в неизвестном формате.') from None
    if not isinstance(result, dict) or not isinstance(result.get('choices'), list) or not result['choices']:
        print('[OPENAI_API][RESPONSE][FAILURE] В ответе отсутствует список choices.', flush=True)
        raise OpenAIAPIError('API вернул ответ без вариантов completion.')

    print('[OPENAI_API][RESPONSE][SUCCESS] Получен ответ API.', flush=True)
    return result
