"""Тестовый запуск сбора поисковой выдачи Яндекса через XMLRiver."""

import csv
import sys
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

# Скрипт поддерживает прямой запуск из каталога проекта.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.config import XMLRIVER_KEY as API_KEY
from config.config import XMLRIVER_USER as USER_ID
from modules.xmlriver.settings import SEARCH_SETTINGS, TOP_N
from modules.xmlriver.xmlriver_serp import fetch_search_results

PHRASES_FILE = Path(__file__).with_name("phrases.xlsx")
SERP_OUTPUT_FILE = Path(__file__).with_name("search_results.csv")


# Сбор популярных запросов предыдущим модулем временно отключён:
# from xmlriver_popular import fetch_popular_queries

# Сбор частотности также отключён:
# from xmlriver_frequency import fetch_frequencies

_XML_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def load_phrases_from_xlsx(file_path: Path) -> list[str]:
    """Считывает фразы из колонки A файла XLSX с заголовком phrase."""
    try:
        with ZipFile(file_path) as workbook:
            parts = set(workbook.namelist())
            sheet = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in parts:
                strings_root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
                shared_strings = [
                    "".join(text.text or "" for text in item.iter(f"{_XML_NS}t"))
                    for item in strings_root.findall(f"{_XML_NS}si")
                ]
    except (BadZipFile, OSError, KeyError, ET.ParseError) as error:
        raise SystemExit(f"Не удалось прочитать Excel-файл {file_path}: {error}") from error

    def cell_text(cell: ET.Element | None) -> str:
        if cell is None:
            return ""
        if cell.get("t") == "inlineStr":
            return "".join(text.text or "" for text in cell.iter(f"{_XML_NS}t"))
        value = cell.find(f"{_XML_NS}v")
        if value is None or value.text is None:
            return ""
        if cell.get("t") == "s":
            try:
                return shared_strings[int(value.text)]
            except (ValueError, IndexError) as error:
                raise SystemExit("В Excel-файле повреждён список общих строк.") from error
        return value.text

    rows = sheet.findall(f".//{_XML_NS}row")
    first_cell = next((cell for cell in rows[0].findall(f"{_XML_NS}c") if cell.get("r") == "A1"), None) if rows else None
    if cell_text(first_cell).strip().lower() != "phrase":
        raise SystemExit(f"В файле {file_path} в ячейке A1 должен быть заголовок phrase.")

    phrases = []
    for row in rows[1:]:
        row_number = row.get("r", "")
        cell = next((item for item in row.findall(f"{_XML_NS}c") if item.get("r") == f"A{row_number}"), None)
        phrase = cell_text(cell).strip()
        if phrase:
            phrases.append(phrase)
    if not phrases:
        raise SystemExit(f"В файле {file_path} нет фраз для обработки.")
    return phrases


def main() -> None:
    missing_variables = [
        name
        for name, value in (("XMLRIVER_USER", USER_ID), ("XMLRIVER_KEY", API_KEY))
        if not value
    ]
    if missing_variables:
        missing = ", ".join(missing_variables)
        raise SystemExit(
            f"Не найдены или пусты переменные: {missing}. "
            "Проверьте их в .env рядом с run_test.py или задайте в среде запуска."
        )

    print("[XMLRIVER][INPUT][START] Чтение фраз из XLSX.", flush=True)
    phrases = load_phrases_from_xlsx(PHRASES_FILE)
    print(f"[XMLRIVER][INPUT][SUCCESS] Загружено фраз: {len(phrases)}.", flush=True)

    # Запуск сбора частотности отключён:
    # frequency_results = fetch_frequencies(
    #     phrases, user_id=USER_ID, api_key=API_KEY, settings=SETTINGS
    # )

    # Запуск сбора популярных запросов предыдущим модулем отключён:
    # popular_results = fetch_popular_queries(
    #     phrases, user_id=USER_ID, api_key=API_KEY, settings=SETTINGS
    # )

    print(f"[XMLRIVER][SERP][START] Сбор ТОП-{TOP_N} для {len(phrases)} фраз.", flush=True)
    results = []
    for index, phrase in enumerate(phrases, start=1):
        print(f"[XMLRIVER][SERP][PROGRESS] Обработка фразы {index}/{len(phrases)}.", flush=True)
        result = fetch_search_results(
            [phrase],
            user_id=USER_ID,
            api_key=API_KEY,
            top_n=TOP_N,
            settings=SEARCH_SETTINGS,
        )[0]
        results.append(result)
        if result["error"]:
            print(f"[XMLRIVER][SERP][ERROR] Для фразы {index} данные недоступны.", flush=True)
        else:
            print(
                f"[XMLRIVER][SERP][SUCCESS] Получено результатов: {len(result['results'])}.",
                flush=True,
            )

    output_rows = sum(max(len(result["results"]), 1) for result in results)
    print(f"[XMLRIVER][EXPORT][START] Запись {output_rows} строк в CSV.", flush=True)
    with SERP_OUTPUT_FILE.open("w", newline="", encoding="utf-8-sig") as csv_file:
        columns = ["phrase", "position", "url", "title", "snippet"]
        writer = csv.DictWriter(csv_file, fieldnames=columns)
        writer.writeheader()
        for result in results:
            if not result["results"]:
                writer.writerow({"phrase": result["phrase"]})
                continue
            for search_result in result["results"]:
                writer.writerow({
                    "phrase": result["phrase"],
                    "position": search_result["position"],
                    "url": search_result["url"],
                    "title": search_result["title"],
                    "snippet": search_result["snippet"],
                })

    print(f"[XMLRIVER][EXPORT][SUCCESS] Готово. Строк: {output_rows}.", flush=True)


if __name__ == "__main__":
    main()
