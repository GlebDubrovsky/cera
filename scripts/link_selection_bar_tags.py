import pandas as pd
import re
import pymorphy3
import glob
import os
from bs4 import BeautifulSoup
import requests
import time
import hashlib
import ast


# Инициализация морфологического анализатора для русского языка с кэшированием
morph = pymorphy3.MorphAnalyzer(lang='ru')

# Настройка отображения всех столбцов в DataFrame без ограничений
pd.set_option('display.max_columns', None)


"""
============================ Константы и переменные ============================
"""

HEADERS = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
            'Connection': 'keep-alive',
        }

#===================Функционал связанные категории===================
# Пример оформления

# VILMED_CONNECT_CAT = {
#     "Название категории": ["Название связанной 1", "Название связанной 2", "Название связанной 3"],
#     "Название категории": ["Название связанной 1", "Название связанной 2", "Название связанной 3"]
# }

# ALMAMED_CONNECT_CAT = {
#     "Название категории": ["Название связанной 1", "Название связанной 2", "Название связанной 3"],
#     "Название категории": ["Название связанной 1", "Название связанной 2", "Название связанной 3"]
# }
#====================================================================

"""
============================= Общие вспомогательные функции =============================
"""

def normalize_word(word):
    """
    ============================================================
    Функция приведения слова к нормальной форме с заменой ё на е
    ============================================================
    """
    try:

        normal_form = morph.parse(word)[0].normal_form.replace('ё', 'е')

        return normal_form
    

    except Exception as e:
        print(f"❌ [ОШИБКА] Ошибка при обработке слова '{word}' функцией normalize_word: {e}")
        return word
    


def scrape_page(url, HEADERS):
    """
    =====================================================
    Функция для скачивания страниц с повторными попытками
    =====================================================
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


# def scrape_page(url, HEADERS):
#     """
#     =====================================================
#     Вспомогательная функция для кеширования (для отладки)
#     =====================================================
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



def is_number(word):
    """
    ====================================
    Проверка, является ли строка числом
    ====================================
    Нужна для проверки слов (строковых значений, напрмер '250')
    """
    try:

        float(word)

        return True
    

    except ValueError:

        return False


"""
======================== Основной логический блок ========================
"""


def get_data(file_url, worksheet_url, cat_url, config):
    '''
    =======================
    Функция загрузки таблиц
    =======================
    1. Загружаем таблицу с важными словами
    2. Проверяем таблицы на пустоту
    3. Приводим важные слова к нормальной словоформе
    4. Определение домена с последующей отправкой списка важных слов, рабочей таблицы, названия домена, конфигурации
    '''
    try:
        '''1. Загружаем таблицу с важными словами и рабочую таблицу'''

        df_words = pd.read_excel(file_url, 
                                usecols=[0],           # только столбец B
                                skiprows=1,            # пропустить первую строку
                                header=0,              # следующая строка — заголовок
                                names=['words']        # сразу переименовать в words
                                ) 

        df_work = pd.read_excel(worksheet_url, sheet_name='bar_tags')


        '''2. Проверяем таблицы на пустоту'''

        if df_words.empty:
            print(f"DataFrame {df_words} пустой!")
            exit()
        
        if df_work.empty:
            print(f"DataFrame {df_work} пустой!")
            exit()


        '''3. Приводим важные слова к нормальной словоформе'''

        df_words['words'] = df_words['words'].apply(normalize_word)


        """4. Определение домена с последующей отправкой списка важных слов, рабочей таблицы, названия домена, конфигурации"""

        for domain, domain_config in config.items():

            if domain in cat_url:

                print(f'[GET_DATA][SUCCESS✅] Рабочие таблицы и конфигурация для {domain} загружены')
                
                return (
                    df_words,
                    df_work,
                    domain,
                    domain_config
                )

        raise ValueError("Домен не найден в списке разрешенных")

    except Exception as e:
        print(f"[GET_DATA][ERROR❌]: {e}")
        raise



