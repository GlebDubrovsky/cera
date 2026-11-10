"""HTTP-адаптер для запросов к инструментам XMLStock."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from modules.xmlstock import (
    XMLStockAPIError,
    XMLStockConfigurationError,
    XMLStockInputError,
    request_xmlstock,
)
from shared.log_stream import run_with_log_capture

router = APIRouter()


class XMLStockRequest(BaseModel):
    """Входной контракт для режима, метода и именованных параметров API."""

    model_config = ConfigDict(extra='forbid')

    params: dict[str, Any] = Field(default_factory=dict, max_length=20)
    output_format: str = Field(default='xml', max_length=10)
    method: str = Field(default='GET', max_length=10)
    log_id: UUID | None = None


@router.post('/api/xmlstock/{tool}')
async def execute_xmlstock_request(tool: str, request: XMLStockRequest) -> dict[str, Any]:
    """Запускает единый публичный клиент вне event loop и безопасно отображает ошибки."""
    try:
        return await asyncio.to_thread(
            run_with_log_capture,
            str(request.log_id) if request.log_id else '',
            request_xmlstock,
            tool,
            request.params,
            output_format=request.output_format,
            method=request.method,
        )
    except XMLStockInputError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    except XMLStockConfigurationError:
        raise HTTPException(status_code=503, detail='XMLStock не настроен на сервере.') from None
    except XMLStockAPIError:
        raise HTTPException(status_code=502, detail='Не удалось получить ответ от XMLStock.') from None
