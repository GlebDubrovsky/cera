"""Публичный интерфейс клиента XMLStock."""

from modules.xmlstock.service import (
    XMLStockAPIError,
    XMLStockConfigurationError,
    XMLStockInputError,
    request_xmlstock,
)

__all__ = [
    'XMLStockAPIError',
    'XMLStockConfigurationError',
    'XMLStockInputError',
    'request_xmlstock',
]
