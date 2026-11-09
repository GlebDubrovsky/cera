"""Безопасное формирование четырёх XLSX-отчётов анализатора."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable

from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from modules.relevance_analyzer.relevance import Relevance

TITLE = 'Анализ релевантности — Титло'
REPORTS = (
    'Рекомендации TLP и проверка на спам.xlsx',
    'Топ лист фраз (TLP).xlsx',
    'Топ лист словосочетаний (TLPs).xlsx',
    'Проанализированные сайты.xlsx',
)


def _safe_cell(value: Any) -> Any:
    """Сохраняет типы чисел и сериализует ввод, похожий на формулу, как текст."""
    if value is None or isinstance(value, (int, float, bool)):
        return value
    text = str(value)
    if text.lstrip()[:1] in {'=', '+', '-', '@'}:
        return "'" + text
    return text


def _occurrence_text(occurrences: dict[str, int]) -> str:
    return ''.join(f'{domain}({count})' for domain, count in occurrences.items())


def _median_ceil(values: list[int]) -> int:
    ordered = sorted(values)
    if not ordered:
        return 0
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    return int(math.ceil(median))


def _tf_idf_for_target(frequency: int, word_count: int) -> tuple[float, float]:
    tf = frequency / word_count if word_count else 0.0
    idf = math.log10(word_count / frequency) if word_count and frequency else 0.0
    return tf, idf


def build_recommendations(result: Relevance) -> list[list[Any]]:
    return [
        [word, values['tf'], values['avg'], values['on_page'], values['diapason'],
         values['spam'], values['add'], values['remove']]
        for word, values in result.recommendations.items()
    ]


def build_tlp(result: Relevance) -> list[list[Any]]:
    rows = []
    word_count = max(result.count_words_in_my_page, 1)
    for word_form in result.word_forms.values():
        for word, form in word_form.items():
            if word == 'total':
                continue
            frequency = form['total_repeat_main_page']
            tf, idf = _tf_idf_for_target(frequency, word_count)
            rows.append([
                word, round(form['tf'], 4), round(tf, 4), round(form['tf'] * form['idf'], 4),
                round(tf * idf, 4), f"{form['number_occurrences']} {_occurrence_text(form['occurrences'])}",
                form['re_spam'], form['avg_in_total_competitors'], frequency, form['avg_in_text'],
                form['repeat_in_text_main_page'], form['avg_in_link'], form['repeat_in_link_main_page'],
            ])
    return sorted(rows, key=lambda row: -row[1])


def build_tlps(result: Relevance) -> list[list[Any]]:
    rows = []
    word_count = max(result.count_words_in_my_page, 1)
    for phrase, form in result.phrases.items():
        frequency = form['total_repeat_main_page']
        tf, idf = _tf_idf_for_target(frequency, word_count)
        rows.append([
            phrase, round(form['tf'], 4), round(tf, 4), round(form['tf'] * form['idf'], 4),
            round(tf * idf, 4), f"{form['number_occurrences']} {_occurrence_text(form['occurrences'])}",
            _median_ceil(list(form['occurrences'].values())), form['avg_in_total_competitors'], frequency,
        ])
    return rows


def build_sites(result: Relevance) -> list[list[Any]]:
    rows = []
    for site in result.sites.values():
        position = 'не в топе' if site['main_page'] else site['position']
        rows.append([
            position, site['site'], site['main_points'], site['coverage'], site['coverage_tf'],
            site['width'], site['density']['density_main_percent'], site['count_symbols'],
            'Не удалось получить данные' if site['danger'] else 'Страница успешно проанализирована',
        ])
    return rows


def _write_sheet(worksheet: Worksheet, headers: list[str], rows: Iterable[list[Any]], shift: int = 0) -> None:
    worksheet.cell(row=1, column=1, value=TITLE)
    for column, header in enumerate(headers, start=shift + 1):
        worksheet.cell(row=2, column=column, value=header)
    for row_number, row in enumerate(rows, start=3):
        for column, value in enumerate(row, start=shift + 1):
            worksheet.cell(row=row_number, column=column, value=_safe_cell(value))


def _save_report(path: Path, headers: list[str], rows: list[list[Any]], shift: int = 0) -> None:
    workbook = Workbook()
    try:
        _write_sheet(workbook.active, headers, rows, shift)
        workbook.save(path)
    finally:
        workbook.close()


def export_xlsx(result: Relevance, out_dir: str | Path) -> list[Path]:
    """Записывает отдельные исходные отчёты и возвращает их пути."""
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_data = [
        (['Слово', 'Tf', 'Среднее кол-во повторений у конкурентов', 'Количество у вас на странице',
          'Рекомендуемый диапазон', 'Уровень спама', 'Добавить', 'Удалить'], build_recommendations(result), 1),
        (['Слова', 'TF-IDF ТОП', 'TF-IDF ваш сайт', 'BM25 ТОП', 'BM25 ваш сайт', 'Пересечение', 'Переспам',
          'Среднее количество повторений в тексте и ссылках', 'Общее количество повторений в тексте и ссылках',
          'Среднее количество повторений в тексте', 'Количество повторений в тексте',
          'Среднее количество повторений в ссылках', 'Количество повторений в ссылках'], build_tlp(result), 0),
        (['Фраза', 'TF-IDF ТОП', 'TF-IDF ваш сайт', 'BM25 ТОП', 'BM25 ваш сайт', 'Кол-во сайтов',
          'Медианное вхождение', 'Среднее', 'На нашем сайте'], build_tlps(result), 0),
        (['Позиция в топе', 'Посадочная страница', 'Общий балл', 'Охват по всем важным словам',
          'Охват по tf', 'Ширина', 'Плотность', 'Символов', 'Результат'], build_sites(result), 0),
    ]
    paths = [output_dir / name for name in REPORTS]
    for path, (headers, rows, shift) in zip(paths, report_data, strict=True):
        _save_report(path, headers, rows, shift)
    return paths
