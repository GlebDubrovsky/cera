"""Разбор фраз из веб-форм и XLSX-файлов."""

from __future__ import annotations

from io import BytesIO

from openpyxl import load_workbook


class PhraseInputError(ValueError):
    """Ошибка формата или содержимого пользовательского списка фраз."""


def parse_phrases(
    text: str | None,
    uploaded_filename: str | None = None,
    uploaded_content: bytes | None = None,
) -> list[str]:
    """Возвращает непустые фразы ровно из одного выбранного источника."""
    has_text = bool((text or "").strip())
    has_file = bool(uploaded_filename)
    if has_text and has_file:
        raise PhraseInputError("Укажи фразы либо в списке, либо загрузи XLSX-файл — не оба источника сразу.")
    if not has_text and not has_file:
        raise PhraseInputError("Добавь фразы в поле списка или загрузи XLSX-файл.")

    if has_text:
        phrases = [line.strip() for line in (text or "").splitlines() if line.strip()]
    else:
        if not uploaded_filename or not uploaded_filename.lower().endswith(".xlsx"):
            raise PhraseInputError("Поддерживается только файл .xlsx с колонкой phrase.")
        if not uploaded_content:
            raise PhraseInputError("Загруженный XLSX-файл пуст.")
        workbook = None
        try:
            workbook = load_workbook(BytesIO(uploaded_content), read_only=True, data_only=True)
            worksheet = workbook.active
            header_row = next(worksheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
            headers = [str(value).strip().lower() if value is not None else "" for value in header_row]
            if "phrase" not in headers:
                raise PhraseInputError('В XLSX-файле должна быть колонка с заголовком "phrase".')
            phrase_column = headers.index("phrase")
            phrases = [
                str(row[phrase_column]).strip()
                for row in worksheet.iter_rows(min_row=2, values_only=True)
                if len(row) > phrase_column and row[phrase_column] is not None and str(row[phrase_column]).strip()
            ]
        except PhraseInputError:
            raise
        except Exception as error:
            raise PhraseInputError("Не удалось прочитать XLSX-файл. Проверь его формат и содержимое.") from error
        finally:
            if workbook is not None:
                workbook.close()

    if not phrases:
        raise PhraseInputError("В выбранном источнике не найдено ни одной фразы.")
    return phrases
