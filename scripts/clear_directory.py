import shutil
import os

def clear_directory(path):
    # Очищает все содержимое папки

    for filename in os.listdir(path):

        file_path = os.path.join(path, filename)

        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)  # Удаление файлов и символических ссылок
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)  # Удаление папок (включая вложенные)

        except Exception as e:
            print(f'Ошибка при удалении {file_path}: {e}')