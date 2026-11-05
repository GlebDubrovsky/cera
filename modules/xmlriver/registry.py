"""Реестр доступных XMLRiver-модулей и параметров их запуска."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from modules.xmlriver.xmlriver_frequency import fetch_frequencies
from modules.xmlriver.xmlriver_popular import fetch_popular_queries
from modules.xmlriver.xmlriver_serp import fetch_search_results


ModuleFunction = Callable[..., list[dict[str, Any]]]


@dataclass(frozen=True)
class ModuleSpec:
    """Описание пользовательского модуля, пригодное для веб-форм и сценариев."""

    module_id: str
    title: str
    function: ModuleFunction
    settings: Mapping[str, Any]


MODULES: dict[str, ModuleSpec] = {
    "frequency": ModuleSpec("frequency", "Сбор частот", fetch_frequencies, {}),
    "popular": ModuleSpec("popular", "Сбор фраз", fetch_popular_queries, {}),
    "serp": ModuleSpec("serp", "ТОП конкурентов", fetch_search_results, {}),
}


def get_module(module_id: str) -> ModuleSpec:
    """Возвращает описание модуля или отклоняет неизвестный идентификатор."""
    try:
        return MODULES[module_id]
    except KeyError as error:
        raise ValueError("Неизвестный модуль XMLRiver.") from error
