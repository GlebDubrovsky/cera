"""Настройки XMLStock; учётные данные берутся только из окружения."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class XMLStockSettings:
    """Серверные параметры авторизации и таймаута одного запроса."""

    user: str
    key: str
    timeout_seconds: float


class XMLStockConfigurationError(ValueError):
    """Настройки XMLStock отсутствуют или имеют неверный формат."""


def get_settings() -> XMLStockSettings:
    """Считывает актуальные настройки, не раскрывая их в диагностике."""
    user = os.getenv('XMLSTOCK_USER', '').strip()
    key = os.getenv('XMLSTOCK_KEY', '').strip()
    timeout_value = os.getenv('XMLSTOCK_TIMEOUT_SECONDS', '60').strip()

    if not user or not key:
        raise XMLStockConfigurationError('Не заданы серверные учётные данные XMLStock.')
    try:
        timeout_seconds = float(timeout_value)
    except ValueError:
        raise XMLStockConfigurationError('Таймаут XMLStock должен быть числом.') from None
    if not 0 < timeout_seconds <= 600:
        raise XMLStockConfigurationError('Таймаут XMLStock должен быть больше 0 и не более 600 секунд.')

    return XMLStockSettings(user=user, key=key, timeout_seconds=timeout_seconds)
