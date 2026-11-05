# Скрипт создания / удаления временной папки

import os
import shutil
from pathlib import Path

_TEMP_ROOT = Path(__file__).resolve().parents[1] / "temp_files"


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
            if not _TEMP_ROOT.is_dir():
                return 0

            deleted_count = 0
            for entry in os.scandir(_TEMP_ROOT):
                if not entry.name.startswith(prefix) or not entry.is_dir(follow_symlinks=False):
                    continue
                try:
                    shutil.rmtree(entry.path)
                    deleted_count += 1
                except OSError as error:
                    print(
                        f"[COMMON][TEMP_CLEANUP][ERROR] Ошибка удаления каталога ({type(error).__name__}).",
                        flush=True,
                    )
            return deleted_count

        folder_name = prefix + str(chat_id) + "_" + type_work
        temp_dir_path = (_TEMP_ROOT / folder_name).resolve()
        if temp_dir_path.parent != _TEMP_ROOT:
            print("[COMMON][TEMP_DIR][ERROR] Некорректный идентификатор временной папки.", flush=True)
            return None
        temp_dir = str(temp_dir_path)

        """2. Создаем папку (если она есть сносим и создаем заново) и возвращаем её директорию"""

        if action == "create":

            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

            os.makedirs(temp_dir, exist_ok=False)
            print("[COMMON][TEMP_DIR][SUCCESS] Временный каталог создан.", flush=True)
            return temp_dir

        """3. Получаем название папки"""
        if action == "get":
            return temp_dir
        

        """4. Удаляем папку со свем содержимым"""

        if action == "delete":
            if not os.path.exists(temp_dir):
                print("[COMMON][TEMP_DIR][WARNING] Временный каталог не найден.", flush=True)
                return False

            shutil.rmtree(temp_dir)
            print("[COMMON][TEMP_DIR][SUCCESS] Временный каталог удалён.", flush=True)
            return True

    except Exception as error:
        print(
            f"[COMMON][TEMP_DIR][ERROR] Ошибка обработки ({type(error).__name__}).",
            flush=True,
        )
        return None

# if __name__ == '__main__':
# Example identifier omitted.
# Example identifier omitted.