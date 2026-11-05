# Скрипт для обновления страницы bar_tags в рабочих таблицах. 
# Данный скрипт не привязан к основной логике бота, работает автономно.
# Таблица загружается вручную в папку sourse

import pandas as pd
from bs4 import BeautifulSoup
import requests
import os
import hashlib
import pymorphy3
import re
import time

# Инициализация морфологического анализатора для русского языка с кэшированием
morph = pymorphy3.MorphAnalyzer(lang='ru')

pd.set_option('display.max_columns', None)


# обязательно учесть что кеш нужен только для тестовых запусков скрипта, для продакшн версии страницы должны парситься заново!!!
# когда функция кеша будет удалена, нужно обязательно проверять страницы на ошибку 404, особенно в функции scrape_direct_pages, так как ссылки из плитки могут быть битые (функцию кеша переделать под проверку на работоспособность)
# не забыть убрать ограничение строк
# продумать вариант с неудачным парсингом и где контролировать его
# название столбца address нужно перевести в нижний регистр

# продумать безотказность каждой функции

"""
============================ Общие константы и переменные ============================
"""


HEADERS = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
            'Connection': 'keep-alive',
        }


FILE_URL = 'sources/internal_all.xlsx'


CONFIG = {
            'almamed' : {
                            'domain_full_name' : 'https://almamed.su',
                            'path_cat' : '/category/',
                            'breadcrumbs_item' : '.breadcrumbs-plugin__item__label',
                            'h1' : '.title_h1.category-name',
                            'left_bar_tags' : '.tags-params-sidebar a',
                            'up_bar_tags' : '.tag-slider a',
                            'search_link_pattern' : '/search/',
                            'product_item' : 'ul.product-list a',    
                        },
            'vilmed' :  {
                            'domain_full_name' : 'https://vilmed.ru',
                            'path_cat' : '/catalog/',
                            'breadcrumbs_item' : '.breadcrumb__title',
                            'h1' : '#pagetitle',
                            'left_bar_tags' : '.tag_menu a',
                            'up_bar_tags' : '.tag-slider a',
                            'search_link_pattern' : r'/catalog/\?q=',
                            'product_item' : '#catalog a',
                            'submit_param' : '&submit=Найти'
                        },
            'gnkmed' :  {
                            'domain_full_name' : 'https://gnkmed.ru',
                            'path_cat' : '/catalog/',
                            'breadcrumbs_item' : 'li.breadcrumb__item:not(:first-child) span',
                            'h1' : 'h1.title',
                            'up_bar_tags' : '.tag-slider a',
                            'search_link_pattern' : r'/search/\?q=',
                            'product_item' : '.goods__list a.goods__name',
                            'links_type' : 'nested'
                        },
            'lorshop' : {
                            'domain_full_name' : 'https://lorshop.ru',
                            'path_cat' : '/catalog/',
                            'breadcrumbs_item' : 'li.breadcrumb__item:not(:first-child) span',
                            'h1' : 'h1.title',
                            'up_bar_tags' : '.tag-slider a',
                            'search_link_pattern' : r'/search/\?q=',
                            'product_item' : '.goods__list a.goods__name',
                            'links_type' : 'nested'
                        },
            'riester' : {
                            'domain_full_name' : 'https://riester.su',
                            'path_cat' : '/catalog/',
                            'breadcrumbs_item' : 'li.breadcrumb__item:not(:first-child) span',
                            'h1' : 'h1.title',
                            'up_bar_tags' : '.tag-slider a',
                            'search_link_pattern' : r'/search/\?q=',
                            'product_item' : '.goods__list a.goods__name',
                            'links_type' : 'nested'
                        }
}


PREPOSITIONS = ['под', 'над', 'перед', 'между', 'около', 'вдоль', 'через', 'без', 'для', 'про', 'ото', 'благодаря', 'вместо', 'поводу', 'связи', 'счёт']


"""
============================= Общие вспомогательные функции =============================
"""