def get_main_and_parent_cat(url, site_config):
    '''
    ===========================================================
    Функция получения зазваний главной и родительской категорий
    ===========================================================
    1. Загружаем страницу категории
    2. Извлекаем название главной категории и ближайшей родительской категории
    '''
    try:
        """1. Загружаем страницу категории"""

        html = scrape_page(url, HEADERS) 
        soup = BeautifulSoup(html, 'html.parser')
        
        """2. Извлекаем название главной категории и ближайшей родительской категории"""

        name_main_cat, name_parent_cat = scrape_breadcrumbs(soup, site_config['breadcrumbs_item'])

        print('[GET_MAIN_AND_PARENT_CAT][SUCCESS✅] Названия главной и родительской категорий успешно получены!')
        return name_main_cat, name_parent_cat
    
    except Exception as e:
        print(f"[GET_MAIN_AND_PARENT_CAT][ERROR❌]: {e}")
        raise



def create_bar_tags(df_words, df_work, name_main_cat, name_parent_cat, domain):
    '''
    ===============================================
    Функция создания списка ссылок для плитки тегов
    ===============================================
    1. Создаем временные рабочие списки и пустую таблицу для результата отбора
    2. Подбираем лучшую ссылку для каждого слова
    '''

    '''1. Создаем временные рабочие списки и пустую таблицу для результата отбора'''

    imp_words_used = []
    empty_words_used = []


    columns = ['Address', 'h1', 'main_cat', 'parent_cat', 'normal_form', 'imp_words', 'empty_words', 'important_sum', 'empty_sum', 'empty_index', 'criterion']
    finish_sheet = pd.DataFrame(columns=columns)


    def selection(word, df_words, df_work, imp_words_used, empty_words_used, name_main_cat, name_parent_cat, domain):
        '''
        =======================================================
        Главная функция отбора ссылки для каждого важного слова
        =======================================================
        2.1. Проверяем использовалось ли слово раньше
        2.2. Отбираем важные слова, которые ещё не использовались и делаем из них множество
        '''
        try:
            '''2.1. Проверяем использовалось ли слово раньше'''

            if word in imp_words_used:
                return

            '''2.2. Отбираем важные слова, которые ещё не использовались и делаем из них множество'''

            df_words = df_words[~df_words['words'].isin(imp_words_used)]

            target_words_set = set(df_words['words'].tolist())


            def process_row(words, target_words, empty_words):
                '''
                =============================================================================
                Функция подготовки рабочей таблицы bar_tags для сортировки (подсчет значений)
                =============================================================================
                2.3.1. Переводим слова из столбца normal_form в список (в таблице это строка)
                2.3.2. Проверяем каждое слово на скрытое число, например '250'(строка)
                2.3.3. Сортируем слова на важные и пустые
                2.3.4. Считаем, сколько слов из empty уже есть в empty_words
                '''
                try:
                    '''2.3.1. Переводим слова из столбца normal_form в список (в таблице это строка)'''
                    
                    tuple_data = ast.literal_eval(words)    # Преобразует строку в кортеж
                    words_list = list(tuple_data)           # Преобразует кортеж в список


                    '''2.3.2. Проверяем каждое слово на скрытое число, например '250'(строка)'''
                    
                    str_words = [w for w in words_list if not is_number(w)]


                    '''2.3.3. Сортируем слова на важные и пустые'''
                    
                    imp = [w for w in str_words if w in target_words]
                    empty = [w for w in str_words if w not in target_words]


                    '''2.3.4. Считаем, сколько слов из empty уже есть в empty_words'''
                    
                    empty_index = sum(1 for word in empty if word in empty_words)

                    return imp, empty, len(imp), len(empty), empty_index

                except Exception as e:
                    print(f"[PROCESS_ROW][ERROR❌]: {e}")
                    raise
            

            '''2.3. Применяем функцию и добавляем результаты подсчета'''

            result = df_work['normal_form'].apply(lambda x: process_row(x, target_words_set, empty_words_used))

            df_work['imp_words'], df_work['empty_words'], df_work['important_sum'], df_work['empty_sum'], df_work['empty_index'] = zip(*result)


            '''2.4. Удаляем строки, без совпадений по важным словам'''

            df_work = df_work[df_work['important_sum'] != 0]


            '''2.5. Разбиваем рабочий лист с новыми данными на группы: общий родитель, общая главная , взаимосвязанные категории (опция)'''

            if name_parent_cat:
                df_parent = df_work[df_work['parent_cat'] == name_parent_cat]
            else:
                df_parent = pd.DataFrame(columns=df_work.columns)  # Пустой dataframe (нужен для сложения, чтобы не было ошибки)

            df_main = df_work[df_work['main_cat'] == name_main_cat]

            #===================Функционал связанные категории===================
            # Просто раскомментировать

            # if domain in ['vilmed', 'almamed']:
            
            #   if domain == 'vilmed':
            #       connect_cat = VILMED_CONNECT_CAT

            #   if domain == 'almamed':
            #       connect_cat = ALMAMED_CONNECT_CAT

            #   if name_main_cat in connect_cat:
            #     df_connect = df_work[df_work['main_cat'].isin(connect_cat[name_main_cat])]
            # else:
            #     df_connect = pd.DataFrame(columns=df_work.columns) # Пустой dataframe (нужен для сложения, чтобы не было ошибки)
            #====================================================================


            '''2.6. Объединяем группы и вычитаем их из рабочего листа, чтобы получить: ссылки без особой группы'''

            df_filtered = pd.concat([df_parent, df_main])

            #===================Функционал связанные категории===================
            # Раскомментировать, закомментировать строку выше

            # df_filtered = pd.concat([df_parent, df_main, df_connect])
            #====================================================================

            df_common = df_work[~df_work.index.isin(df_filtered.index)]


            def get_best_row(df, criterion):
                '''
                ===========================================================================
                Функция фильтрации группы строк для получения строки с лучшими показателями
                ===========================================================================
                2.7.1. Выбираем строки с самым высоким количеством важных слов
                2.7.2. Выбираем строки с наименьшим количеством пустых слов
                2.7.3. Выбираем строки с наименьшим индексом пустых слов
                2.7.4. Выбираем первую строку, добавляем столбец критерий
                2.7.5. Добавляем слова во временные рабочие списки
                '''
                try:
                    '''2.7.1. Выбираем строки с самым высоким количеством важных слов'''

                    max_imp = df['important_sum'].max()
                    df1 = df[df['important_sum'] == max_imp]
                    

                    '''2.7.2. Выбираем строки с наименьшим количеством пустых слов'''

                    min_empty = df1['empty_sum'].min()
                    df2 = df1[df1['empty_sum'] == min_empty]
                    

                    '''2.7.3. Выбираем строки с наименьшим индексом пустых слов'''

                    min_index = df2['empty_index'].min()
                    df3 = df2[df2['empty_index'] == min_index]


                    '''2.7.4. Выбираем первую строку, добавляем столбец критерий'''

                    result_row = df3.iloc[0].copy()
                    result_row['criterion'] = criterion


                    '''2.7.5. Добавляем слова во временные рабочие списки'''

                    imp_words = result_row['imp_words']
                    empty_words = result_row['empty_words']

                    imp_words_used.extend(imp_words)
                    empty_words_used.extend(empty_words)


                    return result_row
                
                except Exception as e:
                    print(f"❌ [ОШИБКА] Проблемы функции get_best_row: {e}")
                    raise

            '''2.7. Применяем функцию отбора лучшей строки для каждой группы'''

            if not df_parent.empty:
                best = get_best_row(df_parent, 'parent')
                finish_sheet.loc[len(finish_sheet)] = best
                print(f'Подходящая ссылка для «{word}» найдена! Группа PARENT')

            elif not df_main.empty:
                best = get_best_row(df_main, 'main')
                finish_sheet.loc[len(finish_sheet)] = best
                print(f'Подходящая ссылка для «{word}» найдена! Группа MAIN')

            #===================Функционал связанные категории===================
            # Просто раскомментировать

            # elif not df_connect.empty:
            #   best = get_best_row(df_connect, 'connect')
            #   finish_sheet.loc[len(finish_sheet)] = best
            #====================================================================
            
            elif not df_common.empty:
                best = get_best_row(df_common, 'common')
                finish_sheet.loc[len(finish_sheet)] = best
                print(f'Подходящая ссылка для «{word}» найдена! Группа COMMON')

            else:
                print(f'Подходящая ссылка для «{word}» не найдена! Нет совпадений по таблице bar_tags')

        except Exception as e:
            print(f"❌ [ОШИБКА] Проблемы функции selection: {e}")
            raise


    '''2. Подбираем лучшую ссылку для каждого слова'''

    for word in df_words['words']:
        selection(word, df_words, df_work, imp_words_used, empty_words_used, name_main_cat, name_parent_cat, domain)
    
    print(f'[CREATE_BAR_TAGS][SUCCESS✅] Ссылки для плитки тегов успешно отсортированы!')
    return finish_sheet



