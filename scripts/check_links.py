# Скрипт проверки ссылки на работоспособность
import requests
from requests.exceptions import RequestException
import time



def check_link(url, headers):
    """
    =========================================================
    Функция проверки ссылки (проверяет ответ, а не скачивает)
    =========================================================
    """
    print('[CHECK_LINKS][START] Проверяем полученную ссылку...')
    max_retries = 5 # Количество попыток
    retries = 0
    
    while retries < max_retries:

        try:
            response = requests.head(url, headers=headers, timeout=10)
            if response.status_code == 200:

                print('[CHECK_LINKS][SUCCESS✅] Ссылка работает!')
                return True
            
            else:
                print(f"[CHECK_LINKS][ERROR❌] Попытка {retries + 1}: Ссылка вернула статус {response.status_code}")

        except RequestException as e:
            print(f'[CHECK_LINKS][ERROR❌] Попытка {retries + 1}: Ошибка при проверке ссылки: {str(e)}')
        
        retries += 1
        if retries < max_retries:
            time.sleep(2)  # Пауза между попытками
    
    return False