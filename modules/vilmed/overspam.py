"""Обработка overspam Vilmed с использованием справочника PostgreSQL."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pandas as pd
from pymorphy3 import MorphAnalyzer
from sqlalchemy import Engine

from modules.vilmed.repository import list_vilmed_reference_categories


def overspam_vilmed(input_file: str | Path, chat_id: str, engine: Engine) -> pd.DataFrame | None:
    """Сопоставляет слова релевантности с названиями Vilmed из PostgreSQL.

    Загруженная книга содержит условия обработки, а справочник берётся из базы.
    Функция возвращает DataFrame с прежними русскими названиями столбцов, чтобы
    HTTP-адаптер мог сохранить результат в XLSX без изменения формата.
    """
    print("[VILMED][OVERSPAM][START] Начата обработка входного файла", flush=True)
    try:
        if not os.path.isfile(input_file):
            print("[VILMED][INPUT][ERROR] Входной файл не найден", flush=True)
            return None

        morph = MorphAnalyzer()

        def normalize_word(word: object) -> str:
            normalized_input = str(word).strip().lower()
            if not normalized_input:
                return ""
            try:
                return morph.parse(normalized_input)[0].normal_form
            except (IndexError, TypeError, AttributeError):
                return normalized_input

        # Этап 1: читаем книгу с условиями релевантности и лимитами совпадений.
        relevance_df = pd.read_excel(input_file, header=1)
        required_columns = {"Удалить", "Слово"}
        if not required_columns.issubset(relevance_df.columns):
            raise ValueError("Входная таблица не содержит обязательные столбцы")

        relevance_df["Удалить"] = relevance_df["Удалить"].apply(
            lambda value: int(str(value).split("-")[-1])
        )
        relevance_df = relevance_df[relevance_df["Удалить"] != 0]
        relevance_words: dict[str, int] = {}
        for _, row in relevance_df.iterrows():
            word = normalize_word(row["Слово"])
            if word:
                relevance_words[word] = int(row["Удалить"])
        print(
            f"[VILMED][INPUT][SUCCESS] Загружено условий: {len(relevance_words)}",
            flush=True,
        )

        # Этап 2: читаем подготовленный справочник через репозиторий модуля.
        reference_df = list_vilmed_reference_categories(engine)
        if reference_df.empty:
            print("[VILMED][DATABASE][ERROR] Справочная таблица пуста", flush=True)
            return None
        print(
            f"[VILMED][DATABASE][SUCCESS] Прочитано записей: {len(reference_df)}",
            flush=True,
        )

        # Этап 3: нормализуем названия заранее, чтобы не повторять морфологический разбор.
        processed_data: list[dict[str, object]] = []
        for _, row in reference_df.iterrows():
            title = str(row["Название"])
            clean_title = re.sub(r"[^\w\s]", " ", title).lower()
            normalized_words = {
                normalized_word
                for token in clean_title.split()
                if (normalized_word := normalize_word(token))
            }
            processed_data.append(
                {
                    "id": row["ID раздела"],
                    "title": title,
                    "words": normalized_words,
                }
            )

        # Этап 4: сохраняем прежний лимит первого совпадения и формат XLSX.
        results: list[dict[str, object]] = []
        for word, max_count in relevance_words.items():
            matched_count = 0
            for item in processed_data:
                if word in item["words"]:
                    results.append({"Название": item["title"], "ID": item["id"]})
                    matched_count += 1
                    if matched_count >= max_count:
                        break

        result_df = pd.DataFrame(results, columns=["Название", "ID"])
        if not result_df.empty:
            result_df = result_df.drop_duplicates(subset=["ID"])

        temp_dir = Path(__file__).resolve().parents[2] / "temp_files" / f"temp_for_{chat_id}"
        if not result_df.empty and temp_dir.is_dir():
            result_df.to_excel(temp_dir / "overspam_vilmed_list.xlsx", index=False)

        print(
            f"[VILMED][OVERSPAM][SUCCESS] Сформировано строк: {len(result_df)}",
            flush=True,
        )
        return result_df
    except Exception:
        print(
            "[VILMED][OVERSPAM][ERROR] Обработка завершилась ошибкой",
            flush=True,
        )
        return None
