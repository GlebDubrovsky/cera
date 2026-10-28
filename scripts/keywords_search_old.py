# scripts/keywords_search.py

import os
import re
import time
import openai
import pandas as pd
from config.config import CONFIG_YANDEX_LOUD_API


# Количество пар ID:Название, которые отправляются в ИИ за один запрос.
BATCH_SIZE = 25

# Параметры Yandex Cloud для работы с DeepSeek.
YANDEX_CLOUD_FOLDER = CONFIG_YANDEX_LOUD_API['folder']
YANDEX_CLOUD_API_KEY = CONFIG_YANDEX_LOUD_API['api_key']
YANDEX_CLOUD_MODEL = CONFIG_YANDEX_LOUD_API['model']

# Максимальное количество токенов на ответ.
MAX_OUTPUT_TOKENS = 5000

# Название итогового столбца с ключевой фразой.
RESULT_COLUMN = "Ключевая фраза"

# Обязательные столбцы, которые должны быть во входящей таблице.
REQUIRED_COLUMNS = [
    "Название",
    "Символьный код",
    "Детальное описание",
    "ID",
    "Артикул",
    "Комплектация",
    "Характеристики",
]


def _get_client():
    """
    Создаёт и возвращает OpenAI-клиент, настроенный на Yandex Cloud.
    """
    return openai.OpenAI(
        api_key=YANDEX_CLOUD_API_KEY,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=YANDEX_CLOUD_FOLDER,
    )


def _id_to_str(value):
    """
    Приводит ID к строке.

    Это нужно, потому что pandas может прочитать ID как число,
    а ответ нейросети мы сравниваем как строку.
    """
    if pd.isna(value):
        return ""

    # Если ID прочитался как float вида 123.0, делаем из него "123".
    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    return str(value).strip()


def _text_to_one_line(value):
    """
    Приводит текст к одной строке.

    Убирает переносы строк и лишние пробелы, чтобы не ломать
    формат построчной отправки в промпт.
    """
    if pd.isna(value):
        return ""

    text = str(value)
    text = text.replace("\r", " ")
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def _prepare_work_df(work_df):
    """
    Подготавливает DataFrame:
    - проверяет обязательные столбцы;
    - оставляет только нужные столбцы;
    - нормализует ID и названия.
    """
    df = work_df.copy()

    # Убираем лишние пробелы в названиях столбцов.
    df.columns = [str(column).strip() for column in df.columns]

    # Проверяем, что все обязательные столбцы присутствуют.
    missing_columns = [
        column for column in REQUIRED_COLUMNS
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            "В таблице отсутствуют обязательные столбцы: "
            f"{', '.join(missing_columns)}"
        )

    # Оставляем только нужные столбцы.
    # Всё лишнее не попадает в итоговый файл.
    df = df[REQUIRED_COLUMNS].copy()

    # Приводим служебные значения к удобному виду.
    df["ID"] = df["ID"].map(_id_to_str)
    df["Название"] = df["Название"].map(_text_to_one_line)

    # Если ID пустые во всех строках, обрабатывать нечего.
    if df["ID"].str.strip().eq("").all():
        raise ValueError("В столбце ID нет значений.")

    return df


def _make_unique_records(df):
    """
    Собирает уникальные пары ID:Название.

    Если ID повторяется, берём первую непустую пару.
    Пустые ID или пустые названия не отправляем.
    """
    unique_records = {}

    for row_id, row_name in zip(df["ID"], df["Название"]):
        row_id = row_id.strip()
        row_name = row_name.strip()

        # Пропускаем строки без ID или без названия.
        if not row_id or not row_name:
            continue

        # Если ID уже встречался, не перезаписываем его.
        if row_id not in unique_records:
            unique_records[row_id] = row_name

    # Возвращаем список кортежей вида [("123", "Название"), ...]
    return list(unique_records.items())


