"""HTTP-адаптер OpenAI-совместимого chat completion-клиента."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from modules.openai_api import (
    OpenAIAPIError,
    OpenAIConfigurationError,
    OpenAIInputError,
    chat_completion,
)

router = APIRouter()


class ChatMessage(BaseModel):
    """Текстовое сообщение диалога в формате Chat Completions."""

    model_config = ConfigDict(extra='forbid')

    role: Literal['system', 'user', 'assistant', 'tool']
    content: str = Field(min_length=1, max_length=100_000)


class ChatCompletionRequest(BaseModel):
    """Ограниченная HTTP-модель запроса, совпадающая с контрактом модуля."""

    model_config = ConfigDict(extra='forbid')

    messages: list[ChatMessage] = Field(min_length=1, max_length=100)
    model: str | None = Field(default=None, min_length=1, max_length=100)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=65_536)
    top_p: float | None = Field(default=None, ge=0, le=1)


@router.post('/api/openai/chat/completions')
async def create_chat_completion(request: ChatCompletionRequest) -> dict[str, Any]:
    """Выполняет синхронный вызов вне event loop; доступ ограничивается доверенной сетью."""
    try:
        return await asyncio.to_thread(
            chat_completion,
            [message.model_dump() for message in request.messages],
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            top_p=request.top_p,
        )
    except OpenAIInputError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    except OpenAIConfigurationError:
        raise HTTPException(status_code=503, detail='OpenAI API не настроен на сервере.') from None
    except OpenAIAPIError:
        raise HTTPException(status_code=502, detail='Не удалось получить ответ от OpenAI API.') from None
