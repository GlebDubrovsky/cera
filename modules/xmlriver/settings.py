"""Настройки запусков XMLRiver; секреты загружаются общим конфигом приложения."""

from pathlib import Path

from config.config import XMLRIVER_KEY as API_KEY
from config.config import XMLRIVER_USER as USER_ID

# Настройки Wordstat New для повторного включения предыдущих модулей.
SETTINGS = {
    "regions": "",
    "device": "",
    "period": "",
    "start": "",
    "end": "",
}

# Параметры поисковой выдачи Яндекса.
# Для TOP 20 и TOP 30 модуль выполнит запросы на несколько страниц.
TOP_N = 10
SEARCH_SETTINGS = {
    "lr": "",           # ID региона Яндекса; пусто — настройка аккаунта XMLRiver
    "lang": "ru",       # язык результатов
    "domain": "ru",     # домен Яндекса
    "device": "desktop",  # desktop, tablet или mobile
    "filter": "",       # 1 — скрывать похожие результаты; пусто — настройка сервиса
}

# Файлы результатов разных режимов.
SERP_OUTPUT_FILE = Path(__file__).with_name("search_results.csv")
POPULAR_OUTPUT_FILE = Path(__file__).with_name("popular_queries.csv")
OUTPUT_FILE = Path(__file__).with_name("frequency_results.csv")