def _build_prompt(pattern_prompt, product_lines):
    """
    Подставляет список товаров в шаблон промпта.

    В шаблоне обязательно должна быть конструкция:
    {{product_list}}
    """
    if "{{product_list}}" not in pattern_prompt:
        raise ValueError(
            "В шаблоне промпта не найдена конструкция {{product_list}}."
        )

    # Каждая пара ID:Название должна быть на новой строке.
    product_list_text = "\n".join(product_lines)

    return pattern_prompt.replace("{{product_list}}", product_list_text)


def _clean_answer_line(line):
    """
    Очищает одну строку ответа нейросети.

    Ожидаемый формат:
    id:ключевая фраза

    Также пытаемся пережить простые мусорные варианты:
    - 123: фраза
    * 123: фраза
    `123: фраза`
    "123": фраза
    """
    line = line.strip()

    # Пропускаем пустые строки и служебные блоки кода.
    if not line:
        return None

    # Удаляем возможные обратные кавычки по краям.
    line = line.strip("`").strip()

    if line.startswith("```"):
        return None

    # В строке должен быть разделитель ID и фразы.
    if ":" not in line:
        return None

    left, right = line.split(":", 1)

    # Чистим левую часть, где должен быть ID.
    # Удаляем возможные маркеры списка и прочие символы в начале.
    left = re.sub(
        r"^[^\w\-]+",
        "",
        left.strip(),
        flags=re.UNICODE
    )

    left = left.strip()
    left = left.strip('"')
    left = left.strip("'")
    left = left.strip()

    # Чистим правую часть с ключевой фразой.
    right = right.strip()
    right = right.strip('"')
    right = right.strip("'")
    right = right.strip()

    if not left or not right:
        return None

    return left, right


def _parse_ai_answer(text, expected_ids):
    """
    Разбирает ответ нейросети.

    Ожидаем строки вида:
    123:ключевая фраза

    Возвращаем словарь:
    {
        "123": "ключевая фраза",
        ...
    }
    """
    result = {}
    expected_ids = set(expected_ids)

    for raw_line in text.splitlines():
        cleaned_line = _clean_answer_line(raw_line)

        if not cleaned_line:
            continue

        answer_id, phrase = cleaned_line

        # Самый простой вариант: нейросеть вернула ID как есть.
        if answer_id in expected_ids:
            result[answer_id] = phrase
            continue

        # Запасной вариант: ищем ожидаемый ID внутри левой части.
        # Например, если пришло "ID 123" или "123.".
        for expected_id in expected_ids:
            if not expected_id:
                continue

            pattern = rf"(?<!\w){re.escape(expected_id)}(?!\w)"

            if re.search(pattern, answer_id):
                result[expected_id] = phrase
                break

    return result


def _call_yandex_ai(prompt, client):
    """
    Отправляет запрос в Yandex Cloud (модель DeepSeek) и возвращает текст ответа.

    Используется OpenAI-совместимый интерфейс Yandex Cloud.
    """
    try:
        response = client.responses.create(
            model=f"gpt://{YANDEX_CLOUD_FOLDER}/{YANDEX_CLOUD_MODEL}",
            temperature=0,
            instructions="",
            input=prompt,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            store=False,
            reasoning={"effort": "none"},
        )
    except openai.OpenAIError as exc:
        # Пробрасываем ошибку выше, чтобы её обработал _process_batch.
        raise RuntimeError(f"Ошибка запроса к Yandex Cloud: {exc}") from exc

    # Ответ лежит в поле output_text.
    return response.output_text or ""