def build_final_url(row):
    '''
    =================================================
    Функция формирования ссылки пригодной для вставки
    =================================================
    1. Разбиваем ссылку на список по слешу
    2. Берем элементы списка, начиная с 4 склеиваем их слешем и добавляем слеш вначало
    3. Заголовок и получившийся путь через собаку
    '''
    try:
        url = row['Address']
        h1 = row['h1']

        '''1. Разбиваем ссылку на список по слешу'''
        parts = url.split('/')

        '''2. Берем элементы списка, начиная с 4 склеиваем их слешем и добавляем слеш вначало'''
        path = '/' + '/'.join(parts[3:])
        
        '''3. Заголовок и получившийся путь через собаку'''
        return f"{h1}@{path}"
    
    except Exception as e:
        print(f"[BUILD_FINAL_URL][ERROR❌]: {e}")
        raise



def link_selection_bar_tags(file_url, worksheet_url, cat_url, main_config):

    """
    ==========================================
    Основная функция выполнения всего процесса
    ==========================================
    1. Загружаем рабочие таблицы и данные конфигурации
    2. Получаем главную и родительскую категории
    3. Отбираем ссылки по лучшим показателям
    4. Формируем ссылки для вставки, убираем url и h1, готовые ссылки делаем первым столбцом
    """
    print("🚀 [START] Запуск модуля LINK_SELECTION...")


    '''1. Загружаем рабочие таблицы и данные конфигурации'''
    print('[GET_DATA][START] Загрузка рабочих таблиц и конфигурации...')

    df_words, df_work, domain, site_config = get_data(file_url, worksheet_url, cat_url, main_config)


    '''2. Получаем главную и родительскую категории'''
    print('[GET_MAIN_AND_PARENT_CAT][START] Получение главной и родительской категории со страницы...')

    name_main_cat, name_parent_cat = get_main_and_parent_cat(cat_url, site_config)


    '''3. Отбираем ссылки по лучшим показателям'''
    print('[CREATE_BAR_TAGS][START] Загрузка рабочих таблиц и конфигурации...')

    result_sheet = create_bar_tags(df_words, df_work, name_main_cat, name_parent_cat, domain)

    
    '''4. Формируем ссылки для вставки, убираем url и h1, готовые ссылки делаем первым столбцом'''
    print('[BUILD_FINAL_URL][START] Формируем ссылки и форматируем итоговую таблицу...')

    result_sheet['final_url'] = result_sheet.apply(build_final_url, axis=1)
    result_sheet = result_sheet.drop(['Address', 'h1'], axis=1)
    
    col = result_sheet.pop('final_url')         # вырезали столбец 
    result_sheet.insert(0, 'final_url', col)    # вставили на позицию 0


    print(f"🏁 [FINAL] Завершена работа модуля LINK_SELECTION!")
    # result_sheet.to_excel("result_sheet.xlsx", index=False)
    return result_sheet

    




# Реализовать запуск скрипта для отладки
# if __name__ == "__main__":

#     result = link_selection_bar_tags(FILE_URL, WORKSHEET_URL, CAT_URL)
#     result.to_excel("result_sheet.xlsx", index=False)