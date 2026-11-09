"""Публичный интерфейс OpenAI-совместимого API-клиента."""

from modules.openai_api.service import OpenAIAPIError, OpenAIInputError, chat_completion
from modules.openai_api.settings import OpenAIConfigurationError

__all__ = [
    'OpenAIAPIError',
    'OpenAIConfigurationError',
    'OpenAIInputError',
    'chat_completion',
]