def _process_batch(batch_records, pattern_prompt, client, max_tries=3):
    """
    Обрабатывает одну пачку товаров.

    batch_records: список кортежей [("123", "Название"), ...]
    """
    batch_ids = [item[0] for item in batch_records]
    expected_ids = set(batch_ids)

    # Строки для промпта вида "123:Название".
    product_lines = [
        f"{item[0]}:{item[1]}"
        for item in batch_records
    ]

    result = {}

    for attempt in range(1, max_tries + 1):
        # Определяем, для каких ID ещё нет ответа.
        missing_ids = expected_ids - set(result.keys())

        if not missing_ids:
            return result

        # На повторных попытках отправляем только недостающие ID.
        lines_for_prompt = [
            line for line in product_lines
            if line.split(":", 1)[0] in missing_ids
        ]

        prompt = _build_prompt(pattern_prompt, lines_for_prompt)

        # Для повторной попытки добавляем небольшое уточнение.
        if attempt > 1:
            prompt += (
                "\n\n"
                "Верни только недостающие строки в формате id:ключевая фраза."
            )

        try:
            answer_text = _call_yandex_ai(prompt, client)
        except RuntimeError:
            # Если это последняя попытка, пробрасываем ошибку выше.
            if attempt == max_tries:
                raise

            # Небольшая пауза перед повтором.
            time.sleep(2)
            continue

        # Разбираем ответ и добавляем найденные фразы.
        parsed_answer = _parse_ai_answer(answer_text, missing_ids)
        result.update(parsed_answer)

        # Если получили все ID, выходим.
        if expected_ids <= set(result.keys()):
            return result

        # Пауза перед следующей попыткой.
        time.sleep(2)

    # Если дошли сюда, значит часть ID так и не получили.
    missing_ids = sorted(expected_ids - set(result.keys()))

    raise RuntimeError(
        "Не получили ключевые фразы для ID: "
        f"{', '.join(missing_ids)}"
    )


def get_keywords(work_df, pattern_prompt):
    """
    Основная функция модуля.

    Принимает:
    - work_df: pandas.DataFrame с таблицей товаров;
    - pattern_prompt: строка с шаблоном промпта.

    Возвращает:
    - pandas.DataFrame с обязательными столбцами и столбцом "Ключевая фраза".
    """
    # Создаём клиента один раз и переиспользуем для всех батчей.
    client = _get_client()

    # Подготавливаем таблицу и проверяем обязательные столбцы.
    df = _prepare_work_df(work_df)

    # Собираем уникальные пары ID:Название.
    records = _make_unique_records(df)

    # Если отправлять нечего, просто возвращаем таблицу с пустым столбцом.
    if not records:
        df[RESULT_COLUMN] = ""
        return df

    phrases_by_id = {}

    # Режем список товаров на пачки по BATCH_SIZE.
    for start in range(0, len(records), BATCH_SIZE):
        batch_records = records[start:start + BATCH_SIZE]

        # Обрабатываем одну пачку.
        batch_result = _process_batch(
            batch_records=batch_records,
            pattern_prompt=pattern_prompt,
            client=client,
        )

        phrases_by_id.update(batch_result)

        # Небольшая пауза между пачками, чтобы не перегружать API.
        if start + BATCH_SIZE < len(records):
            time.sleep(1)

    # Добавляем ключевые фразы в исходную таблицу по ID.
    df[RESULT_COLUMN] = df["ID"].map(phrases_by_id).fillna("")

    return df


def read_prompt_file(prompt_path):
    """
    Читает файл шаблона промпта.
    """
    with open(prompt_path, "r", encoding="utf-8") as file:
        pattern = file.read().strip()

    if not pattern:
        raise ValueError("Файл шаблона промпта пустой.")

    return pattern


def keywords_search(file_path, prompt_path):
    """
    Точка входа для модуля.

    Принимает пути к файлам:
    - file_path: Excel-файл с товарами;
    - prompt_path: файл с шаблоном промпта.

    Возвращает готовый DataFrame.
    """
    # Читаем Excel-файл.
    work_df = pd.read_excel(file_path)

    # Читаем шаблон промпта.
    pattern_prompt = read_prompt_file(prompt_path)

    # Запускаем подбор ключевых фраз.
    return get_keywords(work_df, pattern_prompt)