def get_page_with_cache(url, HEADERS):
    """
    =======================================
    Функция для скачивания страниц с повторными попытками
    =======================================
    """
    max_retries = 5
    retry_delay = 2  # секунды
    
    for attempt in range(max_retries):
        try:
            print(f"[Попытка {attempt + 1}/{max_retries}] {url[:50]}...")
            
            response = requests.get(url, headers=HEADERS, timeout=10)
            
            if response.status_code == 200:
                return response.text
            else:
                print(f"   HTTP {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            print(f"   Ошибка: {e}")
        
        # Ждем перед повторной попыткой (кроме последней)
        if attempt < max_retries - 1:
            time.sleep(retry_delay * (attempt + 1))  # увеличиваем задержку с каждой попыткой
    
    raise Exception(f"Не удалось скачать страницу после {max_retries} попыток: {url}")


# def get_page_with_cache(url, HEADERS):
#     """
#     =======================================
#     Вспомогательная функция для кеширования (для отладки)
#     =======================================
#     """
#     # Создание папки для кеша в корневой директории
#     CACHE_DIR = 'cache'
#     if not os.path.exists(CACHE_DIR):
#         os.makedirs(CACHE_DIR)

#     # Создаем имя файла для кеша
#     filename = hashlib.md5(url.encode()).hexdigest()[:10]
#     cache_path = os.path.join(CACHE_DIR, f'{filename}.html')
    
#     # Пробуем прочитать из кеша
#     if os.path.exists(cache_path):
#         print(f"[КЕШ] {url[:40]}...")
#         with open(cache_path, 'r', encoding='utf-8') as f:
#             return f.read()
    
#     # Если кеша нет - скачиваем
#     print(f"[СЕТЬ] {url}")
#     response = requests.get(url, headers=HEADERS, timeout=(5, 30))
    
#     if response.status_code == 200:
#         # Сохраняем в кеш
#         with open(cache_path, 'w', encoding='utf-8') as f:
#             f.write(response.text)
#         return response.text
#     else:
#         raise Exception(f"HTTP {response.status_code}")



def clean_and_normalize(text):
    """
    ==============================================================
    Очищает текст и возвращает список слов в нормальной словоформе
    ==============================================================
    1. Проверяем текст на пустоту или NaN
    2. Переводим текст в нижний регистр, меняем 'ё' на 'е', удаляем знаки препинания и множественные пробелы
    3. Разбиваем текст по словам, убираем предлоги и короткие слова (<3 символов), приводим к нормальной форме
    4. Сортируем результат по алфавиту для последующего сравнения
    """
    try:
        """1. Проверяем текст на пустоту или NaN"""
        
        if pd.isna(text) or not str(text).strip():
            return []
        
        
        """2. Переводим текст в нижний регистр, меняем 'ё' на 'е', удаляем знаки препинания и множественные пробелы"""

        text = text.lower()
        text = str(text).replace('ё', 'е')
        text = re.sub(r'[^\w\s]', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        

        """3. Разбиваем текст по словам, убираем предлоги и короткие слова (<3 символов), приводим к нормальной форме"""

        result = []
        for word in text.split():
            # Убираем предлоги и слова короче 3 букв
            if word in PREPOSITIONS or len(word) < 3:
                continue
            
            normal_form = morph.parse(word)[0].normal_form
            if normal_form:
                result.append(normal_form)

        """4. Сортируем результат по алфавиту для последующего сравнения"""

        result = tuple(sorted(result))
        
        
        return result
    
    except Exception as e:
        print(f"❌ [ОШИБКА] Проблемы функции clean_and_normalize: {e}, текст: '{text[:50]}...'")
        return ()



def scrape_breadcrumbs(soup_obj, bc_item):
    """
    =====================================================================
    Парсинг названий главной и родительской категорий из хлебных крошек
    =====================================================================
    """
    try:

        breadcrumbs = soup_obj.select(bc_item)

        
        main_cat = breadcrumbs[1].get_text(strip=True) if len(breadcrumbs) > 1 else ""
        
        
        parent_cat = breadcrumbs[-2].text.strip() if len(breadcrumbs) > 3 else ""

        
        print(f"✅ [УСПЕШНО] Получены главная и родительская категории!")
        return main_cat, parent_cat

    except Exception as e:
        print(f"❌ [ОШИБКА] Проблемы функции scrape_breadcrumbs: {e}")
        return "", ""


"""
======================== Основной логический блок ========================
"""


def download_data_sheet(file_url):
    """
    ===================================================
    Загрузка файла в DataFrame и определение параметров
    ===================================================
    1. Загрузка файла в DataFrame
    2. Определение: рабочей таблицы, названия домена, полного названия домена, названия каталога
    """
    try:
        """1. Загрузка файла в DataFrame"""

        spider_sheet = pd.read_excel(file_url)


        """2. Определение: рабочей таблицы, названия домена, полного названия домена, названия каталога, конфигурацию"""

        for domain, domain_config in CONFIG.items():
            if spider_sheet['Address'].head(10).str.contains(domain).any():
                print(f"✅ [УСПЕШНО] Загружены данные, домен: {domain}")
                return (
                    spider_sheet,
                    domain,
                    domain_config
                )
            
        
        raise ValueError("Домен не найден в списке разрешенных")
        

    except Exception as e:
        print(f"❌ [ОШИБКА] Проблемы функции download_data_sheet: {e}")
        raise



def filter_links(spider_sheet, config_site):
    """
    =========================================
    Извлечение категорийных ссылок из таблицы
    =========================================
    1. Фильтрация по статусу кода и сегменту пути (название папки каталога), количеству слешей (опционально)

    """
    try:
        
        """1. Фильтрация по статусу кода и сегменту пути (название папки каталога), количеству слешей (опционально)"""

        status_filter = spider_sheet['Status Code'] == 200
        pattern_filter = spider_sheet['Address'].str.contains(config_site['path_cat'])
        
        # Фильтрация по количеству слешей, так как у некоторых сайтов ссылки на товары вложенные, а не разделенные на /catalog/ и /product/
        if config_site.get('links_type') == 'nested':
            slash_filter = spider_sheet['Address'].str.count('/') == 5
            combined_filter = status_filter & pattern_filter & slash_filter
        
        else:
            combined_filter = status_filter & pattern_filter

        cat_links = spider_sheet.loc[combined_filter, ['Address']].copy() #.head(20) - ограничитель строк

        
        print(f"✅ [УСПЕШНО] Отфильтровано {len(cat_links)} категорийных ссылок")
        return cat_links
        
    except Exception as e:
        print(f"❌ [ОШИБКА] Проблемы функции filter_links: {e}")
        raise



def scrape_cat_pages(cat_links, config_site):
    """
    ===================================
    Парсинг данных со страниц категорий
    ===================================
    1. Парсим страницы категорий получаем заголовок, название главной категории, ссылки плиток тегов
    2. Записываем список слов (очищенные и в норальной словоформе) в новый столбец 'normal_form' для каждого 'h1'
    """

    def scrape_cat_page(page_link, config_site):
        """
        ==========================
        Парсинг данных со страницы
        ==========================
        1. Загружаем страницу категории
        2. Извлекаем заголовок h1
        3. Извлекаем название главной категории и ближайшей родительской категории
        4. Извлекаем список ссылок (<a></a>) из плиток тегов
        """
        try:
            """1. Загружаем страницу категории"""

            # Заменяем requests.get на нашу функцию с кешем (убирается в продакшине)
            html = get_page_with_cache(page_link, HEADERS) 
            soup = BeautifulSoup(html, 'html.parser')

            
            """2. Извлекаем заголовок h1"""

            h1 = soup.select_one(config_site['h1']).get_text(strip=True)


            """3. Извлекаем название главной категории и ближайшей родительской категории"""

            name_main_cat, name_parent_cat = scrape_breadcrumbs(soup, config_site['breadcrumbs_item'])

            
            """4. Извлекаем список ссылок (<a></a>) из плиток тегов"""

            up_bar_tags = soup.select(config_site['up_bar_tags'])
            
            if 'left_bar_tags' in config_site:
                left_bar_tags = soup.select(config_site['left_bar_tags'])
                all_bar_tags = left_bar_tags + up_bar_tags
            
            else:
                all_bar_tags = up_bar_tags
            

            print(f"✅ [УСПЕШНО] Получены основные данные страницы: {page_link}")
            return h1, name_main_cat, name_parent_cat, all_bar_tags
            
        except Exception as e:
            print(f"❌ [ОШИБКА] Проблемы функции scrape_cat_page: {e}")
            return "", "", "", []
    

    """1. Парсим страницы категорий получаем заголовок, название главной категории, ссылки плиток тегов"""

    cat_links[['h1', 'main_cat', 'parent_cat', 'bar_tags_list']] = cat_links['Address'].apply(lambda x: pd.Series(scrape_cat_page(x, config_site)))
    

    """2. Записываем список слов (очищенные и в норальной словоформе) в новый столбец 'normal_form' для каждого h1"""
    
    cat_links['normal_form'] = cat_links['h1'].apply(clean_and_normalize)

    return cat_links



def extract_and_filter_tag_links(data_all_cat_sheet, config_site):
    """
    ==============================================
    Извлечение и фильтрация ссылок из плиток тегов
    ==============================================
    1. Собираем все ссылки плиток тегов (конструкции <a></a>) в единый список
    2. Оставляем в списке только уникальные значения
    3. Выбираем из <a></a> значения href и текст формируем из них два новых столбца 'Address' и 'h1'
    4. Записываем список слов (очищенные и в норальной словоформе) в новый столбец 'normal_form' для каждого 'h1'
    5. Делаем относительных ссылок в 'Address' полноценные ссылки с доменом (абсолютные)
    6. Сравниваем списки плитки тегов и категорий по столбцу 'normal_form' и убираем дубликаты
    7. Сравниваем строки таблицы по столбцу 'normal_form' и убираем дубликаты
    8. Разделяем таблицу на две с поисковыми ссылками (/search/) и прямыми ссылками (/catalog/ или /product/)
    """
    try:
        bar_tags_links = []

        """ 1. Собираем все ссылки <a></a> плиток тегов в единый список"""

        for links_list in data_all_cat_sheet['bar_tags_list']:
            bar_tags_links.extend(links_list)


        """2. Оставляем в списке только уникальные значения"""
        
        bar_tags_links = list(set(bar_tags_links))


        """3. Выбираем из <a></a> значения href и текст формируем из них два новых столбца Address и h1"""
        
        data = []

        for item in bar_tags_links:
            soup = BeautifulSoup(str(item), 'html.parser')
            link = soup.find('a')
            if link:
                data.append([link.get('href'), link.text])

        bar_tags_df = pd.DataFrame(data, columns=['Address', 'h1'])


        """4. Записываем список слов (очищенные и в норальной словоформе) в новый столбец 'normal_form' для каждого h1"""
        
        bar_tags_df['normal_form'] = bar_tags_df['h1'].apply(clean_and_normalize)


        """5. Делаем из значений столбца 'Address' полноценные ссылки с доменом"""
        
        bar_tags_df['Address'] = config_site['domain_full_name'] + bar_tags_df['Address']


        """6. Сравниваем списки плитки тегов и категорий по столбцу 'normal_form' и убираем дубликаты"""
        
        cat_set = set(tuple(sorted(item)) for item in data_all_cat_sheet['normal_form'] if isinstance(item, (list, tuple)))

        mask = [lst not in cat_set for lst in bar_tags_df['normal_form']]
        bar_tags_filtered = bar_tags_df[mask]

        
        """7. Сравниваем строки таблицы по столбцу 'normal_form' и убираем дубликаты"""
        
        bar_tags_filtered = bar_tags_filtered.drop_duplicates(subset=['normal_form'], keep='first')

        
        """8. Разделяем таблицу на две с поисковыми ссылками (/search/) и прямыми ссылками (/catalog/ или /product/)"""

        mask = bar_tags_filtered['Address'].str.contains(config_site['search_link_pattern'], na=False, regex=True)

        search_links = bar_tags_filtered[mask].copy()
        direct_links = bar_tags_filtered[~mask].copy()
        

        print(f"✅ [УСПЕШНО] Формирование таблиц ссылок из плиток прошло успешно!")
        return search_links, direct_links
    

    except Exception as e:
        print(f"❌ [ОШИБКА] Проблемы функции extract_and_filter_tag_links: {e}")
        raise



def scrape_search_pages(search_links, config_site):
    """
    ===============================================================
    Получение главной и родительской категорий для поисковой ссылки
    ===============================================================
    1. Парсим страницы c помощью внутренней функции для получения главной и родительской категорий
    """
    
    def scrape_search_page(page_link, config_site):
        """
        ======================================================================
        Функция парсинга данных со страницы (Поисковая ссылка)
        ======================================================================
        1. Загружаем станицу поиска
        3. Получаем ссылку первого товара (он наиболее релевантен категории)
        2. Проверяем наличие товаров (нет элемента - нет товаров - итерация пропускается)
        4. Загружаем страницу товара
        5. Получаем название главной категории и родительской категории
        """
        try:
            """1. Загружаем страницу поиска"""

            # Заменяем requests.get на нашу функцию с кешем (убирается в продакшине)
            html = get_page_with_cache(page_link, HEADERS)       
            soup = BeautifulSoup(html, 'html.parser')

            
            """3. Получаем ссылку первого товара"""

            first_link = soup.select_one(config_site['product_item'])


            """2. Проверяем наличие товаров"""

            if not first_link:
                return "", ""


            first_product_link = config_site['domain_full_name'] + first_link['href']

        
            """4. Загружаем страницу товара""" 

            # Заменяем requests.get на нашу функцию с кешем (убирается в продакшине)
            html = get_page_with_cache(first_product_link, HEADERS)        
            soup = BeautifulSoup(html, 'html.parser')


            """5. Получаем название главной категории и ближайшей родительской категории"""

            name_main_cat, name_parent_cat = scrape_breadcrumbs(soup, config_site['breadcrumbs_item'])


            print(f"✅ [УСПЕШНО] Получено название главной категории для ссылки: {page_link}")
            return name_main_cat, name_parent_cat

            
        except Exception as e:
            print(f"❌ [ОШИБКА] Проблемы функции scrape_search_page: {e}")
            return "", ""
        

    """1. Парсим страницы c помощью внутренней функции для получения главной и родительской категорий"""

    search_links[['main_cat', 'parent_cat']] = search_links['Address'].apply(lambda x: pd.Series(scrape_search_page(x, config_site)))


    return search_links



def scrape_direct_pages(direct_links, config_site):
    """
    ===============================================================
    Получение главной и родительской категорий для прямой ссылки
    ===============================================================
    1. Парсим страницы c помощью внутренней функции для получения главной и родительской категорий
    """

    def scrape_direct_page(page_link, config_site):
        """
        ===================================================================
        Функция парсинга данных со страницы (Прямая ссылка)
        ===================================================================
        1. Загружаем страницу категории или товара
        2. Получаем название главной категории и ближайшей родительской категории
        """
        try:
            """1. Загружаем страницу категории или товара"""

            # Заменяем requests.get на нашу функцию с кешем (убирается в продакшине)
            html = get_page_with_cache(page_link, HEADERS)
            soup = BeautifulSoup(html, 'html.parser')


            """2. Получаем название главной категории и ближайшей родительской категории"""

            name_main_cat, name_parent_cat = scrape_breadcrumbs(soup, config_site['breadcrumbs_item'])

            print(f"✅ [УСПЕШНО] Получено название главной категории для ссылки: {page_link}")
            return name_main_cat, name_parent_cat

            
        except Exception as e:
            print(f"❌ [ОШИБКА] Проблемы функции scrape_direct_page: {e}")
            return "", ""
        

    """1. Парсим страницы c помощью внутренней функции для получения главной и родительской категорий"""

    direct_links[['main_cat', 'parent_cat']] = direct_links['Address'].apply(lambda x: pd.Series(scrape_direct_page(x, config_site)))


    return direct_links



def build_final_sheet(cat_links, search_links, direct_links, config_site):
    """
    ============================================
    Финальная сборка обновленного листа bar_tags
    ============================================
    1. Удаление лишнего столбца 'bar_tags_list' (Категорийные ссылки)
    2. Замена пробела на + и удаление пробела в конце (Поисковые ссылки)
    3. Добавление параметра submit или слеша в конец (Поисковые ссылки)
    4. Удаление пробела в конце и добавление слеша (Прямые ссылки)
    5. Проверка первой заглавной буквы в названиях и добавление слеша (Ссылки плитки тегов)
    6. Сборка всех таблиц в одну
    7. Удаление строк с пустой ячейкой столбца 'main_cat'
    """
    try:
        """1. Удаление лишнего столбца 'bar_tags_list' (Категорийные ссылки)"""

        cat_links = cat_links.drop('bar_tags_list', axis=1)


        """2. Заменяем пробелы на + в поисковых ссылках, удаляем при наличии пробел в конце (Поисковые ссылки)"""

        search_links['Address'] = search_links['Address'].str.replace(' ', '+', regex=False)
        search_links['Address'] = search_links['Address'].str.strip()
        

        """3. Подставляем конструкцию submit, если она нужна либо добавляем слеш в конец (Поисковые ссылки)"""

        if 'submit_param' in config_site:
            param = config_site["submit_param"]

            search_links['Address'] = search_links['Address'].apply(
                lambda url: url if isinstance(url, str) and url.endswith(param)
                else url + param if isinstance(url, str)
                else url
                )
        
        else:
            search_links['Address'] = search_links['Address'].apply(lambda url: url + '/' if isinstance(url, str) and not url.endswith('/') else url)

            
        """4. Убираем лишний пробел в конце. если он есть, добавляем слеш в конец (Прямые ссылки)"""

        direct_links['Address'] = direct_links['Address'].str.strip()
        direct_links['Address'] = direct_links['Address'].apply(lambda url: url + '/' if isinstance(url, str) and not url.endswith('/') else url)

        # Объединяем две таблицы, так как последующие действия одинаковы для обоих
        bar_tags_links = pd.concat([search_links, direct_links], ignore_index=True)


        """5. Проверка названий на первую заглавную букву, если нет, меняется регистр, добавление слеша в конец (Ссылки плитки тегов)"""

        bar_tags_links['h1'] = bar_tags_links['h1'].apply(lambda x: x[0].upper() + x[1:] if isinstance(x, str) and len(x) > 0 else x)
        # bar_tags_links['Address'] = bar_tags_links['Address'].apply(lambda url: url + '/' if isinstance(url, str) and not url.endswith('/') else url)


        """6. Сборка таблиц в одну"""

        final_sheet = pd.concat([cat_links, bar_tags_links], ignore_index=True)


        """7. Удаление строк с пустой ячейкой столбца 'main_cat' (NaN, none, '')"""

        final_sheet = final_sheet[final_sheet['main_cat'].notna() & (final_sheet['main_cat'] != '')]


        print(f"✅ [УСПЕШНО] Финальная таблица собрана!")
        return final_sheet


    except Exception as e:
        print(f"❌ [ОШИБКА] Проблемы функции build_final_sheet: {e}")
        raise



def main():
    """
    ==========================================
    Основная функция выполнения всего процесса
    ==========================================
    1. Загрузка таблицы от screaming frog, определение домена и получение списка конфигурации
    2. Выбор всех категорийных ссылок
    3. Для категорийных ссылок получаем заголовок, нормальную словоформу слов заголовка, главную и родительскую категории, ссылки из плиток тегов
    4. Извлекаем и фильтруем ссылки из плиток тегов, формируем рабочую ссылку, заголовок, нормальную словоформу для слов заголовка, убираем дубликаты
    5. Получаем главную и родительскую категории для поисковых и прямых ссылок плитки тегов
    6. Объединяем результаты в финальный лист
    """
    print("🚀 [СТАРТ] Запуск обновления листа bar_tags...")
    

    """1. Загрузка таблицы от screaming frog, определение домена и получение списка конфигурации"""

    spider_sheet, domain, config_site = download_data_sheet(FILE_URL)
    

    """2. Выбор всех категорийных ссылок"""

    cat_links = filter_links(spider_sheet, config_site)

    
    """3. Для категорийных ссылок получаем заголовок, нормальную словоформу для слов заголовка, главную и родительскую категории, ссылки из плиток тегов"""

    data_all_cat_sheet = scrape_cat_pages(cat_links, config_site)

    
    """4. Извлекаем и фильтруем ссылки из плиток тегов, формируем рабочую ссылку, заголовок, нормальную словоформу для слов заголовка, убираем дубликаты"""

    data_all_search_links, data_all_direct_links = extract_and_filter_tag_links(data_all_cat_sheet, config_site)

    
    """5. Получаем главную и родительскую категории для поисковых и прямых ссылок плитки тегов"""

    data_all_search_sheet = scrape_search_pages(data_all_search_links, config_site)
    data_all_direct_sheet = scrape_direct_pages(data_all_direct_links, config_site)
    
    
    """6. Объединяем результаты в финальный лист"""

    final_sheet = build_final_sheet(data_all_cat_sheet, data_all_search_sheet, data_all_direct_sheet, config_site)

    
    # Сохранение результата
    # data_all_cat_sheet.to_excel("data_all_cat_sheet.xlsx", index=False)
    # data_all_search_sheet.to_excel("data_all_search_sheet.xlsx", index=False)
    # data_all_direct_sheet.to_excel("data_all_direct_sheet.xlsx", index=False)
    # final_sheet.to_excel("final_sheet.xlsx", index=False)


    file_path = f"worksheets/work_{domain}.xlsx"

    # Записываем лист bar_tags
    with pd.ExcelWriter(file_path, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
        final_sheet.to_excel(writer, sheet_name='bar_tags', index=False)
    

    print(f"🏁 [ФИНИШ] Обновление листа bar_tags домена {domain.upper()} завершено!")



# Запуск программы
if __name__ == "__main__":
    main()