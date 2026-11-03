"""Реестр кодовых сценариев, составляемых из XMLRiver-модулей.

Сценарии намеренно остаются пустыми до появления конкретных бизнес-процессов.
Каждый сценарий в дальнейшем сможет вызывать общий ``run_module`` и получать
те же проверки и формат результатов, что и веб-интерфейс.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Scenario = Callable[..., Any]
SCENARIOS: dict[str, Scenario] = {}
