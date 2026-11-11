"""Формирование XLSX-отчётов для результатов XMLRiver."""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

from config.config import XMLRIVER_KEY, XMLRIVER_USER


def _safe_cell(value: Any) -> str | int | float | bool | None:
    """Убирает учётные данные и блокирует интерпретацию текста как формулы."""
    if value is None or isinstance(value, (int, float, bool)):
        return value
    text = str(value)
    for secret in (XMLRIVER_KEY, XMLRIVER_USER):
        if secret:
            text = text.replace(secret, "[скрыто]")
    if text[:1] in {"=", "+", "-", "@"}:
        return "'" + text
    return text


def _safe_error(value: Any) -> str:
    """Сохраняет сведения об ошибке, скрывая URL, которые могут содержать ключи."""
    message = str(value or "")
    return re.sub(r"https?://\S+", "[URL скрыт]", message)


def _rows_for_result(module_id: str, result: Mapping[str, Any]) -> Iterable[list[Any]]:
    phrase = result.get("phrase", "")
    error = _safe_error(result.get("error"))
    if module_id == "frequency":
        if "phrasal_value" in result:
            yield [phrase, result.get("total_value"), result.get("phrasal_value")]
        else:
            yield [phrase, result.get("total_value"), error]
    elif module_id == "popular":
        popular_items = result.get("popular") or []
        if not popular_items:
            yield [phrase, "", "", error]
        for item in popular_items:
            if isinstance(item, Mapping):
                popular_phrase = item.get("text", item.get("phrase", item.get("query", item.get("word", ""))))
                value = item.get("totalValue", item.get("value", item.get("count", "")))
            else:
                popular_phrase, value = item, ""
            yield [phrase, popular_phrase, value, error]
    elif module_id in {"serp", "google_serp"}:
        search_results = result.get("results") or []
        if not search_results:
            yield [phrase, "", "", "", error]
        for item in search_results:
            yield [phrase, item.get("position", ""), item.get("url", ""), item.get("title", ""), item.get("snippet", ""), error]
    else:
        raise ValueError("Неизвестный модуль XMLRiver для XLSX-экспорта.")


def write_results_xlsx(path: str | Path, module_id: str, results: Sequence[Mapping[str, Any]]) -> Path:
    """Сохраняет табличный XLSX с отдельными строками для вложенных результатов."""
    headers = {
        "frequency": ["phrase", "total_value", "error"],
        "popular": ["phrase", "popular_phrase", "value", "error"],
        "serp": ["phrase", "position", "url", "title", "snippet", "error"],
        "google_serp": ["phrase", "position", "url", "title", "snippet", "error"],
    }
    if module_id not in headers:
        raise ValueError("Неизвестный модуль XMLRiver для XLSX-экспорта.")
    if module_id == "frequency" and any("phrasal_value" in result for result in results):
        headers["frequency"] = ["phrase", "total_value", "phrasal_value"]

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = module_id
    worksheet.append(headers[module_id])
    for cell in worksheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="0D6EFD")
    for result in results:
        for row in _rows_for_result(module_id, result):
            worksheet.append([_safe_cell(value) for value in row])
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    workbook.save(output_path)
    workbook.close()
    return output_path


def append_phrasal_values_xlsx(
    path: str | Path,
    source_content: bytes,
    results: Sequence[Mapping[str, Any]],
) -> Path:
    """Добавляет phrasal_value к исходному листу, не перестраивая остальные столбцы."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = load_workbook(BytesIO(source_content))
    values_workbook = load_workbook(BytesIO(source_content), read_only=True, data_only=True)
    try:
        worksheet = workbook.active
        values_worksheet = values_workbook[worksheet.title]
        header_row = next(values_worksheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
        headers = [str(value).strip().lower() if value is not None else "" for value in header_row]
        if "phrase" not in headers:
            raise ValueError('В XLSX-файле должна быть колонка с заголовком "phrase".')

        phrase_column = headers.index("phrase")
        output_column = worksheet.max_column + 1
        worksheet.cell(row=1, column=output_column, value="phrasal_value")
        result_iterator = iter(results)
        for row_number, row in enumerate(values_worksheet.iter_rows(min_row=2, values_only=True), start=2):
            if phrase_column >= len(row) or row[phrase_column] is None or not str(row[phrase_column]).strip():
                continue
            result = next(result_iterator, None)
            if result is None:
                raise ValueError("Количество результатов не совпадает с числом фраз в XLSX.")
            worksheet.cell(row=row_number, column=output_column, value=_safe_cell(result.get("phrasal_value")))

        if next(result_iterator, None) is not None:
            raise ValueError("Количество результатов не совпадает с числом фраз в XLSX.")
        worksheet.auto_filter.ref = worksheet.dimensions
        workbook.save(output_path)
    finally:
        workbook.close()
        values_workbook.close()
    return output_path
