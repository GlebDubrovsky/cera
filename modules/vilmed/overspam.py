import pandas as pd
import re
from pymorphy3 import MorphAnalyzer
import os

def overspam_vilmed(input_file, chat_id):
    try:
        # Инициализация морфологического анализатора
        morph = MorphAnalyzer()

        prefix = "temp_for_"
        folder_name = prefix + str(chat_id)

        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        temp_dir = os.path.join(base_dir, "temp_files", folder_name)
        work_sheet_url = os.path.join(base_dir, "worksheets/work_vilmed.xlsx")

        # Проверяем, что файл существует
        if not os.path.exists(input_file):
            print(f"Файл {input_file} не найден.")
            return None

        # Чтение файла релевантности
        relevance_df = pd.read_excel(input_file, header=1)
        
        # Функция для приведения слова к нормальной форме
        def normalize_word(word):
            try:
                parsed_word = morph.parse(word)[0]
                return parsed_word.normal_form
            except:
                return str(word).strip().lower()

        # Обработка DataFrame релевантности
        relevance_df['Удалить'] = relevance_df['Удалить'].apply(lambda x: int(str(x).split('-')[-1]))
        relevance_df = relevance_df[relevance_df['Удалить'] != 0]
        
        relevance_words = {}
        for index, row in relevance_df.iterrows():
            word = str(row['Слово']).strip().lower()
            normalized_word = normalize_word(word)
            max_count = row['Удалить']
            relevance_words[normalized_word] = max_count

        # Загрузка данных из "work_vilmed.xlsx"
        if not os.path.exists(work_sheet_url):
            print(f"Файл {work_sheet_url} не найден.")
            return None
            
        work_df = pd.read_excel(work_sheet_url, sheet_name='Готовый список ID')
        work_df = work_df[['Название', 'ID раздела']].dropna()

        # Обработка названий
        processed_data = []
        for index, row in work_df.iterrows():
            title = str(row['Название'])
            # Удаление знаков препинания и приведение к нижнему регистру
            clean_title = re.sub(r'[^\w\s]', ' ', title).lower()
            # Разделение на слова и нормализация
            words = clean_title.split()
            normalized_words = [normalize_word(word) for word in words if word.strip()]
            processed_data.append({
                'id': row['ID раздела'],
                'title': title,
                'words': set(normalized_words)  # Используем множество для быстрого поиска
            })

        # Поиск совпадений и формирование результатов
        results = []
        for word, max_count in relevance_words.items():
            matched_entries = []
            for item in processed_data:
                if word in item['words']:
                    matched_entries.append(item)
                    if len(matched_entries) >= max_count:
                        break  # Прекращаем поиск при достижении лимита
            if matched_entries:
                for entry in matched_entries:
                    results.append({
                        'Название': entry['title'],
                        'ID': entry['id']
                    })

        # Создание DataFrame для результата
        result_df = pd.DataFrame(results)

        # Удаление дубликатов (если один ID попал под несколько слов)
        if not result_df.empty:
            result_df = result_df.drop_duplicates(subset=['ID'])
            
            # Сохраняем результат во временную папку (опционально)
            if temp_dir and os.path.exists(temp_dir):
                output_file_url = os.path.join(temp_dir, "overspam_vilmed_list.xlsx")
                result_df.to_excel(output_file_url, index=False)
                print(f"Результат сохранен в {output_file_url}")
        
        print("Готово! Функция overspam_vilmed отработала успешно!")
        return result_df
        
    except Exception as e:
        print(f"Ошибка при обработке файла: {e}")
        import traceback
        traceback.print_exc()
        return None