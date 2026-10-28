import pandas as pd

# Настройка отображения всех столбцов в DataFrame без ограничений
pd.set_option('display.max_columns', None)


def update_cat_menu_vilmed(all_cat_sheet, work_sheet):

    # Читаем таблицу, говорим, что заголовка нет
    tables = pd.read_html(all_cat_sheet, header=None)
    df_all_cat = tables[0]


    # Ручками задаем правильные имена столбцов
    # Список ниже скопируй из самой первой строки своего HTML (она в файле есть)
    # Обязательно сверь количество (у тебя должно быть 10 колонок)
    df_all_cat.columns = [
        'Название',
        'Активность',
        'Символьный код',
        'Элементов',
        'Дата изменения',
        'ID раздела',
        'Уровень',
        'Скрыть из меню и категорий вывод',
        'Название для меню',
        'Скрыть только из меню'
    ]

    df_all_cat['Уровень'] = pd.to_numeric(df_all_cat['Уровень'], errors='coerce')

    # Теперь твой фильтр должен отработать
    df_cat_menu = df_all_cat[(df_all_cat['Активность'] == 'Да') & (df_all_cat['Уровень'] < 3) & (df_all_cat['Скрыть только из меню'] == 'N')]

    # Записываем с перезаписью конкретного листа
    with pd.ExcelWriter(
        work_sheet,
        mode='a',  # Режим добавления (append)
        if_sheet_exists='replace',  # Перезаписать лист, если существует
        engine='openpyxl'  # Нужен для работы с существующими файлами .xlsx
    ) as writer:
        df_cat_menu.to_excel(writer, sheet_name='menu_categories', index=False)

