# Скрипт создания / удаления временной папки

import os
import sys
import shutil
sys.stdout.reconfigure(encoding='utf-8')

def manage_temp_dir(chat_id, action, type_work):
    """
    ===========================================
    Функция создания / удаления временной папки
    ===========================================
    1. Создаем путь временной папки
    2. Создаем папку (если она есть сносим и создаем заново) и возвращаем её директорию
    3. Получаем название папки
    4. Удаляем папку со свем содержимым
    """
    try:

        """1. Создаем полный путь временной папки"""

        prefix = "temp_for_"

        if action == "delete_all":
            temp_root = "temp_files"
            if not os.path.isdir(temp_root):
                return 0

            deleted_count = 0
            for entry in os.scandir(temp_root):
                if not entry.name.startswith(prefix) or not entry.is_dir(follow_symlinks=False):
                    continue
                try:
                    shutil.rmtree(entry.path)
                    deleted_count += 1
                except OSError as e:
                    print(f'[MANAGE_TEMP_DIR][ERROR❌] Не удалось удалить {entry.path}: {e}')
            return deleted_count

        folder_name = prefix + str(chat_id) + "_" + type_work
        temp_dir = os.path.join('temp_files', folder_name)

        
        """2. Создаем папку (если она есть сносим и создаем заново) и возвращаем её директорию"""

        if action == "create":

            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

            os.makedirs(temp_dir, exist_ok=False)
            
            print(f'[{chat_id}][MANAGE_TEMP_DIR][SUCCESS✅] Временная папка создана!')
            return temp_dir
        

        """3. Получаем название папки"""
        if action == "get":
            return temp_dir
        

        """4. Удаляем папку со свем содержимым"""

        if action == "delete":
            
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

                return True
            
            print(f'[{chat_id}][MANAGE_TEMP_DIR][SUCCESS✅] Временная папка со всем её содержимым успешно удалена!')
            return False
            
            
    except Exception as e:
        print(f'[MANAGE_TEMP_DIR][ERROR❌]: {e}') 
        return None

# if __name__ == '__main__':
# Example identifier omitted.
# Example identifier omitted.